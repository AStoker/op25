import { useMemo, useState } from 'react';
import {
  Paper, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Typography, Box, Chip, Collapse, IconButton, Tooltip,
  Accordion, AccordionSummary, AccordionDetails, Button,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import type { NacData, SmartColor } from '../types';

interface Props {
  nacData: Record<string, NacData>;
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
  showBandPlan: boolean;
  showAdjacentSites: boolean;
  radioIdInFreqTable: boolean;
  getSiteAlias: (sysname: string, rfss: unknown, site: unknown) => string;
  onHold: (tgid: number) => void;
}

function getSmartColor(text: string, smartColors: SmartColor[], enabled: boolean): string | undefined {
  if (!enabled || !text) return undefined;
  const lower = text.toLowerCase();
  for (const sc of smartColors) {
    if (sc.keywords.some((kw) => lower.includes(kw.toLowerCase()))) return sc.color;
  }
  return undefined;
}

function fmtFreq(hz: unknown): string {
  const n = parseInt(String(hz), 10);
  if (isNaN(n)) return '-';
  return (n / 1e6).toFixed(6);
}

function hexVal(v: unknown): string {
  if (v == null) return '-';
  const n = typeof v === 'number' ? v : parseInt(String(v), 16);
  if (isNaN(n)) return String(v);
  return '0x' + n.toString(16).toUpperCase();
}

export default function FrequencyTable({
  nacData, smartColors, settingsSmartColors, showBandPlan,
  showAdjacentSites, radioIdInFreqTable, getSiteAlias, onHold,
}: Props) {
  const entries = useMemo(() => Object.entries(nacData), [nacData]);

  if (entries.length === 0) return null;

  return (
    <>
      {entries.map(([nacKey, nac]) => {
        const isP25 = nac.type === 'p25';
        const isSmartnet = nac.type === 'smartnet';
        const sysname = nac.system ?? '-';
        const rfid = nac.rfid;
        const stid = nac.stid;
        const siteName = getSiteAlias(sysname, rfid, stid);

        return (
          <Box key={nacKey} sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {/* System info card */}
            <Paper elevation={1} sx={{ p: 1.5, border: '1px solid #2a2a2a' }}>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'primary.main', fontSize: '0.75rem' }}>
                {siteName.startsWith('Site ') ? siteName : `Site ${stid}: ${siteName}`}
              </Typography>

              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(90px, 1fr))',
                  gap: '2px 8px',
                }}
              >
                {[
                  { label: 'Callsign', value: nac.callsign || '-' },
                  { label: 'Type', value: nac.type || '-' },
                  { label: 'Sys ID', value: hexVal(nac.sysid) },
                  { label: 'WACN', value: hexVal(nac.wacn) },
                  { label: 'NAC', value: hexVal(nac.nac) },
                  { label: 'RFSS', value: String(rfid ?? '-') },
                  { label: 'Site', value: String(stid ?? '-') },
                  { label: 'Last TSBK', value: nac.last_tsbk ? epochToTime(nac.last_tsbk) : '-' },
                ].map(({ label, value }) => (
                  <Box key={label}>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.2 }}>
                      {label}
                    </Typography>
                    <Typography variant="caption" sx={{ fontWeight: 600, color: 'primary.main', lineHeight: 1.4, fontVariantNumeric: 'tabular-nums' }}>
                      {value}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Paper>

            {/* Band Plan (P25 only, optional) */}
            {isP25 && showBandPlan && nac.band_plan && Object.keys(nac.band_plan).length > 0 && (
              <Accordion
                elevation={1}
                disableGutters
                sx={{ border: '1px solid #2a2a2a', '&:before': { display: 'none' } }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 36, '& .MuiAccordionSummary-content': { my: 0.5 } }}>
                  <Typography variant="subtitle2" sx={{ fontSize: '0.72rem', color: 'text.secondary' }}>
                    BAND PLAN
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0 }}>
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          {['ID', 'Type', 'Frequency', 'Tx Offset (MHz)', 'Spacing (kHz)', 'Slots'].map((h) => (
                            <TableCell key={h}>{h}</TableCell>
                          ))}
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {Object.entries(nac.band_plan).map(([id, bp]) => {
                          const freq = bp.frequency != null ? (bp.frequency / 1e6).toFixed(6) : '-';
                          const offset = bp.offset != null ? (bp.offset / 1e6).toFixed(3) : '-';
                          const step = bp.step != null ? (bp.step / 1000).toFixed(1) : '-';
                          const slots = String(bp.tdma ?? 1);
                          const type = (bp.tdma ?? 1) > 1 ? 'TDMA' : 'FDMA';
                          return (
                            <TableRow key={id}>
                              <TableCell>{id}</TableCell>
                              <TableCell>{type}</TableCell>
                              <TableCell>{freq}</TableCell>
                              <TableCell>{offset}</TableCell>
                              <TableCell>{step}</TableCell>
                              <TableCell>{slots}</TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </AccordionDetails>
              </Accordion>
            )}

            {/* Frequency table */}
            <Paper elevation={1} sx={{ border: '1px solid #2a2a2a', overflow: 'hidden' }}>
              <Box sx={{ px: 1.5, py: 0.75, borderBottom: '1px solid #2a2a2a', display: 'flex', alignItems: 'center' }}>
                <Typography variant="subtitle2" sx={{ fontSize: '0.72rem', color: 'text.secondary' }}>
                  FREQUENCIES
                </Typography>
              </Box>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Frequency</TableCell>
                      <TableCell>Last</TableCell>
                      <TableCell colSpan={2}>Active Talkgroup</TableCell>
                      <TableCell>Mode</TableCell>
                      <TableCell align="right">Count</TableCell>
                      <TableCell />
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(nac.frequency_data ?? {}).map(([freq, entry]) => {
                      const chanType = entry.type;
                      const [tg1, tg2] = entry.tgids;
                      const [tag1, tag2] = entry.tags;
                      const [src1, src2] = entry.srctags;
                      const [addr1, addr2] = entry.srcaddrs;

                      const src1Str = src1 || (addr1 ? `ID: ${addr1}` : '-');
                      const src2Str = src2 || (addr2 ? `ID: ${addr2}` : '-');

                      const isControl = chanType === 'control';
                      const isAlt = chanType === 'alternate';
                      const isTdma = tg1 != null && tg2 != null && tg1 !== tg2;

                      const tgDisplay1 = tag1 || (tg1 != null ? `Talkgroup ${tg1}` : '');
                      const tgDisplay2 = tag2 || (tg2 != null ? `Talkgroup ${tg2}` : '');

                      let modeLabel = '-';
                      if (isControl) modeLabel = isSmartnet ? 'CC' : '  CC  ';
                      else if (isAlt) modeLabel = isP25 ? 'Sec CC' : 'Alt CC';
                      else if (isP25) modeLabel = isTdma ? 'TDMA' : 'FDMA';
                      else if (isSmartnet && entry.mode) modeLabel = entry.mode;

                      const freqMhz = fmtFreq(freq);
                      const count = isControl ? '-' : String(entry.counter ?? 0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

                      const color1 = getSmartColor(tgDisplay1, smartColors, settingsSmartColors);
                      const color2 = getSmartColor(tgDisplay2, smartColors, settingsSmartColors);

                      if (isControl) {
                        return (
                          <TableRow key={freq}>
                            <TableCell sx={{ fontVariantNumeric: 'tabular-nums', color: 'text.secondary' }}>{freqMhz}</TableCell>
                            <TableCell>{entry.last_activity}</TableCell>
                            <TableCell colSpan={2} align="center" sx={{ color: 'text.secondary' }}>Control</TableCell>
                            <TableCell sx={{ color: 'text.secondary' }}>{modeLabel}</TableCell>
                            <TableCell />
                            <TableCell />
                          </TableRow>
                        );
                      }

                      if (tg1 == null && tg2 == null) {
                        return (
                          <TableRow key={freq}>
                            <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{freqMhz}</TableCell>
                            <TableCell>{entry.last_activity}</TableCell>
                            <TableCell colSpan={2} align="center" sx={{ color: 'text.secondary' }}>—</TableCell>
                            <TableCell sx={{ color: isAlt ? 'warning.main' : undefined }}>{modeLabel}</TableCell>
                            <TableCell align="right">{count}</TableCell>
                            <TableCell />
                          </TableRow>
                        );
                      }

                      if (!isTdma) {
                        // Single TG (FDMA or SmartNet)
                        const tgNum = tg1 ?? tg2;
                        const tgStr = tgDisplay1 || tgDisplay2 || String(tgNum);
                        const truncated = tgStr.length > 20 ? tgStr.substring(0, 19) + '…' : tgStr;
                        const srcStr = src1Str;
                        return (
                          <TableRow key={freq}>
                            <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{freqMhz}</TableCell>
                            <TableCell>{entry.last_activity}</TableCell>
                            <TableCell colSpan={2}>
                              <Box>
                                <Typography variant="body2" sx={{ color: color1 ?? 'inherit' }}>
                                  {tgNum} · {truncated}
                                </Typography>
                                {radioIdInFreqTable && (
                                  <Typography variant="caption" color="text.secondary">{srcStr}</Typography>
                                )}
                              </Box>
                            </TableCell>
                            <TableCell>{modeLabel}</TableCell>
                            <TableCell align="right">{count}</TableCell>
                            <TableCell sx={{ p: 0.5 }}>
                              {tgNum != null && (
                                <Tooltip title={`Hold TGID ${tgNum}`} arrow>
                                  <IconButton size="small" onClick={() => onHold(tgNum as number)} sx={{ p: 0.5 }}>
                                    <PauseCircleIcon sx={{ fontSize: 14 }} />
                                  </IconButton>
                                </Tooltip>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      }

                      // TDMA: two rows
                      return [
                        <TableRow key={`${freq}-0`}>
                          <TableCell rowSpan={2} sx={{ fontVariantNumeric: 'tabular-nums', verticalAlign: 'middle' }}>{freqMhz}</TableCell>
                          <TableCell rowSpan={2} sx={{ verticalAlign: 'middle' }}>{entry.last_activity}</TableCell>
                          <TableCell>
                            <Box>
                              <Typography variant="body2" sx={{ color: color1 ?? 'inherit' }}>
                                {tg1} · {tgDisplay1.substring(0, 20)}
                              </Typography>
                              {radioIdInFreqTable && (
                                <Typography variant="caption" color="text.secondary">{src1Str}</Typography>
                              )}
                            </Box>
                          </TableCell>
                          <TableCell rowSpan={2} sx={{ verticalAlign: 'middle' }}>{modeLabel}</TableCell>
                          <TableCell rowSpan={2} align="right" sx={{ verticalAlign: 'middle' }}>{count}</TableCell>
                          <TableCell sx={{ p: 0.5, verticalAlign: 'middle' }}>
                            {tg1 != null && (
                              <Tooltip title={`Hold TGID ${tg1}`} arrow>
                                <IconButton size="small" onClick={() => onHold(tg1 as number)} sx={{ p: 0.5 }}>
                                  <PauseCircleIcon sx={{ fontSize: 14 }} />
                                </IconButton>
                              </Tooltip>
                            )}
                          </TableCell>
                        </TableRow>,
                        <TableRow key={`${freq}-1`}>
                          <TableCell>
                            <Box>
                              <Typography variant="body2" sx={{ color: color2 ?? 'inherit' }}>
                                {tg2} · {tgDisplay2.substring(0, 20)}
                              </Typography>
                              {radioIdInFreqTable && (
                                <Typography variant="caption" color="text.secondary">{src2Str}</Typography>
                              )}
                            </Box>
                          </TableCell>
                          <TableCell sx={{ p: 0.5 }}>
                            {tg2 != null && (
                              <Tooltip title={`Hold TGID ${tg2}`} arrow>
                                <IconButton size="small" onClick={() => onHold(tg2 as number)} sx={{ p: 0.5 }}>
                                  <PauseCircleIcon sx={{ fontSize: 14 }} />
                                </IconButton>
                              </Tooltip>
                            )}
                          </TableCell>
                        </TableRow>,
                      ];
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>

            {/* Adjacent Sites */}
            {showAdjacentSites && nac.adjacent_data && Object.keys(nac.adjacent_data).length > 0 && (
              <AdjacentSitesTable data={nac.adjacent_data} sysid={nac.sysid} isP25={isP25} isSmartnet={isSmartnet} getSiteAlias={getSiteAlias} sysname={sysname} />
            )}

            {/* Patches */}
            {nac.patch_data && Object.keys(nac.patch_data).length > 0 && (
              <PatchesTable data={nac.patch_data} isP25={isP25} isSmartnet={isSmartnet} />
            )}
          </Box>
        );
      })}
    </>
  );
}

function epochToTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

// ── Adjacent Sites sub-component ─────────────────────────────────────────────
function AdjacentSitesTable({
  data, sysid, isP25, isSmartnet, getSiteAlias, sysname,
}: {
  data: Record<string, { rfid: number; stid: number; uplink: number }>;
  sysid?: number;
  isP25: boolean;
  isSmartnet: boolean;
  getSiteAlias: (sys: string, rfss: unknown, site: unknown) => string;
  sysname: string;
}) {
  const [open, setOpen] = useState(true);

  return (
    <Paper elevation={1} sx={{ border: '1px solid #2a2a2a', overflow: 'hidden' }}>
      <Box
        sx={{ px: 1.5, py: 0.75, borderBottom: open ? '1px solid #2a2a2a' : 'none', display: 'flex', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setOpen((v) => !v)}
      >
        <Typography variant="subtitle2" sx={{ flex: 1, fontSize: '0.72rem', color: 'text.secondary' }}>
          ADJACENT SITES
        </Typography>
        <IconButton size="small" sx={{ p: 0 }}>
          {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>
      <Collapse in={open}>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                {isP25 && <TableCell>System</TableCell>}
                {isP25 && <TableCell>Site Name</TableCell>}
                {isP25 && <TableCell>RFSS</TableCell>}
                <TableCell>Site</TableCell>
                <TableCell>Frequency</TableCell>
                <TableCell>Uplink</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Object.entries(data).map(([freq, entry]) => {
                const rx = (parseInt(freq) / 1e6).toFixed(6);
                const ul = (entry.uplink / 1e6).toFixed(6);
                const alias = getSiteAlias(sysname, entry.rfid, entry.stid);
                return (
                  <TableRow key={freq}>
                    {isP25 && <TableCell>{sysid != null ? sysid.toString(16).toUpperCase() : '-'}</TableCell>}
                    {isP25 && <TableCell>{alias}</TableCell>}
                    {isP25 && <TableCell>{entry.rfid}</TableCell>}
                    <TableCell>{entry.stid}</TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{rx}</TableCell>
                    <TableCell sx={{ fontVariantNumeric: 'tabular-nums' }}>{ul}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Collapse>
    </Paper>
  );
}

// ── Patches sub-component ─────────────────────────────────────────────────────
function PatchesTable({
  data, isP25, isSmartnet,
}: {
  data: Record<string, Record<string, { sg?: number; sgtag?: string; ga: number; gatag?: string; tgid_dec?: number; tgid_hex?: string; sub_tgid_dec?: number; sub_tgid_hex?: string; mode?: string }>>;
  isP25: boolean;
  isSmartnet: boolean;
}) {
  const [open, setOpen] = useState(true);

  return (
    <Paper elevation={1} sx={{ border: '1px solid #2a2a2a', overflow: 'hidden' }}>
      <Box
        sx={{ px: 1.5, py: 0.75, borderBottom: open ? '1px solid #2a2a2a' : 'none', display: 'flex', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setOpen((v) => !v)}
      >
        <Typography variant="subtitle2" sx={{ flex: 1, fontSize: '0.72rem', color: 'text.secondary' }}>
          PATCHES
        </Typography>
        <IconButton size="small" sx={{ p: 0 }}>
          {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>
      <Collapse in={open}>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                {isP25 && <TableCell>Supergroup</TableCell>}
                {isP25 && <TableCell>Group</TableCell>}
                {isSmartnet && <TableCell>TG</TableCell>}
                {isSmartnet && <TableCell>Sub TG</TableCell>}
                {isSmartnet && <TableCell>Mode</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {Object.entries(data).flatMap(([tgid, subTgids]) =>
                Object.entries(subTgids).map(([subTgid, entry], i) => (
                  <TableRow key={`${tgid}-${subTgid}`}>
                    {isP25 && i === 0 && (
                      <TableCell rowSpan={Object.keys(subTgids).length}>
                        {entry.sg}{entry.sgtag ? ` — ${entry.sgtag}` : ''}
                      </TableCell>
                    )}
                    {isP25 && (
                      <TableCell>
                        {entry.ga}{entry.gatag ? ` — ${entry.gatag}` : ''}
                      </TableCell>
                    )}
                    {isSmartnet && i === 0 && (
                      <TableCell rowSpan={Object.keys(subTgids).length}>
                        {entry.tgid_dec} / {entry.tgid_hex}
                      </TableCell>
                    )}
                    {isSmartnet && (
                      <TableCell>{entry.sub_tgid_dec} / {entry.sub_tgid_hex}</TableCell>
                    )}
                    {isSmartnet && <TableCell>{entry.mode}</TableCell>}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Collapse>
    </Paper>
  );
}
