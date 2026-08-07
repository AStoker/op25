import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import MenuItem from '@mui/material/MenuItem';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import BoltIcon from '@mui/icons-material/Bolt';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import Field from '../common/Field';
import type { ConfigField } from '../../types/config';

/**
 * One control, rendered from the server's field description.
 *
 * Nothing here knows what a gain or a NAC is — the label, help text, units,
 * bounds and choices all come from `config_schema.py`, which is what lets a
 * protocol other than P25 appear without editing this file.
 */

interface Props {
  field: ConfigField;
  value: unknown;
  /** Value the preset would give, shown when an override is masking it. */
  presetValue?: unknown;
  overridden: boolean;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}

/** Empty string means "unset" for a number, since 0 is a legitimate ppm. */
function toNumber(raw: string): number | '' {
  if (raw.trim() === '') return '';
  const n = Number(raw);
  return Number.isFinite(n) ? n : '';
}

export default function ConfigFieldInput({
  field, value, presetValue, overridden, onChange, disabled = false,
}: Props) {
  const ro = disabled || field.readonly;

  const meta = (
    <>
      {field.live ? (
        <Tooltip title="Applies immediately — no restart needed">
          <Chip icon={<BoltIcon />} label="live" variant="outlined" color="success" />
        </Tooltip>
      ) : (
        <Tooltip title="Read by the decoder at startup — saving stores it, but it takes a restart to take effect">
          <Chip icon={<RestartAltIcon />} label="restart" variant="outlined" />
        </Tooltip>
      )}
      {overridden && (
        <Tooltip title={`Overriding the preset, which has ${JSON.stringify(presetValue)}`}>
          <Chip label="overridden" variant="outlined" color="warning" />
        </Tooltip>
      )}
    </>
  );

  const label = (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
      {field.label}
      {field.unit && <Box component="span" sx={{ opacity: 0.7 }}>({field.unit})</Box>}
      {meta}
    </Box>
  );

  if (field.type === 'boolean') {
    return (
      <Field label={label} hint={field.help}>
        <Box sx={{ display: 'flex', alignItems: 'center', minHeight: 32 }}>
          <Switch
            checked={Boolean(value)}
            disabled={ro}
            onChange={(e) => onChange(e.target.checked)}
            inputProps={{ 'aria-label': field.label }}
          />
        </Box>
      </Field>
    );
  }

  if (field.type === 'enum') {
    return (
      <Field label={label} hint={field.help}>
        <TextField
          select
          value={value === undefined || value === null ? '' : String(value)}
          disabled={ro}
          onChange={(e) => {
            // Choices may be numbers (crypt_behavior); keep the original type so
            // the diff does not report 2 -> "2" as a change.
            const chosen = field.choices?.find((c) => String(c) === e.target.value);
            onChange(chosen ?? e.target.value);
          }}
          slotProps={{ htmlInput: { 'aria-label': field.label } }}
        >
          {(field.choices ?? []).map((c) => (
            <MenuItem key={String(c)} value={String(c)}>{String(c)}</MenuItem>
          ))}
        </TextField>
      </Field>
    );
  }

  if (field.type === 'list') {
    const text = Array.isArray(value) ? value.join(', ') : '';
    return (
      <Field label={label} hint={field.help ?? 'Comma separated.'}>
        <TextField
          value={text}
          disabled={ro}
          placeholder={field.placeholder}
          onChange={(e) => onChange(
            e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
              // A list of ports has to go back as numbers, or the decoder gets
              // strings where it indexes by int.
              .map((s) => (/^-?\d+(\.\d+)?$/.test(s) ? Number(s) : s)),
          )}
          slotProps={{ htmlInput: { 'aria-label': field.label } }}
        />
      </Field>
    );
  }

  if (field.type === 'number') {
    const listId = field.suggestions?.length ? `sugg-${field.path}` : undefined;
    return (
      <Field label={label} hint={field.help}>
        <TextField
          type="number"
          value={value === undefined || value === null ? '' : String(value)}
          disabled={ro}
          placeholder={field.placeholder}
          onChange={(e) => onChange(toNumber(e.target.value))}
          slotProps={{
            htmlInput: {
              'aria-label': field.label,
              min: field.min, max: field.max, step: field.step ?? 'any',
              list: listId,
            },
          }}
        />
        {listId && (
          <Box component="datalist" id={listId}>
            {field.suggestions?.map((s) => <option key={String(s)} value={String(s)} />)}
          </Box>
        )}
      </Field>
    );
  }

  return (
    <Field label={label} hint={field.help}>
      <TextField
        value={value === undefined || value === null ? '' : String(value)}
        disabled={ro}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value)}
        slotProps={{ htmlInput: { 'aria-label': field.label } }}
      />
    </Field>
  );
}
