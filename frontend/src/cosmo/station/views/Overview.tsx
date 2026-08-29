/**
 * COS-022 / COS-047: Control Station Overview View.
 *
 * Dashboard: Active Runs, Security Gates, Failed Deployments, and System Metrics.
 * Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, Chip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, Skeleton, Alert, IconButton, Tooltip, Dialog,
  DialogTitle, DialogContent, DialogActions, TextField, MenuItem,
} from '@mui/material';
import {
  PlayArrow, Gavel, Warning, Apps, Refresh, Stop,
  CheckCircle, HourglassEmpty, Block, ArrowForward,
} from '@mui/icons-material';
import { api, type Run, type Gate, type Application, type Domain } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';
import { ExecutivePostureWidget } from './ExecutivePostureWidget';
import { SlaRemediationWidget } from './SlaRemediationWidget';

interface OverviewProps {
  selectedDomain?: string;
  onNavigateToView?: (view: string, params?: Record<string, string>) => void;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function Overview({ selectedDomain = 'all', onNavigateToView, onNavigateToIDE }: OverviewProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [gates, setGates] = useState<Gate[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Quick run modal state
  const [openRunDialog, setOpenRunDialog] = useState(false);
  const [newRunId, setNewRunId] = useState('');
  const [newRunPlanId, setNewRunPlanId] = useState('');
  const [newRunDomainId, setNewRunDomainId] = useState('');
  const [submittingRun, setSubmittingRun] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [runsData, gatesData, appsData, domainsData] = await Promise.all([
        api.getRuns({ domainId: selectedDomain }),
        api.getGates(),
        api.getApps(selectedDomain),
        api.getDomains(),
      ]);
      setRuns(runsData || []);
      setGates(gatesData || []);
      setApps(appsData || []);
      setDomains(domainsData || []);
      if (domainsData.length > 0 && !newRunDomainId) {
        setNewRunDomainId(domainsData[0].id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки данных';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedDomain, newRunDomainId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const activeRuns = runs.filter((r) => r.status === 'running' || r.status === 'pending' || r.status === 'queued');
  const failedRuns = runs.filter((r) => r.status === 'failed');
  const pendingGates = gates.filter((g) => !g.decision || g.decision === 'manual_required');

  const handleCancelRun = async (runId: string) => {
    try {
      await api.cancelRun(runId);
      toast.info(`Прогон #${runId} успешно отменён`);
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка при отмене прогона';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleCreateRun = async () => {
    if (!newRunId.trim() || !newRunPlanId.trim() || !newRunDomainId.trim()) return;
    setSubmittingRun(true);
    try {
      await api.createRun({
        id: newRunId.trim(),
        plan_id: newRunPlanId.trim(),
        domain_id: newRunDomainId.trim(),
        trigger: 'manual',
      });
      toast.success(`Прогон #${newRunId.trim()} запущен`);
      setOpenRunDialog(false);
      setNewRunId('');
      setNewRunPlanId('');
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка запуска прогона';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmittingRun(false);
    }
  };

  const getStatusChip = (status: string) => {
    switch (status) {
      case 'running':
        return <Chip icon={<PlayArrow />} label="running" size="small" color="primary" sx={{ fontSize: 11 }} />;
      case 'succeeded':
      case 'passed':
        return <Chip icon={<CheckCircle />} label="succeeded" size="small" color="success" sx={{ fontSize: 11 }} />;
      case 'failed':
        return <Chip icon={<Warning />} label="failed" size="small" color="error" sx={{ fontSize: 11 }} />;
      case 'blocked':
        return <Chip icon={<Block />} label="blocked" size="small" color="warning" sx={{ fontSize: 11 }} />;
      case 'cancelled':
        return <Chip label="cancelled" size="small" sx={{ fontSize: 11, bgcolor: 'action.disabledBackground' }} />;
      default:
        return <Chip icon={<HourglassEmpty />} label={status} size="small" sx={{ fontSize: 11 }} />;
    }
  };

  return (
    <ErrorBoundary viewName="Обзор (Overview)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Top action header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Обзор системы (Control Station)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Сводка активности, статусы пайплайнов и контрольные точки Security Gates.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить данные">
              <IconButton onClick={fetchData} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="contained"
              size="small"
              startIcon={<PlayArrow />}
              onClick={() => setOpenRunDialog(true)}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Новый запуск
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* COS-100: Executive Security Posture Widget */}
        <ExecutivePostureWidget domain={selectedDomain} />

        {/* COS-107: SLA Remediation Widget */}
        <SlaRemediationWidget domain={selectedDomain} onNavigateToIDE={onNavigateToIDE} />

        {/* Metrics Row */}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Активные прогоны
                  </Typography>
                  <PlayArrow sx={{ color: 'primary.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Typography variant="h4" sx={{ fontWeight: 700, mt: 1 }}>
                    {activeRuns.length}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">
                  {loading ? <Skeleton width={120} /> : `${runs.length} всего запусков в истории`}
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Security Gates
                  </Typography>
                  <Gavel sx={{ color: pendingGates.length > 0 ? 'warning.main' : 'success.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Typography variant="h4" sx={{ fontWeight: 700, mt: 1, color: pendingGates.length > 0 ? 'warning.main' : 'text.primary' }}>
                    {pendingGates.length}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">
                  {loading ? <Skeleton width={120} /> : `${gates.length} контрольных точек настроено`}
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Ошибки и сбои
                  </Typography>
                  <Warning sx={{ color: 'error.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Typography variant="h4" sx={{ fontWeight: 700, mt: 1, color: failedRuns.length > 0 ? 'error.main' : 'text.primary' }}>
                    {failedRuns.length}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">
                  {loading ? <Skeleton width={140} /> : failedRuns.length === 0 ? 'Сбоев не обнаружено' : 'Требуют внимания инженеров'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Приложения и сервисы
                  </Typography>
                  <Apps sx={{ color: 'info.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Typography variant="h4" sx={{ fontWeight: 700, mt: 1 }}>
                    {apps.length}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">
                  {loading ? <Skeleton width={140} /> : `${domains.length} доменов / КИТС зарегистрировано`}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Main Tables Row */}
        <Grid container spacing={2}>
          {/* Recent Runs */}
          <Grid size={{ xs: 12, lg: 8 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  Последние запуски пайплайнов
                </Typography>
                {onNavigateToView && (
                  <Button
                    size="small"
                    endIcon={<ArrowForward />}
                    onClick={() => onNavigateToView('runs')}
                    sx={{ textTransform: 'none', fontSize: 12 }}
                  >
                    Все прогоны
                  </Button>
                )}
              </Box>
              <TableContainer component={Paper} elevation={0} sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead sx={{ bgcolor: 'action.hover' }}>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 600 }}>ID Прогона</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>План / Приложение</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Триггер</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Статус</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Батчи</TableCell>
                      <TableCell sx={{ fontWeight: 600 }} align="right">Действия</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      [1, 2, 3].map((i) => (
                        <TableRow key={i}>
                          <TableCell><Skeleton width={100} /></TableCell>
                          <TableCell><Skeleton width={120} /></TableCell>
                          <TableCell><Skeleton width={60} /></TableCell>
                          <TableCell><Skeleton width={80} /></TableCell>
                          <TableCell><Skeleton width={80} /></TableCell>
                          <TableCell align="right"><Skeleton width={30} sx={{ ml: 'auto' }} /></TableCell>
                        </TableRow>
                      ))
                    ) : runs.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} sx={{ p: 0 }}>
                          <EmptyState
                            icon={<PlayArrow sx={{ fontSize: 28 }} />}
                            title="Нет активных или завершенных прогонов"
                            description="Запустите первый пайплайн для анализа и проверки безопасности."
                            actionLabel="Запустить пайплайн"
                            onAction={() => setOpenRunDialog(true)}
                          />
                        </TableCell>
                      </TableRow>
                    ) : (
                      runs.slice(0, 6).map((r) => (
                        <TableRow key={r.id} hover>
                          <TableCell sx={{ fontWeight: 600, fontFamily: 'monospace', fontSize: 12 }}>
                            {r.id}
                          </TableCell>
                          <TableCell sx={{ fontSize: 12 }}>{r.plan_id}</TableCell>
                          <TableCell sx={{ fontSize: 12, color: 'text.secondary' }}>{r.trigger}</TableCell>
                          <TableCell>{getStatusChip(r.status)}</TableCell>
                          <TableCell sx={{ fontSize: 12 }}>
                            {r.batches.length > 0 ? (
                              <Box sx={{ display: 'flex', gap: 0.5 }}>
                                {r.batches.map((b) => (
                                  <span
                                    key={b.id}
                                    title={`${b.type}: ${b.status}`}
                                    style={{
                                      width: 8,
                                      height: 8,
                                      borderRadius: '50%',
                                      display: 'inline-block',
                                      backgroundColor:
                                        b.status === 'passed' ? '#10B981' : b.status === 'failed' ? '#EF4444' : b.status === 'running' ? '#3B82F6' : '#9CA3AF',
                                    }}
                                  />
                                ))}
                              </Box>
                            ) : (
                              '—'
                            )}
                          </TableCell>
                          <TableCell align="right">
                            {(r.status === 'running' || r.status === 'pending' || r.status === 'queued') && (
                              <IconButton
                                size="small"
                                color="error"
                                title="Отменить"
                                onClick={() => handleCancelRun(r.id)}
                              >
                                <Stop fontSize="small" />
                              </IconButton>
                            )}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Card>
          </Grid>

          {/* Security Gates Queue */}
          <Grid size={{ xs: 12, lg: 4 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  Security Gates Очередь
                </Typography>
                {onNavigateToView && (
                  <Button
                    size="small"
                    endIcon={<ArrowForward />}
                    onClick={() => onNavigateToView('gates')}
                    sx={{ textTransform: 'none', fontSize: 12 }}
                  >
                    Все гейты
                  </Button>
                )}
              </Box>
              <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                {loading ? (
                  [1, 2].map((i) => (
                    <Paper key={i} variant="outlined" sx={{ p: 1.5, borderRadius: 1.5 }}>
                      <Skeleton width="60%" height={20} />
                      <Skeleton width="40%" height={16} sx={{ mt: 0.5 }} />
                    </Paper>
                  ))
                ) : gates.length === 0 ? (
                  <EmptyState
                    icon={<Gavel sx={{ fontSize: 28 }} />}
                    title="Контрольные точки не найдены"
                    description="Создайте Security Gate для контроля качества релиза."
                  />
                ) : (
                  gates.slice(0, 4).map((g) => (
                    <Box
                      key={g.id}
                      sx={{
                        p: 1.5,
                        border: 1,
                        borderColor: g.decision === 'block' ? 'error.light' : g.decision === 'pass' ? 'success.light' : 'warning.light',
                        borderRadius: 1.5,
                        bgcolor: 'background.paper',
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                        <Typography variant="body2" sx={{ fontWeight: 700 }}>
                          {g.id}
                        </Typography>
                        <Chip
                          label={g.decision || (g.type === 'manual' ? 'manual required' : 'auto')}
                          size="small"
                          color={g.decision === 'pass' ? 'success' : g.decision === 'block' ? 'error' : 'warning'}
                          sx={{ fontSize: 10, height: 20 }}
                        />
                      </Box>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        Тип: {g.type} · Позиция #{g.position}
                      </Typography>
                      {g.policy.rules.length > 0 && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                          Правила: {g.policy.rules.map((r) => `${r.finding_type}→${r.action}`).join(', ')}
                        </Typography>
                      )}
                    </Box>
                  ))
                )}
              </Box>
            </Card>
          </Grid>
        </Grid>

        {/* Trigger Run Dialog */}
        <Dialog open={openRunDialog} onClose={() => setOpenRunDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Запуск нового пайплайна</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Прогона"
              placeholder="run-prod-001"
              value={newRunId}
              onChange={(e) => setNewRunId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="ID Плана пайплайна"
              placeholder="plan-main-app"
              value={newRunPlanId}
              onChange={(e) => setNewRunPlanId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Домен / КИТС"
              value={newRunDomainId}
              onChange={(e) => setNewRunDomainId(e.target.value)}
              fullWidth
              size="small"
            >
              {domains.map((d) => (
                <MenuItem key={d.id} value={d.id}>
                  {d.label} ({d.id})
                </MenuItem>
              ))}
            </TextField>
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenRunDialog(false)} disabled={submittingRun}>
              Отмена
            </Button>
            <Button
              onClick={handleCreateRun}
              variant="contained"
              disabled={submittingRun || !newRunId || !newRunPlanId}
              startIcon={<PlayArrow />}
            >
              Запустить
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
