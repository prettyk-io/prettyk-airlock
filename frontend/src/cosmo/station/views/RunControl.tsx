/**
 * COS-022 / COS-047 / COS-064: Control Station Run Control View.
 *
 * Execution tracking, live DAG/batch monitoring, status transitions, cancellation,
 * and COS-064 Bulk Actions (multi-select + floating action bar).
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Grid,
  Checkbox, Slide, Badge,
} from '@mui/material';
import {
  PlayArrow, Refresh, Stop, CheckCircle, Warning, Block,
  HourglassEmpty, OpenInNew, Cancel, Compare,
} from '@mui/icons-material';
import { api, type Run, type RunStatus, type Domain } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

interface RunControlProps {
  selectedDomain?: string;
  initialRunId?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
  onNavigateToView?: (view: string, params?: Record<string, string>) => void;
}

export function RunControl({
  selectedDomain = 'all',
  initialRunId,
  onNavigateToView,
}: RunControlProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // COS-064: Bulk selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkCancelling, setBulkCancelling] = useState(false);

  // New run dialog
  const [openRunDialog, setOpenRunDialog] = useState(false);
  const [runIdInput, setRunIdInput] = useState('');
  const [planIdInput, setPlanIdInput] = useState('');
  const [domainIdInput, setDomainIdInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [runsData, domainsData] = await Promise.all([
        api.getRuns({
          domainId: selectedDomain,
          status: statusFilter !== 'all' ? statusFilter : undefined,
        }),
        api.getDomains(),
      ]);
      setRuns(runsData || []);
      setDomains(domainsData || []);
      if (domainsData.length > 0 && !domainIdInput) {
        setDomainIdInput(domainsData[0].id);
      }
      if (initialRunId) {
        const found = runsData.find((r) => r.id === initialRunId);
        if (found) setSelectedRun(found);
      }
      // Clear selections on reload
      setSelectedIds(new Set());
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки прогонов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedDomain, statusFilter, initialRunId, domainIdInput]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // COS-064: Toggle individual row checkbox
  const handleToggleSelect = (runId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  // COS-064: Toggle all selectable rows (active runs only)
  const handleToggleAll = () => {
    const activeIds = runs.filter((r) => r.status === 'running' || r.status === 'pending' || r.status === 'queued').map((r) => r.id);
    const allSelected = activeIds.every((id) => selectedIds.has(id));
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(activeIds));
    }
  };

  // COS-064: Bulk cancel
  const handleBulkCancel = async () => {
    if (selectedIds.size === 0) return;
    setBulkCancelling(true);
    const ids = Array.from(selectedIds);
    let succeeded = 0;
    let failed = 0;

    for (const id of ids) {
      try {
        await api.cancelRun(id);
        succeeded++;
      } catch {
        failed++;
      }
    }

    if (succeeded > 0) {
      toast.success(`Отменено прогонов: ${succeeded} из ${ids.length}`);
    }
    if (failed > 0) {
      toast.error(`Не удалось отменить ${failed} прогонов из ${ids.length}`);
    }

    setBulkCancelling(false);
    setSelectedIds(new Set());
    await fetchRuns();
  };

  const handleCreateRun = async () => {
    if (!runIdInput.trim() || !planIdInput.trim() || !domainIdInput.trim()) return;
    setSubmitting(true);
    try {
      const created = await api.createRun({
        id: runIdInput.trim(),
        plan_id: planIdInput.trim(),
        domain_id: domainIdInput.trim(),
        trigger: 'manual',
      });
      toast.success(`Прогон #${runIdInput.trim()} запущен`);
      setOpenRunDialog(false);
      setRunIdInput('');
      setPlanIdInput('');
      setSelectedRun(created);
      await fetchRuns();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка запуска';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancelRun = async (id: string) => {
    try {
      const updated = await api.cancelRun(id);
      toast.info(`Прогон #${id} отменён`);
      if (selectedRun?.id === id) setSelectedRun(updated);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      await fetchRuns();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка отмены прогона';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleUpdateStatus = async (id: string, newStatus: RunStatus) => {
    try {
      const updated = await api.updateRunStatus(id, newStatus);
      toast.success(`Статус прогона #${id} изменен на ${newStatus}`);
      if (selectedRun?.id === id) setSelectedRun(updated);
      await fetchRuns();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка обновления статуса';
      setError(msg);
      toast.error(msg);
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

  const isSelectionActive = selectedIds.size > 0;
  const activeRunsCount = runs.filter((r) => r.status === 'running' || r.status === 'pending' || r.status === 'queued').length;
  const allActiveSelected = activeRunsCount > 0 && activeRunsCount === selectedIds.size;

  return (
    <ErrorBoundary viewName="Управление прогонами (Run Control)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Run Control Plane (Прогоны)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Управление запусками, отслеживание стадий выполнения батчей и валидация результатов.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchRuns} disabled={loading} size="small">
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
              Новый прогон
            </Button>
            {onNavigateToView && (
              <Button
                variant="outlined"
                size="small"
                startIcon={<Compare />}
                onClick={() => onNavigateToView('compare')}
                sx={{ textTransform: 'none', fontWeight: 600 }}
              >
                Сравнить прогоны
              </Button>
            )}
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Filter Bar */}
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
            Фильтр по статусу:
          </Typography>
          {['all', 'running', 'pending', 'succeeded', 'failed', 'blocked', 'cancelled'].map((st) => (
            <Chip
              key={st}
              label={st}
              size="small"
              clickable
              color={statusFilter === st ? 'primary' : 'default'}
              variant={statusFilter === st ? 'filled' : 'outlined'}
              onClick={() => setStatusFilter(st)}
              sx={{ fontSize: 11, textTransform: 'capitalize' }}
            />
          ))}
        </Box>

        <Grid container spacing={2}>
          {/* Runs List Table */}
          <Grid size={{ xs: 12, lg: selectedRun ? 7 : 12 }}>
            <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, overflowX: 'auto' }}>
              <Table size="small">
                <TableHead sx={{ bgcolor: 'action.hover' }}>
                  <TableRow>
                    <TableCell sx={{ width: 48, px: 1 }}>
                      {activeRunsCount > 0 && (
                        <Checkbox
                          size="small"
                          checked={allActiveSelected}
                          indeterminate={selectedIds.size > 0 && !allActiveSelected}
                          onChange={handleToggleAll}
                          title="Выбрать все активные прогоны"
                        />
                      )}
                    </TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>ID Прогона</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>План</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Домен</TableCell>
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
                        <TableCell sx={{ px: 1 }}><Skeleton variant="circular" width={20} height={20} /></TableCell>
                        <TableCell><Skeleton width={90} /></TableCell>
                        <TableCell><Skeleton width={110} /></TableCell>
                        <TableCell><Skeleton width={60} /></TableCell>
                        <TableCell><Skeleton width={70} /></TableCell>
                        <TableCell><Skeleton width={75} /></TableCell>
                        <TableCell><Skeleton width={70} /></TableCell>
                        <TableCell align="right"><Skeleton width={30} sx={{ ml: 'auto' }} /></TableCell>
                      </TableRow>
                    ))
                  ) : runs.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} sx={{ p: 0 }}>
                        <EmptyState
                          icon={<PlayArrow sx={{ fontSize: 28 }} />}
                          title="Прогоны не найдены"
                          description="Запустите пайплайн вручную или измените фильтр по статусу."
                          actionLabel="Новый прогон"
                          onAction={() => setOpenRunDialog(true)}
                        />
                      </TableCell>
                    </TableRow>
                  ) : (
                    runs.map((r) => {
                      const isCancelable = r.status === 'running' || r.status === 'pending' || r.status === 'queued';
                      return (
                        <TableRow
                          key={r.id}
                          hover
                          selected={selectedRun?.id === r.id}
                          onClick={() => setSelectedRun(r)}
                          sx={{ cursor: 'pointer' }}
                        >
                          <TableCell sx={{ px: 1 }} onClick={(e) => e.stopPropagation()}>
                            {isCancelable && (
                              <Checkbox
                                size="small"
                                checked={selectedIds.has(r.id)}
                                onChange={() => handleToggleSelect(r.id)}
                              />
                            )}
                          </TableCell>
                          <TableCell sx={{ fontWeight: 700, fontFamily: 'monospace', fontSize: 12 }}>
                            {r.id}
                          </TableCell>
                          <TableCell sx={{ fontSize: 12 }}>{r.plan_id}</TableCell>
                          <TableCell sx={{ fontSize: 12 }}>{r.domain_id}</TableCell>
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
                                        b.status === 'passed'
                                          ? '#10B981'
                                          : b.status === 'failed'
                                          ? '#EF4444'
                                          : b.status === 'running'
                                          ? '#3B82F6'
                                          : '#9CA3AF',
                                    }}
                                  />
                                ))}
                              </Box>
                            ) : (
                              '—'
                            )}
                          </TableCell>
                          <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                            {isCancelable && (
                              <IconButton
                                size="small"
                                color="error"
                                title="Отменить прогон"
                                onClick={() => handleCancelRun(r.id)}
                              >
                                <Stop fontSize="small" />
                              </IconButton>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>

          {/* Selected Run Details Panel */}
          {selectedRun && (
            <Grid size={{ xs: 12, lg: 5 }}>
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                      {selectedRun.id}
                    </Typography>
                    {getStatusChip(selectedRun.status)}
                  </Box>

                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 13, mb: 2 }}>
                    <div>
                      <strong>План:</strong> <span style={{ fontFamily: 'monospace' }}>{selectedRun.plan_id}</span>
                    </div>
                    <div>
                      <strong>Домен:</strong> {selectedRun.domain_id}
                    </div>
                    <div>
                      <strong>Инициатор:</strong> {selectedRun.initiator} ({selectedRun.trigger})
                    </div>
                    <div>
                      <strong>Создан:</strong> {new Date(selectedRun.created_at).toLocaleString()}
                    </div>
                    {selectedRun.started_at && (
                      <div>
                        <strong>Старт:</strong> {new Date(selectedRun.started_at).toLocaleString()}
                      </div>
                    )}
                    {selectedRun.finished_at && (
                      <div>
                        <strong>Завершён:</strong> {new Date(selectedRun.finished_at).toLocaleString()}
                      </div>
                    )}
                  </Box>

                  {/* Batches Progress */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Этапы выполнения (Batches)
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2 }}>
                    {selectedRun.batches.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">
                        Батчи не сгенерированы
                      </Typography>
                    ) : (
                      selectedRun.batches.map((b) => (
                        <Box
                          key={b.id}
                          sx={{
                            p: 1.5,
                            border: 1,
                            borderColor: 'divider',
                            borderRadius: 1.5,
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                          }}
                        >
                          <Box>
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                              {b.type}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              Кирпичи: {b.bricks.join(', ') || 'нет'}
                            </Typography>
                          </Box>
                          <Chip
                            label={b.status}
                            size="small"
                            color={b.status === 'passed' ? 'success' : b.status === 'failed' ? 'error' : b.status === 'running' ? 'primary' : 'default'}
                            sx={{ fontSize: 10, height: 20 }}
                          />
                        </Box>
                      ))
                    )}
                  </Box>

                  {/* Action buttons */}
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', pt: 1, borderTop: 1, borderColor: 'divider' }}>
                    {selectedRun.status === 'running' && (
                      <>
                        <Button
                          size="small"
                          color="success"
                          variant="outlined"
                          onClick={() => handleUpdateStatus(selectedRun.id, 'succeeded')}
                          sx={{ textTransform: 'none', fontSize: 11 }}
                        >
                          Отметить успехом
                        </Button>
                        <Button
                          size="small"
                          color="error"
                          variant="outlined"
                          onClick={() => handleCancelRun(selectedRun.id)}
                          sx={{ textTransform: 'none', fontSize: 11 }}
                        >
                          Отменить
                        </Button>
                      </>
                    )}
                    {onNavigateToView && (
                      <Button
                        size="small"
                        startIcon={<OpenInNew />}
                        onClick={() => onNavigateToView('audit', { run_id: selectedRun.id })}
                        sx={{ textTransform: 'none', fontSize: 11 }}
                      >
                        Журнал доказательств
                      </Button>
                    )}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>

        {/* Trigger Run Dialog */}
        <Dialog open={openRunDialog} onClose={() => setOpenRunDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Запуск нового пайплайна</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Прогона"
              placeholder="run-prod-001"
              value={runIdInput}
              onChange={(e) => setRunIdInput(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="ID Плана пайплайна"
              placeholder="plan-steel"
              value={planIdInput}
              onChange={(e) => setPlanIdInput(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Домен / КИТС"
              value={domainIdInput}
              onChange={(e) => setDomainIdInput(e.target.value)}
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
            <Button onClick={() => setOpenRunDialog(false)} disabled={submitting}>
              Отмена
            </Button>
            <Button
              onClick={handleCreateRun}
              variant="contained"
              disabled={submitting || !runIdInput || !planIdInput}
              startIcon={<PlayArrow />}
            >
              Запустить
            </Button>
          </DialogActions>
        </Dialog>

        {/* COS-064: Floating Bulk Action Bar */}
        <Slide direction="up" in={isSelectionActive} mountOnEnter unmountOnExit>
          <Paper
            elevation={6}
            sx={{
              position: 'fixed',
              bottom: 24,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 1200,
              px: 3,
              py: 1.5,
              borderRadius: 3,
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              bgcolor: 'error.dark',
              color: 'white',
              boxShadow: '0 8px 32px rgba(239,68,68,0.35)',
            }}
          >
            <Badge badgeContent={selectedIds.size} color="warning" sx={{ '& .MuiBadge-badge': { fontWeight: 700 } }}>
              <Cancel sx={{ fontSize: 22 }} />
            </Badge>
            <Typography variant="body2" sx={{ fontWeight: 700, fontSize: 13 }}>
              Выбрано прогонов: <strong>{selectedIds.size}</strong>
            </Typography>
            <Button
              variant="contained"
              color="error"
              size="small"
              onClick={handleBulkCancel}
              disabled={bulkCancelling}
              startIcon={bulkCancelling ? <HourglassEmpty /> : <Stop />}
              sx={{
                textTransform: 'none',
                fontWeight: 700,
                bgcolor: 'white',
                color: 'error.main',
                '&:hover': { bgcolor: 'grey.200' },
              }}
            >
              {bulkCancelling ? 'Отмена...' : `Отменить выбранные (${selectedIds.size})`}
            </Button>
            <IconButton
              size="small"
              onClick={() => setSelectedIds(new Set())}
              sx={{ color: 'rgba(255,255,255,0.7)', '&:hover': { color: 'white' } }}
            >
              <span style={{ fontSize: 18 }}>×</span>
            </IconButton>
          </Paper>
        </Slide>
      </Box>
    </ErrorBoundary>
  );
}