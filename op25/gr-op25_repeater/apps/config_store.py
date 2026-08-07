"""
Editable configuration: a preset base, a user overlay, and a version history.

The problem this solves is that the two things we want are in tension. A config
that ships inside the add-on image keeps receiving fixes when the add-on updates;
a config the user owns does not (see addons/op25/presets/ and the 0.0.8 notes).
Editing in the GUI has to leave the first property intact.

So the effective config is composed, never stored:

    preset (read-only, in the image)  +  overlay (only what the user changed)

The overlay is *just the deltas*, which makes three operations fall out for free:

  * roll back to preset  -> discard the overlay
  * adopt preset changes -> nothing to do; unoverridden fields already track it,
                            and :meth:`preset_drift` reports the fields where an
                            override is now masking a newer preset value
  * export a full config -> compose and write it out, for `preset: custom`

Every write is recorded in SQLite as a version: the overlay before, the overlay
after, and a computed field-level diff. That is a history of *intent* (what the
user changed) rather than of whole files, so a rollback to any point is exact
even if the preset moved underneath it.

Storage rules follow tg_metadata.py deliberately: the in-memory state is
authoritative, sqlite mirrors it, and a bad path or corrupt file degrades to
memory-only with one log line. Losing the version history must never stop the
scanner from running -- and must never stop a config from being *saved* either,
which is why the overlay is a plain file and the database is only a log.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
import threading
import time
from typing import Any

from ha_bridge import REDACTED, SECRET_KEYS

# Keep the history bounded. Config edits are human-paced, so this is years of
# them; it exists so nothing can grow the database without limit.
MAX_VERSIONS = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS config_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'gui',
    summary     TEXT    NOT NULL DEFAULT '',
    base_id     TEXT    NOT NULL DEFAULT '',
    overlay     TEXT    NOT NULL,
    diff        TEXT    NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS config_versions_ts ON config_versions (ts DESC);
"""


# ---------------------------------------------------------------------------
# Merge / diff primitives
#
# These are the semantics of the whole module, so they are plain functions with
# no state: easy to test, and easy to reason about when a merge surprises you.
# ---------------------------------------------------------------------------


def deep_merge(base: Any, overlay: Any) -> Any:
    """Recursively merge *overlay* onto *base*, returning a new structure.

    Dicts merge key-by-key. **Lists of dicts merge element-wise by ``name``**
    when both sides carry one, and otherwise the overlay replaces the list
    outright.

    That list rule is the important one. ``jq``'s ``*`` replaces arrays, which
    would mean an overlay touching one field of ``devices[0]`` has to restate the
    whole device -- and then a preset fix to ``rate`` could never reach it, which
    is exactly the staleness this module exists to avoid. Merging by ``name``
    works because every list multi_rx cares about is keyed that way already:
    ``devices[].name``, ``channels[].name``, ``trunking.chans[].sysname``.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        # Deep-copy the untouched subtrees rather than aliasing them. dict(base)
        # is shallow, so callers of effective() would get references *into* the
        # preset and editing the returned config would silently rewrite the base
        # -- which then makes the overlay look empty and the diff look empty,
        # because the "before" it is compared against has already changed.
        out = {k: copy.deepcopy(v) for k, v in base.items()}
        for key, value in overlay.items():
            out[key] = deep_merge(base.get(key), value) if key in base else copy.deepcopy(value)
        return out

    if isinstance(base, list) and isinstance(overlay, list):
        key = _list_key(base, overlay)
        if key is None:
            return copy.deepcopy(overlay)
        out_list = [copy.deepcopy(item) for item in base]
        index = {item[key]: i for i, item in enumerate(out_list)
                 if isinstance(item, dict) and key in item}
        for item in overlay:
            if isinstance(item, dict) and key in item and item[key] in index:
                pos = index[item[key]]
                out_list[pos] = deep_merge(out_list[pos], item)
            else:
                out_list.append(copy.deepcopy(item))
        return out_list

    return copy.deepcopy(overlay)


def _list_key(base: list[Any], overlay: list[Any]) -> str | None:
    """The identity field to merge two lists on, or None to replace wholesale."""
    for candidate in ('name', 'sysname', 'instance_name'):
        if all(isinstance(i, dict) and candidate in i for i in base) and \
           all(isinstance(i, dict) and candidate in i for i in overlay) and base:
            return candidate
    return None


def prune_overlay(base: Any, overlay: Any) -> Any:
    """Drop anything in *overlay* that already equals *base*.

    Keeps the overlay honest: it must contain only genuine overrides, or a value
    that merely happens to match today's preset would silently pin itself and
    stop tracking a future change to it. Returns ``None`` when nothing is left.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        out: dict[str, Any] = {}
        for key, value in overlay.items():
            if key not in base:
                out[key] = copy.deepcopy(value)
                continue
            pruned = prune_overlay(base[key], value)
            if pruned is not None:
                out[key] = pruned
        return out or None

    if isinstance(base, list) and isinstance(overlay, list):
        key = _list_key(base, overlay)
        if key is None:
            return None if base == overlay else copy.deepcopy(overlay)
        index = {i[key]: i for i in base if isinstance(i, dict) and key in i}
        kept: list[Any] = []
        for item in overlay:
            if isinstance(item, dict) and key in item and item[key] in index:
                pruned = prune_overlay(index[item[key]], item)
                if pruned is not None:
                    # Carry the identity field so the merge can find it again.
                    pruned[key] = item[key]
                    kept.append(pruned)
            else:
                kept.append(copy.deepcopy(item))
        return kept or None

    return None if base == overlay else copy.deepcopy(overlay)


