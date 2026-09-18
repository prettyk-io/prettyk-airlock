# PROGRESS — текущее состояние репозитория

> **Зачем:** worker начинает КАЖДУЮ сессию с чтения этого файла + `git log --oneline -10`.
> Без этого worker тратит контекст на угадывание состояния.
> **Формат:** факты, не проза. Последние действия вверху.
> **Пишет:** Cosmo или worker по факту завершения сессии.
> **Правило:** worker читает это ПЕРВЫМ действием после `pwd`.

## Последнее действие
2026-09-18 | Boss | COS-133 closed: Workspace Run Lifecycle — Detail Sync, Cancel & Rerun API. `GET /workspace/runs/{run_id}` (шаги `WorkspaceRunStepSummary` + sync статуса из Woodpecker для незавершённых), `POST .../cancel` (killed, 400 на терминальном), `POST .../rerun` (новая WorkspaceRunRow с `original_run_id`); адаптер `get_pipeline_detail`/`cancel_pipeline`/`rerun_pipeline`; миграция `f5a6b7c8d9e0` (nullable `original_run_id`, guarded); 35 passed, suite gate 3046/0/17.
2026-09-18 | Flash | COS-131 closed: Web IDE File Operations & Local Dirty Diff Engine — createFile, deleteFile (JSON body), moveFile по контракту COS-120 API; локальный in-memory LCS-diff в ChangeReviewPanel (снято ограничение COS-130); диалоги New File, New Folder (.gitkeep), Rename, Delete с подтверждением; guards (beforeunload, смен ветки и файлов с dirty); 155 passed (10 тестовых файлов, baseline 114, порог ≥130), `tsc -b` 0, vite build green.
2026-09-18 | Luna | COS-132 closed: `POST /workspace/gate-scan` — полный скан дерева репозитория/ветки (resolve_ref → get_tree_by_sha → scan_tree), вердикт PASS/WARN/BLOCK, SARIF 2.1.0 export (`application/sarif+json`), лимит maxFiles→413, ghost/unknown-ref 404; 53 passed, suite gate 3011/0/17.

## Текущее состояние
Репозиторий: `D:\prettyk-airlock` + `D:\prettyk-ide`. Доставлены COS-102..COS-133 (COS-117 blame остаётся blocked до Gitea ≥1.23). Airlock и Web IDE содержат незакоммиченные изменения; чистая точка сохраняется до команды Максима на коммит.
Тестовый базис: 3046 passed / 0 failed / 17 skipped (Cosmo suite gate) + 155/155 passed (Web IDE vitest, `tsc -b` 0, `vite build` green).

**Resolved (COS-133):** детализация запусков с live-sync статуса из Woodpecker, отмена активного пайплайна и перезапуск со связью `original_run_id`.
**Resolved (COS-131):** полный набор файловых операций в проводнике Web IDE (создание, переименование, удаление) + локальный in-memory diff для dirty-файлов до коммита + guards потери данных.
**Resolved (COS-132):** полный аудит безопасности дерева репозитория с экспортом в SARIF 2.1.0.
**Resolved (COS-130):** сквозное сравнение веток работает в UI Web IDE против живого бэкенда.

## Следующие действия — параллельная волна воркеров (~20–24h)
1. **Boss: COS-133 закрыт** — ожидает коммит-батча / следующего диспетча.
2. **Flash: COS-131 закрыт** — ожидает коммит-батча / следующего диспетча.
3. **Luna: COS-132 закрыт** — ожидает коммит-батча / следующего диспетча.

---

## История (последние 5)
- 2026-09-18 | Boss | COS-133: Workspace Run Lifecycle — detail sync/cancel/rerun, original_run_id migration (35 passed, 3046 suite gate) | docs/BACKLOG.md
- 2026-09-18 | Flash | COS-131: Web IDE File Operations & Local Dirty Diff — fileOps dialogs, local LCS diff, dirty guards (155 passed, tsc 0, vite build ok) | docs/BACKLOG.md
- 2026-09-18 | Luna | COS-132: Full repo security scan & SARIF 2.1.0 export — scan_tree, to_sarif, POST /workspace/gate-scan (53 passed, 3011 suite gate) | docs/BACKLOG.md
- 2026-09-18 | Flash | COS-130: Web IDE Live Compare Wire-Up & Tree Status — live client.compare, retry 400/404/413, treeStatus markers (114 passed, tsc 0) | docs/BACKLOG.md
- 2026-09-18 | Boss | COS-129: GiteaForgeAdapter list_commits unification — _fetch_commits + GiteaCommit/dict проекции, shadowing fix (20 passed, 2958 suite gate) | docs/BACKLOG.md
