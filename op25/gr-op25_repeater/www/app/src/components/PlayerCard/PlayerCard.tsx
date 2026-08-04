import { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import LockIcon from '@mui/icons-material/Lock';
import LockOpenIcon from '@mui/icons-material/LockOpen';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import CardShell from '../CardShell/CardShell';
import { useWebSocketService } from '../../services/websocketService';
import { useAudioStream } from '../../hooks/useAudioStream';
import { audioSourceLabel, useAudioSources, AGGREGATE_AUDIO_URL } from '../../hooks/useAudioSources';
import { useSmartColor } from '../../hooks/useSmartColor';
import { useOp25Service, useSelectedChannel, useSelectedSystem } from '../../services/op25Service';

const AUDIO_STREAM_URL = AGGREGATE_AUDIO_URL;

interface InfoRowProps {
  label: string;
  value: string;
  /** Smart-colour tint, when the value is a talkgroup tag. */
  color?: string;
}

function InfoRow({ label, value, color }: InfoRowProps) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight="medium" sx={{ overflowWrap: 'anywhere', color }}>
        {value}
      </Typography>
    </Box>
  );
}

function formatFreq(hz: number | null | undefined): string {
  if (!hz || !Number.isFinite(hz)) return '—';
  return `${(hz / 1e6).toFixed(4)} MHz`;
}

