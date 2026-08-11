import type { CallClip } from '../types/op25';

// ---------------------------------------------------------------------------
// Joining the call log to captured audio
//
// These two feeds come from different places and share no identifier:
//
//   call_log   the decoder's trunking layer, written when a voice grant is
//              *issued* — tgid, rid, freq, slot, and the grant timestamp.
//   call_clip  ha_bridge's UDP segmenter, emitted when the transmission
//              *ends* — start/end timestamps and whatever channel metadata
//              was live at the time.
//
// So the join is heuristic: same talkgroup, and the clip started at or just
// after the grant. That is exact on a single-channel receiver (the only case
// where ha_bridge's own metadata attribution is exact either — see CLAUDE.md)
// and best-effort when several channels are up at once.
// ---------------------------------------------------------------------------

/** Audio may be timestamped fractionally before the grant row is written. */
const PRE_ROLL_SECS = 2.0;

/** Ceiling on grant → audio latency. Just above the recorder's default
 *  `max_call_secs` of 120, past which a transmission is split anyway. */
const MATCH_WINDOW_SECS = 130;

export interface CallLogRowKey {
  /** Stable key for the rendered row. */
  key: string;
  time: number;
  tgid: number;
}

/**
 * Attach captured clips to call-log rows.
 *
 * Each clip is claimed by at most one row, and each row by at most one clip.
 * Rows are considered oldest-first so that when two grants on the same
 * talkgroup fall inside one window, the earlier grant takes the earlier clip
 * rather than both racing for it.
 */
export function matchClipsToCalls(
  rows: readonly CallLogRowKey[],
  clips: readonly CallClip[],
): Map<string, CallClip> {
  const out = new Map<string, CallClip>();
  if (rows.length === 0 || clips.length === 0) return out;

  // Clips arrive newest-first from the service; work oldest-first here.
  const byTime = clips
    .filter((c) => c.tgid)
    .slice()
    .sort((a, b) => a.started - b.started);
  if (byTime.length === 0) return out;

  const ordered = rows
    .filter((r) => r.tgid && r.time)
    .slice()
    .sort((a, b) => a.time - b.time);

  // For each row, when does the *next* grant on the same talkgroup happen?
  // A clip after that point belongs to the later grant, not this one.
  const nextSameTgid = new Map<string, number>();
  const lastSeen = new Map<number, CallLogRowKey>();
  for (let i = ordered.length - 1; i >= 0; i--) {
    const r = ordered[i];
    const later = lastSeen.get(r.tgid);
    if (later) nextSameTgid.set(r.key, later.time);
    lastSeen.set(r.tgid, r);
  }

  const claimed = new Set<string>();
  for (const row of ordered) {
    const from = row.time - PRE_ROLL_SECS;
    const to = Math.min(
      row.time + MATCH_WINDOW_SECS,
      nextSameTgid.get(row.key) ?? Number.POSITIVE_INFINITY,
    );
    for (const clip of byTime) {
      if (clip.started > to) break;          // sorted — nothing later can match
      if (clip.started < from) continue;
      if (clip.tgid !== row.tgid) continue;
      if (claimed.has(clip.id)) continue;
      claimed.add(clip.id);
      out.set(row.key, clip);
      break;
    }
  }

  return out;
}

export type TranscriptState =
  | { kind: 'none' }                                   // no clip captured
  | { kind: 'pending' }                                // queued for STT
  | { kind: 'text'; text: string; keywords: string[] }
  | { kind: 'error'; detail: string }
  | { kind: 'discarded'; text: string }
  | { kind: 'empty' };                                 // STT ran, heard nothing

/** Why a run of text is marked. The two are styled differently on purpose: a
 *  keyword hit is a configured alert and means something on its own, a search
 *  hit only means "this is what you asked for". */
export type HighlightKind = 'keyword' | 'search';

export interface HighlightHit {
  hit: string;
  kind: HighlightKind;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Split *text* around every keyword and search-term occurrence so the matched
 * runs can be rendered highlighted. Terms are escaped before going into the
 * RegExp — keywords come from the user's config and search terms from whatever
 * they are typing right now, both of which may legitimately contain characters
 * like `10-33` or a half-typed `(` that would otherwise change the pattern's
 * meaning or fail to compile.
 *
 * A run that is both a keyword and a search hit is reported as a keyword: the
 * alert is the fact worth keeping.
 */
export function highlight(
  text: string,
  keywords: readonly string[],
  search: readonly string[] = [],
): (string | HighlightHit)[] {
  const terms = [...keywords, ...search].filter(Boolean);
  if (!text || terms.length === 0) return [text];
  const parts = text.split(new RegExp(`(${terms.map(escapeRe).join('|')})`, 'ig'));
  const kw = new Set(keywords.map((k) => k.toLowerCase()));
  const se = new Set(search.map((k) => k.toLowerCase()));
  return parts.map((p) => {
    const l = p.toLowerCase();
    if (kw.has(l)) return { hit: p, kind: 'keyword' as const };
    if (se.has(l)) return { hit: p, kind: 'search' as const };
    return p;
  });
}

/** Reduce a clip to the one thing the Call History column should say. */
export function transcriptState(clip: CallClip | undefined): TranscriptState {
  if (!clip) return { kind: 'none' };
  if (clip.transcript) {
    return { kind: 'text', text: clip.transcript, keywords: clip.keywords ?? [] };
  }
  if (clip.transcript_pending) return { kind: 'pending' };
  if (clip.stt_error) return { kind: 'error', detail: clip.stt_error };
  if (clip.discarded_transcript) {
    return { kind: 'discarded', text: clip.discarded_transcript };
  }
  return { kind: 'empty' };
}
