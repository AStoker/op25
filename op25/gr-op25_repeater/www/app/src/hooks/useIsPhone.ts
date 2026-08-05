import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';

/**
 * True on phone-width viewports (below MUI's `sm` breakpoint, 600 px).
 *
 * Used by the data tables to drop lower-value columns rather than let them
 * squeeze the important ones into unreadable slivers or force the page to
 * scroll sideways. Anything wider keeps the full column set.
 */
export function useIsPhone(): boolean {
  const theme = useTheme();
  return useMediaQuery(theme.breakpoints.down('sm'));
}
