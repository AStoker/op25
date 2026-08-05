import Box from '@mui/material/Box';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import type { SxProps, Theme } from '@mui/material/styles';
import type { ReactNode } from 'react';

interface InfoRowProps {
  label: ReactNode;
  value: ReactNode;
  /** Explains the field. Radio terms (WACN, LRA, RFSS) need one. */
  tooltip?: string;
  /** Smart-colour tint, when the value is a talkgroup tag. */
  color?: string;
  sx?: SxProps<Theme>;
}

/**
 * A read-only labelled value: caption above, value below.
 *
 * The same shape as `Field`, deliberately — a static value and an input should
 * not label themselves differently.
 */
export default function InfoRow({ label, value, tooltip, color, sx }: InfoRowProps) {
  const content = (
    <Box sx={{ minWidth: 0, ...sx }}>
      <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.3}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight="medium" sx={{ overflowWrap: 'anywhere', color }}>
        {value}
      </Typography>
    </Box>
  );

  if (!tooltip) return content;
  return <Tooltip title={tooltip} placement="top">{content}</Tooltip>;
}
