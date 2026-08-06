import { useCallback, useDeferredValue, useEffect, useMemo, useState, forwardRef } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import type { TableComponents } from 'react-virtuoso';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import DialogShell from '../common/DialogShell';
import ControlRow from '../common/ControlRow';
import Hint from '../common/Hint';
import SearchField from '../common/SearchField';
import { useIsPhone } from '../../hooks/useIsPhone';
import { useSmartColor } from '../../hooks/useSmartColor';
import type { TalkgroupFocus } from '../../hooks/useTalkgroupFocus';
import { formatFreqMHz, formatLastSeen, formatLastSeenExact } from '../../utils/lastSeen';
import { useOp25Service } from '../../services/op25Service';
import { apiUrl } from '../../utils/url';
import type { TalkgroupRecord } from '../../types/op25';

/**
 * Pick talkgroups out of the full configured list.
 *
 * The problem this solves: the dashboard's talkgroup table re-sorts and re-renders
 * as traffic comes and goes, so finding one specific talkgroup in a couple of
 * thousand means chasing a moving row. Here the list is frozen (loaded once when
 * the dialog opens), filterable by substring *or* regex as you type, and
 * selectable in bulk — including "select everything the filter currently matches",
 * which is the whole point of the regex.
 *
 * Two separate outputs, deliberately kept apart:
 *
 *  - the focus set, which only affects what this browser's *display* pins and
 *    filters (localStorage, per browser);
 *  - the decoder's scan list, applied only by an explicit button, because it
 *    genuinely stops other talkgroups being received, recorded and transcribed.
 */

interface TalkgroupBrowserProps {
  open: boolean;
  onClose: () => void;
  focus: TalkgroupFocus;
}

type Row = TalkgroupRecord & { configured: boolean; prio?: number };

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

/** A compiled live filter, or the reason it could not be compiled. */
function useFilter(query: string, useRegex: boolean) {
  return useMemo(() => {
    const trimmed = query.trim();
    if (!trimmed) return { match: () => true, error: null as string | null };
    if (!useRegex) {
      const needle = trimmed.toLowerCase();
      return {
        match: (row: Row) =>
          row.tag.toLowerCase().includes(needle) || String(row.tgid).includes(needle),
        error: null,
      };
    }
    try {
      // Case-insensitive: a scanner list is shouty and nobody wants to type it.
      const re = new RegExp(trimmed, 'i');
      return {
        match: (row: Row) => re.test(row.tag) || re.test(String(row.tgid)),
        error: null,
      };
    } catch (e) {
      // Live regex means most keystrokes are a syntax error in progress. Show
      // everything and say why rather than emptying the table mid-word.
      return { match: () => true, error: (e as Error).message };
    }
  }, [query, useRegex]);
}

export default function TalkgroupBrowser({ open, onClose, focus }: TalkgroupBrowserProps) {
  const phone = useIsPhone();
  const tint = useSmartColor();
  const { systems, setScanList, scanWhitelist } = useOp25Service();

  const [query, setQuery] = useState('');
  const [useRegex, setUseRegex] = useState(false);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  // Filtering two thousand rows on every keystroke is what makes a live regex
  // feel laggy; deferring it keeps the input itself responsive.
  const deferredQuery = useDeferredValue(query);
  const { match, error: regexError } = useFilter(deferredQuery, useRegex);

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

  const visible = useMemo(() => (rows ?? []).filter(match), [rows, match]);
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
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '22%' : '12%' }}>TGID</TableCell>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? 'auto' : '38%' }}>Tag</TableCell>
      {!phone && <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '16%' }}>Last heard</TableCell>}
      {!phone && <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '16%' }}>Freq</TableCell>}
      {!phone && <TableCell variant="head" align="right" sx={{ backgroundColor: 'background.paper', width: '10%' }}>Calls</TableCell>}
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
      <TableCell>{row.tgid}</TableCell>
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
      {!phone && <TableCell align="right">{row.count || '—'}</TableCell>}
    </>
  );

  return (
    <DialogShell
      open={open}
      onClose={onClose}
      title="Talkgroup Browser"
      subheader={
        <Typography variant="caption" color="text.secondary">
          {rows === null ? 'Loading…' : `${visible.length} of ${rows.length} shown`}
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
          <SearchField
            value={query}
            onChange={setQuery}
            placeholder={useRegex ? 'Regex' : 'Filter tag or TGID'}
            ariaLabel="filter talkgroups"
            sx={{ width: { xs: '100%', sm: 260 } }}
          />
          <FormControlLabel
            control={<Switch checked={useRegex} onChange={(e) => setUseRegex(e.target.checked)} />}
            label="Regex"
          />
          {/* No "show only selected" switch here: that filters the dashboard's
              table, not this one, so it belongs on the card where its effect is
              visible. This dialog is for choosing; the card is for looking. */}
        </ControlRow>

        {regexError
          ? <Hint error>Incomplete pattern: {regexError}</Hint>
          : (
            <Hint>
              {useRegex
                ? 'Matched against both tag and TGID. Use the header checkbox to select every match at once.'
                : 'Matches any part of the tag or TGID. Turn on Regex for patterns like ^(FIRE|EMS).'}
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
            Nothing matches that filter.
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
