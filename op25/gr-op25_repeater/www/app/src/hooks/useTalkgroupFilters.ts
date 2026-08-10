import { useCallback, useMemo } from 'react';
import { useUiState } from './useUiState';
import { PATTERN_KINDS } from '../utils/talkgroupPatterns';
import type { PatternKind, TalkgroupPattern } from '../utils/talkgroupPatterns';

/**
 * The talkgroup browser's saved search patterns.
 *
 * Stored on the receiver beside the pins, for the same reason: a pattern set is
 * how someone found their talkgroups last time, and retyping `RCHP*` on every
 * visit — and again on the phone — is the navigation cost this is meant to
 * remove. The server caps and validates the list; see `ui_state.py`.
 *
 * Note this is *not* the scan list. Narrowing what you are looking at must not
 * narrow what the decoder receives — that still takes the explicit button.
 */

const KNOWN_KINDS = new Set(PATTERN_KINDS.map((k) => k.kind));

export interface TalkgroupFilters {
  patterns: TalkgroupPattern[];
  /** False when the receiver is too old to store these, so they live in this
   *  browser only. Worth telling the user, since the whole point of storing
   *  them receiver-side is that the phone and the desktop agree. */
  shared: boolean;
  add: (pattern: TalkgroupPattern) => void;
  update: (index: number, pattern: TalkgroupPattern) => void;
  removeAt: (index: number) => void;
  clear: () => void;
}

export function useTalkgroupFilters(): TalkgroupFilters {
  const { state, patch, unsupported } = useUiState();
  const shared = !unsupported.has('talkgroup_filters');

  const patterns = useMemo<TalkgroupPattern[]>(() => (
    (state.talkgroup_filters ?? [])
      .filter((p) => p && typeof p.text === 'string' && p.text.trim() !== '')
      // An unrecognised kind reads as plain text rather than being dropped: a
      // newer client may have written one this build has never heard of, and
      // losing the text the user typed is the worse outcome.
      .map((p) => ({
        kind: (KNOWN_KINDS.has(p.kind as PatternKind) ? p.kind : 'contains') as PatternKind,
        text: p.text,
      }))
  ), [state.talkgroup_filters]);

  const store = useCallback((next: TalkgroupPattern[]) => {
    patch({ talkgroup_filters: next });
  }, [patch]);

  const add = useCallback((pattern: TalkgroupPattern) => {
    const text = pattern.text.trim();
    if (!text) return;
    // Adding the same pattern twice is a no-op rather than a duplicate chip:
    // the filter is a union, so a repeat changes nothing but the clutter.
    if (patterns.some((p) => p.kind === pattern.kind && p.text === text)) return;
    store([...patterns, { ...pattern, text }]);
  }, [patterns, store]);

  const update = useCallback((index: number, pattern: TalkgroupPattern) => {
    store(patterns.map((p, i) => (i === index ? pattern : p)));
  }, [patterns, store]);

  const removeAt = useCallback((index: number) => {
    store(patterns.filter((_p, i) => i !== index));
  }, [patterns, store]);

  const clear = useCallback(() => store([]), [store]);

  return useMemo(
    () => ({ patterns, shared, add, update, removeAt, clear }),
    [patterns, shared, add, update, removeAt, clear],
  );
}
