/**
 * Shapes for the editable-configuration API.
 *
 * Mirrors `apps/config_schema.py` and `apps/config_store.py`. The editor renders
 * itself from `ConfigSchema` rather than hardcoding fields, which is what lets a
 * protocol other than P25 appear without another form being written.
 */

/** A single editable field, as described by the server. */
export interface ConfigField {
  /** Path pattern, e.g. `devices[*].gains`. `[*]` stands for any list element. */
  path: string;
  label: string;
  type: 'string' | 'number' | 'boolean' | 'enum' | 'list';
  /**
   * Whether changing this takes effect without rebuilding the flowgraph.
   *
   * Almost nothing is. Trusting an optimistic value here is the dangerous
   * direction: the UI would report success while the decoder kept running the
   * old value, so the server classifies every save and returns `needs_restart`.
   */
  live: boolean;
  /** Trunking modules the field means anything for. */
  applies_to: string[];
  help?: string;
  unit?: string;
  placeholder?: string;
  readonly?: boolean;
  /** Hidden behind the "advanced" switch — rarely-touched or expert knobs. */
  advanced?: boolean;
  choices?: (string | number)[];
  /** Offered as a datalist but not enforced, unlike `choices`. */
  suggestions?: (string | number)[];
  min?: number;
  max?: number;
  step?: number;
  /** Decimal places worth keeping for a float.
   *
   *  `adj_tune` works in fractional ppm and produces values like
   *  `2.3749999999999996`. Those digits are below what the hardware can act on —
   *  at 859 MHz the smallest tuning step is ~0.116 ppm — but they make the value
   *  unreadable, and the config is something a human reads. */
  precision?: number;
}

export interface ConfigSection {
  key: string;
  label: string;
  kind: 'list' | 'object' | 'mixed';
  /** Dotted path of the list this section repeats over, when it has one. */
  list_path?: string;
  /** Field within each element that identifies it (`name`, `sysname`). */
  identity?: string;
  fields: ConfigField[];
}

export interface ConfigSchema {
  protocol: string | null;
  protocols: string[];
  sections: ConfigSection[];
  live_paths: string[];
}

/** One field's worth of change, as computed by `config_store.diff_fields`. */
export interface ConfigChange {
  path: string;
  op: 'add' | 'remove' | 'change';
  old?: unknown;
  new?: unknown;
}

/** A field where an override is masking a *different* preset value. */
export interface PresetDrift {
  path: string;
  preset: unknown;
  override: unknown;
}

export interface ConfigVersion {
  /** null when no history database is available — saving still worked. */
  id: number | null;
  ts: number;
  source: string;
  summary: string;
  base_id: string;
  overlay: Record<string, unknown>;
  diff: ConfigChange[];
}

export interface ConfigState {
  /** False when writes are disabled, or no overlay path is configured. */
  editable: boolean;
  /** `ingress` | `open` | `off` — who the server will accept a write from. */
  write_policy: string;
  /** preset + overlay: what the decoder should be running. Secrets masked. */
  effective: Record<string, unknown>;
  /** The preset alone, for "what would reset give me". */
  base: Record<string, unknown>;
  /** Only the user's overrides. */
  overlay: Record<string, unknown>;
  preset_drift: PresetDrift[];
  overlay_file: string | null;
  base_id: string;
  overrides: number;
  versions: number;
  history_enabled: boolean;
}

/** What a successful write reports back. */
export interface ConfigSaveResult {
  ok: true;
  version: ConfigVersion;
  live: ConfigChange[];
  restart_required: ConfigChange[];
  needs_restart: boolean;
  /** Paths actually dispatched to the running decoder. */
  applied: string[];
}
