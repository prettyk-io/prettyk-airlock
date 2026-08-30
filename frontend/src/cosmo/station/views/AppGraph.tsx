/**
 * AppGraph — временный плейсхолдер.
 * Используйте ProjectGraph.tsx (React Flow) для графа проекта.
 */
import { Box, Typography, Button } from '@mui/material';
import { ErrorBoundary } from '../../shared/ErrorBoundary';

export function AppGraph() {
  return (
    <ErrorBoundary viewName="App Graph">
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>
          Граф зависимостей приложений
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Перейдите в карточку проекта и откройте вкладку «Граф зависимостей».
        </Typography>
      </Box>
    </ErrorBoundary>
  );
}