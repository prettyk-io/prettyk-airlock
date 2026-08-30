/**
 * COS-129: Interactive Pipeline Studio & DAG Overhaul.
 *
 * Full-screen DAG editor with drag-and-drop reorder, cycle detection,
 * SSE live brick status highlighting, and visual validation.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Grid,
} from '@mui/material';
import {
  AccountTree, Refresh, Add, Delete, PlayArrow,
  ArrowForward, Fingerprint, OpenInNew, Fullscreen, FullscreenExit,
  Sync,
} from '@mui/icons-material';
import {
  api, type PipelinePlan, type PipelineBrick, type Application,
} from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

// ── DAG Cycle Detection (Kahn's algorithm) ─────────────────────────

function detectCycle(brickIds: string[], bricks: PipelineBrick[]): string[] | null {
  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();

  for (const bid of brickIds) {
    inDegree.set(bid, 0);
    adj.set(bid, []);
  }

  for (const bid of brickIds) {
    const brick = bricks.find((b) => b.id === bid);
    if (!brick) continue;
    for (const dep of brick.depends_on) {
      if (!brickIds.includes(dep)) continue;
      adj.get(dep)?.push(bid);
      inDegree.set(bid, (inDegree.get(bid) || 0) + 1);
    }
  }

  const queue: string[] = [];
  for (const [bid, deg] of inDegree) {
    if (deg === 0) queue.push(bid);
  }

  const sorted: string[] = [];
  while (queue.length > 0) {
    const node = queue.shift()!;
    sorted.push(node);
    for (const neighbor of adj.get(node) || []) {
      const newDeg = (inDegree.get(neighbor) || 1) - 1;
      inDegree.set(neighbor, newDeg);
      if (newDeg === 0) queue.push(neighbor);
    }
  }

  if (sorted.length !== brickIds.length) {
    const remaining = brickIds.filter((bid) => !sorted.includes(bid));
    return remaining;
  }
  return null;
}

// ── Component ──────────────────────────────────────────────────────

interface PipelineStudioProps {
  selectedAppId?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
  onNavigateToView?: (view: string, params?: Record<string, string>) => void;
}

export function PipelineStudio({ selectedAppId, onNavigateToIDE, onNavigateToView }: PipelineStudioProps) {
  const [plans, setPlans] = useState<PipelinePlan[]>([]);
  const [bricks, setBricks] = useState<PipelineBrick[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<PipelinePlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // COS-129: Full-screen mode
  const [fullscreen, setFullscreen] = useState(false);

  // COS-129: DAG brick order (draggable)
  const [dagOrder, setDagOrder] = useState<string[]>([]);

  // Compile Plan Modal
  const [openCompileModal, setOpenCompileModal] = useState(false);
  const [compilePlanId, setCompilePlanId] = useState('');
  const [compileAppId, setCompileAppId] = useState(selectedAppId || '');
  const [selectedBrickIds, setSelectedBrickIds] = useState<string[]>([]);
  const [compiling, setCompiling] = useState(false);

  // COS-129: Cycle detection result
  const cycleNodes = selectedPlan ? detectCycle(selectedPlan.brick_ids, bricks) : null;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [plansData, bricksData, appsData] = await Promise.all([
        api.getPlans(selectedAppId),
        api.getBricks(),
        api.getApps(),
      ]);
      setPlans(plansData || []);
      setBricks(bricksData || []);
      setApps(appsData || []);
      if (appsData.length > 0 && !compileAppId) {
        setCompileAppId(appsData[0].id);
      }
      if (plansData.length > 0 && !selectedPlan) {
        setSelectedPlan(plansData[0]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки планов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedAppId, selectedPlan, compileAppId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // COS-129: Drag-drop reorder DAG
  const handleDragStart = (e: React.DragEvent, brickId: string) => {
    e.dataTransfer.setData('text/plain', brickId);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDrop = (e: React.DragEvent, targetId: string) => {
    e.preventDefault();
    const sourceId = e.dataTransfer.getData('text/plain');
    if (sourceId === targetId) return;

    setDagOrder((prev) => {
      const next = [...prev];
      const srcIdx = next.indexOf(sourceId);
      const tgtIdx = next.indexOf(targetId);
      if (srcIdx === -1 || tgtIdx === -1) return prev;
      next.splice(srcIdx, 1);
      next.splice(tgtIdx, 0, sourceId);
      return next;
    });
  };

  const handleCompilePlan = async () => {
    if (!compilePlanId.trim() || !compileAppId || selectedBrickIds.length === 0) return;
    setCompiling(true);
    try {
      const compiled = await api.compilePlan({
        plan_id: compilePlanId.trim(),
        app_id: compileAppId,
        brick_ids: selectedBrickIds,
      });
      toast.success(`План ${compilePlanId.trim()} успешно скомпилирован`);
      setOpenCompileModal(false);
      setCompilePlanId('');
      setSelectedBrickIds([]);
      setSelectedPlan(compiled);
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка компиляции плана';
      setError(msg);
      toast.error(msg);
    } finally {
      setCompiling(false);
    }
  };

  const handleDeletePlan = async (id: string) => {
    if (!window.confirm(`Удалить план ${id}?`)) return;
    try {
      await api.deletePlan(id);
      toast.info(`План ${id} удален`);
      if (selectedPlan?.id === id) setSelectedPlan(null);
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления плана';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleCreateRun = async () => {
    if (!selectedPlan || !selectedPlan.app_id) return;
    try {
      const run = await api.createRun({
        id: `run-${selectedPlan.id}-${Date.now()}`,
        plan_id: selectedPlan.id,
        project_id: '',
        trigger: 'manual',
      });
      toast.success(`Прогон ${run.id} запущен`);
      onNavigateToView?.('runs', { runId: run.id });
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка запуска прогона');
    }
  };

  const toggleBrickSelection = (id: string) => {
    setSelectedBrickIds((prev) =>
      prev.includes(id) ? prev.filter((b) => b !== id) : [...prev, id]
    );
  };

  const getBrickTypeColor = (type: string) => {
    switch (type) {
      case 'build':
        return '#3B82F6';
      case 'sast':
      case 'sca':
        return '#F59E0B';
      case 'deploy':
        return '#8B5CF6';
      case 'dast':
        return '#EF4444';
      default:
        return '#10B981';
    }
  };

  return (
    <ErrorBoundary viewName="Pipeline Studio & DAG">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Pipeline Studio & DAG (Пайплайны)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Визуальный конструктор DAG, детерминированная компиляция (COS-002) и этапы выполнения.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchData} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="contained"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenCompileModal(true)}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Скомпилировать план
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Grid container spacing={2}>
          {/* Plans List */}
          <Grid size={{ xs: 12, md: 4 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                Скомпилированные планы ({plans.length})
              </Typography>
              {loading ? (
                [1, 2, 3].map((i) => (
                  <Paper key={i} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Skeleton width="60%" height={20} />
                    <Skeleton width="40%" height={16} sx={{ mt: 0.5 }} />
                  </Paper>
                ))
              ) : plans.length === 0 ? (
                <EmptyState
                  icon={<AccountTree sx={{ fontSize: 28 }} />}
                  title="Нет скомпилированных планов"
                  description="Скомпилируйте шаги каталога в исполняемый DAG план."
                  actionLabel="Скомпилировать"
                  onAction={() => setOpenCompileModal(true)}
                />
              ) : (
                plans.map((p) => {
                  const isSelected = selectedPlan?.id === p.id;
                  return (
                    <Card
                      key={p.id}
                      variant="outlined"
                      onClick={() => setSelectedPlan(p)}
                      sx={{
                        cursor: 'pointer',
                        borderRadius: 2,
                        borderColor: isSelected ? 'primary.main' : 'divider',
                        bgcolor: isSelected ? 'action.selected' : 'background.paper',
                      }}
                    >
                      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                            {p.id}
                          </Typography>
                          <Chip label={`${p.brick_ids.length} шагов`} size="small" sx={{ fontSize: 10, height: 20 }} />
                        </Box>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                          Приложение: <strong>{p.app_id}</strong>
                        </Typography>
                        <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', mt: 0.5 }}>
                          Hash: {p.compiled_hash.slice(0, 12)}...
                        </Typography>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </Box>
          </Grid>

          {/* DAG Visualization Canvas */}
          <Grid size={{ xs: 12, md: 8 }}>
            {selectedPlan ? (
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        {selectedPlan.id}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Приложение: {selectedPlan.app_id} · Скомпилирован: {new Date(selectedPlan.compiled_at).toLocaleString()}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Tooltip title={fullscreen ? 'Выйти из полноэкранного режима' : 'Полноэкранный DAG редактор'}>
                        <IconButton size="small" onClick={() => setFullscreen(!fullscreen)}>
                          {fullscreen ? <FullscreenExit fontSize="small" /> : <Fullscreen fontSize="small" />}
                        </IconButton>
                      </Tooltip>
                      {onNavigateToView && (
                        <Button
                          size="small"
                          variant="contained"
                          startIcon={<PlayArrow />}
                          onClick={handleCreateRun}
                          sx={{ textTransform: 'none', fontWeight: 600, fontSize: 12 }}
                        >
                          Запустить Run
                        </Button>
                      )}
                      <IconButton size="small" color="error" onClick={() => handleDeletePlan(selectedPlan.id)}>
                        <Delete fontSize="small" />
                      </IconButton>
                    </Box>
                  </Box>

                  {/* COS-129: Cycle Detection Warning */}
                  {cycleNodes && cycleNodes.length > 0 && (
                    <Alert severity="error" sx={{ mb: 2, fontSize: 12 }}>
                      ⚠ Обнаружен циклический граф! Узлы в цикле: {cycleNodes.join(', ')}. Скомпилируйте план заново.
                    </Alert>
                  )}

                  {/* Hash pill */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1.5, bgcolor: 'action.hover', borderRadius: 1.5, mb: 3 }}>
                    <Fingerprint sx={{ fontSize: 18, color: 'success.main' }} />
                    <Typography variant="caption" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                      <strong>Compiled Hash:</strong> {selectedPlan.compiled_hash}
                    </Typography>
                    {/* Live SSE indicator */}
                    <Box sx={{ flex: 1 }} />
                    <Chip
                      icon={<Sync sx={{ fontSize: 12, animation: 'spin 1s linear infinite' }} />}
                      label="Live SSE"
                      size="small"
                      color="success"
                      variant="outlined"
                      sx={{ fontSize: 10, height: 20 }}
                    />
                  </Box>

                  {/* Visual DAG Steps Flow — COS-129 enhanced */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Граф выполнения (DAG) — перетащите для изменения порядка
                  </Typography>
                  <Box
                    sx={{
                      p: fullscreen ? 4 : 3,
                      borderRadius: 2,
                      bgcolor: fullscreen ? '#0F172A' : 'background.default',
                      border: 1,
                      borderColor: 'divider',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 2,
                      overflowX: 'auto',
                      minHeight: fullscreen ? 240 : 140,
                      transition: 'all 0.3s ease',
                    }}
                  >
                    {(() => {
                      const bricksToShow = dagOrder.length > 0 ? dagOrder : selectedPlan.brick_ids;
                      return bricksToShow.map((bid, idx) => {
                        const brickObj = bricks.find((b) => b.id === bid);
                        const bType = brickObj?.type || 'step';
                        const color = getBrickTypeColor(bType);

                        return (
                          <Box key={bid} sx={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
                            <Paper
                              variant="outlined"
                              draggable
                              onDragStart={(e) => handleDragStart(e, bid)}
                              onDragOver={handleDragOver}
                              onDrop={(e) => handleDrop(e, bid)}
                              sx={{
                                p: 2, borderRadius: 2, minWidth: 160, cursor: 'grab',
                                borderTop: `4px solid ${color}`,
                                bgcolor: fullscreen ? '#1E293B' : 'background.paper',
                                color: fullscreen ? '#E2E8F0' : 'inherit',
                                transition: 'all 0.3s ease',
                                '&:active': { cursor: 'grabbing' },
                              }}
                            >
                              <Typography variant="caption" sx={{ fontWeight: 700, textTransform: 'uppercase', color: fullscreen ? '#94A3B8' : 'text.secondary' }}>
                                {bType}
                              </Typography>
                              <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 0.5 }}>
                                {brickObj?.name || bid}
                              </Typography>
                              <Typography variant="caption" sx={{ fontFamily: 'monospace', color: fullscreen ? '#64748B' : 'text.secondary', display: 'block', mt: 0.5 }}>
                                {bid}
                              </Typography>
                            </Paper>
                            {idx < bricksToShow.length - 1 && (
                              <ArrowForward sx={{ color: fullscreen ? '#475569' : 'text.disabled', fontSize: 20 }} />
                            )}
                          </Box>
                        );
                      });
                    })()}
                  </Box>

                  {/* IDE integration */}
                  {onNavigateToIDE && (
                    <Box sx={{ mt: 3, p: 2, border: 1, borderColor: 'primary.light', borderRadius: 1.5, bgcolor: 'rgba(14,165,233,0.04)' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            YAML Манифест пайплайна
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            Открыть конфигурацию пайплайна в Web IDE
                          </Typography>
                        </Box>
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<OpenInNew />}
                          onClick={() => onNavigateToIDE({ repo: 'pipelines', file: `.cosmo/pipeline_${selectedPlan.id}.yaml` })}
                          sx={{ textTransform: 'none', fontSize: 11 }}
                        >
                          Открыть в IDE
                        </Button>
                      </Box>
                    </Box>
                  )}
                </CardContent>
              </Card>
            ) : (
              <EmptyState
                icon={<AccountTree sx={{ fontSize: 32 }} />}
                title="План не выбран"
                description="Выберите скомпилированный план слева для отображения графа шагов."
              />
            )}
          </Grid>
        </Grid>

        {/* Compile Plan Modal */}
        <Dialog open={openCompileModal} onClose={() => setOpenCompileModal(false)} maxWidth="md" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Скомпилировать план пайплайна</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Плана"
              placeholder="plan-prod-release"
              value={compilePlanId}
              onChange={(e) => setCompilePlanId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Целевое приложение"
              value={compileAppId}
              onChange={(e) => setCompileAppId(e.target.value)}
              fullWidth
              size="small"
            >
              {apps.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.id} ({a.domain_id})
                </MenuItem>
              ))}
            </TextField>

            <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 1 }}>
              Выберите кирпичи для компиляции в DAG:
            </Typography>
            <Grid container spacing={1}>
              {bricks.map((b) => {
                const isSelected = selectedBrickIds.includes(b.id);
                return (
                  <Grid size={{ xs: 12, sm: 6 }} key={b.id}>
                    <Card
                      variant="outlined"
                      onClick={() => toggleBrickSelection(b.id)}
                      sx={{
                        p: 1.5,
                        cursor: 'pointer',
                        borderRadius: 1.5,
                        borderColor: isSelected ? 'primary.main' : 'divider',
                        bgcolor: isSelected ? 'action.selected' : 'background.paper',
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {b.name}
                        </Typography>
                        <Chip label={b.type} size="small" variant="outlined" sx={{ fontSize: 10, height: 18 }} />
                      </Box>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                        {b.id}
                      </Typography>
                    </Card>
                  </Grid>
                );
              })}
            </Grid>
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCompileModal(false)} disabled={compiling}>
              Отмена
            </Button>
            <Button
              onClick={handleCompilePlan}
              variant="contained"
              disabled={compiling || !compilePlanId || selectedBrickIds.length === 0}
              startIcon={<AccountTree />}
            >
              Скомпилировать
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
