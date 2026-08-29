/**
 * COS-022 / COS-047: Control Station Applications View.
 *
 * Applications & Groups hierarchy: Domain → Group → App/Library with Git Repo Bindings.
 * Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Tabs, Tab,
} from '@mui/material';
import {
  Apps, Add, Delete, Refresh,
  Code, Folder, AccountTree, Link as LinkIcon,
} from '@mui/icons-material';
import {
  api, type Application, type Group, type Domain,
} from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

interface ApplicationsProps {
  selectedDomain?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function Applications({ selectedDomain = 'all', onNavigateToIDE }: ApplicationsProps) {
  const [tab, setTab] = useState(0);
  const [apps, setApps] = useState<Application[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dialogs
  const [openAppDialog, setOpenAppDialog] = useState(false);
  const [openGroupDialog, setOpenGroupDialog] = useState(false);
  const [openDomainDialog, setOpenDomainDialog] = useState(false);

  // New App form
  const [appId, setAppId] = useState('');
  const [appDomainId, setAppDomainId] = useState('');
  const [appLevel, setAppLevel] = useState(1);
  const [appGroupId, setAppGroupId] = useState('');
  const [repoForgeId, setRepoForgeId] = useState('gitea');
  const [repoPath, setRepoPath] = useState('');
  const [repoBranch, setRepoBranch] = useState('main');

  // New Group form
  const [groupId, setGroupId] = useState('');
  const [groupName, setGroupName] = useState('');
  const [groupDomainId, setGroupDomainId] = useState('');

  // New Domain form
  const [domId, setDomId] = useState('');
  const [domLabel, setDomLabel] = useState('');
  const [domForgeType, setDomForgeType] = useState<'gitea' | 'jenkins'>('gitea');
  const [domForgeUrl, setDomForgeUrl] = useState('http://gitea:3000');
  const [domTokenRef, setDomTokenRef] = useState('VAULT/TOKEN');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [appsData, groupsData, domainsData] = await Promise.all([
        api.getApps(selectedDomain),
        api.getGroups(selectedDomain),
        api.getDomains(),
      ]);
      setApps(appsData || []);
      setGroups(groupsData || []);
      setDomains(domainsData || []);
      if (domainsData.length > 0) {
        if (!appDomainId) setAppDomainId(domainsData[0].id);
        if (!groupDomainId) setGroupDomainId(domainsData[0].id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки приложений';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedDomain, appDomainId, groupDomainId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCreateApp = async () => {
    if (!appId.trim() || !appDomainId || !repoPath.trim()) return;
    try {
      await api.createApp({
        id: appId.trim(),
        domain_id: appDomainId,
        level: appLevel,
        group_id: appGroupId.trim() || null,
        repo_binding: {
          forge_id: repoForgeId,
          repo_path: repoPath.trim(),
          default_branch: repoBranch.trim() || 'main',
        },
      });
      toast.success(`Приложение ${appId.trim()} создано`);
      setOpenAppDialog(false);
      setAppId('');
      setRepoPath('');
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка создания приложения';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleCreateGroup = async () => {
    if (!groupId.trim() || !groupName.trim() || !groupDomainId) return;
    try {
      await api.createGroup({
        id: groupId.trim(),
        name: groupName.trim(),
        domain_id: groupDomainId,
        level: 2,
      });
      toast.success(`Группа ${groupName.trim()} создана`);
      setOpenGroupDialog(false);
      setGroupId('');
      setGroupName('');
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка создания группы';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleCreateDomain = async () => {
    if (!domId.trim() || !domLabel.trim()) return;
    try {
      await api.createDomain({
        id: domId.trim(),
        label: domLabel.trim(),
        forge_binding: {
          forge_type: domForgeType,
          url: domForgeUrl.trim(),
          token_ref: domTokenRef.trim(),
        },
        rbac_config: {},
        quota: { max_runs: 50, max_storage_gb: 100, max_cpu: 8 },
      });
      toast.success(`Домен ${domLabel.trim()} зарегистрирован`);
      setOpenDomainDialog(false);
      setDomId('');
      setDomLabel('');
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка создания домена';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleDeleteApp = async (id: string) => {
    if (!window.confirm(`Удалить приложение ${id}?`)) return;
    try {
      await api.deleteApp(id);
      toast.info(`Приложение ${id} удалено`);
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleDeleteGroup = async (id: string) => {
    if (!window.confirm(`Удалить группу ${id}?`)) return;
    try {
      await api.deleteGroup(id);
      toast.info(`Группа ${id} удалена`);
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления';
      setError(msg);
      toast.error(msg);
    }
  };

  const handleDeleteDomain = async (id: string) => {
    if (!window.confirm(`Удалить домен ${id}?`)) return;
    try {
      await api.deleteDomain(id);
      toast.info(`Домен ${id} удален`);
      await fetchData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка удаления';
      setError(msg);
      toast.error(msg);
    }
  };

  return (
    <ErrorBoundary viewName="Приложения (Applications)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Приложения и архитектура
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Управление иерархией КИТС (Домены → Группы → Приложения/Библиотеки) и связками с Git-репозиториями.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchData} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenDomainDialog(true)}
              sx={{ textTransform: 'none' }}
            >
              Домен
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenGroupDialog(true)}
              sx={{ textTransform: 'none' }}
            >
              Группа
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenAppDialog(true)}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Приложение
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Tabs */}
        <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tabs value={tab} onChange={(_, val) => setTab(val)}>
            <Tab label={`Приложения (${apps.length})`} sx={{ textTransform: 'none', fontWeight: 600 }} />
            <Tab label={`Группы (${groups.length})`} sx={{ textTransform: 'none', fontWeight: 600 }} />
            <Tab label={`Домены (${domains.length})`} sx={{ textTransform: 'none', fontWeight: 600 }} />
          </Tabs>
        </Box>

        {/* Tab 0: Applications */}
        {tab === 0 && (
          <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, overflowX: 'auto' }}>
            <Table size="small">
              <TableHead sx={{ bgcolor: 'action.hover' }}>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>ID Приложения</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Домен</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Уровень</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Группа</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Git Репозиторий</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Активный план</TableCell>
                  <TableCell sx={{ fontWeight: 600 }} align="right">Действия</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  [1, 2, 3].map((i) => (
                    <TableRow key={i}>
                      <TableCell><Skeleton width={120} /></TableCell>
                      <TableCell><Skeleton width={80} /></TableCell>
                      <TableCell><Skeleton width={100} /></TableCell>
                      <TableCell><Skeleton width={60} /></TableCell>
                      <TableCell><Skeleton width={140} /></TableCell>
                      <TableCell><Skeleton width={100} /></TableCell>
                      <TableCell align="right"><Skeleton width={60} sx={{ ml: 'auto' }} /></TableCell>
                    </TableRow>
                  ))
                ) : apps.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} sx={{ p: 0 }}>
                      <EmptyState
                        icon={<Apps sx={{ fontSize: 28 }} />}
                        title="Приложения не найдены"
                        description="Создайте первое приложение или привяжите существующий Git-репозиторий."
                        actionLabel="Добавить приложение"
                        onAction={() => setOpenAppDialog(true)}
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  apps.map((a) => (
                    <TableRow key={a.id} hover>
                      <TableCell sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          {a.level === 0 ? <Code sx={{ fontSize: 16, color: 'text.secondary' }} /> : <Apps sx={{ fontSize: 16, color: 'primary.main' }} />}
                          {a.id}
                        </Box>
                      </TableCell>
                      <TableCell sx={{ fontSize: 12 }}>{a.domain_id}</TableCell>
                      <TableCell>
                        <Chip
                          label={a.level === 0 ? 'L0 Библиотека' : `L${a.level} Приложение`}
                          size="small"
                          color={a.level === 0 ? 'default' : 'primary'}
                          variant={a.level === 0 ? 'outlined' : 'filled'}
                          sx={{ fontSize: 10, height: 20 }}
                        />
                      </TableCell>
                      <TableCell sx={{ fontSize: 12, color: 'text.secondary' }}>
                        {a.group_id || '—'}
                      </TableCell>
                      <TableCell sx={{ fontSize: 12 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <LinkIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                          <span style={{ fontFamily: 'monospace' }}>{a.repo_binding.repo_path}</span>
                          <span style={{ color: '#64748B', fontSize: 11 }}>({a.repo_binding.default_branch})</span>
                        </Box>
                      </TableCell>
                      <TableCell sx={{ fontSize: 12, fontFamily: 'monospace', color: 'text.secondary' }}>
                        {a.pipeline_plan_id || '—'}
                      </TableCell>
                      <TableCell align="right">
                        {onNavigateToIDE && (
                          <Tooltip title="Открыть в Web IDE">
                            <Button
                              size="small"
                              onClick={() => onNavigateToIDE({ repo: a.repo_binding.repo_path, file: 'scenarios/main.wire' })}
                              sx={{ textTransform: 'none', fontSize: 11, mr: 1 }}
                            >
                              IDE
                            </Button>
                          </Tooltip>
                        )}
                        <IconButton size="small" color="error" onClick={() => handleDeleteApp(a.id)}>
                          <Delete fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* Tab 1: Groups */}
        {tab === 1 && (
          <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, overflowX: 'auto' }}>
            <Table size="small">
              <TableHead sx={{ bgcolor: 'action.hover' }}>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>ID Группы</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Название</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Домен</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Родительская группа</TableCell>
                  <TableCell sx={{ fontWeight: 600 }} align="right">Действия</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  [1, 2].map((i) => (
                    <TableRow key={i}>
                      <TableCell><Skeleton width={100} /></TableCell>
                      <TableCell><Skeleton width={140} /></TableCell>
                      <TableCell><Skeleton width={80} /></TableCell>
                      <TableCell><Skeleton width={80} /></TableCell>
                      <TableCell align="right"><Skeleton width={40} sx={{ ml: 'auto' }} /></TableCell>
                    </TableRow>
                  ))
                ) : groups.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} sx={{ p: 0 }}>
                      <EmptyState
                        icon={<Folder sx={{ fontSize: 28 }} />}
                        title="Группы не созданы"
                        description="Создайте логические папки для группировки микросервисов."
                        actionLabel="Создать группу"
                        onAction={() => setOpenGroupDialog(true)}
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  groups.map((g) => (
                    <TableRow key={g.id} hover>
                      <TableCell sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Folder sx={{ fontSize: 16, color: 'warning.main' }} />
                          {g.id}
                        </Box>
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>{g.name}</TableCell>
                      <TableCell sx={{ fontSize: 12 }}>{g.domain_id}</TableCell>
                      <TableCell sx={{ fontSize: 12, color: 'text.secondary' }}>{g.parent_group_id || 'Корень'}</TableCell>
                      <TableCell align="right">
                        <IconButton size="small" color="error" onClick={() => handleDeleteGroup(g.id)}>
                          <Delete fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* Tab 2: Domains */}
        {tab === 2 && (
          <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, overflowX: 'auto' }}>
            <Table size="small">
              <TableHead sx={{ bgcolor: 'action.hover' }}>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>ID Домена</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Метка (Label)</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Forge URL</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Квоты (Runs/Storage/CPU)</TableCell>
                  <TableCell sx={{ fontWeight: 600 }} align="right">Действия</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  [1, 2].map((i) => (
                    <TableRow key={i}>
                      <TableCell><Skeleton width={100} /></TableCell>
                      <TableCell><Skeleton width={140} /></TableCell>
                      <TableCell><Skeleton width={160} /></TableCell>
                      <TableCell><Skeleton width={120} /></TableCell>
                      <TableCell align="right"><Skeleton width={40} sx={{ ml: 'auto' }} /></TableCell>
                    </TableRow>
                  ))
                ) : domains.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} sx={{ p: 0 }}>
                      <EmptyState
                        icon={<AccountTree sx={{ fontSize: 28 }} />}
                        title="Домены не найдены"
                        description="Зарегистрируйте КИТС или домен разработки."
                        actionLabel="Создать домен"
                        onAction={() => setOpenDomainDialog(true)}
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  domains.map((d) => (
                    <TableRow key={d.id} hover>
                      <TableCell sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <AccountTree sx={{ fontSize: 16, color: 'info.main' }} />
                          {d.id}
                        </Box>
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>{d.label}</TableCell>
                      <TableCell sx={{ fontSize: 12, fontFamily: 'monospace' }}>
                        {d.forge_binding.url} ({d.forge_binding.forge_type})
                      </TableCell>
                      <TableCell sx={{ fontSize: 12 }}>
                        {d.quota.max_runs} runs · {d.quota.max_storage_gb} GB · {d.quota.max_cpu} CPU
                      </TableCell>
                      <TableCell align="right">
                        <IconButton size="small" color="error" onClick={() => handleDeleteDomain(d.id)}>
                          <Delete fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {/* Modal: Create Application */}
        <Dialog open={openAppDialog} onClose={() => setOpenAppDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать новое приложение</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Приложения"
              placeholder="app-payments-api"
              value={appId}
              onChange={(e) => setAppId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Домен / КИТС"
              value={appDomainId}
              onChange={(e) => setAppDomainId(e.target.value)}
              fullWidth
              size="small"
            >
              {domains.map((d) => (
                <MenuItem key={d.id} value={d.id}>
                  {d.label} ({d.id})
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Уровень приложения"
              value={appLevel}
              onChange={(e) => setAppLevel(Number(e.target.value))}
              fullWidth
              size="small"
            >
              <MenuItem value={0}>Level 0 — Общая библиотека</MenuItem>
              <MenuItem value={1}>Level 1 — Микросервис / Приложение</MenuItem>
              <MenuItem value={2}>Level 2 — Подсистема</MenuItem>
              <MenuItem value={3}>Level 3 — Комплекс</MenuItem>
            </TextField>
            <TextField
              label="ID Группы (опционально)"
              placeholder="grp-core"
              value={appGroupId}
              onChange={(e) => setAppGroupId(e.target.value)}
              fullWidth
              size="small"
            />
            <TextField
              label="Путь к Git-репозиторию (owner/repo)"
              placeholder="org/payments-api"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Ветка по умолчанию"
              value={repoBranch}
              onChange={(e) => setRepoBranch(e.target.value)}
              fullWidth
              size="small"
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenAppDialog(false)}>Отмена</Button>
            <Button onClick={handleCreateApp} variant="contained" disabled={!appId || !appDomainId || !repoPath}>
              Создать
            </Button>
          </DialogActions>
        </Dialog>

        {/* Modal: Create Group */}
        <Dialog open={openGroupDialog} onClose={() => setOpenGroupDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать группу приложений</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Группы"
              placeholder="grp-billing"
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Название группы"
              placeholder="Биллинг и расчеты"
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Домен"
              value={groupDomainId}
              onChange={(e) => setGroupDomainId(e.target.value)}
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
            <Button onClick={() => setOpenGroupDialog(false)}>Отмена</Button>
            <Button onClick={handleCreateGroup} variant="contained" disabled={!groupId || !groupName}>
              Создать
            </Button>
          </DialogActions>
        </Dialog>

        {/* Modal: Create Domain */}
        <Dialog open={openDomainDialog} onClose={() => setOpenDomainDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Зарегистрировать новый Домен</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Домена"
              placeholder="dom-cbr"
              value={domId}
              onChange={(e) => setDomId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Человекочитаемое имя (Label)"
              placeholder="Цифровой рубль"
              value={domLabel}
              onChange={(e) => setDomLabel(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Forge URL"
              value={domForgeUrl}
              onChange={(e) => setDomForgeUrl(e.target.value)}
              fullWidth
              size="small"
            />
            <TextField
              label="Ссылка на токен (Secret Reference)"
              value={domTokenRef}
              onChange={(e) => setDomTokenRef(e.target.value)}
              fullWidth
              size="small"
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenDomainDialog(false)}>Отмена</Button>
            <Button onClick={handleCreateDomain} variant="contained" disabled={!domId || !domLabel}>
              Создать
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
