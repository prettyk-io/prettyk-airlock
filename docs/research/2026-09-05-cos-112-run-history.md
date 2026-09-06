# COS-112 Plan — Workspace Run History & Step Logs REST API

> Исполнитель: Luna. Дата: 2026-09-05. Зависимость: COS-108 (done).
> Режим: Strategy (план). Выполнение — следующим заходом отдельным worker-диспетчем.

## 1. Что строим

Два REST-эндпоинта для исторического просмотра workspace-прогонов и постраничного чтения логов
завершённых шагов. SSE-поток (COS-109) покрывает живой стриминг; COS-112 даёт REST-альтернативу
для Control Station и Web IDE без постоянного соединения.

| Эндпоинт | Назначение |
|---|---|
| `GET /api/v1/repos/workspace/runs` | История запусков по репозиторию/ветке из `cosmo_workspace_runs` |
| `GET /api/v1/runs/{run_id}/steps/{step_id}/logs` | Постраничное чтение логов шага через Woodpecker API |

---

## 2. DTO — domain/workspace.py (дописать в конец файла)

### 2.1 Ответ на список прогонов

```python
class WorkspaceRunSummary(_WorkspaceDTO):
    """Один прогон в истории запусков."""
    run_id: str
    repo_owner: str
    repo_name: str
    branch: str
    commit_sha: str
    pipeline_number: int | None = None
    status: str  # pending / running / succeeded / failed
    tracking_url: str | None = None
    created_at: str  # ISO-8601 строка (сериализация datetime)


class WorkspaceRunListResponse(_WorkspaceDTO):
    """Пагинированный список прогонов."""
    runs: list[WorkspaceRunSummary]
    total: int  # всего записей по фильтру
    limit: int
    offset: int
```

### 2.2 Ответ на логи шага

```python
class StepLogsResponse(_WorkspaceDTO):
    """Постраничный ответ с логами одного шага."""
    run_id: str
    step_id: int
    step_name: str | None = None
    total_lines: int
    lines: list[str]
    has_more: bool  # True если есть ещё строки за offset+limit
```

**Примечания:**
- `WorkspaceRunSummary` не наследует camelCase-алиасы (run_id, repo_owner etc. —
  это внутренние snake_case имена базы, не зеркало types.ts). Используем
  `_WorkspaceDTO` ради `extra="forbid"` и `populate_by_name=True`.
- Для единообразия с COS-108: `total_lines` — общее число строк в логе шага
  (Woodpecker API отдаёт все строки массивом — мы считаем на стороне сервера).

---

## 3. Маршруты

### 3.1 GET /api/v1/repos/workspace/runs

Добавляется в `orchestrator/cosmo/api/routes/workspace.py` (существующий
роутер `prefix="/api/v1/repos"`).

```
GET /api/v1/repos/workspace/runs?repo=owner/name&branch=main&status=running&limit=20&offset=0
```

**Параметры запроса:**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| repo | str (Query, required) | — | owner/name, валидируется через существующую `validate_repo` |
| branch | str (Query, optional) | None | Фильтр по ветке |
| status | str (Query, optional) | None | Фильтр: pending/running/succeeded/failed |
| limit | int (Query, ge=1, le=100) | 20 | Размер страницы |
| offset | int (Query, ge=0) | 0 | Смещение |

**Логика обработчика:**

1. `require_principal()` — аутентификация (как все workspace-роуты)
2. `_binding_for_repo(db, repo, principal, caller_domain)` — ownership-чек
   (маппинг на существующую domain/app/binding цепочку)
3. `SELECT` из `cosmo_workspace_runs`:
   - `WHERE repo_owner = :owner AND repo_name = :name`
   - `AND branch = :branch` (если передан)
   - `AND status = :status` (если передан)
   - `ORDER BY created_at DESC`
   - `LIMIT :limit OFFSET :offset`
4. Отдельный `SELECT count(*)` с теми же WHERE-фильтрами для `total`
5. Формирование `WorkspaceRunListResponse`

**Важно:** `_binding_for_repo` уже делает ownership-чек — чужая
domain → 404 (ghost). Двойной чекаут не нужен.

### 3.2 GET /api/v1/runs/{run_id}/steps/{step_id}/logs

Для этого эндпоинта нужен **отдельный роутер** внутри `workspace.py` —
префикс `/api/v1/runs` конфликтует с существующим `runs.py` (тот без префикса,
но регистрирует роуты в том же пространстве). Решение:

