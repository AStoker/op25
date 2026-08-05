import Box from '@mui/material/Box';
import type { SxProps, Theme } from '@mui/material/styles';
import type { ReactNode } from 'react';

interface InsetPanelProps {
  children: ReactNode;
  /** Draw attention to this one — a keyword hit, an alarm condition. Tints the
   *  background rather than filling it, so text stays legible in both themes. */
  highlight?: boolean;
  sx?: SxProps<Theme>;
}

/**
 * The outlined tile used for a repeated item inside a card: a configured
 * channel, a trunked system, a frequency, a captured clip, a plot.
 *
 * Five cards each had their own `border: 1, borderColor: divider, ...` literal
 * with a different padding; this is the one of them that wins.
 */
export default function InsetPanel({ children, highlight = false, sx }: InsetPanelProps) {
  return (
    <Box
      sx={{
        border: 1,
        borderColor: highlight ? 'warning.main' : 'divider',
        borderRadius: 1,
        bgcolor: highlight ? 'action.hover' : 'transparent',
        p: { xs: 0.75, sm: 1 },
        minWidth: 0,
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}
