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
 * Reconnect-safe: при обрыве автоматически переподключается.
 * Использует EventSource API с полифиллом для автопереподключения.
 */
import { useState, useEffect, useRef, useCallback } from 'react';

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

  const connect = useCallback(() => {
    if (!runId) {
      setState((s) => ({ ...s, connectionStatus: 'disconnected' }));
      return;
    }

    const url = `${apiBase}/api/v1/runs/${encodeURIComponent(runId)}/stream`;
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
        setState((s) => ({
          ...s,
          status: data.status,
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('batch_complete', (e) => {
      try {
        const data = JSON.parse(e.data);
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
        setState((s) => ({
          ...s,
          findingsCount: data.count,
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('error', () => {
      // EventSource сам переподключается.
      // Устанавливаем статус disconnected на случай долгого отсутствия.
      setState((s) => ({
        ...s,
        connectionStatus: es.readyState === EventSource.OPEN ? 'connected' : 'disconnected',
        error: es.readyState === EventSource.CLOSED ? 'Connection closed' : null,
      }));

      // Если CLOSED — пробуем переподключиться через 3s
      if (es.readyState === EventSource.CLOSED) {
        reconnectTimer.current = setTimeout(() => {
          setState((s) => ({ ...s, connectionStatus: 'connecting' }));
          connect();
        }, 3000);
      }
    });
  }, [runId, apiBase]);

  useEffect(() => {
    connect();
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