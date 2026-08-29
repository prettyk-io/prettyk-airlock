/**
 * COS-047: Reusable Empty State component.
 */
import { type ReactNode } from 'react';
import { Box, Typography, Button, Paper } from '@mui/material';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  actionIcon?: ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
  actionIcon,
}: EmptyStateProps) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 4,
        textAlign: 'center',
        borderRadius: 2,
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 1.5,
        minHeight: 180,
      }}
    >
      {icon && (
        <Box
          sx={{
            p: 1.5,
            borderRadius: '50%',
            bgcolor: 'action.hover',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'text.secondary',
            mb: 0.5,
          }}
        >
          {icon}
        </Box>
      )}
      <Typography variant="subtitle1" sx={{ fontWeight: 700, color: 'text.primary' }}>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: 440, fontSize: 13 }}>
          {description}
        </Typography>
      )}
      {actionLabel && onAction && (
        <Button
          variant="contained"
          size="small"
          startIcon={actionIcon}
          onClick={onAction}
          sx={{ mt: 1, textTransform: 'none', fontWeight: 600, fontSize: 12 }}
        >
          {actionLabel}
        </Button>
      )}
    </Paper>
  );
}
