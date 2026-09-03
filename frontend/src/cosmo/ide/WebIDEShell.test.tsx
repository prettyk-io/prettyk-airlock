// @vitest-environment jsdom
/**
 * COS-100: Web IDE (Surface B) — Core Unit & Component Tests.
 *
 * Verifies:
 *   - Style boundary: root container has .cosmo-ide-root class
 *   - File tree rendering from /api/v1/repos/tree
 *   - File content loading from /api/v1/repos/file
 *   - Monaco Editor mount & YAML/DSL language detection
 *   - Auto-save draft to localStorage & draft restore on reload
 *   - Save file to backend via PUT /api/v1/repos/file
 *   - Diff viewer toggle (button & shortcut)
 *   - Repo switching via top bar selector
 *   - Station navigation callback (← Station)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { WebIDEShell } from './WebIDEShell';

vi.mock('@monaco-editor/react', () => ({
  default: ({ onChange, value }: { onChange?: (v: string) => void; value?: string }) => (
    <div data-testid="mock-monaco-editor">
      <textarea
        data-testid="mock-monaco-textarea"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
      />
    </div>
  ),
  DiffEditor: ({ modified }: { modified?: string }) => (
    <div data-testid="mock-monaco-diff-editor">{modified}</div>
  ),
}));

const mockTree = [
  {
    name: 'scenarios',
    path: 'scenarios',
    kind: 'dir',
    children: [
      { name: 'auth.wire', path: 'scenarios/auth.wire', kind: 'file', size: 320 },
      { name: 'payment.wire', path: 'scenarios/payment.wire', kind: 'file', size: 280 },
    ],
  },
  {
    name: '.cosmo',
    path: '.cosmo',
    kind: 'dir',
    children: [
      { name: 'pipeline.yaml', path: '.cosmo/pipeline.yaml', kind: 'file', size: 240 },
    ],
  },
  { name: 'README.md', path: 'README.md', kind: 'file', size: 150 },
];

const mockFiles: Record<string, string> = {
  'README.md': '# Payments API\nCore banking service.\n',
  'scenarios/auth.wire': 'navigate "https://bank.local/login"\nfill "#user", "admin"\n',
  '.cosmo/pipeline.yaml': 'version: "2.0"\npipeline:\n  name: Test\n',
};

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();

  globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    // GET /api/v1/repos/tree
    if (url.includes('/api/v1/repos/tree')) {
      return Promise.resolve(new Response(JSON.stringify(mockTree), { status: 200 }));
    }

    // GET & PUT /api/v1/repos/file
    if (url.includes('/api/v1/repos/file')) {
      if (init?.method === 'PUT') {
        const body = JSON.parse(init.body as string);
        return Promise.resolve(
          new Response(
            JSON.stringify({ repo: body.repo, path: body.path, content: body.content, sha: 'sha256:saved' }),
            { status: 200 }
          )
        );
      }

      const u = new URL(url, 'http://localhost');
      const pathParam = u.searchParams.get('path') || 'README.md';
      const content = mockFiles[pathParam] || `// ${pathParam}\n`;
      return Promise.resolve(
        new Response(
          JSON.stringify({ repo: 'payments/api', path: pathParam, content, sha: 'sha256:orig' }),
          { status: 200 }
        )
      );
    }

    // POST /api/v1/repos/commit
    if (url.includes('/api/v1/repos/commit')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({ ok: true, commit_hash: 'a1b2c3d', branch: 'main', repo: 'payments/api', message: 'test commit' }),
          { status: 200 }
        )
      );
    }

    return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
  });
});

describe('COS-100: WebIDEShell Surface B', () => {
  it('1. Изоляция стилей: корневой контейнер имеет класс .cosmo-ide-root', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    const root = screen.getByTestId('web-ide-shell');
    expect(root).toBeTruthy();
    expect(root.classList.contains('cosmo-ide-root')).toBe(true);
  });

  it('2. Дерево файлов: отображает структуру файлов из /api/v1/repos/tree', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      const tree = screen.getByTestId('file-tree');
      expect(tree).toBeTruthy();
      expect(within(tree).getByText('scenarios')).toBeTruthy();
      expect(within(tree).getByText('auth.wire')).toBeTruthy();
      expect(within(tree).getByText('payment.wire')).toBeTruthy();
      expect(within(tree).getByText('.cosmo')).toBeTruthy();
      expect(within(tree).getByText('pipeline.yaml')).toBeTruthy();
      expect(within(tree).getByText('README.md')).toBeTruthy();
    });
  });

  it('3. Выбор файла: клик по .cosmo/pipeline.yaml загружает контент и определяет язык yaml', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByText('pipeline.yaml')).toBeTruthy();
    });

    fireEvent.click(screen.getByText('pipeline.yaml'));

    await waitFor(() => {
      expect(screen.getByTestId('current-file-badge').textContent).toContain('.cosmo/pipeline.yaml');
      expect(screen.getByTestId('active-file-tab').textContent).toContain('yaml');
    });
  });

  it('4. Автосохранение черновика: редактирование сохраняется в localStorage с ключом репо:файл', async () => {
    render(<WebIDEShell repo="payments/api" file="scenarios/auth.wire" />);

    await waitFor(() => {
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
    });

    const textarea = screen.getByTestId('mock-monaco-textarea');
    fireEvent.change(textarea, { target: { value: 'navigate "https://bank.local/login"\nclick "#submit"\n' } });

    // Auto-save debounce (800ms)
    await waitFor(
      () => {
        const draft = localStorage.getItem('cosmo_ide_draft:payments/api:scenarios/auth.wire');
        expect(draft).toContain('click "#submit"');
      },
      { timeout: 2000 }
    );
  });

  it('5. Восстановление черновика: перезагрузка файла восстанавливает несохранённый черновик', async () => {
    // Pre-populate draft in localStorage
    localStorage.setItem(
      'cosmo_ide_draft:payments/api:README.md',
      '# Payments API - Modified Draft\n'
    );

    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      const textarea = screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement;
      expect(textarea.value).toBe('# Payments API - Modified Draft\n');
      expect(screen.getByTestId('status-message').textContent).toContain('Восстановлен локальный черновик');
    });
  });

  it('6. Сброс черновика: кнопка «Сбросить» откатывает код к серверной версии и очищает draft', async () => {
    localStorage.setItem(
      'cosmo_ide_draft:payments/api:README.md',
      '# Modified Draft\n'
    );

    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByTestId('discard-draft-btn')).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId('discard-draft-btn'));

    await waitFor(() => {
      const textarea = screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement;
      expect(textarea.value).toBe(mockFiles['README.md']);
      expect(localStorage.getItem('cosmo_ide_draft:payments/api:README.md')).toBeNull();
    });
  });

  it('7. Сохранение файла: кнопка «Сохранить (⌘S)» отправляет PUT /api/v1/repos/file и удаляет draft', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
    });

    const textarea = screen.getByTestId('mock-monaco-textarea');
    fireEvent.change(textarea, { target: { value: '# Updated Content\n' } });

    await waitFor(() => {
      const saveBtn = screen.getByTestId('save-btn');
      expect(saveBtn).not.toBeDisabled();
    });

    fireEvent.click(screen.getByTestId('save-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('status-message').textContent).toContain('Файл успешно сохранён');
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/v1/repos/file',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            repo: 'payments/api',
            path: 'README.md',
            content: '# Updated Content\n',
          }),
        })
      );
      expect(localStorage.getItem('cosmo_ide_draft:payments/api:README.md')).toBeNull();
    });
  });

  it('8. Diff View: кнопка Diff переключает в режим сравнения изменений', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByTestId('diff-btn')).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId('diff-btn'));
    expect(screen.getByTestId('mock-monaco-diff-editor')).toBeTruthy();

    fireEvent.click(screen.getByTestId('diff-btn'));
    expect(screen.queryByTestId('mock-monaco-diff-editor')).toBeNull();
  });

  it('9. Переключатель репозиториев: выбор cbr/wallet-api перезапрашивает дерево', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByTestId('repo-select')).toBeTruthy();
    });

    const repoSelect = screen.getByTestId('repo-select');
    fireEvent.change(repoSelect, { target: { value: 'cbr/wallet-api' } });

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/repos/tree?repo=cbr%2Fwallet-api'),
        expect.anything()
      );
    });
  });

  it('10. Навигация обратно в Control Station: кнопка ← Station вызывает onNavigateToStation', async () => {
    const handleBack = vi.fn();
    render(<WebIDEShell repo="payments/api" file="README.md" onNavigateToStation={handleBack} />);

    await waitFor(() => {
      expect(screen.getByTestId('back-station-btn')).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId('back-station-btn'));
    expect(handleBack).toHaveBeenCalledWith({ view: 'domains' });
  });
});
