import { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Box, Button,
  Typography, IconButton, Table, TableBody, TableCell, TableContainer,
  TableRow, Accordion, AccordionSummary, AccordionDetails, Paper,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { FullConfigResponse } from '../types';

interface Props {
  open: boolean;
  config: FullConfigResponse | null;
  onClose: () => void;
}

// ── Recursive config value renderer ─────────────────────────────────────────
function ConfigValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <Typography variant="caption" color="text.secondary">null</Typography>;
  }
  if (typeof value === 'boolean') {
    return (
      <Typography variant="caption" color={value ? 'success.main' : 'error.main'}>
        {String(value)}
      </Typography>
    );
  }
  if (typeof value === 'number' || typeof value === 'string') {
    return (
      <Typography variant="caption" sx={{ fontFamily: 'monospace', wordBreak: 'break-word' }}>
        {String(value)}
      </Typography>
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <Typography variant="caption" color="text.secondary">[]</Typography>;
    }
    if (value.every((v) => typeof v !== 'object' || v === null)) {
      return (
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
          [{value.join(', ')}]
        </Typography>
      );
    }
    // Array of objects — show inline table
    return (
      <Box sx={{ ml: 1 }}>
        {value.map((item, i) => (
          <Box key={i} sx={{ mb: 0.5, pl: 1, borderLeft: '2px solid #333' }}>
            {typeof item === 'object' && item !== null ? (
              <ObjectTable obj={item as Record<string, unknown>} depth={2} />
            ) : (
              <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{String(item)}</Typography>
            )}
          </Box>
        ))}
      </Box>
    );
  }
  if (typeof value === 'object') {
    return <ObjectTable obj={value as Record<string, unknown>} depth={2} />;
  }
  return <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{String(value)}</Typography>;
}

function ObjectTable({ obj, depth = 0 }: { obj: Record<string, unknown>; depth?: number }) {
  const entries = Object.entries(obj);
  if (entries.length === 0) {
    return <Typography variant="caption" color="text.secondary">{'{}'}</Typography>;
  }

  return (
    <TableContainer component={depth === 0 ? Paper : Box} sx={depth === 0 ? { border: '1px solid #2a2a2a' } : undefined}>
      <Table size="small">
        <TableBody>
          {entries.map(([key, val]) => (
            <TableRow key={key}>
              <TableCell
                sx={{
                  width: 160,
                  minWidth: 120,
                  fontFamily: 'monospace',
                  fontSize: '0.72rem',
                  color: 'primary.main',
                  verticalAlign: 'top',
                  py: 0.5,
                }}
              >
                {key}
              </TableCell>
              <TableCell sx={{ py: 0.5, verticalAlign: 'top' }}>
                <ConfigValue value={val} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

// ── Main dialog ──────────────────────────────────────────────────────────────
export default function ConfigDialog({ open, config, onClose }: Props) {
  if (!open) return null;

  const entries = config
    ? Object.entries(config).filter(([k]) => k !== 'json_type')
    : [];

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center' }}>
        <Typography variant="h6" sx={{ flex: 1 }}>Full Configuration</Typography>
        <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ p: 1.5 }}>
        {!config && (
          <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
            Configuration not yet loaded. Open settings to refresh.
          </Typography>
        )}

        {entries.map(([key, value]) => (
          <Accordion
            key={key}
            elevation={1}
            disableGutters
            defaultExpanded={key === 'trunking'}
            sx={{ mb: 0.5, border: '1px solid #2a2a2a', '&:before': { display: 'none' } }}
          >
            <AccordionSummary
              expandIcon={<ExpandMoreIcon />}
              sx={{ minHeight: 36, '& .MuiAccordionSummary-content': { my: 0.5 } }}
            >
              <Typography
                variant="subtitle2"
                sx={{ fontFamily: 'monospace', fontSize: '0.75rem', color: 'primary.main' }}
              >
                {key}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1, mt: 0.1 }}>
                {typeLabel(value)}
              </Typography>
            </AccordionSummary>
            <AccordionDetails sx={{ p: 1 }}>
              <ConfigValue value={value} />
            </AccordionDetails>
          </Accordion>
        ))}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

function typeLabel(v: unknown): string {
  if (v === null) return 'null';
  if (Array.isArray(v)) return `array[${(v as unknown[]).length}]`;
  if (typeof v === 'object') return `object (${Object.keys(v as object).length} keys)`;
  return typeof v;
}
