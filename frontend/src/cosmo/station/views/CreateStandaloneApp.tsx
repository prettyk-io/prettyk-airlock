/**
 * POST-FLASH-002: Standalone App Creation — single app + repo, no project.
 *
 * Automatic characteristic / level detection based on structure,
 * artifact kind, and repository shape (manual level selection is optional, not mandatory).
 */
import { useState, useMemo } from 'react';
import {
  Box, Typography, Button, TextField, Select, MenuItem,
  Paper, Alert, CircularProgress, Chip, Grid, Collapse,
} from '@mui/material';
import { Add, CheckCircle, AutoAwesome, Tune } from '@mui/icons-material';
import { api, type Application } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { toast } from '../../shared/toast';

interface StandaloneAppProps {
  onComplete?: (app: Application) => void;
  onCancel: () => void;
}

const ARTIFACT_KINDS = ['docker', 'jar', 'npm', 'pip', 'binary', 'helm', 'wasm'];

export function detectAppCharacteristics(appId: string, repoPath: string, artifactKind: string): {
  suggestedLevel: number;
  label: string;
  reason: string;
} {
  const lower = `${appId} ${repoPath}`.toLowerCase();

  if (artifactKind === 'npm' || artifactKind === 'pip' || artifactKind === 'jar' || lower.includes('lib') || lower.includes('sdk') || lower.includes('common') || lower.includes('shared')) {
    return {
      suggestedLevel: 0,
      label: 'L0 Библиотека / Shared SDK',
      reason: 'Определено по пакетному артефакту / структуре библиотеки',
    };
  }

  if (lower.includes('gw') || lower.includes('gateway') || lower.includes('router') || lower.includes('proxy')) {
    return {
      suggestedLevel: 1,
      label: 'L1 API Gateway',
      reason: 'Определено по структуре шлюза маршрутизации',
    };
  }

  if (lower.includes('ui') || lower.includes('frontend') || lower.includes('web') || lower.includes('spa') || lower.includes('client')) {
    return {
      suggestedLevel: 1,
      label: 'L1 Фронтенд / Клиент',
      reason: 'Определено по структуре клиентского приложения',
    };
  }

  if (artifactKind === 'wasm' || lower.includes('capsule') || lower.includes('edge')) {
    return {
      suggestedLevel: 1,
      label: 'L1 Капсула (WASM / Edge)',
      reason: 'Определено по WASM/Edge исполнению',
    };
  }

  if (lower.includes('core') || lower.includes('platform') || lower.includes('subsystem')) {
    return {
      suggestedLevel: 2,
      label: 'L2 Подсистема / Core Service',
      reason: 'Определено по платформенному масштабу',
    };
  }

  return {
    suggestedLevel: 1,
    label: 'L1 Микросервис / Приложение',
    reason: 'Автоматический базовый сервис по умолчанию',
  };
}

