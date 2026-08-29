/**
 * COS-057: Navigation Breadcrumbs component.
 *
 * Header breadcrumb chain: КИТС (Domain) → Проект (Group) → Приложение (App) → Раздел.
 */
import { Box, Breadcrumbs as MuiBreadcrumbs, Typography, Link as MuiLink, Chip } from '@mui/material';
import { NavigateNext, AccountTree, Folder, Apps } from '@mui/icons-material';

export interface BreadcrumbItem {
  label: string;
  id?: string;
  type?: 'domain' | 'group' | 'app' | 'view';
  onClick?: () => void;
}

interface BreadcrumbsProps {
  domain?: string;
  group?: string;
  app?: string;
  viewTitle?: string;
  onNavigateToView?: (view: string) => void;
  onSelectDomain?: (domain: string) => void;
}

export function Breadcrumbs({
  domain = 'all',
  group,
  app,
  viewTitle,
  onNavigateToView,
  onSelectDomain,
}: BreadcrumbsProps) {
  const domainLabel =
    domain === 'all'
      ? 'Все домены'
      : domain === 'cbr'
      ? 'Цифровой рубль'
      : domain === 'payments'
      ? 'Платежи'
      : domain;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center' }}>
      <MuiBreadcrumbs
        separator={<NavigateNext sx={{ fontSize: 14, color: 'text.disabled' }} />}
        aria-label="breadcrumb"
        sx={{
          '& .MuiBreadcrumbs-ol': {
            alignItems: 'center',
            flexWrap: 'nowrap',
          },
        }}
      >
        {/* Level 1: Domain / КИТС */}
        <MuiLink
          component="button"
          underline="hover"
          onClick={() => {
            if (onNavigateToView) onNavigateToView('domains');
            if (onSelectDomain) onSelectDomain(domain);
          }}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            fontSize: 12,
            fontWeight: 600,
            color: 'text.secondary',
            cursor: 'pointer',
            border: 'none',
            background: 'none',
            p: 0,
            '&:hover': { color: 'primary.main' },
          }}
        >
          <AccountTree sx={{ fontSize: 14, color: 'primary.main' }} />
          <span>{domainLabel}</span>
        </MuiLink>

        {/* Level 2: Group (Optional) */}
        {group && (
          <MuiLink
            component="button"
            underline="hover"
            onClick={() => onNavigateToView && onNavigateToView('applications')}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              fontSize: 12,
              fontWeight: 600,
              color: 'text.secondary',
              cursor: 'pointer',
              border: 'none',
              background: 'none',
              p: 0,
              '&:hover': { color: 'warning.main' },
            }}
          >
            <Folder sx={{ fontSize: 14, color: 'warning.main' }} />
            <span>{group}</span>
          </MuiLink>
        )}

        {/* Level 3: Application (Optional) */}
        {app && (
          <MuiLink
            component="button"
            underline="hover"
            onClick={() => onNavigateToView && onNavigateToView('applications')}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              fontSize: 12,
              fontWeight: 600,
              color: 'text.secondary',
              cursor: 'pointer',
              border: 'none',
              background: 'none',
              p: 0,
              '&:hover': { color: 'info.main' },
            }}
          >
            <Apps sx={{ fontSize: 14, color: 'info.main' }} />
            <span style={{ fontFamily: 'monospace' }}>{app}</span>
          </MuiLink>
        )}

        {/* Level 4: Current View Title */}
        {viewTitle && (
          <Typography
            sx={{
              fontSize: 12,
              fontWeight: 700,
              color: 'text.primary',
            }}
          >
            {viewTitle}
          </Typography>
        )}
      </MuiBreadcrumbs>
    </Box>
  );
}
