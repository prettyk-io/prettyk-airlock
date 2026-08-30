/**
 * COS-051: Audit Log Viewer View.
 *
 * Comprehensive compliance & security audit trail (cosmo_audit_events).
 * Features:
 *   - Filtering by user, action, resource type, status, and date
 *   - Detail inspection panel for raw details JSON and provenance
 *   - Export to CSV & JSON
 *   - Skeletons, ErrorBoundary, EmptyState, and Toasts
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Box, Typography, Button, Chip, Paper, Skeleton,
  Alert, IconButton, Tooltip, TextField, MenuItem, Card, CardContent,
  Grid, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, InputAdornment,
} from '@mui/material';
import {
  Refresh, Download, Search, CheckCircle, Warning, Block,
  History, Security, Gavel, RocketLaunch, PlayArrow,
  Person, Public, Code,
} from '@mui/icons-material';
import { api, type AuditEvent } from '../api';
import { ErrorBoundary } from '../../shared/ErrorBoundary';
import { EmptyState } from '../../shared/EmptyState';
import { toast } from '../../shared/toast';

const ACTIONS = [
  { value: 'all', label: 'Все действия' },
  { value: 'gate_decision', label: 'Решение Gate' },
  { value: 'transfer_zone', label: 'Трансфер зоны' },
  { value: 'commit_push', label: 'Git Commit & Push' },
  { value: 'trigger_run', label: 'Запуск прогона' },
  { value: 'login_attempt', label: 'Аутентификация' },
  { value: 'create_app', label: 'Создание сервиса' },
];

const STATUSES = [
  { value: 'all', label: 'Все статусы' },
  { value: 'success', label: 'Успешно (Success)' },
  { value: 'failed', label: 'Сбой (Failed)' },
  { value: 'blocked', label: 'Заблокировано (Blocked)' },
];

const RESOURCE_TYPES = [
  { value: 'all', label: 'Все ресурсы' },
  { value: 'gate', label: 'Security Gate' },
  { value: 'release', label: 'Release' },
  { value: 'repo', label: 'Repository' },
  { value: 'run', label: 'Run / Pipeline' },
  { value: 'auth', label: 'Auth & Session' },
  { value: 'app', label: 'Application' },
];

export function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter criteria
  const [userQuery, setUserQuery] = useState('');
  const [actionFilter, setActionFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [resourceFilter, setResourceFilter] = useState('all');

  const fetchAuditLog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAuditEvents({
        userId: userQuery.trim() || undefined,
        action: actionFilter !== 'all' ? actionFilter : undefined,
        resourceType: resourceFilter !== 'all' ? resourceFilter : undefined,
        status: statusFilter !== 'all' ? statusFilter : undefined,
      });
      if (data && data.length > 0) {
        setEvents(data);
      } else {
        setEvents([]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка загрузки журнала аудита';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [userQuery, actionFilter, statusFilter, resourceFilter]);

  useEffect(() => {
    fetchAuditLog();
  }, [fetchAuditLog]);

  const handleResetFilters = () => {
    setUserQuery('');
    setActionFilter('all');
    setStatusFilter('all');
    setResourceFilter('all');
  };

  const handleExportCSV = () => {
    const rows = [
      ['ID', 'Timestamp', 'User', 'Role', 'Action', 'Resource', 'Status', 'IP'],
      ...events.map((e) => [
        e.id,
        new Date(e.timestamp).toISOString(),
        e.user_id,
        e.role,
        e.action,
        `${e.resource_type}/${e.resource_id}`,
        e.status,
        e.ip_address,
      ]),
    ];
    const csvContent = rows.map((r) => r.join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cosmo_audit_events_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Журнал аудита экспортирован в CSV');
  };

  const handleExportJSON = () => {
    const jsonStr = JSON.stringify(events, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cosmo_audit_events_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Журнал аудита экспортирован в JSON');
  };

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'gate_decision':
        return <Gavel sx={{ fontSize: 16, color: 'warning.main' }} />;
      case 'transfer_zone':
        return <RocketLaunch sx={{ fontSize: 16, color: 'primary.main' }} />;
      case 'commit_push':
        return <Code sx={{ fontSize: 16, color: 'info.main' }} />;
      case 'trigger_run':
        return <PlayArrow sx={{ fontSize: 16, color: 'success.main' }} />;
      case 'login_attempt':
        return <Security sx={{ fontSize: 16, color: 'secondary.main' }} />;
      default:
        return <History sx={{ fontSize: 16, color: 'text.secondary' }} />;
    }
  };

  const getStatusChip = (status: string) => {
    switch (status) {
      case 'success':
        return <Chip icon={<CheckCircle />} label="Успешно" size="small" color="success" sx={{ fontSize: 10, height: 20 }} />;
      case 'failed':
        return <Chip icon={<Warning />} label="Ошибка" size="small" color="error" sx={{ fontSize: 10, height: 20 }} />;
      case 'blocked':
        return <Chip icon={<Block />} label="Блок" size="small" color="warning" sx={{ fontSize: 10, height: 20 }} />;
      default:
        return <Chip label={status} size="small" sx={{ fontSize: 10, height: 20 }} />;
    }
  };

  return (
    <ErrorBoundary viewName="Журнал аудита (Audit Log)">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Журнал аудита безопасности (Audit Log)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Неизменяемый журнал действий пользователей, трансфера релизов, вердиктов Security Gates и системных событий.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Tooltip title="Обновить журнал">
              <IconButton onClick={fetchAuditLog} disabled={loading} size="small">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Download />}
              onClick={handleExportCSV}
              sx={{ textTransform: 'none' }}
            >
              Экспорт CSV
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<Download />}
              onClick={handleExportJSON}
              sx={{ textTransform: 'none' }}
            >
              Экспорт JSON
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Filter Bar Card */}
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'background.paper' }}>
          <Grid container spacing={1.5} sx={{ alignItems: 'center' }}>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <TextField
                placeholder="Поиск по пользователю..."
                value={userQuery}
                onChange={(e) => setUserQuery(e.target.value)}
                size="small"
                fullWidth
                slotProps={{
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <Search sx={{ fontSize: 18, color: 'text.secondary' }} />
                      </InputAdornment>
                    ),
                  },
                }}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 6, md: 2.5 }}>
              <TextField
                select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                size="small"
                fullWidth
              >
                {ACTIONS.map((a) => (
                  <MenuItem key={a.value} value={a.value}>
                    {a.label}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 6, sm: 6, md: 2.5 }}>
              <TextField
                select
                value={resourceFilter}
                onChange={(e) => setResourceFilter(e.target.value)}
                size="small"
                fullWidth
              >
                {RESOURCE_TYPES.map((r) => (
                  <MenuItem key={r.value} value={r.value}>
                    {r.label}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 6, sm: 6, md: 2 }}>
              <TextField
                select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                size="small"
                fullWidth
              >
                {STATUSES.map((s) => (
                  <MenuItem key={s.value} value={s.value}>
                    {s.label}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 6, sm: 6, md: 2 }} sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                size="small"
                onClick={handleResetFilters}
                sx={{ textTransform: 'none', color: 'text.secondary' }}
              >
                Сбросить
              </Button>
            </Grid>
          </Grid>
        </Paper>

        <Grid container spacing={2}>
          {/* Main Table */}
          <Grid size={{ xs: 12, lg: selectedEvent ? 7 : 12 }}>
            <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, overflowX: 'auto' }}>
              <Table size="small">
                <TableHead sx={{ bgcolor: 'action.hover' }}>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>ID</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Время</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Пользователь</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Действие</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Целевой ресурс</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>IP</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Статус</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {loading ? (
                    [1, 2, 3, 4, 5].map((i) => (
                      <TableRow key={i}>
                        <TableCell><Skeleton width={70} /></TableCell>
                        <TableCell><Skeleton width={110} /></TableCell>
                        <TableCell><Skeleton width={130} /></TableCell>
                        <TableCell><Skeleton width={100} /></TableCell>
                        <TableCell><Skeleton width={120} /></TableCell>
                        <TableCell><Skeleton width={80} /></TableCell>
                        <TableCell><Skeleton width={70} /></TableCell>
                      </TableRow>
                    ))
                  ) : events.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} sx={{ p: 0 }}>
                        <EmptyState
                          icon={<History sx={{ fontSize: 28 }} />}
                          title="События аудита не найдены"
                          description="Попробуйте изменить параметры фильтрации или поисковый запрос."
                          actionLabel="Сбросить фильтры"
                          onAction={handleResetFilters}
                        />
                      </TableCell>
                    </TableRow>
                  ) : (
                    events.map((e) => (
                      <TableRow
                        key={e.id}
                        hover
                        selected={selectedEvent?.id === e.id}
                        onClick={() => setSelectedEvent(e)}
                        sx={{ cursor: 'pointer' }}
                      >
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700 }}>
                          {e.id}
                        </TableCell>
                        <TableCell sx={{ fontSize: 12, color: 'text.secondary', whiteSpace: 'nowrap' }}>
                          {new Date(e.timestamp).toLocaleString()}
                        </TableCell>
                        <TableCell sx={{ fontSize: 12 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <Person sx={{ fontSize: 14, color: 'text.secondary' }} />
                            <span>{e.user_id}</span>
                            <Chip label={e.role} size="small" variant="outlined" sx={{ fontSize: 9, height: 16 }} />
                          </Box>
                        </TableCell>
                        <TableCell sx={{ fontSize: 12 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            {getActionIcon(e.action)}
                            <span style={{ fontWeight: 600 }}>{e.action}</span>
                          </Box>
                        </TableCell>
                        <TableCell sx={{ fontSize: 12, fontFamily: 'monospace' }}>
                          <span style={{ color: '#64748B' }}>{e.resource_type}/</span>
                          <strong>{e.resource_id}</strong>
                        </TableCell>
                        <TableCell sx={{ fontSize: 11, fontFamily: 'monospace', color: 'text.secondary' }}>
                          {e.ip_address}
                        </TableCell>
                        <TableCell>
                          {getStatusChip(e.status)}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>

          {/* Detail Inspector Panel */}
          {selectedEvent && (
            <Grid size={{ xs: 12, lg: 5 }}>
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {getActionIcon(selectedEvent.action)}
                      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                        {selectedEvent.action}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {getStatusChip(selectedEvent.status)}
                      <IconButton size="small" onClick={() => setSelectedEvent(null)}>
                        ×
                      </IconButton>
                    </Box>
                  </Box>

                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: 12, mb: 3 }}>
                    <div>
                      <strong>ID события:</strong> <span style={{ fontFamily: 'monospace' }}>{selectedEvent.id}</span>
                    </div>
                    <div>
                      <strong>Время:</strong> {new Date(selectedEvent.timestamp).toLocaleString()}
                    </div>
                    <div>
                      <strong>Пользователь:</strong> {selectedEvent.user_id} ({selectedEvent.role})
                    </div>
                    <div>
                      <strong>Целевой ресурс:</strong>{' '}
                      <span style={{ fontFamily: 'monospace' }}>
                        {selectedEvent.resource_type}/{selectedEvent.resource_id}
                      </span>
                    </div>
                    <div>
                      <strong>IP адрес:</strong> <span style={{ fontFamily: 'monospace' }}>{selectedEvent.ip_address}</span>
                    </div>
                  </Box>

                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Детали операции (Payload & Metadata)
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
                    {JSON.stringify(selectedEvent.details_json, null, 2)}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      </Box>
    </ErrorBoundary>
  );
}
