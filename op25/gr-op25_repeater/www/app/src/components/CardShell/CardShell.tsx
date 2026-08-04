import { useCallback, useEffect, useState } from 'react';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Collapse from '@mui/material/Collapse';
import IconButton from '@mui/material/IconButton';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { ReactNode } from 'react';

interface CardShellProps {
  title: string;
  children?: ReactNode;
  /** Start collapsed the first time this card is seen on this browser. Once the
   *  user toggles it, their choice wins and is remembered. */
  defaultCollapsed?: boolean;
  /** Set false for a card that should never be collapsible. */
  collapsible?: boolean;
}

/** localStorage key for one card's collapsed state, derived from its title. */
function storageKey(title: string): string {
  return `op25.card.${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.collapsed`;
}

function storedCollapsed(title: string): boolean | null {
  try {
    const v = window.localStorage.getItem(storageKey(title));
    if (v === '1') return true;
    if (v === '0') return false;
  } catch { /* private mode / storage disabled */ }
  return null;
}

/**
 * The frame every panel sits in: outlined card, bold title, and a collapse
 * toggle so panels that are not interesting on this install can be folded away.
 *
 * Collapsed state persists per card, so the dashboard stays how it was left.
 * Children stay mounted while collapsed — the WebSocket-fed tables keep their
 * filter text and scroll position, and a collapsed card is not a paused one.
 */
export default function CardShell({
  title,
  children,
  defaultCollapsed = false,
  collapsible = true,
}: CardShellProps) {
  const [collapsed, setCollapsed] = useState<boolean>(
    () => storedCollapsed(title) ?? defaultCollapsed,
  );

  // Persist on every toggle rather than on unmount, so a reload immediately
  // after a click still remembers.
  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey(title), collapsed ? '1' : '0');
    } catch { /* ignore */ }
  }, [title, collapsed]);

  const toggle = useCallback(() => setCollapsed((v) => !v), []);

  if (!collapsible) {
    return (
      <Card variant="outlined">
        <CardHeader
          title={title}
          titleTypographyProps={{ variant: 'subtitle1', fontWeight: 'bold' }}
          sx={{ pb: 0 }}
        />
        <CardContent sx={{ '&:last-child': { pb: 2 } }}>{children}</CardContent>
      </Card>
    );
  }

  return (
    <Card variant="outlined">
      <CardHeader
        title={title}
        titleTypographyProps={{ variant: 'subtitle1', fontWeight: 'bold' }}
        onClick={toggle}
        action={
          <IconButton
            aria-label={collapsed ? `Expand ${title}` : `Collapse ${title}`}
            aria-expanded={!collapsed}
            size="small"
            // The whole header is the hit target; this is just the affordance.
            onClick={(e) => { e.stopPropagation(); toggle(); }}
            sx={{
              transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: (t) => t.transitions.create('transform', { duration: 150 }),
            }}
          >
            <ExpandMoreIcon />
          </IconButton>
        }
        sx={{
          pb: collapsed ? 1.5 : 0,
          cursor: 'pointer',
          userSelect: 'none',
          '& .MuiCardHeader-action': { alignSelf: 'center', mt: 0, mr: 0 },
        }}
      />
      <Collapse in={!collapsed} timeout={150}>
        <CardContent sx={{ pt: 0, '&:last-child': { pb: 2 } }}>{children}</CardContent>
      </Collapse>
    </Card>
  );
}
