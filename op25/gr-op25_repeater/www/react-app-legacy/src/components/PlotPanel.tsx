import { useRef, useEffect } from 'react';
import { Paper, Box, Typography, Button, Tooltip } from '@mui/material';
import { useTheme } from '@mui/material/styles';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import type { PlotResponse, PlotMode } from '../types';

const CANVAS_W = 400;
const CANVAS_H = 220;

const PLOT_TOGGLES: { cmd: string; label: string; mode: PlotMode }[] = [
  { cmd: 'datascope',     label: 'Datascope',     mode: 'eye' },
  { cmd: 'fft',           label: 'FFT',           mode: 'fft' },
  { cmd: 'constellation', label: 'Constellation', mode: 'constellation' },
  { cmd: 'symbol',        label: 'Symbol',        mode: 'symbol' },
  { cmd: 'mixer',         label: 'Mixer',         mode: 'mixer' },
  { cmd: 'fll',           label: 'FLL',           mode: 'fll' },
];

function PlotCanvas({ plot }: { plot: PlotResponse }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const theme = useTheme();
  const lineColor = theme.palette.primary.main;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = CANVAS_W;
    const H = CANVAS_H;
    const [xmin, xmax] = plot.xrange;
    const [ymin, ymax] = plot.yrange;
    const xspan = xmax - xmin || 1;
    const yspan = ymax - ymin || 1;

    const toPixel = (x: number, y: number): [number, number] => [
      ((x - xmin) / xspan) * W,
      H - ((y - ymin) / yspan) * H,
    ];

    // Background
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, W, H);

    // Subtle grid
    ctx.strokeStyle = '#1c1c1c';
    ctx.lineWidth = 0.5;
    for (let i = 1; i < 4; i++) {
      const gx = (i / 4) * W;
      ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke();
      const gy = (i / 4) * H;
      ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke();
    }

    // Zero baseline when y spans zero
    if (ymin < 0 && ymax > 0) {
      const [, zy] = toPixel(0, 0);
      ctx.strokeStyle = '#383838';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, zy); ctx.lineTo(W, zy); ctx.stroke();
    }

    ctx.strokeStyle = lineColor;
    ctx.fillStyle = lineColor;
    ctx.lineWidth = 1.5;

    const { mode, data } = plot;

    if (mode === 'eye') {
      // Each segment: x goes 0 → sps-1, then resets to 0 for next segment
      let segStart = 0;
      for (let i = 1; i <= data.length; i++) {
        const isBreak = i === data.length || data[i][0] === 0;
        if (isBreak) {
          const seg = data.slice(segStart, i);
          if (seg.length > 1) {
            ctx.beginPath();
            const [px0, py0] = toPixel(seg[0][0], seg[0][1]);
            ctx.moveTo(px0, py0);
            for (let j = 1; j < seg.length; j++) {
              const [px, py] = toPixel(seg[j][0], seg[j][1]);
              ctx.lineTo(px, py);
            }
            ctx.stroke();
          }
          segStart = i;
        }
      }
    } else if (mode === 'constellation' || mode === 'symbol') {
      for (const [x, y] of data) {
        const [px, py] = toPixel(x, y);
        ctx.beginPath();
        ctx.arc(px, py, 2, 0, Math.PI * 2);
        ctx.fill();
      }
    } else {
      // fft / mixer / fll — line plot
      if (data.length > 1) {
        ctx.beginPath();
        const [px0, py0] = toPixel(data[0][0], data[0][1]);
        ctx.moveTo(px0, py0);
        for (let i = 1; i < data.length; i++) {
          const [px, py] = toPixel(data[i][0], data[i][1]);
          ctx.lineTo(px, py);
        }
        ctx.stroke();
      }
    }

    // Plot title (top-left)
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '10px monospace';
    ctx.fillText(plot.title, 5, 13);

    // Channel label (top-right)
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '9px monospace';
    const chanLabel = `ch:${plot.chan}`;
    const labelW = ctx.measureText(chanLabel).width;
    ctx.fillText(chanLabel, W - labelW - 5, 13);
  }, [plot, lineColor]);

  return (
    <canvas
      ref={canvasRef}
      width={CANVAS_W}
      height={CANVAS_H}
      style={{ display: 'block', width: '100%', height: 'auto' }}
    />
  );
}

interface Props {
  plots: Record<string, PlotResponse>;
  onTogglePlot: (type: string) => void;
}

export default function PlotPanel({ plots, onTogglePlot }: Props) {
  const activeModes = new Set(Object.values(plots).map((p) => p.mode));
  const hasAny = activeModes.size > 0;

  return (
    <Paper elevation={1} sx={{ p: 1.5, border: '1px solid #2a2a2a' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <ShowChartIcon fontSize="small" sx={{ color: 'text.secondary' }} />
        <Typography variant="subtitle2" color="text.secondary">
          Signal Plots
        </Typography>
      </Box>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: hasAny ? 1.5 : 0 }}>
        {PLOT_TOGGLES.map(({ cmd, label, mode }) => (
          <Tooltip key={cmd} title={`Toggle ${label} plot`} arrow>
            <Button
              size="small"
              variant={activeModes.has(mode) ? 'contained' : 'outlined'}
              color={activeModes.has(mode) ? 'primary' : 'inherit'}
              sx={{ minWidth: 0, px: 1.5, fontSize: '0.7rem' }}
              onClick={() => onTogglePlot(cmd)}
            >
              {label}
            </Button>
          </Tooltip>
        ))}
      </Box>

      {hasAny ? (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
            gap: 1,
          }}
        >
          {Object.values(plots).map((plot) => (
            <Box
              key={`${plot.chan}:${plot.mode}`}
              sx={{ bgcolor: '#0a0a0a', borderRadius: '4px', overflow: 'hidden' }}
            >
              <PlotCanvas plot={plot} />
            </Box>
          ))}
        </Box>
      ) : (
        <Typography
          variant="caption"
          color="text.disabled"
          sx={{ display: 'block', textAlign: 'center', py: 1 }}
        >
          Toggle a plot type above to enable signal visualization
        </Typography>
      )}
    </Paper>
  );
}
