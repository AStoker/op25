import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import type { SxProps, Theme } from '@mui/material/styles';
import type { ReactNode } from 'react';
import Hint from './Hint';

interface FieldProps {
  /**
   * Caption above the control.
   *
   * This app has no floating input labels. A label that lives inside the box
   * has to grow the box to hold it — that is what stopped the TGID and filter
   * inputs lining up with the buttons next to them — and it disagrees with the
   * caption-above-value pattern every read-only field here already uses
   * (see `InfoRow`). Omit it for a control whose purpose its placeholder or the
   * surrounding heading already makes obvious.
   */
  label?: ReactNode;
  /** Help under the control. Rendered only when set, so nothing reserves a
   *  blank line the way `helperText=" "` did. */
  hint?: ReactNode;
  /** Takes the place of `hint` and renders in the error colour. */
  error?: ReactNode;
  children: ReactNode;
  sx?: SxProps<Theme>;
}

/**
 * A labelled form control: caption, control, optional one-line hint.
 *
 * The control itself is a plain MUI input — the theme owns its height, so
 * anything wrapped here lines up with the buttons beside it.
 */
export default function Field({ label, hint, error, children, sx }: FieldProps) {
  const note = error ?? hint;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: 0, ...sx }}>
      {label && (
        <Typography
          variant="caption"
          color="text.secondary"
          component="span"
          lineHeight={1.3}
          sx={{ mb: 0.25 }}
        >
          {label}
        </Typography>
      )}
      {children}
      {note && <Hint error={Boolean(error)} sx={{ mt: 0.25 }}>{note}</Hint>}
    </Box>
  );
}
