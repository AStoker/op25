import Box from '@mui/material/Box';
import { highlight } from '../../utils/callTranscripts';
import type { HighlightKind } from '../../utils/callTranscripts';

interface HighlightedTextProps {
  text: string;
  /** Configured alert keywords found in the text. */
  keywords?: readonly string[];
  /** Terms the user is currently searching for. */
  search?: readonly string[];
}

/** Keyword hits keep the alert colour; a search hit is deliberately quieter —
 *  it says "this is the bit you asked for", not "this call matters". */
const MARK_SX: Record<HighlightKind, object> = {
  keyword: { bgcolor: 'warning.light', color: 'warning.contrastText' },
  search:  { bgcolor: 'action.selected', color: 'inherit', fontWeight: 600 },
};

/**
 * Text with matched runs marked.
 *
 * Shared because Call History and the clip list render the same thing, and once
 * there were two kinds of mark the duplicated JSX would have had to agree about
 * both.
 */
export default function HighlightedText({ text, keywords = [], search = [] }: HighlightedTextProps) {
  return (
    <>
      {highlight(text, keywords, search).map((part, i) =>
        typeof part === 'string' ? (
          <span key={i}>{part}</span>
        ) : (
          <Box
            key={i}
            component="mark"
            sx={{ px: 0.25, borderRadius: 0.5, ...MARK_SX[part.kind] }}
          >
            {part.hit}
          </Box>
        ),
      )}
    </>
  );
}
