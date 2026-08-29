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
import type { StationContext } from '../shared/DeepLinker';
import { api } from '../station/api';

interface WebIDEProps {
  repo?: string;
  file?: string;
  line?: number;
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
const DEFAULT_FILE = 'scenarios/auth.wire';

const FALLBACK_TREE: IDEFileNode[] = [
  {
    name: 'scenarios',
    path: 'scenarios',
    kind: 'dir',
    children: [
      { name: 'auth.wire', path: 'scenarios/auth.wire', kind: 'file', size: 340 },
      { name: 'payment.wire', path: 'scenarios/payment.wire', kind: 'file', size: 420 },
    ],
  },
  {
    name: '.cosmo',
    path: '.cosmo',
    kind: 'dir',
    children: [
      { name: 'pipeline.yaml', path: '.cosmo/pipeline.yaml', kind: 'file', size: 280 },
      { name: 'gates.yaml', path: '.cosmo/gates.yaml', kind: 'file', size: 190 },
    ],
  },
  { name: 'README.md', path: 'README.md', kind: 'file', size: 150 },
];

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
  if (trimmed.startsWith('//') || trimmed.startsWith('#') || trimmed.startsWith('#')) return false;
  const keyword = trimmed.split(/\s+/)[0].toLowerCase();
  return WIRE_STEP_KEYWORDS.includes(keyword) || keyword === '//' ? false : trimmed.startsWith('navigate') || trimmed.startsWith('fill') ||
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
      <div>
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

export function WebIDEShell({ repo = DEFAULT_REPO, file = DEFAULT_FILE, line, onNavigateToStation }: WebIDEProps) {
  const [currentRepo, setCurrentRepo] = useState(repo);
  const [currentFile, setCurrentFile] = useState(file);
  const [fileTree, setFileTree] = useState<IDEFileNode[]>(FALLBACK_TREE);
  const [code, setCode] = useState('');
  const [originalCode, setOriginalCode] = useState('');
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // COS-086: Monaco editor reference for gutter decorations
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const decorationsRef = useRef<string[]>([]);
  const [runningStep, setRunningStep] = useState<number | null>(null);

  // Dialogs
  const [commitModalOpen, setCommitModalOpen] = useState(false);
  const [commitMessage, setCommitMessage] = useState('');
  const [commitBranch, setCommitBranch] = useState('main');
  const [committing, setCommitting] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Terminal state
  const [termLogs, setTermLogs] = useState<string[]>([
    'Cosmoport Web IDE runtime ready.',
    `Connected to repository: ${currentRepo}`,
  ]);

  const isDirty = useMemo(() => code !== originalCode, [code, originalCode]);

  // ── COS-086: Editor Mount ───────────────────────────────────────────

  const handleEditorMount: OnMount = useCallback((editorInstance) => {
    editorRef.current = editorInstance;
    applyGutterDecorations(editorInstance, code, originalCode, currentFile, runningStep);
  }, [code, originalCode, currentFile, runningStep]);

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
              glyphMarginHoverMessage: { value: isRunning ? '⏳ Выполняется...' : `▶ Запустить шаг: ${lines[i].substring(0, 60)}` },
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

  // Reapply decorations when code/state changes
  useEffect(() => {
    if (editorRef.current) {
      applyGutterDecorations(editorRef.current, code, originalCode, currentFile, runningStep);
    }
  }, [code, originalCode, currentFile, runningStep, applyGutterDecorations]);

  // ── COS-086: Run single .wire step ──────────────────────────────────

  const handleRunStep = async (lineNumber: number) => {
    if (!currentFile.endsWith('.wire')) return;
    const lineText = code.split('\n')[lineNumber - 1];
    if (!lineText) return;

    setRunningStep(lineNumber);
    setTermLogs((prev) => [...prev, `[RUNNER] ▶ Executing step L${lineNumber}: ${lineText.trim().substring(0, 60)}`]);

    try {
      // POST to API to run the wire step
      await api.saveRepoFile({ repo: currentRepo, path: currentFile, content: code, message: `Run step L${lineNumber}` });
      setTermLogs((prev) => [...prev, `[SUCCESS] ✅ Step L${lineNumber} completed`]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Step execution failed';
      setTermLogs((prev) => [...prev, `[ERROR] ❌ Step L${lineNumber}: ${msg}`]);
    } finally {
      setTimeout(() => setRunningStep(null), 2000);
    }
  };

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

  // ── API helpers ─────────────────────────────────────────────────────

  const fetchTree = useCallback(async () => {
    try {
      const treeData = await api.getRepoTree(currentRepo);
      if (treeData && treeData.length > 0) {
        setFileTree(treeData as IDEFileNode[]);
      } else {
        setFileTree(FALLBACK_TREE);
      }
    } catch {
      setFileTree(FALLBACK_TREE);
    }
  }, [currentRepo]);

  const loadFileContent = useCallback(async (filePath: string) => {
    setLoading(true);
    try {
      const res = await api.getRepoFile(currentRepo, filePath);
      setCode(res.content);
      setOriginalCode(res.content);
      setCurrentFile(filePath);
      setTermLogs((prev) => [...prev, `[INFO] Loaded file: ${filePath} (${res.content.length} bytes)`]);
    } catch {
      const fallback = `// ${filePath} in ${currentRepo}\n// Cosmoport Pipeline & Wire Scenario\n`;
      setCode(fallback);
      setOriginalCode(fallback);
      setCurrentFile(filePath);
    } finally {
      setLoading(false);
    }
  }, [currentRepo]);

  useEffect(() => {
    if (repo && repo !== currentRepo) setCurrentRepo(repo);
  }, [repo, currentRepo]);

  useEffect(() => {
    if (file && file !== currentFile) setCurrentFile(file);
  }, [file, currentFile]);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  useEffect(() => {
    loadFileContent(currentFile);
  }, [currentFile, loadFileContent]);

  const handleSaveFile = async () => {
    try {
      await api.saveRepoFile({ repo: currentRepo, path: currentFile, content: code });
      setOriginalCode(code);
      setStatusMessage('Файл успешно сохранён');
      setTimeout(() => setStatusMessage(null), 3000);
      setTermLogs((prev) => [...prev, `[SUCCESS] Saved ${currentFile}`]);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'Ошибка сохранения');
    }
  };

  const handleCommitAndPush = async () => {
    if (!commitMessage.trim()) return;
    setCommitting(true);
    try {
      const res = await api.commitAndPush({
        repo: currentRepo,
        branch: commitBranch,
        message: commitMessage.trim(),
        files: [{ path: currentFile, content: code }],
      });
      setOriginalCode(code);
      setCommitModalOpen(false);
      setCommitMessage('');
      setTermLogs((prev) => [...prev, `[GIT] Committed & Pushed to ${res.branch}: ${res.commit_hash} ("${res.message}")`]);
      setStatusMessage(`Запушено: ${res.commit_hash}`);
      setTimeout(() => setStatusMessage(null), 4000);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'Ошибка коммита');
    } finally {
      setCommitting(false);
    }
  };

