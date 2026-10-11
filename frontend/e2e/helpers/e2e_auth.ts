/**
 * COS-176: e2e auth — реальный login (боевой RS256 issuer, COS-157/158).
 *
 * История: COS-092 минтил локальный unsigned JWT (deps тогда проверял только
 * формат). COS-156 закрыл это: verifier требует крипто-подпись и отвергает
 * unsigned/HMAC-токены. Приватный ключ issuer'а живёт ТОЛЬКО в
 * OpenBao (`secret/cosmo/jwt-keys`), поэтому единственный честный
 * e2e-credential против живого стенда — реальный
 * `POST /api/v1/auth/login` (dev-admin сидирован COS-175, OpenBao).
 *
 * Все e2e-спеки используют ЭТОТ хелпер: page-сессия через
 * `authenticatePage()` (localStorage-контракт `cosmo_auth_token`, COS-158),
 * API-вызовы через `authHeaders()`.
 */
import { test, type Page } from '@playwright/test';

export const E2E_EMAIL = process.env.E2E_COSMO_EMAIL ?? 'admin@cosmoport.local';
export const E2E_PASSWORD = process.env.E2E_COSMO_PASSWORD ?? 'cosmo-admin-dev';
// COS-187: второй seeded-пользователь (отдельный principal/inbox).
export const E2E_VIEWER_EMAIL = process.env.E2E_COSMO_VIEWER_EMAIL ?? 'viewer@cosmoport.local';
export const E2E_VIEWER_PASSWORD = process.env.E2E_COSMO_VIEWER_PASSWORD ?? 'cosmo-viewer-dev';
export const API_BASE_URL = (
  process.env.E2E_COSMO_API_URL ?? 'http://127.0.0.1:8100'
).replace(/\/+$/, '');

/** Креды второго principal'а (viewer) для раздельных inbox-проверок. */
export function viewerCredentials(): { email: string; password: string } {
  return { email: E2E_VIEWER_EMAIL, password: E2E_VIEWER_PASSWORD };
}

/** Живой auth-контур недоступен (backend down / login отверг / не seeded). */
export class E2eAuthUnavailableError extends Error {}

export interface E2eSession {
  token: string;
  /** principal.user_id на бэкенде (recipient inbox/SSE резолвится из sub). */
  sub: string;
  email: string;
  expiresAt: number;
}

type E2eCredentials = { email?: string; password?: string };

// COS-187: кэш сессий per-principal (два seeded-юзера в одной e2e-линии).
const sessions = new Map<string, E2eSession>();

function sessionKey(credentials?: E2eCredentials): string {
  return credentials?.email ?? E2E_EMAIL;
}

function decodePayload(token: string): Record<string, unknown> {
  const part = token.split('.')[1] ?? '';
  const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
  try {
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

async function login(credentials?: E2eCredentials): Promise<E2eSession> {
  const email = credentials?.email ?? E2E_EMAIL;
  const password = credentials?.password ?? E2E_PASSWORD;

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  } catch (err) {
    throw new E2eAuthUnavailableError(
      `cosmo-api unreachable at ${API_BASE_URL}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  if (!res.ok) {
    throw new E2eAuthUnavailableError(`login failed: HTTP ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { access_token?: string; expires_in?: number };
  if (!body.access_token) {
    throw new E2eAuthUnavailableError('login response has no access_token');
  }
  const claims = decodePayload(body.access_token);
  return {
    token: body.access_token,
    sub: typeof claims.sub === 'string' ? claims.sub : email,
    email: typeof claims.email === 'string' ? claims.email : email,
    // -60s запас: не отдаём токен на последней минуте жизни.
    expiresAt: Date.now() + ((body.expires_in ?? 3600) - 60) * 1000,
  };
}

/** Реальная сессия; login кэшируется per-email до истечения exp (COS-187). */
export async function fetchSession(credentials?: E2eCredentials): Promise<E2eSession> {
  const key = sessionKey(credentials);
  const cached = sessions.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached;
  const session = await login(credentials);
  sessions.set(key, session);
  return session;
}

/** Сброс кэша (негативный тест login / смена кредов). */
export function resetSessionCache(): void {
  sessions.clear();
}

/** Bearer headers для API-запросов (Playwright request / global fetch). */
export async function authHeaders(credentials?: E2eCredentials): Promise<Record<string, string>> {
  const session = await fetchSession(credentials);
  return { Authorization: `Bearer ${session.token}` };
}

/** Recipient уведомлений = principal.user_id живого токена (env override — default-юзеру). */
export async function e2eRecipient(credentials?: E2eCredentials): Promise<string> {
  if (!credentials && process.env.E2E_COSMO_RECIPIENT) {
    return process.env.E2E_COSMO_RECIPIENT;
  }
  return (await fetchSession(credentials)).sub;
}

/** Засеять FE-сессию (localStorage-контракт COS-158) до навигации. */
export async function authenticatePage(page: Page, credentials?: E2eCredentials): Promise<E2eSession> {
  const session = await fetchSession(credentials);
  await page.addInitScript((token) => {
    globalThis.localStorage?.setItem('cosmo_auth_token', token);
  }, session.token);
  return session;
}

/**
 * Честный skip, если живой auth-контур недоступен (стенд не поднят):
 * acceptance COS-176 допускает skip вместо фейкового green.
 */
export async function authenticatePageOrSkip(
  page: Page,
  credentials?: E2eCredentials,
): Promise<E2eSession | null> {
  try {
    return await authenticatePage(page, credentials);
  } catch (err) {
    test.skip(
      true,
      `live auth contour unavailable: ${err instanceof Error ? err.message : String(err)}`,
    );
    return null;
  }
}

/** Подменить подпись (последний сегмент) — forged-вектор для негатив-тестов. */
export function tamperSignature(token: string): string {
  const [header, payload, signature = ''] = token.split('.');
  const flipped = signature.startsWith('A') ? 'B' : 'A';
  return `${header}.${payload}.${flipped}${signature.slice(1)}`;
}
