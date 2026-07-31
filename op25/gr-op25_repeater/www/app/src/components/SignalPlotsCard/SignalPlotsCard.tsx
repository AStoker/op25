import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import CardShell from '../CardShell/CardShell';
import { useOp25Service } from '../../services/op25Service';
import type { PlotMode, PlotPayload } from '../../types/op25';

const PLOT_MODES: { mode: PlotMode; label: string }[] = [
  { mode: 'fft',           label: 'FFT' },
  { mode: 'constellation', label: 'Constellation' },
  { mode: 'symbol',        label: 'Symbol' },
  { mode: 'eye',           label: 'Eye' },
  { mode: 'mixer',         label: 'Mixer' },
  { mode: 'fll',           label: 'FLL' },
];

/** Render shape that looks natural for each plot kind. */
const RENDER_STYLE: Record<PlotMode, 'line' | 'scatter' | 'stem'> = {
  fft:           'line',
  mixer:         'line',
  fll:           'line',
  constellation: 'scatter',
  symbol:        'stem',
  eye:           'line',
};

interface PlotViewProps {
  plot: PlotPayload;
}

function PlotView({ plot }: PlotViewProps) {
  const W = 320;
  const H = 160;
  const PAD = 18;

  const { data, xrange, yrange, mode } = plot;
  const style = RENDER_STYLE[mode];

  const xs = data.map((p) => p[0]);
  const ys = data.map((p) => p[1]);
  const xMin = xrange?.[0] ?? (xs.length ? Math.min(...xs) : 0);
  const xMax = xrange?.[1] ?? (xs.length ? Math.max(...xs) : 1);
  const yMin = yrange?.[0] ?? (ys.length ? Math.min(...ys) : 0);
  const yMax = yrange?.[1] ?? (ys.length ? Math.max(...ys) : 1);

  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;

  const sx = (x: number) => PAD + ((x - xMin) / xSpan) * (W - 2 * PAD);
  const sy = (y: number) => H - PAD - ((y - yMin) / ySpan) * (H - 2 * PAD);

  const path = useMemo(() => {
    if (style !== 'line' || data.length === 0) return '';
    let d = `M ${sx(data[0][0])} ${sy(data[0][1])}`;
    for (let i = 1; i < data.length; i++) {
      d += ` L ${sx(data[i][0])} ${sy(data[i][1])}`;
    }
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, style, xMin, xMax, yMin, yMax]);

  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1 }}>
      <Typography variant="caption" color="text.secondary" display="block" gutterBottom>
        {plot.title || mode}
      </Typography>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ display: 'block', maxHeight: 220 }}
        preserveAspectRatio="none"
        aria-label={`${mode} plot`}
      >
        <rect x={PAD} y={PAD} width={W - 2 * PAD} height={H - 2 * PAD}
              fill="none" stroke="currentColor" strokeOpacity={0.15} />

        {style === 'line' && (
          <path d={path} fill="none" stroke="currentColor" strokeWidth={1} />
        )}
        {style === 'scatter' && data.map(([x, y], i) => (
          <circle key={i} cx={sx(x)} cy={sy(y)} r={1.2} fill="currentColor" opacity={0.7} />
        ))}
        {style === 'stem' && data.map(([x, y], i) => (
          <line key={i} x1={sx(x)} y1={sy(0)} x2={sx(x)} y2={sy(y)}
                stroke="currentColor" strokeOpacity={0.7} strokeWidth={1} />
        ))}

        <text x={PAD} y={H - 4} fontSize={9} fill="currentColor" opacity={0.5}>
          {xMin.toFixed(2)}
        </text>
        <text x={W - PAD} y={H - 4} fontSize={9} textAnchor="end" fill="currentColor" opacity={0.5}>
          {xMax.toFixed(2)}
        </text>
        <text x={2} y={PAD + 4} fontSize={9} fill="currentColor" opacity={0.5}>
          {yMax.toFixed(1)}
        </text>
        <text x={2} y={H - PAD} fontSize={9} fill="currentColor" opacity={0.5}>
          {yMin.toFixed(1)}
        </text>
      </svg>
      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
        ch {plot.chan} · {data.length} pts
      </Typography>
    </Box>
  );
}

export default function SignalPlotsCard() {
  const {
    plots, activePlotModes, togglePlotMode,
    selectedChannelId, channels,
  } = useOp25Service();

  const msgqid = selectedChannelId !== null
    ? (channels[selectedChannelId]?.msgqid ?? Number(selectedChannelId))
    : null;

  const visible: PlotPayload[] = [];
  for (const mode of activePlotModes) {
    if (msgqid === null) continue;
    const p = plots[`${msgqid}:${mode}`];
    if (p) visible.push(p);
  }

  return (
    <CardShell title="Signal Plots">
      <Stack spacing={1.5}>
        <ToggleButtonGroup
          size="small"
          value={Array.from(activePlotModes)}
          onChange={(_, modes) => {
            // Diff the new selection against current and toggle each delta to
            // keep the decoder in sync with the UI.
            const current = activePlotModes;
            const next    = new Set<PlotMode>(modes as PlotMode[]);
            for (const m of current) if (!next.has(m)) togglePlotMode(m);
            for (const m of next)    if (!current.has(m)) togglePlotMode(m);
          }}
          aria-label="signal plot modes"
          sx={{ flexWrap: 'wrap' }}
        >
          {PLOT_MODES.map(({ mode, label }) => (
            <ToggleButton
              key={mode}
              value={mode}
              aria-label={`toggle ${label}`}
              sx={{ textTransform: 'none' }}
            >
              {label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        {activePlotModes.size === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Toggle one or more plots above to view live signal data.
          </Typography>
        ) : visible.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Waiting for plot data…
          </Typography>
        ) : (
          <Box sx={{
            display: 'grid',
            // min() keeps the track from exceeding the viewport on a narrow
            // phone, where a hard 260px floor would force a sideways scroll.
            gridTemplateColumns: 'repeat(auto-fill, minmax(min(260px, 100%), 1fr))',
            gap: 1,
          }}>
            {visible.map((p) => (
              <PlotView key={`${p.chan}:${p.mode}`} plot={p} />
            ))}
          </Box>
        )}
      </Stack>
    </CardShell>
  );
}
