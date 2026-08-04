import { useState } from 'react';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CardShell from '../CardShell/CardShell';
import { useOp25Service } from '../../services/op25Service';

/**
 * The running configuration, read-only.
 *
 * Deliberately not editable: the decoder has no working `set_full_config`
 * (it answers with an explicit error), and writing the user's JSON from an
 * unauthenticated browser is a non-goal. This exists so the config the decoder
 * actually loaded can be inspected without shell access — which is the common
 * question when a channel or talkgroup file is not behaving.
 */
export default function ConfigCard() {
  const { config, terminalConfig } = useOp25Service();
  const [expanded, setExpanded] = useState(false);

  if (!config) {
    return (
      <CardShell title="Configuration">
        <Typography variant="body2" color="text.secondary">
          Waiting for the decoder's configuration…
        </Typography>
      </CardShell>
    );
  }

  const devices = config.devices ?? [];
  const channels = config.channels ?? [];
  const trunkChans = config.trunking?.chans ?? [];

  return (
    <CardShell title="Configuration">
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" variant="outlined" label={`${devices.length} device${devices.length === 1 ? '' : 's'}`} />
          <Chip size="small" variant="outlined" label={`${channels.length} channel${channels.length === 1 ? '' : 's'}`} />
          <Chip size="small" variant="outlined" label={`${trunkChans.length} trunked system${trunkChans.length === 1 ? '' : 's'}`} />
          {config.trunking?.module && (
            <Tooltip title="Trunking module handling these systems">
              <Chip size="small" variant="outlined" label={config.trunking.module} />
            </Tooltip>
          )}
          {terminalConfig?.terminal_type && (
            <Tooltip title="Terminal type from the config's terminal block">
              <Chip size="small" variant="outlined" label={terminalConfig.terminal_type} />
            </Tooltip>
          )}
        </Stack>

        {trunkChans.length > 0 && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>Trunked systems</Typography>
            <Stack spacing={0.5}>
              {trunkChans.map((c, i) => (
                <Box
                  key={`${c.sysname || 'system'}-${i}`}
                  sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 0.75 }}
                >
                  <Typography variant="body2" fontWeight="medium">{c.sysname || `system ${i}`}</Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ overflowWrap: 'anywhere' }}>
                    CC list: {c.control_channel_list || '—'}
                  </Typography>
                  {c.tgid_tags_file && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ overflowWrap: 'anywhere' }}>
                      tags: {c.tgid_tags_file}
                    </Typography>
                  )}
                  {(c.whitelist || c.blacklist) && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ overflowWrap: 'anywhere' }}>
                      {c.whitelist ? `whitelist: ${c.whitelist}` : ''}
                      {c.whitelist && c.blacklist ? ' · ' : ''}
                      {c.blacklist ? `blacklist: ${c.blacklist}` : ''}
                    </Typography>
                  )}
                </Box>
              ))}
            </Stack>
          </Box>
        )}

        <Accordion
          expanded={expanded}
          onChange={() => setExpanded((v) => !v)}
          disableGutters
          variant="outlined"
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="body2">Full JSON</Typography>
          </AccordionSummary>
          <AccordionDetails>
            {/* Wide content scrolls inside its own box rather than pushing the
                page sideways. */}
            <Box
              component="pre"
              sx={{
                m: 0, p: 1, maxHeight: 320, overflow: 'auto',
                fontSize: '0.72rem', lineHeight: 1.5,
                bgcolor: 'action.hover', borderRadius: 1,
              }}
            >
              {JSON.stringify(config, null, 2)}
            </Box>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              Read-only. Edit the JSON file on the server and restart —
              the decoder does not accept configuration changes over the socket.
            </Typography>
          </AccordionDetails>
        </Accordion>
      </Stack>
    </CardShell>
  );
}
