// ─────────────────────────────────────────────────────────────────────────────
// WebSocket message protocol types
//
// Every message on the wire is:  { type: MessageType, payload: <PayloadType> }
//
// Downstream  (server → client):  SYSTEM_STATE | SDR_STATUS | CALL_ACTIVITY
// Upstream    (client → server):  CALL_CONTROL | SYSTEM_CONTROL
//
// The Python decoder wraps every emission with a `json_type` field; the
// FastAPI bridge then routes it to one of the WS message types defined in
// websocket_server.py::_JSON_TYPE_TO_MSG.  Both the routed type and the
// inner json_type are needed to fully discriminate a message.
// ─────────────────────────────────────────────────────────────────────────────

import type {
  TrunkUpdatePayload,
  ChannelUpdatePayload,
  CallLogPayload,
} from './op25';

// ---------------------------------------------------------------------------
// Initial SYSTEM_STATE snapshot sent from websocket_server.py on connect.
// ---------------------------------------------------------------------------

export interface InitialSystemStatePayload {
  status: 'running' | 'stopped' | 'error';
  uptime: number;
  site_name: string;
  trunk_id: string;
  error_detail: string;
}

// SYSTEM_STATE payload union — initial snapshot OR decoder-emitted updates
// that fall through the json_type map (e.g. trunk_update, channel_update,
// terminal_config, full_config, ws_instances).
export type SystemStatePayload =
  | InitialSystemStatePayload
  | TrunkUpdatePayload
  | ChannelUpdatePayload
  | (Record<string, unknown> & { json_type: string });

export interface SdrStatusPayload {
  json_type?: string;
  source?: string;
  frequency?: number;
  gain?: number;
  locked?: boolean;
  signal_level?: number;
  error_rate?: number;
  [k: string]: unknown;
}

// CALL_ACTIVITY payload — call_log / trunked_site_status / sys_info all
// arrive on this channel with a json_type discriminator.
export type CallActivityPayload =
  | CallLogPayload
  | (Record<string, unknown> & { json_type: string });

// ---------------------------------------------------------------------------
// Upstream payload types
//
// These must match the handlers registered in websocket_server.py
// (`handle_call_control` / `handle_system_control`).  CALL_CONTROL is
// forwarded to the GNURadio decoder as a raw `command/arg1/arg2` message,
// so the wire shape mirrors the decoder's `send_command()` arguments.
// ---------------------------------------------------------------------------

export interface CallControlPayload {
  command: string;        // e.g. 'hold' | 'skip' | 'lockout' | 'whitelist'
  arg1?: number;          // typically tgid
  arg2?: number;          // typically msgqid (channel index)
}

export interface SystemControlPayload {
  action: 'start' | 'stop' | 'restart' | 'mute' | 'unmute' | 'quit';
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
