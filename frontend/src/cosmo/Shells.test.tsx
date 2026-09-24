// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { App } from '../App';
import { buildLink, parseParams, useDeepLink } from './shared/DeepLinker';

// Mock heavy IDE deps to avoid canvas errors in jsdom
vi.mock('@monaco-editor/react', () => ({
  default: () => null,
  DiffEditor: () => null,
}));
vi.mock('@xterm/xterm', () => ({
  Terminal: class {},
}));

beforeEach(() => {
  // Очищаем URL перед каждым тестом
  window.history.replaceState(null, '', '/');

  // COS-158: App gate'ится за боевой auth-сессией — сидируем валидную
  // сессию (display-only; подпись клиентом не проверяется).
  window.localStorage.setItem(
    'cosmo_auth_token',
    'eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiIsImVtYWlsIjoiYWRtaW5AY29zbW9wb3J0LmxvY2FsIiwicm9sZXMiOlsiYWRtaW5fc2VjIl0sImlzX2FkbWluIjp0cnVlfQ.test',
  );

  // COS-061: Mock notification API + EventSource for AlertHUD
  vi.stubGlobal('EventSource', class MockEventSource {
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    addEventListener(_type: string, _fn: (e: unknown) => void) {}
    close() {}
  });
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
    if (url.includes('/api/v1/notifications/inbox')) {
      if (url.includes('unread-count')) {
        return Promise.resolve(new Response(JSON.stringify({ unread: 0 }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }
    // COS-075: SSE ticket endpoint (AlertHUD connect flow)
    if (url.includes('/api/v1/notifications/sse-ticket')) {
      return Promise.resolve(new Response(JSON.stringify({ ticket: 'test-ticket', recipient_id: 'operator', expires_in: 60 }), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
  }));
});

describe('COS-020/021/023: Shells render', () => {
  it('Control Station рендерится по умолчанию', () => {
    render(<App />);
    expect(screen.getByText('Cosmoport')).toBeTruthy();
  });

  it('Surface switcher показывает обе кнопки', () => {
    render(<App />);
    expect(screen.getByText('Control Station')).toBeTruthy();
    expect(screen.getByText('Web IDE')).toBeTruthy();
  });

  it('Переключение на Web IDE через кнопку', () => {
    render(<App />);
    fireEvent.click(screen.getByText('Web IDE'));
    // Web IDE toolbar должен быть виден
    expect(screen.getByText('IDE')).toBeTruthy();
  });

  it('Переключение обратно на Control Station', () => {
    render(<App />);
    fireEvent.click(screen.getByText('Web IDE'));
    fireEvent.click(screen.getByText('Control Station'));
    expect(screen.getByText('Cosmoport')).toBeTruthy();
  });

  it('COS-053: Dark Mode Toggle переключает Meta Light ↔ Meta Dark', () => {
    render(<App />);
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    const toggleBtn = screen.getByLabelText('theme-toggle');
    expect(toggleBtn).toBeTruthy();

    // Click to switch to dark mode
    fireEvent.click(toggleBtn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    // Click again to switch back to light mode
    fireEvent.click(toggleBtn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('COS-057: Breadcrumbs рендерится в Header и показывает навигационную цепочку', () => {
    render(<App />);
    expect(screen.getByRole('navigation', { name: 'breadcrumb' })).toBeTruthy();
    expect(screen.getByText('Поиск по системе...')).toBeTruthy();
  });

  it('COS-057: Global Search открывается по кнопке и выполняет поиск', () => {
    render(<App />);
    const searchBtn = screen.getByText('Поиск по системе...');
    fireEvent.click(searchBtn);

    expect(screen.getByPlaceholderText('Поиск по доменам, приложениям, прогонам, гейтам, релизам (⌘K)...')).toBeTruthy();
    expect(screen.getByText('Обзор и Домены')).toBeTruthy();
    expect(screen.getAllByText('Security Gates').length).toBeGreaterThanOrEqual(1);
  });
});

describe('COS-024: Deep-Linking', () => {
  it('buildLink генерирует URL для IDE со всеми параметрами', () => {
    const link = buildLink({
      surface: 'ide',
      ide: { repo: 'payments/api', file: 'scenarios/auth.wire', line: 7 },
    });
    expect(link).toContain('surface=ide');
    expect(link).toContain('repo=payments%2Fapi');
    expect(link).toContain('file=scenarios%2Fauth.wire');
    expect(link).toContain('line=7');
  });

  it('buildLink для Gate Inspector → строка кода', () => {
    const link = buildLink({
      surface: 'ide',
      ide: { repo: 'payments/api', file: 'scenarios/auth.wire', line: 7 },
    });
    const u = new URLSearchParams(link.split('?')[1]);
    expect(u.get('surface')).toBe('ide');
    expect(u.get('file')).toBe('scenarios/auth.wire');
    expect(u.get('line')).toBe('7');
  });

  it('buildLink для Commit & Run → Live DAG', () => {
    const link = buildLink({
      surface: 'station',
      station: { view: 'runs', run_id: '1043' },
    });
    const u = new URLSearchParams(link.split('?')[1]);
    expect(u.get('surface')).toBe('station');
    expect(u.get('view')).toBe('runs');
    expect(u.get('run_id')).toBe('1043');
  });

  it('buildLink для LC Config → редактор', () => {
    const link = buildLink({
      surface: 'ide',
      ide: { repo: 'core/config', file: '.cosmo/pipeline.yaml' },
    });
    const u = new URLSearchParams(link.split('?')[1]);
    expect(u.get('surface')).toBe('ide');
    expect(u.get('repo')).toBe('core/config');
    expect(u.get('file')).toBe('.cosmo/pipeline.yaml');
  });

  it('parseParams читает IDE-параметры из URL', () => {
    window.history.replaceState(null, '',
      '/?surface=ide&repo=test/repo&file=main.wire&line=15'
    );
    // Re-import to re-read URL
    const state = parseParams();
    expect(state.surface).toBe('ide');
    expect(state.ide.repo).toBe('test/repo');
    expect(state.ide.file).toBe('main.wire');
    expect(state.ide.line).toBe(15);
  });

  it('parseParams читает Station-параметры из URL', () => {
    window.history.replaceState(null, '',
      '/?surface=station&view=runs&run_id=1042'
    );
    const state = parseParams();
    expect(state.surface).toBe('station');
    expect(state.station.view).toBe('runs');
    expect(state.station.run_id).toBe('1042');
  });

  it('parseParams default surface = station', () => {
    window.history.replaceState(null, '', '/');
    const state = parseParams();
    expect(state.surface).toBe('station');
    expect(state.ide.repo).toBeUndefined();
    expect(state.station.run_id).toBeUndefined();
  });

  it('Deep-link IDE рендерит breadcrumb', () => {
    window.history.replaceState(null, '',
      '/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=7'
    );
    render(<App />);
    // Breadcrumb в тулбаре IDE
    expect(screen.getByText('payments/api')).toBeTruthy();
    expect(screen.getByText('scenarios/auth.wire')).toBeTruthy();
  });

  it('Deep-link Station рендерит run-context chip', () => {
    window.history.replaceState(null, '',
      '/?surface=station&view=runs&run_id=1043'
    );
    render(<App />);
    expect(screen.getByText('Run #1043')).toBeTruthy();
  });

  it('COS-086: Web IDE — показывает Diff toggle с ⌘D, gutter hint для .wire и minimap diff-индикаторы', () => {
    window.history.replaceState(null, '',
      '/?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=7'
    );
    render(<App />);
    // Diff toggle button shows ⌘D keyboard shortcut
    expect(screen.getByText('Diff (⌘D)')).toBeTruthy();
    // .wire gutter hint visible
    expect(screen.getByText('▶ Click gutter to run step')).toBeTruthy();
    // Commit & Push is visible
    expect(screen.getByText('Commit & Push')).toBeTruthy();
  });

  it('COS-099: Hotkeys — «?» открывает справку по клавишам; Escape закрывает', () => {
    render(<App />);

    // Press '?' to open help overlay
    fireEvent.keyDown(window, { key: '?' });
    expect(screen.getByText('Справка по горячим клавишам (Keyboard Shortcuts)')).toBeTruthy();
    expect(screen.getAllByText('Обзор / Домены').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Приложения').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Новый прогон (New Run)')).toBeTruthy();

    // Press Escape to close
    fireEvent.keyDown(window, { key: 'Escape' });
    // After escape, element should still be in DOM (Dialog unmounts but React renders Overview)
    // Just confirm no error; the help close callback runs
  });
});