/**
 * COS-022 / COS-047: Control Station Pipeline Studio View.
 *
 * Visual DAG builder, Plan Compiler, deterministic compilation hash, and execution stages.
 * Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Grid,
} from '@mui/material';
import {
  AccountTree, Refresh, Add, Delete, PlayArrow,
  ArrowForward, Fingerprint, OpenInNew,
} from '@mui/icons-material';
import {
  api, type PipelinePlan, type PipelineBrick, type Application,
} from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

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

  // Compile Plan Modal
  const [openCompileModal, setOpenCompileModal] = useState(false);
  const [compilePlanId, setCompilePlanId] = useState('');
  const [compileAppId, setCompileAppId] = useState(selectedAppId || '');
  const [selectedBrickIds, setSelectedBrickIds] = useState<string[]>([]);
  const [compiling, setCompiling] = useState(false);

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
                      {onNavigateToView && (
                        <Button
                          size="small"
                          variant="contained"
                          startIcon={<PlayArrow />}
                          onClick={() => onNavigateToView('runs')}
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

                  {/* Hash pill */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1.5, bgcolor: 'action.hover', borderRadius: 1.5, mb: 3 }}>
                    <Fingerprint sx={{ fontSize: 18, color: 'success.main' }} />
                    <Typography variant="caption" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                      <strong>Compiled Hash:</strong> {selectedPlan.compiled_hash}
                    </Typography>
                  </Box>

                  {/* Visual DAG Steps Flow */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 2 }}>
                    Граф выполнения шагов (DAG Workflow)
                  </Typography>
                  <Box
                    sx={{
                      p: 3,
                      borderRadius: 2,
                      bgcolor: 'background.default',
                      border: 1,
                      borderColor: 'divider',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 2,
                      overflowX: 'auto',
                      minHeight: 140,
                    }}
                  >
                    {selectedPlan.brick_ids.map((bid, idx) => {
                      const brickObj = bricks.find((b) => b.id === bid);
                      const bType = brickObj?.type || 'step';
                      const color = getBrickTypeColor(bType);

                      return (
                        <Box key={bid} sx={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
                          <Paper
                            variant="outlined"
                            sx={{
                              p: 2,
                              borderRadius: 2,
                              minWidth: 160,
                              borderTop: `4px solid ${color}`,
                              bgcolor: 'background.paper',
                            }}
                          >
                            <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 700, textTransform: 'uppercase' }}>
                              {bType}
                            </Typography>
                            <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 0.5 }}>
                              {brickObj?.name || bid}
                            </Typography>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', mt: 0.5 }}>
                              {bid}
                            </Typography>
                          </Paper>
                          {idx < selectedPlan.brick_ids.length - 1 && (
                            <ArrowForward sx={{ color: 'text.disabled', fontSize: 20 }} />
                          )}
                        </Box>
                      );
                    })}
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
