import Typography from '@mui/material/Typography';
import type { SxProps, Theme } from '@mui/material/styles';
import type { ReactNode } from 'react';

interface HintProps {
  children: ReactNode;
  /** Render in the error colour — a validation message about the control above. */
  error?: boolean;
  sx?: SxProps<Theme>;
}

/**
 * One line of explanation under a control or a group of them.
 *
 * `Field` renders its own hint through this, so a note attached to a single
 * input and a note attached to a whole button row look the same.
 */
export default function Hint({ children, error = false, sx }: HintProps) {
  return (
    <Typography
      variant="caption"
      component="span"
      display="block"
      color={error ? 'error.main' : 'text.secondary'}
      lineHeight={1.35}
      sx={{ mt: 0.5, ...sx }}
    >
      {children}
    </Typography>
  );
}
