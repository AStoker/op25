
import Box from '@mui/material/Box';
import Toolbar from '@mui/material/Toolbar';
import Header from './components/Header/Header';
import type { NavItem } from './components/Header/Header';
import { ThemeServiceProvider } from './services/themeService';

const navItems: NavItem[] = [
  { label: 'Settings', onClick: () => { /* TODO: open Settings dialog */ } },
  { label: 'Config', onClick: () => { /* TODO: open Config dialog */ } },
  { label: 'Legacy UI', href: '/' },
  { label: 'About', onClick: () => { /* TODO: open About dialog */ } },
];

export default function App() {
  return (
    <ThemeServiceProvider>
      <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <Header navItems={navItems} />
        <Box component="main" sx={{ p: 3 }}>
          {/* Offset below the fixed AppBar */}
          <Toolbar />
          {/* Page content will go here */}
        </Box>
      </Box>
    </ThemeServiceProvider>
  );
}