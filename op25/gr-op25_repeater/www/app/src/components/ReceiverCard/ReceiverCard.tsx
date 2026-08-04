import { useCallback, useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import ButtonGroup from '@mui/material/ButtonGroup';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StopCircleIcon from '@mui/icons-material/StopCircle';
import CardShell from '../CardShell/CardShell';
import { useOp25Service, useSelectedChannel } from '../../services/op25Service';

/** Log levels multi_rx actually distinguishes. 0-2 are the useful day-to-day
 *  settings; 10 turns on ESS/encryption-sync decoding. */
const LOG_LEVELS = [0, 1, 2, 3, 5, 9, 10];

function formatHz(hz: number | null | undefined): string {
  if (hz === null || hz === undefined || !Number.isFinite(hz)) return '—';
  return `${hz > 0 ? '+' : ''}${Math.round(hz)} Hz`;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

interface CaptureFile {
  name: string;
  path: string;
  size: number;
  modified: number;
  exists: boolean;
}

/**
 * Receiver-level controls: the commands multi_rx has always accepted from the
 * curses terminal (fine tune, log level, symbol capture, list reload, state
 * dumps) which had no browser equivalent until now.  Everything here acts on
 * the channel selected in ChannelsCard.
 */
export default function ReceiverCard() {
  const {
    channels, channelIds, selectedChannelId,
    adjustTune, tuningStepSmall, tuningStepLarge,
    setLogLevel, logLevel,
    toggleCapture, reloadLists, dumpTgids, dumpBuffer,
    decoderRunning,
  } = useOp25Service();
  const channel = useSelectedChannel();

  const noChannels = channelIds.length === 0;
  const disabled   = noChannels || !decoderRunning;
  const capturing  = Boolean(channel?.capture);
  const channelName = channel?.name || (selectedChannelId !== null ? `Channel ${selectedChannelId}` : '—');

  const [captures, setCaptures] = useState<CaptureFile[]>([]);

  const refreshCaptures = useCallback(() => {
    fetch('/api/captures')
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { captures?: CaptureFile[] } | null) => {
        if (body?.captures) setCaptures(body.captures);
      })
      .catch(() => { /* older server without the endpoint — no list, no harm */ });
  }, []);

  // Refresh on mount and whenever a capture starts or stops, so a file appears
  // as soon as it exists and its final size shows once the sink is closed.
  useEffect(() => { refreshCaptures(); }, [refreshCaptures, capturing]);

  return (
    <CardShell title="Tuning & Diagnostics">
      <Stack spacing={2}>
        <Box>
          <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
            Acting on
          </Typography>
          <Typography variant="body2" fontWeight="medium">{channelName}</Typography>
          {noChannels && (
            <Typography variant="caption" color="text.secondary">
              No channels reported yet — controls unlock once the decoder is running.
            </Typography>
          )}
        </Box>

        {/* ---- Fine tuning ------------------------------------------------ */}
        <Box>
          <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle2">Fine tune</Typography>
            <Tooltip title="Demodulator frequency error reported by the FLL. This is an automatic-frequency-control figure in Hz, not a bit error rate.">
              <Chip
                size="small"
                variant="outlined"
                label={`freq error ${formatHz(channel?.error)}`}
              />
            </Tooltip>
            {channel?.ppm !== undefined && (
              <Tooltip title="Device tuning correction currently applied, in parts per million">
                <Chip size="small" variant="outlined" label={`ppm ${channel.ppm.toFixed(2)}`} />
              </Tooltip>
            )}
          </Stack>
          <ButtonGroup size="small" disabled={disabled} sx={{ mt: 1, flexWrap: 'wrap' }}>
            <Button onClick={() => adjustTune(-tuningStepLarge)}>{`-${tuningStepLarge}`}</Button>
            <Button onClick={() => adjustTune(-tuningStepSmall)}>{`-${tuningStepSmall}`}</Button>
            <Button onClick={() => adjustTune(tuningStepSmall)}>{`+${tuningStepSmall}`}</Button>
            <Button onClick={() => adjustTune(tuningStepLarge)}>{`+${tuningStepLarge}`}</Button>
          </ButtonGroup>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            Steps come from terminal_config (tuning_step_small / tuning_step_large).
          </Typography>
        </Box>

        <Divider />

        {/* ---- Log level -------------------------------------------------- */}
        <Box>
          <Typography variant="subtitle2" gutterBottom>Log level</Typography>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField
              select
              size="small"
              label="Verbosity"
              disabled={disabled}
              value={logLevel ?? ''}
              onChange={(e) => setLogLevel(Number(e.target.value))}
              sx={{ minWidth: 140 }}
              helperText={logLevel === null ? 'decoder default' : undefined}
            >
              {LOG_LEVELS.map((lvl) => (
                <MenuItem key={lvl} value={lvl}>
                  {lvl === 0 ? '0 — quiet' : lvl === 10 ? '10 — ESS/crypt' : String(lvl)}
                </MenuItem>
              ))}
            </TextField>
            <Typography variant="caption" color="text.secondary" sx={{ maxWidth: 260 }}>
              Applies immediately and goes to the decoder's stderr, not this page.
            </Typography>
          </Stack>
        </Box>

        <Divider />

        {/* ---- Symbol capture --------------------------------------------- */}
        <Box>
          <Typography variant="subtitle2" gutterBottom>Symbol capture</Typography>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button
              size="small"
              variant={capturing ? 'contained' : 'outlined'}
              color={capturing ? 'error' : 'primary'}
              disabled={disabled}
              startIcon={capturing ? <StopCircleIcon /> : <FiberManualRecordIcon />}
              onClick={toggleCapture}
            >
              {capturing ? 'Stop capture' : 'Start capture'}
            </Button>
            {capturing && (
              <Chip
                size="small"
                color="error"
                variant="outlined"
                label={channel?.capture_file || 'recording'}
              />
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            Writes raw demodulated symbols on the server, replayable with the
            channel's <code>symbols</code> device args. Not available for replay
            (non-realtime) sessions.
          </Typography>

          {captures.length > 0 && (
            <Box sx={{ mt: 1 }}>
              <Typography variant="caption" color="text.secondary" display="block">
                Captures this session
              </Typography>
              <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                {captures.map((c) => (
                  <Stack
                    key={c.path}
                    direction="row"
                    spacing={1}
                    alignItems="baseline"
                    flexWrap="wrap"
                    useFlexGap
                  >
                    {c.exists ? (
                      <Link
                        href={`/api/captures/${encodeURIComponent(c.name)}`}
                        variant="body2"
                        sx={{ overflowWrap: 'anywhere' }}
                      >
                        {c.name}
                      </Link>
                    ) : (
                      <Tooltip title="The decoder reported this file but it is no longer on disk">
                        <Typography variant="body2" color="text.disabled">{c.name}</Typography>
                      </Tooltip>
                    )}
                    <Typography variant="caption" color="text.secondary">
                      {formatBytes(c.size)}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          )}
        </Box>

        <Divider />

        {/* ---- Lists and diagnostics -------------------------------------- */}
        <Box>
          <Typography variant="subtitle2" gutterBottom>Lists &amp; diagnostics</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Tooltip title="Re-read this system's blacklist and whitelist files from disk, discarding talkgroups blacklisted at runtime">
              <Button size="small" variant="outlined" disabled={disabled} onClick={reloadLists}>
                Reload lists
              </Button>
            </Tooltip>
            <Tooltip title="Log every known talkgroup, patch, WUID and radio ID to the decoder's stderr">
              <Button size="small" variant="outlined" disabled={disabled} onClick={dumpTgids}>
                Dump tgids
              </Button>
            </Tooltip>
            <Tooltip title="Force each channel's decoder to dump its internal buffer to stderr">
              <Button size="small" variant="outlined" disabled={disabled} onClick={dumpBuffer}>
                Dump buffer
              </Button>
            </Tooltip>
          </Stack>
        </Box>
      </Stack>
    </CardShell>
  );
}