def flatten(node: Any, prefix: str = '') -> dict[str, Any]:
    """Flatten to ``{'devices[sdr0].gains': 'LNA:40'}`` style paths.

    Lists are indexed by their identity field rather than by position, so a diff
    stays readable and stays correct when something is inserted ahead of it.
    """
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(flatten(value, f'{prefix}.{key}' if prefix else str(key)))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            label = i
            if isinstance(item, dict):
                for candidate in ('name', 'sysname', 'instance_name'):
                    if candidate in item:
                        label = item[candidate]
                        break
            out.update(flatten(item, f'{prefix}[{label}]'))
    else:
        out[prefix] = node
    return out


def diff_fields(before: Any, after: Any) -> list[dict[str, Any]]:
    """Field-level diff between two structures, as a list of change records."""
    flat_before, flat_after = flatten(before or {}), flatten(after or {})
    changes: list[dict[str, Any]] = []
    for path in sorted(set(flat_before) | set(flat_after)):
        old, new = flat_before.get(path), flat_after.get(path)
        if old == new:
            continue
        if path not in flat_before:
            changes.append({'path': path, 'op': 'add', 'new': new})
        elif path not in flat_after:
            changes.append({'path': path, 'op': 'remove', 'old': old})
        else:
            changes.append({'path': path, 'op': 'change', 'old': old, 'new': new})
    return changes


def unredact(proposed: Any, current: Any) -> Any:
    """Replace masked secrets in *proposed* with their value from *current*.

    The config is served to the browser with secrets masked (``ha_bridge``
    ``redact_config``), so an editor that reads, edits one field and writes back
    would otherwise persist the literal ``***redacted***`` as the token -- and
    the failure would show up later as a Home Assistant 401, a long way from the
    edit that caused it. A masked value means "unchanged", which is the only
    thing it can honestly mean.
    """
    if isinstance(proposed, dict):
        out = {}
        for key, value in proposed.items():
            base_value = current.get(key) if isinstance(current, dict) else None
            if key in SECRET_KEYS and value == REDACTED:
                if base_value is not None:
                    out[key] = base_value
                continue
            out[key] = unredact(value, base_value)
        return out
    if isinstance(proposed, list):
        cur_list = current if isinstance(current, list) else []
        return [unredact(v, cur_list[i] if i < len(cur_list) else None)
                for i, v in enumerate(proposed)]
    return proposed


def strip_doc_keys(node: Any) -> Any:
    """Remove ``#``-prefixed documentation keys, as the add-on run script does."""
    if isinstance(node, dict):
        return {k: strip_doc_keys(v) for k, v in node.items() if not str(k).startswith('#')}
    if isinstance(node, list):
        return [strip_doc_keys(v) for v in node]
    return node


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def overlay_path(config: dict[str, Any] | None) -> str | None:
    """Where the overlay lives, or None to disable editing entirely.

    ``$OP25_CONFIG_OVERLAY`` wins, then ``terminal.config_overlay``, then a
    default in the cwd -- which is the user's data directory, the same place
    tg_metadata puts its database and multi_rx resolves tag files against.
    Either source may be set empty to make the config read-only.
    """
    env = os.environ.get('OP25_CONFIG_OVERLAY')
    if env is not None:
        return env.strip() or None
    terminal = (config or {}).get('terminal', {}) or {}
    if 'config_overlay' in terminal:
        configured = terminal.get('config_overlay')
        if configured is False or configured is None:
            return None
        return str(configured).strip() or None
    return 'op25_config_overlay.json'


