// @vitest-environment jsdom
/**
 * COS-098: ReleaseReadiness — честные состояния + live (domain SSE).
 *
 * Покрывает:
 *   - happy path: domains/releases/runs с бэкенда, summary по живым статусам
 *   - empty: нет доменов / нет релизов и прогонов — честные info-alerts
 *   - error: REST-ошибка → load-error + retry
 *   - live: MockEventSource → status_change/resync обновляют грид прогонов
 *   - run detail: evidence chain (verified/integrity) + degraded-логи (COS-097)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CosmoThemeProvider } from './theme';
import { ReleaseReadiness } from './station/views/ReleaseReadiness';
import type { Release } from './station/api';

interface Listener { (e: { data: string; lastEventId?: string }): void }

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  listeners: Record<string, Listener[]> = {};
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: Listener) {
    (this.listeners[type] ??= []).push(fn);
  }
  close() { this.closed = true; }
  emit(type: string, data: unknown, lastEventId?: string) {
    for (const fn of this.listeners[type] ?? []) {
      fn({ data: JSON.stringify(data), lastEventId });
    }
  }
}

const mockDomains = [
  { id: 'dom-alpha', label: 'Альфа', forge_binding: {}, rbac_config: {}, quota: {} },
  { id: 'dom-beta', label: 'Бета', forge_binding: {}, rbac_config: {}, quota: {} },
];

const mockReleases: Release[] = [
  {
    id: 'rel-001', version: 'v1.2.0', domain_id: 'dom-alpha', plan_id: 'plan-1',
    run_ids: ['run-101', 'run-102'], trigger: 'pre_release', status: 'approved',
    changelog: 'fix: auth', artifacts: ['sbom.json'],
    approvals: [{ decided_by: 'sec', decision: 'approved', comment: '', decided_at: new Date().toISOString(), signature: 'sig' }],
    current_zone: 'zt', transfer_history: [],
  },
  {
    id: 'rel-002', version: 'v0.9.0', domain_id: 'dom-alpha', plan_id: 'plan-2',
    run_ids: [], trigger: 'manual', status: 'draft',
    changelog: '', artifacts: [], approvals: [], current_zone: 'zr', transfer_history: [],
  },
];

const mockRuns = [
  {
    id: 'run-101', plan_id: 'plan-1', trigger: 'pre_release', initiator: 'dev',
    domain_id: 'dom-alpha', status: 'running', started_at: null, finished_at: null,
    created_at: new Date().toISOString(),
    batches: [{ id: 'batch-1', plan_id: 'plan-1', type: 'build', status: 'passed', bricks: [], artifacts: [], evidence: [] }],
    gates: ['gate-1'], findings: [],
  },
  {
    id: 'run-102', plan_id: 'plan-1', trigger: 'manual', initiator: 'dev',
    domain_id: 'dom-alpha', status: 'failed', started_at: null, finished_at: null,
    created_at: new Date().toISOString(),
    batches: [], gates: [], findings: ['f1'],
  },
];

const mockEvidence = {
  chain: { entries: [], length: 2, verified: true, last_hash: 'abc' },
  verified: true,
  integrity: 'ok',
  anchor: null,
  head_mismatch: false,
  tampered_entries: [],
  tampered_details: [],
  broken_links: [],
  unsealed_entries: [],
  tampered_chain: false,
  replay_count: 0,
  total_entries: 2,
};

const mockTrail = [
  { id: 1, gate_id: 'gate-1', plan_id: 'plan-1', run_id: 'run-101', batch_id: null, decision: 'pass', decided_by: 'op', initiator: '', signature: null, policy_snapshot: {}, evidence_ids: [], decided_at: new Date().toISOString(), created_at: new Date().toISOString() },
];

const mockPlanGates = [
  { id: 'gate-1', type: 'automatic', position: 0, policy: { rules: [] }, decision: 'pass', decided_by: 'auto', signature: null, decided_at: null },
];

function okFetch(routes: Record<string, unknown>) {
  return vi.fn().mockImplementation((url: string) => {
    for (const [needle, body] of Object.entries(routes)) {
      if (url.includes(needle)) {
        return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
      }
    }
    return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
  });
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource);
});

describe('COS-098: ReleaseReadiness', () => {
  it('рендерит summary + releases/runs гриды из REST, LIVE-бейдж честный', async () => {
    globalThis.fetch = okFetch({
      '/api/v1/domains': mockDomains,
      '/api/v1/releases': mockReleases,
      '/api/v1/runs': mockRuns,
      '/api/v1/notifications/sse-ticket': { ticket: 't', recipient_id: 'op', expires_in: 60 },
    });

    render(
      <CosmoThemeProvider>
        <ReleaseReadiness />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('release-readiness-view')).toBeTruthy();
      expect(screen.getByTestId('domain-select')).toBeTruthy();
    });

    // Summary по живым статусам: 2 релиза, 1 approved
    await waitFor(() => {
      expect(screen.getByText('2')).toBeTruthy(); // релизов
    });
    // Releases grid: оба релиза
    await waitFor(() => {
      expect(screen.getByText('rel-001')).toBeTruthy();
      expect(screen.getByText('rel-002')).toBeTruthy();
    });
    // Runs grid
    await waitFor(() => {
      expect(screen.getByTestId('run-status-run-101')).toBeTruthy();
      expect(screen.getByTestId('run-status-run-102')).toBeTruthy();
    });
    // Честный LIVE-бейдж (mock не открывает соединение → не connected)
    const badge = screen.getByTestId('live-badge');
    expect(badge.textContent).toMatch(/LIVE/);
    expect(badge.textContent).not.toMatch(/^LIVE$/);
  });

  it('live: status_change по domain SSE обновляет статус прогона без перезагрузки', async () => {
    globalThis.fetch = okFetch({
      '/api/v1/domains': mockDomains,
      '/api/v1/releases': mockReleases,
      '/api/v1/runs': mockRuns,
      '/api/v1/notifications/sse-ticket': { ticket: 't', recipient_id: 'op', expires_in: 60 },
    });

    render(
      <CosmoThemeProvider>
        <ReleaseReadiness />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('run-status-run-101')).toBeTruthy();
    });

    // Открываем доменный SSE и шлём status_change
    const domainEs = MockEventSource.instances.find((es) => es.url.includes('/events/stream'));
    expect(domainEs).toBeTruthy();
    domainEs!.emit('open', {});
    domainEs!.emit('status_change', { run_id: 'run-101', status: 'succeeded', previous: 'running', domain_id: 'dom-alpha' }, 'sse-1');

    await waitFor(() => {
      expect(screen.getByTestId('run-status-run-101').textContent).toContain('succeeded');
    });

    // backlog-флаг честно отображается в бейдже
    domainEs!.emit('stream_backlog', { mode: 'valkey' });
    await waitFor(() => {
      expect(screen.getByTestId('live-badge').textContent).toContain('backlog');
    });
  });

  it('run detail: evidence chain + честный degraded для логов (COS-097)', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/v1/domains')) return Promise.resolve(new Response(JSON.stringify(mockDomains), { status: 200 }));
      if (url.includes('/api/v1/releases')) return Promise.resolve(new Response(JSON.stringify(mockReleases), { status: 200 }));
      if (url.includes('/api/v1/runs/run-101/evidence')) return Promise.resolve(new Response(JSON.stringify(mockEvidence), { status: 200 }));
      if (url.includes('/api/v1/gates/trail/runs')) return Promise.resolve(new Response(JSON.stringify(mockTrail), { status: 200 }));
      if (url.includes('/api/v1/runs/run-101')) return Promise.resolve(new Response(JSON.stringify(mockRuns[0]), { status: 200 }));
      if (url.includes('/api/v1/runs')) return Promise.resolve(new Response(JSON.stringify(mockRuns), { status: 200 }));
      if (url.includes('/api/v1/gates')) return Promise.resolve(new Response(JSON.stringify(mockPlanGates), { status: 200 }));
      if (url.includes('/api/v1/notifications/sse-ticket')) return Promise.resolve(new Response(JSON.stringify({ ticket: 't', recipient_id: 'op', expires_in: 60 }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(
      <CosmoThemeProvider>
        <ReleaseReadiness />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('run-status-run-101')).toBeTruthy();
    });

    // Клик по строке прогона → run-detail
    fireEvent.click(screen.getByTestId('run-status-run-101').closest('[role="row"]')!);

    const detail = await screen.findByTestId('run-detail');
    expect(detail).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId('evidence-verified').textContent).toContain('Verified');
      expect(screen.getByTestId('evidence-integrity').textContent).toContain('ok');
    });
    // Trail
    expect(screen.getByText(/gate-1 → pass/)).toBeTruthy();
    // Логи — честный degraded, не пустышка
    expect(screen.getByTestId('logs-degraded').textContent).toContain('COS-097');
  });

  it('empty: нет доменов — честный info, не пустой экран', async () => {
    globalThis.fetch = okFetch({
      '/api/v1/domains': [],
      '/api/v1/notifications/sse-ticket': { ticket: 't', recipient_id: 'op', expires_in: 60 },
    });

    render(
      <CosmoThemeProvider>
        <ReleaseReadiness />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Домены не найдены/)).toBeTruthy();
    });
  });

  it('error: REST-ошибка → load-error + retry, не тихий ноль', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/v1/domains')) {
        return Promise.resolve(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }));
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(
      <CosmoThemeProvider>
        <ReleaseReadiness />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('load-error').textContent).toContain('boom');
    });
  });

  it('resync (COS-088): полный снапшот замещает статусы', async () => {
    globalThis.fetch = okFetch({
      '/api/v1/domains': mockDomains,
      '/api/v1/releases': mockReleases,
      '/api/v1/runs': mockRuns,
      '/api/v1/notifications/sse-ticket': { ticket: 't', recipient_id: 'op', expires_in: 60 },
    });

    render(
      <CosmoThemeProvider>
        <ReleaseReadiness />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('run-status-run-101')).toBeTruthy();
    });

    const domainEs = MockEventSource.instances.find((es) => es.url.includes('/events/stream'));
    domainEs!.emit('resync', {
      domain_id: 'dom-alpha',
      runs: {
        'run-101': { status: 'failed', findings_count: 3 },
        'run-102': { status: 'succeeded', findings_count: 0 },
      },
    }, 'sse-2');

    await waitFor(() => {
      expect(screen.getByTestId('run-status-run-101').textContent).toContain('failed');
      expect(screen.getByTestId('run-status-run-102').textContent).toContain('succeeded');
    });
  });
});
