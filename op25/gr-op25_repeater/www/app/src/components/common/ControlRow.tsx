import Box from '@mui/material/Box';
import type { SxProps, Theme } from '@mui/material/styles';
import type { ReactNode } from 'react';

interface ControlRowProps {
  children: ReactNode;
  /**
   * `center` for a row of bare controls (the common case, since they are all
   * CONTROL_HEIGHT tall); `end` when the row mixes `Field`s that carry a label
   * with controls that do not, so the controls still share a baseline.
   */
  align?: 'center' | 'end' | 'baseline';
  sx?: SxProps<Theme>;
}

/**
 * A horizontal group of controls: one gap, one wrap rule, one alignment.
 *
 * Every toolbar in the app used a hand-rolled Stack or flex Box with slightly
 * different spacing, which is visible as soon as two cards sit side by side.
 */
export default function ControlRow({ children, align = 'center', sx }: ControlRowProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: align === 'end' ? 'flex-end' : align,
        gap: 1,
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}
