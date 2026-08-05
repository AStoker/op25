import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import type { SxProps, Theme } from '@mui/material/styles';
import type { ReactNode } from 'react';

interface SectionHeadingProps {
  title: ReactNode;
  /** Muted detail beside the title: counts, units, state chips. */
  meta?: ReactNode;
  /** Controls pinned to the right of the heading row — a filter, a toggle. */
  action?: ReactNode;
  sx?: SxProps<Theme>;
}

/**
 * The heading for a group inside a card ("Talk Groups", "Fine tune").
 *
 * Cards used `subtitle2` with and without `gutterBottom`, sometimes inside a
 * hand-built flex row to get a control onto the right; this gives all of them
 * the same spacing and the same wrap behaviour on a phone.
 */
export default function SectionHeading({ title, meta, action, sx }: SectionHeadingProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 1,
        mb: 0.75,
        ...sx,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.75, minWidth: 0 }}>
        <Typography variant="subtitle2" component="h3">{title}</Typography>
        {meta && (
          <Box
            sx={{
              display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.75,
              typography: 'caption', color: 'text.secondary',
            }}
          >
            {meta}
          </Box>
        )}
      </Box>
      {action}
    </Box>
  );
}
