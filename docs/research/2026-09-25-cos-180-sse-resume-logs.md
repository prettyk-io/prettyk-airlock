# COS-180 Acceptance — SSE resume логов прогона: event id + backlog replay (2026-09-25)

**Выполнил:** Luna · **Итог:** PASS · **Новые тесты:** 9/9 (resume) + 11/11 (COS-109 обновлён) · **Suite gate:** 3559/0 · **Live-smoke:** 12/12

## Что сделано

Лог-стрим прогона (`GET /api/v1/runs/{run_id}/logs/stream`, COS-109) получил resume-половину
контракта COS-088, которую ждал IDE-клиент (IDE-CORE-017: `Last-Event-ID` + dedupe + resync):
SSE `id` на каждом data-событии и replay недоставленного из Valkey backlog.

### Backlog (`api/sse_backlog.py`)

- Новый `read_window(kind, key) -> list[EventRecord] | None` — всё удержанное окно stream'а
  хронологически. `replay()` отдаёт только записи после `after_id`, а производному стриму для
  продолжения без дублей нужно всё окно (восстановление позиции). `None` — хранилище недоступно
  (caller → честный resync); пустой список — окно пусто.

### Стрим (`api/routes/sse.py`)

- **kind `runlog`**, key = `run_id` — отдельное backlog-пространство; иначе replay логов
  смешался бы с run-событиями на общем ключе.
- Каждое data-событие (`step_start`/`log_chunk`/`step_finish`/`run_finish`) идёт через
  `_backlog_item` → publish в backlog → SSE `id` == XADD-id (инвариант COS-088). Первым в
  стрим идёт `stream_backlog`-флаг (mode `valkey|memory`, без id) — наблюдаемый флаг деградации.
- **Resume-блок (до терминальной отсечки):** при `last_event_id` (query сильнее заголовка):
  - окно содержит last-id → недоставленный хвост реплеится с исходными id;
  - `_seed_log_cursors(records)`: для каждого (batch, step) считается сумма строк во всех
    чанках окна (acked + missed) и состояние из последней записи — live-loop после реконнекта
    догоняет только строки, которых в окне ещё не было (никакой повторной отдачи всего лога);
  - окно не содержит last-id → **gap** → `resync` (`reason: "gap"`), не тишина;
  - хранилище недоступно → `resync` (`reason: "backlog_unavailable"`).
- **`run_finish` без дублей:** если финальное событие уже в backlog — replay его доставит, а
  повторная эмиссия подавляется; свежий коннект к терминальному прогону эмитит его с id.
- Свежий коннект (без last-id) сохраняет прежний полный catch-up COS-109.

### Честные границы

- При вытеснении записей ДО `last-event-id` (TTL/MAXLEN) счётчик доставленного занижен —
  возможен повторный догон части логов; **потерь нет**, непрерывность вне окна не
  подтверждается (это и есть gap-семантика COS-088). TTL 900 c sliding, MAXLEN ≈2000 на ключ.
- `error`-диагностики остаются без id (не replay-able); pty-события эпика пойдут тем же
  publish-путём, когда появятся.
- Payload'ы событий и xterm-формат не менялись — только SSE-конверт получил `id`.

## Тесты

- `tests/cosmo/test_sse_logs_resume.py` (**новый, 9 passed**): флаг+уникальные id; replay
  пропущенного ровно один раз с исходным id; уже доставленные строки не дублируются (a..e
  ровно по разу на двух сессиях); порядок replay; gap→resync; backlog-unavailable→resync;
  no-dup `run_finish`; восстановление курсоров; compat-catch-up свежего коннекта.
- `tests/cosmo/test_sse_logs_stream.py` (COS-109, обновлён под флаг) — 11 passed.
- SSE-контур `-k "sse or notification or logs"` — **320 passed / 0 failed**.
- OpenAPI-артефакты регенерированы из живого `app.openapi()` (дифф — дельта описания
  лог-эндпоинта; json==yaml==live; контракт-гвард COS-177 поймал рассинхрон).
- **Suite gate: 3559 passed / 23 skipped / 0 failed** (370 s).

## Live-smoke (живой стенд; реальный HTTP SSE + реальный Valkey backlog)

Сценарий `D:\Infra\Temp\opencode\cos180_live_smoke.py` — **12/12 PASS**:

| Шаг | Действие | Результат |
|---|---|---|
| 1 | conn1, `last_event_id=A` (A — «доставленное») | флаг + `X-Cosmo-Backlog: valkey`, replay нет |
| 2 | «офлайн»: событие B посеяно в backlog | id(B) > id(A) |
| 3 | conn2, `last_event_id=A` | replay B ровно один раз, исходный id, без повторной отдачи A |
| 4 | conn3, `last_event_id=B` | повторного B нет (дедуп) |
| 5 | conn4, битый `last_event_id` | `resync` c `reason=gap` по проводу |

**Стенд-факты (не блокеры):**
- `login` отдавал 500 — `prettyk-openbao` (dev-mode, in-memory) снова потерял секреты
  (зона COS-178/Buddy). Для смоука `ot1`-тикет посеян напрямую в Valkey в формате
  `sse_tickets`; валидация на сервере — реальная (`GETDEL`).
- Woodpecker DB пуста (0 repos / 0 pipelines) — деривация чанков из реального пайплайна на
  стенде не воспроизводилась; она покрыта unit-тестами, по проводу проверены id/replay/дедуп/gap.

## Артефакты

- `orchestrator/cosmo/api/routes/sse.py` — resume-блок, `_seed_log_cursors`, `runlog`-публикация.
- `orchestrator/cosmo/api/sse_backlog.py` — `read_window`.
- `orchestrator/tests/cosmo/test_sse_logs_resume.py` (новый), `test_sse_logs_stream.py` (флаг).
- `docs/cosmo-openapi.{json,yaml}` — регенерация.
