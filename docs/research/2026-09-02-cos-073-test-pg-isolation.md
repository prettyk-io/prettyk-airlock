# COS-073 — Test PG Isolation and Stand Discipline

> **Дата:** 2 сентября 2026 · **Исполнитель:** Buddy · **Статус:** ✅ DONE
> **Зависимость:** COS-071 (runtime-gate). **Связанные:** COS-064 (flake-разбор), COS-070 (scratch-only), COS-067 (периметр, WIP чужой)

## 0. TL;DR

Структурная изоляция тестов от dev-стенда сдана. pytest теперь физически не
может дотянуться до живой cosmo-БД (отдельный PG-контейнер на :5433 + guard
на импорте), stand-lock сериализует доступ к стенду, порт-канон MinIO
9100/9101 синхронизирован в hardening-доках. Полный тест-сет зелёный
(2118 passed), runtime-gate exit 0, живая БД доказанно не получает DELETE.

## 1. Что сделано

### 1.1 Тестовый PG (`services/docker-compose.test-pg.yml`)

| Параметр | Значение |
|---|---|
| Контейнер | `cosmo-test-pg` (postgres:16-alpine) |
| Host-порт | **5433** (5432 = dev-stand cosmo-postgres, тестам запрещён) |
| БД | `cosmo_test` (имя отличимо от dev `cosmo`) |
| Volume | `cosmo_test_pg` (отдельный; `down -v` — безопасный сброс тестовых данных) |
| Сеть | отдельный bridge `test-pg-net` (не kdt-net/cosmo-net) |
| Подъём | `docker compose -f services/docker-compose.test-pg.yml up -d` |

### 1.2 Контракт `_testpg.py` (`orchestrator/tests/cosmo/`)

Единая точка резолва тестового URL для всех тестов:

- URL: env `COSMO_TEST_DATABASE_URL` или дефолт
  `postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test`
  (**127.0.0.1, не localhost** — `localhost` резолвится в `::1`, который
  перехватывает WSL-relay; факт доказан в COS-064);
- **guard `refuse_dev_stand`**: любой URL на порт 5432 (явный ИЛИ неявный —
  URL без порта для postgres по умолчанию 5432) отвергается `RuntimeError`
  на импорте — тест-сет падает громко на сборке, не тихо бьёт в dev;
- хелперы: `asyncpg_dsn()`, `psycopg2_url(dbname)`, `admin_dsn()`,
  `pg_available()`.

### 1.3 Перевод тестов (11 файлов)

Хардкод `localhost:5432/cosmo` убран из: `conftest.py`,
`test_email_adapter.py`, `test_notification_manager/worker/triggers/sse_sessions.py`,
`test_migrations.py`, `test_migration_reconciliation.py`,
`test_transfer_registry_durable.py`, `test_transfer_failed_gateway_lease.py`,
`test_steel_thread.py` (reason/docstring). Fake-DSN в негативных тестах
маскировки (`test_security_perimeter_negative`, `test_vault_secret_ref`)
намеренно не тронуты — они не подключаются к БД.

Ключевые решения:

- **conftest принудительно перекрывает `COSMO_DATABASE_URL`** (не setdefault)
  до импорта продуктовых модулей: `session.py` фиксирует `DATABASE_URL`
  константой при импорте, и чужой env из внешнего окружения мог протащить
  тесты на живую БД.
- **`alembic_cycle` нейтрализует env на время command-вызовов**
  (`migration_verifier.py`): `alembic/env.py:_target_url()` приоритизирует
  env `COSMO_DATABASE_URL` над `cfg sqlalchemy.url` (контракт subprocess-тестов),
  из-за чего in-process цикл в pytest-процессе уезжал мимо scratch прямо в
  cosmo_test. Без фикса миграционные тесты падали на свежем цикле
  (`fk_apps_pipeline_plan_id does not exist` — create_all-схема cosmo_test
  использует ORM-имена FK). Fix сохраняет subprocess-контракт нетронутым.
- `test_cycle_preserves_dev_db` → `test_cycle_preserves_main_db`: проверка
  «main-БД не тронута scratch-циклом» теперь легитимно живёт на тестовом
  инстансе вместо живой БД.

### 1.4 Stand-lock (`services/scripts/stand-lock.ps1`)

Файл-протокол сериализации стенда (runtime-артефакт в `$env:TEMP`,
вне git): `acquire / release / status / force-release` (force требует
`-Reason`), TTL 240 мин, expired-лок перехватывается, corrupted = stale.

- **runtime-gate интегрирован**: acquire в начале, release на всех выходах;
  занятое окно → **exit 3 (STAND-BUSY)**, честный отказ без прогонов.
- **pytest lock не нужен**: тесты идут только на :5433 и физически не
  трогают стенд — сериализация им больше не нужна. Это и есть смысл пакета.

### 1.5 Порт-канон (хвост COS-064/COS-071)

- `verify-hardening.ps1` / `verify-hardening.sh`: `DEV_INFRA_PORTS` =
  `9100/9101` (host-канон; container-internal остаются 9000/9001);
- `HARDENING_CHECKLIT.md`: MinIO-строки помечены host-каноном, новая
  секция 1.3 (тестовый PG + stand-lock), дата обновлена;
- шапка `docker-compose.yml` синхронизирована с реальными биндами.

### 1.6 Багфиксы по пути

