/**
 * COS-047: Toast Container component rendering active toast notifications.
 */
import { Box, Alert, IconButton, Slide } from '@mui/material';
import { Close } from '@mui/icons-material';
import { useToastMessages, toast } from './toast';

export function ToastContainer() {
  const toasts = useToastMessages();

  if (toasts.length === 0) return null;

  return (
    <Box
      sx={{
        position: 'fixed',
        bottom: 24,
        right: 24,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        maxWidth: 400,
        width: '100%',
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => (
        <Slide key={t.id} direction="left" in mountOnEnter unmountOnExit>
          <Alert
            severity={t.severity}
            variant="filled"
            action={
              <IconButton
                aria-label="close"
                color="inherit"
                size="small"
                onClick={() => toast.dismiss(t.id)}
              >
                <Close fontSize="inherit" />
              </IconButton>
            }
            sx={{
              pointerEvents: 'auto',
              boxShadow: '0 4px 14px rgba(0,0,0,0.2)',
              borderRadius: 2,
              fontSize: 13,
              fontWeight: 500,
              alignItems: 'center',
            }}
          >
            {t.message}
          </Alert>
        </Slide>
      ))}
    </Box>
  );
}
