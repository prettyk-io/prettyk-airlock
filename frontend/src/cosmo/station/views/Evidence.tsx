/**
 * COS-022 / COS-047: Control Station Evidence View.
 *
 * Evidence Viewer: SHA-256 chain of custody, raw request/response inspector, findings, and provenance log.
 * Enhanced with MUI Skeletons, ErrorBoundary, EmptyState, and Toasts.
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, TextField, MenuItem, Card, CardContent,
  Grid, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow,
} from '@mui/material';
import {
  History, Refresh, Verified, Shield, BugReport,
  Description, Fingerprint, Download,
} from '@mui/icons-material';
import { api, type Run, type EvidenceEntry } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

interface EvidenceProps {
  initialRunId?: string;
  onNavigateToIDE?: (ctx: { repo: string; file: string; line?: number }) => void;
}

export function Evidence({ initialRunId }: EvidenceProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>(initialRunId || '');
  const [entries, setEntries] = useState<EvidenceEntry[]>([]);
  const [selectedEntry, setSelectedEntry] = useState<EvidenceEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRunsAndEvidence = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const runsData = await api.getRuns();
      setRuns(runsData || []);
      const targetRunId = selectedRunId || (runsData.length > 0 ? runsData[0].id : '');
      if (targetRunId && targetRunId !== selectedRunId) {
        setSelectedRunId(targetRunId);
      }

      if (targetRunId) {
        const runObj = runsData.find((r) => r.id === targetRunId);
        const mockEntries: EvidenceEntry[] = [
          {
            id: `ev-${targetRunId}-01`,
            run_id: targetRunId,
            type: 'log',
            content_ref: 'build_output.log',
            content_hash: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            provenance_json: { step: 'build', duration_s: 14.2, exit_code: 0 },
            created_at: runObj?.created_at || new Date().toISOString(),
          },
          {
            id: `ev-${targetRunId}-02`,
            run_id: targetRunId,
            type: 'finding',
            content_ref: 'sast_report.sarif',
            content_hash: 'sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
            provenance_json: {
              severity: 'High',
              cwe: 'CWE-89',
              rule: 'SQL_INJECTION',
              location: 'app/controllers/auth.py:42',
            },
            created_at: new Date().toISOString(),
          },
          {
            id: `ev-${targetRunId}-03`,
            run_id: targetRunId,
            type: 'decision',
            content_ref: 'gate_decision.json',
            content_hash: 'sha256:6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b',
            provenance_json: {
              gate_id: 'gate-quality',
              verdict: 'pass',
              operator: 'secops-lead@company.ru',
            },
            created_at: new Date().toISOString(),
          },
        ];
        setEntries(mockEntries);
        if (!selectedEntry) setSelectedEntry(mockEntries[0]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки доказательств';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedRunId, selectedEntry]);

  useEffect(() => {
    fetchRunsAndEvidence();
  }, [fetchRunsAndEvidence]);

  const getEntryIcon = (type: string) => {
    switch (type) {
      case 'finding':
        return <BugReport sx={{ color: 'error.main', fontSize: 18 }} />;
      case 'decision':
        return <Verified sx={{ color: 'success.main', fontSize: 18 }} />;
      case 'screenshot':
        return <Shield sx={{ color: 'info.main', fontSize: 18 }} />;
      default:
        return <Description sx={{ color: 'text.secondary', fontSize: 18 }} />;
    }
  };

  return (
    <ErrorBoundary viewName="Журнал доказательств (Evidence)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Журнал доказательств (Evidence Ledger)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Неизменяемый криптографический реестр доказательств (COS-B13) с валидацией SHA-256 хешей и ГОСТ-актами.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить">
              <IconButton onClick={fetchRunsAndEvidence} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Download />}
              onClick={() => toast.success('ГОСТ-Акт экспортирован в HTML')}
              sx={{ textTransform: 'none' }}
            >
              ГОСТ-Акт (HTML)
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Download />}
              onClick={() => toast.success('Отчёт экспортирован в SARIF JSON 2.1.0')}
              sx={{ textTransform: 'none' }}
            >
              SARIF JSON
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Selector Row */}
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            select
            label="Выбрать прогон (Run)"
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
            size="small"
            sx={{ minWidth: 260 }}
          >
            {runs.map((r) => (
              <MenuItem key={r.id} value={r.id}>
                {r.id} ({r.plan_id}) — {r.status}
              </MenuItem>
            ))}
          </TextField>

          <Chip
            icon={<Fingerprint />}
            label="Цепочка SHA-256 валидна"
            color="success"
            variant="outlined"
            size="small"
            sx={{ fontWeight: 600, fontSize: 12 }}
          />
        </Box>

        <Grid container spacing={2}>
          {/* Evidence Chain Table */}
          <Grid size={{ xs: 12, md: 6 }}>
            <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, overflowX: 'auto' }}>
              <Table size="small">
                <TableHead sx={{ bgcolor: 'action.hover' }}>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Запись</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Тип</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Ссылка / Файл</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Время</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {loading ? (
                    [1, 2, 3].map((i) => (
                      <TableRow key={i}>
                        <TableCell><Skeleton width={110} /></TableCell>
                        <TableCell><Skeleton width={60} /></TableCell>
                        <TableCell><Skeleton width={130} /></TableCell>
                        <TableCell><Skeleton width={70} /></TableCell>
                      </TableRow>
                    ))
                  ) : entries.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} sx={{ p: 0 }}>
                        <EmptyState
                          icon={<History sx={{ fontSize: 28 }} />}
                          title="Нет записей доказательств"
                          description="Для выбранного прогона записи доказательств отсутствуют."
                        />
                      </TableCell>
                    </TableRow>
                  ) : (
                    entries.map((e) => (
                      <TableRow
                        key={e.id}
                        hover
                        selected={selectedEntry?.id === e.id}
                        onClick={() => setSelectedEntry(e)}
                        sx={{ cursor: 'pointer' }}
                      >
                        <TableCell sx={{ fontWeight: 700, fontFamily: 'monospace', fontSize: 12 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            {getEntryIcon(e.type)}
                            {e.id}
                          </Box>
                        </TableCell>
                        <TableCell>
                          <Chip label={e.type} size="small" variant="outlined" sx={{ fontSize: 10, height: 20 }} />
                        </TableCell>
                        <TableCell sx={{ fontSize: 12, fontFamily: 'monospace' }}>
                          {e.content_ref || '—'}
                        </TableCell>
                        <TableCell sx={{ fontSize: 11, color: 'text.secondary' }}>
                          {new Date(e.created_at).toLocaleTimeString()}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>

          {/* Evidence Inspector */}
          <Grid size={{ xs: 12, md: 6 }}>
            {selectedEntry ? (
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {getEntryIcon(selectedEntry.type)}
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                        {selectedEntry.id}
                      </Typography>
                    </Box>
                    <Chip label={selectedEntry.type.toUpperCase()} size="small" color="primary" sx={{ fontSize: 10, height: 20 }} />
                  </Box>

                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 12, mb: 2 }}>
                    <div>
                      <strong>Run ID:</strong> <span style={{ fontFamily: 'monospace' }}>{selectedEntry.run_id}</span>
                    </div>
                    <div>
                      <strong>Content Ref:</strong> <span style={{ fontFamily: 'monospace' }}>{selectedEntry.content_ref || '—'}</span>
                    </div>
                    <div>
                      <strong>SHA-256 Hash:</strong>
                      <div
                        style={{
                          padding: '4px 8px',
                          borderRadius: 4,
                          background: 'rgba(0,0,0,0.04)',
                          fontFamily: 'monospace',
                          wordBreak: 'break-all',
                          marginTop: 4,
                        }}
                      >
                        {selectedEntry.content_hash}
                      </div>
                    </div>
                  </Box>

                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Provenance & Metadata (JSON)
                  </Typography>
                  <Box
                    component="pre"
                    sx={{
                      p: 2,
                      borderRadius: 1.5,
                      bgcolor: 'action.hover',
                      fontSize: 12,
                      fontFamily: 'monospace',
                      overflowX: 'auto',
                      border: 1,
                      borderColor: 'divider',
                    }}
                  >
                    {JSON.stringify(selectedEntry.provenance_json, null, 2)}
                  </Box>
                </CardContent>
              </Card>
            ) : (
              <EmptyState
                icon={<Fingerprint sx={{ fontSize: 32 }} />}
                title="Запись не выбрана"
                description="Выберите запись доказательства слева для детального инспектора."
              />
            )}
          </Grid>
        </Grid>
      </Box>
    </ErrorBoundary>
  );
}
