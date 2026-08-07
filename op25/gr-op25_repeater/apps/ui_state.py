"""
Scanner state that belongs to the receiver, not to a browser.

Pins, holds and scan lists were split across two places that both lose them:
localStorage, which is per browser *and per origin* — so the same scanner reached
through Home Assistant ingress and through port 8099 keeps two separate sets —
and the decoder's own memory, which is gone on restart.

This is the third small persisted store in ``apps/``, alongside
``tg_metadata`` (talkgroup history) and ``config_store`` (the config overlay).
It is deliberately not folded into either:

  * the config overlay is *decoder configuration*. Putting a pin toggle there
    would file it in the config editor's diff and version history, so pinning a
    talkgroup would read as changing the receiver's setup.
  * tg_metadata is per-talkgroup observation, keyed by (system, tgid), and this
    is neither.

A flat JSON document, because it is small, read once at startup and written when
a human clicks something. Same degradation rule as its siblings: a bad path or a
corrupt file logs once and runs memory-only. Losing your pins must never stop the
scanner.

**Display preferences stay in the browser.** Theme, accent colour and which cards
are collapsed are per *device* — a phone wants dark and a desk monitor may not —
so they are not here.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from typing import Any

#: Keys the store will accept. An allow-list rather than a free-for-all: this
#: file is written from an unauthenticated endpoint, so it must not become a
#: place to park arbitrary data on someone's SD card.
KNOWN_KEYS = (
    'focused_talkgroups',   # list[int]  — pinned talkgroups
    'focus_only',           # bool       — hide everything unpinned
    'holds',                # {channel: tgid} — active holds, by channel name
    'selected_channel',     # int | None
    'audio_source',         # str | None — which stream the player last used
)

#: Cap on the pinned list. Pinning is a manual act; this exists so a scripted
#: client cannot grow the file without bound.
MAX_FOCUSED = 2_000


def state_path(config: dict[str, Any] | None) -> str | None:
    """Where the file lives, or None to disable persistence.

    ``$OP25_UI_STATE`` wins, then ``terminal.ui_state``, then a default in the
    cwd — the user's data directory, where tg_metadata and the config overlay
    also land. Either may be set empty to turn persistence off.
    """
    env = os.environ.get('OP25_UI_STATE')
    if env is not None:
        return env.strip() or None
    terminal = (config or {}).get('terminal', {}) or {}
    if 'ui_state' in terminal:
        configured = terminal.get('ui_state')
        if configured is False or configured is None:
            return None
        return str(configured).strip() or None
    return 'op25_ui_state.json'


def _clean(key: str, value: Any) -> Any:
    """Coerce *value* into the shape *key* is allowed to hold, or raise."""
    if key == 'focused_talkgroups':
        if not isinstance(value, list):
            raise ValueError('focused_talkgroups must be a list')
        out = sorted({int(v) for v in value
                      if isinstance(v, (int, float)) and not isinstance(v, bool)
                      and 0 < int(v) < 0x10000})
        return out[:MAX_FOCUSED]
    if key == 'focus_only':
        return bool(value)
    if key == 'holds':
        if not isinstance(value, dict):
            raise ValueError('holds must be an object keyed by channel')
        # 0 means "no hold" in the decoder's own vocabulary, so it is dropped
        # rather than stored -- a released hold should not be re-applied.
        return {str(k): int(v) for k, v in value.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) > 0}
    if key == 'selected_channel':
        return None if value is None else int(value)
    if key == 'audio_source':
        return None if value is None else str(value)[:200]
    raise KeyError(key)


class UiState:
    """A small persisted document. In-memory copy is authoritative."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._broken = False
        if path:
            self._load()

    def _load(self) -> None:
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path) as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise ValueError('ui state must be a JSON object')
        except (OSError, ValueError) as e:
            self._fail('read %s' % self.path, e)
            return
        for key, value in loaded.items():
            if key not in KNOWN_KEYS:
                continue
            try:
                self._data[key] = _clean(key, value)
            except (KeyError, TypeError, ValueError):
                continue        # one bad key must not lose the rest
        sys.stderr.write('ui state: %d key(s) from %s\n' % (len(self._data), self.path))

    def _fail(self, what: str, exc: Exception) -> None:
        if not self._broken:
            self._broken = True
            sys.stderr.write('ui state not persisted (%s: %s)\n' % (what, exc))

    def _write(self) -> None:
        if not self.path:
            return
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = self.path + '.tmp'
            # Write-then-rename: a crash mid-write must not leave a truncated
            # document that the next start refuses.
            with open(tmp, 'w') as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
                fh.write('\n')
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except OSError as e:
            self._fail('write %s' % self.path, e)

    # -- reading --------------------------------------------------------

    @property
    def persistent(self) -> bool:
        return bool(self.path) and not self._broken

    def all(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))

    # -- writing --------------------------------------------------------

    def merge(self, patch: dict[str, Any]) -> dict[str, str]:
        """Apply *patch*, ignoring unknown keys. Returns {key: reason} for rejects.

        A merge rather than a replace so two panels — or two browsers — can each
        own the keys they know about without clobbering the rest.
        """
        rejected: dict[str, str] = {}
        with self._lock:
            changed = False
            for key, value in (patch or {}).items():
                if key not in KNOWN_KEYS:
                    rejected[key] = 'unknown key'
                    continue
                try:
                    cleaned = _clean(key, value)
                except (KeyError, TypeError, ValueError) as e:
                    rejected[key] = str(e) or 'invalid value'
                    continue
                if self._data.get(key) != cleaned:
                    self._data[key] = cleaned
                    changed = True
            if changed:
                self._write()
        return rejected

    def set_hold(self, channel: str, tgid: int) -> None:
        """Record (or clear, when *tgid* is 0) a hold so a restart can restore it."""
        with self._lock:
            holds = dict(self._data.get('holds') or {})
            if tgid > 0:
                holds[str(channel)] = int(tgid)
            else:
                holds.pop(str(channel), None)
            if holds != self._data.get('holds'):
                self._data['holds'] = holds
                self._write()

    def stats(self) -> dict[str, Any]:
        """Note the absence of a 'holds' key: /api/ui-state spreads this next to
        the document itself, and a same-named counter would replace the map with
        an integer. Same trap as tg_metadata.stats() and config_store.stats()."""
        with self._lock:
            return {
                'persistent': self.persistent,
                'path': self.path,
                'focused_count': len(self._data.get('focused_talkgroups') or []),
                'hold_count': len(self._data.get('holds') or {}),
            }
