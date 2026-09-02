# COS-076 (Hardening) + Test Infra Tails — Acceptance Report

**Дата:** 2026-09-02
**Карточка:** Пакет Boss «TEST INFRA TAILS + MIGRATION TEST HARDENING» (~10-16h)
**Статус:** DONE (не закоммичено; commit — только по явной команде)

## Что сделано

### 1. conftest wipe tail (transfer_* + trail)
- `orchestrator/tests/cosmo/conftest.py`:
  - wipe `delete_order` пополнен transfer-таблицами в FK-безопасном порядке
    (child → parent): `transfer_received_revisions` (без FK) →
    `transfer_landing_states` → `transfer_items` → `transfer_plans`;
  - `gate_decision_trail` (COS-081) в порядке согласован (без FK, до
    таблиц с FK);
  - `pg_client` create_all теперь поднимает и `TransferRegistryBase`
    (transfer-таблицы существуют централизованно, а не только в
    самодельных фикстурах transfer-тестов).

### 2. alembic/env.py fileConfig мина (поверхность COS-078)
Мина имела ДВА механизма поражения:
- (а) `fileConfig()` с дефолтом `disable_existing_loggers=True` ставит
  `.disabled=True` всем логгерам вне ini (`cosmoport.*`);
- (б) даже с `disable_existing_loggers=False` fileConfig **сносит handlers**
  на root/sqlalchemy/alembic — вместе с caplog-хэндлером pytest.

Фикс на поверхности env.py:
- in-process вызовы (marker `cfg.attributes["cosmo_in_process"]=True`,
  ставится `migration_verifier._alembic_cfg`) — fileConfig не вызывается
  вовсе: логирование хост-процесса (pytest/приложение) уже настроено;
- standalone CLI-прогоны (subprocess: reconciliation, runtime-gate) —
  `fileConfig(..., disable_existing_loggers=False)`.
- Regression-тесты (`test_migrations.py::TestLogSurvival`):
  * `test_caplog_survives_inprocess_cycle` — caplog ловит запись
    `cosmoport.migration_probe` ПОСЛЕ in-process `alembic_cycle()`;
  * `test_app_logger_not_disabled_after_cycle` — `cosmoport.*` не disabled.
- Мина-комментарий в `test_notification_ops.py` снят: тест
  `test_retry_and_dlq_logs_hide_recipient` переведён с прямого handler +
  `log.disabled=False` реанимации на честный `caplog`.

### 3. Migration Test Hardening (COS-076)
- `test_cycle_then_schema_matches` уже был scratch-based с COS-078 —
  добавлен regression `test_verify_schema_does_not_touch_main_db`:
  `verify_schema(url=scratch)` зелёный при битом/чужом
  `COSMO_DATABASE_URL` (ghost :5999) — верификация не консультируется с
  основным резолвом.
- Fixtured teardown scratch-БД: `_CREATED_SCRATCH` реестр +
  session-scoped `_scratch_session_teardown` в `test_migrations.py` —
  scratch, пережившие тест (падение мимо try/finally), дропаются в конце
  сессии. xdist-безопасно: каждый worker дропает только свои имена.
- Каталожная гонка pg_type_typname_nsp_index: корень — параллельный
  create_all двух процессов на ОДНОМ cosmo_test (check-then-create не
  атомарен). Фикс: `pg_advisory_xact_lock` вокруг create_all в pg_client
  (сериализация bootstrap; второй процесс пере-проверяет после первого).
- Per-session изоляция данных (opt-in): `_testpg` при
  `COSMO_TEST_SESSION_DB=1` создаёт уникальную БД `cosmo_test_s<hex>` на
  том же инстансе, переключает `TEST_PG_URL` (все потребители резолвят
  через него — split-brain исключён), atexit дропает. Без флага — прежнее
  поведение (общий cosmo_test).

## Верификация
- Migration-сет: **27/27** (`--noconftest`, 14→17 в test_migrations + 10
  reconciliation).
- Связка «in-process циклы → caplog»: test_migrations + reconciliation +
  notification_ops + worker + email_adapter в одном процессе —
  **103 passed** (исторический сценарий мины).
- Notification ops: **37/37** (конвертированный caplog-тест зелёный).
- Transfer durable API + trail: **27/27**.
- **Wipe tail**: после прогона transfer+trail файлов точные count(*) по
  всем 12 ключевым таблицам (transfer_*, trail, runs, gates, domains,
  evidence_ledger, notification_events, batches, groups) — **все 0**.
- Параллельные прогоны на :5433:
  * `test_migrations` ∥ `test_migration_reconciliation` — **17 + 10
    passed**, exit 0/0;
  * conftest-путь без флага: pg_type/UniqueViolation — **0 вхождений**
    (advisory lock работает); data-FK-гонки общего cosmo_test остаются
    (дизайн shared DB) — решаются флагом;
  * с `COSMO_TEST_SESSION_DB=1`: две параллельные сессии —
    **10 + 64 passed, ноль фейлов**, session-БД дропнуты по atexit
    (leftover: пусто).
- **Полный сет: 2224 passed / 2 skipped / 0 failed** — первый полностью
  чистый прогон за день.

## Границы
- Не тронуто: миграционная цепочка (FROZEN — новых миграций нет),
  integration/conftest.py (Luna COS-080 WIP — там свой create_all без
  advisory lock; при параллельных сессиях с флагом не актуально),
  rbac-счётчики/Luna routes (чужие WIP), deps.py (Apex), prod-nginx (Buddy).
- Известный gap: session-БД при SIGKILL процесса не дропается (atexit не
  срабатывает) — останется `cosmo_test_s*` до ручного дропа; риск
  осознанно принят (авто-janitor по живости соединений опасен для
  простаивающего worker'а).

## Инвариант
Тестовый PG после любого прогона чист (wipe покрывает все три Base);
caplog жив после in-process миграций; ни один migration-тест не зависит
от dev-схемы; параллельные сессии на :5433 изолированы (opt-in флаг) и
никогда не ловят каталожных гонок (advisory lock + per-run scratch).
