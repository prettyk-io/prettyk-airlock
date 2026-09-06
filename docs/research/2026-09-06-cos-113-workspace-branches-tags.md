# COS-113 Acceptance — Workspace Branches & Tags (2026-09-06)

**Выполнил:** Boss  ·  **Итог:** PASS  ·  **Зелёные тесты:** 20/20  ·  **Suite gate:** 2693/0

## Что сделано

4 endpoint'а управления ветками и тегами для Web IDE через Gitea API:

### DTO (`domain/workspace.py`)
- `WorkspaceBranchSummary` (name, sha, isDefault, isProtected)
- `WorkspaceBranchListResponse` (branches, defaultBranch)
- `WorkspaceCreateBranchRequest` (repo, baseBranch, newBranch, Pydantic alias)
- `WorkspaceTagSummary` (name, sha)
- `WorkspaceTagListResponse` (tags)
- `validate_branch_name()` — git ref validation (rejects empty, spaces, `..`, dots, leading dash)

### Adapter (`adapters/forge_gitea.py`)
- `list_branches(owner, repo)` → Gitea GET `/branches` + GET `/` для default
- `create_branch(owner, repo, new_branch, base_branch)` → Gitea POST `/branches`
- `delete_branch(owner, repo, branch_name)` → Gitea DELETE `/branches/{name}`, 404-aware
- `list_tags(owner, repo)` → Gitea GET `/tags`

### Routes (`api/routes/workspace.py`)
| Метод | Endpoint | Статус | Что делает |
|-------|----------|--------|------------|
| GET | `/workspace/branches?repo=` | 200 | Список веток с флагами default/protected |
| POST | `/workspace/branches` | 201 | Создание ветки от baseBranch |
| DELETE | `/workspace/branches?repo=&branch=` | 204 | Удаление ветки (400 на default) |
| GET | `/workspace/tags?repo=` | 200 | Список тегов с SHA |

### Guards
- `_binding_for_repo()` — 404 ghost для чужих репозиториев
- Traversal guard — `validate_branch_name()` на уровне Pydantic (422)
- 400 при попытке удалить default branch
- 404 при удалении несуществующей ветки
- 409 (через forge_http_error) при коллизии имён веток

### Тесты (`test_workspace_branches.py`)
- 9 DTO unit-тестов: camelCase alias, extra=forbid, branch name validation
- 11 route-тестов: list/create/delete branches + list tags, ghost 404, delete default 400, traversal reject, delete 404, collision 409

## OpenAPI
Новые эндпоинты в спеке:
- `GET /api/v1/repos/workspace/branches`
- `POST /api/v1/repos/workspace/branches`
- `DELETE /api/v1/repos/workspace/branches`
- `GET /api/v1/repos/workspace/tags`

Новые схемы: `WorkspaceBranchSummary`, `WorkspaceBranchListResponse`, `WorkspaceCreateBranchRequest`, `WorkspaceTagSummary`, `WorkspaceTagListResponse`.