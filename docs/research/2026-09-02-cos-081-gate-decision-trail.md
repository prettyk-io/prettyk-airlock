# COS-081: Durable Gate Decision Trail — Acceptance Report

**Дата:** 2026-09-02
**Карточка:** BACKLOG.md COS-081 (Boss, 20-24h, P1, dep COS-078)
**Статус:** DONE (не закоммичено; commit — только по явной команде)

## Что сделано

### 1. PG-хранилище gate-решений (отдельный Base, frozen chain safe)
- `orchestrator/cosmo/db/models_gate_trail.py` (новый): `GateTrailBase`
  (отдельный DeclarativeBase по образцу `TransferRegistryBase`, COS-070) +
  `GateDecisionTrailRow` → таблица **`gate_decision_trail`**:
  - `id` (uid PK), `gate_id`, `plan_id`, `run_id` nullable, `batch_id` nullable,
    `decision`, `decided_by`, `initiator`, `signature` nullable,
    `policy_snapshot` JSONB, `evidence_ids` JSONB (список),
    `decided_at`, `created_at`;
  - индексы: `ix_gdt_gate_id/plan_id/run_id/decided_at`;
  - **без cross-Base FK** — связи логические (gate/run/evidence могли быть
    удалены; trail переживает их), миграционная цепочка не тронута.
- Миграционная цепочка FROZEN не изменялась; таблица создаётся idempotent
  `create_all` (см. §3). **Документированное отклонение:** таблица вне
  alembic-цепочки, `verify_schema` не расширялся (frozen-chain faithful).

### 2. Репозиторий (append-only)
- `orchestrator/cosmo/db/gate_trail_repo.py` (новый), async-функции над
  `AsyncSession`:
  - `append_gate_decision(...)` — INSERT; вызывается **до commit** API-пути,
    строка фиксируется той же транзакцией, что и обновление `gates`
    (write-before-response, атомарно);
  - `trail_for_gate(gate_id, run_id=None)` — новые первыми;
  - `trail_for_run(run_id)` — хронологически (acceptance read-path);
  - инвариант append-only: только INSERT/SELECT, UPDATE/DELETE отсутствуют.

### 3. Интеграция в API gates
- `orchestrator/cosmo/api/routes/gates.py`:
  - `GateDecisionRequest` расширен опциональными `run_id`, `batch_id`,
    `evidence_ids` — **back-compat** (старый payload валиден);
  - `record_gate_decision` пишет trail-строку в той же транзакции до
    возврата ответа; `initiator` — из `principal.user_id` (auth-контекст);
    `policy_snapshot` — `gate.policy_json` на момент решения;
  - read-paths (COS-068 auth: `require_principal`):
    - `GET /api/v1/gates/{gate_id}/decisions[?run_id=]` (404 на unknown gate);
    - `GET /api/v1/gates/trail/runs/{run_id}` — trail всех решений прогона.
- `orchestrator/cosmo/api/startup.py`: lifespan создаёт таблицу
  idempotent `create_all(GateTrailBase.metadata)` (bootstrap не роняет
  старт — warning при сбое).
- `orchestrator/tests/cosmo/conftest.py`: wipe-список пополнен
  `gate_decision_trail` (без FK — порядок свободный); pg_client делает
  `create_all` обоих Base.

### 4. Тесты (test PG :5433, контракт COS-073/078)
- `orchestrator/tests/cosmo/test_gate_trail_durable.py` (новый, 13 тестов):
  - **RepoDurable (6)** — scratch-БД `_testpg.scratch_name("gate_trail")`:
    append+roundtrip полей, newest-first, trail по run (хронология,
    изоляция чужих run), фильтр gate×run, **restart-survival** (dispose
    engine → новый engine читает запись — симуляция смерти процесса),
    evidence_ids JSONB roundtrip;
  - **TestApiTrail (7)** — через `pg_client`:
    * `test_decision_persisted_before_response` — после возврата POST-ответа
      строка УЖЕ в PG (читается отдельным engine мимо приложения —
      write-before-response + restart-proof);
    * read-path по gate (newest-first, 3 решения) и по run (хронология,
      2 gate одного run, empty trail);
    * policy_snapshot захвачен (семантическая сверка — policy_json
      нормализуется `GatePolicyRule` добавлением `max_count`);
    * back-compat payload → trail с `run_id=NULL`;
    * unknown gate → 404.

## Верификация
- Trail-сет: **13/13 passed** (изолированно и в комбинированных прогонах).
- Transfer/migration focused (`--noconftest`): 73 passed (lease 27 +
  registry durable + migrations 14 + reconciliation 10 + repo trail 6) —
  регрессий нет.
- Gates-поверхности (api_routes + deps_guard + surface_auth +
  metrics_trends): 59/59 passed (повторный прогон; единичные фейлы в
  первом прогоне — межпроцессная гонка на общем test PG).
- Полный сет: **2191 passed / 2 skipped**; фейлы — **только чужие WIP**:
  * `test_rbac*.py` счётные матрицы — WIP воркера добавил `Action.BUILD_RUN`
    (rbac.py/deps.py модифицированы), счётчики в тестах ещё не обновлены
    (`AttributeError: Action has no attribute BUILD_RUN` без их правки —
    подтверждено stash-пробой, проба откачена, stash пуст, WIP цел);
  * Luna project/app API + integration/ — их WIP-поверхности (COS-080);
  * число фейлов плавает (15↔25) из-за конкурентных pytest-сессий на общем
    test PG — известное ограничение стенда (shared cosmo_test).
- **Попутный фикс инфры:** wipe-порядок в conftest — `evidence_ledger`
  удалался ПОСЛЕ `runs` → FK `evidence_ledger_run_id_fkey` ронял wipe и
  каскадно следующие тесты (проявилось с новым evidence_writer чужого WIP).
  Перенесён перед `runs` — каскад (10+ фейлов) устранён.

## Границы (по карточке)
- Не тронуто: миграционная цепочка (FROZEN), transfer API (Apex COS-077),
  notification surfaces (Flash COS-079), integration-фикстуры Luna (COS-080),
  BACKLOG (метит Максим).
- Commit/push — только по явной команде.

## Инвариант для эксплуатации
Решение gate невозможно зафиксировать без записи в `gate_decision_trail`
(одна транзакция). Рестарт процесса API не теряет историю (PG). Аудит
append-only: строки trail никогда не изменяются и не удаляются.
