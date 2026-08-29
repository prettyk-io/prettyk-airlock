/**
 * COS-047: View-level Error Boundary component for graceful crash recovery.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Box, Typography, Button, Paper, Alert } from '@mui/material';
import { Refresh, Warning } from '@mui/icons-material';

interface Props {
  children: ReactNode;
  viewName?: string;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error(`[ErrorBoundary:${this.props.viewName || 'View'}]`, error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  public override render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <Paper
          variant="outlined"
          sx={{
            p: 4,
            borderRadius: 2,
            bgcolor: 'background.paper',
            border: '1px solid',
            borderColor: 'error.light',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
            gap: 2,
            my: 2,
          }}
        >
          <Box
            sx={{
              p: 1.5,
              borderRadius: '50%',
              bgcolor: 'error.lighter',
              color: 'error.main',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Warning sx={{ fontSize: 32 }} />
          </Box>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700, color: 'text.primary' }}>
              Произошла ошибка при отрисовке {this.props.viewName ? `компонента «${this.props.viewName}»` : 'страницы'}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 500, fontSize: 13 }}>
              Мы изолировали сбой, чтобы остальные модули продолжали работать стабильно.
            </Typography>
          </Box>

          {this.state.error && (
            <Alert severity="error" sx={{ width: '100%', maxWidth: 600, textAlign: 'left', fontSize: 12, fontFamily: 'monospace' }}>
              {this.state.error.message}
            </Alert>
          )}

          <Button
            variant="contained"
            color="primary"
            size="small"
            startIcon={<Refresh />}
            onClick={this.handleReset}
            sx={{ textTransform: 'none', fontWeight: 600 }}
          >
            Попробовать снова
          </Button>
        </Paper>
      );
    }

    return this.props.children;
  }
}
