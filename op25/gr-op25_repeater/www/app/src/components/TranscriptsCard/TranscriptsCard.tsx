import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import DownloadIcon from '@mui/icons-material/Download';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import CircularProgress from '@mui/material/CircularProgress';
import CardShell from '../CardShell/CardShell';
import InsetPanel from '../common/InsetPanel';
import HighlightedText from '../common/HighlightedText';
import SearchField from '../common/SearchField';
import ControlRow from '../common/ControlRow';
import { useOp25Service } from '../../services/op25Service';
import { matchesClip, searchTerms } from '../../utils/callSearch';
import { apiUrl } from '../../utils/url';
import type { CallClip } from '../../types/op25';

/** Clips are short; keep the list light rather than virtualising it. */
const MAX_VISIBLE = 60;

/** How often to re-check the capture/STT pipeline. Slow: it only changes when
 *  the server is reconfigured, or when errors start accumulating. */
const HA_STATUS_POLL_MS = 30_000;

interface HaStatusResponse {
  call_recording?: boolean;
  home_assistant?: {
    enabled?: boolean;
    url?: string;
    stt_engine?: string | null;
    webhook_id?: string | null;
    keywords?: string[];
    stt_errors?: number;
    transcribed?: number;
    hallucinations?: number;
    webhook_errors?: number;
  };
}

interface HaChipState {
  label: string;
  color: 'default' | 'success' | 'warning' | 'error';
  detail: string;
}

/** Summarise /api/ha/status for the one chip that answers "why no transcripts?" */
function summariseHa(body: HaStatusResponse): HaChipState {
  if (!body.call_recording) {
    return {
      label: 'capture off',
      color: 'warning',
      detail: 'The server is not recording call clips, so nothing can be transcribed.',
    };
  }
  const ha = body.home_assistant;
  if (!ha?.enabled) {
    return {
      label: 'transcripts off',
      color: 'default',
      detail: 'Clips are being captured but no Home Assistant speech-to-text is '
        + 'configured — see README-home-assistant.md.',
    };
  }
  const errs = (ha.stt_errors ?? 0) + (ha.webhook_errors ?? 0);
  if (errs > 0) {
    return {
      label: `STT ${errs} error${errs === 1 ? '' : 's'}`,
      color: 'error',
      detail: `${ha.url ?? 'Home Assistant'} — ${ha.stt_errors ?? 0} speech-to-text `
        + `error(s), ${ha.webhook_errors ?? 0} webhook error(s). `
        + `${ha.transcribed ?? 0} transcribed so far.`,
    };
  }
  return {
    label: ha.stt_engine ? `STT ${ha.stt_engine}` : 'HA webhook',
    color: 'success',
    detail: `${ha.url ?? 'Home Assistant'} — ${ha.transcribed ?? 0} transcribed`
      + `${ha.hallucinations ? `, ${ha.hallucinations} discarded as hallucinations` : ''}`
      + `${ha.keywords?.length ? `, ${ha.keywords.length} keyword(s) watched` : ''}.`,
  };
}

/** Poll the capture / Home Assistant pipeline status. Null until first reply,
 *  and stays null on an older server that has no such endpoint. */
function useHaStatus(): HaChipState | null {
  const [state, setState] = useState<HaChipState | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(apiUrl('/api/ha/status'))
        .then((r) => (r.ok ? r.json() : null))
        .then((body: HaStatusResponse | null) => {
          if (!cancelled && body) setState(summariseHa(body));
        })
        .catch(() => { /* endpoint absent — no chip */ });
    };
    load();
    const timer = setInterval(load, HA_STATUS_POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  return state;
}

function fmtClock(epoch: number): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleTimeString();
}

function fmtDuration(secs: number): string {
  return `${secs.toFixed(1)}s`;
}

interface ClipRowProps {
  clip: CallClip;
  playing: boolean;
  onToggle: (clip: CallClip) => void;
  /** Terms to mark in the talkgroup and transcript, so it is visible *why* this
   *  row survived the filter. */
  search: readonly string[];
}

