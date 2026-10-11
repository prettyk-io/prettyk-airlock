/**
 * COS-064: Notification Surface — Browser Acceptance (Playwright).
 *
 * Live stack: vite :5175 + FastAPI :8100 + PG :5432 (stand).
 * Fixtures через production-путь: cosmo_notify_helper.py (record_event → POST /process).
 *
 * COS-075: recipient резолвится на бэкенде из principal (bearer → user_id);
 * SSE-стрим открывается по short-TTL ticket'у (без bearer в URL).
 * V1 recipient contract: 'operator' (bearer principal + explicit_recipients).
 */
import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import {
  authHeaders,
  authenticatePageOrSkip,
  e2eRecipient,
  fetchSession,
  tamperSignature,
  viewerCredentials,
} from './helpers/e2e_auth';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..');
const HELPER = path.join(__dirname, 'helpers', 'cosmo_notify_helper.py');
const PY_ENV = { ...process.env, PYTHONPATH: REPO_ROOT };

/**
 * COS-176: реальный RS256-сеанс (login → issuer token). Раньше здесь был
 * локальный unsigned mint — COS-156 его отвергает. OPS_AUTH заполняется в
 * beforeEach живым токеном; RECIPIENT — principal.user_id (sub) того же токена,
 * потому что inbox/SSE резолвят получателя из principal на бэкенде.
 */
let OPS_AUTH: Record<string, string> = {};
let RECIPIENT = 'admin';

let eventCounter = 0;

function helper(args: string): string {
  return execSync(`python "${HELPER}" ${args}`, {
    cwd: REPO_ROOT,
    env: PY_ENV,
    encoding: 'utf-8',
    timeout: 30_000,
  }).trim();
}

/** Publish a unique notification through the production outbox path. */
function publish(opts: {
  type?: string;
  title?: string;
  message?: string;
  severity?: string;
  eventId?: string;
  /** COS-187: recipient события (default — principal живого admin-токена). */
  recipient?: string;
}): string {
  eventCounter += 1;
  const eventId = opts.eventId ?? `evt-e2e-${Date.now()}-${eventCounter}`;
  helper(
    `publish --type ${opts.type ?? 'run_failed'} --aggregate run/run-e2e-${eventCounter}` +
      ` --recipient ${opts.recipient ?? RECIPIENT}` +
      ` --title "${opts.title ?? `E2E notification ${eventCounter}`}"` +
      ` --message "${opts.message ?? 'browser acceptance payload'}"` +
      ` --event-id ${eventId}` +
      (opts.severity ? ` --severity ${opts.severity}` : ''),
  );
  return eventId;
}

function cleanInbox(): void {
  helper('clean');
}

function unreadInDb(): number {
  return JSON.parse(helper(`unread --recipient ${RECIPIENT}`)).unread as number;
}

async function openDrawer(page: Page): Promise<void> {
  await page.getByTestId('notification-bell').click();
  await expect(page.getByTestId('notification-drawer')).toBeVisible();
}

/** Клик по карточке с ожиданием фактического read-эффекта (1 retry).
 * POST /read идемпотентен; SSE-ререндеры могут съесть первый клик. */
async function clickCardUntilRead(page: Page, card: ReturnType<Page['getByTestId']>): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await card.click();
    try {
      await expect(card).toHaveAttribute('data-read', 'true', { timeout: 5_000 });
      return;
    } catch {
      if (attempt === 1) throw new Error('card did not become read after click retry');
    }
  }
}

async function waitSSEConnected(page: Page): Promise<void> {
  await openDrawer(page);
  await expect(page.getByTestId('notification-sse-status')).toContainText('Live (SSE)', {
    timeout: 20_000,
  });
}

test.beforeEach(async ({ page }) => {
  // COS-176: живая RS256-сессия до любой навигации (skip при недоступном контуре).
  await authenticatePageOrSkip(page);
  OPS_AUTH = await authHeaders();
  RECIPIENT = await e2eRecipient();
  cleanInbox();
});

test.afterAll(() => {
  cleanInbox();
});

// ── AC1: inbox load → unread badge → live notification → mark read ──

test('COS-064: initial inbox load shows unread badge and cards from backend', async ({ page }) => {
  publish({ title: 'Pre-existing unread #1', severity: 'high' });
  publish({ title: 'Pre-existing unread #2', severity: 'info' });

  await page.goto('/');

  const bell = page.getByTestId('notification-bell');
  await expect(bell).toHaveAttribute('aria-label', /2 непрочитанных/);
  await expect(page.getByTestId('notification-badge')).toHaveText('2');

  await openDrawer(page);
  await expect(page.getByTestId('notification-card')).toHaveCount(2);
  await expect(page.getByTestId('notification-card').first()).toContainText('Pre-existing unread #2');
});

