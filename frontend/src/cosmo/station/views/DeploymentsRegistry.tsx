/**
 * SAN-017: DeploymentsRegistry — Global Deployment History Table (Live API Wired).
 *
 * Fetches deployments from GET /api/v1/deployments. No mocks — honest EmptyState on empty/failure.
 */
import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, MenuItem, Select,
  IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, Alert, Skeleton,
} from '@mui/material';
import {
  CloudUpload, OpenInNew, Refresh, Science,
} from '@mui/icons-material';
import { api, type Deployment as DeploymentRecord } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

const zoneLabels: Record<string, { label: string; color: string }> = {
  zr:  { label: 'ЗР', color: '#3B82F6' },
  zt:  { label: 'ЗТ', color: '#F59E0B' },
  zpe: { label: 'ЗПЭ', color: '#10B981' },
};
const statusMeta: Record<string, { color: string; label: string }> = {
  success: { color: '#10B981', label: 'active' },
  failed:  { color: '#EF4444', label: 'failed' },
  running: { color: '#3B82F6', label: 'running' },
  pending: { color: '#9CA3AF', label: 'pending' },
  deleted: { color: '#F59E0B', label: 'deleted' },
  // COS-204: декларативный деплой (без материализации) — не «active».
  declarative: { color: '#64748B', label: 'declarative' },
};

interface DeploymentsRegistryProps {
}

