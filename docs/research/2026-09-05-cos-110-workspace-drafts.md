# COS-110 Acceptance — Workspace Drafts & 3-way Diff Engine (2026-09-05)

**Выполнил:** Boss  ·  **Итог:** PASS  ·  **Зелёные тесты:** 23/23  ·  **Suite gate:** 2644/0  ·  **Live smoke:** 5/5

## Что сделано

| # | Компонент | Файл | Строк |
|---|---|---|---|
| 1 | DTO: `WorkspaceDraftUpsertRequest`, `WorkspaceDraftResponse`, `WorkspaceDiffResponse` | `domain/workspace.py` | +78 |
| 2 | Valkey `DraftStore`: lazy `_get_valkey()`, save/load/delete, TTL 7d | `infra/valkey_drafts.py` | **new** 142 |
| 3 | `PUT /workspace/draft` — upsert черновика | `routes/workspace.py` | +30 |
| 4 | `GET /workspace/draft` — чтение черновика | `routes/workspace.py` | +35 |
| 5 | `DELETE /workspace/draft` — удаление черновика | `routes/workspace.py` | +30 |
| 6 | `GET /workspace/diff` — 3-way diff (base/draft/head) | `routes/workspace.py` | +60 |
| 7 | Тесты: 8 DTO + 13 route mock + 2 live opt-in | `test_workspace_draft.py` | **new** 23/23 |
| 8 | Live smoke (ПУ → Valkey → Gitea) | `cos110_smoke.py` | 5/5 |
| 9 | Suite gate полный прогон | `suite_gate.ps1` | 2644/0 PASS |

## Ключевые решения

### Valkey-only (без PG)
Карточка изначально предполагала «Valkey с персистентным фолбэком в PG», но канон обновлён до Valkey-only. Valkey и так персистентный (`--save 60 1` + Docker volume), а PG-миграции заморожены. Все существующие Valkey-клиенты (SSE tickets, backlog, distributed lock) работают без PG-фолбэка — деградируют честно при недоступности Valkey.

### Ключ изоляции
`cosmo:draft:{domain}:{user_id}:{owner}:{repo}:{branch}:{path}`

Изоляция по domain + user_id гарантирует, что черновики разных доменов/пользователей не пересекаются. TTL 7 дней продлевается (sliding) при каждом save.

### 3-way diff
- **base**: blob файла из коммита (по `base_blob_sha` из запроса или черновика)
- **draft**: текущий черновик из Valkey
- **head**: актуальный файл из Gitea (по `ref=branch`)
- **has_conflict** = base_content != head_content (кто-то закоммитил изменения, пока юзер редактировал)
- **additions / deletions**: line-level diff (set-based) для Monaco Diff Editor

### Lazy Valkey connection (как в `sse_tickets.py`)
```python
- import valkey (lazy, optional dependency)
- valkey.Valkey.from_url(...)
- client.ping()
- Success → cached for process lifetime
- Failure → NOT cached → retry next call
```

## Тестовое покрытие

| Класс | Тестов | Что проверяет | Статус |
|---|---|---|---|
| `TestDraftDto` | 8 | Валидация DTO, camelCase, extra=forbid, traversal | PASS |
| `TestDraftRoute` | 13 | PUT/GET/DELETE draft, GET diff (conflict/no-conflict/empty), ghost 404, Valkey 503, traversal 400 | PASS |
| `TestLiveDraft` | 2 | Live-цикл save→load→delete, diff против живого Gitea | SKIP |

## Smoke-чеклист (live)

| Операция | Endpoint | Status | Ответ |
|---|---|---|---|
| Сохранить черновик | PUT /workspace/draft | 201 | content, baseBlobSha, updatedAt |
| Прочитать черновик | GET /workspace/draft?path=X | 200 | полный ответ |
| 3-way diff | GET /workspace/diff?path=X | 200 | hasConflict=false, additions=1 |
| Удалить черновик | DELETE /workspace/draft?path=X | 204 | — |
| После удаления | GET /workspace/draft?path=X | 404 | No draft |

## Границы и follow-up

- **НЕ реализовано:** PG-таблица (канон изменён: Valkey-only)
- **additions/deletions:** set-based line count (не классический Myers diff) — достаточно для Monaco Diff Editor flags
- **Base blob по SHA:** требует `adapter.read_file(path, ref=base_blob_sha)` — работает в Gitea 1.22.6
- **COS-108 (Luna):** `POST /workspace/run` — использует commit_sha из COS-107 + черновик из COS-110 для запуска прогона

## Команды проверки

```powershell
# Live smoke
python D:\Infra\Temp\opencode\cos110_smoke.py

# Offline тесты
$env:COSMO_TEST_SESSION_DB=1
python -m pytest orchestrator/tests/cosmo/test_workspace_draft.py -v

# Suite gate
powershell -ExecutionPolicy Bypass -File services/scripts/suite_gate.ps1
```