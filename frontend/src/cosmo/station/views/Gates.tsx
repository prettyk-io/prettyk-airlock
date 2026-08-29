/**
 * COS-022 / COS-047 / COS-064: Control Station Security Gates View.
 *
 * Gate Decision Inspector: policies, findings, decision status, approve/reject/manual decision modals.
 * COS-064: Bulk Actions — multi-select pending manual gates, batch Pass / Block with signature modal.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton, CircularProgress,
  Alert, IconButton, Tooltip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Card, CardContent, Grid,
  Divider, Checkbox, Slide, Badge,
} from '@mui/material';
import {
  Gavel, Refresh, Add, CheckCircle, Block,
  HourglassEmpty, OpenInNew, VerifiedUser, Settings,
} from '@mui/icons-material';
import { api, type Gate, type GatePolicyRule } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

interface GatesProps {
  selectedPlanId?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
  onNavigateToPolicyBuilder?: () => void;
}

export function Gates({ selectedPlanId, onNavigateToIDE, onNavigateToPolicyBuilder }: GatesProps) {
  const [gates, setGates] = useState<Gate[]>([]);
  const [selectedGate, setSelectedGate] = useState<Gate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // COS-064: Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkSubmitting, setBulkSubmitting] = useState(false);

  // Decision Modal (single)
  const [openDecisionModal, setOpenDecisionModal] = useState(false);
  const [decisionType, setDecisionType] = useState<'pass' | 'block'>('pass');
  const [decidedBy, setDecidedBy] = useState('secops-operator@cosmo.local');
  const [decisionSignature, setDecisionSignature] = useState('');
  const [submittingDecision, setSubmittingDecision] = useState(false);

  // COS-064: Bulk Decision Modal
  const [openBulkDecisionModal, setOpenBulkDecisionModal] = useState(false);
  const [bulkDecisionType, setBulkDecisionType] = useState<'pass' | 'block'>('pass');
  const [bulkDecidedBy, setBulkDecidedBy] = useState('secops-operator@cosmo.local');
  const [bulkSignature, setBulkSignature] = useState('');
  const [bulkSubmittingDecision, setBulkSubmittingDecision] = useState(false);

  // Create Gate Modal
  const [openCreateModal, setOpenCreateModal] = useState(false);
  const [newGateId, setNewGateId] = useState('');
  const [newGatePlanId, setNewGatePlanId] = useState(selectedPlanId || 'plan-default');
  const [newGateType, setNewGateType] = useState<'automatic' | 'manual'>('automatic');
  const [newGatePosition, setNewGatePosition] = useState(0);
  const [rules, setRules] = useState<GatePolicyRule[]>([
    { finding_type: 'Critical', action: 'block', max_count: 0 },
    { finding_type: 'High', action: 'warn', max_count: 3 },
  ]);

  const fetchGates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getGates(selectedPlanId);
      setGates(data || []);
      if (data && data.length > 0 && !selectedGate) {
        setSelectedGate(data[0]);
      }
      setSelectedIds(new Set());
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки гейтов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedPlanId, selectedGate]);

  useEffect(() => {
    fetchGates();
  }, [fetchGates]);

  // ── Single Gate Decision ──────────────────────────────────────────

  const handleOpenDecision = (type: 'pass' | 'block') => {
    setDecisionType(type);
    setDecisionSignature(`sig-sha256-${Date.now().toString(16)}`);
    setOpenDecisionModal(true);
  };

  const handleSubmitDecision = async () => {
    if (!selectedGate || !decidedBy.trim()) return;
    setSubmittingDecision(true);
    try {
      const updated = await api.submitGateDecision(selectedGate.id, {
        decision: decisionType,
        decided_by: decidedBy.trim(),
        signature: decisionSignature.trim() || undefined,
      });
      setSelectedGate(updated);
      setOpenDecisionModal(false);
      toast.success(`Вердикт «${decisionType.toUpperCase()}» зафиксирован в Decision Ledger`);
      await fetchGates();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка сохранения решения';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmittingDecision(false);
    }
  };

  // ── COS-064: Bulk Gate Decision ────────────────────────────────────

  const pendingManualGates = gates.filter(
    (g) => g.type === 'manual' && (!g.decision || g.decision === 'manual_required')
  );

  const handleToggleSelect = (gateId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(gateId)) {
        next.delete(gateId);
      } else {
        next.add(gateId);
      }
      return next;
    });
  };

  const handleToggleAllPending = () => {
    const pendingIds = pendingManualGates.map((g) => g.id);
    const allSelected = pendingIds.every((id) => selectedIds.has(id));
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(pendingIds));
    }
  };

  const handleOpenBulkDecision = (type: 'pass' | 'block') => {
    setBulkDecisionType(type);
    setBulkSignature(`sig-sha256-bulk-${Date.now().toString(16)}`);
    setOpenBulkDecisionModal(true);
  };

  const handleSubmitBulkDecision = async () => {
    if (selectedIds.size === 0 || !bulkDecidedBy.trim()) return;
    setBulkSubmittingDecision(true);
    const ids = Array.from(selectedIds);
    let succeeded = 0;
    let failed = 0;

    for (const gateId of ids) {
      try {
        await api.submitGateDecision(gateId, {
          decision: bulkDecisionType,
          decided_by: bulkDecidedBy.trim(),
          signature: bulkSignature.trim() || `sig-bulk-${Date.now()}`,
        });
        succeeded++;
      } catch {
        failed++;
      }
    }

    if (succeeded > 0) {
      toast.success(`Пакетный вердикт «${bulkDecisionType.toUpperCase()}» применён к ${succeeded} гейтам`);
    }
    if (failed > 0) {
      toast.error(`Не удалось обработать ${failed} гейтов из ${ids.length}`);
    }

    setBulkSubmittingDecision(false);
    setOpenBulkDecisionModal(false);
    setSelectedIds(new Set());
    await fetchGates();
  };

  // ── Create Gate ────────────────────────────────────────────────────

  const handleCreateGate = async () => {
    if (!newGateId.trim() || !newGatePlanId.trim()) return;
    try {
      await api.createGate({
        id: newGateId.trim(),
        plan_id: newGatePlanId.trim(),
        type: newGateType,
        position: newGatePosition,
        policy: { rules },
      });
      toast.success(`Security Gate ${newGateId.trim()} создан`);
      setOpenCreateModal(false);
      setNewGateId('');
      await fetchGates();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка создания гейта';
      setError(msg);
      toast.error(msg);
    }
  };

  const isSelectionActive = selectedIds.size > 0;

  return (
    <ErrorBoundary viewName="Security Gates">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Security Gates (Контрольные точки)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Автоматические и ручные пороги безопасности (Quality Gates, Release Gates, Decision Ledger).
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchGates} disabled={loading} size="small">
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
              Создать Gate
            </Button>
            {onNavigateToPolicyBuilder && (
              <Button
                variant="outlined"
                size="small"
                startIcon={<Settings />}
                onClick={onNavigateToPolicyBuilder}
                sx={{ textTransform: 'none', fontWeight: 600 }}
              >
                Настроить политики
              </Button>
            )}
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Grid container spacing={2}>
          {/* Gates Cards / List */}
          <Grid size={{ xs: 12, md: 5 }}>
            {/* COS-064: Pending manual gates summary */}
            {pendingManualGates.length > 0 && (
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                <Chip
                  icon={<HourglassEmpty />}
                  label={`${pendingManualGates.length} ожидают ручного вердикта`}
                  size="small"
                  color="warning"
                  sx={{ fontWeight: 600, fontSize: 11 }}
                />
                <Checkbox
                  size="small"
                  checked={pendingManualGates.length > 0 && selectedIds.size === pendingManualGates.length}
                  indeterminate={selectedIds.size > 0 && selectedIds.size < pendingManualGates.length}
                  onChange={handleToggleAllPending}
                  sx={{ p: 0.5 }}
                  title="Выбрать все ожидающие ручные гейты"
                />
              </Box>
            )}
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {loading ? (
                [1, 2, 3].map((i) => (
                  <Paper key={i} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Skeleton width="50%" height={22} />
                    <Skeleton width="30%" height={16} sx={{ mt: 0.5 }} />
                  </Paper>
                ))
              ) : gates.length === 0 ? (
                <EmptyState
                  icon={<Gavel sx={{ fontSize: 28 }} />}
                  title="Security Gates не найдены"
                  description="Создайте контрольную точку для валидации порогов безопасности."
                  actionLabel="Создать Gate"
                  onAction={() => setOpenCreateModal(true)}
                />
              ) : (
                gates.map((g) => {
                  const isSelected = selectedGate?.id === g.id;
                  const isBulkChecked = selectedIds.has(g.id);
                  const isPendingManual = g.type === 'manual' && (!g.decision || g.decision === 'manual_required');
                  return (
                    <Card
                      key={g.id}
                      variant="outlined"
                      sx={{
                        cursor: 'pointer',
                        borderRadius: 2,
                        borderColor: isSelected ? 'primary.main' : 'divider',
                        bgcolor: isSelected ? 'action.selected' : 'background.paper',
                        transition: 'border-color 0.15s ease',
                      }}
                    >
                      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            {isPendingManual && (
                              <Checkbox
                                size="small"
                                checked={isBulkChecked}
                                onChange={(e) => {
                                  e.stopPropagation();
                                  handleToggleSelect(g.id);
                                }}
                                onClick={(e) => e.stopPropagation()}
                                sx={{ p: 0.5 }}
                              />
                            )}
                            <Gavel sx={{ fontSize: 18, color: 'primary.main' }} />
                            <Typography
                              variant="subtitle2"
                              sx={{ fontWeight: 700, fontFamily: 'monospace', cursor: 'pointer' }}
                              onClick={() => setSelectedGate(g)}
                            >
                              {g.id}
                            </Typography>
                          </Box>
                          <Box onClick={(e) => e.stopPropagation()}>
                            <Chip
                              label={g.decision || (g.type === 'manual' ? 'manual required' : 'pending')}
                              size="small"
                              color={g.decision === 'pass' ? 'success' : g.decision === 'block' ? 'error' : 'warning'}
                              sx={{ fontSize: 10, height: 20 }}
                              onClick={() => setSelectedGate(g)}
                            />
                          </Box>
                        </Box>
                        <Box onClick={() => setSelectedGate(g)}>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            Тип: <strong>{g.type}</strong> · Позиция #{g.position}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                            Правил политики: {g.policy.rules.length} ({g.policy.rules.map((r) => r.finding_type).join(', ')})
                          </Typography>
                        </Box>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </Box>
          </Grid>

          {/* Gate Inspector Details */}
          <Grid size={{ xs: 12, md: 7 }}>
            {selectedGate ? (
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        {selectedGate.id}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Тип: {selectedGate.type.toUpperCase()} · Позиция #{selectedGate.position}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        size="small"
                        variant="contained"
                        color="success"
                        startIcon={<CheckCircle />}
                        onClick={() => handleOpenDecision('pass')}
                        sx={{ textTransform: 'none', fontWeight: 600, fontSize: 12 }}
                      >
                        Одобрить (Pass)
                      </Button>
                      <Button
                        size="small"
                        variant="contained"
                        color="error"
                        startIcon={<Block />}
                        onClick={() => handleOpenDecision('block')}
                        sx={{ textTransform: 'none', fontWeight: 600, fontSize: 12 }}
                      >
                        Заблокировать (Block)
                      </Button>
                    </Box>
                  </Box>

                  <Divider sx={{ my: 2 }} />

                  {/* Current Decision Status */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Текущий статус вердикта
                  </Typography>
                  <Box sx={{ p: 2, bgcolor: 'action.hover', borderRadius: 1.5, mb: 3 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      {selectedGate.decision === 'pass' ? (
                        <CheckCircle sx={{ color: 'success.main' }} />
                      ) : selectedGate.decision === 'block' ? (
                        <Block sx={{ color: 'error.main' }} />
                      ) : (
                        <HourglassEmpty sx={{ color: 'warning.main' }} />
                      )}
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        Решение: {selectedGate.decision?.toUpperCase() || 'ОЖИДАЕТ РЕШЕНИЯ'}
                      </Typography>
                    </Box>
                    {selectedGate.decided_by && (
                      <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                        Принял: <strong>{selectedGate.decided_by}</strong>
                      </Typography>
                    )}
                    {selectedGate.decided_at && (
                      <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                        Время: {new Date(selectedGate.decided_at).toLocaleString()}
                      </Typography>
                    )}
                    {selectedGate.signature && (
                      <Typography variant="caption" sx={{ display: 'block', fontFamily: 'monospace', color: 'text.secondary', mt: 0.5 }}>
                        Подпись: {selectedGate.signature}
                      </Typography>
                    )}
                  </Box>

                  {/* Policy Rules Table */}
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Правила политики Security Gate
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 3 }}>
                    {selectedGate.policy.rules.map((rule, idx) => (
                      <Box
                        key={idx}
                        sx={{
                          p: 1.5,
                          border: 1,
                          borderColor: 'divider',
                          borderRadius: 1,
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            Уровень: {rule.finding_type}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            Порог: {rule.max_count !== null && rule.max_count !== undefined ? `макс. ${rule.max_count} находок` : 'без лимита'}
                          </Typography>
                        </Box>
                        <Chip
                          label={rule.action.toUpperCase()}
                          size="small"
                          color={rule.action === 'block' ? 'error' : rule.action === 'warn' ? 'warning' : 'success'}
                          sx={{ fontSize: 10, height: 20, fontWeight: 700 }}
                        />
                      </Box>
                    ))}
                  </Box>

                  {/* Web IDE Deep-link helper */}
                  {onNavigateToIDE && (
                    <Box sx={{ p: 2, border: 1, borderColor: 'primary.light', borderRadius: 1.5, bgcolor: 'rgba(14,165,233,0.04)' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            Связь с кодовой базой
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            Открыть политику или заблокированный сценарий в Web IDE
                          </Typography>
                        </Box>
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<OpenInNew />}
                          onClick={() => onNavigateToIDE({ repo: 'security/gates', file: `policies/${selectedGate.id}.yaml` })}
                          sx={{ textTransform: 'none', fontSize: 11 }}
                        >
                          Редактировать в IDE
                        </Button>
                      </Box>
                    </Box>
                  )}
                </CardContent>
              </Card>
            ) : (
              <EmptyState
                icon={<Gavel sx={{ fontSize: 32 }} />}
                title="Gate не выбран"
                description="Выберите Security Gate из списка слева для инспекции и принятия вердикта."
              />
            )}
          </Grid>
        </Grid>

        {/* Decision Dialog (single) */}
        <Dialog open={openDecisionModal} onClose={() => setOpenDecisionModal(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>
            {decisionType === 'pass' ? 'Одобрение Security Gate' : 'Блокировка Security Gate'}
          </DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="Ответственный оператор / ФИО"
              value={decidedBy}
              onChange={(e) => setDecidedBy(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Криптографическая подпись решения (SHA-256)"
              value={decisionSignature}
              onChange={(e) => setDecisionSignature(e.target.value)}
              fullWidth
              size="small"
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenDecisionModal(false)} disabled={submittingDecision}>
              Отмена
            </Button>
            <Button
              onClick={handleSubmitDecision}
              variant="contained"
              color={decisionType === 'pass' ? 'success' : 'error'}
              disabled={submittingDecision || !decidedBy}
              startIcon={<VerifiedUser />}
            >
              Подтвердить вердикт
            </Button>
          </DialogActions>
        </Dialog>

        {/* COS-064: Bulk Decision Modal */}
        <Dialog open={openBulkDecisionModal} onClose={() => setOpenBulkDecisionModal(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>
            Пакетный вердикт «{bulkDecisionType.toUpperCase()}» на {selectedIds.size} гейтов
          </DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Выбранные Security Gates получат вердикт <strong>{bulkDecisionType.toUpperCase()}</strong> с общей подписью.
            </Typography>
            <Box sx={{ p: 1.5, border: 1, borderColor: 'warning.light', borderRadius: 1.5, bgcolor: 'warning.lighter' }}>
              <Typography variant="caption" sx={{ fontWeight: 600 }}>
                Затронутые гейты: {Array.from(selectedIds).slice(0, 5).join(', ')}{selectedIds.size > 5 ? ` и ещё ${selectedIds.size - 5}` : ''}
              </Typography>
            </Box>
            <TextField
              label="Ответственный офицер безопасности / Оператор"
              value={bulkDecidedBy}
              onChange={(e) => setBulkDecidedBy(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="Криптографическая подпись (SHA-256)"
              value={bulkSignature}
              onChange={(e) => setBulkSignature(e.target.value)}
              fullWidth
              size="small"
              required
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenBulkDecisionModal(false)} disabled={bulkSubmittingDecision}>
              Отмена
            </Button>
            <Button
              onClick={handleSubmitBulkDecision}
              variant="contained"
              color={bulkDecisionType === 'pass' ? 'success' : 'error'}
              disabled={bulkSubmittingDecision || !bulkDecidedBy.trim()}
              startIcon={bulkSubmittingDecision ? <CircularProgress size={16} /> : <VerifiedUser />}
            >
              Применить к {selectedIds.size} гейтам
            </Button>
          </DialogActions>
        </Dialog>

        {/* Create Gate Dialog */}
        <Dialog open={openCreateModal} onClose={() => setOpenCreateModal(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ fontWeight: 700 }}>Создать новый Security Gate</DialogTitle>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="ID Gate"
              placeholder="gate-release-prod"
              value={newGateId}
              onChange={(e) => setNewGateId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              label="ID Плана"
              placeholder="plan-steel"
              value={newGatePlanId}
              onChange={(e) => setNewGatePlanId(e.target.value)}
              fullWidth
              size="small"
              required
            />
            <TextField
              select
              label="Тип проверки"
              value={newGateType}
              onChange={(e) => setNewGateType(e.target.value as 'automatic' | 'manual')}
              fullWidth
              size="small"
            >
              <MenuItem value="automatic">Automatic — Автоматический (по правилам)</MenuItem>
              <MenuItem value="manual">Manual — Ручной (требует подписи оператора)</MenuItem>
            </TextField>
            <TextField
              label="Позиция в пайплайне"
              type="number"
              value={newGatePosition}
              onChange={(e) => setNewGatePosition(Number(e.target.value))}
              fullWidth
              size="small"
            />
          </DialogContent>
          <DialogActions sx={{ p: 2 }}>
            <Button onClick={() => setOpenCreateModal(false)}>Отмена</Button>
            <Button onClick={handleCreateGate} variant="contained" disabled={!newGateId || !newGatePlanId}>
              Создать
            </Button>
          </DialogActions>
        </Dialog>

        {/* COS-064: Floating Bulk Decision Bar */}
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
              bgcolor: 'warning.dark',
              color: 'white',
              boxShadow: '0 8px 32px rgba(245,158,11,0.35)',
            }}
          >
            <Badge badgeContent={selectedIds.size} color="error" sx={{ '& .MuiBadge-badge': { fontWeight: 700 } }}>
              <Gavel sx={{ fontSize: 22 }} />
            </Badge>
            <Typography variant="body2" sx={{ fontWeight: 700, fontSize: 13 }}>
              Выбрано гейтов: <strong>{selectedIds.size}</strong>
            </Typography>
            <Button
              variant="contained"
              color="success"
              size="small"
              onClick={() => handleOpenBulkDecision('pass')}
              disabled={bulkSubmitting}
              startIcon={<CheckCircle />}
              sx={{
                textTransform: 'none',
                fontWeight: 700,
                bgcolor: 'white',
                color: 'success.main',
                '&:hover': { bgcolor: 'grey.200' },
              }}
            >
              Пакетный Pass ({selectedIds.size})
            </Button>
            <Button
              variant="contained"
              color="error"
              size="small"
              onClick={() => handleOpenBulkDecision('block')}
              disabled={bulkSubmitting}
              startIcon={<Block />}
              sx={{
                textTransform: 'none',
                fontWeight: 700,
                bgcolor: 'white',
                color: 'error.main',
                '&:hover': { bgcolor: 'grey.200' },
              }}
            >
              Пакетный Block ({selectedIds.size})
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