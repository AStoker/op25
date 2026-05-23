import {
  AppBar, Toolbar, Box, Button, Tooltip, Alert, Collapse,
  Typography, IconButton, Chip,
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';
import InfoIcon from '@mui/icons-material/Info';
import ArticleIcon from '@mui/icons-material/Article';
import type { ControlStats } from '../hooks/useControl';

interface Props {
  connectionError: string | null;
  wsConnected: boolean;
  onOpenSettings: () => void;
  onOpenConfig: () => void;
  onOpenAbout: () => void;
  debugInfo: ControlStats;
}

export default function NavBar({ connectionError, wsConnected, onOpenSettings, onOpenConfig, onOpenAbout, debugInfo }: Props) {
  return (
    <>
      <AppBar position="sticky" elevation={0}>
        <Toolbar variant="dense" sx={{ gap: 0.5, minHeight: 48 }}>
          {/* Logo */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mr: 2 }}>
            <Box
              component="svg"
              viewBox="0 0 180 40"
              sx={{ height: 32, width: 'auto' }}
              xmlns="http://www.w3.org/2000/svg"
            >
              <polygon points="8,34 18,10 28,34" fill="#66aaff" />
              <rect x="8" y="34" width="20" height="3" fill="#ffaa55" rx="1" />
              <text x="34" y="28" fill="#ffffff" fontSize="20" fontFamily="Arial" fontWeight="bold">
                OP25
              </text>
            </Box>
            <Typography variant="caption" sx={{ color: 'text.secondary', display: { xs: 'none', sm: 'block' } }}>
              boatbod
            </Typography>
          </Box>

          {/* Nav buttons */}
          <Tooltip title="Open settings" arrow>
            <Button
              startIcon={<SettingsIcon fontSize="small" />}
              size="small"
              onClick={onOpenSettings}
              sx={{ color: 'text.secondary', '&:hover': { color: 'primary.main' } }}
            >
              Settings
            </Button>
          </Tooltip>

          <Tooltip title="View server-side configuration" arrow>
            <Button
              startIcon={<ArticleIcon fontSize="small" />}
              size="small"
              onClick={onOpenConfig}
              sx={{ color: 'text.secondary', '&:hover': { color: 'primary.main' } }}
            >
              Config
            </Button>
          </Tooltip>

          <Tooltip title="View legacy HTML UI" arrow>
            <Button
              size="small"
              component="a"
              href="legacy-index.html"
              sx={{ color: 'text.secondary', '&:hover': { color: 'primary.main' } }}
            >
              Legacy UI
            </Button>
          </Tooltip>

          <Box sx={{ flex: 1 }} />

          {/* Debug pill */}
          <Tooltip
            title={`Requests: ${debugInfo.requests} | WS OK: ${debugInfo.wsOk} | HTTP OK: ${debugInfo.httpOk} | Errors: ${debugInfo.errors} | Transport: ${wsConnected ? 'WebSocket' : 'HTTP'}`}
            arrow
          >
            <Chip
              label={wsConnected ? `WS: ${debugInfo.wsOk}` : `HTTP: ${debugInfo.httpOk}`}
              size="small"
              color={debugInfo.errors > 0 ? 'error' : wsConnected ? 'success' : 'default'}
              variant="outlined"
              sx={{ fontSize: '0.65rem', height: 20, cursor: 'default' }}
            />
          </Tooltip>

          <Tooltip title="About OP25" arrow>
            <IconButton size="small" onClick={onOpenAbout} sx={{ color: 'text.secondary' }}>
              <InfoIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      {/* Connection error banner */}
      <Collapse in={!!connectionError}>
        <Alert
          severity="error"
          variant="filled"
          sx={{ borderRadius: 0, py: 0.5, fontSize: '0.8rem' }}
        >
          {connectionError}
        </Alert>
      </Collapse>
    </>
  );
}
