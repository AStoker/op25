import { useState } from 'react';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import DialogShell from '../common/DialogShell';
import ControlRow from '../common/ControlRow';
import Field from '../common/Field';
import Hint from '../common/Hint';
import InfoRow from '../common/InfoRow';
import SectionHeading from '../common/SectionHeading';
import RunningConfigPanel from './RunningConfigPanel';
import SettingsTab from './SettingsTab';
import AdvancedJsonTab from './AdvancedJsonTab';
import HistoryTab from './HistoryTab';
import { useConfigEditor } from '../../hooks/useConfigEditor';
import { useOp25Service } from '../../services/op25Service';
import { useSmartColorsEnabled } from '../../hooks/useSmartColor';
import { PRESET_PRIMARY_COLORS, useThemeService } from '../../services/themeService';

/** Log levels multi_rx actually distinguishes. 0-2 are the useful day-to-day
 *  settings; 10 turns on ESS/encryption-sync decoding. */
const LOG_LEVELS = [0, 1, 2, 3, 5, 9, 10];

const LOG_LEVEL_LABEL = (lvl: number): string =>
  lvl === 0 ? '0 — quiet' : lvl === 10 ? '10 — ESS/crypt' : String(lvl);

/** Read-only value with an em dash for "not set", so an absent key reads the
 *  same everywhere instead of leaving a blank line. */
function orDash(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}

// ---------------------------------------------------------------------------
// Decoder tab
// ---------------------------------------------------------------------------

/**
 * The knobs the decoder accepts at runtime, plus how it was started.
 *
 * multi_rx is configured by its JSON file and takes only four command-line
 * options (`-c`, `-v`, `-p`, `-d`), of which exactly one can be changed while
 * it runs: verbosity. That is what this tab is — the GUI equivalent of `-v`,
 * with the rest of the startup picture read-only beside it so the difference
 * between "adjustable" and "restart to change" is visible.
 */
function DecoderTab() {
  const { config, terminalConfig, setLogLevel, logLevel, decoderRunning } = useOp25Service();

  const terminal = terminalConfig ?? config?.terminal ?? null;
  const ha = terminal?.home_assistant as Record<string, unknown> | undefined;
  const audioModule = config?.audio?.module;
  const audioPorts  = terminal?.audio_ports;

  return (
    <Stack spacing={2}>
      <Box>
        <SectionHeading
          title="Log level"
          meta={<Chip variant="outlined" label="-v" />}
        />
        <Field
          hint={`${logLevel === null ? 'Currently the level multi_rx started with. ' : ''}`
            + 'Applies immediately to every channel, device and trunking module, '
            + "and goes to the decoder's stderr rather than this page."}
          sx={{ maxWidth: 420 }}
        >
          <TextField
            select
            disabled={!decoderRunning}
            value={logLevel ?? ''}
            onChange={(e) => setLogLevel(Number(e.target.value))}
            slotProps={{
              htmlInput: { 'aria-label': 'log verbosity' },
              // The decoder never reports its verbosity, so until this UI sets
              // one the value is genuinely unknown — and an empty box reads as
              // a broken control rather than a default.
              select: {
                displayEmpty: true,
                renderValue: (v: unknown) => (v === '' || v === null
                  ? <Box component="span" sx={{ color: 'text.disabled' }}>not set</Box>
                  : LOG_LEVEL_LABEL(Number(v))),
              },
            }}
            sx={{ width: 150 }}
          >
            {LOG_LEVELS.map((lvl) => (
              <MenuItem key={lvl} value={lvl}>{LOG_LEVEL_LABEL(lvl)}</MenuItem>
            ))}
          </TextField>
        </Field>
      </Box>

      <Divider />

      <Box>
        <SectionHeading title="How this instance was started" />
        <Box
          sx={{
            display: 'grid',
            // minmax(min(...)) so the grid cannot force a sideways scroll on a
            // narrow phone.
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))',
            gap: 1.5,
          }}
        >
          <InfoRow
            label="Terminal"
            value={orDash(terminal?.terminal_type)}
            tooltip="terminal.terminal_type — selects this web UI (ws:), the curses TUI, or a headless UDP port"
          />
          <InfoRow label="Terminal module" value={orDash(terminal?.module)} />
          <InfoRow
            label="Trunking module"
            value={orDash(config?.trunking?.module)}
            tooltip="tk_p25 / tk_smartnet / tk_trbo — which protocol's trunking logic is loaded"
          />
          <InfoRow
            label="Default channel"
            value={orDash(terminal?.default_channel)}
            tooltip="Channel focused when a browser first connects"
          />
          <InfoRow
            label="Plot interval"
            value={terminal?.http_plot_interval !== undefined
              ? `${terminal.http_plot_interval} s`
              : '1 s (default)'}
            tooltip="How often the decoder emits a plot frame to this UI (http_plot_interval)"
          />
          <InfoRow
            label="Local speaker output"
            value={audioModule || 'off — audio goes to the browser'}
            tooltip="audio.module. A unicast UDP port has one consumer, so a port claimed here is not available to the browser stream."
          />
          <InfoRow
            label="Browser audio ports"
            value={Array.isArray(audioPorts) && audioPorts.length > 0
              ? audioPorts.join(', ')
              : 'discovered from the channels'}
            tooltip="terminal.audio_ports — an explicit override that wins over discovery"
          />
          <InfoRow
            label="Speech-to-text"
            value={ha?.enabled ? orDash(ha.stt_engine) : 'not configured'}
            tooltip="Home Assistant STT engine used to transcribe captured calls"
          />
        </Box>
        <Hint>
          These are read once at startup, so changing one takes a restart — but
          they are editable now: see the <strong>Settings</strong> tab, which
          marks each field live or restart-required, and <strong>Advanced JSON</strong>
          for anything the form does not cover. The log level above is applied
          immediately and is not stored. Per-channel controls (fine tune, symbol
          capture, list reload) live in Tuning &amp; Diagnostics.
        </Hint>
      </Box>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// Interface tab