export function DeploymentsRegistry({}: DeploymentsRegistryProps) {
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterApp, setFilterApp] = useState('all');
  const [filterZone, setFilterZone] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [search, setSearch] = useState('');

  // Rollback
  const [rollbackTarget, setRollbackTarget] = useState<DeploymentRecord | null>(null);
  const [rollbackConfirm, setRollbackConfirm] = useState('');
  const [rollbackDone, setRollbackDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const fetchDeployments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAllDeployments();
      setDeployments(data ?? []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки деплоев');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDeployments(); }, [fetchDeployments]);

  const filtered = useMemo(() => {
    let list = deployments;
    if (filterApp !== 'all') list = list.filter((d) => d.app_id === filterApp);
    if (filterZone !== 'all') list = list.filter((d) => d.target_zone === filterZone);
    if (filterStatus !== 'all') list = list.filter((d) => d.status === filterStatus);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((d) =>
        d.id.includes(q) ||
        (d.app_name ?? '').toLowerCase().includes(q) ||
        (d.custom_url ?? '').includes(q)
      );
    }
    return list;
  }, [deployments, filterApp, filterZone, filterStatus, search]);

  const handleOpenRollback = (dep: DeploymentRecord) => {
    setRollbackTarget(dep);
    setRollbackConfirm('');
    setRollbackDone(false);
  };

  const handleRollback = async () => {
    if (rollbackConfirm !== 'ROLLBACK' || !rollbackTarget) return;
    setSubmitting(true);
    try {
      await api.rollbackDeployment(rollbackTarget.id);
      setRollbackDone(true);
      toast.success(`Деплой ${rollbackTarget.id} откачен`);
      await fetchDeployments();
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка отката');
    } finally {
      setSubmitting(false);
    }
  };

  const apps = [...new Map(deployments.map((d) => [d.app_id, { id: d.app_id, name: d.app_name ?? d.app_id }] as const)).values()];

  return (
    <ErrorBoundary viewName="Deployments Registry">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              <CloudUpload sx={{ mr: 1, verticalAlign: 'middle', color: 'info.main' }} />
              Реестр развертываний (Deployments Registry)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {loading ? 'Загрузка...' : `Сводка деплоев по зонам безопасности · ${filtered.length} из ${deployments.length}`}
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить"><IconButton onClick={fetchDeployments} disabled={loading} size="small"><Refresh fontSize="small" /></IconButton></Tooltip>
            <Chip
              label={`ЗР: ${deployments.filter(d => d.target_zone === 'zr').length} · ЗТ: ${deployments.filter(d => d.target_zone === 'zt').length} · ЗПЭ: ${deployments.filter(d => d.target_zone === 'zpe').length}`}
              size="small" variant="outlined" sx={{ fontWeight: 600, fontSize: 11 }} />
          </Box>
        </Box>

        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        {/* Filters */}
        <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', gap: 1.5, flexWrap: 'wrap', borderRadius: 2 }}>
          <TextField size="small" placeholder="Поиск по ID, приложению, URL..." value={search}
            onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 240 }} />
          <Select size="small" value={filterApp} onChange={(e) => setFilterApp(e.target.value)}
            displayEmpty sx={{ minWidth: 160 }}>
            <MenuItem value="all">Все приложения</MenuItem>
            {apps.map((a) => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
          </Select>
          <Select size="small" value={filterZone} onChange={(e) => setFilterZone(e.target.value)}
            displayEmpty sx={{ minWidth: 120 }}>
            <MenuItem value="all">Все зоны</MenuItem>
            <MenuItem value="zr">ЗР — Разработка</MenuItem>
            <MenuItem value="zt">ЗТ — Тестирование</MenuItem>
            <MenuItem value="zpe">ЗПЭ — Пром</MenuItem>
          </Select>
          <Select size="small" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
            displayEmpty sx={{ minWidth: 140 }}>
            <MenuItem value="all">Все статусы</MenuItem>
            <MenuItem value="success">active</MenuItem>
            <MenuItem value="running">running</MenuItem>
            <MenuItem value="pending">pending</MenuItem>
            <MenuItem value="failed">failed</MenuItem>
            <MenuItem value="deleted">deleted</MenuItem>
          </Select>
        </Paper>

        {/* Table */}
        {loading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} variant="rectangular" height={36} sx={{ borderRadius: 1 }} />)}
          </Box>
        ) : filtered.length === 0 ? (
          <EmptyState icon={<CloudUpload sx={{ fontSize: 36 }} />} title="Деплои не найдены"
            description={deployments.length === 0 ? 'Развертываний ещё нет. Деплои появятся здесь после первого развертывания.' : 'Измените параметры фильтрации.'} />
        ) : (
          <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, maxHeight: 560, overflowY: 'auto' }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow sx={{ bgcolor: 'action.hover' }}>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>ID деплоя</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Приложение</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Сегмент</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Зона</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Runtime</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Статус</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>URL сервиса</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Сборка</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Оператор</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }} align="right">Действия</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((d) => {
                  const z = zoneLabels[d.target_zone] ?? { label: d.target_zone, color: '#64748B' };
                  const sMeta = statusMeta[d.status] ?? statusMeta.pending;
                  return (
                    <TableRow key={d.id} hover>
                      <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 11 }}>{d.id}</TableCell>
                      <TableCell sx={{ fontSize: 12, fontWeight: 600 }}>{d.app_name ?? d.app_id}</TableCell>
                      <TableCell><Chip label={d.segment === 'bare' ? 'Голый (bare)' : 'Интеграционный'} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} /></TableCell>
                      <TableCell>
                        <Chip label={z.label} size="small" sx={{ fontWeight: 700, fontSize: 9, bgcolor: z.color, color: '#fff' }} />
                      </TableCell>
                      <TableCell sx={{ fontSize: 11 }}>{d.runtime_name}</TableCell>
                      <TableCell>
                        <Chip label={sMeta.label} size="small" variant="outlined"
                          sx={{ fontSize: 9, height: 18, borderColor: sMeta.color, color: sMeta.color }} />
                      </TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>
                        {d.custom_url ? (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            {d.custom_url}
                            <Tooltip title={`Открыть: https://${d.custom_url}`}>
                              <IconButton size="small" sx={{ p: 0, color: 'primary.main' }}>
                                <OpenInNew sx={{ fontSize: 12 }} />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        ) : '—'}
                      </TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>{d.build_id}</TableCell>
                      <TableCell sx={{ fontSize: 11 }}>{d.operator || '—'}</TableCell>
                      <TableCell align="right">
                        <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end' }}>
                          <Tooltip title="Открыть в SecOps Lab (PrettyK DAST)">
                            <IconButton size="small" sx={{ color: 'warning.main' }}>
                              <Science sx={{ fontSize: 14 }} />
                            </IconButton>
                          </Tooltip>
                          {d.status === 'success' && (
                            <Button size="small" color="error" variant="outlined"
                              onClick={() => handleOpenRollback(d)}
                              sx={{ textTransform: 'none', fontSize: 10, minHeight: 24, py: 0 }}>
                              Откатить
                            </Button>
                          )}
                        </Box>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* Rollback Modal */}
        <Dialog open={!!rollbackTarget} onClose={() => setRollbackTarget(null)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>
            {rollbackDone ? '✅ Откат выполнен' : '⚠ Подтверждение отката деплоя'}
          </DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            {!rollbackDone ? (
              <>
                <Alert severity="error" sx={{ fontSize: 12 }}>
                  Вы собираетесь откатить деплой <strong>{rollbackTarget?.id}</strong> для{' '}
                  <strong>{rollbackTarget?.app_name ?? rollbackTarget?.app_id}</strong> в зоне{' '}
                  <strong>{zoneLabels[rollbackTarget?.target_zone ?? 'zr']?.label}</strong>.
                </Alert>
                <TextField size="small" label='Введите "ROLLBACK" для подтверждения'
                  value={rollbackConfirm} onChange={(e) => setRollbackConfirm(e.target.value)} fullWidth />
              </>
            ) : (
              <Alert severity="success" sx={{ fontSize: 12 }}>Деплой успешно откачен.</Alert>
            )}
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setRollbackTarget(null)}>{rollbackDone ? 'Закрыть' : 'Отмена'}</Button>
            {!rollbackDone && (
              <Button variant="contained" color="error" onClick={handleRollback}
                disabled={submitting || rollbackConfirm !== 'ROLLBACK'}
                sx={{ textTransform: 'none', fontWeight: 700 }}>
                {submitting ? 'Откат...' : 'Подтвердить откат'}
              </Button>
            )}
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}