export default function PlayerCard() {
  const { status } = useWebSocketService();
  const sources = useAudioSources();
  // Which stream to pull. Defaults to the aggregate mix, so a single-channel
  // setup behaves exactly as it did before per-channel streams existed.
  const [sourceUrl, setSourceUrl] = useState<string>(AUDIO_STREAM_URL);
  const { start, stop, audioStatus } = useAudioStream(sourceUrl);
  const channel        = useSelectedChannel();
  const system         = useSelectedSystem();
  const { decoderRunning, releaseHold, skipCall } = useOp25Service();
  const tint = useSmartColor();

  // Muting is entirely client-side: stopping the Web Audio path stops pulling
  // /api/stream, which is the whole mechanism.  This used to also send
  // SYSTEM_CONTROL mute/unmute, which the server silently discarded.
  function handlePlay() {
    start().catch(() => {});
  }

  function handleStop() {
    stop();
  }

  const connected = status === 'open';
  const playing   = audioStatus === 'playing' || audioStatus === 'loading';

  // Switching source mid-playback has to re-open the HTTP stream; start()
  // tears down the previous session itself. Skip the first run so mounting
  // does not auto-play (browsers require a gesture for that anyway).
  const playedUrlRef = useRef<string | null>(null);
  useEffect(() => {
    if (!playing) return;
    if (playedUrlRef.current === sourceUrl) return;
    playedUrlRef.current = sourceUrl;
    start().catch(() => {});
  }, [sourceUrl, playing, start]);

  // Only worth showing a picker when there is more than one thing to pick, and
  // hide slots that have never carried a byte (slot B on a P25 system).
  const selectableSources = sources.filter((s) => s.slot === 'A' || s.bytes > 0);
  const showSourcePicker  = selectableSources.length > 1;

  const channelName = channel?.name ?? '—';
  const tgValue     = channel?.tgid
    ? `${channel.tag || 'TG'} (${channel.tgid})`
    : '—';
  const freqValue   = formatFreq(channel?.freq);
  const sourceValue = channel?.srcaddr
    ? (channel.srctag ? `${channel.srctag} (${channel.srcaddr})` : String(channel.srcaddr))
    : '—';

  // Look up a tag name for a TGID from the trunked-system's tag table.
  const tgTag = (tgid: number): string | null =>
    system?.tgid_tags?.[String(tgid)]?.tag ?? null;

  type ChipDef = { key: string; label: string; tooltip: string; color: 'default' | 'success' | 'error' | 'warning'; icon: React.ReactElement };
  const chips: ChipDef[] = [];

  if (channel) {
    chips.push({
      key:     'enc',
      label:   channel.encrypted ? 'Encrypted' : 'Open',
      tooltip: channel.encrypted
        ? 'Call is encrypted — audio may not decode'
        : 'Call is unencrypted',
      color: channel.encrypted ? 'error' : 'success',
      icon:  <LockIcon sx={{ fontSize: '0.9rem' }} />,
    });
    if (channel.emergency) {
      chips.push({
        key:     'emrg',
        label:   'Emergency',
        tooltip: 'Emergency call in progress',
        color:   'error',
        icon:    <WarningAmberIcon sx={{ fontSize: '0.9rem' }} />,
      });
    }
    if (channel.hold_tgid) {
      const holdName = tgTag(channel.hold_tgid);
      chips.push({
        key:     'hold',
        label:   holdName ? `Held: ${holdName}` : `Held ${channel.hold_tgid}`,
        tooltip: holdName
          ? `Talk-group hold active: ${holdName} (TGID ${channel.hold_tgid})`
          : `Talk-group hold active: TGID ${channel.hold_tgid}`,
        color:   'warning',
        icon:    <LockIcon sx={{ fontSize: '0.9rem' }} />,
      });
    }
  }

  // Derive system identity from live trunk_update data.
  const sysName   = system?.system ?? channel?.system ?? '';
  const callsign  = system?.callsign ?? '';
  const sysLabel  = [sysName, callsign].filter(Boolean).join(' / ') || 'System';
  const chanLabel = channel?.name ?? system?.system ?? '—';

  const decoderStatusLabel = !connected
    ? 'offline'
    : decoderRunning ? 'running' : 'connecting';
  const decoderStatusColor: 'success' | 'warning' | 'default' =
    decoderRunning ? 'success' : connected ? 'warning' : 'default';

  return (
    <CardShell title="Player">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {/* System info — always shown */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}
                        sx={{ overflowWrap: 'anywhere' }}>
              {sysLabel}
            </Typography>
            <Typography variant="body2" fontWeight="medium" sx={{ overflowWrap: 'anywhere' }}>
              {chanLabel}
            </Typography>
          </Box>
          <Tooltip title="Decoder status">
            <Chip
              label={decoderStatusLabel}
              color={decoderStatusColor}
              size="small"
              sx={{ textTransform: 'capitalize' }}
            />
          </Tooltip>
        </Box>

        {/* Call info */}
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
          <InfoRow label="Channel"    value={channelName} />
          <InfoRow label="Frequency"  value={freqValue} />
          <InfoRow label="Talk Group" value={tgValue} color={tint(channel?.tag)} />
          <InfoRow label="Source"     value={sourceValue} />
        </Box>

        {/* Status chips */}
        {chips.length > 0 && (
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
            {chips.map(({ key, label, tooltip, color, icon }) => (
              <Tooltip key={key} title={tooltip}>
                <Chip label={label} color={color} size="small" icon={icon} />
              </Tooltip>
            ))}
          </Box>
        )}

        {/* Playback controls — sized for a thumb, not a mouse pointer */}
        <Box sx={{
          display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap',
          '& .MuiIconButton-root': { minWidth: 44, minHeight: 44 },
        }}>
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
          <Tooltip title="Skip current call">
            <span>
              <IconButton
                onClick={skipCall}
                disabled={!connected}
                aria-label="skip"
              >
                <SkipNextIcon />
              </IconButton>
            </span>
          </Tooltip>
          {channel?.hold_tgid ? (
            <Tooltip title="Release talk-group hold">
              <span>
                <IconButton onClick={releaseHold} disabled={!connected} aria-label="release hold">
                  <LockOpenIcon />
                </IconButton>
              </span>
            </Tooltip>
          ) : null}
            {audioStatus === 'error' && (
            <Typography variant="caption" color="error.main" sx={{ ml: 'auto' }}>
                stream error
              </Typography>
            )}
        </Box>

        {/* Audio source. Every configured channel sends its own UDP audio, so
            with more than one there is a real choice to make — a single mixed
            stream means hearing two conversations at once. */}
        {showSourcePicker && (
          <TextField
            select
            size="small"
            label="Audio source"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            helperText={sourceUrl === AGGREGATE_AUDIO_URL
              ? 'All channels mixed together'
              : 'One channel only'}
            sx={{ maxWidth: { sm: 320 } }}
          >
            <MenuItem value={AGGREGATE_AUDIO_URL}>All channels (mix)</MenuItem>
            {selectableSources.map((src) => (
              <MenuItem key={src.port} value={src.url}>
                {audioSourceLabel(src)}
              </MenuItem>
            ))}
          </TextField>
        )}
      </Box>
    </CardShell>
  );
}
