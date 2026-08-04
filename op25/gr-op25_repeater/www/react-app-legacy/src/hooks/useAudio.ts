import { useRef, useState, useEffect, useCallback } from 'react';
import { normalizeServerUrl } from './useControl';

const WS_AUDIO_SAMPLE_RATE = 8000;

interface AudioChannelState {
  queue: Int16Array[];
  nextPlayTime: number;
  muted: boolean;
}

export function useAudio(
  wsEndpoints: Record<string, string | null>,
  muteAtStartup: boolean,
  serverUrl = '',
) {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const channelsRef = useRef<Record<string, AudioChannelState>>({});
  const connectionsRef = useRef<Record<string, WebSocket | null>>({});
  // Reconnect trigger: increment to cause reconnect useEffect to re-run
  const [reconnectBump, setReconnectBump] = useState(0);
  // Reactive set of currently-playing (un-muted) channels
  const [playingChannels, setPlayingChannels] = useState<Set<string>>(new Set());

  /** Lazily create the AudioContext on first user gesture */
  const initAudioCtx = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new (window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext; }).webkitAudioContext)({
          sampleRate: WS_AUDIO_SAMPLE_RATE,
        });
    }
  }, []);

  /** Drain the queued samples into the Web Audio API scheduler */
  const drainQueue = useCallback((channel: string) => {
    const ctx = audioCtxRef.current;
    const state = channelsRef.current[channel];
    if (!ctx || !state || state.muted || state.queue.length === 0) return;

    // Resume AudioContext if it was suspended (Chrome autoplay policy)
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => { /* ignore */ });
      return;
    }

    if (state.nextPlayTime < ctx.currentTime) {
      state.nextPlayTime = ctx.currentTime;
    }
    while (state.queue.length > 0) {
      const samples = state.queue.shift()!;
      const buf = ctx.createBuffer(1, samples.length, WS_AUDIO_SAMPLE_RATE);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < samples.length; i++) ch[i] = samples[i] / 32768.0;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.start(state.nextPlayTime);
      state.nextPlayTime += buf.duration;
    }
  }, []);

  /** Toggle audio on/off for a channel */
  const toggleAudio = useCallback(
    (channel: string) => {
      initAudioCtx();
      if (!channelsRef.current[channel]) {
        channelsRef.current[channel] = { queue: [], nextPlayTime: 0, muted: true };
      }
      const state = channelsRef.current[channel];
      state.muted = !state.muted;
      if (state.muted) {
        state.queue = [];
        state.nextPlayTime = 0;
      }
      setPlayingChannels((prev) => {
        const next = new Set(prev);
        if (state.muted) next.delete(channel);
        else next.add(channel);
        return next;
      });
    },
    [initAudioCtx],
  );

  /** Connect (or reconnect) WebSocket audio streams */
  useEffect(() => {
    Object.entries(wsEndpoints).forEach(([channel, endpoint]) => {
      if (!endpoint) return;

      // Already connected or connecting
      const existing = connectionsRef.current[channel];
      if (existing && existing.readyState <= WebSocket.OPEN) return;

      // Initialize audio channel state if needed
      if (!channelsRef.current[channel]) {
        channelsRef.current[channel] = {
          queue: [],
          nextPlayTime: 0,
          muted: muteAtStartup,
        };
        if (!muteAtStartup) {
          setPlayingChannels((prev) => new Set([...prev, channel]));
        }
      }

      // Normalize WebSocket URL:
      // 1. If serverUrl is configured, replace only the hostname (keep the
      //    audio port from the endpoint — it's independently configured).
      // 2. Otherwise replace 0.0.0.0 / 127.0.0.1 with the page's hostname.
      let wsUrl = endpoint;
      try {
        const u = new URL(endpoint);
        if (serverUrl.trim()) {
          const base = new URL(normalizeServerUrl(serverUrl.trim()));
          u.hostname = base.hostname;
          // Do NOT copy base.port — audio uses its own dedicated port
        } else if (u.hostname === '0.0.0.0' || u.hostname === '127.0.0.1') {
          u.hostname = window.location.hostname;
        }
        wsUrl = u.toString();
      } catch {
        // keep original
      }

      const ws = new WebSocket(wsUrl);
      connectionsRef.current[channel] = ws;
      ws.binaryType = 'arraybuffer';

      ws.onmessage = (event: MessageEvent) => {
        const state = channelsRef.current[channel];
        if (!state) return;
        if (typeof event.data === 'string') {
          const msg = JSON.parse(event.data) as { cmd?: string; };
          if (msg.cmd === 'audio_drain' || msg.cmd === 'audio_drop') {
            state.queue = [];
            state.nextPlayTime = 0;
          }
        } else if (!state.muted && audioCtxRef.current) {
          state.queue.push(new Int16Array(event.data as ArrayBuffer));
          drainQueue(channel);
        }
      };

      ws.onclose = () => {
        connectionsRef.current[channel] = null;
        // Reconnect after 3 s by bumping the counter
        setTimeout(() => setReconnectBump((n) => n + 1), 3000);
      };

      ws.onerror = () => {
        console.warn(`[OP25 audio] WebSocket error for channel ${channel}`);
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsEndpoints, reconnectBump, muteAtStartup, serverUrl]);

  return { playingChannels, toggleAudio, initAudioCtx };
}
