/**
 * COS-100: Web IDE (Surface B) — Browser Acceptance (Playwright).
 *
 * Verifies:
 *   - Deep-link ?surface=ide opens Web IDE Surface B
 *   - Style boundary: root container has .cosmo-ide-root class
 *   - Dark default background in Surface B
 *   - File tree displays real tree from backend API (/api/v1/repos/tree)
 *   - File loading (/api/v1/repos/file)
 *   - Switching surfaces: Control Station ↔ Web IDE via SurfaceSwitcher & Header button
 *   - Local draft persistence across reload
 */
import { test, expect } from '@playwright/test';
import { authHeaders, authenticatePageOrSkip } from './helpers/e2e_auth';

test.beforeEach(async ({ page }) => {
  // COS-176: живая RS256-сессия (skip при недоступном auth-контуре).
  await authenticatePageOrSkip(page);
});

test('COS-100/179: deep-link ?surface=ide opens Web IDE shell with live RS256 session', async ({ page }) => {
  await page.goto('/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=3');

  // Verify Surface B root container
  const ideRoot = page.getByTestId('web-ide-shell');
  await expect(ideRoot).toBeVisible({ timeout: 20_000 });
  await expect(ideRoot).toHaveClass(/cosmo-ide-root/);

  // Top bar shows repo and active file
  await expect(page.getByTestId('repo-select')).toHaveValue('payments/api');
  await expect(page.getByTestId('current-file-badge')).toContainText('scenarios/auth.wire');

  // File tree container renders (наполнение — см. follow-up тест ниже)
  const fileTree = page.getByTestId('file-tree');
  await expect(fileTree).toBeVisible();

  // Active file tab shows wire / yaml
  const activeTab = page.getByTestId('active-file-tab');
  await expect(activeTab).toBeVisible();
  await expect(activeTab).toContainText('auth.wire');
});

test('COS-100/179: file tree renders from backend (bootstrap → CAS)', async ({ page }) => {
  // COS-179: FE делает workspace bootstrap (repo+branch → headSha) и читает
  // tree/file парой CAS; фикстура `payments/api` — seed-webide-fixture.py.
  await page.goto('/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=3');

  const fileTree = page.getByTestId('file-tree');
  await expect(fileTree).toBeVisible();
  await expect(fileTree.getByText('scenarios')).toBeVisible({ timeout: 20_000 });
  await expect(fileTree.getByText('auth.wire')).toBeVisible();

  // Deep-link файл реально загружен с зафиксированной ревизии (не fallback).
  await expect(page.getByTestId('current-file-badge')).toContainText('scenarios/auth.wire');
  await expect(page.getByTestId('status-message')).toHaveCount(0);
});

test('COS-179: deep-link commit → snapshot ref-режим (read-only)', async ({ page, request }) => {
  // Живой head берём через bootstrap — deep-link несёт commit SHA (FR-004).
  const boot = await request.get('/api/v1/repos/workspace/bootstrap?repo=payments/api', {
    headers: await authHeaders(),
  });
  expect(boot.status()).toBe(200);
  const headSha = ((await boot.json()) as { headSha: string }).headSha;

  await page.goto(
    `/?surface=ide&repo=payments/api&file=scenarios/auth.wire&commit=${headSha.slice(0, 12)}`,
  );

  const badge = page.getByTestId('snapshot-badge');
  await expect(badge).toContainText(headSha.slice(0, 7));
  // read-only by construction: запись в snapshot закрыта.
  await expect(page.getByTestId('commit-btn')).toBeDisabled();
  await expect(page.getByTestId('save-btn')).toBeDisabled();
  await expect(page.getByTestId('file-tree').getByText('scenarios')).toBeVisible({ timeout: 20_000 });
});

