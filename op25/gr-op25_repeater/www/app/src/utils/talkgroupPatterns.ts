/**
 * Search patterns for the talkgroup browser.
 *
 * One search box could only ever express one idea. A scanner user's actual
 * question is a *union*: "West Columbia 1, and everything starting RCHP, and
 * 4501". So a filter here is a list of patterns OR'd together, each with its own
 * matching rule — plain text for the name you know, a wildcard for a prefix
 * family, a regex when nothing else will do.
 *
 * Every pattern matches against the tag *or* the TGID as text, which is what
 * makes a bare number work as a pattern without a separate field for it.
 */

export type PatternKind = 'contains' | 'starts' | 'exact' | 'wildcard' | 'regex';

export interface TalkgroupPattern {
  kind: PatternKind;
  text: string;
}

export const PATTERN_KINDS: { kind: PatternKind; label: string; help: string }[] = [
  { kind: 'contains', label: 'Contains',    help: 'Anywhere in the tag or TGID' },
  { kind: 'starts',   label: 'Starts with', help: 'Tag or TGID begins with this' },
  { kind: 'exact',    label: 'Exact',       help: 'The whole tag, or the exact TGID' },
  { kind: 'wildcard', label: 'Wildcard',    help: '* matches any run, ? any one character' },
  { kind: 'regex',    label: 'Regex',       help: 'Full regular expression' },
];

export const KIND_LABEL: Record<PatternKind, string> = PATTERN_KINDS
  .reduce((acc, k) => ({ ...acc, [k.kind]: k.label }), {} as Record<PatternKind, string>);

/**
 * The kind a typed pattern most likely means.
 *
 * Only used to preselect the dropdown as you type — the choice stays visible and
 * editable. Guessing matters because the natural thing to type for a family of
 * talkgroups is `RCHP*`, and under the default "contains" rule that silently
 * matches nothing (there is no literal asterisk in any tag), which reads as the
 * filter being broken rather than as the wrong rule being applied.
 */
export function guessKind(text: string): PatternKind {
  const t = text.trim();
  if (!t) return 'contains';
  // Regex metacharacters that a wildcard cannot express. `*` and `?` are
  // deliberately absent: on their own they read as globbing, which is what a
  // scanner user means by them.
  if (/[\^$[\]()|\\]|\{\d/.test(t)) return 'regex';
  if (/[*?]/.test(t)) return 'wildcard';
  return 'contains';
}

/** Escape everything a RegExp treats specially. */
function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** `RCHP*` / `W Cola ?` as a regex, with only `*` and `?` left meaningful. */
function globToRe(text: string): string {
  return text.split('').map((ch) => {
    if (ch === '*') return '.*';
    if (ch === '?') return '.';
    return escapeRe(ch);
  }).join('');
}

export interface CompiledPattern {
  /** Null when the pattern could not be compiled — see `error`. */
  test: ((tag: string, tgid: number) => boolean) | null;
  error: string | null;
}

/**
 * Compile one pattern.
 *
 * A pattern that will not compile is reported, never silently dropped and never
 * silently matched: with several patterns OR'd together, a broken one that
 * matched everything would quietly widen the result, and one that matched
 * nothing would look like a pattern that simply found nothing.
 */
export function compilePattern({ kind, text }: TalkgroupPattern): CompiledPattern {
  const trimmed = text.trim();
  if (!trimmed) return { test: null, error: 'empty' };

  if (kind === 'contains' || kind === 'starts' || kind === 'exact') {
    const needle = trimmed.toLowerCase();
    const cmp = (value: string): boolean => {
      const v = value.toLowerCase();
      if (kind === 'contains') return v.includes(needle);
      if (kind === 'starts') return v.startsWith(needle);
      return v === needle;
    };
    return { test: (tag, tgid) => cmp(tag) || cmp(String(tgid)), error: null };
  }

  const source = kind === 'wildcard' ? globToRe(trimmed) : trimmed;
  try {
    // Case-insensitive: a scanner list is shouty and nobody wants to type it.
    const re = new RegExp(source, 'i');
    return { test: (tag, tgid) => re.test(tag) || re.test(String(tgid)), error: null };
  } catch (e) {
    return { test: null, error: (e as Error).message };
  }
}

export interface CompiledFilter {
  /** True when *no* usable pattern is present, i.e. everything shows. */
  passthrough: boolean;
  match: (tag: string, tgid: number) => boolean;
  /** Per-pattern predicate, index-aligned with the input. Null if broken. */
  tests: (((tag: string, tgid: number) => boolean) | null)[];
  errors: (string | null)[];
}

/** Compile a list of patterns into one OR'd predicate. */
export function compileFilter(patterns: TalkgroupPattern[]): CompiledFilter {
  const compiled = patterns.map(compilePattern);
  const usable = compiled.map((c) => c.test).filter(Boolean) as ((tag: string, tgid: number) => boolean)[];
  return {
    passthrough: usable.length === 0,
    match: usable.length === 0
      ? () => true
      : (tag, tgid) => usable.some((t) => t(tag, tgid)),
    tests: compiled.map((c) => c.test),
    errors: compiled.map((c) => c.error),
  };
}
