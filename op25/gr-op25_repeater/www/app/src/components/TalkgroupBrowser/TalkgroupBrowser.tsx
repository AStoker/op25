import { useCallback, useDeferredValue, useEffect, useMemo, useState, forwardRef } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import type { TableComponents } from 'react-virtuoso';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import DialogShell from '../common/DialogShell';
import ControlRow from '../common/ControlRow';
import Hint from '../common/Hint';
import SearchField from '../common/SearchField';
import { useIsPhone } from '../../hooks/useIsPhone';
import { useSmartColor } from '../../hooks/useSmartColor';
import { useTalkgroupFilters } from '../../hooks/useTalkgroupFilters';
import type { TalkgroupFocus } from '../../hooks/useTalkgroupFocus';
import { formatFreqMHz, formatLastSeen, formatLastSeenExact } from '../../utils/lastSeen';
import {
  KIND_LABEL, PATTERN_KINDS, compileFilter, compilePattern, guessKind,
} from '../../utils/talkgroupPatterns';
import type { PatternKind, TalkgroupPattern } from '../../utils/talkgroupPatterns';
import { useOp25Service } from '../../services/op25Service';
import { apiUrl } from '../../utils/url';
import type { TalkgroupRecord } from '../../types/op25';

/**
 * Pick talkgroups out of the full configured list.
 *
 * The problem this solves: the dashboard's talkgroup table re-sorts and re-renders
 * as traffic comes and goes, so finding one specific talkgroup in a couple of
 * thousand means chasing a moving row. Here the list is frozen (loaded once when
 * the dialog opens), filtered by a *set* of patterns, sortable by any column, and
 * selectable in bulk — including "select everything the filter currently matches",
 * which is the point of the patterns.
 *
 * Two things make a talkgroup worth selecting, and the table answers both:
 * whether it is the one you were looking for (patterns) and whether it carries
 * any traffic (sort by Calls or Last heard, or hide the never-heard entirely).
 *
 * Two separate outputs, deliberately kept apart:
 *
 *  - the focus set, which pins and filters the *display*;
 *  - the decoder's scan list, applied only by an explicit button, because it
 *    genuinely stops other talkgroups being received, recorded and transcribed.
 */

interface TalkgroupBrowserProps {
  open: boolean;
  onClose: () => void;
  focus: TalkgroupFocus;
}

type Row = TalkgroupRecord & { configured: boolean; prio?: number };

type SortKey = 'tgid' | 'tag' | 'last_seen' | 'last_freq' | 'count';
type SortDirection = 'asc' | 'desc';

/** Which way a column reads first. "Most calls" and "most recent" are the
 *  questions being asked of the two numeric columns, so they open descending;
 *  an identifier reads ascending. */
const FIRST_DIRECTION: Record<SortKey, SortDirection> = {
  tgid: 'asc', tag: 'asc', last_seen: 'desc', last_freq: 'asc', count: 'desc',
};

function compare(a: Row, b: Row, key: SortKey): number {
  if (key === 'tag') return (a.tag || '').localeCompare(b.tag || '');
  const av = a[key] ?? 0;
  const bv = b[key] ?? 0;
  return Number(av) - Number(bv);
}

interface RowContext {
  focused: ReadonlySet<number>;
  toggle: (tgid: number) => void;
}

const VirtuosoTableComponents: TableComponents<Row, RowContext> = {
  Scroller: forwardRef<HTMLDivElement>((props, ref) => (
    <TableContainer {...props} ref={ref} />
  )),
  Table: (props) => <Table size="small" sx={{ tableLayout: 'fixed' }} {...props} />,
  TableHead: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableHead {...props} ref={ref} />
  )),
  TableRow: ({ item, context, ...props }) => (
    <TableRow hover selected={Boolean(item && context?.focused.has(item.tgid))} {...props} />
  ),
  TableBody: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableBody {...props} ref={ref} />
  )),
};

