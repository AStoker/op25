import { useCallback, useMemo } from 'react';
import { useUiState } from './useUiState';

/**
 * The set of talkgroups the user has picked out to watch.
 *
 * Purely a display concern: focused talkgroups sort to the top of the talkgroup
 * table and can filter it, but the decoder keeps scanning everything unless the
 * user explicitly applies the selection as a scan list. That separation is
 * deliberate — narrowing what you are *looking at* should not silently narrow
 * what gets recorded and transcribed.
 *
 * Stored on the receiver via useUiState, not in localStorage.
 *
 * It used to be per browser, on the reasoning that two people watching one
 * receiver should not fight over it. In practice the cost of that outweighed the
 * benefit: localStorage is per *origin*, so the same scanner reached through Home
 * Assistant ingress and through port 8099 kept two separate sets of pins, and a
 * phone never agreed with a desktop. Pins read as scanner state, and they now
 * are. Display preferences (theme, accent, card collapse) stay per browser,
 * because those genuinely are per device.
 */

export interface TalkgroupFocus {
  focused: ReadonlySet<number>;
  /** Whether the table should hide everything not focused. */
  focusOnly: boolean;
  setFocusOnly: (only: boolean) => void;
  toggle: (tgid: number) => void;
  /** Add every tgid in *tgids* to the selection. */
  add: (tgids: Iterable<number>) => void;
  /** Remove every tgid in *tgids* from the selection. */
  remove: (tgids: Iterable<number>) => void;
  /** Replace the whole selection. */
  replace: (tgids: Iterable<number>) => void;
  clear: () => void;
}

export function useTalkgroupFocus(): TalkgroupFocus {
  const { state, patch } = useUiState();

  const focused = useMemo(
    () => new Set(state.focused_talkgroups ?? []),
    [state.focused_talkgroups],
  );
  const focusOnly = Boolean(state.focus_only) && focused.size > 0;

  const store = useCallback((next: Set<number>) => {
    patch({ focused_talkgroups: [...next].sort((a, b) => a - b) });
  }, [patch]);

  const toggle = useCallback((tgid: number) => {
    const next = new Set(focused);
    if (!next.delete(tgid)) next.add(tgid);
    store(next);
  }, [focused, store]);

  const add = useCallback((tgids: Iterable<number>) => {
    const next = new Set(focused);
    for (const t of tgids) next.add(t);
    store(next);
  }, [focused, store]);

  const remove = useCallback((tgids: Iterable<number>) => {
    const next = new Set(focused);
    for (const t of tgids) next.delete(t);
    store(next);
  }, [focused, store]);

  const replace = useCallback((tgids: Iterable<number>) => {
    store(new Set(tgids));
  }, [store]);

  const clear = useCallback(() => store(new Set()), [store]);

  // Showing "focused only" with nothing focused would empty the table, which
  // reads as a bug rather than as a filter.
  const setFocusOnly = useCallback((only: boolean) => {
    patch({ focus_only: only && focused.size > 0 });
  }, [patch, focused.size]);

  return useMemo(
    () => ({ focused, focusOnly, setFocusOnly, toggle, add, remove, replace, clear }),
    [focused, focusOnly, setFocusOnly, toggle, add, remove, replace, clear],
  );
}
