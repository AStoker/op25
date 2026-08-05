import { useMemo, forwardRef } from 'react';
import { TableVirtuoso } from 'react-virtuoso';
import type { TableComponents } from 'react-virtuoso';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TableContainer from '@mui/material/TableContainer';
import CircularProgress from '@mui/material/CircularProgress';
import Tooltip from '@mui/material/Tooltip';
import CardShell from '../CardShell/CardShell';
import { useIsPhone } from '../../hooks/useIsPhone';
import { useSmartColor } from '../../hooks/useSmartColor';
import { useOp25Service, useSelectedSystem } from '../../services/op25Service';
import { highlight, matchClipsToCalls, transcriptState } from '../../utils/callTranscripts';
import type { TranscriptState } from '../../utils/callTranscripts';

interface Row {
  key: string;
  time: string;
  freq: number;
  tgid: number;
  tag: string;
  src: number;
  srcTag: string;
  /** Time slot — the two slots of a DMR/TDMA channel are independent
   *  conversations, so a call log without it is ambiguous. */
  slot?: number;
  /** Trunk priority (lower wins). */
  prio?: number;
  /** What the transcript column should show for this call. */
  transcript: TranscriptState;
}

function fmtFreq(hz: number): string {
  return (hz / 1e6).toFixed(4);
}

function fmtTime(epoch: number): string {
  if (!epoch) return '';
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString();
}

const VirtuosoTableComponents: TableComponents<Row> = {
  Scroller: forwardRef<HTMLDivElement>((props, ref) => (
    <TableContainer {...props} ref={ref} />
  )),
  Table: (props) => <Table size="small" sx={{ tableLayout: 'fixed' }} {...props} />,
  TableHead: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableHead {...props} ref={ref} />
  )),
  TableRow: ({ item: _item, ...props }) => <TableRow hover {...props} />,
  TableBody: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <TableBody {...props} ref={ref} />
  )),
};

/**
 * The transcript for one call.
 *
 * The distinction that matters here is "waiting" vs "nothing" — a clip queued
 * behind a slow Whisper model and a clip that came back empty both carry an
 * empty `transcript`, and a blank cell for the first one reads as a bug.
 */
function TranscriptCell({ state }: { state: TranscriptState }) {
  if (state.kind === 'text') {
    return (
      <Typography variant="body2" component="span" sx={{ overflowWrap: 'anywhere' }}>
        {highlight(state.text, state.keywords).map((part, i) =>
          typeof part === 'string' ? (
            <span key={i}>{part}</span>
          ) : (
            <Box
              key={i}
              component="mark"
              sx={{ bgcolor: 'warning.light', color: 'warning.contrastText', px: 0.25, borderRadius: 0.5 }}
            >
              {part.hit}
            </Box>
          ),
        )}
      </Typography>
    );
  }

  if (state.kind === 'pending') {
    return (
      <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
        <CircularProgress size={11} thickness={6} />
        <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
          awaiting transcript
        </Typography>
      </Box>
    );
  }

  const muted = (label: string, title?: string) => {
    const body = (
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontStyle: 'italic', overflowWrap: 'anywhere' }}
      >
        {label}
      </Typography>
    );
    return title ? <Tooltip title={title}><span>{body}</span></Tooltip> : body;
  };

  switch (state.kind) {
    case 'error':
      return muted('transcription failed', state.detail);
    // Surfaced rather than hidden: if the hallucination filter is eating real
    // traffic, this is how you would notice.
    case 'discarded':
      return muted('discarded as hallucination', state.text);
    case 'empty':
      return muted('no speech recognised');
    default:
      return <span>—</span>;
  }
}

