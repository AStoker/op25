import { useCallback, useEffect, useMemo, useState, forwardRef } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import type { TableComponents } from 'react-virtuoso';

type SortKey = keyof TalkGroupRow;
type SortDirection = 'asc' | 'desc';

/** Comparators per column. Everything sortable is either a number, a string or a
 *  boolean, and `lastSeen` is now a number — it used to be a preformatted string,
 *  so the column string-compared values like `"  Now"` against `" 4.1s"`. */
function compare(a: TalkGroupRow, b: TalkGroupRow, key: SortKey): number {
  const aVal = a[key];
  const bVal = b[key];
  if (aVal == null && bVal == null) return 0;
  if (aVal == null) return -1;
  if (bVal == null) return 1;
  if (typeof aVal === 'number' && typeof bVal === 'number') return aVal - bVal;
  if (typeof aVal === 'boolean' && typeof bVal === 'boolean') {
    return Number(aVal) - Number(bVal);
  }
  return String(aVal).localeCompare(String(bVal));
}

function sortRows(
  rows: TalkGroupRow[],
  sortKey: SortKey,
  direction: SortDirection,
  pinned: ReadonlySet<number>,
): TalkGroupRow[] {
  const sign = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    // Focused talkgroups float above the sort so the ones being watched stop
    // drifting out of view as traffic reorders everything else.
    if (pinned.size > 0) {
      const pa = pinned.has(a.tgid) ? 0 : 1;
      const pb = pinned.has(b.tgid) ? 0 : 1;
      if (pa !== pb) return pa - pb;
    }
    const primary = sign * compare(a, b, sortKey);
    // Tie-break on tgid so equal values (every never-heard row shares
    // lastSeen 0) keep a stable order instead of shuffling on each update.
    return primary !== 0 ? primary : a.tgid - b.tgid;
  });
}
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import Switch from '@mui/material/Switch';
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
import PushPinIcon from '@mui/icons-material/PushPin';
import PushPinOutlinedIcon from '@mui/icons-material/PushPinOutlined';
import TuneIcon from '@mui/icons-material/Tune';
import CardShell from '../CardShell/CardShell';
import ControlRow from '../common/ControlRow';
import Field from '../common/Field';
import Hint from '../common/Hint';
import InsetPanel from '../common/InsetPanel';
import SearchField from '../common/SearchField';
import SectionHeading from '../common/SectionHeading';
import TalkgroupBrowser from '../TalkgroupBrowser/TalkgroupBrowser';
import { useIsPhone } from '../../hooks/useIsPhone';
import { useSmartColor } from '../../hooks/useSmartColor';
import { useTalkgroupFocus } from '../../hooks/useTalkgroupFocus';
import { formatFreqMHz, formatLastSeen, formatLastSeenExact } from '../../utils/lastSeen';
import { useOp25Service, useSelectedSystem } from '../../services/op25Service';

interface TalkGroupRow {
  tgid: number;
  tag: string;
  configured: boolean;
  seen: boolean;
  lastFreq?: number | null;
  /** Epoch seconds of last activity; 0 when never heard.
   *
   *  From `tgid_tags[tgid].last_seen`, which is per-talkgroup and durable — the
   *  server merges in values from previous decoder runs. This column used to read
   *  `frequency_data[freq].last_activity`, a per-*frequency* preformatted string
   *  that only lists a talkgroup while its call is up (one second), so it could
   *  only ever show "Now" or nothing at all. Same root cause as `lastFreq`. */
  lastSeen: number;
  /** Trunk priority for mid-call preemption; lower wins, 3 is the default. */
  prio?: number;
  /** Lifetime call count, across decoder restarts. */
  count?: number;
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
  const [browserOpen, setBrowserOpen] = useState(false);
  const phone = useIsPhone();
  const {
    config,
    channels, channelIds,
    selectedChannelId, selectChannel,
    holdTalkGroup, releaseHold,
    lockoutTalkGroup, whitelistTalkGroup,
    setScanList, scanWhitelist, scanBlacklist,
  } = useOp25Service();
  const system = useSelectedSystem();
  const tint = useSmartColor();
  const focus = useTalkgroupFocus();

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

