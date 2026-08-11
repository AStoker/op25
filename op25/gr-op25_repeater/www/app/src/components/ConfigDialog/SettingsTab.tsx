import { useEffect, useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ControlRow from '../common/ControlRow';
import Hint from '../common/Hint';
import InsetPanel from '../common/InsetPanel';
import SectionHeading from '../common/SectionHeading';
import ConfigFieldInput from './ConfigFieldInput';
import FieldLegend from './FieldLegend';
import type { UseConfigEditor } from '../../hooks/useConfigEditor';
import { concretePath, listKeys, readPath, writePath } from '../../hooks/useConfigEditor';
import type { ConfigField, ConfigSection } from '../../types/config';

/**
 * The settings form, built from the server's schema.
 *
 * Edits are held locally until Save, so a half-typed frequency is never sent —
 * and so the diff the server records is one deliberate change set rather than
 * one per keystroke, which would bury the version history.
 *
 * One instance renders any subset of the schema's sections, selected by `only`:
 * Transcription is its own tab, but it is the same form, so it inherits the
 * dirty tracking, the preset badges, the write gate and the restart banner
 * rather than reimplementing five of them.
 */

interface Props {
  editor: UseConfigEditor;
  /** Section keys to render. Defaults to every section the server did not mark
   *  standalone — those have a tab of their own. */
  only?: string[];
  /** Rendered above the form, inside the same scroll area. */
  header?: React.ReactNode;
}

function fieldsFor(section: ConfigSection, advanced: boolean): ConfigField[] {
  return section.fields.filter((f) => advanced || !f.advanced);
}

/** Fields in declaration order, split into their `group` runs. A field with no
 *  group joins the run before it, so an ungrouped section stays one block. */
function groupRuns(fields: ConfigField[]): { group: string; fields: ConfigField[] }[] {
  const runs: { group: string; fields: ConfigField[] }[] = [];
  for (const f of fields) {
    const group = f.group ?? '';
    const last = runs[runs.length - 1];
    if (last && last.group === group) last.fields.push(f);
    else runs.push({ group, fields: [f] });
  }
  return runs;
}

/** Fields whose path has no `[*]` — they belong to the section, not an element. */
function scalarFields(fields: ConfigField[]): ConfigField[] {
  return fields.filter((f) => !f.path.includes('[*]'));
}

function elementFields(fields: ConfigField[]): ConfigField[] {
  return fields.filter((f) => f.path.includes('[*]'));
}

export default function SettingsTab({ editor, only, header }: Props) {
  const { schema, state, save, busy, error, lastSave, dismissSave, restartAddon } = editor;
  const [restarting, setRestarting] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [advanced, setAdvanced] = useState(false);

  // Adopt the server's config whenever it changes underneath us — after a save,
  // a rollback, or a reset. Editing on top of a stale copy would silently
  // resurrect values the user just discarded.
  useEffect(() => {
    setDraft(state ? structuredClone(state.effective) : null);
  }, [state]);

  const dirtyPaths = useMemo(() => {
    if (!draft || !state) return new Set<string>();
    const changed = new Set<string>();
    const walk = (a: unknown, b: unknown, prefix: string) => {
      if (JSON.stringify(a) === JSON.stringify(b)) return;
      if (a && b && typeof a === 'object' && typeof b === 'object'
          && !Array.isArray(a) && !Array.isArray(b)) {
        const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
        keys.forEach((k) => walk(
          (a as Record<string, unknown>)[k],
          (b as Record<string, unknown>)[k],
          prefix ? `${prefix}.${k}` : k,
        ));
        return;
      }
      changed.add(prefix);
    };
    walk(state.effective, draft, '');
    return changed;
  }, [draft, state]);

  const dirty = dirtyPaths.size > 0;

  if (!schema || !state || !draft) {
    return (
      <Stack spacing={2}>
        {error ? (
          <Alert severity={error.status === 503 ? 'info' : 'error'}>
            <AlertTitle>{error.message}</AlertTitle>
            {error.detail}
          </Alert>
        ) : <CircularProgress size={24} />}
      </Stack>
    );
  }

  const readOnly = !state.editable || busy;

  const setValue = (path: string, value: unknown) => {
    setDraft((prev) => (prev ? writePath(prev, path, value) : prev));
  };

  const renderField = (field: ConfigField, key?: string | number) => {
    const path = key === undefined ? field.path : concretePath(field.path, key);
    const presetValue = readPath(state.base, path);
    // Overridden against what is *saved*, not against the draft: an unsaved edit
    // is already flagged by the dirty count, and showing it as an override would
    // claim something is stored that is not.
    const overridden = readPath(state.overlay, path) !== undefined;
    return (
      <ConfigFieldInput
        key={path}
        field={field}
        value={readPath(draft, path)}
        presetValue={presetValue}
        overridden={overridden}
        disabled={readOnly}
        onChange={(v) => setValue(path, v)}
        // Writing the preset value back is all a reset needs to be: the server
        // prunes anything equal to the base, so saving drops the override. When
        // the preset has no such key, undefined removes it from the submitted
        // JSON, which has the same effect.
        onReset={() => setValue(path, presetValue)}
      />
    );
  };

  const grid = (children: React.ReactNode) => (
    <Box
      sx={{
        display: 'grid',
        // minmax(min(...)) so a long help string cannot force a sideways scroll
        // on a phone.
        gridTemplateColumns: 'repeat(auto-fit, minmax(min(260px, 100%), 1fr))',
        gap: 2,
      }}
    >
      {children}
    </Box>
  );

  const standalone = schema.standalone_sections ?? [];
  const sections = schema.sections.filter((s) => (
    only ? only.includes(s.key) : !standalone.includes(s.key)
  ));
  // The section title would just repeat the tab label when a tab holds one
  // section, so it is only drawn where it separates one section from another.
  const showSectionHeadings = sections.length > 1;

  return (
    <Stack spacing={2}>
      {header}

      {!state.editable && (
        <Alert severity="warning">
          <AlertTitle>Read-only</AlertTitle>
          {state.write_policy === 'ingress'
            ? 'Open OP25 from the Home Assistant sidebar to edit. The published '
              + 'port is unauthenticated, so config changes are not accepted there.'
            : `Editing is disabled (write policy: ${state.write_policy}).`}
        </Alert>
      )}

      {lastSave?.needs_restart && (
        <Alert severity="warning" onClose={dismissSave}>
          <AlertTitle>Saved — restart to apply</AlertTitle>
          {lastSave.applied.length > 0 && (
            <Box sx={{ mb: 0.5 }}>
              Applied immediately: <code>{lastSave.applied.join(', ')}</code>
            </Box>
          )}
          These need the decoder rebuilt, so they are stored but not yet running:{' '}
          <code>{lastSave.restart_required.map((c) => c.path).join(', ')}</code>.
          <Box sx={{ mt: 1 }}>
            <Button
              variant="contained"
              color="warning"
              disabled={busy || restarting}
              onClick={async () => {
                setRestarting(true);
                const ok = await restartAddon();
                // Stays disabled on success: the page is about to lose its
                // server, and re-enabling invites a second restart into the
                // first. On a refusal there is nothing to wait for, so the
                // button comes back and `error` above says why.
                if (!ok) setRestarting(false);
              }}
            >
              {restarting ? 'Restarting…' : 'Restart add-on'}
            </Button>
            {restarting && (
              <Hint>
                The decoder is coming back up — the connection indicator in the
                header will go red and then green again by itself. Nothing here
                needs clicking twice.
              </Hint>
            )}
          </Box>
        </Alert>
      )}

      {lastSave && !lastSave.needs_restart && (
        <Alert severity="success" onClose={dismissSave}>
          Applied immediately
          {lastSave.applied.length > 0 && <>: <code>{lastSave.applied.join(', ')}</code></>}
          . No restart needed.
        </Alert>
      )}

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

      {state.preset_drift.length > 0 && (
        <Alert severity="info">
          <AlertTitle>The preset has moved on</AlertTitle>
          Your overrides are masking newer preset values. Clear an override to
          adopt the preset's:
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {state.preset_drift.map((d) => (
              <li key={d.path}>
                <code>{d.path}</code>: preset {JSON.stringify(d.preset)}, yours{' '}
                {JSON.stringify(d.override)}
              </li>
            ))}
          </Box>
        </Alert>
      )}

      <ControlRow>
        <Button
          variant="contained"
          disabled={!dirty || readOnly}
          onClick={() => void save(draft, undefined, 'settings-form')}
        >
          {busy ? 'Saving…' : 'Save changes'}
        </Button>
        <Button
          disabled={!dirty || busy}
          onClick={() => setDraft(structuredClone(state.effective))}
        >
          Discard
        </Button>
        <Box sx={{ flexGrow: 1 }} />
        <FormControlLabel
          control={<Switch checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />}
          label="Advanced fields"
        />
      </ControlRow>
      <Hint>
        {dirty
          ? `${dirtyPaths.size} unsaved change${dirtyPaths.size === 1 ? '' : 's'}. `
          : 'No unsaved changes. '}
        Only values that differ from the preset are stored, so anything you leave
        alone keeps tracking add-on updates.
        {state.overrides > 0 && ` Currently overriding ${state.overrides} value(s).`}
      </Hint>

      <FieldLegend />

      {sections.map((section) => {
        const visible = fieldsFor(section, advanced);
        const scalars = scalarFields(visible);
        const perElement = elementFields(visible);
        const keys = listKeys(draft, section.list_path, section.identity ?? 'name');

        if (scalars.length === 0 && perElement.length === 0) return null;

        return (
          <Box key={section.key}>
            {showSectionHeadings && (
              <>
                <Divider sx={{ mb: 1.5 }} />
                <SectionHeading
                  title={section.label}
                  meta={keys.length > 0
                    ? <Chip variant="outlined" label={`${keys.length}`} />
                    : undefined}
                />
              </>
            )}

            {scalars.length > 0 && (
              <Box sx={{ mb: perElement.length > 0 ? 2 : 0 }}>
                {groupRuns(scalars).map((run, i) => (
                  <Box key={run.group || `run-${i}`} sx={{ mb: 2 }}>
                    {run.group && <SectionHeading title={run.group} />}
                    {grid(run.fields.map((f) => renderField(f)))}
                  </Box>
                ))}
              </Box>
            )}

            {perElement.length > 0 && (
              <Stack spacing={1.5}>
                {keys.length === 0 && (
                  <Hint>
                    Nothing configured here yet. Adding one needs the raw JSON
                    editor — the form edits what exists rather than inventing a
                    device the hardware may not have.
                  </Hint>
                )}
                {keys.map((key) => (
                  <InsetPanel key={key}>
                    <Typography variant="subtitle2" sx={{ mb: 1 }}>{key}</Typography>
                    {grid(perElement.map((f) => renderField(f, key)))}
                  </InsetPanel>
                ))}
              </Stack>
            )}
          </Box>
        );
      })}

      <Divider />
      <Box>
        <SectionHeading
          title="Where this is stored"
          meta={
            <Tooltip title="The preset ships inside the add-on and keeps receiving fixes; your overrides live beside it in this file">
              <Chip variant="outlined" label={state.base_id} />
            </Tooltip>
          }
        />
        <Hint>
          Overrides: <code>{state.overlay_file ?? 'not configured'}</code>
          {!state.history_enabled && ' — version history unavailable, but saving still works.'}
        </Hint>
      </Box>
    </Stack>
  );
}
