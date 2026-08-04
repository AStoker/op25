import { useState } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Toolbar from '@mui/material/Toolbar';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import Header from './components/Header/Header';
import type { NavItem } from './components/Header/Header';
import { ThemeServiceProvider } from './services/themeService';
import { WebSocketServiceProvider } from './services/websocketService';
import { OP25ServiceProvider } from './services/op25Service';
import PlayerCard from './components/PlayerCard/PlayerCard';
import ChannelsCard from './components/ChannelsCard/ChannelsCard';
import BandPlanCard from './components/BandPlanCard/BandPlanCard';
import SiteInfoCard from './components/SiteInfoCard/SiteInfoCard';
import AdjacentSitesCard from './components/AdjacentSitesCard/AdjacentSitesCard';
import PatchesCard from './components/PatchesCard/PatchesCard';
import ReceiverCard from './components/ReceiverCard/ReceiverCard';
import SignalPlotsCard from './components/SignalPlotsCard/SignalPlotsCard';
import CallHistoryCard from './components/CallHistoryCard/CallHistoryCard';
import SubscribersCard from './components/SubscribersCard/SubscribersCard';
import TranscriptsCard from './components/TranscriptsCard/TranscriptsCard';

const navItems: NavItem[] = [
  { label: 'Settings', onClick: () => { /* TODO: open Settings dialog */ } },
  { label: 'Config', onClick: () => { /* TODO: open Config dialog */ } },
  { label: 'Legacy UI', href: '/' },
  { label: 'About', onClick: () => { /* TODO: open About dialog */ } },
];

/**
 * Mobile section grouping. A phone cannot usefully show nine cards at once,
 * so below the `md` breakpoint they are split across tabs; above it the
 * original two-column dashboard is kept, since a desktop user scanning for
 * activity wants everything visible without navigating.
 */
const SECTIONS = [
  { label: 'Live',   render: () => <><PlayerCard /><ChannelsCard /></> },
  { label: 'Audio',  render: () => <><TranscriptsCard /><CallHistoryCard /></> },
  { label: 'System', render: () => <><SiteInfoCard /><BandPlanCard /><AdjacentSitesCard /><PatchesCard /><SubscribersCard /></> },
  { label: 'Signal', render: () => <><ReceiverCard /><SignalPlotsCard /></> },
];

function MobileLayout() {
  const [tab, setTab] = useState(0);

  return (
    <>
      <Box
        sx={{
          position: 'sticky',
          // Sit directly under the fixed AppBar so the tab bar is always
          // reachable with a thumb, however far the content has scrolled.
          // 56/64 are MUI's default Toolbar heights at those breakpoints.
          top: { xs: 56, sm: 64 },
          zIndex: (t) => t.zIndex.appBar - 1,
          bgcolor: 'background.default',
          borderBottom: 1,
          borderColor: 'divider',
          mx: { xs: -1, sm: -2 },
          px: { xs: 1, sm: 2 },
          mb: 1.5,
        }}
      >
        <Tabs
          value={tab}
          onChange={(_e, v: number) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
        >
          {SECTIONS.map((s) => <Tab key={s.label} label={s.label} sx={{ minWidth: 88 }} />)}
        </Tabs>
      </Box>

      <Stack direction="column" spacing={1.5}>
        {SECTIONS[tab].render()}
      </Stack>
    </>
  );
}

function DesktopLayout() {
  return (
    <Stack direction="row" spacing={2} alignItems="flex-start">
      <Stack direction="column" spacing={2} sx={{ flex: 1, minWidth: 0 }}>
        <PlayerCard />
        <ChannelsCard />
        <TranscriptsCard />
        <CallHistoryCard />
        <SubscribersCard />
      </Stack>

      <Stack direction="column" spacing={2} sx={{ flex: 1, minWidth: 0 }}>
        <SiteInfoCard />
        <ReceiverCard />
        <SignalPlotsCard />
        <BandPlanCard />
        <AdjacentSitesCard />
        <PatchesCard />
      </Stack>
    </Stack>
  );
}

function AppShell() {
  const theme = useTheme();
  const compact = useMediaQuery(theme.breakpoints.down('md'));

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100dvh' }}>
      <Header navItems={navItems} />
      <Box
        component="main"
        sx={{
          px: { xs: 1, sm: 2, md: 3 },
          pt: { xs: 1, sm: 2 },
          // Clear the iOS home indicator when the page is scrolled to the end.
          pb: 'calc(env(safe-area-inset-bottom) + 16px)',
          width: '100%',
          maxWidth: '100%',
          overflowX: 'hidden',
        }}
      >
        {/* Offset below the fixed AppBar */}
        <Toolbar />
        {compact ? <MobileLayout /> : <DesktopLayout />}
      </Box>
    </Box>
  );
}

export default function App() {
  return (
    <ThemeServiceProvider>
      <WebSocketServiceProvider>
        <OP25ServiceProvider>
          <AppShell />
        </OP25ServiceProvider>
      </WebSocketServiceProvider>
    </ThemeServiceProvider>
  );
}
