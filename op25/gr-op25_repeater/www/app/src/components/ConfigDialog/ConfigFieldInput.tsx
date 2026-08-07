import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import BoltIcon from '@mui/icons-material/Bolt';
import EditIcon from '@mui/icons-material/Edit';
import LockIcon from '@mui/icons-material/Lock';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import SettingsBackupRestoreIcon from '@mui/icons-material/SettingsBackupRestore';
import Field from '../common/Field';
import type { ConfigField } from '../../types/config';

/**
 * One control, rendered from the server's field description.
 *
 * Nothing here knows what a gain or a NAC is — the label, help text, units,
 * bounds, precision and choices all come from `config_schema.py`, which is what
 * lets a protocol other than P25 appear without editing this file.
 *
 * The status badges are icons rather than text chips: every field carries at
 * least one, and three words repeated down a column of twenty fields drowns out
 * the labels they are attached to. `FieldLegend` in SettingsTab names them once.
 */

interface Props {
  field: ConfigField;
  value: unknown;
  /** Value the preset would give. Undefined when the preset has no such key. */
  presetValue?: unknown;
  overridden: boolean;
  onChange: (value: unknown) => void;
  /** Revert to `presetValue`. Absent when the field is not overridden. */
  onReset?: () => void;
  disabled?: boolean;
}

/** Empty string means "unset" for a number, since 0 is a legitimate ppm. */
function toNumber(raw: string): number | '' {
  if (raw.trim() === '') return '';
  const n = Number(raw);
  return Number.isFinite(n) ? n : '';
}

/**
 * Trim a float to the precision the field declares.
 *
 * `adj_tune` works in fractional ppm and lands on values like
 * `2.3749999999999996`. Those digits are noise — at 859 MHz the smallest tuning
 * step is about 0.116 ppm — but they make the value unreadable. Rounds rather
 * than truncating, and leaves the value alone when no precision is declared.
 */
export function trimFloat(value: unknown, precision?: number): unknown {
  if (precision === undefined || typeof value !== 'number' || !Number.isFinite(value)) {
    return value;
  }
  return Number(value.toFixed(precision));
}

/** How a value reads in a tooltip: quoted strings, `unset` for absent. */
export function describeValue(value: unknown): string {
  if (value === undefined) return 'unset';
  if (value === null) return 'null';
  if (typeof value === 'string') return value === '' ? '(empty)' : `"${value}"`;
  return JSON.stringify(value);
}

const BADGE_SX = { fontSize: 15, verticalAlign: 'text-bottom' } as const;

export default function ConfigFieldInput({
  field, value, presetValue, overridden, onChange, onReset, disabled = false,
}: Props) {
  const ro = disabled || field.readonly;
  const shown = field.type === 'number' ? trimFloat(value, field.precision) : value;

  const label = (
    <Box
      component="span"
      sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}
    >
      {field.label}
      {field.unit && <Box component="span" sx={{ opacity: 0.7 }}>({field.unit})</Box>}

      {field.live ? (
        <Tooltip title="Live — applies as soon as you save, no restart">
          <BoltIcon color="success" sx={BADGE_SX} aria-label="live" />
        </Tooltip>
      ) : (
        <Tooltip title="Restart required — saved straight away, but the decoder only reads this at startup">
          <RestartAltIcon color="disabled" sx={BADGE_SX} aria-label="restart required" />
        </Tooltip>
      )}

      {field.readonly && (
        <Tooltip title="Read-only — changing it would break references elsewhere in the config">
          <LockIcon color="disabled" sx={BADGE_SX} aria-label="read-only" />
        </Tooltip>
      )}

      {overridden && (
        <Tooltip title={`Overriding the preset, which has ${describeValue(trimFloat(presetValue, field.precision))}`}>
          <EditIcon color="warning" sx={BADGE_SX} aria-label="overridden" />
        </Tooltip>
      )}

      {overridden && onReset && !ro && (
        <Tooltip
          title={presetValue === undefined
            ? 'Remove this override — the preset does not set this field'
            : `Reset to the preset value: ${describeValue(trimFloat(presetValue, field.precision))}`}
        >
          {/* Small, and inline with the caption rather than beside the control:
              it belongs to the label's status row, and putting it next to the
              input would shorten every input by its width. */}
          <IconButton
            size="small"
            aria-label={`reset ${field.label} to the preset value`}
            onClick={onReset}
            sx={{ p: 0.25, ml: -0.25 }}
          >
            <SettingsBackupRestoreIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      )}
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
          value={shown === undefined || shown === null ? '' : String(shown)}
          disabled={ro}
          placeholder={field.placeholder}
          onChange={(e) => onChange(trimFloat(toNumber(e.target.value), field.precision))}
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
