import { useCallback, useEffect, useRef, useState } from 'react';
import { apiUrl } from '../utils/url';

/**
 * These constants MUST match websocket_server.py:
 *   _SAMPLE_RATE, _CHUNK_SAMPLES, _SAMPLE_WIDTH
 */
const SERVER_SAMPLE_RATE = 8_000;
const SERVER_CHUNK_MS = 20;  // chunk duration — 20 ms matches one P25 voice frame (160 samples)
const SERVER_CHUNK_SAMPLES = SERVER_SAMPLE_RATE * SERVER_CHUNK_MS / 1_000;  // 160 samples
const SERVER_CHUNK_BYTES = SERVER_CHUNK_SAMPLES * 2;  // 16-bit LE PCM = 2 bytes/sample
const WAV_HEADER_BYTES = 44;

/**
 * Output block length. Deliberately much longer than one 20 ms server chunk:
 * every scheduled block is a seam, and long blocks mean far fewer of them.
 */
const BLOCK_MS = 120;

/**
 * Buffer this much decoded audio before playback starts, and again after a
 * starve. This is the whole jitter budget: because audio arrives in real time,
 * the scheduling lead settles at roughly whatever was primed, so PRIME_MS is
 * both the added latency and the largest hiccup that can be absorbed silently.
 * It must comfortably exceed BLOCK_MS — when it did not, the resync branch
 * below fired about every two seconds, punching a PRIME_MS-sized hole in the
 * audio each time.
 */
const PRIME_MS = 400;

/** Drop audio once the queue exceeds this, rather than drifting ever further
 *  behind real time — a scanner wants to be live, not complete. */
const MAX_QUEUE_MS = 1_500;

/**
 * Playback gain. The P25 decoder's output is quiet — measured RMS ≈ 0.045 of
 * full scale on live traffic — so it needs a boost to be comfortable. But gain
 * alone clips: at 6x, peaks reached 4.4x full scale and 1.3% of speech samples
 * hard-clipped, which is what made voice sound distorted. Everything now runs
 * through SOFT_CLIP below, so peaks compress smoothly instead of squaring off.
 * Raise this if traffic is too quiet; the limiter keeps it from breaking up.
 */
const PLAYBACK_GAIN = 4.0;

function concat(a: Uint8Array, b: Uint8Array): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

export type AudioStreamStatus = 'idle' | 'loading' | 'playing' | 'stopped' | 'error';

export interface UseAudioStreamResult {
  start: () => Promise<void>;
  stop: () => void;
  audioStatus: AudioStreamStatus;
}

/**
 * tanh-shaped soft clipper. Bounds the signal to ±1 with a smooth knee, so
 * loud syllables lose a little headroom instead of hard-clipping into buzz.
 */
function softClipCurve(steps = 2_048): Float32Array<ArrayBuffer> {
  const curve = new Float32Array(steps);
  for (let i = 0; i < steps; i++) {
    const x = (i / (steps - 1)) * 2 - 1;   // -1 .. +1
    curve[i] = Math.tanh(x * 2) / Math.tanh(2);
  }
  return curve;
}

