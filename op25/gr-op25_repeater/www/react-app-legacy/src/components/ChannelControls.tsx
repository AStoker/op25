import { useState } from 'react';
import {
  Paper, Box, Button, ButtonGroup, Tooltip, Typography,
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Divider,
} from '@mui/material';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import BlockIcon from '@mui/icons-material/Block';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import NavigateBeforeIcon from '@mui/icons-material/NavigateBefore';
import NavigateNextIcon from '@mui/icons-material/NavigateNext';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import StopIcon from '@mui/icons-material/Stop';
import FastRewindIcon from '@mui/icons-material/FastRewind';
import FastForwardIcon from '@mui/icons-material/FastForward';
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious';
import SkipNextOutlinedIcon from '@mui/icons-material/SkipNextOutlined';

type TuneDir = 'ld' | 'sd' | 'su' | 'lu';

interface Props {
  captureActive: boolean;
  errorVal: number | null;
  currentTgid: number | null;
  onScan: () => void;
  onHold: (tgid: number) => void;
  onLockout: (tgid?: number) => void;
  onWhitelist: (tgid?: number) => void;
  onPrevChannel: () => void;
  onNextChannel: () => void;
  onTune: (dir: TuneDir) => void;
  onCapture: () => void;
  onDumpTgids: () => void;
  onDumpBuffer: () => void;
  onSetLogVerbosity: (level: number) => void;
  onTogglePlot: (type: string) => void;
}

