# COS-103 — Workspace API: Routes & Repos Refactor (acceptance)

Дата: 2026-09-04 · Worker: Luna · Статус: готово к приёмке
Зависимости: COS-102 (DTO — принято). Contract-тесты/OpenAPI — COS-104 (Flash).

## Что сделано

### 1. Новый роутер `orchestrator/cosmo/api/routes/workspace.py`

Три CAS-ready read-роута поверх **реального** `GiteaForgeAdapter`
(никакого mock-substrate):

| Роут | Контракт |
|---|---|
| `GET /api/v1/repos/workspace/bootstrap` | `WorkspaceBootstrapResponse`: repo, branch, `headSha`, capabilities, authorization. branch пуст → default branch из forge (`get_repo_info`); binding.default_branch — fallback. |
| `GET /api/v1/repos/tree` | `WorkspaceTreeResponse` — плоское рекурсивное дерево на head_sha; kind: blob→file, tree→directory. head_sha обязателен, сверяется с головой ветки. |
| `GET /api/v1/repos/file` | `WorkspaceBlobResponse` — content, sha, `encoding: utf-8`, `baseBlobSha` (база черновика для 3-way CAS). |

Ключевые решения:

- **Ресурс = binding приложения**, не свободный forge-путь: `repo`
  (`owner/repo`) ищется в `RepositoryBinding.repo_path`; не найден /
  app в чужом домене → единый **404** (ghost, anti-enumeration) через
  канонический `verify_ownership` + `resolve_caller_domain` (COS-067/083
  инвариант соблюдён: не-админ не может заголовком расширить домен).
- **Честный CAS:** tree/file сверяют `head_sha` с фактической головой
  ветки (`get_commit`); не совпадает (полностью или префиксом) →
  **409** "branch moved; re-bootstrap" — клиент не читает дерево чужой
  головы под именем ветки. Сокращённые sha (7+ hex) принимаются.
- **Валидация путей** — guard-функции DTO (`validate_repo/branch/
  head_sha/tree_path`); при ручном вызове `WorkspaceContractError`
  мапится в **400** (traversal, abs-пути, backslash, NUL и т.д. —
  reject до ForgeAdapter).
- **Forge-ошибки** — канонический `forge_client.forge_http_error`:
  не сконфигурирован → **503**, недоступен/отверг креды → **502**,
  нет repo/файла (LookupError/HTTP 404) → **404**. Пустое репо —
  честное: bootstrap честно фейлится 404 (коммитов нет), tree →
  `entries: []`.
- **capabilities честные:** свой домен → `read|draft|commit|run` +
  authorization allow; админский cross-domain доступ → read-only
  (видит, не пишет). Write-side (PUT/commit в forge) — out of scope
  (остался `POST /commit`, `POST /commit-and-run` в repos.py).
- Импорт `build_adapter` — локальный внутри каждого роута (канон
  pipelines.py): late-binding даёт тестируемость через monkeypatch
  `forge_client.build_adapter` (грабля: top-level `from X import Y`
  замораживает ссылку на момент импорта модуля роута).

### 2. GiteaForgeAdapter: +2 метода

- `get_commit(owner, repo, ref)` — резолв branch/sha в голову
  (commits?limit=1); пустой репозиторий (Gitea-квирк 200+[]) → честный
  LookupError.
- `get_tree(owner, repo, ref, recursive)` — рекурсивный git/trees;
  `truncated: true` → RuntimeError (частичное дерево нельзя выдать за
  полное); 404 → LookupError. + dataclass `GiteaTreeEntry`.

### 3. Вычистка mock/wire substrate из repos.py

Удалено: `_MOCK_REPO_FILES` (включая все захардкоженные `.wire`
сценарии — это кликер-мусор, запрещённый инвариантом), in-memory VFS
fallback в tree/file, PUT /file (in-memory запись), вымышленное
"default tree" для неизвестных репо. Файл ужался 330 → 174 строки.

Сохранено (реальные поверхности): `POST /commit` (заготовка write-side,
без VFS), `POST /commit-and-run` (полный COS-067/068 контракт:
SCAN_START + identity binding + реальный Run в PG), `FileTreeNode`
(используется security-matrix тестом forward-ref).

### 4. Роутинг

`workspace_router` подключён в main.py **рядом** с repos_router;
workspace-роуты объявлены раньше — `/workspace/bootstrap` новый путь,
`/tree` и `/file` перекрывают старые mock-эндпоинты теми же путями
(OpenAPI показывает `WorkspaceTreeResponse`/`WorkspaceBlobResponse`
как response_model). Обновление docs/cosmo-openapi.* — COS-104 (Flash),
в открытой спеке app.openapi() схемы уже корректны.

## Тесты

| Файл | Покрытие | Статус |
|---|---|---|
| `tests/cosmo/test_workspace_routes.py` (новый) | 21: bootstrap (happy/default-branch, ghost-404, foreign-domain-404 anti-enumeration, traversal-400, forge 502/503), tree (плоское рекурсивное, kinds, empty honest, CAS 409, short-sha, не-hex 400, ghost-404, forge-404), file (baseBlobSha, missing-404, traversal-400, CAS-409), anonymous-401 на всех трёх, mock-substrate мёртв (wire-пути приходят только из forge; PUT /file → 405) | 21 passed |
| Регрессия соседних линий | workspace DTO 75 + surface_auth 47 + transfer_security_matrix 26 + forge_cycle 26 | 195 passed |
| Полный сет | orchestrator/tests/cosmo | **2555 passed / 12 skipped / 0 failed** (3:57) |

Файлы: `orchestrator/cosmo/api/routes/workspace.py` (новый),
`orchestrator/cosmo/api/routes/repos.py` (clean),
`orchestrator/cosmo/adapters/forge_gitea.py` (+get_commit/get_tree),
`orchestrator/cosmo/api/main.py` (+include), тест новый.

## Грабли

- `from X import Y` top-level в роуте + monkeypatch `X.Y` не работают
  вместе: ссылка заморожена при импорте роута. Канон — локальный import
  в теле функции (как pipelines.py).
- Fake-репо в тесте без binding в PG → 404 от _binding_for_repo раньше
  fake-adapter'а: workspace адресует ТОЛЬКО привязанные репо (это фича
  изоляции, не баг).

## Для COS-104 (Flash)

- Открытая спека: `/api/v1/repos/tree` → `#/components/schemas/
  WorkspaceTreeResponse`, `/file` → `WorkspaceBlobResponse`,
  `/workspace/bootstrap` → `WorkspaceBootstrapResponse` (401/403/404/400/
  409 коды уже в спеке через raise HTTPException).
- prettyk-ide types.ts не содержит `baseBlobSha` и request-типы —
  FE follow-up (из доклада COS-102).
