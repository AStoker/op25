/**
 * Formatting for talkgroup last-heard timestamps.
 *
 * The decoder publishes `last_seen` as a raw epoch in seconds (tgid_tags), and
 * the server merges in values from earlier runs before broadcasting. Formatting
 * happens here rather than in Python for two reasons: the browser knows the
 * viewer's clock and locale, and a number sorts correctly where the old
 * preformatted string did not — the previous column string-compared values like
 * `"  Now"` and `" 4.1s"`.
 *
 * The old column could in fact only ever show `"Now"` or nothing: it read
 * `frequency_data[freq].last_activity`, and a talkgroup is only listed against a
 * frequency while its call is up (TGID_EXPIRY_TIME, one second).
 */

/** Seconds in each unit, largest first. */
const UNITS: [limit: number, secs: number, suffix: string][] = [
  [60, 1, 's'],
  [3600, 60, 'm'],
  [86400, 3600, 'h'],
  [Infinity, 86400, 'd'],
];

/**
 * A short relative age: `12s`, `4m`, `3h`, `2d`.
 *
 * `epoch` of 0 (or missing) means the talkgroup has never been heard — the
 * decoder's initial value for an entry loaded from tgid_tags_file.
 */
export function formatLastSeen(epoch?: number | null, now: number = Date.now()): string {
  if (!epoch || !Number.isFinite(epoch) || epoch <= 0) return '—';
  const age = now / 1000 - epoch;
  // Clock skew, or a call still in progress. Both read better as "now" than as a
  // negative age; the server and browser clocks need not agree.
  if (age < 5) return 'now';
  for (const [limit, secs, suffix] of UNITS) {
    if (age < limit) return `${Math.floor(age / secs)}${suffix}`;
  }
  return '—';
}

/** Full timestamp for a tooltip, in the viewer's locale. */
export function formatLastSeenExact(epoch?: number | null): string {
  if (!epoch || !Number.isFinite(epoch) || epoch <= 0) return 'Never heard';
  return new Date(epoch * 1000).toLocaleString();
}

/** MHz to 4dp, or an em dash when the frequency is unknown. */
export function formatFreqMHz(hz?: number | null): string {
  if (!hz || !Number.isFinite(hz)) return '—';
  return (hz / 1e6).toFixed(4);
}
