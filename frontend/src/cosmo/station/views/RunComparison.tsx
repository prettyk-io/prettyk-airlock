/**
 * COS-070: Run Comparison Diff View.
 *
 * Side-by-side comparison of two pipeline runs (Base vs Target).
 * Shows regression analysis, findings diff, and batch timeline comparison.
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, TextField, MenuItem, Card, CardContent,
  Grid, Divider, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow,
} from '@mui/material';
import {
  Refresh, Compare, ArrowUpward, ArrowDownward,
  TrendingUp, TrendingDown, RemoveCircle,
  BugReport, CheckCircle, Warning, HourglassEmpty,
  PlayArrow, Timer,
} from '@mui/icons-material';
import { api, type Run, type Batch } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

// ── Types ─────────────────────────────────────────────────────────────

interface RunComparisonProps {
  initialBaseRunId?: string;
  initialTargetRunId?: string;
}

interface FindingEntry {
  id: string;
  severity: 'Critical' | 'High' | 'Medium' | 'Low' | 'Info';
  title: string;
  cwe: string;
  location: string;
  scanType: 'sast' | 'dast' | 'sca';
}

type FindingDiff = {
  finding: FindingEntry;
  status: 'new_regression' | 'fixed' | 'persistent';
};

// ── Mock Findings ─────────────────────────────────────────────────────

function generateFindings(seed: string): FindingEntry[] {
  const base: FindingEntry[] = [
    { id: `${seed}-f01`, severity: 'Critical', title: 'SQL Injection in /api/auth/login', cwe: 'CWE-89', location: 'app/auth/login.py:42', scanType: 'sast' },
    { id: `${seed}-f02`, severity: 'High', title: 'Stored XSS in User Profile', cwe: 'CWE-79', location: 'app/views/profile.html:156', scanType: 'sast' },
    { id: `${seed}-f03`, severity: 'High', title: 'Hardcoded JWT Secret', cwe: 'CWE-798', location: 'app/config/auth.py:12', scanType: 'sast' },
    { id: `${seed}-f04`, severity: 'Medium', title: 'Missing Content-Security-Policy Header', cwe: 'CWE-693', location: 'nginx.conf', scanType: 'dast' },
    { id: `${seed}-f05`, severity: 'Medium', title: 'Open S3 Bucket Permissions', cwe: 'CWE-200', location: 'terraform/s3.tf', scanType: 'sca' },
    { id: `${seed}-f06`, severity: 'Low', title: 'Cookie without HttpOnly flag', cwe: 'CWE-1004', location: 'app/middleware/session.py:89', scanType: 'sast' },
  ];

  if (seed === 'base') {
    return base;
  }

  // Target run: fix 2, add 2 new
  const target = [...base];
  // Fix the JWT secret and the XSS
  target.splice(2, 1);
  target.splice(1, 1);
  // Add new regressions
  target.push(
    { id: `${seed}-nf1`, severity: 'Critical', title: 'Remote Code Execution in /api/admin/upload', cwe: 'CWE-94', location: 'app/admin/upload.py:78', scanType: 'dast' },
    { id: `${seed}-nf2`, severity: 'High', title: 'SSRF via Webhook Endpoint', cwe: 'CWE-918', location: 'app/webhooks/dispatch.py:23', scanType: 'dast' },
  );
  return target;
}

const BASE_FINDINGS = generateFindings('base');
const TARGET_FINDINGS = generateFindings('target');

function computeFindingsDiff(base: FindingEntry[], target: FindingEntry[]): FindingDiff[] {
  const baseTitles = new Set(base.map((f) => f.title));
  const targetTitles = new Set(target.map((f) => f.title));

  const diffs: FindingDiff[] = [];

  target.forEach((f) => {
    diffs.push({
      finding: f,
      status: baseTitles.has(f.title) ? 'persistent' : 'new_regression',
    });
  });

  base.forEach((f) => {
    if (!targetTitles.has(f.title)) {
      diffs.push({ finding: f, status: 'fixed' });
    }
  });

  return diffs.sort((a, b) => {
    const order = { new_regression: 0, persistent: 1, fixed: 2 };
    return order[a.status] - order[b.status];
  });
}

// ── Mock Batches with timing ──────────────────────────────────────────

function generateBatches(runId: string, durationBias: number): Batch[] {
  const bias = runId === 'target' ? durationBias : 1;
  return [
    { id: `b-build-${runId}`, plan_id: 'plan-steel', type: 'build', status: 'passed', bricks: ['b-build'], artifacts: [], evidence: [] },
    { id: `b-sast-${runId}`, plan_id: 'plan-steel', type: 'static_scan', status: runId === 'base' ? 'passed' : 'passed', bricks: ['b-sast'], artifacts: [], evidence: [] },
    { id: `b-dast-${runId}`, plan_id: 'plan-steel', type: 'dynamic_test', status: runId === 'base' ? 'passed' : 'passed', bricks: ['b-dast'], artifacts: [], evidence: [] },
    { id: `b-deploy-${runId}`, plan_id: 'plan-steel', type: 'deploy', status: runId === 'base' ? 'failed' : 'passed', bricks: ['b-deploy'], artifacts: [], evidence: [] },
  ];
}

const BATCH_DURATIONS_BASE: Record<string, number> = { 'b-build-base': 34, 'b-sast-base': 128, 'b-dast-base': 245, 'b-deploy-base': 18 };
const BATCH_DURATIONS_TARGET: Record<string, number> = { 'b-build-target': 31, 'b-sast-target': 142, 'b-dast-target': 198, 'b-deploy-target': 45 };

// ── Component ──────────────────────────────────────────────────────────

export function RunComparison({ initialBaseRunId, initialTargetRunId }: RunComparisonProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [baseRunId, setBaseRunId] = useState(initialBaseRunId || 'run-101');
  const [targetRunId, setTargetRunId] = useState(initialTargetRunId || 'run-102');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getRuns();
      setRuns(data || []);
      if (data && data.length >= 2) {
        if (!baseRunId || !data.find((r) => r.id === baseRunId)) {
          setBaseRunId(data[0].id);
        }
        if (!targetRunId || !data.find((r) => r.id === targetRunId)) {
          setTargetRunId(data.length >= 2 ? data[1].id : data[0].id);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки прогонов';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [baseRunId, targetRunId]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  const swapRuns = () => {
    setBaseRunId(targetRunId);
    setTargetRunId(baseRunId);
  };

  // ── Compute diff data ───────────────────────────────────────────────
  const baseFindings = baseRunId === 'run-101' ? BASE_FINDINGS : TARGET_FINDINGS;
  const targetFindings = targetRunId === 'run-102' ? TARGET_FINDINGS : BASE_FINDINGS;

  const findingsDiff = useMemo(
    () => computeFindingsDiff(baseFindings, targetFindings),
    [baseRunId, targetRunId]
  );

  const baseBatches = generateBatches('base', 1);
  const targetBatches = generateBatches('target', 1.2);

  const newRegressions = findingsDiff.filter((d) => d.status === 'new_regression').length;
  const fixedFindings = findingsDiff.filter((d) => d.status === 'fixed').length;
  const persistentFindings = findingsDiff.filter((d) => d.status === 'persistent').length;

  // ── Batch timeline comparison ───────────────────────────────────────
  const batchTypes = ['build', 'static_scan', 'dynamic_test', 'deploy'];

  return (
    <ErrorBoundary viewName="Сравнение прогонов (Run Comparison)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Сравнительный анализ прогонов (Run Diff)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Мгновенный анализ регрессий безопасности: новые уязвимости, исправления дельты времени выполнения шагов.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить список прогонов">
              <IconButton onClick={fetchRuns} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Compare />}
              onClick={swapRuns}
              disabled={loading}
              sx={{ textTransform: 'none' }}
            >
              Поменять местами
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Base vs Target Selectors */}
        <Grid container spacing={2} sx={{ alignItems: 'center' }}>
          <Grid size={{ xs: 12, md: 5 }}>
            <Card variant="outlined" sx={{ borderRadius: 2, p: 2, bgcolor: 'action.hover' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <Chip icon={<ArrowUpward />} label="BASE" color="primary" size="small" sx={{ fontWeight: 700 }} />
                <TextField
                  select
                  value={baseRunId}
                  onChange={(e) => setBaseRunId(e.target.value)}
                  size="small"
                  fullWidth
                  label="Базовый прогон (Base Run)"
                >
                  {runs.map((r) => (
                    <MenuItem key={r.id} value={r.id}>
                      {r.id} — {r.plan_id} ({r.status})
                    </MenuItem>
                  ))}
                </TextField>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Эталонный прогон, относительно которого сравниваем.
              </Typography>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 2 }} sx={{ display: 'flex', justifyContent: 'center' }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
              <Compare sx={{ fontSize: 36, color: 'primary.main' }} />
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                VS
              </Typography>
            </Box>
          </Grid>

          <Grid size={{ xs: 12, md: 5 }}>
            <Card variant="outlined" sx={{ borderRadius: 2, p: 2, bgcolor: 'action.hover' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <Chip icon={<ArrowDownward />} label="TARGET" color="warning" size="small" sx={{ fontWeight: 700 }} />
                <TextField
                  select
                  value={targetRunId}
                  onChange={(e) => setTargetRunId(e.target.value)}
                  size="small"
                  fullWidth
                  label="Целевой прогон (Target Run)"
                >
                  {runs.map((r) => (
                    <MenuItem key={r.id} value={r.id}>
                      {r.id} — {r.plan_id} ({r.status})
                    </MenuItem>
                  ))}
                </TextField>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Проверяемый прогон на наличие регрессий.
              </Typography>
            </Card>
          </Grid>
        </Grid>

        {/* Summary Delta Cards */}
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2, borderColor: newRegressions > 0 ? 'error.light' : 'divider' }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Новые уязвимости (Регрессии)
                  </Typography>
                  <BugReport sx={{ color: 'error.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={40} height={36} sx={{ mt: 0.5 }} />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mt: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700, color: newRegressions > 0 ? 'error.main' : 'success.main' }}>
                      +{newRegressions}
                    </Typography>
                    <TrendingUp sx={{ color: newRegressions > 0 ? 'error.main' : 'text.disabled', fontSize: 20 }} />
                  </Box>
                )}
                <Typography variant="caption" color="text.secondary">
                  {newRegressions === 0 ? 'Регрессий не обнаружено' : 'Требуют немедленного исправления'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2, borderColor: fixedFindings > 0 ? 'success.light' : 'divider' }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Исправлено (Fixed)
                  </Typography>
                  <CheckCircle sx={{ color: 'success.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={40} height={36} sx={{ mt: 0.5 }} />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mt: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700, color: 'success.main' }}>
                      -{fixedFindings}
                    </Typography>
                    <TrendingDown sx={{ color: 'success.main', fontSize: 20 }} />
                  </Box>
                )}
                <Typography variant="caption" color="text.secondary">
                  {fixedFindings === 0 ? 'Нет устранённых находок' : 'Устранены в целевом прогоне'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Без изменений (Persistent)
                  </Typography>
                  <RemoveCircle sx={{ color: 'text.secondary', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={40} height={36} sx={{ mt: 0.5 }} />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mt: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700 }}>
                      ={persistentFindings}
                    </Typography>
                  </Box>
                )}
                <Typography variant="caption" color="text.secondary">
                  Присутствуют в обоих прогонах
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, sm: 6, md: 3 }}>
            <Card variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Время выполнения
                  </Typography>
                  <Timer sx={{ color: 'info.main', fontSize: 20 }} />
                </Box>
                {loading ? (
                  <Skeleton width={60} height={36} sx={{ mt: 0.5 }} />
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mt: 1 }}>
                    <Typography variant="h4" sx={{ fontWeight: 700 }}>
                      {(() => {
                        const baseTotal = Object.values(BATCH_DURATIONS_BASE).reduce((a, b) => a + b, 0);
                        const targetTotal = Object.values(BATCH_DURATIONS_TARGET).reduce((a, b) => a + b, 0);
                        const delta = targetTotal - baseTotal;
                        return `${delta > 0 ? '+' : ''}${delta}s`;
                      })()}
                    </Typography>
                    <TrendingDown sx={{ color: 'success.main', fontSize: 20 }} />
                  </Box>
                )}
                <Typography variant="caption" color="text.secondary">
                  Δ общего времени пайплайна
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {/* Findings Diff Table */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              Построчный дифф находок (Findings Diff)
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Chip label={`+${newRegressions} NEW`} size="small" sx={{ bgcolor: 'error.lighter', color: 'error.main', fontWeight: 700, fontSize: 11 }} />
              <Chip label={`-${fixedFindings} FIXED`} size="small" sx={{ bgcolor: 'success.lighter', color: 'success.main', fontWeight: 700, fontSize: 11 }} />
              <Chip label={`=${persistentFindings} SAME`} size="small" sx={{ bgcolor: 'action.hover', fontWeight: 700, fontSize: 11 }} />
            </Box>
          </Box>
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead sx={{ bgcolor: 'action.hover' }}>
                <TableRow>
                  <TableCell sx={{ width: 80, fontWeight: 600 }}>Статус</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Критичность</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Наименование находки</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>CWE</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Локация</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Скан</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  [1, 2, 3, 4, 5].map((i) => (
                    <TableRow key={i}>
                      <TableCell><Skeleton width={50} /></TableCell>
                      <TableCell><Skeleton width={60} /></TableCell>
                      <TableCell><Skeleton width={180} /></TableCell>
                      <TableCell><Skeleton width={70} /></TableCell>
                      <TableCell><Skeleton width={140} /></TableCell>
                      <TableCell><Skeleton width={40} /></TableCell>
                    </TableRow>
                  ))
                ) : findingsDiff.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} sx={{ p: 0 }}>
                      <EmptyState
                        icon={<BugReport sx={{ fontSize: 28 }} />}
                        title="Нет находок для сравнения"
                        description="В обоих прогонах отутствуют зарегестрированные уязвимости."
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  findingsDiff.map((d) => {
                    const isNew = d.status === 'new_regression';
                    const isFixed = d.status === 'fixed';
                    return (
                      <TableRow
                        key={d.finding.id}
                        sx={{
                          bgcolor: isNew ? 'error.lighter' : isFixed ? 'success.lighter' : 'transparent',
                          borderLeft: isNew ? '4px solid #EF4444' : isFixed ? '4px solid #10B981' : '4px solid transparent',
                        }}
                      >
                        <TableCell>
                          {isNew ? (
                            <Chip
                              icon={<BugReport sx={{ fontSize: 12 }} />}
                              label="NEW"
                              size="small"
                              color="error"
                              sx={{ fontSize: 10, height: 18, fontWeight: 700 }}
                            />
                          ) : isFixed ? (
                            <Chip
                              icon={<CheckCircle sx={{ fontSize: 12 }} />}
                              label="FIXED"
                              size="small"
                              color="success"
                              sx={{ fontSize: 10, height: 18, fontWeight: 700 }}
                            />
                          ) : (
                            <Chip
                              icon={<RemoveCircle sx={{ fontSize: 12 }} />}
                              label="SAME"
                              size="small"
                              variant="outlined"
                              sx={{ fontSize: 10, height: 18 }}
                            />
                          )}
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={d.finding.severity}
                            size="small"
                            color={
                              d.finding.severity === 'Critical' ? 'error' :
                              d.finding.severity === 'High' ? 'warning' :
                              d.finding.severity === 'Medium' ? 'info' : 'default'
                            }
                            sx={{ fontSize: 10, height: 18, fontWeight: 700 }}
                          />
                        </TableCell>
                        <TableCell sx={{ fontSize: 12, fontWeight: 600 }}>
                          {d.finding.title}
                        </TableCell>
                        <TableCell sx={{ fontSize: 11, fontFamily: 'monospace', color: 'text.secondary' }}>
                          {d.finding.cwe}
                        </TableCell>
                        <TableCell sx={{ fontSize: 11, fontFamily: 'monospace', color: 'text.secondary' }}>
                          {d.finding.location}
                        </TableCell>
                        <TableCell>
                          <Chip label={d.finding.scanType.toUpperCase()} size="small" variant="outlined" sx={{ fontSize: 9, height: 18 }} />
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>

        {/* Batch Timeline Comparison */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              Сравнение длительности шагов DAG (Batch Timeline)
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 12, height: 12, borderRadius: 0.5, bgcolor: 'primary.main' }} />
                <Typography variant="caption">Base Run</Typography>
              </Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 12, height: 12, borderRadius: 0.5, bgcolor: 'warning.main' }} />
                <Typography variant="caption">Target Run</Typography>
              </Box>
            </Box>
          </Box>
          <Box sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {batchTypes.map((bt) => {
              const baseBatch = baseBatches.find((b) => b.type === bt || (bt === 'static_scan' && b.type === 'static_scan') || (bt === 'dynamic_test' && b.type === 'dynamic_test'));
              const targetBatch = targetBatches.find((b) => b.type === bt || (bt === 'static_scan' && b.type === 'static_scan') || (bt === 'dynamic_test' && b.type === 'dynamic_test'));
              const baseDuration = baseBatch ? (BATCH_DURATIONS_BASE[baseBatch.id] || 0) : 0;
              const targetDuration = targetBatch ? (BATCH_DURATIONS_TARGET[targetBatch.id] || 0) : 0;
              const maxDuration = Math.max(baseDuration, targetDuration, 1);
              const delta = targetDuration - baseDuration;
              const deltaColor = delta < 0 ? 'success.main' : delta > 0 ? 'warning.main' : 'text.secondary';

              return (
                <Box key={bt}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5, fontSize: 12 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Chip
                        label={bt.replace('_', ' ').toUpperCase()}
                        size="small"
                        variant="outlined"
                        sx={{ fontSize: 10, height: 20, fontWeight: 700 }}
                      />
                      {baseBatch && (
                        <Chip
                          label={baseBatch.status}
                          size="small"
                          color={baseBatch.status === 'passed' ? 'success' : 'error'}
                          sx={{ fontSize: 9, height: 16 }}
                        />
                      )}
                    </Box>
                    <Typography variant="caption" sx={{ fontWeight: 700, color: deltaColor }}>
                      Δ {delta > 0 ? `+${delta}s` : delta < 0 ? `${delta}s` : '0s'}
                    </Typography>
                  </Box>

                  {/* Base Run Bar */}
                  <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
                    <Typography variant="caption" sx={{ width: 50, fontSize: 10, color: 'text.secondary' }}>
                      Base
                    </Typography>
                    <Box sx={{ flex: 1, height: 20, borderRadius: 1, bgcolor: 'action.hover', position: 'relative', overflow: 'hidden' }}>
                      <Box
                        sx={{
                          height: '100%',
                          width: `${(baseDuration / maxDuration) * 100}%`,
                          borderRadius: 1,
                          bgcolor: 'primary.main',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'flex-end',
                          px: 1,
                          minWidth: 40,
                        }}
                      >
                        <Typography variant="caption" sx={{ color: 'white', fontWeight: 700, fontSize: 10 }}>
                          {baseDuration}s
                        </Typography>
                      </Box>
                    </Box>
                  </Box>

                  {/* Target Run Bar */}
                  <Box sx={{ display: 'flex', alignItems: 'center' }}>
                    <Typography variant="caption" sx={{ width: 50, fontSize: 10, color: 'text.secondary' }}>
                      Target
                    </Typography>
                    <Box sx={{ flex: 1, height: 20, borderRadius: 1, bgcolor: 'action.hover', position: 'relative', overflow: 'hidden' }}>
                      <Box
                        sx={{
                          height: '100%',
                          width: `${(targetDuration / maxDuration) * 100}%`,
                          borderRadius: 1,
                          bgcolor: 'warning.main',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'flex-end',
                          px: 1,
                          minWidth: 40,
                        }}
                      >
                        <Typography variant="caption" sx={{ color: 'white', fontWeight: 700, fontSize: 10 }}>
                          {targetDuration}s
                        </Typography>
                      </Box>
                    </Box>
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Card>
      </Box>
    </ErrorBoundary>
  );
}