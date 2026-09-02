# COS-078 — Acceptance: канонический БД-контракт, миграционная изоляция, 5174

Дата: 2026-09-02 · Worker: Dev (pool) · Включает COS-076 · Status: implemented, верифицировано

## Что сделано

### 1. Канонический контракт конфигурации БД (один порядок, задокументирован)
`orchestrator/cosmo/db/session.py` — контракт в docstring, применён одинаково в
session.py / alembic env.py / migration_verifier.py:

1. **Explicit programmatic target** — alembic Config с атрибутом
   `attributes["cosmo_url_explicit"]=True` (in-process верификатор → scratch).
   Env **не консультируется** — conftest-set env не может увести цикл мимо scratch.
2. **`COSMO_DATABASE_URL` env** — явный override, **loud-logged** (warning,
   раз на значение, logger `cosmo.db.config`) через `env_override_url()`.
3. **Канонический дефолт** — `DEFAULT_DATABASE_URL` (dev stand) / ini placeholder.

- **Lazy-резолв везде**: URL больше не фиксируется при импорте (корень
  COS-072/075 split-brain: модули, импортированные до conftest, держались за dev).
  `get_engine()`/`get_sync_engine()` пересоздают движок при смене URL.
- **pop-env хак удалён**: `alembic_cycle` больше не снимает env на время
  command-вызовов — env.py видит explicit-маркер (архитектурная замена COS-073 хака).
- `migration_verifier.is_pg_available`/`_alembic_cfg` — локальные os.getenv-дубли
  убраны, единая точка `session.get_sync_url()`.

### 2. Scratch-based schema verification (COS-076)
- `verify_schema(url=...)`, `verify_enums(url=...)`, `verify_gin(url=...)`,
  `test_non_destructive(url=...)` — верифицируют произвольную БД.
- `alembic_cycle(keep_scratch=True)` возвращает scratch-URL;
  `drop_scratch_db(url)` с guard-префиксом — дроп в finally.
- `test_cycle_then_schema_matches` и TestEnums/TestGin/TestNonDestructive —
  **на свежей scratch**: ни один migration-тест не зависит от состояния dev-БД.

### 3. Catalog-race isolation (COS-076)
- `_testpg.scratch_name(prefix)` — уникальное имя per-run; «migration_verifier»
  (`cosmo_scratch_cycle_<hex>`) и все тест-фикстуры переведены.
- Митигирует гонку `pg_type_typname_nsp_index` (два pytest-процесса CREATE
  одинаково именованных таблиц в одной fixed-name scratch — наблюдено 2 сентября
  в паре с параллельным чужим прогоном).
- Миграционные тесты идут на **изолированный test PG :5433** (форс env в шапке
  test_migrations.py, как в conftest — внешний env не утекает при --noconftest).

### 4. Унификация дублирующих availability-чеков
- 7 файлов переведены на `_testpg.pg_available` (делегирование вместо локальных
  копий asyncpg-чека): test_email_adapter, test_notification_{worker,triggers,
  sse_sessions,identity,manager}, test_steel_thread (+импорт _testpg).
- test_migration_reconciliation `_pg_reachable` → `_testpg.pg_available`;
  transfer-durable тесты — admin/scratch через `_testpg` (был хардкод :5432 admin).

### 5. Порт 5174 (WSL-relay) — инфра-хвост закрыт документированием
Факт (netstat): `0.0.0.0:5174`/`[::]:5174` — docker-proxy (канон, frontend
`5174:80`); `[::1]:5174` — `wslrelay.exe` (сторонний). `localhost:5174` может
уехать в wslrelay → **канонический доступ `http://127.0.0.1:5174`**; Playwright
уже на `:5175`. Записано в COSMOPORT2-CANONICAL-MONOLITH.md §17.2. Очистка WSL
не планируется (Buddy выведен из пула, решение Максима от 2 сентября).

## Верификация

- Миграционный набор: `test_migrations` (14, +2 новых) + `test_migration_reconciliation`
  (10) — **24 passed ×3 прогона подряд**, в т.ч. в фоне параллельной активности
  на стенде; scratch-БД чистятся (pg_database — 0 остаточных).
- Transfer-набор (kernel+offline+recovery+durable+lease): **179 passed**.
- Унифицированные файлы: сборка 101 теста; smokes steel_thread 8 passed,
  notification_identity 8 passed.
- Полный сет с conftest: **2120 passed / 2 skipped**; фейлы — только чужие WIP-
  поверхности (flap security_matrix — известный хвост Apex COS-077; integration/
  — незакоммиченный WIP Luna COS-080, 404-ассерты падают изолированно тоже,
  к БД-контракту отношения не имеют). Против baseline: сет вырос 2029→2120,
  pre-existing fails не воспроизвелись в этом прогоне.
- **Runtime-gate: GATE OK** (6 PASS + 1 известная DEVIATION `/ready=200`,
  идентично baseline COS-073); migration-шаг гейта на per-run scratch
  `cosmo_scratch_gate_<id>`, head=e4f5a6b7c8d9.

## Out of scope (по карточке)
- Миграционная цепочка (заморожена, новых миграций нет).
- transfer API (Apex COS-077), notification surfaces (Flash COS-079),
  integration-фикстуры Luna (COS-080), чужие тест-поверхности.
