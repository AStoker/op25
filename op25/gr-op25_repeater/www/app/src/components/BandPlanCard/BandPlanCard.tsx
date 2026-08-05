import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import CardShell from '../CardShell/CardShell';
import { useSelectedSystem } from '../../services/op25Service';
import { isKind, systemKind, SYSTEM_KIND_LABEL } from '../../utils/systemKind';

export default function BandPlanCard() {
  const system = useSelectedSystem();
  const entries = system ? Object.entries(system.band_plan || {}) : [];

  if (!system || entries.length === 0) {
    // A band plan (iden_up) is a P25 concept. Saying "not yet" on a SmartNet or
    // Connect+ system promises data that is never coming.
    const notApplicable = system !== null && !isKind(system, 'p25', 'unknown');
    return (
      <CardShell title="Band Plan">
        <Typography variant="body2" color="text.secondary">
          {notApplicable
            ? `Band plans are P25-specific — ${SYSTEM_KIND_LABEL[systemKind(system)]} does not broadcast one.`
            : 'No band-plan data yet.'}
        </Typography>
      </CardShell>
    );
  }

  return (
    <CardShell title="Band Plan">
      <Box sx={{ maxHeight: { xs: 200, sm: 240 }, overflow: 'auto' }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              <TableCell align="right">Base</TableCell>
              <TableCell align="right">Step</TableCell>
              <TableCell align="right">Offset</TableCell>
              <TableCell>TDMA</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {entries.map(([id, bp]) => (
              <TableRow key={id} hover>
                <TableCell>{id}</TableCell>
                <TableCell align="right">{(bp.frequency / 1e6).toFixed(6)} MHz</TableCell>
                <TableCell align="right">{bp.step} Hz</TableCell>
                <TableCell align="right">{(bp.offset / 1e6).toFixed(3)} MHz</TableCell>
                <TableCell>{bp.tdma ? `×${bp.tdma}` : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </CardShell>
  );
}
