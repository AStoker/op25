/**
 * Free-text search over captured calls.
 *
 * A captured call is findable by two different things, and which one the user
 * remembers is not predictable: what was *said* (the transcript, when speech-to-
 * text ran at all) and *who* said it (the talkgroup). So one box searches both,
 * and a call with no transcript is still reachable by its talkgroup name.
 *
 * The query is split on whitespace and **every** term must match, though not
 * necessarily in the same field. That is what makes `cola fire` useful: it means
 * "a call on the Columbia talkgroup where someone said fire", which neither an
 * OR nor a single-field search can express. Each term is a case-insensitive
 * substring, not a pattern — unlike the talkgroup browser's filter, which
 * guesses between contains/wildcard/regex. Transcript text legitimately contains
 * `10-33`, `(inaudible)` and `*`, and guessing a rule from those would turn a
 * plain phrase search into a pattern that matches nothing.
 *
 * A term matched against a whole field would fail on the rendered `TG 4501`
 * label, so the TGID is searched as its own bare text.
 */

export interface ClipSearchFields {
  talkgroup?: string;
  tgid?: number;
  transcript?: string;
  /** Searched because it is *displayed*: a row whose visible text does not
   *  match what you typed reads as the search being broken. */
  discarded_transcript?: string;
}

/** Split a raw query into the terms that must all match. */
export function searchTerms(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/**
 * The fields one term may match, each lowercased and tested separately.
 *
 * Separately rather than joined: concatenating them would let a term straddle
 * the boundary between a talkgroup name and a transcript and match text that
 * exists nowhere.
 */
function fieldsOf(clip: ClipSearchFields): string[] {
  const out: string[] = [];
  if (clip.talkgroup) out.push(clip.talkgroup.toLowerCase());
  if (clip.tgid) out.push(String(clip.tgid));
  if (clip.transcript) out.push(clip.transcript.toLowerCase());
  if (clip.discarded_transcript) out.push(clip.discarded_transcript.toLowerCase());
  return out;
}

/** True when every term appears somewhere in *clip*. No terms means everything. */
export function matchesClip(clip: ClipSearchFields, terms: readonly string[]): boolean {
  if (terms.length === 0) return true;
  const fields = fieldsOf(clip);
  if (fields.length === 0) return false;
  return terms.every((t) => fields.some((f) => f.includes(t)));
}
