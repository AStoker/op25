import { useState } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import UndoIcon from '@mui/icons-material/Undo';
import ControlRow from '../common/ControlRow';
import Hint from '../common/Hint';
import InsetPanel from '../common/InsetPanel';
import SectionHeading from '../common/SectionHeading';
import type { UseConfigEditor } from '../../hooks/useConfigEditor';
import type { ConfigChange } from '../../types/config';

/**
 * Config version history, with rollback.
 *
 * What is stored per version is the *overlay* — the user's overrides — not the
 * whole config. So rolling back replays their intent onto today's preset rather
 * than reinstating an old preset's values, which means a rollback cannot silently
 * undo an add-on fix they never chose to undo.
 */

function when(ts: number): string {
  // The browser knows the viewer's clock and locale; the server deliberately
  // sends a raw epoch.
  return new Date(ts * 1000).toLocaleString();
}

function short(value: unknown): string {
  if (value === undefined) return '—';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > 48 ? `${text.slice(0, 47)}…` : text;
}

function ChangeLine({ change }: { change: ConfigChange }) {
  return (
    <Box
      component="li"
      sx={{ typography: 'caption', color: 'text.secondary', wordBreak: 'break-word' }}
    >
      <Box component="code" sx={{ color: 'text.primary' }}>{change.path}</Box>
      {change.op === 'change' && <> : {short(change.old)} → {short(change.new)}</>}
      {change.op === 'add' && <> : added {short(change.new)}</>}
      {change.op === 'remove' && <> : removed (was {short(change.old)})</>}
    </Box>
  );
}

export default function HistoryTab({ editor }: { editor: UseConfigEditor }) {
  const { state, history, rollback, busy, error } = editor;
  const [confirming, setConfirming] = useState<number | null>(null);

  if (!state) {
    return (
      <Alert severity={error?.status === 503 ? 'info' : 'error'}>
        <AlertTitle>{error?.message ?? 'Configuration unavailable'}</AlertTitle>
        {error?.detail}
      </Alert>
    );
  }

  if (!state.history_enabled) {
    return (
      <Alert severity="info">
        <AlertTitle>No version history</AlertTitle>
        No history database is configured, so changes are saved but not recorded.
        Losing the history deliberately never blocks a save. Set
        <code> terminal.config_history_db</code> to enable it.
      </Alert>
    );
  }

  if (history.length === 0) {
    return (
      <Stack spacing={1}>
        <SectionHeading title="No changes yet" />
        <Hint>
          Every save, reset and rollback is recorded here with the fields it
          touched, and any of them can be restored.
        </Hint>
      </Stack>
    );
  }

  return (
    <Stack spacing={1.5}>
      {error && (
        <Alert severity="error">
          <AlertTitle>{error.message}</AlertTitle>
          {error.detail}
        </Alert>
      )}

      <SectionHeading
        title="Change history"
        meta={<Chip variant="outlined" label={`${state.versions}`} />}
      />
      <Hint>
        Each entry stores the overrides in force after it, so restoring one
        replays your changes onto the current preset — it will not undo an add-on
        fix you never chose to undo.
      </Hint>

      {history.map((version, index) => (
        <InsetPanel key={version.id ?? `${version.ts}-${index}`}>
          <Stack spacing={0.75}>
            <SectionHeading
              title={version.summary || 'no change'}
              meta={
                <>
                  <Tooltip title={`Recorded ${when(version.ts)}`}>
                    <Box component="span">{when(version.ts)}</Box>
                  </Tooltip>
                  <Chip variant="outlined" label={version.source} />
                  {index === 0 && <Chip variant="outlined" color="primary" label="current" />}
                </>
              }
              action={
                index === 0 || version.id === null ? undefined : (
                  <Button
                    startIcon={<UndoIcon />}
                    disabled={!state.editable || busy}
                    onClick={() => setConfirming(version.id)}
                  >
                    Restore
                  </Button>
                )
              }
              sx={{ mb: 0 }}
            />

            {version.diff.length > 0 && (
              <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                {version.diff.map((c) => <ChangeLine key={c.path} change={c} />)}
              </Box>
            )}

            {confirming === version.id && version.id !== null && (
              <Box>
                <Typography variant="caption" color="warning.main" display="block">
                  Restore the overrides from this point? Your current overrides
                  are replaced — and this restore is itself recorded, so it can be
                  undone too.
                </Typography>
                <ControlRow sx={{ mt: 0.5 }}>
                  <Button
                    variant="contained"
                    color="warning"
                    disabled={busy}
                    onClick={async () => {
                      const id = version.id;
                      setConfirming(null);
                      if (id !== null) await rollback(id);
                    }}
                  >
                    Restore
                  </Button>
                  <Button onClick={() => setConfirming(null)}>Cancel</Button>
                </ControlRow>
              </Box>
            )}
          </Stack>
        </InsetPanel>
      ))}
    </Stack>
  );
}
