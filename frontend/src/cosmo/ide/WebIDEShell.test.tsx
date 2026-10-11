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
 *   - Save file → серверный черновик (PUT /api/v1/repos/workspace/draft, COS-182)
 *   - Diff viewer toggle (button & shortcut)
 *   - Repo switching via top bar selector
 *   - Station navigation callback (← Station)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { WebIDEShell, buildTree } from './WebIDEShell';

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

/** COS-179: плоские entries бэкенда (CAS/ref-чтение). */
const mockEntries = [
  { path: '.cosmo', kind: 'directory' },
  { path: '.cosmo/pipeline.yaml', kind: 'file' },
  { path: 'README.md', kind: 'file' },
  { path: 'scenarios', kind: 'directory' },
  { path: 'scenarios/auth.wire', kind: 'file' },
  { path: 'scenarios/payment.wire', kind: 'file' },
];

const mockWorkspace = {
  repo: 'payments/api',
  branch: 'main',
  headSha: 'sha256:head',
  capabilities: ['read', 'draft', 'commit', 'run'],
  authorization: 'allow',
};

const mockFiles: Record<string, string> = {
  'README.md': '# Payments API\nCore banking service.\n',
  'scenarios/auth.wire': 'navigate "https://bank.local/login"\nfill "#user", "admin"\n',
  '.cosmo/pipeline.yaml': 'version: "2.0"\npipeline:\n  name: Test\n',
};

