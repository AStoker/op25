import { createTheme } from '@mui/material/styles';

const OP25_CYAN = '#00ffff';

export function buildTheme(accentColor = OP25_CYAN) {
  return createTheme({
    palette: {
      mode: 'dark',
      primary: {
        main: accentColor,
        contrastText: '#000',
      },
      secondary: {
        main: '#ffaa55',
      },
      background: {
        default: '#111111',
        paper: '#1a1a1a',
      },
      text: {
        primary: '#e0e0e0',
        secondary: '#aaaaaa',
      },
      divider: '#333333',
      error: { main: '#f44336' },
      warning: { main: '#ff9800' },
      success: { main: '#4caf50' },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica Neue", Arial, sans-serif',
      fontSize: 13,
      h6: { fontWeight: 600 },
      subtitle2: { fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            backgroundColor: '#111111',
            color: '#e0e0e0',
          },
          ':root': {
            '--op25-accent': accentColor,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      MuiButton: {
        defaultProps: { size: 'small' },
        styleOverrides: {
          root: { textTransform: 'none', fontWeight: 600 },
        },
      },
      MuiIconButton: {
        defaultProps: { size: 'small' },
      },
      MuiTableCell: {
        styleOverrides: {
          root: {
            padding: '4px 8px',
            borderColor: '#2a2a2a',
            fontSize: '0.78rem',
          },
          head: {
            fontWeight: 700,
            backgroundColor: '#252525',
            color: '#cccccc',
            fontSize: '0.72rem',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          },
        },
      },
      MuiTableRow: {
        styleOverrides: {
          root: {
            '&:hover': {
              backgroundColor: 'rgba(255,255,255,0.04)',
            },
          },
        },
      },
      MuiChip: {
        defaultProps: { size: 'small' },
      },
      MuiTooltip: {
        defaultProps: {
          arrow: true,
          enterDelay: 300,
        },
        styleOverrides: {
          tooltip: {
            backgroundColor: '#333',
            color: '#eee',
            fontSize: '0.75rem',
            border: '1px solid #555',
          },
          arrow: {
            color: '#333',
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundColor: '#1a1a1a',
            backgroundImage: 'none',
            borderBottom: '1px solid #333',
          },
        },
      },
      MuiDivider: {
        styleOverrides: {
          root: { borderColor: '#333' },
        },
      },
    },
  });
}

export const defaultTheme = buildTheme();
