import { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Box, Button,
  Typography, Switch, FormControlLabel, Select, MenuItem,
  InputLabel, FormControl, Divider, Tooltip, TextField,
  IconButton, Chip, Alert,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StopIcon from '@mui/icons-material/Stop';
import type { Settings } from '../types';

interface DebugInfo {
  requestCount: number;
  httpOk: number;
  httpErrors: number;
  fetchErrors: number;
}

interface Props {
  open: boolean;
  settings: Settings;
  onClose: () => void;
  onUpdate: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  captureActive: boolean;
  onCapture: () => void;
  onDumpTgids: () => void;
  onDumpBuffer: () => void;
  onSetLogVerbosity: (level: number) => void;
  streamUrl: string | null;
  debugInfo: DebugInfo;
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
  open, settings, onClose, onUpdate, captureActive,
  onCapture, onDumpTgids, onDumpBuffer, onSetLogVerbosity,
  streamUrl, debugInfo,
}: Props) {
  const [logLevel, setLogLevel] = useState(0);

  const Toggle = ({ item }: { item: ToggleKey }) => (
    <Tooltip title={item.tooltip ?? ''} placement="right" arrow>
      <FormControlLabel
        control={
          <Switch
            size="small"
            checked={!!settings[item.key]}
            onChange={(e) => onUpdate(item.key, e.target.checked as Settings[typeof item.key])}
          />
        }
        label={<Typography variant="body2">{item.label}</Typography>}
        sx={{ mr: 0, mb: 0.5 }}
      />
    </Tooltip>
  );

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center' }}>
        <Typography variant="h6" sx={{ flex: 1 }}>Settings</Typography>
        <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: 2 }}>
        {/* Server URL */}
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
            OP25 Server
          </Typography>
          <Tooltip
            title="Base URL of the OP25 HTTP server. Leave empty to use the same origin as this page. Example: http://192.168.1.10:8080"
            placement="right"
            arrow
          >
            <TextField
              fullWidth
              size="small"
              label="Server URL"
              placeholder="http://192.168.1.10:8080  (empty = same origin)"
              value={settings.serverUrl}
              onChange={(e) => onUpdate('serverUrl', e.target.value.trim())}
              sx={{ mt: 0.75 }}
              InputProps={{ sx: { fontFamily: 'monospace', fontSize: '0.82rem' } }}
            />
          </Tooltip>
          {settings.serverUrl && (
            <Alert severity="info" sx={{ mt: 0.75, py: 0.25, fontSize: '0.72rem' }}>
              Connecting to <strong>{settings.serverUrl}</strong>. The OP25 server must have CORS enabled or be served on the same origin.
            </Alert>
          )}
        </Box>

        <Divider />

        {/* Toggle groups */}
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

        {/* Select controls */}
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
          <FormControl size="small">
            <InputLabel>Call History Source</InputLabel>
            <Select
              label="Call History Source"
              value={settings.callHistorySource}
              onChange={(e) => onUpdate('callHistorySource', e.target.value as Settings['callHistorySource'])}
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
              value={settings.subscriberMode}
              onChange={(e) => onUpdate('subscriberMode', e.target.value as Settings['subscriberMode'])}
            >
              <MenuItem value="all">All Systems</MenuItem>
              <MenuItem value="selected">Current System</MenuItem>
            </Select>
          </FormControl>

          <TextField
            label="Max History Rows"
            type="number"
            size="small"
            value={settings.callHistoryMaxRows}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10);
              if (n > 0 && n <= 10000) onUpdate('callHistoryMaxRows', n);
            }}
            inputProps={{ min: 50, max: 10000, step: 50 }}
          />

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" sx={{ minWidth: 70 }}>Accent Color</Typography>
            <Tooltip title="Accent / primary color for the interface" arrow>
              <input
                type="color"
                value={settings.accentColor}
                onChange={(e) => onUpdate('accentColor', e.target.value)}
                style={{
                  width: 36,
                  height: 36,
                  border: 'none',
                  background: 'none',
                  cursor: 'pointer',
                  padding: 0,
                }}
              />
            </Tooltip>
            <Typography variant="caption" color="text.secondary">{settings.accentColor}</Typography>
          </Box>
        </Box>

        <Divider />

        {/* Actions */}
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
              <Button size="small" variant="outlined" onClick={onDumpTgids}>
                Dump TGIDs
              </Button>
            </Tooltip>

            <Tooltip title="Force buffer dump" arrow>
              <Button size="small" variant="outlined" onClick={onDumpBuffer}>
                Dump Buffer
              </Button>
            </Tooltip>
          </Box>
        </Box>

        {/* Log verbosity */}
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
              <Button size="small" variant="outlined" onClick={() => onSetLogVerbosity(logLevel)}>
                Set Level
              </Button>
            </Tooltip>
          </Box>
        </Box>

        {/* Stream URL */}
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

        {/* Debug Info */}
        <Divider />
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
            Debug Info
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 0.75 }}>
            <Chip label={`Requests: ${debugInfo.requestCount}`} size="small" variant="outlined" />
            <Chip label={`HTTP OK: ${debugInfo.httpOk}`} size="small" color="success" variant="outlined" />
            {debugInfo.httpErrors > 0 && (
              <Chip label={`HTTP Errors: ${debugInfo.httpErrors}`} size="small" color="error" variant="outlined" />
            )}
            {debugInfo.fetchErrors > 0 && (
              <Chip label={`Fetch Errors: ${debugInfo.fetchErrors}`} size="small" color="warning" variant="outlined" />
            )}
          </Box>
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