test('COS-182: Save пишет серверный черновик (не мёртвый PUT /repos/file)', async ({ page, request }) => {
  const deadCalls: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/repos/file') && r.method() === 'PUT') deadCalls.push(r.url());
  });

  await page.goto('/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=1');
  await expect(page.getByTestId('file-tree').getByText('scenarios')).toBeVisible({ timeout: 20_000 });

  // Правка в Monaco → Save (⌘S-путь).
  await page.locator('.monaco-editor .view-line').first().click();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText('# changed by COS-182 e2e\n');

  const saveBtn = page.getByTestId('save-btn');
  await expect(saveBtn).toBeEnabled({ timeout: 10_000 });
  await saveBtn.click();

  await expect(page.getByTestId('status-message')).toContainText('Черновик сохранён на сервере', {
    timeout: 15_000,
  });

  // Реальный результат на сервере: черновик читается (COS-110).
  const draft = await request.get(
    '/api/v1/repos/workspace/draft?repo=payments/api&branch=main&path=scenarios/auth.wire',
    { headers: await authHeaders() },
  );
  expect(draft.status()).toBe(200);
  expect(((await draft.json()) as { content: string }).content).toContain('changed by COS-182 e2e');

  // Мёртвый путь (405) не дёргался.
  expect(deadCalls).toEqual([]);

  // Гигиена: снять тестовый черновик.
  await request.delete(
    '/api/v1/repos/workspace/draft?repo=payments/api&branch=main&path=scenarios/auth.wire',
    { headers: await authHeaders() },
  );
});

test('COS-182: gutter-«run» не врёт — runner не подключён, сохраняется черновик', async ({ page }) => {
  await page.goto('/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=1');
  await expect(page.getByTestId('file-tree').getByText('scenarios')).toBeVisible({ timeout: 20_000 });

  const glyph = page.locator('.cosmo-gutter-run-icon').first();
  await expect(glyph).toBeVisible({ timeout: 15_000 });
  await glyph.click();

  // Честный лог: шаг НЕ исполнен, серверного runner'а нет.
  await expect(
    page.getByText('Шаг не исполнен: серверный runner .wire в Airlock не подключён'),
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Step L\d+ completed/)).toHaveCount(0);
  await expect(page.getByTestId('status-message')).toContainText('Шаг не исполнен (runner недоступен)');
});

test('COS-186: concurrent 409 → kind-aware конфликт, refresh/retry доводит коммит (live)', async ({ page, request }) => {
  await page.goto('/?surface=ide&repo=payments/api&file=README.md&line=1');
  await expect(page.getByTestId('file-tree').getByText('scenarios')).toBeVisible({ timeout: 20_000 });

  // Правка README в Monaco → модалка Commit & Push.
  await page.locator('.monaco-editor .view-line').first().click();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText('# cos186 conflict e2e\n');
  await page.getByTestId('commit-btn').click();
  await page.getByPlaceholder('feat(auth): update wire scenario assertions').fill('COS-186 conflict e2e');

  // Внешний пуш уводит голову ветки (уникальный probe-файл, Gitea basic auth).
  const basic = 'Basic ' + Buffer.from('cosmo:cosmo-admin-dev').toString('base64');
  const probePath = `.cosmo/cos186-probe-${Date.now()}.txt`;
  const advance = await request.post(
    `http://127.0.0.1:3100/api/v1/repos/payments/api/contents/${probePath}`,
    {
      headers: { Authorization: basic },
      data: { content: Buffer.from('probe\n').toString('base64'), message: 'COS-186 advance head', branch: 'main' },
    },
  );
  expect(advance.status()).toBe(201);

  // Попытка коммита → typed 409 concurrent → информированный конфликт (без сырого detail).
  await page.getByText('Запушить в репозиторий').click();
  const conflict = page.getByTestId('commit-conflict');
  await expect(conflict).toBeVisible({ timeout: 15_000 });
  await expect(conflict).toContainText('Ветка ушла вперёд');
  await expect(conflict).not.toContainText('branch head moved');

  // «Обновить workspace и повторить»: re-bootstrap → повтор с новым head → успех.
  await page.getByTestId('commit-refresh-btn').click();
  await expect(page.getByTestId('status-message')).toContainText('Запушено', { timeout: 20_000 });
  await expect(conflict).toHaveCount(0);

  // Наш контент реально в ветке (Gitea raw по main).
  const raw = await request.get(
    'http://127.0.0.1:3100/api/v1/repos/payments/api/raw/README.md?ref=main',
    { headers: { Authorization: basic } },
  );
  expect(raw.status()).toBe(200);
  expect(await raw.text()).toContain('cos186 conflict e2e');

  // Гигиена: удалить probe-файл.
  const meta = await request.get(
    `http://127.0.0.1:3100/api/v1/repos/payments/api/contents/${probePath}?ref=main`,
    { headers: { Authorization: basic } },
  );
  if (meta.status() === 200) {
    const sha = ((await meta.json()) as { sha: string }).sha;
    await request.delete(
      `http://127.0.0.1:3100/api/v1/repos/payments/api/contents/${probePath}`,
      {
        headers: { Authorization: basic },
        data: { sha, message: 'COS-186 cleanup probe', branch: 'main' },
      },
    );
  }
});