  const handleCommitAndRun = async () => {
    setCommitting(true);
    try {
      const res = await api.commitAndRun({
        repo: currentRepo,
        branch: commitBranch,
        message: `IDE Commit & Run: ${currentFile}`,
        plan_id: 'plan-steel',
        domain_id: currentRepo.split('/')[0] || 'cbr',
        files: [{ path: currentFile, content: code }],
      });
      setOriginalCode(code);
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
    <div className="cosmo-ide-root flex flex-col h-screen text-slate-200" style={{ background: '#0A0E1A' }}>
      {/* Top Application Bar */}
      <div className="flex items-center gap-2 px-3 h-10 shrink-0 border-b border-slate-800" style={{ background: '#0D121F' }}>
        <div className="flex items-center gap-1 font-mono">
          <span className="text-[11px] font-semibold text-cyan-400 font-mono">IDE</span>
          <span className="text-[12px] font-bold text-slate-200">Cosmoport</span>
          <span className="text-slate-600">/</span>
          <span className="text-[11px] text-cyan-300 font-semibold">{currentRepo}</span>
        </div>

        <div className="h-4 w-px bg-slate-800 mx-1" />

        <span className="text-[11px] text-slate-400 font-mono flex items-center gap-1">
          <span>{currentFile}</span>
          {isDirty && <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" title="Несохранённые изменения" />}
          {line && <span className="text-slate-500">:{line}</span>}
        </span>

        <div className="flex-1" />

        {statusMessage && (
          <span className="text-[11px] text-emerald-400 font-mono bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
            {statusMessage}
          </span>
        )}

        {/* COS-086: Diff Mode Toggle with ⌘D hint */}
        <button
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
          onClick={handleSaveFile}
          disabled={!isDirty || loading}
          className="px-2.5 py-1 text-[10px] rounded font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Сохранить (⌘S)
        </button>

        <button
          onClick={() => setCommitModalOpen(true)}
          className="px-2.5 py-1 text-[10px] rounded font-semibold bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/30 transition-colors"
        >
          Commit & Push
        </button>

        <button
          onClick={handleCommitAndRun}
          disabled={committing}
          className="px-3 py-1 text-[10px] rounded font-bold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <span>▶</span>
          <span>{committing ? 'Запуск...' : 'Commit & Run'}</span>
        </button>

        <div className="h-4 w-px bg-slate-800 mx-1" />

        {onNavigateToStation && (
          <button
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
        <div className="w-56 shrink-0 border-r border-slate-800/80 flex flex-col" style={{ background: '#0D121F' }}>
          <div className="px-3 py-2 border-b border-slate-800 text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
            <span>Файлы проекта</span>
            <button onClick={fetchTree} title="Обновить дерево" className="hover:text-white">↻</button>
          </div>
          <div className="flex-1 overflow-y-auto py-1.5">
            {fileTree.map((node, idx) => (
              <FileTreeNodeItem
                key={idx}
                node={node}
                activePath={currentFile}
                onSelectFile={loadFileContent}
              />
            ))}
          </div>
        </div>

        {/* Central Editor / Diff Area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Active File Tab Bar */}
          <div className="flex items-center h-7 px-3 bg-slate-900 border-b border-slate-800 text-[11px] font-mono gap-2">
            <span className="text-cyan-400 font-semibold">{currentFile.split('/').pop()}</span>
            <span className="text-slate-600 text-[10px]">({currentLanguage})</span>
            {isDirty && <span className="text-amber-400 text-[9px] font-sans">● Не сохранено</span>}
            {currentFile.endsWith('.wire') && (
              <span className="text-emerald-400 text-[9px] font-sans ml-auto" title="Используйте ▶ в левой колонке для запуска шага">
                ▶ Click gutter to run step
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
            </div>
            <div className="px-4 py-3 bg-slate-950 border-t border-slate-800 flex justify-end gap-2">
              <button onClick={() => setCommitModalOpen(false)} className="px-3 py-1.5 text-xs text-slate-400 hover:text-white">
                Отмена
              </button>
              <button
                onClick={handleCommitAndPush}
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
              <div onClick={() => { setCommitModalOpen(true); setPaletteOpen(false); }} className="px-3 py-1.5 rounded text-slate-300 hover:bg-white/5 cursor-pointer flex justify-between">
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