def history_db_path(config: dict[str, Any] | None) -> str | None:
    """Where the version history lives, or None for no history."""
    env = os.environ.get('OP25_CONFIG_HISTORY_DB')
    if env is not None:
        return env.strip() or None
    terminal = (config or {}).get('terminal', {}) or {}
    if 'config_history_db' in terminal:
        configured = terminal.get('config_history_db')
        if configured is False or configured is None:
            return None
        return str(configured).strip() or None
    return 'op25_config_history.sqlite'


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class ConfigStore:
    """Composes preset + overlay, persists the overlay, logs every version."""

    def __init__(self,
                 base: dict[str, Any],
                 overlay_file: str | None = None,
                 history_file: str | None = None,
                 base_id: str = '') -> None:
        #: The preset / file the decoder was started from. Never written.
        self.base = strip_doc_keys(copy.deepcopy(base))
        #: Identifies the base in the history, e.g. "preset:palmetto800".
        self.base_id = base_id
        self.overlay_file = overlay_file
        self._lock = threading.RLock()
        self._overlay: dict[str, Any] = {}
        self._db: sqlite3.Connection | None = None
        self._broken = False

        if overlay_file:
            self._load_overlay()
        if history_file:
            self._open_history(history_file)

    # -- overlay file ---------------------------------------------------

    def _load_overlay(self) -> None:
        path = self.overlay_file
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path) as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise ValueError('overlay must be a JSON object')
            self._overlay = strip_doc_keys(loaded)
            sys.stderr.write('config overlay: %d top-level override(s) from %s\n'
                             % (len(self._overlay), path))
        except (OSError, ValueError) as e:
            # Refusing to start because a config *override* is corrupt would be
            # worse than ignoring it: the preset alone is a working scanner.
            sys.stderr.write('config overlay ignored (%s: %s)\n' % (path, e))
            self._overlay = {}

    def _write_overlay(self) -> None:
        """Atomically replace the overlay file. Raises on failure."""
        path = self.overlay_file
        if not path:
            raise RuntimeError('config editing is disabled (no overlay path)')
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + '.tmp'
        # Write-then-rename: a crash mid-write must not leave a half-written
        # overlay that the next start would refuse or, worse, half-apply.
        with open(tmp, 'w') as fh:
            json.dump(self._overlay, fh, indent=4, sort_keys=True)
            fh.write('\n')
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    # -- history db -----------------------------------------------------

    def _open_history(self, path: str) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.executescript(_SCHEMA)
            self._db.commit()
            sys.stderr.write('config history: %s (%d version(s))\n'
                             % (path, self.version_count()))
        except (sqlite3.Error, OSError) as e:
            self._fail('open %s' % path, e)

    def _fail(self, what: str, exc: Exception) -> None:
        """Log once and carry on without history. Never fatal, never blocks a save."""
        if not self._broken:
            self._broken = True
            sys.stderr.write('config history disabled (%s: %s)\n' % (what, exc))
        if self._db is not None:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
            self._db = None

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                try:
                    self._db.commit()
                    self._db.close()
                except sqlite3.Error:
                    pass
                self._db = None

    # -- reading --------------------------------------------------------

    @property
    def editable(self) -> bool:
        return bool(self.overlay_file)

    def overlay(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._overlay)

    def effective(self) -> dict[str, Any]:
        """preset + overlay: what the decoder should be running."""
        with self._lock:
            return deep_merge(self.base, self._overlay)

    def preset_drift(self) -> list[dict[str, Any]]:
        """Fields where an override is masking a *different* preset value.

        This is the "adopt preset changes" report. Unoverridden fields already
        track the preset with no action needed, so what a user actually needs to
        see after an update is the short list where their override now differs
        from a preset that has moved -- e.g. they pinned ``gains`` at 30 and the
        preset has since gone to 40.
        """
        flat_base = flatten(self.base)
        flat_eff = flatten(self.effective())
        out = []
        for path, overridden in flat_eff.items():
            if path in flat_base and flat_base[path] != overridden:
                out.append({'path': path,
                            'preset': flat_base[path],
                            'override': overridden})
        return sorted(out, key=lambda d: d['path'])

    # -- writing --------------------------------------------------------

    def save(self, proposed: dict[str, Any], source: str = 'gui',
             summary: str = '') -> dict[str, Any]:
        """Store *proposed* (a full effective config) as overrides of the base.

        The caller hands over what it wants to be running, not a patch: that is
        what a form or a JSON editor naturally produces. The delta against the
        base is computed here, so a field the user set back to the preset value
        stops being an override rather than silently pinning itself.
        """
        with self._lock:
            before = copy.deepcopy(self._overlay)
            # A masked secret means "unchanged" -- see unredact().
            wanted = unredact(strip_doc_keys(proposed), self.effective())
            pruned = prune_overlay(self.base, wanted) or {}
            self._overlay = pruned
            try:
                self._write_overlay()
            except (OSError, RuntimeError):
                self._overlay = before          # leave memory matching disk
                raise
            version = self._record(before, pruned, source, summary)
        return version

    def reset_to_preset(self, source: str = 'gui') -> dict[str, Any]:
        """Discard every override. The rollback that always exists."""
        return self.save({}, source=source, summary='reset to preset')

    def rollback(self, version_id: int, source: str = 'gui') -> dict[str, Any]:
        """Restore the overlay recorded *after* version *version_id*.

        Restoring an overlay rather than a whole config is what makes this exact
        across a preset update: it replays the user's intent onto today's base,
        so a rollback never silently reinstates an old preset value they never
        chose.
        """
        row = self.version(version_id)
        if row is None:
            raise KeyError('no such config version: %s' % version_id)
        with self._lock:
            before = copy.deepcopy(self._overlay)
            self._overlay = strip_doc_keys(row['overlay'])
            try:
                self._write_overlay()
            except (OSError, RuntimeError):
                self._overlay = before
                raise
            return self._record(before, self._overlay, source,
                                'rollback to version %d' % version_id)

    def export(self, path: str) -> str:
        """Write the effective config out as a standalone file.

        For graduating to ``preset: custom``: the result is fully owned and no
        longer tracks the preset, which is the trade the user is making by
        exporting. Returns the path written.
        """
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(self.effective(), fh, indent=4)
            fh.write('\n')
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return path

    # -- history --------------------------------------------------------

    def _record(self, before: dict[str, Any], after: dict[str, Any],
                source: str, summary: str) -> dict[str, Any]:
        """Append a version row. Assumes the lock is held."""
        changes = diff_fields(deep_merge(self.base, before),
                              deep_merge(self.base, after))
        version = {
            'id': None,
            'ts': time.time(),
            'source': source,
            'summary': summary or _summarise(changes),
            'base_id': self.base_id,
            'overlay': copy.deepcopy(after),
            'diff': changes,
        }
        if self._db is None:
            return version
        try:
            cur = self._db.execute(
                'INSERT INTO config_versions (ts, source, summary, base_id, overlay, diff)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (version['ts'], source, version['summary'], self.base_id,
                 json.dumps(after), json.dumps(changes)))
            version['id'] = cur.lastrowid
            self._db.execute(
                'DELETE FROM config_versions WHERE id NOT IN '
                '(SELECT id FROM config_versions ORDER BY id DESC LIMIT ?)',
                (MAX_VERSIONS,))
            self._db.commit()
        except sqlite3.Error as e:
            self._fail('insert', e)
        return version

    def _row_to_version(self, row: tuple) -> dict[str, Any]:
        return {
            'id': row[0],
            'ts': row[1],
            'source': row[2],
            'summary': row[3],
            'base_id': row[4],
            'overlay': json.loads(row[5]),
            'diff': json.loads(row[6]),
        }

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if self._db is None:
                return []
            try:
                rows = self._db.execute(
                    'SELECT id, ts, source, summary, base_id, overlay, diff'
                    ' FROM config_versions ORDER BY id DESC LIMIT ?',
                    (max(1, int(limit)),)).fetchall()
            except sqlite3.Error as e:
                self._fail('select', e)
                return []
        return [self._row_to_version(r) for r in rows]

    def version(self, version_id: int) -> dict[str, Any] | None:
        with self._lock:
            if self._db is None:
                return None
            try:
                row = self._db.execute(
                    'SELECT id, ts, source, summary, base_id, overlay, diff'
                    ' FROM config_versions WHERE id = ?', (int(version_id),)).fetchone()
            except sqlite3.Error as e:
                self._fail('select', e)
                return None
        return self._row_to_version(row) if row else None

    def version_count(self) -> int:
        if self._db is None:
            return 0
        try:
            return int(self._db.execute(
                'SELECT COUNT(*) FROM config_versions').fetchone()[0])
        except sqlite3.Error:
            return 0

    def stats(self) -> dict[str, Any]:
        """Deliberately has no 'history' key -- see tg_metadata.stats()."""
        with self._lock:
            return {
                'editable': self.editable,
                'overlay_file': self.overlay_file,
                'overrides': len(flatten(self._overlay)),
                'base_id': self.base_id,
                'versions': self.version_count(),
                'history_enabled': self._db is not None,
            }


def _summarise(changes: list[dict[str, Any]]) -> str:
    if not changes:
        return 'no change'
    if len(changes) == 1:
        c = changes[0]
        if c['op'] == 'change':
            return '%s: %s -> %s' % (c['path'], c.get('old'), c.get('new'))
        return '%s %s' % (c['op'], c['path'])
    return '%d field(s) changed' % len(changes)
