# COS-107 Acceptance — Workspace Commit (2026-09-05)

**Выполнил:** Boss  ·  **Итог:** PASS  ·  **Зелёные тесты:** 16/16  ·  **Suite gate:** 2586/0  ·  **Live smoke:** 201 + commitSha/treeSha

## Что сделано

| # | Компонент | Файл | Статус |
|---|---|---|---|
| 1 | DTO: `WorkspaceCommitRequest`, `WorkspaceCommitResponse`, `FileChange` | `domain/workspace.py` | COS-102 ✅ |
| 2 | CAS guard: `expected_head_sha` + per-file `base_blob_sha` | `routes/workspace.py:291-354` | ✅ |
| 3 | Маршрут `POST /workspace/commit` | `routes/workspace.py:266-380` | ✅ |
| 4 | Адаптер `create_commit` через Contents API | `adapters/forge_gitea.py:455-520` | ✅ |
| 5 | `_put` метод (соседний с `_post`/`_patch`/`_delete`) | `adapters/forge_gitea.py:147-149` | ✅ |
| 6 | `_username`/`_password` атрибуты в `__init__` | `adapters/forge_gitea.py:96-97` | ✅ |
| 7 | Audit-трейл: `cosmo_audit_events` | `routes/workspace.py:368-380` | ✅ |
| 8 | Тесты: DTO unit (8) + route mock (8) | `test_workspace_commit.py` | 16/16 ✅ |
| 9 | Live smoke (через ПУ → живой Gitea) | `cos107_smoke.py` | 201 ✅ |
| 10 | Suite gate полный прогон | `suite_gate.ps1` | 2586/0 PASS |

## Ключевые решения

### Contents API вместо Tree API
Gitea 1.22.6 **не поддерживает** POST `/api/v1/repos/{o}/{r}/git/trees` (404). Вместо этого:

- **POST** `/contents/{path}` — новый файл (без `sha`)
- **PUT** `/contents/{path}` — обновление существующего (требует `sha`: file blob sha)
- **DELETE** `/contents/{path}` — удаление (требует `sha`)

Множественные файлы → столько же отдельных коммитов (ограничение Contents API). Итоговый SHA коммита снимается `get_commit(owner, repo, branch)` после всех операций.

### CAS (Compare-And-Swap)
- `expected_head_sha` сверяется с HEAD ветки до изменений → 409 конфликт, если ветка ушла
- `base_blob_sha` сверяется с текущим blob sha каждого файла → 409 на конкретном пути
- Поддержка сокращённых SHA (первые 7+ hex-символов)
- Delete без base_blob_sha — идемпотентен (отсутствующий файл молча пропускается)

### Idempotent delete
Если файла нет на ветке (delete уже применён или файл никогда не существовал) — delete пропускается без ошибки. При этом если **все** changes — пустые delete → 400 "no file changes to commit".

## Что исправлено в процессе

1. **forge_gitea.py восстановлен через `git checkout`** после серии неудачных скриптовых правок предыдущей сессии
2. **3 точечных Edit'а** (не скрипты!) — `_put`, `_username`/`_password`, `create_commit`
3. **test_delete_action_honors_base_tree** — добавлен `file_sha_map` в FakeAdapter (delete без файла → идемпотентный skip → пустой коммит → 400)

## Границы и follow-up

- **НЕ реализовано:** проверка `parent_sha` в адаптере (Contents API не принимает parent) — branch-level CAS через `expected_head_sha` на роуте
- **Content encoding:** всегда base64 (как требует Contents API)
- **COS-108 (Luna):** `POST /workspace/run` — компиляция пайплайна из закоммиченного workspace context

## Команды проверки

```powershell
# Smoke (живой Gitea + ПУ)
python D:\Infra\Temp\opencode\cos107_smoke.py

# Offline тесты изолированно
$env:COSMO_TEST_SESSION_DB=1
python -m pytest orchestrator/tests/cosmo/test_workspace_commit.py -v

# Suite gate
powershell -ExecutionPolicy Bypass -File services/scripts/suite_gate.ps1
```