// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CosmoThemeProvider } from './theme';
import { Overview } from './station/views/Overview';
import { Applications } from './station/views/Applications';
import { RunControl } from './station/views/RunControl';
import { Gates } from './station/views/Gates';
import { Evidence } from './station/views/Evidence';
import { Catalog } from './station/views/Catalog';
import { PipelineStudio } from './station/views/PipelineStudio';
import { Releases } from './station/views/Releases';
import { AppGraph } from './station/views/AppGraph';
import { AuditLog } from './station/views/AuditLog';
import { RunComparison } from './station/views/RunComparison';
import { Analytics } from './station/views/Analytics';
import { GatePolicyBuilder } from './station/views/GatePolicyBuilder';
import { ReleaseTransferWizard } from './station/views/ReleaseTransferWizard';
import { AlertHUD } from './station/views/AlertHUD';
import { ExecutivePostureWidget } from './station/views/ExecutivePostureWidget';
import { SlaRemediationWidget } from './station/views/SlaRemediationWidget';
import { WebIDEShell } from './ide/WebIDEShell';

vi.mock('@monaco-editor/react', () => ({
  default: () => null,
  DiffEditor: () => null,
}));

const mockDomains = [
  {
    id: 'dom-alpha',
    label: 'Alpha Core Domain',
    forge_binding: { forge_type: 'gitea', url: 'http://gitea:3000', token_ref: 'TOK' },
    rbac_config: {},
    quota: { max_runs: 50, max_storage_gb: 100, max_cpu: 8 },
  },
];

const mockApps = [
  {
    id: 'app-payments',
    domain_id: 'dom-alpha',
    level: 1,
    repo_binding: { forge_id: 'gitea', repo_path: 'org/payments', default_branch: 'main' },
    pipeline_plan_id: 'plan-payments',
  },
  {
    id: 'lib-auth',
    domain_id: 'dom-alpha',
    level: 0,
    repo_binding: { forge_id: 'gitea', repo_path: 'org/auth-lib', default_branch: 'main' },
  },
];

const mockGroups = [
  {
    id: 'grp-fintech',
    domain_id: 'dom-alpha',
    level: 2,
    name: 'FinTech Services',
  },
];

const mockBricks = [
  {
    id: 'b-build',
    name: 'Go Builder',
    type: 'build',
    source: 'internal',
    definition: { executor: 'woodpecker', image: 'golang:1.22', timeout_s: 600, inputs: {}, outputs: {} },
    depends_on: [],
    gates: [],
  },
  {
    id: 'b-sast',
    name: 'Sonar SAST',
    type: 'sast',
    source: 'internal',
    definition: { executor: 'woodpecker', image: 'sonarqube:scanner', timeout_s: 1200, inputs: {}, outputs: {} },
    depends_on: ['b-build'],
    gates: [],
  },
];

const mockPlans = [
  {
    id: 'plan-payments',
    app_id: 'app-payments',
    level: 'app',
    scope_id: 'app-payments',
    compiled_at: new Date().toISOString(),
    compiled_hash: 'sha256:1234567890abcdef',
    brick_ids: ['b-build', 'b-sast'],
  },
];

const mockRuns = [
  {
    id: 'run-101',
    plan_id: 'plan-payments',
    trigger: 'scheduled',
    initiator: 'cron-system',
    domain_id: 'dom-alpha',
    status: 'running',
    created_at: new Date().toISOString(),
    batches: [
      { id: 'batch-1', plan_id: 'plan-payments', type: 'build', status: 'passed', bricks: ['b-build'], artifacts: [], evidence: [] },
      { id: 'batch-2', plan_id: 'plan-payments', type: 'static_scan', status: 'running', bricks: ['b-sast'], artifacts: [], evidence: [] },
    ],
    gates: ['gate-qg'],
    findings: [],
  },
];

const mockGates = [
  {
    id: 'gate-qg',
    type: 'automatic',
    position: 0,
    policy: {
      rules: [
        { finding_type: 'Critical', action: 'block', max_count: 0 },
        { finding_type: 'High', action: 'warn', max_count: 3 },
      ],
    },
    decision: null,
  },
  {
    id: 'gate-manual-release',
    type: 'manual',
    position: 1,
    policy: {
      rules: [
        { finding_type: 'Critical', action: 'block', max_count: 0 },
      ],
    },
    decision: null,
  },
  {
    id: 'gate-manual-compliance',
    type: 'manual',
    position: 2,
    policy: {
      rules: [
        { finding_type: 'High', action: 'warn', max_count: 2 },
      ],
    },
    decision: null,
  },
];

