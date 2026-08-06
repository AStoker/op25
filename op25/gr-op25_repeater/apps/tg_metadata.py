# Copyright 2026 OP25 Contributors
#
# This file is part of OP25
#
# OP25 is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.

"""Durable per-talkgroup metadata: when it was last heard, on what frequency.

The decoder already tracks this (``talkgroups[tgid]['time']`` and the sticky
``['last_freq']``, published in the ``tgid_tags`` block of ``trunk_update``), but
only for the life of the process.  A tgid_tags_file with two thousand entries
therefore reads "never heard" after every restart, which is exactly when a
last-heard column is most useful.

Design
------
The in-memory dict is the source of truth and every read is served from it.
SQLite is a write-behind cache: dirty rows are flushed in one transaction on a
timer (:data:`FLUSH_INTERVAL`) and at shutdown, so a talkgroup seen twice a
second does not become two disk writes a second.  On a Home Assistant OS box
the database lives on the same partition as the recorder, which may be an SD
card -- the batching is the point, not an optimisation.

Nothing here is on the audio path and nothing here can fail the decoder: every
public method swallows sqlite errors after logging them once, and the process
keeps running with an in-memory-only store.

Why not extend the decoder instead: ``tk_p25.py`` / ``tk_smartnet.py`` /
``tk_trbo.py`` are the files where an upstream cherry-pick is still realistic
(see CLAUDE.md), so they get the smallest possible change -- publish the numbers
they already have -- and the storage policy lives here, on the fork's side.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from typing import Any

# How long a dirty row may sit in memory before it is written.  A crash loses at
# most this much last-heard history, which is worth trading for not writing to
# disk on every control-channel grant.
FLUSH_INTERVAL = 30.0

# Guard against a runaway tgid space (a mis-tuned receiver invents talkgroups).
# 65534 is the protocol maximum, so this is generous; it exists so a decode
# fault cannot grow the database without bound.
MAX_ROWS = 200_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS talkgroups (
    system     TEXT    NOT NULL,
    tgid       INTEGER NOT NULL,
    tag        TEXT    NOT NULL DEFAULT '',
    last_seen  REAL    NOT NULL DEFAULT 0,
    last_freq  INTEGER,
    count      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (system, tgid)
);
CREATE INDEX IF NOT EXISTS talkgroups_last_seen ON talkgroups (last_seen DESC);
"""


def db_path(config: dict[str, Any] | None) -> str | None:
    """Where the database should live, or None to run memory-only.

    ``$OP25_METADATA_DB`` wins, then ``terminal.metadata_db`` in the config, then
    a default in the cwd -- which is the user's data directory (multi_rx resolves
    tgid_tags_file and the whitelists against it too, and the add-on runs with
    cwd set to the config dir).  Either source may be set to an empty string to
    turn persistence off.
    """
    env = os.environ.get('OP25_METADATA_DB')
    if env is not None:
        return env.strip() or None
    terminal = (config or {}).get('terminal', {}) or {}
    if 'metadata_db' in terminal:
        configured = terminal.get('metadata_db')
        if configured is False or configured is None:
            return None
        return str(configured).strip() or None
    return 'op25_metadata.sqlite'


