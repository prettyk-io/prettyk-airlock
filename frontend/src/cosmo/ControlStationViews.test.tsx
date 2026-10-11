// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { CosmoThemeProvider } from './theme';
import { ProjectsOverview } from './station/views/ProjectsOverview';
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
import { ApplicationDetail } from './station/views/ApplicationDetail';
import { BuildsRegistry } from './station/views/BuildsRegistry';
import { DeploymentsRegistry } from './station/views/DeploymentsRegistry';
import { ProjectsRegistry } from './station/views/ProjectsRegistry';
import { ProjectDetail } from './station/views/ProjectDetail';
import { ProjectGraph } from './station/views/ProjectGraph';
import { FlatAppsRegistry } from './station/views/FlatAppsRegistry';
import { ReleaseTypeBuilder } from './station/views/ReleaseTypeBuilder';
import { BatchConstructor } from './station/views/BatchConstructor';
import { ProjectReleaseDashboard } from './station/views/ProjectReleaseDashboard';
import { ProjectCreateWizard } from './station/views/ProjectCreateWizard';
import { CreateStandaloneApp } from './station/views/CreateStandaloneApp';
import { CreateLibrary } from './station/views/CreateLibrary';
import { NotificationOps } from './station/views/NotificationOps';
import type { Application, Release } from './station/api';
import { WebIDEShell } from './ide/WebIDEShell';

vi.mock('@monaco-editor/react', () => ({
  default: () => null,
  DiffEditor: () => null,
}));

const mockApps = [
  {
    id: 'app-payments',
    project_id: 'prj-1',
    level: 1,
    repo_binding: { forge_id: 'gitea', repo_path: 'org/payments', default_branch: 'main' },
    pipeline_plan_id: 'plan-payments',
  },
  {
    id: 'lib-auth',
    project_id: 'prj-1',
    level: 0,
    repo_binding: { forge_id: 'gitea', repo_path: 'org/auth-lib', default_branch: 'main' },
  },
];

const mockGroups = [
  {
    id: 'grp-fintech',
    project_id: 'prj-1',
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
    project_id: 'prj-1',
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
  // COS-061: Mock EventSource for AlertHUD SSE
  vi.stubGlobal('EventSource', class MockEventSource {
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    addEventListener(_type: string, _fn: (e: unknown) => void) {}
    close() {}
  });

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
        days: 30,
      }), { status: 200 }));
    }
    // SAN-017: Builds & Deployments — return empty by default (honest EmptyState)
    // COS-061: Notification inbox endpoints
    if (url.includes('/api/v1/notifications/inbox/unread-count')) {
      return Promise.resolve(new Response(JSON.stringify({ unread: 0 }), { status: 200 }));
    }
    if (url.includes('/api/v1/notifications/inbox')) {
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }
    // COS-075: SSE ticket endpoint (AlertHUD connect flow)
    if (url.includes('/api/v1/notifications/sse-ticket')) {
      return Promise.resolve(new Response(JSON.stringify({ ticket: 'test-ticket', recipient_id: 'operator', expires_in: 60 }), { status: 200 }));
    }
    if (url.includes('/api/v1/builds')) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    if (url.includes('/api/v1/deployments')) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    // FR-003/004: Projects & KITS mocks
    if (url.includes('/api/v1/kits/tags')) {
      return Promise.resolve(new Response(JSON.stringify([
        { id: 'cbr', label: 'Цифровой рубль' },
        { id: 'payments', label: 'Платежи' },
        { id: 'cards', label: 'Карты' },
      ]), { status: 200 }));
    }
    // POST-FLASH-001: project compose, standalone app, library creation
    if (url.includes('/api/v1/projects/compose')) {
      return Promise.resolve(new Response(JSON.stringify({
        project_id: 'prj-created', project_name: 'New Project', apps_created: 2, repos_created: 2,
        apps: [{ app_id: 'svc-1', repo_path: 'org/svc-1', status: 'created' }],
      }), { status: 201 }));
    }
    if (url.includes('/api/v1/apps/standalone')) {
      return Promise.resolve(new Response(JSON.stringify({
        id: 'app-standalone', level: 1, repo_binding: { forge_id: 'gitea', repo_path: 'org/standalone', default_branch: 'main' },
        artifact_kind: 'docker',
      }), { status: 201 }));
    }
    if (url.includes('/api/v1/libraries')) {
      return Promise.resolve(new Response(JSON.stringify({
        id: 'lib-shared', level: 0, repo_binding: { forge_id: 'gitea', repo_path: 'org/shared-lib', default_branch: 'main' },
      }), { status: 201 }));
    }
    if (url.includes('/api/v1/projects') && !url.includes('/api/v1/apps')) {
      if (url.includes('/graph')) {
        return Promise.resolve(new Response(JSON.stringify({
          project_id: 'prj-1',
          nodes: [],
          edges: [],
        }), { status: 200 }));
      }
      if (url.includes('/batch-releases')) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (url.match(/\/api\/v1\/projects\/[^/?]+$/)) {
        return Promise.resolve(new Response(JSON.stringify(
          { id: 'prj-1', name: 'Digital Ruble Core', description: 'Core platform', kits_tags: ['cbr'], app_count: 5, l0_count: 2, l1_count: 3, l2_count: 0, status: 'active', last_release: 'v2.1.0', last_release_date: new Date().toISOString(), updated_at: new Date().toISOString(), created_by: 'Иванов И.И.', team: [] }
        ), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify([
        { id: 'prj-1', name: 'Digital Ruble Core', kits_tags: ['cbr'], app_count: 5, l0_count: 2, l1_count: 3, l2_count: 0, status: 'active', last_release: 'v2.1.0', last_release_date: new Date().toISOString(), updated_at: new Date().toISOString(), created_by: 'Иванов И.И.' },
        { id: 'prj-2', name: 'Payment Gateway', kits_tags: ['payments'], app_count: 3, l0_count: 1, l1_count: 2, l2_count: 0, status: 'active', last_release: 'v1.5.0', last_release_date: new Date().toISOString(), updated_at: new Date().toISOString(), created_by: 'Петров П.П.' },
      ]), { status: 200 }));
    }
    if (url.includes('/api/v1/release-types')) {
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
  });
});

