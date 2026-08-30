/**
 * COS-057: Navigation Breadcrumbs component — KITS edition.
 *
 * Simple breadcrumb: Текущий раздел.
 */
import { Box, Breadcrumbs as MuiBreadcrumbs, Typography } from '@mui/material';
import { NavigateNext } from '@mui/icons-material';

interface BreadcrumbsProps {
  viewTitle?: string;
  onNavigateToView?: (view: string) => void;
}

export function Breadcrumbs({ viewTitle, onNavigateToView }: BreadcrumbsProps) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center' }}>
      <MuiBreadcrumbs
        separator={<NavigateNext sx={{ fontSize: 14, color: 'text.disabled' }} />}
        aria-label="breadcrumb"
        sx={{ '& .MuiBreadcrumbs-ol': { alignItems: 'center', flexWrap: 'nowrap' } }}
      >
        <Typography sx={{ fontSize: 12, fontWeight: 700, color: 'text.primary' }}>
          {viewTitle || 'Control Station'}
        </Typography>
      </MuiBreadcrumbs>
    </Box>
  );
}