test('COS-064: notification arrives via SSE without reload', async ({ page }) => {
  await page.goto('/');
  await waitSSEConnected(page);

  await publish({ title: 'Live SSE notification', severity: 'critical' });

  const cards = page.getByTestId('notification-card');
  await expect(cards.filter({ hasText: 'Live SSE notification' })).toHaveCount(1, {
    timeout: 15_000,
  });

  // Badge updated by notification_unread_count event
  await expect(page.getByTestId('notification-badge')).toHaveText('1');
  await expect(page.getByTestId('notification-sse-status')).toContainText('Live (SSE)');
});

test('COS-064: mark one read → badge updates + backend verification', async ({ page }) => {
  publish({ title: 'To be read', severity: 'medium' });
  publish({ title: 'Stays unread', severity: 'low' });

  await page.goto('/');
  await expect(page.getByTestId('notification-badge')).toHaveText('2');

  await openDrawer(page);
  const target = page.getByTestId('notification-card').filter({ hasText: 'To be read' });
  await expect(target).toHaveCount(1);
  await expect(target).toHaveAttribute('data-read', 'false');

  await clickCardUntilRead(page, target);

  await expect(page.getByTestId('notification-badge')).toHaveText('1');
  expect(unreadInDb()).toBe(1);
});

test('COS-064: mark all read → badge 0 + backend verification', async ({ page }) => {
  publish({ title: 'Bulk read #1' });
  publish({ title: 'Bulk read #2' });

  await page.goto('/');
  await expect(page.getByTestId('notification-badge')).toHaveText('2');

  await openDrawer(page);
  const markAll = page.getByTestId('notification-mark-all');
  await expect(markAll).toBeEnabled();
  await markAll.click();

  // MUI Badge-root span stays mounted; emptiness shows via aria-label + disabled controls
  await expect(page.getByTestId('notification-bell')).toHaveAttribute(
    'aria-label',
    'Центр уведомлений — нет непрочитанных',
  );
  await expect(page.getByTestId('notification-badge').locator('.MuiBadge-badge')).toBeHidden();
  await expect(page.getByTestId('notification-mark-all-header')).toBeDisabled();
  await expect(page.getByTestId('notification-sse-status')).toBeVisible();
  expect(unreadInDb()).toBe(0);
});

// ── AC2: SSE reconnect без дублей ──

test('COS-064: SSE reconnect delivers pending notification without duplicates', async ({ page }) => {
  await page.goto('/');

  // Block SSE from the very start → EventSource retries until unblocked
  let sseBlocked = true;
  await page.route('**/api/v1/notifications/stream*', (route) => {
    if (sseBlocked) void route.abort();
    else void route.continue();
  });

  await page.goto('/');
  await openDrawer(page);
  await expect(page.getByTestId('notification-sse-status')).toContainText(
    /Disconnected|Подключение/,
    { timeout: 20_000 },
  );

  // Notification published while SSE is down → sits in durable inbox
  publish({ title: 'Published while offline', severity: 'high' });

  // Unblock → EventSource auto-reconnect → initial + pending rows delivered
  sseBlocked = false;
  await expect(page.getByTestId('notification-sse-status')).toContainText('Live (SSE)', {
    timeout: 30_000,
  });

  // Delivered exactly once after reconnect
  await expect(
    page.getByTestId('notification-card').filter({ hasText: 'Published while offline' }),
  ).toHaveCount(1, { timeout: 15_000 });

  // Reconnect delivered initial unread_count → badge honest
  await expect(page.getByTestId('notification-badge')).toHaveText('1');

  // No duplicates accumulated after reconnect settles
  await page.waitForTimeout(3_000);
  await expect(page.getByTestId('notification-card')).toHaveCount(1);
});

test('COS-064: duplicate event_id creates no duplicate notification rows', async ({ page }) => {
  await page.goto('/');
  await waitSSEConnected(page);

  // Same event_id twice → record_event dedup → single inbox row
  publish({ title: 'Idempotent event', eventId: 'evt-e2e-dedup-fixed' });
  publish({ title: 'Idempotent event', eventId: 'evt-e2e-dedup-fixed' });

  await expect(
    page.getByTestId('notification-card').filter({ hasText: 'Idempotent event' }),
  ).toHaveCount(1, { timeout: 15_000 });
  await expect(page.getByTestId('notification-badge')).toHaveText('1');

  await page.waitForTimeout(3_000);
  await expect(page.getByTestId('notification-card')).toHaveCount(1);
});

