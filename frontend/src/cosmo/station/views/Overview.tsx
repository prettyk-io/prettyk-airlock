/**
 * Overview — перенаправляет на ProjectsOverview.
 */
import { Box, Button } from '@mui/material';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { ProjectsOverview } from './ProjectsOverview';

interface OverviewProps {
  onNavigateToView?: (view: string, params?: Record<string, string>) => void;
}

export function Overview({ onNavigateToView }: OverviewProps) {
  return (
    <ErrorBoundary viewName="Overview">
      <ProjectsOverview onNavigate={onNavigateToView || (() => {})} />
    </ErrorBoundary>
  );
}