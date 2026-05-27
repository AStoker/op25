import { useEffect, useState } from 'react';
import type { SystemStatePayload } from '../types/websocket';
import { useWebSocketService } from '../services/websocketService';

/**
 * Subscribes to SYSTEM_STATE messages and returns the latest payload.
 * Returns null until the first message is received.
 */
export function useSystemState(): SystemStatePayload | null {
  const { subscribe } = useWebSocketService();
  const [state, setState] = useState<SystemStatePayload | null>(null);

  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'SYSTEM_STATE') {
        setState(msg.payload);
      }
    });
  }, [subscribe]);

  return state;
}
