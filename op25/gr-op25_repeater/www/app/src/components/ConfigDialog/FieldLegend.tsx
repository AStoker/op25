import Box from '@mui/material/Box';
import BoltIcon from '@mui/icons-material/Bolt';
import EditIcon from '@mui/icons-material/Edit';
import LockIcon from '@mui/icons-material/Lock';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import SettingsBackupRestoreIcon from '@mui/icons-material/SettingsBackupRestore';
import type { SvgIconProps } from '@mui/material/SvgIcon';
import type { ComponentType } from 'react';

/**
 * What the icons on each field mean.
 *
 * Every field carries at least one badge, so spelling them out per field —
 * "restart", "restart", "restart" down a column of twenty — buries the labels.
 * Naming them once here is what lets the fields themselves stay quiet.
 */

interface Entry {
  Icon: ComponentType<SvgIconProps>;
  color: SvgIconProps['color'];
  label: string;
}

const ENTRIES: Entry[] = [
  { Icon: BoltIcon, color: 'success', label: 'Applies immediately' },
  { Icon: RestartAltIcon, color: 'disabled', label: 'Needs a restart' },
  { Icon: EditIcon, color: 'warning', label: 'You changed this' },
  { Icon: SettingsBackupRestoreIcon, color: 'action', label: 'Reset to preset' },
  { Icon: LockIcon, color: 'disabled', label: 'Read-only' },
];

export default function FieldLegend() {
  return (
    <Box
      component="ul"
      aria-label="field icon legend"
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 1.5,
        m: 0,
        p: 0,
        listStyle: 'none',
        typography: 'caption',
        color: 'text.secondary',
      }}
    >
      {ENTRIES.map(({ Icon, color, label }) => (
        <Box
          key={label}
          component="li"
          sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
        >
          <Icon color={color} sx={{ fontSize: 15 }} />
          {label}
        </Box>
      ))}
    </Box>
  );
}
