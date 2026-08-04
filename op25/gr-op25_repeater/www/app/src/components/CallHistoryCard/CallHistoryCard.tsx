import { useMemo, forwardRef } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import type { TableComponents } from 'react-virtuoso';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TableContainer from '@mui/material/TableContainer';
import CardShell from '../CardShell/CardShell';
import { useIsPhone } from '../../hooks/useIsPhone';
import { useSmartColor } from '../../hooks/useSmartColor';
import { useOp25Service, useSelectedSystem } from '../../services/op25Service';

interface Row {
  key: string;
  time: string;
  freq: number;
  tgid: number;
  tag: string;
  src: number;
  srcTag: string;
  /** Time slot — the two slots of a DMR/TDMA channel are independent
   *  conversations, so a call log without it is ambiguous. */
  slot?: number;
  /** Trunk priority (lower wins). */
  prio?: number;
}

function fmtFreq(hz: number): string {
  return (hz / 1e6).toFixed(4);
}

function fmtTime(epoch: number): string {
  if (!epoch) return '';
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString();
}

const VirtuosoTableComponents: TableComponents<Row> = {
  Scroller: forwardRef<HTMLDivElement>((props, ref) => (
    <TableContainer {...props} ref={ref} />
  )),
  Table: (props) => <Table size="small" sx={{ tableLayout: 'fixed' }} {...props} />,
  TableHead: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableHead {...props} ref={ref} />
  )),
  TableRow: ({ item: _item, ...props }) => <TableRow hover {...props} />,
  TableBody: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableBody {...props} ref={ref} />
  )),
};

export default function CallHistoryCard() {
  const system    = useSelectedSystem();
  const { callLog } = useOp25Service();
  const phone     = useIsPhone();
  const tint      = useSmartColor();

  // Primary source: the rolling call_log (when present).
  // Fallback: derive entries from per-frequency tgid/srcaddr history.
  const rows = useMemo<Row[]>(() => {
    if (callLog.length > 0) {
      return callLog
        .slice()
        .reverse()
        .map((e, i) => ({
          key:    `${e.time}-${i}`,
          time:   fmtTime(e.time),
          freq:   e.freq,
          tgid:   e.tgid,
          tag:    e.tgtag,
          src:    e.rid,
          srcTag: e.rtag,
          slot:   e.slot,
          prio:   e.prio,
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
    return out;
  }, [callLog, system]);

  // On a phone the frequency and the bare TGID are the least useful columns \u2014
  // the tag already names the talkgroup \u2014 so they make way for the two that
  // answer "who just talked, and when".
  const fixedHeaderContent = () => (
    <TableRow>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '24%' : '16%' }}>Time</TableCell>
      {!phone && (
        <>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '13%' }}>Freq</TableCell>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '9%' }}>TG</TableCell>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '7%' }}>Slot</TableCell>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '7%' }}>Prio</TableCell>
        </>
      )}
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '40%' : '25%' }}>Tag</TableCell>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '36%' : '24%' }}>Source</TableCell>
    </TableRow>
  );

  const rowContent = (_index: number, r: Row) => (
    <>
      <TableCell>{r.time || '\u2014'}</TableCell>
      {!phone && (
        <>
          <TableCell>{fmtFreq(r.freq)}</TableCell>
          <TableCell>{r.tgid || '\u2014'}</TableCell>
          <TableCell>{r.slot === undefined || r.slot === null ? '\u2014' : r.slot}</TableCell>
          <TableCell>{r.prio ?? '\u2014'}</TableCell>
        </>
      )}
      <TableCell sx={{ overflowWrap: 'anywhere', color: tint(r.tag) }}>
        {r.tag || (r.tgid ? `TG ${r.tgid}` : '\u2014')}
      </TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        {r.src ? (r.srcTag ? `${r.srcTag} (${r.src})` : r.src) : '\u2014'}
      </TableCell>
    </>
  );

  return (
    <CardShell title="Call History">
      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No calls yet.
        </Typography>
      ) : (
        <Box sx={{ height: { xs: 280, sm: 320 } }}>
          <TableVirtuoso
            data={rows}
            components={VirtuosoTableComponents}
            fixedHeaderContent={fixedHeaderContent}
            itemContent={rowContent}
          />
        </Box>
      )}
    </CardShell>
  );
}