beforeEach(() => {
  // Mock global fetch for API calls
  globalThis.fetch = vi.fn().mockImplementation((url: string) => {
    if (url.includes('/graph')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            domain: 'dom-alpha',
            groups: mockGroups,
            apps: mockApps.filter((a) => a.level >= 1),
            libraries: mockApps.filter((a) => a.level === 0),
          }),
          { status: 200 }
        )
      );
    }
    if (url.includes('/api/v1/domains')) return Promise.resolve(new Response(JSON.stringify(mockDomains), { status: 200 }));
    if (url.includes('/api/v1/apps')) return Promise.resolve(new Response(JSON.stringify(mockApps), { status: 200 }));
    if (url.includes('/api/v1/groups')) return Promise.resolve(new Response(JSON.stringify(mockGroups), { status: 200 }));
    if (url.includes('/api/v1/bricks')) return Promise.resolve(new Response(JSON.stringify(mockBricks), { status: 200 }));
    if (url.includes('/api/v1/plans')) return Promise.resolve(new Response(JSON.stringify(mockPlans), { status: 200 }));
    if (url.includes('/api/v1/runs')) return Promise.resolve(new Response(JSON.stringify(mockRuns), { status: 200 }));
    if (url.includes('/api/v1/gates')) return Promise.resolve(new Response(JSON.stringify(mockGates), { status: 200 }));
    if (url.includes('/api/v1/metrics/trends')) {
      return Promise.resolve(new Response(JSON.stringify({
        pass_rate_trend: [{ date: '2026-08-28', value: 85 }, { date: '2026-08-29', value: 92 }],
        findings_severity_trend: [{ date: '2026-08-29', critical: 2, high: 3, medium: 5 }],
        mean_duration_trend: [{ date: '2026-08-29', value: 145 }],
        flaky_gates: [{ gate_id: 'gate-qg', plan_id: 'plan-test', total_decisions: 10, blocks: 3, block_rate: 30, passes: 7 }],
        summary: { total_runs: 25, pass_rate_pct: 92.0, failed_runs: 2, mean_duration_seconds: 145, total_critical_findings: 2, last_updated: new Date().toISOString() },
        domain_id: 'all', days: 30,
      }), { status: 200 }));
    }
    if (url.includes('/api/v1/posture')) {
      return Promise.resolve(new Response(JSON.stringify({
        score: 85,
        grade: 'B',
        critical_open: 1,
        high_open: 4,
        gate_pass_rate_pct: 89.5,
        sla_compliance_pct: 93.2,
        gost_56939_pct: 82,
        cbr_683_pct: 88,
        cbr_757_pct: 79,
        auto_gates_pct: 68.0,
        manual_gates_count: 8,
        total_gates: 25,
        last_updated: new Date().toISOString(),
      }), { status: 200 }));
    }
    if (url.includes('/api/v1/metrics/sla')) {
      return Promise.resolve(new Response(JSON.stringify({
        overall_compliance_pct: 76,
        total_open: 15,
        breached_count: 3,
        critical_breached: 1,
        high_breached: 1,
        medium_breached: 1,
        tiers: [
          { tier: 'critical', sla_hours: 24, on_time: 3, breached: 1, total: 4, compliance_pct: 75 },
          { tier: 'high', sla_hours: 168, on_time: 5, breached: 1, total: 6, compliance_pct: 83 },
          { tier: 'medium', sla_hours: 720, on_time: 4, breached: 1, total: 5, compliance_pct: 80 },
        ],
        breaches: [
          { id: 'slab-1', finding_id: 'FND-101', title: 'SQL Injection in auth', tier: 'critical', opened_at: new Date().toISOString(), sla_deadline: new Date().toISOString(), overdue_hours: 12, repo: 'cbr/wallet', file: 'src/auth/login.ts', line: 88, app_id: 'app-auth' },
          { id: 'slab-2', finding_id: 'FND-202', title: 'XSS in reports', tier: 'high', opened_at: new Date().toISOString(), sla_deadline: new Date().toISOString(), overdue_hours: 72, repo: 'cbr/reports', file: 'src/views/Report.tsx', line: 45, app_id: 'app-reports' },
          { id: 'slab-3', finding_id: 'FND-303', title: 'Missing CSP header', tier: 'medium', opened_at: new Date().toISOString(), sla_deadline: new Date().toISOString(), overdue_hours: 360, repo: 'cbr/frontend', file: 'src/index.html', line: 1, app_id: 'app-frontend' },
        ],
        last_updated: new Date().toISOString(),
      }), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
  });
});

