/**
 * COS-090: Release Transfer Wizard UI.
 *
 * COS-098 (контракт-первым): зона — backend 'zr'|'zt'|'zpe' (не 'ЗР'/'ЗТ');
 * трансфер — честный TransferReleaseRequest (target_zone, officer_name,
 * sign_signature, token_2fa, transfer_notes) → POST /transfer; итог —
 * Release ИЗ ОТВЕТА БЭКЕНДА, не client-side фальсификация. Гост-акт —
 * реальный эндпоинт /runs/{run_id}/gost-act/html. Трансфер разрешён
 * бэкендом только из статуса deployed — целевая зона = следующая
 * в порядке ЗР → ЗТ → ЗПЭ.
 *
 *   Step 1 — Pre-Flight Checks (gates плана, approvals с подписью)
 *   Step 2 — Target Zone (следующая зона) + сводка состава
 *   Step 3 — Signoff & 2FA (officer credentials, signature, transfer)
 *   Success — экран с GOST-Act download (реальный endpoint)
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Stepper, Step, StepLabel,
  StepContent, Card, Grid,
  TextField, Checkbox, FormControlLabel, CircularProgress,
} from '@mui/material';
import {
  ArrowForward, ArrowBack, VerifiedUser, CheckCircle,
  Warning, Gavel, Fingerprint, Download,
  TaskAlt,
} from '@mui/icons-material';
import {
  api, type Release, type ReleaseZone, type Gate,
} from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { toast } from '../../shared/toast';

export const ZONE_LABELS: Record<ReleaseZone, string> = {
  zr: 'ЗР (Разработка)',
  zt: 'ЗТ (Тестирование)',
  zpe: 'ЗПЭ (Пром)',
};

const NEXT_ZONE: Record<ReleaseZone, ReleaseZone | null> = {
  zr: 'zt',
  zt: 'zpe',
  zpe: null,
};

interface PreFlightResult {
  allGatesPassed: boolean;
  pendingGates: string[];
  hasOfficerApproval: boolean;
  gateCount: number;
  overallScore: number;
}

interface ReleaseTransferWizardProps {
  release: Release;
  onComplete?: (release: Release) => void;
  onClose?: () => void;
}

export function ReleaseTransferWizard({ release, onComplete, onClose }: ReleaseTransferWizardProps) {
  const targetZone: ReleaseZone | null = NEXT_ZONE[release.current_zone];

  const [activeStep, setActiveStep] = useState(0);
  const [gates, setGates] = useState<Gate[]>([]);
  const [loadingPreflight, setLoadingPreflight] = useState(true);

  // Signoff form
  const [officerName, setOfficerName] = useState('');
  const [authToken, setAuthToken] = useState('');
  const [confirmTransfer, setConfirmTransfer] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [transferSuccess, setTransferSuccess] = useState(false);
  const [updatedRelease, setUpdatedRelease] = useState<Release | null>(null);
  const [transferError, setTransferError] = useState<string | null>(null);

  // ── Pre-flight checks ───────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    const runPreflight = async () => {
      setLoadingPreflight(true);
      try {
        const gatesData = await api.getGates(release.plan_id);
        if (!cancelled) setGates(gatesData || []);
      } catch {
        if (!cancelled) setGates([]);
      } finally {
        if (!cancelled) setLoadingPreflight(false);
      }
    };
    runPreflight();
    return () => { cancelled = true; };
  }, [release.plan_id]);

  const preFlight = useMemo<PreFlightResult>(() => {
    const pendingGates = gates
      .filter((g) => !g.decision || g.decision === 'manual_required')
      .map((g) => g.id);
    const allGatesPassed = gates.length > 0 && pendingGates.length === 0;
    // COS-098: подпись офицера ИБ = approved-approval с подписью (backend-поля)
    const hasOfficerApproval = release.approvals.some(
      (a) => a.decision === 'approved' && !!a.signature,
    );
    const score = (allGatesPassed ? 50 : 0) + (hasOfficerApproval ? 50 : 0);
    return { allGatesPassed, pendingGates, hasOfficerApproval, gateCount: gates.length, overallScore: score };
  }, [gates, release.approvals]);

  // ── Step handlers ───────────────────────────────────────────────────

  const handleNext = () => setActiveStep((prev) => prev + 1);
  const handleBack = () => setActiveStep((prev) => prev - 1);

  const handleSubmitTransfer = async () => {
    if (!officerName.trim() || !authToken.trim() || !targetZone) return;
    setSubmitting(true);
    setTransferError(null);

    try {
      // COS-098: честный TransferReleaseRequest → Release из ответа бэкенда
      const released = await api.transferRelease(release.id, {
        target_zone: targetZone,
        officer_name: officerName.trim(),
        sign_signature: `transfer-request:${officerName.trim()}:${targetZone}`,
        token_2fa: authToken,
        transfer_notes: confirmTransfer ? 'Подтверждено офицером ИБ' : undefined,
      });
      setUpdatedRelease(released);
      setTransferSuccess(true);
      toast.success(`Релиз ${release.id} трансферирован в контур «${ZONE_LABELS[targetZone]}»`);

      if (onComplete) {
        setTimeout(() => onComplete(released), 1500);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка трансфера релиза';
      setTransferError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDownloadGOST = () => {
    // COS-098: реальный ГОСТ-Акт эндпоинт по первому прогону релиза
    if (release.run_ids.length === 0) {
      toast.error('В релизе нет прогонов — ГОСТ-Акт недоступен');
      return;
    }
    window.open(`/api/v1/runs/${encodeURIComponent(release.run_ids[0])}/gost-act/html`, '_blank');
  };

  // ── Step labels ─────────────────────────────────────────────────────

  const steps = [
    { label: 'Pre-Flight Checks (Проверка допуска)', description: 'Автоматическая верификация критериев' },
    { label: 'Target Zone & Состав', description: `Целевая зона: ${targetZone ? ZONE_LABELS[targetZone] : '—'}` },
    { label: 'Signoff & 2FA (Подтверждение)', description: 'Авторизация офицера безопасности' },
  ];

  // ── Render ──────────────────────────────────────────────────────────

  if (transferSuccess && updatedRelease) {
    return (
      <Card variant="outlined" sx={{ borderRadius: 2, p: 4, textAlign: 'center', borderColor: 'success.main' }}>
        <Box sx={{ py: 3, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
          <TaskAlt sx={{ fontSize: 64, color: 'success.main' }} />
          <Typography variant="h5" sx={{ fontWeight: 700, color: 'success.main' }}>
            Трансфер успешно выполнен!
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Релиз <strong>{updatedRelease.id}</strong> ({updatedRelease.version || 'без версии'}) перемещён
            {' '}из <Chip label={ZONE_LABELS[updatedRelease.transfer_history.at(-1)?.from_zone ?? 'zr']} size="small" color="primary" sx={{ fontWeight: 700 }} />
            {' '}в <Chip label={ZONE_LABELS[updatedRelease.current_zone]} size="small" color="success" sx={{ fontWeight: 700 }} />
          </Typography>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'action.hover', mt: 1, width: '100%', maxWidth: 400 }}>
            <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', display: 'block', textAlign: 'left', wordBreak: 'break-all' }}>
              Зона подтверждена ответом бэкенда: {updatedRelease.current_zone}
            </Typography>
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary' }}>
              Сертифицировал: <strong>{officerName}</strong>
            </Typography>
          </Paper>
          <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
            <Button
              variant="contained"
              color="success"
              startIcon={<Download />}
              onClick={handleDownloadGOST}
              sx={{ textTransform: 'none', fontWeight: 600 }}
            >
              Скачать ГОСТ-Акт
            </Button>
            {onClose && (
              <Button variant="outlined" onClick={onClose} sx={{ textTransform: 'none' }}>
                Закрыть
              </Button>
            )}
          </Box>
        </Box>
      </Card>
    );
  }

  return (
    <ErrorBoundary viewName="Мастер трансфера релиза">
      <Card variant="outlined" sx={{ borderRadius: 2, overflow: 'visible' }}>
        {/* Header */}
        <Box sx={{ p: 2.5, borderBottom: 1, borderColor: 'divider' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                Мастер трансфера релиза
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {release.id} ({release.version || 'без версии'}) — текущая зона:{' '}
                <Chip label={ZONE_LABELS[release.current_zone]} size="small" color="primary" sx={{ fontWeight: 700, fontSize: 12 }} />
              </Typography>
            </Box>
            {onClose && (
              <IconButton size="small" onClick={onClose}><span style={{ fontSize: 18 }}>×</span></IconButton>
            )}
          </Box>
        </Box>

        {transferError && (
          <Alert severity="error" sx={{ mx: 2, mt: 2 }} onClose={() => setTransferError(null)}>
            {transferError}
          </Alert>
        )}

        {!targetZone && (
          <Alert severity="warning" sx={{ mx: 2, mt: 2 }}>
            Релиз уже в конечной зоне (ЗПЭ) — трансфер недоступен.
          </Alert>
        )}

        {/* Stepper */}
        <Box sx={{ p: 2.5 }}>
          <Stepper activeStep={activeStep} orientation="vertical">
            {/* ═══ Step 1: Pre-Flight ═══ */}
            <Step>
              <StepLabel
                icon={
                  loadingPreflight ? (
                    <CircularProgress size={20} />
                  ) : preFlight.overallScore >= 100 ? (
                    <CheckCircle sx={{ color: 'success.main' }} />
                  ) : (
                    <Warning sx={{ color: preFlight.overallScore >= 50 ? 'warning.main' : 'error.main' }} />
                  )
                }
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                    Pre-Flight Checks (Проверка готовности)
                  </Typography>
                  <Chip
                    label={preFlight.overallScore >= 100 ? 'ГОТОВ' : 'ТРЕБУЕТ ВНИМАНИЯ'}
                    size="small"
                    color={preFlight.overallScore >= 100 ? 'success' : preFlight.overallScore >= 50 ? 'warning' : 'error'}
                    sx={{ fontWeight: 700, fontSize: 10 }}
                  />
                  <Chip label={`${preFlight.overallScore}%`} size="small" variant="outlined" sx={{ fontSize: 10 }} />
                </Box>
                <Typography variant="caption" color="text.secondary">
                  Автоматическая верификация Security Gates плана и подписанных approvals.
                </Typography>
              </StepLabel>
              <StepContent>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, py: 1 }}>
                  {/* Gate Check */}
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Gavel sx={{ color: preFlight.allGatesPassed ? 'success.main' : 'warning.main', fontSize: 22 }} />
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          Security Gates ({preFlight.gateCount})
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {preFlight.gateCount === 0
                            ? 'В плане релиза нет гейтов'
                            : preFlight.allGatesPassed
                              ? 'Все гейты имеют вердикт PASS'
                              : `${preFlight.pendingGates.length} гейтов без вердикта: ${preFlight.pendingGates.join(', ')}`}
                        </Typography>
                      </Box>
                    </Box>
                    {preFlight.allGatesPassed ? (
                      <CheckCircle sx={{ color: 'success.main', fontSize: 20 }} />
                    ) : (
                      <Warning sx={{ color: 'warning.main', fontSize: 20 }} />
                    )}
                  </Paper>

                  {/* Approval/Signature Check */}
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Fingerprint sx={{ color: preFlight.hasOfficerApproval ? 'success.main' : 'error.main', fontSize: 22 }} />
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          Подпись офицера ИБ
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {preFlight.hasOfficerApproval
                            ? 'Есть approved-решение с подписью'
                            : 'Требуется approval с подписью офицера безопасности'}
                        </Typography>
                      </Box>
                    </Box>
                    {preFlight.hasOfficerApproval ? (
                      <CheckCircle sx={{ color: 'success.main', fontSize: 20 }} />
                    ) : (
                      <Warning sx={{ color: 'error.main', fontSize: 20 }} />
                    )}
                  </Paper>

                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleNext}
                      disabled={loadingPreflight || !targetZone}
                      endIcon={<ArrowForward />}
                      sx={{ textTransform: 'none', fontWeight: 600 }}
                    >
                      Подтвердить и продолжить
                    </Button>
                    {onClose && (
                      <Button size="small" onClick={onClose} sx={{ textTransform: 'none' }}>
                        Отмена
                      </Button>
                    )}
                  </Box>
                </Box>
              </StepContent>
            </Step>

            {/* ═══ Step 2: Target Zone ═══ */}
            <Step>
              <StepLabel
                icon={activeStep >= 2 ? <CheckCircle sx={{ color: 'success.main' }} /> : <VerifiedUser sx={{ color: 'primary.main' }} />}
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Target Zone & Состав
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Целевая зона — следующая в порядке ЗР → ЗТ → ЗПЭ (правило бэкенда).
                </Typography>
              </StepLabel>
              <StepContent>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, py: 1 }}>
                  {/* Zone Summary */}
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                      Целевая зона безопасности
                    </Typography>
                    <Grid container spacing={1.5}>
                      <Grid size={{ xs: 6 }}>
                        <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5, borderColor: 'divider' }}>
                          <Typography variant="caption" color="text.secondary">Из</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>{ZONE_LABELS[release.current_zone]}</Typography>
                        </Paper>
                      </Grid>
                      <Grid size={{ xs: 6 }}>
                        <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5, borderColor: targetZone === 'zpe' ? 'success.main' : 'warning.main', bgcolor: 'rgba(245,158,11,0.05)' }}>
                          <Typography variant="caption" color="text.secondary">В</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 700 }}>{targetZone ? ZONE_LABELS[targetZone] : '—'}</Typography>
                        </Paper>
                      </Grid>
                    </Grid>
                  </Paper>

                  {/* Release Composition Summary (честный состав) */}
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                      Состав релиза
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 12 }}>
                      <div><strong>Прогонов:</strong> {release.run_ids.length}</div>
                      <div><strong>Артефактов:</strong> {release.artifacts.length}</div>
                      <div><strong>Approvals:</strong> {release.approvals.length}</div>
                    </Box>
                  </Paper>

                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button size="small" onClick={handleBack} sx={{ textTransform: 'none' }}>
                      <ArrowBack sx={{ fontSize: 16, mr: 0.5 }} /> Назад
                    </Button>
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleNext}
                      endIcon={<ArrowForward />}
                      sx={{ textTransform: 'none', fontWeight: 600 }}
                    >
                      Перейти к подписанию
                    </Button>
                  </Box>
                </Box>
              </StepContent>
            </Step>

            {/* ═══ Step 3: Signoff ═══ */}
            <Step>
              <StepLabel
                icon={
                  submitting ? (
                    <CircularProgress size={20} />
                  ) : (
                    <VerifiedUser sx={{ color: 'primary.main' }} />
                  )
                }
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Signoff & 2FA (Подтверждение трансфера)
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Авторизация офицера безопасности, передача подписи в бэкенд.
                </Typography>
              </StepLabel>
              <StepContent>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, py: 1 }}>
                  {/* Summary */}
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 2 }}>
                      Сводка трансфера
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 12 }}>
                      <div><strong>Релиз:</strong> {release.id} ({release.version || 'без версии'})</div>
                      <div><strong>Текущая зона:</strong> {ZONE_LABELS[release.current_zone]}</div>
                      <div><strong>Целевая зона:</strong> <Chip label={targetZone ? ZONE_LABELS[targetZone] : '—'} size="small" color={targetZone === 'zpe' ? 'success' : 'warning'} sx={{ fontWeight: 700, ml: 1 }} /></div>
                      <div><strong>Статус Pre-Flight:</strong> <Chip label={`${preFlight.overallScore}%`} size="small" color={preFlight.overallScore >= 100 ? 'success' : 'warning'} sx={{ fontWeight: 700 }} /></div>
                    </Box>
                  </Paper>

                  {/* Officer Form */}
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 2 }}>
                      Авторизация офицера безопасности
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <TextField
                        label="ФИО / Идентификатор офицера"
                        placeholder="Иванов Иван Иванович (secops-lead@example.com)"
                        value={officerName}
                        onChange={(e) => setOfficerName(e.target.value)}
                        size="small"
                        fullWidth
                        required
                        helperText="Уйдёт в бэкенд как officer_name (SAN-009)"
                      />
                      <TextField
                        label="2FA Токен подтверждения / Пароль подписи"
                        type="password"
                        placeholder="Введите токен 2FA или пароль"
                        value={authToken}
                        onChange={(e) => setAuthToken(e.target.value)}
                        size="small"
                        fullWidth
                        required
                        helperText="Второй фактор аутентификации (TOTP / SMS / Hardware Key)"
                      />
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={confirmTransfer}
                            onChange={(_, v) => setConfirmTransfer(v)}
                            color="warning"
                          />
                        }
                        label={
                          <Typography variant="caption" color="text.secondary">
                            Я подтверждаю трансфер релиза в контур <strong>{targetZone ? ZONE_LABELS[targetZone] : ''}</strong> и принимаю на себя ответственность за соответствие требованиям безопасности.
                          </Typography>
                        }
                      />
                    </Box>
                  </Paper>

                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button size="small" onClick={handleBack} disabled={submitting} sx={{ textTransform: 'none' }}>
                      <ArrowBack sx={{ fontSize: 16, mr: 0.5 }} /> Назад
                    </Button>
                    <Button
                      variant="contained"
                      color={targetZone === 'zpe' ? 'success' : 'warning'}
                      size="small"
                      onClick={handleSubmitTransfer}
                      disabled={submitting || !officerName.trim() || !authToken.trim() || !confirmTransfer || !targetZone}
                      startIcon={submitting ? <CircularProgress size={16} /> : <VerifiedUser />}
                      sx={{ textTransform: 'none', fontWeight: 700 }}
                    >
                      {submitting ? 'Выполнение трансфера...' : `Подтвердить трансфер в ${targetZone ? ZONE_LABELS[targetZone] : ''}`}
                    </Button>
                  </Box>
                </Box>
              </StepContent>
            </Step>
          </Stepper>
        </Box>
      </Card>
    </ErrorBoundary>
  );
}