export default function ChannelControls({
  captureActive, errorVal, currentTgid,
  onScan, onHold, onLockout, onWhitelist,
  onPrevChannel, onNextChannel, onTune, onCapture,
}: Props) {
  const [gotoOpen, setGotoOpen] = useState(false);
  const [gotoValue, setGotoValue] = useState('');
  const [lockoutOpen, setLockoutOpen] = useState(false);
  const [lockoutValue, setLockoutValue] = useState('');
  const [whitelistOpen, setWhitelistOpen] = useState(false);
  const [whitelistValue, setWhitelistValue] = useState('');

  const handleGotoConfirm = () => {
    const tgid = parseInt(gotoValue, 10);
    if (!isNaN(tgid) && tgid >= 0 && tgid <= 65535) {
      onHold(tgid);
    }
    setGotoOpen(false);
    setGotoValue('');
  };

  const handleLockoutConfirm = () => {
    const tgid = parseInt(lockoutValue, 10);
    if (!isNaN(tgid) && tgid > 0 && tgid <= 65534) {
      onLockout(tgid);
    }
    setLockoutOpen(false);
    setLockoutValue('');
  };

  const handleWhitelistConfirm = () => {
    const tgid = parseInt(whitelistValue, 10);
    if (!isNaN(tgid) && tgid > 0 && tgid <= 65534) {
      onWhitelist(tgid);
    }
    setWhitelistOpen(false);
    setWhitelistValue('');
  };

  const btnSx = { minWidth: 0, px: 1.5, fontWeight: 700, fontSize: '0.72rem' };

  return (
    <Paper elevation={1} sx={{ p: 1.5, border: '1px solid #2a2a2a' }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>

        {/* Scan control buttons */}
        <ButtonGroup size="small" variant="outlined">
          <Tooltip title="Skip current talkgroup and resume scanning" arrow>
            <Button sx={btnSx} startIcon={<SkipNextIcon />} onClick={onScan}>
              SCAN
            </Button>
          </Tooltip>

          <Tooltip title="Hold on the current talkgroup (stops scanning)" arrow>
            <Button sx={btnSx} startIcon={<PauseCircleIcon />} onClick={() => onHold(currentTgid ?? 0)}>
              HOLD
            </Button>
          </Tooltip>

          <Tooltip title="Lockout (blacklist) the current talkgroup" arrow>
            <Button
              sx={btnSx}
              startIcon={<BlockIcon />}
              color="warning"
              onClick={() => {
                if (currentTgid != null) onLockout(currentTgid);
                else { setLockoutValue(''); setLockoutOpen(true); }
              }}
            >
              LOCKOUT
            </Button>
          </Tooltip>

          <Tooltip title="Whitelist a talkgroup (allow it to be decoded)" arrow>
            <Button
              sx={btnSx}
              startIcon={<CheckCircleIcon />}
              color="success"
              onClick={() => { setWhitelistValue(''); setWhitelistOpen(true); }}
            >
              WHITELIST
            </Button>
          </Tooltip>
        </ButtonGroup>

        <Tooltip title="Go to (hold on) a specific talkgroup ID" arrow>
          <Button
            size="small"
            variant="contained"
            color="primary"
            sx={{ ...btnSx, color: '#000' }}
            onClick={() => { setGotoValue(currentTgid != null ? String(currentTgid) : ''); setGotoOpen(true); }}
          >
            GO TO
          </Button>
        </Tooltip>

        <Divider orientation="vertical" flexItem />

        {/* Channel navigation */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Tooltip title="Previous channel" arrow>
            <Button size="small" variant="outlined" sx={{ minWidth: 32, px: 0.5 }} onClick={onPrevChannel}>
              <NavigateBeforeIcon fontSize="small" />
            </Button>
          </Tooltip>
          <Tooltip title="Next channel" arrow>
            <Button size="small" variant="outlined" sx={{ minWidth: 32, px: 0.5 }} onClick={onNextChannel}>
              <NavigateNextIcon fontSize="small" />
            </Button>
          </Tooltip>
        </Box>

        <Divider orientation="vertical" flexItem />

        {/* Frequency tuning */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>Tune:</Typography>
          <Tooltip title="Large step down" arrow>
            <Button size="small" variant="outlined" sx={{ minWidth: 32, px: 0.5 }} onClick={() => onTune('ld')}>
              <FastRewindIcon fontSize="small" />
            </Button>
          </Tooltip>
          <Tooltip title="Small step down" arrow>
            <Button size="small" variant="outlined" sx={{ minWidth: 32, px: 0.5 }} onClick={() => onTune('sd')}>
              <SkipPreviousIcon fontSize="small" />
            </Button>
          </Tooltip>
          <Tooltip title="Small step up" arrow>
            <Button size="small" variant="outlined" sx={{ minWidth: 32, px: 0.5 }} onClick={() => onTune('su')}>
              <SkipNextOutlinedIcon fontSize="small" />
            </Button>
          </Tooltip>
          <Tooltip title="Large step up" arrow>
            <Button size="small" variant="outlined" sx={{ minWidth: 32, px: 0.5 }} onClick={() => onTune('lu')}>
              <FastForwardIcon fontSize="small" />
            </Button>
          </Tooltip>
        </Box>

        <Divider orientation="vertical" flexItem />

        {/* Capture */}
        <Tooltip title={captureActive ? 'Stop capturing IQ data' : 'Start capturing IQ data to file'} arrow>
          <Button
            size="small"
            variant={captureActive ? 'contained' : 'outlined'}
            color={captureActive ? 'error' : 'inherit'}
            startIcon={captureActive ? <StopIcon /> : <FiberManualRecordIcon />}
            sx={btnSx}
            onClick={onCapture}
          >
            {captureActive ? 'STOP CAP' : 'CAPTURE'}
          </Button>
        </Tooltip>

        {/* Error display */}
        {errorVal !== null && errorVal !== 0 && (
          <Tooltip title="Frequency error in Hz (fine tune offset)" arrow>
            <Typography
              variant="caption"
              sx={{ color: Math.abs(errorVal) > 1000 ? 'warning.main' : 'text.secondary', ml: 'auto' }}
            >
              Err: {errorVal} Hz
            </Typography>
          </Tooltip>
        )}
      </Box>

      {/* Go To dialog */}
      <Dialog open={gotoOpen} onClose={() => setGotoOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Go To Talkgroup</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Talkgroup ID (0–65535)"
            type="number"
            value={gotoValue}
            onChange={(e) => setGotoValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleGotoConfirm()}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGotoOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleGotoConfirm}>Hold</Button>
        </DialogActions>
      </Dialog>

      {/* Lockout dialog */}
      <Dialog open={lockoutOpen} onClose={() => setLockoutOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Lockout (Blacklist) Talkgroup</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Talkgroup ID (1–65534)"
            type="number"
            value={lockoutValue}
            onChange={(e) => setLockoutValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleLockoutConfirm()}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLockoutOpen(false)}>Cancel</Button>
          <Button variant="contained" color="warning" onClick={handleLockoutConfirm}>Lockout</Button>
        </DialogActions>
      </Dialog>

      {/* Whitelist dialog */}
      <Dialog open={whitelistOpen} onClose={() => setWhitelistOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Whitelist Talkgroup</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Talkgroup ID (1–65534)"
            type="number"
            value={whitelistValue}
            onChange={(e) => setWhitelistValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleWhitelistConfirm()}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setWhitelistOpen(false)}>Cancel</Button>
          <Button variant="contained" color="success" onClick={handleWhitelistConfirm}>Whitelist</Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