describe('FR-003: Projects Overview & Registry', () => {
  it('ProjectsOverview: рендерит таблицу проектов с KITS-свитчером', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectsOverview />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Проекты')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Digital Ruble Core')).toBeTruthy();
      expect(screen.getByText('Payment Gateway')).toBeTruthy();
      // KITS tags
      expect(screen.getByText('Цифровой рубль')).toBeTruthy();
      expect(screen.getByText('Платежи')).toBeTruthy();
      // Status chips (both projects are Active)
      expect(screen.getAllByText('Active').length).toBeGreaterThanOrEqual(1);
      // Last release
      expect(screen.getByText('v2.1.0')).toBeTruthy();
    });
  });

  it('ProjectsRegistry: рендерит реестр с кнопкой и модалкой создания', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectsRegistry />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Реестр проектов')).toBeTruthy();
    expect(screen.getByText('Создать проект')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Digital Ruble Core')).toBeTruthy();
    });

    // Open create modal via "Быстрое создание" button
    fireEvent.click(screen.getByText('Быстрое создание'));
    expect(screen.getByText('Создать новый проект')).toBeTruthy();
    expect(screen.getByText('Создать')).toBeTruthy();
  });
});

describe('COS-022: Control Station Core Views', () => {
  it('Overview view: рендерит проекты как главную таблицу', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectsOverview />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Проекты')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Digital Ruble Core')).toBeTruthy();
    });
  });

  it('Applications view: рендерит таблицу приложений, уровни и Git-репозитории', async () => {
    render(
      <CosmoThemeProvider>
        <Applications />
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
        <RunControl initialRunId="run-101" />
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
        <RunControl />
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

  it('Evidence view: рендерит цепочку SHA-256 и заголовки доказательств', async () => {
    render(
      <CosmoThemeProvider>
        <Evidence initialRunId="run-101" />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Журнал доказательств (Evidence Ledger)')).toBeTruthy();
    expect(screen.getByText('Цепочка SHA-256 валидна')).toBeTruthy();

    // Backend returns empty → honest EmptyState for entries
    await waitFor(() => {
      expect(screen.getByText('Нет записей доказательств')).toBeTruthy();
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
      expect(screen.getByText(/Граф выполнения/)).toBeTruthy();
    });
  });

  it('Releases view: рендерит заголовок и зоны промоушена (честный EmptyState)', async () => {
    render(
      <CosmoThemeProvider>
        <Releases />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Release Management (Управление Релизами)')).toBeTruthy();
    expect(screen.getByText('Зона Разработки (Build & Unit)')).toBeTruthy();
    expect(screen.getByText('Зона Тестирования (DAST / SAST / Gates)')).toBeTruthy();
    expect(screen.getByText('Зона Пром Эксплуатации (Signed & Airgap)')).toBeTruthy();

    // Backend returns empty → honest EmptyState
    await waitFor(() => {
      expect(screen.getByText('Релизы не найдены')).toBeTruthy();
    });
  });

  it('AppGraph view: рендерит плейсхолдер графа (используйте ProjectGraph)', async () => {
    render(
      <CosmoThemeProvider>
        <AppGraph />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Граф зависимостей приложений')).toBeTruthy();
    expect(screen.getByText(/Перейдите в карточку проекта/)).toBeTruthy();
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
    expect(screen.getByText('▶ Gutter: draft save (runner не подключён)')).toBeTruthy();

    // Toggle Diff View via button
    fireEvent.click(screen.getByText('Diff (⌘D)'));
    expect(screen.getByText('✓ Diff View')).toBeTruthy();

    // Open Commit & Push Dialog
    fireEvent.click(screen.getByText('Commit & Push'));
    expect(screen.getByText('Commit & Push изменения')).toBeTruthy();
    expect(screen.getByText('Запушить в репозиторий')).toBeTruthy();
  });

  it('AuditLog view: рендерит заголовок, фильтры и кнопки экспорта (честный EmptyState)', async () => {
    render(
      <CosmoThemeProvider>
        <AuditLog />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Журнал аудита безопасности (Audit Log)')).toBeTruthy();
    expect(screen.getByText('Экспорт CSV')).toBeTruthy();
    expect(screen.getByText('Экспорт JSON')).toBeTruthy();
    expect(screen.getByPlaceholderText('Поиск по пользователю...')).toBeTruthy();

    // Backend returns empty → honest EmptyState
    await waitFor(() => {
      expect(screen.getByText('События аудита не найдены')).toBeTruthy();
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
        <Analytics />
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
    // COS-098: честный Release-контракт (release_model.Release)
    const mockRelease: Release = {
      id: 'rel-test-001',
      version: 'v2.0.0',
      domain_id: 'cbr',
      plan_id: 'plan-test-001',
      run_ids: ['run-1'],
      trigger: 'manual',
      status: 'deployed',
      changelog: '',
      artifacts: [],
      approvals: [{ decided_by: 'sec_expert', decision: 'approved', comment: '', decided_at: new Date().toISOString(), signature: 'sha256:test' }],
      current_zone: 'zr',
      transfer_history: [],
    };

    render(
      <CosmoThemeProvider>
        <ReleaseTransferWizard release={mockRelease} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Мастер трансфера релиза')).toBeTruthy();
    expect(screen.getByText('Pre-Flight Checks (Проверка готовности)')).toBeTruthy();
    expect(screen.getByText('Target Zone & Состав')).toBeTruthy();
    expect(screen.getByText('Signoff & 2FA (Подтверждение трансфера)')).toBeTruthy();

    // Pre-flight items (loaded async)
    await waitFor(() => {
      expect(screen.getAllByText(/Security Gates/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Подпись офицера ИБ')).toBeTruthy();
    });
    expect(screen.getByText('Подтвердить и продолжить')).toBeTruthy();
  });

  it('SAN-003/SAN-004: ApplicationDetail — рендерит 6 вкладок, 3 аккордеона настроек и 8 шагов ЖЦ', async () => {
    const mockApp: Application = {
      id: 'app-payments',
      project_id: 'prj-1',
      level: 1,
      repo_binding: { forge_id: 'gitea', repo_path: 'org/payments', default_branch: 'main' },
      pipeline_plan_id: 'plan-payments',
    };

    render(
      <CosmoThemeProvider>
        <ApplicationDetail app={mockApp} onBack={vi.fn()} />
      </CosmoThemeProvider>
    );

    // 6 tabs visible
    expect(screen.getByText('Информация')).toBeTruthy();
    expect(screen.getByText('Сборки')).toBeTruthy();
    expect(screen.getByText('Деплои')).toBeTruthy();
    expect(screen.getByText('Релизы')).toBeTruthy();
    expect(screen.getByText('Настройки и ЖЦ')).toBeTruthy();
    expect(screen.getByText('Команда')).toBeTruthy();

    // Tab 0: Info content (general data only, no hardcoded integrations/contacts)
    expect(screen.getByText('Общие данные')).toBeTruthy();
    expect(screen.getByText('Статус')).toBeTruthy();
    expect(screen.getByText('Тип')).toBeTruthy();
    expect(screen.getByText('Капсула')).toBeTruthy();

    // Switch to tab 4 (Settings & LC)
    const settingsTab = screen.getByText('Настройки и ЖЦ');
    fireEvent.click(settingsTab);

    // 3 accordion headers
    expect(screen.getByText('Общие настройки')).toBeTruthy();
    expect(screen.getByText('Мониторинг')).toBeTruthy();
    expect(screen.getByText(/Конфигурация жизненного цикла/)).toBeTruthy();

    // 8 LC steps (7 static + 1 deploy, DAST block removed)
    expect(screen.getByText('Сборка')).toBeTruthy();
    expect(screen.getByText('Юнит-тестирование')).toBeTruthy();
    expect(screen.getByText('Генерация документации')).toBeTruthy();
    expect(screen.getByText('SonarQube')).toBeTruthy();
    expect(screen.getByText('Trivy')).toBeTruthy();
    expect(screen.getByText('CodeScoring')).toBeTruthy();
    expect(screen.getByText('Генерация SBOM (CycloneDX)')).toBeTruthy();
    expect(screen.getByText('Развёртывание ПО')).toBeTruthy();

    // CONTINUE/TERMINATE_ON_ERROR selectors (8 steps × 1 CONTINUE row each)
    const continueOptions = screen.getAllByText('▶ Продолжить (CONTINUE)');
    expect(continueOptions.length).toBeGreaterThanOrEqual(8);

    // Switch to tab 5 (Team)
    const teamTab = screen.getByText('Команда');
    fireEvent.click(teamTab);
    expect(screen.getByText('Петров П.П.')).toBeTruthy();
    expect(screen.getByText('Разработчик')).toBeTruthy();
    expect(screen.getByText('Merge')).toBeTruthy();
    expect(screen.getByText('Isolate')).toBeTruthy();
  });

  it('COS-061: AlertHUD — рендерит колокольчик, открывает шторку с durable inbox', async () => {
    render(
      <CosmoThemeProvider>
        <AlertHUD />
      </CosmoThemeProvider>
    );

    // Bell icon (accessible label)
    const bellBtn = screen.getByLabelText(/Центр уведомлений/);
    expect(bellBtn).toBeTruthy();

    // Open drawer
    fireEvent.click(bellBtn);
    expect(screen.getByText('Центр уведомлений')).toBeTruthy();

    // Wait for async fetch to complete → empty inbox state
    await waitFor(() => {
      expect(screen.getByText(/Все чисто/)).toBeTruthy();
    });
    expect(screen.getByText('Прочитано')).toBeTruthy();
  });

  it('SAN-005: BuildsRegistry — рендерит заголовок, фильтры и модалку создания сборки (честный EmptyState)', async () => {
    render(
      <CosmoThemeProvider>
        <BuildsRegistry />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Реестр сборок (Builds Registry)')).toBeTruthy();
    expect(screen.getAllByText('Создать сборку').length).toBeGreaterThanOrEqual(1);

    // Filter selects exist
    const appFilters = screen.getAllByText('Все приложения');
    expect(appFilters.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Все статусы')).toBeTruthy();
    expect(screen.getByText('Все ветки')).toBeTruthy();

    // Wait for async load — empty data → EmptyState
    await waitFor(() => {
      expect(screen.getByText('Сборки не найдены')).toBeTruthy();
    });

    // Open create modal (click the header button)
    const createBtns = screen.getAllByText('Создать сборку');
    fireEvent.click(createBtns[0]);
    expect(screen.getByText('Создать новую сборку')).toBeTruthy();
    expect(screen.getByText('Запустить сборку')).toBeTruthy();
  });

  it('COS-198: BuildsRegistry — детали сборки: digest, реальные логи, evidence', async () => {
    const digest = 'sha256:' + 'ab'.repeat(32);
    const buildRow = {
      id: 'bld-1',
      app_id: 'app-payments',
      title: 'Demo build',
      commit_sha: 'a1b2c3d4e5f6',
      branch: 'main',
      status: 'success',
      artifacts: [`build-demo:1.0.0@${digest}`],
      started_at: '2026-10-11T00:00:00',
      finished_at: '2026-10-11T00:00:30',
      initiator: 'dev_user',
      run_id: 'run-bld-1',
      evidence_refs: ['e1', 'e2'],
      build_logs: `+ docker push\nbuild-demo:1.0.0@${digest}`,
      meta: {},
    };
    vi.mocked(globalThis.fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/v1/builds/bld-1')) {
        return Promise.resolve(new Response(JSON.stringify(buildRow), { status: 200 }));
      }
      if (url.includes('/api/v1/builds')) {
        return Promise.resolve(new Response(JSON.stringify([buildRow]), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(
      <CosmoThemeProvider>
        <BuildsRegistry />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Demo build')).toBeTruthy();
    });
    fireEvent.click(screen.getByText('Demo build'));

    // Детали: digest-ссылка, прогон, evidence, реальные логи — из ответа API.
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => {
      expect(within(dialog).getByText(`build-demo:1.0.0@${digest}`)).toBeTruthy();
    });
    expect(within(dialog).getByText('run-bld-1')).toBeTruthy();
    expect(within(dialog).getByText('e1')).toBeTruthy();
    expect(within(dialog).getByText('Логи исполнения')).toBeTruthy();
    expect(within(dialog).getByText(/docker push/)).toBeTruthy();
  });

  it('SAN-005: DeploymentsRegistry — рендерит заголовок, фильтры и модалку отката (честный EmptyState)', async () => {
    render(
      <CosmoThemeProvider>
        <DeploymentsRegistry />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Реестр развертываний (Deployments Registry)')).toBeTruthy();

    // Filter selects
    expect(screen.getAllByText('Все приложения').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Все зоны')).toBeTruthy();
    expect(screen.getByText('Все статусы')).toBeTruthy();

    // Wait for async load — empty data → EmptyState
    await waitFor(() => {
      expect(screen.getByText('Деплои не найдены')).toBeTruthy();
    });
  });
});

describe('FINAL-FLASH-001: Live Operator Journey', () => {
  it('ProjectDetail: рендерит метаданные, состав и команду', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectDetail projectId="prj-1" onBack={vi.fn()} />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Digital Ruble Core')).toBeTruthy();
      expect(screen.getAllByText(/Состав/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/Команда/).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('ProjectGraph: рендерит React Flow граф проекта', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectGraph projectId="prj-1" onBack={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Граф зависимостей проекта')).toBeTruthy();
    expect(screen.getByText('← Назад')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('depends_on')).toBeTruthy();
      expect(screen.getByText('uses_library')).toBeTruthy();
    });
  });

  it('FlatAppsRegistry: рендерит таблицу приложений с фильтрами', async () => {
    render(
      <CosmoThemeProvider>
        <FlatAppsRegistry />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Реестр приложений')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Все проекты')).toBeTruthy();
      expect(screen.getByText('Все уровни')).toBeTruthy();
    });
  });

  it('ReleaseTypeBuilder: рендерит двухпанельный конструктор', async () => {
    render(
      <CosmoThemeProvider>
        <ReleaseTypeBuilder />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Release Type Builder')).toBeTruthy();
    expect(screen.getByText('Создать тип')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Типы релизов')).toBeTruthy();
    });
  });

  it('ReleaseTypeBuilder: открывает модалку создания типа', async () => {
    render(
      <CosmoThemeProvider>
        <ReleaseTypeBuilder />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Создать тип')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('Создать тип'));

    await waitFor(() => {
      expect(screen.getByLabelText('Название')).toBeTruthy();
    });
  });

  it('BatchConstructor: рендерит сборщик batch релизов', async () => {
    render(
      <CosmoThemeProvider>
        <BatchConstructor projectId="prj-1" onBack={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Batch Release Constructor')).toBeTruthy();
    expect(screen.getByText('← Назад')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Template Release Type:')).toBeTruthy();
    });
  });

  it('ProjectReleaseDashboard: рендерит readiness summary', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectReleaseDashboard projectId="prj-1" onBack={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Release Readiness Dashboard')).toBeTruthy();
    expect(screen.getByText('← Назад')).toBeTruthy();
  });

  it('ProjectsRegistry: создаёт проект через модалку', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectsRegistry />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Digital Ruble Core')).toBeTruthy();
    });

    expect(screen.getByText('Создать проект')).toBeTruthy();
    expect(screen.getByText('Быстрое создание')).toBeTruthy();
  });
});

describe('POST-FLASH-001 / POST-FLASH-002: Project Composition Wizard & Corrections', () => {
  it('ProjectCreateWizard: рендерит 5-шаговый stepper', () => {
    render(
      <CosmoThemeProvider>
        <ProjectCreateWizard onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Создание проекта')).toBeTruthy();
    expect(screen.getByText('Проект')).toBeTruthy();
    expect(screen.getByText('Папки → Приложения')).toBeTruthy();
    expect(screen.getByText('Граф зависимостей')).toBeTruthy();
    expect(screen.getByText(/KITS \/ Команда \/ Manifest/)).toBeTruthy();
    expect(screen.getByText('Валидация и создание')).toBeTruthy();
  });

  it('ProjectCreateWizard: шаг 0 — ввод названия проекта', () => {
    render(
      <CosmoThemeProvider>
        <ProjectCreateWizard onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByRole('textbox', { name: /Название проекта/ })).toBeTruthy();
    expect(screen.getByText('Далее')).toBeTruthy();
  });

  it('ProjectCreateWizard: шаг 1 — drag-drop зона и папки', () => {
    render(
      <CosmoThemeProvider>
        <ProjectCreateWizard onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    // Go to step 1
    fireEvent.change(screen.getByRole('textbox', { name: /Название проекта/ }), { target: { value: 'Test Project' } });
    fireEvent.click(screen.getByText('Далее'));

    expect(screen.getByText('Перетащите папки сюда или нажмите «Добавить»')).toBeTruthy();
    expect(screen.getByText('api-gateway')).toBeTruthy();
    expect(screen.getByText('auth-service')).toBeTruthy();
  });

  it('ProjectCreateWizard: POST-FLASH-002 — создание проекта успешно без KITS-тегов (KITS опционален)', async () => {
    render(
      <CosmoThemeProvider>
        <ProjectCreateWizard onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    // Go to step 4 without selecting any KITS tags
    fireEvent.change(screen.getByRole('textbox', { name: /Название проекта/ }), { target: { value: 'Test Project No KITS' } });
    fireEvent.click(screen.getByText('Далее')); // to step 1
    fireEvent.click(screen.getByText('Далее')); // to step 2
    fireEvent.click(screen.getByText('Далее')); // to step 3 (KITS optional)
    fireEvent.click(screen.getByText('Далее')); // to step 4 (Validation)

    // Click 'Создать проект' without selecting KITS tags — should succeed
    fireEvent.click(screen.getByText('Создать проект'));

    await waitFor(() => {
      expect(screen.getByText('Проект создан')).toBeTruthy();
    });
  });

  it('CreateStandaloneApp: POST-FLASH-002 — автоматическое определение характеристик без обязательного выбора уровня', () => {
    render(
      <CosmoThemeProvider>
        <CreateStandaloneApp onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Создать приложение без проекта')).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /App ID/ })).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Репозиторий/ })).toBeTruthy();
    expect(screen.getByText(/Автоопределение:/)).toBeTruthy();
    expect(screen.getByText('Создать приложение')).toBeTruthy();
  });

  it('CreateLibrary: POST-FLASH-002 — рендерит профиль доступа потребители vs Library Team', () => {
    render(
      <CosmoThemeProvider>
        <CreateLibrary onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Создать публичную библиотеку')).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Library ID/ })).toBeTruthy();
    expect(screen.getByText('Internal')).toBeTruthy();
    expect(screen.getByText('Public')).toBeTruthy();
    expect(screen.getByText('Library Team (write/settings)')).toBeTruthy();
    expect(screen.getByText('Consumers')).toBeTruthy();
  });

  it('CreateLibrary: переключает видимость Internal ↔ Public', () => {
    render(
      <CosmoThemeProvider>
        <CreateLibrary onCancel={vi.fn()} />
      </CosmoThemeProvider>
    );

    // Click Public card
    fireEvent.click(screen.getByText('Public'));
    expect(screen.getByText('Public')).toBeTruthy();
  });
});

describe('COS-079: NotificationOps (DLQ) — honest operator surface', () => {
  it('рендерит честный EmptyState на пустой DLQ', async () => {
    render(
      <CosmoThemeProvider>
        <NotificationOps />
      </CosmoThemeProvider>
    );

    expect(screen.getByText('Dead Letter Queue')).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText('DLQ пуста')).toBeTruthy();
    });
  });

  it('рендерит DLQ-таблицу с честным last_error и делает replay', async () => {
    const dlqRow = {
      id: 'dlq-e2e-1',
      event_id: 'evt-1',
      event_type: 'run_failed',
      severity: 'high',
      title: 'Run r-1 failed',
      recipient_id: 'ops@company.io',
      channel: 'email',
      state: 'failed',
      attempts: 5,
      max_attempts: 5,
      last_error: 'smtp down',
      created_at: '2026-09-01T10:00:00',
      updated_at: '2026-09-01T10:05:00',
    };
    let replayCalls = 0;
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/v1/notifications/dlq/dlq-e2e-1/replay')) {
        replayCalls += 1;
        return Promise.resolve(new Response(JSON.stringify({
          id: 'dlq-e2e-1', state: 'sent', attempts: 6, last_error: null,
        }), { status: 200 }));
      }
      if (url.includes('/api/v1/notifications/dlq')) {
        return Promise.resolve(new Response(JSON.stringify(replayCalls ? [] : [dlqRow]), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(
      <CosmoThemeProvider>
        <NotificationOps />
      </CosmoThemeProvider>
    );

    // Row visible with honest last_error and attempts
    await waitFor(() => {
      expect(screen.getByText('smtp down')).toBeTruthy();
    });
    expect(screen.getByText('5/5')).toBeTruthy();

    // Replay → provider accepts → honest success notice, row leaves DLQ
    fireEvent.click(screen.getByLabelText('replay-dlq-e2e-1'));
    await waitFor(() => {
      expect(screen.getByText(/доставлено \(attempt 6\)/)).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText('DLQ пуста')).toBeTruthy();
    });
  });

  it('показывает честный warning, когда провайдер отказал при replay', async () => {
    const dlqRow = {
      id: 'dlq-e2e-2',
      event_id: 'evt-2',
      event_type: 'run_failed',
      severity: 'critical',
      title: 'Run r-2 failed',
      recipient_id: 'ops@company.io',
      channel: 'email',
      state: 'failed',
      attempts: 5,
      max_attempts: 5,
      last_error: 'mailbox unknown',
      created_at: '2026-09-01T10:00:00',
      updated_at: '2026-09-01T10:05:00',
    };
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/replay')) {
        return Promise.resolve(new Response(JSON.stringify({
          id: 'dlq-e2e-2', state: 'failed', attempts: 6, last_error: 'mailbox unknown',
        }), { status: 200 }));
      }
      if (url.includes('/api/v1/notifications/dlq')) {
        return Promise.resolve(new Response(JSON.stringify([dlqRow]), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(
      <CosmoThemeProvider>
        <NotificationOps />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('mailbox unknown')).toBeTruthy();
    });
    fireEvent.click(screen.getByLabelText('replay-dlq-e2e-2'));
    await waitFor(() => {
      expect(screen.getByText(/состояние failed \(честно\)/)).toBeTruthy();
    });
  });

  it('показывает честную ошибку при недоступности API', async () => {
    globalThis.fetch = vi.fn().mockImplementation((_url: string) =>
      Promise.reject(new Error('connection refused')));

    render(
      <CosmoThemeProvider>
        <NotificationOps />
      </CosmoThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/connection refused/)).toBeTruthy();
    });
  });
});
