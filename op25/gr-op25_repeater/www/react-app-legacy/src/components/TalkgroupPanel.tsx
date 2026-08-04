import { useMemo } from 'react';
import {
  Paper, Box, Typography, Chip, Tooltip, Button,
  Divider, ButtonGroup,
} from '@mui/material';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import BlockIcon from '@mui/icons-material/Block';
import type { SmartColor, Preset, TgCacheEntry, CallHistoryEntry } from '../types';

interface Props {
  presets: Preset[];
  tgTagCache: Record<string, Record<string, TgCacheEntry>>;
  currentTgid: number | null;
  callHistory: CallHistoryEntry[];
  smartColors: SmartColor[];
  settingsSmartColors: boolean;
  onHold: (tgid: number) => void;
  onLockout: (tgid: number) => void;
}

function getSmartColor(text: string, smartColors: SmartColor[], enabled: boolean): string | undefined {
  if (!enabled || !text) return undefined;
  const lower = text.toLowerCase();
  for (const sc of smartColors) {
    if (sc.keywords.some((kw) => lower.includes(kw.toLowerCase()))) return sc.color;
  }
  return undefined;
}

interface RecentTg {
  tgid: string;
  tgName: string;
  sysHex: string;
  lastMs: number;
}

export default function TalkgroupPanel({
  presets, tgTagCache, currentTgid, callHistory,
  smartColors, settingsSmartColors, onHold, onLockout,
}: Props) {
  // Derive recently-seen TGs from call history (up to 30 unique TGs)
  const recentTgs = useMemo<RecentTg[]>(() => {
    const seen = new Map<string, RecentTg>();
    for (const entry of callHistory) {
      const key = `${entry.sysHex}|${entry.tgid}`;
      if (!seen.has(key)) {
        seen.set(key, { tgid: entry.tgid, tgName: entry.tgName, sysHex: entry.sysHex, lastMs: entry.epochMs });
      }
      if (seen.size >= 30) break;
    }
    return Array.from(seen.values());
  }, [callHistory]);

  // Also collect from tgTagCache for any TGs seen via trunk_update
  const cachedTgs = useMemo<RecentTg[]>(() => {
    const result: RecentTg[] = [];
    for (const [sysHex, tgMap] of Object.entries(tgTagCache)) {
      for (const [tgid, entry] of Object.entries(tgMap)) {
        if (entry.tag) {
          result.push({ tgid, tgName: entry.tag, sysHex, lastMs: 0 });
        }
      }
    }
    return result.slice(0, 50);
  }, [tgTagCache]);

  // Merge: recentTgs take priority (have timestamps)
  const allTgs = useMemo<RecentTg[]>(() => {
    const keys = new Set<string>();
    const merged: RecentTg[] = [];
    for (const t of recentTgs) {
      const k = `${t.sysHex}|${t.tgid}`;
      if (!keys.has(k)) { keys.add(k); merged.push(t); }
    }
    for (const t of cachedTgs) {
      const k = `${t.sysHex}|${t.tgid}`;
      if (!keys.has(k)) { keys.add(k); merged.push(t); }
    }
    return merged.slice(0, 40);
  }, [recentTgs, cachedTgs]);

  const hasPresets = presets.length > 0;
  const hasTgs = allTgs.length > 0;

  if (!hasPresets && !hasTgs) return null;

  return (
    <Paper elevation={1} sx={{ p: 1.5, border: '1px solid #2a2a2a' }}>
      {hasPresets && (
        <>
          <Typography
            variant="subtitle2"
            sx={{ mb: 1, color: 'text.secondary', fontSize: '0.7rem' }}
          >
            PRESETS
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb: hasTgs ? 1.5 : 0 }}>
            {presets.map((preset) => {
              const isActive = currentTgid === preset.tgid;
              const color = getSmartColor(preset.label, smartColors, settingsSmartColors);
              return (
                <Tooltip
                  key={preset.id}
                  title={
                    <Box>
                      <div><strong>{preset.label}</strong></div>
                      <div>TGID: {preset.tgid}</div>
                      <div>Click to hold · Right-click for options</div>
                    </Box>
                  }
                  arrow
                >
                  <Button
                    size="small"
                    variant={isActive ? 'contained' : 'outlined'}
                    color={isActive ? 'primary' : 'inherit'}
                    onClick={() => onHold(preset.tgid)}
                    sx={{
                      fontSize: '0.72rem',
                      px: 1.25,
                      py: 0.4,
                      minWidth: 0,
                      color: isActive ? '#000' : (color ?? 'inherit'),
                      borderColor: color ?? undefined,
                      fontWeight: isActive ? 700 : 500,
                    }}
                  >
                    {preset.label}
                  </Button>
                </Tooltip>
              );
            })}
          </Box>
        </>
      )}

      {hasPresets && hasTgs && <Divider sx={{ my: 1 }} />}

      {hasTgs && (
        <>
          <Typography
            variant="subtitle2"
            sx={{ mb: 1, color: 'text.secondary', fontSize: '0.7rem' }}
          >
            SEEN TALKGROUPS
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
            {allTgs.map((tg) => {
              const tgNum = parseInt(tg.tgid, 10);
              const isActive = !isNaN(tgNum) && currentTgid === tgNum;
              const color = getSmartColor(tg.tgName, smartColors, settingsSmartColors);
              const label = tg.tgName.length > 18 ? tg.tgName.substring(0, 17) + '…' : tg.tgName;

              return (
                <Tooltip
                  key={`${tg.sysHex}|${tg.tgid}`}
                  title={
                    <Box>
                      <div><strong>{tg.tgName}</strong></div>
                      <div>TGID: {tg.tgid} · Sys: {tg.sysHex}</div>
                      <div>
                        <em>Click to hold · Block button to lockout</em>
                      </div>
                    </Box>
                  }
                  arrow
                >
                  <Box sx={{ display: 'inline-flex', alignItems: 'center' }}>
                    <ButtonGroup size="small" variant={isActive ? 'contained' : 'outlined'}>
                      <Button
                        sx={{
                          fontSize: '0.7rem',
                          px: 1,
                          py: 0.25,
                          minWidth: 0,
                          color: isActive ? '#000' : (color ?? 'inherit'),
                          borderColor: isActive ? undefined : (color ?? undefined),
                          fontWeight: isActive ? 700 : 400,
                          borderTopRightRadius: 0,
                          borderBottomRightRadius: 0,
                        }}
                        onClick={() => onHold(tgNum)}
                        disabled={isNaN(tgNum)}
                      >
                        <PauseCircleIcon sx={{ fontSize: 12, mr: 0.4 }} />
                        {label}
                      </Button>
                      <Tooltip title={`Lockout TGID ${tg.tgid}`} arrow>
                        <Button
                          sx={{
                            px: 0.5,
                            minWidth: 0,
                            borderTopLeftRadius: 0,
                            borderBottomLeftRadius: 0,
                          }}
                          color="warning"
                          onClick={() => !isNaN(tgNum) && onLockout(tgNum)}
                          disabled={isNaN(tgNum)}
                        >
                          <BlockIcon sx={{ fontSize: 11 }} />
                        </Button>
                      </Tooltip>
                    </ButtonGroup>
                  </Box>
                </Tooltip>
              );
            })}
          </Box>
        </>
      )}

      {/* Active hold indicator */}
      {currentTgid != null && (
        <Box sx={{ mt: 1.5, pt: 1, borderTop: '1px solid #2a2a2a', display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Currently holding:
          </Typography>
          <Chip
            label={`TGID ${currentTgid}`}
            size="small"
            color="primary"
            variant="filled"
            sx={{ fontSize: '0.7rem', height: 20, color: '#000', fontWeight: 700 }}
          />
          <Tooltip title="Resume scanning (release hold)" arrow>
            <Button
              size="small"
              variant="text"
              sx={{ fontSize: '0.68rem', py: 0, minWidth: 0 }}
              onClick={() => onHold(0)}
            >
              Release
            </Button>
          </Tooltip>
        </Box>
      )}
    </Paper>
  );
}
