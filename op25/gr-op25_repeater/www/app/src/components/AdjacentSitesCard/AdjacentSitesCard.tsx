import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import CardShell from '../CardShell/CardShell';
import { useSelectedSystem } from '../../services/op25Service';

function fmtFreq(hz: number): string {
  return `${(hz / 1e6).toFixed(4)} MHz`;
}

export default function AdjacentSitesCard() {
  const system = useSelectedSystem();
  const entries = system ? Object.entries(system.adjacent_data || {}) : [];

  return (
    <CardShell title="Adjacent Sites">
      {entries.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No adjacent sites reported.
        </Typography>
      ) : (
        <Box sx={{ maxHeight: { xs: 220, sm: 280 }, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>RFSS.Site</TableCell>
                <TableCell>Downlink</TableCell>
                <TableCell>Uplink</TableCell>
                <TableCell>Band</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {entries.map(([freqStr, adj]) => (
                <TableRow key={freqStr} hover>
                  <TableCell>{`${adj.rfid}.${adj.stid}`}</TableCell>
                  <TableCell>{fmtFreq(Number(freqStr))}</TableCell>
                  <TableCell>{fmtFreq(adj.uplink)}</TableCell>
                  <TableCell>{adj.table}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </CardShell>
  );
}
