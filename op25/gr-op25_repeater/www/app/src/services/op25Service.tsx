import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useWebSocketService } from './websocketService';
import type {
  CallClip,
  CallClipPayload,
  CallLogEntry,
  ChannelStatus,
  OP25Config,
  PlotMode,
  PlotPayload,
  TrunkSystem,
} from '../types/op25';

// ---------------------------------------------------------------------------
// Service shape
// ---------------------------------------------------------------------------

export interface OP25ServiceContextType {
  /** Static config loaded from /api/config (mirrors multi_rx JSON). */
  config: OP25Config | null;

  /** Trunked-system snapshots keyed by system index ("0", "1", ...). */
  systems: Record<string, TrunkSystem>;

  /** Channel snapshots keyed by channel/msgqid index ("0", "1", ...). */
  channels: Record<string, ChannelStatus>;

  /** Ordered list of channel indexes as published by the decoder. */
  channelIds: string[];

  /** Rolling list of recent calls (most-recent last). */
  callLog: CallLogEntry[];

  /** Captured call audio + transcripts, most-recent first. */
  callClips: CallClip[];

  /** Latest plot snapshot per `${chan}:${mode}`. */
  plots: Record<string, PlotPayload>;
  /** Modes the UI has requested for the selected channel. */
  activePlotModes: Set<PlotMode>;
  /** Toggle a plot mode on/off for the selected channel. */
  togglePlotMode: (mode: PlotMode) => void;

  /** True once the decoder has sent at least one trunk/channel update. */
  decoderRunning: boolean;

  /** Index of the channel the UI is focused on (audio + active call). */
  selectedChannelId: string | null;
  selectChannel: (id: string) => void;

  /** Hold the given tgid on the selected channel. 0 releases hold. */
  holdTalkGroup: (tgid: number) => void;
  /** Release any active hold on the selected channel. */
  releaseHold: () => void;
  /** Skip past the current call on the selected channel. */
  skipCall: () => void;
  /** Lockout the given tgid (or current call when omitted) on the selected channel. */
  lockoutTalkGroup: (tgid?: number) => void;
  /** Whitelist the given tgid on the selected channel. */
  whitelistTalkGroup: (tgid: number) => void;
}

const noop = () => { };

const OP25ServiceContext = createContext<OP25ServiceContextType>({
  config:             null,
  systems:            {},
  channels:           {},
  channelIds:         [],
  callLog:            [],
  callClips:          [],
  plots:              {},
  activePlotModes:    new Set(),
  togglePlotMode:     noop,
  decoderRunning:     false,
  selectedChannelId:  null,
  selectChannel:      noop,
  holdTalkGroup:      noop,
  releaseHold:        noop,
  skipCall:           noop,
  lockoutTalkGroup:   noop,
  whitelistTalkGroup: noop,
});