  // Aggregate talk-groups from tgid_tags (the authoritative per-talkgroup record)
  // and the channels currently demodulating one.
  const rows = useMemo<TalkGroupRow[]>(() => {
    const map = new Map<number, TalkGroupRow>();

    // tgid_tags carries every talkgroup the decoder knows — seen on air or loaded
    // from tgid_tags_file — with its own last_seen / last_freq / count. This is
    // the only source for those; frequency_data cannot supply them because it
    // drops a talkgroup one second after its call ends.
    if (system?.tgid_tags) {
      for (const [tgidStr, tgData] of Object.entries(system.tgid_tags)) {
        const tgid = Number(tgidStr);
        if (!Number.isFinite(tgid) || tgid <= 0) continue;
        const lastSeen = Number(tgData.last_seen) || 0;
        map.set(tgid, {
          tgid,
          tag: tgData.tag || '',
          configured: Boolean(tgData.configured),
          seen: lastSeen > 0,
          lastFreq: tgData.last_freq ?? undefined,
          lastSeen,
          prio: tgData.prio,
          count: tgData.count,
        });
      }
    }

    // A channel demodulating right now is more current than the 1 Hz trunk
    // snapshot, so let it override.
    for (const ch of Object.values(channels)) {
      if (!ch.tgid || ch.tgid <= 0) continue;
      const existing = map.get(ch.tgid);
      const nowSecs = Date.now() / 1000;
      if (existing) {
        if (ch.tag && !existing.tag) existing.tag = ch.tag;
        if (ch.freq) existing.lastFreq = ch.freq;
        existing.lastSeen = Math.max(existing.lastSeen, nowSecs);
        existing.seen = true;
      } else {
        map.set(ch.tgid, {
          tgid: ch.tgid,
          tag: ch.tag || '',
          configured: false,
          seen: true,
          lastFreq: ch.freq,
          lastSeen: nowSecs,
        });
      }
    }

    let arr = Array.from(map.values());
    if (focus.focusOnly) {
      arr = arr.filter((row) => focus.focused.has(row.tgid));
    }
    if (tagFilter.trim()) {
      // Matches the TGID too: typing a number you half-remember is at least as
      // common as typing part of a tag.
      const filter = tagFilter.trim().toLowerCase();
      arr = arr.filter((row) => row.tag.toLowerCase().includes(filter)
        || String(row.tgid).includes(filter));
    }
    return sortRows(arr, sortKey, sortDirection, focus.focusOnly ? new Set() : focus.focused);
  }, [system, channels, tagFilter, sortKey, sortDirection, focus.focused, focus.focusOnly]);

