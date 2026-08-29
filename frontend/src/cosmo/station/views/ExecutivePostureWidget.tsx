/**
 * COS-100: Executive Security Posture Widget & C-Level Overview.
 *
 * Executive dashboard with Radial Gauge score, compliance summaries,
 * automation metrics, and auditor report download.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Card, CardContent, Grid,
  Divider, LinearProgress,
} from '@mui/material';
import {
  Refresh, Security, CheckCircle, AutoAwesome, Description,
  VerifiedUser, Gavel, TrendingUp,
} from '@mui/icons-material';
import { api, type SecurityPosture } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';

// ── Radial Gauge (SVG) ──────────────────────────────────────────────

function RadialGauge({ score, grade, loading }: { score: number; grade: string; loading: boolean }) {
  const r = 70;
  const circumference = 2 * Math.PI * r;
  const safeScore = Math.max(0, Math.min(100, score));

  const getColor = (s: number) => {
    if (s >= 90) return { stroke: '#10B981', bg: '#D1FAE5', text: '#065F46', shadow: 'rgba(16,185,129,0.3)' };
    if (s >= 70) return { stroke: '#F59E0B', bg: '#FEF3C7', text: '#92400E', shadow: 'rgba(245,158,11,0.3)' };
    return { stroke: '#EF4444', bg: '#FEE2E2', text: '#991B1B', shadow: 'rgba(239,68,68,0.3)' };
  };

  const colors = getColor(safeScore);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
        <Skeleton variant="circular" width={160} height={160} />
        <Skeleton width={80} height={24} />
      </Box>
    );
  }

  return (
    <Box sx={{ position: 'relative', display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width={180} height={180} viewBox="0 0 180 180">
        {/* Background circle */}
        <circle
          cx={90}
          cy={90}
          r={r}
          fill="none"
          stroke={colors.bg}
          strokeWidth={12}
        />
        {/* Progress arc */}
        <circle
          cx={90}
          cy={90}
          r={r}
          fill="none"
          stroke={colors.stroke}
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - safeScore / 100)}
          transform="rotate(-90 90 90)"
          style={{
            transition: 'stroke-dashoffset 1s ease-in-out',
            filter: `drop-shadow(0 0 6px ${colors.shadow})`,
          }}
        />
        {/* Inner glow ring */}
        <circle
          cx={90}
          cy={90}
          r={r}
          fill="none"
          stroke={colors.stroke}
          strokeWidth={2}
          opacity={0.3}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - safeScore / 100)}
          transform="rotate(-90 90 90)"
          style={{ transition: 'stroke-dashoffset 1s ease-in-out' }}
        />
      </svg>
      <Box
        sx={{
          position: 'absolute',
          top: 0, left: 0, right: 0, bottom: 0,
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}
      >
        <Typography variant="h3" sx={{ fontWeight: 800, color: colors.text, lineHeight: 1 }}>
          {safeScore}
        </Typography>
        <Typography variant="body2" sx={{ color: colors.text, fontWeight: 700, opacity: 0.8 }}>
          из 100
        </Typography>
      </Box>
      {/* Grade badge */}
      <Chip
        label={`Grade ${grade}`}
        size="small"
        sx={{
          mt: 1,
          fontWeight: 800,
          fontSize: 13,
          bgcolor: colors.bg,
          color: colors.text,
          border: `2px solid ${colors.stroke}`,
        }}
      />
    </Box>
  );
}

// ── Compliance Bar ──────────────────────────────────────────────────

