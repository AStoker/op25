import { useState, useMemo } from 'react';
import {
  Paper, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Typography, Box, IconButton, Tooltip, TextField,
  InputAdornment, Select, MenuItem, FormControl, Button,
} from '@mui/material';
import FilterListIcon from '@mui/icons-material/FilterList';
import ClearIcon from '@mui/icons-material/Clear';
import DownloadIcon from '@mui/icons-material/Download';
import VisibilityIcon from '@mui/icons-material/Visibility';
import type { CallHistoryEntry, SmartColor } from '../types';

interface Props {
  entries: CallHistoryEntry[];
  source: string;
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
  onClear: () => void;
  maxRows: number;
}

function getSmartColor(text: string, smartColors: SmartColor[], enabled: boolean): string | undefined {
  if (!enabled || !text) return undefined;
  const lower = text.toLowerCase();
  for (const sc of smartColors) {
    if (sc.keywords.some((kw) => lower.includes(kw.toLowerCase()))) return sc.color;
  }
  return undefined;
}

function sourceLabel(src: string): string {
  const map: Record<string, string> = {
    frequency: 'Frequency Data',
    voice: 'Voice Grants',
    display: 'Display',
  };
  return map[src] ?? src;
}

export default function CallHistory({
  entries, source, smartColors, settingsSmartColors, onClear, maxRows,
}: Props) {
  const [filter, setFilter] = useState('');
  const [seenOpen, setSeenOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!filter.trim()) return entries.slice(0, maxRows);
    const q = filter.toLowerCase();
    return entries.filter((e) =>
      e.tgid.includes(q) || e.tgName.toLowerCase().includes(q) || e.sysHex.toLowerCase().includes(q) || e.source.toLowerCase().includes(q) || e.freq.includes(q)
    ).slice(0, maxRows);
  }, [entries, filter, maxRows]);

  // Unique seen TGs derived from all entries
  const seenTgs = useMemo(() => {
    const map = new Map<string, { tgid: string; tgName: string; sysHex: string; hits: number }>();
    for (const e of entries) {
      const key = `${e.sysHex}|${e.tgid}`;
      const ex = map.get(key);
      if (ex) ex.hits++;
      else map.set(key, { tgid: e.tgid, tgName: e.tgName, sysHex: e.sysHex, hits: 1 });
    }
    return Array.from(map.values()).sort((a, b) => b.hits - a.hits);
  }, [entries]);

  const exportCsv = () => {
    const header = 'Time,System,Frequency,TGID,Talkgroup,Source\n';
    const rows = filtered.map((e) =>
      [e.timestamp, e.sysHex, e.freq, e.tgid, `"${e.tgName}"`, `"${e.source}"`].join(',')
    );
    const blob = new Blob([header + rows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `op25-callhistory-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Paper elevation={1} sx={{ border: '1px solid #2a2a2a', overflow: 'hidden' }}>
        {/* Header */}
        <Box
          sx={{
            px: 1.5,
            py: 0.75,
            borderBottom: '1px solid #2a2a2a',
            display: 'grid',
            gridTemplateColumns: '1fr auto 1fr',
            alignItems: 'center',
            gap: 1,
          }}
        >
          {/* Filter */}
          <TextField
            size="small"
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <FilterListIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                </InputAdornment>
              ),
              endAdornment: filter && (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => setFilter('')} sx={{ p: 0.25 }}>
                    <ClearIcon sx={{ fontSize: 12 }} />
                  </IconButton>
                </InputAdornment>
              ),
              sx: { fontSize: '0.75rem', height: 28 },
            }}
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 1 } }}
          />

          {/* Title */}
          <Typography variant="subtitle2" sx={{ textAlign: 'center', whiteSpace: 'nowrap', fontSize: '0.72rem', color: 'text.secondary' }}>
            CALL HISTORY — {sourceLabel(source).toUpperCase()}
          </Typography>

          {/* Actions */}
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
            <Tooltip title="Seen talkgroups" arrow>
              <IconButton size="small" onClick={() => setSeenOpen(true)} sx={{ color: 'text.secondary' }}>
                <VisibilityIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
            <Tooltip title="Export call history to CSV" arrow>
              <IconButton size="small" onClick={exportCsv} sx={{ color: 'text.secondary' }}>
                <DownloadIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
            <Tooltip title="Clear call history" arrow>
              <IconButton size="small" onClick={onClear} sx={{ color: 'text.secondary' }}>
                <ClearIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        {/* Table */}
        <TableContainer sx={{ maxHeight: 500, overflowY: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Sys</TableCell>
                <TableCell>Frequency</TableCell>
                <TableCell>TGID</TableCell>
                <TableCell>Talkgroup</TableCell>
                <TableCell>Source</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((entry, i) => {
                const color = getSmartColor(entry.tgName, smartColors, settingsSmartColors);
                return (
                  <TableRow key={i}>
                    <TableCell sx={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums', color: 'text.secondary' }}>
                      {entry.timestamp}
                    </TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{entry.sysHex}</TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{entry.freq}</TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums', color: color ?? 'inherit' }}>
                      {entry.tgid}
                    </TableCell>
                    <TableCell
                      sx={{
                        maxWidth: 200,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: color ?? 'inherit',
                      }}
                    >
                      {entry.tgName}
                    </TableCell>
                    <TableCell
                      sx={{
                        maxWidth: 160,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: 'text.secondary',
                      }}
                    >
                      {entry.source}
                    </TableCell>
                  </TableRow>
                );
              })}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center" sx={{ color: 'text.secondary', py: 3 }}>
                    {filter ? 'No matching entries' : 'No call history yet'}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>

        {entries.length > 0 && (
          <Box sx={{ px: 1.5, py: 0.5, borderTop: '1px solid #2a2a2a' }}>
            <Typography variant="caption" color="text.secondary">
              {filtered.length} entries{filter ? ` (filtered from ${entries.length})` : ''}
            </Typography>
          </Box>
        )}
      </Paper>

      {/* Seen Talkgroups Dialog */}
      <SeenTgDialog open={seenOpen} onClose={() => setSeenOpen(false)} tgs={seenTgs} smartColors={smartColors} settingsSmartColors={settingsSmartColors} />
    </>
  );
}

// ── Seen TG Dialog ────────────────────────────────────────────────────────────
import {
  Dialog, DialogTitle, DialogContent,
} from '@mui/material';

function SeenTgDialog({
  open, onClose, tgs, smartColors, settingsSmartColors,
}: {
  open: boolean;
  onClose: () => void;
  tgs: Array<{ tgid: string; tgName: string; sysHex: string; hits: number }>;
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
}) {
  const [filter, setFilter] = useState('');

  const filtered = useMemo(() => {
    if (!filter.trim()) return tgs;
    const q = filter.toLowerCase();
    return tgs.filter((t) => t.tgid.includes(q) || t.tgName.toLowerCase().includes(q) || t.sysHex.toLowerCase().includes(q));
  }, [tgs, filter]);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', pb: 1 }}>
        <Typography variant="h6" sx={{ flex: 1 }}>Seen Talkgroups ({tgs.length})</Typography>
        <IconButton size="small" onClick={onClose}><ClearIcon fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent sx={{ p: 0 }}>
        <Box sx={{ px: 2, py: 1, borderBottom: '1px solid #333' }}>
          <TextField
            fullWidth
            size="small"
            placeholder="Filter by TGID, name, or system…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </Box>
        <TableContainer sx={{ maxHeight: '60vh' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>System</TableCell>
                <TableCell>TGID</TableCell>
                <TableCell>Talkgroup</TableCell>
                <TableCell align="right">Hits</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((t) => {
                const color = getSmartColor(t.tgName, smartColors, settingsSmartColors);
                return (
                  <TableRow key={`${t.sysHex}|${t.tgid}`}>
                    <TableCell>{t.sysHex}</TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{t.tgid}</TableCell>
                    <TableCell sx={{ color: color ?? 'inherit' }}>{t.tgName}</TableCell>
                    <TableCell align="right" sx={{ color: 'text.secondary' }}>{t.hits}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </DialogContent>
    </Dialog>
  );
}
