import React, { createContext, useContext, useMemo, useState } from 'react';
import { createTheme, ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';

type ThemeMode = 'light' | 'dark';

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

interface ThemeServiceProviderProps {
  children: React.ReactNode;
}

export function ThemeServiceProvider({ children }: ThemeServiceProviderProps) {
  const [mode, setMode] = useState<ThemeMode>('light');
  const [primaryColor, setPrimaryColor] = useState<PrimaryColor>(PRESET_PRIMARY_COLORS[0]);

  const toggleTheme = () => {
    setMode((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: primaryColor.main },
        },
      }),
    [mode, primaryColor],
  );

  return (
    <ThemeServiceContext.Provider value={{ mode, toggleTheme, primaryColor, setPrimaryColor }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeServiceContext.Provider>
  );
}

