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
    // Numeric sort for tgid, lastFreq, prio
    if (sortKey === 'tgid' || sortKey === 'lastFreq' || sortKey === 'prio') {
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
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
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
import BlockIcon from '@mui/icons-material/Block';
import LockIcon from '@mui/icons-material/Lock';
import LockOpenIcon from '@mui/icons-material/LockOpen';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck';
import CardShell from '../CardShell/CardShell';
import { useIsPhone } from '../../hooks/useIsPhone';
import { useSmartColor } from '../../hooks/useSmartColor';
import { useOp25Service, useSelectedSystem } from '../../services/op25Service';

interface TalkGroupRow {
  tgid: number;
  tag: string;
  configured: boolean;
  seen: boolean;
  lastFreq?: number;
  lastActivity?: string;
  /** Trunk priority for mid-call preemption; lower wins, 3 is the default. */
  prio?: number;
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
  // Row overflow menu (one Menu instance, re-anchored per row — a virtualized
  // table must not mount a Menu per row).
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [menuTgid, setMenuTgid] = useState<number>(0);
  // Manual TGID entry, mirroring the curses H / W / B prompts.
  const [manualTgid, setManualTgid] = useState('');
  const phone = useIsPhone();
  const {
    config,
    channels, channelIds,
    selectedChannelId, selectChannel,
    holdTalkGroup, releaseHold,
    lockoutTalkGroup, whitelistTalkGroup,
  } = useOp25Service();
  const system = useSelectedSystem();
  const tint = useSmartColor();

  const closeMenu = () => setMenuAnchor(null);
  const openMenu = (el: HTMLElement, tgid: number) => {
    setMenuTgid(tgid);
    setMenuAnchor(el);
  };

  // The decoder rejects anything outside 1-65534 (add_blacklist/add_whitelist),
  // so screen it here rather than sending a command that only logs a warning.
  const manualTgidValue = Number(manualTgid);
  const manualTgidValid = Number.isInteger(manualTgidValue)
    && manualTgidValue > 0 && manualTgidValue <= 65534;

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

    // Talk-groups the decoder knows about (tgid_tags carries every TG it has
    // seen or loaded from tgid_tags_file, plus the trunk priority).
    if (system?.tgid_tags) {
      for (const [tgidStr, tgData] of Object.entries(system.tgid_tags)) {
        const tgid = Number(tgidStr);
        if (!Number.isFinite(tgid) || tgid <= 0) continue;
        const existing = map.get(tgid);
        if (existing) {
          if (tgData.configured) existing.configured = true;
          if (tgData.tag && !existing.tag) existing.tag = tgData.tag;
          if (tgData.prio !== undefined) existing.prio = tgData.prio;
        } else if (tgData.configured) {
          map.set(tgid, {
            tgid,
            tag: tgData.tag || '',
            configured: true,
            seen: false,
            prio: tgData.prio,
          });
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

  // Column set differs by viewport: on a phone the frequency and
  // last-activity columns are dropped so TGID, tag and the hold control —
  // the three that are actually actionable — keep readable widths.
  const sortableHead = (key: SortKey, label: string, width: string) => (
    <TableCell
      variant="head"
      onClick={() => { setSortKey(key); setSortDirection(sortKey === key && sortDirection === 'asc' ? 'desc' : 'asc'); }}
      sx={{ cursor: 'pointer', userSelect: 'none', backgroundColor: 'background.paper', width }}
    >
      {label} {sortKey === key ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
    </TableCell>
  );

  const fixedHeaderContent = () => (
    <TableRow>
      {sortableHead('tgid', 'TGID', phone ? '20%' : '10%')}
      {sortableHead('tag',  'Tag',  phone ? '40%' : '26%')}
      {!phone && sortableHead('prio',         'Prio', '8%')}
      {!phone && sortableHead('lastFreq',     'Freq', '13%')}
      {!phone && sortableHead('lastActivity', 'Last', '16%')}
      {sortableHead('configured', 'State', phone ? '20%' : '15%')}
      <TableCell variant="head" align="right" sx={{ backgroundColor: 'background.paper', width: phone ? '20%' : '12%' }}>Actions</TableCell>
    </TableRow>
  );

  const rowContent = (_index: number, row: TalkGroupRow) => {
    const isHeld = row.tgid === heldTgid;
    return (
      <>
        <TableCell>{row.tgid}</TableCell>
        <TableCell sx={{ overflowWrap: 'anywhere', color: tint(row.tag) }}>
          {row.tag || '\u2014'}
        </TableCell>
        {!phone && <TableCell>{row.prio ?? '\u2014'}</TableCell>}
        {!phone && <TableCell>{formatFreqMHz(row.lastFreq)}</TableCell>}
        {!phone && <TableCell>{row.lastActivity?.trim() ?? ''}</TableCell>}
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
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
          <Tooltip title={isHeld ? 'Release hold' : `Hold ${row.tgid}`}>
            <IconButton
              size="small"
              onClick={() => (isHeld ? releaseHold() : holdTalkGroup(row.tgid))}
              color={isHeld ? 'warning' : 'default'}
            >
              {isHeld ? <LockOpenIcon fontSize="small" /> : <LockIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
          <Tooltip title="More actions">
            <IconButton size="small" onClick={(e) => openMenu(e.currentTarget, row.tgid)}>
              <MoreVertIcon fontSize="small" />
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
              sx={{ width: { xs: '100%', sm: 240 } }}
            />
          </Box>

          {/* Act on a TGID that is not in the table yet — the curses terminal's
              H / W / B prompts, which had no browser equivalent. */}
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            flexWrap="wrap"
            useFlexGap
            sx={{ mb: 1 }}
          >
            <TextField
              size="small"
              label="TGID"
              value={manualTgid}
              onChange={(e) => setManualTgid(e.target.value.replace(/[^0-9]/g, ''))}
              error={manualTgid !== '' && !manualTgidValid}
              helperText={manualTgid !== '' && !manualTgidValid ? '1–65534' : ' '}
              inputProps={{ inputMode: 'numeric', 'aria-label': 'talkgroup id' }}
              sx={{ width: 120 }}
            />
            <Button
              size="small"
              variant="outlined"
              disabled={!manualTgidValid}
              onClick={() => { holdTalkGroup(manualTgidValue); setManualTgid(''); }}
            >
              Hold
            </Button>
            <Button
              size="small"
              variant="outlined"
              disabled={!manualTgidValid}
              onClick={() => { whitelistTalkGroup(manualTgidValue); setManualTgid(''); }}
            >
              Whitelist
            </Button>
            <Button
              size="small"
              variant="outlined"
              color="error"
              disabled={!manualTgidValid}
              onClick={() => { lockoutTalkGroup(manualTgidValue); setManualTgid(''); }}
            >
              Lockout
            </Button>
          </Stack>
          {rows.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No talk-groups seen yet.
            </Typography>
          ) : (
            <Box sx={{ height: { xs: 320, sm: 360 } }}>
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

      <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={closeMenu}>
        <MenuItem
          onClick={() => { whitelistTalkGroup(menuTgid); closeMenu(); }}
        >
          <ListItemIcon><PlaylistAddCheckIcon fontSize="small" /></ListItemIcon>
          <ListItemText
            primary={`Whitelist ${menuTgid}`}
            secondary="Scan only whitelisted talk-groups"
          />
        </MenuItem>
        <MenuItem
          onClick={() => { lockoutTalkGroup(menuTgid); closeMenu(); }}
        >
          <ListItemIcon><BlockIcon fontSize="small" color="error" /></ListItemIcon>
          <ListItemText
            primary={`Lockout ${menuTgid}`}
            secondary="Blacklist until reload"
          />
        </MenuItem>
      </Menu>
    </CardShell>
  );
}
