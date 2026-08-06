import type { SmartColorRule } from '../types/op25';

/**
 * Smart colours: tint a talkgroup tag by keyword so agency types are
 * distinguishable at a glance.
 *
 * Rules come from the `smart_colors` key of the config's terminal block and
 * arrive over the WebSocket as part of `terminal_config`.
 */

/** The built-in set, matching the defaults the removed legacy UI used
 *  ([www-static/main.js:27](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/www-static/main.js#L27)).
 *  A `smart_colors` list in the config replaces this wholesale — it does not
 *  extend it, so a config that omits EMS loses the EMS rule. */
export const DEFAULT_SMART_COLORS: SmartColorRule[] = [
  { keywords: ['fire', 'fd'], color: '#ff5c5c' },
  { keywords: ['pd', 'police', 'sheriff', 'so'], color: '#66aaff' },
  { keywords: ['ems', 'med', 'amr', 'ambulance'], color: '#ffb84d' },
];

/**
 * First rule whose keyword appears anywhere in *text* wins, case-insensitively.
 *
 * Substring matching is deliberately the same crude test the legacy UI uses, so
 * a config behaves identically in both — including the sharp edge that short
 * keywords over-match ("so" hits "Jackson Schools"). Rule order is the tie
 * breaker, so put the specific rules first.
 */
export function matchSmartColor(
  text: string | null | undefined,
  rules: SmartColorRule[],
): string | undefined {
  if (!text) return undefined;
  const lower = text.toLowerCase();
  for (const rule of rules) {
    if (!rule?.keywords?.length || !rule.color) continue;
    if (rule.keywords.some((kw) => kw && lower.includes(kw.toLowerCase()))) {
      return rule.color;
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Contrast
// ---------------------------------------------------------------------------

function parseHex(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/** WCAG relative luminance. */
function luminance([r, g, b]: [number, number, number]): number {
  const f = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(a: [number, number, number], b: [number, number, number]): number {
  const [l1, l2] = [luminance(a), luminance(b)];
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

function mix(
  c: [number, number, number],
  toward: [number, number, number],
  amount: number,
): [number, number, number] {
  return [0, 1, 2].map((i) =>
    Math.round(c[i] + (toward[i] - c[i]) * amount)) as [number, number, number];
}

function toHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/** Minimum contrast ratio to aim for. 3:1 is the WCAG floor for large/bold
 *  text; tags are small but this is a tint on top of an already-legible
 *  layout, and pushing to 4.5:1 washes the hues into mud. */
const MIN_CONTRAST = 3;

/**
 * Nudge *color* until it is legible on *background*.
 *
 * These palettes were chosen for the legacy dark-only UI, so on a light theme
 * a mid-blue or orange lands close to invisible. Mixing toward black (or white
 * on a dark theme) in small steps keeps the hue recognisable while making the
 * text readable. A colour that already has enough contrast is returned as-is.
 */
export function readableOn(color: string, background: string): string {
  const fg = parseHex(color);
  const bg = parseHex(background);
  if (!fg || !bg) return color;
  if (contrast(fg, bg) >= MIN_CONTRAST) return color;

  const target: [number, number, number] = luminance(bg) > 0.5 ? [0, 0, 0] : [255, 255, 255];
  for (let amount = 0.1; amount <= 0.9; amount += 0.1) {
    const candidate = mix(fg, target, amount);
    if (contrast(candidate, bg) >= MIN_CONTRAST) return toHex(candidate);
  }
  return toHex(target);
}