function ClipRow({ clip, playing, onToggle, search }: ClipRowProps) {
  const alert = clip.keywords.length > 0;
  const label = clip.talkgroup || (clip.tgid ? `TG ${clip.tgid}` : 'Unknown talkgroup');
  const source = clip.source_tag || (clip.source ? String(clip.source) : '');

  return (
    <InsetPanel
      highlight={alert}
      sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}
    >
      <Tooltip title={playing ? 'Stop' : 'Play this call'}>
        <IconButton
          size="small"
          onClick={() => onToggle(clip)}
          color={playing ? 'error' : 'primary'}
          aria-label={playing ? 'stop clip' : 'play clip'}
        >
          {playing ? <StopIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
        </IconButton>
      </Tooltip>

      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 0.75 }}>
          <Typography variant="body2" fontWeight="medium" sx={{ overflowWrap: 'anywhere' }}>
            <HighlightedText text={label} search={search} />
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {/* The TGID rides here whenever the label is the *name*, because the
                number is searchable: a row matched by "4520" that shows only
                "Cayce Fire" gives no visible reason for being in the results. */}
            {clip.talkgroup && clip.tgid ? (
              <>
                <HighlightedText text={String(clip.tgid)} search={search} />
                {' · '}
              </>
            ) : null}
            {fmtClock(clip.started)} · {fmtDuration(clip.duration)}
            {clip.continuity !== undefined && clip.continuity < 0.9 && (
              <Tooltip
                title={`Only ${Math.round(clip.continuity * 100)}% of this transmission decoded. `
                  + 'The recording concatenates what arrived, so it sounds continuous — '
                  + 'but live playback renders the missing frames as silence, which is '
                  + 'what "choppy" is. Low values mean marginal reception, not a '
                  + 'streaming fault.'}
              >
                <Chip
                  variant="outlined"
                  color={clip.continuity < 0.7 ? 'error' : 'warning'}
                  label={`${Math.round(clip.continuity * 100)}% decoded`}
                  sx={{ ml: 0.75 }}
                />
              </Tooltip>
            )}
            {source ? ` · ${source}` : ''}
          </Typography>
          {alert && (
            <Chip
              color="warning"
              icon={<NotificationsActiveIcon />}
              label={clip.keywords.join(', ')}
            />
          )}
        </Box>

        {clip.transcript ? (
          <Typography variant="body2" sx={{ mt: 0.25, overflowWrap: 'anywhere' }}>
            <HighlightedText text={clip.transcript} keywords={clip.keywords} search={search} />
          </Typography>
        ) : clip.transcript_pending ? (
          // A clip queued behind a slow model and a clip that came back empty
          // both carry an empty transcript; saying "no transcript" for the
          // first one reads as a failure that has not happened yet.
          <Box sx={{ mt: 0.25, display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <CircularProgress size={11} thickness={6} />
            <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic' }}>
              awaiting transcript…
            </Typography>
          </Box>
        ) : (
          <Typography variant="caption" color="text.secondary" sx={{ fontStyle: 'italic', overflowWrap: 'anywhere' }}>
            {clip.stt_error
              ? `speech-to-text failed: ${clip.stt_error}`
              : clip.discarded_transcript
                // Surfaced rather than hidden: if the filter is eating real
                // traffic, this is how you would notice. Searchable for the same
                // reason, hence highlighted like any other transcript text.
                ? (
                  <>
                    {'discarded as a likely hallucination: “'}
                    <HighlightedText text={clip.discarded_transcript} search={search} />
                    {'”'}
                  </>
                )
                : 'no transcript'}
          </Typography>
        )}
      </Box>

      <Tooltip title="Download WAV">
        <IconButton
          size="small"
          component="a"
          href={clip.audio_url}
          download
          aria-label="download clip"
        >
          <DownloadIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </InsetPanel>
  );
}