| Баг | Фикс |
|---|---|
| `test_caddy_uses_8180_not_8080`: `UnicodeDecodeError cp1251` на UTF-8 compose | `read_text(encoding="utf-8")` (cp1251-хвост из Routing-заметки) |
| `alembic_cycle` уезжал мимо scratch в pytest-процессе | env-нейтрализация на время command-вызовов (см. 1.3) |
| `localhost` в тестовом URL — риск WSL-relay `::1`-перехвата | дефолт `_testpg` на `127.0.0.1` (факт COS-064) |
| gate/smoke без auth → 401 после закрытия периметра (COS-067 WIP) | dev-токен `Bearer gate-agent:admin_sec` (контракт frontend `getCosmoAuthToken`, `deps.py` даёт is_system_admin) |

## 2. Acceptance

### 2.1 Полный pytest-сет на тестовом PG

- **run 2 (финальный): 2118 passed / 0 failed / 2 skipped** за 91s
  (baseline COS-070: 2029 passed — сет вырос, ничего не сломано).
- run 1: 5 failed → разобраны: 1 = cp1251 encoding (фикс выше),
  4 = `test_transfer_security_matrix` (см. Follow-up — флакнули в run1,
  в run2 и изолированно 26/26 зелёные).

### 2.2 Живая БД не получает DELETE-серий

Доказательство трёхуровневое:

1. **Код-свип**: 0 живых ссылок на `:5432` в тестах (кроме guard-модуля
   `_testpg` и fake-DSN негативных тестов).
2. `pg_stat_activity` живого PG во время/после прогонов: только
   `cosmoport2` (API, 172.22.0.5) и `cosmo_gitea` (172.22.0.9). Ни одного
   host-коннекта от pytest.
3. Контрольный эксперимент: `log_statement=all` на **тестовом** инстансе →
   контрольный subset-прогон → **96 DELETE-запросов в логе :5433**; на живой
   БД (log_statement=none, диагностика COS-064 отключена) — relying на
   п.1-2. После эксперимента test-pg возвращён в `log_statement=none`.

### 2.3 Runtime-gate

| Прогон | Результат |
|---|---|
| run 1 | FAIL: smoke/restart/sse = 401 Unauthorized (периметр закрыт COS-067 WIP). migration/clean-start/full-profile/dep-failure = PASS — изоляция не при чём |
| run 2 (после токен-фикса) | **GATE OK, exit 0**: 6 PASS + 1 DEVIATION (`/ready=200 degraded`, известная, PO-решение pending) |

Gate сам взял stand-lock (`[ACQUIRED] owner=buddy-cos073`) и отдал его на
выходе — протокол работает в бою.

### 2.4 Порт-канон

`compose = hardening-доки = verify-скрипты` = 9100/9101 (host), 9000/9001
(internal). Проверено grep'ом.

## 3. Сигналы для PO / владельцев (не блокеры)

1. **security_matrix ×4 flaky** — run1 полного прогона упал, run2 зелёный,
   изолированно зелёные. Подозрение: кросс-файловый стейт (in-memory
   registry / pg_client overrides). Владелец transfer-тестов.
2. **dep-failure сдвинулся 503 → 200**: утром (COS-064) `/ready` при PG down
   отдавал 503 (критерий PASS), сейчас 200 `degraded` — чужой WIP `main.py`
   (COS-067 зона). DEVIATION честно зафиксирован gate'ом; PO-решение по
   критерию всё ещё pending.
3. **Дубли `_pg_available`/`_pg_reachable`** в notification/steel-тестах —
   механика работает (URL берут из `_testpg`), но тела дублируют
   `_testpg.pg_available`. Унифицировать в следующий пакет.
4. **env.py приоритет env > cfg** — хрупкий контракт: любой будущий
   in-process alembic-вызов в процессе с установленным env молча уедет
   мимо cfg-URL. Точечный фикс сделан в `alembic_cycle`; системно — кандид
   в продуктовый пакет (владелец migrations).
5. Порт **5174 (WSL-relay)** остаётся инфра-хвостом Buddy (Routing-заметка).

## 4. Файлы пакета

| Файл | Изменение |
|---|---|
| `services/docker-compose.test-pg.yml` | **новый** — тестовый PG (:5433, cosmo_test) |
| `orchestrator/tests/cosmo/_testpg.py` | **новый** — URL-контракт + guard + хелперы |
| `orchestrator/tests/cosmo/conftest.py` | перевод на _testpg, принудительный env, guard |
| `orchestrator/tests/cosmo/test_*.py` (10 файлов) | перевод с хардкода :5432 |
| `orchestrator/cosmo/db/migration_verifier.py` | alembic_cycle: env-нейтрализация |
| `services/scripts/stand-lock.ps1` | **новый** — протокол сериализации стенда |
| `services/scripts/runtime-gate.ps1` | stand-lock интеграция (exit 3), dev-токен |
| `services/scripts/smoke-delivery.ps1` | dev-токен для /api/v1/domains |
| `services/scripts/verify-hardening.ps1/.sh` | DEV_INFRA_PORTS 9100/9101 |
| `services/scripts/HARDENING_CHECKLIT.md` | MinIO host-канон, секция 1.3, дата |
| `services/docker-compose.yml` | шапка-комментарий (порт-канон) |
| `docs/BACKLOG.md` | карточка → DONE, acceptance-заметка |

## 5. Как жить дальше

```powershell
# перед pytest (один раз):
docker compose -f services/docker-compose.test-pg.yml up -d

# pytest — не трогает стенд вообще:
.venv\Scripts\python.exe -m pytest orchestrator\tests\cosmo -q

# стенд-работа (gate, миграции, ручные прогоны):
services\scripts\stand-lock.ps1 acquire -Owner "<имя>" -Purpose "<пакет>"
# ... работа ...
services\scripts\stand-lock.ps1 release -Owner "<имя>"
# runtime-gate берёт/отдаёт lock сам; занято → exit 3
```