// COS-186: per-test хуки для commit-пути (typed 409 сценарии) и head bootstrap'а.
let commitResponder: (() => Response) | null = null;
let bootstrapHead = 'sha256:head';
// COS-191: серверный черновик (COS-110) для restore-сценариев.
let serverDraft: string | null = null;
let draftGetError: number | null = null;

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  commitResponder = null;
  bootstrapHead = 'sha256:head';
  serverDraft = null;
  draftGetError = null;

  globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    // COS-179: workspace bootstrap (repo+branch → headSha)
    if (url.includes('/api/v1/repos/workspace/bootstrap')) {
      return Promise.resolve(
        new Response(JSON.stringify({ ...mockWorkspace, headSha: bootstrapHead }), { status: 200 })
      );
    }

    // COS-186: атомарный commit (plural, typed 409) — per-test responder.
    if (url.includes('/api/v1/repos/workspace/commits')) {
      if (commitResponder) return Promise.resolve(commitResponder());
      return Promise.resolve(
        new Response(
          JSON.stringify({
            sha: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
            htmlUrl: 'http://gitea/commit/a1b2c3d',
            authoredAt: '2026-09-25T00:00:00Z',
            filesChanged: 1,
          }),
          { status: 201 }
        )
      );
    }

    // GET /api/v1/repos/tree (CAS/ref) → плоские entries
    if (url.includes('/api/v1/repos/tree')) {
      return Promise.resolve(new Response(JSON.stringify({ entries: mockEntries }), { status: 200 }));
    }

    // COS-182/191: серверный черновик — save-path + восстановление (COS-110)
    if (url.includes('/api/v1/repos/workspace/draft')) {
      if (init?.method === 'PUT') {
        const body = JSON.parse(init.body as string);
        serverDraft = body.content;
        return Promise.resolve(
          new Response(
            JSON.stringify({
              path: body.path,
              content: body.content,
              baseBlobSha: body.baseBlobSha ?? null,
              updatedAt: '2026-09-25T00:00:00Z',
            }),
            { status: 201 }
          )
        );
      }
      if (init?.method === 'DELETE') {
        serverDraft = null;
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (draftGetError) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: `draft unavailable (${draftGetError})` }), { status: draftGetError })
        );
      }
      if (serverDraft !== null) {
        const u = new URL(url, 'http://localhost');
        return Promise.resolve(
          new Response(
            JSON.stringify({
              path: u.searchParams.get('path') ?? 'README.md',
              content: serverDraft,
              baseBlobSha: null,
              updatedAt: '2026-09-25T00:00:00Z',
            }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response(JSON.stringify({ detail: 'draft not found' }), { status: 404 }));
    }

    // GET /api/v1/repos/file (COS-182: PUT здесь больше нет — был мёртвый путь 405)
    if (url.includes('/api/v1/repos/file')) {
      const u = new URL(url, 'http://localhost');
      const pathParam = u.searchParams.get('path') || 'README.md';
      const content = mockFiles[pathParam] || `// ${pathParam}\n`;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            path: pathParam,
            content,
            sha: 'sha256:orig',
            encoding: 'utf-8',
            baseBlobSha: 'sha256:orig',
          }),
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

  it('7. COS-182: Save пишет серверный черновик (PUT /workspace/draft), а не мёртвый PUT /repos/file', async () => {
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
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const hit = calls.find(
        (c) =>
          String(c[0]).includes('/api/v1/repos/workspace/draft') &&
          (c[1] as RequestInit)?.method === 'PUT'
      );
      expect(hit).toBeTruthy();
      expect(JSON.parse(String((hit?.[1] as RequestInit)?.body))).toEqual({
        repo: 'payments/api',
        branch: 'main',
        path: 'README.md',
        content: '# Updated Content\n',
        baseBlobSha: 'sha256:orig',
      });
      expect(screen.getByTestId('status-message').textContent).toContain('Черновик сохранён на сервере');
      expect(localStorage.getItem('cosmo_ide_draft:payments/api:README.md')).toBeNull();

      // Мёртвый путь (405) не дёргается вообще.
      const dead = calls.find(
        (c) =>
          String(c[0]).includes('/api/v1/repos/file') &&
          (c[1] as RequestInit)?.method === 'PUT'
      );
      expect(dead).toBeFalsy();
    });
  });

  it('16. COS-182: ошибка draft-save → честная ошибка, без «сохранено»', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);
    await waitFor(() => {
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
    });

    // После загрузки файла подменяем draft-ручку на 503 (Valkey недоступен).
    globalThis.fetch = vi.fn().mockImplementation((url: string) =>
      url.includes('/api/v1/repos/workspace/draft')
        ? Promise.resolve(new Response(JSON.stringify({ detail: 'valkey unavailable' }), { status: 503 }))
        : Promise.resolve(new Response(JSON.stringify({}), { status: 404 }))
    );

    fireEvent.change(screen.getByTestId('mock-monaco-textarea'), { target: { value: '# X\n' } });
    await waitFor(() => {
      expect(screen.getByTestId('save-btn')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByTestId('save-btn'));

    await waitFor(() => {
      const text = screen.getByTestId('status-message').textContent ?? '';
      expect(text).toContain('Не сохранено');
      expect(text).toContain('valkey unavailable');
      expect(text).not.toContain('сохранён на сервере');
    });
  });

  it('17. COS-182: wire-файл честно сообщает, что runner не подключён', async () => {
    render(<WebIDEShell repo="payments/api" file="scenarios/auth.wire" />);

    await waitFor(() => {
      expect(screen.getByText('▶ Gutter: draft save (runner не подключён)')).toBeTruthy();
    });
  });

  it('8. Diff View: кнопка Diff переключает в режим сравнения изменений', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      // COS-179: дождаться загрузки файла (bootstrap → CAS-чтение), иначе spinner.
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
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

  it('11. COS-179: bootstrap (repo+branch → headSha) выполняется до CAS-чтения дерева', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/v1/repos/workspace/bootstrap?repo=payments%2Fapi',
        expect.anything()
      );
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/repos/tree?repo=payments%2Fapi&branch=main&head_sha=sha256%3Ahead'),
        expect.anything()
      );
    });
  });

  it('12. COS-179: deep-link commit → ref-режим (ref в tree/file, без bootstrap) и read-only', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" commit="abc1234def" />);

    await waitFor(() => {
      expect(screen.getByTestId('snapshot-badge').textContent).toContain('abc1234');
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/repos/tree?repo=payments%2Fapi&ref=abc1234def'),
        expect.anything()
      );
    });

    const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.some((c) => String(c[0]).includes('/workspace/bootstrap'))).toBe(false);

    expect(screen.getByTestId('commit-btn')).toBeDisabled();
    expect(screen.getByTestId('save-btn')).toBeDisabled();
    expect(screen.getByTestId('commit-run-btn')).toBeDisabled();
  });

  it('13. COS-179: ошибка bootstrap/дерева видна (не молчаливое пустое дерево)', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/v1/repos/workspace/bootstrap')) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "Repository 'payments/api' not found" }), { status: 404 })
        );
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    });

    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByTestId('tree-error').textContent).toContain('not found');
    });
  });

  it('14. COS-179: buildTree вкладывает плоские entries', () => {
    const tree = buildTree([
      { path: 'scenarios', kind: 'directory' },
      { path: 'scenarios/auth.wire', kind: 'file' },
      { path: 'README.md', kind: 'file' },
    ]);
    expect(tree.map((n) => n.path)).toEqual(['README.md', 'scenarios']);
    const dir = tree.find((n) => n.path === 'scenarios');
    expect(dir?.kind).toBe('dir');
    expect(dir?.children?.map((c) => c.name)).toEqual(['auth.wire']);
  });

  it('15. COS-186: Commit & Push идёт в plural /workspace/commits с fileChanges + CAS head', async () => {
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
    });

    fireEvent.change(screen.getByTestId('mock-monaco-textarea'), { target: { value: '# Changed\n' } });
    fireEvent.click(screen.getByTestId('commit-btn'));
    fireEvent.change(screen.getByPlaceholderText('feat(auth): update wire scenario assertions'), {
      target: { value: 'test commit' },
    });
    fireEvent.click(screen.getByText('Запушить в репозиторий'));

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const hit = calls.find((c) => String(c[0]).includes('/api/v1/repos/workspace/commits'));
      expect(hit).toBeTruthy();
      const body = JSON.parse(String((hit?.[1] as RequestInit)?.body));
      expect(body.repo).toBe('payments/api');
      expect(body.branch).toBe('main');
      expect(body.fileChanges).toEqual([
        { path: 'README.md', content: '# Changed\n', action: 'update' },
      ]);
      expect(body.expectedHeadSha).toBe('sha256:head');
      expect(screen.getByTestId('status-message').textContent).toContain('Запушено');
    });
  });

  it('18. COS-186: concurrent 409 → понятный конфликт; «Обновить и повторить» делает re-bootstrap + retry', async () => {
    let commitCalls = 0;
    commitResponder = () => {
      commitCalls += 1;
      if (commitCalls === 1) {
        return new Response(
          JSON.stringify({
            // live-форма COS-181: конверт top-level (COS-186)
            error: {
              code: 'WORKSPACE_CONFLICT',
              message: 'branch head moved in payments/api@main: expected sha256:head, actual sha256:new (refresh workspace and retry)',
              details: {
                kind: 'concurrent',
                expected_sha: 'sha256:head',
                actual_sha: 'sha256:new',
                paths: [],
              },
            },
          }),
          { status: 409 }
        );
      }
      return new Response(
        JSON.stringify({
          sha: 'b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3',
          htmlUrl: 'http://gitea/commit/b2c3d4e',
          authoredAt: '2026-09-25T00:00:00Z',
          filesChanged: 1,
        }),
        { status: 201 }
      );
    };

    render(<WebIDEShell repo="payments/api" file="README.md" />);
    await waitFor(() => {
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId('mock-monaco-textarea'), { target: { value: '# Conflict\n' } });
    fireEvent.click(screen.getByTestId('commit-btn'));
    fireEvent.change(screen.getByPlaceholderText('feat(auth): update wire scenario assertions'), {
      target: { value: 'conflict test' },
    });
    fireEvent.click(screen.getByText('Запушить в репозиторий'));

    await waitFor(() => {
      const box = screen.getByTestId('commit-conflict');
      expect(box.textContent).toContain('Ветка ушла вперёд');
      expect(box.textContent).toContain('sha256:');
      // Сырой detail конверта не показывается.
      expect(box.textContent).not.toContain('branch head moved');
    });
    // Модалка осталась открытой (успех/конфликт различимы).
    expect(screen.getByText('Commit & Push изменения')).toBeTruthy();

    // Внешний пуш увёл голову — refresh подхватывает новый head и повторяет.
    bootstrapHead = 'sha256:head2';
    fireEvent.click(screen.getByTestId('commit-refresh-btn'));

    await waitFor(() => {
      expect(commitCalls).toBe(2);
      const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const commitBodies = calls
        .filter((c) => String(c[0]).includes('/api/v1/repos/workspace/commits'))
        .map((c) => JSON.parse(String((c[1] as RequestInit)?.body)));
      expect(commitBodies[1].expectedHeadSha).toBe('sha256:head2');
      expect(screen.queryByTestId('commit-conflict')).toBeNull();
      expect(screen.getByTestId('status-message').textContent).toContain('Запушено');
      const bootstrapCalls = calls.filter((c) => String(c[0]).includes('/workspace/bootstrap'));
      expect(bootstrapCalls.length).toBeGreaterThan(1);
    });
  });

  it('19. COS-186: missing 409 показывает конфликтующие файлы (kind-aware, без retry-кнопки)', async () => {
    commitResponder = () =>
      new Response(
        JSON.stringify({
          detail: {
            error: {
              code: 'WORKSPACE_CONFLICT',
              message: 'file missing',
              details: {
                kind: 'missing',
                expected_sha: 'sha256:head',
                actual_sha: 'sha256:head',
                paths: ['scenarios/auth.wire'],
              },
            },
          },
        }),
        { status: 409 }
      );

    render(<WebIDEShell repo="payments/api" file="README.md" />);
    await waitFor(() => {
      expect(screen.getByTestId('mock-monaco-textarea')).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId('mock-monaco-textarea'), { target: { value: '# Missing\n' } });
    fireEvent.click(screen.getByTestId('commit-btn'));
    fireEvent.change(screen.getByPlaceholderText('feat(auth): update wire scenario assertions'), {
      target: { value: 'missing test' },
    });
    fireEvent.click(screen.getByText('Запушить в репозиторий'));

    await waitFor(() => {
      const box = screen.getByTestId('commit-conflict');
      expect(box.textContent).toContain('Файлы отсутствуют в ветке');
      expect(box.textContent).toContain('scenarios/auth.wire');
    });
    const refreshBtn = screen.getByTestId('commit-refresh-btn');
    expect(refreshBtn.textContent).toContain('Обновить workspace');
    expect(refreshBtn.textContent).not.toContain('повторить');
  });

  it('20. COS-191: серверный черновик восстанавливается при открытии + индикация server WIP', async () => {
    serverDraft = '# Server WIP\n';
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect((screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement).value).toBe('# Server WIP\n');
    });
    expect(screen.getByTestId('content-source-badge').textContent).toBe('server WIP');
    expect(screen.getByTestId('status-message').textContent).toContain('Восстановлен серверный черновик');
    // Контент отличается от repo-версии → доступен «Сбросить».
    expect(screen.getByTestId('discard-draft-btn')).toBeTruthy();
  });

  it('21. COS-191: локальный черновик приоритетнее серверного (индикация local draft)', async () => {
    serverDraft = '# Server WIP\n';
    localStorage.setItem('cosmo_ide_draft:payments/api:README.md', '# Local WIP\n');

    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect((screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement).value).toBe('# Local WIP\n');
    });
    expect(screen.getByTestId('content-source-badge').textContent).toBe('local draft');
  });

  it('22. COS-191: черновик недоступен (503) — тихо repo-версия, без индикации и ошибок', async () => {
    draftGetError = 503;
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect((screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement).value).toBe(mockFiles['README.md']);
    });
    expect(screen.queryByTestId('content-source-badge')).toBeNull();
    expect(screen.queryByTestId('status-message')).toBeNull();
  });

  it('23. COS-191: черновик, равный repo-версии, не помечается как WIP', async () => {
    serverDraft = mockFiles['README.md'];
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect((screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement).value).toBe(mockFiles['README.md']);
    });
    expect(screen.queryByTestId('content-source-badge')).toBeNull();
  });

  it('24. COS-191: «Сбросить» возвращает repo-версию и удаляет серверный черновик', async () => {
    serverDraft = '# Server WIP\n';
    render(<WebIDEShell repo="payments/api" file="README.md" />);

    await waitFor(() => {
      expect((screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement).value).toBe('# Server WIP\n');
    });
    expect(screen.getByTestId('content-source-badge').textContent).toBe('server WIP');

    fireEvent.click(screen.getByTestId('discard-draft-btn'));

    await waitFor(() => {
      expect((screen.getByTestId('mock-monaco-textarea') as HTMLTextAreaElement).value).toBe(mockFiles['README.md']);
      expect(screen.queryByTestId('content-source-badge')).toBeNull();
    });
    const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(
      calls.some(
        (c) =>
          String(c[0]).includes('/api/v1/repos/workspace/draft') &&
          (c[1] as RequestInit)?.method === 'DELETE'
      )
    ).toBe(true);
    expect(serverDraft).toBeNull();
  });
});
