import {
  Paper, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Typography, Box, Chip, Tooltip, IconButton, Collapse,
} from '@mui/material';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import { useState } from 'react';
import type { ChannelData, SmartColor } from '../types';

interface Props {
  channels: ChannelData[];
  currentChannelId: number;
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
  onHold: (tgid: number) => void;
}

function getSmartColor(text: string, smartColors: SmartColor[], enabled: boolean): string | undefined {
  if (!enabled || !text) return undefined;
  const lower = text.toLowerCase();
  for (const sc of smartColors) {
    if (sc.keywords.some((kw) => lower.includes(kw.toLowerCase()))) return sc.color;
  }
  return undefined;
}

function fmtFreq(hz: number | null | undefined): string {
  if (!hz) return '—';
  return (hz / 1e6).toFixed(4);
}

export default function ChannelTable({
  channels, currentChannelId, smartColors, settingsSmartColors, onHold,
}: Props) {
  const [open, setOpen] = useState(true);

  if (channels.length === 0) return null;

  return (
    <Paper elevation={1} sx={{ border: '1px solid #2a2a2a', overflow: 'hidden' }}>
      <Box
        sx={{ px: 1.5, py: 0.75, borderBottom: open ? '1px solid #2a2a2a' : 'none', display: 'flex', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setOpen((v) => !v)}
      >
        <Typography variant="subtitle2" sx={{ flex: 1, fontSize: '0.72rem', color: 'text.secondary' }}>
          CHANNELS
        </Typography>
        <IconButton size="small" sx={{ p: 0 }}>
          {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>
      <Collapse in={open}>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Ch</TableCell>
                <TableCell>Name</TableCell>
                <TableCell>System</TableCell>
                <TableCell>Freq (MHz)</TableCell>
                <TableCell>Talkgroup</TableCell>
                <TableCell>Mode</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Error</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {channels.map((ch) => {
                const isActive = ch.index === currentChannelId;
                const tgText = ch.tgtag || (ch.tgid != null ? `Talkgroup ${ch.tgid}` : '—');
                const tgColor = getSmartColor(tgText, smartColors, settingsSmartColors);

                return (
                  <TableRow
                    key={ch.index}
                    sx={{
                      backgroundColor: isActive ? 'rgba(0,255,255,0.06)' : undefined,
                      '& td': { borderLeft: isActive ? '2px solid' : undefined, borderLeftColor: isActive ? 'primary.main' : undefined },
                    }}
                  >
                    <TableCell sx={{ fontWeight: isActive ? 700 : 400, color: isActive ? 'primary.main' : undefined }}>
                      {ch.index}
                    </TableCell>
                    <TableCell>{ch.tag}</TableCell>
                    <TableCell sx={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ch.system || '—'}
                    </TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {fmtFreq(ch.freq)}
                    </TableCell>
                    <TableCell sx={{ color: tgColor, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {tgText}
                    </TableCell>
                    <TableCell>{ch.mode || '—'}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                        {ch.hold && (
                          <Tooltip title="Hold is active on this channel" arrow>
                            <Chip label="HOLD" size="small" color="primary" sx={{ fontSize: '0.6rem', height: 16, color: '#000' }} />
                          </Tooltip>
                        )}
                        {ch.capture && (
                          <Tooltip title="IQ capture is active" arrow>
                            <Chip label="REC" size="small" color="error" sx={{ fontSize: '0.6rem', height: 16 }} />
                          </Tooltip>
                        )}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums', color: ch.error ? 'warning.main' : 'text.secondary' }}>
                      {ch.error != null ? `${ch.error} Hz` : '—'}
                    </TableCell>
                    <TableCell sx={{ p: 0.5 }}>
                      {ch.tgid != null && (
                        <Tooltip title={`Hold TGID ${ch.tgid}`} arrow>
                          <IconButton size="small" onClick={() => onHold(ch.tgid!)} sx={{ p: 0.5 }}>
                            <PauseCircleIcon sx={{ fontSize: 14 }} />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Collapse>
    </Paper>
  );
}
