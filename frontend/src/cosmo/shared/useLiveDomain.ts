/**
 * COS-098: SSE-потребитель доменного стрима — useLiveDomain.
 *
 * Подключается к GET /api/v1/domains/{domain_id}/events/stream (SSE, COS-101).
 * Одно соединение = все прогоны домена: run_created, status_change,
 * batch_complete, gate_decision, finding (sse.py _domain_stream).
 *
 * Контракт (сверен с orchestrator/cosmo/api/routes/sse.py):
 *   - stream_backlog {mode}  — первый event, флаг backlog-режима (COS-088)
 *   - run_created    {run_id, status, domain_id}
 *   - status_change  {run_id, status, previous, domain_id}
 *   - batch_complete {run_id, batch_id, type, status, domain_id}
 *   - gate_decision  {run_id, gate_id, decision, domain_id}
 *   - finding        {run_id, count, delta, domain_id}
 *   - resync         {domain_id, runs: {rid: {status, findings_count}}}
 *     — непрерывность не подтверждена (gap/TTL-вытеснение): замена
 *     статус-состояния снапшотом, а не дельта (COS-088)
 *
 * Auth (COS-079): stream закрыт ticket-гвардом (без ticket — 401).
 * EventSource не умеет custom headers → short-TTL ticket через
 * api.getSseTicket() перед каждым открытием. Reconnect-safe: при обрыве
 * переподключаемся со СВЕЖИМ ticket'ом + last_event_id (COS-088 resample:
 * сервер доливает пропущенное из backlog или шлёт resync).
 *
 * Данные — ТОЛЬКО дельты поверх REST-загрузки: канонический список
 * прогонов view берёт из api.getRuns(), хук ускоряет его до live.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../station/api';

export interface LiveDomainState {
  /** run_id → live статус */
  runStatuses: Record<string, string>;
  /** run_id → findings count (последнее известное) */
  runFindings: Record<string, number>;
  /** run_id → { batch_id → status } — дельты с момента подключения */
  runBatches: Record<string, Record<string, string>>;
  /** run_id → { gate_id → decision } — дельты с момента подключения */
  runGates: Record<string, Record<string, string>>;
  /** true — сервер сообщил о backlog-режиме (resample/replay, COS-088) */
  backlogMode: boolean;
  /** Время последнего применённого события */
  lastUpdate: number | null;
  /** Статус соединения */
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
  /** Ошибка соединения, если есть */
  error: string | null;
}

const INITIAL_STATE: LiveDomainState = {
  runStatuses: {},
  runFindings: {},
  runBatches: {},
  runGates: {},
  backlogMode: false,
  lastUpdate: null,
  connectionStatus: 'connecting',
  error: null,
};

const RECONNECT_MS = 3000;

/**
 * COS-098: хук живого доменного стрима (все прогоны домена одним SSE).
 *
 * @param domainId — ID домена. null/undefined → не подключаемся.
 * @param apiBase — базовый URL API (default: '' — same origin)
 */
export function useLiveDomain(
  domainId: string | undefined | null,
  apiBase: string = '',
): LiveDomainState {
  const [state, setState] = useState<LiveDomainState>(INITIAL_STATE);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // COS-088: последний SSE id (EventSource.lastEventId) для resample при reconnect
  const lastEventIdRef = useRef<string>('');

  const connect = useCallback(async () => {
    if (!domainId) {
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
      }, RECONNECT_MS);
      return;
    }

    // COS-088: reconnect с resample — сервер доливает пропущенное из backlog
    let url = `${apiBase}/api/v1/domains/${encodeURIComponent(domainId)}/events/stream?ticket=${encodeURIComponent(ticket)}`;
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

    es.addEventListener('stream_backlog', (e) => {
      try {
        const data = JSON.parse(e.data);
        setState((s) => ({ ...s, backlogMode: !!data.mode }));
      } catch { /* ignore malformed event */ }
    });

    // COS-088: непрерывность не подтверждена — сервер прислал полный
    // статус-снапшот домена вместо пропущенных событий. Замена статусов.
    es.addEventListener('resync', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        const runs = (data.runs ?? {}) as Record<string, { status?: string; findings_count?: number }>;
        setState((s) => {
          const statuses = { ...s.runStatuses };
          const findings = { ...s.runFindings };
          for (const [rid, snap] of Object.entries(runs)) {
            if (typeof snap.status === 'string') statuses[rid] = snap.status;
            if (typeof snap.findings_count === 'number') findings[rid] = snap.findings_count;
          }
          return { ...s, runStatuses: statuses, runFindings: findings };
        });
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('run_created', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => ({
          ...s,
          runStatuses: { ...s.runStatuses, [data.run_id]: data.status },
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('status_change', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => ({
          ...s,
          runStatuses: { ...s.runStatuses, [data.run_id]: data.status },
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('batch_complete', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => {
          const runBatches = { ...s.runBatches };
          runBatches[data.run_id] = {
            ...(runBatches[data.run_id] ?? {}),
            [data.batch_id]: data.status,
          };
          return { ...s, runBatches, lastUpdate: Date.now() };
        });
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('gate_decision', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => {
          const runGates = { ...s.runGates };
          runGates[data.run_id] = {
            ...(runGates[data.run_id] ?? {}),
            [data.gate_id]: data.decision,
          };
          return { ...s, runGates, lastUpdate: Date.now() };
        });
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('finding', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (e.lastEventId) lastEventIdRef.current = e.lastEventId;
        setState((s) => ({
          ...s,
          runFindings: { ...s.runFindings, [data.run_id]: data.count },
          lastUpdate: Date.now(),
        }));
      } catch { /* ignore malformed event */ }
    });

    es.addEventListener('error', (e: MessageEvent) => {
      // Честная ошибка сервера (domain_not_found) приходит как event 'error'
      // с JSON-телом; обрыв соединения — как error без данных.
      es.close();
      esRef.current = null;

      let serverError: string | null = null;
      try {
        const data = JSON.parse(e.data);
        if (data?.error === 'domain_not_found') {
          serverError = `Domain '${data.domain_id}' not found`;
        }
      } catch { /* обрыв соединения — обычный reconnect-путь */ }

      setState((s) => ({
        ...s,
        connectionStatus: serverError ? 'error' : 'disconnected',
        error: serverError,
      }));

      if (serverError) {
        // domain_not_found не чинится переподключением — не молотим
        return;
      }
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      reconnectTimer.current = setTimeout(() => {
        setState((s) => ({ ...s, connectionStatus: 'connecting' }));
        void connect();
      }, RECONNECT_MS);
    });
  }, [domainId, apiBase]);

  useEffect(() => {
    // Смена домена — чистое переподключение: дельты прошлого домена невалидны
    lastEventIdRef.current = '';
    setState(INITIAL_STATE);
    void connect();
    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
    };
  }, [connect]);

  return state;
}
