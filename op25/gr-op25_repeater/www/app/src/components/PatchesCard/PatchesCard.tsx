import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import CardShell from '../CardShell/CardShell';
import { useSelectedSystem } from '../../services/op25Service';
import type { PatchEntry } from '../../types/op25';

export default function PatchesCard() {
  const system = useSelectedSystem();

  const rows: PatchEntry[] = [];
  if (system?.patch_data) {
    for (const sg of Object.values(system.patch_data)) {
      for (const patch of Object.values(sg)) rows.push(patch);
    }
  }

  return (
    <CardShell title="Patches">
      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No active patches.
        </Typography>
      ) : (
        <Box sx={{ maxHeight: { xs: 200, sm: 240 }, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Super-group</TableCell>
                <TableCell>Patched TG</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((p, i) => (
                <TableRow key={`${p.sg}-${p.ga}-${i}`} hover>
                  <TableCell>{p.sgtag ? `${p.sgtag} (${p.sg})` : p.sg}</TableCell>
                  <TableCell>{p.gatag ? `${p.gatag} (${p.ga})` : p.ga}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </CardShell>
  );
}
