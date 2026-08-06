// ─────────────────────────────────────────────────────────────────────────────
// WebSocket message protocol types
//
// Every message on the wire is:  { type: MessageType, payload: <PayloadType> }
//
// Downstream  (server → client):  SYSTEM_STATE | CALL_ACTIVITY | CALL_AUDIO
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
  CallClipPayload,
  CallLogPayload,
} from './op25';

// ---------------------------------------------------------------------------
// Health SYSTEM_STATE payload from websocket_server.py::_system_state_payload().
// Sent on connect and then on the server's 1 Hz tick, so `status` reports
// whether the decoder is actually feeding the bridge — not a fixed value.
// ---------------------------------------------------------------------------

export interface SystemHealthPayload {
  /** 'running' while decoder updates are arriving, 'error' once they stall,
   *  'stopped' before the first one. */
  status: 'running' | 'stopped' | 'error';
  /** Server uptime in seconds. */
  uptime: number;
  site_name: string;
  trunk_id: string;
  error_detail: string;
}

// SYSTEM_STATE payload union — the health payload OR decoder-emitted updates
// that fall through the json_type map (e.g. trunk_update, channel_update,
// plot, terminal_config, full_config).
export type SystemStatePayload =
  | SystemHealthPayload
  | TrunkUpdatePayload
  | ChannelUpdatePayload
  | (Record<string, unknown> & { json_type: string });

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

/** The only system-level action the decoder implements.  Muting is handled in
 *  the browser (the player stops pulling /api/stream), and start/stop/restart
 *  would mean process control the decoder does not expose — so neither is
 *  declared here.  See websocket_server.py::handle_system_control. */
export interface SystemControlPayload {
  action: 'quit';
}

// ---------------------------------------------------------------------------
// Discriminated union for every message that can arrive from the server
// ---------------------------------------------------------------------------

export type DownstreamMessage =
  | { type: 'SYSTEM_STATE'; payload: SystemStatePayload; }
  | { type: 'CALL_ACTIVITY'; payload: CallActivityPayload; }
  | { type: 'CALL_AUDIO'; payload: CallClipPayload; }
  | { type: 'ERROR'; payload: { detail: string; }; };

// ---------------------------------------------------------------------------
// Discriminated union for every message the client can send
// ---------------------------------------------------------------------------

export type UpstreamMessage =
  | { type: 'CALL_CONTROL'; payload: CallControlPayload; }
  | { type: 'SYSTEM_CONTROL'; payload: SystemControlPayload; };
