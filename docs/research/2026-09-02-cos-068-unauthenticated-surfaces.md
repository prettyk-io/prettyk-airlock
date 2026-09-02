# COS-068 — Unauthenticated Surfaces Hardening

**Дата:** 2026-09-02
**Владелец:** Apex (worker, Cosmo → Control Plane)
**Статус:** implemented + accepted
**Пакет:** follow-up finding 1 из отчёта COS-067 (deps._guard Domain Binding Hardening)

---

## 1. Контекст

COS-067 закрыл доменный binding в `deps._guard` (3 режима: `header`, `header_bound`,
`identity`), но приёмочный аудит маршрутов выявил, что значительная часть API-поверхностей
оставалась **полностью анонимной**: без `get_current_principal`, без capability, без
доменного binding. Анонимный клиент мог читать домены, аудит, метрики, findings,
evidence, artifacts-status, список проектов/KITS/release-types и — критично —
выполнять мутации: `POST /audit` (инъекция записей аудита), `POST /artifacts/cleanup`,
`POST /projects/{id}/apps`, создание release-type/release-batch.

COS-068 закрывает эту поверхность единообразно, не ломая контракт transfer-маршрутов
(COS-066) и не затрагивая зоны других исполнителей.

---

## 2. Что сделано

### 2.1 Новые guard-фабрики в `cosmo/api/deps.py`

| Фабрика | Поведение |
|---|---|
| `require_principal()` | Auth-only барьер: `get_current_principal` сам возвращает 401 анониму; любой аутентифицированный principal проходит. Domain-scoping при необходимости выполняет handler. |
| `require_system_admin()` | 401 — аноним, 403 «System administrator role required» — аутентифицированный не-админ. Для привилегированных мутаций, не покрытых capability-моделью. |

Обе вставлены до `_get_require_domain` (порядок фабрик в файле).

### 2.2 Матрица guard'ов по маршрутам (12 файлов)

| Файл | Поверхность | Guard |
|---|---|---|
| `repos.py` | tree / file / PUT file / POST commit | `require_principal()` |
| `repos.py` | `POST /commit-and-run` | `require_capability(SCAN_START, identity)` + binding: не-админ — только свой `body.domain_id` (403 на чужой, до db-операций); initiator/role из principal |
| `domains.py` | чтения | `require_principal()` |
| `domains.py` | POST / PUT / DELETE | `require_system_admin()` |
| `audit.py` | чтения + `/export/csv` | `require_principal()` |
| `audit.py` | `POST /audit` | `require_system_admin()` — закрыта дыра инъекции аудита |
| `metrics.py` | `/trends`, `/sla`, `/compliance/audit` | `require_principal()` |
| `metrics.py` | `GET /metrics` | **намеренно открыт** — Prometheus scrape-контракт; агрегированные счётчики; сетевая изоляция = Caddy (Buddy). Рационал в docstring |
| `status.py` | `/dashboard` | `require_principal()` |
| `evidence.py` | все 3 handler'а | `require_principal()` + для не-админа `verify_ownership(run.domain_id)` — чужой run → 404 ghost |
| `findings.py` | `GET /search` | `require_principal()` + доменный override: не-админ ищет только в своём домене (`principal.domain_id` или `__no_domain__`), клиентский `domain_id` игнорируется; админ фильтрует свободно |
| `artifacts.py` | `/cleanup` | `require_system_admin()` |
| `artifacts.py` | `/retention/status` | `require_principal()` |
| `gates.py` | GET list/get | `require_principal()` |
| `gates.py` | POST / PUT / DELETE | `require_capability(PIPELINE_CONFIGURE, identity)` + ownership-цепочка `_resolve_plan_domain` (plan.app_id → Application.domain_id); чужой план → 404 ghost |
| `release_batches.py` | release-type list/get, batch list/get | `require_principal()` |
| `release_batches.py` | release-type create/update | `require_system_admin()` |
| `release_batches.py` | create release-batch, run batch | `require_capability(RELEASE_CREATE, identity)` |
| `projects.py` | 6 project-handler'ов + graph/team | `require_principal()` (был полностью анонимный `add_app_to_project`) |
| `projects.py` | 3 KITS-handler'а | `require_principal()` |

### 2.3 Намеренно не тронуто

| Поверхность | Причина |
|---|---|
| `/live`, `/health` (`api/health.py`) | Docker/Caddy healthcheck — зона Buddy |
| `GET /metrics` | Prometheus scrape-контракт |
| `transfer.py` | COS-066 — своя auth-матрица на handler-уровне |
| `builds.py`, `deployments.py` | уже principal + `verify_ownership` (COS-067); capability-дополнение — pass 2 |
| `notifications.py` | зона Flash (COS-055/056); 4/7 handler'ов уже имеют principal |

---

## 3. Ключевые решения

1. **Read-поверхности — auth-only, без capability.** Базовый барьер: аноним 401,
   аутентифицированный — читает. Capability-гранулярность на чтениях — pass 2
   (когда будет real principal-domain фильтрация на уровне списков).
2. **Привилегированные мутации без capability-семантики → `require_system_admin`.**
   Управление доменами, прямая запись в audit trail, очистка артефактов,
   справочник release-type'ов — это platform-admin операции, не доменные.
3. **Доменные мутации → capability + identity binding** (паттерн COS-067):
   `commit-and-run` (SCAN_START), gates CRUD (PIPELINE_CONFIGURE),
   release-batch (RELEASE_CREATE).
4. **Gates ownership через план.** `PipelinePlan` не имеет собственного `domain_id`
   — домен резолвится цепочкой `plan.app_id → Application.domain_id`
   (хелпер `_resolve_plan_domain` в `gates.py`). Чужой план → 404 (anti-enumeration).
