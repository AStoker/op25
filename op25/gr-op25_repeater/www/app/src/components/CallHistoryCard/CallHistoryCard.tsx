import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import CardShell from '../CardShell/CardShell';
import { useOp25Service, useSelectedSystem } from '../../services/op25Service';

interface Row {
  key: string;
  time: string;
  freq: number;
  tgid: number;
  tag: string;
  src: number;
  srcTag: string;
}

function fmtFreq(hz: number): string {
  return (hz / 1e6).toFixed(4);
}

function fmtTime(epoch: number): string {
  if (!epoch) return '';
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString();
}

export default function CallHistoryCard() {
  const system    = useSelectedSystem();
  const { callLog } = useOp25Service();

  // Primary source: the rolling call_log (when present).
  // Fallback: derive entries from per-frequency tgid/srcaddr history.
  const rows = useMemo<Row[]>(() => {
    if (callLog.length > 0) {
      return callLog
        .slice()
        .reverse()
        .slice(0, 100)
        .map((e, i) => ({
          key:    `${e.time}-${i}`,
          time:   fmtTime(e.time),
          freq:   e.freq,
          tgid:   e.tgid,
          tag:    e.tgtag,
          src:    e.rid,
          srcTag: e.rtag,
        }));
    }

    if (!system?.frequency_data) return [];
    const out: Row[] = [];
    for (const [freqStr, data] of Object.entries(system.frequency_data)) {
      if (data.type !== 'voice') continue;
      const freq = Number(freqStr);
      const len  = data.tgids.length;
      // Walk the per-frequency history newest → oldest.
      for (let i = len - 1; i >= 0; i--) {
        out.push({
          key:    `${freq}-${i}`,
          time:   data.last_activity.trim(),
          freq,
          tgid:   Number(data.tgids[i]),
          tag:    data.tags[i] ?? '',
          src:    data.srcaddrs[i] ?? 0,
          srcTag: data.srctags[i] ?? '',
        });
      }
    }
    return out.slice(0, 100);
  }, [callLog, system]);

  return (
    <CardShell title="Call History">
      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No calls yet.
        </Typography>
      ) : (
        <Box sx={{ maxHeight: 320, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Freq</TableCell>
                <TableCell>TG</TableCell>
                <TableCell>Tag</TableCell>
                <TableCell>Source</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.key} hover>
                  <TableCell>{r.time || '—'}</TableCell>
                  <TableCell>{fmtFreq(r.freq)}</TableCell>
                  <TableCell>{r.tgid || '—'}</TableCell>
                  <TableCell>{r.tag || '—'}</TableCell>
                  <TableCell>
                    {r.src ? (r.srcTag ? `${r.srcTag} (${r.src})` : r.src) : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </CardShell>
  );
}
