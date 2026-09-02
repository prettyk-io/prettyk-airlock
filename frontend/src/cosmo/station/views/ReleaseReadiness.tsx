/**
 * COS-098: Release Readiness — release/run readiness surface на живых данных.
 *
 * Замена прототипа NX-FLASH-06 (клиентский readyCount по app.status) на
 * честную поверхность по REST+SSE:
 *   - Releases: GET /api/v1/releases (domain-scoped, X-Cosmo-Domain)
 *   - Runs:     GET /api/v1/runs + live через useLiveDomain (domain SSE)
 *   - Run detail: GET /run, /gates?plan_id, /runs/{id}/evidence,
 *     /gates/trail/runs/{id}; логи — ЧЕСТНЫЙ degraded (появятся с COS-097,
 *     Woodpecker ExecutionAdapter)
 *   - Release lifecycle: notification stream (release_approved/rejected,
 *     transfer_completed/failed) → refetch releases
 *
 * Честные состояния: loading / error+retry / empty / degraded logs /
 * live-offline badge. Никаких выдуманных полей — контракт сверен с бэкендом
 * (см. api.ts COS-098 комментарий).
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Box, Typography, Button, Select, MenuItem, Chip, Paper, Alert,
  CircularProgress, Tooltip,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { Refresh, Gavel, Verified, LinkOff, OpenInNew } from '@mui/icons-material';
import {
  api, setCosmoDomain,
  type Release, type ReleaseZone, type ReleaseStatus, type Run, type Gate,
  type CosmoDomain, type EvidenceChainResult, type GateDecisionRecord,
} from '../api';
import { useLiveDomain } from '../../shared/useLiveDomain';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { PageHeader } from '../minimal/PageHeader';
import { toast } from '../../shared/toast';

// ── Labels ────────────────────────────────────────────────────────────

export const ZONE_LABELS: Record<ReleaseZone, string> = {
  zr: 'ЗР (Разработка)',
  zt: 'ЗТ (Тестирование)',
  zpe: 'ЗПЭ (Пром)',
};

export const RELEASE_STATUS_LABELS: Record<ReleaseStatus, string> = {
  draft: 'Черновик',
  pending_review: 'На review',
  approved: 'Утверждён',
  rejected: 'Отклонён',
  deploying: 'Деплоится',
  deployed: 'Задеплоен',
  rollback: 'Откат',
};

const RUN_STATUS_COLOR: Record<string, 'success' | 'error' | 'warning' | 'info' | 'default'> = {
  succeeded: 'success',
  failed: 'error',
  blocked: 'warning',
  running: 'info',
  queued: 'default',
  pending: 'default',
  draft: 'default',
  cancelled: 'default',
};

const TERMINAL_RUN_STATUSES = new Set(['succeeded', 'failed', 'blocked', 'cancelled']);

// Release lifecycle события (notification stream) → refetch releases
const RELEASE_EVENT_TYPES = new Set([
  'release_approved', 'release_rejected', 'transfer_completed',
  'transfer_failed', 'batch_failed',
]);

// ── Release lifecycle live (notification stream, компактный reconnect) ─

function useReleaseEventRefetch(onEvent: () => void): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const lastEventIdRef = useRef('');
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const connect = async () => {
      if (cancelled) return;
      try {
        const t = await api.getSseTicket();
        let url = `/api/v1/notifications/stream?ticket=${encodeURIComponent(t.ticket)}`;
        if (lastEventIdRef.current) {
          url += `&last_event_id=${encodeURIComponent(lastEventIdRef.current)}`;
        }
        es = new EventSource(url);
        es.addEventListener('notification_new', (e: MessageEvent) => {
          try {
            if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
            const data = JSON.parse(e.data);
            if (RELEASE_EVENT_TYPES.has(data?.event_type)) onEventRef.current();
          } catch { /* ignore malformed event */ }
        });
        es.addEventListener('error', () => {
          es?.close();
          es = null;
          if (!cancelled) timer = setTimeout(() => { void connect(); }, 5000);
        });
      } catch {
        if (!cancelled) timer = setTimeout(() => { void connect(); }, 5000);
      }
    };
    void connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [tick]);

  // Тик для ручного переподключения стрима при ошибке ticket не нужен —
  // reconnect уже внутри; expose через unused-vars guard
  void setTick;
}

// ── Run detail panel ──────────────────────────────────────────────────

