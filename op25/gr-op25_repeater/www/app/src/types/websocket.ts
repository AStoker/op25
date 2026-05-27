// ─────────────────────────────────────────────────────────────────────────────
// WebSocket message protocol types
//
// Every message on the wire is:  { type: MessageType, payload: <PayloadType> }
//
// Downstream  (server → client):  SYSTEM_STATE | SDR_STATUS | CALL_ACTIVITY
// Upstream    (client → server):  CALL_CONTROL | SYSTEM_CONTROL
//
// Payloads are intentionally flat so consumers can use shallow equality checks.
// ─────────────────────────────────────────────────────────────────────────────

// ---------------------------------------------------------------------------
// Downstream payload types
// ---------------------------------------------------------------------------

export interface SystemStatePayload {
  /** Overall decoder state */
  status: 'running' | 'stopped' | 'error';
  /** Seconds since the decoder started */
  uptime: number;
  site_name: string;
  trunk_id: string;
  /** Human-readable error detail when status === 'error' */
  error_detail: string;
}

export interface SdrStatusPayload {
  source: string;
  frequency: number;
  /** Gain in dB */
  gain: number;
  /** Frequency-lock indicator */
  locked: boolean;
  /** Signal level in dBm */
  signal_level: number;
  /** Bit-error rate (0–1) */
  error_rate: number;
}

export interface CallActivityPayload {
  tgid: number;
  tg_label: string;
  src_id: number;
  freq: number;
  encrypted: boolean;
  emergency: boolean;
  /** Human-readable name of the active channel */
  channel_name?: string;
  /** Call duration in seconds (0 while active) */
  duration: number;
}

// ---------------------------------------------------------------------------
// Upstream payload types
// ---------------------------------------------------------------------------

export interface CallControlPayload {
  action: 'hold' | 'skip' | 'lockout' | 'whitelist';
  /** Target talk-group ID (omit to apply to the current call) */
  tgid?: number;
}

export interface SystemControlPayload {
  action: 'start' | 'stop' | 'restart' | 'mute' | 'unmute';
  /** Volume level 0–100 (only relevant for mute/unmute) */
  volume?: number;
}

// ---------------------------------------------------------------------------
// Discriminated union for every message that can arrive from the server
// ---------------------------------------------------------------------------

export type DownstreamMessage =
  | { type: 'SYSTEM_STATE'; payload: SystemStatePayload; }
  | { type: 'SDR_STATUS'; payload: SdrStatusPayload; }
  | { type: 'CALL_ACTIVITY'; payload: CallActivityPayload; }
  | { type: 'ERROR'; payload: { detail: string; }; };

// ---------------------------------------------------------------------------
// Discriminated union for every message the client can send
// ---------------------------------------------------------------------------

export type UpstreamMessage =
  | { type: 'CALL_CONTROL'; payload: CallControlPayload; }
  | { type: 'SYSTEM_CONTROL'; payload: SystemControlPayload; };
