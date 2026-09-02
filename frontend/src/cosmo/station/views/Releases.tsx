/**
 * COS-029 / COS-047 / COS-098: Release Management View.
 *
 * COS-098 (контракт-первым): рендер и create-пейлоад приведены к бэкенду
 * (release_model.Release + CreateReleaseRequest). Старые выдуманные поля
 * (name / manifest.nodes / zone 'ЗР') удалены — вместо них честные
 * version / artifacts / run_ids / approvals / transfer_history.
 * Трансфер по зонам: ЗР → ЗТ → ЗПЭ (ReleaseTransferWizard, COS-090).
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
  Download, CheckCircle, Shield, Gavel,
} from '@mui/icons-material';
import {
  api, type Release, type ReleaseZone, type ReleaseStatus,
  type CosmoDomain, type CreateReleaseRequest, type ReleaseTrigger,
} from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';
import { ReleaseTransferWizard, ZONE_LABELS } from './ReleaseTransferWizard';

const STATUS_LABELS: Record<ReleaseStatus, string> = {
  draft: 'Черновик',
  pending_review: 'На review',
  approved: 'Утверждён',
  rejected: 'Отклонён',
  deploying: 'Деплоится',
  deployed: 'Задеплоен',
  rollback: 'Откат',
};

interface ReleasesProps {
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function Releases({ onNavigateToIDE }: ReleasesProps) {
  const [releases, setReleases] = useState<Release[]>([]);
  const [domains, setDomains] = useState<CosmoDomain[]>([]);
  const [selectedRelease, setSelectedRelease] = useState<Release | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // COS-090: Release Transfer Wizard
  const [wizardOpen, setWizardOpen] = useState(false);

  // Create Release Dialog — честный CreateReleaseRequest
  const [openCreateModal, setOpenCreateModal] = useState(false);
  const [form, setForm] = useState<CreateReleaseRequest>({
    id: '', domain_id: '', plan_id: '', run_ids: [], trigger: 'manual',
    changelog: '', version: '',
  });

  const fetchReleases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [remoteReleases, domainList] = await Promise.all([
        api.getReleases(),
        api.getDomains().catch(() => [] as CosmoDomain[]),
      ]);
      setReleases(remoteReleases || []);
      setDomains(domainList || []);
      if (remoteReleases && remoteReleases.length > 0) {
        setSelectedRelease((prev) => (prev && remoteReleases.some((r) => r.id === prev.id) ? prev : remoteReleases[0]));
      } else {
        setSelectedRelease(null);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки релизов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReleases();
  }, [fetchReleases]);

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
    const payload: CreateReleaseRequest = {
      ...form,
      run_ids: form.run_ids.filter((r) => r.trim().length > 0),
    };
    if (!payload.id.trim() || !payload.domain_id || !payload.plan_id.trim() || payload.run_ids.length === 0) return;

    try {
      const created = await api.createRelease(payload);
      setReleases((prev) => [created, ...prev]);
      setSelectedRelease(created);
      setOpenCreateModal(false);
      setForm({ id: '', domain_id: '', plan_id: '', run_ids: [], trigger: 'manual', changelog: '', version: '' });
      toast.success(`Релиз ${created.id} (${created.version || 'без версии'}) создан`);
    } catch (err) {
      // Честная ошибка бэкенда — никаких offline fallback
      const msg = err instanceof Error ? err.message : 'Ошибка создания релиза';
      toast.error(msg);
    }
  };

  const handleExportRelease = (release: Release) => {
    const jsonStr = JSON.stringify(release, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `release-${release.id}-${release.version || 'unversioned'}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast.info('Релиз скачан в JSON');
  };

  const getZoneChip = (zone: ReleaseZone) => {
    const color = zone === 'zr' ? 'primary' : zone === 'zt' ? 'warning' : 'success';
    return <Chip label={ZONE_LABELS[zone] ?? zone} size="small" color={color} variant="outlined" sx={{ fontWeight: 700, fontSize: 11 }} />;
  };

  const getNextZone = (zone: ReleaseZone): ReleaseZone | null =>
    zone === 'zr' ? 'zt' : zone === 'zt' ? 'zpe' : null;

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
              Релизные пакеты: прогон-связки с approvals и артефактами, трансфер по зонам (ЗР → ЗТ → ЗПЭ).
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchReleases} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
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
                          <Typography variant="subtitle2" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                            {rel.id}
                          </Typography>
                          {getZoneChip(rel.current_zone)}
                        </Box>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                          <Chip label={rel.version || '—'} size="small" sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 11 }} />
                          <Chip label={STATUS_LABELS[rel.status] ?? rel.status} size="small" sx={{ fontSize: 11 }} />
                        </Box>
                        <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 0.5 }}>
                          Домен: <strong>{rel.domain_id}</strong> · Прогонов: {rel.run_ids.length} · Артефактов: {rel.artifacts.length}
                        </Typography>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </Box>
          </Grid>

          {/* Right: Release Detail */}
          <Grid size={{ xs: 12, md: 7 }}>
            {selectedRelease ? (
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  {/* Header */}
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        {selectedRelease.id}
                      </Typography>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                        <Chip label={selectedRelease.version || '—'} size="small" color="primary" sx={{ fontWeight: 700 }} />
                        <Chip label={STATUS_LABELS[selectedRelease.status] ?? selectedRelease.status} size="small" sx={{ fontWeight: 700 }} />
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<Download />}
                        onClick={() => handleExportRelease(selectedRelease)}
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
                          Контур безопасности: {ZONE_LABELS[selectedRelease.current_zone]}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {selectedRelease.current_zone === 'zr' && 'Релиз сформирован в зоне разработки. Трансфер возможен после деплоя (status: deployed).'}
                          {selectedRelease.current_zone === 'zt' && 'Релиз проходит аудит и валидацию политик Security Gates в Зоне Тестирования.'}
                          {selectedRelease.current_zone === 'zpe' && 'Релиз находится в Промышленной Эксплуатации (Пром).'}
                        </Typography>
                      </Box>

                      {getNextZone(selectedRelease.current_zone) ? (
                        <Tooltip title={selectedRelease.status === 'deployed' ? '' : 'Трансфер разрешён только из статуса deployed (release_model.can_transfer)'}>
                          <span>
                            <Button
                              variant="contained"
                              color={selectedRelease.current_zone === 'zr' ? 'warning' : 'success'}
                              size="small"
                              endIcon={<ArrowForward />}
                              onClick={handleOpenTransferWizard}
                              disabled={selectedRelease.status !== 'deployed'}
                              sx={{ textTransform: 'none', fontWeight: 600 }}
                            >
                              Трансфер: {selectedRelease.current_zone.toUpperCase()} → {getNextZone(selectedRelease.current_zone)!.toUpperCase()}
                            </Button>
                          </span>
                        </Tooltip>
                      ) : (
                        <Chip icon={<CheckCircle />} label="В промышленной эксплуатации" color="success" sx={{ fontWeight: 600 }} />
                      )}
                    </Box>
                  </Box>

                  {/* Runs */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                    Прогоны в релизе ({selectedRelease.run_ids.length})
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mb: 3 }}>
                    {selectedRelease.run_ids.length === 0 ? (
                      <Typography variant="caption" color="text.secondary">Прогонов нет</Typography>
                    ) : (
                      selectedRelease.run_ids.map((rid) => (
                        <Chip key={rid} label={rid} size="small" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: 10 }} />
                      ))
                    )}
                  </Box>

                  {/* Artifacts */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                    Артефакты ({selectedRelease.artifacts.length})
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 3 }}>
                    {selectedRelease.artifacts.length === 0 ? (
                      <Typography variant="caption" color="text.secondary">
                        Артефакты (SBOM, SARIF, image digests) не привязаны.
                      </Typography>
                    ) : (
                      selectedRelease.artifacts.map((a, idx) => (
                        <Typography key={idx} variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', wordBreak: 'break-all' }}>
                          {a}
                        </Typography>
                      ))
                    )}
                  </Box>

                  {/* Approvals */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                    <Gavel sx={{ fontSize: 14, mr: 0.5, verticalAlign: 'text-bottom' }} />
                    Решения по релизу ({selectedRelease.approvals.length})
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 3 }}>
                    {selectedRelease.approvals.length === 0 ? (
                      <Typography variant="caption" color="text.secondary">Решений пока нет.</Typography>
                    ) : (
                      selectedRelease.approvals.map((ap, idx) => (
                        <Box key={idx} sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 1.5, bgcolor: 'action.hover' }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Chip label={ap.decision === 'approved' ? 'Утверждён' : 'Отклонён'} size="small" color={ap.decision === 'approved' ? 'success' : 'error'} sx={{ fontWeight: 700, fontSize: 10 }} />
                            <Typography variant="caption" color="text.secondary">{new Date(ap.decided_at).toLocaleString()}</Typography>
                          </Box>
                          <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary' }}>
                            Оператор: <strong>{ap.decided_by}</strong>{ap.comment ? ` · ${ap.comment}` : ''}
                          </Typography>
                          {ap.signature && (
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', mt: 0.5, wordBreak: 'break-all' }}>
                              Подпись: {ap.signature}
                            </Typography>
                          )}
                        </Box>
                      ))
                    )}
                  </Box>

                  {/* Transfer History */}
                  {selectedRelease.transfer_history.length > 0 && (
                    <>
                      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                        История трансферов по зонам безопасности
                      </Typography>
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2 }}>
                        {selectedRelease.transfer_history.map((h, idx) => (
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
                                {ZONE_LABELS[h.from_zone]} → {ZONE_LABELS[h.to_zone]}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {new Date(h.transferred_at).toLocaleString()}
                              </Typography>
                            </Box>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                              Оператор: <strong>{h.initiated_by}</strong> · Gates: {h.gate_check_passed ? 'пройдены' : 'не пройдены'}
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
                            Релиз в репозитории
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

        {/* Create Release Modal — честный CreateReleaseRequest */}
        <Dialog open={openCreateModal} onClose={() => setOpenCreateModal(false)} maxWidth="md" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать релизный пакет</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Релиза"
              placeholder="rel-cbr-v3.0.0"
              value={form.id}
              onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Домен"
              select
              value={form.domain_id}
              onChange={(e) => setForm((f) => ({ ...f, domain_id: e.target.value }))}
              fullWidth
              size="small"
              required
            >
              {domains.length === 0 && <MenuItem value="">— домены не загружены —</MenuItem>}
              {domains.map((d) => (
                <MenuItem key={d.id} value={d.id}>
                  {d.label || d.id}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="ID плана (plan_id)"
              placeholder="plan-..."
              value={form.plan_id}
              onChange={(e) => setForm((f) => ({ ...f, plan_id: e.target.value }))}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="ID прогонов (через запятую, минимум 1)"
              placeholder="run-..., run-..."
              value={form.run_ids.join(', ')}
              onChange={(e) => setForm((f) => ({ ...f, run_ids: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) }))}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Версия (SemVer)"
              placeholder="v3.0.0"
              value={form.version}
              onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))}
              fullWidth
              size="small"
            />
            <TextField
              select
              label="Триггер"
              value={form.trigger}
              onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value as ReleaseTrigger }))}
              fullWidth
              size="small"
            >
              <MenuItem value="manual">manual</MenuItem>
              <MenuItem value="pre_release">pre_release</MenuItem>
              <MenuItem value="scheduled">scheduled</MenuItem>
              <MenuItem value="emergency">emergency</MenuItem>
            </TextField>
            <TextField
              label="Changelog"
              placeholder="Описание изменений"
              value={form.changelog}
              onChange={(e) => setForm((f) => ({ ...f, changelog: e.target.value }))}
              fullWidth
              size="small"
              multiline
              rows={2}
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCreateModal(false)}>Отмена</Button>
            <Button
              onClick={handleCreateRelease}
              variant="contained"
              disabled={!form.id.trim() || !form.domain_id || !form.plan_id.trim() || form.run_ids.length === 0}
            >
              Создать релиз
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </ErrorBoundary>
  );
}
