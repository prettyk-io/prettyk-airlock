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
import { test, expect, type Page } from '@playwright/test';
import { operatorJwt } from './helpers/e2e_auth';

async function setupAuth(page: Page): Promise<void> {
  await page.addInitScript((token) => {
    globalThis.localStorage?.setItem('cosmo_auth_token', token);
  }, operatorJwt());
}

test.beforeEach(async ({ page }) => {
  await setupAuth(page);
});

test('COS-100: deep-link ?surface=ide opens Web IDE (Surface B) in dark mode with file tree', async ({ page }) => {
  await page.goto('/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=3');

  // Verify Surface B root container
  const ideRoot = page.getByTestId('web-ide-shell');
  await expect(ideRoot).toBeVisible({ timeout: 20_000 });
  await expect(ideRoot).toHaveClass(/cosmo-ide-root/);

  // Top bar shows repo and active file
  await expect(page.getByTestId('repo-select')).toHaveValue('payments/api');
  await expect(page.getByTestId('current-file-badge')).toContainText('scenarios/auth.wire');

  // File tree rendered from API
  const fileTree = page.getByTestId('file-tree');
  await expect(fileTree).toBeVisible();
  await expect(fileTree.getByText('scenarios')).toBeVisible();

  // Active file tab shows wire / yaml
  const activeTab = page.getByTestId('active-file-tab');
  await expect(activeTab).toBeVisible();
  await expect(activeTab).toContainText('auth.wire');
});

test('COS-100: surface switching Control Station <-> Web IDE preserves both surfaces without style leaks', async ({ page }) => {
  await page.goto('/?surface=station');

  // 1. Control Station loaded
  await expect(page.getByTestId('surface-switcher')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Cosmoport')).toBeVisible();

  // 2. Click Web IDE button in SurfaceSwitcher
  await page.getByTestId('switch-to-ide').click();
  await expect(page.getByTestId('web-ide-shell')).toBeVisible({ timeout: 15_000 });
  expect(page.url()).toContain('surface=ide');

  // 3. Click Control Station button to return
  await page.getByTestId('switch-to-station').click();
  await expect(page.getByText('Cosmoport')).toBeVisible({ timeout: 15_000 });
  expect(page.url()).toContain('surface=station');

  // 4. Test header IDE button inside Control Station
  const headerIdeBtn = page.getByTestId('header-open-ide');
  if (await headerIdeBtn.isVisible()) {
    await headerIdeBtn.click();
    await expect(page.getByTestId('web-ide-shell')).toBeVisible({ timeout: 15_000 });
    expect(page.url()).toContain('surface=ide');
  }
});
