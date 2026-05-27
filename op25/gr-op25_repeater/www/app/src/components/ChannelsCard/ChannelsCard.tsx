import { useMemo, useState, forwardRef } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import type { TableComponents } from 'react-virtuoso';
// Sorting helpers
type SortKey = keyof TalkGroupRow;
type SortDirection = 'asc' | 'desc';

function sortRows(rows: TalkGroupRow[], sortKey: SortKey, direction: SortDirection): TalkGroupRow[] {
  return [...rows].sort((a, b) => {
    let aVal = a[sortKey];
    let bVal = b[sortKey];
    // For undefined/null, treat as smallest
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return direction === 'asc' ? -1 : 1;
    if (bVal == null) return direction === 'asc' ? 1 : -1;
    // Numeric sort for tgid, lastFreq
    if (sortKey === 'tgid' || sortKey === 'lastFreq') {
      return direction === 'asc' ? (Number(aVal) - Number(bVal)) : (Number(bVal) - Number(aVal));
    }
    // Date/time sort for lastActivity (string)
    if (sortKey === 'lastActivity') {
      return direction === 'asc'
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal));
    }
    // String sort for tag
    if (sortKey === 'tag') {
      return direction === 'asc'
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal));
    }
    // Boolean sort for configured/seen
    if (sortKey === 'configured' || sortKey === 'seen') {
      return direction === 'asc'
        ? (Number(Boolean(aVal)) - Number(Boolean(bVal)))
        : (Number(Boolean(bVal)) - Number(Boolean(aVal)));
    }
    return 0;
  });
}
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
import TextField from '@mui/material/TextField';
import TableContainer from '@mui/material/TableContainer';
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

interface ChannelsContext {
  heldTgid: number;
  holdTalkGroup: (tgid: number) => void;
  releaseHold: () => void;
}

const VirtuosoTableComponents: TableComponents<TalkGroupRow, ChannelsContext> = {
  Scroller: forwardRef<HTMLDivElement>((props, ref) => (
    <TableContainer {...props} ref={ref} />
  )),
  Table: (props) => <Table size="small" sx={{ tableLayout: 'fixed' }} {...props} />,
  TableHead: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableHead {...props} ref={ref} />
  )),
  TableRow: ({ item, context, ...props }) => (
    <TableRow hover selected={item?.tgid === context?.heldTgid} {...props} />
  ),
  TableBody: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableBody {...props} ref={ref} />
  )),
};

export default function ChannelsCard() {
  // Sorting state
  const [sortKey, setSortKey] = useState<SortKey>('configured');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  // Filter state
  const [tagFilter, setTagFilter] = useState('');
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

    // Configured talk-groups from tgid_tags (populated by tgid_tags_file on the server).
    if (system?.tgid_tags) {
      for (const [tgidStr, tgData] of Object.entries(system.tgid_tags)) {
        if (!tgData.configured) continue;
        const tgid = Number(tgidStr);
        if (!Number.isFinite(tgid) || tgid <= 0) continue;
        const existing = map.get(tgid);
        if (existing) {
          existing.configured = true;
          if (tgData.tag && !existing.tag) existing.tag = tgData.tag;
        } else {
          map.set(tgid, { tgid, tag: tgData.tag || '', configured: true, seen: false });
        }
      }
    }

    let arr = Array.from(map.values());
    // Filter by tag
    if (tagFilter.trim()) {
      const filter = tagFilter.trim().toLowerCase();
      arr = arr.filter(row => row.tag.toLowerCase().includes(filter));
    }
    // Sort
    arr = sortRows(arr, sortKey, sortDirection);
    return arr;
  }, [system, channels, tagFilter, sortKey, sortDirection]);

  const fixedHeaderContent = () => (
    <TableRow>
      <TableCell
        variant="head"
        onClick={() => { setSortKey('tgid'); setSortDirection(sortKey === 'tgid' && sortDirection === 'asc' ? 'desc' : 'asc'); }}
        sx={{ cursor: 'pointer', userSelect: 'none', backgroundColor: 'background.paper', width: '10%' }}
      >
        TGID {sortKey === 'tgid' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
      </TableCell>
      <TableCell
        variant="head"
        onClick={() => { setSortKey('tag'); setSortDirection(sortKey === 'tag' && sortDirection === 'asc' ? 'desc' : 'asc'); }}
        sx={{ cursor: 'pointer', userSelect: 'none', backgroundColor: 'background.paper', width: '30%' }}
      >
        Tag {sortKey === 'tag' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
      </TableCell>
      <TableCell
        variant="head"
        onClick={() => { setSortKey('lastFreq'); setSortDirection(sortKey === 'lastFreq' && sortDirection === 'asc' ? 'desc' : 'asc'); }}
        sx={{ cursor: 'pointer', userSelect: 'none', backgroundColor: 'background.paper', width: '14%' }}
      >
        Freq {sortKey === 'lastFreq' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
      </TableCell>
      <TableCell
        variant="head"
        onClick={() => { setSortKey('lastActivity'); setSortDirection(sortKey === 'lastActivity' && sortDirection === 'asc' ? 'desc' : 'asc'); }}
        sx={{ cursor: 'pointer', userSelect: 'none', backgroundColor: 'background.paper', width: '18%' }}
      >
        Last {sortKey === 'lastActivity' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
      </TableCell>
      <TableCell
        variant="head"
        onClick={() => { setSortKey('configured'); setSortDirection(sortKey === 'configured' && sortDirection === 'asc' ? 'desc' : 'asc'); }}
        sx={{ cursor: 'pointer', userSelect: 'none', backgroundColor: 'background.paper', width: '20%' }}
      >
        State {sortKey === 'configured' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
      </TableCell>
      <TableCell variant="head" align="right" sx={{ backgroundColor: 'background.paper', width: '8%' }}>Hold</TableCell>
    </TableRow>
  );

  const rowContent = (_index: number, row: TalkGroupRow) => {
    const isHeld = row.tgid === heldTgid;
    return (
      <>
        <TableCell>{row.tgid}</TableCell>
        <TableCell>{row.tag || '\u2014'}</TableCell>
        <TableCell>{formatFreqMHz(row.lastFreq)}</TableCell>
        <TableCell>{row.lastActivity?.trim() ?? ''}</TableCell>
        <TableCell>
          <Stack direction="row" spacing={0.5}>
            {row.configured && 
            <Tooltip title="This talk-group is configured in tgid_tags_file on the server">
              <Chip size="small" label="cfg" variant="outlined" />
            </Tooltip>
            }
            {row.seen       && 
            <Tooltip title="This talk-group has been seen active on the air (from frequency_data updates)">
              <Chip size="small" label="seen" color="success" variant="outlined" />
            </Tooltip>
            }
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
      </>
    );
  };

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
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.75, gap: 1, flexWrap: 'wrap' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
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
                />
              )}
            </Box>
            <TextField
              size="small"
              label="Filter tag"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder="Type to filter..."
              sx={{ width: 240 }}
            />
          </Box>
          {rows.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No talk-groups seen yet.
            </Typography>
          ) : (
            <Box sx={{ height: 360 }}>
              <TableVirtuoso
                data={rows}
                context={{ heldTgid, holdTalkGroup, releaseHold }}
                components={VirtuosoTableComponents}
                fixedHeaderContent={fixedHeaderContent}
                itemContent={rowContent}
              />
            </Box>
          )}
        </Box>
      </Stack>
    </CardShell>
  );
}
