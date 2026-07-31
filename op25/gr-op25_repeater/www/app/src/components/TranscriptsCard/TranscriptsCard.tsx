import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import DownloadIcon from '@mui/icons-material/Download';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import CardShell from '../CardShell/CardShell';
import { useOp25Service } from '../../services/op25Service';
import type { CallClip } from '../../types/op25';

/** Clips are short; keep the list light rather than virtualising it. */
const MAX_VISIBLE = 60;

function fmtClock(epoch: number): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleTimeString();
}

function fmtDuration(secs: number): string {
  return `${secs.toFixed(1)}s`;
}

/**
 * Split *text* around every keyword occurrence so the matched terms can be
 * rendered highlighted. Terms are escaped before going into the RegExp —
 * they come from the user's config, which may legitimately contain
 * characters like `10-33` that would otherwise change the pattern's meaning.
 */
function highlight(text: string, keywords: string[]): (string | { hit: string })[] {
  if (!text || keywords.length === 0) return [text];
  const escaped = keywords.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const parts = text.split(new RegExp(`(${escaped.join('|')})`, 'ig'));
  const lower = new Set(keywords.map((k) => k.toLowerCase()));
  return parts.map((p) => (lower.has(p.toLowerCase()) ? { hit: p } : p));
}

interface ClipRowProps {
  clip: CallClip;
  playing: boolean;
  onToggle: (clip: CallClip) => void;
}

function ClipRow({ clip, playing, onToggle }: ClipRowProps) {
  const alert = clip.keywords.length > 0;
  const label = clip.talkgroup || (clip.tgid ? `TG ${clip.tgid}` : 'Unknown talkgroup');
  const source = clip.source_tag || (clip.source ? String(clip.source) : '');

  return (
    <Box
      sx={{
        border: 1,
        borderColor: alert ? 'warning.main' : 'divider',
        borderRadius: 1,
        p: { xs: 1, sm: 1.25 },
        display: 'flex',
        gap: 1,
        alignItems: 'flex-start',
        // A tinted background rather than a solid warning colour, so the
        // transcript stays legible in both light and dark mode.
        bgcolor: alert ? 'action.hover' : 'transparent',
      }}
    >
      <Tooltip title={playing ? 'Stop' : 'Play this call'}>
        <IconButton
          size="small"
          onClick={() => onToggle(clip)}
          color={playing ? 'error' : 'primary'}
          aria-label={playing ? 'stop clip' : 'play clip'}
        >
          {playing ? <StopIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
        </IconButton>
      </Tooltip>

      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 0.75 }}>
          <Typography variant="body2" fontWeight="medium" sx={{ overflowWrap: 'anywhere' }}>
            {label}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {fmtClock(clip.started)} · {fmtDuration(clip.duration)}
            {source ? ` · ${source}` : ''}
          </Typography>
          {alert && (
            <Chip
              size="small"
              color="warning"
              icon={<NotificationsActiveIcon sx={{ fontSize: '0.9rem' }} />}
              label={clip.keywords.join(', ')}
              sx={{ height: 20, fontSize: '0.7rem' }}
            />
          )}
        </Box>

        {clip.transcript ? (
          <Typography variant="body2" sx={{ mt: 0.25, overflowWrap: 'anywhere' }}>
            {highlight(clip.transcript, clip.keywords).map((part, i) =>
              typeof part === 'string' ? (
                <span key={i}>{part}</span>
              ) : (
                <Box
                  key={i}
                  component="mark"
                  sx={{ bgcolor: 'warning.light', color: 'warning.contrastText', px: 0.25, borderRadius: 0.5 }}
                >
                  {part.hit}
                </Box>
              ),
            )}
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
            {clip.stt_error ? `speech-to-text failed: ${clip.stt_error}` : 'no transcript'}
          </Typography>
        )}
      </Box>

      <Tooltip title="Download WAV">
        <IconButton
          size="small"
          component="a"
          href={clip.audio_url}
          download
          aria-label="download clip"
        >
          <DownloadIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

export default function TranscriptsCard() {
  const { callClips } = useOp25Service();
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopPlayback = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlayingId(null);
  }, []);

  const togglePlay = useCallback((clip: CallClip) => {
    if (audioRef.current) {
      audioRef.current.pause();
      const wasPlaying = playingId === clip.id;
      audioRef.current = null;
      setPlayingId(null);
      if (wasPlaying) return;
    }
    // A finite WAV clip plays fine through a plain <audio> element — unlike
    // the unbounded /api/stream response, which needs the Web Audio path.
    const el = new Audio(clip.audio_url);
    el.onended = () => setPlayingId(null);
    el.onerror  = () => setPlayingId(null);
    audioRef.current = el;
    setPlayingId(clip.id);
    el.play().catch(() => setPlayingId(null));
  }, [playingId]);

  useEffect(() => stopPlayback, [stopPlayback]);

  const rows = useMemo(
    () => (alertsOnly ? callClips.filter((c) => c.keywords.length > 0) : callClips)
      .slice(0, MAX_VISIBLE),
    [callClips, alertsOnly],
  );

  const alertCount = useMemo(
    () => callClips.filter((c) => c.keywords.length > 0).length,
    [callClips],
  );

  return (
    <CardShell title="Call Audio & Transcripts">
      <Stack spacing={1}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {callClips.length} captured
            {alertCount > 0 ? ` · ${alertCount} keyword ${alertCount === 1 ? 'hit' : 'hits'}` : ''}
          </Typography>
          <FormControlLabel
            control={<Switch size="small" checked={alertsOnly} onChange={(e) => setAlertsOnly(e.target.checked)} />}
            label={<Typography variant="caption">Keyword hits only</Typography>}
            sx={{ mr: 0 }}
          />
        </Box>

        {rows.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {callClips.length === 0
              ? 'No calls captured yet. Clips appear here as transmissions end; '
                + 'transcripts need a Home Assistant speech-to-text engine — see README-home-assistant.md.'
              : 'No calls matched a configured keyword.'}
          </Typography>
        ) : (
          <Stack spacing={0.75} sx={{ maxHeight: { xs: 380, md: 440 }, overflowY: 'auto', pr: 0.5 }}>
            {rows.map((clip) => (
              <ClipRow
                key={clip.id}
                clip={clip}
                playing={playingId === clip.id}
                onToggle={togglePlay}
              />
            ))}
          </Stack>
        )}
      </Stack>
    </CardShell>
  );
}
