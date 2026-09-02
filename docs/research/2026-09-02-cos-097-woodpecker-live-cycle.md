# COS-097 — Live Woodpecker Run Cycle, Part 2 (Apex)

Дата: 2026-09-02 · Карточка: `docs/BACKLOG.md` COS-097 · Статус: DONE

## Что закрыто

Живой цикл исполнения батчей через реальный Woodpecker CI, Part 2: durable-ручки
исполнения, честная деградация, evidence на завершение, restart-survival и wiring
в API. Adapter v3.5 (COS-008) доведён до прод-формы.

## Контракт Woodpecker 3.5 (верифицирован по исходникам тега)

- Репозитории маршрутизируются **только по числовому `repo_id`**;
  человеческое имя owner/name резолвится через `GET /api/repos/lookup/{owner}/{name}`.
- Отмена пайплайна — **`POST /api/repos/{rid}/pipelines/{number}/cancel`**;
  `DELETE .../pipelines/{number}` удаляет запись из истории — запрещено.
- Логи: `GET /api/repos/{rid}/logs/{number}/{stepId}` (нужен step-id, не просто number).
- Сабмит: `POST /api/repos/{rid}/pipelines`, JSON `{"branch": ...}`.
- Статусы: `pending | running | success | failure | killed | error | blocked | declined | skipped`.
  Terminal-набор исполнителя: `{success, failure, killed, error, declined, skipped}`.
  **`blocked` — НЕ terminal** (ждёт approval), маппится как in-flight.
- Маппинг в канон: `declined → blocked`, `skipped → failed`, остальное 1:1.

## Ключевые решения

1. **Side-таблица `cosmo_execution_handles`** на отдельном `ExecutionBase`
   (СУБД-схема канона не тронута, миграционная цепочка заморожена — COS-093).
   Ручка переживает рестарт процесса: recover() поднимает все не-terminal строки.
2. **Honest degraded-модель.** Транспортная ошибка/неизвестный результат не
   симулируют успех: счётчик подряд ≥ threshold (5) → честный terminal:
   batch `failed`, run `FAILED/INFRA` + `degraded=True` + reason,
   alert-evidence с consume-once (`pop_degraded_reason`).
3. **Evidence как канон.** Завершение батча публикует `commit_evidence_entry`
   (type=`log`, SHA-256 логов) через ledger-якорь и пишет digest в
   `Batch.evidence_refs` — никакого параллельного учёта.
4. **Wiring opt-in:** `COSMO_EXECUTOR_ENABLED=1` в lifespan; POST /runs вызывает
   `submit_run` только в running-фазе. Без флага поведение прежнее (COS-046).

## Найденные и исправленные баги (важно для будущих карт)

1. **Deadlock фонового лупа.** `await asyncio.wait_for(self._stopping.wait(), t)`
   при `threading.Event` — `.wait()` без таймаута **синхронно блокировал поток
   event loop'а**: loop заморожен, все `run_coroutine_threadsafe` фьючерсы висят
   навечно. Диагностика — faulthandler-дамп. Фикс: `await asyncio.sleep(interval)`.
2. **Revert-race.** Параллельные poll'ы (фон-луп + ручные) роняли stale-наблюдение
   `running` поверх terminal `passed`. Фикс: poll пропускает запись, если
   `old_status in _TERMINAL_BATCH` (pop + continue).
3. **Нет атомарного claim.** Два конкурентных poll'а могли дважды обработать
   батч (двойной evidence, двойной finalize). Фикс: claim под локом в начале
   `_finish_terminal` и degraded-ветки (`self._active.get(id) is not ph → return`).
4. **Resubmit-guard.** Повторный submit по батчу в полёте отрежен тройной
   проверкой: in-memory `_active` → `store.get_active()` (не-terminal строка)
   → PG-статус батча ≠ pending.
5. **asyncpg DataError.** `finalize_run` писал aware-`datetime.now(timezone.utc)`
   в `TIMESTAMP WITHOUT TIME ZONE`. Конвенция кодовой базы — naive UTC
   (`datetime.utcnow()`), приведено к ней (executor + service).

## Тестовая стратегия

- `test_execution_service.py` (14, детерминированные): `_start_core()` без
  фонового лупа; полный цикл — отдельный класс с реальным `start()` и
  wait-for-terminal. Fixture чистит `cosmo_execution_handles` per-test
  (иначе recover() поднимает зомби-ручки прошлых тестов и съедает очередь
  FakeWoodpecker).
- `test_batch_executor.py` обновлён под новый контракт (stateful pg-моки,
  resubmit-guard, расширенный terminal-frozenset, visible-unknown при
  adapter-ошибке).
- `test_int_woodpecker_smoke.py` — opt-in против живого стенда
  (`COSMO_WOODPECKER_URL`, сабмит только по `COSMO_WOODPECKER_SMOKE_SUBMIT=1`).
- Итог: **2498 passed / 8 skipped / 1 failed** (×2 стабильность), ~3.5 мин.

## Открытый finding (чужая поверхность, не трогал)

`test_openapi_contract.py::test_no_raw_token_in_parameters` падает:
параметр `session_token` появился в `GET /api/v1/domains` из модифицированного
чужого WIP `api/deps.py` (COS-066/067/068 auth-поверхность, их собственные
регрессионные тесты зелёные). Нужна маршрутизация владельцу: либо токен в
header, либо осознанное обновление OpenAPI-контракт-теста.

## Commit-партия

`P13-execution-woodpecker` (11 файлов): adapter, executor, run_control,
execution_service, models_execution, startup, runs, 4 тест-файла.
`runs.py` перенесён из P08, `startup.py` из P12 — их diff несёт COS-097 wiring.
Аудит: `D:\Infra\Temp\opencode\cos095_party_audit.py` → 226/226 OK
(чужое: WIP-COS094 ×3, WIP-COS096 ×6, WIP-DOCS ×4).
