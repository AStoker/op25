import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { createTheme, responsiveFontSizes, ThemeProvider } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';
import CssBaseline from '@mui/material/CssBaseline';

type ThemeMode = 'light' | 'dark';

const STORAGE_KEY_MODE = 'op25.theme.mode';
const STORAGE_KEY_COLOR = 'op25.theme.primary';

export interface PrimaryColor {
  label: string;
  main: string;
}

export const PRESET_PRIMARY_COLORS: PrimaryColor[] = [
  { label: 'Blue', main: '#1976d2' },
  { label: 'Purple', main: '#9c27b0' },
  { label: 'Green', main: '#2e7d32' },
  { label: 'Orange', main: '#e65100' },
  { label: 'Red', main: '#c62828' },
  { label: 'Teal', main: '#00695c' },
];

interface ThemeServiceContextType {
  mode: ThemeMode;
  toggleTheme: () => void;
  primaryColor: PrimaryColor;
  setPrimaryColor: (color: PrimaryColor) => void;
}

const ThemeServiceContext = createContext<ThemeServiceContextType>({
  mode: 'light',
  toggleTheme: () => {},
  primaryColor: PRESET_PRIMARY_COLORS[0],
  setPrimaryColor: () => {},
});

// eslint-disable-next-line react-refresh/only-export-components
export function useThemeService() {
  return useContext(ThemeServiceContext);
}

function storedMode(): ThemeMode | null {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY_MODE);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;   // private browsing / storage disabled
  }
}

function storedColor(): PrimaryColor | null {
  try {
    const label = window.localStorage.getItem(STORAGE_KEY_COLOR);
    return PRESET_PRIMARY_COLORS.find((c) => c.label === label) ?? null;
  } catch {
    return null;
  }
}

interface ThemeServiceProviderProps {
  children: React.ReactNode;
}

export function ThemeServiceProvider({ children }: ThemeServiceProviderProps) {
  // A scanner UI gets used on a phone at night as often as at a desk, so start
  // from the device's own preference rather than always forcing light mode.
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)', { noSsr: true });
  const [mode, setMode] = useState<ThemeMode>(() => storedMode() ?? (prefersDark ? 'dark' : 'light'));
  const [primaryColor, setPrimaryColorState] = useState<PrimaryColor>(
    () => storedColor() ?? PRESET_PRIMARY_COLORS[0],
  );

  // Follow the OS while the user has not made an explicit choice.
  useEffect(() => {
    if (storedMode() === null) setMode(prefersDark ? 'dark' : 'light');
  }, [prefersDark]);

  const toggleTheme = useCallback(() => {
    setMode((prev) => {
      const next = prev === 'light' ? 'dark' : 'light';
      try { window.localStorage.setItem(STORAGE_KEY_MODE, next); } catch { /* ignore */ }
      return next;
    });
  }, []);

  const setPrimaryColor = useCallback((color: PrimaryColor) => {
    setPrimaryColorState(color);
    try { window.localStorage.setItem(STORAGE_KEY_COLOR, color.label); } catch { /* ignore */ }
  }, []);

  const theme = useMemo(() => {
    const base = createTheme({
      palette: {
        mode,
        primary: { main: primaryColor.main },
      },
      components: {
        // Denser cards on small screens — the default 16px padding costs a
        // meaningful fraction of a phone's width once it is doubled up.
        MuiCardContent: {
          styleOverrides: {
            root: ({ theme: t }) => ({
              padding: t.spacing(1.5),
              [t.breakpoints.up('sm')]: { padding: t.spacing(2) },
            }),
          },
        },
        MuiCardHeader: {
          styleOverrides: {
            root: ({ theme: t }) => ({
              paddingLeft: t.spacing(1.5),
              paddingRight: t.spacing(1.5),
              [t.breakpoints.up('sm')]: {
                paddingLeft: t.spacing(2),
                paddingRight: t.spacing(2),
              },
            }),
          },
        },
        MuiTableCell: {
          styleOverrides: {
            // Tables carry the most data and are the first thing to overflow
            // on a phone; tighten the horizontal padding there only.
            sizeSmall: ({ theme: t }) => ({
              paddingLeft: t.spacing(0.75),
              paddingRight: t.spacing(0.75),
              [t.breakpoints.up('sm')]: {
                paddingLeft: t.spacing(2),
                paddingRight: t.spacing(2),
              },
            }),
          },
        },
      },
    });
    return responsiveFontSizes(base);
  }, [mode, primaryColor]);

  // Keep the browser chrome (Android address bar, iOS status bar) in step with
  // the app's own background instead of flashing white behind a dark UI.
  useEffect(() => {
    let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.appendChild(meta);
    }
    // In dark mode MUI renders the AppBar in a dark surface colour rather than
    // the primary one, so matching primary here would put a bright blue bar
    // above an otherwise dark app.
    meta.content = mode === 'dark'
      ? theme.palette.background.default
      : theme.palette.primary.main;
  }, [theme, mode]);

  return (
    <ThemeServiceContext.Provider value={{ mode, toggleTheme, primaryColor, setPrimaryColor }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeServiceContext.Provider>
  );
}
