/**
 * COS-107: SLA Remediation Dashboard Widget & Alerts.
 *
 * Displays SLA compliance for vulnerability remediation per ЦБ РФ norms:
 *   Critical — 24h, High — 7d, Medium — 30d.
 *
 * Components:
 *   - Circular SLA compliance gauge
 *   - Criticality tier breakdown cards
 *   - Breached findings list with overdue badges + jump-to-code
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Card, CardContent, Grid, Divider, IconButton, Tooltip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
} from '@mui/material';
import {
  Refresh, AccessTime, Warning, Error, Info,
  OpenInNew, Timer, CheckCircle,
} from '@mui/icons-material';
import { api, type SlaMetrics, type SlaBreach, type SlaTier } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';

// ── Tier meta ───────────────────────────────────────────────────────

const TIER_META: Record<SlaTier, { color: string; bg: string; label: string; norm: string; icon: typeof Error }> = {
  critical: { color: '#EF4444', bg: '#FEE2E2', label: 'Critical', norm: 'норма ≤ 24 ч', icon: Error },
  high:     { color: '#F59E0B', bg: '#FEF3C7', label: 'High',     norm: 'норма ≤ 7 дн', icon: Warning },
  medium:   { color: '#3B82F6', bg: '#DBEAFE', label: 'Medium',   norm: 'норма ≤ 30 дн', icon: Info },
};

// ── Mini radial gauge ───────────────────────────────────────────────

function SlaGauge({ pct, loading }: { pct: number; loading: boolean }) {
  const r = 52;
  const circumference = 2 * Math.PI * r;
  const safe = Math.max(0, Math.min(100, pct));

  const getColor = (v: number) => {
    if (v >= 90) return { stroke: '#10B981', bg: '#D1FAE5', text: '#065F46' };
    if (v >= 70) return { stroke: '#F59E0B', bg: '#FEF3C7', text: '#92400E' };
    return { stroke: '#EF4444', bg: '#FEE2E2', text: '#991B1B' };
  };
  const c = getColor(safe);

  if (loading) {
    return <Skeleton variant="circular" width={130} height={130} sx={{ mx: 'auto' }} />;
  }

  return (
    <Box sx={{ position: 'relative', width: 130, height: 130, mx: 'auto' }}>
      <svg width={130} height={130} viewBox="0 0 130 130">
        <circle cx={65} cy={65} r={r} fill="none" stroke={c.bg} strokeWidth={10} />
        <circle
          cx={65} cy={65} r={r} fill="none" stroke={c.stroke} strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - safe / 100)}
          transform="rotate(-90 65 65)"
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <Typography variant="h5" sx={{ fontWeight: 800, color: c.text, lineHeight: 1 }}>
          {safe.toFixed(0)}%
        </Typography>
        <Typography variant="caption" sx={{ color: c.text, opacity: 0.7, fontWeight: 600 }}>
          SLA
        </Typography>
      </Box>
    </Box>
  );
}

// ── Overdue badge formatter ─────────────────────────────────────────

function overdueLabel(hours: number): string {
  if (hours < 1) return 'Менее часа';
  if (hours < 24) return `Просрочено на ${Math.round(hours)} ч`;
  const days = Math.round(hours / 24);
  return `Просрочено на ${days} дн`;
}

// ── Tier summary card ───────────────────────────────────────────────

function TierCard({ tier, onTime, breached, total, slaHours, loading }: {
  tier: SlaTier; onTime: number; breached: number; total: number; slaHours: number; loading: boolean;
}) {
  const meta = TIER_META[tier];
  const compliancePct = total > 0 ? Math.round((onTime / total) * 100) : 100;

  if (loading) {
    return (
      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
          <Skeleton width={80} height={20} />
          <Skeleton width={50} height={32} sx={{ mt: 0.5 }} />
          <Skeleton width={120} height={16} sx={{ mt: 0.5 }} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card variant="outlined" sx={{ borderRadius: 2, borderColor: meta.color, borderWidth: breached > 0 ? 2 : 1 }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <meta.icon sx={{ color: meta.color, fontSize: 18 }} />
            <Typography variant="body2" sx={{ fontWeight: 700, color: meta.color }}>
              {meta.label}
            </Typography>
          </Box>
          <Chip
            label={meta.norm}
            size="small"
            sx={{ fontSize: 9, height: 20, bgcolor: meta.bg, color: meta.color, fontWeight: 600 }}
          />
        </Box>
        <Typography variant="h5" sx={{ fontWeight: 800, color: compliancePct >= 90 ? 'success.main' : compliancePct >= 70 ? 'warning.main' : 'error.main' }}>
          {compliancePct}%
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {onTime} в срок / {breached} просроч. из {total}
        </Typography>
      </CardContent>
    </Card>
  );
}

// ── Main Widget ─────────────────────────────────────────────────────

interface SlaRemediationWidgetProps {
  domain?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function SlaRemediationWidget({ domain = 'all', onNavigateToIDE }: SlaRemediationWidgetProps) {
  const [sla, setSla] = useState<SlaMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const fetchSla = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSlaMetrics(domain);
      setSla(data);
    } catch (e: unknown) {
      const msg = (e as Error)?.message || 'Ошибка загрузки SLA-метрик';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [domain]);

  useEffect(() => { fetchSla(); }, [fetchSla]);

  const breaches = sla?.breaches ?? [];
  const visibleBreaches = expanded ? breaches : breaches.slice(0, 3);

  return (
    <ErrorBoundary viewName="SLA Remediation Widget">
      <Card variant="outlined" sx={{ borderRadius: 2 }}>
        <CardContent sx={{ p: 2.5, '&:last-child': { pb: 2.5 } }}>
          {/* Header */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Timer sx={{ color: 'warning.main', fontSize: 22 }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                SLA устранения уязвимостей
              </Typography>
              <Chip
                label="ЦБ РФ 683-П"
                size="small"
                color="warning"
                variant="outlined"
                sx={{ fontSize: 10, height: 22 }}
              />
            </Box>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchSla} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>

          {error && (
            <Typography variant="body2" color="error" sx={{ mb: 2 }}>
              {error}
            </Typography>
          )}

          {/* Main layout: Gauge | Tier Cards | Breach list */}
          <Grid container spacing={2} sx={{ alignItems: 'flex-start' }}>
            {/* Gauge */}
            <Grid size={{ xs: 12, sm: 3, md: 2 }} sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <SlaGauge pct={sla?.overall_compliance_pct ?? 0} loading={loading} />
              {!loading && sla && (
                <Box sx={{ textAlign: 'center', mt: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    {sla.breached_count} просроч.
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    из {sla.total_open} открытых
                  </Typography>
                </Box>
              )}
            </Grid>

            {/* Tier cards */}
            <Grid size={{ xs: 12, sm: 9, md: 4 }}>
              <Grid container spacing={1}>
                {(['critical', 'high', 'medium'] as SlaTier[]).map((tier) => {
                  const t = sla?.tiers.find((x) => x.tier === tier);
                  return (
                    <Grid size={12} key={tier}>
                      <TierCard
                        tier={tier}
                        onTime={t?.on_time ?? 0}
                        breached={t?.breached ?? 0}
                        total={t?.total ?? 0}
                        slaHours={t?.sla_hours ?? 0}
                        loading={loading}
                      />
                    </Grid>
                  );
                })}
              </Grid>
            </Grid>

            {/* Breached list */}
            <Grid size={{ xs: 12, md: 6 }}>
              <Typography variant="overline" sx={{ fontWeight: 700, color: 'text.secondary', display: 'block', mb: 1 }}>
                Нарушения SLA (Breached)
              </Typography>

              {loading ? (
                [1, 2, 3].map((i) => (
                  <Paper key={i} variant="outlined" sx={{ p: 1.5, mb: 1, borderRadius: 2 }}>
                    <Skeleton width="70%" height={18} />
                    <Skeleton width="40%" height={14} sx={{ mt: 0.5 }} />
                  </Paper>
                ))
              ) : breaches.length === 0 ? (
                <EmptyState
                  icon={<CheckCircle sx={{ fontSize: 28, color: 'success.main' }} />
}
                  title="Нарушений SLA нет"
                  description="Все уязвимости закрываются в срок."
                />
              ) : (
                <>
                  <TableContainer component={Paper} elevation={0} sx={{ borderRadius: 2, border: 1, borderColor: 'divider' }}>
                    <Table size="small">
                      <TableHead sx={{ bgcolor: 'action.hover' }}>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Уязвимость</TableCell>
                          <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Класс</TableCell>
                          <TableCell sx={{ fontWeight: 600, fontSize: 11 }}>Статус</TableCell>
                          <TableCell sx={{ fontWeight: 600, fontSize: 11 }} align="right" />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {visibleBreaches.map((b: SlaBreach) => {
                          const meta = TIER_META[b.tier];
                          return (
                            <TableRow key={b.id} hover>
                              <TableCell sx={{ fontSize: 12, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                  <meta.icon sx={{ color: meta.color, fontSize: 14, flexShrink: 0 }} />
                                  <span>{b.title}</span>
                                </Box>
                              </TableCell>
                              <TableCell>
                                <Chip
                                  label={meta.label}
                                  size="small"
                                  sx={{ fontSize: 9, height: 18, bgcolor: meta.bg, color: meta.color, fontWeight: 700 }}
                                />
                              </TableCell>
                              <TableCell>
                                <Chip
                                  icon={<AccessTime sx={{ fontSize: 11 }} />}
                                  label={overdueLabel(b.overdue_hours)}
                                  size="small"
                                  color="error"
                                  variant="outlined"
                                  sx={{ fontSize: 9, height: 20 }}
                                />
                              </TableCell>
                              <TableCell align="right">
                                {onNavigateToIDE && (
                                  <Tooltip title={`Открыть ${b.file}:${b.line}`}>
                                    <IconButton
                                      size="small"
                                      onClick={() => onNavigateToIDE({ repo: b.repo, file: b.file, line: b.line })}
                                      sx={{ color: 'text.secondary' }}
                                    >
                                      <OpenInNew sx={{ fontSize: 14 }} />
                                    </IconButton>
                                  </Tooltip>
                                )}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>

                  {breaches.length > 3 && (
                    <Button
                      size="small"
                      onClick={() => setExpanded(!expanded)}
                      sx={{ mt: 1, textTransform: 'none', fontSize: 12 }}
                    >
                      {expanded ? `Свернуть (показать 3)` : `Показать все ${breaches.length} нарушений`}
                    </Button>
                  )}
                </>
              )}
            </Grid>
          </Grid>

          {/* Footer */}
          {!loading && sla && (
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
              <Typography variant="caption" color="text.disabled">
                Обновлено: {new Date(sla.last_updated).toLocaleString('ru-RU')}
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </ErrorBoundary>
  );
}