/**
 * Stream audio from *url* using the Web Audio API.
 *
 * The server sends a WAV-wrapped stream of 8 kHz / 16-bit / mono PCM. This hook
 * strips the 44-byte WAV header, converts the PCM to the AudioContext's own
 * sample rate, and schedules it as a small number of long blocks.
 *
 * Scheduling one 20 ms buffer at a time was the problem. Each buffer had to be
 * placed on the timeline individually, so any event-loop delay longer than a
 * chunk pushed its start past the previous buffer's end and left an audible
 * gap; and the "too far ahead" guard reset the timeline by 100 ms, which
 * overlapped buffers that were already scheduled. Long blocks give the
 * scheduler far more slack and far fewer chances to make either mistake.
 *
 * Resampling is done here rather than by handing the context an 8 kHz buffer
 * per chunk. At 48 kHz (and 44.1 kHz) a 20 ms chunk happens to be a whole
 * number of output samples, so the old approach was not itself introducing a
 * phase error — but doing it explicitly, with the read position carried across
 * blocks, keeps that true for any sample rate a device reports.
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
      // AudioContext must be created (or resumed) inside a user-gesture handler.
      // Since start() is always called from a button click this is always safe.
      const ctx = new AudioContext();
      if (ctx.state === 'suspended') {
        await ctx.resume();
      }
      ctxRef.current = ctx;

      const gainNode = ctx.createGain();
      gainNode.gain.value = PLAYBACK_GAIN;
      const limiter = ctx.createWaveShaper();
      limiter.curve = softClipCurve();
      limiter.oversample = '4x';   // reduces aliasing introduced by the curve
      gainNode.connect(limiter);
      limiter.connect(ctx.destination);

      const outRate = ctx.sampleRate;
      const ratio = SERVER_SAMPLE_RATE / outRate;      // input samples per output sample
      const blockOutSamples = Math.round((BLOCK_MS / 1_000) * outRate);
      const primeInSamples = Math.round((PRIME_MS / 1_000) * SERVER_SAMPLE_RATE);
      const maxInSamples = Math.round((MAX_QUEUE_MS / 1_000) * SERVER_SAMPLE_RATE);

      // `url` may be a server-generated root-absolute path such as
      // /api/stream?port=N, so normalise it against the document base.
      const response = await fetch(apiUrl(url));
      if (!response.ok || !response.body) {
        throw new Error(`Stream request failed: HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      readerRef.current = reader;

      setAudioStatus('playing');

      let pending = new Uint8Array(0) as Uint8Array<ArrayBuffer>;
      let headerDone = false;

      // Decoded 8 kHz mono samples awaiting resampling, plus the fractional
      // read position within it. `pos` is what makes resampling continuous.
      let queue: Float32Array = new Float32Array(0);
      let pos = 0;
      let scheduleUntil = 0;   // 0 = not started; set on first scheduled block
      let primed = false;

      const enqueue = (chunk: Uint8Array) => {
        const view = new DataView(chunk.buffer, chunk.byteOffset, chunk.byteLength);
        const n = chunk.byteLength >> 1;
        const grown = new Float32Array(queue.length + n);
        grown.set(queue, 0);
        for (let i = 0; i < n; i++) {
          grown[queue.length + i] = view.getInt16(i * 2, true) / 32_768.0;
        }
        queue = grown;
        if (queue.length > maxInSamples) {
          const drop = queue.length - maxInSamples;
          queue = queue.subarray(drop);
          pos = Math.max(0, pos - drop);
        }
      };

      while (activeRef.current) {
        const { done, value } = await reader.read();
        if (done || !activeRef.current) {
          console.warn(`Audio stream ended (done=${done}, active=${activeRef.current})`);
          break;
        }

        pending = concat(pending, value);

        // Strip the 44-byte WAV header that precedes the raw PCM data.
        if (!headerDone) {
          if (pending.length < WAV_HEADER_BYTES) continue;
          pending = pending.slice(WAV_HEADER_BYTES) as Uint8Array<ArrayBuffer>;
          headerDone = true;
        }

        while (pending.length >= SERVER_CHUNK_BYTES) {
          enqueue(pending.slice(0, SERVER_CHUNK_BYTES));
          pending = pending.slice(SERVER_CHUNK_BYTES) as Uint8Array<ArrayBuffer>;
        }

        if (!primed) {
          if (queue.length - pos < primeInSamples) continue;
          primed = true;
        }

        // Emit as many whole blocks as the queue can fill. Interpolation needs
        // one sample beyond the last position it reads, hence the +1.
        for (;;) {
          const needed = pos + (blockOutSamples - 1) * ratio + 1;
          if (queue.length < needed) break;

          const buffer = ctx.createBuffer(1, blockOutSamples, outRate);
          const out = buffer.getChannelData(0);
          for (let j = 0; j < blockOutSamples; j++) {
            const p = pos + j * ratio;
            const i = Math.floor(p);
            const frac = p - i;
            out[j] = queue[i] * (1 - frac) + queue[i + 1] * frac;
          }
          pos += blockOutSamples * ratio;

          // Discard input we have moved past, keeping the fractional remainder.
          const consumed = Math.floor(pos);
          if (consumed > 0) {
            queue = queue.subarray(consumed);
            pos -= consumed;
          }

          const now = ctx.currentTime;
          if (scheduleUntil < now) {
            // We ran dry: the graph has already played silence. Restart the
            // timeline after a fresh prime instead of scheduling in the past,
            // which would drop the block entirely.
            scheduleUntil = now + PRIME_MS / 1_000;
            primed = false;
          }
          const src = ctx.createBufferSource();
          src.buffer = buffer;
          src.connect(gainNode);
          src.start(scheduleUntil);
          scheduleUntil += buffer.duration;
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
