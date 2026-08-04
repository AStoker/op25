import { useState, useRef, useEffect } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Box, Button,
  Typography, Switch, FormControlLabel, Select, MenuItem,
  InputLabel, FormControl, Divider, Tooltip, TextField,
  IconButton, Chip, Alert, CircularProgress,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StopIcon from '@mui/icons-material/Stop';
import WifiIcon from '@mui/icons-material/Wifi';
import WifiOffIcon from '@mui/icons-material/WifiOff';
import type { Settings } from '../types';
import type { ControlStats } from '../hooks/useControl';
import { normalizeServerUrl, deriveWsUrl } from '../hooks/useControl';

interface Props {
  open: boolean;
  settings: Settings;
  onClose: () => void;
  /** Called with the full committed settings when the user clicks Save. */
  onSave: (settings: Settings) => void;
  captureActive: boolean;
  onCapture: () => void;
  onDumpTgids: () => void;
  onDumpBuffer: () => void;
  onSetLogVerbosity: (level: number) => void;
  streamUrl: string | null;
  wsConnected: boolean;
  debugInfo: ControlStats;
}

type ToggleKey = {
  key: keyof Settings;
  label: string;
  tooltip?: string;
};

const TOGGLE_GROUPS: { group: string; items: ToggleKey[] }[] = [
  {
    group: 'Display',
    items: [
      { key: 'smartColors', label: 'Smart Colors', tooltip: 'Color-code talkgroup names by keyword' },
      { key: 'showBandPlan', label: 'Show Band Plan', tooltip: 'Display P25 band plan table' },
      { key: 'showAdjacentSites', label: 'Show Adjacent Sites', tooltip: 'Display adjacent sites section' },
      { key: 'radioIdInFreqTable', label: 'Radio ID in Freq Table', tooltip: 'Show source radio IDs in frequency table' },
      { key: 'showChannelsTable', label: 'Show Channels Table', tooltip: 'Display the channel list panel' },
    ],
  },
  {
    group: 'Call History',
    items: [
      { key: 'showCallHistory', label: 'Show Call History', tooltip: 'Display call history panel' },
    ],
  },
  {
    group: 'Subscribers',
    items: [
      { key: 'trackSubscribers', label: 'Track Subscribers', tooltip: 'Show subscriber (radio) tracking table' },
    ],
  },
  {
    group: 'Audio',
    items: [
      { key: 'muteAudioAtStartup', label: 'Mute Audio at Startup', tooltip: 'Start with WebSocket audio muted' },
    ],
  },
];

