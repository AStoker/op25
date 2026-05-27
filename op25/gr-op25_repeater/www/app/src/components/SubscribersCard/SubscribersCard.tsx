import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import CardShell from '../CardShell/CardShell';
import { useSelectedSystem } from '../../services/op25Service';

function fmtTime(epoch: number): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleTimeString();
}

export default function SubscribersCard() {
  const system = useSelectedSystem();

  const rows = useMemo(() => {
    if (!system?.wuid_data) return [];
    return Object.entries(system.wuid_data)
      .map(([key, entry]) => ({ ...entry, key }))
      .sort((a, b) => b.time - a.time);
  }, [system]);

  return (
    <CardShell title="Subscribers">
      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No subscriber units seen yet.
        </Typography>
      ) : (
        <Box sx={{ maxHeight: 280, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Source</TableCell>
                <TableCell>Affiliated TG</TableCell>
                <TableCell>Site</TableCell>
                <TableCell>Last</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.slice(0, 100).map((r) => (
                <TableRow key={r.key} hover>
                  <TableCell>{r.tag || r.srcaddr}</TableCell>
                  <TableCell>{r.aff_ga_tag ? `${r.aff_ga_tag} (${r.aff_ga})` : (r.aff_ga || '—')}</TableCell>
                  <TableCell>{`${r.rfss}.${r.site}`}</TableCell>
                  <TableCell>{fmtTime(r.time)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </CardShell>
  );
}
