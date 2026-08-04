import React, { useState } from 'react';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Drawer from '@mui/material/Drawer';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import MenuIcon from '@mui/icons-material/Menu';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import RadioIcon from '@mui/icons-material/Radio';
import FormControlLabel from '@mui/material/FormControlLabel';
import Menu from '@mui/material/Menu';
import Switch from '@mui/material/Switch';
import Tooltip from '@mui/material/Tooltip';
import SettingsIcon from '@mui/icons-material/Settings';
import { useThemeService } from '../../services/themeService';
import { useWebSocketService } from '../../services/websocketService';
import { useSystemState } from '../../hooks/useSystemState';
import { useSmartColorsEnabled } from '../../hooks/useSmartColor';

export interface NavItem {
  label: string;
  href?: string;
  onClick?: () => void;
}

interface HeaderProps {
  navItems: NavItem[];
}

const DRAWER_WIDTH = 240;
const APP_TITLE = 'OP25';

const CONNECTION_LABEL: Record<string, string> = {
  open:       'connected',
  connecting: 'connecting',
  closed:     'offline',
  error:      'error',
};

/** Compact uptime: 45s, 12m, 3h 07m, 2d 04h. */
function formatUptime(secs: number): string {
  if (!Number.isFinite(secs) || secs < 0) return '';
  if (secs < 60)    return `${Math.floor(secs)}s`;
  if (secs < 3600)  return `${Math.floor(secs / 60)}m`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ${String(Math.floor((secs % 3600) / 60)).padStart(2, '0')}m`;
  return `${Math.floor(secs / 86400)}d ${String(Math.floor((secs % 86400) / 3600)).padStart(2, '0')}h`;
}

export default function Header({ navItems }: HeaderProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { mode, toggleTheme } = useThemeService();
  const { status } = useWebSocketService();
  const health = useSystemState();
  const [settingsAnchor, setSettingsAnchor] = useState<HTMLElement | null>(null);
  const [smartColors, setSmartColors] = useSmartColorsEnabled();

  const handleDrawerToggle = () => {
    setMobileOpen((prev) => !prev);
  };

  const drawer = (
    <Box onClick={handleDrawerToggle} sx={{ textAlign: 'center' }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 1,
          my: 2,
        }}
      >
        <RadioIcon />
        <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: '.1rem' }}>
          {APP_TITLE}
        </Typography>
      </Box>
      <Divider />
      <List>
        {navItems.map((item) => (
          <ListItem key={item.label} disablePadding>
            <ListItemButton
              sx={{ textAlign: 'left' }}
              {...(item.href
                ? { component: 'a', href: item.href }
                : { onClick: item.onClick })}
            >
              <ListItemText primary={item.label} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar component="nav" position="fixed">
        <Toolbar>
          {/* Hamburger — mobile only */}
          <IconButton
            color="inherit"
            aria-label="open navigation drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>

          {/* Logo section — desktop */}
          <Box
            sx={{
              display: { xs: 'none', sm: 'flex' },
              alignItems: 'center',
              gap: 1,
              mr: 3,
            }}
          >
            <RadioIcon />
            <Typography
              variant="h6"
              component="div"
              sx={{ fontWeight: 700, letterSpacing: '.1rem', whiteSpace: 'nowrap' }}
            >
              {APP_TITLE}
            </Typography>
          </Box>

          {/* Logo section — mobile (centered) */}
          <Box
            sx={{
              display: { xs: 'flex', sm: 'none' },
              alignItems: 'center',
              gap: 1,
              flexGrow: 1,
            }}
          >
            <RadioIcon />
            <Typography
              variant="h6"
              component="div"
              sx={{ fontWeight: 700, letterSpacing: '.1rem' }}
            >
              {APP_TITLE}
            </Typography>
          </Box>

          {/* Nav buttons — desktop */}
          <Box sx={{ flexGrow: 1, display: { xs: 'none', sm: 'flex' } }}>
            {navItems.map((item) => (
              <Button
                key={item.label}
                sx={{ color: 'inherit' }}
                {...(item.href
                  ? { component: 'a', href: item.href }
                  : { onClick: item.onClick })}
              >
                {item.label}
              </Button>
            ))}
          </Box>

          {/* Decoder health, distinct from socket state: the page can be
              connected to a server whose decoder has stopped answering. */}
          {health && (
            <Tooltip
              title={health.error_detail
                || `${health.site_name || 'decoder'}${health.trunk_id ? ` · ${health.trunk_id}` : ''} · up ${formatUptime(health.uptime)}`}
            >
              <Chip
                size="small"
                variant="outlined"
                label={health.status === 'running'
                  ? `decoder · ${formatUptime(health.uptime)}`
                  : `decoder ${health.status}`}
                sx={{
                  display: { xs: 'none', md: 'inline-flex' },
                  mr: 1,
                  color: 'inherit',
                  borderColor: health.status === 'running' ? 'currentColor' : 'error.light',
                }}
              />
            </Tooltip>
          )}

          {/* Connection state — a dot on phones, a labelled chip elsewhere,
              so the most important status is never the thing that wraps. */}
          <Chip
            size="small"
            variant="outlined"
            label={CONNECTION_LABEL[status]}
            sx={{
              display: { xs: 'none', sm: 'inline-flex' },
              mr: 1,
              color: 'inherit',
              borderColor: 'currentColor',
            }}
          />
          <Box
            aria-label={`connection ${CONNECTION_LABEL[status]}`}
            sx={{
              display: { xs: 'block', sm: 'none' },
              width: 10,
              height: 10,
              borderRadius: '50%',
              mr: 1,
              bgcolor: status === 'open' ? 'success.light'
                : status === 'connecting' ? 'warning.light' : 'error.light',
            }}
          />

          {/* Settings */}
          <Tooltip title="Display settings">
            <IconButton
              color="inherit"
              onClick={(e) => setSettingsAnchor(e.currentTarget)}
              aria-label="display settings"
              aria-haspopup="true"
            >
              <SettingsIcon />
            </IconButton>
          </Tooltip>
          <Menu
            anchorEl={settingsAnchor}
            open={Boolean(settingsAnchor)}
            onClose={() => setSettingsAnchor(null)}
          >
            <Box sx={{ px: 2, py: 1, maxWidth: 300 }}>
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={smartColors}
                    onChange={(e) => setSmartColors(e.target.checked)}
                  />
                }
                label={<Typography variant="body2">Smart colours</Typography>}
              />
              <Typography variant="caption" color="text.secondary" display="block">
                Tint talkgroup tags by keyword, using the{' '}
                <code>smart_colors</code> rules from the config (fire, law,
                EMS by default).
              </Typography>
            </Box>
          </Menu>

          {/* Theme toggle */}
          <IconButton
            color="inherit"
            onClick={toggleTheme}
            aria-label={`Switch to ${mode === 'light' ? 'dark' : 'light'} mode`}
          >
            {mode === 'dark' ? <Brightness7Icon /> : <Brightness4Icon />}
          </IconButton>
        </Toolbar>
      </AppBar>

      {/* Mobile navigation drawer */}
      <nav>
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': {
              boxSizing: 'border-box',
              width: DRAWER_WIDTH,
            },
          }}
        >
          {drawer}
        </Drawer>
      </nav>
    </Box>
  );
}