```python
run_log_router = APIRouter(prefix="/api/v1/runs", tags=["workspace"])
```

И регистрация в `main.py` — **перед** `runs_router`, как уже сделано с
`evidence_router` и `sse_router` (комментарий COS-097).

```
GET /api/v1/runs/{run_id}/steps/{step_id}/logs?offset=0&limit=1000&tail=0
```

**Параметры:**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| run_id | str (Path) | — | `WorkspaceRunRow.run_id` |
| step_id | int (Path) | — | Woodpecker step ID (из `_flatten_steps`) |
| offset | int (Query, ge=0) | 0 | С какой строки начинать |
| limit | int (Query, ge=1, le=5000) | 1000 | Сколько строк вернуть |
| tail | int (Query, ge=0) | 0 | Последние N строк (tail > 0 → игнорирует offset) |

**Логика обработчика:**

1. `require_principal()` — аутентификация
2. `SELECT WorkspaceRunRow WHERE run_id = :run_id` → 404 если нет
3. Построить woodpecker-handle из полей строки:
   ```python
   handle = {
       "number": row.wp_number,
       "repo_id": row.repo_id,
       "repo_owner": row.repo_owner,
       "repo_name": row.repo_name,
   }
   ```
4. `build_woodpecker().get_pipeline(handle)` → получить pipeline-дерево
5. `_flatten_steps(detail)` → найти шаг с `step.get("id") == step_id`
   → 404 если не найден
6. Вызвать новый публичный метод `get_step_logs_by_id(handle, step_id)`
   на WoodpeckerAdapter (см. §4)
7. Получить полный массив строк, посчитать `total_lines`
8. Применить пагинацию:
   - Если `tail > 0`: `lines[-tail:]`
   - Иначе: `lines[offset:offset+limit]`
9. `has_more = (offset + limit) < total_lines` (или `False` если tail)
10. Вернуть `StepLogsResponse`

**Edge cases:**
- Pipeline ещё не создан (`wp_number is None`) → 404 "pipeline not found"
- Шаг ещё не завершён — всё равно возвращаем текущие логи (пустой список ок)
- Woodpecker недоступен → 502 через `woodpecker_http_error`

---

## 4. WoodpeckerAdapter — новый публичный метод

Добавить в `orchestrator/cosmo/adapters/execution_woodpecker.py`:

```python
def get_step_logs_by_id(self, handle: dict, step_id: int) -> list[str]:
    """Логи конкретного шага по Woodpecker step ID (не индексу).

    Используется COS-112 для REST-пагинации логов.
    """
    detail = self.get_pipeline(handle)
    for step in self._flatten_steps(detail):
        if step.get("id") == step_id:
            return self._fetch_step_logs(handle, step)
    return []
```

**Почему отдельный метод:** `get_logs(handle, step=0)` принимает индекс в
уплощённом списке — это легаси-интерфейс. COS-112 нужен поиск по Woodpecker
step ID (числовой, из pipeline-дерева). Новый публичный метод не ломает
существующих потребителей `get_logs`.

---

## 5. main.py — регистрация run_log_router

В `orchestrator/cosmo/api/main.py`:

```python
from orchestrator.cosmo.api.routes.workspace import router as workspace_router, run_log_router
```

И регистрация **перед** `runs_router` (тот же паттерн, что `evidence_router`
перед `runs_router` для предотвращения затенения `GET /api/v1/runs/{id}`):

```python
app.include_router(run_log_router)
# ... потом workspace_router, потом всё остальное ...
```

Фактически — вставить сразу перед `app.include_router(workspace_router)` на строке 82.

---

## 6. Файлы, которые меняем

| Файл | Что |
|---|---|
| `orchestrator/cosmo/domain/workspace.py` | +3 DTO: `WorkspaceRunSummary`, `WorkspaceRunListResponse`, `StepLogsResponse` |
| `orchestrator/cosmo/api/routes/workspace.py` | +2 маршрута: `GET /workspace/runs` (существующий router), `GET /runs/{run_id}/steps/{step_id}/logs` (новый `run_log_router`), +экспорт `run_log_router` |
| `orchestrator/cosmo/adapters/execution_woodpecker.py` | +1 метод: `get_step_logs_by_id` |
| `orchestrator/cosmo/api/main.py` | +1 импорт `run_log_router`, +1 `include_router` |
| `orchestrator/tests/cosmo/test_workspace_run_history.py` | Новый файл: DTO-тесты + route-тесты |

