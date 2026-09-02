/**
 * COS-079: NotificationOps — DLQ (dead letter queue) для email-канала.
 *
 * Operator surface: список терминально неудавшихся доставок (GET /dlq),
 * повторная отправка одним действием (POST /dlq/{id}/replay). State после
 * replay честный: sent | retryable_failure | failed — без украшательств.
 * Honest states: загрузка (Skeleton), ошибка (Alert + retry), пусто (EmptyState).
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, IconButton, Tooltip, Skeleton, Alert,
} from '@mui/material';
import { Refresh, Replay, MarkEmailUnread } from '@mui/icons-material';
import { api, type DlqItem } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';

const severityMeta: Record<string, string> = {
  critical: '#EF4444',
  high: '#F59E0B',
  medium: '#0EA5E9',
  low: '#64748B',
  info: '#64748B',
};

export function NotificationOps() {
  const [rows, setRows] = useState<DlqItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [replayingId, setReplayingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const fetchDlq = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDlq();
      setRows(data ?? []);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки DLQ');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchDlq(); }, [fetchDlq]);

  const handleReplay = async (id: string) => {
    setReplayingId(id);
    setNotice(null);
    try {
      const result = await api.replayDlq(id);
      if (result.state === 'sent') {
        setNotice({ ok: true, text: `Повторная отправка: доставлено (attempt ${result.attempts})` });
      } else {
        setNotice({
          ok: false,
          text: `Повторная отправка: провайдер отказал — состояние ${result.state} (честно)`,
        });
      }
      await fetchDlq();
    } catch (err: unknown) {
      setNotice({
        ok: false,
        text: (err as Error)?.message || 'Ошибка повторной отправки',
      });
    } finally {
      setReplayingId(null);
    }
  };

  const fmtTime = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString('ru-RU') : '—';

  return (
    <ErrorBoundary viewName="Notification Ops (DLQ)">
      <Box
        data-testid="notification-ops-view"
        sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>Dead Letter Queue</Typography>
            <Typography variant="body2" color="text.secondary">
              Терминально неудавшиеся email-доставки. Replay — одна повторная
              попытка; итоговое состояние всегда честное.
            </Typography>
          </Box>
          <IconButton
            data-testid="dlq-retry"
            onClick={() => { void fetchDlq(); }}
            disabled={loading}
            size="small"
            aria-label="refresh-dlq"
          >
            <Refresh />
          </IconButton>
        </Box>

        {error && (
          <Alert
            data-testid="dlq-error"
            severity="error"
            onClose={() => setError(null)}
            action={
              <Button color="inherit" size="small" onClick={() => { void fetchDlq(); }}>
                Повторить
              </Button>
            }
          >
            {error}
          </Alert>
        )}

        {notice && (
          <Alert
            severity={notice.ok ? 'success' : 'warning'}
            onClose={() => setNotice(null)}
          >
            {notice.text}
          </Alert>
        )}

        <TableContainer component={Paper} sx={{ border: 1, borderColor: 'divider' }}>
          <Table size="small" data-testid="dlq-table">
            <TableHead>
              <TableRow>
                <TableCell>Событие</TableCell>
                <TableCell>Тип</TableCell>
                <TableCell>Получатель</TableCell>
                <TableCell>Попытки</TableCell>
                <TableCell>Последняя ошибка</TableCell>
                <TableCell>Обновлено</TableCell>
                <TableCell align="right">Действия</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                [...Array(3)].map((_, i) => (
                  <TableRow key={`sk-${i}`}>
                    <TableCell colSpan={7}><Skeleton height={32} /></TableCell>
                  </TableRow>
                ))
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7}>
                    {error ? null : (
                      <EmptyState
                        icon={<MarkEmailUnread sx={{ fontSize: 36 }} />}
                        title="DLQ пуста"
                        description="Все email-доставки либо отправлены, либо в ожидании повтора. Мёртвых писем нет."
                      />
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={row.id} data-testid="dlq-row" hover>
                    <TableCell>
                      <Typography sx={{ fontWeight: 600, fontSize: 13 }}>{row.title}</Typography>
                      <Chip
                        size="small"
                        label={row.severity}
                        sx={{
                          height: 18, fontSize: 10, mt: 0.5,
                          bgcolor: `${severityMeta[row.severity] ?? '#64748B'}22`,
                          color: severityMeta[row.severity] ?? '#64748B',
                        }}
                      />
                    </TableCell>
                    <TableCell sx={{ fontSize: 12 }}>{row.event_type}</TableCell>
                    <TableCell sx={{ fontSize: 12 }}>{row.recipient_id}</TableCell>
                    <TableCell sx={{ fontSize: 12 }}>{row.attempts}/{row.max_attempts}</TableCell>
                    <TableCell sx={{ fontSize: 12, maxWidth: 260, overflowWrap: 'anywhere' }}>
                      {row.last_error ?? '—'}
                    </TableCell>
                    <TableCell sx={{ fontSize: 12 }}>{fmtTime(row.updated_at)}</TableCell>
                    <TableCell align="right">
                      <Tooltip title="Повторная отправка (одна попытка)">
                        <span>
                          <IconButton
                            data-testid="dlq-replay-btn"
                            size="small"
                            color="primary"
                            disabled={replayingId === row.id}
                            onClick={() => { void handleReplay(row.id); }}
                            aria-label={`replay-${row.id}`}
                          >
                            <Replay fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    </ErrorBoundary>
  );
}
