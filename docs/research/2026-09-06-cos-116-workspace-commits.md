# COS-116 Acceptance — Workspace Commits History & Timeline (2026-09-06)

**Выполнил:** Boss  ·  **Итог:** PASS  ·  **Зелёные тесты:** 14/14  ·  **Suite gate:** 2727/0

## Что сделано

Endpoint истории коммитов ветки и таймлайна файла через Gitea API.

### DTO (`domain/workspace.py`)
- `WorkspaceCommitSummary` — sha, shortSha, message, authorName, authorEmail, committedAt, parentShas (camelCase alias, extra=forbid)
- `WorkspaceCommitListResponse` — commits, total, hasMore

### Adapter (`adapters/forge_gitea.py`)
- `list_commits(owner, repo, branch=None, path=None, limit=30, page=1)` — Gitea GET `/repos/{owner}/{repo}/commits`
- Парсинг Gitea-ответа: commit → sha, short_sha, message, author_name, author_email, committed_at, parent_shas
- Пагинация: limit (max 100), page (converted from offset in route layer)

### Route (`api/routes/workspace.py`)
| Метод | Endpoint | Статус | Что делает |
|-------|----------|--------|------------|
| GET | `/workspace/commits?repo=&branch=&path=&limit=&offset=` | 200 | История коммитов |

Параметры:
- `repo` — обязателен (owner/repo)
- `branch` — опционален, default HEAD
- `path` — опционален, фильтр истории одного файла
- `limit` — 1..100 (default 30)
- `offset` — ≥0 (default 0), конвертируется в page = offset // limit + 1
- `has_more` — True если возвращён полный лимит (Gitea не даёт total count)

### Guards
- `_binding_for_repo()` — 404 ghost для чужих репозиториев
- `_validate_or_400(repo=repo, path=path)` — валидация owner/repo формата и пути
- `limit` capped на уровне Pydantic/FastAPI (ge=1, le=100)

### Тесты (`test_workspace_commits.py`)
- 6 DTO unit-тестов: camelCase alias, extra=forbid, parentShas default, hasMore dump
- 8 route-тестов: list commits 200, pagination (offset/limit), has_more flag, branch filter, path filter, limit default 30, limit cap 422, ghost 404

### Fix: COS-114 missing import
- `WorkspaceSearchMatch` и `WorkspaceSearchResponse` добавлены в импорт `routes/workspace.py` (были пропущены при добавлении COS-114)