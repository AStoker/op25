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

/**
 * Height of every interactive control — button, input, select, toggle, icon
 * button. Mixing MUI's own sizes is what stopped the old TGID and filter boxes
 * lining up with the buttons beside them: a `size="small"` outlined input is
 * 40px tall against a 32px button, and a floating label plus reserved helper
 * text added another 30px on top of that. One token, one height.
 */
export const CONTROL_HEIGHT = 32;

/** Font size for control text (buttons, inputs, toggles) — MUI's own dense size. */
const CONTROL_FONT = '0.8125rem';

/** Chips are labels, not controls: deliberately smaller than CONTROL_HEIGHT. */
const CHIP_HEIGHT = 22;

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

        // ---- Controls -----------------------------------------------------
        // Everything below exists so a component never has to restate a size.
        // If a control needs a different height, change CONTROL_HEIGHT, not the
        // component.

        MuiButton: {
          defaultProps: { size: 'small', disableElevation: true },
          styleOverrides: {
            // Sentence case: the labels here are words like "Whitelist" and
            // "Dump buffer", which read worse shouted.
            root: { textTransform: 'none', fontWeight: 500 },
            sizeSmall: ({ theme: t }) => ({
              minHeight: CONTROL_HEIGHT,
              paddingTop: 0,
              paddingBottom: 0,
              paddingLeft: t.spacing(1.25),
              paddingRight: t.spacing(1.25),
              fontSize: CONTROL_FONT,
            }),
          },
        },
        MuiButtonGroup: {
          defaultProps: { size: 'small' },
        },
        MuiToggleButton: {
          defaultProps: { size: 'small' },
          styleOverrides: {
            root: { textTransform: 'none' },
            sizeSmall: ({ theme: t }) => ({
              minHeight: CONTROL_HEIGHT,
              paddingTop: 0,
              paddingBottom: 0,
              paddingLeft: t.spacing(1.25),
              paddingRight: t.spacing(1.25),
              fontSize: CONTROL_FONT,
            }),
          },
        },
        MuiToggleButtonGroup: {
          defaultProps: { size: 'small' },
        },
        MuiIconButton: {
          styleOverrides: {
            // 6px around a `fontSize="small"` (20px) icon lands on exactly
            // CONTROL_HEIGHT, so an icon button in a row of buttons or a table
            // cell is as tall as they are. A medium icon inside a small button
            // (the card-header chevron) is deliberately bigger.
            sizeSmall: { padding: 6 },
          },
        },
        MuiTab: {
          styleOverrides: {
            root: { textTransform: 'none' },
          },
        },

        MuiTextField: {
          defaultProps: { size: 'small', variant: 'outlined' },
        },
        MuiSelect: {
          defaultProps: { size: 'small' },
        },
        MuiOutlinedInput: {
          styleOverrides: {
            root: { fontSize: CONTROL_FONT },
            // The input keeps its intrinsic 1.4375em line box and the root
            // centres it (InputBase is already a flex row), so the control is
            // CONTROL_HEIGHT tall without hard-coding the inner text height —
            // which a Select, whose "input" is a div, would not survive.
            sizeSmall: ({ theme: t }) => ({
              minHeight: CONTROL_HEIGHT,
              '&.MuiInputBase-adornedStart': { paddingLeft: t.spacing(1) },
              '&.MuiInputBase-adornedEnd': { paddingRight: t.spacing(0.5) },
            }),
            inputSizeSmall: ({ theme: t }) => ({
              paddingTop: 0,
              paddingBottom: 0,
              paddingLeft: t.spacing(1.25),
              paddingRight: t.spacing(1.25),
            }),
          },
        },
        MuiMenuItem: {
          styleOverrides: {
            // Match the closed control: a 16px dropdown over a 13px select
            // looks like two different widgets.
            root: { fontSize: CONTROL_FONT },
          },
        },
        MuiFormHelperText: {
          styleOverrides: {
            // Helper text is a caption under a field, not an indented aside.
            root: { marginLeft: 0, marginRight: 0 },
          },
        },
        MuiFormControlLabel: {
          styleOverrides: {
            // Matches the caption/control type scale, so switch rows no longer
            // each wrap their label in a <Typography> to get there.
            label: { fontSize: CONTROL_FONT },
          },
        },

        MuiChip: {
          defaultProps: { size: 'small' },
          styleOverrides: {
            sizeSmall: { height: CHIP_HEIGHT, fontSize: '0.72rem' },
            labelSmall: ({ theme: t }) => ({
              paddingLeft: t.spacing(0.75),
              paddingRight: t.spacing(0.75),
            }),
            // Icons inside a chip have to be scaled down explicitly; MUI's own
            // default is sized for the medium chip.
            iconSmall: { fontSize: '0.9rem', marginLeft: 4, marginRight: -3 },
            deleteIconSmall: { fontSize: '0.9rem' },
          },
        },
        MuiTooltip: {
          defaultProps: { arrow: true, enterDelay: 400 },
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
