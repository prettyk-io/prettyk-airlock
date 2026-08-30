/**
 * FR-001: Empty table placeholder.
 */
import { Box, Typography, Button } from '@mui/material';

interface EmptyTableProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: React.ReactNode;
}

export function EmptyTable({ title, description, actionLabel, onAction, icon }: EmptyTableProps) {
  return (
    <Box sx={{ py: 6, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, color: 'text.secondary' }}>
      {icon && <Box sx={{ mb: 1, opacity: 0.5 }}>{icon}</Box>}
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title}</Typography>
      {description && <Typography variant="body2" color="text.disabled">{description}</Typography>}
      {actionLabel && onAction && (
        <Button variant="outlined" size="small" onClick={onAction} sx={{ mt: 1, textTransform: 'none' }}>
          {actionLabel}
        </Button>
      )}
    </Box>
  );
}