// ── AC3: empty / error states ──

test('COS-064: empty inbox state is visible', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('notification-bell')).toBeVisible();

  await openDrawer(page);
  await expect(page.getByTestId('notification-empty')).toContainText('Все чисто');
  await expect(page.getByTestId('notification-card')).toHaveCount(0);
});

test('COS-064: API failure shows honest error state with retry', async ({ page }) => {
  await page.route('**/api/v1/notifications/inbox?**', (route) => void route.abort());
  await page.route('**/api/v1/notifications/inbox/unread-count*', (route) => void route.abort());

  await page.goto('/');
  await openDrawer(page);

  await expect(page.getByTestId('notification-error')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('notification-error')).toContainText('Ошибка загрузки');
});

// ── AC4: keyboard / accessibility path ──

test('COS-064: keyboard path — bell, mark read on card, close', async ({ page }) => {
  publish({ title: 'Keyboard target', severity: 'medium' });

  await page.goto('/');

  // Focus bell by keyboard and open with Enter
  await page.getByTestId('notification-bell').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('notification-drawer')).toBeVisible();

  // Card is focusable → Enter marks read
  const card = page.getByTestId('notification-card').filter({ hasText: 'Keyboard target' });
  await card.focus();
  await expect(card).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(card).toHaveAttribute('data-read', 'true');

  // Close button reachable and works via keyboard
  const close = page.getByTestId('notification-close');
  await close.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('notification-drawer')).toBeHidden();
});

// ── AC5: ticket-based SSE auth + principal-bound recipient identity ──

test('COS-075: SSE stream opens via ticket — no recipient_id, no bearer in URL', async ({ page }) => {
  const sseUrlPromise = page.waitForRequest('**/api/v1/notifications/stream*');
  await page.goto('/');
  const req = await sseUrlPromise;

  const url = new URL(req.url());
  // Ticket present, recipient never client-asserted, bearer never in URL
  expect(url.searchParams.get('ticket')).toBeTruthy();
  expect(url.searchParams.get('recipient_id')).toBeNull();
  expect(req.url()).not.toContain(':admin');
  expect(req.headers()['authorization']).toBeUndefined();
});

test('COS-075/176: real principal reads own inbox; forged-signature token rejected (401)', async ({ request }) => {
  await publish({ title: 'Identity check', severity: 'high' });

  // operator (живой RS256 admin-токен): доставленный event виден в своём inbox
  const operatorRes = await request.get('/api/v1/notifications/inbox/unread-count', {
    headers: OPS_AUTH,
  });
  expect(operatorRes.status()).toBe(200);
  expect((await operatorRes.json()).unread).toBeGreaterThanOrEqual(1);

  // forged principal: структурно валидный JWT с подменённой подписью —
  // verifier COS-156 обязан отвергнуть, никакого identity-fallback.
  const session = await fetchSession();
  const forgedAuth = { Authorization: `Bearer ${tamperSignature(session.token)}` };

  const forgedCount = await request.get('/api/v1/notifications/inbox/unread-count', {
    headers: forgedAuth,
  });
  expect(forgedCount.status()).toBe(401);

  const forgedInbox = await request.get('/api/v1/notifications/inbox', {
    headers: forgedAuth,
  });
  expect(forgedInbox.status()).toBe(401);

  // COS-176: живой principal изолирован, forged identity не получает ничего.
  // Раздельные inbox'ы двух principals — отдельный тест COS-187 ниже.
});

test('COS-187: два seeded-principal — раздельные inbox (A не видит B)', async ({ request }) => {
  const adminAuth = await authHeaders();
  const adminRecipient = await e2eRecipient();
  const viewerAuth = await authHeaders(viewerCredentials());
  const viewerRecipient = await e2eRecipient(viewerCredentials());
  expect(viewerRecipient).not.toBe(adminRecipient);

  // B получает своё событие: A его не видит.
  publish({ title: 'For viewer only', recipient: viewerRecipient });
  const viewerCount = await request.get('/api/v1/notifications/inbox/unread-count', {
    headers: viewerAuth,
  });
  expect(viewerCount.status()).toBe(200);
  expect(((await viewerCount.json()) as { unread: number }).unread).toBe(1);

  const adminCount = await request.get('/api/v1/notifications/inbox/unread-count', {
    headers: adminAuth,
  });
  expect(((await adminCount.json()) as { unread: number }).unread).toBe(0);

  // A получает своё: B по-прежнему видит только своё.
  publish({ title: 'For admin only', recipient: adminRecipient });
  const adminCount2 = await request.get('/api/v1/notifications/inbox/unread-count', {
    headers: adminAuth,
  });
  expect(((await adminCount2.json()) as { unread: number }).unread).toBe(1);

  const viewerCount2 = await request.get('/api/v1/notifications/inbox/unread-count', {
    headers: viewerAuth,
  });
  expect(((await viewerCount2.json()) as { unread: number }).unread).toBe(1);

  const viewerInbox = await request.get('/api/v1/notifications/inbox', { headers: viewerAuth });
  const titles = ((await viewerInbox.json()) as Array<{ title: string }>).map((i) => i.title);
  expect(titles).toEqual(['For viewer only']);
});