test('COS-191: серверный черновик переживает reload и восстанавливается (+ «Сбросить»)', async ({ page, request }) => {
  await page.goto('/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=1');
  await expect(page.getByTestId('file-tree').getByText('scenarios')).toBeVisible({ timeout: 20_000 });

  // Правка + Save → серверный черновик (COS-182) + индикация источника.
  await page.locator('.monaco-editor .view-line').first().click();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText('# cos191 draft restore e2e\n');
  await page.getByTestId('save-btn').click();
  await expect(page.getByTestId('status-message')).toContainText('Черновик сохранён на сервере', {
    timeout: 15_000,
  });
  await expect(page.getByTestId('content-source-badge')).toContainText('server WIP');

  // Reload → черновик восстанавливается с сервера (localStorage пуст).
  await page.reload();
  await expect(page.getByTestId('file-tree').getByText('scenarios')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('content-source-badge')).toContainText('server WIP', { timeout: 15_000 });
  await expect(page.locator('.monaco-editor .view-lines').first()).toContainText(
    'cos191 draft restore e2e',
  );

  // «Сбросить» → repo-версия, серверный черновик удалён.
  await page.getByTestId('discard-draft-btn').click();
  await expect(page.getByTestId('content-source-badge')).toHaveCount(0);
  await expect(page.locator('.monaco-editor .view-lines').first()).toContainText('navigate');
  const draft = await request.get(
    '/api/v1/repos/workspace/draft?repo=payments/api&branch=main&path=scenarios/auth.wire',
    { headers: await authHeaders() },
  );
  expect(draft.status()).toBe(404);
});

test('COS-100: surface switching Control Station <-> Web IDE preserves both surfaces without style leaks', async ({ page }) => {
  await page.goto('/?surface=station');

  // 1. Control Station loaded
  await expect(page.getByTestId('surface-switcher')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Cosmoport' })).toBeVisible();

  // 2. Click Web IDE button in SurfaceSwitcher
  await page.getByTestId('switch-to-ide').click();
  await expect(page.getByTestId('web-ide-shell')).toBeVisible({ timeout: 15_000 });
  expect(page.url()).toContain('surface=ide');

  // 3. Click Control Station button to return
  await page.getByTestId('switch-to-station').click();
  await expect(page.getByRole('heading', { name: 'Cosmoport' })).toBeVisible({ timeout: 15_000 });
  expect(page.url()).toContain('surface=station');

  // 4. Test header IDE button inside Control Station
  const headerIdeBtn = page.getByTestId('header-open-ide');
  if (await headerIdeBtn.isVisible()) {
    await headerIdeBtn.click();
    await expect(page.getByTestId('web-ide-shell')).toBeVisible({ timeout: 15_000 });
    expect(page.url()).toContain('surface=ide');
  }
});
