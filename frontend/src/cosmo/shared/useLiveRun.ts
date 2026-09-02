/**
 * COS-025: SSE-потребитель — хук useLiveRun для живого мониторинга.
 *
 * Подключается к GET /api/v1/runs/{run_id}/stream (SSE).
 * Обновляет DAG без перезагрузки страницы.
 * Статус-бар IDE показывает прогресс.
 *
 * События:
 *   - status_change  — run status transitions (queued→running→succeeded/failed)
 *   - batch_complete — batch finished (build, static_scan, deploy, dynamic_test)
 *   - gate_decision  — gate evaluated (pass, block, manual_required)
 *   - finding        — new security finding count
 *
 * Auth (COS-079): stream закрыт ticket-гвардом — EventSource не умеет
 * custom headers, поэтому перед открытием запрашивается short-TTL ticket
 * через api.getSseTicket() (bearer уходит только в этот POST).
 * Reconnect-safe: при обрыве закрываем EventSource и переподключаемся
 * со СВЕЖИМ ticket'ом (клиентский reconnect — как AlertHUD COS-075).
 *
 * COS-088: последний полученный SSE id запоминается и передаётся
 * query-параметром last_event_id при переподключении — сервер ресемплит
 * backlog и доставляет события, пропущенные за время обрыва. Если
 * непрерывность не подтверждена (TTL-вытеснение / рестарт без Valkey),
 * сервер шлёт event `resync` с полным снапшотом — применяем его как
 * state-замену, не как дельту.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../station/api';

export interface LiveRunState {
  /** Текущий статус прогона */
  status: string;
  /** Статусы batch'ей: { "batch-build": "passed", "batch-scan": "running", ... } */
  batches: Record<string, string>;
  /** DAG-порядок batch-типов: ["build", "static_scan", "deploy", "dynamic_test"] */
  batchOrder: string[];
  /** Решения gate'ов: { "gate-0": "pass", "gate-1": "block", ... } */
  gates: Record<string, string>;
  /** Количество находок */
  findingsCount: number;
  /** Время последнего обновления */
  lastUpdate: number | null;
  /** Статус соединения */
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
  /** Ошибка соединения, если есть */
  error: string | null;
}

const INITIAL_STATE: LiveRunState = {
  status: 'pending',
  batches: {},
  batchOrder: [],
  gates: {},
  findingsCount: 0,
  lastUpdate: null,
  connectionStatus: 'connecting',
  error: null,
};

/**
 * COS-025: хук живого мониторинга прогона через SSE.
 *
 * @param runId — ID прогона. Если null/undefined — не подключаемся.
 * @param apiBase — базовый URL API (default: '' — same origin)
 */
