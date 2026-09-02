# COS-080 — Steel Thread integration suite: Domain → App → Bricks → Compile → Run → Batch → Gate → Evidence

> **Дата:** 2 сентября 2026. **Исполнитель:** Luna.
> **Карточка:** BACKLOG.md COS-080 (строка 351).
> **DoD:** сквозной сет API-тестов на изолированном PG (:5433/cosmo_test) зелёный
> ×3 подряд, в т.ч. параллельно с миграционными; recovery-рестарты без дублей;
> честные ошибки контракта в негативах.

## 1. Что сделано

### 1.1 Harness (`orchestrator/tests/cosmo/integration/conftest.py`)

- **Канонический путь без дублирования движков:** харнесс использует ленивый
  синглтон приложения `db.session.get_engine()`/`get_sessionmaker()` — как в
  проде. Родительский conftest (COS-073) форсит `COSMO_DATABASE_URL` на тестовый
  PG до импорта app. Никаких собственных engines в тестах.
- **Override только идентичности:** `get_current_principal` → integration-admin
  (`ADMIN_SEC`, `domain_id="it-integration"`, `is_system_admin=True`, zone=zr).
  `get_db` НЕ переопределяется — сессии ходят через продовый dependency.
- **`wipe()`** через app-сессию: nullify circular FK (`apps.pipeline_plan_id`,
  `runs.batch_id`) → ordered DELETE по `_WIPE_ORDER`.
- **`_WIPE_ORDER`** (урок FK-топологии): `notification_*` → `evidence_ledger` →
  `plan_bricks` → `batches` → `gates` → `runs` → `releases` → `pipeline_plans` →
  `pipeline_bricks` → `repo_bindings` → `apps` → `groups` → `domains`.
  `evidence_ledger` обязана идти ДО `runs`/`batches` (FK на оба).
- **`restart()`** эмулирует смерть процесса: `client.aclose()` →
  `dispose_engine()` (все соединения убиты) → сброс sync-синглтонов
  (`_sync_engine`, `_SyncSessionLocal`) → новый клиент. Данные в PG не трогаются —
  стейт восстанавливается из БД.
- **COS-075 loop-safety:** fixture на setup И teardown вызывает
  `dispose_engine()` — синглтон-движок привязан к loop'у, каждый pytest-asyncio
  тест получает свежий loop.

### 1.2 Сьют (`test_steel_thread_integration.py`, 12 тестов)

| Тест | Что фиксирует |
|---|---|
| `test_full_steel_thread_happy_path` | полный Steel Thread: domain → app → bricks → compile (hash) → run → batches running/passed → gate pass → run succeeded → evidence log/finding/decision → verify-chain OK, tamper-free |
| `test_repeated_compiles_and_runs_are_rejected_not_duplicated` | повторный compile того же app → отказ; повторный run того же плана → отказ; дублей нет |
| `test_same_inputs_no_evidence_duplicates` | повторные evidence на тот же run+batch+type → отказ (уникальность), цепочка валидна |
| `test_restart_between_steps_restores_state_from_pg` | 2× `restart()` между шагами: plan/batch/gate/run читаются из PG после смерти движка, batch продолжается, decision сохраняется, дублей нет |
| `test_invalid_pipeline_cycle_detected` | cycle в `depends_on` → compile отказывает с перечнем кирпичей |
| `test_compile_with_missing_bricks_is_404` | ghost-brick → 404 с перечнем недостающих; план не создан |
| `test_run_on_missing_plan_and_app_on_missing_domain` | 404-контракт: run без плана (домен существует), app без домена, run в несуществующем домене (проверяется раньше плана) |
| `test_gate_reject_blocks_run` | decision=block → gate blocked, run → blocked (терминальный, finished_at), evidence отражает reject |
| `test_evidence_on_missing_run_is_404` | evidence по ghost-run → 404 |
| `test_evidence_fk_violation_is_honest_contract_error` | FK-нарушение (batch чужого плана) → `IntegrityError`, не маскировка |
| `test_evidence_invalid_type_rejected_by_check_constraint` | invalid enum → `(IntegrityError, DBAPIError)` с "evidence_type" (CHECK `ck_evidence_type`) |
| `test_tampered_content_hash_is_visible_in_chain` | подменённый `content_hash` в БД виден в цепочке (см. Observation 2) |

Контракт записи evidence: единственный существующий путь — ORM-сущность
`EvidenceLedgerEntry` (API отдаёт цепочку и верификацию, не приём);
`content_hash = sha256(payload)`.

