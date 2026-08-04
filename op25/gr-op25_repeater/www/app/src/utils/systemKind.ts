import type { TrunkSystem } from '../types/op25';

/**
 * Which trunking module produced a system snapshot.
 *
 * The payload shapes differ substantially: `tk_p25` publishes NAC/WACN/RFSS and
 * a band plan, `tk_smartnet` a system id and site id, `tk_trbo` an LCN table.
 * Cards that assume P25 fields do not merely look empty on the others — reading
 * `system.wacn.toString(16)` on a SmartNet snapshot throws — so every card that
 * needs P25 data must check first.
 */
export type SystemKind = 'p25' | 'smartnet' | 'trbo' | 'unknown';

export function systemKind(system: TrunkSystem | null | undefined): SystemKind {
  switch (system?.type) {
    case 'p25':      return 'p25';
    case 'smartnet': return 'smartnet';
    case 'trbo':     return 'trbo';
    default:         return 'unknown';
  }
}

/** Human name for a system kind, for "not available for …" messages. */
export const SYSTEM_KIND_LABEL: Record<SystemKind, string> = {
  p25:      'P25',
  smartnet: 'SmartNet/SmartZone',
  trbo:     'Connect+ (DMR)',
  unknown:  'this system',
};

/** True when *system* is one of *kinds*. */
export function isKind(system: TrunkSystem | null | undefined, ...kinds: SystemKind[]): boolean {
  return kinds.includes(systemKind(system));
}

/** Hex with an 0x prefix, or an em dash when the field is absent.
 *  Every trunking module omits fields that do not apply to it, so a formatter
 *  that assumes a number is how a card crashes on the wrong system type. */
export function hexOrDash(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `0x${value.toString(16).toUpperCase().padStart(digits, '0')}`;
}

/** Decimal, or an em dash when absent. */
export function numOrDash(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return String(value);
}

/** MHz with 4 decimals, or an em dash when absent. */
export function freqOrDash(hz: number | null | undefined): string {
  if (!hz || !Number.isFinite(hz)) return '—';
  return `${(hz / 1e6).toFixed(4)} MHz`;
}
