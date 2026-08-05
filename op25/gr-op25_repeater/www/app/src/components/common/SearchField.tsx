import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import TextField from '@mui/material/TextField';
import ClearIcon from '@mui/icons-material/Clear';
import SearchIcon from '@mui/icons-material/Search';
import type { SxProps, Theme } from '@mui/material/styles';

interface SearchFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** Accessible name, since there is no visible label. */
  ariaLabel?: string;
  sx?: SxProps<Theme>;
}

/**
 * The filter box that sits in a section heading.
 *
 * No label: the magnifier and the placeholder say what it is in the space a
 * floating label would have taken, which is the difference between fitting on
 * the heading line and pushing the table down.
 */
export default function SearchField({
  value, onChange, placeholder, ariaLabel, sx,
}: SearchFieldProps) {
  return (
    <TextField
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      sx={{ width: { xs: '100%', sm: 200 }, ...sx }}
      slotProps={{
        htmlInput: { 'aria-label': ariaLabel ?? placeholder },
        input: {
          startAdornment: (
            <InputAdornment position="start" sx={{ mr: 0.5 }}>
              <SearchIcon sx={{ fontSize: '1.05rem', color: 'text.disabled' }} />
            </InputAdornment>
          ),
          // Only present when there is something to clear, so the control does
          // not carry a dead button most of the time.
          endAdornment: value ? (
            <InputAdornment position="end">
              <IconButton
                size="small"
                aria-label="clear filter"
                onClick={() => onChange('')}
                sx={{ p: 0.25 }}
              >
                <ClearIcon sx={{ fontSize: '1rem' }} />
              </IconButton>
            </InputAdornment>
          ) : null,
        },
      }}
    />
  );
}
