/**
 * COS-158: FE login surface — browser acceptance (Playwright).
 *
 * Live stack: vite :5175 + FastAPI :8100 + PG :5432 + OpenBao :8200.
 * Идёт через боевой login-путь (POST /api/v1/auth/login) с OpenBao-seeded
 * admin'ом (COS-175). Никакого dev-stub minting токенов.
 */
import { test, expect } from '@playwright/test';

const EMAIL = process.env.E2E_COSMO_EMAIL ?? 'admin@cosmoport.local';
const PASSWORD = process.env.E2E_COSMO_PASSWORD ?? 'cosmo-admin-dev';

test.describe('COS-158: login surface', () => {
  test('no session token → login view', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('login-view')).toBeVisible();
    await expect(page.getByTestId('login-submit')).toBeVisible();
  });

  test('empty fields → client-side honest error, no request', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('login-submit').click();
    await expect(page.getByTestId('login-error')).toContainText('Введите email и пароль');
  });

  test('wrong password → honest 401, stays on login', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Email').fill(EMAIL);
    await page.getByLabel('Пароль').fill('definitely-wrong-password');
    await page.getByTestId('login-submit').click();
    await expect(page.getByTestId('login-error')).toContainText('Неверный email или пароль');
    await expect(page.getByTestId('login-view')).toBeVisible();
  });

  test('correct credentials → session → Control Station → logout', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Email').fill(EMAIL);
    await page.getByLabel('Пароль').fill(PASSWORD);
    await page.getByTestId('login-submit').click();

    // App gate флипает на Control Station через useSession()
    await expect(page.getByTestId('header-user')).toContainText(EMAIL);

    // Реальный RS256 JWT из issuer лежит в localStorage (боевой контракт)
    const token = await page.evaluate(() =>
      globalThis.localStorage?.getItem('cosmo_auth_token'),
    );
    expect(token).toBeTruthy();

    // Logout возвращает на login и вычищает сессию
    await page.getByLabel('logout').click();
    await expect(page.getByTestId('login-view')).toBeVisible();
    const stale = await page.evaluate(() =>
      globalThis.localStorage?.getItem('cosmo_auth_token'),
    );
    expect(stale).toBeNull();
  });
});