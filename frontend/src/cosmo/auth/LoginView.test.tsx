// @vitest-environment jsdom
/**
 * COS-158: LoginView — боевая форма входа (честные состояния).
 *
 * Покрывает:
 *   - рендер формы
 *   - 401 → «Неверный email или пароль», сессия не создаётся
 *   - успех → access_token сохранён в authStore + localStorage
 *   - пустые поля → локальная валидация без сетевого запроса
 *   - logout() сбрасывает сессию
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CosmoThemeProvider } from '../theme';
import { LoginView } from './LoginView';
import { getSession, logout } from './authStore';

const TEST_TOKEN =
  'eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiIsImVtYWlsIjoiYWRtaW5AY29zbW9wb3J0LmxvY2FsIiwicm9sZXMiOlsiYWRtaW5fc2VjIl0sImlzX2FkbWluIjp0cnVlfQ.test';

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

function fillAndSubmit(email: string, password: string) {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/пароль/i), { target: { value: password } });
  fireEvent.click(screen.getByTestId('login-submit'));
}

beforeEach(() => {
  localStorage.clear();
  logout();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('COS-158: LoginView', () => {
  it('рендерит форму входа', () => {
    render(<CosmoThemeProvider><LoginView /></CosmoThemeProvider>);
    expect(screen.getByTestId('login-email')).toBeTruthy();
    expect(screen.getByTestId('login-password')).toBeTruthy();
    expect(screen.getByTestId('login-submit')).toBeTruthy();
  });

  it('401 → «Неверный email или пароль», сессия не создаётся', async () => {
    vi.stubGlobal('fetch', mockFetch(401, { detail: '401_UNAUTHORIZED: invalid credentials' }));
    render(<CosmoThemeProvider><LoginView /></CosmoThemeProvider>);
    fillAndSubmit('admin@cosmoport.local', 'wrong-password');

    await waitFor(() => expect(screen.getByTestId('login-error')).toBeTruthy());
    expect(screen.getByTestId('login-error').textContent).toContain('Неверный email или пароль');
    expect(getSession()).toBeNull();
    expect(localStorage.getItem('cosmo_auth_token')).toBeNull();
  });

  it('успех → access_token сохранён в authStore + localStorage', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(200, {
        access_token: TEST_TOKEN,
        token_type: 'bearer',
        expires_in: 3600,
        user: { sub: 'admin', email: 'admin@cosmoport.local', roles: ['admin_sec'], is_admin: true },
      }),
    );
    render(<CosmoThemeProvider><LoginView /></CosmoThemeProvider>);
    fillAndSubmit('admin@cosmoport.local', 'cosmo-admin-dev');

    await waitFor(() => expect(getSession()).not.toBeNull());
    expect(getSession()?.user.email).toBe('admin@cosmoport.local');
    expect(getSession()?.user.roles).toEqual(['admin_sec']);
    expect(localStorage.getItem('cosmo_auth_token')).toBe(TEST_TOKEN);
  });

  it('пустые поля → локальная валидация без сетевого запроса', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(<CosmoThemeProvider><LoginView /></CosmoThemeProvider>);
    fireEvent.click(screen.getByTestId('login-submit'));

    await waitFor(() => expect(screen.getByTestId('login-error')).toBeTruthy());
    expect(screen.getByTestId('login-error').textContent).toContain('Введите email и пароль');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('logout() очищает сессию', async () => {
    vi.stubGlobal('fetch', mockFetch(200, { access_token: TEST_TOKEN, token_type: 'bearer' }));
    render(<CosmoThemeProvider><LoginView /></CosmoThemeProvider>);
    fillAndSubmit('admin@cosmoport.local', 'cosmo-admin-dev');
    await waitFor(() => expect(getSession()).not.toBeNull());

    logout();
    expect(getSession()).toBeNull();
    expect(localStorage.getItem('cosmo_auth_token')).toBeNull();
  });
});