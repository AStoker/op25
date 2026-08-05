import { useEffect, useState } from 'react';

/** One selectable audio stream, as reported by GET /api/audio/channels. */
export interface AudioSource {
  /** Config channel index, or null when the port cannot be attributed
   *  (an explicit `terminal.audio_ports` override). */
  channel: number | null;
  /** Channel name from the config. */
  name: string;
  /** 'A' or 'B' — the two slots of a channel are separate conversations on
   *  DMR, so they are separate streams rather than being mixed. */
  slot: string;
  port: number;
  /** Bytes the server has received on this port. 0 means nothing has ever
   *  arrived, which is normal for slot B on a P25 system. */
  bytes: number;
  url: string;
}

/** The aggregate mix of every port — what /api/stream serves with no params. */
export const AGGREGATE_AUDIO_URL = '/api/stream';

/** How often to refresh, so a slot that starts carrying audio shows up. */
const POLL_MS = 15_000;

/**
 * The audio streams this server can serve.
 *
 * Empty on a server without the endpoint, in which case callers should just
 * use {@link AGGREGATE_AUDIO_URL} — which is exactly the previous behaviour.
 */
export function useAudioSources(): AudioSource[] {
  const [sources, setSources] = useState<AudioSource[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch('/api/audio/channels')
        .then((r) => (r.ok ? r.json() : null))
        .then((body: { streams?: AudioSource[] } | null) => {
          if (!cancelled && body?.streams) setSources(body.streams);
        })
        .catch(() => { /* older server — aggregate stream only */ });
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  return sources;
}

/** Human label for a source: "voice channel" or "voice channel · slot B". */
export function audioSourceLabel(src: AudioSource): string {
  return src.slot === 'B' ? `${src.name} · slot B` : src.name;
}
