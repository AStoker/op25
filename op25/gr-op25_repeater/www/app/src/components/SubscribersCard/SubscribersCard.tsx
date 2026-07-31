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
import { useSelectedSystem } from '../../services/op25Service';

function fmtTime(epoch: number): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleTimeString();
}

interface SubscriberRow {
  key: string;
  tag?: string;
  srcaddr?: number | string;
  aff_ga_tag?: string;
  aff_ga?: number | string;
  rfss?: number | string;
  site?: number | string;
  time: number;
}

const VirtuosoTableComponents: TableComponents<SubscriberRow> = {
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

export default function SubscribersCard() {
  const system = useSelectedSystem();
  const phone  = useIsPhone();

  const rows = useMemo<SubscriberRow[]>(() => {
    if (!system?.wuid_data) return [];
    return Object.entries(system.wuid_data)
      .map(([key, entry]) => ({
        ...entry,
        key,
        aff_ga_tag:  entry.aff_ga_tag  ?? undefined,
        aff_aga_tag: entry.aff_aga_tag ?? undefined,
      }))
      .sort((a, b) => b.time - a.time);
  }, [system]);

  // The RFSS/site column is dropped on phones: with a single monitored site
  // it is the same value on every row.
  const fixedHeaderContent = () => (
    <TableRow>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '30%' : '25%' }}>Source</TableCell>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '46%' : '45%' }}>Affiliated TG</TableCell>
      {!phone && (
        <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '15%' }}>Site</TableCell>
      )}
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '24%' : '15%' }}>Last</TableCell>
    </TableRow>
  );

  const rowContent = (_index: number, r: SubscriberRow) => (
    <>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>{r.tag || r.srcaddr}</TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        {r.aff_ga_tag ? `${r.aff_ga_tag} (${r.aff_ga})` : (r.aff_ga || '\u2014')}
      </TableCell>
      {!phone && <TableCell>{`${r.rfss}.${r.site}`}</TableCell>}
      <TableCell>{fmtTime(r.time)}</TableCell>
    </>
  );

  return (
    <CardShell title="Subscribers">
      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No subscriber units seen yet.
        </Typography>
      ) : (
        <Box sx={{ height: { xs: 240, sm: 280 } }}>
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
