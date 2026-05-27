import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Tooltip from '@mui/material/Tooltip';
import LockIcon from '@mui/icons-material/Lock';
import LockOpenIcon from '@mui/icons-material/LockOpen';
import CardShell from '../CardShell/CardShell';
import { useOp25Service, useSelectedSystem } from '../../services/op25Service';

interface TalkGroupRow {
  tgid: number;
  tag: string;
  configured: boolean;
  seen: boolean;
  lastFreq?: number;
  lastActivity?: string;
}

function formatFreqMHz(hz?: number): string {
  if (!hz || !Number.isFinite(hz)) return '—';
  return `${(hz / 1e6).toFixed(4)}`;
}

export default function ChannelsCard() {
  const {
    config,
    channels, channelIds,
    selectedChannelId, selectChannel,
    holdTalkGroup, releaseHold,
  } = useOp25Service();
  const system = useSelectedSystem();

  const activeChannel = selectedChannelId !== null ? channels[selectedChannelId] : null;
  const heldTgid = activeChannel?.hold_tgid ?? 0;

  // Aggregate talk-groups from frequency_data (seen) and channels (active).
  const rows = useMemo<TalkGroupRow[]>(() => {
    const map = new Map<number, TalkGroupRow>();

    // Seen talk-groups from the trunk frequency_data.
    if (system?.frequency_data) {
      for (const [freqStr, data] of Object.entries(system.frequency_data)) {
        const freq = Number(freqStr);
        for (let i = 0; i < data.tgids.length; i++) {
          const tgid = Number(data.tgids[i]);
          if (!Number.isFinite(tgid) || tgid <= 0) continue;
          const tag = data.tags[i] || '';
          const existing = map.get(tgid);
          if (existing) {
            if (tag && !existing.tag) existing.tag = tag;
            existing.lastFreq = freq;
            existing.lastActivity = data.last_activity;
          } else {
            map.set(tgid, {
              tgid, tag,
              configured: false,
              seen: true,
              lastFreq: freq,
              lastActivity: data.last_activity,
            });
          }
        }
      }
    }

    // Channels currently demodulating a TG.
    for (const ch of Object.values(channels)) {
      if (ch.tgid && ch.tgid > 0) {
        const existing = map.get(ch.tgid);
        if (existing) {
          if (ch.tag && !existing.tag) existing.tag = ch.tag;
          existing.lastFreq = ch.freq;
          existing.seen = true;
        } else {
          map.set(ch.tgid, {
            tgid: ch.tgid,
            tag:  ch.tag || '',
            configured: false,
            seen: true,
            lastFreq: ch.freq,
          });
        }
      }
    }

    // TODO: when the server exposes the parsed tgid_tags_file we can mark
    // configured talk-groups here.  For now flag any TG that appears in the
    // trunking config's whitelist as configured.
    const whitelist = config?.trunking?.chans?.[0]?.whitelist;
    if (whitelist) {
      for (const tok of whitelist.split(/[,\s]+/).filter(Boolean)) {
        const tgid = Number(tok);
        if (!Number.isFinite(tgid)) continue;
        const existing = map.get(tgid);
        if (existing) existing.configured = true;
        else map.set(tgid, { tgid, tag: '', configured: true, seen: false });
      }
    }

    return Array.from(map.values()).sort((a, b) => a.tgid - b.tgid);
  }, [system, channels, config]);

  return (
    <CardShell title="Channels / Talkgroups">
      <Stack spacing={2}>
        {/* Channel selector */}
        <Box>
          <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
            Active channel
          </Typography>
          {channelIds.length > 0 ? (
            <Select
              size="small"
              value={selectedChannelId ?? ''}
              onChange={(e) => selectChannel(String(e.target.value))}
              fullWidth
            >
              {channelIds.map((id) => {
                const ch = channels[id];
                const label = ch?.name || `Channel ${id}`;
                return (
                  <MenuItem key={id} value={id}>
                    {label}
                    {ch?.tgid ? ` — ${ch.tag || ch.tgid}` : ''}
                  </MenuItem>
                );
              })}
            </Select>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No channels reported yet
            </Typography>
          )}
        </Box>

        {/* Configured channels (from richland-single.json style config) */}
        {config?.channels?.length ? (
          <Box>
            <Typography variant="subtitle2" gutterBottom>Configured channels</Typography>
            <Stack spacing={0.5}>
              {config.channels.map((c) => (
                <Box
                  key={c.name}
                  sx={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    border: 1, borderColor: 'divider', borderRadius: 1, p: 0.75, gap: 1,
                  }}
                >
                  <Box>
                    <Typography variant="body2" fontWeight="medium">{c.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {c.trunking_sysname} · {c.demod_type} · {c.device}
                    </Typography>
                  </Box>
                  <Chip
                    size="small"
                    label={c.enable_analog === 'on' ? 'analog' : 'digital'}
                    variant="outlined"
                  />
                </Box>
              ))}
            </Stack>
          </Box>
        ) : null}

        <Divider />

        {/* Talkgroup table */}
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5, gap: 1 }}>
            <Typography variant="subtitle2">Talk Groups</Typography>
            <Typography variant="caption" color="text.secondary">
              {rows.length} known
            </Typography>
            {heldTgid > 0 && (
              <Chip
                size="small"
                color="warning"
                icon={<LockIcon sx={{ fontSize: '0.9rem' }} />}
                label={`Hold ${heldTgid}`}
                onDelete={releaseHold}
                deleteIcon={<LockOpenIcon />}
                sx={{ ml: 'auto' }}
              />
            )}
          </Box>
          {rows.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No talk-groups seen yet.
            </Typography>
          ) : (
            <Box sx={{ maxHeight: 360, overflow: 'auto' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>TGID</TableCell>
                    <TableCell>Tag</TableCell>
                    <TableCell>Freq</TableCell>
                    <TableCell>Last</TableCell>
                    <TableCell>State</TableCell>
                    <TableCell align="right">Hold</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => {
                    const isHeld = row.tgid === heldTgid;
                    return (
                      <TableRow key={row.tgid} hover selected={isHeld}>
                        <TableCell>{row.tgid}</TableCell>
                        <TableCell>{row.tag || '—'}</TableCell>
                        <TableCell>{formatFreqMHz(row.lastFreq)}</TableCell>
                        <TableCell>{row.lastActivity?.trim() ?? ''}</TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={0.5}>
                            {row.configured && <Chip size="small" label="cfg" variant="outlined" />}
                            {row.seen       && <Chip size="small" label="seen" color="success" variant="outlined" />}
                          </Stack>
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip title={isHeld ? 'Release hold' : `Hold ${row.tgid}`}>
                            <IconButton
                              size="small"
                              onClick={() => (isHeld ? releaseHold() : holdTalkGroup(row.tgid))}
                              color={isHeld ? 'warning' : 'default'}
                            >
                              {isHeld ? <LockOpenIcon fontSize="small" /> : <LockIcon fontSize="small" />}
                            </IconButton>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          )}
        </Box>
      </Stack>
    </CardShell>
  );
}