  // Re-render on a slow tick so the relative ages in the Last column advance even
  // while the decoder is quiet. One second would be wasted work for a column that
  // reads in whole seconds and then whole minutes.
  const [, setAgeTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setAgeTick((n) => n + 1), 5_000);
    return () => clearInterval(id);
  }, []);

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
      {sortableHead('tag',  'Tag',  phone ? '38%' : '24%')}
      {!phone && sortableHead('prio',     'Prio', '7%')}
      {!phone && sortableHead('lastFreq', 'Freq', '13%')}
      {!phone && sortableHead('lastSeen', 'Last', '11%')}
      {!phone && sortableHead('count',    'Calls', '8%')}
      {sortableHead('configured', 'State', phone ? '20%' : '12%')}
      <TableCell variant="head" align="right" sx={{ backgroundColor: 'background.paper', width: phone ? '22%' : '15%' }}>Actions</TableCell>
    </TableRow>
  );

  const rowContent = (_index: number, row: TalkGroupRow) => {
    const isHeld = row.tgid === heldTgid;
    const isPinned = focus.focused.has(row.tgid);
    const isLockedOut = scanBlacklist.includes(row.tgid);
    const isScanned = scanWhitelist === null || scanWhitelist.includes(row.tgid);
    return (
      <>
        <TableCell>{row.tgid}</TableCell>
        <TableCell sx={{ overflowWrap: 'anywhere', color: tint(row.tag) }}>
          {row.tag || '\u2014'}
        </TableCell>
        {!phone && <TableCell>{row.prio ?? '\u2014'}</TableCell>}
        {!phone && <TableCell>{formatFreqMHz(row.lastFreq)}</TableCell>}
        {!phone && (
          <TableCell>
            <Tooltip title={formatLastSeenExact(row.lastSeen)}>
              <span>{formatLastSeen(row.lastSeen)}</span>
            </Tooltip>
          </TableCell>
        )}
        {!phone && <TableCell>{row.count || '\u2014'}</TableCell>}
        <TableCell>
          <Stack direction="row" spacing={0.5}>
            {row.configured &&
            <Tooltip title="This talk-group is configured in tgid_tags_file on the server">
              <Chip label="cfg" variant="outlined" />
            </Tooltip>
            }
            {row.seen &&
            <Tooltip title="This talk-group has been heard on the air">
              <Chip label="seen" color="success" variant="outlined" />
            </Tooltip>
            }
            {isLockedOut &&
            <Tooltip title="Locked out \u2014 the decoder will not tune this talk-group">
              <Chip label="lockout" color="error" variant="outlined" />
            </Tooltip>
            }
            {!isScanned && !isLockedOut &&
            <Tooltip title="Not in the active scan list, so it is not being received">
              <Chip label="off-list" variant="outlined" />
            </Tooltip>
            }
          </Stack>
        </TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
          {/* Three icon buttons do not fit a phone's Actions column — the third
              gets clipped — so below sm the pin moves into the overflow menu. */}
          {!phone && (
            <Tooltip title={isPinned ? 'Unpin' : 'Pin to top'}>
              <IconButton
                size="small"
                onClick={() => focus.toggle(row.tgid)}
                color={isPinned ? 'primary' : 'default'}
                aria-label={isPinned ? `unpin ${row.tgid}` : `pin ${row.tgid}`}
              >
                {isPinned
                  ? <PushPinIcon fontSize="small" />
                  : <PushPinOutlinedIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
          )}
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
        <Field label="Active channel" sx={{ maxWidth: { sm: 360 } }}>
          {channelIds.length > 0 ? (
            <Select
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
        </Field>

        {/* Configured channels (from richland-single.json style config) */}
        {config?.channels?.length ? (
          <Box>
            <SectionHeading title="Configured channels" />
            <Stack spacing={0.5}>
              {config.channels.map((c) => (
                <InsetPanel
                  key={c.name}
                  sx={{
                    display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center', gap: 1,
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight="medium">{c.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {c.trunking_sysname} · {c.demod_type} · {c.device}
                    </Typography>
                  </Box>
                  <Chip
                    label={c.enable_analog === 'on' ? 'analog' : 'digital'}
                    variant="outlined"
                  />
                </InsetPanel>
              ))}
            </Stack>
          </Box>
        ) : null}

        <Divider />

        {/* Talkgroup table */}
        <Box>
          <SectionHeading
            title="Talk Groups"
            meta={
              <>
                <span>{rows.length} shown</span>
                {focus.focused.size > 0 && (
                  <Chip
                    icon={<PushPinIcon />}
                    label={`${focus.focused.size} pinned`}
                    onDelete={focus.clear}
                    variant="outlined"
                  />
                )}
                {scanWhitelist !== null && (
                  <Tooltip title="Only these talk-groups are being received. Everything else is ignored, including for recording and transcription.">
                    <Chip
                      color="info"
                      label={`Scan list: ${scanWhitelist.length}`}
                      onDelete={() => setScanList('whitelist', [])}
                      variant="outlined"
                    />
                  </Tooltip>
                )}
                {heldTgid > 0 && (
                  <Chip
                    color="warning"
                    icon={<LockIcon />}
                    label={`Hold ${heldTgid}`}
                    onDelete={releaseHold}
                    deleteIcon={<LockOpenIcon />}
                  />
                )}
              </>
            }
            action={
              <ControlRow>
                <SearchField
                  value={tagFilter}
                  onChange={setTagFilter}
                  placeholder="Filter tag or TGID"
                  ariaLabel="filter talkgroups"
                />
                <Tooltip title="Browse and batch-select from every configured talk-group">
                  <Button
                    variant="outlined"
                    startIcon={<TuneIcon />}
                    onClick={() => setBrowserOpen(true)}
                  >
                    Browse
                  </Button>
                </Tooltip>
              </ControlRow>
            }
          />

          {/* Act on a TGID that is not in the table yet — the curses terminal's
              H / W / B prompts, which had no browser equivalent. The input is
              unlabelled and exactly as tall as the buttons, so the whole action
              reads as one row. */}
          <Box sx={{ mb: 1 }}>
            <ControlRow>
              <TextField
                value={manualTgid}
                onChange={(e) => setManualTgid(e.target.value.replace(/[^0-9]/g, ''))}
                error={manualTgid !== '' && !manualTgidValid}
                placeholder="TGID"
                slotProps={{
                  htmlInput: {
                    inputMode: 'numeric',
                    maxLength: 5,
                    'aria-label': 'talkgroup id',
                  },
                }}
                sx={{ width: 92 }}
              />
              <Button
                variant="outlined"
                disabled={!manualTgidValid}
                onClick={() => { holdTalkGroup(manualTgidValue); setManualTgid(''); }}
              >
                Hold
              </Button>
              <Button
                variant="outlined"
                disabled={!manualTgidValid}
                onClick={() => { whitelistTalkGroup(manualTgidValue); setManualTgid(''); }}
              >
                Whitelist
              </Button>
              <Button
                variant="outlined"
                color="error"
                disabled={!manualTgidValid}
                onClick={() => { lockoutTalkGroup(manualTgidValue); setManualTgid(''); }}
              >
                Lockout
              </Button>
            </ControlRow>
            {/* Under the row, not inside the field: helper text on the input
                would make it taller than the buttons whether or not it says
                anything. */}
            <Hint error={manualTgid !== '' && !manualTgidValid}>
              {manualTgid !== '' && !manualTgidValid
                ? 'TGID must be between 1 and 65534.'
                : 'Act on a talkgroup before it appears in the table.'}
            </Hint>
          </Box>

          {focus.focused.size > 0 && (
            <FormControlLabel
              control={
                <Switch
                  checked={focus.focusOnly}
                  onChange={(e) => focus.setFocusOnly(e.target.checked)}
                />
              }
              label={`Show only pinned (${focus.focused.size})`}
              sx={{ mb: 0.5 }}
            />
          )}
          {rows.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {tagFilter.trim() || focus.focusOnly
                ? 'Nothing matches the current filter.'
                : 'No talk-groups seen yet.'}
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

      <TalkgroupBrowser
        open={browserOpen}
        onClose={() => setBrowserOpen(false)}
        focus={focus}
      />

      <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={closeMenu}>
        {phone && (
          <MenuItem onClick={() => { focus.toggle(menuTgid); closeMenu(); }}>
            <ListItemIcon>
              {focus.focused.has(menuTgid)
                ? <PushPinIcon fontSize="small" color="primary" />
                : <PushPinOutlinedIcon fontSize="small" />}
            </ListItemIcon>
            <ListItemText
              primary={focus.focused.has(menuTgid) ? `Unpin ${menuTgid}` : `Pin ${menuTgid}`}
              secondary="Keeps it at the top of the table"
            />
          </MenuItem>
        )}
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
