/**
 * Scanner state stored on the receiver: pins, holds, the selected channel.
 *
 * These used to live in `localStorage`, which loses them in two ways that are
 * easy to mistake for a bug. It is per *origin*, so the same scanner reached
 * through Home Assistant ingress and through port 8099 keeps two separate sets;
 * and it is per browser, so a phone and a desktop never agree.
 *
 * `localStorage` is still written, but only as a fallback for the first paint
 * and for a server too old to have `/api/ui-state`. The server is the source of
 * truth whenever it answers.
 *
 * Display preferences — theme, accent colour, which cards are collapsed — stay
 * in `localStorage` on purpose. Those are per device: a phone wants dark and a
 * desk monitor may not.
 */

import { useEffect, useState } from 'react';
import { apiUrl } from '../utils/url';

export interface UiStateDoc {
  focused_talkgroups?: number[];
  focus_only?: boolean;
  holds?: Record<string, number>;
  selected_channel?: number | null;
  audio_source?: string | null;
}

const CACHE_KEY = 'op25.uiState';

/** How long to coalesce writes. Pinning a run of talkgroups should be one PUT,
 *  not one per click, but the delay has to stay short enough that a reload right
 *  after a click does not lose it. */
const FLUSH_MS = 400;

function readCache(): UiStateDoc {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) as UiStateDoc : {};
  } catch {
    return {};   // private-mode Safari throws; a hand-edited value can be anything
  }
}

function writeCache(doc: UiStateDoc): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(doc));
  } catch {
    /* nothing we can do, and nothing that needs doing */
  }
}

export interface UseUiState {
  state: UiStateDoc;
  /** True once the server has answered — before that, `state` is the cache. */
  loaded: boolean;
  /** Whether the receiver is actually storing this, or we are cache-only. */
  persistent: boolean;
  /** Merge a patch. Applies locally at once, then syncs. */
  patch: (patch: UiStateDoc) => void;
}

// ---------------------------------------------------------------------------
// One document per page, shared by every caller.
//
// Module-level rather than per-hook state: two components calling useUiState()
// would otherwise each fetch, each hold their own copy, and drift apart the
// moment one of them wrote. There is exactly one receiver, so there is exactly
// one document.
// ---------------------------------------------------------------------------

let doc: UiStateDoc = readCache();
let docLoaded = false;
let docPersistent = false;
let fetchStarted = false;
const listeners = new Set<() => void>();

/** Pending patch and its timer, so a burst of clicks becomes one request. */
let pending: UiStateDoc = {};
let timer: ReturnType<typeof setTimeout> | null = null;

function announce(): void {
  listeners.forEach((fn) => fn());
}

function setDoc(next: UiStateDoc): void {
  doc = next;
  writeCache(next);
  announce();
}

async function flush(): Promise<void> {
  const body = pending;
  pending = {};
  timer = null;
  if (Object.keys(body).length === 0) return;
  try {
    const resp = await fetch(apiUrl('api/ui-state'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: body }),
    });
    if (!resp.ok) return;
    const answer = await resp.json();
    docPersistent = Boolean(answer.persistent);
    // Adopt what the server stored rather than what we sent: it normalises
    // (sorts and dedupes the pin list, drops a released hold), and disagreeing
    // about that would make the next comparison look dirty forever.
    if (answer.state) setDoc(answer.state);
    else announce();
  } catch {
    /* the local copy still applies; the next patch will try again */
  }
}

function patchDoc(next: UiStateDoc): void {
  setDoc({ ...doc, ...next });
  pending = { ...pending, ...next };
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => { void flush(); }, FLUSH_MS);
}

async function loadOnce(): Promise<void> {
  if (fetchStarted) return;
  fetchStarted = true;
  try {
    const resp = await fetch(apiUrl('api/ui-state'));
    if (!resp.ok) return;                  // older server: stay on the cache
    const body = await resp.json();
    docPersistent = Boolean(body.persistent);
    // The server wins. Merging the cache over it would resurrect pins the user
    // cleared on another device.
    setDoc(body.state ?? {});
  } catch {
    /* offline or no such endpoint — the cache is already loaded */
  } finally {
    docLoaded = true;
    announce();
  }
}

// A tab closing mid-debounce should not lose the click that caused it.
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => { if (timer) void flush(); });
}

export function useUiState(): UseUiState {
  const [, bump] = useState(0);

  useEffect(() => {
    const fn = () => bump((n) => n + 1);
    listeners.add(fn);
    void loadOnce();
    return () => { listeners.delete(fn); };
  }, []);

  return {
    state: doc,
    loaded: docLoaded,
    persistent: docPersistent,
    patch: patchDoc,
  };
}