5. **Findings domain-override.** Не-админ не может расширить поиск на чужой домен:
   `effective_domain = domain_id if admin else (principal.domain_id or "__no_domain__")`.
   `__no_domain__` даёт заведомо пустой результат вместо глобального поиска.
6. **binding до db-операций** в `commit-and-run`: сравнение `body.domain_id` с
   principal происходит до любых обращений к БД — негативные тесты не требуют данных.

---

## 4. Тесты

### 4.1 Новый `tests/cosmo/test_surface_auth_regression.py` — 39 тестов

- Anonymous → 401 на 16 auth-only read-поверхностях (параметризовано).
- Открытые поверхности остаются открытыми: `/metrics`, `/live`, `/health`.
- USER → 403 на system-admin мутации (domains POST, audit POST, artifacts cleanup,
  release-type POST/PUT) и capability-поверхности (gates create, commit-and-run).
- USER → 200 на 10 auth-only reads; evidence ghost → 404.
- Gates create ownership-цепочка: USER → 403, foreign SERVICE_ADMIN → 404 ghost,
  own-domain SERVICE_ADMIN → 201 (HTTP, с реальным планом в test-PG).
- commit-and-run binding: foreign domain_id → 403.
- Findings domain-override (unit, monkeypatch `FindingSearchEngine.search_pg`):
  не-админ → свой домен; без домена → `__no_domain__`; админ → домен из запроса.

### 4.2 Обновлённые существующие тесты (прямой вызов handler'ов)

- 5 файлов получили `principal=` в direct-call (13 вызовов): `test_int_012_013_016_steel_thread.py`,
  `test_final_luna_001.py`, `test_lr_persist_api_visiblity.py`, `test_nx_luna_integration.py`,
  `test_post_luna_001_semantic_boundary.py` — системный админ `PrincipalContext`.
- `test_sod_and_transfer_linear.py` CLN-007 (2 теста): добавлен mock-`Application`
  с `domain_id` в `db.get` side-effect — новая ownership-цепочка `create_gate`.
- `test_transfer_security_matrix.py`: `_ensure_domain` теперь создаёт домен под
  временным system-admin override с restore прежнего principal (POST /domains
  стал system-admin only).

### 4.3 Результат

| Прогон | COS-067 (фон) | COS-068 |
|---|---|---|
| Полный suite | 2020 passed / 6–9 failed (фон) | **2117 passed / 1 failed / 2 skipped** |
| Единственный фейл | — | `test_caddy_uses_8180_not_8080` (известный фон: docker-стенд, port-boundary smoke) |

---

## 5. Инфра-находка: bootstrap test-PG (не кодовая регрессия)

Подъём свежего test-PG контейнера (`services/docker-compose.test-pg.yml`, порт :5433)
обнаружил **design-баг `migration_verifier.alembic_cycle()`** (Luna-зона):

`alembic/env.py::_target_url()` отдаёт **приоритет env `COSMO_DATABASE_URL`** над
`cfg sqlalchemy.url`. In-process `alembic_cycle()` строит scratch-URL, но команды
`command.upgrade/downgrade` выполняются по env-URL — то есть на **main test-БД**
(`cosmo_test`), а не на scratch.

- Раньше это маскировалось: `cosmo_test` была промигрирована Alembic'ом → имена
  FK совпадали (`fk_apps_pipeline_plan_id`) → цикл «проходил» (цикля main).
- На свежем volume `cosmo_test` создаётся conftest'ом через `create_all`
  (SQLAlchemy-имена FK) → `downgrade base` падает на `DROP CONSTRAINT`.
- Симптом «flaky 6↔9» из COS-067 — та же природа.

**Bootstrap-восстановление (выполнено, test-PG можно чистить свободно — COS-073):**
`cosmo_test` пересоздана пустой + `alembic upgrade head` (env `COSMO_DATABASE_URL`
на :5433). Схема теперь alembic-managed; миграционный кластер 53/53 зелёный;
conftest `create_all` становится no-op — pg_client-тесты не затронуты.

**Follow-up для Luna (карточка):** починить `alembic_cycle` — при in-process вызове
временно подменять `os.environ["COSMO_DATABASE_URL"]` на scratch-URL (и восстанавливать),
либо прокидывать URL через `cfg.attributes` в env.py, чтобы scratch был настоящим.
До фикса: при пересоздании volume test-PG обязателен bootstrap `alembic upgrade head`.

---

## 6. Findings для Cosmo

1. **Pass 2 — capability на остатках:** `builds.py`, `deployments.py` (сейчас
   principal + ownership, без capability), `projects.py` мутации (сейчас auth-only),
   read-поверхности без доменного scoping'а списков.
2. **notifications.py** — 4/7 handler'ов с principal; остальное — зона Flash
   (COS-055/056), туда не вмешивался.
3. **SSE-поверхности** (`sse.py`: 3 stream-эндпоинта) — не закрыты guard'ом;
   отдельная карточка после контракта аутентификации SSE (EventSource не шлёт
   заголовки стандартно).
4. **`preferences.py`** (GET/PUT) — проверен: уже имеет principal (не менялся).
5. Migration verifier design-баг — см. §5, карточка Luna.

---

## 7. Acceptance

- 0×500 на всей негативной матрице (аноним/USER/foreign admin) — только 401/403/404.
- Существующие HTTP-тесты зелёные без правок логики: conftest-админ
  (`is_system_admin=True`) проходит все guard'ы; `pg_client` override не тронут.
- Transfer-сет (135 тестов, COS-066) — зелёный.
- Полный suite: 2117 passed / 1 known-background failed / 2 skipped.
- Git: изменения в рабочем дереве, commit/push — по прямой команде Максима.