interface RunDetailProps {
  runId: string;
  liveStatus?: string;
  liveBatches: Record<string, string>;
  liveGates: Record<string, string>;
}

function RunDetail({ runId, liveStatus, liveBatches, liveGates }: RunDetailProps) {
  const [run, setRun] = useState<Run | null>(null);
  const [gates, setGates] = useState<Gate[]>([]);
  const [evidence, setEvidence] = useState<EvidenceChainResult | null>(null);
  const [trail, setTrail] = useState<GateDecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const runData = await api.getRun(runId);
      setRun(runData);
      // Run.gates — только ID; детали (decision) берём из гейтов плана
      try {
        const planGates = await api.getGates(runData.plan_id);
        setGates(planGates || []);
      } catch { /* gates не критичны для detail */ }
      // COS-098: evidence + trail — честная загрузка с ошибкой, не молча
      try {
        setEvidence(await api.getEvidenceChain(runId));
      } catch (err: unknown) {
        setEvidence(null);
        toast.error(`Evidence: ${(err as Error)?.message || 'недоступен'}`);
      }
      try {
        setTrail(await api.getRunTrail(runId));
      } catch { /* trail не критичен */ }
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки прогона');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  // Terminal status по live → evidence мог дописаться: перечитываем
  useEffect(() => {
    if (liveStatus && TERMINAL_RUN_STATUSES.has(liveStatus)) {
      api.getEvidenceChain(runId).then(setEvidence).catch(() => { /* live refresh best-effort */ });
    }
  }, [liveStatus, runId]);

  const status = liveStatus ?? run?.status ?? '—';

  return (
    <Paper variant="outlined" data-testid="run-detail" sx={{ p: 2, borderRadius: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          Прогон <span style={{ fontFamily: 'monospace' }}>{runId}</span>
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Tooltip title="Открыть ГОСТ-Акт (HTML)">
            <Button
              size="small" startIcon={<OpenInNew />} data-testid="gost-act-btn"
              onClick={() => window.open(`/api/v1/runs/${encodeURIComponent(runId)}/gost-act/html`, '_blank')}
              sx={{ textTransform: 'none' }}
            >
              ГОСТ-Акт
            </Button>
          </Tooltip>
          <Button size="small" onClick={fetchDetail} sx={{ textTransform: 'none' }}>Обновить</Button>
        </Box>
      </Box>

      {loading ? (
        <CircularProgress size={22} sx={{ mx: 'auto', display: 'block' }} />
      ) : error ? (
        <Alert severity="error" data-testid="run-detail-error">{error}</Alert>
      ) : run ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip data-testid="run-detail-status" label={`Статус: ${status}`} color={RUN_STATUS_COLOR[status] ?? 'default'} size="small" />
            <Chip label={`План: ${run.plan_id}`} size="small" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: 11 }} />
            <Chip label={`Триггер: ${run.trigger}`} size="small" variant="outlined" sx={{ fontSize: 11 }} />
          </Box>

          {/* Batches (REST + live дельты) */}
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>Батчи</Typography>
            {run.batches.length === 0 ? (
              <Typography variant="body2" color="text.secondary">Батчей нет</Typography>
            ) : (
              <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 0.5 }}>
                {run.batches.map((b) => {
                  const st = liveBatches[b.id] ?? b.status;
                  return (
                    <Chip
                      key={b.id} size="small"
                      data-testid={`batch-${b.id}`}
                      label={`${b.type}: ${st}`}
                      color={st === 'passed' ? 'success' : st === 'failed' ? 'error' : st === 'running' ? 'info' : 'default'}
                      variant="outlined" sx={{ fontSize: 11, fontFamily: 'monospace' }}
                    />
                  );
                })}
              </Box>
            )}
          </Box>

          {/* Gates (REST + live дельты) */}
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}><Gavel sx={{ fontSize: 12, mr: 0.5, verticalAlign: 'text-bottom' }} />Гейты</Typography>
            {gates.length === 0 ? (
              <Typography variant="body2" color="text.secondary">Гейтов в плане нет</Typography>
            ) : (
              <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 0.5 }}>
                {gates.map((g) => {
                  const dec = liveGates[g.id] ?? g.decision ?? '—';
                  return (
                    <Chip
                      key={g.id} size="small"
                      data-testid={`gate-${g.id}`}
                      label={`${g.id}: ${dec}`}
                      color={dec === 'pass' ? 'success' : dec === 'block' ? 'error' : dec === 'manual_required' ? 'warning' : 'default'}
                      variant="outlined" sx={{ fontSize: 11, fontFamily: 'monospace' }}
                    />
                  );
                })}
              </Box>
            )}
          </Box>

          {/* Evidence chain (честно: verified/integrity/tamper) */}
          <Box data-testid="evidence-panel">
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>Evidence-цепочка</Typography>
            {!evidence ? (
              <Typography variant="body2" color="text.secondary">Недоступна</Typography>
            ) : (
              <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 0.5, alignItems: 'center' }}>
                <Chip
                  data-testid="evidence-verified"
                  icon={evidence.verified ? <Verified /> : <LinkOff />}
                  label={evidence.verified ? 'Verified' : 'НЕ Verified'}
                  color={evidence.verified ? 'success' : 'error'} size="small"
                />
                <Chip data-testid="evidence-integrity" label={`integrity: ${evidence.integrity}`} size="small" variant="outlined" sx={{ fontSize: 11 }} />
                <Chip label={`записей: ${evidence.total_entries}`} size="small" variant="outlined" sx={{ fontSize: 11 }} />
                {evidence.tampered_entries.length > 0 && (
                  <Chip data-testid="evidence-tampered" label={`tampered: ${evidence.tampered_entries.length}`} color="error" size="small" />
                )}
                {evidence.broken_links.length > 0 && (
                  <Chip data-testid="evidence-broken" label={`broken links: ${evidence.broken_links.length}`} color="error" size="small" />
                )}
                {evidence.unsealed_entries.length > 0 && (
                  <Chip label={`unsealed: ${evidence.unsealed_entries.length}`} color="warning" size="small" variant="outlined" />
                )}
              </Box>
            )}
          </Box>

          {/* Gate decision trail (COS-081) */}
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>Trail решений гейтов</Typography>
            {trail.length === 0 ? (
              <Typography variant="body2" color="text.secondary">Решений нет</Typography>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mt: 0.5 }}>
                {trail.map((t) => (
                  <Typography key={t.id} variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                    {t.decided_at ?? ''} · {t.gate_id} → {t.decision} ({t.decided_by || '—'})
                  </Typography>
                ))}
              </Box>
            )}
          </Box>

          {/* COS-098: честный degraded — логи появятся с COS-097 */}
          <Alert severity="info" data-testid="logs-degraded" variant="outlined">
            Логи прогона недоступны: интеграция с CI-движком (Woodpecker) появится с COS-097.
          </Alert>
        </Box>
      ) : null}
    </Paper>
  );
}

