import { useCallback, useEffect, useMemo, useState } from 'react';

/**
 * The set of talkgroups the user has picked out to watch.
 *
 * Purely a display concern: focused talkgroups sort to the top of the talkgroup
 * table and can filter it, but the decoder keeps scanning everything unless the
 * user explicitly applies the selection as a scan list. That separation is
 * deliberate — narrowing what you are *looking at* should not silently narrow
 * what gets recorded and transcribed.
 *
 * Kept in localStorage rather than on the server for the same reason the theme
 * and display preferences are: it is per browser, not per decoder, and two people
 * watching one receiver should not fight over it.
 */

const STORAGE_KEY = 'op25.focusedTalkgroups';

function load(): Set<number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((t): t is number => Number.isInteger(t) && t > 0));
  } catch {
    // Private-mode Safari throws on localStorage, and a hand-edited value can be
    // anything at all. Neither is worth breaking the table over.
    return new Set();
  }
}

function save(tgids: Set<number>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...tgids].sort((a, b) => a - b)));
  } catch {
    /* nothing we can do, and nothing that needs doing */
  }
}

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
  const [focused, setFocused] = useState<Set<number>>(load);
  const [focusOnly, setFocusOnlyState] = useState(false);

  useEffect(() => { save(focused); }, [focused]);

  const toggle = useCallback((tgid: number) => {
    setFocused((prev) => {
      const next = new Set(prev);
      if (!next.delete(tgid)) next.add(tgid);
      return next;
    });
  }, []);

  const add = useCallback((tgids: Iterable<number>) => {
    setFocused((prev) => {
      const next = new Set(prev);
      for (const t of tgids) next.add(t);
      return next;
    });
  }, []);

  const remove = useCallback((tgids: Iterable<number>) => {
    setFocused((prev) => {
      const next = new Set(prev);
      for (const t of tgids) next.delete(t);
      return next;
    });
  }, []);

  const replace = useCallback((tgids: Iterable<number>) => {
    setFocused(new Set(tgids));
  }, []);

  const clear = useCallback(() => setFocused(new Set()), []);

  // Showing "focused only" with nothing focused would empty the table, which
  // reads as a bug rather than as a filter.
  const setFocusOnly = useCallback((only: boolean) => {
    setFocusOnlyState(only && focused.size > 0);
  }, [focused.size]);

  useEffect(() => {
    if (focused.size === 0) setFocusOnlyState(false);
  }, [focused.size]);

  return useMemo(
    () => ({ focused, focusOnly, setFocusOnly, toggle, add, remove, replace, clear }),
    [focused, focusOnly, setFocusOnly, toggle, add, remove, replace, clear],
  );
}
