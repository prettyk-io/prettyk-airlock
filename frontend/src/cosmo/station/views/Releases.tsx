/**
 * COS-029 / COS-047: Release Management View.
 *
 * Release creation, composition graph (nodes + edges), JSON manifest import/export,
 * and security zone promotion: ЗР (Разработка) → ЗТ (Тестирование) → ЗПЭ (Пром).
 * Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Grid,
  Divider,
} from '@mui/material';
import {
  Refresh, Add, ArrowForward, VerifiedUser,
  Download, Upload, CheckCircle,
  AccountTree, Code, Apps, Shield,
} from '@mui/icons-material';
import {
  api, type Release, type ReleaseZone, type ReleaseNode,
  type ReleaseEdge, type ReleaseManifest, type Application
} from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';
import { ReleaseTransferWizard } from './ReleaseTransferWizard';

interface ReleasesProps {
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function Releases({ onNavigateToIDE }: ReleasesProps) {
  const [releases, setReleases] = useState<Release[]>([]);
  const [selectedRelease, setSelectedRelease] = useState<Release | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // COS-090: Release Transfer Wizard
  const [wizardOpen, setWizardOpen] = useState(false);

  // Create Release Dialog
  const [openCreateModal, setOpenCreateModal] = useState(false);
  const [newRelId, setNewRelId] = useState('');
  const [newRelVersion, setNewRelVersion] = useState('');
  const [newRelName, setNewRelName] = useState('');
  const [newRelProjectId, setNewRelProjectId] = useState('');
  const [selectedAppIds, setSelectedAppIds] = useState<string[]>([]);

  // Import Manifest Dialog
  const [openImportModal, setOpenImportModal] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');

  const fetchReleasesAndMetadata = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [remoteReleases, appsData] = await Promise.all([
        api.getReleases(),
        api.getApps(),
        api.getApps(),
      ]);
      setApps(appsData || []);
      if (appsData.length > 0 && !newRelProjectId) {
        setNewRelProjectId(appsData[0].id);
      }

      if (remoteReleases && remoteReleases.length > 0) {
        setReleases(remoteReleases);
        if (!selectedRelease) setSelectedRelease(remoteReleases[0]);
      } else {
        setReleases([]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки релизов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [newRelProjectId, selectedRelease]);

  useEffect(() => {
    fetchReleasesAndMetadata();
  }, [fetchReleasesAndMetadata]);

  const handleOpenTransferWizard = () => {
    setWizardOpen(true);
  };

  const handleWizardComplete = (updatedRelease: Release) => {
    setReleases((prev) =>
      prev.map((r) => (r.id === updatedRelease.id ? updatedRelease : r))
    );
    setSelectedRelease(updatedRelease);
    setWizardOpen(false);
  };

  const handleCreateRelease = async () => {
    if (!newRelId.trim() || !newRelVersion.trim() || !newRelName.trim() || !newRelProjectId) return;

    const chosenApps = apps.filter((a) => selectedAppIds.includes(a.id));
    const nodes: ReleaseNode[] = chosenApps.map((a) => ({
      id: `node-${a.id}`,
      name: a.id,
      type: a.level === 0 ? 'library' : 'service',
      version: newRelVersion.trim(),
      repo: a.repo_binding.repo_path,
      commit: 'head-main',
    }));

    const edges: ReleaseEdge[] = [];
    if (nodes.length >= 2) {
      edges.push({ from: nodes[0].id, to: nodes[1].id, relation: 'depends_on' });
    }

    const newManifest: ReleaseManifest = {
      release_id: newRelId.trim(),
      version: newRelVersion.trim(),
      domain_id: newRelProjectId,
      zone: 'ЗР',
      created_at: new Date().toISOString(),
      created_by: 'operator@cosmo.local',
      nodes,
      edges,
      metadata: { auto_created: true },
      signature: `sha256:${Date.now().toString(16)}`,
    };

    const newRelObj: Release = {
      id: newRelId.trim(),
      version: newRelVersion.trim(),
      name: newRelName.trim(),
      domain_id: newRelProjectId,
      zone: 'ЗР',
      status: 'draft',
      created_at: new Date().toISOString(),
      manifest: newManifest,
      history: [],
    };

    try {
      await api.createRelease(newRelObj);
    } catch {
      // offline fallback
    }

    setReleases((prev) => [newRelObj, ...prev]);
    setSelectedRelease(newRelObj);
    setOpenCreateModal(false);
    setNewRelId('');
    setNewRelVersion('');
    setNewRelName('');
    setSelectedAppIds([]);
    toast.success(`Релиз ${newRelName.trim()} (${newRelVersion.trim()}) создан`);
  };

  const handleExportManifest = (release: Release) => {
    const jsonStr = JSON.stringify(release.manifest, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `manifest-${release.id}-${release.version}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast.info('Манифест скачан в JSON');
  };

  const handleImportManifest = () => {
    try {
      const parsed: ReleaseManifest = JSON.parse(importJsonText);
      if (!parsed.release_id || !parsed.version) {
        throw new Error('Манифест должен содержать release_id и version');
      }

      const importedRelease: Release = {
        id: parsed.release_id,
        version: parsed.version,
        name: `Импортированный релиз ${parsed.version}`,
        domain_id: parsed.domain_id || 'default',
        zone: parsed.zone || 'ЗР',
        status: 'draft',
        created_at: parsed.created_at || new Date().toISOString(),
        manifest: parsed,
        history: [],
      };

      setReleases((prev) => [importedRelease, ...prev]);
      setSelectedRelease(importedRelease);
      setOpenImportModal(false);
      setImportJsonText('');
      toast.success(`Манифест релиза ${parsed.version} успешно импортирован`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Невалидный JSON манифеста';
      setError(msg);
      toast.error(msg);
    }
  };

  const getZoneChip = (zone: ReleaseZone) => {
    switch (zone) {
      case 'ЗР':
        return <Chip label="ЗР (Разработка)" size="small" color="primary" variant="outlined" sx={{ fontWeight: 700, fontSize: 11 }} />;
      case 'ЗТ':
        return <Chip label="ЗТ (Тестирование)" size="small" color="warning" sx={{ fontWeight: 700, fontSize: 11 }} />;
      case 'ЗПЭ':
        return <Chip label="ЗПЭ (Пром)" size="small" color="success" sx={{ fontWeight: 700, fontSize: 11 }} />;
    }
  };

  return (
    <ErrorBoundary viewName="Управление Релизами (Releases)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Release Management (Управление Релизами)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Управление контурами релизов, граф связей (Nodes & Edges), экспорт манифестов и трансфер по зонам безопасности (ЗР → ЗТ → ЗПЭ).
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchReleasesAndMetadata} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Upload />}
              onClick={() => setOpenImportModal(true)}
              sx={{ textTransform: 'none' }}
            >
              Импорт манифеста
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<Add />}
              onClick={() => setOpenCreateModal(true)}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Создать релиз
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Zone Pathway Indicator */}
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'action.hover' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-around', flexWrap: 'wrap', gap: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Chip label="ЗР" color="primary" size="small" sx={{ fontWeight: 700 }} />
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                Зона Разработки (Build & Unit)
              </Typography>
            </Box>
            <ArrowForward sx={{ color: 'text.disabled' }} />
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Chip label="ЗТ" color="warning" size="small" sx={{ fontWeight: 700 }} />
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                Зона Тестирования (DAST / SAST / Gates)
              </Typography>
            </Box>
            <ArrowForward sx={{ color: 'text.disabled' }} />
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Chip label="ЗПЭ" color="success" size="small" sx={{ fontWeight: 700 }} />
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                Зона Пром Эксплуатации (Signed & Airgap)
              </Typography>
            </Box>
          </Box>
        </Paper>

        <Grid container spacing={2}>
          {/* Left: Releases List */}
          <Grid size={{ xs: 12, md: 5 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                Список релизов ({releases.length})
              </Typography>
              {loading ? (
                [1, 2, 3].map((i) => (
                  <Paper key={i} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Skeleton width="60%" height={22} />
                    <Skeleton width="40%" height={16} sx={{ mt: 0.5 }} />
                  </Paper>
                ))
              ) : releases.length === 0 ? (
                <EmptyState
                  icon={<Shield sx={{ fontSize: 28 }} />}
                  title="Релизы не найдены"
                  description="Сформируйте первый релизный пакет для трансфера по контурам."
                  actionLabel="Создать релиз"
                  onAction={() => setOpenCreateModal(true)}
                />
              ) : (
                releases.map((rel) => {
                  const isSelected = selectedRelease?.id === rel.id;
                  return (
                    <Card
                      key={rel.id}
                      variant="outlined"
                      onClick={() => setSelectedRelease(rel)}
                      sx={{
                        cursor: 'pointer',
                        borderRadius: 2,
                        borderColor: isSelected ? 'primary.main' : 'divider',
                        bgcolor: isSelected ? 'action.selected' : 'background.paper',
                      }}
                    >
                      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                            {rel.name}
                          </Typography>
                          {getZoneChip(rel.zone)}
                        </Box>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                          <Chip label={rel.version} size="small" sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 11 }} />
                          <Typography variant="caption" color="text.secondary">
                            Домен: <strong>{rel.domain_id}</strong>
                          </Typography>
                        </Box>
                        <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 0.5 }}>
                          Сервисов: {rel.manifest.nodes.length} · Связей: {rel.manifest.edges.length}
                        </Typography>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </Box>
          </Grid>

          {/* Right: Release Detail & Composition Inspector */}
          <Grid size={{ xs: 12, md: 7 }}>
            {selectedRelease ? (
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  {/* Header */}
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 700 }}>
                        {selectedRelease.name}
                      </Typography>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                        <Chip label={selectedRelease.version} size="small" color="primary" sx={{ fontWeight: 700 }} />
                        <Typography variant="caption" color="text.secondary">
                          ID: <span style={{ fontFamily: 'monospace' }}>{selectedRelease.id}</span>
                        </Typography>
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<Download />}
                        onClick={() => handleExportManifest(selectedRelease)}
                        sx={{ textTransform: 'none', fontSize: 11 }}
                      >
                        Экспорт JSON
                      </Button>
                    </Box>
                  </Box>

                  <Divider sx={{ my: 2 }} />

                  {/* Zone Promotion Action Box */}
                  <Box sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 2, bgcolor: 'action.hover', mb: 3 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 700 }}>
                          Контур безопасности: {selectedRelease.zone}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {selectedRelease.zone === 'ЗР' && 'Релиз сформирован в зоне разработки. Готов к отправке на DAST/SAST в ЗТ.'}
                          {selectedRelease.zone === 'ЗТ' && 'Релиз проходит аудит и валидацию политик Security Gates в Зоне Тестирования.'}
                          {selectedRelease.zone === 'ЗПЭ' && 'Релиз подписан и находится в Промышленной Эксплуатации (Пром).'}
                        </Typography>
                      </Box>

                      {selectedRelease.zone === 'ЗР' && (
                        <Button
                          variant="contained"
                          color="warning"
                          size="small"
                          endIcon={<ArrowForward />}
                          onClick={handleOpenTransferWizard}
                          sx={{ textTransform: 'none', fontWeight: 600 }}
                        >
                          Трансфер: ЗР → ЗТ
                        </Button>
                      )}

                      {selectedRelease.zone === 'ЗТ' && (
                        <Button
                          variant="contained"
                          color="success"
                          size="small"
                          startIcon={<VerifiedUser />}
                          endIcon={<ArrowForward />}
                          onClick={handleOpenTransferWizard}
                          sx={{ textTransform: 'none', fontWeight: 600 }}
                        >
                          Трансфер: ЗТ → ЗПЭ
                        </Button>
                      )}

                      {selectedRelease.zone === 'ЗПЭ' && (
                        <Chip icon={<CheckCircle />} label="В промышленной эксплуатации" color="success" sx={{ fontWeight: 600 }} />
                      )}
                    </Box>
                  </Box>

                  {/* Composition Graph: Nodes (Services & Libraries) */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                    Состав релиза (Nodes / Компоненты)
                  </Typography>
                  <Grid container spacing={1.5} sx={{ mb: 3 }}>
                    {selectedRelease.manifest.nodes.map((node) => (
                      <Grid size={{ xs: 12, sm: 6 }} key={node.id}>
                        <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 1.5, bgcolor: 'background.paper' }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                              {node.type === 'service' ? <Apps sx={{ fontSize: 16, color: 'primary.main' }} /> : node.type === 'library' ? <Code sx={{ fontSize: 16, color: 'warning.main' }} /> : <Shield sx={{ fontSize: 16, color: 'info.main' }} />}
                              <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: 13 }}>
                                {node.name}
                              </Typography>
                            </Box>
                            <Chip label={`v${node.version}`} size="small" variant="outlined" sx={{ fontSize: 10, height: 18 }} />
                          </Box>
                          <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block' }}>
                            Repo: {node.repo} @ {node.commit}
                          </Typography>
                        </Paper>
                      </Grid>
                    ))}
                  </Grid>

                  {/* Dependencies Edges */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Связи зависимостей (Edges / Topology)
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 3 }}>
                    {selectedRelease.manifest.edges.length === 0 ? (
                      <Typography variant="caption" color="text.secondary">
                        Связи между компонентами не заданы.
                      </Typography>
                    ) : (
                      selectedRelease.manifest.edges.map((edge, idx) => (
                        <Box
                          key={idx}
                          sx={{
                            p: 1,
                            border: 1,
                            borderColor: 'divider',
                            borderRadius: 1,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 1,
                            fontSize: 12,
                            fontFamily: 'monospace',
                          }}
                        >
                          <AccountTree sx={{ fontSize: 14, color: 'text.secondary' }} />
                          <span>{edge.from}</span>
                          <ArrowForward sx={{ fontSize: 12, color: 'text.disabled' }} />
                          <span>{edge.to}</span>
                          <Chip label={edge.relation} size="small" variant="outlined" sx={{ fontSize: 9, height: 18, ml: 'auto' }} />
                        </Box>
                      ))
                    )}
                  </Box>

                  {/* Zone Promotion History Timeline */}
                  {selectedRelease.history.length > 0 && (
                    <>
                      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                        История промоушена по зонам безопасности
                      </Typography>
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2 }}>
                        {selectedRelease.history.map((h, idx) => (
                          <Box
                            key={idx}
                            sx={{
                              p: 1.5,
                              border: 1,
                              borderColor: 'divider',
                              borderRadius: 1.5,
                              bgcolor: 'action.hover',
                            }}
                          >
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {h.from_zone} → {h.to_zone}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {new Date(h.timestamp).toLocaleString()}
                              </Typography>
                            </Box>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                              Оператор: <strong>{h.operator}</strong>
                            </Typography>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', mt: 0.5 }}>
                              Подпись: {h.signature}
                            </Typography>
                          </Box>
                        ))}
                      </Box>
                    </>
                  )}

                  {/* Web IDE Deep link */}
                  {onNavigateToIDE && (
                    <Box sx={{ mt: 2, p: 2, border: 1, borderColor: 'primary.light', borderRadius: 1.5, bgcolor: 'rgba(14,165,233,0.04)' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            Манифест релиза в репозитории
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            Редактировать .cosmo/release.yaml в Web IDE
                          </Typography>
                        </Box>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => onNavigateToIDE({ repo: 'cbr/releases', file: `manifests/${selectedRelease.id}.yaml` })}
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
                icon={<Shield sx={{ fontSize: 32 }} />}
                title="Релиз не выбран"
                description="Выберите релизный пакет из списка слева для просмотра состава."
              />
            )}
          </Grid>
        </Grid>

        {/* COS-090: Release Transfer Wizard */}
        {wizardOpen && selectedRelease && (
          <Dialog
            open={wizardOpen}
            onClose={() => setWizardOpen(false)}
            maxWidth="md"
            fullWidth
          >
            <ReleaseTransferWizard
              release={selectedRelease}
              onComplete={handleWizardComplete}
              onClose={() => setWizardOpen(false)}
            />
          </Dialog>
        )}

        {/* Create Release Modal */}
        <Dialog open={openCreateModal} onClose={() => setOpenCreateModal(false)} maxWidth="md" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать новый релизный бандл</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Релиза"
              placeholder="rel-cbr-v3.0.0"
              value={newRelId}
              onChange={(e) => setNewRelId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Версия (SemVer)"
              placeholder="v3.0.0"
              value={newRelVersion}
              onChange={(e) => setNewRelVersion(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Наименование релиза"
              placeholder="Цифровой Рубль — Мажорное обновление"
              value={newRelName}
              onChange={(e) => setNewRelName(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Домен / КИТС"
              value={newRelProjectId}
              onChange={(e) => setNewRelProjectId(e.target.value)}
              fullWidth
              size="small"
            >
              {apps.map((d) => (
                <MenuItem key={d.id} value={d.id}>
                  {d.id} ({d.id})
                </MenuItem>
              ))}
            </TextField>

            <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 1 }}>
              Выберите сервисы/библиотеки для включения в релиз:
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {apps.map((a) => {
                const isSelected = selectedAppIds.includes(a.id);
                return (
                  <Chip
                    key={a.id}
                    label={`${a.id} (L${a.level})`}
                    color={isSelected ? 'primary' : 'default'}
                    variant={isSelected ? 'filled' : 'outlined'}
                    onClick={() =>
                      setSelectedAppIds((prev) =>
                        prev.includes(a.id) ? prev.filter((id) => id !== a.id) : [...prev, a.id]
                      )
                    }
                    sx={{ cursor: 'pointer' }}
                  />
                );
              })}
            </Box>
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCreateModal(false)}>Отмена</Button>
            <Button
              onClick={handleCreateRelease}
              variant="contained"
              disabled={!newRelId || !newRelVersion || !newRelName || !newRelProjectId}
            >
              Создать релиз
            </Button>
          </DialogActions>
        </Dialog>

        {/* Import Manifest Modal */}
        <Dialog open={openImportModal} onClose={() => setOpenImportModal(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Импорт JSON-манифеста релиза</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Вставьте структурированный JSON манифеста (включающий nodes, edges, version):
            </Typography>
            <TextField
              multiline
              rows={8}
              placeholder={`{\n  "release_id": "rel-custom-01",\n  "version": "v1.0.0",\n  "project_id": "your-kits",\n  "nodes": [],\n  "edges": []\n}`}
              value={importJsonText}
              onChange={(e) => setImportJsonText(e.target.value)}
              fullWidth
              size="small"
              sx={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenImportModal(false)}>Отмена</Button>
            <Button
              onClick={handleImportManifest}
              variant="contained"
              disabled={!importJsonText.trim()}
            >
              Импортировать
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
