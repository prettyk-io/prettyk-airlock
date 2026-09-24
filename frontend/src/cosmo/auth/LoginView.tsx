/**
 * COS-158: LoginView — боевая форма входа (email/password → JWT-сессия).
 *
 * Честные состояния:
 *   - idle         — пустая форма
 *   - submitting   — спиннер на кнопке, поля залочены
 *   - 401          — «Неверный email или пароль»
 *   - 503          — auth-сервис не стартовал / секреты не сидированы
 *   - network/other — сырое сообщение ошибки
 */
import { useState, type FormEvent } from 'react';
import { Box, Paper, Typography, TextField, Button, Alert, CircularProgress } from '@mui/material';
import { AccountCircle, LockOpen } from '@mui/icons-material';
import { login } from './authStore';

function mapLoginError(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (msg.includes('invalid credentials') || msg.includes('401')) {
    return 'Неверный email или пароль';
  }
  if (msg.includes('503') || msg.includes('not bootstrapped')) {
    return 'Auth-сервис недоступен — обратитесь к администратору';
  }
  return msg;
}

export function LoginView() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Введите email и пароль');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      // Успех: App перерисуется через useSession() автоматически.
    } catch (err) {
      setError(mapLoginError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Box
      data-testid="login-view"
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        px: 2,
        bgcolor: 'background.default',
      }}
    >
      <Paper elevation={4} sx={{ p: 4, width: '100%', maxWidth: 400, borderRadius: 3 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AccountCircle sx={{ color: 'primary.main' }} />
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Cosmoport
            </Typography>
          </Box>
          <Typography variant="body2" color="text.secondary">
            Вход в Control Station
          </Typography>

          <Box component="form" onSubmit={handleSubmit} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              fullWidth
              autoFocus
              size="small"
              data-testid="login-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
            />
            <TextField
              label="Пароль"
              type="password"
              autoComplete="current-password"
              fullWidth
              size="small"
              data-testid="login-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />

            {error && (
              <Alert severity="error" data-testid="login-error">
                {error}
              </Alert>
            )}

            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="medium"
              data-testid="login-submit"
              disabled={submitting}
              startIcon={submitting ? <CircularProgress size={16} /> : <LockOpen />}
            >
              {submitting ? 'Входим…' : 'Войти'}
            </Button>
          </Box>
        </Box>
      </Paper>
    </Box>
  );
}