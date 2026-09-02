/**
 * COS-061: Durable Notification Surface — Control Station bell + inbox drawer.
 *
 * Data source: durable PG inbox (COS-055) via REST + SSE (COS-056).
 * No in-memory polling, no synthetic alert generation, no mock data.
 *
 * SSE events:
 *   notification_initial      → initial unread count on connect
 *   notification_new          → new inbox item (live)
 *   notification_unread_count → updated unread badge
 *   notification_degraded     → backend degraded (PG unavailable)
 *   keepalive (comment)       → proxy timeout prevention
 *
 * Reconnect (COS-075): client-driven — новый short-TTL ticket на каждый
 * connect; server sends fresh initial state, no duplicate visible
 * notifications (durable inbox is source of truth).
 *
 * COS-088: последний SSE id запоминается и передаётся query-параметром
 * last_event_id при переподключении — сервер ресемплит backlog (durable
 * inbox остаётся source of truth; клиент дедуплицирует по id).
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box, Typography, IconButton, Badge, Tooltip, Drawer, Chip,
  Button, Paper, Alert, AlertTitle, CircularProgress,
} from '@mui/material';
import {
  Notifications, Close, Block, Warning, CheckCircle,
  RocketLaunch, BugReport, Gavel, Error as ErrorIcon,
  DoneAll, WifiOff, Wifi, Refresh,
} from '@mui/icons-material';
import { api, type InboxNotification, type NotificationSeverity } from '../api';
import { toast } from '../../shared/toast';

// ── SSE connection state ─────────────────────────────────────────────

type SSEState = 'connecting' | 'connected' | 'disconnected' | 'degraded';

// ── Severity helpers ──────────────────────────────────────────────────

function severityColor(sev: NotificationSeverity): string {
  switch (sev) {
    case 'critical': return '#EF4444';
    case 'high': return '#F97316';
    case 'medium': return '#F59E0B';
    case 'low': return '#3B82F6';
    case 'info': return '#0EA5E9';
    default: return '#64748B';
  }
}

function severityIcon(sev: NotificationSeverity) {
  switch (sev) {
    case 'critical': return <ErrorIcon sx={{ color: '#EF4444', fontSize: 16 }} />;
    case 'high': return <Warning sx={{ color: '#F97316', fontSize: 16 }} />;
    case 'medium': return <Warning sx={{ color: '#F59E0B', fontSize: 16 }} />;
    case 'low': return <CheckCircle sx={{ color: '#3B82F6', fontSize: 16 }} />;
    default: return <CheckCircle sx={{ color: '#0EA5E9', fontSize: 16 }} />;
  }
}

function typeIcon(notificationType: string) {
  if (notificationType.includes('gate')) return <Gavel sx={{ fontSize: 14 }} />;
  if (notificationType.includes('run')) return <Block sx={{ fontSize: 14 }} />;
  if (notificationType.includes('transfer')) return <RocketLaunch sx={{ fontSize: 14 }} />;
  if (notificationType.includes('batch')) return <BugReport sx={{ fontSize: 14 }} />;
  return <Notifications sx={{ fontSize: 14 }} />;
}

// ── Component ──────────────────────────────────────────────────────────

interface AlertHUDProps {
  onNavigateToView?: (view: string, params?: Record<string, string>) => void;
}

export function AlertHUD({ onNavigateToView }: AlertHUDProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notifications, setNotifications] = useState<InboxNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sseState, setSSEState] = useState<SSEState>('connecting');

  const esRef = useRef<EventSource | null>(null);

  // ── API: Fetch inbox from durable backend ──

  const fetchInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [inboxData, unreadData] = await Promise.all([
        api.getInbox(false, 100),
        api.getUnreadCount(),
      ]);
      setNotifications(inboxData || []);
      setUnreadCount(unreadData?.unread ?? 0);
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Ошибка загрузки уведомлений');
    } finally {
      setLoading(false);
    }
  }, []);

  // ── API: Mark one read ──

  const handleMarkRead = useCallback(async (notificationId: string) => {
    try {
      await api.markNotificationRead(notificationId);
      setNotifications((prev) =>
        prev.map((n) => (n.id === notificationId ? { ...n, read: true } : n)),
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      toast.error('Не удалось отметить уведомление');
    }
  }, []);

  // ── API: Mark all read ──

  const handleMarkAllRead = useCallback(async () => {
    try {
      const result = await api.markAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnreadCount(0);
      toast.info(`Отмечено ${result.marked} уведомлений`);
    } catch {
      toast.error('Ошибка отметки уведомлений');
    }
  }, []);

  // ── SSE: Live notification stream (COS-075 ticket auth) ──

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let es: EventSource | null = null;
    // COS-088: последний SSE id — для resample при reconnect
    let lastEventId = '';

    // EventSource не умеет custom headers: bearer уходит только в POST
    // sse-ticket; стрим открывается по short-TTL ticket'у, привязанному
    // к principal. Recipient резолвится на бэкенде из ticket.
    const scheduleReconnect = () => {
      if (disposed) return;
      setSSEState((prev) => (prev === 'degraded' ? prev : 'disconnected'));
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 2000);
    };

    const connect = async (): Promise<void> => {
      if (disposed) return;
      try {
        const t = await api.getSseTicket();
        if (disposed) return;
        // COS-088: reconnect с resample — сервер доливает пропущенные
        // notification_new из backlog; дубликаты отсекаются по id.
        let url = `/api/v1/notifications/stream?ticket=${encodeURIComponent(t.ticket)}`;
        if (lastEventId) {
          url += `&last_event_id=${encodeURIComponent(lastEventId)}`;
        }
        es = new EventSource(url);
        esRef.current = es;

        es.onopen = () => { setSSEState('connected'); };
        es.onerror = () => {
          // Ticket истёк/невалиден или сеть упала: EventSource сам не
          // переподключится с прожжённым ticket'ом — закрываем и берём
          // новый ticket (клиентский reconnect).
          es?.close();
          if (esRef.current === es) esRef.current = null;
          scheduleReconnect();
        };

        es.addEventListener('notification_initial', (e) => {
          setSSEState('connected');
          try {
            const data = JSON.parse((e as MessageEvent).data);
            setUnreadCount(data.unread_count ?? 0);
          } catch { /* parse error — ignore */ }
        });

        es.addEventListener('notification_new', (e) => {
          setSSEState('connected');
          try {
            const me = e as MessageEvent;
            if (me.lastEventId) lastEventId = me.lastEventId;
            const item = JSON.parse(me.data) as Partial<InboxNotification>;
            // Dedup: skip if already shown (id-based) — покрывает и replay
            setNotifications((prev) => {
              if (prev.some((n) => n.id === item.id)) return prev;
              const newNotification: InboxNotification = {
                id: item.id ?? '',
                event_id: item.event_id ?? '',
                notification_type: item.notification_type ?? '',
                severity: (item.severity as NotificationSeverity) ?? 'info',
                title: item.title ?? '',
                message: item.message ?? '',
                channel: 'in_app',
                state: 'delivered',
                read: false,
                read_at: null,
                created_at: item.created_at ?? new Date().toISOString(),
              };
              return [newNotification, ...prev];
            });
          } catch { /* parse error — ignore */ }
        });

        es.addEventListener('notification_unread_count', (e) => {
          try {
            const data = JSON.parse((e as MessageEvent).data);
            setUnreadCount(data.unread_count ?? 0);
          } catch { /* parse error */ }
        });

        es.addEventListener('notification_degraded', () => {
          setSSEState('degraded');
        });
      } catch {
        // Ticket-endpoint недоступен: retry с новым ticket'ом
        scheduleReconnect();
      }
    };

    void connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      es?.close();
      if (esRef.current === es) esRef.current = null;
    };
  }, []); // connect once on mount; reconnects go through fresh tickets

  // ── Initial fetch on mount ──

  useEffect(() => { fetchInbox(); }, [fetchInbox]);

  // ── Handlers ──

  const handleToggleDrawer = () => setDrawerOpen((prev) => !prev);

  const handleNotificationClick = (notification: InboxNotification) => {
    if (!notification.read) handleMarkRead(notification.id);
    // Deep-link: navigate to relevant view based on notification_type
    if (onNavigateToView) {
      const type = notification.notification_type;
      if (type.includes('run')) onNavigateToView('runs');
      else if (type.includes('gate')) onNavigateToView('gates');
      else if (type.includes('release') || type.includes('transfer')) onNavigateToView('releases');
      else if (type.includes('batch')) onNavigateToView('pipelines');
    }
  };

  const unreadCritical = notifications.filter(
    (n) => !n.read && (n.severity === 'critical' || n.severity === 'high'),
  ).length;

  // ── SSE status indicator ──

  const sseIndicator = (() => {
    switch (sseState) {
      case 'connected':
        return <Wifi sx={{ fontSize: 14, color: 'success.main' }} />;
      case 'degraded':
        return <WifiOff sx={{ fontSize: 14, color: 'warning.main' }} />;
      case 'disconnected':
        return <WifiOff sx={{ fontSize: 14, color: 'error.main' }} />;
      default:
        return <CircularProgress size={12} />;
    }
  })();

  const sseLabel = (() => {
    switch (sseState) {
      case 'connected': return 'Live (SSE)';
      case 'degraded': return 'Degraded (backend недоступен)';
      case 'disconnected': return 'Disconnected — переподключение...';
      default: return 'Подключение...';
    }
  })();

  return (
    <>
      {/* Bell Icon with Badge — accessible */}
      <Tooltip title={unreadCritical > 0 ? `${unreadCritical} критических уведомлений` : 'Центр уведомлений'}>
        <IconButton
          size="small"
          onClick={handleToggleDrawer}
          data-testid="notification-bell"
          aria-label={unreadCount > 0 ? `${unreadCount} непрочитанных уведомлений` : 'Центр уведомлений — нет непрочитанных'}
          aria-live="polite"
          sx={{ animation: unreadCritical > 0 ? 'cosmo-pulse 2s ease-in-out infinite' : 'none' }}
        >
          <Badge
            badgeContent={unreadCount}
            color={unreadCritical > 0 ? 'error' : 'primary'}
            data-testid="notification-badge"
            sx={{ '& .MuiBadge-badge': { fontSize: 9, fontWeight: 700 } }}
            aria-hidden
          >
            <Notifications fontSize="small" />
          </Badge>
        </IconButton>
      </Tooltip>

      {/* Notification Drawer */}
      <Drawer
        anchor="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        data-testid="notification-drawer"
        slotProps={{
          paper: {
            sx: {
              width: 420, maxWidth: '90vw',
              borderTopLeftRadius: 12, borderBottomLeftRadius: 12,
              bgcolor: 'background.paper',
              boxShadow: '-4px 0 24px rgba(0,0,0,0.15)',
              display: 'flex', flexDirection: 'column',
            },
          },
        }}
        role="dialog"
        aria-label="Центр уведомлений"
      >
        {/* Header */}
        <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: 1, borderColor: 'divider', bgcolor: 'action.hover' }}>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
              <Notifications sx={{ color: unreadCritical > 0 ? 'error.main' : 'primary.main' }} />
              Центр уведомлений
            </Typography>
            <Typography variant="caption" color="text.secondary" aria-live="polite">
              {unreadCount > 0
                ? `${unreadCount} непрочитанных${unreadCritical > 0 ? ` (${unreadCritical} критических)` : ''}`
                : 'Все уведомления прочитаны'}
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <Tooltip title="Отметить все прочитанными">
              <IconButton size="small" onClick={handleMarkAllRead} aria-label="Отметить все прочитанными" disabled={unreadCount === 0} data-testid="notification-mark-all-header">
                <DoneAll fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Обновить из backend">
              <IconButton size="small" onClick={fetchInbox} aria-label="Обновить уведомления" data-testid="notification-refresh">
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
            <IconButton size="small" onClick={() => setDrawerOpen(false)} aria-label="Закрыть панель уведомлений" data-testid="notification-close">
              <Close fontSize="small" />
            </IconButton>
          </Box>
        </Box>

        {/* Body: honest states */}
        <Box sx={{ flex: 1, overflowY: 'auto', py: 1 }}>

          {/* Loading state */}
          {loading && (
            <Box sx={{ p: 4, textAlign: 'center' }}>
              <CircularProgress size={28} sx={{ mb: 1 }} />
              <Typography variant="body2" color="text.secondary">Загрузка уведомлений...</Typography>
            </Box>
          )}

          {/* Error state */}
          {!loading && error && (
            <Box sx={{ p: 2 }} data-testid="notification-error">
              <Alert severity="error" action={
                <Button color="inherit" size="small" onClick={fetchInbox}>Повторить</Button>
              }>
                <AlertTitle>Ошибка загрузки</AlertTitle>
                {error}
              </Alert>
            </Box>
          )}

          {/* Empty state */}
          {!loading && !error && notifications.length === 0 && (
            <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }} role="status" data-testid="notification-empty">
              <CheckCircle sx={{ fontSize: 40, color: 'success.main', mb: 1 }} />
              <Typography variant="body2" sx={{ fontWeight: 600 }}>Все чисто — уведомлений нет</Typography>
              <Typography variant="caption" color="text.secondary">
                Система работает в штатном режиме
              </Typography>
            </Box>
          )}

          {/* Notification list */}
          {!loading && !error && notifications.map((n) => {
            const sevColor = severityColor(n.severity);
            return (
              <Paper
                key={n.id}
                variant="outlined"
                role="button"
                tabIndex={0}
                data-testid="notification-card"
                data-notification-id={n.id}
                data-read={n.read ? 'true' : 'false'}
                aria-label={`${n.severity}: ${n.title}`}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleNotificationClick(n); } }}
                sx={{
                  mx: 1.5, my: 0.5, p: 1.5, borderRadius: 2,
                  cursor: 'pointer',
                  borderLeft: `4px solid ${sevColor}`,
                  bgcolor: n.read ? 'transparent' : 'action.hover',
                  opacity: n.read ? 0.75 : 1,
                  transition: 'all 0.15s ease',
                  '&:hover': { bgcolor: 'action.selected', borderLeftWidth: 6 },
                  '&:focus-visible': { outline: '2px solid primary.main', outlineOffset: 2 },
                }}
                onClick={() => handleNotificationClick(n)}
              >
                {/* Severity + timestamp */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    {severityIcon(n.severity)}
                    <Chip
                      label={n.severity.toUpperCase()}
                      size="small"
                      sx={{ fontSize: 9, height: 18, fontWeight: 700, bgcolor: sevColor, color: '#fff' }}
                    />
                    {n.read === false && (
                      <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'error.main' }} aria-label="непрочитано" />
                    )}
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>
                      {n.created_at ? new Date(n.created_at).toLocaleTimeString() : ''}
                    </Typography>
                    {typeIcon(n.notification_type)}
                  </Box>
                </Box>

                {/* Title */}
                <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>{n.title}</Typography>

                {/* Message */}
                {n.message && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    {n.message}
                  </Typography>
                )}

                {/* Type chip */}
                <Chip
                  icon={typeIcon(n.notification_type)}
                  label={n.notification_type}
                  size="small"
                  variant="outlined"
                  sx={{ fontSize: 9, height: 20 }}
                />
              </Paper>
            );
          })}
        </Box>

        {/* Footer with SSE state */}
        <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider', bgcolor: 'action.hover', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }} aria-live="polite" data-testid="notification-sse-status">
            {sseIndicator}
            <Typography variant="caption" color="text.secondary">{sseLabel}</Typography>
          </Box>
          <Button
            size="small"
            onClick={handleMarkAllRead}
            startIcon={<DoneAll />}
            disabled={unreadCount === 0}
            sx={{ textTransform: 'none', fontSize: 11 }}
            aria-label="Отметить все уведомления прочитанными"
            data-testid="notification-mark-all"
          >
            Прочитано
          </Button>
        </Box>

        {/* CSS Keyframe */}
        <style>{`
          @keyframes cosmo-pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
          }
        `}</style>
      </Drawer>
    </>
  );
}