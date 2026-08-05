import {
  Dialog, DialogContent, DialogTitle, IconButton, Typography,
  Box, Link, Divider,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function AboutDialog({ open, onClose }: Props) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 2, pb: 1 }}>
        <Box
          component="svg"
          viewBox="0 0 180 40"
          sx={{ height: 36 }}
          xmlns="http://www.w3.org/2000/svg"
        >
          <polygon points="8,34 18,10 28,34" fill="#66aaff" />
          <rect x="8" y="34" width="20" height="3" fill="#ffaa55" rx="1" />
          <text x="34" y="28" fill="#ffffff" fontSize="20" fontFamily="Arial" fontWeight="bold">
            OP25
          </text>
        </Box>
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>

      <Divider />

      <DialogContent sx={{ pt: 2 }}>
        <Typography variant="body2" gutterBottom color="text.secondary">
          © 2017–2026 Max H. Parke &amp; Graham J. Norbury [boatbod version]
          <br />
          React UI — Michael Rose
        </Typography>

        <Typography variant="body2" sx={{ mt: 1.5 }} gutterBottom>
          This program comes with <strong>ABSOLUTELY NO WARRANTY</strong>.
        </Typography>

        <Typography variant="body2" gutterBottom>
          OP25 is free software, and you are welcome to redistribute it under certain conditions.
          Refer to the License link below for details.
        </Typography>

        <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography variant="body2">
            <strong>License:</strong>{' '}
            <Link href="https://www.gnu.org/licenses/gpl-3.0.en.html" target="_blank" rel="noreferrer">
              GPLv3
            </Link>
          </Typography>
          <Typography variant="body2">
            <strong>Original:</strong>{' '}
            <Link href="https://gitea.osmocom.org/op25/op25" target="_blank" rel="noreferrer">
              gitea.osmocom.org/op25/op25
            </Link>
          </Typography>
          <Typography variant="body2">
            <strong>boatbod fork:</strong>{' '}
            <Link href="https://github.com/boatbod/op25" target="_blank" rel="noreferrer">
              github.com/boatbod/op25
            </Link>
          </Typography>
          <Typography variant="body2">
            <strong>Website:</strong>{' '}
            <Link href="http://op25.osmocom.org" target="_blank" rel="noreferrer">
              op25.osmocom.org
            </Link>
          </Typography>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
