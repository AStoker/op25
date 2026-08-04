/**
 * useControl – WebSocket-based control transport with HTTP fallback.
 *
 * Primary path: connects to the OP25 WebSocket control server on HTTP port+1.
 * The server pushes JSON arrays of ServerResponse objects as text frames.
 * Commands are sent as JSON arrays of SendCommand objects.
 *
 * Fallback path: when the WebSocket is not connected, commands are queued and
 * flushed via HTTP POST every HTTP_POLL_MS milliseconds — identical to the old
 * polling behaviour, ensuring the app stays functional if the websockets Python
 * library is not installed on the server.
 */
import { useEffect, useRef, useCallback, useState } from 'react';
import type { ServerResponse } from '../types';

// ── Constants ─────────────────────────────────────────────────────────────────
const RECONNECT_MS = 3000;
const HTTP_POLL_MS = 1000;
const CMD_QLIMIT = 10;

// ── Types ─────────────────────────────────────────────────────────────────────
export interface ControlStats {
  requests: number;
  wsOk: number;
  httpOk: number;
  errors: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
/**
 * Ensure the URL has an http(s):// scheme.
 * "192.168.1.10:8080" → "http://192.168.1.10:8080"
 */
export function normalizeServerUrl(url: string): string {
  const t = url.trim();
  if (!t) return '';
  if (!/^https?:\/\//i.test(t)) return 'http://' + t;
  return t;
}

/** Compute WebSocket control URL from the configured server URL. */
export function deriveWsUrl(serverUrl: string): string {
  try {
    const normalized = normalizeServerUrl(serverUrl);
    if (normalized) {
      const u = new URL(normalized);
      const httpPort = u.port
        ? parseInt(u.port, 10)
        : u.protocol === 'https:' ? 443 : 80;
      return `ws://${u.hostname}:${httpPort + 1}/`;
    }
  } catch { /* fall through to same-origin */ }
  const port = parseInt(window.location.port, 10) || 80;
  return `ws://${window.location.hostname}:${port + 1}/`;
}

/** Compute HTTP POST endpoint from the configured server URL. */
function deriveHttpEndpoint(serverUrl: string): string {
  const normalized = normalizeServerUrl(serverUrl);
  return normalized ? normalized.replace(/\/+$/, '') + '/' : '/';
}

// ── Hook ──────────────────────────────────────────────────────────────────────
/**
 * @param serverUrl  Value from Settings.serverUrl — empty means same origin.
 * @param onMessage  Called whenever the server sends a batch of responses.
 */
export function useControl(
  serverUrl: string,
  onMessage: (responses: ServerResponse[]) => void,
) {
  const [wsConnected, setWsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [stats, setStats] = useState<ControlStats>({ requests: 0, wsOk: 0, httpOk: 0, errors: 0 });

  // Stable refs
  const serverUrlRef = useRef(serverUrl);
  serverUrlRef.current = serverUrl;

  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const wsRef = useRef<WebSocket | null>(null);
  const wsConnectedRef = useRef(false);

  // Commands waiting to be sent when WS is unavailable (HTTP fallback queue)
  const httpQueueRef = useRef<Array<{ command: string; arg1: number; arg2: number; }>>([]);
  const isFetchingRef = useRef(false);

  // ── Stats helpers ───────────────────────────────────────────────────────────
  const inc = useCallback((key: keyof ControlStats) => {
    setStats((prev) => ({ ...prev, [key]: prev[key] + 1 }));
  }, []);

  // ── HTTP fallback ───────────────────────────────────────────────────────────
  const flushHttp = useCallback(async () => {
    if (isFetchingRef.current || wsConnectedRef.current) return;
    const batch = httpQueueRef.current.splice(0);
    if (batch.length === 0) return;

    isFetchingRef.current = true;
    try {
      const res = await fetch(deriveHttpEndpoint(serverUrlRef.current), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(batch),
      });
      if (!res.ok) {
        setConnectionError(`HTTP ${res.status}`);
        inc('errors');
      } else {
        setConnectionError(null);
        inc('httpOk');
        const data = (await res.json()) as ServerResponse[];
        if (Array.isArray(data)) onMessageRef.current(data);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setConnectionError(`Connection error: ${msg}`);
      inc('errors');
    } finally {
      isFetchingRef.current = false;
    }
  }, [inc]);

  // ── WebSocket lifecycle ─────────────────────────────────────────────────────
  useEffect(() => {
    let destroyed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (destroyed) return;

      const url = deriveWsUrl(serverUrlRef.current);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (destroyed) { ws.close(); return; }
        wsConnectedRef.current = true;
        setWsConnected(true);
        setConnectionError(null);

        // Drain any commands that accumulated while disconnected
        const pending = httpQueueRef.current.splice(0);
        if (pending.length > 0) {
          ws.send(JSON.stringify(pending));
          inc('wsOk');
        }
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data as string) as ServerResponse[];
          if (Array.isArray(data)) onMessageRef.current(data);
        } catch { /* ignore malformed frame */ }
      };

      ws.onerror = () => { /* onclose always follows */ };

      ws.onclose = () => {
        wsRef.current = null;
        wsConnectedRef.current = false;
        setWsConnected(false);
        if (!destroyed) {
          reconnectTimer = setTimeout(connect, RECONNECT_MS);
        }
      };
    }

    connect();

    // HTTP fallback poll — only sends when WS is not connected
    const httpTimer = setInterval(flushHttp, HTTP_POLL_MS);

    return () => {
      destroyed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearInterval(httpTimer);
      const ws = wsRef.current;
      if (ws) {
        ws.onclose = null; // prevent reconnect after unmount
        ws.close();
        wsRef.current = null;
      }
      wsConnectedRef.current = false;
      setWsConnected(false);
    };
  }, [serverUrl, flushHttp, inc]); // re-run when serverUrl changes to reconnect to new endpoint

  // ── Public sendCommand ──────────────────────────────────────────────────────
  const sendCommand = useCallback(
    (command: string, arg1 = 0, arg2 = 0) => {
      inc('requests');
      const msg = { command, arg1, arg2 };
      const ws = wsRef.current;

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify([msg]));
        inc('wsOk');
      } else {
        // Queue for HTTP fallback
        if (httpQueueRef.current.length >= CMD_QLIMIT) {
          httpQueueRef.current.shift(); // drop oldest to make room
        }
        httpQueueRef.current.push(msg);
      }
    },
    [inc],
  );

  return { sendCommand, wsConnected, connectionError, stats };
}