class TalkgroupStore:
    """Merges decoder-reported talkgroup activity with what's on disk."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        # (system, tgid) -> row dict.  Authoritative; sqlite only mirrors it.
        self._rows: dict[tuple[str, int], dict[str, Any]] = {}
        self._dirty: set[tuple[str, int]] = set()
        self._last_flush = time.time()
        # Per key, the count the decoder last reported.  The decoder's counter
        # restarts at zero with the process, so only the *delta* may be added to
        # the stored lifetime total -- adding the raw value would re-add the
        # whole session on every update.
        self._counted: dict[tuple[str, int], int] = {}
        self._db: sqlite3.Connection | None = None
        self._broken = False
        if path:
            self._open(path)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _open(self, path: str) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            # check_same_thread=False: written by the ws_terminal thread, read by
            # the uvicorn event loop for /api/talkgroups.  self._lock serialises
            # both, which is what sqlite3 actually requires.
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.executescript(_SCHEMA)
            self._db.commit()
            self._load()
            sys.stderr.write('talkgroup metadata: %d row(s) from %s\n'
                             % (len(self._rows), path))
        except (sqlite3.Error, OSError) as e:
            self._fail('open %s' % path, e)

    def _fail(self, what: str, exc: Exception) -> None:
        """Log once and continue memory-only.  This is never fatal."""
        if not self._broken:
            self._broken = True
            sys.stderr.write('talkgroup metadata disabled (%s: %s)\n' % (what, exc))
        if self._db is not None:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
            self._db = None

    def _load(self) -> None:
        if self._db is None:
            return
        cur = self._db.execute(
            'SELECT system, tgid, tag, last_seen, last_freq, count FROM talkgroups')
        for system, tgid, tag, last_seen, last_freq, count in cur:
            self._rows[(system, int(tgid))] = {
                'tag': tag or '', 'last_seen': float(last_seen or 0),
                'last_freq': last_freq, 'count': int(count or 0),
            }

    def flush(self, force: bool = False) -> int:
        """Write dirty rows.  Returns the number written."""
        now = time.time()
        with self._lock:
            if not force and now - self._last_flush < FLUSH_INTERVAL:
                return 0
            self._last_flush = now
            if self._db is None or not self._dirty:
                self._dirty.clear()
                return 0
            batch = [
                (system, tgid, row['tag'], row['last_seen'], row['last_freq'], row['count'])
                for system, tgid in self._dirty
                if (row := self._rows.get((system, tgid))) is not None
            ]
            self._dirty.clear()
        if not batch:
            return 0
        try:
            with self._db:      # one transaction for the whole batch
                self._db.executemany(
                    'INSERT INTO talkgroups (system, tgid, tag, last_seen, last_freq, count)'
                    ' VALUES (?, ?, ?, ?, ?, ?)'
                    ' ON CONFLICT(system, tgid) DO UPDATE SET'
                    '   tag = excluded.tag,'
                    # Never move last_seen backwards: two receivers on one system
                    # report independently and a stale snapshot must not win.
                    '   last_seen = MAX(talkgroups.last_seen, excluded.last_seen),'
                    '   last_freq = COALESCE(excluded.last_freq, talkgroups.last_freq),'
                    '   count = MAX(talkgroups.count, excluded.count)',
                    batch)
        except sqlite3.Error as e:
            self._fail('flush', e)
            return 0
        return len(batch)

    def close(self) -> None:
        self.flush(force=True)
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                except sqlite3.Error:
                    pass
                self._db = None

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def observe(self, system: str, tgid_tags: dict[str, Any]) -> None:
        """Fold one trunk_update's tgid_tags block into the store.

        Only real activity is recorded.  A talkgroup the decoder loaded from
        tgid_tags_file but has never heard reports ``last_seen == 0``, which must
        not overwrite a genuine timestamp from a previous run.
        """
        if not isinstance(tgid_tags, dict):
            return
        with self._lock:
            for tgid_str, tg in tgid_tags.items():
                if not isinstance(tg, dict):
                    continue
                try:
                    tgid = int(tgid_str)
                except (TypeError, ValueError):
                    continue
                key = (system, tgid)
                row = self._rows.get(key)
                if row is None:
                    if len(self._rows) >= MAX_ROWS:
                        continue
                    row = {'tag': '', 'last_seen': 0.0, 'last_freq': None, 'count': 0}
                    self._rows[key] = row

                changed = False
                tag = tg.get('tag') or ''
                if tag and tag != row['tag']:
                    row['tag'] = tag
                    changed = True

                seen = float(tg.get('last_seen') or 0)
                if seen > row['last_seen']:
                    row['last_seen'] = seen
                    changed = True
                    freq = tg.get('last_freq')
                    if freq:
                        row['last_freq'] = int(freq)
                elif row['last_freq'] is None and tg.get('last_freq'):
                    row['last_freq'] = int(tg['last_freq'])
                    changed = True

                reported = int(tg.get('count') or 0)
                previous = self._counted.get(key, 0)
                if reported > previous:
                    row['count'] += reported - previous
                    self._counted[key] = reported
                    changed = True
                elif reported < previous:
                    # The decoder restarted (or the tgid was re-created) and its
                    # counter went back to zero: rebase without double-counting.
                    self._counted[key] = reported
                    row['count'] += reported
                    changed = True

                if changed:
                    self._dirty.add(key)

    def merge_into(self, system: str, tgid_tags: dict[str, Any]) -> None:
        """Fill a tgid_tags block in place with the durable values.

        Mutates the dict the decoder just sent, so the browser sees one merged
        view and needs no idea that persistence exists.  Talkgroups known only
        from a previous run are *not* added: the payload describes what the
        decoder currently has configured, and /api/talkgroups is where the full
        history lives.
        """
        if not isinstance(tgid_tags, dict):
            return
        with self._lock:
            for tgid_str, tg in tgid_tags.items():
                if not isinstance(tg, dict):
                    continue
                try:
                    row = self._rows.get((system, int(tgid_str)))
                except (TypeError, ValueError):
                    continue
                if row is None:
                    continue
                if row['last_seen'] > float(tg.get('last_seen') or 0):
                    tg['last_seen'] = row['last_seen']
                    tg['last_freq'] = row['last_freq']
                elif not tg.get('last_freq') and row['last_freq']:
                    tg['last_freq'] = row['last_freq']
                tg['count'] = max(int(tg.get('count') or 0), row['count'])

    # ------------------------------------------------------------------
    # Read-out
    # ------------------------------------------------------------------

    def talkgroups(self, system: str | None = None) -> list[dict[str, Any]]:
        """Every talkgroup on record, newest activity first, never-heard last."""
        with self._lock:
            rows = [
                dict(row, system=sys_name, tgid=tgid)
                for (sys_name, tgid), row in self._rows.items()
                if system is None or sys_name == system
            ]
        rows.sort(key=lambda r: (-r['last_seen'], r['tgid']))
        return rows

    def stats(self) -> dict[str, Any]:
        """Summary counters.

        Deliberately no 'talkgroups' key: /api/talkgroups spreads this alongside
        its ``talkgroups`` list, and a same-named count would silently replace the
        list with an integer.
        """
        with self._lock:
            total = len(self._rows)
            heard = sum(1 for row in self._rows.values() if row['last_seen'] > 0)
            pending = len(self._dirty)
        return {
            'path':          self.path,
            'persistent':    self._db is not None,
            'total':         total,
            'heard':         heard,
            'pending_write': pending,
        }
