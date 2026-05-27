import { useEffect, useState } from 'react';
import type { InitialSystemStatePayload, SystemStatePayload } from '../types/websocket';
import { useWebSocketService } from '../services/websocketService';

/** Type-guard for the connect-time SYSTEM_STATE snapshot emitted by
 *  websocket_server.py::_initial_system_state().  The decoder's own
 *  trunk_update / channel_update messages also arrive as SYSTEM_STATE
 *  but carry a `json_type` field, so we use that to discriminate. */
function isInitialSystemState(p: SystemStatePayload): p is InitialSystemStatePayload {
  return typeof (p as { json_type?: unknown }).json_type !== 'string'
      && typeof (p as { status?: unknown }).status === 'string';
}

/**
 * Subscribes to the initial SYSTEM_STATE snapshot and returns the latest one.
 * Returns null until the first message is received.
 */
export function useSystemState(): InitialSystemStatePayload | null {
  const { subscribe } = useWebSocketService();
  const [state, setState] = useState<InitialSystemStatePayload | null>(null);

  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'SYSTEM_STATE' && isInitialSystemState(msg.payload)) {
        setState(msg.payload);
      }
    });
  }, [subscribe]);

  return state;
}
