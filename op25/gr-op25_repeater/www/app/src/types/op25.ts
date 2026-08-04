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
  /** All known talkgroups keyed by TGID string. `configured` is true for
   *  entries loaded from tgid_tags_file at startup.  `prio` is the trunk
   *  priority used for mid-call preemption (lower = higher priority,
   *  default 3 when the tags file omits a third column). */
  tgid_tags?: Record<string, { tag: string; configured: boolean; prio?: number }>;

  // --- P25-only site details -------------------------------------------
  /** Non-null when the control channel itself is encrypted (P_PARM_BCST). */
  encryption_algid?: number | null;
  /** 0 means the site is running failsoft (RFSS_STS_BCST 'A' bit clear). */
  network_active?: number;
  /** Location Registration Area. */
  lra?: number;

  // --- SmartNet-only site details ---------------------------------------
  /** SmartNet/SmartZone system id (`rx_sys_id`). */
  sysid_smartnet?: number | null;
  /** SmartZone site id; null on a single-site SmartNet system. */
  siteid?: number | null;

  // --- Connect+/DMR-only details ----------------------------------------
  /** Logical channel number → frequency map. */
  lcn_data?: Record<string, DmrLcnEntry>;
  /** LCN currently carrying the rest channel, 0 when unknown. */
  rest_lcn?: number;
}

/** One Connect+ logical channel and the state of its two time slots. */
export interface DmrLcnEntry {
  lcn: number;
  frequency: number;
  slots: DmrSlotEntry[];
}

export interface DmrSlotEntry {
  slot: number;
  tgid: number;
  srcaddr: number;
  /** Unix epoch seconds of the most recent grant, 0 when never granted. */
  grant_time: number;
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
  /** Path the raw symbol capture is being written to while `capture` is true. */
  capture_file?: string;
  /** Demodulator frequency error in Hz (AFC figure — NOT a bit error rate). */
  error?: number;
  conventional?: boolean;
  /** Time slot for two-slot DMR; absent/0 elsewhere. */
  slot?: number;
  /** Encryption algorithm / key ids for the current call, when known. */
  algid?: number;
  keyid?: number;
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
// Captured call audio (websocket_server.py + ha_bridge.py).
//
// One clip per transmission, sliced out of the decoder's UDP audio.  Arrives
// twice: `call_clip` as soon as the transmission ends, then `call_transcript`
// once Home Assistant's speech-to-text has run (if configured).  The same
// objects are served by GET /api/calls so a reloaded page is not empty.
// ---------------------------------------------------------------------------

export interface CallClip {
  id: string;
  /** Unix epoch seconds when the transmission started. */
  started: number;
  ended: number;
  /** Clip length in seconds. */
  duration: number;
  /** Speech-to-text result — empty until transcription completes or if off. */
  transcript: string;
  /** Configured keywords found in `transcript`. */
  keywords: string[];
  /** Path to the clip as a finite WAV file. */
  audio_url: string;
  /** Present when speech-to-text was attempted and failed. */
  stt_error?: string;
  /** Text the model returned that was rejected as a probable hallucination.
   *  Shown for tuning; never matched against keywords. */
  discarded_transcript?: string;

  /** Peak sample value as received, before normalisation (0–32767). */
  peak?: number;
  /** Speech RMS as received, before normalisation. */
  rms?: number;
  /** Gain applied to reach a consistent playback level. */
  gain_db?: number;
  /** Speech-likeness heuristic, 0–1. Only present when the gate is enabled. */
  voiced_ratio?: number;

  system?: string;
  channel?: string;
  tgid?: number;
  talkgroup?: string;
  source?: number;
  source_tag?: string;
  frequency?: number;
  encrypted?: boolean;
  emergency?: boolean;
}

export interface CallClipPayload extends CallClip {
  json_type: 'call_clip' | 'call_transcript';
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
  terminal?: TerminalConfig;
}

/** One smart-colour rule: any tag containing one of `keywords` (case-
 *  insensitive substring) is drawn in `color`. */
export interface SmartColorRule {
  keywords: string[];
  color: string;
}

/** The `terminal` block of the multi_rx config, echoed back by the decoder as
 *  `json_type: "terminal_config"`.  The curses terminal honours the tuning
 *  steps and default channel (terminal.py:504-514); so do we. */
export interface TerminalConfig {
  module?: string;
  terminal_type?: string;
  /** Fine-tune increments in Hz for the ±small / ±large controls. */
  tuning_step_small?: number;
  tuning_step_large?: number;
  /** Channel `name` to focus when the UI first sees the channel list. */
  default_channel?: string;
  /** Keyword → colour rules for tinting talkgroup tags. A list here replaces
   *  the built-in defaults rather than extending them. */
  smart_colors?: SmartColorRule[];
  http_plot_interval?: number;
  curses_plot_interval?: number;
  http_plot_directory?: string;
  terminal_timeout?: number;
  /** Explicit browser-audio UDP port override. */
  audio_ports?: number[];
  [k: string]: unknown;
}
