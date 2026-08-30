/**
 * COS-062: Analytics & Run Metrics Trend Dashboard.
 *
 * Visual trends: Pass Rate, Findings Severity Over Time, Run Duration,
 * and Flaky Gates heatmap.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, Card, CardContent, Grid,
  Divider, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, MenuItem,
} from '@mui/material';
import {
  Refresh, TrendingUp, TrendingDown, TrendingFlat,
  CheckCircle, Timer, BugReport, Gavel,
} from '@mui/icons-material';
import { api, type MetricsTrends, type TrendDataPoint } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

// ── Sparkline SVG component ───────────────────────────────────────────

function Sparkline({ points, width = 220, height = 40, color = '#0EA5E9' }: {
  points: TrendDataPoint[]; width?: number; height?: number; color?: string;
}) {
  if (points.length < 2) {
    return (
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
        <text x={width / 2} y={height / 2 + 4} textAnchor="middle" fill="#94A3B8" fontSize={10}>
          Недостаточно данных
        </text>
      </svg>
    );
  }

  const max = Math.max(...points.map((p) => p.value), 1);
  const min = Math.min(...points.map((p) => p.value), 0);
  const range = max - min || 1;
  const stepX = (width - 16) / (points.length - 1);

  const pointsStr = points
    .map((p, i) => {
      const x = 8 + i * stepX;
      const y = height - 8 - ((p.value - min) / range) * (height - 16);
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <polyline
        points={pointsStr}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {points.map((p, i) => {
        const x = 8 + i * stepX;
        const y = height - 8 - ((p.value - min) / range) * (height - 16);
        return <circle key={i} cx={x} cy={y} r={2} fill={color} opacity={i === 0 || i === points.length - 1 ? 0.9 : 0.4} />;
      })}
    </svg>
  );
}

// ── Severity Heatmap Bars ─────────────────────────────────────────────

function SeverityBars({ trends }: { trends: Array<{ date: string; critical: number; high: number; medium: number }> }) {
  if (trends.length === 0) return <Typography variant="caption" color="text.secondary">Нет данных о находках</Typography>;

  const last14 = trends.slice(-14);
  const maxVal = Math.max(
    ...last14.flatMap((d) => [d.critical, d.high, d.medium]),
    1
  );

  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 56, mt: 0.5 }}>
      {last14.map((d) => (
        <Box key={d.date} sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <Box
              sx={{
                width: 5, borderRadius: 1,
                height: `${Math.max((d.medium / maxVal) * 44, 2)}px`,
                bgcolor: 'primary.light',
              }}
              title="Medium"
            />
            <Box
              sx={{
                width: 5, borderRadius: 1,
                height: `${Math.max((d.high / maxVal) * 44, 2)}px`,
                bgcolor: 'warning.main',
              }}
              title="High"
            />
            <Box
              sx={{
                width: 5, borderRadius: 1,
                height: `${Math.max((d.critical / maxVal) * 44, 2)}px`,
                bgcolor: 'error.main',
              }}
              title="Critical"
            />
          </Box>
          <Typography variant="caption" sx={{ fontSize: 8, color: 'text.disabled', transform: 'rotate(-30deg)', mt: 0.3 }}>
            {d.date.slice(5)}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

// ── Main Component ─────────────────────────────────────────────────────

interface AnalyticsProps {
}

export function Analytics({}: AnalyticsProps) {
  const [trends, setTrends] = useState<MetricsTrends | null>(null);
  const [daysFilter, setDaysFilter] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrends = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getMetricsTrends(undefined, daysFilter);
      setTrends(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки метрик';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [daysFilter]);

  useEffect(() => {
    fetchTrends();
  }, [fetchTrends]);

  const passRateTrend = (trends?.pass_rate_trend || []) as TrendDataPoint[];
  const lastPassRate = passRateTrend.length > 0 ? passRateTrend[passRateTrend.length - 1].value : 0;
  const prevPassRate = passRateTrend.length > 1 ? passRateTrend[passRateTrend.length - 2].value : lastPassRate;
  const passRateDelta = lastPassRate - prevPassRate;

  const durTrend = (trends?.mean_duration_trend || []) as TrendDataPoint[];
  const lastDur = durTrend.length > 0 ? durTrend[durTrend.length - 1].value : 0;
  const prevDur = durTrend.length > 1 ? durTrend[durTrend.length - 2].value : lastDur;
  const durDelta = prevDur > 0 ? ((lastDur - prevDur) / prevDur) * 100 : 0;

  return (
    <ErrorBoundary viewName="Аналитика (Analytics)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Аналитика и Тренды Безопасности
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Динамика устранения уязвимостей, Pass Rate прогонов, длительность пайплайна, сбойные гейты.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <TextField
              select
              value={daysFilter}
              onChange={(e) => setDaysFilter(Number(e.target.value))}
              size="small"
              sx={{ minWidth: 120 }}
            >
              <MenuItem value={7}>7 дней</MenuItem>
              <MenuItem value={14}>14 дней</MenuItem>
              <MenuItem value={30}>30 дней</MenuItem>
              <MenuItem value={90}>90 дней</MenuItem>
            </TextField>
            <Tooltip title="Обновить метрики">
              <IconButton onClick={fetchTrends} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Summary KPI Cards */}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Pass Rate (Успешность)
                  </Typography>
                  <CheckCircle sx={{ color: lastPassRate >= 70 ? 'success.main' : 'warning.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={80} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mt: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700 }}>
                      {lastPassRate.toFixed(0)}%
                    </Typography>
                    {passRateTrend.length > 1 && (
                      <Box sx={{ display: 'flex', alignItems: 'center', color: passRateDelta >= 0 ? 'success.main' : 'error.main', fontSize: 12, fontWeight: 700 }}>
                        {passRateDelta >= 0 ? <TrendingUp sx={{ fontSize: 16 }} /> : <TrendingDown sx={{ fontSize: 16 }} />}
                        {passRateDelta >= 0 ? '+' : ''}{passRateDelta.toFixed(0)}%
                      </Box>
                    )}
                  </Box>
                )}
                <Typography variant="caption" color="text.secondary">
                  {trends?.summary.total_runs || 0} всего прогонов за {daysFilter} дн.
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Критических уязвимостей
                  </Typography>
                  <BugReport sx={{ color: 'error.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Typography variant="h4" sx={{ fontWeight: 700, mt: 1, color: trends && trends.summary.total_critical_findings > 0 ? 'error.main' : 'text.primary' }}>
                    {trends?.summary.total_critical_findings ?? 0}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">
                  Суммарно за период High + Medium
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Среднее время прогона
                  </Typography>
                  <Timer sx={{ color: 'info.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={80} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mt: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700 }}>
                      {lastDur < 60 ? `${lastDur.toFixed(0)}s` : `${(lastDur / 60).toFixed(1)}m`}
                    </Typography>
                    {durTrend.length > 1 && (
                      <Box sx={{ display: 'flex', alignItems: 'center', fontSize: 12, fontWeight: 700, color: durDelta <= 0 ? 'success.main' : durDelta > 10 ? 'error.main' : 'text.secondary' }}>
                        {durDelta <= 0 ? <TrendingDown sx={{ fontSize: 16 }} /> : <TrendingUp sx={{ fontSize: 16 }} />}
                        {durDelta > 0 ? '+' : ''}{durDelta.toFixed(0)}%
                      </Box>
                    )}
                  </Box>
                )}
                <Typography variant="caption" color="text.secondary">
                  {durDelta <= 0 ? 'Быстрее на' : 'Медленнее на'}: <strong>{Math.abs(durDelta).toFixed(0)}%</strong>
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Сбойных гейтов
                  </Typography>
                  <Gavel sx={{ color: 'warning.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={40} sx={{ mt: 0.5 }} />
                ) : (
                  <Typography variant="h4" sx={{ fontWeight: 700, mt: 1, color: (trends?.flaky_gates.length || 0) > 0 ? 'warning.main' : 'text.primary' }}>
                    {trends?.flaky_gates.length ?? 0}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">
                  Гейты с block_rate {'>'} 0%
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Sparklines Row */}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Динамика Pass Rate (%)
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  {passRateTrend.length > 1 && (
                    passRateDelta >= 0
                      ? <Chip icon={<TrendingUp />} label="Растёт" size="small" color="success" sx={{ fontSize: 10, height: 20 }} />
                      : <Chip icon={<TrendingDown />} label="Падает" size="small" color="error" sx={{ fontSize: 10, height: 20 }} />
                  )}
                </Box>
              </Box>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
                {loading ? (
                  <Skeleton variant="rectangular" width={380} height={52} />
                ) : passRateTrend.length > 0 ? (
                  <Sparkline
                    points={passRateTrend}
                    width={400}
                    height={52}
                    color={passRateDelta >= 0 ? '#10B981' : '#EF4444'}
                  />
                ) : (
                  <EmptyState icon={<TrendingFlat sx={{ fontSize: 24 }} />} title="Нет данных Pass Rate" description="Запустите несколько прогонов для накопления статистики." />
                )}
              </Box>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Средняя длительность прогона (сек)
                </Typography>
              </Box>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
                {loading ? (
                  <Skeleton variant="rectangular" width={380} height={52} />
                ) : durTrend.length > 0 ? (
                  <Sparkline points={durTrend} width={400} height={52} color="#3B82F6" />
                ) : (
                  <EmptyState icon={<Timer sx={{ fontSize: 24 }} />} title="Нет данных о длительности" description="Прогоны с заполненными метками started_at/finished_at появятся здесь." />
                )}
              </Box>
            </Card>
          </Grid>
        </Grid>

        {/* Severity Bars + Flaky Gates */}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Уязвимости по критичности
                </Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 8, height: 8, borderRadius: 1, bgcolor: 'error.main' }} />
                    <Typography variant="caption">Crit</Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 8, height: 8, borderRadius: 1, bgcolor: 'warning.main' }} />
                    <Typography variant="caption">High</Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 8, height: 8, borderRadius: 1, bgcolor: 'primary.light' }} />
                    <Typography variant="caption">Med</Typography>
                  </Box>
                </Box>
              </Box>
              <Box sx={{ p: 2, overflowX: 'auto' }}>
                {loading ? (
                  <Skeleton variant="rectangular" height={72} />
                ) : (
                  <SeverityBars trends={trends?.findings_severity_trend || []} />
                )}
              </Box>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
<Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Сбойные Security Gates
                </Typography>
                <Chip label={`Топ ${trends?.flaky_gates.length || 0}`} size="small" variant="outlined" sx={{ fontSize: 10, height: 20 }} />
              </Box>
              <TableContainer>
                <Table size="small">
                  <TableHead sx={{ bgcolor: 'action.hover' }}>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 600 }}>Gate ID</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Решений</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Block Rate</TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>Pass / Block</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      [1, 2, 3].map((i) => (
                        <TableRow key={i}>
                          <TableCell><Skeleton width={90} /></TableCell>
                          <TableCell><Skeleton width={50} /></TableCell>
                          <TableCell><Skeleton width={60} /></TableCell>
                          <TableCell><Skeleton width={80} /></TableCell>
                        </TableRow>
                      ))
                    ) : (trends?.flaky_gates.length || 0) === 0 ? (
                      <TableRow>
                        <TableCell colSpan={4} sx={{ p: 0 }}>
                          <EmptyState
                            icon={<Gavel sx={{ fontSize: 24 }} />}
                            title="Сбойные гейты отсутствуют"
                            description="Все гейты работают стабильно без блокировок."
                          />
                        </TableCell>
                      </TableRow>
                    ) : (
                      trends!.flaky_gates.map((g) => (
                        <TableRow key={g.gate_id} hover>
                          <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 12 }}>
                            {g.gate_id}
                          </TableCell>
                          <TableCell sx={{ fontSize: 12 }}>{g.total_decisions}</TableCell>
                          <TableCell>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Box
                                sx={{
                                  height: 6, borderRadius: 3,
                                  width: `${Math.min(g.block_rate, 100)}%`,
                                  maxWidth: 60, bgcolor: g.block_rate > 50 ? 'error.main' : g.block_rate > 20 ? 'warning.main' : 'success.main',
                                }}
                              />
                              <Typography variant="caption" sx={{ fontWeight: 700 }}>
                                {g.block_rate}%
                              </Typography>
                            </Box>
                          </TableCell>
                          <TableCell sx={{ fontSize: 11, fontFamily: 'monospace' }}>
                            {g.passes} ✓ / {g.blocks} �
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Card>
          </Grid>
        </Grid>

        {/* Last Updated Footer */}
        {trends?.summary.last_updated && (
          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Typography variant="caption" color="text.disabled">
              Данные обновлены: {new Date(trends.summary.last_updated).toLocaleString()}
            </Typography>
          </Box>
        )}
      </Box>
    </ErrorBoundary>
  );
}