test('COS-075: stream rejects invalid ticket (401, no recipient fallback)', async ({ request }) => {
  const res = await request.get('/api/v1/notifications/stream?ticket=invalid.sig.here');
  expect(res.status()).toBe(401);
});

// ── COS-079: SSE guards on run/domain streams + DLQ operator surface ──

test('COS-079: run stream rejects missing and invalid tickets (401)', async ({ request }) => {
  const missing = await request.get('/api/v1/runs/r-e2e-guard/stream');
  expect(missing.status()).toBe(401);

  const garbage = await request.get('/api/v1/runs/r-e2e-guard/stream?ticket=garbage.sig.x');
  expect(garbage.status()).toBe(401);
});

test('COS-079: domain stream rejects missing and invalid tickets (401)', async ({ request }) => {
  const missing = await request.get('/api/v1/domains/dom-e2e-guard/events/stream');
  expect(missing.status()).toBe(401);

  const garbage = await request.get('/api/v1/domains/dom-e2e-guard/events/stream?ticket=garbage.sig.x');
  expect(garbage.status()).toBe(401);
});

test('COS-079: DLQ shows seeded failed email row, replay sends honestly, row leaves DLQ', async ({ page, request }) => {
  const seeded = JSON.parse(helper('dlq-fixture --title "COS-079 DLQ row"')) as { id: string };

  // API surface: seeded row is terminal-failed
  const listRes = await request.get('/api/v1/notifications/dlq', { headers: OPS_AUTH });
  expect(listRes.status()).toBe(200);
  const dlqItems = (await listRes.json()) as Array<{ id: string; state: string }>;
  const seededItem = dlqItems.find((i) => i.id === seeded.id);
  expect(seededItem).toBeTruthy();
  expect(seededItem?.state).toBe('failed');

  // UI: operator view lists the row with honest last_error.
  // COS-084: hydrate usePreference('nav') больше не перебивает deep-link —
  // честный deep-link без клика по нав-кнопке.
  await page.goto('/?surface=station&view=notification-ops');
  const row = page.getByTestId('dlq-row').filter({ hasText: 'COS-079 DLQ row' });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('smtp down');
  await expect(row).toContainText('5/5');

  // Replay: stand provider (LoggingEmailProvider) honestly accepts → sent
  await row.getByTestId('dlq-replay-btn').click();
  await expect(page.getByText(/доставлено \(attempt 6\)/)).toBeVisible({ timeout: 15_000 });

  // Row honestly left the DLQ (state=sent), empty state appears
  await expect(page.getByText('DLQ пуста')).toBeVisible({ timeout: 15_000 });
  const afterRes = await request.get('/api/v1/notifications/dlq', { headers: OPS_AUTH });
  expect(((await afterRes.json()) as Array<unknown>).length).toBe(0);
});

test('COS-079: DLQ API rejects replay of unknown id (404)', async ({ request }) => {
  const res = await request.post('/api/v1/notifications/dlq/no-such-id/replay', {
    headers: OPS_AUTH,
  });
  expect(res.status()).toBe(404);
});

test('COS-084: deep-link ?view=notification-ops wins over hydrated nav preference (×2)', async ({ page, request }) => {
  for (let round = 1; round <= 2; round++) {
    // Сохранённая preference заведомо ДРУГАЯ (round 1 — честная гонка hydrate
    // vs deep-link; round 2 — стабильность после PUT'ов первого прохода).
    const put = await request.put('/api/v1/preferences', { data: { nav: 'runs' } });
    expect(put.status()).toBe(200);

    await page.goto('/?surface=station&view=notification-ops');

    // View открылась deep-link'ом, без клика по нав-кнопке.
    await expect(page.getByTestId('notification-ops-view')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('dlq-table')).toBeVisible();
  }
});
