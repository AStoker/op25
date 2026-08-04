import { useState, useMemo } from 'react';
import {
  Paper, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Typography, Box, TextField, InputAdornment, IconButton,
  TableSortLabel, Tooltip,
} from '@mui/material';
import FilterListIcon from '@mui/icons-material/FilterList';
import ClearIcon from '@mui/icons-material/Clear';
import type { WuidEntry, SmartColor } from '../types';

interface Props {
  data: Record<string, WuidEntry>;
  mode: 'all' | 'selected';
  currentSystem: string;
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
}

type SortKey = 'time' | 'system' | 'tgid' | 'tgName' | 'src' | 'ag';
type SortDir = 'asc' | 'desc';

function getSmartColor(text: string, smartColors: SmartColor[], enabled: boolean): string | undefined {
  if (!enabled || !text) return undefined;
  const lower = text.toLowerCase();
  for (const sc of smartColors) {
    if (sc.keywords.some((kw) => lower.includes(kw.toLowerCase()))) return sc.color;
  }
  return undefined;
}

interface RowData {
  id: string;
  time: string;
  epochMs: number;
  system: string;
  tgid: string;
  tgName: string;
  src: string;
  ag: string;
  rfss: string;
  site: string;
}

export default function SubscriberTable({
  data, mode, currentSystem, smartColors, settingsSmartColors,
}: Props) {
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('time');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const rows = useMemo<RowData[]>(() => {
    const result: RowData[] = [];
    for (const [id, entry] of Object.entries(data)) {
      const epochMs = entry.time ? entry.time * 1000 : 0;
      const d = epochMs ? new Date(epochMs) : null;
      const timeStr = d
        ? [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':')
        : '—';

      result.push({
        id,
        time: timeStr,
        epochMs,
        system: entry.rfss != null ? `RFSS ${entry.rfss}` : '—',
        tgid: entry.aff_ga != null ? String(entry.aff_ga) : '—',
        tgName: entry.aff_ga_tag ?? '',
        src: entry.tag || entry.suid || String(entry.srcaddr),
        ag: entry.aff_aga != null ? String(entry.aff_aga) : '—',
        rfss: entry.rfss != null ? String(entry.rfss) : '—',
        site: entry.site != null ? String(entry.site) : '—',
      });
    }
    return result;
  }, [data, mode, currentSystem]);

  const filtered = useMemo(() => {
    if (!filter.trim()) return rows;
    const q = filter.toLowerCase();
    return rows.filter((r) =>
      r.src.toLowerCase().includes(q) ||
      r.tgid.includes(q) ||
      r.tgName.toLowerCase().includes(q) ||
      r.system.toLowerCase().includes(q)
    );
  }, [rows, filter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let av: string | number = a[sortKey as keyof RowData] as string | number;
      let bv: string | number = b[sortKey as keyof RowData] as string | number;
      if (sortKey === 'time') { av = a.epochMs; bv = b.epochMs; }
      if (typeof av === 'string' && typeof bv === 'string') {
        av = av.toLowerCase(); bv = bv.toLowerCase();
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filtered, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  const SortCell = ({ label, id }: { label: string; id: SortKey }) => (
    <TableCell sortDirection={sortKey === id ? sortDir : false}>
      <TableSortLabel
        active={sortKey === id}
        direction={sortKey === id ? sortDir : 'asc'}
        onClick={() => handleSort(id)}
      >
        {label}
      </TableSortLabel>
    </TableCell>
  );

  return (
    <Paper elevation={1} sx={{ border: '1px solid #2a2a2a', overflow: 'hidden' }}>
      <Box
        sx={{
          px: 1.5, py: 0.75, borderBottom: '1px solid #2a2a2a',
          display: 'flex', alignItems: 'center', gap: 1,
        }}
      >
        <TextField
          size="small"
          placeholder="Filter subscribers…"
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
          sx={{ flex: 1, '& .MuiOutlinedInput-root': { borderRadius: 1 } }}
        />

        <Typography variant="subtitle2" sx={{ whiteSpace: 'nowrap', fontSize: '0.72rem', color: 'text.secondary' }}>
          SUBSCRIBERS
        </Typography>

        <Typography variant="caption" sx={{ whiteSpace: 'nowrap', color: 'text.secondary', ml: 'auto' }}>
          {sorted.length}
        </Typography>
      </Box>

      <TableContainer sx={{ maxHeight: 400, overflowY: 'auto' }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <SortCell label="Time" id="time" />
              <SortCell label="System" id="system" />
              <SortCell label="TGID" id="tgid" />
              <SortCell label="Talkgroup" id="tgName" />
              <SortCell label="Source" id="src" />
              <SortCell label="AG" id="ag" />
            </TableRow>
          </TableHead>
          <TableBody>
            {sorted.map((row) => {
              const color = getSmartColor(row.tgName, smartColors, settingsSmartColors);
              return (
                <TableRow key={row.id}>
                  <TableCell sx={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums', color: 'text.secondary' }}>
                    {row.time}
                  </TableCell>
                  <TableCell>{row.system}</TableCell>
                  <TableCell sx={{ fontVariantNumeric: 'tabular-nums', color: color ?? 'inherit' }}>
                    {row.tgid}
                  </TableCell>
                  <TableCell sx={{ color: color ?? 'inherit', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.tgName || '—'}
                  </TableCell>
                  <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{row.src}</TableCell>
                  <TableCell>{row.ag}</TableCell>
                </TableRow>
              );
            })}
            {sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ color: 'text.secondary', py: 3 }}>
                  {filter ? 'No matching subscribers' : 'No subscriber data'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}
