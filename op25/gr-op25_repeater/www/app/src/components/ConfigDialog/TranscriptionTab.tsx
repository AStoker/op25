import { useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Hint from '../common/Hint';
import InfoRow from '../common/InfoRow';
import InsetPanel from '../common/InsetPanel';
import SectionHeading from '../common/SectionHeading';
import SettingsTab from './SettingsTab';
import { useTalkgroupFocus } from '../../hooks/useTalkgroupFocus';
import type { UseConfigEditor } from '../../hooks/useConfigEditor';
import { apiUrl } from '../../utils/url';

/**
 * Transcription: which calls leave this host, where they go, what comes back.
 *
 * The form itself is the shared `SettingsTab` rendering the schema's
 * `transcription` section, so it keeps the dirty tracking, preset badges, write
 * gate and restart banner. What this file adds is the half of the picture the
 * config cannot show: what the *running* bridge is doing. Those two disagree
 * whenever a change has been saved but not restarted into, which is the state
 * most likely to be mistaken for a bug.
 */

/** Slow: it only moves when the server is reconfigured or errors accumulate. */
const STATUS_POLL_MS = 15_000;

interface HaStatus {
  call_recording?: boolean;
  home_assistant?: {
    enabled?: boolean;
    url?: string;
    stt_engine?: string | null;
    webhook_id?: string | null;
    talkgroup_scope?: 'all' | 'focused' | 'list';
    talkgroup_filter?: number[];
    filtering?: boolean;
    submitted?: number;
    filtered?: number;
    transcribed?: number;
    stt_errors?: number;
  };
}

function useHaStatus(): HaStatus | null {
  const [status, setStatus] = useState<HaStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(apiUrl('/api/ha/status'))
        .then((r) => (r.ok ? r.json() : null))
        .then((body: HaStatus | null) => { if (!cancelled && body) setStatus(body); })
        .catch(() => { /* older server, or none — the form still works */ });
    };
    load();
    const timer = setInterval(load, STATUS_POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  return status;
}

const SCOPE_LABEL: Record<string, string> = {
  all: 'All traffic',
  focused: 'Only pinned talkgroups',
  list: 'Only the configured list',
};

export default function TranscriptionTab({ editor }: { editor: UseConfigEditor }) {
  const status = useHaStatus();
  const { focused } = useTalkgroupFocus();
  const ha = status?.home_assistant;

  const running = (
    <Box>
      <SectionHeading
        title="Running now"
        meta={
          <Chip
            variant="outlined"
            color={ha?.enabled ? 'success' : 'default'}
            label={ha?.enabled ? 'transcribing' : 'off'}
          />
        }
      />
      <Box
        sx={{
          display: 'grid',
          // 140px so a phone still gets two columns: six single-column stat
          // rows push the form itself off the first screen.
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(140px, 100%), 1fr))',
          gap: 1.5,
        }}
      >
        <InfoRow
          label="Scope"
          value={SCOPE_LABEL[ha?.talkgroup_scope ?? ''] ?? '—'}
          tooltip="What the decoder is running, which is what the form below says only after a restart"
        />
        <InfoRow
          label="Talkgroups sent"
          value={ha?.filtering ? `${ha.talkgroup_filter?.length ?? 0} selected` : 'everything'}
          tooltip="An empty selection means no restriction rather than silence"
        />
        <InfoRow label="Pinned in this UI" value={focused.size} />
        <InfoRow
          label="Transcribed"
          value={ha ? `${ha.transcribed ?? 0}` : '—'}
        />
        <InfoRow
          label="Skipped by scope"
          value={ha ? `${ha.filtered ?? 0}` : '—'}
          tooltip="Calls recorded but not sent for transcription, because the scope excluded their talkgroup"
        />
        <InfoRow
          label="Errors"
          value={ha ? `${ha.stt_errors ?? 0}` : '—'}
        />
      </Box>
      <Hint>
        Pins are shared with the talkgroup table and are read live — with the
        scope set to pinned talkgroups, pinning one takes effect on its next
        call, no restart. The scope itself is config, so changing it below does
        need one.
      </Hint>
    </Box>
  );

  const header = (
    <Stack spacing={2}>
      {status && !status.call_recording && (
        <Alert severity="warning">
          <AlertTitle>Call recording is off</AlertTitle>
          Nothing is being sliced into clips, so none of these settings have
          anything to act on. Check <code>Record calls</code> below — if it is
          already on, the decoder has not started the capture, which the log
          explains.
        </Alert>
      )}
      {ha?.talkgroup_scope === 'focused' && focused.size === 0 && (
        <Alert severity="info">
          Scope is set to pinned talkgroups but nothing is pinned, so
          <strong> every</strong> call is being transcribed. Pin talkgroups in
          the Talkgroup Browser to narrow it.
        </Alert>
      )}
      <InsetPanel>{running}</InsetPanel>
    </Stack>
  );

  return <SettingsTab editor={editor} only={['transcription']} header={header} />;
}