function ComplianceBar({ label, pct, loading }: { label: string; pct: number; loading: boolean }) {
  const getBarColor = (p: number) => {
    if (p >= 90) return '#10B981';
    if (p >= 75) return '#F59E0B';
    return '#EF4444';
  };

  return (
    <Box sx={{ mb: 1.5 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
          {label}
        </Typography>
        {loading ? (
          <Skeleton width={36} height={16} />
        ) : (
          <Typography variant="caption" sx={{ fontWeight: 700, color: getBarColor(pct) }}>
            {pct}%
          </Typography>
        )}
      </Box>
      {loading ? (
        <Skeleton variant="rounded" height={8} />
      ) : (
        <LinearProgress
          variant="determinate"
          value={pct}
          sx={{
            height: 8,
            borderRadius: 4,
            bgcolor: 'action.hover',
            '& .MuiLinearProgress-bar': {
              borderRadius: 4,
              bgcolor: getBarColor(pct),
            },
          }}
        />
      )}
    </Box>
  );
}

// ── Main Widget ─────────────────────────────────────────────────────

interface ExecutivePostureWidgetProps {
  domain?: string;
}

export function ExecutivePostureWidget({ domain = 'all' }: ExecutivePostureWidgetProps) {
  const [posture, setPosture] = useState<SecurityPosture | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPosture = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSecurityPosture(domain);
      setPosture(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки данных Security Posture';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [domain]);

  useEffect(() => {
    fetchPosture();
  }, [fetchPosture]);

  const handleDownloadReport = () => {
    const reportLines = [
      `=== СВОДНЫЙ ОТЧЁТ О ЗАЩИЩЁННОСТИ КИТС ===`,
      `Дата формирования: ${new Date().toLocaleDateString('ru-RU')}`,
      ``,
      `Индекс защищённости КИТС: ${posture?.score ?? '—'} / 100 (Grade ${posture?.grade ?? '—'})`,
      `Открыто Critical: ${posture?.critical_open ?? '—'} | High: ${posture?.high_open ?? '—'}`,
      `Проход гейтов: ${posture?.gate_pass_rate_pct ?? '—'}% | SLA: ${posture?.sla_compliance_pct ?? '—'}%`,
      ``,
      `── Комплаенс ──`,
      `ГОСТ Р 56939-2016: ${posture?.gost_56939_pct ?? '—'}%`,
      `Положение ЦБ 683-П:  ${posture?.cbr_683_pct ?? '—'}%`,
      `Положение ЦБ 757-П:  ${posture?.cbr_757_pct ?? '—'}%`,
      ``,
      `── Автоматизация ──`,
      `Авто-гейты: ${posture?.auto_gates_pct ?? '—'}% (${(posture?.total_gates ?? 0) - (posture?.manual_gates_count ?? 0)} из ${posture?.total_gates ?? 0})`,
      `Ручные гейты: ${posture?.manual_gates_count ?? '—'}`,
    ];

    const blob = new Blob([reportLines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Security_Posture_Report_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const score = posture?.score ?? 0;
  const grade = posture?.grade ?? '—';

  return (
    <ErrorBoundary viewName="Executive Posture Widget">
      <Card
        variant="outlined"
        sx={{
          borderRadius: 2,
          background: 'linear-gradient(135deg, rgba(14,165,233,0.03) 0%, rgba(124,58,237,0.03) 100%)',
          borderColor: 'primary.light',
        }}
      >
        <CardContent sx={{ p: 2.5, '&:last-child': { pb: 2.5 } }}>
          {/* Header */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Security sx={{ color: 'primary.main', fontSize: 22 }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Security Posture КИТС
              </Typography>
              <Chip
                icon={<VerifiedUser sx={{ fontSize: 12 }} />}
                label="C-Level Overview"
                size="small"
                color="primary"
                variant="outlined"
                sx={{ fontSize: 10, height: 22 }}
              />
            </Box>
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Tooltip title="Обновить данные">
                <IconButton onClick={fetchPosture} disabled={loading} size="small">
                  <Refresh fontSize="small" />
                </IconButton>
              </Tooltip>
              <Button
                variant="outlined"
                size="small"
                startIcon={<Description sx={{ fontSize: 14 }} />}
                onClick={handleDownloadReport}
                disabled={loading || !posture}
                sx={{ textTransform: 'none', fontSize: 12, fontWeight: 600 }}
              >
                Отчёт аудитору
              </Button>
            </Box>
          </Box>

          {error && (
            <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {/* Main grid: Gauge + Compliance + Automation */}
          <Grid container spacing={2} sx={{ alignItems: 'center' }}>
            {/* Radial Gauge */}
            <Grid size={{ xs: 12, sm: 4, md: 3 }} sx={{ display: 'flex', justifyContent: 'center' }}>
              <RadialGauge score={score} grade={grade} loading={loading} />
            </Grid>

            {/* Compliance + Findings */}
            <Grid size={{ xs: 12, sm: 4, md: 5 }}>
              <Typography variant="overline" sx={{ fontWeight: 700, color: 'text.secondary', display: 'block', mb: 1 }}>
                Соответствие нормативам
              </Typography>
              <ComplianceBar
                label="ГОСТ Р 56939-2016 (Защита ПДн)"
                pct={posture?.gost_56939_pct ?? 0}
                loading={loading}
              />
              <ComplianceBar
                label="Положение ЦБ 683-П"
                pct={posture?.cbr_683_pct ?? 0}
                loading={loading}
              />
              <ComplianceBar
                label="Положение ЦБ 757-П"
                pct={posture?.cbr_757_pct ?? 0}
                loading={loading}
              />
            </Grid>

            {/* Automation & Findings summary */}
            <Grid size={{ xs: 12, sm: 4, md: 4 }}>
              <Typography variant="overline" sx={{ fontWeight: 700, color: 'text.secondary', display: 'block', mb: 1 }}>
                Метрики и автоматизация
              </Typography>

              {/* Findings summary */}
              {loading ? (
                <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5, borderRadius: 2 }}>
                  <Skeleton width="60%" height={16} />
                  <Skeleton width="40%" height={14} sx={{ mt: 0.5 }} />
                </Paper>
              ) : (
                <Paper
                  variant="outlined"
                  sx={{
                    p: 1.5,
                    mb: 1.5,
                    borderRadius: 2,
                    borderColor: posture && posture.critical_open === 0 ? 'success.light' : 'error.light',
                    bgcolor: posture && posture.critical_open === 0 ? 'success.50' : 'error.50',
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    {posture && posture.critical_open === 0 ? (
                      <CheckCircle sx={{ color: 'success.main', fontSize: 18 }} />
                    ) : (
                      <Gavel sx={{ color: 'error.main', fontSize: 18 }} />
                    )}
                    <Box>
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        {posture?.critical_open === 0
                          ? 'Critical уязвимостей нет'
                          : `${posture?.critical_open ?? '—'} Critical · ${posture?.high_open ?? '—'} High открыто`}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Gate Pass Rate: {posture?.gate_pass_rate_pct ?? '—'}% · SLA: {posture?.sla_compliance_pct ?? '—'}%
                      </Typography>
                    </Box>
                  </Box>
                </Paper>
              )}

              {/* Automation metric */}
              {loading ? (
                <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                  <Skeleton width="50%" height={16} />
                  <Skeleton width="30%" height={14} sx={{ mt: 0.5 }} />
                </Paper>
              ) : (
                <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <AutoAwesome sx={{ color: 'primary.main', fontSize: 18 }} />
                    <Box>
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        Автоматизация гейтов: {posture?.auto_gates_pct ?? '—'}%
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {posture
                          ? `${(posture.total_gates - posture.manual_gates_count)} авто / ${posture.manual_gates_count} ручных (из ${posture.total_gates} всего)`
                          : '—'}
                      </Typography>
                    </Box>
                    <Box sx={{ flex: 1 }} />
                    <TrendingUp sx={{ color: 'text.disabled', fontSize: 16 }} />
                  </Box>
                </Paper>
              )}

              {/* Last updated */}
              {!loading && posture && (
                <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mt: 1, textAlign: 'right' }}>
                  Обновлено: {new Date(posture.last_updated).toLocaleString('ru-RU')}
                </Typography>
              )}
            </Grid>
          </Grid>
        </CardContent>
      </Card>
    </ErrorBoundary>
  );
}