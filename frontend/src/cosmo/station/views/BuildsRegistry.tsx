/**
 * SAN-017: BuildsRegistry — Global Build History Table (Live API Wired).
 * COS-198: детали сборки — честный статус, реальные логи (или честное
 * «недоступно»), digest-ссылка, evidence-след; прерывание активной сборки.
 *
 * Fetches builds from GET /api/v1/builds. No mocks — honest EmptyState on empty/failure.
 */
import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, MenuItem,
  IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, Select, Skeleton, Alert, Divider,
} from '@mui/material';
import {
  Build, Add, ContentCopy, Refresh,
  CheckCircle, Cancel, HourglassEmpty, Code,
} from '@mui/icons-material';
import { api, type Build as BuildRecord } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';

const statusMeta: Record<string, { color: string; label: string }> = {
  success: { color: '#10B981', label: 'success' },
  failed:  { color: '#EF4444', label: 'failed' },
  running: { color: '#3B82F6', label: 'running' },
  pending: { color: '#9CA3AF', label: 'pending' },
  aborted: { color: '#F59E0B', label: 'aborted' },
};

/** COS-198: честная строка метаданных (или undefined, если её нет). */
function metaString(build: BuildRecord | null, key: string): string | undefined {
  const value = build?.meta?.[key];
  return typeof value === 'string' && value ? value : undefined;
}

interface BuildsRegistryProps {
}