export default function TalkgroupBrowser({ open, onClose, focus }: TalkgroupBrowserProps) {
  const phone = useIsPhone();
  const tint = useSmartColor();
  const { systems, setScanList, scanWhitelist } = useOp25Service();
  const filters = useTalkgroupFilters();

  const [draft, setDraft] = useState('');
  const [draftKind, setDraftKind] = useState<PatternKind>('contains');
  // Once the user picks a kind by hand, stop second-guessing them. Before that,
  // typing `RCHP*` should land on Wildcard rather than silently matching nothing.
  const [kindPinned, setKindPinned] = useState(false);
  const [heardOnly, setHeardOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('count');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  // Filtering two thousand rows on every keystroke is what makes a live pattern
  // feel laggy; deferring it keeps the input itself responsive.
  const deferredDraft = useDeferredValue(draft);

  const setDraftText = useCallback((text: string) => {
    setDraft(text);
    if (!kindPinned) setDraftKind(guessKind(text));
  }, [kindPinned]);

  const commitDraft = useCallback(() => {
    if (!draft.trim()) return;
    filters.add({ kind: draftKind, text: draft });
    setDraft('');
    setKindPinned(false);
    setDraftKind('contains');
  }, [draft, draftKind, filters]);

  /** Pull a saved pattern back into the editor. Editing in place would need a
   *  second form; this is one click and the chip reappears on Add. */
  const editPattern = useCallback((index: number) => {
    const p = filters.patterns[index];
    setDraft(p.text);
    setDraftKind(p.kind);
    setKindPinned(true);
    filters.removeAt(index);
  }, [filters]);

  /**
   * The full list, loaded once per opening.
   *
   * From /api/talkgroups, not from the live trunk_update: that endpoint is the
   * durable view and includes talkgroups last heard in an earlier run, which is
   * exactly what a pick-list needs. `configured` and `prio` are not stored, so
   * they come from the live payload where available.
   */
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadError(null);
    setApplied(null);

    const live = new Map<number, { configured: boolean; prio?: number }>();
    for (const system of Object.values(systems)) {
      for (const [tgidStr, tg] of Object.entries(system.tgid_tags ?? {})) {
        const tgid = Number(tgidStr);
        if (Number.isFinite(tgid) && tgid > 0) {
          live.set(tgid, { configured: Boolean(tg.configured), prio: tg.prio });
        }
      }
    }

    (async () => {
      try {
        const res = await fetch(apiUrl('api/talkgroups'));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body: { talkgroups?: TalkgroupRecord[] } = await res.json();
        if (cancelled) return;
        const stored = body.talkgroups ?? [];
        const merged = new Map<number, Row>();
        for (const rec of stored) {
          merged.set(rec.tgid, { ...rec, ...(live.get(rec.tgid) ?? { configured: false }) });
        }
        // Talkgroups the decoder has configured but the store has never seen —
        // a first run against a fresh tgid_tags_file is entirely this case.
        for (const [tgid, extra] of live) {
          if (!merged.has(tgid)) {
            const tg = Object.values(systems)
              .map((s) => s.tgid_tags?.[String(tgid)])
              .find(Boolean);
            merged.set(tgid, {
              system: '', tgid, tag: tg?.tag ?? '',
              last_seen: 0, last_freq: null, count: 0, ...extra,
            });
          }
        }
        setRows([...merged.values()].sort((a, b) => a.tgid - b.tgid));
      } catch (e) {
        if (!cancelled) {
          setRows([]);
          setLoadError((e as Error).message);
        }
      }
    })();

    return () => { cancelled = true; };
    // systems is deliberately not a dependency: the list must not reshuffle
    // under the user while they are picking from it. That is the bug being fixed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /**
   * Saved patterns plus whatever is half-typed.
   *
   * The draft participates so the table previews what pressing Add would do.
   * Without it a pattern has to be committed before its effect is visible, and
   * the natural way to find out whether `RCHP*` is right is to watch the table
   * while typing it.
   */
  const active = useMemo<TalkgroupPattern[]>(() => (
    deferredDraft.trim()
      ? [...filters.patterns, { kind: draftKind, text: deferredDraft }]
      : filters.patterns
  ), [filters.patterns, deferredDraft, draftKind]);

  const compiled = useMemo(() => compileFilter(active), [active]);
  const draftError = useMemo(
    () => (deferredDraft.trim()
      ? compilePattern({ kind: draftKind, text: deferredDraft }).error
      : null),
    [deferredDraft, draftKind],
  );

  const heard = useMemo(
    () => (rows ?? []).filter((r) => !heardOnly || (r.count ?? 0) > 0 || (r.last_seen ?? 0) > 0),
    [rows, heardOnly],
  );

  const visible = useMemo(() => {
    const matched = heard.filter((r) => compiled.match(r.tag || '', r.tgid));
    const sign = sortDirection === 'asc' ? 1 : -1;
    // Selected rows are NOT floated to the top, unlike the dashboard's table:
    // ticking a checkbox would move the row out from under the pointer, and
    // this dialog exists to be ticked through.
    return matched.sort((a, b) => {
      const primary = sign * compare(a, b, sortKey);
      // Tie-break on tgid: every never-heard row shares count 0, and without
      // this they would shuffle whenever the list is recomputed.
      return primary !== 0 ? primary : a.tgid - b.tgid;
    });
  }, [heard, compiled, sortKey, sortDirection]);

  /** How many talkgroups each saved pattern accounts for. A chip that matches
   *  nothing is the single most common reason a search "does not work". */
  const patternCounts = useMemo(() => (
    compiled.tests.slice(0, filters.patterns.length).map((test) => (
      test === null ? null : heard.filter((r) => test(r.tag || '', r.tgid)).length
    ))
  ), [compiled.tests, filters.patterns.length, heard]);

  const visibleIds = useMemo(() => visible.map((r) => r.tgid), [visible]);
  const allVisibleFocused = visibleIds.length > 0
    && visibleIds.every((t) => focus.focused.has(t));

  const selectedRows = useMemo(
    () => (rows ?? []).filter((r) => focus.focused.has(r.tgid)),
    [rows, focus.focused],
  );

  const applyScanList = useCallback(() => {
    const tgids = [...focus.focused];
    setScanList('whitelist', tgids);
    setApplied(tgids.length === 0
      ? 'Scan list cleared — the decoder is scanning every talkgroup again.'
      : `Scan list applied: ${tgids.length} talkgroup${tgids.length === 1 ? '' : 's'}.`);
  }, [focus.focused, setScanList]);

  const clearScanList = useCallback(() => {
    setScanList('whitelist', []);
    setApplied('Scan list cleared — the decoder is scanning every talkgroup again.');
  }, [setScanList]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDirection(FIRST_DIRECTION[key]);
    }
  };

  const sortableHead = (key: SortKey, label: string, width: string,
                        align?: 'right', inset = false) => (
    <TableCell
      variant="head"
      align={align}
      onClick={() => onSort(key)}
      sx={{
        cursor: 'pointer', userSelect: 'none',
        backgroundColor: 'background.paper', width, pl: inset ? 1 : undefined,
      }}
      aria-sort={sortKey === key ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      {label} {sortKey === key ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
    </TableCell>
  );

  const fixedHeaderContent = () => (
    <TableRow>
      <TableCell
        variant="head"
        padding="checkbox"
        sx={{ backgroundColor: 'background.paper', width: 48 }}
      >
        <Tooltip title={allVisibleFocused ? 'Deselect all matches' : 'Select all matches'}>
          <Checkbox
            size="small"
            checked={allVisibleFocused}
            indeterminate={!allVisibleFocused && visibleIds.some((t) => focus.focused.has(t))}
            disabled={visibleIds.length === 0}
            onChange={() => (allVisibleFocused ? focus.remove(visibleIds) : focus.add(visibleIds))}
            inputProps={{ 'aria-label': 'select all matching talkgroups' }}
          />
        </Tooltip>
      </TableCell>
      {/* padding="checkbox" strips the neighbouring cell's inset, so on a
          phone the tick box and the id run into each other. */}
      {sortableHead('tgid', 'TGID', phone ? '22%' : '12%', undefined, phone)}
      {sortableHead('tag', 'Tag', phone ? 'auto' : '38%')}
      {!phone && sortableHead('last_seen', 'Last heard', '16%')}
      {!phone && sortableHead('last_freq', 'Freq', '16%')}
      {/* Calls survives on a phone where Freq does not: "is anyone using this
          talkgroup" is the question this dialog is for. */}
      {sortableHead('count', 'Calls', phone ? '20%' : '10%', 'right')}
    </TableRow>
  );

  const rowContent = (_i: number, row: Row) => (
    <>
      <TableCell padding="checkbox">
        <Checkbox
          size="small"
          checked={focus.focused.has(row.tgid)}
          onChange={() => focus.toggle(row.tgid)}
          inputProps={{ 'aria-label': `select talkgroup ${row.tgid}` }}
        />
      </TableCell>
      <TableCell sx={{ pl: phone ? 1 : undefined }}>{row.tgid}</TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere', color: tint(row.tag) }}>
        {row.tag || '—'}
      </TableCell>
      {!phone && (
        <TableCell>
          <Tooltip title={formatLastSeenExact(row.last_seen)}>
            <span>{formatLastSeen(row.last_seen)}</span>
          </Tooltip>
        </TableCell>
      )}
      {!phone && <TableCell>{formatFreqMHz(row.last_freq)}</TableCell>}
      <TableCell align="right">{row.count || '—'}</TableCell>
    </>
  );

  const heardCount = useMemo(
    () => (rows ?? []).filter((r) => (r.count ?? 0) > 0 || (r.last_seen ?? 0) > 0).length,
    [rows],
  );

  return (
    <DialogShell
      open={open}
      onClose={onClose}
      title="Talkgroup Browser"
      subheader={
        <Typography variant="caption" color="text.secondary">
          {rows === null ? 'Loading…' : `${visible.length} of ${rows.length} shown`}
          {rows !== null && ` · ${heardCount} ever heard`}
          {focus.focused.size > 0 && ` · ${focus.focused.size} selected`}
        </Typography>
      }
      actions={
        <Stack direction="row" spacing={1} sx={{ mr: 'auto' }} flexWrap="wrap" useFlexGap>
          <Button variant="outlined" onClick={applyScanList} disabled={focus.focused.size === 0}>
            Apply as scan list
          </Button>
          <Button variant="outlined" onClick={clearScanList} disabled={scanWhitelist === null}>
            Clear scan list
          </Button>
          <Button variant="outlined" onClick={focus.clear} disabled={focus.focused.size === 0}>
            Deselect all
          </Button>
        </Stack>
      }
    >
      <Stack spacing={1.5}>
        <ControlRow>
          <TextField
            select
            value={draftKind}
            onChange={(e) => { setDraftKind(e.target.value as PatternKind); setKindPinned(true); }}
            slotProps={{ htmlInput: { 'aria-label': 'pattern type' } }}
            sx={{ width: 132 }}
          >
            {PATTERN_KINDS.map((k) => (
              <MenuItem key={k.kind} value={k.kind}>
                <Tooltip title={k.help} placement="right"><span>{k.label}</span></Tooltip>
              </MenuItem>
            ))}
          </TextField>
          <SearchField
            value={draft}
            onChange={setDraftText}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commitDraft(); } }}
            placeholder={draftKind === 'wildcard' ? 'RCHP*' : 'Tag or TGID'}
            ariaLabel="talkgroup pattern"
            sx={{ width: { xs: '100%', sm: 240 } }}
          />
          <Button
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={commitDraft}
            disabled={!draft.trim()}
          >
            Add
          </Button>
          <Box sx={{ flexGrow: 1 }} />
          <FormControlLabel
            control={<Switch checked={heardOnly} onChange={(e) => setHeardOnly(e.target.checked)} />}
            label="Heard only"
          />
        </ControlRow>

        {filters.patterns.length > 0 && (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap alignItems="center">
            {filters.patterns.map((p, i) => {
              const count = patternCounts[i];
              const broken = count === null;
              return (
                <Tooltip
                  key={`${p.kind}:${p.text}`}
                  title={broken
                    ? `Not a valid ${KIND_LABEL[p.kind].toLowerCase()} pattern — click to fix`
                    : `${KIND_LABEL[p.kind]} · matches ${count} · click to edit`}
                >
                  <Chip
                    label={`${p.text}${broken ? '' : ` · ${count}`}`}
                    color={broken ? 'error' : count === 0 ? 'default' : 'primary'}
                    variant="outlined"
                    onClick={() => editPattern(i)}
                    onDelete={() => filters.removeAt(i)}
                  />
                </Tooltip>
              );
            })}
            <Button size="small" onClick={filters.clear}>Clear patterns</Button>
          </Stack>
        )}

        {draftError
          ? <Hint error>Incomplete pattern: {draftError}</Hint>
          : (
            <Hint>
              {filters.patterns.length > 0
                ? 'Patterns add up — a talkgroup shows if it matches any of them. '
                : 'Add as many patterns as you like; a talkgroup shows if it matches any of them. '}
              Every pattern is matched against the tag and the TGID, and the
              patterns are saved {filters.shared
                ? 'on the receiver'
                : 'in this browser — the receiver is running an older build that '
                  + 'cannot store them, so they will not follow you to another device'}.
              Sort by <strong>Calls</strong> or <strong>Last heard</strong> to find
              the talkgroups that actually carry traffic.
            </Hint>
          )}

        {loadError && (
          <Alert severity="warning">
            Could not load stored talkgroup history ({loadError}). Showing only what
            the decoder has configured.
          </Alert>
        )}

        {applied && <Alert severity="success" onClose={() => setApplied(null)}>{applied}</Alert>}

        {scanWhitelist !== null && (
          <Alert severity="info" icon={false}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <span>
                The decoder is currently scanning {scanWhitelist.length} talkgroup
                {scanWhitelist.length === 1 ? '' : 's'} only. Everything else is
                ignored, including for recording and transcription.
              </span>
              <Button
                onClick={() => focus.replace(scanWhitelist)}
                disabled={scanWhitelist.length === 0}
              >
                Select those
              </Button>
            </Stack>
          </Alert>
        )}

        {focus.focused.size > 0 && (
          <Box>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {selectedRows.slice(0, 40).map((row) => (
                <Chip
                  key={row.tgid}
                  label={row.tag || row.tgid}
                  onDelete={() => focus.toggle(row.tgid)}
                  variant="outlined"
                  sx={{ color: tint(row.tag) }}
                />
              ))}
              {/* Selections can outlive the rows they came from — a talkgroup
                  removed from the tags file, say — so count from the set. */}
              {focus.focused.size > selectedRows.length && (
                <Chip label={`+${focus.focused.size - selectedRows.length} not listed`} />
              )}
              {selectedRows.length > 40 && (
                <Chip label={`+${selectedRows.length - 40} more`} />
              )}
            </Stack>
          </Box>
        )}

        {rows !== null && visible.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {heardOnly && !compiled.passthrough
              ? 'Nothing matches those patterns among the talkgroups heard so far. Turn off "Heard only" to search the whole list.'
              : 'Nothing matches those patterns.'}
          </Typography>
        ) : (
          // Height follows the row count up to a cap, so filtering down to three
          // matches does not leave 400px of empty table under them.
          <Box sx={{ height: Math.min(420, 41 + visible.length * 44), minHeight: 130 }}>
            <TableVirtuoso
              data={visible}
              context={{ focused: focus.focused, toggle: focus.toggle }}
              components={VirtuosoTableComponents}
              fixedHeaderContent={fixedHeaderContent}
              itemContent={rowContent}
            />
          </Box>
        )}
      </Stack>
    </DialogShell>
  );
}
