import { useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import LockIcon from '@mui/icons-material/Lock';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import CardShell from '../CardShell/CardShell';
import { useWebSocketService } from '../../services/websocketService';
import { useAudioStream } from '../../hooks/useAudioStream';
import { useSystemState } from '../../hooks/useSystemState';
import type { CallActivityPayload } from '../../types/websocket';

const AUDIO_STREAM_URL = '/api/stream';

interface InfoRowProps {
  label: string;
  value: string;
}

function InfoRow({ label, value }: InfoRowProps) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight="medium">
        {value}
      </Typography>
    </Box>
  );
}

export default function PlayerCard() {
  const { status, send, subscribe } = useWebSocketService();
  const { start, stop, audioStatus } = useAudioStream(AUDIO_STREAM_URL);
  const [activeCall, setActiveCall] = useState<CallActivityPayload | null>(null);
  const systemState = useSystemState();

  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'CALL_ACTIVITY') {
        setActiveCall(msg.payload);
      }
    });
  }, [subscribe]);

  function handlePlay() {
    start().catch(() => {});
    send({ type: 'SYSTEM_CONTROL', payload: { action: 'unmute' } });
  }

  function handleStop() {
    stop();
    send({ type: 'SYSTEM_CONTROL', payload: { action: 'mute' } });
  }

  const connected = status === 'open';
  const playing   = audioStatus === 'playing' || audioStatus === 'loading';

  const channelName = activeCall?.channel_name ?? '—';
  const tgValue     = activeCall ? `${activeCall.tg_label} (${activeCall.tgid})` : '—';
  const freqValue   = activeCall ? `${(activeCall.freq / 1e6).toFixed(4)} MHz` : '—';
  const sourceValue = activeCall ? String(activeCall.src_id) : '—';

  type ChipDef = { key: string; label: string; tooltip: string; color: 'default' | 'success' | 'error'; icon: React.ReactElement };
  const chips: ChipDef[] = [
    {
      key:     'enc',
      label:   activeCall?.encrypted ? 'Encrypted' : 'Open',
      tooltip: activeCall?.encrypted
        ? 'Call is encrypted — audio may not decode'
        : 'Call is unencrypted',
      color: activeCall?.encrypted ? 'error' : 'success',
      icon:  <LockIcon sx={{ fontSize: '0.9rem' }} />,
    },
    ...(activeCall?.emergency ? [{
      key:     'emrg',
      label:   'Emergency',
      tooltip: 'Emergency call in progress',
      color:   'error' as const,
      icon:    <WarningAmberIcon sx={{ fontSize: '0.9rem' }} />,
    }] : []),
  ];

  const sysStatusColor: Record<string, 'success' | 'error' | 'default'> = {
    running: 'success',
    error:   'error',
    stopped: 'default',
  };

  return (
    <CardShell title="Player">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {/* System info */}
        {systemState && (
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Box>
              <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
                {systemState.trunk_id || 'System'}
              </Typography>
              <Typography variant="body2" fontWeight="medium">
                {systemState.site_name || '—'}
              </Typography>
            </Box>
            <Chip
              label={systemState.status}
              color={sysStatusColor[systemState.status] ?? 'default'}
              size="small"
              sx={{ textTransform: 'capitalize' }}
            />
          </Box>
        )}

        {/* Call info */}
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
          <InfoRow label="Channel"    value={channelName} />
          <InfoRow label="Frequency"  value={freqValue} />
          <InfoRow label="Talk Group" value={tgValue} />
          <InfoRow label="Source"     value={sourceValue} />
        </Box>

        {/* Status chips */}
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {chips.map(({ key, label, tooltip, color, icon }) => (
            <Tooltip key={key} title={tooltip}>
              <Chip label={label} color={color} size="small" icon={icon} />
            </Tooltip>
          ))}
        </Box>

        {/* Playback controls */}
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Tooltip title={connected ? 'Play' : 'Not connected'}>
            <span>
              <IconButton
                onClick={handlePlay}
                disabled={!connected || playing}
                color="primary"
                aria-label="play"
              >
                <PlayArrowIcon />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Stop">
            <span>
              <IconButton
                onClick={handleStop}
                disabled={!playing}
                color="error"
                aria-label="stop"
              >
                <StopIcon />
              </IconButton>
            </span>
          </Tooltip>
          {audioStatus === 'error' && (
            <Typography variant="caption" color="error.main" sx={{ ml: 'auto' }}>
              stream error
            </Typography>
          )}
        </Box>
      </Box>
    </CardShell>
  );
}

