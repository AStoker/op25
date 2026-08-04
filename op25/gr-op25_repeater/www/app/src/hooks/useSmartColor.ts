import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTheme } from '@mui/material/styles';
import { useOp25Service } from '../services/op25Service';
import {
  DEFAULT_SMART_COLORS, matchSmartColor, readableOn,
} from '../utils/smartColors';
import type { SmartColorRule } from '../types/op25';

const STORAGE_KEY_ENABLED = 'op25.smartColors.enabled';

function storedEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY_ENABLED) !== '0';
  } catch {
    return true;   // on by default, as in the legacy UI
  }
}

/** Read/write the smart-colour on/off preference. The config supplies the
 *  rules; this is the user's switch, kept separate exactly as the legacy UI
 *  does (JSON = rules, checkbox = whether to use them). */
export function useSmartColorsEnabled(): [boolean, (v: boolean) => void] {
  const [enabled, setEnabled] = useState<boolean>(storedEnabled);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY_ENABLED, enabled ? '1' : '0');
    } catch { /* ignore */ }
  }, [enabled]);

  // Same key in every tab/card, so a change in one place is seen everywhere on
  // the next render of any consumer.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY_ENABLED) setEnabled(storedEnabled());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  return [enabled, setEnabled];
}

/**
 * Returns `tint(tag)` → a CSS colour for that talkgroup tag, or undefined for
 * "leave it alone".
 *
 * Rules come from terminal_config's `smart_colors`, falling back to the same
 * built-in defaults the legacy UI uses. The result is contrast-corrected for
 * the active theme, because these palettes were picked for a dark-only UI and
 * a mid-blue on white is close to unreadable.
 */
export function useSmartColor(): (tag: string | null | undefined) => string | undefined {
  const { terminalConfig } = useOp25Service();
  const theme = useTheme();
  const [enabled] = useSmartColorsEnabled();

  const rules: SmartColorRule[] = useMemo(() => {
    const configured = terminalConfig?.smart_colors;
    return Array.isArray(configured) && configured.length > 0
      ? configured
      : DEFAULT_SMART_COLORS;
  }, [terminalConfig]);

  const background = theme.palette.background.paper;

  return useCallback((tag: string | null | undefined) => {
    if (!enabled) return undefined;
    const hit = matchSmartColor(tag, rules);
    return hit ? readableOn(hit, background) : undefined;
  }, [enabled, rules, background]);
}