export function BuildsRegistry({}: BuildsRegistryProps) {
  const [builds, setBuilds] = useState<BuildRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterApp, setFilterApp] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterBranch, setFilterBranch] = useState('all');
  const [search, setSearch] = useState('');

  // Create modal
  const [openCreate, setOpenCreate] = useState(false);
  const [createApp, setCreateApp] = useState('');
  const [createBranch, setCreateBranch] = useState('main');
  const [createCommit, setCreateCommit] = useState('');
  const [createTitle, setCreateTitle] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // COS-198: детали сборки
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsBuild, setDetailsBuild] = useState<BuildRecord | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [aborting, setAborting] = useState(false);

  const fetchBuilds = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAllBuilds();
      setBuilds(data ?? []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки сборок');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchBuilds(); }, [fetchBuilds]);

  // COS-198: лёгкий поллинг — активные сборки должны честно доходить
  // до терминала без ручного Refresh.
  const hasActive = builds.some((b) => b.status === 'pending' || b.status === 'running');
  useEffect(() => {
    if (!hasActive) return;
    const t = setInterval(() => { void fetchBuilds(); }, 5000);
    return () => clearInterval(t);
  }, [hasActive, fetchBuilds]);

  const openDetails = useCallback(async (record: BuildRecord) => {
    setDetailsOpen(true);
    setDetailsBuild(record);
    setDetailsError(null);
    setDetailsLoading(true);
    try {
      const full = await api.getBuild(record.id);
      setDetailsBuild(full);
    } catch (err: unknown) {
      setDetailsError((err as Error)?.message || 'Ошибка загрузки деталей сборки');
    } finally {
      setDetailsLoading(false);
    }
  }, []);

  const handleAbort = useCallback(async () => {
    if (!detailsBuild) return;
    setAborting(true);
    try {
      const aborted = await api.abortBuild(detailsBuild.id);
      setDetailsBuild(aborted);
      await fetchBuilds();
    } catch (err: unknown) {
      setDetailsError((err as Error)?.message || 'Ошибка прерывания сборки');
    } finally {
      setAborting(false);
    }
  }, [detailsBuild, fetchBuilds]);

  const filtered = useMemo(() => {
    let list = builds;
    if (filterApp !== 'all') list = list.filter((b) => b.app_id === filterApp);
    if (filterStatus !== 'all') list = list.filter((b) => b.status === filterStatus);
    if (filterBranch !== 'all') list = list.filter((b) => b.branch === filterBranch);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((b) =>
        b.id.includes(q) ||
        (b.app_name ?? '').toLowerCase().includes(q) ||
        b.commit_sha.includes(q) ||
        (b.title ?? '').toLowerCase().includes(q)
      );
    }
    return list;
  }, [builds, filterApp, filterStatus, filterBranch, search]);

  const handleCreate = async () => {
    if (!createApp || !createCommit.trim() || !createBranch.trim()) return;
    setSubmitting(true);
    try {
      await api.createBuild(createApp, {
        title: createTitle.trim() || `Build ${createBranch}:${createCommit.slice(0, 7)}`,
        branch: createBranch.trim(),
        commit_sha: createCommit.trim(),
      });
      setOpenCreate(false);
      setCreateTitle('');
      setCreateCommit('');
      await fetchBuilds();
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка создания сборки');
    } finally {
      setSubmitting(false);
    }
  };

  const apps = [...new Map(builds.map((b) => [b.app_id, { id: b.app_id, name: b.app_name ?? b.app_id }] as const)).values()];
  const branches = [...new Set(builds.map((b) => b.branch).filter(Boolean))];

  const formatDuration = (started?: string, finished?: string) => {
    if (!started) return '—';
    const start = new Date(started).getTime();
    const end = finished ? new Date(finished).getTime() : Date.now();
    const s = Math.max(0, Math.round((end - start) / 1000));
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  };

  const handleCopySha = (sha: string) => { navigator.clipboard?.writeText(sha); };

  return (
    <ErrorBoundary viewName="Builds Registry">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              <Build sx={{ mr: 1, verticalAlign: 'middle', color: 'primary.main' }} />
              Реестр сборок (Builds Registry)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {loading ? 'Загрузка...' : `Сводная история сборок по всему КИТС · ${filtered.length} из ${builds.length}`}
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить"><IconButton onClick={fetchBuilds} disabled={loading} size="small"><Refresh fontSize="small" /></IconButton></Tooltip>
            <Button variant="contained" size="small" startIcon={<Add />}
              onClick={() => setOpenCreate(true)} sx={{ textTransform: 'none', fontWeight: 600 }}>
              Создать сборку
            </Button>
          </Box>
        </Box>

        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        {/* Filters */}
        <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', gap: 1.5, flexWrap: 'wrap', borderRadius: 2 }}>
          <TextField size="small" placeholder="Поиск по ID, SHA, названию..." value={search}
            onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 240 }} />
          <Select size="small" value={filterApp} onChange={(e) => setFilterApp(e.target.value)}
            displayEmpty sx={{ minWidth: 160 }}>
            <MenuItem value="all">Все приложения</MenuItem>
            {apps.map((a) => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
          </Select>
          <Select size="small" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
            displayEmpty sx={{ minWidth: 130 }}>
            <MenuItem value="all">Все статусы</MenuItem>
            <MenuItem value="pending">pending</MenuItem>
            <MenuItem value="running">running</MenuItem>
            <MenuItem value="success">success</MenuItem>
            <MenuItem value="failed">failed</MenuItem>
            <MenuItem value="aborted">aborted</MenuItem>
          </Select>
          <Select size="small" value={filterBranch} onChange={(e) => setFilterBranch(e.target.value)}
            displayEmpty sx={{ minWidth: 140 }}>
            <MenuItem value="all">Все ветки</MenuItem>
            {branches.map((b) => <MenuItem key={b} value={b}>{b}</MenuItem>)}
          </Select>
        </Paper>

        {/* Table */}
        {loading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} variant="rectangular" height={36} sx={{ borderRadius: 1 }} />)}
          </Box>
        ) : filtered.length === 0 ? (
          <EmptyState icon={<Build sx={{ fontSize: 36 }} />} title="Сборки не найдены"
            description={builds.length === 0 ? 'Сборок ещё нет. Создайте первую сборку через кнопку «Создать сборку».' : 'Измените параметры фильтрации.'}
            actionLabel={builds.length === 0 ? 'Создать сборку' : undefined}
            onAction={builds.length === 0 ? () => setOpenCreate(true) : undefined} />
        ) : (
          <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, maxHeight: 560, overflowY: 'auto' }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow sx={{ bgcolor: 'action.hover' }}>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>ID сборки</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Название</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Приложение</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Git SHA</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Ветка</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Статус</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Артефакты</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Инициатор</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Запуск</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Длит.</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((b) => {
                  const meta = statusMeta[b.status] ?? statusMeta.pending;
                  return (
                    <TableRow key={b.id} hover onClick={() => void openDetails(b)}
                      sx={{ cursor: 'pointer' }}>
                      <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 11 }}>{b.id}</TableCell>
                      <TableCell sx={{ fontSize: 12, fontWeight: 500 }}>{b.title || b.id}</TableCell>
                      <TableCell sx={{ fontSize: 12 }}>{b.app_name ?? b.app_id}</TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Code sx={{ fontSize: 11, color: 'text.secondary' }} />
                          {b.commit_sha.slice(0, 8)}
                          <IconButton size="small" sx={{ p: 0 }} onClick={() => handleCopySha(b.commit_sha)}>
                            <ContentCopy sx={{ fontSize: 10 }} />
                          </IconButton>
                        </Box>
                      </TableCell>
                      <TableCell><Chip label={b.branch} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} /></TableCell>
                      <TableCell>
                        <Chip label={meta.label} size="small" variant="outlined"
                          sx={{ fontSize: 9, height: 18, borderColor: meta.color, color: meta.color }} />
                      </TableCell>
                      <TableCell sx={{ fontSize: 11, fontFamily: 'monospace', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {b.artifacts?.join(', ') || '—'}
                      </TableCell>
                      <TableCell sx={{ fontSize: 11 }}>{b.initiator || '—'}</TableCell>
                      <TableCell sx={{ fontSize: 10, color: 'text.secondary' }}>
                        {b.started_at ? new Date(b.started_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                      </TableCell>
                      <TableCell sx={{ fontSize: 11, fontFamily: 'monospace' }}>{formatDuration(b.started_at, b.finished_at)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* Create Build Modal */}
        <Dialog open={openCreate} onClose={() => setOpenCreate(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать новую сборку</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField size="small" label="Название сборки" placeholder="Build main:a3f8c21e"
              value={createTitle} onChange={(e) => setCreateTitle(e.target.value)} fullWidth />
            <TextField size="small" label="App ID" placeholder="app-payments"
              value={createApp} onChange={(e) => setCreateApp(e.target.value)} fullWidth required />
            <TextField size="small" label="Ветка" value={createBranch}
              onChange={(e) => setCreateBranch(e.target.value)} fullWidth />
            <TextField size="small" label="Git Commit SHA" placeholder="a3f8c21e"
              value={createCommit} onChange={(e) => setCreateCommit(e.target.value)} fullWidth required />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCreate(false)} disabled={submitting}>Отмена</Button>
            <Button variant="contained" startIcon={<Build />}
              onClick={handleCreate} disabled={submitting || !createApp.trim() || !createCommit.trim()}
              sx={{ textTransform: 'none', fontWeight: 600 }}>
              {submitting ? 'Создание...' : 'Запустить сборку'}
            </Button>
          </DialogActions>
        </Dialog>

        {/* COS-198: Build Details — честные данные исполнения */}
        <Dialog open={detailsOpen} onClose={() => setDetailsOpen(false)} maxWidth="md" fullWidth>
          <DialogTitle sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
            <Build sx={{ color: 'primary.main' }} />
            Сборка {detailsBuild?.id ?? ''}
            {detailsBuild && (
              <Chip label={(statusMeta[detailsBuild.status] ?? statusMeta.pending).label}
                size="small" variant="outlined"
                sx={{
                  ml: 1, fontSize: 11,
                  borderColor: (statusMeta[detailsBuild.status] ?? statusMeta.pending).color,
                  color: (statusMeta[detailsBuild.status] ?? statusMeta.pending).color,
                }} />
            )}
          </DialogTitle>
          <DialogContent dividers>
            {detailsError && <Alert severity="error" sx={{ mb: 2 }}>{detailsError}</Alert>}
            {detailsLoading && !detailsBuild?.build_logs && (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2 }}>
                {[1, 2, 3].map((i) => <Skeleton key={i} variant="rectangular" height={28} sx={{ borderRadius: 1 }} />)}
              </Box>
            )}
            {detailsBuild && (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                {metaString(detailsBuild, 'failure_reason') && (
                  <Alert severity="error">
                    Провал: {metaString(detailsBuild, 'failure_reason')}
                  </Alert>
                )}
                {metaString(detailsBuild, 'logs_error') && (
                  <Alert severity="warning">
                    Логи недоступны: {metaString(detailsBuild, 'logs_error')}
                  </Alert>
                )}
                {metaString(detailsBuild, 'artifact_note') && (
                  <Alert severity="info">{metaString(detailsBuild, 'artifact_note')}</Alert>
                )}

                <Box sx={{ display: 'grid', gridTemplateColumns: '140px 1fr 140px 1fr', gap: 1 }}>
                  <Typography variant="caption" color="text.secondary">Название</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 500 }}>{detailsBuild.title || '—'}</Typography>
                  <Typography variant="caption" color="text.secondary">Приложение</Typography>
                  <Typography variant="body2">{detailsBuild.app_name ?? detailsBuild.app_id}</Typography>

                  <Typography variant="caption" color="text.secondary">Ветка</Typography>
                  <Typography variant="body2"><Chip label={detailsBuild.branch} size="small" variant="outlined" sx={{ fontSize: 10, height: 20 }} /></Typography>
                  <Typography variant="caption" color="text.secondary">Коммит</Typography>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {detailsBuild.commit_sha}
                    <IconButton size="small" sx={{ p: 0, ml: 0.5 }} onClick={() => handleCopySha(detailsBuild.commit_sha)}>
                      <ContentCopy sx={{ fontSize: 11 }} />
                    </IconButton>
                  </Typography>

                  <Typography variant="caption" color="text.secondary">Инициатор</Typography>
                  <Typography variant="body2">{detailsBuild.initiator || '—'}</Typography>
                  <Typography variant="caption" color="text.secondary">Прогон</Typography>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>{detailsBuild.run_id || '—'}</Typography>

                  <Typography variant="caption" color="text.secondary">Начало</Typography>
                  <Typography variant="body2">
                    {detailsBuild.started_at ? new Date(detailsBuild.started_at).toLocaleString('ru-RU') : '—'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">Финиш</Typography>
                  <Typography variant="body2">
                    {detailsBuild.finished_at ? new Date(detailsBuild.finished_at).toLocaleString('ru-RU') : '—'}
                  </Typography>
                </Box>

                <Divider />

                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>Артефакты (digest-ссылка)</Typography>
                  {(detailsBuild.artifacts?.length ?? 0) === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      {detailsBuild.status === 'success'
                        ? 'Успех без зафиксированного артефакта — см. примечание выше.'
                        : 'Нет (провал/отмена не оставляют артефактов).'}
                    </Typography>
                  ) : (
                    detailsBuild.artifacts?.map((a) => (
                      <Typography key={a} variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>{a}</Typography>
                    ))
                  )}
                </Box>

                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>Evidence-след ({detailsBuild.evidence_refs?.length ?? 0})</Typography>
                  {(detailsBuild.evidence_refs?.length ?? 0) === 0 ? (
                    <Typography variant="body2" color="text.secondary">Записей ещё нет.</Typography>
                  ) : (
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {detailsBuild.evidence_refs?.map((e) => (
                        <Chip key={e} label={e} size="small" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: 10 }} />
                      ))}
                    </Box>
                  )}
                </Box>

                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>Логи исполнения</Typography>
                  {detailsBuild.build_logs ? (
                    <Box component="pre" sx={{
                      fontFamily: 'monospace', fontSize: 11, whiteSpace: 'pre-wrap',
                      maxHeight: 280, overflow: 'auto', bgcolor: 'action.hover',
                      borderRadius: 1, p: 1, m: 0,
                    }}>
                      {detailsBuild.build_logs}
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      {metaString(detailsBuild, 'logs_error')
                        ? 'Логи недоступны (причина выше).'
                        : (detailsBuild.status === 'pending' || detailsBuild.status === 'running')
                          ? 'Исполнение ещё не оставило логов.'
                          : 'Логов нет.'}
                    </Typography>
                  )}
                </Box>
              </Box>
            )}
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            {(detailsBuild?.status === 'pending' || detailsBuild?.status === 'running') && (
              <Button color="warning" onClick={handleAbort} disabled={aborting}
                sx={{ textTransform: 'none', fontWeight: 600 }}>
                {aborting ? 'Прерывание...' : 'Прервать сборку'}
              </Button>
            )}
            <Button onClick={() => setDetailsOpen(false)} sx={{ textTransform: 'none' }}>Закрыть</Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}