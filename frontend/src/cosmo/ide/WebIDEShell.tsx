/**
 * COS-023 / COS-041 / COS-086: Web IDE Shell — Full Integration.
 *
 * Real file tree from ForgeAdapter/API, Monaco Editor with live file loading,
 * Diff Viewer, Commit & Push, Commit & Run, and COS-086 fast-diff polish:
 *   - Gutter [▶] run icons for .wire DSL step execution
 *   - ⌘D hotkey for Diff Viewer toggle
 *   - Unsaved-line minimap & gutter diff decorations
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import Editor, { DiffEditor, type OnMount } from '@monaco-editor/react';
import type { editor } from 'monaco-editor';
// COS-086: use numeric constants for OverviewRulerLane to avoid monaco runtime import
const RULER_LEFT = 1;
const RULER_RIGHT = 7;
// COS-182: Monaco MouseTargetType.GUTTER_GLYPH_MARGIN (без runtime-импорта monaco).
const GUTTER_GLYPH_MARGIN = 2;
import type { StationContext } from '../shared/DeepLinker';
import {
  api,
  CosmoApiError,
  type WorkspaceBootstrap,
  type WorkspaceConflictDetails,
  type WorkspaceConflictKind,
  type WorkspaceTreeEntry,
} from '../station/api';

interface WebIDEProps {
  repo?: string;
  file?: string;
  line?: number;
  /** COS-179 / FR-004: commit SHA из deep-link → immutable snapshot (ref-режим). */
  commit?: string;
  onNavigateToStation?: (ctx: Partial<StationContext>) => void;
}

export interface IDEFileNode {
  name: string;
  path: string;
  kind: 'file' | 'dir';
  size?: number;
  children?: IDEFileNode[];
}

const DEFAULT_REPO = 'payments/api';
const DEFAULT_FILE = 'README.md';
const DRAFT_PREFIX = 'cosmo_ide_draft:';

function getDraftKey(repo: string, file: string): string {
  return `${DRAFT_PREFIX}${repo}:${file}`;
}

// ── COS-186: typed 409 WORKSPACE_CONFLICT (kind-aware UX) ───────────────

function shortSha(sha: string | null): string {
  return sha ? sha.slice(0, 7) : '—';
}

/** Понятное сообщение по конверту COS-181 (без сырого detail). */
export function describeWorkspaceConflict(conflict: WorkspaceConflictDetails): string {
  if (conflict.kind === 'concurrent') {
    return `Ветка ушла вперёд (ожидался ${shortSha(conflict.expected_sha)}, сейчас ${shortSha(conflict.actual_sha)})`;
  }
  if (conflict.kind === 'exists') {
    return `Файлы уже существуют в ветке: ${conflict.paths.join(', ') || '—'}`;
  }
  return `Файлы отсутствуют в ветке: ${conflict.paths.join(', ') || '—'}`;
}

/** details конверта → типизированный конфликт (fallback — concurrent). */
export function toWorkspaceConflict(details: Record<string, unknown> | null): WorkspaceConflictDetails {
  const kindRaw = details?.kind;
  const kind: WorkspaceConflictKind =
    kindRaw === 'exists' || kindRaw === 'missing' || kindRaw === 'concurrent' ? kindRaw : 'concurrent';
  return {
    kind,
    expected_sha: typeof details?.expected_sha === 'string' ? details.expected_sha : null,
    actual_sha: typeof details?.actual_sha === 'string' ? details.actual_sha : null,
    paths: Array.isArray(details?.paths)
      ? (details?.paths as unknown[]).filter((p): p is string => typeof p === 'string')
      : [],
  };
}

/**
 * COS-179: плоские entries бэкенда (`{path, kind}`) → вложенное дерево shell'а.
 * Порядок сортировки гарантирует, что директория появляется раньше детей.
 */
export function buildTree(entries: WorkspaceTreeEntry[]): IDEFileNode[] {
  const root: IDEFileNode[] = [];
  const dirs = new Map<string, IDEFileNode>();
  const sorted = [...entries].sort((a, b) => a.path.localeCompare(b.path));
  for (const entry of sorted) {
    const parts = entry.path.split('/');
    const node: IDEFileNode = {
      name: parts[parts.length - 1] ?? entry.path,
      path: entry.path,
      kind: entry.kind === 'directory' ? 'dir' : 'file',
    };
    if (node.kind === 'dir') dirs.set(entry.path, node);
    const parentPath = parts.slice(0, -1).join('/');
    const parent = parentPath ? dirs.get(parentPath) : undefined;
    if (parent) {
      parent.children = parent.children ?? [];
      parent.children.push(node);
    } else {
      root.push(node);
    }
  }
  return root;
}

function detectLanguage(filePath: string): string {
  if (filePath.endsWith('.yaml') || filePath.endsWith('.yml')) return 'yaml';
  if (filePath.endsWith('.json')) return 'json';
  if (filePath.endsWith('.py')) return 'python';
  if (filePath.endsWith('.ts') || filePath.endsWith('.tsx')) return 'typescript';
  if (filePath.endsWith('.js') || filePath.endsWith('.jsx')) return 'javascript';
  if (filePath.endsWith('.sql')) return 'sql';
  if (filePath.endsWith('.md')) return 'markdown';
  if (filePath.endsWith('.wire') || filePath.endsWith('.pipeline')) return 'yaml';
  return 'plaintext';
}

// ── COS-086: .wire DSL step keywords ─────────────────────────────────

