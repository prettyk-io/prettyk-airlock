/**
 * COS-158: боевая auth-сессия (reactive store + localStorage persistence).
 *
 * Единственный источник правды о сессии клиента:
 *   - ``login(email, password)`` → POST /api/v1/auth/login → JWT в localStorage
 *   - ``logout()`` → сброс сессии
 *   - ``api.ts`` читает access-токен отсюда (Bearer) и на 401 дёргает
 *     ``clearSessionOnUnauthorized()`` → UI сам вернётся на login.
 *
 * Storage contract:
 *   - ``cosmo_auth_token`` — сырой JWT (совместимо с pre-COS-158 seam и e2e).
 *   - user выводится из payload токена (base64url, БЕЗ проверки подписи —
 *     это display-only; единственный авторитет по правам — бэкенд).
 */
import { useSyncExternalStore } from 'react';

export interface CosmoUser {
  sub: string;
  email: string;
  roles: string[];
  is_admin: boolean;
}

export interface CosmoSession {
  accessToken: string;
  user: CosmoUser;
}

export const LOGIN_PATH = '/api/v1/auth/login';
const TOKEN_KEY = 'cosmo_auth_token';

let session: CosmoSession | null = loadSession();
const listeners = new Set<() => void>();

function readToken(): string | null {
  try {
    return globalThis.localStorage?.getItem(TOKEN_KEY) ?? null;
  } catch {
    return null;
  }
}

function b64urlDecode(input: string): string {
  const b64 = input.replace(/-/g, '+').replace(/_/g, '/');
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
  return atob(padded);
}

function decodeUser(token: string): CosmoUser {
  const fallback: CosmoUser = { sub: 'operator', email: 'operator', roles: [], is_admin: false };
  const parts = token.split('.');
  if (parts.length < 2) return fallback;
  try {
    const payload = JSON.parse(b64urlDecode(parts[1])) as Record<string, unknown>;
    const sub = typeof payload.sub === 'string' ? payload.sub : fallback.sub;
    const roles = Array.isArray(payload.roles)
      ? payload.roles.filter((r): r is string => typeof r === 'string')
      : [];
    return {
      sub,
      email: typeof payload.email === 'string' ? payload.email : sub,
      roles,
      is_admin: payload.is_admin === true,
    };
  } catch {
    return fallback;
  }
}

function loadSession(): CosmoSession | null {
  const token = readToken();
  if (!token) return null;
  return { accessToken: token, user: decodeUser(token) };
}

function setToken(token: string | null): void {
  try {
    if (token) globalThis.localStorage?.setItem(TOKEN_KEY, token);
    else globalThis.localStorage?.removeItem(TOKEN_KEY);
  } catch {
    /* no localStorage */
  }
}

function commit(next: CosmoSession | null): void {
  session = next;
  setToken(next ? next.accessToken : null);
  for (const fn of listeners) fn();
}

export function getSession(): CosmoSession | null {
  // Ленивое чтение localStorage: покрывает кейс, когда токен засеян извне
  // (e2e addInitScript / тесты) уже после инициализации модуля.
  if (!session) {
    session = loadSession();
  }
  return session;
}

export function getAccessToken(): string | null {
  return session?.accessToken ?? null;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook: перерисовывает дерево при login/logout/401-инвалидации. */
export function useSession(): CosmoSession | null {
  return useSyncExternalStore(subscribe, getSession, getSession);
}

export class LoginError extends Error {}

async function describeError(res: Response): Promise<string> {
  try {
    const json = (await res.json()) as { detail?: unknown };
    if (json && typeof json.detail === 'string') return json.detail;
    if (json && json.detail) return JSON.stringify(json.detail);
  } catch {
    /* non-JSON body */
  }
  return `${res.status} ${res.statusText}`;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(LOGIN_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    throw new LoginError(await describeError(res));
  }
  const json = (await res.json()) as { access_token?: string };
  if (!json?.access_token) {
    throw new LoginError('в ответе нет access_token');
  }
  commit({ accessToken: json.access_token, user: decodeUser(json.access_token) });
}

export function logout(): void {
  commit(null);
}

/** 401 на любом API-вызове → сессия больше не валидна, сброс до login. */
export function clearSessionOnUnauthorized(): void {
  if (session) commit(null);
}