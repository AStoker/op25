import { Paper, Box, Typography, Tooltip, IconButton, Chip } from '@mui/material';
import HeadphonesIcon from '@mui/icons-material/Headphones';
import VolumeOffIcon from '@mui/icons-material/VolumeOff';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import LockIcon from '@mui/icons-material/Lock';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import type { SmartColor } from '../types';

interface Props {
  system: string;
  freq: number;
  tgid: number | null;
  tgtag: string;
  srcAddr: number;
  encrypted: number;
  emergency: number;
  channelName: string;
  streamUrl: string | null;
  channelId: number;
  wsEndpoints: Record<string, string | null>;
  playingChannels: Set<string>;
  onToggleAudio: (channel: string) => void;
  onInitAudio: () => void;
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
}

function getSmartColor(text: string, smartColors: SmartColor[], enabled: boolean): string | undefined {
  if (!enabled || !text) return undefined;
  const lower = text.toLowerCase();
  for (const sc of smartColors) {
    if (sc.keywords.some((kw) => lower.includes(kw.toLowerCase()))) return sc.color;
  }
  return undefined;
}

function fmtFreq(hz: number): string {
  if (!hz) return '—';
  return (hz / 1e6).toFixed(6) + ' MHz';
}

export default function MainDisplay({
  system, freq, tgid, tgtag, srcAddr, encrypted, emergency,
  channelName, streamUrl, channelId, wsEndpoints, playingChannels,
  onToggleAudio, onInitAudio, smartColors, settingsSmartColors,
}: Props) {
  const tgColor = getSmartColor(tgtag, smartColors, settingsSmartColors);
  const chKey = String(channelId);
  const hasWsAudio = chKey in wsEndpoints && wsEndpoints[chKey] != null;
  const isPlaying = playingChannels.has(chKey);

  return (
    <Paper
      elevation={2}
      sx={{
        background: 'linear-gradient(145deg, #1e1e2e 0%, #1a1a2a 100%)',
        border: '1px solid #2a2a3a',
        borderRadius: 2,
        p: 2,
        position: 'relative',
      }}
    >
      {/* Header row: System name + channel + indicators */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Typography
          variant="h6"
          sx={{
            flex: 1,
            color: 'primary.main',
            fontWeight: 700,
            letterSpacing: '0.05em',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {system || 'Waiting for data…'}
        </Typography>

        {/* Encryption indicator */}
        {!!encrypted && (
          <Tooltip title="Encrypted transmission" arrow>
            <LockIcon sx={{ color: '#ff9800', fontSize: 18 }} />
          </Tooltip>
        )}

        {/* Emergency indicator */}
        {!!emergency && (
          <Tooltip title="EMERGENCY" arrow>
            <WarningAmberIcon sx={{ color: '#f44336', fontSize: 18 }} />
          </Tooltip>
        )}

        {/* Stream audio (external URL) */}
        {streamUrl && (
          <Tooltip title={`Open audio stream: ${streamUrl}`} arrow>
            <IconButton
              size="small"
              component="a"
              href={streamUrl}
              target="_blank"
              rel="noreferrer"
              sx={{ color: 'text.secondary' }}
            >
              <VolumeUpIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}

        {/* WebSocket audio toggle */}
        {hasWsAudio && (
          <Tooltip
            title={isPlaying ? 'Playing WebSocket audio — click to stop' : 'Click to play WebSocket audio'}
            arrow
          >
            <IconButton
              size="small"
              onClick={() => { onInitAudio(); onToggleAudio(chKey); }}
              sx={{ color: isPlaying ? 'primary.main' : 'text.secondary' }}
            >
              {isPlaying ? <HeadphonesIcon fontSize="small" /> : <VolumeOffIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        )}
      </Box>

      {/* Main info grid */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          gap: '4px 16px',
          alignItems: 'center',
        }}
      >
        {/* Talkgroup name */}
        <Typography
          variant="h5"
          sx={{
            fontWeight: 700,
            color: tgColor ?? 'text.primary',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            transition: 'color 0.2s',
          }}
        >
          {tgtag || '—'}
        </Typography>

        {/* Talkgroup ID */}
        <Box sx={{ textAlign: 'right' }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1 }}>
            Talkgroup
          </Typography>
          <Typography
            variant="body1"
            sx={{ fontWeight: 700, color: 'primary.main', fontVariantNumeric: 'tabular-nums' }}
          >
            {tgid ?? '—'}
          </Typography>
        </Box>

        {/* Source */}
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {srcAddr ? `ID: ${srcAddr}` : '—'}
        </Typography>

        {/* Frequency */}
        <Box sx={{ textAlign: 'right' }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1 }}>
            Frequency
          </Typography>
          <Typography
            variant="body2"
            sx={{ fontWeight: 600, color: 'primary.main', fontVariantNumeric: 'tabular-nums' }}
          >
            {fmtFreq(freq)}
          </Typography>
        </Box>
      </Box>

      {/* Status chips row */}
      <Box sx={{ display: 'flex', gap: 1, mt: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
        <Chip
          label={`Ch: ${channelName}`}
          size="small"
          variant="outlined"
          sx={{ fontSize: '0.7rem', height: 20 }}
        />
        <Chip
          label={`Enc: ${encrypted ? 'Yes' : 'No'}`}
          size="small"
          color={encrypted ? 'warning' : 'default'}
          variant={encrypted ? 'filled' : 'outlined'}
          sx={{ fontSize: '0.7rem', height: 20 }}
        />
        <Chip
          label={`Emg: ${emergency ? 'YES' : 'No'}`}
          size="small"
          color={emergency ? 'error' : 'default'}
          variant={emergency ? 'filled' : 'outlined'}
          sx={{ fontSize: '0.7rem', height: 20 }}
        />
      </Box>
    </Paper>
  );
}
