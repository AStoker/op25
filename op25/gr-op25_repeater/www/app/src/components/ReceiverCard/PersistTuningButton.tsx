import { useCallback, useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import SaveIcon from '@mui/icons-material/Save';
import Hint from '../common/Hint';
import { apiUrl } from '../../utils/url';
import { readPath, writePath } from '../../hooks/useConfigEditor';

/** Decimal places to store ppm at. Mirrors the `precision` on `devices[*].ppm`
 *  in config_schema.py; at 859 MHz one ppm is 859 Hz, so three decimals is
 *  already finer than the 100 Hz small tuning step. Rounding here is what keeps
 *  2.3749999999999996 out of the config file in the first place. */
const PPM_PRECISION = 3;

/**
 * Persist the fine-tuned ppm so it survives a restart.
 *
 * `adj_tune` moves `device.ppm` in the running decoder and nothing writes it
 * back, so every restart reverted to whatever the config said — usually 0.0, and
 * the tuning had to be redone by hand each time. `ppm` was always a config key;
 * what was missing was a way to get the live value into it.
 *
 * This does the whole round trip rather than adding an endpoint, because the
 * server does not know the live ppm: it arrives in `channel_update`, which only
 * the browser sees.
 */

interface Props {
  /** Device the selected channel is on, from `channel_update`. */
  device: string | undefined;
  /** Live ppm in the running decoder. */
  livePpm: number | null | undefined;
  disabled?: boolean;
}

export default function PersistTuningButton({ device, livePpm, disabled = false }: Props) {
  const [savedPpm, setSavedPpm] = useState<number | null>(null);
  const [editable, setEditable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl('api/config/state'));
      if (!resp.ok) { setEditable(false); return; }
      const state = await resp.json();
      setEditable(Boolean(state.editable));
      if (device) {
        const stored = readPath(state.effective, `devices[${device}].ppm`);
        setSavedPpm(typeof stored === 'number' ? stored : null);
      }
    } catch {
      setEditable(false);   // an older server without the config API
    }
  }, [device]);

  useEffect(() => { void refresh(); }, [refresh]);

  // Compare at the precision we store at. adj_tune works in fractional ppm, so
  // an exact === against a rounded stored value would read as dirty forever.
  const differs = typeof livePpm === 'number' && savedPpm !== null
    && Number(livePpm.toFixed(PPM_PRECISION)) !== Number(savedPpm.toFixed(PPM_PRECISION));
  const unsaved = typeof livePpm === 'number' && (savedPpm === null || differs);

  const persist = async () => {
    if (!device || typeof livePpm !== 'number') return;
    const rounded = Number(livePpm.toFixed(PPM_PRECISION));
    setBusy(true);
    setResult(null);
    try {
      const stateResp = await fetch(apiUrl('api/config/state'));
      if (!stateResp.ok) throw new Error(`could not read the config (${stateResp.status})`);
      const state = await stateResp.json();

      const next = writePath(state.effective, `devices[${device}].ppm`, rounded);
      const resp = await fetch(apiUrl('api/config'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config: next,
          source: 'fine-tune',
          summary: `ppm ${rounded} for ${device}`,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(String(body.detail ?? body.error ?? `HTTP ${resp.status}`));
      }
      setResult({ ok: true, message: `Saved ppm ${rounded}` });
      await refresh();
    } catch (e) {
      setResult({ ok: false, message: e instanceof Error ? e.message : 'save failed' });
    } finally {
      setBusy(false);
    }
  };

  if (!editable) return null;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Button
          startIcon={<SaveIcon />}
          disabled={disabled || busy || !device || !unsaved}
          onClick={() => void persist()}
        >
          {busy ? 'Saving…' : 'Save tuning'}
        </Button>
        {savedPpm !== null && (
          <Tooltip title="ppm currently stored in the config, which is what a restart will use">
            <Chip variant="outlined" label={`saved ${Number(savedPpm.toFixed(PPM_PRECISION))}`} />
          </Tooltip>
        )}
        {unsaved && <Chip variant="outlined" color="warning" label="unsaved" />}
      </Box>
      <Hint>
        Fine tuning moves ppm in the running decoder only — without this it is
        lost on restart. Saving stores it as an override, so it survives and
        applies without a restart.
      </Hint>
      {result && (
        <Alert
          severity={result.ok ? 'success' : 'error'}
          sx={{ mt: 1 }}
          onClose={() => setResult(null)}
        >
          {result.message}
        </Alert>
      )}
    </Box>
  );
}