export function CreateStandaloneApp({ onComplete, onCancel }: StandaloneAppProps) {
  const [appId, setAppId] = useState('');
  const [repoPath, setRepoPath] = useState('');
  const [branch, setBranch] = useState('main');
  const [artifactKind, setArtifactKind] = useState('docker');
  const [manualLevelOverride, setManualLevelOverride] = useState<number | null>(null);
  const [showOverride, setShowOverride] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);

  const autoProfile = useMemo(
    () => detectAppCharacteristics(appId, repoPath, artifactKind),
    [appId, repoPath, artifactKind]
  );

  const effectiveLevel = manualLevelOverride !== null ? manualLevelOverride : autoProfile.suggestedLevel;

  const handleCreate = async () => {
    if (!appId.trim() || !repoPath.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const app = await api.createStandaloneApp({
        id: appId.trim(),
        level: effectiveLevel,
        repo_path: repoPath.trim(),
        branch: branch.trim() || 'main',
        artifact_kind: artifactKind,
        detected_profile: autoProfile.label,
      });
      setCreated(app);
      toast.success(`Приложение ${app.id} создано`);
      onComplete?.(app);
    } catch (err: unknown) {
      const msg = (err as Error)?.message || 'Ошибка создания приложения';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (created) {
    return (
      <ErrorBoundary viewName="App Created">
        <Box sx={{ py: 4, textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <CheckCircle sx={{ fontSize: 64, color: 'success.main', mx: 'auto' }} />
          <Typography variant="h5" sx={{ fontWeight: 700 }}>Приложение создано</Typography>
          <Paper variant="outlined" sx={{ p: 2, maxWidth: 400, mx: 'auto', borderRadius: 2 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 12 }}>
              <div><strong>ID:</strong> {created.id}</div>
              <div><strong>Уровень:</strong> L{created.level}</div>
              <div><strong>Repo:</strong> {created.repo_binding.repo_path}</div>
              <div><strong>Artifact:</strong> {created.artifact_kind || 'docker'}</div>
            </Box>
          </Paper>
          <Button variant="contained" onClick={() => onComplete?.(created)} sx={{ textTransform: 'none', fontWeight: 600, mx: 'auto' }}>
            Продолжить
          </Button>
        </Box>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary viewName="Create Standalone App">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 600 }}>
        <PageHeader
          title="Создать приложение без проекта"
          subtitle="Характеристики и уровень определяются автоматически. Позже приложение можно подключить к проектам."
          action={<Button size="small" variant="outlined" onClick={onCancel} sx={{ textTransform: 'none' }}>Отмена</Button>}
        />

        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField
            label="App ID"
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
            size="small"
            fullWidth
            required
            autoFocus
            placeholder="my-service"
          />

          <Grid container spacing={1}>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField
                label="Репозиторий (org/repo)"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                size="small"
                fullWidth
                required
                placeholder="org/my-service"
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 3 }}>
              <TextField
                label="Ветка"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                size="small"
                fullWidth
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 3 }}>
              <Select
                size="small"
                value={artifactKind}
                onChange={(e) => setArtifactKind(e.target.value)}
                fullWidth
              >
                {ARTIFACT_KINDS.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
              </Select>
            </Grid>
          </Grid>

          {/* Auto-detected characteristics card */}
          <Paper
            variant="outlined"
            sx={{
              p: 1.5,
              borderRadius: 2,
              bgcolor: 'action.hover',
              border: 1,
              borderColor: manualLevelOverride !== null ? 'warning.light' : 'primary.light',
            }}
          >
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <AutoAwesome sx={{ color: 'primary.main', fontSize: 18 }} />
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {manualLevelOverride !== null ? `Ручная корректировка: L${manualLevelOverride}` : `Автоопределение: ${autoProfile.label}`}
                </Typography>
              </Box>
              <Button
                size="small"
                startIcon={<Tune sx={{ fontSize: 14 }} />}
                onClick={() => setShowOverride(!showOverride)}
                sx={{ textTransform: 'none', fontSize: 11 }}
              >
                {showOverride ? 'Скрыть' : 'Скорректировать'}
              </Button>
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {manualLevelOverride !== null ? 'Установлен ручной override оператора' : autoProfile.reason}
            </Typography>

            <Collapse in={showOverride}>
              <Box sx={{ mt: 1.5, pt: 1.5, borderTop: 1, borderColor: 'divider', display: 'flex', gap: 1, alignItems: 'center' }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>Override уровня:</Typography>
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                  {[0, 1, 2].map((lvl) => (
                    <Chip
                      key={lvl}
                      label={`L${lvl}`}
                      size="small"
                      color={effectiveLevel === lvl ? 'primary' : 'default'}
                      variant={effectiveLevel === lvl ? 'filled' : 'outlined'}
                      onClick={() => setManualLevelOverride(lvl)}
                      sx={{ cursor: 'pointer', fontWeight: 600 }}
                    />
                  ))}
                  {manualLevelOverride !== null && (
                    <Button
                      size="small"
                      onClick={() => setManualLevelOverride(null)}
                      sx={{ textTransform: 'none', fontSize: 10, p: 0.5, minWidth: 0 }}
                    >
                      Сброс
                    </Button>
                  )}
                </Box>
              </Box>
            </Collapse>
          </Paper>

          <Alert severity="info" sx={{ fontSize: 12 }}>
            Приложение без проекта можно позже подключить к одному или нескольким проектам без копирования репозитория.
          </Alert>
        </Paper>

        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button onClick={onCancel} sx={{ textTransform: 'none' }}>Отмена</Button>
          <Button
            variant="contained"
            startIcon={submitting ? <CircularProgress size={16} /> : <Add />}
            onClick={handleCreate}
            disabled={submitting || !appId.trim() || !repoPath.trim()}
            sx={{ textTransform: 'none', fontWeight: 600 }}
          >
            {submitting ? 'Создание...' : 'Создать приложение'}
          </Button>
        </Box>
      </Box>
    </ErrorBoundary>
  );
}