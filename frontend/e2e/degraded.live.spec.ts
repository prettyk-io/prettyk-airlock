/**
 * Notification Delivery Hardening: LIVE degraded test (docker stop/start PG).
 *
 * Запуск (останавливает cosmo-postgres на время теста!):
 *   COSMO_E2E_DEGRADED=1 npx playwright test e2e/degraded.live.spec.ts
 *
 * Без флага — skip. Сценарий:
 *   1. Живой стенд → Live (SSE).
 *   2. docker stop cosmo-postgres → UI показывает Degraded (notification_degraded).
 *   3. docker start cosmo-postgres → SSE recovery → Live (SSE) без reload.
 *   4. Событие после recovery доставлено ровно 1 раз (без дублей).
 */
import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..');
const HELPER = path.join(__dirname, 'helpers', 'cosmo_notify_helper.py');
const PY_ENV = { ...process.env, PYTHONPATH: REPO_ROOT };
const PG_CONTAINER = process.env.COSMO_PG_CONTAINER ?? 'cosmo-postgres';

const DEGRADED_ENABLED = process.env.COSMO_E2E_DEGRADED === '1';

function helper(args: string): string {
  return execSync(`python "${HELPER}" ${args}`, {
    cwd: REPO_ROOT,
    env: PY_ENV,
    encoding: 'utf-8',
    timeout: 30_000,
  }).trim();
}

function docker(args: string, timeoutMs = 60_000): string {
  return execSync(`docker ${args}`, { encoding: 'utf-8', timeout: timeoutMs }).trim();
}

function sleepMs(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function stopPostgres(): void {
  docker(`stop ${PG_CONTAINER}`, 90_000);
}

function startPostgres(): void {
  docker(`start ${PG_CONTAINER}`);
  // Ждать готовности PG (макс ~45s)
  for (let i = 0; i < 15; i += 1) {
    try {
      docker(`exec ${PG_CONTAINER} pg_isready -U cosmo -d cosmo`, 10_000);
      return;
    } catch {
      sleepMs(3_000);
    }
  }
  throw new Error(`${PG_CONTAINER} did not become ready after start`);
}

async function openDrawer(page: Page): Promise<void> {
  await page.getByTestId('notification-bell').click();
  await expect(page.getByTestId('notification-drawer')).toBeVisible();
}

test.skip(!DEGRADED_ENABLED, 'Set COSMO_E2E_DEGRADED=1 to run the live degraded test');

test.describe('COS-064+: live degraded SSE (PG docker stop/start)', () => {
  let pgStoppedByTest = false;

  test.beforeEach(() => {
    helper('clean');
  });

  test.afterEach(() => {
    // КРИТИЧНО: вернуть PG в любом случае (упавший тест не должен валить стенд)
    if (pgStoppedByTest) {
      try {
        const running = docker(`inspect -f '{{.State.Running}}' ${PG_CONTAINER}`);
        if (running !== 'true') startPostgres();
      } catch {
        startPostgres();
      }
      pgStoppedByTest = false;
    }
    helper('clean');
  });

  test('degraded state visible after PG stop; recovery without duplicates', async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto('/');
    await openDrawer(page);

    // 1. Живой стенд → Live (SSE)
    await expect(page.getByTestId('notification-sse-status')).toContainText('Live (SSE)', {
      timeout: 20_000,
    });

    // 2. Остановить PG → стрим шлёт notification_degraded → UI: Degraded
    stopPostgres();
    pgStoppedByTest = true;
    await expect(page.getByTestId('notification-sse-status')).toContainText(
      'Degraded (backend недоступен)',
      { timeout: 45_000 },
    );

    // 3. Вернуть PG → recovery-ветка стрима шлёт notification_initial → Live
    startPostgres();
    await expect(page.getByTestId('notification-sse-status')).toContainText('Live (SSE)', {
      timeout: 45_000,
    });

    // 4. Событие после recovery — доставлено ровно один раз
    helper(
      'publish --type run_failed --aggregate run/run-degraded-1 ' +
        '--title "After PG recovery" --message "single delivery" ' +
        '--event-id evt-e2e-degraded-recovery',
    );

    const cards = page.getByTestId('notification-card').filter({ hasText: 'After PG recovery' });
    await expect(cards).toHaveCount(1, { timeout: 20_000 });

    // Стабильность: пауза → дублей не появилось
    await page.waitForTimeout(5_000);
    await expect(cards).toHaveCount(1);
    await expect(page.getByTestId('notification-card')).toHaveCount(1);
    await expect(page.getByTestId('notification-badge')).toHaveText('1');
  });
});