export function useLiveRun(
  runId: string | undefined | null,
  apiBase: string = '',
): LiveRunState & { close: () => void } {
  const [state, setState] = useState<LiveRunState>(INITIAL_STATE);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // COS-088: последний SSE id (EventSource.lastEventId) для resample при reconnect
  const lastEventIdRef = useRef<string>('');

  const connect = useCallback(async () => {
    if (!runId) {
      setState((s) => ({ ...s, connectionStatus: 'disconnected' }));
      return;
    }

    // COS-079: fresh ticket per connection attempt (one-time/expiring)
    let ticket: string;
    try {
      const t = await api.getSseTicket();
      ticket = t.ticket;
    } catch {
      setState((s) => ({
        ...s,
        connectionStatus: 'disconnected',
        error: 'ticket unavailable',
      }));
      reconnectTimer.current = setTimeout(() => {
        void connect();
      }, 3000);
      return;
    }

    // COS-088: reconnect с resample — сервер доливает пропущенное из backlog
    let url = `${apiBase}/api/v1/runs/${encodeURIComponent(runId)}/stream?ticket=${encodeURIComponent(ticket)}`;
    if (lastEventIdRef.current) {
      url += `&last_event_id=${encodeURIComponent(lastEventIdRef.current)}`;
    }
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener('open', () => {
      setState((s) => ({
        ...s,
        connectionStatus: 'connected',
        error: null,
      }));
    });

    es.addEventListener('status_change', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => {
          const next: LiveRunState = {
            ...s,
            status: data.status,
            lastUpdate: Date.now(),
          };
          // COS-088: initial-событие несёт полный снапшот — hydrate дельт,
          // которых не было на момент подключения
          if (Array.isArray(data.batches)) {
            next.batches = { ...s.batches };
            for (const b of data.batches) next.batches[b.id] = b.status;
            next.batchOrder = data.batches.map((b: { type: string }) => b.type);
          }
          if (Array.isArray(data.gates)) {
            next.gates = { ...s.gates };
            for (const g of data.gates) if (g.decision) next.gates[g.id] = g.decision;
          }
          if (typeof data.findings_count === 'number') {
            next.findingsCount = data.findings_count;
          }
          return next;
        });
      } catch { /* ignore malformed event */ }
    });

    // COS-088: непрерывность не подтверждена (gap/TTL-вытеснение) — сервер
    // прислал полный снапшот вместо пропущенных событий. Замена state.
    es.addEventListener('resync', (e) => {
      try {
        const data = JSON.parse(e.data);
        const batches: Record<string, string> = {};
        for (const b of data.batches ?? []) batches[b.id] = b.status;
        const gates: Record<string, string> = {};
        for (const g of data.gates ?? []) if (g.decision) gates[g.id] = g.decision;
        setState((s) => ({
          ...s,
          status: data.status ?? s.status,
          batches,
          gates,
          findingsCount: data.findings_count ?? s.findingsCount,
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('batch_complete', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => ({
          ...s,
          batches: { ...s.batches, [data.batch_id]: data.status },
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('gate_decision', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => ({
          ...s,
          gates: { ...s.gates, [data.gate_id]: data.decision },
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('finding', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => ({
          ...s,
          findingsCount: data.count,
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('error', () => {
      // COS-079: ticket может истечь/сгореть — EventSource автопереподключение
      // бесполезно со старым URL. Закрываем и переподключаемся со свежим ticket.
      es.close();
      esRef.current = null;
      setState((s) => ({ ...s, connectionStatus: 'disconnected', error: null }));

      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      reconnectTimer.current = setTimeout(() => {
        setState((s) => ({ ...s, connectionStatus: 'connecting' }));
        void connect();
      }, 3000);
    });
  }, [runId, apiBase]);

  useEffect(() => {
    void connect();
    return () => {
      if (esRef.current) {
        esRef.current.close();
      }
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
    };
  }, [connect]);

  const close = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
    }
    setState((s) => ({ ...s, connectionStatus: 'disconnected', error: null }));
  }, []);

  return { ...state, close };
}

/**
 * COS-025: Хелпер — процент завершённых batch'ей.
 */
export function batchProgress(state: LiveRunState): number {
  const total = Object.keys(state.batches).length;
  if (total === 0) return 0;
  const completed = Object.values(state.batches).filter(
    (s) => s === 'passed' || s === 'failed',
  ).length;
  return Math.round((completed / total) * 100);
}

/**
 * COS-025: Хелпер — человекопонятная метка статуса для статус-бара.
 */
export function statusLabel(state: LiveRunState): string {
  const labels: Record<string, string> = {
    draft: 'Черновик',
    pending: 'Ожидание',
    queued: 'В очереди',
    running: 'Выполняется',
    succeeded: 'Успешно',
    failed: 'Ошибка',
    blocked: 'Заблокирован',
    cancelled: 'Отменён',
  };
  return labels[state.status] || state.status;
}

/**
 * COS-025: Хелпер — состояние статус-бара IDE.
 * Возвращает { label, className } для отрисовки.
 */
export function statusBarInfo(state: LiveRunState): {
  label: string;
  color: string;
  progress: number;
} {
  const label = statusLabel(state);
  const progress = batchProgress(state);
  const colorMap: Record<string, string> = {
    pending: '#94a3b8',
    queued: '#94a3b8',
    running: '#06b6d4',
    succeeded: '#10b981',
    failed: '#ef4444',
    blocked: '#f59e0b',
    cancelled: '#64748b',
  };

  return {
    label,
    color: colorMap[state.status] || '#94a3b8',
    progress,
  };
}