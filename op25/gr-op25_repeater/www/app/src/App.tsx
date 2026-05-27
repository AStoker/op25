
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Toolbar from '@mui/material/Toolbar';
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
import SignalPlotsCard from './components/SignalPlotsCard/SignalPlotsCard';
import CallHistoryCard from './components/CallHistoryCard/CallHistoryCard';
import SubscribersCard from './components/SubscribersCard/SubscribersCard';

const navItems: NavItem[] = [
  { label: 'Settings', onClick: () => { /* TODO: open Settings dialog */ } },
  { label: 'Config', onClick: () => { /* TODO: open Config dialog */ } },
  { label: 'Legacy UI', href: '/' },
  { label: 'About', onClick: () => { /* TODO: open About dialog */ } },
];

export default function App() {
  return (
    <ThemeServiceProvider>
      <WebSocketServiceProvider>
        <OP25ServiceProvider>
          <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            <Header navItems={navItems} />
            <Box component="main" sx={{ p: 3 }}>
              {/* Offset below the fixed AppBar */}
              <Toolbar />
              <Stack
                direction={{ xs: 'column', md: 'row' }}
                spacing={2}
                alignItems="flex-start"
              >
                <Stack direction="column" spacing={2} sx={{ flex: 1, width: '100%' }}>
                  <PlayerCard />
                  <ChannelsCard />
                  <CallHistoryCard />
                  <SubscribersCard />
                </Stack>

                <Stack direction="column" spacing={2} sx={{ flex: 1, width: '100%' }}>
                  <SiteInfoCard />
                  <SignalPlotsCard />
                  <BandPlanCard />
                  <AdjacentSitesCard />
                  <PatchesCard />
                </Stack>
              </Stack>
            </Box>
          </Box>
        </OP25ServiceProvider>
      </WebSocketServiceProvider>
    </ThemeServiceProvider>
  );
}