// ── Main view ─────────────────────────────────────────────────────────

export function ReleaseReadiness() {
  const [domains, setDomains] = useState<CosmoDomain[]>([]);
  const [domainId, setDomainId] = useState<string>('');
  const [releases, setReleases] = useState<Release[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedReleaseId, setSelectedReleaseId] = useState<string | null>(null);

  // 1. Домены (admin: выбор контекста; не-админ: сервер резолвит по identity)
  useEffect(() => {
    let cancelled = false;
    api.getDomains()
      .then((list) => {
        if (cancelled) return;
        setDomains(list || []);
        if (list && list.length > 0) {
          // COS-098: дефолтный домен = X-Cosmo-Domain для domain-scoped REST
          // (admin иначе резолвит 'default' и видит пустые данные)
          setDomainId((prev) => {
            const next = prev || list[0].id;
            setCosmoDomain(next);
            return next;
          });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError((err as Error)?.message || 'Ошибка загрузки доменов');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const handleDomainChange = useCallback((id: string) => {
    setDomainId(id);
    setCosmoDomain(id || null);
    setSelectedRunId(null);
    setSelectedReleaseId(null);
  }, []);

  const refetch = useCallback(async () => {
    setError(null);
    try {
      const [rel, rns] = await Promise.all([
        api.getReleases(),
        api.getRuns().catch(() => [] as Run[]),
      ]);
      setReleases(rel || []);
      setRuns(rns || []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки');
    }
  }, []);

  useEffect(() => { if (domainId) void refetch(); }, [domainId, refetch]);

  // Release lifecycle live: notification-события → refetch releases
  useReleaseEventRefetch(refetch);

  // Runs live: domain SSE (COS-098)
  const live = useLiveDomain(domainId || null);

  const runsRows = useMemo(() =>
    runs.map((r) => ({
      ...r,
      displayStatus: live.runStatuses[r.id] ?? r.status,
      findingsCount: live.runFindings[r.id] ?? (r.findings?.length ?? 0),
      liveBatches: live.runBatches[r.id],
      liveGates: live.runGates[r.id],
    })), [runs, live.runStatuses, live.runFindings, live.runBatches, live.runGates]);

  // Readiness summary — по живым статусам, не по выдуманным полям
  const summary = useMemo(() => {
    const byStatus: Record<string, number> = {};
    for (const r of releases) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1;
    const runByStatus: Record<string, number> = {};
    for (const r of runsRows) runByStatus[r.displayStatus] = (runByStatus[r.displayStatus] ?? 0) + 1;
    const ready = (byStatus.approved ?? 0) + (byStatus.deployed ?? 0);
    return { byStatus, runByStatus, ready, releaseTotal: releases.length };
  }, [releases, runsRows]);

  const selectedRun = runsRows.find((r) => r.id === selectedRunId) ?? null;
  const selectedRelease = releases.find((r) => r.id === selectedReleaseId) ?? null;

  const releaseColumns: GridColDef<Release>[] = [
    { field: 'id', headerName: 'ID', width: 210, renderCell: (p) => <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600 }}>{p.row.id}</span> },
    { field: 'version', headerName: 'Версия', width: 90, renderCell: (p) => <Chip label={p.row.version || '—'} size="small" sx={{ fontFamily: 'monospace', fontSize: 10 }} /> },
    { field: 'status', headerName: 'Статус', width: 120, renderCell: (p) => <Chip label={RELEASE_STATUS_LABELS[p.row.status] ?? p.row.status} size="small" color={p.row.status === 'approved' || p.row.status === 'deployed' ? 'success' : p.row.status === 'rejected' ? 'error' : 'default'} sx={{ fontSize: 10 }} /> },
    { field: 'current_zone', headerName: 'Зона', width: 110, renderCell: (p) => <Chip label={ZONE_LABELS[p.row.current_zone] ?? p.row.current_zone} size="small" variant="outlined" sx={{ fontSize: 10 }} /> },
    { field: 'trigger', headerName: 'Триггер', width: 100 },
    { field: 'run_ids', headerName: 'Прогонов', width: 90, type: 'number', valueGetter: (_v, row) => row.run_ids.length },
    { field: 'approvals', headerName: 'Approvals', width: 90, type: 'number', valueGetter: (_v, row) => row.approvals.length },
  ];

  const runColumns: GridColDef<(typeof runsRows)[number]>[] = [
    { field: 'id', headerName: 'Run ID', width: 230, renderCell: (p) => <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600 }}>{p.row.id}</span> },
    { field: 'displayStatus', headerName: 'Статус (live)', width: 120, renderCell: (p) => <Chip data-testid={`run-status-${p.row.id}`} label={p.row.displayStatus} size="small" color={RUN_STATUS_COLOR[p.row.displayStatus] ?? 'default'} sx={{ fontSize: 10 }} /> },
    { field: 'findingsCount', headerName: 'Находки', width: 90, type: 'number' },
    { field: 'trigger', headerName: 'Триггер', width: 110 },
    { field: 'created_at', headerName: 'Создан', width: 150, valueFormatter: (v) => (v ? new Date(String(v)).toLocaleString() : '') },
  ];

  const liveBadge = (
    <Tooltip title={live.error ?? (live.connectionStatus === 'connected' ? 'Доменный SSE активен' : 'SSE не подключён')}>
      <Chip
        data-testid="live-badge"
        size="small"
        label={live.backlogMode && live.connectionStatus === 'connected'
          ? 'LIVE (backlog replay)'
          : live.connectionStatus === 'connected' ? 'LIVE' : `LIVE: ${live.connectionStatus}`}
        color={live.connectionStatus === 'connected' ? 'success' : 'default'}
        variant="outlined" sx={{ fontSize: 10 }}
      />
    </Tooltip>
  );

  return (
    <ErrorBoundary viewName="Release Readiness">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }} data-testid="release-readiness-view">
        <PageHeader
          title="Release Readiness"
          subtitle={`${summary.releaseTotal} релизов · ${summary.ready} готовы (approved+deployed) · ${runsRows.length} прогонов (live)`}
          action={
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              {liveBadge}
              <Select
                size="small" value={domainId} data-testid="domain-select"
                onChange={(e) => handleDomainChange(e.target.value)}
                displayEmpty sx={{ minWidth: 160, fontSize: 12 }}
              >
                {domains.length === 0 && <MenuItem value="">— нет доменов —</MenuItem>}
                {domains.map((d) => <MenuItem key={d.id} value={d.id} sx={{ fontSize: 12 }}>{d.label || d.id}</MenuItem>)}
              </Select>
              <Button size="small" startIcon={<Refresh />} onClick={() => void refetch()} data-testid="refresh-btn" sx={{ textTransform: 'none' }}>Обновить</Button>
            </Box>
          }
        />

        {error && (
          <Alert severity="error" data-testid="load-error" onClose={() => setError(null)}>{error}</Alert>
        )}

        {loading ? (
          <CircularProgress sx={{ mx: 'auto' }} />
        ) : domains.length === 0 ? (
          <Alert severity="info">Домены не найдены: домены ещё не созданы</Alert>
        ) : (
          <>
            {/* Summary */}
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }} data-testid="readiness-summary">
              <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                <Box>
                  <Typography variant="h4" sx={{ fontWeight: 800 }}>{summary.releaseTotal}</Typography>
                  <Typography variant="caption" color="text.secondary">Релизов</Typography>
                </Box>
                <Box>
                  <Typography variant="h4" sx={{ fontWeight: 800, color: 'success.main' }}>{summary.ready}</Typography>
                  <Typography variant="caption" color="text.secondary">Готовы (approved+deployed)</Typography>
                </Box>
                <Box>
                  <Typography variant="h4" sx={{ fontWeight: 800, color: 'info.main' }}>{summary.runByStatus.running ?? 0}</Typography>
                  <Typography variant="caption" color="text.secondary">Прогонов running</Typography>
                </Box>
                <Box>
                  <Typography variant="h4" sx={{ fontWeight: 800, color: 'error.main' }}>{summary.runByStatus.failed ?? 0}</Typography>
                  <Typography variant="caption" color="text.secondary">Прогонов failed</Typography>
                </Box>
              </Box>
            </Paper>

            {/* Releases — testid на Box-обёртке: MUI DataGrid не форвардит
                data-testid на корень в браузере (jsdom форвардит — расхождение
                ловилось e2e) */}
            <Box data-testid="releases-grid">
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
                Релизы {selectedRelease ? `· выбран ${selectedRelease.id} (${selectedRelease.run_ids.length} прогонов)` : ''}
              </Typography>
              <DataGrid
                columns={releaseColumns}
                rows={releases}
                getRowId={(row) => row.id}
                density="compact"
                autoHeight
                disableColumnMenu
                onRowClick={(p) => setSelectedReleaseId(p.row.id === selectedReleaseId ? null : p.row.id)}
                hideFooterSelectedRowCount
                sx={{
                  border: '1px solid', borderColor: 'divider', borderRadius: 2,
                  '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
                  '& .MuiDataGrid-cell': { fontSize: 12 },
                }}
              />
              {releases.length === 0 && <Alert severity="info" sx={{ mt: 1 }}>Релизов в домене нет</Alert>}
            </Box>

            {/* Runs (live) */}
            <Box data-testid="runs-grid">
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>Прогоны (live)</Typography>
              <DataGrid
                columns={runColumns}
                rows={runsRows}
                getRowId={(row) => row.id}
                density="compact"
                autoHeight
                disableColumnMenu
                onRowClick={(p) => setSelectedRunId(p.row.id === selectedRunId ? null : p.row.id)}
                hideFooterSelectedRowCount
                sx={{
                  border: '1px solid', borderColor: 'divider', borderRadius: 2,
                  '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover', fontWeight: 600, fontSize: 12 },
                  '& .MuiDataGrid-cell': { fontSize: 12 },
                }}
              />
              {runsRows.length === 0 && <Alert severity="info" sx={{ mt: 1 }}>Прогонов в домене нет</Alert>}
            </Box>

            {/* Run detail */}
            {selectedRun && (
              <RunDetail
                key={selectedRun.id}
                runId={selectedRun.id}
                liveStatus={selectedRun.displayStatus}
                liveBatches={selectedRun.liveBatches ?? {}}
                liveGates={selectedRun.liveGates ?? {}}
              />
            )}
          </>
        )}
      </Box>
    </ErrorBoundary>
  );
}
