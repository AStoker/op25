import { useEffect, useState } from 'react';
import type { SystemHealthPayload, SystemStatePayload } from '../types/websocket';
import { useWebSocketService } from '../services/websocketService';

/** Type-guard for the health payload emitted by
 *  websocket_server.py::_system_state_payload().  The decoder's own
 *  trunk_update / channel_update / plot messages also arrive as SYSTEM_STATE
 *  but carry a `json_type` field, so we use that to discriminate. */
function isSystemHealth(p: SystemStatePayload): p is SystemHealthPayload {
  return typeof (p as { json_type?: unknown }).json_type !== 'string'
      && typeof (p as { status?: unknown }).status === 'string';
}

/**
 * Latest server/decoder health snapshot.
 *
 * Arrives once on connect and then on the server's 1 Hz tick, so `status`
 * flips to 'error' on its own if the decoder stops answering the heartbeat.
 * Returns null until the first message is received.
 */
export function useSystemState(): SystemHealthPayload | null {
  const { subscribe } = useWebSocketService();
  const [state, setState] = useState<SystemHealthPayload | null>(null);

  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'SYSTEM_STATE' && isSystemHealth(msg.payload)) {
        setState(msg.payload);
      }
    });
  }, [subscribe]);

  return state;
}