export default function TranscriptsCard() {
  const { callClips } = useOp25Service();
  const [alertsOnly, setAlertsOnly] = useState(false);
  // Transient, unlike the talkgroup browser's saved patterns: this searches a
  // live feed of the last 60 clips, so a query restored on the next visit would
  // hide traffic that arrived since, having been typed about calls that are gone.
  const [query, setQuery] = useState('');
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopPlayback = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlayingId(null);
  }, []);

  const togglePlay = useCallback((clip: CallClip) => {
    if (audioRef.current) {
      audioRef.current.pause();
      const wasPlaying = playingId === clip.id;
      audioRef.current = null;
      setPlayingId(null);
      if (wasPlaying) return;
    }
    // A finite WAV clip plays fine through a plain <audio> element — unlike
    // the unbounded /api/stream response, which needs the Web Audio path.
    const el = new Audio(apiUrl(clip.audio_url));
    el.onended = () => setPlayingId(null);
    el.onerror  = () => setPlayingId(null);
    audioRef.current = el;
    setPlayingId(clip.id);
    el.play().catch(() => setPlayingId(null));
  }, [playingId]);

  useEffect(() => stopPlayback, [stopPlayback]);

  const terms = useMemo(() => searchTerms(query), [query]);

  // Both filters narrow, so they compose: "keyword hits, that also mention this".
  const matched = useMemo(
    () => callClips.filter((c) =>
      (!alertsOnly || c.keywords.length > 0) && matchesClip(c, terms)),
    [callClips, alertsOnly, terms],
  );

  const rows = useMemo(() => matched.slice(0, MAX_VISIBLE), [matched]);

  // Counted over the *matched* set, not every clip: while a search is active the
  // rest of the caption describes what is on screen, and a keyword total that
  // did not would read as rows being hidden. Unfiltered, the two are the same.
  const alertCount = useMemo(
    () => matched.filter((c) => c.keywords.length > 0).length,
    [matched],
  );

  const filtering = terms.length > 0 || alertsOnly;

  // Only used to explain an empty search result: with speech-to-text off there
  // is nothing but talkgroup names to match, which is worth saying once rather
  // than leaving the user to conclude the search does not work.
  const transcribedCount = useMemo(
    () => callClips.filter((c) => c.transcript || c.discarded_transcript).length,
    [callClips],
  );

  const ha = useHaStatus();

  return (
    <CardShell title="Call Audio & Transcripts">
      <Stack spacing={1}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="caption" color="text.secondary">
              {/* While filtering, how many of the captured clips are on screen is
                  the number being asked about — the total stays, because a
                  search that matches nothing is otherwise indistinguishable
                  from nothing having been captured. */}
              {filtering ? `${matched.length} of ${callClips.length} captured` : `${callClips.length} captured`}
              {alertCount > 0 ? ` · ${alertCount} keyword ${alertCount === 1 ? 'hit' : 'hits'}` : ''}
              {matched.length > rows.length ? ` · showing ${rows.length}` : ''}
            </Typography>
            {/* Whether transcription is even configured is the first thing to
                check when transcripts do not appear — /api/ha/status knows, so
                surface it here instead of making the user curl it. */}
            {ha && (
              <Tooltip title={ha.detail}>
                <Chip variant="outlined" color={ha.color} label={ha.label} />
              </Tooltip>
            )}
          </Stack>
          <ControlRow sx={{ flex: { xs: '1 1 100%', sm: '0 0 auto' } }}>
            {/* One box over both fields: which of the two the user remembers —
                what was said, or who said it — is not predictable. */}
            <SearchField
              value={query}
              onChange={setQuery}
              placeholder="Search transcripts, talkgroups"
              ariaLabel="search captured calls"
              sx={{ width: { xs: '100%', sm: 220 } }}
            />
            <FormControlLabel
              control={<Switch size="small" checked={alertsOnly} onChange={(e) => setAlertsOnly(e.target.checked)} />}
              label="Keyword hits only"
              sx={{ mr: 0 }}
            />
          </ControlRow>
        </Box>

        {rows.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {/* Three different reasons for an empty list, and conflating them is
                what makes a search look broken: nothing captured, nothing
                matched, or a search matching nothing among calls that have no
                transcript to search in the first place. */}
            {callClips.length === 0
              ? 'No calls captured yet. Clips appear here as transmissions end; '
                + 'transcripts need a Home Assistant speech-to-text engine — see README-home-assistant.md.'
              : terms.length > 0
                ? `No captured call matches “${query.trim()}”`
                  + (alertsOnly ? ' among keyword hits.' : '.')
                  + (transcribedCount === 0
                    ? ' None of these calls has a transcript, so only talkgroup names are searchable.'
                    : '')
                : 'No calls matched a configured keyword.'}
          </Typography>
        ) : (
          <Stack spacing={0.75} sx={{ maxHeight: { xs: 380, md: 440 }, overflowY: 'auto', pr: 0.5 }}>
            {rows.map((clip) => (
              <ClipRow
                key={clip.id}
                clip={clip}
                playing={playingId === clip.id}
                onToggle={togglePlay}
                search={terms}
              />
            ))}
          </Stack>
        )}
      </Stack>
    </CardShell>
  );
}
