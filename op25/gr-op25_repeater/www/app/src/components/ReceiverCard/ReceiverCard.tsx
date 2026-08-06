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
import ControlRow from '../common/ControlRow';
import Field from '../common/Field';
import Hint from '../common/Hint';
import InfoRow from '../common/InfoRow';
import SectionHeading from '../common/SectionHeading';
import { useOp25Service, useSelectedChannel } from '../../services/op25Service';
import { apiUrl } from '../../utils/url';

/** Log levels multi_rx actually distinguishes. 0-2 are the useful day-to-day
 *  settings; 10 turns on ESS/encryption-sync decoding. */
const LOG_LEVELS = [0, 1, 2, 3, 5, 9, 10];

/** Shared by the menu items and the closed select, so both read the same. */
const LOG_LEVEL_LABEL = (lvl: number): string =>
  lvl === 0 ? '0 — quiet' : lvl === 10 ? '10 — ESS/crypt' : String(lvl);

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
    fetch(apiUrl('/api/captures'))
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
    // Collapsed by default: these are occasional-use controls, not something to
    // scan. The header still names them, so they are findable when wanted.
    <CardShell title="Tuning & Diagnostics" defaultCollapsed>
      <Stack spacing={2}>
        <Box>
          <InfoRow label="Acting on" value={channelName} />
          {noChannels && (
            <Typography variant="caption" color="text.secondary">
              No channels reported yet — controls unlock once the decoder is running.
            </Typography>
          )}
        </Box>

        {/* ---- Fine tuning ------------------------------------------------ */}
        <Box>
          <SectionHeading
            title="Fine tune"
            meta={
              <>
                <Tooltip title="Demodulator frequency error reported by the FLL. This is an automatic-frequency-control figure in Hz, not a bit error rate.">
                  <Chip variant="outlined" label={`freq error ${formatHz(channel?.error)}`} />
                </Tooltip>
                {channel?.ppm !== undefined && (
                  <Tooltip title="Device tuning correction currently applied, in parts per million">
                    <Chip variant="outlined" label={`ppm ${channel.ppm.toFixed(2)}`} />
                  </Tooltip>
                )}
              </>
            }
          />
          <ButtonGroup disabled={disabled} sx={{ flexWrap: 'wrap' }}>
            <Button onClick={() => adjustTune(-tuningStepLarge)}>{`-${tuningStepLarge}`}</Button>
            <Button onClick={() => adjustTune(-tuningStepSmall)}>{`-${tuningStepSmall}`}</Button>
            <Button onClick={() => adjustTune(tuningStepSmall)}>{`+${tuningStepSmall}`}</Button>
            <Button onClick={() => adjustTune(tuningStepLarge)}>{`+${tuningStepLarge}`}</Button>
          </ButtonGroup>
          <Hint>Steps come from terminal_config (tuning_step_small / tuning_step_large).</Hint>
        </Box>

        <Divider />

        {/* ---- Log level -------------------------------------------------- */}
        <Box>
          {/* The section heading names the control, so the field itself carries
              no second label of its own. */}
          <SectionHeading title="Log level" />
          <Field
            hint={`${logLevel === null ? 'Decoder default. ' : ''}Applies immediately and `
              + `goes to the decoder's stderr, not this page.`}
            sx={{ maxWidth: 380 }}
          >
            <TextField
              select
              disabled={disabled}
              value={logLevel ?? ''}
              onChange={(e) => setLogLevel(Number(e.target.value))}
              slotProps={{
                htmlInput: { 'aria-label': 'log verbosity' },
                // Until terminal_config arrives the level is unknown, and an
                // empty box reads as a broken control rather than a default.
                select: {
                  displayEmpty: true,
                  renderValue: (v: unknown) => (v === '' || v === null
                    ? <Box component="span" sx={{ color: 'text.disabled' }}>not set</Box>
                    : LOG_LEVEL_LABEL(Number(v))),
                },
              }}
              sx={{ width: 150 }}
            >
              {LOG_LEVELS.map((lvl) => (
                <MenuItem key={lvl} value={lvl}>{LOG_LEVEL_LABEL(lvl)}</MenuItem>
              ))}
            </TextField>
          </Field>
        </Box>

        <Divider />

        {/* ---- Symbol capture --------------------------------------------- */}
        <Box>
          <SectionHeading title="Symbol capture" />
          <ControlRow>
            <Button
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
                color="error"
                variant="outlined"
                label={channel?.capture_file || 'recording'}
              />
            )}
          </ControlRow>
          <Hint>
            Writes raw demodulated symbols on the server, replayable with the
            channel's <code>symbols</code> device args. Not available for replay
            (non-realtime) sessions.
          </Hint>

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
                        href={apiUrl(`/api/captures/${encodeURIComponent(c.name)}`)}
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
          <SectionHeading title="Lists &amp; diagnostics" />
          <ControlRow>
            <Tooltip title="Re-read this system's blacklist and whitelist files from disk, discarding talkgroups blacklisted at runtime">
              <Button variant="outlined" disabled={disabled} onClick={reloadLists}>
                Reload lists
              </Button>
            </Tooltip>
            <Tooltip title="Log every known talkgroup, patch, WUID and radio ID to the decoder's stderr">
              <Button variant="outlined" disabled={disabled} onClick={dumpTgids}>
                Dump tgids
              </Button>
            </Tooltip>
            <Tooltip title="Force each channel's decoder to dump its internal buffer to stderr">
              <Button variant="outlined" disabled={disabled} onClick={dumpBuffer}>
                Dump buffer
              </Button>
            </Tooltip>
          </ControlRow>
        </Box>
      </Stack>
    </CardShell>
  );
}