export default function CallHistoryCard() {
  const system    = useSelectedSystem();
  const { callLog, callClips } = useOp25Service();
  const phone     = useIsPhone();
  const tint      = useSmartColor();

  // Primary source: the rolling call_log (when present).
  // Fallback: derive entries from per-frequency tgid/srcaddr history.
  const rows = useMemo<Row[]>(() => {
    if (callLog.length > 0) {
      const keyed = callLog.map((e, i) => ({ key: `${e.time}-${i}`, entry: e }));
      // The call log and the captured clips share no id, so they are joined on
      // talkgroup + time — see utils/callTranscripts.
      const clipFor = matchClipsToCalls(
        keyed.map(({ key, entry }) => ({ key, time: entry.time, tgid: entry.tgid })),
        callClips,
      );
      return keyed
        .slice()
        .reverse()
        .map(({ key, entry: e }) => ({
          key,
          time:   fmtTime(e.time),
          freq:   e.freq,
          tgid:   e.tgid,
          tag:    e.tgtag,
          src:    e.rid,
          srcTag: e.rtag,
          slot:   e.slot,
          prio:   e.prio,
          transcript: transcriptState(clipFor.get(key)),
        }));
    }

    if (!system?.frequency_data) return [];
    const out: Row[] = [];
    for (const [freqStr, data] of Object.entries(system.frequency_data)) {
      if (data.type !== 'voice') continue;
      const freq = Number(freqStr);
      const len  = data.tgids.length;
      // Walk the per-frequency history newest → oldest.
      for (let i = len - 1; i >= 0; i--) {
        out.push({
          key:    `${freq}-${i}`,
          time:   data.last_activity.trim(),
          freq,
          tgid:   Number(data.tgids[i]),
          tag:    data.tags[i] ?? '',
          src:    data.srcaddrs[i] ?? 0,
          srcTag: data.srctags[i] ?? '',
          // This fallback path carries no usable timestamp — `last_activity`
          // is preformatted text — so clips cannot be joined to it.
          transcript: { kind: 'none' },
        });
      }
    }
    return out;
  }, [callLog, callClips, system]);

  // On a phone the frequency and the bare TGID are the least useful columns \u2014
  // the tag already names the talkgroup \u2014 so they make way for the two that
  // answer "who just talked, and when".
  const fixedHeaderContent = () => (
    <TableRow>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '22%' : '11%' }}>Time</TableCell>
      {!phone && (
        <>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '11%' }}>Freq</TableCell>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '7%' }}>TG</TableCell>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '5%' }}>Slot</TableCell>
          <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '5%' }}>Prio</TableCell>
        </>
      )}
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '42%' : '17%' }}>Tag</TableCell>
      <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: phone ? '36%' : '16%' }}>Source</TableCell>
      {!phone && (
        <TableCell variant="head" sx={{ backgroundColor: 'background.paper', width: '28%' }}>Transcript</TableCell>
      )}
    </TableRow>
  );

  const rowContent = (_index: number, r: Row) => (
    <>
      <TableCell>{r.time || '\u2014'}</TableCell>
      {!phone && (
        <>
          <TableCell>{fmtFreq(r.freq)}</TableCell>
          <TableCell>{r.tgid || '\u2014'}</TableCell>
          <TableCell>{r.slot === undefined || r.slot === null ? '\u2014' : r.slot}</TableCell>
          <TableCell>{r.prio ?? '\u2014'}</TableCell>
        </>
      )}
      <TableCell sx={{ overflowWrap: 'anywhere', color: tint(r.tag) }}>
        {r.tag || (r.tgid ? `TG ${r.tgid}` : '\u2014')}
        {/* No room for a column on a phone, so the transcript rides along
            under the talkgroup it belongs to. */}
        {phone && r.transcript.kind !== 'none' && (
          <Box sx={{ mt: 0.25, color: 'text.primary' }}>
            <TranscriptCell state={r.transcript} />
          </Box>
        )}
      </TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        {r.src ? (r.srcTag ? `${r.srcTag} (${r.src})` : r.src) : '\u2014'}
      </TableCell>
      {!phone && (
        <TableCell sx={{ overflowWrap: 'anywhere' }}>
          <TranscriptCell state={r.transcript} />
        </TableCell>
      )}
    </>
  );

  return (
    <CardShell title="Call History">
      {rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No calls yet.
        </Typography>
      ) : (
        <Box sx={{ height: { xs: 280, sm: 320 } }}>
          <TableVirtuoso
            data={rows}
            components={VirtuosoTableComponents}
            fixedHeaderContent={fixedHeaderContent}
            itemContent={rowContent}
          />
        </Box>
      )}
    </CardShell>
  );
}
