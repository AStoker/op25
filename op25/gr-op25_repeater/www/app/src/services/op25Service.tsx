import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useWebSocketService } from './websocketService';
import type {
  CallLogEntry,
  ChannelStatus,
  OP25Config,
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
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [decoderRunning, setDecoderRunning] = useState(false);

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
        }
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

  const value = useMemo<OP25ServiceContextType>(() => ({
    config,
    systems,
    channels,
    channelIds,
    callLog,
    decoderRunning,
    selectedChannelId,
    selectChannel,
    holdTalkGroup,
    releaseHold,
    skipCall,
    lockoutTalkGroup,
    whitelistTalkGroup,
  }), [config, systems, channels, channelIds, callLog, decoderRunning, selectedChannelId,
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
