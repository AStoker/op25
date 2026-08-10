/**
 * Scanner state stored on the receiver: pins, holds, the selected channel.
 *
 * These used to live in `localStorage`, which loses them in two ways that are
 * easy to mistake for a bug. It is per *origin*, so the same scanner reached
 * through Home Assistant ingress and through port 8099 keeps two separate sets;
 * and it is per browser, so a phone and a desktop never agree.
 *
 * `localStorage` is still written, but only as a fallback for the first paint,
 * for a server too old to have `/api/ui-state`, and for a server too old to know
 * a particular *key*. The server is the source of truth whenever it answers.
 *
 * That last case is not hypothetical: `KNOWN_KEYS` in `ui_state.py` is an
 * allow-list, so a browser built from newer source than the receiver it is
 * pointed at — exactly what `OP25_BACKEND=… yarn dev` produces, and what an
 * add-on that has not been updated produces — gets its write answered with
 * `rejected: {key: "unknown key"}` and a state that has no such key. Adopting
 * that answer wholesale threw the user's input away a moment after they typed
 * it. Rejected keys are therefore kept locally instead, and the rejection is
 * remembered so a page reload does not lose them either.
 *
 * Display preferences — theme, accent colour, which cards are collapsed — stay
 * in `localStorage` on purpose. Those are per device: a phone wants dark and a
 * desk monitor may not.
 */

import { useEffect, useState } from 'react';
import { notify } from '../services/toastService';
import { apiUrl } from '../utils/url';

export interface UiStateDoc {
  focused_talkgroups?: number[];
  focus_only?: boolean;
  /** Saved talkgroup-browser search patterns, OR'd together. */
  talkgroup_filters?: { kind: string; text: string }[];
  holds?: Record<string, number>;
  selected_channel?: number | null;
  audio_source?: string | null;
}

const CACHE_KEY = 'op25.uiState';

/** What a stored key is called in a sentence. The toast is read by someone who
 *  has never seen `ui_state.py`, and "talkgroup_filters" names nothing to them. */
const KEY_NAMES: Record<string, string> = {
  focused_talkgroups: 'pinned talkgroups',
  focus_only: 'the pinned-only filter',
  talkgroup_filters: 'search patterns',
  holds: 'holds',
  selected_channel: 'the selected channel',
  audio_source: 'the selected audio source',
};

/** Keys this receiver has refused. Persisted, because the refusal happens on a
 *  write and the loss it causes would otherwise happen again on the next load,
 *  before any write has been attempted. */
const UNSUPPORTED_KEY = 'op25.uiStateUnsupported';

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

function readUnsupported(): Set<string> {
  try {
    const raw = localStorage.getItem(UNSUPPORTED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

function writeUnsupported(keys: Set<string>): void {
  try {
    localStorage.setItem(UNSUPPORTED_KEY, JSON.stringify([...keys]));
  } catch {
    /* as above */
  }
}

/** The subset of *doc* the server will not store, so we must keep ourselves. */
function localOnly(source: UiStateDoc, keys: Set<string>): UiStateDoc {
  const out: Record<string, unknown> = {};
  for (const key of keys) {
    const value = (source as Record<string, unknown>)[key];
    if (value !== undefined) out[key] = value;
  }
  return out as UiStateDoc;
}

export interface UseUiState {
  state: UiStateDoc;
  /** True once the server has answered — before that, `state` is the cache. */
  loaded: boolean;
  /** Whether the receiver is actually storing this, or we are cache-only. */
  persistent: boolean;
  /** Keys this receiver rejected — held in `localStorage` only, so they do not
   *  follow the user to another browser. Worth saying so in the UI. */
  unsupported: ReadonlySet<string>;
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
let unsupported: Set<string> = readUnsupported();
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
  const sent = Object.keys(body);
  if (sent.length === 0) return;
  try {
    const resp = await fetch(apiUrl('api/ui-state'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: body }),
    });
    if (!resp.ok) {
      notify({
        key: 'ui-state-write',
        severity: 'error',
        message: 'Could not save scanner state',
        detail: `The receiver answered HTTP ${resp.status}. Pins, holds and `
          + 'saved patterns are being kept in this browser only.',
      });
      return;
    }
    const answer = await resp.json();
    docPersistent = Boolean(answer.persistent);

    // Which of the keys we just sent does this receiver understand? Recomputed
    // from every write rather than latched, so upgrading the add-on heals it:
    // the first accepted write of a key drops it back out of the set.
    const rejected: Record<string, string> = answer.rejected ?? {};
    const before = new Set(unsupported);
    for (const key of sent) {
      if (key in rejected) unsupported.add(key);
      else unsupported.delete(key);
    }
    const news = [...unsupported].filter((k) => !before.has(k));
    if (news.length > 0 || unsupported.size !== before.size) writeUnsupported(unsupported);
    if (news.length > 0) {
      // Say it out loud. This used to be silent, and the only visible effect
      // was the user's input reverting a moment after they typed it -- which
      // reads as a broken UI rather than as an out-of-date receiver.
      notify({
        key: 'ui-state-unsupported',
        severity: 'warning',
        message: 'This receiver cannot save '
          + news.map((k) => KEY_NAMES[k] ?? k).join(' or '),
        detail: 'Kept in this browser instead, so it will not follow you to '
          + 'another device. Updating the OP25 add-on fixes it.',
      });
    }

    // Adopt what the server stored rather than what we sent: it normalises
    // (sorts and dedupes the pin list, drops a released hold), and disagreeing
    // about that would make the next comparison look dirty forever. Keys it
    // refused are the exception — they are absent from its answer, and taking
    // that literally would delete what the user just typed.
    if (answer.state) setDoc({ ...answer.state, ...localOnly(doc, unsupported) });
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
    // The server wins, key by key. Merging the whole cache over it would
    // resurrect pins the user cleared on another device — but a key this
    // receiver has already told us it does not know is one it can never be the
    // source of truth for, and dropping those here would undo on reload exactly
    // what flush() preserved.
    setDoc({ ...(body.state ?? {}), ...localOnly(doc, unsupported) });
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
    unsupported,
    patch: patchDoc,
  };
}
