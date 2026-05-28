import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * These constants MUST match websocket_server.py:
 *   _SAMPLE_RATE, _CHUNK_SAMPLES, _SAMPLE_WIDTH
 */
const SERVER_SAMPLE_RATE = 8_000;
const SERVER_CHUNK_MS = 20;  // chunk duration — 20 ms matches one P25 voice frame (160 samples)
const SERVER_CHUNK_SAMPLES = SERVER_SAMPLE_RATE * SERVER_CHUNK_MS / 1_000;  // 160 samples
const SERVER_CHUNK_BYTES = SERVER_CHUNK_SAMPLES * 2;  // 16-bit LE PCM = 2 bytes/sample
const WAV_HEADER_BYTES = 44;
const SCHEDULE_LOOKAHEAD = 0.06;

export type AudioStreamStatus = 'idle' | 'loading' | 'playing' | 'stopped' | 'error';

export interface UseAudioStreamResult {
  start: () => Promise<void>;
  stop: () => void;
  audioStatus: AudioStreamStatus;
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/**
 * Stream audio from *url* using the Web Audio API.
 *
 * The server sends a WAV-wrapped stream of 8 kHz / 16-bit / mono PCM.
 * This hook strips the 44-byte WAV header, decodes the raw PCM chunks in
 * the browser, and schedules them into an AudioContext so playback is
 * continuous and gap-free — critical for radio voice intelligibility.
 *
 * Using the Web Audio API instead of an <audio> element avoids all the
 * Range-request / seekability requirements that make browsers reject
 * infinite streaming WAV responses.
 */
export function useAudioStream(url: string): UseAudioStreamResult {
  const [audioStatus, setAudioStatus] = useState<AudioStreamStatus>('idle');

  const ctxRef = useRef<AudioContext | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const activeRef = useRef(false);

  const stop = useCallback(() => {
    activeRef.current = false;
    readerRef.current?.cancel().catch(() => { });
    readerRef.current = null;
    ctxRef.current?.close().catch(() => { });
    ctxRef.current = null;
    setAudioStatus('stopped');
  }, []);

  const start = useCallback(async () => {
    // Silently tear down any prior session before starting a new one.
    activeRef.current = false;
    readerRef.current?.cancel().catch(() => { });
    readerRef.current = null;
    ctxRef.current?.close().catch(() => { });
    ctxRef.current = null;

    activeRef.current = true;
    setAudioStatus('loading');

    try {
      // Use custom sampleRate to allow the browser to use native hardware clocks (44.1k / 48k)
      // AudioContext must be created (or resumed) inside a user-gesture handler.
      // Since start() is always called from a button click this is always safe.
      const ctx = new AudioContext();
      if (ctx.state === 'suspended') {
        await ctx.resume();
      }
      ctxRef.current = ctx;

      const gainNode = ctx.createGain();
      gainNode.gain.value = 6.0; // Keep a solid boost for quiet radio decodes
      gainNode.connect(ctx.destination);

      console.log(`AudioContext initialized successfully at native rate: ${ctx.sampleRate}Hz`);

      const response = await fetch(url);
      if (!response.ok || !response.body) {
        throw new Error(`Stream request failed: HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      readerRef.current = reader;

      setAudioStatus('playing');

      let pending = new Uint8Array(0) as Uint8Array<ArrayBuffer>;
      let headerDone = false;
      // Start scheduling a little ahead so the first chunk has time to decode.
      let scheduleUntil = ctx.currentTime + SCHEDULE_LOOKAHEAD;

      while (activeRef.current) {
        const { done, value } = await reader.read();

        // DIAGNOSTIC LOG: Check if the server explicitly disconnected us
        if (done || !activeRef.current) {
          console.warn(`Stream read terminated loop. Server closed connection (done=${done}), hook active=${activeRef.current}`);
          break;
        }

        pending = concat(pending, value);

        // Strip the 44-byte WAV header that precedes the raw PCM data.
        if (!headerDone) {
          if (pending.length < WAV_HEADER_BYTES) continue;
          pending = pending.slice(WAV_HEADER_BYTES);
          headerDone = true;
        }


        // Decode and schedule every complete PCM chunk in the buffer.
        while (pending.length >= SERVER_CHUNK_BYTES) {
          const chunk = pending.slice(0, SERVER_CHUNK_BYTES);
          pending = pending.slice(SERVER_CHUNK_BYTES);

          // We keep this buffer natively at 8000Hz; the context upsamples it automatically
          const audioBuffer = ctx.createBuffer(1, SERVER_CHUNK_SAMPLES, SERVER_SAMPLE_RATE);
          const channel = audioBuffer.getChannelData(0);
          const view = new DataView(chunk.buffer, chunk.byteOffset, chunk.byteLength);

          for (let i = 0; i < SERVER_CHUNK_SAMPLES; i++) {
            channel[i] = view.getInt16(i * 2, true) / 32_768.0;
          }

          const src = ctx.createBufferSource();
          src.buffer = audioBuffer;
          src.connect(gainNode);

          const now = ctx.currentTime;

          // Schedule gaplessly; keep a small margin ahead of now so the
          // first chunk in a burst has time to decode before its start.
          if (scheduleUntil > now + 0.15) {
            scheduleUntil = now + 0.05;
          }

          const startAt = Math.max(now + 0.02, scheduleUntil);
          src.start(startAt);
          scheduleUntil = startAt + audioBuffer.duration;
        }
      }
    } catch (error) {
      console.error('Audio stream runtime crash: ', error);
      if (activeRef.current) {
        setAudioStatus('error');
      }
    }
  }, [url]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      activeRef.current = false;
      ctxRef.current?.close().catch(() => { });
    };
  }, []);

  return { start, stop, audioStatus };
}