// eslint-disable-next-line react-refresh/only-export-components
export function useOp25Service(): OP25ServiceContextType {
  return useContext(OP25ServiceContext);
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CALL_LOG_MAX = 200;

/** How many captured audio clips to keep client-side. The server's own ring is
 *  the real bound; this just keeps the transcript list from growing forever. */
const CALL_CLIP_MAX = 100;

/** Minimum ms between successive plot setState calls for the same key.
 *  gr_gnuplot may emit several frames per second; this keeps React happy. */
const PLOT_THROTTLE_MS = 100;

const PLOT_TYPE_BY_MODE: Record<PlotMode, number> = {
  fft:           1,
  constellation: 2,
  symbol:        3,
  eye:           4,
  mixer:         5,
  fll:           6,
};

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function OP25ServiceProvider({ children }: { children: React.ReactNode }) {
  const { subscribe, send, status: wsStatus } = useWebSocketService();

  const [config, setConfig] = useState<OP25Config | null>(null);
  const [systems,  setSystems]  = useState<Record<string, TrunkSystem>>({});
  const [channels, setChannels] = useState<Record<string, ChannelStatus>>({});
  const [channelIds, setChannelIds] = useState<string[]>([]);
  const [callLog,  setCallLog]  = useState<CallLogEntry[]>([]);
  const [callClips, setCallClips] = useState<CallClip[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [decoderRunning, setDecoderRunning] = useState(false);
  const [plots, setPlots] = useState<Record<string, PlotPayload>>({});
  const [activePlotModes, setActivePlotModes] = useState<Set<PlotMode>>(new Set());

  // Per-plot last-flush timestamp for client-side throttling.
  const plotLastFlushRef = useRef<Record<string, number>>({});

  // When the WebSocket opens, request the full config from the decoder.
  useEffect(() => {
    if (wsStatus === 'open') {
      send({ type: 'CALL_CONTROL', payload: { command: 'get_full_config', arg1: 0, arg2: 0 } });
      send({ type: 'CALL_CONTROL', payload: { command: 'get_terminal_config', arg1: 0, arg2: 0 } });
    }
    if (wsStatus === 'closed' || wsStatus === 'error') {
      setDecoderRunning(false);
    }
  }, [wsStatus, send]);

  // Seed the clip list from the server's ring buffer. Unlike call_log — which
  // is a draining delta feed — captured clips survive on the server, so a
  // reloaded page can show the calls it missed while it was gone.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/calls?limit=100')
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { calls?: CallClip[] } | null) => {
        if (cancelled || !body?.calls) return;
        setCallClips((prev) => (prev.length > 0 ? prev : body.calls!));
      })
      .catch(() => { /* endpoint absent on an older server — no clips, no card */ });
    return () => { cancelled = true; };
  }, []);

  // Auto-pick the first channel as soon as we see one.
  useEffect(() => {
    if (selectedChannelId === null && channelIds.length > 0) {
      setSelectedChannelId(channelIds[0]);
    }
  }, [channelIds, selectedChannelId]);

  // Subscribe to every downstream WS message and route by json_type.
  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'SYSTEM_STATE') {
        const p = msg.payload as Record<string, unknown> & { json_type?: string };
        if (p.json_type === 'full_config') {
          // full_config is the complete multi_rx JSON (same shape as OP25Config).
          const { json_type: _jt, ...cfg } = p;
          setConfig(cfg as unknown as OP25Config);
        } else if (p.json_type === 'trunk_update') {
          // Numeric-string keys are system indexes; everything else is metadata.
          const next: Record<string, TrunkSystem> = {};
          for (const [k, v] of Object.entries(p)) {
            if (/^\d+$/.test(k) && v && typeof v === 'object') {
              next[k] = v as TrunkSystem;
            }
          }
          setSystems(next);
          setDecoderRunning(true);
        } else if (p.json_type === 'channel_update') {
          const ids = Array.isArray(p.channels) ? (p.channels as string[]) : [];
          const next: Record<string, ChannelStatus> = {};
          for (const id of ids) {
            const entry = p[id];
            if (entry && typeof entry === 'object') {
              next[id] = entry as ChannelStatus;
            }
          }
          setChannels(next);
          setChannelIds(ids);
          setDecoderRunning(true);
        } else if (p.json_type === 'plot') {
          const plot = p as unknown as PlotPayload;
          const key  = `${plot.chan}:${plot.mode}`;
          // The decoder owns plot on/off state, and it survives a page reload.
          // Adopt any mode it is actually sending so the toggle reflects
          // reality — otherwise a reload leaves the button dark while data
          // streams, and the next click would switch the decoder off while
          // switching the display on.
          setActivePlotModes((prev) =>
            prev.has(plot.mode) ? prev : new Set(prev).add(plot.mode));
          const now  = Date.now();
          const last = plotLastFlushRef.current[key] ?? 0;
          if (now - last >= PLOT_THROTTLE_MS) {
            plotLastFlushRef.current[key] = now;
            setPlots((prev) => ({ ...prev, [key]: plot }));
          }
        }
      } else if (msg.type === 'CALL_AUDIO') {
        // A clip arrives twice: once when the transmission ends, and again
        // with `transcript` filled in once speech-to-text has run. Match on
        // id so the second one updates the row rather than duplicating it.
        const { json_type: _jt, ...clip } = msg.payload as CallClipPayload;
        setCallClips((prev) => {
          const idx = prev.findIndex((c) => c.id === clip.id);
          if (idx >= 0) {
            const next = prev.slice();
            next[idx] = { ...next[idx], ...clip };
            return next;
          }
          return [clip, ...prev].slice(0, CALL_CLIP_MAX);
        });
      } else if (msg.type === 'CALL_ACTIVITY') {
        const p = msg.payload as Record<string, unknown> & { json_type?: string };
        if (p.json_type === 'call_log' && Array.isArray(p.log)) {
          const entries = p.log as CallLogEntry[];
          if (entries.length > 0) {
            setCallLog((prev) => {
              const merged = [...prev, ...entries];
              return merged.length > CALL_LOG_MAX
                ? merged.slice(merged.length - CALL_LOG_MAX)
                : merged;
            });
          }
        }
      }
    });
  }, [subscribe]);

  // ---- Actions --------------------------------------------------------

  const sendCommand = useCallback((command: string, arg1 = 0, arg2 = 0) => {
    send({ type: 'CALL_CONTROL', payload: { command, arg1, arg2 } });
  }, [send]);

  const selectChannel = useCallback((id: string) => {
    setSelectedChannelId(id);
  }, []);

  // The decoder addresses the target channel via msgqid in arg2.  When the
  // selected channel exists we resolve its msgqid, otherwise fall back to
  // the numeric channel id (which is the msgqid in multi_rx.py).
  const resolveMsgqid = useCallback((): number => {
    const id = selectedChannelId;
    if (id === null) return 0;
    const ch = channels[id];
    if (ch && typeof ch.msgqid === 'number') return ch.msgqid;
    const asNum = Number(id);
    return Number.isFinite(asNum) ? asNum : 0;
  }, [selectedChannelId, channels]);

  const holdTalkGroup = useCallback((tgid: number) => {
    sendCommand('hold', tgid, resolveMsgqid());
  }, [sendCommand, resolveMsgqid]);

  const releaseHold = useCallback(() => {
    // The python-curses UI uses tgid=0 to release the hold.
    sendCommand('hold', 0, resolveMsgqid());
  }, [sendCommand, resolveMsgqid]);

  const skipCall = useCallback(() => {
    sendCommand('skip', 0, resolveMsgqid());
  }, [sendCommand, resolveMsgqid]);

  const lockoutTalkGroup = useCallback((tgid: number = 0) => {
    sendCommand('lockout', tgid, resolveMsgqid());
  }, [sendCommand, resolveMsgqid]);

  const whitelistTalkGroup = useCallback((tgid: number) => {
    sendCommand('whitelist', tgid, resolveMsgqid());
  }, [sendCommand, resolveMsgqid]);

  const togglePlotMode = useCallback((mode: PlotMode) => {
    const msgqid = resolveMsgqid();
    // Toggle the decoder-side sink. The same command both enables and disables.
    sendCommand('toggle_plot', PLOT_TYPE_BY_MODE[mode], msgqid);
    setActivePlotModes((prev) => {
      const next = new Set(prev);
      if (next.has(mode)) {
        next.delete(mode);
        // Drop the stale snapshot so the card hides immediately on disable.
        setPlots((prevPlots) => {
          const key = `${msgqid}:${mode}`;
          if (!(key in prevPlots)) return prevPlots;
          const { [key]: _drop, ...rest } = prevPlots;
          return rest;
        });
      } else {
        next.add(mode);
      }
      return next;
    });
  }, [sendCommand, resolveMsgqid]);

  const value = useMemo<OP25ServiceContextType>(() => ({
    config,
    systems,
    channels,
    channelIds,
    callLog,
    callClips,
    plots,
    activePlotModes,
    togglePlotMode,
    decoderRunning,
    selectedChannelId,
    selectChannel,
    holdTalkGroup,
    releaseHold,
    skipCall,
    lockoutTalkGroup,
    whitelistTalkGroup,
  }), [config, systems, channels, channelIds, callLog, callClips, plots, activePlotModes,
       togglePlotMode, decoderRunning, selectedChannelId,
       selectChannel, holdTalkGroup, releaseHold, skipCall,
       lockoutTalkGroup, whitelistTalkGroup]);

  return (
    <OP25ServiceContext.Provider value={value}>
      {children}
    </OP25ServiceContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Convenience selectors
// ---------------------------------------------------------------------------

/** Currently focused channel, or null when nothing is selected/known. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSelectedChannel(): ChannelStatus | null {
  const { channels, selectedChannelId } = useOp25Service();
  if (selectedChannelId === null) return null;
  return channels[selectedChannelId] ?? null;
}

/** The system snapshot that matches the selected channel by sysname.
 *  Falls back to the first known system when no exact match exists. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSelectedSystem(): TrunkSystem | null {
  const { systems } = useOp25Service();
  const channel = useSelectedChannel();
  const values  = Object.values(systems);
  if (values.length === 0) return null;
  if (channel?.system) {
    const match = values.find((s) => s.system === channel.system);
    if (match) return match;
  }
  return values[0];
}