describe('COS-022: Control Station Core Views', () => {
  it('Overview view: рендерит дашборд, активные runs и security gates', async () => {
    render(
      <CosmoThemeProvider>
        <Overview selectedDomain="dom-alpha" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Обзор системы (Control Station)')).toBeTruthy();
    expect(screen.getByText('Активные прогоны')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('run-101').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('gate-qg').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('Applications view: рендерит таблицу приложений, уровни и Git-репозитории', async () => {
    render(
      <CosmoThemeProvider>
        <Applications selectedDomain="dom-alpha" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Приложения и архитектура')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('app-payments').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('lib-auth').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('L1 Приложение')).toBeTruthy();
      expect(screen.getByText('L0 Библиотека')).toBeTruthy();
    });
  });

  it('RunControl view: рендерит список прогонов и детальную панель со статусами батчей', async () => {
    render(
      <CosmoThemeProvider>
        <RunControl selectedDomain="dom-alpha" initialRunId="run-101" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Run Control Plane (Прогоны)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('run-101').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Этапы выполнения (Batches)')).toBeTruthy();
      expect(screen.getByText('build')).toBeTruthy();
      expect(screen.getByText('static_scan')).toBeTruthy();
    });
  });

  it('COS-064: RunControl — рендерит чекбоксы пакетного выбора и плавающий экшн-бар', async () => {
    render(
      <CosmoThemeProvider>
        <RunControl selectedDomain="dom-alpha" />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText('run-101').length).toBeGreaterThanOrEqual(1);
    });

    // Checkboxes should exist for active runs
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBeGreaterThanOrEqual(1);
  });

  it('Gates view: рендерит инспектор гейтов, правила политик и кнопки вердикта', async () => {
    render(
      <CosmoThemeProvider>
        <Gates />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Security Gates (Контрольные точки)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('gate-qg').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Одобрить (Pass)')).toBeTruthy();
      expect(screen.getByText('Заблокировать (Block)')).toBeTruthy();
      expect(screen.getByText('Уровень: Critical')).toBeTruthy();
    });
  });

  it('COS-064: Gates — рендерит чекбоксы для ожидающих ручных гейтов и показывает их количество', async () => {
    render(
      <CosmoThemeProvider>
        <Gates />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Security Gates (Контрольные точки)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('gate-qg').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('gate-manual-release').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('gate-manual-compliance').length).toBeGreaterThanOrEqual(1);
    });

    // Verify the pending manual gates summary badge
    expect(screen.getByText('2 ожидают ручного вердикта')).toBeTruthy();
  });

  it('Evidence view: рендерит SHA-256 цепочку доказательств и метаданные', async () => {
    render(
      <CosmoThemeProvider>
        <Evidence initialRunId="run-101" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Журнал доказательств (Evidence Ledger)')).toBeTruthy();
    expect(screen.getByText('Цепочка SHA-256 валидна')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Provenance & Metadata (JSON)')).toBeTruthy();
    });
  });

  it('Catalog view: рендерит каталог кирпичей и параметры Docker-образов', async () => {
    render(
      <CosmoThemeProvider>
        <Catalog />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Каталог кирпичей (Pipeline Bricks)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('Go Builder').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Sonar SAST').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Docker образ:')).toBeTruthy();
    });
  });

  it('PipelineStudio view: рендерит скомпилированный DAG план и шаги выполнения', async () => {
    render(
      <CosmoThemeProvider>
        <PipelineStudio selectedAppId="app-payments" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Pipeline Studio & DAG (Пайплайны)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('plan-payments').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Граф выполнения шагов (DAG Workflow)')).toBeTruthy();
    });
  });

  it('Releases view: рендерит релизы, состав (nodes + edges) и трансфер ЗР→ЗТ→ЗПЭ', async () => {
    render(
      <CosmoThemeProvider>
        <Releases selectedDomain="cbr" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Release Management (Управление Релизами)')).toBeTruthy();
    expect(screen.getByText('Зона Разработки (Build & Unit)')).toBeTruthy();
    expect(screen.getByText('Зона Тестирования (DAST / SAST / Gates)')).toBeTruthy();
    expect(screen.getByText('Зона Пром Эксплуатации (Signed & Airgap)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('Цифровой Рубль — Релиз Q3 2026').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Состав релиза (Nodes / Компоненты)')).toBeTruthy();
      expect(screen.getByText('Digital Wallet API')).toBeTruthy();
      expect(screen.getByText('GOST Crypto Provider')).toBeTruthy();
      expect(screen.getByText('Трансфер: ЗТ → ЗПЭ')).toBeTruthy();
    });
  });

  it('AppGraph view: рендерит редактор топологии, L0/L1/L2 легенду и узлы', async () => {
    render(
      <CosmoThemeProvider>
        <AppGraph selectedDomain="dom-alpha" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Graph Topology Editor (Редактор топологии)')).toBeTruthy();
    expect(screen.getByText('Авто-раскладка')).toBeTruthy();
    expect(screen.getByText('Экспорт топологии')).toBeTruthy();
    expect(screen.getByText('Добавить узел')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('L0 Библиотека')).toBeTruthy();
      expect(screen.getByText('L1 Приложение')).toBeTruthy();
      expect(screen.getByText('L2 Группа')).toBeTruthy();
      expect(screen.getAllByText('app-payments').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('WebIDEShell: рендерит файл-дерево, тулбар с Diff View, Commit & Push и Commit & Run', async () => {
    const handleNavigate = vi.fn();
    render(
      <WebIDEShell
        repo="payments/api"
        file="scenarios/auth.wire"
        line={12}
        onNavigateToStation={handleNavigate}
      />
    );

    expect(screen.getByText('IDE')).toBeTruthy();
    expect(screen.getByText('Cosmoport')).toBeTruthy();
    expect(screen.getByText('payments/api')).toBeTruthy();
    expect(screen.getByText('Diff (⌘D)')).toBeTruthy();
    expect(screen.getByText('Commit & Push')).toBeTruthy();
    expect(screen.getByText('Commit & Run')).toBeTruthy();
    expect(screen.getByText('Terminal & Pipeline Logs')).toBeTruthy();
    expect(screen.getByText('▶ Click gutter to run step')).toBeTruthy();

    // Toggle Diff View via button
    fireEvent.click(screen.getByText('Diff (⌘D)'));
    expect(screen.getByText('✓ Diff View')).toBeTruthy();

    // Open Commit & Push Dialog
    fireEvent.click(screen.getByText('Commit & Push'));
    expect(screen.getByText('Commit & Push изменения')).toBeTruthy();
    expect(screen.getByText('Запушить в репозиторий')).toBeTruthy();
  });

  it('AuditLog view: рендерит журнал событий аудита, фильтры и кнопки экспорта', async () => {
    render(
      <CosmoThemeProvider>
        <AuditLog />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Журнал аудита безопасности (Audit Log)')).toBeTruthy();
    expect(screen.getByText('Экспорт CSV')).toBeTruthy();
    expect(screen.getByText('Экспорт JSON')).toBeTruthy();
    expect(screen.getByPlaceholderText('Поиск по пользователю...')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('operator@cosmo.local').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('gate_decision').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('transfer_zone').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('COS-070: RunComparison — рендерит селекторы Base/Target, дельта-карточки и дифф-таблицу находок', async () => {
    render(
      <CosmoThemeProvider>
        <RunComparison />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Сравнительный анализ прогонов (Run Diff)')).toBeTruthy();
    expect(screen.getByText('Поменять местами')).toBeTruthy();
    expect(screen.getAllByText('VS').length).toBeGreaterThanOrEqual(1);

    // Delta cards
    expect(screen.getByText('Новые уязвимости (Регрессии)')).toBeTruthy();
    expect(screen.getByText('Исправлено (Fixed)')).toBeTruthy();
    expect(screen.getByText('Без изменений (Persistent)')).toBeTruthy();
    expect(screen.getByText('Время выполнения')).toBeTruthy();

    // Findings diff table header
    expect(screen.getByText('Построчный дифф находок (Findings Diff)')).toBeTruthy();

    // Batch timeline
    expect(screen.getByText('Сравнение длительности шагов DAG (Batch Timeline)')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getAllByText('NEW').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('FIXED').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('SAME').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('COS-062: Analytics — рендерит KPI карточки, спарклайны Pass Rate и трендовые индикаторы', async () => {
    render(
      <CosmoThemeProvider>
        <Analytics selectedDomain="dom-alpha" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Аналитика и Тренды Безопасности')).toBeTruthy();
    expect(screen.getByText('Pass Rate (Успешность)')).toBeTruthy();
    expect(screen.getByText('Критических уязвимостей')).toBeTruthy();
    expect(screen.getByText('Среднее время прогона')).toBeTruthy();
    expect(screen.getByText('Сбойных гейтов')).toBeTruthy();
    expect(screen.getByText('Динамика Pass Rate (%)')).toBeTruthy();
    expect(screen.getByText('Средняя длительность прогона (сек)')).toBeTruthy();
    expect(screen.getByText('Уязвимости по критичности')).toBeTruthy();
    expect(screen.getByText('Сбойные Security Gates')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Растёт')).toBeTruthy();
    });
  });

  it('COS-080: GatePolicyBuilder — рендерит селектор гейтов, шаблоны политик и редактор правил', async () => {
    render(
      <CosmoThemeProvider>
        <GatePolicyBuilder />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Редактор политик Security Gates')).toBeTruthy();
    expect(screen.getByText('Экспорт JSON')).toBeTruthy();
    expect(screen.getByText('Тест на findings')).toBeTruthy();
    expect(screen.getByText('Сохранить политику')).toBeTruthy();
    expect(screen.getAllByText('Выберите Gate для редактирования').length).toBeGreaterThanOrEqual(1);

    // Template cards visible
    expect(screen.getByText('Строгий ГОСТ')).toBeTruthy();
    expect(screen.getByText('Standard Release')).toBeTruthy();
    expect(screen.getByText('Fast Hotfix')).toBeTruthy();

    // Admission settings
    expect(screen.getByText('Требования допуска (Admission Gate)')).toBeTruthy();
    expect(screen.getByText('Требовать ручную подпись офицера безопасности')).toBeTruthy();

    // Preview section
    expect(screen.getByText('Препросмотр результирующей конфигурации')).toBeTruthy();
  });

  it('COS-090: ReleaseTransferWizard — рендерит 3-шаговый Stepper Pre-Flight/Zone/Signoff', async () => {
    const mockRelease = {
      id: 'rel-test-001',
      version: 'v2.0.0',
      name: 'Test Release',
      domain_id: 'cbr',
      zone: 'ЗР' as const,
      status: 'draft' as const,
      created_at: new Date().toISOString(),
      manifest: {
        release_id: 'rel-test-001',
        version: 'v2.0.0',
        domain_id: 'cbr',
        zone: 'ЗР' as const,
        created_at: new Date().toISOString(),
        created_by: 'test@cosmo.local',
        nodes: [
          { id: 'node-1', name: 'Wallet API', type: 'service' as const, version: '2.0.0', repo: 'cbr/wallet', commit: 'abc123' },
        ],
        edges: [],
        metadata: {},
        signature: 'sha256:test',
      },
      history: [],
    };

    render(
      <CosmoThemeProvider>
        <ReleaseTransferWizard release={mockRelease} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Мастер трансфера релиза')).toBeTruthy();
    expect(screen.getByText('Pre-Flight Checks (Проверка готовности)')).toBeTruthy();
    expect(screen.getByText('Target Zone & Manifest Diff')).toBeTruthy();
    expect(screen.getByText('Signoff & 2FA (Подтверждение трансфера)')).toBeTruthy();

    // Pre-flight items (loaded async)
    await waitFor(() => {
      expect(screen.getAllByText(/Security Gates/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Незавершенные батчи')).toBeTruthy();
      expect(screen.getByText('Подпись офицера ИБ')).toBeTruthy();
    });
    expect(screen.getByText('Подтвердить и продолжить')).toBeTruthy();
  });

  it('COS-100: ExecutivePostureWidget — рендерит радиальный индикатор Security Posture, сводку комплаенса и кнопку отчёта', async () => {
    render(
      <CosmoThemeProvider>
        <ExecutivePostureWidget domain="all" />
      </CosmoThemeProvider>
    );

    // Header elements
    expect(screen.getByText('Security Posture КИТС')).toBeTruthy();
    expect(screen.getByText('C-Level Overview')).toBeTruthy();
    expect(screen.getByText('Отчёт аудитору')).toBeTruthy();

    // Wait for async data load
    await waitFor(() => {
      // Radial gauge score and grade
      expect(screen.getByText('85')).toBeTruthy();
      expect(screen.getByText('из 100')).toBeTruthy();
      expect(screen.getByText('Grade B')).toBeTruthy();

      // Compliance bars
      expect(screen.getByText('ГОСТ Р 56939-2016 (Защита ПДн)')).toBeTruthy();
      expect(screen.getByText('Положение ЦБ 683-П')).toBeTruthy();
      expect(screen.getByText('Положение ЦБ 757-П')).toBeTruthy();

      // Findings
      expect(screen.getByText(/1 Critical/)).toBeTruthy();
      expect(screen.getByText(/4 High/)).toBeTruthy();

      // Automation
      expect(screen.getByText('Автоматизация гейтов: 68%')).toBeTruthy();
      expect(screen.getByText(/17 авто/)).toBeTruthy();

      // SLA
      expect(screen.getByText(/SLA: 93.2%/)).toBeTruthy();
    });
  });

  it('COS-107: SlaRemediationWidget — рендерит SLA-гейдж, карточки разбивки по критичности и список просроченных уязвимостей', async () => {
    render(
      <CosmoThemeProvider>
        <SlaRemediationWidget domain="all" />
      </CosmoThemeProvider>
    );

    // Header
    expect(screen.getByText('SLA устранения уязвимостей')).toBeTruthy();
    expect(screen.getByText('ЦБ РФ 683-П')).toBeTruthy();
    expect(screen.getByText('Нарушения SLA (Breached)')).toBeTruthy();

    await waitFor(() => {
      // Gauge
      expect(screen.getByText('76%')).toBeTruthy();
      expect(screen.getByText('SLA')).toBeTruthy();
      expect(screen.getByText('3 просроч.')).toBeTruthy();

      // Tier cards — Critical/High/Medium may appear in both cards and breach chips
      expect(screen.getAllByText('Critical').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('High').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Medium').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('норма ≤ 24 ч')).toBeTruthy();
      expect(screen.getByText('норма ≤ 7 дн')).toBeTruthy();
      expect(screen.getByText('норма ≤ 30 дн')).toBeTruthy();

      // Breach list
      expect(screen.getByText('SQL Injection in auth')).toBeTruthy();
      expect(screen.getByText('XSS in reports')).toBeTruthy();
      expect(screen.getByText('Missing CSP header')).toBeTruthy();

      // Overdue badges
      expect(screen.getByText('Просрочено на 12 ч')).toBeTruthy();
      expect(screen.getByText('Просрочено на 3 дн')).toBeTruthy();
      expect(screen.getByText('Просрочено на 15 дн')).toBeTruthy();
    });
  });

  it('COS-084: AlertHUD — рендерит колокольчик с бейджем, открывает шторку и показывает оповещения', async () => {
    render(
      <CosmoThemeProvider>
        <AlertHUD />
      </CosmoThemeProvider>
    );

    // Bell icon button exists
    const bellBtn = screen.getByLabelText('open notifications');
    expect(bellBtn).toBeTruthy();

    // Click to open drawer
    fireEvent.click(bellBtn);
    expect(screen.getByText('Центр уведомлений')).toBeTruthy();
    expect(screen.getByText('Все чисто — инцидентов нет')).toBeTruthy();
    expect(screen.getByText('Прочитано')).toBeTruthy();
    expect(screen.getByText('Очистить')).toBeTruthy();
  });
});
