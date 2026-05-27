import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import type { ReactNode } from 'react';

interface CardShellProps {
  title: string;
  children?: ReactNode;
}

export default function CardShell({ title, children }: CardShellProps) {
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
