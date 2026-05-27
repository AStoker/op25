// ─────────────────────────────────────────────────────────────────────────────
// OP25 decoder payload shapes.
//
// These match the JSON emitted by the Python trunking modules
// (tk_p25.py / tk_smartnet.py / trunking.py) and forwarded to the browser
// over the WebSocket as `json_type` discriminated objects wrapped inside
// SYSTEM_STATE / CALL_ACTIVITY envelopes.  See sample-data/*.json.
// ─────────────────────────────────────────────────────────────────────────────

export interface FrequencyDataEntry {
  type: 'voice' | 'control' | 'alternate' | string;
  tgids: string[];
  last_activity: string;
  counter: number;
  tags: string[];
  srcaddrs: number[];
  srctags: string[];
}

export interface PatchEntry {
  sg: string;
  sgtag: string;
  ga: string;
  gatag: string;
}

export interface WuidEntry {
  rfss: number;
  site: number;
  suid: string;
  srcaddr: number;
  tag: string;
  aff_ga: number;
  aff_ga_tag: string | null;
  aff_aga: number;
  aff_aga_tag: string | null;
  time: number;
}

export interface AdjacentEntry {
  rfid: number;
  stid: number;
  uplink: number;
  table: number;
}

export interface BandPlanEntry {
  offset: number;
  step: number;
  frequency: number;
  tdma?: number;
}

export interface TrunkSystem {
  type: string;
  system: string;
  top_line: string;
  callsign: string;
  nac: number;
  syid: number;
  rfid: number;
  stid: number;
  sysid: number;
  rxchan: number;
  txchan: number;
  wacn: number;
  secondary: number[];
  frequencies: Record<string, string>;
  frequency_data: Record<string, FrequencyDataEntry>;
  patch_data: Record<string, Record<string, PatchEntry>>;
  wuid_data: Record<string, WuidEntry>;
  last_tsbk: number;
  adjacent_data: Record<string, AdjacentEntry>;
  band_plan: Record<string, BandPlanEntry>;
}

export interface TrunkUpdatePayload {
  json_type: 'trunk_update';
  nac: number;
  // Index keys ("0", "1", ...) each map to a system snapshot.
  [systemIdx: string]: TrunkSystem | number | string;
}

export interface ChannelStatus {
  freq: number;
  tdma: number | null;
  tgid: number | null;
  system: string;
  tag: string;
  srcaddr: number;
  svcopts: number;
  srctag: string;
  encrypted: number;
  emergency: number;
  hold_tgid: number;
  mode: number | null;
  stream: string;
  msgqid: number;
  name: string;
  ppm?: number;
  capture?: boolean;
  error?: number;
  conventional?: boolean;
}

export interface ChannelUpdatePayload {
  json_type: 'channel_update';
  channels: string[];
  // Index keys ("0", "1", ...) each map to a channel snapshot.
  [chanIdx: string]: ChannelStatus | string[] | string;
}

export interface CallLogEntry {
  time: number;
  sysid: number;
  rcvr: number;
  rcvrtag: string;
  freq: number;
  slot: number;
  prio: number;
  tgid: number;
  tgtag: string;
  rid: number;
  rtag: string;
}

export interface CallLogPayload {
  json_type: 'call_log';
  log: CallLogEntry[];
}

// ---------------------------------------------------------------------------
// Signal-plot snapshot emitted by gr_gnuplot.py.  One arrives per channel
// per plot mode while that plot is enabled.
// ---------------------------------------------------------------------------

export type PlotMode = 'fft' | 'constellation' | 'symbol' | 'eye' | 'mixer' | 'fll';

export interface PlotPayload {
  json_type: 'plot';
  chan: number;
  mode: PlotMode;
  /** Array of [x, y] tuples. Coordinate space depends on `mode`. */
  data: [number, number][];
  xrange?: [number, number];
  yrange?: [number, number];
  title?: string;
}

// ---------------------------------------------------------------------------
// Static config (from /api/config — mirrors richland-single.json)
// ---------------------------------------------------------------------------

export interface DeviceConfig {
  name: string;
  args: string;
  frequency: number;
  gains: string;
  gain_mode: boolean;
  offset: number;
  ppm: number;
  rate: number;
  usable_bw_pct: number;
  tunable: boolean;
}

export interface ChannelConfig {
  name: string;
  device: string;
  trunking_sysname: string;
  demod_type: string;
  filter_type?: string;
  excess_bw?: number;
  destination: string;
  meta_endpoint?: string;
  if_rate?: number;
  symbol_rate?: number;
  enable_analog?: string;
}

export interface TrunkingChanConfig {
  sysname: string;
  control_channel_list: string;
  tgid_tags_file?: string;
  nac?: string;
  whitelist?: string;
  blacklist?: string;
}

export interface OP25Config {
  devices: DeviceConfig[];
  channels: ChannelConfig[];
  trunking: {
    module: string;
    chans: TrunkingChanConfig[];
  };
  terminal?: Record<string, unknown>;
}
