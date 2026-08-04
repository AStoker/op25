// OP25 TypeScript type definitions

export interface SmartColor {
  keywords: string[];
  color: string;
}

export interface Preset {
  id: number;
  label: string;
  tgid: number;
}

// ── Channel table row (from channel_update) ──────────────────────────────────
export interface ChannelData {
  index: number;
  tag: string;
  tgid: number | null;
  tgtag: string | null;
  system: string;
  freq: number;
  mode: string;
  hold: boolean;
  capture: boolean;
  error: number | null;
  stream_url?: string | null;
}

// ── Per-frequency entry inside trunk_update ──────────────────────────────────
export interface FrequencyEntry {
  type: 'control' | 'voice' | 'alternate';
  last_activity: string;
  tgids: [number | null, number | null];
  tags: [string | null, string | null];
  srcaddrs: [number | null, number | null];
  srctags: [string | null, string | null];
  mode: string;
  counter: number;
}

export interface BandPlanEntry {
  frequency?: number;
  offset?: number;
  step?: number;
  tdma?: number;
}

export interface AdjacentEntry {
  rfid: number;
  stid: number;
  uplink: number;
}

// P25 patch entry
export interface PatchEntry {
  sg?: number;
  sgtag?: string;
  ga: number;
  gatag?: string;
  // SmartNet fields
  tgid_dec?: number;
  tgid_hex?: string;
  sub_tgid_dec?: number;
  sub_tgid_hex?: string;
  mode?: string;
}

export interface WuidEntry {
  suid: string;
  srcaddr: number;
  aff_ga: number;
  aff_ga_tag?: string;
  aff_aga?: number;
  aff_aga_tag?: string;
  tag?: string;
  rfss?: number;
  site?: number;
  time: number;
}

// ── NAC-level data inside trunk_update ───────────────────────────────────────
export interface NacData {
  system: string;
  type: 'p25' | 'smartnet';
  callsign?: string;
  sysid?: number;
  wacn?: number;
  nac?: number;
  rfid?: number;
  stid?: number;
  top_line?: string;
  last_tsbk?: number;
  frequency_data: Record<string, FrequencyEntry>;
  band_plan?: Record<string, BandPlanEntry>;
  wuid_data?: Record<string, WuidEntry>;
  adjacent_data?: Record<string, AdjacentEntry>;
  patch_data?: Record<string, Record<string, PatchEntry>>;
}

// ── Server response types (dispatched by json_type) ──────────────────────────
export interface TerminalConfigResponse {
  json_type: 'terminal_config';
  smart_colors?: SmartColor[];
  terminal_interface?: string;
  tuning_step_large?: number;
  tuning_step_small?: number;
  default_channel?: number;
}

export interface ChannelUpdateResponse {
  json_type: 'channel_update';
  channels: ChannelData[];
}

export interface TrunkUpdateResponse {
  json_type: 'trunk_update';
  nac?: number;
  srcaddr?: number;
  grpaddr?: number;
  encrypted?: number;
  emergency?: number;
  [key: string]: NacData | number | string | undefined;
}

export interface ChangeFreqResponse {
  json_type: 'change_freq';
  freq: number;
  system: string;
  tgid: number;
  tag: string;
  stream_url: string | null;
  nac?: number;
}

export interface RxUpdateResponse {
  json_type: 'rx_update';
  files: string[];
  error?: number;
  fine_tune?: number;
}

export interface WsInstancesResponse {
  json_type: 'ws_instances';
  [channel: string]: string | null | 'ws_instances';
}

export interface CallLogEntry {
  time: number;
  sysid: number;
  tgid: number;
  tgtag: string;
  rid: number;
  rtag: string;
  rcvr: number;
  prio: number;
  rcvrtag: string;
  freq: number;
  slot: number | null;
}

export interface CallLogResponse {
  json_type: 'call_log';
  log: CallLogEntry[];
}

export interface FullConfigResponse {
  json_type: 'full_config';
  trunking?: {
    chans: Array<{
      sysname: string;
      presets?: Preset[];
      site_alias?: Record<string, Record<string, Record<string, { alias: string; }>>>;
    }>;
  };
  [key: string]: unknown;
}

export type PlotMode = 'eye' | 'constellation' | 'symbol' | 'fft' | 'mixer' | 'fll';

export interface PlotResponse {
  json_type: 'plot';
  chan: number;
  mode: PlotMode;
  data: [number, number][];
  xrange: [number, number];
  yrange: [number, number];
  title: string;
}

export type ServerResponse =
  | TerminalConfigResponse
  | ChannelUpdateResponse
  | TrunkUpdateResponse
  | ChangeFreqResponse
  | RxUpdateResponse
  | WsInstancesResponse
  | CallLogResponse
  | FullConfigResponse
  | PlotResponse;

// ── App-level derived types ───────────────────────────────────────────────────
export interface CallHistoryEntry {
  timestamp: string;
  epochMs: number;
  sysHex: string;
  freq: string;
  tgid: string;
  tgName: string;
  source: string;
}

export interface SiteAliases {
  [sysname: string]: {
    [rfss: string]: {
      [site: string]: { alias: string; };
    };
  };
}

export interface TgCacheEntry {
  tag: string;
  hits: number;
}

export interface Settings {
  smartColors: boolean;
  showBandPlan: boolean;
  showAdjacentSites: boolean;
  showChannelsTable: boolean;
  showCallHistory: boolean;
  trackSubscribers: boolean;
  subscriberMode: 'all' | 'selected';
  callHistorySource: 'frequency' | 'voice' | 'display';
  muteAudioAtStartup: boolean;
  accentColor: string;
  callHistoryMaxRows: number;
  radioIdInFreqTable: boolean;
  /** Base URL of the OP25 server, e.g. "http://192.168.1.10:8080". Empty = same origin. */
  serverUrl: string;
}

export interface SendCommand {
  command: string;
  arg1: number;
  arg2: number;
}