const WIRE_STEP_KEYWORDS = ['navigate', 'fill', 'click', 'assert_url', 'assert_status', 'assert_text', 'wait', 'scroll', 'type', 'select', 'hover', 'double_click', 'drag_and_drop'];

function isWireStepLine(line: string): boolean {
  const trimmed = line.trim();
  if (trimmed.startsWith('//') || trimmed.startsWith('#')) return false;
  const keyword = trimmed.split(/\s+/)[0].toLowerCase();
  return WIRE_STEP_KEYWORDS.includes(keyword) || trimmed.startsWith('navigate') || trimmed.startsWith('fill') ||
    trimmed.startsWith('click') || trimmed.startsWith('assert_') || trimmed.startsWith('wait') || trimmed.startsWith('type') || trimmed.startsWith('select') || trimmed.startsWith('hover') || trimmed.startsWith('scroll') || trimmed.startsWith('double_click') || trimmed.startsWith('drag_and_drop');
}

// ── File Tree Node ────────────────────────────────────────────────────

interface TreeItemProps {
  node: IDEFileNode;
  activePath: string;
  depth?: number;
  onSelectFile: (path: string) => void;
}

function FileTreeNodeItem({ node, activePath, depth = 0, onSelectFile }: TreeItemProps) {
  const [open, setOpen] = useState(depth === 0 || activePath.startsWith(node.path));

  if (node.kind === 'dir') {
    return (
      <div data-testid={`dir-node-${node.path}`}>
        <div
          className="flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-white/5 rounded text-[11px] select-none text-slate-300 font-medium"
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="w-3 text-center text-[10px] text-slate-500">{open ? '▾' : '▸'}</span>
          <span className="text-amber-400">📁</span>
          <span>{node.name}</span>
        </div>
        {open &&
          node.children?.map((child, idx) => (
            <FileTreeNodeItem
              key={idx}
              node={child}
              activePath={activePath}
              depth={depth + 1}
              onSelectFile={onSelectFile}
            />
          ))}
      </div>
    );
  }

  const isSelected = activePath === node.path;
  return (
    <div
      data-testid={`file-node-${node.path}`}
      className={`flex items-center gap-1 px-2 py-1 cursor-pointer rounded text-[11px] select-none transition-colors ${
        isSelected ? 'bg-cyan-500/15 text-cyan-300 font-semibold' : 'hover:bg-white/5 text-slate-400'
      }`}
      style={{ paddingLeft: `${depth * 12 + 16}px` }}
      onClick={() => onSelectFile(node.path)}
    >
      <span className="text-[10px] text-slate-500">{node.path.endsWith('.wire') ? '⚡' : '📄'}</span>
      <span className="truncate">{node.name}</span>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────

export function WebIDEShell({ repo, file, line, commit, onNavigateToStation }: WebIDEProps) {
  const [currentRepo, setCurrentRepo] = useState(repo || DEFAULT_REPO);
  const [currentFile, setCurrentFile] = useState(file || DEFAULT_FILE);
  const [fileTree, setFileTree] = useState<IDEFileNode[]>([]);
  const [code, setCode] = useState('');
  const [originalCode, setOriginalCode] = useState('');
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // ── COS-179: workspace bootstrap (CAS) + ref-снимок из deep-link ──
  /** Immutable snapshot commit из deep-link; задан → read-only ref-режим. */
  const snapshotRef = commit;
  const [workspace, setWorkspace] = useState<WorkspaceBootstrap | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [fileBlobSha, setFileBlobSha] = useState<string | null>(null);
  // COS-191: источник текущего контента (repo / локальный / серверный черновик).
  const [contentSource, setContentSource] = useState<'repo' | 'local' | 'server'>('repo');
  /** Repo-версия открытого файла (baseline для честной индикации черновиков). */
  const [repoContent, setRepoContent] = useState('');

  // COS-086: Monaco editor reference for gutter decorations
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const decorationsRef = useRef<string[]>([]);
  const [runningStep, setRunningStep] = useState<number | null>(null);
  // COS-182: клик по глифу ▶ → честный draft-save (ref, чтобы не терять свежий closure).
  const handleRunStepRef = useRef<(lineNumber: number) => void>(() => {});

  // Dialogs
  const [commitModalOpen, setCommitModalOpen] = useState(false);
  const [commitMessage, setCommitMessage] = useState('');
  const [commitBranch, setCommitBranch] = useState('main');
  const [committing, setCommitting] = useState(false);
  // COS-186: typed 409 WORKSPACE_CONFLICT из commit-пути (kind-aware UX).
  const [commitConflict, setCommitConflict] = useState<WorkspaceConflictDetails | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Terminal state
  const [termLogs, setTermLogs] = useState<string[]>([
    'Cosmoport Web IDE runtime ready.',
    `Connected to repository: ${currentRepo}`,
  ]);

  const isDirty = useMemo(() => code !== originalCode, [code, originalCode]);

  // ── COS-086: Apply Gutter Run + Diff decorations ────────────────────

  const applyGutterDecorations = useCallback(
    (ed: editor.IStandaloneCodeEditor | null, current: string, original: string, filePath: string, running: number | null) => {
      if (!ed) return;

      const model = ed.getModel();
      if (!model) return;

      const newDecorations: editor.IModelDeltaDecoration[] = [];
      const isWire = filePath.endsWith('.wire');
      const lines = current.split('\n');
      const origLines = original.split('\n');

      for (let i = 0; i < lines.length; i++) {
        const lineNum = i + 1;
        const isChanged = i < origLines.length ? lines[i] !== origLines[i] : true;

        // COS-086: Gutter [▶] run icon for .wire step lines
        if (isWire && isWireStepLine(lines[i])) {
          const isRunning = running === lineNum;
          newDecorations.push({
            range: { startLineNumber: lineNum, startColumn: 0, endLineNumber: lineNum, endColumn: 0 },
            options: {
              isWholeLine: false,
              glyphMarginClassName: isRunning ? 'cosmo-gutter-run-spinner' : 'cosmo-gutter-run-icon',
              glyphMarginHoverMessage: {
                value: isRunning
                  ? '⏳ Сохраняем черновик…'
                  : `▶ Шаг: ${lines[i].substring(0, 60)} (runner .wire не подключён — сохранит черновик)`,
              },
              overviewRuler: isRunning ? { color: '#06B6D4', position: RULER_LEFT } : undefined,
            },
          });
        }

        // COS-086: Unsaved line diff indicators (red for changed, amber for new)
        if (isChanged) {
          newDecorations.push({
            range: { startLineNumber: lineNum, startColumn: 1, endLineNumber: lineNum, endColumn: 1 },
            options: {
              isWholeLine: true,
              className: i >= origLines.length ? 'cosmo-line-added' : 'cosmo-line-changed',
              overviewRuler: {
                color: i >= origLines.length ? '#F59E0B' : '#EF4444',
                position: RULER_RIGHT,
              },
            },
          });
        }
      }

      decorationsRef.current = ed.deltaDecorations(decorationsRef.current, newDecorations);
    },
    []
  );

  // ── COS-086 / COS-100: Editor Mount ──────────────────────────────────

  const handleEditorMount: OnMount = useCallback((editorInstance) => {
    editorRef.current = editorInstance;
    applyGutterDecorations(editorInstance, code, originalCode, currentFile, runningStep);

    // COS-182: клик по глиф-маргину ▶ (wire) → честный draft-save
    // (серверного runner'а .wire нет; мёртвый PUT /repos/file не зовём).
    editorInstance.onMouseDown((e) => {
      if (e.target.type === GUTTER_GLYPH_MARGIN && e.target.position) {
        handleRunStepRef.current(e.target.position.lineNumber);
      }
    });

    // COS-100: Deep-link line jump
    if (line && line > 0) {
      editorInstance.revealLineInCenter(line);
      editorInstance.setPosition({ lineNumber: line, column: 1 });
    }
  }, [code, originalCode, currentFile, runningStep, line, applyGutterDecorations]);

  // Reapply decorations when code/state changes
  useEffect(() => {
    if (editorRef.current) {
      applyGutterDecorations(editorRef.current, code, originalCode, currentFile, runningStep);
    }
  }, [code, originalCode, currentFile, runningStep, applyGutterDecorations]);

  // ── COS-086: Run single .wire step ──────────────────────────────────

  /**
   * COS-182: gutter-«run» больше не врёт. Серверного runner'а .wire в Airlock
   * нет (PTY epic — кандидат, не нарезан), поэтому клик по глифу честно
   * сохраняет серверный черновик файла и явно сообщает, что шаг не исполнен.
   */
  const handleRunStep = async (lineNumber: number) => {
    if (!currentFile.endsWith('.wire')) return;
    if (snapshotRef) {
      setStatusMessage('Snapshot-режим (commit) — только чтение');
      setTimeout(() => setStatusMessage(null), 3000);
      return;
    }
    if (!workspace) {
      setStatusMessage('Нет workspace-сессии — сохранение недоступно');
      setTimeout(() => setStatusMessage(null), 3000);
      return;
    }
    const lineText = code.split('\n')[lineNumber - 1];
    if (!lineText) return;

    setRunningStep(lineNumber);
    setTermLogs((prev) => [...prev, `[RUNNER] ▶ Шаг L${lineNumber}: ${lineText.trim().substring(0, 60)}`]);

    try {
      await api.saveWorkspaceDraft({
        repo: currentRepo,
        branch: workspace.branch,
        path: currentFile,
        content: code,
        ...(fileBlobSha ? { baseBlobSha: fileBlobSha } : {}),
      });
      setTermLogs((prev) => [
        ...prev,
        '[RUNNER] Шаг не исполнен: серверный runner .wire в Airlock не подключён (PTY epic в бэклоге)',
        `[INFO] Черновик ${currentFile} сохранён на сервере`,
      ]);
      setStatusMessage('Шаг не исполнен (runner недоступен) — черновик сохранён');
      setTimeout(() => setStatusMessage(null), 4000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'draft save failed';
      setTermLogs((prev) => [...prev, `[ERROR] draft save L${lineNumber}: ${msg}`]);
      setStatusMessage(`Не сохранено: ${msg}`);
      setTimeout(() => setStatusMessage(null), 4000);
    } finally {
      setTimeout(() => setRunningStep(null), 800);
    }
  };
  handleRunStepRef.current = handleRunStep;

  // ── COS-086: ⌘D / Ctrl+D Diff toggle ───────────────────────────────

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'd') {
        e.preventDefault();
        setIsDiffMode((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // ── API helpers (COS-179: bootstrap → CAS-пара; ref — snapshot) ────

  const ensureWorkspace = useCallback(async (): Promise<WorkspaceBootstrap> => {
    const ws = await api.openWorkspace(currentRepo);
    setWorkspace(ws);
    setCommitBranch(ws.branch);
    return ws;
  }, [currentRepo]);

  const fetchTree = useCallback(async () => {
    try {
      if (snapshotRef) {
        // FR-004: ref — authority; CAS-пара не нужна (BE игнорирует branch/head_sha).
        const res = await api.getRepoTree(currentRepo, { ref: snapshotRef });
        setTreeError(null);
        setFileTree(buildTree(res.entries));
        return;
      }
      const ws = await ensureWorkspace();
      const res = await api.getRepoTree(currentRepo, { branch: ws.branch, headSha: ws.headSha });
      setTreeError(null);
      setFileTree(buildTree(res.entries));
    } catch (err) {
      // Честная деградация: видимая ошибка вместо молча пустого дерева.
      setTreeError(err instanceof Error ? err.message : 'не удалось загрузить дерево');
      setFileTree([]);
      // Bootstrap не удался — не держим вечный спиннер (файл не загрузится).
      setLoading(false);
    }
  }, [currentRepo, snapshotRef, ensureWorkspace]);

  const loadFileContent = useCallback(async (filePath: string) => {
    if (!snapshotRef && !workspace) {
      // Ждём bootstrap: файл загрузится, когда workspace приедет (deps ниже).
      return;
    }
    setLoading(true);
    try {
      const blob = snapshotRef
        ? await api.getRepoFile(currentRepo, filePath, { ref: snapshotRef })
        : await api.getRepoFile(currentRepo, filePath, {
            branch: workspace?.branch,
            headSha: workspace?.headSha,
          });
      setFileBlobSha(blob.sha || blob.baseBlobSha || null);
      setOriginalCode(blob.content);
      setRepoContent(blob.content);
      setCurrentFile(filePath);

      // COS-100: Auto-restore local draft if one exists
      let initialContent = blob.content;
      let source: 'repo' | 'local' | 'server' = 'repo';
      try {
        const savedDraft = globalThis.localStorage?.getItem(getDraftKey(currentRepo, filePath));
        if (savedDraft !== null && savedDraft !== blob.content) {
          initialContent = savedDraft;
          source = 'local';
          setStatusMessage('Восстановлен локальный черновик');
          setTimeout(() => setStatusMessage(null), 3000);
        }
      } catch { /* no localStorage */ }

      // COS-191: server draft (COS-110) — восстановление после reload;
      // 404/503 (нет черновика / Valkey недоступен) — тихо к repo-версии.
      if (source === 'repo' && !snapshotRef && workspace) {
        try {
          const serverDraft = await api.getWorkspaceDraft(currentRepo, workspace.branch, filePath);
          if (serverDraft?.content && serverDraft.content !== blob.content) {
            initialContent = serverDraft.content;
            source = 'server';
            setStatusMessage('Восстановлен серверный черновик');
            setTimeout(() => setStatusMessage(null), 3000);
          }
        } catch { /* тихо: не ошибка (COS-191 scope 3) */ }
      }

      setCode(initialContent);
      setContentSource(source);
      setTermLogs((prev) => [...prev, `[INFO] Loaded file: ${filePath} (${blob.content.length} bytes)`]);
    } catch (err) {
      // COS-179: fallback-контент + видимая ошибка (не молчаливая подмена).
      const msg = err instanceof Error ? err.message : 'файл не загружен';
      setFileBlobSha(null);
      const fallback = `// ${filePath} in ${currentRepo}\n// Cosmoport Pipeline & Wire Scenario\n`;
      setOriginalCode(fallback);
      setCurrentFile(filePath);

      let initialContent = fallback;
      try {
        const savedDraft = globalThis.localStorage?.getItem(getDraftKey(currentRepo, filePath));
        if (savedDraft !== null) {
          initialContent = savedDraft;
        }
      } catch { /* no localStorage */ }
      setCode(initialContent);
      setStatusMessage(`Не удалось загрузить ${filePath}: ${msg}`);
      setTermLogs((prev) => [...prev, `[ERROR] load ${filePath}: ${msg}`]);
      setContentSource('repo');
      setRepoContent('');
    } finally {
      setLoading(false);
    }
  }, [currentRepo, snapshotRef, workspace]);

  // COS-100: Auto-save draft to localStorage (session persistence)
  useEffect(() => {
    if (!currentRepo || !currentFile || loading) return;
    const timer = setTimeout(() => {
      try {
        if (code !== originalCode) {
          globalThis.localStorage?.setItem(getDraftKey(currentRepo, currentFile), code);
        } else {
          globalThis.localStorage?.removeItem(getDraftKey(currentRepo, currentFile));
        }
      } catch { /* no localStorage */ }
    }, 800);
    return () => clearTimeout(timer);
  }, [code, originalCode, currentRepo, currentFile, loading]);

  useEffect(() => {
    if (repo && repo !== currentRepo) setCurrentRepo(repo);
  }, [repo, currentRepo]);

  useEffect(() => {
    if (file && file !== currentFile) setCurrentFile(file);
  }, [file, currentFile]);

  useEffect(() => {
    // COS-179: смена repo/ref → новый bootstrap-цикл (workspace сбрасывается).
    setWorkspace(null);
    setFileBlobSha(null);
    setTreeError(null);
  }, [currentRepo, snapshotRef]);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  useEffect(() => {
    loadFileContent(currentFile);
  }, [currentFile, loadFileContent]);

  const handleSaveFile = useCallback(async () => {
    if (snapshotRef) {
      // FR-004: snapshot read-only by construction — запись не открываем.
      setStatusMessage('Snapshot-режим (commit) — только чтение');
      setTimeout(() => setStatusMessage(null), 3000);
      return;
    }
    if (!workspace) {
      setStatusMessage('Нет workspace-сессии — сохранение недоступно');
      setTimeout(() => setStatusMessage(null), 3000);
      return;
    }
    try {
      // COS-182: канонический save-path — серверный черновик (COS-110),
      // а не мёртвый PUT /repos/file (405).
      const saved = await api.saveWorkspaceDraft({
        repo: currentRepo,
        branch: workspace.branch,
        path: currentFile,
        content: code,
        ...(fileBlobSha ? { baseBlobSha: fileBlobSha } : {}),
      });
      setOriginalCode(saved.content);
      setContentSource('server');
      try {
        globalThis.localStorage?.removeItem(getDraftKey(currentRepo, currentFile));
      } catch { /* no localStorage */ }
      setStatusMessage('Черновик сохранён на сервере');
      setTimeout(() => setStatusMessage(null), 3000);
      setTermLogs((prev) => [...prev, `[INFO] Черновик ${currentFile} сохранён (server draft)`]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка сохранения';
      setStatusMessage(`Не сохранено: ${msg}`);
      setTermLogs((prev) => [...prev, `[ERROR] save ${currentFile}: ${msg}`]);
    }
  }, [currentRepo, currentFile, code, snapshotRef, workspace, fileBlobSha]);

  // COS-100: ⌘S keyboard shortcut for save
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (isDirty && !loading) {
          void handleSaveFile();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isDirty, loading, handleSaveFile]);

  const handleDiscardDraft = () => {
    setCode(originalCode);
    setContentSource('repo');
    try {
      globalThis.localStorage?.removeItem(getDraftKey(currentRepo, currentFile));
    } catch { /* no localStorage */ }
    setStatusMessage('Черновик сброшен к версии с сервера');
    setTimeout(() => setStatusMessage(null), 3000);
    // COS-191: серверный черновик тоже снимаем — иначе reload вернёт его снова.
    if (!snapshotRef && workspace) {
      void api
        .deleteWorkspaceDraft(currentRepo, workspace.branch, currentFile)
        .catch((err: unknown) => {
          setStatusMessage(
            `Локально сброшено, но серверный черновик не удалён: ${
              err instanceof Error ? err.message : String(err)
            }`
          );
        });
    }
  };

  const handleCommitAndPush = async (freshWorkspace?: WorkspaceBootstrap) => {
    if (!commitMessage.trim() || snapshotRef) return;
    const message = commitMessage.trim();
    const wsForCas = freshWorkspace ?? workspace;
    setCommitting(true);
    try {
      // COS-179/186: атомарный commit workspace (COS-124) с typed 409 (COS-181);
      // expectedHeadSha — CAS только при совпадении ветки модалки и workspace.
      const res = await api.commitWorkspace({
        repo: currentRepo,
        branch: commitBranch,
        message,
        changes: [{ path: currentFile, content: code }],
        ...(wsForCas && commitBranch === wsForCas.branch ? { expectedHeadSha: wsForCas.headSha } : {}),
      });
      setCommitConflict(null);
      setOriginalCode(code);
      // COS-191: контент зафиксирован в ветке — источник снова repo.
      setRepoContent(code);
      setContentSource('repo');
      try {
        globalThis.localStorage?.removeItem(getDraftKey(currentRepo, currentFile));
      } catch { /* no localStorage */ }
      setCommitModalOpen(false);
      setCommitMessage('');
      setTermLogs((prev) => [...prev, `[GIT] Committed ${res.sha.slice(0, 8)} to ${commitBranch} ("${message}")`]);
      setStatusMessage(`Запушено: ${res.sha.slice(0, 8)}`);
      setTimeout(() => setStatusMessage(null), 4000);
      // Ветка двинулась: re-bootstrap обновит head/blob sha (файл перечитается).
      void fetchTree();
    } catch (err) {
      if (err instanceof CosmoApiError && err.code === 'WORKSPACE_CONFLICT') {
        // COS-186: machine-readable конфликт → понятный UX (без сырого detail).
        const conflict = toWorkspaceConflict(err.details);
        setCommitConflict(conflict);
        setStatusMessage(describeWorkspaceConflict(conflict));
      } else {
        setStatusMessage(err instanceof Error ? err.message : 'Ошибка коммита');
      }
    } finally {
      setCommitting(false);
    }
  };

  /** COS-186: re-bootstrap workspace; для `concurrent` — сразу повтор коммита. */
  const handleRefreshWorkspace = async () => {
    const retry = commitConflict?.kind === 'concurrent';
    setCommitConflict(null);
    try {
      const ws = await ensureWorkspace();
      await fetchTree();
      if (retry && commitMessage.trim()) {
        await handleCommitAndPush(ws);
      } else {
        setStatusMessage('Workspace обновлён');
        setTimeout(() => setStatusMessage(null), 3000);
      }
    } catch (err) {
      setStatusMessage(
        `Не удалось обновить workspace: ${err instanceof Error ? err.message : String(err)}`
      );
    }
  };

  const handleCommitAndRun = async () => {
    setCommitting(true);
    try {
      const res = await api.commitAndRun({
        repo: currentRepo,
        branch: commitBranch,
        message: `IDE Commit & Run: ${currentFile}`,
        plan_id: '',
        project_id: currentRepo.split('/')[0] || '',
        files: [{ path: currentFile, content: code }],
      });
      setOriginalCode(code);
      try {
        globalThis.localStorage?.removeItem(getDraftKey(currentRepo, currentFile));
      } catch { /* no localStorage */ }
      setTermLogs((prev) => [...prev, `[PIPELINE] Commit ${res.commit_hash} -> Triggered Run #${res.run_id}`]);
      if (onNavigateToStation) {
        onNavigateToStation({ view: 'runs', run_id: res.run_id });
      }
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'Ошибка запуска прогона');
    } finally {
      setCommitting(false);
    }
  };

  const currentLanguage = detectLanguage(currentFile);

  return (
    <div className="cosmo-ide-root flex flex-col h-screen text-slate-200" style={{ background: '#0A0E1A' }} data-testid="web-ide-shell">
      {/* Top Application Bar */}
      <div className="flex items-center gap-2 px-3 h-10 shrink-0 border-b border-slate-800" style={{ background: '#0D121F' }}>
        <div className="flex items-center gap-1.5 font-mono">
          <span className="text-[11px] font-semibold text-cyan-400 font-mono">IDE</span>
          <span className="text-[12px] font-bold text-slate-200">Cosmoport</span>
          <span className="text-slate-600">/</span>
          <select
            data-testid="repo-select"
            value={currentRepo}
            onChange={(e) => {
              const r = e.target.value;
              setCurrentRepo(r);
              setCurrentFile(DEFAULT_FILE);
            }}
            className="bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-cyan-300 font-mono font-semibold outline-none hover:border-cyan-500 cursor-pointer"
          >
            <option value="payments/api">payments/api</option>
            <option value="cbr/wallet-api">cbr/wallet-api</option>
            {!['payments/api', 'cbr/wallet-api'].includes(currentRepo) && (
              <option value={currentRepo}>{currentRepo}</option>
            )}
          </select>
        </div>

        <div className="h-4 w-px bg-slate-800 mx-1" />

        <span className="text-[11px] text-slate-400 font-mono flex items-center gap-1" data-testid="current-file-badge">
          <span>{currentFile}</span>
          {isDirty && <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" title="Несохранённые изменения (черновик)" />}
          {line && <span className="text-slate-500">:{line}</span>}
        </span>

        {/* COS-191: честная индикация источника контента (server WIP / local draft). */}
        {(contentSource === 'local' || (contentSource === 'server' && code !== repoContent)) && (
          <span
            data-testid="content-source-badge"
            title={
              contentSource === 'server'
                ? 'Серверный черновик (COS-110, не закоммичен) — сохранён на сервере, переживает reload'
                : 'Локальный черновик — ещё не сохранён на сервере'
            }
            className={
              contentSource === 'server'
                ? 'px-1.5 py-0.5 rounded text-[9px] font-mono border bg-cyan-500/15 text-cyan-300 border-cyan-500/40'
                : 'px-1.5 py-0.5 rounded text-[9px] font-mono border bg-amber-500/15 text-amber-300 border-amber-500/40'
            }
          >
            {contentSource === 'server' ? 'server WIP' : 'local draft'}
          </span>
        )}

        {snapshotRef && (
          <span
            data-testid="snapshot-badge"
            title="Immutable snapshot из deep-link (FR-004): чтение зафиксированной ревизии, запись закрыта"
            className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/40"
          >
            snapshot {snapshotRef.slice(0, 7)}
          </span>
        )}

        <div className="flex-1" />

        {statusMessage && (
          <span data-testid="status-message" className="text-[11px] text-emerald-400 font-mono bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
            {statusMessage}
          </span>
        )}

        {/* COS-086: Diff Mode Toggle with ⌘D hint */}
        <button
          data-testid="diff-btn"
          onClick={() => setIsDiffMode((v) => !v)}
          className={`px-2.5 py-1 text-[10px] rounded font-semibold transition-colors border ${
            isDiffMode
              ? 'bg-purple-500/20 text-purple-300 border-purple-500/40'
              : 'bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700'
          }`}
          title={isDiffMode ? 'Закрыть Diff View (⌘D)' : 'Сравнить изменения (⌘D)'}
        >
          {isDiffMode ? '✓ Diff View' : 'Diff (⌘D)'}
        </button>

        <button
          data-testid="save-btn"
          onClick={handleSaveFile}
          disabled={!isDirty || loading || !!snapshotRef}
          title={snapshotRef ? 'Snapshot-режим: только чтение' : undefined}
          className="px-2.5 py-1 text-[10px] rounded font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Сохранить (⌘S)
        </button>

        {isDirty && (
          <button
            data-testid="discard-draft-btn"
            onClick={handleDiscardDraft}
            className="px-2 py-1 text-[10px] rounded font-semibold bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 transition-colors"
            title="Сбросить изменения к версии с сервера"
          >
            Сбросить
          </button>
        )}

        <button
          data-testid="commit-btn"
          onClick={() => { setCommitConflict(null); setCommitModalOpen(true); }}
          disabled={!!snapshotRef}
          title={snapshotRef ? 'Snapshot-режим: только чтение' : undefined}
          className="px-2.5 py-1 text-[10px] rounded font-semibold bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Commit & Push
        </button>

        <button
          data-testid="commit-run-btn"
          onClick={handleCommitAndRun}
          disabled={committing || !!snapshotRef}
          title={snapshotRef ? 'Snapshot-режим: только чтение' : undefined}
          className="px-3 py-1 text-[10px] rounded font-bold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5 transition-colors shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <span>▶</span>
          <span>{committing ? 'Запуск...' : 'Commit & Run'}</span>
        </button>

        <div className="h-4 w-px bg-slate-800 mx-1" />

        {onNavigateToStation && (
          <button
            data-testid="back-station-btn"
            onClick={() => onNavigateToStation({ view: 'domains' })}
            className="px-2 py-1 text-[10px] text-slate-400 hover:text-slate-200 hover:bg-white/5 rounded"
            title="Вернуться в Control Station"
          >
            ← Station
          </button>
        )}

        <button
          onClick={() => setPaletteOpen(true)}
          className="px-2 py-1 text-[10px] text-slate-400 hover:text-slate-200 hover:bg-white/5 rounded font-mono"
        >
          ⌘K
        </button>
      </div>

      {/* Main Workspace (Sidebar + Editor + Terminal) */}
      <div className="flex-1 flex min-h-0">
        {/* File Explorer Sidebar */}
        <div className="w-56 shrink-0 border-r border-slate-800/80 flex flex-col" style={{ background: '#0D121F' }} data-testid="file-tree">
          <div className="px-3 py-2 border-b border-slate-800 text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
            <span>Файлы проекта</span>
            <button data-testid="refresh-tree-btn" onClick={fetchTree} title="Обновить дерево" className="hover:text-white">↻</button>
          </div>
          <div className="flex-1 overflow-y-auto py-1.5">
            {treeError ? (
              <div data-testid="tree-error" className="px-3 py-2 text-[10px] text-red-300/90 font-mono leading-snug">
                Дерево не загружено: {treeError}
              </div>
            ) : fileTree.length === 0 ? (
              <div data-testid="tree-empty" className="px-3 py-2 text-[10px] text-slate-500 font-mono">
                Файлы не найдены
              </div>
            ) : (
              fileTree.map((node, idx) => (
                <FileTreeNodeItem
                  key={idx}
                  node={node}
                  activePath={currentFile}
                  onSelectFile={loadFileContent}
                />
              ))
            )}
          </div>
        </div>

        {/* Central Editor / Diff Area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Active File Tab Bar */}
          <div className="flex items-center h-7 px-3 bg-slate-900 border-b border-slate-800 text-[11px] font-mono gap-2" data-testid="active-file-tab">
            <span className="text-cyan-400 font-semibold">{currentFile.split('/').pop()}</span>
            <span className="text-slate-600 text-[10px]">({currentLanguage})</span>
            {isDirty && <span className="text-amber-400 text-[9px] font-sans">● Не сохранено</span>}
            {currentFile.endsWith('.wire') && (
              <span className="text-amber-400/90 text-[9px] font-sans ml-auto" title="Runner .wire в Airlock не подключён (PTY epic в бэклоге): клик по ▶ сохранит серверный черновик">
                ▶ Gutter: draft save (runner не подключён)
              </span>
            )}
          </div>

          {/* COS-086: Monaco Editor / Monaco Diff Editor with gutter icons */}
          <div className="flex-1 relative">
            {loading ? (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-950/60 text-slate-400 font-mono text-xs">
                Загрузка файла...
              </div>
            ) : isDiffMode ? (
              <DiffEditor
                height="100%"
                language={currentLanguage}
                original={originalCode}
                modified={code}
                theme="vs-dark"
                options={{
                  fontSize: 13,
                  fontFamily: '"JetBrains Mono", monospace',
                  minimap: { enabled: false },
                  lineNumbers: 'on',
                  readOnly: false,
                  renderSideBySide: true,
                }}
              />
            ) : (
              <Editor
                height="100%"
                language={currentLanguage}
                value={code}
                onChange={(v) => setCode(v ?? '')}
                onMount={handleEditorMount}
                theme="vs-dark"
                options={{
                  fontSize: 13,
                  fontFamily: '"JetBrains Mono", monospace',
                  minimap: { enabled: true, showSlider: 'mouseover', scale: 1, maxColumn: 80 },
                  lineNumbers: 'on',
                  padding: { top: 8 },
                  glyphMargin: currentFile.endsWith('.wire'),
                }}
              />
            )}
          </div>

          {/* Terminal & Output Drawer */}
          <div className="h-36 shrink-0 border-t border-slate-800 flex flex-col" style={{ background: '#090D16' }}>
            <div className="px-3 py-1 bg-slate-900/60 border-b border-slate-800/80 flex items-center justify-between text-[10px] text-slate-400 font-mono">
              <span className="font-semibold text-slate-300">Terminal & Pipeline Logs</span>
              <button onClick={() => setTermLogs([])} className="hover:text-slate-200 text-[9px]">
                Clear
              </button>
            </div>
            <div className="flex-1 p-2 overflow-y-auto font-mono text-[11px] text-slate-300 space-y-0.5">
              {termLogs.map((log, idx) => (
                <div
                  key={idx}
                  className={
                    log.startsWith('[SUCCESS]') || log.startsWith('✅')
                      ? 'text-emerald-400'
                      : log.startsWith('[PIPELINE]')
                      ? 'text-cyan-400'
                      : log.startsWith('[GIT]')
                      ? 'text-amber-300'
                      : log.startsWith('[RUNNER]')
                      ? 'text-cyan-300'
                      : log.startsWith('[ERROR]') || log.startsWith('❌')
                      ? 'text-red-400'
                      : 'text-slate-400'
                  }
                >
                  {log}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Commit & Push Modal */}
      {commitModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setCommitModalOpen(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-[500px] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-100">Commit & Push изменения</h3>
              <button onClick={() => setCommitModalOpen(false)} className="text-slate-500 hover:text-white">✕</button>
            </div>
            <div className="p-4 space-y-3">
              <div>
                <label className="text-[11px] font-semibold text-slate-400 block mb-1">Репозиторий и ветка:</label>
                <div className="flex gap-2">
                  <input
                    disabled
                    value={currentRepo}
                    className="flex-1 bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-400 font-mono outline-none"
                  />
                  <input
                    value={commitBranch}
                    onChange={(e) => setCommitBranch(e.target.value)}
                    className="w-28 bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none focus:border-cyan-500"
                    placeholder="branch"
                  />
                </div>
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-400 block mb-1">Изменённый файл:</label>
                <div className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-cyan-400 font-mono">
                  {currentFile} {isDirty && <span className="text-amber-400 ml-1">● modified</span>}
                </div>
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-400 block mb-1">Сообщение коммита:</label>
                <textarea
                  autoFocus
                  rows={3}
                  value={commitMessage}
                  onChange={(e) => setCommitMessage(e.target.value)}
                  placeholder="feat(auth): update wire scenario assertions"
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-xs text-slate-200 outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              {commitConflict && (
                <div
                  data-testid="commit-conflict"
                  className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 space-y-1.5"
                >
                  <div className="text-[11px] font-semibold text-amber-300">
                    {commitConflict.kind === 'concurrent'
                      ? 'Конфликт: ветка ушла вперёд'
                      : 'Конфликт состояния файла'}
                  </div>
                  <div className="text-[10px] text-amber-200/90 font-mono">
                    {describeWorkspaceConflict(commitConflict)}
                  </div>
                  {commitConflict.paths.length > 0 && (
                    <div className="text-[10px] text-amber-200/80 font-mono">
                      Файлы: {commitConflict.paths.join(', ')}
                    </div>
                  )}
                  <button
                    data-testid="commit-refresh-btn"
                    onClick={handleRefreshWorkspace}
                    className="px-2.5 py-1 text-[10px] font-semibold rounded bg-amber-500/20 text-amber-200 border border-amber-500/40 hover:bg-amber-500/30"
                  >
                    {commitConflict.kind === 'concurrent'
                      ? 'Обновить workspace и повторить'
                      : 'Обновить workspace'}
                  </button>
                </div>
              )}
            </div>
            <div className="px-4 py-3 bg-slate-950 border-t border-slate-800 flex justify-end gap-2">
              <button onClick={() => setCommitModalOpen(false)} className="px-3 py-1.5 text-xs text-slate-400 hover:text-white">
                Отмена
              </button>
              <button
                onClick={() => { void handleCommitAndPush(); }}
                disabled={committing || !commitMessage.trim()}
                className="px-4 py-1.5 text-xs font-bold rounded bg-cyan-500 hover:bg-cyan-400 text-slate-950 disabled:opacity-40"
              >
                {committing ? 'Запушивание...' : 'Запушить в репозиторий'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Command Palette (⌘K) */}
      {paletteOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/60" onClick={() => setPaletteOpen(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-[480px] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 px-3 h-10 border-b border-slate-700 bg-slate-950">
              <span className="text-[10px] text-cyan-400 font-mono">⌘K</span>
              <input
                autoFocus
                className="flex-1 bg-transparent border-0 outline-none text-xs text-slate-200"
                placeholder="Поиск команд (Save, Diff, Commit, Run)..."
              />
            </div>
            <div className="p-1 space-y-0.5 text-xs">
              <div onClick={() => { handleSaveFile(); setPaletteOpen(false); }} className="px-3 py-1.5 rounded text-slate-300 hover:bg-white/5 cursor-pointer flex justify-between">
                <span>Сохранить файл</span>
                <span className="text-slate-500 font-mono text-[10px]">⌘S</span>
              </div>
              <div onClick={() => { setIsDiffMode((v) => !v); setPaletteOpen(false); }} className="px-3 py-1.5 rounded text-slate-300 hover:bg-white/5 cursor-pointer flex justify-between">
                <span>Переключить Diff Viewer</span>
                <span className="text-slate-500 font-mono text-[10px]">⌘D</span>
              </div>
              <div onClick={() => { setCommitConflict(null); setCommitModalOpen(true); setPaletteOpen(false); }} className="px-3 py-1.5 rounded text-slate-300 hover:bg-white/5 cursor-pointer flex justify-between">
                <span>Commit & Push изменения</span>
                <span className="text-slate-500 font-mono text-[10px]">Git</span>
              </div>
              <div onClick={() => { handleCommitAndRun(); setPaletteOpen(false); }} className="px-3 py-1.5 rounded text-emerald-400 hover:bg-white/5 cursor-pointer flex justify-between font-semibold">
                <span>Commit & Run (Запустить в Control Station)</span>
                <span className="text-emerald-500 font-mono text-[10px]">▶</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* COS-086: Custom CSS for gutter icons and diff indicators */}
      <style>{`
        .cosmo-gutter-run-icon {
          width: 14px !important;
          height: 14px !important;
          margin-left: 4px;
          background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14'%3E%3Cpolygon points='2,0 2,14 12,7' fill='%2338BDF8' opacity='0.7'/%3E%3C/svg%3E") center/contain no-repeat;
          cursor: pointer;
          transition: opacity 0.15s;
        }
        .cosmo-gutter-run-icon:hover {
          opacity: 1 !important;
          transform: scale(1.15);
        }
        .cosmo-gutter-run-spinner {
          width: 12px !important;
          height: 12px !important;
          margin-left: 4px;
          border: 2px solid rgba(6,182,212,0.3);
          border-top: 2px solid #06B6D4;
          border-radius: 50%;
          animation: cosmo-spin 0.8s linear infinite;
        }
        @keyframes cosmo-spin {
          to { transform: rotate(360deg); }
        }
        .cosmo-line-changed {
          background: rgba(239,68,68,0.08);
          border-left: 3px solid rgba(239,68,68,0.5);
        }
        .cosmo-line-added {
          background: rgba(245,158,11,0.06);
          border-left: 3px solid rgba(245,158,11,0.4);
        }
      `}</style>
    </div>
  );
}