export default function SettingsDialog({
  open, settings, onClose, onSave, captureActive,
  onCapture, onDumpTgids, onDumpBuffer, onSetLogVerbosity,
  streamUrl, wsConnected, debugInfo,
}: Props) {
  // ── Draft state (staged until Save is clicked) ────────────────────────
  const [draft, setDraft] = useState<Settings>(settings);
  const prevOpenRef = useRef(false);

  // Reset draft each time the dialog transitions from closed → open
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setDraft(settings);
      setConnectState('idle');
      setConnectMsg('');
    }
    prevOpenRef.current = open;
  }, [open, settings]);

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    if (key === 'serverUrl') setConnectState('idle');
  };

  const handleSave = () => {
    onSave({ ...draft, serverUrl: normalizeServerUrl(draft.serverUrl) });
    onClose();
  };

  const handleClose = () => {
    setDraft(settings); // discard unsaved edits
    onClose();
  };

  // ── Connection test ────────────────────────────────────────────────────
  const [connectState, setConnectState] = useState<'idle' | 'testing' | 'ok' | 'error'>('idle');
  const [connectMsg, setConnectMsg] = useState('');

  const testConnection = async () => {
    setConnectState('testing');
    setConnectMsg('');
    const normalized = normalizeServerUrl(draft.serverUrl);
    const endpoint = normalized ? normalized.replace(/\/+$/, '') + '/' : '/';
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      try {
        const res = await fetch(endpoint, { signal: controller.signal });
        if (res.status === 426) {
          setConnectState('error');
          setConnectMsg('HTTP 426 — this looks like a WebSocket-only port. Use the OP25 HTTP server port instead (e.g. 8080).');
        } else {
          setConnectState('ok');
          setConnectMsg(`HTTP ${res.status} — server reached`);
        }
      } finally {
        clearTimeout(timer);
      }
    } catch (err) {
      setConnectState('error');
      setConnectMsg(err instanceof Error ? err.message : 'Connection failed');
    }
  };

  // ── Local non-setting state ────────────────────────────────────────────
  const [logLevel, setLogLevel] = useState(0);

  const Toggle = ({ item }: { item: ToggleKey }) => (
    <Tooltip title={item.tooltip ?? ''} placement="right" arrow>
      <FormControlLabel
        control={
          <Switch
            size="small"
            checked={!!draft[item.key]}
            onChange={(e) => update(item.key, e.target.checked as Settings[typeof item.key])}
          />
        }
        label={<Typography variant="body2">{item.label}</Typography>}
        sx={{ mr: 0, mb: 0.5 }}
      />
    </Tooltip>
  );

  // Derived control WS URL shown as a hint below the server URL field
  const normalizedUrl = normalizeServerUrl(draft.serverUrl);
  const wsControlUrl  = normalizedUrl ? deriveWsUrl(normalizedUrl) : deriveWsUrl('');

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="h6" sx={{ flex: 1 }}>Settings</Typography>
        <Chip
          size="small"
          icon={
            wsConnected
              ? <WifiIcon sx={{ fontSize: '14px !important' }} />
              : <WifiOffIcon sx={{ fontSize: '14px !important' }} />
          }
          label={wsConnected ? 'WS Live' : 'HTTP Fallback'}
          color={wsConnected ? 'success' : 'default'}
          variant="outlined"
          sx={{ fontSize: '0.65rem', height: 22 }}
        />
        <IconButton size="small" onClick={handleClose}><CloseIcon fontSize="small" /></IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 2 }}>

        {/* ── OP25 Server URL ── */}
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
            OP25 Server
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, mt: 0.75 }}>
            <Tooltip
              title="HTTP base URL of the OP25 server — e.g. http://192.168.1.10:8080. Leave empty when this page is served directly from OP25. The WebSocket control channel opens on HTTP port+1 (e.g. 8081). Audio WebSocket ports come from the OP25 channel config and are unaffected."
              placement="right"
              arrow
            >
              <TextField
                fullWidth
                size="small"
                label="Server URL"
                placeholder="http://192.168.1.10:8080  (empty = same origin)"
                value={draft.serverUrl}
                onChange={(e) => update('serverUrl', e.target.value)}
                InputProps={{ sx: { fontFamily: 'monospace', fontSize: '0.82rem' } }}
              />
            </Tooltip>
            <Tooltip title="Test HTTP connectivity to the configured server (does not save)" arrow>
              <span>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={testConnection}
                  disabled={connectState === 'testing'}
                  sx={{ whiteSpace: 'nowrap', minWidth: 90 }}
                >
                  {connectState === 'testing'
                    ? <CircularProgress size={14} sx={{ mx: 1 }} />
                    : 'Connect'}
                </Button>
              </span>
            </Tooltip>
          </Box>

          {connectState === 'ok' && (
            <Alert severity="success" sx={{ mt: 0.75, py: 0.25, fontSize: '0.72rem' }}>{connectMsg}</Alert>
          )}
          {connectState === 'error' && (
            <Alert severity="error" sx={{ mt: 0.75, py: 0.25, fontSize: '0.72rem' }}>{connectMsg}</Alert>
          )}
          {connectState === 'idle' && (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary', fontFamily: 'monospace', fontSize: '0.7rem' }}>
              Control WS → {wsControlUrl}
            </Typography>
          )}
        </Box>

        <Divider />

        {/* ── Toggle groups ── */}
        {TOGGLE_GROUPS.map(({ group, items }) => (
          <Box key={group}>
            <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
              {group}
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', mt: 0.5 }}>
              {items.map((item) => <Toggle key={item.key as string} item={item} />)}
            </Box>
          </Box>
        ))}

        <Divider />

        {/* ── Selects / numeric inputs ── */}
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
          <FormControl size="small">
            <InputLabel>Call History Source</InputLabel>
            <Select
              label="Call History Source"
              value={draft.callHistorySource}
              onChange={(e) => update('callHistorySource', e.target.value as Settings['callHistorySource'])}
            >
              <MenuItem value="frequency">Frequency Data</MenuItem>
              <MenuItem value="voice">Voice Grants</MenuItem>
              <MenuItem value="display">Display</MenuItem>
            </Select>
          </FormControl>

          <FormControl size="small">
            <InputLabel>Subscriber Mode</InputLabel>
            <Select
              label="Subscriber Mode"
              value={draft.subscriberMode}
              onChange={(e) => update('subscriberMode', e.target.value as Settings['subscriberMode'])}
            >
              <MenuItem value="all">All Systems</MenuItem>
              <MenuItem value="selected">Current System</MenuItem>
            </Select>
          </FormControl>

          <TextField
            label="Max History Rows"
            type="number"
            size="small"
            value={draft.callHistoryMaxRows}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10);
              if (n > 0 && n <= 10000) update('callHistoryMaxRows', n);
            }}
            inputProps={{ min: 50, max: 10000, step: 50 }}
          />

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" sx={{ minWidth: 70 }}>Accent Color</Typography>
            <Tooltip title="Accent / primary color for the interface" arrow>
              <input
                type="color"
                value={draft.accentColor}
                onChange={(e) => update('accentColor', e.target.value)}
                style={{ width: 36, height: 36, border: 'none', background: 'none', cursor: 'pointer', padding: 0 }}
              />
            </Tooltip>
            <Typography variant="caption" color="text.secondary">{draft.accentColor}</Typography>
          </Box>
        </Box>

        <Divider />

        {/* ── Immediate actions (not part of staged settings) ── */}
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
            Actions
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
            <Tooltip title={captureActive ? 'Stop IQ capture' : 'Start IQ capture'} arrow>
              <Button
                size="small"
                variant={captureActive ? 'contained' : 'outlined'}
                color={captureActive ? 'error' : 'primary'}
                startIcon={captureActive ? <StopIcon /> : <FiberManualRecordIcon />}
                onClick={onCapture}
              >
                {captureActive ? 'Stop Capture' : 'Start Capture'}
              </Button>
            </Tooltip>

            <Tooltip title="Dump talkgroup IDs and tracking state to log" arrow>
              <Button size="small" variant="outlined" onClick={onDumpTgids}>Dump TGIDs</Button>
            </Tooltip>

            <Tooltip title="Force buffer dump" arrow>
              <Button size="small" variant="outlined" onClick={onDumpBuffer}>Dump Buffer</Button>
            </Tooltip>
          </Box>
        </Box>

        {/* ── Log verbosity ── */}
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
            Log Verbosity
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.75 }}>
            <TextField
              type="number"
              size="small"
              value={logLevel}
              onChange={(e) => setLogLevel(parseInt(e.target.value, 10))}
              inputProps={{ min: 0, max: 10 }}
              sx={{ width: 80 }}
            />
            <Tooltip title="Set log verbosity level on the receiver" arrow>
              <Button size="small" variant="outlined" onClick={() => onSetLogVerbosity(logLevel)}>Set Level</Button>
            </Tooltip>
          </Box>
        </Box>

        {/* ── Stream URL ── */}
        {streamUrl && (
          <>
            <Divider />
            <Box>
              <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
                Current Stream URL
              </Typography>
              <Typography variant="body2" sx={{ mt: 0.5, wordBreak: 'break-all', fontFamily: 'monospace', color: 'text.secondary' }}>
                {streamUrl}
              </Typography>
            </Box>
          </>
        )}

        {/* ── Debug Info ── */}
        <Divider />
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
            Debug Info
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 0.75 }}>
            <Chip label={`Requests: ${debugInfo.requests}`} size="small" variant="outlined" />
            <Chip label={`WS OK: ${debugInfo.wsOk}`}        size="small" color="success" variant="outlined" />
            <Chip label={`HTTP OK: ${debugInfo.httpOk}`}    size="small" variant="outlined" />
            {debugInfo.errors > 0 && (
              <Chip label={`Errors: ${debugInfo.errors}`} size="small" color="error" variant="outlined" />
            )}
          </Box>
        </Box>

      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained" color="primary">Save</Button>
      </DialogActions>
    </Dialog>
  );
}
