import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import DialogShell from '../common/DialogShell';
import InsetPanel from '../common/InsetPanel';
import SectionHeading from '../common/SectionHeading';
import Hint from '../common/Hint';
import { useOp25Service } from '../../services/op25Service';
import { useSystemState } from '../../hooks/useSystemState';

const REPO_URL     = 'https://github.com/AStoker/op25';
const UPSTREAM_URL = 'https://github.com/boatbod/op25';

/** Merge-base with boatbod/op25. This fork no longer tracks upstream — the
 *  remote is deliberately gone — so the divergence point is a fixed fact. */
const FORK_POINT = 'b2e04c3f';

/** What this fork changed, in the order someone comparing the two would care
 *  about. Kept short on purpose: each line is one visible difference, not a
 *  changelog entry. */
const DIFFERENCES: { title: string; body: string }[] = [
  {
    title: 'One web UI, one port',
    body: 'A React single-page app over a FastAPI/uvicorn server. Static files, '
        + 'the control WebSocket and the audio stream all share one port. '
        + "Upstream's two-port waitress GUI and its static pages are gone.",
  },
  {
    title: 'Built for a phone as well as a desk',
    body: 'The dashboard collapses to tabs below 900px, tables drop their '
        + 'lower-value columns on a phone, and the theme follows the device '
        + 'between light and dark.',
  },
  {
    title: 'Call capture, transcripts and alerts',
    body: 'Each transmission is sliced into its own clip, levelled, optionally '
        + "transcribed through Home Assistant's speech-to-text, keyword-matched "
        + 'and pushed to a webhook. Clips can be uploaded to the HA media library.',
  },
  {
    title: 'A Home Assistant add-on',
    body: 'This repository is also an add-on store. Supervisor pulls a prebuilt '
        + 'image rather than compiling GNU Radio on the box, and the UI works '
        + 'behind ingress.',
  },
  {
    title: 'Plots without gnuplot',
    body: 'The decoder sends raw traces over the WebSocket and the browser draws '
        + 'them — FFT, constellation, symbol, eye, mixer and FLL. No gnuplot '
        + 'subprocess, no PNG files, no X11.',
  },
  {
    title: 'Runs on macOS',
    body: 'Local speaker output goes through PortAudio (CoreAudio on a Mac) '
        + 'alongside the historical ALSA and PulseAudio backends, so the same '
        + 'tree develops on Apple Silicon and deploys on Debian or a Pi 5.',
  },
  {
    title: 'multi_rx only',
    body: "The older single-channel receiver (rx.py, trunking.py) and the C++ "
        + 'websocketpp audio transport were removed. Everything is configured '
        + 'by the JSON config file that multi_rx loads.',
  },
];

/**
 * What this is and how it differs from upstream.
 *
 * Reached from the header. Anyone who found this build through the add-on store
 * rather than through the git history needs somewhere that says plainly what
 * they are running and where the code came from.
 */
export default function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { config, terminalConfig } = useOp25Service();
  const health = useSystemState();

  const trunkChans = config?.trunking?.chans ?? [];
  // Configured counts, not live ones: this dialog can be opened before the
  // decoder has reported a channel, and "0 channels" would then be wrong about
  // the install rather than merely quiet about the moment.
  const channels = config?.channels ?? [];
  const terminalType = terminalConfig?.terminal_type ?? config?.terminal?.terminal_type;

  return (
    <DialogShell open={open} onClose={onClose} title="About OP25">
      <Stack spacing={2}>
        <Box>
          <Typography variant="body2">
            OP25 decodes P25, DMR/Connect+ and SmartNet trunked radio from a
            software-defined radio, following the control channel and playing the
            voice traffic it grants. The decoder itself is GNU Radio: a C++
            out-of-tree module driven by Python.
          </Typography>
          <Typography variant="body2" sx={{ mt: 1 }}>
            This build is a fork whose goal is a scanner you operate from a
            browser — on a phone, or through Home Assistant — rather than from a
            terminal.
          </Typography>
        </Box>

        <Box>
          <SectionHeading title="How this differs from boatbod/op25" />
          <Stack spacing={0.75}>
            {DIFFERENCES.map((d) => (
              <InsetPanel key={d.title}>
                <Typography variant="body2" fontWeight="medium">{d.title}</Typography>
                <Typography variant="caption" color="text.secondary" display="block">
                  {d.body}
                </Typography>
              </InsetPanel>
            ))}
          </Stack>
          <Hint>
            A hard fork, not a patch set: it diverged from upstream at{' '}
            <code>{FORK_POINT}</code> and no longer merges from it. Decoder fixes
            are cherry-picked deliberately.
          </Hint>
        </Box>

        <Box>
          <SectionHeading title="This session" />
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip variant="outlined" label={`decoder ${health?.status ?? 'unknown'}`} />
            <Chip variant="outlined" label={`${channels.length} channel${channels.length === 1 ? '' : 's'}`} />
            <Chip variant="outlined" label={`${trunkChans.length} trunked system${trunkChans.length === 1 ? '' : 's'}`} />
            {terminalType && <Chip variant="outlined" label={terminalType} />}
          </Stack>
        </Box>

        <Box>
          <SectionHeading title="Source and licence" />
          <Stack spacing={0.25}>
            <Link href={REPO_URL} target="_blank" rel="noopener" variant="body2">
              This fork — github.com/AStoker/op25
            </Link>
            <Link href={UPSTREAM_URL} target="_blank" rel="noopener" variant="body2">
              Upstream — github.com/boatbod/op25
            </Link>
          </Stack>
          <Hint>
            GPL v3, as upstream. OP25 is the work of the osmocom OP25 project and
            of boatbod's fork before this one; the decoder internals here are
            still theirs.
          </Hint>
        </Box>
      </Stack>
    </DialogShell>
  );
}
