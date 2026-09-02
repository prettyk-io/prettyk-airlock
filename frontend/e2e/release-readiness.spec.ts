/**
 * COS-098: Release Readiness surface — Browser Acceptance (Playwright).
 *
 * Live stack: vite :5175 + FastAPI :8100 + PG :5432 (stand).
 *
 * Покрывает acceptance карточки:
 *   - deep-link ?view=release-readiness открывает витрину (COS-084 sticky-ref
 *     deep-link механика);
 *   - данные рендерятся с бэкенда (REST: domains/releases/runs), а не из
 *     localStorage-прототипа;
 *   - SSE-подключение поднимается на живом бэкенде (LIVE-бейдж connected);
 *   - release, созданный через API, появляется в гриде после refresh
 *     (честный refetch, не выдуманный client-side объект).
 */
import { test, expect, type Page } from '@playwright/test';
import { operatorJwt } from './helpers/e2e_auth';

const OPS_AUTH = { Authorization: `Bearer ${operatorJwt()}` };
const OPS_HEADERS = { ...OPS_AUTH, 'Content-Type': 'application/json' };

async function setupAuth(page: Page): Promise<void> {
  await page.addInitScript((token) => {
    globalThis.localStorage?.setItem('cosmo_auth_token', token);
  }, operatorJwt());
}

const API = 'http://127.0.0.1:8100';

interface Domain { id: string }
interface Plan { id: string }
interface App { id: string }

async function apiGet(path: string): Promise<unknown[] | null> {
  const res = await fetch(`${API}${path}`, { headers: OPS_AUTH });
  if (!res.ok) return null;
  return (await res.json()) as unknown[];
}

async function getFirstDomain(): Promise<string | null> {
  const list = await apiGet('/api/v1/domains');
  return (list?.[0] as Domain | undefined)?.id ?? null;
}

/** Seed через production API: run по первому плану стенда → release.
 *  Идентификаторы УНИКАЛЬНЫ на прогон: id релиза глобально уникален (PK),
 *  на мультидоменном стенде повторный id давал бы тихий 409 в чужом домене. */
async function ensureRelease(releaseId: string, domainId: string): Promise<{ releaseId: string; runId: string }> {
  const runId = `${releaseId}-run`;
  // 1. план: первый на стенде (без плана релиз по контракту не собрать)
  let planId = (await apiGet('/api/v1/plans') as Plan[] | null)?.[0]?.id ?? null;
  if (!planId) {
    const appId = (await apiGet('/api/v1/apps') as App[] | null)?.[0]?.id;
    if (!appId) return { releaseId, runId }; // нечего честно засеять
    await fetch(`${API}/api/v1/plans`, {
      method: 'POST', headers: OPS_HEADERS,
      body: JSON.stringify({ id: `${releaseId}-plan`, app_id: appId, brick_ids: [] }),
    });
    planId = `${releaseId}-plan`;
  }

  // 2. прогон (run_ids релиза обязаны существовать и принадлежать плану)
  await fetch(`${API}/api/v1/runs`, {
    method: 'POST', headers: OPS_HEADERS,
    body: JSON.stringify({ id: runId, plan_id: planId, domain_id: domainId, trigger: 'manual' }),
  });

  // 3. релиз
  await fetch(`${API}/api/v1/releases`, {
    method: 'POST', headers: OPS_HEADERS,
    body: JSON.stringify({
      id: releaseId,
      domain_id: domainId,
      plan_id: planId,
      run_ids: [runId],
      trigger: 'manual',
      version: 'v9.9.9',
      changelog: 'COS-098 e2e fixture',
    }),
  });
  return { releaseId, runId };
}

test.beforeEach(async ({ page }) => {
  await setupAuth(page);
});

test('COS-098: deep-link открывает readiness-витрину, данные с бэкенда, SSE live', async ({ page }) => {
  await page.goto('/?surface=station&view=release-readiness');

  // Витрина отрендерилась (deep-link механика COS-084)
  const view = page.getByTestId('release-readiness-view');
  await expect(view).toBeVisible({ timeout: 20_000 });

  // Домены с реального бэкенда: селектор не пуст (либо честный empty).
  // Ожидание с ретраем — чтение текста селекта до резолва getDomains гонка.
  const domainSelect = page.getByTestId('domain-select');
  await expect(domainSelect).toBeVisible();
  const firstDomain = await getFirstDomain();
  if (firstDomain) {
    await expect(domainSelect).not.toContainText('нет доменов', { timeout: 15_000 });
  }

  // Гриды присутствуют (пустые данные — честные info-alerts, не пустой экран)
  await expect(page.getByTestId('releases-grid')).toBeVisible();
  await expect(page.getByTestId('runs-grid')).toBeVisible();

  // SSE-подключение к живому бэкенду: бейдж становится connected
  // ('LIVE', в backlog-режиме — 'LIVE (backlog replay)')
  await expect(page.getByTestId('live-badge')).toHaveText(/^LIVE/, { timeout: 30_000 });
});

test('COS-098: релиз, созданный через API, появляется в гриде после refresh', async ({ page }) => {
  const domainId = await getFirstDomain();
  test.skip(!domainId, 'на стенде нет доменов — honest empty проверяется отдельно');

  // Уникальный id на прогон: release.id глобально уникален (PK)
  const releaseId = `rel-e2e-cos098-${Date.now()}`;
  await ensureRelease(releaseId, domainId!);

  await page.goto('/?surface=station&view=release-readiness');
  await expect(page.getByTestId('release-readiness-view')).toBeVisible({ timeout: 20_000 });

  // Селект домена доехал до данных (по умолчанию — первый домен, он же seed-домен)
  await expect(page.getByTestId('domain-select')).not.toContainText('нет доменов', { timeout: 15_000 });

  // Честный refetch: кнопка Обновить тянет данные с бэкенда
  await page.getByTestId('refresh-btn').click();
  await expect(page.getByTestId('releases-grid').getByText(releaseId)).toBeVisible({
    timeout: 15_000,
  });
  // И seeded-прогон виден в живом гриде прогонов
  await expect(page.getByTestId('runs-grid').getByText(`${releaseId}-run`)).toBeVisible({
    timeout: 15_000,
  });
});
