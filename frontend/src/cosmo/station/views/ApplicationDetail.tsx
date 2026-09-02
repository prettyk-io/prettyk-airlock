/**
 * SAN-003 / SAN-004: Application Detail — Canonical 6-Tab Card.
 *
 * Tabs:
 *   [1] Информация    — General data, integrations, contacts
 *   [2] Сборки        — Builds table (ID, SHA, status, artifacts)
 *   [3] Деплои        — Deployments table (zone, segment, runtime, rollback)
 *   [4] Релизы        — Release bundles, SemVer tags
 *   [5] Настройки и ЖЦ — 3 accordions, 14 LC steps
 *   [6] Команда       — Members with roles, merge/isolate toggle
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Card, CardContent, Grid, Chip, Paper,
  Button, Tabs, Tab, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, MenuItem,
  Accordion, AccordionSummary, AccordionDetails, Divider,
  Switch, FormControlLabel, Select, Alert, Tooltip, IconButton,
  Skeleton, Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material';
import {
  Info, Build, CloudUpload, RocketLaunch, Settings, Group,
  CheckCircle, Cancel, HourglassEmpty, PlayArrow, Warning,
  ExpandMore, Code, Link as LinkIcon, Delete, Refresh,
  ContentCopy, Add,
} from '@mui/icons-material';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';
import { api, type Application, type Build as BuildRecord, type Deployment as DeploymentRecord, type ForgeLastPush } from '../api';

// ── Status helpers ──────────────────────────────────────────────────

const buildStatusMeta: Record<string, { color: string; icon: React.ReactElement }> = {
  success: { color: '#10B981', icon: <CheckCircle sx={{ fontSize: 14, color: '#10B981' }} /> },
  failed:  { color: '#EF4444', icon: <Cancel sx={{ fontSize: 14, color: '#EF4444' }} /> },
  running: { color: '#3B82F6', icon: <HourglassEmpty sx={{ fontSize: 14, color: '#3B82F6' }} /> },
  pending: { color: '#9CA3AF', icon: <HourglassEmpty sx={{ fontSize: 14, color: '#9CA3AF' }} /> },
  aborted: { color: '#F59E0B', icon: <Cancel sx={{ fontSize: 14, color: '#F59E0B' }} /> },
};

const deploymentStatusMeta: Record<string, { color: string; label: string }> = {
  success: { color: '#10B981', label: 'active' },
  failed:  { color: '#EF4444', label: 'failed' },
  running: { color: '#3B82F6', label: 'running' },
  pending: { color: '#9CA3AF', label: 'pending' },
  deleted: { color: '#F59E0B', label: 'deleted' },
};

const zoneLabels: Record<string, { label: string; color: string }> = {
  zr:  { label: 'ЗР', color: '#3B82F6' },
  zt:  { label: 'ЗТ', color: '#F59E0B' },
  zpe: { label: 'ЗПЭ', color: '#10B981' },
};

// ── LC Step definitions (8 steps: 7 static + 1 deploy) ──────────

type LcCondition = 'CONTINUE' | 'TERMINATE_ON_ERROR';

interface LcStep {
  id: string; label: string; category: 'static' | 'deploy'; required: boolean;
}

const LC_STEPS: LcStep[] = [
  // 7 статики (без PTAI, Solar Appscreener, Sandbox, Kaspersky Container Security)
  { id: 'lc-build',      label: 'Сборка',                     category: 'static', required: true },
  { id: 'lc-unit',       label: 'Юнит-тестирование',           category: 'static', required: false },
  { id: 'lc-docs',       label: 'Генерация документации',       category: 'static', required: false },
  { id: 'lc-sonar',      label: 'SonarQube',                   category: 'static', required: false },
  { id: 'lc-trivy',      label: 'Trivy',                       category: 'static', required: false },
  { id: 'lc-codescoring',label: 'CodeScoring',                 category: 'static', required: false },
  { id: 'lc-sbom',       label: 'Генерация SBOM (CycloneDX)',  category: 'static', required: false },
  // 1 деплой
  { id: 'lc-deploy',     label: 'Развёртывание ПО',             category: 'deploy', required: true },
];

// ── Props ───────────────────────────────────────────────────────────

interface ApplicationDetailProps {
  app: Application;
  onBack: () => void;
}

// ── Component ───────────────────────────────────────────────────────

export function ApplicationDetail({ app, onBack }: ApplicationDetailProps) {
  const [tab, setTab] = useState(0);

  // ── API state ──
  const [builds, setBuilds] = useState<BuildRecord[]>([]);
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([]);
  const [buildsLoading, setBuildsLoading] = useState(false);
  const [deploysLoading, setDeploysLoading] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);

  // Create build modal
  const [openCreateBuild, setOpenCreateBuild] = useState(false);
  const [createBranch, setCreateBranch] = useState('main');
  const [createCommit, setCreateCommit] = useState('');

  // COS-096: live forge surface
  const [forge, setForge] = useState<ForgeLastPush | null>(null);
  const [forgeLoading, setForgeLoading] = useState(false);

  const fetchBuilds = useCallback(async () => {
    setBuildsLoading(true);
    try { setBuilds(await api.getAppBuilds(app.id) ?? []); } catch { setBuilds([]); }
    finally { setBuildsLoading(false); }
  }, [app.id]);

  const fetchDeployments = useCallback(async () => {
    setDeploysLoading(true);
    try { setDeployments(await api.getAppDeployments(app.id) ?? []); } catch { setDeployments([]); }
    finally { setDeploysLoading(false); }
  }, [app.id]);

  const fetchForge = useCallback(async () => {
    setForgeLoading(true);
    try { setForge(await api.getAppForgeLastPush(app.id)); }
    catch { setForge(null); } // честный empty — не выдумываем статус
    finally { setForgeLoading(false); }
  }, [app.id]);

  useEffect(() => { fetchBuilds(); fetchDeployments(); fetchForge(); }, [fetchBuilds, fetchDeployments, fetchForge]);

  const handleCreateBuild = async () => {
    if (!createCommit.trim() || !createBranch.trim()) return;
    try {
      await api.createBuild(app.id, { title: `Build ${createBranch}:${createCommit.slice(0, 7)}`, branch: createBranch, commit_sha: createCommit.trim() });
      toast.success('Сборка запущена');
      setOpenCreateBuild(false); setCreateCommit('');
      await fetchBuilds();
    } catch (err: unknown) { toast.error((err as Error)?.message || 'Ошибка создания сборки'); }
  };

  const handleCreateDeployment = async (buildId: string, zone: string) => {
    try {
      await api.createDeployment(app.id, { build_id: buildId, target_zone: zone, segment: 'bare', runtime_id: 'k8s-default' });
      toast.success(`Деплой в ${zoneLabels[zone]?.label || zone} запущен`);
      await fetchDeployments();
    } catch (err: unknown) { toast.error((err as Error)?.message || 'Ошибка создания деплоя'); }
  };

  const handleRollback = async (deployId: string) => {
    try {
      await api.rollbackDeployment(deployId);
      toast.success(`Деплой ${deployId} откачен`);
      await fetchDeployments();
    } catch (err: unknown) { toast.error((err as Error)?.message || 'Ошибка отката'); }
  };

  const handleSaveSettings = async () => {
    setSavingSettings(true);
    try {
      await api.updateAppSettings(app.id, {
        jira_url: jiraUrl, app_status: appStatus, pib_category: pibCategory,
        unit_tests: unitTestsEnabled, multithreading,
        auto_start: autoStart, code_transfer: codeTransfer, deploy_timeout: deployTimeout,
        abac_roles: abacRoles, db_query_norm: dbQueryNorm, health_monitoring: healthMonitoring,
        lc_conditions: lcConditions,
      });
      toast.success('Настройки карточки и ЖЦ сохранены');
    } catch (err: unknown) {
      toast.error((err as Error)?.message || 'Ошибка сохранения настроек');
    } finally { setSavingSettings(false); }
  };

  // Settings state
  const [jiraUrl, setJiraUrl] = useState('');
  const [appStatus, setAppStatus] = useState('active');
  const [pibCategory, setPibCategory] = useState('Критичная');
  const [unitTestsEnabled, setUnitTestsEnabled] = useState(true);
  const [multithreading, setMultithreading] = useState(false);
  const [autoStart, setAutoStart] = useState(true);
  const [codeTransfer, setCodeTransfer] = useState(true);
  const [deployTimeout, setDeployTimeout] = useState(30);
  const [abacRoles, setAbacRoles] = useState('secops,dev,auditor');
  const [dbQueryNorm, setDbQueryNorm] = useState(20.0);
  const [healthMonitoring, setHealthMonitoring] = useState(true);
  const [lcConditions, setLcConditions] = useState<Record<string, LcCondition>>(() => {
    const initial: Record<string, LcCondition> = {};
    LC_STEPS.forEach((s) => { initial[s.id] = 'CONTINUE'; });
    return initial;
  });
  const [teamInheritance, setTeamInheritance] = useState<'merge' | 'isolate'>('merge');

  return (
    <ErrorBoundary viewName={`Карточка приложения: ${app.id}`}>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Box>
            <Button size="small" onClick={onBack} sx={{ textTransform: 'none', mb: 0.5 }}>
              ← Назад к приложениям
            </Button>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              {app.id}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, mt: 0.5, alignItems: 'center' }}>
              <Chip label={`L${app.level} Приложение`} size="small" color="primary" />
              <Chip label={app.domain_id} size="small" variant="outlined" />
              <Chip icon={<LinkIcon sx={{ fontSize: 12 }} />} label={app.repo_binding.repo_path} size="small" variant="outlined" />
            </Box>
          </Box>
          <Box sx={{ textAlign: 'right' }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              ID: {app.id} · Код: {app.id.toUpperCase().replace(/-/g, '_')}
            </Typography>
          </Box>
        </Box>

        {/* Tabs */}
        <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
            <Tab icon={<Info />} iconPosition="start" label="Информация" sx={{ textTransform: 'none', fontWeight: 600, minHeight: 44 }} />
            <Tab icon={<Build />} iconPosition="start" label="Сборки" sx={{ textTransform: 'none', fontWeight: 600, minHeight: 44 }} />
            <Tab icon={<CloudUpload />} iconPosition="start" label="Деплои" sx={{ textTransform: 'none', fontWeight: 600, minHeight: 44 }} />
            <Tab icon={<RocketLaunch />} iconPosition="start" label="Релизы" sx={{ textTransform: 'none', fontWeight: 600, minHeight: 44 }} />
            <Tab icon={<Settings />} iconPosition="start" label="Настройки и ЖЦ" sx={{ textTransform: 'none', fontWeight: 600, minHeight: 44 }} />
            <Tab icon={<Group />} iconPosition="start" label="Команда" sx={{ textTransform: 'none', fontWeight: 600, minHeight: 44 }} />
          </Tabs>
        </Box>

        {/* ═══ Tab 0: Информация ═══ */}
        {tab === 0 && (
          <Grid container spacing={2}>
            {/* General Data */}
            <Grid size={12}>
          <Card variant="outlined" sx={{ borderRadius: 2 }}>
            <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Общие данные</Typography>
            </Box>
            <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {[
                ['Статус', <Chip label="Active" size="small" color="success" />],
                ['Код', <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{app.id.toUpperCase().replace(/-/g, '_')}</Typography>],
                ['Тип', <Typography variant="body2">{app.level === 0 ? 'Библиотека' : 'Микросервис'}</Typography>],
                ['Приоритет запуска', <Typography variant="body2">75 / 100</Typography>],
                ['Капсула', <Chip label="Нет" size="small" variant="outlined" />],
              ].map(([label, value]) => (
                <Box key={label as string} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary">{label}</Typography>
                  {value}
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>

            {/* COS-096: Live Forge */}
            <Grid size={12}>
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Git-активность (live forge)</Typography>
                  <IconButton size="small" onClick={fetchForge} disabled={forgeLoading} data-testid="forge-refresh">
                    <Refresh sx={{ fontSize: 16 }} />
                  </IconButton>
                </Box>
                <CardContent>
                  {forgeLoading && !forge ? (
                    <Skeleton variant="rectangular" height={64} sx={{ borderRadius: 1 }} />
                  ) : !forge ? (
                    <Typography variant="body2" color="text.secondary">
                      Статус forge недоступен — проверьте подключение к API.
                    </Typography>
                  ) : (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                      {forge.last_push ? (
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                          <Chip size="small" color="success" label={`push · ${forge.last_push.branch}`} />
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                            {forge.last_push.head_sha.slice(0, 8)}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {forge.last_push.pusher} · {forge.last_push.commit_count} коммит(ов) · {new Date(forge.last_push.received_at).toLocaleString()}
                          </Typography>
                        </Box>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          Пушей с момента старта ПУ не было (пусто = пусто).
                        </Typography>
                      )}
                      {forge.forge_unreachable ? (
                        <Alert severity="warning" sx={{ py: 0.5 }}>
                          Forge недоступен: {forge.forge_unreachable}
                        </Alert>
                      ) : forge.recent_commits.length > 0 ? (
                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                          {forge.recent_commits.slice(0, 3).map((c) => (
                            <Box key={c.sha} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                              <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 600, minWidth: 64 }}>
                                {c.sha.slice(0, 7)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary" noWrap>
                                {c.message}
                              </Typography>
                            </Box>
                          ))}
                        </Box>
                      ) : null}
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        )}

        {/* ═══ Tab 1: Сборки (Live API) ═══ */}
        {tab === 1 && (
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
              <Typography variant="body2" color="text.secondary">
                {buildsLoading ? 'Загрузка...' : `История сборок · ${builds.length}`}
              </Typography>
              <Button variant="contained" size="small" startIcon={<Add />}
                onClick={() => setOpenCreateBuild(true)} sx={{ textTransform: 'none', fontWeight: 600 }}>
                Создать сборку
              </Button>
            </Box>
            {buildsLoading ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {[1, 2, 3].map((i) => <Skeleton key={i} variant="rectangular" height={36} sx={{ borderRadius: 1 }} />)}
              </Box>
            ) : builds.length === 0 ? (
              <EmptyState icon={<Build sx={{ fontSize: 28 }} />} title="Сборок ещё нет" description="Запустите первую сборку для этого приложения." actionLabel="Создать сборку" onAction={() => setOpenCreateBuild(true)} />
            ) : (
              <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
                <Table size="small">
                  <TableHead sx={{ bgcolor: 'action.hover' }}><TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>ID</TableCell><TableCell sx={{ fontWeight: 600 }}>Название</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Git SHA</TableCell><TableCell sx={{ fontWeight: 600 }}>Статус</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Ветка</TableCell><TableCell sx={{ fontWeight: 600 }}>Артефакты</TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {builds.map((b) => {
                      const meta = buildStatusMeta[b.status];
                      return (
                        <TableRow key={b.id} hover>
                          <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600 }}>{b.id}</TableCell>
                          <TableCell>{b.title || b.id}</TableCell>
                          <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                              <Code sx={{ fontSize: 12, color: 'text.secondary' }} />
                              {b.commit_sha.slice(0, 8)}
                              <IconButton size="small" sx={{ p: 0 }}><ContentCopy sx={{ fontSize: 10 }} /></IconButton>
                            </Box>
                          </TableCell>
                          <TableCell> {meta && <Chip icon={meta.icon} label={b.status} size="small" variant="outlined" sx={{ fontSize: 10, height: 20, borderColor: meta.color, color: meta.color }} />} </TableCell>
                          <TableCell><Chip label={b.branch} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} /></TableCell>
                          <TableCell sx={{ fontSize: 12, fontFamily: 'monospace' }}>{b.artifacts?.join(', ') || '—'}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>
        )}

        {/* ═══ Tab 2: Деплои (Live API) ═══ */}
        {tab === 2 && (
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {deploysLoading ? 'Загрузка...' : `Развертывания по зонам безопасности · ${deployments.length}`}
            </Typography>
            {deploysLoading ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {[1, 2].map((i) => <Skeleton key={i} variant="rectangular" height={36} sx={{ borderRadius: 1 }} />)}
              </Box>
            ) : deployments.length === 0 ? (
              <EmptyState icon={<CloudUpload sx={{ fontSize: 28 }} />} title="Деплоев ещё нет"
                description={builds.length > 0 ? 'Выберите успешную сборку для развертывания.' : 'Сначала создайте успешную сборку.'} />
            ) : (
              <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
                <Table size="small">
                  <TableHead sx={{ bgcolor: 'action.hover' }}><TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>ID</TableCell><TableCell sx={{ fontWeight: 600 }}>Зона</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Сегмент</TableCell><TableCell sx={{ fontWeight: 600 }}>Runtime</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Сборка</TableCell><TableCell sx={{ fontWeight: 600 }}>Статус</TableCell>
                    <TableCell sx={{ fontWeight: 600 }} align="right">Действия</TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {deployments.map((d) => {
                      const z = zoneLabels[d.target_zone] ?? { label: d.target_zone, color: '#64748B' };
                      const sMeta = deploymentStatusMeta[d.status] ?? deploymentStatusMeta.pending;
                      return (
                        <TableRow key={d.id} hover>
                          <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600 }}>{d.id}</TableCell>
                          <TableCell><Chip label={z.label} size="small" sx={{ fontWeight: 700, bgcolor: z.color, color: '#fff' }} /></TableCell>
                          <TableCell><Chip label={d.segment === 'bare' ? 'Голый' : 'Интегр.'} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} /></TableCell>
                          <TableCell sx={{ fontSize: 12 }}>{d.runtime_name}</TableCell>
                          <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>{d.build_id}</TableCell>
                          <TableCell><Chip label={sMeta.label} size="small" variant="outlined" sx={{ fontSize: 10, height: 20, borderColor: sMeta.color, color: sMeta.color }} /></TableCell>
                          <TableCell align="right">
                            {d.status === 'success' && (
                              <Button size="small" color="error" variant="outlined" onClick={() => handleRollback(d.id)}
                                sx={{ textTransform: 'none', fontSize: 11, minHeight: 26 }}>Откатить</Button>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>
        )}

        {/* ═══ Tab 3: Релизы (static) ═══ */}
        {tab === 3 && (
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Релизные бандлы и SemVer-теги</Typography>
            <EmptyState icon={<RocketLaunch sx={{ fontSize: 28 }} />} title="Релизов пока нет"
              description="Релизы появятся после прохождения всех Security Gates и 2FA-подписания." />
          </Box>
        )}

        {/* ═══ Tab 4: Настройки и ЖЦ (SAN-004) ═══ */}
        {tab === 4 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {/* Accordion 1: Общие настройки */}
            <Accordion defaultExpanded sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Settings sx={{ color: 'text.secondary', fontSize: 20 }} />
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Общие настройки</Typography>
                  <Chip label="JIRA · Статусы · Vault · ABAC" size="small" variant="outlined" sx={{ fontSize: 10 }} />
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField label="JIRA URL" value={jiraUrl} onChange={(e) => setJiraUrl(e.target.value)} size="small" fullWidth />
                  </Grid>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField select label="Статус приложения" value={appStatus} onChange={(e) => setAppStatus(e.target.value)} size="small" fullWidth>
                      {['active', 'staging', 'idle', 'maintenance', 'decommissioned'].map((s) => (
                        <MenuItem key={s} value={s}>{s}</MenuItem>
                      ))}
                    </TextField>
                  </Grid>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField select label="Категоризация ПИБ" value={pibCategory} onChange={(e) => setPibCategory(e.target.value)} size="small" fullWidth>
                      {['Критичная', 'Высокая', 'Средняя', 'Низкая'].map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
                    </TextField>
                  </Grid>
                  <Grid size={12}><Divider /></Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <FormControlLabel control={<Switch checked={unitTestsEnabled} onChange={(_, v) => setUnitTestsEnabled(v)} />} label="Unit-тесты" />
                  </Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <FormControlLabel control={<Switch checked={multithreading} onChange={(_, v) => setMultithreading(v)} />} label="Многопоточность" />
                  </Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <FormControlLabel control={<Switch checked={autoStart} onChange={(_, v) => setAutoStart(v)} />} label="Авто-запуск" />
                  </Grid>
                  <Grid size={{ xs: 6, sm: 3 }}>
                    <FormControlLabel control={<Switch checked={codeTransfer} onChange={(_, v) => setCodeTransfer(v)} />} label="Передача кода/бинарей" />
                  </Grid>
                  <Grid size={12}><Divider /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField label="Таймаут деплоя (мин)" type="number" value={deployTimeout} onChange={(e) => setDeployTimeout(Number(e.target.value))} size="small" fullWidth slotProps={{ htmlInput: { min: 1, max: 120 } }} />
                  </Grid>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField label="ABAC роли" value={abacRoles} onChange={(e) => setAbacRoles(e.target.value)} size="small" fullWidth helperText="Через запятую" />
                  </Grid>
                </Grid>
              </AccordionDetails>
            </Accordion>

            {/* Accordion 2: Мониторинг */}
            <Accordion sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Warning sx={{ color: 'text.secondary', fontSize: 20 }} />
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Мониторинг</Typography>
                  <Chip label="БД · Доступность" size="small" variant="outlined" sx={{ fontSize: 10 }} />
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField label="Норматив выполнения запроса в БД (сек)" type="number" value={dbQueryNorm} onChange={(e) => setDbQueryNorm(Number(e.target.value))} size="small" fullWidth slotProps={{ htmlInput: { min: 0.1, max: 300, step: 0.1 } }} />
                  </Grid>
                  <Grid size={{ xs: 12, sm: 6 }} sx={{ display: 'flex', alignItems: 'center' }}>
                    <FormControlLabel control={<Switch checked={healthMonitoring} onChange={(_, v) => setHealthMonitoring(v)} />} label="Мониторинг доступности" />
                  </Grid>
                </Grid>
              </AccordionDetails>
            </Accordion>

            {/* Accordion 3: Конфигурация ЖЦ (14 шагов) */}
            <Accordion defaultExpanded sx={{ borderRadius: 2, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Code sx={{ color: 'text.secondary', fontSize: 20 }} />
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Конфигурация жизненного цикла (8 шагов)</Typography>
                  <Chip label={`${LC_STEPS.filter(s => s.required).length} обязательных`} size="small" color="warning" variant="outlined" sx={{ fontSize: 10 }} />
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                {/* Category: Статический анализ */}
                <Typography variant="overline" sx={{ fontWeight: 700, color: 'text.secondary', display: 'block', mb: 1 }}>
                  🔍 Статический анализ (7 шагов)
                </Typography>
                <Grid container spacing={1}>
                  {LC_STEPS.filter(s => s.category === 'static').map((step) => (
                    <Grid size={{ xs: 12, sm: 6, md: 4 }} key={step.id}>
                      <Card variant="outlined" sx={{ borderRadius: 1.5, p: 1.5, borderColor: step.required ? 'warning.light' : 'divider' }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            {step.required && <Chip label="required" size="small" color="warning" sx={{ fontSize: 8, height: 16, fontWeight: 700 }} />}
                            <Typography variant="caption" sx={{ fontWeight: 700 }}>{step.label}</Typography>
                          </Box>
                        </Box>
                        <Select
                          value={lcConditions[step.id]}
                          onChange={(e) => setLcConditions(prev => ({ ...prev, [step.id]: e.target.value as LcCondition }))}
                          size="small"
                          fullWidth
                          sx={{ fontSize: 11 }}
                        >
                          <MenuItem value="CONTINUE" sx={{ fontSize: 11 }}>▶ Продолжить (CONTINUE)</MenuItem>
                          <MenuItem value="TERMINATE_ON_ERROR" sx={{ fontSize: 11 }}>⏹ Завершить при ошибке (TERMINATE_ON_ERROR)</MenuItem>
                        </Select>
                      </Card>
                    </Grid>
                  ))}
                </Grid>

                <Divider sx={{ my: 2 }} />

                {/* Category: Деплой */}
                <Typography variant="overline" sx={{ fontWeight: 700, color: 'text.secondary', display: 'block', mb: 1 }}>
                  🚀 Деплой (1 шаг)
                </Typography>
                <Grid container spacing={1}>
                  {LC_STEPS.filter(s => s.category === 'deploy').map((step) => (
                    <Grid size={{ xs: 12, sm: 6, md: 4 }} key={step.id}>
                      <Card variant="outlined" sx={{ borderRadius: 1.5, p: 1.5, borderColor: step.required ? 'warning.light' : 'divider' }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <Chip label="required" size="small" color="warning" sx={{ fontSize: 8, height: 16, fontWeight: 700 }} />
                            <Typography variant="caption" sx={{ fontWeight: 700 }}>{step.label}</Typography>
                          </Box>
                        </Box>
                        <Select
                          value={lcConditions[step.id]}
                          onChange={(e) => setLcConditions(prev => ({ ...prev, [step.id]: e.target.value as LcCondition }))}
                          size="small"
                          fullWidth
                          sx={{ fontSize: 11 }}
                        >
                          <MenuItem value="CONTINUE" sx={{ fontSize: 11 }}>▶ Продолжить (CONTINUE)</MenuItem>
                          <MenuItem value="TERMINATE_ON_ERROR" sx={{ fontSize: 11 }}>⏹ Завершить при ошибке (TERMINATE_ON_ERROR)</MenuItem>
                        </Select>
                      </Card>
                    </Grid>
                  ))}
                </Grid>

                <Divider sx={{ my: 2 }} />
              </AccordionDetails>
            </Accordion>

            {/* Save button */}
            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button variant="contained" startIcon={<Settings />}
                onClick={handleSaveSettings} disabled={savingSettings}
                sx={{ textTransform: 'none', fontWeight: 600 }}>
                {savingSettings ? 'Сохранение...' : 'Сохранить настройки'}
              </Button>
            </Box>
          </Box>
        )}

        {/* ═══ Tab 5: Команда ═══ */}
        {tab === 5 && (
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="body2" color="text.secondary">Участники проекта и их роли</Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Typography variant="caption" color="text.secondary">Наследование:</Typography>
                <Box sx={{ display: 'flex', gap: 0 }}>
                  <Chip label="Merge" size="small" color={teamInheritance === 'merge' ? 'primary' : 'default'}
                    variant={teamInheritance === 'merge' ? 'filled' : 'outlined'}
                    onClick={() => setTeamInheritance('merge')} sx={{ cursor: 'pointer', borderTopRightRadius: 0, borderBottomRightRadius: 0 }} />
                  <Chip label="Isolate" size="small" color={teamInheritance === 'isolate' ? 'error' : 'default'}
                    variant={teamInheritance === 'isolate' ? 'filled' : 'outlined'}
                    onClick={() => setTeamInheritance('isolate')} sx={{ cursor: 'pointer', borderTopLeftRadius: 0, borderBottomLeftRadius: 0 }} />
                </Box>
              </Box>
            </Box>
            <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
              <Table size="small">
                <TableHead sx={{ bgcolor: 'action.hover' }}>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Участник</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Роль</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Email</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {[
                    { name: 'Иванов И.И.', role: 'IT-лидер', email: 'it-lead@cosmo.local', avatar: 'II' },
                    { name: 'Петров П.П.', role: 'Разработчик', email: 'dev@cosmo.local', avatar: 'PP' },
                  ].map((m) => (
                    <TableRow key={m.email} hover>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                          <Box sx={{ width: 32, height: 32, borderRadius: '50%', bgcolor: m.role === 'IT-лидер' ? 'primary.main' : 'action.selected', color: m.role === 'IT-лидер' ? '#fff' : 'text.primary', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 12 }}>
                            {m.avatar}
                          </Box>
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>{m.name}</Typography>
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip label={m.role} size="small" variant="outlined" sx={{ fontSize: 10 }} />
                      </TableCell>
                      <TableCell sx={{ fontSize: 12, fontFamily: 'monospace', color: 'text.secondary' }}>{m.email}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}
        {/* Create Build Modal */}
        <Dialog open={openCreateBuild} onClose={() => setOpenCreateBuild(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать сборку для {app.id}</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField size="small" label="Ветка" value={createBranch}
              onChange={(e) => setCreateBranch(e.target.value)} fullWidth />
            <TextField size="small" label="Git Commit SHA" placeholder="a3f8c21e"
              value={createCommit} onChange={(e) => setCreateCommit(e.target.value)} fullWidth required />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCreateBuild(false)}>Отмена</Button>
            <Button variant="contained" startIcon={<Build />}
              onClick={handleCreateBuild} disabled={!createCommit.trim()}
              sx={{ textTransform: 'none', fontWeight: 600 }}>Запустить сборку</Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}