import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import type { DownstreamMessage, UpstreamMessage } from '../types/websocket';
import { wsUrl } from '../utils/url';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Derive the WebSocket URL from the document base so the app works regardless
 *  of host, port *and* path prefix (Home Assistant ingress), falling back to
 *  localhost:8080 for local dev. */
function defaultWsUrl(): string {
  if (typeof window === 'undefined') return 'ws://127.0.0.1:8080/ws';
  return wsUrl('ws');
}

const RECONNECT_DELAY_MS = 3_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MessageHandler = (message: DownstreamMessage) => void;

export type WebSocketStatus = 'connecting' | 'open' | 'closed' | 'error';

export interface WebSocketServiceContextType {
  status: WebSocketStatus;
  /** Send an upstream command to the server. No-op when not connected. */
  send: (message: UpstreamMessage) => void;
  /** Subscribe to all downstream messages. Returns an unsubscribe function. */
  subscribe: (handler: MessageHandler) => () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const WebSocketServiceContext = createContext<WebSocketServiceContextType>({
  status: 'closed',
  send: () => {},
  subscribe: () => () => {},
});

// eslint-disable-next-line react-refresh/only-export-components
export function useWebSocketService(): WebSocketServiceContextType {
  return useContext(WebSocketServiceContext);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface WebSocketServiceProviderProps {
  children: React.ReactNode;
  /** Override the WebSocket URL (useful for testing). */
  url?: string;
}

export function WebSocketServiceProvider({
  children,
  url,
}: WebSocketServiceProviderProps) {
  const wsUrl = url ?? defaultWsUrl();

  const [status, setStatus] = useState<WebSocketStatus>('connecting');
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef<Set<MessageHandler>>(new Set());
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track whether the provider is still mounted to avoid state updates after unmount.
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    setStatus('connecting');

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus('open');
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      let msg: DownstreamMessage;
      try {
        msg = JSON.parse(event.data) as DownstreamMessage;
      } catch {
        return;
      }
      handlersRef.current.forEach((h) => h(msg));
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      setStatus('error');
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus('closed');
      // Schedule reconnect
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };
  }, [wsUrl]);

  // Open connection on mount, clean up on unmount.
  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current !== null) {
        clearTimeout(reconnectTimer.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((message: UpstreamMessage) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    }
  }, []);

  const subscribe = useCallback((handler: MessageHandler) => {
    handlersRef.current.add(handler);
    return () => {
      handlersRef.current.delete(handler);
    };
  }, []);

  return (
    <WebSocketServiceContext.Provider value={{ status, send, subscribe }}>
      {children}
    </WebSocketServiceContext.Provider>
  );
}