// ---------------------------------------------------------------------------

/** Everything on this tab is a browser preference kept in localStorage — it
 *  never reaches the decoder, so two people watching the same receiver can set
 *  it differently. */
function InterfaceTab() {
  const { mode, toggleTheme, primaryColor, setPrimaryColor } = useThemeService();
  const [smartColors, setSmartColors] = useSmartColorsEnabled();

  return (
    <Stack spacing={2}>
      <Box>
        <SectionHeading title="Theme" />
        <ToggleButtonGroup
          exclusive
          value={mode}
          onChange={(_e, v: 'light' | 'dark' | null) => { if (v && v !== mode) toggleTheme(); }}
          aria-label="colour theme"
        >
          <ToggleButton value="light" aria-label="light theme">
            <Brightness7Icon fontSize="small" sx={{ mr: 0.5 }} /> Light
          </ToggleButton>
          <ToggleButton value="dark" aria-label="dark theme">
            <Brightness4Icon fontSize="small" sx={{ mr: 0.5 }} /> Dark
          </ToggleButton>
        </ToggleButtonGroup>
        <Hint>
          Follows the device's own light/dark setting until you choose here or
          from the header, after which your choice is remembered on this browser.
        </Hint>
      </Box>

      <Divider />

      <Box>
        <SectionHeading title="Accent colour" />
        <ControlRow>
          {PRESET_PRIMARY_COLORS.map((c) => (
            <Tooltip key={c.label} title={c.label}>
              <Chip
                label={c.label}
                onClick={() => setPrimaryColor(c)}
                variant={c.label === primaryColor.label ? 'filled' : 'outlined'}
                aria-pressed={c.label === primaryColor.label}
                sx={{
                  bgcolor: c.label === primaryColor.label ? c.main : undefined,
                  color: c.label === primaryColor.label ? '#fff' : undefined,
                  borderColor: c.main,
                }}
              />
            </Tooltip>
          ))}
        </ControlRow>
        <Hint>Used for the header, links, and every active control.</Hint>
      </Box>

      <Divider />

      <Box>
        <SectionHeading title="Talkgroup colours" />
        <FormControlLabel
          control={
            <Switch
              checked={smartColors}
              onChange={(e) => setSmartColors(e.target.checked)}
            />
          }
          label="Smart colours"
        />
        <Hint>
          Tint talkgroup tags by keyword, using the <code>smart_colors</code>{' '}
          rules from the config (fire, law, EMS by default).
        </Hint>
      </Box>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

/** One editor instance is shared by Settings, Advanced and History: they read
 *  the same document, and three copies would each re-fetch and then disagree
 *  about what was saved. */
const TABS = [
  { label: 'Settings',       needsEditor: true  },
  { label: 'Decoder',        needsEditor: false },
  { label: 'Interface',      needsEditor: false },
  { label: 'Advanced JSON',  needsEditor: true  },
  { label: 'History',        needsEditor: true  },
  { label: 'Running config', needsEditor: false },
] as const;

/**
 * Configuration, as far as a browser can go.
 *
 * The aim of this fork is a scanner run from a GUI, so the settings that used
 * to be command-line flags or config-file-only belong somewhere visible. Today
 * that is one runtime decoder knob, the browser's own display preferences, and
 * a read-only view of the loaded JSON. When the UI grows to drive more than
 * `multi_rx`, this is where a per-app settings panel goes.
 */
export default function ConfigDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState(0);
  // Only load while the dialog is open: /api/config/state serialises the whole
  // config, and nothing here changes on its own.
  const editor = useConfigEditor(open && TABS[tab].needsEditor);

  const panel = () => {
    switch (TABS[tab].label) {
      case 'Settings':       return <SettingsTab editor={editor} />;
      case 'Decoder':        return <DecoderTab />;
      case 'Interface':      return <InterfaceTab />;
      case 'Advanced JSON':  return <AdvancedJsonTab editor={editor} />;
      case 'History':        return <HistoryTab editor={editor} />;
      default:               return <RunningConfigPanel />;
    }
  };

  return (
    <DialogShell
      open={open}
      onClose={onClose}
      title="Configuration"
      subheader={
        <Tabs
          value={tab}
          onChange={(_e, v: number) => setTab(v)}
          variant="scrollable"
          // Six tabs no longer fit a 390px phone, so the row does scroll now --
          // but still without MUI's arrows, which render even when not needed and
          // sit on top of the first label.
          scrollButtons={false}
          aria-label="configuration sections"
          sx={{ mt: 0.5, minHeight: 40 }}
        >
          {TABS.map((t) => <Tab key={t.label} label={t.label} sx={{ minWidth: 88 }} />)}
        </Tabs>
      }
    >
      {/* One panel at a time; unmounting the others keeps the JSON block from
          re-serialising while the Interface tab is open. */}
      <Box role="tabpanel">{panel()}</Box>
    </DialogShell>
  );
}