## 2. Ключевые открытия (контракт доменного доступа)

### 2.1 Ownership-masking — 404 вместо 403 (продуктовое поведение, COS-061/067)

`domain_guard.verify_ownership()` при несовпадении домена ресурса и домена
вызывающего бросает **HTTP 404** («Run 'X' not found»), не 403 — сознательно,
чтобы не раскрывать существование ресурса. Для system admin `resolve_caller_domain()`
возвращает `X-Cosmo-Domain` header или **`"default"`** — без заголовка админ
«видит» домен default → честный 404 на любой чужой ресурс. Это не баг БД — это
контракт, и suite его фиксирует: все read-запросы (GET/PATCH runs, batches,
plans, gates) обязаны нести `X-Cosmo-Domain`.

### 2.2 Два механизма доменной проверки (важно для будущих тестов)

- `runs.py` GET/PATCH-status: `resolve_caller_domain(principal, caller_domain)` —
  нужен заголовок;
- `evidence.py:57/91/132`, `gates.py` (create/decision/get), `pipelines.py`
  (compile): **`principal.domain_id` напрямую** — заголовок игнорируется,
  совпадение `resource.domain_id == principal.domain_id` обязательно.

Следствие для тестов: все сущности suite живут в одном домене = домену
integration-админа (`it-integration`); уникальность обеспечивают id сущностей.

### 2.3 Мелкие контракты, пойманные тестами

- `Gate`-схема НЕ содержит `plan_id` (только id/type/position/policy/decision/*);
  `run["gates"]` — список **id-строк**, не объектов.
- POST /runs: доменная проверка (`Domain not found`) выполняется **раньше**
  план-проверки — негатив «run без плана» требует существующий домен.
- asyncpg invalid enum value → `DBAPIError`, не `IntegrityError` — негативные
  CHECK-тесты ждут кортеж.

## 3. Верификация (acceptance)

| Проверка | Результат |
|---|---|
| Интеграционный сет | **12 passed** |
| ×3 прогона подряд | 12/12, 12/12, 12/12 — 4.95s / 5.55s / 5.08s |
| Параллельно с миграционными (`test_migrations.py` + `test_migration_reconciliation.py`) | 12 passed (4.64s) + 24 passed (37.40s) одновременно, без cross-contamination |
| Полный снапшот `orchestrator/tests` | **2274 passed, 2 skipped** (98.90s); базлайн 2200 passed / 16 failed вне scope — 16 фейлов уехали (чужие фиксы доехали), регрессий нет |
| Чистота тестового PG после прогона | domains/runs/evidence = 0 (teardown wipe работает) |

Debug-артефакты убраны: `_debug_probe.py`/`_debug_probe2.py`/`_debug_split.py`
удалены, loop-probe middleware и wipe-зонды из conftest сняты, PG-аудит-триггер
удалён.

## 4. Observations (для продукта, вне scope коробки)

1. **404-masking ownership + несимметричная доменная проверка** — половина
   read-путей резолвит caller-domain из заголовка, половина берёт
   `principal.domain_id`. Для человека с заголовком evidence-путь behaves
   иначе, чем runs-путь. Не блокер (админ единый домен проходит), но контракт
   стоит зафиксировать в ADR на COS-061/067.
2. **`verify_and_get` на PG пересчитывает хеши от текущих строк** — tamper/replay-
   детект, работавший in-memory, на PG не срабатывает для подменённого
   `content_hash`: подделка становится «легальной» головой цепочки. Suite честно
   фиксирует видимость подмены (`test_tampered_content_hash_is_visible_in_chain`)
   как текущее поведение. Усиление (бесконечная ретро-верификация от genesis) —
   кандидат в отдельную карточку.
3. **`_IncludedRouter`-обёртки** в `app.routes` (main.py include_router через
   нестандартный wrapper) — маршруты уникальны, дублей нет, но отладка роутинга
   требует распаковки `original_router`.

## 5. Файлы

- `orchestrator/tests/cosmo/integration/conftest.py` — harness (этот PR)
- `orchestrator/tests/cosmo/integration/test_steel_thread_integration.py` — 12 тестов (этот PR)
- `orchestrator/tests/cosmo/conftest.py`, `_testpg.py` — использованы как есть (COS-073)
- `orchestrator/cosmo/api/domain_guard.py`, `routes/{runs,evidence,gates,pipelines,domains}.py` — только чтение (контракт)
