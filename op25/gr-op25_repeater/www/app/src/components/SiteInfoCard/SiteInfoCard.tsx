import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import CardShell from '../CardShell/CardShell';
import InfoRow from '../common/InfoRow';
import InsetPanel from '../common/InsetPanel';
import SectionHeading from '../common/SectionHeading';
import { useSelectedSystem } from '../../services/op25Service';
import type { FrequencyDataEntry } from '../../types/op25';
import {
  freqOrDash, hexOrDash, numOrDash, systemKind, SYSTEM_KIND_LABEL,
} from '../../utils/systemKind';

function formatFreq(hz: number): string {
  return `${(hz / 1e6).toFixed(4)} MHz`;
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

  // Each trunking module publishes a different set of identity fields, and
  // omits the ones that do not apply — so the rows are chosen by system type
  // rather than assuming the P25 shape.
  const kind = systemKind(system);

  const commonRows = (
    <>
      <InfoRow label="System" value={`${system.system} (${SYSTEM_KIND_LABEL[kind]})`}
        tooltip="The configured system name, and which trunking module is decoding it." />
      <InfoRow label="Control RX" value={freqOrDash(system.rxchan)}
        tooltip="The receive frequency of the current control channel — the channel OP25 is monitoring to track calls and system activity." />
      <InfoRow label="Secondary CCs"
               value={system.secondary?.length
                 ? system.secondary.map(formatFreq).join(', ')
                 : '—'}
        tooltip="Secondary (alternate) control channel frequencies broadcast by the site. OP25 can fall back to these if the primary control channel is lost." />
    </>
  );

  return (
    <CardShell title="Site Information">
      <Stack spacing={1.5}>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(3, 1fr)' }, gap: 1 }}>
          {commonRows}

          {kind === 'p25' && (
            <>
              <InfoRow label="Callsign" value={system.callsign || '—'}
                tooltip="The FCC-assigned callsign for this radio system, if broadcast by the site." />
              <InfoRow label="NAC" value={hexOrDash(system.nac)}
                tooltip="Network Access Code — a 12-bit identifier (0x000–0xFFF) used to gate access to a P25 channel and distinguish networks sharing the same frequency." />
              <InfoRow label="WACN" value={hexOrDash(system.wacn)}
                tooltip="Wide Area Communications Network ID — a 20-bit identifier that groups multiple P25 systems belonging to the same wide-area network (e.g. a state or regional network)." />
              <InfoRow label="SysID" value={hexOrDash(system.sysid)}
                tooltip="System ID — a 12-bit value that uniquely identifies this P25 system within its WACN." />
              <InfoRow label="RFSS / Site" value={`${numOrDash(system.rfid)}.${numOrDash(system.stid)}`}
                tooltip="RF Sub-System ID (RFSS) and Site ID — together they pinpoint the physical tower site within the system. RFSS groups sites into sub-systems; Site ID identifies the individual site." />
              <InfoRow label="Control TX" value={freqOrDash(system.txchan)}
                tooltip="The transmit (uplink) frequency of the control channel — the frequency radios use when talking back to the site. Not used by OP25 for receiving." />
              <InfoRow label="LRA" value={hexOrDash(system.lra)}
                tooltip="Location Registration Area — the registration zone this site belongs to, broadcast in RFSS_STS_BCST." />
            </>
          )}

          {kind === 'smartnet' && (
            <>
              <InfoRow label="System ID" value={hexOrDash(system.sysid_smartnet, 4)}
                tooltip="SmartNet/SmartZone system ID as broadcast in the control-channel OSWs." />
              <InfoRow label="Site" value={numOrDash(system.siteid)}
                tooltip="SmartZone site number. Absent on a single-site SmartNet system, which does not broadcast one." />
            </>
          )}

          {kind === 'trbo' && (
            <>
              <InfoRow label="Rest LCN" value={numOrDash(system.rest_lcn)}
                tooltip="Connect+ rest channel — the logical channel radios idle on between calls." />
              <InfoRow label="Channels" value={numOrDash(Object.keys(system.lcn_data || {}).length)}
                tooltip="Number of logical channels (LCNs) configured for this Connect+ system." />
            </>
          )}
        </Box>

        {/* Conditions worth knowing about, when the decoder reports them. */}
        {(system.network_active === 0 || (system.encryption_algid ?? null) !== null) && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {system.network_active === 0 && (
              <Tooltip title="The site has cleared the RFSS_STS_BCST 'A' bit: it is running failsoft, isolated from the wider network. Local traffic only.">
                <Chip color="warning" variant="outlined" label="failsoft" />
              </Tooltip>
            )}
            {(system.encryption_algid ?? null) !== null && (
              <Tooltip title="The control channel itself is encrypted (P_PARM_BCST reported an algorithm id), so trunking messages may not decode.">
                <Chip
                  color="error"
                  variant="outlined"
                  label={`CC encrypted (alg ${hexOrDash(system.encryption_algid)})`}
                />
              </Tooltip>
            )}
          </Stack>
        )}

        {system.top_line && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ fontFamily: 'monospace', overflowX: 'auto', whiteSpace: 'pre' }}
          >
            {system.top_line}
          </Typography>
        )}

        <Box>
          <SectionHeading title="Frequencies" meta={`${freqEntries.length} known`} />
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(220px, 100%), 1fr))', gap: 0.75 }}>
            {freqEntries.map(([hz, data]) => (
              <InsetPanel
                key={hz}
                sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}
              >
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 0.5 }}>
                  <Typography variant="body2" fontFamily="monospace" fontWeight="medium">
                    {formatFreq(hz)}
                  </Typography>
                  <Chip
                    label={data.type}
                    color={FREQ_TYPE_COLOR[data.type] ?? 'default'}
                    variant={data.type === 'control' ? 'filled' : 'outlined'}
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
              </InsetPanel>
            ))}
          </Box>
        </Box>
      </Stack>
    </CardShell>
  );
}
