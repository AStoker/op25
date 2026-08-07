import { useEffect, useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import ControlRow from '../common/ControlRow';
import Field from '../common/Field';
import Hint from '../common/Hint';
import SectionHeading from '../common/SectionHeading';
import type { UseConfigEditor } from '../../hooks/useConfigEditor';

/**
 * The escape hatch: edit the config as JSON.
 *
 * A plain textarea rather than a code editor. CodeMirror or Monaco would be
 * ~300 kB of bundle for syntax colouring, on a UI that has to load over ingress
 * on a phone — and the thing that actually prevents mistakes here is the
 * server's validation, which runs either way.
 */

type View = 'effective' | 'overlay' | 'preset';

const VIEW_HELP: Record<View, string> = {
  effective: 'preset + your overrides — what the decoder should be running. '
    + 'Editing this is how you add a device or a system the form cannot invent.',
  overlay: 'Only your overrides, exactly as stored on disk. Read-only here: save '
    + 'from the effective view instead, so the server computes the delta and a '
    + 'value equal to the preset stops being an override.',
  preset: 'The preset as shipped, read-only. This is what "reset to preset" '
    + 'would leave you with.',
};

export default function AdvancedJsonTab({ editor }: { editor: UseConfigEditor }) {
  const { state, save, resetToPreset, exportConfig, busy, error, lastSave } = editor;
  const [view, setView] = useState<View>('effective');
  const [text, setText] = useState('');
  const [summary, setSummary] = useState('');
  const [exportPath, setExportPath] = useState('op25.exported.json');
  const [exported, setExported] = useState<string | null>(null);

  const source = useMemo(() => {
    if (!state) return null;
    return view === 'overlay' ? state.overlay
      : view === 'preset' ? state.base
        : state.effective;
  }, [state, view]);

  // Re-serialise whenever the server's copy or the selected view changes, so the
  // box never shows a stale document after a save or a rollback.
  useEffect(() => {
    setText(source ? `${JSON.stringify(source, null, 2)}\n` : '');
  }, [source]);

  const parsed = useMemo((): { ok: true; value: Record<string, unknown> }
  | { ok: false; message: string } => {
    try {
      const value = JSON.parse(text);
      if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return { ok: false, message: 'The config must be a JSON object.' };
      }
      return { ok: true, value };
    } catch (e) {
      return { ok: false, message: e instanceof Error ? e.message : 'Invalid JSON' };
    }
  }, [text]);

  if (!state) {
    return (
      <Alert severity={error?.status === 503 ? 'info' : 'error'}>
        <AlertTitle>{error?.message ?? 'Configuration unavailable'}</AlertTitle>
        {error?.detail}
      </Alert>
    );
  }

  const editable = view === 'effective' && state.editable && !busy;
  const dirty = source ? text !== `${JSON.stringify(source, null, 2)}\n` : false;

  return (
    <Stack spacing={2}>
      {error && (
        <Alert severity="error">
          <AlertTitle>{error.message}</AlertTitle>
          {error.detail}
          {error.problems && (
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {error.problems.map((p) => <li key={p}>{p}</li>)}
            </Box>
          )}
        </Alert>
      )}

      {lastSave?.needs_restart && (
        <Alert severity="warning">
          <AlertTitle>Saved — restart to apply</AlertTitle>
          <code>{lastSave.restart_required.map((c) => c.path).join(', ')}</code> are
          read at startup. Restart the OP25 add-on from Home Assistant.
        </Alert>
      )}

      <Box>
        <ToggleButtonGroup
          exclusive
          value={view}
          onChange={(_e, v: View | null) => { if (v) setView(v); }}
          aria-label="which document to show"
        >
          <ToggleButton value="effective">Effective</ToggleButton>
          <ToggleButton value="overlay">Overrides</ToggleButton>
          <ToggleButton value="preset">Preset</ToggleButton>
        </ToggleButtonGroup>
        <Hint>{VIEW_HELP[view]}</Hint>
      </Box>

      <TextField
        multiline
        minRows={14}
        maxRows={30}
        value={text}
        disabled={!editable && view === 'effective' && !state.editable}
        onChange={(e) => setText(e.target.value)}
        error={!parsed.ok}
        // Not a Field: the monospace body and the full-width box are the point,
        // and the validation message needs to sit under a very tall control.
        slotProps={{
          htmlInput: {
            'aria-label': `${view} configuration JSON`,
            readOnly: view !== 'effective',
            spellCheck: false,
            style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 },
          },
        }}
      />
      {!parsed.ok && <Hint error>{parsed.message}</Hint>}

      {view === 'effective' && (
        <>
          <Field
            label="Change note"
            hint="Recorded against this version so the history reads as intent rather than a list of paths."
            sx={{ maxWidth: 420 }}
          >
            <TextField
              value={summary}
              placeholder="e.g. gain sweep step 3"
              onChange={(e) => setSummary(e.target.value)}
            />
          </Field>

          <ControlRow>
            <Button
              variant="contained"
              disabled={!parsed.ok || !dirty || !state.editable || busy}
              onClick={() => {
                if (parsed.ok) void save(parsed.value, summary || undefined, 'advanced-editor');
              }}
            >
              {busy ? 'Saving…' : 'Save JSON'}
            </Button>
            <Button
              disabled={!dirty || busy}
              onClick={() => setText(source ? `${JSON.stringify(source, null, 2)}\n` : '')}
            >
              Discard
            </Button>
            {dirty && <Chip label="unsaved" variant="outlined" color="warning" />}
          </ControlRow>
        </>
      )}

      <Divider />

      <Box>
        <SectionHeading title="Reset" />
        <Button
          color="warning"
          disabled={!state.editable || busy || state.overrides === 0}
          onClick={() => void resetToPreset()}
        >
          Reset to preset
        </Button>
        <Hint>
          Discards all {state.overrides} override(s) and runs the preset as
          shipped. Recorded as a version, so it can itself be rolled back.
        </Hint>
      </Box>

      <Divider />

      <Box>
        <SectionHeading title="Export a standalone copy" />
        <ControlRow align="end">
          <Field label="Path" sx={{ minWidth: 260, flexGrow: 1 }}>
            <TextField
              value={exportPath}
              onChange={(e) => setExportPath(e.target.value)}
              slotProps={{ htmlInput: { 'aria-label': 'export path' } }}
            />
          </Field>
          <Button
            disabled={!state.editable || busy || !exportPath.trim()}
            onClick={async () => setExported(await exportConfig(exportPath.trim()))}
          >
            Export
          </Button>
        </ControlRow>
        <Hint>
          Writes the effective config as one complete file. That copy stops
          tracking the preset — point the add-on's <code>config_file</code> at it
          and set <code>preset: custom</code> to use it. Relative paths land in
          the working directory.
        </Hint>
        {exported && (
          <Alert severity="success" sx={{ mt: 1 }} onClose={() => setExported(null)}>
            Wrote <code>{exported}</code>
          </Alert>
        )}
      </Box>
    </Stack>
  );
}
