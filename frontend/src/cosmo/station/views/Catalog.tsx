/**
 * COS-022 / COS-047: Control Station Brick Catalog View.
 *
 * Catalog of reusable CI/CD & Security Bricks (SAST, SCA, Build, Deploy, DAST, Autotest, Gate).
 * Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Grid,
} from '@mui/material';
import {
  Refresh, Add, Delete,
  Build, BugReport, Security, CloudUpload, PlayCircle,
} from '@mui/icons-material';
import { api, type PipelineBrick, type BrickType } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

const BRICK_TYPES: BrickType[] = ['build', 'sast', 'sca', 'deploy', 'dast', 'autotest', 'gate'];

export function Catalog() {
  const [bricks, setBricks] = useState<PipelineBrick[]>([]);
  const [selectedType, setSelectedType] = useState<BrickType | 'all'>('all');
  const [selectedBrick, setSelectedBrick] = useState<PipelineBrick | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create Modal
  const [openCreateDialog, setOpenCreateDialog] = useState(false);
  const [brickId, setBrickId] = useState('');
  const [brickName, setBrickName] = useState('');
  const [brickType, setBrickType] = useState<BrickType>('sast');
  const [brickSource, setBrickSource] = useState('internal');
  const [brickImage, setBrickImage] = useState('sonarsource/sonar-scanner-cli:latest');
  const [brickTimeout, setBrickTimeout] = useState(1200);
  const [dependsOnStr, setDependsOnStr] = useState('');

  const fetchBricks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getBricks(selectedType === 'all' ? undefined : selectedType);
      setBricks(data || []);
      if (data && data.length > 0 && !selectedBrick) {
        setSelectedBrick(data[0]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки кирпичей каталога';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedType, selectedBrick]);

  useEffect(() => {
    fetchBricks();
  }, [fetchBricks]);

  const handleCreateBrick = async () => {
    if (!brickId.trim() || !brickName.trim() || !brickImage.trim()) return;
    try {
      const deps = dependsOnStr
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      await api.createBrick({
        id: brickId.trim(),
        name: brickName.trim(),
        type: brickType,
        source: brickSource.trim(),
        definition: {
          executor: 'woodpecker',
          image: brickImage.trim(),
          timeout_s: brickTimeout,
          inputs: {},
          outputs: {},
        },
        depends_on: deps,
        gates: [],
      });
      toast.success(`Кирпич ${brickName.trim()} добавлен в каталог`);
      setOpenCreateDialog(false);
      setBrickId('');
      setBrickName('');
      await fetchBricks();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка создания кирпича';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleDeleteBrick = async (id: string) => {
    if (!window.confirm(`Удалить кирпич ${id}?`)) return;
    try {
      await api.deleteBrick(id);
      toast.info(`Кирпич ${id} удален`);
      if (selectedBrick?.id === id) setSelectedBrick(null);
      await fetchBricks();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления';
      setError(msg);
      toast.error(msg);
    }
  };

  const getBrickIcon = (type: BrickType) => {
    switch (type) {
      case 'build':
        return <Build sx={{ fontSize: 18, color: 'primary.main' }} />;
      case 'sast':
      case 'sca':
        return <Security sx={{ fontSize: 18, color: 'warning.main' }} />;
      case 'dast':
        return <BugReport sx={{ fontSize: 18, color: 'error.main' }} />;
      case 'deploy':
        return <CloudUpload sx={{ fontSize: 18, color: 'info.main' }} />;
      default:
        return <PlayCircle sx={{ fontSize: 18, color: 'success.main' }} />;
    }
  };

  return (
    <ErrorBoundary viewName="Каталог кирпичей (Catalog)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Каталог кирпичей (Pipeline Bricks)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Библиотека атомарных переиспользуемых шагов пайплайна: сборка, SAST, SCA, DAST, тесты, деплой.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchBricks} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="contained"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenCreateDialog(true)}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Добавить Brick
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Filter Tabs / Chips */}
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
            Тип шага:
          </Typography>
          <Chip
            label="Все кирпичи"
            size="small"
            clickable
            color={selectedType === 'all' ? 'primary' : 'default'}
            variant={selectedType === 'all' ? 'filled' : 'outlined'}
            onClick={() => setSelectedType('all')}
            sx={{ fontWeight: 600 }}
          />
          {BRICK_TYPES.map((t) => (
            <Chip
              key={t}
              label={t.toUpperCase()}
              size="small"
              clickable
              color={selectedType === t ? 'primary' : 'default'}
              variant={selectedType === t ? 'filled' : 'outlined'}
              onClick={() => setSelectedType(t)}
              sx={{ fontWeight: 600, fontSize: 11 }}
            />
          ))}
        </Box>

        <Grid container spacing={2}>
          {/* Bricks Grid */}
          <Grid size={{ xs: 12, md: 7 }}>
            <Grid container spacing={1.5}>
              {loading ? (
                [1, 2, 3, 4].map((i) => (
                  <Grid size={{ xs: 12, sm: 6 }} key={i}>
                    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                      <Skeleton width="60%" height={20} />
                      <Skeleton width="40%" height={16} sx={{ mt: 0.5 }} />
                    </Paper>
                  </Grid>
                ))
              ) : bricks.length === 0 ? (
                <Grid size={{ xs: 12 }}>
                  <EmptyState
                    icon={<Security sx={{ fontSize: 28 }} />}
                    title="Кирпичи выбранного типа не найдены"
                    description="Зарегистрируйте новый шаг пайплайна в каталоге."
                    actionLabel="Добавить Brick"
                    onAction={() => setOpenCreateDialog(true)}
                  />
                </Grid>
              ) : (
                bricks.map((b) => {
                  const isSelected = selectedBrick?.id === b.id;
                  return (
                    <Grid size={{ xs: 12, sm: 6 }} key={b.id}>
                      <Card
                        variant="outlined"
                        onClick={() => setSelectedBrick(b)}
                        sx={{
                          cursor: 'pointer',
                          borderRadius: 2,
                          borderColor: isSelected ? 'primary.main' : 'divider',
                          bgcolor: isSelected ? 'action.selected' : 'background.paper',
                          height: '100%',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                        }}
                      >
                        <CardContent sx={{ p: 2 }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              {getBrickIcon(b.type)}
                              <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                                {b.name}
                              </Typography>
                            </Box>
                            <Chip label={b.type} size="small" variant="outlined" sx={{ fontSize: 10, height: 18 }} />
                          </Box>
                          <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block' }}>
                            ID: {b.id}
                          </Typography>
                          <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
                            Образ: {b.definition.image}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  );
                })
              )}
            </Grid>
          </Grid>

          {/* Selected Brick Details */}
          <Grid size={{ xs: 12, md: 5 }}>
            {selectedBrick ? (
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {getBrickIcon(selectedBrick.type)}
                      <Typography variant="h6" sx={{ fontWeight: 700 }}>
                        {selectedBrick.name}
                      </Typography>
                    </Box>
                    <IconButton size="small" color="error" onClick={() => handleDeleteBrick(selectedBrick.id)}>
                      <Delete fontSize="small" />
                    </IconButton>
                  </Box>

                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, fontSize: 13, mb: 3 }}>
                    <div>
                      <strong>ID:</strong> <span style={{ fontFamily: 'monospace' }}>{selectedBrick.id}</span>
                    </div>
                    <div>
                      <strong>Тип:</strong> <Chip label={selectedBrick.type} size="small" color="primary" sx={{ ml: 1, fontSize: 11 }} />
                    </div>
                    <div>
                      <strong>Источник:</strong> {selectedBrick.source}
                    </div>
                    <div>
                      <strong>Docker образ:</strong>
                      <div style={{ padding: '4px 8px', borderRadius: 4, background: 'rgba(0,0,0,0.04)', fontFamily: 'monospace', marginTop: 4 }}>
                        {selectedBrick.definition.image}
                      </div>
                    </div>
                    <div>
                      <strong>Таймаут:</strong> {selectedBrick.definition.timeout_s} сек. ({Math.round(selectedBrick.definition.timeout_s / 60)} мин.)
                    </div>
                    <div>
                      <strong>Зависимости (depends_on):</strong>
                      {selectedBrick.depends_on.length > 0 ? (
                        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                          {selectedBrick.depends_on.map((d) => (
                            <Chip key={d} label={d} size="small" variant="outlined" sx={{ fontSize: 10, fontFamily: 'monospace' }} />
                          ))}
                        </Box>
                      ) : (
                        ' Нет (первый в цепочке)'
                      )}
                    </div>
                  </Box>
                </CardContent>
              </Card>
            ) : (
              <EmptyState
                icon={<Security sx={{ fontSize: 32 }} />}
                title="Кирпич не выбран"
                description="Выберите Pipeline Brick из каталога слева для просмотра параметров."
              />
            )}
          </Grid>
        </Grid>

        {/* Create Brick Dialog */}
        <Dialog open={openCreateDialog} onClose={() => setOpenCreateDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Зарегистрировать Pipeline Brick</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Кирпича"
              placeholder="brick-sast-sonar"
              value={brickId}
              onChange={(e) => setBrickId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Название шага"
              placeholder="SonarQube SAST Scanner"
              value={brickName}
              onChange={(e) => setBrickName(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Тип шага"
              value={brickType}
              onChange={(e) => setBrickType(e.target.value as BrickType)}
              fullWidth
              size="small"
            >
              {BRICK_TYPES.map((t) => (
                <MenuItem key={t} value={t}>
                  {t.toUpperCase()}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Docker Образ"
              value={brickImage}
              onChange={(e) => setBrickImage(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Таймаут (сек)"
              type="number"
              value={brickTimeout}
              onChange={(e) => setBrickTimeout(Number(e.target.value))}
              fullWidth
              size="small"
            />
            <TextField
              label="Зависимости (ID через запятую)"
              placeholder="brick-build, brick-dep"
              value={dependsOnStr}
              onChange={(e) => setDependsOnStr(e.target.value)}
              fullWidth
              size="small"
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCreateDialog(false)}>Отмена</Button>
            <Button onClick={handleCreateBrick} variant="contained" disabled={!brickId || !brickName || !brickImage}>
              Создать
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
