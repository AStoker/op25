import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import CardShell from '../CardShell/CardShell';
import { useSelectedSystem } from '../../services/op25Service';
import type { FrequencyDataEntry } from '../../types/op25';

function formatFreq(hz: number): string {
  return `${(hz / 1e6).toFixed(4)} MHz`;
}

function InfoRow({ label, value, tooltip }: { label: string; value: React.ReactNode; tooltip?: string }) {
  const content = (
    <Box>
      <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight="medium" sx={{ overflowWrap: 'anywhere' }}>
        {value}
      </Typography>
    </Box>
  );

  if (!tooltip) return content;

  return (
    <Tooltip title={tooltip} placement="top" arrow enterDelay={400}>
      {content}
    </Tooltip>
  );
}

const FREQ_TYPE_COLOR: Record<string, 'primary' | 'success' | 'info' | 'default'> = {
  control:   'primary',
  voice:     'success',
  alternate: 'info',
};

export default function SiteInfoCard() {
  const system = useSelectedSystem();

  if (!system) {
    return (
      <CardShell title="Site Information">
        <Typography variant="body2" color="text.secondary">
          Waiting for site data…
        </Typography>
      </CardShell>
    );
  }

  const freqEntries = Object.entries(system.frequency_data || {})
    .map(([k, v]) => [Number(k), v] as [number, FrequencyDataEntry])
    .sort((a, b) => a[0] - b[0]);

  return (
    <CardShell title="Site Information">
      <Stack spacing={1.5}>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1 }}>
          <InfoRow label="System"   value={`${system.system} (${system.type})`}
            tooltip="The system name and its P25 phase/type (e.g. Phase 1 FDMA or Phase 2 TDMA)." />
          <InfoRow label="Callsign" value={system.callsign || '—'}
            tooltip="The FCC-assigned callsign for this radio system, if broadcast by the site." />
          <InfoRow label="NAC"      value={`0x${system.nac.toString(16).toUpperCase()}`}
            tooltip="Network Access Code — a 12-bit identifier (0x000–0xFFF) used to gate access to a P25 channel and distinguish networks sharing the same frequency." />
          <InfoRow label="WACN"     value={`0x${system.wacn.toString(16).toUpperCase()}`}
            tooltip="Wide Area Communications Network ID — a 20-bit identifier that groups multiple P25 systems belonging to the same wide-area network (e.g. a state or regional network)." />
          <InfoRow label="SysID"    value={`0x${system.sysid.toString(16).toUpperCase()}`}
            tooltip="System ID — a 12-bit value that uniquely identifies this P25 system within its WACN." />
          <InfoRow label="RFSS / Site" value={`${system.rfid}.${system.stid}`}
            tooltip="RF Sub-System ID (RFSS) and Site ID — together they pinpoint the physical tower site within the system. RFSS groups sites into sub-systems; Site ID identifies the individual site." />
          <InfoRow label="Control RX" value={formatFreq(system.rxchan)}
            tooltip="The receive frequency of the current control channel — the channel OP25 is monitoring to track calls and system activity." />
          <InfoRow label="Control TX" value={formatFreq(system.txchan)}
            tooltip="The transmit (uplink) frequency of the control channel — the frequency radios use when talking back to the site. Not used by OP25 for receiving." />
          <InfoRow label="Secondary CCs"
                   value={system.secondary?.length
                     ? system.secondary.map(formatFreq).join(', ')
                     : '—'}
            tooltip="Secondary (alternate) control channel frequencies broadcast by the site. OP25 can fall back to these if the primary control channel is lost." />
        </Box>

        {system.top_line && (
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
            {system.top_line}
          </Typography>
        )}

        <Box>
          <Typography variant="subtitle2" gutterBottom>Frequencies</Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 0.75 }}>
            {freqEntries.map(([hz, data]) => (
              <Box
                key={hz}
                sx={{
                  border: 1, borderColor: 'divider', borderRadius: 1, p: 0.75,
                  display: 'flex', flexDirection: 'column', gap: 0.25,
                }}
              >
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 0.5 }}>
                  <Typography variant="body2" fontFamily="monospace" fontWeight="medium">
                    {formatFreq(hz)}
                  </Typography>
                  <Chip
                    size="small"
                    label={data.type}
                    color={FREQ_TYPE_COLOR[data.type] ?? 'default'}
                    variant={data.type === 'control' ? 'filled' : 'outlined'}
                    sx={{ height: 18, fontSize: '0.65rem' }}
                  />
                </Box>
                <Typography variant="caption" color="text.secondary">
                  {data.last_activity.trim() || 'idle'} · cnt {data.counter}
                </Typography>
                {data.tgids.length > 0 && (
                  <Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>
                    {Array.from(new Set(data.tags.filter(Boolean))).slice(0, 3).join(', ')
                      || Array.from(new Set(data.tgids)).slice(0, 3).join(', ')}
                  </Typography>
                )}
              </Box>
            ))}
          </Box>
        </Box>
      </Stack>
    </CardShell>
  );
}