**Не трогаем:**
- `conftest.py` — wipe уже включает `cosmo_workspace_runs`, create_all уже вызывает `ExecutionBase.metadata.create_all`
- `db/models_execution.py` — `WorkspaceRunRow` уже содержит всё нужное
- `db/models.py` — миграционная цепочка заморожена
- `api/startup.py` — `ExecutionBase.metadata.create_all` уже в lifespan

---

## 7. Тестовый план

Файл: `orchestrator/tests/cosmo/test_workspace_run_history.py`

### 7.1 DTO unit (~9 тестов)

| Тест | Что проверяет |
|---|---|
| `test_summary_minimal` | WorkspaceRunSummary с обязательными полями |
| `test_summary_extra_forbid` | forbid лишнего поля |
| `test_list_response` | WorkspaceRunListResponse валидация |
| `test_list_response_empty` | Пустой список runs |
| `test_step_logs_response` | StepLogsResponse полный |
| `test_step_logs_has_more_false` | has_more=False когда все строки поместились |
| `test_step_logs_extra_forbid` | forbid лишнего поля |
| `test_summary_serializes_datetime` | created_at → ISO-8601 строка |

### 7.2 Route tests — GET /workspace/runs (~10 тестов)

Используем тот же паттерн `TestRunHistoryRoute` + `_mocks` + `_seed_db`, что в `test_workspace_run.py`.
Но seed должен включать создание нескольких `WorkspaceRunRow` записей (через прямой PG):

| Тест | Что проверяет |
|---|---|
| `test_list_ok_200` | Успешный запрос, возвращает прогоны |
| `test_list_pagination` | limit=2 offset=1 — ровно 2 записи |
| `test_list_total_correct` | total соответствует количеству в базе |
| `test_list_filter_by_status` | status=running — только running |
| `test_list_filter_by_branch` | branch=dev — только dev |
| `test_list_unknown_repo_404` | ghost-репо → 404 |
| `test_list_anonymous_401` | Без аутентификации → 401 |
| `test_list_bad_repo_422` | repo="../bad" → 422 |
| `test_list_limit_too_high_422` | limit=101 → 422 |
| `test_list_empty_ok` | Нет прогонов → 200, runs=[], total=0 |

### 7.3 Route tests — GET /runs/{run_id}/steps/{step_id}/logs (~8 тестов)

Mock-адаптер Woodpecker должен уметь возвращать логи для фейкового шага.

| Тест | Что проверяет |
|---|---|
| `test_logs_ok_200` | Успешный запрос, возвращает строки |
| `test_logs_pagination` | offset=2 limit=3 — 3 строки, правильный has_more |
| `test_logs_tail` | tail=50 — последние 50 строк |
| `test_logs_run_not_found_404` | Несуществующий run_id → 404 |
| `test_logs_step_not_found_404` | Несуществующий step_id → 404 |
| `test_logs_anonymous_401` | Без аутентификации → 401 |
| `test_logs_woodpecker_error_502` | Woodpecker недоступен → 502 |
| `test_logs_negative_offset_422` | offset=-1 → 422 |

### 7.4 Регресс

После всех правок: полный suite `orchestrator/tests/cosmo/` — gate должен остаться
зелёным (2621+ passed, 0 failed).

---

## 8. Риски и edge cases

| Риск | Меры |
|---|---|
| Конфликт `/api/v1/runs/*` с `runs.py` | Регистрировать `run_log_router` ПЕРЕД `runs_router` (паттерн `evidence_router`) |
| Большие логи (>5000 строк) | limit ceiling 5000 — больше = несколько запросов с offset |
| Синхронный Woodpecker в асинхронном роуте | `requests.Session` в адаптере — для COS-112 оборачивать в `await asyncio.to_thread()` или `run_in_executor`. Либо оставить как есть (весь workspace.py уже так работает — `build_woodpecker` и `build_adapter` синхронные, FastAPI терпит) |
| Роутер с `prefix="/api/v1/runs"` и `tags=["workspace"]` | Ок — в OpenAPI схлопнутся в один тэг |
| `WorkspaceRunRow` без шагов | `wp_number is None` для staged-прогонов — вернуть 404 |
| `StepLogsResponse.created_at` vs `WorkspaceRunRow.created_at` | База хранит `datetime`, Pydantic сереализует в ISO-8601 через `model_validate` / `model_dump(mode='json')` |