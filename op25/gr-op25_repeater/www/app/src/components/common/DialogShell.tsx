import Box from '@mui/material/Box';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import CloseIcon from '@mui/icons-material/Close';
import type { ReactNode } from 'react';
import { useIsPhone } from '../../hooks/useIsPhone';

interface DialogShellProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Rendered under the title, inside the same sticky header row. */
  subheader?: ReactNode;
  /** Footer content, left-aligned before the close button. */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * The frame the modal panels sit in — the dialog equivalent of `CardShell`.
 *
 * Full-screen below `sm`, because a scrolling dialog inside a 390px viewport
 * with margins on all four sides leaves too little room to read a config in.
 * The content area is the only thing that scrolls, so wide content (JSON,
 * tables) has to keep its own `overflow-x` rather than widening the page.
 */
export default function DialogShell({
  open, onClose, title, subheader, actions, children,
}: DialogShellProps) {
  const isPhone = useIsPhone();

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="md"
      fullScreen={isPhone}
      aria-labelledby="dialog-shell-title"
    >
      <DialogTitle
        id="dialog-shell-title"
        component="div"
        sx={{ pr: 6, pb: subheader ? 0 : undefined }}
      >
        <Box sx={{ typography: 'h6', fontWeight: 'bold' }}>{title}</Box>
        {subheader}
        <IconButton
          aria-label="close"
          onClick={onClose}
          sx={{ position: 'absolute', right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>{children}</DialogContent>

      {/* Rendered only when there is something to put in it: an empty action
          bar is 52px of nothing, which on a phone is a whole row of content. */}
      {actions && <DialogActions>{actions}</DialogActions>}
    </Dialog>
  );
}
