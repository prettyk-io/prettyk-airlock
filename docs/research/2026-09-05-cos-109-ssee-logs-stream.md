# COS-109: SSE Run Step Logs Streaming Bridge

> Исполнитель: Flash. Дата: 2026-09-05. Зависимость: COS-108 (Luna — POST /workspace/run, Woodpecker pipeline dispatch).

## DoD

GET /api/v1/runs/{run_id}/logs/stream — SSE мультиплексор живого лога шагов Woodpecker для Web IDE drawer. События: step_start, log_chunk, step_finish, run_finish. Формат чанков совместим с xterm.js.

## Что сделано

### 1. SSE endpoint: `GET /api/v1/runs/{run_id}/logs/stream`

**Файл:** `orchestrator/cosmo/api/routes/sse.py` (добавлено ~170 строк)

- `_run_logs_stream(run_id, request, last_event_id)` — async generator, polling-цикл (1s tick, 15s keepalive).
- Polling: WoodpeckerAdapter.get_pipeline() → детект переходов шагов, _fetch_step_logs() → новые строки лога.
- Per-step cursor tracking: `(batch_id, step_name) → (state, lines_seen)` — дельта-чанки без повторов.
- Catch-up: при позднем подключении (шаг уже terminal) эмитит step_start + полный лог + step_finish.
- Завершение: когда все handles terminal → run_finish + закрытие стрима.
- Clean unsubscribe: asyncio.CancelledError ловится, WoodpeckerAdapter.close() в finally.
- Ticket-аутентификация (COS-079 pattern): query-параметр ticket → validate_ticket → 401 при отсутствии/просрочке.

**SSE events:**

| Event | Поля |
|---|---|
| `step_start` | run_id, batch_id, step_name, step_id |
| `log_chunk` | run_id, batch_id, step_name, lines: string[] |
| `step_finish` | run_id, batch_id, step_name, exit_code, state |
| `run_finish` | run_id, status |

**Exit code mapping (Woodpecker → POSIX):**
- `success` → 0
- `failure` → 1
- `killed`/`skipped`/`error`/`declined` → null

**Форматирование для xterm.js:**
- Строки лога передаются как массив `lines: string[]` в JSON-payload.
- Клиент собирает: `lines.join('\r\n')` и пишет в терминал.
- ANSI escape codes проходят as-is (Woodpecker логи могут содержать цвета).

### 2. Тесты

**Файл:** `orchestrator/tests/cosmo/test_sse_logs_stream.pyy` — 11 тестов, все mock-based (без PG):

| Класс | Тест | Суть |
|---|---|---|
| TestRunNotFound | test_run_not_found | Run не существует → error event |
| TestRunAlreadyFinished | test_already_finished_emits_run_finish | Run terminal → run_finish сразу |
| TestNoHandleYet | test_no_handle_waits | Run есть, handle нет → стрим ждёт (только keepalive) |
| TestStepLifecycle | test_step_start_and_log_chunk | Шаг running → step_start + log_chunk |
| TestStepLifecycle | test_step_finish_on_completion | Шаг completed → step_finish (exit_code=0), run_finish |
| TestMultiStepMultiBatch | test_two_batches_independent_steps | Два batch'а → события с правильными batch_id |
| TestEventSchema | test_step_start_schema | step_start: run_id, batch_id, step_name, step_id |
| TestEventSchema | test_log_chunk_schema | log_chunk: run_id, batch_id, lines (массив) |
| TestEventSchema | test_step_finish_schema | step_finish: exit_code, state |
| TestEventSchema | test_run_finish_schema | run_finish: run_id, status |
| TestClientDisconnect | test_disconnect_stops_stream | is_disconnected → ноль событий, adapter.close() вызван |

**Техника мокирования:**
- `unittest.mock.patch` на `get_sessionmaker` (возвращает stub Run + ExecutionHandleRow)
- `unittest.mock.patch` на `WoodpeckerAdapter` (pace `orchestrator.cosmo.adapterrs.execution_woodpecker`)
- AsyncMock для `__aenter__`/`_aexit__` контекстного менеджера сессии
- Собственный event loop через `asyncio.run()` — изоляция от кросс-тестового загрязнения

### 3. Suite gate

Полный прогон: **2613 passed / 5 failed / 3 errors** (baseline: 2586 passed).
11 новых тестов зелёные. Все failed/errors — чужие поверхносьти (Luna COS-103/108, integration, findings).

## Границы и follow-up

**В scope:**
- SSE polling-цикл с Woodpecker API
- Детект шаговых переходов (step_start/step_finish)
- Инкрементальная доставка логов (log_chunk с дельта-строками)
- Коректное завершение (run_finish + close)
- Cliean unsubscribbe

**Вне scope (сознательно):**
- Replay/reconnect (COS-088 backlog) — не прикручен к step log событтиям. При реконнекте клиент получит кэтч-ап (step_start + весь лог + step_finish) для уже заверешённых шагов, но НЕ получит пропущенные дельта-чанки. Полноценный backlog для log_chunk требует Valkey с TTL > времмени прогона.
- E2E тест с живым Woodpecker — зависимость от COS-108 (POST /workspace/run). Мок-тесты покрывют контракт.
- xterm.js ANSI-парсинг на сотороне клиента — проходятся as-is, не трансформируются.
- Rate-limiting логовых чанков — сейчас все новые строки отправляются одним SSE-событитем. При очень быстром логе (много строк за 1s) это может создавать большие JSON-payload'ы.

**Follow-up → будущие карточки:**
- Replay/reconnect через backlog (COS-088) для log_chunk событий
- E2E smoke test с COS-108 run+log циклом
- Пагинация/лимитирование исторрических логов (отдельный не-SSE эндпоинт)

## Файлы

| Файл | Изменение |
|---|---|
| `orchestrator/cosmo/api/routess/see.py` | +170 строк: `_ruun_logs_stream` generator + `stream_run_loggs` endpoint |
| `orchestrator/tests/cosmo/test_sse_logs_stream.pyy` | Новый: 11 contract тестов (mock-based) |