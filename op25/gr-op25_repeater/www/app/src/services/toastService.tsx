import { useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Snackbar from '@mui/material/Snackbar';
import Typography from '@mui/material/Typography';

/**
 * Transient error reporting for things with nowhere else to go.
 *
 * Most failures in this app already have a home: a config save reports itself in
 * the dialog that produced it, the WebSocket has a status chip, a card that
 * cannot load says so where its content would be. What had no home at all were
 * failures that happen *behind* an action which appeared to succeed — a pinned
 * talkgroup written to a receiver that refuses the key, a decoder `ERROR` frame.
 * Those simply undid themselves a moment later, which reads as a UI bug rather
 * than as a message from the server.
 *
 * The bus is module-level, not a context, for the same reason `useUiState` is:
 * the code that needs to report is not always inside React. `notify()` is a
 * plain function callable from anywhere.
 *
 * Two rules keep this from becoming noise, which is the failure mode of every
 * toast system:
 *
 *  - **Same `key`, same toast.** A rejected write repeats on every keystroke
 *    that triggers a save. Repeats bump a counter on the toast already on
 *    screen; they never stack.
 *  - **Dismissing a `key` silences it.** The user has read it, and the
 *    underlying condition (an old receiver, a decoder that does not support a
 *    command) will not have changed by the next attempt. Errors do not
 *    auto-dismiss, so dismissal is always deliberate.
 */

export type ToastSeverity = 'error' | 'warning' | 'info' | 'success';

export interface ToastRequest {
  severity: ToastSeverity;
  message: string;
  /** Second line, for the "what do I do about it" part. */
  detail?: string;
  /** Identity for deduplication. Defaults to the message. */
  key?: string;
}

interface Toast extends ToastRequest {
  id: number;
  key: string;
  /** How many times this has happened since it appeared. */
  count: number;
}

/** Informational toasts get out of the way; errors wait to be read. */
const AUTO_HIDE_MS = 6_000;

/** More than this on screen at once is a wall, not a notification. */
const MAX_VISIBLE = 3;

let toasts: Toast[] = [];
let nextId = 1;
const silenced = new Set<string>();
const listeners = new Set<() => void>();

function announce(): void {
  listeners.forEach((fn) => fn());
}

export function notify(request: ToastRequest): void {
  const key = request.key ?? request.message;
  if (silenced.has(key)) return;

  const existing = toasts.find((t) => t.key === key);
  if (existing) {
    // New object: the list is compared by identity to decide what to re-render.
    toasts = toasts.map((t) => (t.key === key ? { ...t, count: t.count + 1 } : t));
    announce();
    return;
  }

  toasts = [...toasts, { ...request, key, id: nextId++, count: 1 }].slice(-MAX_VISIBLE);
  announce();
}

/** Dismiss one toast. `silence` stops that key coming back this session. */
export function dismissToast(id: number, silence = true): void {
  const gone = toasts.find((t) => t.id === id);
  if (gone && silence) silenced.add(gone.key);
  toasts = toasts.filter((t) => t.id !== id);
  announce();
}

/** Test/debug helper: forget every toast and every silenced key. */
export function resetToasts(): void {
  toasts = [];
  silenced.clear();
  announce();
}

function useToasts(): Toast[] {
  const [, bump] = useState(0);
  useEffect(() => {
    const fn = () => bump((n) => n + 1);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);
  return toasts;
}

/**
 * Renders the current toasts. Mounted once, at the app root.
 *
 * Bottom-centre rather than MUI's default bottom-left: the left edge is where
 * the cards are, and on a phone a bottom-left toast lands on the tab bar.
 */
export default function ToastHost() {
  const current = useToasts();

  return (
    <Snackbar
      open={current.length > 0}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      sx={{ maxWidth: 'min(560px, calc(100vw - 32px))' }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, width: '100%' }}>
        {current.map((toast) => (
          <ToastRow key={toast.id} toast={toast} />
        ))}
      </Box>
    </Snackbar>
  );
}

function ToastRow({ toast }: { toast: Toast }) {
  const transient = toast.severity === 'success' || toast.severity === 'info';

  useEffect(() => {
    if (!transient) return undefined;
    // Keyed on count as well as id, so a repeat restarts the clock rather than
    // letting the toast vanish while the thing it describes is still happening.
    const timer = setTimeout(() => dismissToast(toast.id, false), AUTO_HIDE_MS);
    return () => clearTimeout(timer);
  }, [toast.id, toast.count, transient]);

  return (
    <Alert
      severity={toast.severity}
      variant="filled"
      onClose={() => dismissToast(toast.id)}
      sx={{ width: '100%', alignItems: 'flex-start' }}
    >
      <AlertTitle sx={{ mb: toast.detail ? 0.5 : 0 }}>
        {toast.message}
        {toast.count > 1 && ` (×${toast.count})`}
      </AlertTitle>
      {toast.detail && (
        <Typography variant="body2" sx={{ opacity: 0.95 }}>{toast.detail}</Typography>
      )}
    </Alert>
  );
}
