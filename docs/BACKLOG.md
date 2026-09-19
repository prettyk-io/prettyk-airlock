# Бэклог Cosmoport 2.0

> **Ты:** Cosmo. **Исполнители:** Boss, Flash, Luna, Buddy.
> **Легенда:** 🔄 в работе · ⬜ ready · ✅ done · ❌ cancelled

---

## ✅ DONE — TRANSFER KERNEL / LANDING KERNEL

| ID | Кто | h | Результат |
|---|---|---:|---|
| **COS-050** | Flash | 8-10h | Provider-neutral TransferItem/TransferPlan, package modes, artifact planes, transport profiles, idempotent PackageRevision and SOD seam |
| **COS-053** | Flash | 12-16h | PackageBuilder, SHA-256 manifest, PreTransferValidator, LandingCheckReport and target landing state machine |

> **Acceptance:** приняты 1 сентября 2026. Worker reports 357 passed (51 new
> transfer-kernel + 306 existing); local verification of the key suites passed
> 87 tests. Acceptance covers multi-plane plans, metadata-only negative paths,
> checksum mismatch, duplicate revision, rejected target, recoverable bootstrap,
> reconcile and transport/bootstrap failure separation.
>
> **Follow-up:** Pydantic `PackageRevision` is conceptually immutable but not
> runtime-frozen; physical SOD/diode/gateway adapters, session lease/TTL,
> registry bridges and real target integration remain downstream work.

---

## ✅ DONE — SFERA / PROVIDER BOUNDARY WAVE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|

| **COS-054** | Boss | 10-14h | P1 | COS-053 | ✅ DONE — Offline importer и vendor-neutral DiodeAdapter: spool/chunk/resume/status без физического diode |
| **COS-049** | Luna | 6-8h | P3 | — | ✅ DONE — Sfera/ДиБ discovery evidence, legacy source-code map и redacted-contract checklist без выдуманных endpoints |
| **COS-058** | Apex | 20-24h | P0 | COS-050 + COS-053 | ✅ DONE — Transfer API boundary: create/validate/status/landing/reconcile endpoints with auth, durable error contract and integration tests |

### Порядок

1. COS-050 замораживает внутреннюю границу Cosmoport и не зависит от конкретной
   Sfera implementation.
2. COS-053 реализует общий package/landing kernel после контракта; он не зависит
   от конкретного Sfera provider.
3. COS-052 и COS-054 развивают самостоятельную provider/airgap линию.
4. COS-049 остаётся низкоприоритетным discovery item: он находится в backlog,
   но не блокирует общий transfer kernel. Legacy backend уже дал первичную карту
   Sfera API и release flow; продолжение ждёт tool/API access.
   **Принят 2 сентября 2026:** discovery pack консолидирован
   (`docs/research/2026-09-02-cos-049-sfera-redacted-contract-checklist.md`):
   карта кода (COS-068) + scrape-доказательство (2026-09-01) + alignment
   (COS-069) + redacted-contract checklist (A1–A9 запрос у команды Сферы,
   L1–L13 live-верификация по код-подтверждённым эндпоинтам, anti-checklist
   «не выдумывать», gates CONFIRMED). Focused Sfera/provider сет 234 passed;
   выдуманных эндпоинтов нет (UNKNOWN честно). Live-верификация остаётся
   гейтом CONFIRMED.
5. COS-051 не блокируется отсутствием vendor OpenAPI: legacy client даёт базовый
   push/pull/provisioning contract. Live OpenAPI нужен для verification и
   расширенных операций, а не для старта adapter seam.
6. Sfera в Cosmoport может оказаться optional artifact provider (raw/OCI/package)
   и/или transfer bridge; SOD, Portal events и Sfera artifact API не смешиваем.
7. COS-058 — ближайший API follow-up для Flash после принятого kernel; он не
   зависит от физического SOD/diode/gateway и не блокирует provider adapters.

---

## ✅ DONE — PROVIDER CAPABILITY / SFERA ADAPTER WAVE

| ID | Кто | h | Результат |
|---|---|---:|---|
| **COS-052** | Luna | 10-14h | Provider-neutral capability contract, honest UNSUPPORTED, matrices and fake provider fixtures |
| **COS-051** | Luna | 10-14h | Optional SferaProviderAdapter: raw/OCI push-pull, health, provisioning seam and contract tests |

> **Acceptance:** 1 сентября 2026. Focused tests: 43 passed (24 capability +
> 19 Sfera). Transfer/provider regression: 88 passed. Full Cosmo regression
> reported 1617 passed, 5 failed, 7 skipped: four stale table-count assertions
> caused by accepted COS-055 schema additions, one pre-existing Caddy encoding
> assertion. These failures are follow-up hygiene, not defects in COS-051/052.
>
> **Follow-up:** COS-049 for Sfera CORE OpenAPI export/live contract; Sfera
> exists/digest/promotion/quota/signature capabilities remain honest
> `UNSUPPORTED` until evidence arrives. TLS/mTLS live verification and Nexus
> pagination remain open.

---

## ⬜ READY — PROVIDER CONFORMANCE HARDENING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-060** | Luna | 20-24h | P1 | COS-051 + COS-052 | ✅ DONE — Provider conformance suite, TLS/mTLS config verification, digest/error normalization and adapter edge-case hardening |

> **Acceptance:** 2 сентября 2026. Focused provider/TLS/Sfera suite — **221
> passed**; transfer-kernel regression зелёный. Полный regression snapshot
> содержит только ранее известные/чужие failures. Live private-CA и live Sfera
> остаются follow-up, не ложная capability.

---

## ✅ DONE — INFRASTRUCTURE RUNTIME ACCEPTANCE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-063** | Buddy | 20-24h | P1 | COS-059 + COS-062 | ✅ DONE — Full core/full startup, 9/9 smoke, restart-preserves-state, SSE durability and dependency-failure verification |

> **Acceptance:** 2 сентября 2026. Clean cold start до `/ready=ok` — 16.3 s;
> smoke delivery — **9/9**; full profile — **10/10**; fresh Alembic upgrade —
> 8 шагов, 32 таблицы, head `d2e3f4a5b6c7`; restart recovery — 3.3 s;
> SSE keepalive через Caddy — PASS; idempotent rerun — 5.7 s. Исправлены
> Gitea bootstrap, Woodpecker grpc resolver (`passthrough:///`), side-DB init и
> migration-aware entrypoint. Отклонение: `/ready` при недоступном PostgreSQL
> возвращает `200 degraded`, а не `503`; это отдельный product/health follow-up.

---

## ✅ DONE — REGRESSION HYGIENE + LEGACY SFERA CONTRACT MAP

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-068** | Luna | 14-20h | P1 | COS-062 + текущие тест-поверхности | ✅ DONE — Schema-aware table-count assertions, global test-data teardown, legacy Sfera contract map from source |

> **Acceptance:** 2 сентября 2026. 4 stale table-count теста переведены на
> `>= 27` с привязкой к миграциям — локальный прогон **5 passed**. conftest
> teardown (`_wipe` после yield) закрывает утечку домена `test` глобально;
> A/B-проверка transfer suite — 26 passed на обоих conftest. Полный снапшот
> 2123 passed / 14 failed — все вне scope и колеблются от параллельной работы.
> Contract map: 14 эндпоинтов с файл:строка, push=Basic/pull=Bearer,
> VERIFY_NONE задокументирован как анти-паттерн. Источник —
> `D:\cosmo\cosmoport\backend` (в пакете был указан неверный путь, отклонение
> зафиксировано исполнителем). Capability matrix фактически **18**, не 19.
>
> **Follow-up:** matrix micro-PR одобрен → COS-069. Belt-and-suspenders
> изоляция доменов в transfer-тестах — владельцам COS-066/COS-067, не блокер.

## ✅ DONE — DURABLE TRANSFER REGISTRY + SCRATCH-DB HYGIENE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-070** | Boss | 20-24h | P1 | COS-062 + COS-058 | ✅ DONE — PgTransferRegistryRepository (Protocol + PG impl, 1:1 контракт с in-memory), миграция e4f5a6b7c8d9 на отдельном TransferRegistryBase, scratch-only alembic_cycle |

> **Acceptance:** 2 сентября 2026. Локальный прогон durable + migration
> reconciliation — **26 passed, 0 failed**. Dev-БД: d2e3f4a5b6c7 → e4f5a6b7c8d9
> (head, 35 таблиц). Полный cosmo: 2029 passed / 2 pre-existing failed —
> лучше baseline. Drift-check shared Base не сломан отдельной TransferRegistryBase.
> Контракт-дрифт-ловушки задокументированы (URL password masking, UoW flush
> порядок, ::1 wslrelay перехват, watchdog откат).
>
> **Follow-up:** врезка PgTransferRegistryRepository в routes/transfer.py —
> следующий пакет владельца transfer-поверхности после COS-067 (один поток
> на модуль).

## ✅ DONE — RUNTIME GATE AND OPERATIONS HARDENING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-071** | Buddy | 20-24h | P1 | COS-063 + COS-059 | ✅ DONE — Единый runtime-gate (7 чеков, JSON-отчёт, exit 0/1/2), flake-детект FLAKE-EXTERNAL, port-канон MinIO 9100/9101, PS 5.1 старт/стоп фиксы |

> **Acceptance:** 2 сентября 2026. Runs 8+9 подряд GATE OK (exit 0), нулевой
> residue. Корень «пропажи» доменов доказан PG-логом: чужой host-harness
> (pytest conftest + alembic downgrade) чистил живую cosmo-БД через
> localhost:5432; gate сериализуется и честно помечает интерференцию,
> продукт не обвиняется. DEVIATION `/ready=200 degraded` зафиксирован явно.
> **Перерегистрация:** пакет заявлен исполнителем как COS-064 — коллизия
> с принятой карточкой COS-064 (Flash, browser acceptance); номер заменён
> на COS-071. Имя research-файла историческое, SoT номеров — этот backlog.
>
> **Follow-up → COS-073:** HARDENING_CHECKLIT.md и verify-hardening.ps1/.sh
> всё ещё перечисляют MinIO на 9000/9001; синхронизация порт-канона.

## ✅ DONE — NOTIFICATION DELIVERY OPS

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-072** | Flash | 20-24h | P1 | COS-055/056/061/064 | ✅ DONE — Background outbox worker, SSE session-reuse + degraded/recovery, SKIP LOCKED race fix, deterministic e2e fixtures |

> **Acceptance:** 2 сентября 2026. e2e browser **10/10 × 2 подряд** в выделенном
> окне стенда; vitest **56/56**; build green; live degraded PASSED (18.4s);
> auto-delivery ~14s без POST /process. SKIP LOCKED race fix (worker↔helper)
> и `_wait_inbox_row` верифицированы в коде. Отчёт полностью принят.
>
> **Расхождение (зафиксировано PO-верификацией):** claim «pytest
> notification-линия 52/52» не воспроизводится: **3 теста падают
> детерминированно даже изолированно** (worker tick, 2×trigger persistence) —
> глобальный sessionmaker прибит к закрытому event loop'у per-test фикстур;
> `dispose_engine` в `trigger_db` покрывает не все фикстуры. Продуктовый
> дефект исключён (production-loop smoke зелёный) — это test-infrastructure.
> → **COS-075**.

## ✅ DONE — UNAUTH SURFACES PERIMETER + DOMAIN BINDING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-067** | Apex | 20-24h | P0 | COS-066 | ✅ DONE — deps._guard domain binding hardening: guard-фабрики `require_principal()` / `require_system_admin()`, 12 route-файлов закрыты, auth-regression suite 39 тестов |

> **Acceptance:** 2 сентября 2026. Код верифицирован (deps.py фабрики,
> повсеместный binding, `test_surface_auth_regression.py`). Независимый
> acceptance-прогон Buddy (COS-073): полный сет **2118 passed / 0 failed**
> на изолированном тестовом PG. Ранние PO-расхождения (404≠403, FK app)
> объяснены диагностированным артефактом среды: PO-прогоны без
> `COSMO_DATABASE_URL` били в живую cosmo-БД, где deployed worker съедал
> outbox-события и мутил стейт. Отчёт принят.
>
> **Сигнал Buddy:** gate/smoke переведены на dev-токен `user_id:role` —
> контракт auth-заголовка теперь зависит от этого периметра (frontend
> `getCosmoAuthToken`).
>
> **Follow-up:** Pass 2 (capability-гранулярность builds/deployments/projects,
> доменный scoping read-списков) → **COS-083**. Guards для 3 SSE-эндпоинтов
> `sse.py` → COS-079 (Flash).

## ✅ DONE — NOTIFICATION LOOP-SAFE ISOLATION + RECIPIENT IDENTITY + SSE TICKET

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-075** | Flash | 16-24h | P1 | COS-072 | ✅ DONE — Loop-safe notification test infrastructure, real recipient identity, SSE one-time ticket auth (HMAC, 60s TTL) |

> **Acceptance:** 2 сентября 2026. Код верифицирован: `loop_safe_engine_reset`
> в 4 PG-фикстурах conftest; `sse_tickets.py` (HMAC-SHA256, env
> `COSMO_SSE_TICKET_SECRET`); `POST /api/v1/notifications/sse-ticket`;
> `getSseTicket()` + ticket-connect в AlertHUD; `test_notification_identity.py`
> — раздельные inbox'ы. vitest **56/56**. Независимый acceptance-прогон Buddy
> (COS-073): notification-линия зелёная в полном сете **2118 passed / 0 failed**.
> Claim «60/60 связка» не воспроизводился только в невалидной PO-среде
> (живая БД) — расхождение снято, отчёт принят.
>
> **Зафиксированный tradeoff:** ticket stateless — replay возможен в окне
> 60s TTL. Принято PO для v1; one-time через Valkey GETDEL — опциональный
> follow-up в COS-079 (без жёсткой зависимости SSE→Valkey).
>
> **Follow-up → COS-079:** guards на 3 SSE-эндпоинта `sse.py`.

## ✅ DONE — TEST PG ISOLATION AND STAND DISCIPLINE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-073** | Buddy | 16-24h | P0 | COS-071 | ✅ DONE — Изолированный тестовый PG (cosmo-test-pg, host :5433, db cosmo_test, свой volume), conftest-контракт «никогда не трогать dev-stand БД» с import-time guard, stand-lock протокол + интеграция в runtime-gate (exit 3 при чужом окне), порт-канон 9100/9101 в hardening-доках |

> **Routing (Максим, 2 сентября 2026):** Buddy работает индивидуально с
> Максимом; **текущий пакет доделывает и сдаёт**. Новые Buddy-пакеты
> не назначаются до команды о его доступности. Инфра-хвосты на него же:
> cp1251 Caddy-тест, порт-канон в hardening-доках (9000/9001 → 9100/9101),
> порт 5174 (WSL-relay). До посадки COS-073 — PO-сериализация стенда
> сохраняется для остальных. **Инфра-хвосты закрыты этим пакетом** (кроме 5174).

> **Acceptance (2 сентября 2026):**
> 1. Полный pytest-сет на тестовом PG: **2118 passed / 0 failed / 2 skipped**
>    (baseline COS-070 не сломан, сет вырос с 2029).
> 2. Живая cosmo-БД чиста: код-свип — 0 живых ссылок на :5432 в тестах
>    (кроме guard-модуля и fake-DSN негативных тестов маскировки);
>    `pg_stat_activity` живого PG — только `cosmoport2` (API) и `cosmo_gitea`;
>    контрольный прогон с `log_statement=all` на тестовом инстансе поймал
>    **96 DELETE-серий на :5433 и ноль на живой БД**.
> 3. Runtime-gate повторно: **GATE OK, exit 0** (6 PASS + 1 известная
>    DEVIATION `/ready=200 degraded`). Первый прогон FAIL'нулся честно:
>    периметр API (COS-067 WIP) закрыл 401 — gate и smoke-delivery переведены
>    на dev-токен `user_id:role` (контракт frontend getCosmoAuthToken).
> 4. Порт-канон: `DEV_INFRA_PORTS` в verify-hardening.ps1/.sh = 9100/9101,
>    HARDENING_CHECKLIT.md + шапка docker-compose.yml синхронизированы.
>
> **Механика:** `_testpg.py` (tests/cosmo) — единая точка резолва тестового
> URL (`COSMO_TEST_DATABASE_URL` env или дефолт
> `postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test`); guard
> `refuse_dev_stand` отвергает :5432 (явный и неявный) на импорте; conftest
> принудительно перекрывает `COSMO_DATABASE_URL` до импорта продуктовых
> модулей (session.py фиксирует URL при импорте); `alembic_cycle` нейтрализует
> env на время command-вызовов (env.py приоритизирует env над cfg — иначе
> in-process цикл уезжает мимо scratch на cosmo_test). 11 тестовых файлов
> переведены с хардкода :5432. Подъём:
> `docker compose -f services/docker-compose.test-pg.yml up -d`.
>
> **Follow-up (не блокеры):** security_matrix ×4 флакнули в run1 полного
> прогона (run2 зелёный) — кросс-файловый стейт, владельцу transfer-тестов
> → **COS-077 (Apex)**; дубли `_pg_available`/`_pg_reachable` в части тестов —
> унификация на `_testpg.pg_available` → **COS-078 (Boss)**; dep-failure
> сдвинулся 503→200 (чужой WIP main.py, DEVIATION честно зафиксирован gate'ом,
> PO-наблюдение); порт 5174 (WSL-relay) → **COS-078 (Boss)** — пул Buddy
> закрыт решением Максима от 2 сентября 2026 (Buddy выведен из пула; активный
> пул: Apex, Boss, Flash, Luna).

## ✅ DONE — TRANSFER DURABLE REPO WIRING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-077** | Apex | 20-24h | P1 | COS-067 + COS-070 + COS-074 | ✅ DONE — Transfer API на durable PgTransferRegistryRepository, TRANSFER_FAILED/lease через API (423/409), ленивый синглтон-репозиторий (паритет COS-078), security_matrix flake устранён по корню (reset синглтона в autouse-фикстуре), 14 durable-API тестов |

> **Acceptance:** 2 сентября 2026. PO-прогон `test_transfer_durable_api.py +
> test_transfer_security_matrix.py` — **40 passed** (совпал). По отчёту:
> полный сет на тестовом PG ×2 — 2274/2/0; matrix зелёный ×3; restart-survival,
> идемпотентный TRANSFER_FAILED, lease-матрица до любой мутации. Отчёт принят.
>
> **Follow-up (адресный):** conftest `pg_client._wipe` не чистит `transfer_*`
> (отдельный TransferRegistryBase) → дополнить delete_order — **микро-хвост
> Boss** (включить в его следующий пакет после COS-081); параллельные
> worker-сессии на общем test-PG — источник one-off падений → scratch-DB
> паттерн Luna закреплён как норма для новых тест-файлов; sync-репозиторий
> в sync-обработчиках — принято, пересмотр при росте нагрузки.

## ⬜ READY — CAPABILITY-GRANULAR GUARDS PASS 2 + DOMAIN ACCESS UNIFICATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-083** | Apex | 20-24h | P1 | COS-077 | Capability-гранулярность guard'ов (builds/deployments/projects), доменный scoping read-списков, унификация резолва домена caller'а |

> **Scope:** (1) Pass 2 из COS-067: guard-фабрики тоньше, чем system-admin/
> principal — capability-гранулярность для builds/deployments/projects
> (write-операции требуют соответствующей capability, не просто principal);
> (2) доменный scoping read-списков: списки возвращают только сущности
> домена caller'а (сейчас отдаётся всё, 404-masking работает лишь на
> item-level); (3) унификация несимметрии из COS-080: runs резолвит caller
> из X-Cosmo-Domain, evidence/gates/pipelines сравнивают principal.domain_id
> напрямую — один контракт резолва для всех поверхностей; (4) regression
> suite расширяется на новые гранулы.
>
> **Acceptance:** write без capability → честный 403; read-список чужого
> домена пуст/404 по единому контракту; один резолв-путь домена во всех
> route-файлах (проверяется тестом-инвариантом); полный сет на тестовом PG
> без новых падений вне поверхности.
>
> **Out of scope:** ledger/verify (Luna COS-082), gate trail (Boss COS-081),
> notifications (Flash COS-079), миграционная цепочка (заморожена).
>
> **Follow-up найден при приёмке (→ COS-085):** legacy opaque-bearer в
> `get_current_principal`.

## ⬜ READY — OPAQUE-BEARER LEGACY CONTRACT CLOSURE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-085** | Apex | 4-6h | P1 | COS-083 | ✅ DONE — Строгий reject opaque bearer (только JWT-shaped токен, 401 на все legacy-форматы); keyword-blacklist удалён (ложные 401 на валидные JWT); +8 негативных форматов + секция 8 в auth-regression |

> **Scope:** находка при приёмке COS-079/COS-084 (PO live-smoke, подтверждено
> живьём): `get_current_principal` по legacy-контракту принимает любой
> opaque bearer (`garbage.sig.x` → 200 как Role.USER). Гварды роутов
> работают, но «аутентификация» мусорного токена — легальна. Решение:
> либо строгий reject всех opaque-форматов (401), либо явный allowlist с
> задокументированной причиной; попутно баг `domain_guard.py:72-73`
> (`.strip()` на FastAPI Header → AttributeError).
>
> **Acceptance:** `Bearer garbage.sig.x` на любом guarded-роуте → 401;
> негативные тесты на opaque-форматы в auth-regression suite; полный сет
> на тестовом PG без новых падений вне поверхности.
>
> **Out of scope:** e2e (Flash), notification-роуты (Flash), deps-фабрики
> granularity (сама COS-083).

## ✅ DONE — TEST & MIGRATION INFRA HARDENING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-078** | Boss | 16-24h | P1 | COS-073 + COS-076 | ✅ DONE — Канонический контракт БД-конфигурации (lazy URL + explicit-маркер, pop-env хак удалён), scratch schema verification, catalog-race isolation, `_testpg` унификация, порт 5174 зафиксирован |

> **Acceptance:** 2 сентября 2026. PO-верификация кода: lazy-резолв в
> session.py (`get_engine` lazy-init, URL не фиксируется при импорте),
> `cosmo_url_explicit`-маркер в env.py/migration_verifier — conftest-env не
> может увести alembic_cycle мимо scratch. Миграционный набор 24 passed ×3
> подряд; полный сет 2120 passed / 2 skipped (2029→2120); GATE OK. Красные
> зоны полного сета — только чужие поверхности: security_matrix flap (Apex
> COS-077) и незакоммиченный WIP Luna (COS-080). Порт 5174: канон
> `http://127.0.0.1:5174`, документирован CANONICAL-MONOLITH §17.2.
> Отчёт принят.

## ✅ DONE — GATE DECISION TRAIL DURABLE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-081** | Boss | 20-24h | P1 | COS-078 | ✅ DONE — Durable gate decision trail: `gate_decision_trail` (JSONB, append-only, без FK на frozen chain), one-transaction write-before-response, restart-survival, auth read-paths по gate и run |

> **Scope:** звено Gate в Steel Thread без durable decision trail —
> `GateDecisionRequest` существует только как API-модель: (1) PG-хранилище
> gate-решений (decision, policy_snapshot, run/batch link, initiator) на
> отдельном Base без правки замороженной миграционной цепочки — по образцу
> TransferRegistryBase (COS-070); (2) интеграция в API-путь gates; (3)
> recovery: решения переживают рестарт, read-path отдаёт историю по run;
> (4) интеграционные тесты на тестовом PG (:5433, `_testpg.py`).
>
> **Acceptance:** решение gate пишется в PG до возврата API-ответа; рестарт
> процесса не теряет историю решений; read-path отдаёт trail по run_id;
> полный сет на тестовом PG без новых падений вне новой поверхности.
>
> **Acceptance (PO, 2 сентября 2026):** trail-сет **13/13** на тестовом PG
> (scratch-репо с restart-survival, write-before-response читается отдельным
> engine, back-compat `GateDecisionRequest` без новых полей, 404); gates
> + engine + transfer-failed-lease поверхности — **89 passed**, регрессии
> нет. Задокументированное отклонение: таблица вне миграционной цепочки,
> idempotent `create_all` в lifespan и conftest — по прецеденту
> TransferRegistryBase, приемлемо. Попутный фикс: wipe-порядок conftest —
> `evidence_ledger` удаляется до `runs` (FK ронял wipe → каскад 10+ фейлов).
>
> **Зарегистрированные чужие фейлы полного сета (не блокер COS-081):**
> rbac-счётчики под `Action.BUILD_RUN`; Luna project/app routes — учесть
> в соответствующих потоках (Luna ждёт отправки COS-082).
>
> **Out of scope:** transfer API (Apex COS-077), notification surfaces
> (Flash COS-079), integration-фикстуры Luna (COS-080), миграционная цепочка
> (заморожена).

## ✅ DONE — NOTIFICATION OPS + DLQ OPERATOR SURFACE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-079** | Flash | 20-24h | P1 | COS-075 | ✅ DONE — SSE endpoint guards (one-time ticket, GETDEL), redaction value masking + recipient_id log hygiene, DLQ/retry operator surface в Control Station |

> **Scope:** (1) guards на 3 незакрытых SSE-эндпоинта `sse.py` (COS-067
> follow-up — тот же периметр, другой поток); (2) опционально one-time
> ticket через Valkey GETDEL — только если не создаёт жёсткой зависимости
> SSE→Valkey для degraded-режима, иначе остаётся deferred; (3) email
> follow-ups из COS-057: `redaction.py` маскирует только ключ sensitive-
> паттерна — значение утекает; `manager.py` пишет `recipient_id` в логи
> retryable/DLQ — маскировать/хэшировать; (4) продуктовая поверхность:
> DLQ/retry operator view в Control Station — список DLQ, честные empty/
> degraded/error состояния, retry-действие и provider failure visibility
> (backend endpoint list/replay в той же notification поверхности).
>
> **Acceptance:** SSE-эндпоинты отвечают 401 без валидного ticket;DLQ-поток:
> событие в DLQ видно оператору, retry уводит в sent или остаётся честно
> failed, state не врёт; redaction-тесты доказывают: значения sensitive-
> паттернов и recipient_id не встречаются в логах; vitest/build green,
> e2e зелёный ×2.
>
> **Out of scope:** deps.py (поток Apex), db/session.py (Boss COS-078),
> transfer API (Apex COS-077), email provider adapter (принят, COS-057).
>
> **Acceptance (PO, 2 сентября 2026):** notification-линия pytest — **113
> passed** (7 файлов) + SSE/email/multiplexer — **51 passed**; live-smoke:
> `GET /runs/{id}/stream` без ticket → **401** ✅, `/notifications/stream`
> без ticket → **422** (ticket обязателен) ✅; e2e ×2 — 16 passed; vitest
> 60/60, build OK; DLQ-операторская view с честными состояниями и retry.
>
> **Гэп, найденный PO-приёмкой (→ COS-084, must-fix):** mutation/ops
> эндпоинты notification-поверхности добавлены **без identity-guard**:
> `GET /dlq` → 200 без токена, `POST /dlq/{id}/replay` достижим без auth,
> `POST /process` → **200 без токена** (живьём), webhook-config CRUD и
> `GET /outbox/{id}` без `get_current_principal`. SSE-гарды из карточки
> закрыты, но периметр COS-067 на новых ops-роутах не продлён.
>
> **Отрепортованные follow-ups (не поверхность Flash):**
> - Boss: `alembic/env.py` вызывает `fileConfig()` с дефолтным
>   `disable_existing_loggers=True` → in-process migration-тесты глушат все
>   логгеры процесса, включая `cosmoport.notifications` — мина под любой
>   caplog-тест после migration-тестов (поверхность COS-078);
> - Buddy/prod: prod-nginx на 5174 не проксирует `/api` (отдаёт SPA-HTML +
>   405) — API-smoke валиден только напрямую на 8100 или через Caddy;
> - Apex: untracked steel-thread / transfer-security-matrix файлы флакают
>   на FK `it-happy` (pre-existing, чужая поверхность);
> - продукт-квирк COS-012/021: deep-link `?view=` проигрывает гонку
>   hydrate'у `usePreference('nav')` из `GET /preferences` → забран в
>   следующий пакет Flash.

## ✅ DONE — NOTIFICATION OPS IDENTITY GUARD (MUST-FIX)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-084** | Flash | 3-4h | **P0** | COS-079 | ✅ DONE — Identity-guard на все 7 ops/mutation-эндпоинтов notification-поверхности + 14 негативных 401-тестов |

> **Scope:** продлить периметр COS-067 на роуты, добавленные в COS-079/ops:
> `GET /api/v1/notifications/dlq`, `POST /dlq/{id}/replay`,
> `POST /process`, webhook-config CRUD (`list/create/delete`),
> `GET /outbox/{event_id}` → `Depends(get_current_principal)`; SSE-роуты
> не трогать (уже прикрыты ticket-гардом).
>
> **Acceptance (PO, 2 сентября 2026):** live-smoke подтверждён PO на 8100:
> `GET /dlq`, `GET /outbox/{id}`, `POST /process`, `POST /dlq/{id}/replay`
> — no-auth и `Bearer invalid-token` → **401**; `POST /process` анонимно
> больше не исполняется. Notification-линия pytest 130/130 (116 + 14
> COS-084), e2e ×2 — 17 passed с честным deep-link-тестом, vitest/build
> зелёные, cosmo-api пересобран и healthy.
>
> **Гэп за границей карточки (→ COS-085, Apex):** с валидным по legacy
> opaque-контракту `Bearer garbage.sig.x` guarded-роуты отвечают
> 200/404 — токен «аутентифицирует» как Role.USER. Это deps.py, не
> notification-поверхность.
>
> **Out of scope:** inbox-роуты (уже guarded), SSE ticket-механика,
> deps.py (поток Apex), e2e-поверхность.

## ✅ DONE — STEEL THREAD INTEGRATION HARDENING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-080** | Luna | 20-24h | P1 | COS-073 | ✅ DONE — Сквозной Steel Thread integration suite: 12 API-тестов Domain→App→Bricks→Compile→Run→Batch→Gate→Evidence на изолированном тестовом PG, идемпотентность/параллельность/чистота teardown |

> **Acceptance:** 2 сентября 2026. PO-прогон `tests/cosmo/integration` —
> **12 passed** (совпал с отчётом); параллель с миграционными (12+24) и
> полный снапшот 2274 passed / 2 skipped — по отчёту, красных зон в скоупе
> нет. Фикстуры в собственном `integration/conftest.py`, debug-артефакты
> удалены. Отчёт принят.
>
> **Открытия контракта (evidence-док):** 404-masking ownership (сознательный,
> COS-061/067); несимметричный резолв домена (runs — из заголовка,
> evidence/gates/pipelines — principal.domain_id напрямую); Gate-схема без
> plan_id; домен-проверка в POST /runs раньше план-проверки.
>
> **Follow-up:** tamper-детект на PG не срабатывает (verify_and_get
> пересчитывает хеши от текущих строк) → **COS-082 (Luna)**; несимметрия
> domain-access — зарегистрирована отдельной карточкой **COS-083 (Apex)**.

## ✅ DELIVERED — EVIDENCE TAMPER DETECTION ON DURABLE LEDGER

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-082** | Luna | 16-24h | P1 | COS-080 | ✅ DONE — Честный tamper-детект на durable evidence: verify проверяет сохранённые хеши/цепочку, а не пересчитывает от мутированных строк |

> **Scope:** открытие COS-080: verify_and_get пересчитывает хеши от текущих
> строк БД — подмена строки остаётся незамеченной. (1) верификация против
> сохранённых хеш-значений + rebuild цепочки с явным mismatch-результатом;
> (2) негативные тесты: UPDATE строки в PG → verify честно FAIL с указанием
> звена; (3) API read-path сигнализирует integrity-статус; (4) тесты на
> тестовом PG (:5433, `_testpg.py`).
>
> **Acceptance:** 2 сентября 2026. Якоря цепочки в `provenance_json`
> (frozen chain, новых колонок нет): verify сверяет СОХРАНЁННЫЙ `_chain_hash`
> с пересчитанным от сохранённого снапшота → UPDATE content_hash/provenance
> детектируется как hash_mismatch с указанием звена; DELETE середины →
> broken_link (genesis-связность); незапечатанная строка → unsealed;
> дубликаты → replay. Write-path: add → flush → seal (flush до подписи —
> иначе подписывается id=None). API: `integrity` = ok/tampered/unsealed,
> tampered_details/broken_links/unsealed_entries в evidence-ответе.
> Верификация: юниты 24 passed; integration 20 passed ×3 (12 COS-080 +
> 8 tamper-детект) на изолированном PG; детерминизм ×3. Evidence-док:
> `docs/research/2026-09-02-cos-082-evidence-tamper-detection.md`.
>
> **Follow-up:** внешний якорь головы (публикация last_hash вне БД) —
> задокументирован как граница threat model; гонка общих тестовых прогонов
> на :5433 (пересекающиеся wipe разных воркеров) — кандидаты: per-worker
> test PG или сериализация прогонов.
>
> **Acceptance (PO, 2 сентября 2026):** юниты **24 passed**; integration
> на изолированном `cosmo-test-pg-luna :5434` (COSMO_TEST_DATABASE_URL) —
> **20 passed**; tamper-модель верифицирована по доку. Гонка :5433 —
> решение: системный фикс = per-session/per-worker scratch-изоляция в
> пакете Boss (COS-076-расширение); `:5434` остаётся тактической lane
> Luna до его приземления. «Фантом 409» COS-080 закрыт (идемпотентный
> `_ensure_domain`, ghost-стейта в PG не было).
>
> **Кросс-воркер находки (внесены):** (1) opaque-bearer гэп deps.py →
> **COS-085**; (2) контракт-конфликт `caller_domain` (Apex) vs
> domain-free `test_final_luna_001` — решение PO: направленность Apex
> верна (выравнивание с COS-067 domain binding), Luna обновляет тест
> после acceptance COS-083; (3) баг `domain_guard.py` `.strip()` на
> Header → в поверхности COS-083, отрепортовано Apex'у; (4)
> `test_cycle_preserves_main_db` падает соло → поверхность Boss, входит
> в COS-076-пакет (scratch-перевод миграционных тестов).
>
> **Статусы резолюций (2 сентября):** (2) выполнено — COS-083 принята,
> Luna обновляет `test_final_luna_001` в своём пакете; (3) исправлено
> Apex'ом в fallout COS-083 (Header→str, подтверждено полным сетом);
> (4) закрыто Boss'ом в пакете COS-076.
>
> **Out of scope:** gate decision trail (Boss COS-081), transfer API (Apex
> COS-077), notifications (Flash COS-079), миграционная цепочка (заморожена).

## ✅ DONE — CAPABILITY-GRANULAR GUARDS PASS 2 + DOMAIN ACCESS UNIFICATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-083** | Apex | 20-24h | P1 | COS-077 | ✅ DONE — Capability-гранулярные guard'ы (build:run, deploy:manage, project:write) по 9 route-файлам, единый резолв-контракт `resolve_caller_domain`, ghost 404 всюду, тест-инвариант source-scan |

> **Acceptance (PO, 2 сентября 2026):** полный cosmo-суит — **2224 passed /
> 2 skipped / 0 failed** (PO-прогон 2:18, совпал с отчётом, ×2 у воркера).
> Spot-check: `pg_advisory_xact_lock` в conftest, RBAC-baseline 258→281 по
> инструкции регрессионного теста, Header→str фикс в `domain_guard.py`.
> Бонусом закрыты 3 adjacent-дыры (delete_group, PUT lc-config — анонимные
> записи; get_group, get_lifecycle_config — анонимные чтения) и 3
> prod-бага (NOT NULL cosmo_builds.title, фантомные app.name, Header
> AttributeError). Детектив «app-alpha» — спроектированное ghost-
> поведение, не баг.
>
> **Follow-ups → следующий пакет Apex (COS-086):** семья anonymous writes
> (bricks CRUD + POST /plans); ProjectTeam без доменного якоря.
> Заметка Apex о transfer_*-wipe устарела: Boss закрыл это в пакете
> COS-076.

## ✅ DONE — LANDING TERMINAL PATHS AND LEASE SEMANTICS

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-074** | Boss | 20-24h | P1 | COS-070 | ✅ DONE — Честный терминал TRANSFER_FAILED на durable registry + gateway lease/TTL офлайн-семантика |

> **Acceptance:** 2 сентября 2026. PO-прогон шести файлов — **189 passed**
> (kernel 136 + durable/reconciliation 26 + новые 27), компоненты сходятся
> с отчётом. Код верифицирован: TRANSFER_FAILED — терминал без выходов,
> недостижим после RECEIVED (честность «транспортного провала»);
> record_transfer_failed идемпотентен с durable-зеркалом и restart-survival;
> GatewayLeaseRegistry — single-active на revision_key, инъекция clock,
> LeaseRequiredError различает missing/expired/revoked; lease-gate в diode
> отказывает ДО любых мутаций, enforced только для CONTROLLED_GATEWAY_RELAY.
>
> **Follow-up:** тест-гигиена миграций → COS-076. Врезка репозитория в
> routes/transfer.py — сериально за COS-067 (поток Apex).

## ✅ DONE — MIGRATION TEST HARDENING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-076** | Boss | 6-10h | P2 | COS-074 | ✅ DONE — Scratch-based schema verification + catalog-race isolation + wipe transfer-tail + log-survival (пакет TEST INFRA TAILS) |

> **Scope:** `test_cycle_then_schema_matches` верифицирует схему dev-БД —
> перевести на scratch (латентная зависимость из COS-070, флаг Boss);
> mitigation каталожной гонки `pg_type_typname_nsp_index` при параллельных
> pytest на стенде (уникальные scratch-имена per-run).
>
> **Acceptance (PO, 2 сентября 2026):** полный cosmo-суит **2224 passed /
> 2 skipped / 0 failed** — первый полностью чистый за день, совпал с
> отчётом. Spot-check conftest: advisory-lock, transfer-tail (FK
> child→parent), gate-trail — всё на месте. Корень параллельной гонки
> закрыт `pg_advisory_xact_lock` в pg_client; опция
> `COSMO_TEST_SESSION_DB=1` (per-session БД + atexit-дроп) — opt-in.
> Alembic-мина снята на поверхности: in-process циклы не вызывают
> fileConfig вовсе, CLI — `disable_existing_loggers=False`; caplog-
> регрессия TestLogSurvival добавлена. Зарегистрированные гэпы:
> SIGKILL не дропает per-session БД (осознанный риск → janitor-скрипт
> в пакете Boss); integration/conftest Luna без advisory lock → её
> пакет.

## ✅ DONE — GUARD PASS 3: ANONYMOUS WRITE FAMILY + PROJECT TEAM ANCHOR

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-086** | Apex | 8-12h | P1 | COS-083 + COS-085 | ✅ DONE — Guard pass 3: bricks CRUD (brick:manage), plans write (pipeline:configure), ghost-404 планов через app-якорь, ProjectTeam → резолв-контракт; +2 source-scan инварианта; +59 тестов |

> **Scope:** (1) bricks CRUD и POST /plans остаются анонимными записями —
> та же семья, что delete_group/PUT lc-config, закрытая в COS-083:
> capability-гранулярные guard'ы + ghost-404 контракт; (2) ProjectTeam
> без доменного якоря — привязать к резолв-контракту
> `resolve_caller_domain`; (3) расширить source-scan инвариант на новые
> поверхности.
>
> **Acceptance:** все перечисленные роуты: anonymous → 401, без
> capability → 403, чужой ресурс → 404; source-scan инвариант ловит
> откаты; полный сет на тестовом PG без новых падений вне поверхности.
>
> **Принято 2 сентября 2026 (PO-прогон):** полный сет **2298 passed /
> 2 skipped / 0 failed** в scratch-PG `cosmo_test_apex` (прогресс:
> COS-083 → 2224, COS-085 → 2239, COS-086 → 2298). GUARDED_ROUTES +5,
> GUARD_PASS_MATRIX +6, `TestGuardPass3Pipelines` (6) +
> `TestProjectTeamAnchor` (2), инварианты 4–5 в
> test_domain_resolve_invariant (write-guard pipelines.py, team-anchor).
> Read-роуты `require_principal` в GUARDED_ROUTES сознательно не
> кладутся (матрица ждёт 403 от USER). Research:
> `docs/research/2026-09-02-cos-086-guard-pass-3.md`.
>
> **Follow-up:** in-body auth в notifications.py (зона Flash),
> гибридные проверки releases/runs — кандидат на Pass 4.
>
> **Out of scope:** deps.py opaque-bearer (COS-085, отдельный шаг того же
> пакета), notification-роуты (Flash), transfer API (принят).


## ✅ DONE — SFERA ADAPTER ↔ LEGACY CONTRACT ALIGNMENT

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-069** | Luna | 16-24h | P1 | COS-068 + COS-060 | ✅ DONE — Sfera adapter offline alignment with legacy contract map (auth split, OCI client-side digest, naming, ALREADY_EXISTS semantics) + capability matrix micro-PR |

> **Acceptance:** 2 сентября 2026. Фокуснутый provider-сет — **234 passed**
> (PO-прогон совпал с отчётом). Micro-PR матрицы верифицирован кодом:
> LIST → DOCUMENTED (tree listing), GET_CHECKSUM sha1-note, HEALTH evidence,
> OCI auth-факты. Adapter: Basic/Bearer split с фиксацией
> `registry_auth_mode`, клиентский sha256 identity на push, naming-калька
> REPO_CONFIGS, ALREADY_EXISTS → idempotent OK vs честный CONFLICT,
> `LEGACY_TIMEOUT_PROFILE` задокументирован. Ни одного нового эндпоинта;
> exists/resolve/promote/quota — по-прежнему честный UNSUPPORTED.
>
> **Follow-up:** CONFIRMED только после live-верификации (COS-049/OpenAPI,
> §9 карты); live-профиль обязан выставить `registry_auth_mode == "basic"`.
>
> **Очередь Luna:** пустая очередь закрыта назначением COS-080 (Steel Thread
> integration, стало возможным после изоляции тестового PG). COS-049 остаётся
> заблокированным до live-доступа (Sfera OpenAPI/private CA) — не filler.

> **Scope:** provider_capability.py micro-PR — LIST `UNKNOWN → DOCUMENTED`
> (tree listing код-подтверждён картой), GET_CHECKSUM — задокументировать что
> legacy предпочитает sha1, adapter остаётся sha256-only, HEALTH — evidence-note.
> sfera_provider.py offline-тесты против карты: registry push = Basic auth,
> pull = Bearer (access_token), OCI push digest считается клиентом (sha256,
> серверный Docker-Content-Digest в push-пути не используется), naming
> `{code|-dirty|-raw|-docs}`, ALREADY_EXISTS → idempotent-success семантика
> по OpStatus.CONFLICT/OK, таймаут-профиль — зафиксировать расхождение с legacy.
>
> **DoD / acceptance:** фокуснутый Sfera/provider сет зелёный; ни одного
> нового эндпоинта без ссылки на contract map; live-верификация (COS-049)
> остаётся гейтом для CONFIRMED; полный снапшот — без новых падений в scope.
>
> **Out of scope:** notifications/**, transfer surfaces, миграции, infra,
> live Sfera/Nexus прогоны.

## ✅ DONE — OFFLINE RECOVERY HARDENING

| ID | Кто | h | Результат |
|---|---|---:|---|
| **COS-065** | Boss | 20-24h | ✅ DONE — Offline/diode recovery state matrix, strict checkpoints, crash-gap recovery, ACK/NACK semantics and vendor conformance kit |

> **Acceptance:** 2 сентября 2026. Focused recovery suite — **41 passed**;
> offline baseline — **442 passed**. Terminal delivery identities cannot be
> reused, strict one-way never claims `DELIVERED`, and checkpoint corruption is
> fail-closed.

## ✅ DONE — TRANSFER API SECURITY HARDENING

| ID | Кто | h | Результат |
|---|---|---:|---|
| **COS-066** | Apex | 20-24h | ✅ DONE — Transfer API anti-spoofing, route/auth/ownership matrices, error contract and OpenAPI hardening |

> **Acceptance:** 2 сентября 2026. Transfer/API/kernel plus security matrix —
> **262 passed**; full suite — **1902 passed, 6 failed, 7 skipped**, with the
> same unrelated background failures before and after the packet.

---

## ✅ DONE — CONTROL STATION NOTIFICATION SURFACE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-061** | Flash | 20-24h | P1 | COS-055 + COS-056 | ✅ DONE — Control Station inbox/read state/SSE integration with honest empty, loading, error and degraded states |

## ✅ DONE — CONTROL STATION BROWSER ACCEPTANCE

| ID | Кто | h | Результат |
|---|---|---:|---|
| **COS-064** | Flash | 20-24h | ✅ DONE — Browser-level notification inbox/SSE/read-state acceptance and REST contract-drift fix |

> **Acceptance:** 2 сентября 2026. E2E **10/10 × 3 clean runs**, Vitest
> **56/56**, TypeScript clean, frontend build green. REST `is_read` /
> `event_type` mapping is normalized at the API seam.

---

## ⬜ READY — PORTAL NOTIFICATION MANAGER V1

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|

| **COS-056** | Flash | 8-12h | P1 | COS-055 | Control Station notification inbox, unread state, event detail and SSE projection |
| **COS-057** | Luna | 8-12h | P1 | COS-055 | ✅ DONE — Email provider adapter (SMTP + fake), offline transport seam, delivery failure visibility and redaction-safe error paths |

> **COS-057 acceptance:** 2 сентября 2026. Focused suite **33/33**
> (unit + PG-интеграция через живой NotificationManager); notification+provider
> регрессия 205 passed; полный снапшот без новых падений в scope.
> Transient→retry→sent, 5xx→DLQ, invalid recipient→terminal, redaction
> получателей в error-строках и логах адаптера — проверено.
>
> **Follow-up (поверхность Flash):** `redaction.py` маскирует только ключ
> sensitive-паттерна — значение утекает; `manager.py` пишет `recipient_id`
> в логи retryable и DLQ строк. Live SMTP/Sfera/mTLS остаются evidence-gaps.

> **Dispatch incident (1 Sep 2026):** COS-055 был ошибочно запущен двумя
> workers на одном `REFACTOR-SERIAL` module. Инцидент закрыт routing-решением:
> Flash — единственный owner, Apex снят с COS-055 и продолжает COS-058, Luna
> withdrawn и не пишет в notification surfaces. До report Flash карточка остаётся
> in progress; incident evidence: `docs/research/2026-09-01-cos-055-worker-collision.md`.

---

## ✅ DONE — INFRASTRUCTURE DELIVERY PROFILE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-059** | Buddy | 20-24h | P1 | current backend/frontend entrypoints | ✅ DONE — Docker Compose/Caddy delivery profile, service health/readiness, startup/shutdown and smoke verification |

> **Acceptance:** Implementation and runtime delivery are accepted through
> COS-063. Migration drift was repaired by COS-062; clean-start, full-profile,
> smoke, restart, SSE and dependency-failure evidence is recorded in
> `docs/research/2026-09-02-cos-063-runtime-acceptance.md`.
>
> **Follow-up:** `/ready` status code for PostgreSQL loss remains open as a
> product/health decision; do not reopen the infrastructure delivery card.

---

## ✅ DONE — DATABASE MIGRATION RECONCILIATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-062** | Luna | 20-24h | P0 | COS-060 accepted; current ORM/Base metadata | ✅ DONE — One valid Alembic chain matching current ORM schema, including releases and domains, safe bootstrap/replay |

> **Acceptance:** 2 сентября 2026. One linear Alembic head; inspector diff vs
> `Base.metadata` is zero across 31 tables; fresh upgrade, downgrade-to-base
> and re-upgrade pass; 10 migration tests pass. Main dev DB was advanced through
> a controlled stamp path. Destructive shared-DB downgrade remains prohibited.

### Решение по направлению

МУ — один logical manager на один Cosmoport/портал, внутри модульного монолита.
Он не является межзонным transport и не разворачивается отдельным сервисом.
Kafka и legacy Notification Service не переносятся. Provider libraries допустимы
только под delivery; notification semantics, journal и reliability принадлежат
Cosmoport.

### Порядок

1. COS-055 создаёт backend contract и durable delivery semantics.
2. COS-056 и COS-057 могут идти параллельно после COS-055; у них разные write
   surfaces (Control Station UI против provider adapter/tests).
3. Webhook, digest, quiet-hours и cross-zone notification federation — follow-up,
   только после реального use case.

---

## ✅ DONE — NOTIFICATION MANAGER V1

| ID | Кто | h | Результат |
|---|---|---:|---|
| **COS-055** | Flash | 20-24h | Durable portal-local Notification Manager: outbox, inbox/read state, dedup, retry/DLQ, provider-neutral email seam, redaction |

> **Acceptance:** 1 сентября 2026, **80 passed** (26 manager + 30 legacy
> notification + 12 releases + 12 API routes). Проверено из `orchestrator`:
> `py -3 -m pytest tests/cosmo/test_notification_manager.py tests/cosmo/test_notifications.py tests/cosmo/test_releases.py tests/cosmo/test_api_routes.py -q`.
> Transactional outbox реально подключён для transfer events в той же транзакции.
>
> **Follow-up:** run/gate/batch/release triggers кроме transfer_completed,
> background worker вместо manual tick, real SMTP, Valkey/SSE projection и
> durable replacement legacy in-memory webhook configs.

> **COS-056 acceptance:** focused trigger/SSE/manager/release suites — **109
> passed, 0 failed**. Four SQLAlchemy `Connection._cancel` RuntimeWarnings
> observed under the local Python/async test environment; no failed assertions.
> Full regression remains blocked by pre-existing `repos.py` Pydantic error.

### Следующий notification order

1. COS-056 — Control Station inbox/SSE после backend contract.
2. COS-057 — email provider contract/ops hardening; отдельная provider surface.
3. Отдельный follow-up — подключение всех V1 domain triggers и background tick;
   не переоткрывать COS-055.

### Next packet from Flash

`COS-061` — Control Station notification inbox/SSE integration and honest
empty/loading/error states. Backend trigger and stream contract from COS-056
are accepted; UI is the next product surface.

---

## ✅ CLEANUP WAVE — ВСЕ 13 КАРТОЧЕК ЗАКРЫТЫ (100%)

| ID | Кто | h | Результат |
|---|---|---|---|
| **CLN-001** | Flash | 2h | Колонки исправлены, Vault Path и хардкод-контакты вырезаны |
| **CLN-002** | Flash | 1h | Evidence mockEntries удалены → честный EmptyState |
| **CLN-003** | Flash | 3h | DEFAULT_RELEASES удалены, клиентские хэши-подписи убраны |
| **CLN-004** | Flash | 2h | PipelineStudio setInterval удалён, честный POST /runs |
| **CLN-005** | Flash | 2h | DeepLinker fix + plan-steel убран |
| **CLN-006** | Flash | 2h | api.ts .catch(()=>[]) удалены, честные ошибки |
| **CLN-007** | Luna | 2h | SoD в create_gate: HTTP 409, 10/10 тестов |
| **CLN-008** | Boss/Luna | 1h | Линейный трансфер: ZR→ZPE запрещён → HTTP 400 |
| **CLN-009** | Buddy | 4h | E2E-скрипт 8 фаз |
| **CLN-010** | Buddy | 3h | CI regression gate в GitHub Actions |
| **CLN-011** | Luna | 3h | Негативные тесты SoD + трансфер |
| **CLN-012** | Luna | 2h | Аудит API: 0 хардкод-ответов |
| **CLN-013** | Luna | 2h | Финальный вердикт: **1222 passed, 39 passed, 0 failed** |

> **Acceptance:** Cleanup Wave принята как завершённая. Следующее направление
> открыто отдельно: Sfera/ДиБ — Cosmoport bridge; Harbor + Nexus + MinIO/S3 + Git
> — PureK provider baseline. Artifactory и собственный registry не открываются.
| **COS-056** | Flash | 20-24h | P1 | Domain triggers for V1 events, durable outbox integration, SSE initial/new/reconnect/degraded behavior |
## ✅ DONE — EVIDENCE EXTERNAL HEAD ANCHOR + CONFT LOCK + CONTRACT TEST

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-087** | Luna | 10-16h | P1 | COS-082 + COS-083 | ✅ DONE — Внешний append-only якорь головы evidence-цепочки (head_mismatch), advisory lock в integration/conftest, test_final_luna_001 → caller_domain |

> **Scope:** (1) last sealed `_chain_hash` → append-only sink (audit-file /
> object-store ref, без новых сервисов); verify: externally-anchored режим,
> head_mismatch отдельным статусом, честный unknown-anchor при недоступном
> якоре; негативные тесты: суффикс-переподпись → head_mismatch, детерминизм
> ×3. (2) integration/conftest.py — create_all/wipe под pg_advisory_xact_lock,
> возврат на общий :5433. (3) test_final_luna_001 — X-Cosmo-Domain в seed'ах
> (COS-083 принята, domain-free больше не канон).
>
> **Acceptance:** 2 сентября 2026. (1) якорный sink `evidence_anchor.py`
> (JSONL audit-file, env `COSMO_EVIDENCE_ANCHOR_FILE`, append-only+fsync,
> publish только после commit, fail-visible); verify_and_get: `integrity`
> расширено "head_mismatch" (4-й статус), `anchor{enabled,status,
> anchored_head,computed_head}`, честный unknown_anchor. Суффикс-переподпись
> (payload+якоря, internal verify чист) → head_mismatch — флагман-тест e2e,
> детерминизм ×3; head loss → head_mismatch; юниты sink 11 + anchored
> verify 5. (2) create_all/wipe под pg_advisory_xact_lock('COSM'), wipe в
> одной транзакции; параллель integration+migration на :5433 — 25+27
> passed без каталожких гонок; :5434-хак приёмки COS-082 удалён. (3) luna
> suite после fallout COS-083 — 119 passed (caller_domain опционален,
> Header→str закрыт). Полный снапшот: 2265 passed, 2 skipped, 0 failed.
> Evidence-док: `docs/research/2026-09-02-cos-087-evidence-head-anchor.md`.
>
> **Acceptance (PO, 2 сентября):** юниты якоря+evidence — **44 passed**
> (PO-прогон test_evidence_anchor + test_sse_backlog), полный снапшот
> 2265/0 по отчёту; инвариант «якорится durable-голова, не rebuild-хеш»
> верифицирован по доку — суффикс-переподпись с write-доступом к PG
> детектируема. Принято.
>
> **Follow-up:** object-store ref (S3/MinIO) как sink — тот же контракт,
> отдельная карточка; single-writer assumption sink-файла задокументирована.
>
> **Out of scope:** gate trail (Boss), notifications (Flash), deps/rbac
> (Apex), миграционная цепочка.

## ✅ DONE — SSE DURABILITY VIA VALKEY STREAMS

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-088** | Flash | 12-18h | P1 | COS-079 + COS-084 | ✅ DONE — SSE reconnect без потери событий: Last-Event-ID ресемпл из Valkey Stream backlog, честный degraded |

> **Scope:** события стримов (runs/domains/notifications) дублируются в
> Valkey Stream с TTL; ресемпл по last-event-id с gap-детекцией (пропуск →
> resync-снапшот, не тишина); рестарт cosmo-api не рвёт историю; без Valkey
> — текущее in-memory поведение с наблюдаемым флагом деградации (lazy, never
> hard dependency); юниты resync/gap/degraded + интеграция на тестовом PG.
>
> **Acceptance:** рестарт cosmo-api при живом клиенте — события из окна
> недоступности доставляются ×2; TTL-вытеснение → gap → resync; полный сет
> без новых падений вне поверхности.
>
> **Acceptance (PO, 2 сентября):** юниты backlog — **33 passed** (PO-прогон,
> FakeValkey double с инъекцией сбоев), sse+notification линия 106/106 по
> отчёту, полный сет 2298/0; live-smoke рестарта cosmo-api ×2 по отчёту
> (доигрывание из valkey, `X-Cosmo-Backlog: valkey`). Инвариант SSE id ==
> XADD id верифицирован по коду-отчёту. Принято.
>
> **Out of scope:** ticket/guards (приняты), deps.py (Apex), prod-nginx
> (Buddy), e2e-инфраструктура.

## ✅ DONE (пп.1-2) — STAND HYGIENE + SUITE GATE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-089** | Boss | 8-12h | P2 | COS-076 | ✅ DONE (пп.1-2) — Scratch janitor CLI (dry-run/--apply/--json, guard 5432) + suite gate одной командой (Gate G в DEPLOYMENT.md §14) |

> **Scope:** (1) scripts/cleanup_scratch_pg.py — листинг/дроп cosmo_test_s* и
> orphan scratch-БД без активных соединений, dry-run по умолчанию, --apply
> явно, не демон; (2) suite gate: одна команда → COSMO_TEST_SESSION_DB=1 →
> полный cosmo-суит → вердикт exit-code + summary; секция в docs/DEPLOYMENT.md;
> (3) /ready degraded → 503 + обновление health-документации — пункт
> выполняется только если Максим утвердил.
>
> **Решение по п.3 (PO, 2 сентября, #to evolve resolved):** по канонической
> семантике readiness (Kubernetes liveness/readiness/startup probes) готовность
> = «инстанс может обслуживать трафик СЕЙЧАС»; падение hard-зависимости
> (PostgreSQL) → 503, чтобы Caddy/upstream вывед инстанс из ротации. 200-degraded
> врёт балансировщику. Мягкие деградации с рабочим fallback (SSE без Valkey →
> in-memory из COS-088) НЕ роняют readiness — они видны в теле ответа и
> `X-Cosmo-Backlog`. Итог: /ready = 200 только когда ядро способно обслуживать
> запросы; 503 + честный JSON-компонент-мап при недоступности PG. Пункт
> разблокирован, поверх пп.1-2 тем же владельцем.
>
> **Acceptance (PO, 2 сентября):** janitor dry-run --json — план чист
> (orphan'ов 0 после --apply Boss'а, 2 дропнуты им, живая сессия чужого
> прогона пропущена); suite gate прогнан PO — 2248 passed / 1 fail.
> Единственный фейл `TestGuardPass3Pipelines::test_plan_read_delete_ghost_and_scoping`
> точечно — **6 passed**: транзиентная гонка с live-WIP Apex (COS-086,
> планы/pipelines правятся в моменте), не регрессия Boss. Gate сделал свою
> работу — поймал чужой WIP. П.3 — решение принято (см. выше), выделен в
> COS-090.
>
> **Acceptance:** dry-run показывает план, --apply дропает только orphan,
> живой стенд не тронут; suite gate идемпотентен с чистого состояния; полный
> сет остаётся 2224/0.
>
> **Out of scope:** миграционная цепочка, чужие conftest-поверхности
> (Luna), rbac/deps (Apex).

## ✅ DONE — READY ENDPOINT HONEST SIGNALING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-090** | Boss | 2-4h | P2 | COS-089 (пп.1-2) | ✅ DONE — /ready: 503 при недоступности PG (hard-dep) + честный компонент-мап; Valkey/anchor — soft, видны в теле; health-документация переписана, девиация COS-063 закрыта |

> **Scope:** решение принято (K8s readiness-семантика, #to evolve resolved):
> /ready = 200 только когда ядро способно обслуживать запросы; недоступный
> PostgreSQL → 503 + честный JSON (компонент-мап: pg, valkey, anchor). Мягкие
> деградации (SSE fallback на in-memory) НЕ роняют readiness — видны в теле и
> X-Cosmo-Backlog. Обновить health-секцию DEPLOYMENT.md (известное отклонение
> из COS-063 закрывается).
>
> **Acceptance (PO, 2 сентября):** живьём проверено PO: stop cosmo-postgres →
> **503**, start → **200** (recovery); health/perimeter срез 32 passed;
> SUITE GATE 2312/0 по отчёту (совпадает с COS-091 — единый сет). Семантика:
> PG hard-dep (503), Valkey/anchor soft (200+degraded), anchor без конфига —
> disabled, не деградация. docker healthcheck → /live, Caddy pass-through —
> противоречий нет. Принято.
>
> **Acceptance:** живьём: остановка cosmo-postgres → GET /ready = 503 с телом;
> подъём PG → 200; без Valkey — 200 + видимый degraded-флаг; полный сет на
> тестовом PG без новых падений; docker healthcheck/caddy-логика не
> противоречат новой семантике.
>
> **Out of scope:** миграционная цепочка, чужие conftest-поверхности,
> rbac/deps (Apex).

## ✅ DONE — GUARD PASS 4: IN-BODY AUTH UNIFICATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-091** | Apex | 10-16h | P2 | COS-086 | ✅ DONE — Guard pass 4: releases lifecycle (submit/approve/reject/deploy/delete) + envelope/verify + PATCH run status + batches-семья → deps-guards; in-body доменные проверки → резолв-контракт; попутно фикс JSONB datetime в approvals; +2 файла под source-scan инвариант |

> **Scope:** (1) releases.py / runs.py — гибридные проверки (deps-гвард +
> in-body): унифицировать в deps-guard'ы по матрице GUARD_PASS; (2)
> notifications.py — 13 in-body get_current_principal: зона Flash, есть её
> WIP — координация через PO, не трогать до её accept; (3) source-scan
> инвариант: write-хендлеры releases/runs обязаны нести deps-guard.
>
> **Acceptance:** ни одного in-body auth-решения в releases/runs; дубли не
> дают расхождений (401 vs 403 vs 404 согласованы по матрице); полный сет
> без новых падений вне поверхности.
>
> **Принято 2 сентября 2026 (PO-прогон):** полный сет **2312 passed /
> 2 skipped / 0 failed** в scratch-PG `cosmo_test_apex` (прогресс: COS-086
> → 2298, COS-091 → 2312). GUARDED_ROUTES +9, GUARD_PASS_MATRIX +9
> (включая SoD-строку secoff на approve), `TestGuardPass4ReleasesRuns`
> (9), инвариант 4 параметризован по releases.py/runs.py. Все Actions —
> существующие (rbac frozen не расширялся); delete_release покрыт
> release:create (осознанный отказ от нового Action). Попутно закрыт
> латентный баг: approvals JSONB datetime → `model_dump(mode="json")`.
> Research: `docs/research/2026-09-02-cos-091-guard-pass-4.md`.
>
> **Follow-up:** notifications.py — последняя неунифицированная
> поверхность (зона Flash, ждёт её accept); transfer-роуты можно
> перевести на mode="json" для единообразия.
>
> **Out of scope:** notifications.py до accept Flash; e2e; миграционная
> цепочка.

## ✅ DONE — NOTIFICATIONS IN-BODY AUTH UNIFICATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-092** | Flash | 6-10h | P2 | COS-084 + COS-091 (матрица) | ✅ DONE — notifications.py: 12 маршрутов → deps-guard'ы (ops → DOMAIN_CONFIGURE, личная → require_principal), инвариант расширен, e2e-линия починена (JWT) |

> **Scope:** собственная поверхность Flash (follow-up из приёмки COS-086,
> там не тронута сознательно). In-body principal-проверки → deps-guard'ы,
> семантика 401/403/404 по единой матрице; source-scan-инвариант по
> образцу COS-091. Уведомить Apex (COS-091) — notifications исключена из
> его пакета.
>
> **Acceptance (PO, 2 сентября):** live-smoke через edge 5174: /api/dlq с
> opaque → **401**; notification/guard срез **192 passed**; полный сет
> 2313/0 (базлайн 2312 +1 инвариант); e2e 17/17 ×2; GUARDED_ROUTES/MATRIX
> +7. Маппинг принят: ops → DOMAIN_CONFIGURE (админ-секция жива), личная
> поверхность → require_principal (batches-паттерн). Расхождение 13 vs 12
> маршрутов — счетчик карточки, не гэп. E2E-починка (unsigned-JWT, контракт
> COS-031) зачтена — линия была красной с COS-085. Примечание принято:
> notifications больше не «неунифицированная» — follow-up COS-091 закрыт.
>
> **Out of scope:** releases/runs (Apex, COS-091), transfer, миграционная
> цепочка.

## ✅ DONE — EVIDENCE ANCHOR: OBJECT-STORE SINK

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-093** | Luna | 8-12h | P2 | COS-087 | ✅ DONE — Object-store (S3/MinIO) sink для evidence anchor: тот же контракт publish/verify, audit-file остаётся default для Pure Box |

> **Scope:** follow-up COS-087. Sink-интерфейс: audit-file (есть) +
> object-store ref (MinIO по PERSISTENCE.md; локальный FS для Pure Box).
> Выбор sink — конфиг, не код: COSMO_EVIDENCE_ANCHOR_BACKEND=file|s3.
> Контракт publish/verify без изменений (head_mismatch/unknown_anchor
> честно); single-writer: S3-версионирование как append-only замена.
> Негативные тесты: недоступный S3 → unknown_anchor; объект подменён →
> head_mismatch.
>
> **Acceptance:** e2e с write-доступом к PG + подменой якоря в MinIO →
> head_mismatch; file-режим регрессий не имеет (существующие 44 юнита
> зелёные); полный сет без новых падений вне поверхности.
>
> **Acceptance:** 2 сентября 2026. `COSMO_EVIDENCE_ANCHOR_BACKEND=file|s3`
> (выбор — конфиг); file-режим — байт-в-байт регресс COS-087 (11 юнитов
> без правок), s3-режим — MinIO по канону `PK_MINIO_*`, SigV4 на stdlib
> (MinIO Basic auth не принимает; грабля `httpx.URL.netloc` → bytes
> задокументирована), S3-версионирование как append-only замена
> (best-effort enable + bucket policy). E2E против живого MinIO :9100
> ×2: publish→verify ok, подмена якорного объекта → head_mismatch
> (флагман), suffix-resign → head_mismatch, head loss → head_mismatch,
> недоступный object-store → честный unknown_anchor. Юниты 27 (fake S3
> на MockTransport: статусы read-стороны, fail-visible publish,
> dispatch), линия evidence 69 passed. Полный сет — интерференция
> параллельных воркеров на общем test PG (см.
> docs/research/2026-09-02-cos-093-evidence-anchor-s3-sink.md).
>
> **Out of scope:** KMS/подписи якоря, миграционная цепочка, чужие
> поверхности.

## ✅ DONE — PROD EDGE + AIRGAP PROFILE HARDENING

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-094** | Boss | 8-12h | P1 | COS-063 | ✅ DONE — nginx 5174 проксирует /api + SSE (buffering off, 1h timeout), airgap cold-start EXIT=0 (10/10, pull never), чеклист §5.5, edge-иерархия зафиксирована (§7.0: Caddy — канонический edge, 5174 — same-origin front door) |

> **Scope:** (1) prod-nginx 5174: контейнер cosmo-frontend отдаёт SPA, но
> /api не проксируется — браузер получает SPA-HTML/405 вместо API-ответов.
> Добавить /api → cosmo-api:8100 (и /sse-совместимость: буферизация off,
> read timeout long, X-Accel-Buffering no) — или вынести решение на Caddy-
> edge, если nginx-контейнер не должен знать про API; зафиксировать один
> канонический edge-путь. (2) Airgap-профиль: проверить полный холодный
> старт без внешней сети (образы локальны, тяги в docker-compose нет),
> healthcheck'и не зависят от DNS наружу; составить airgap-чеклист
> (образы/теги/volumes) в DEPLOYMENT.md. (3) Smoke через prod-edge:
> API-эндпоинт, SSE-стрим и /ready через 5174 — все отвечают как напрямую.
>
> **Acceptance (PO, 2 сентября):** live-smoke через 5174 (PO): /api/dlq
> opaque → 401 (JSON-контракт сквозь edge), /ready → 200; статические
> контракты 9 (test_prod_edge_config.py); airgap cold-start EXIT=0
> 10/10 по отчёту; resolver-решение переживает пересоздание API-контейнера.
> Решение по edge принято: Caddy — канонический production edge, 5174 —
> same-origin front door (не второй production edge). Suite gate 2322/0.
> WIP-бакет COS-094 из плана COS-095 теперь коммитабелен.
>
> **Out of scope:** TLS-терминация (отдельно), миграционная цепочка,
> app-код (без правок backend/frontend, только edge-конфиги).

## ✅ DONE — RELEASE CANDIDATE HYGIENE: COMMIT BATCH + KNOWN TAILS

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-095** | Apex | 6-10h | P1 | — | ✅ DONE — Разметка 12 коммит-партий (197/197 status-строк, аудит OK; 3 файла WIP-COS094 Buddy изолированы, не коммитить), test-tails закрыты (2 skips легитимные, janitor задокументирован), transfer mode="json" унифицирован; commit ждёт явной команды Максима |

> **Acceptance (PO, 2 сентября):** transfer mode="json" — верифицирован
> PO-прогоном 2312/0 в составе сетов COS-090/091. План партий принят:
> P02-migrations первым (спорный, пока цепочка свежая), WIP-COS094 бакет
> не коммитить до приёмки Buddy, аудит-скрипт прогонять перед каждым
> коммит-раундом. 4 устаревших ⬜ заголовка — зачистка при следующем
> заходе PO.

> **Scope:** (1) git-инвентарь: полный статус незакоммиченных изменений,
> разложить по логическим партиям (cosmo-083..095 поверхностям) с краткой
> аннотацией каждой партии — ПОЛЬЗОВАТЕЛЬ выполняет commit сам, твоя
> задача — подготовить разметку `git add`-партий и предлагаемые commit-
> сообщения, НЕ выполнять. (2) Закрыть test-tails: e2e 1 skipped
> pre-existing — выяснить легитимность скипа; janitor SIGKILL-хвост —
> задокументировать команду ручной очистки в DEPLOYMENT.md. (3) transfer
> model_dump(mode="json") унификация (follow-up COS-091) — перевести
> transfer-роуты для единообразия.
>
> **Acceptance:** разметка партий покрывает всё незакоммиченное дерево без
> пропусков; каждый test-tail либо закрыт, либо зарегистрирован с владельцем;
> transfer-роуты на mode="json", полный сет зелёный.
>
> **Out of scope:** сам commit/push (только по прямой команде Максима),
> airgap/edge (Buddy COS-094), notifications (Flash COS-092).

## ✅ DONE — LIVE GITEA FORGE CYCLE (DEMO WITHOUT FAKES, PART 1)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-096** | Boss | 16-24h | P1 | COS-094 | ✅ DONE — Gitea ForgeAdapter доведён до живого цикла: привязка реального репо → webhook → read pipeline source → статус виден в ПУ; фейки больше не нужны на forge-слое |

> **Scope:** (1) ForgeAdapter (COS-007 прототип) против живого Gitea стенда:
> create/bind repo binding, read tree/commits, идемпотентный webhook setup
> (секрет, retry); (2) end-to-end: коммит в реальный репо → webhook в ПУ →
> привязка к Application → Plan compile от живого source; (3) honest error
> surface: недоступный Gitea, невалидный токен, missing repo — читаемые
> 4xx/502 с записью в audit; (4) интеграционные тесты против живого
> контейнера Gitea (opt-in маркер, как живой registry).
>
> **Acceptance:** принято 3 сентября 2026. Offline test_forge_cycle.py 26/26,
> live opt-in 6/6 × 2 против живого Gitea :3100. Привязка репо → webhook setup →
> test delivery → last-push (webhook cache) → compile-from-source дерева →
> персистенция плана. Контейнеры healthy. Особенности Gitea 1.22
> (SHA при создании, eventual consistency ~2s, ALLOWED_HOST_LIST) зафиксированы
> в DEPLOYMENT.md §4.2 и research-доке `docs/research/2026-09-03-cos-096-live-gitea-forge-cycle.md`.
>
> **Out of scope:** Woodpecker execution (COS-097), Web IDE, мост, миграционная цепочка.

## ✅ DONE — LIVE WOODPECKER RUN CYCLE (DEMO WITHOUT FAKES, PART 2)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-097** | Apex | 16-24h | P1 | COS-094 | ✅ DONE — Woodpecker ExecutionAdapter до живого цикла: pipeline → run → статус/логи → Evidence; фейки больше не нужны на execution-слое |

> **Scope:** (1) ExecutionAdapter против живого Woodpecker стенда: запуск
> pipeline по compiled plan (COS-096 source), получение статуса/логов;
> (2) завершение цикла: run state machine потребляет живые статусы,
> Evidence пишется из реального прогона (SHA-256 артефакты логов/отчётов);
> (3) honesty: неизвестный статус/таймаут агента — честный degraded, не
> выдуманный PASS; (4) тесты: контракты + opt-in живой интеграционный.
>
> **Acceptance:** принято 3 сентября 2026. Adapter v3.5 доведён до живого
> цикла: lookup по owner/name → числовой repo_id, submit по branch, статус-полл
> с канон-маппингом (`declined → blocked`, `skipped → failed`, `blocked` —
> НЕ terminal), cancel через POST (не DELETE), логи по step-id. Durable-ручки
> в side-таблице `cosmo_execution_handles` (отдельный ExecutionBase, миграции
> не тронуты) — рестарт cosmo-api не теряет факт прогона (recover).
> Honesty: sustained unknown (≥5 подряд) → честный terminal: batch `failed`,
> run `FAILED/INFRA`, `degraded=True` + consume-once reason, alert-evidence;
> никакой симуляции PASS. Evidence канонический: `commit_evidence_entry`
> (type=`log`, SHA-256 логов) + digest в `Batch.evidence_refs`. Wiring
> opt-in `COSMO_EXECUTOR_ENABLED=1` в lifespan; POST /runs сабмитит в
> running-фазе. По пути исправлены 5 реальных багов: deadlock фонового лупа
> (threading.Event в asyncio.wait_for), revert-race параллельных poll'ов,
> отсутствие атомарного claim, resubmit-guard, aware-datetime в
> TIMESTAMP WITHOUT TIME ZONE. Тесты: test_execution_service 14/14,
> test_batch_executor обновлён под контракт, opt-in smoke против живого
> стенда. Полный сет: 2498 passed / 8 skipped / 1 failed (единственный фейл —
> чужой WIP `api/deps.py` COS-066/067/068: `session_token` в GET
> /api/v1/domains ломает старый OpenAPI-тест; finding задокументирован,
> поверхность не трогал). Research: `docs/research/2026-09-02-cos-097-woodpecker-live-cycle.md`.
> Commit-партия P13-execution-woodpecker (11 файлов), аудит 226/226 OK.
>
> **Out of scope:** gates на живых findings (мост), Control Station UI для
> логов (Flash отдельно), миграционная цепочка.

## ✅ DONE — RELEASE READINESS UI: LIVE DATA CONTRACT (COS-012/021 PORT)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-098** | Flash | 14-20h | P1 | COS-092 + COS-096 | ✅ DONE — Release readiness surface в Control Station: живые Release/Batch/Gate/Evidence по REST+SSE вместо localStorage-прототипов, честные empty/error/degraded |

> **Scope:** (1) порт COS-012/021-хвостов: release readiness summary +
> DataGrid от живого REST (прототипы на localStorage); deep-link в
> release/run view; (2) SSE-интеграция: статус release/run живой (backlog
> из COS-088), run detail → логи Woodpecker (COS-097) стримом; (3) honest
> states: empty (нет releases), loading, 403/404 ghost, degraded (SSE
> fallback), error; (4) контракт-первым: сверить DTO с releases/runs API
> до UI-кода.
>
> **Acceptance:** принято 3 сентября 2026. Vitest 66/66 (+6 новых ReleaseReadiness),
> tsc -b / vite build 0 ошибок, e2e release-readiness 2/2. Контракт DTO выправлен
> truthfully против бэкенда (plan_id, run_ids, status, current_zone, transfer_history).
> Хук useLiveDomain.ts поддерживает domain SSE с reconnect fresh-ticket и resync
> по backlog (COS-088). Очищены тестовые релизы/прогоны, стенд чист.
>
> **Out of scope:** Web IDE (Surface B), мост/Studio adapter, transfer UI.

## ✅ DONE — SBOM & VULNERABILITY REPORT IN RELEASE BUNDLE (PK-C-003.6)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-099** | Apex | 12-16h | P2 | COS-053 + COS-096 | ✅ DONE — Генерация SBOM (CycloneDX 1.5 via syft/internal fallback) и vulnerability report (grype offline) в TransferItem/PackageBuilder с SHA-256 digest pinning и tamper-evidence на трёх слоях |

> **Scope:** (1) Расширение `PackageBuilder` и `DigitalReleaseEnvelope`: генерация
> машиночитаемого SBOM (формат SPDX JSON / CycloneDX) из дерева репозитория и
> артефактов сборки; (2) интеграция утилиты `syft` (CLI/docker wrapper с graceful
> fallback на internal AST/dependency parser при отсутствии binary в airgap);
> (3) формирование отчёта уязвимостей через `grype` (offline DB snapshot);
> (4) сохранение digests SBOM и security report в манифест пакета с tamper-proof
> проверкой при landing; (5) тесты: валидность схемы SBOM, фиксация digest,
> landing-верификация в airgap без сетевого egress.
>
> **Acceptance:** принято 3 сентября 2026 (Apex). (1) `transfer/sbom.py`:
> `generate_sbom` — syft CLI wrapper (инъекция runner'а) с честным fallback на
> internal parser (requirements/pyproject/package.json, prune node_modules,
> дедуп, детерминированный CycloneDX 1.5); формат — CycloneDX только (канон
> "CycloneDX is sole SBOM contract", SPDX не делался). (2) `generate_vuln_report`
> — grype с offline-env (GRYPE_DB_AUTO_UPDATE=false), отсутствие инструмента →
> честный source="none" с reason, никогда фейковый отчёт. (3) Digest pinning:
> `manifest["security"]` (SBOMPin/VulnReportPin) входит в детерминированный
> PackageRevision checksum. (4) Tamper-evidence на трёх слоях: manifest checksum ↔
> payload bytes (`PreTransferValidator.validate_with_artifacts` + новый
> `LandingStateMachine.receive_and_verify` → CHECKSUM_MISMATCH, requires new
> revision) ↔ envelope digest (COS-126 bundle import через
> `envelope_artifacts_from_security`). `build_secured_package` facade.
> (5) Тесты +33 (`test_transfer_sbom.py`), включая airgap roundtrip (подменённый
> SBOM в ZIP отвергается bundle-верификацией) и offline-гигиену. Полный сет:
> **2559 passed / 8 skipped / 0 failed** (3:12). Живой smoke syft/grype — при
> появлении бинарников в airgap-образе (wrapper-контракты покрыты fake-runner'ами).
> Research: `docs/research/2026-09-03-cos-099-sbom-vuln-report.md`.
>
> **Out of scope:** live vulnerability enrichment из внешних NVD/OSV в runtime;
> SPDX-формат; вызов `build_secured_package` из release-оркестрации (отдельная
> связующая карточка).

## ✅ DONE — WEB IDE SURFACE B: MONACO & WORKSPACE SHELL (COS-023 PORT)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-100** | Flash | 14-18h | P2 | COS-020 + COS-098 | ✅ DONE — Web IDE (Surface B) ядро: Tailwind v4 + Radix + Monaco editor mount в изолированном `.cosmo-ide-root`, дерево файлов репозитория, переключение поверхностей |

> **Scope:** СТРОГО ПОРТ ИЗ КОРОБКИ (`D:\prettyk-secops`), писать с нуля ЗАПРЕЩЕНО.
> Донорские файлы: `D:\prettyk-secops\frontend\src\workbench\EditorWorkbench.tsx`,
> `workspaceStore.ts`, `frontend/src/monaco/setup.ts`, `editorOptions.ts`, `metaDarkTheme.ts`.
> (1) Прямой перенос и адаптация 3-панельного шелла (Explorer, Monaco, Drawer, resize handles, store);
> (2) Изоляция стилей: монтирование строго внутри контейнера `.cosmo-ide-root` (Tailwind
> Preflight внутри, MUI CssBaseline не ломается);
> (3) Подключение к API Cosmoport 2.0: файловое дерево через `/api/v1/repos/tree` и чтение/запись через `/api/v1/repos/file`;
> (4) Monaco Editor: подсветка `.cosmo/pipeline.yaml` и скриптов, автосохранение черновика, сохранение на бэкенд;
> (5) Переключение между Control Station (Surface A, Meta Light) и Web IDE (Surface B, Dark default) по query param `?surface=ide` и кнопке в хедере;
> (6) Vitest + tsc -b чистые.
>
> **Acceptance:** принято 3 сентября 2026. Web IDE перенесена на базе проверенного
> шелла Коробки (EditorWorkbench). Tailwind Preflight изолирован строго внутри
> `.cosmo-ide-root` (MUI в Control Station не сносит границы/кнопки). Файловое
> дерево синхронизировано с бэкендом (GET /tree, GET /file), сохранение по ⌘S (PUT /file),
> автосохранение черновика в localStorage (800ms debounce) с нотификацией о восстановлении.
> Deep-linking по `?surface=ide` и `line` с авто-скроллом Monaco. Переключатель
> Control Station ↔ Web IDE в хедере. Верификация: vitest 76/76 passed (+10 WebIDEShell),
> tsc -b / vite build 0 ошибок (32s), Playwright e2e (web-ide) 2/2 passed.
>
> **Out of scope:** писать что-либо с нуля (брать из Коробки), xterm pty-сокет к контейнеру (следующий шаг).

## ✅ DONE — FINDINGS-TO-GATES BRIDGE & RUNTIME RECONCILIATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-101** | Apex | 12-16h | P1 | COS-097 | ✅ DONE — Мост Findings ↔ Quality Gates (gate-оценка finalize по живым findings), SigV4 MinIO bucket provisioning, выравнивание OpenAPI контракт-теста |

> **Scope:** (1) Мост Woodpecker Findings ↔ Quality Gates: парсинг отчётов/артефактов прогона (SARIF, JSON findings) из шагов Woodpecker в сущности `cosmo_findings`, привязка к `run_id` и `batch_id`; вычисление Gate Verdict (`PASS`/`WARN`/`FAIL`) на основе живых findings взамен статических заглушек; (2) фикс SigV4 MinIO auto-provisioning в `orchestrator/cosmo/api/startup.py` (`provision_minio_buckets` использует SigV4 stdlib-хелпер из `evidence_anchor.py` взамен Basic Auth, исключая 400 ошибки); (3) исправление `test_openapi_contract.py::test_no_raw_token_in_parameters`: легитимный учёт `session_token` cookie из `deps.py`, достижение 2499/2499 зелёных pytest.
>
> **Acceptance:** принято 3 сентября 2026 (Apex). (1) Мост реализован поверх
> канонического носителя `runs.findings_refs` (COS-104), а не новой таблицы
> `cosmo_findings`: ExecutionService.finalize_run при all_passed оценивает
> плановые gates против РЕАЛЬНЫХ findings прогона через GatePolicyEngine
> (COS-055); verdict block → run.status=blocked (parity RCP COS-055, honesty
> COS-097 сохранена: degraded → failed раньше gate). Scan-сторона —
> POST /api/v1/runs/{run_id}/findings (SCAN_START + ghost-404 ownership,
> severity-валидация). PgFindingsProvider fail-open; авто-wiring в
> _start_core, kill-switch COSMO_GATE_BRIDGE_ENABLED (default on). SARIF-парсинг
> шагов Woodpecker НЕ входил в поставку — findings поступают через ingest
> API (адаптер Woodpecker отдаёт статусы, не отчёты; парсинг SARIF — отдельная
> карточка при появлении требуемых артефактов). (2) provision_minio_buckets:
> каждый HEAD/PUT подписан s3_sigv4_headers (канон COS-093), Basic Auth
> удалён — 400 "Please use AWS4-HMAC-SHA256" на живом MinIO исключены.
> (3) test_no_raw_token_in_parameters запрещает token/password/secret только
> в query (cookie — легитимный auth-канон COS-066/067/068); лок-тест
> test_session_token_is_cookie_only. Тесты: +26 (bridge 23, sigv4 2,
> auth-регрессия 1). Полный сет: **2526 passed / 8 skipped / 0 failed** (7:21).
> Примечание: в cosmo-openapi строка "SSE multiplexer ... (COS-101)"
> из sse.py коллизирует с номером этой карточки — это ложная привязка,
> не трогать (отдельно решает Максим).
>
> **Out of scope:** SARIF-парсинг отчётов Woodpecker-шагов (отдельная
> карточка), Web IDE (Flash в COS-100), live NVD vulnerability enrichment.

## ✅ DONE — WORKSPACE API: PYDANTIC CONTRACTS & DOMAIN DTO (PK-C-006.1)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-102** | Boss | 8-12h | P1 | COS-100 | ✅ DONE — Pydantic DTO в `orchestrator/cosmo/domain/workspace.py`: WorkspaceBootstrapRequest/Response, WorkspaceTreeRequest/Response, WorkspaceBlobRequest/Response, CAS base_blob_sha |

> **Scope:** (1) Реализация строгих Pydantic v2 DTO для Web IDE (`prettyk-ide`, :5176)
> по канону `D:\prettyk-ide\src\workspace\types.ts`;
> (2) `WorkspaceBootstrapRequest` (repo, branch?) → `WorkspaceBootstrapResponse` (repo, branch, head_sha, capabilities[], authorization);
> (3) `WorkspaceTreeRequest` (repo, branch, head_sha) → `WorkspaceTreeResponse` (entries[{path, kind, status?}]);
> (4) `WorkspaceBlobRequest` (repo, branch, path, head_sha) → `WorkspaceBlobResponse` (path, content, sha, encoding, base_blob_sha);
> (5) Валидация путей (directory traversal guard), head_sha обязателен для CAS-ready операций;
> (6) Unit-тесты DTO валидации и сериализации.
>
> **Acceptance:** принято 4 сентября 2026 (Boss).
> `orchestrator/cosmo/domain/workspace.py`: 6 DTO + TreeEntry, extra="forbid",
> camelCase через алиасы (`headSha`, `baseBlobSha`), жесткая валидация путей (отсекаются ..,
> abs-пути, backslash, drive letters, NUL, whitespace), CAS base_blob_sha обязателен.
> Тесты: 75/75 passed (`test_workspace_dto.py`). Mirror-тест с `prettyk-ide` types.ts — OK.
> Отчёт: `docs/research/2026-09-03-cos-102-workspace-dto.md`.

## ✅ DONE — WORKSPACE API: ROUTES & REPOS REFACTOR (PK-C-006.2 + PK-C-006.3)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-103** | Luna | 10-14h | P1 | COS-102 | ✅ DONE — Routes в `orchestrator/cosmo/api/routes/workspace.py`: GET /workspace/bootstrap, CAS-ready /tree и /file, вычистка mock/wire substrate из repos.py |

> **Scope:** (1) Новый роутер `orchestrator/cosmo/api/routes/workspace.py` (или расширение `repos.py` с изоляцией):
> `GET /api/v1/repos/workspace/bootstrap` — capability context, head_sha, authorization check через канонический DTO `WorkspaceBootstrapResponse`;
> (2) Доработка `GET /api/v1/repos/tree` — head_sha обязателен, возврат `WorkspaceTreeResponse`;
> (3) Доработка `GET /api/v1/repos/file` — возврат `WorkspaceBlobResponse` с обязательным `base_blob_sha` для CAS;
> (4) Очистка mock/wire substrate из `repos.py` (удаление in-memory FS fallback и захардкоженных `.wire` примеров);
> (5) Подключение к реальному `GiteaForgeAdapter` для чтения дерева коммита и блобов; маппинг `WorkspaceContractError` в HTTP 400.
>
> **Acceptance:** роуты возвращают строго типизированные Pydantic ответы; при несовпадении head_sha — честный 409/400;
> вызовы читают данные из ForgeAdapter; старый mock-код удалён без регрессий.
>
> **Принято 4 сентября 2026 (Luna):** три CAS-ready read-роута поверх
> реального `GiteaForgeAdapter` (+`get_commit`/`get_tree` с честным
> truncated/empty-repo). Ресурс = binding приложения: ghost-404 через
> канонический `verify_ownership`/`resolve_caller_domain` (чужой домен
> → 404 anti-enumeration, заголовок не расширяет доступ). Честный CAS:
> head_sha сверяется с головой ветки, расхождение → 409. Traversal →
> 400 (guard-функции DTO), forge not configured → 503, unreachable →
> 502, missing → 404, пустое репо → честно пусто. Из repos.py удалён
> `_MOCK_REPO_FILES` со всеми `.wire`-сценариями (кликер-мусор,
> инвариант AGENTS), in-memory VFS и PUT /file; commit/commit-and-run
> (реальный PG) сохранены. capabilities честные (свой домен — полный
> набор, админский cross-domain — read-only).
> Тесты: `test_workspace_routes.py` 21 новый + линии DTO/surface/
> transfer/forge 195 passed; **полный сет 2555 passed / 12 skipped /
> 0 failed**. Отчёт: `docs/research/2026-09-04-cos-103-workspace-routes.md`.
>
> **Out of scope:** contract-тесты и OpenAPI (Flash в COS-104), OpenBao (Boss в COS-105).

## ✅ DONE — WEB IDE CLIENT TYPES & WORKSPACE CONTRACT SYNC (PK-DIR-008 §2)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-104** | Flash | 8-12h | P1 | COS-102 | ✅ DONE — Синхронизация client types в `prettyk-ide`, test_workspace_contract.py (15/15 passed), OpenAPI обновлён (108 paths) |

> **Scope:** (1) В `D:\prettyk-ide\src\workspace\types.ts`: актуализировать интерфейсы под DTO COS-102:
> добавить `baseBlobSha: string` в `WorkspaceBlobResponse`, зафиксировать Request типы (`WorkspaceBootstrapRequest`, `WorkspaceTreeRequest`, `WorkspaceBlobRequest`);
> (2) Обновить MSW handlers / моки в `prettyk-ide` для возврата `baseBlobSha` и поддержки CAS-проверок;
> (3) Contract-тесты в Cosmo: `orchestrator/tests/cosmo/test_workspace_contract.py` — проверка совместимости сериализации FastAPI с ожидаемым форматом клиента;
> (4) Обновление схемы OpenAPI (`docs/cosmo-openapi.json`, `docs/cosmo-openapi.yaml`) с новыми моделями.
>
> **Acceptance:** принято 5 сентября 2026 (Flash).
> Контракт-тесты: `test_workspace_contract.py` — 15/15 passed.
> OpenAPI JSON/YAML обновлены: 108 путей, схемы `WorkspaceBootstrapResponse`, `WorkspaceTreeResponse`,
> `WorkspaceBlobResponse`, `WorkspaceCommitRequest`, `WorkspaceCommitResponse`.
> В `forge_gitea.py` согласованы структуры `GiteaTreeEntry`, `get_commit`, `get_tree`.
>
> **Out of scope:** реализация бекенд-роутов (Luna в COS-103), OpenBao (Boss в COS-105).

## ✅ DONE — PLATFORM OPENBAO MIGRATION & ADAPTER CLEANUP (PK-DIR-008 §1 / PK-C-005)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-105** | Boss | 8-12h | P1 | COS-102 | ✅ DONE — OpenBao AppRole Vault-адаптер (`infra/vault.py`), env-канон, graceful startup, 20 тестов (16 passed / 4 live skipped) |

> **Scope:** (1) `docker-compose.yml`: приведение `cosmo-openbao` к платформенным env (`OPENBAO_DEV_*` / `VAULT_DEV_*`);
> (2) `orchestrator/cosmo/infra/vault.py`: `VaultClient` с AppRole-аутентификацией (`role_id` + `secret_id`), получение scoped token `secret/cosmo/*`, retry на 5xx, re-auth при token expiry, kv-v2 secret I/O;
> (3) Поддержка env-переменных: `VAULT_ADDR` (default `http://localhost:8200`), `VAULT_APPROLE_ROLE_ID`, `VAULT_APPROLE_SECRET_ID`; dev fallback при `COSMO_ENV=test`;
> (4) Интеграция в рантайм: `orchestrator/cosmo/api/deps.py` (`get_vault()`, `init_vault()`), `startup.py` (Vault health check + warning при недоступности, без падения рантайма);
> (5) Unit и интеграционные тесты AppRole-аутентификации и чтения/записи секретов в `tests/cosmo/test_vault.py`.
>
> **Acceptance:** принято 4 сентября 2026 (Boss).
> `orchestrator/cosmo/infra/vault.py` реализован (чистый `requests`, retry, auto-reauth, kv-v2).
> Startup-graceful интеграция проверена. Тесты: 16 passed, 4 live skipped (требуют поднятый сервис).
> Отчёт: `docs/research/2026-09-03-cos-105-openbao-adapter.md`.
>
> **Out of scope:** настройка платформенного OpenBao на хосте (Buddy в PK-C-005).

## ✅ DONE — PLATFORM RENAMING ALIGNMENT: QGFCS → HUB (PK-DIR-008 §1)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-106** | Luna | 4.5h | P2 | COS-103 | ✅ DONE — Сквозная вычистка упоминаний qgfcs -> hub по директиве PK-DIR-008 во всём активном коде и доках Cosmo |

> **Story (done 2026-09-05):** Grep `qgfcs` по всему репозиторию → замена на `hub`/`prettyk-hub` в живых канонах и документах; исторические записи сохранили пометку «ранее qgfcs». 0 вхождений в активном коде (`orchestrator/` свободен).
>
> **Приёмка:**
> - `orchestrator/` — grep `qgfcs` = 0
> - Тесты workspace-линии: 96 passed (routes 21 + dto 75)
> - Изменено 12 файлов в `docs/`, `battlecruiser/`, `AGENTS.md`
>
> **Конфликтующих изменений нет.**

## ✅ DONE — WORKSPACE CAS COMMIT: ATOMIC WRITE & DRAFT PERSISTENCE (PK-DIR-008 §3 / PK-C-006.6)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-107** | Boss | 10-14h | P1 | COS-103 | ✅ DONE — POST /api/v1/repos/workspace/commit: create_commit в GiteaForgeAdapter, CAS base_blob_sha, 16 passed |

> **Scope:** (1) DTO `WorkspaceCommitRequest` (repo, branch, message, changes: [{path, content, base_blob_sha, action: 'upsert'|'delete'}], expected_head_sha) и `WorkspaceCommitResponse` (commit_sha, branch, tree_sha);
> (2) Реализация `POST /api/v1/repos/workspace/commit` в `orchestrator/cosmo/api/routes/workspace.py`;
> (3) CAS-верификация: для каждого изменяемого файла проверяется соответствие текущего `blob_sha` в ветке переданному `base_blob_sha`; при конфликте — HTTP 409 Conflict с деталями расхождения;
> (4) Создание коммита через `GiteaForgeAdapter` (Contents/Tree API);
> (5) Запись события коммита в `cosmo_audit_events`.
>
> **Acceptance:** принято 5 сентября 2026 (Boss).
> `create_commit` в `forge_gitea.py` реализован с Contents API (POST для новых, PUT с SHA для update, DELETE).
> CAS-проверка на роуте через `expected_head_sha` + `base_blob_sha` возвращает 409 при дрифте.
> Live smoke на Gitea: 201 + commitSha + treeSha.
> Тесты: `test_workspace_commit.py` — 16 passed, 2 skipped. Suite gate: 2586 passed, 14 skipped, 0 failed.
> Отчёт: `docs/research/2026-09-05-cos-107-workspace-commit.md`.

## ✅ DONE — WORKSPACE RUN TRIGGER & PIPELINE COMPILATION (PK-DIR-008 §3 / PK-C-006.7)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-108** | Luna | 10-14h | P1 | COS-107 | ✅ DONE — POST /api/v1/repos/workspace/run: компиляция пайплайна, запуск Woodpecker, cosmo_workspace_runs |

> **Scope & Story (done 2026-09-05):**
> (1) DTO `WorkspaceRunRequest` (repo, branch, commit_sha, pipeline_name?) и `WorkspaceRunResponse` (run_id, pipeline_id, status, tracking_url) в `domain/workspace.py`;
> (2) `WorkspaceRunRow` в `db/models_execution.py` (таблица `cosmo_workspace_runs` на `ExecutionBase`);
> (3) Фабрика `build_woodpecker()` и нормализация ошибок в `api/woodpecker_client.py`;
> (4) Маршрут `POST /api/v1/repos/workspace/run` в `api/routes/workspace.py` (resolve binding -> CAS head verification -> submit -> persist -> 201 Created);
> (5) Регистрация метаданных в `api/startup.py` и `conftest.py`.
>
> **Acceptance:** принято 5 сентября 2026 (Luna).
> 24 passed в `test_workspace_run.py` (13 route + 11 DTO).
> Регресс: Workspace-линия 120 passed, полный suite 2621 passed / 15 skipped / 0 failed.
>
> **Приёмка:**
> - `domain/workspace.py` — DTO `WorkspaceRunRequest`/`WorkspaceRunResponse` (Pydantic v2, `extra="forbid"`, camelCase-алиасы)
> - `api/woodpecker_client.py` — фабрика `build_woodpecker()` + нормализация `woodpecker_http_error`
> - `api/routes/workspace.py` — маршрут `POST /workspace/run` (resolve binding → CAS head verification → submit → persist `WorkspaceRunRow` → 201)
> - `db/models_execution.py` — `WorkspaceRunRow` (таблица `cosmo_workspace_runs` на `ExecutionBase`)
> - `api/startup.py` — `ExecutionBase.metadata.create_all` в lifespan
> - `conftest.py` — `create_all` + wipe для execution-моделей
> - Исправлен interference в `test_anonymous_401`: monkeypatch → прямое `dependency_overrides` + `pop`
> - **Конфликтующих изменений нет.**

## ✅ DONE — SSE RUN LOGS STREAMING BRIDGE (PK-DIR-008 §3 / PK-C-006.8)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-109** | Flash | 8-12h | P1 | COS-108 | ✅ DONE — GET /api/v1/runs/{run_id}/logs/stream: SSE мультиплексор живого лога шагов Woodpecker для Web IDE drawer |

> **Acceptance (Flash, 5 сентября 2026):** 11 contract тестов зелёные (mock-based, без PG):
> step_start/log_chunk/step_finish/run_finish schema, run not found, already finished,
> no handle yet, step lifecycle, multi-batch, client disconnect. SSE endpoint
> `GET /api/v1/runs/{run_id}/logs/stream` в `sse.py`, ticket-auth (COS-079 pattern),
> polling-цикл 1s/15s keepalive, per-step cursor tracking, catch-up для поздно
> подключившихся. Suite gate: **2613 passed** (+11), 0 моих failures.
>
> **Scope выполнен:** (1) Роут; (2) Polling Woodpecker API с tail через cursor offset;
> (3) lines[] в JSON-payload, клиент joins с `\r\n`, ansi as-is; (4) asyncio.CancelledError
> + adapter.close() в finally; (5) 11 mock contract тестов (эмуляция pipeline-переходов
> и поступления логов).
>
> **Отчёт:** `docs/research/2026-09-05-cos-109-sse-logs-stream.md`.
>
> **Follow-up:** backlog/replay для log_chunk (COS-088), E2E smoke с COS-108 run+log циклом,
> пагинация исторических логов (отдельный не-SSE эндпоинт).

## ✅ DONE — WORKSPACE DRAFTS & 3-WAY MERGE DIFF ENGINE (PK-DIR-008 §3 / PK-C-006.9)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-110** | Boss | 10-14h | P1 | COS-107 | ✅ DONE — Хранилище черновиков в Valkey-only (TTL 7d), 3-way diff, PUT/GET/DELETE /workspace/draft, 23 passed |

> **Scope & Story (done 2026-09-05):**
> (1) Pydantic DTO `WorkspaceDraftUpsertRequest`, `WorkspaceDraftResponse`, `WorkspaceDiffResponse` в `domain/workspace.py` (camelCase, traversal guard, extra="forbid");
> (2) Хранилище Valkey-only в `infra/valkey_drafts.py`: Lazy Valkey, TTL 7d, ключ `cosmo:draft:{domain}:{user_id}:{owner}:{repo}:{branch}:{path}` (0 новых таблиц в PG); при сбое Valkey — честный 503 Service Unavailable;
> (3) Роуты в `orchestrator/cosmo/api/routes/workspace.py`:
> `PUT /api/v1/repos/workspace/draft` — сохранение черновика (201 Created);
> `GET /api/v1/repos/workspace/draft` — получение сохранённого черновика;
> `DELETE /api/v1/repos/workspace/draft` — удаление черновика (204 No Content);
> `GET /api/v1/repos/workspace/diff` — вычисление 3-way diff (base_blob_sha vs draft vs head в Gitea);
> (4) Diff engine: вычисление `has_conflict`, `additions`, `deletions`;
> (5) Smoke & tests: `cos110_smoke.py` (live PUT -> GET -> diff -> DELETE -> GET 404), `test_workspace_draft.py` (23 passed, 2 skipped), общий сьют 2644 passed / 0 failures.
>
> **Acceptance:** принято 5 сентября 2026 (Boss). Отчёт: `docs/research/2026-09-05-cos-110-workspace-drafts.md`.

## ✅ DONE — WEB IDE TERMINAL DRAWER & LIVE LOGS VIEWER (PK-DIR-008 §3 / PK-C-006.10)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-111** | Flash | 8-12h | P1 | COS-109 | Bottom Drawer в Web IDE: подключение к SSE logs stream, per-step live autoscroll, ANSI colors, collapse/expand |

> **Scope:** (1) React компонент `WebIDETerminalDrawer.tsx` в `D:\prettyk-ide\src\cosmo\ide\`;
> (2) Кастомный хук `useRunLogsStream(runId)`: получение one-time SSE ticket, подключение к `GET /api/v1/runs/{runId}/logs/stream`, обработка `step_start`, `log_chunk`, `step_finish`, `run_finish`;
> (3) Отрисовка шагов с бейджами статусов (`running` спиннер, `success` зелёная галочка, `failed` красный крест);
> (4) Рендеринг ANSI-последовательностей и моноширинный вывод с автопрокруткой к последней строке активного шага через xterm.js + FitAddon;
> (5) Кнопка свернуть/развернуть нижний Drawer в `App.tsx`, кнопка `▶ Run` в topbar, автооткрытие по `?run=` query param, очистка лога, кнопка перехода в RunControl станции;
> (6) Чистый редюсер `reduceRunLogs` и 12 vitest тестов в `useRunLogsStream.test.tsx`, проверка типов `tsc -b` (14/14 passed в `prettyk-ide`).
>
> **Acceptance:** принято 6 сентября 2026 (Flash).
> Тесты в `prettyk-ide`: 14 passed (vitest run), `tsc -b` green. Live SSE logs stream подключён к терминальному Drawer.

## ✅ DONE — WORKSPACE RUN HISTORY & STEP LOGS REST API (PK-DIR-008 §3 / PK-C-006.11)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---|---:|---|---|
| **COS-112** | Luna | 6-8h | P2 | COS-108 | GET /api/v1/workspace/runs & GET /api/v1/runs/{run_id}/steps/{step_id}/logs: исторический просмотр и пагинация |

> **Story:** (1) DTO `WorkspaceRunSummary` + `WorkspaceRunListResponse` + `StepLogsResponse` в `domain/workspace.py`;
> (2) Роут `GET /workspace/runs` на существующем router (пагинация limit/offset, фильтр status/branch, ownership-чек через `_binding_for_repo`);
> (3) Роут `GET /runs/{run_id}/steps/{step_id}/logs` на новом `run_log_router` (prefix `/api/v1/runs`, регистрация перед `runs_router`);
> (4) `WoodpeckerAdapter.get_step_logs_by_id()` — поиск шага по Woodpecker DB id;
> (5) Тесты 29/29 в `test_workspace_run_history.py` (11 DTO + 10 runs list + 8 step logs);
> (6) `run_log_router` зарегистрирован в `main.py` перед `runs_router` во избежание затенения `GET /api/v1/runs/{id}`.
>
> **Acceptance:** принято 5 сентября 2026 (Luna).
> 29 passed в `test_workspace_run_history.py`. Suite gate: 2673 passed / 0 failed.
> `GET /workspace/runs?repo=owner/name` — пагинация, total, фильтрация по status/branch, 404 ghost, 401 anonymous.
> `GET /runs/{run_id}/steps/{step_id}/logs` — offset/limit, tail, 404 на чужой run, 502 на WP down, 401 anonymous.
>
> **Конфликтующих изменений нет.**

## ✅ DONE — WORKSPACE BRANCHES & TAGS LIFECYCLE ENGINE (PK-DIR-008 §3 / PK-C-006.12)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-113** | Boss | 8-12h | P1 | COS-107 | GET/POST/DELETE /workspace/branches & GET /workspace/tags: управление ветками и тегами в Web IDE |

> **Scope:** (1) DTO `WorkspaceBranchSummary`, `WorkspaceBranchListResponse`, `WorkspaceCreateBranchRequest`, `WorkspaceTagSummary`, `WorkspaceTagListResponse` в `domain/workspace.py` (camelCase, extra="forbid", branch name validation);
> (2) Методы в `GiteaForgeAdapter` (`orchestrator/cosmo/adapters/forge_gitea.py`):
> `list_branches(owner, repo)` — получение списка веток с HEAD commit sha, `is_default`, `is_protected`;
> `create_branch(owner, repo, new_branch_name, old_branch_name)` — создание ветки от базы;
> `delete_branch(owner, repo, branch_name)` — удаление feature-ветки;
> `list_tags(owner, repo)` — список тегов с commit sha;
> (3) Роуты в `orchestrator/cosmo/api/routes/workspace.py`:
> `GET /api/v1/repos/workspace/branches?repo=...` — список веток с флагами default/protected;
> `POST /api/v1/repos/workspace/branches` — создание новой ветки (409 при коллизии имени);
> `DELETE /api/v1/repos/workspace/branches?repo=...&branch=...` — удаление ветки (400 при попытке удалить default_branch);
> `GET /api/v1/repos/workspace/tags?repo=...` — список тегов;
> (4) Безопасность: anti-enumeration 404 для не привязанных к домену репозиториев, Bearer token auth;
> (5) Unit + route тесты в `test_workspace_branches.py` (20/20 passed, suite gate 2693/0).
>
> **Acceptance:** принято 6 сентября 2026 (Boss).
> 20 passed в `test_workspace_branches.py`. Suite gate: 2693 passed / 0 failed.
> Отчёт: `docs/research/2026-09-06-cos-113-workspace-branches-tags.md`.

## ✅ DONE — WORKSPACE SEARCH & CODE GREP ENGINE (PK-DIR-008 §3 / PK-C-006.13)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---|---:|---|---|
| **COS-114** | Luna | 6-8h | P2 | COS-103 | GET /api/v1/repos/workspace/search: полнотекстовый поиск и grep по кодовой базе репозитория |

> **Story (done 2026-09-05):** (1) DTO `WorkspaceSearchMatch` (path, lineNumber, lineContent, matchStart, matchEnd) и `WorkspaceSearchResponse` (query, matches, totalMatches, scannedFiles, hasMore) в `domain/workspace.py` — camelCase, extra="forbid";
> (2) Маршрут `GET /api/v1/repos/workspace/search` (repo, q min 2 chars, branch, path_prefix, caseSensitive, isRegex, limit 1-100) в `routes/workspace.py`;
> (3) Механизм: get_tree (рекурсивный) → фильтр бинарных расширений (_BINARY_EXTENSIONS, 30+ типов) → read_file → regex/match (finditer построчный, сбор до limit);
> (4) ReDoS-защита: cap длины паттерна 1000 символов + re.error catch для невалидного regex;
> (5) Безопасность: _binding_for_repo ownership check, ghost 404, traversal guard.
>
> **Acceptance:** принято 5 сентября 2026 (Luna).
> 20 passed в `test_workspace_search.py` (7 DTO + 13 route). Suite gate: 2713 passed / 0 failed.
> Бинарные файлы (.png, .zip, .exe, ...) молча пропускаются; regex search работает; path_prefix фильтрует; limit обрезает с флагом hasMore; инвалидный regex → 400; аноним → 401; ghost repo → 404.
>
> **Конфликтующих изменений нет.**

## ✅ DONE — WEB IDE RUN TRIGGER CLIENT & EXECUTION FLOW (PK-DIR-008 §3 / PK-C-006.14)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-115** | Flash | 6-8h | P1 | COS-111, COS-108 | Web IDE: вызов POST /api/v1/repos/workspace/run по клику ▶ Run, состояние запуска и связка с Terminal Drawer |

> **Scope:** (1) Метод `client.runWorkspace(repo, branch, headSha, pipelineName?)` в `D:\prettyk-ide\src\workspace\client.ts` с DTO `WorkspaceRunResponse` (run_id, pipeline_number, pipeline_id, status, tracking_url);
> (2) Обработчик кнопки `▶ Run` в `App.tsx`:
> - состояние `triggering` (спиннер/disabled на кнопке во время HTTP POST);
> - получение `run_id` из ответа `POST /api/v1/repos/workspace/run`;
> - автоматическое открытие `WebIDETerminalDrawer`, установка `runId`, очистка предыдущих логов;
> - сохранение `?run=<run_id>` в URL query params через `window.history.replaceState` для шаринга/релоада;
> - обработка ошибок запуска (409 CAS out-of-date, 404 no pipeline, 502/503 forge/woodpecker down) с баннером ошибки `.run-error-banner`;
> (3) Юнит-тесты клиента `client.test.ts` (8 passed) и `useRunLogsStream.test.tsx` (12 passed), всего 20/20 passed, `tsc -b` green.
>
> **Acceptance:** принято 6 сентября 2026 (Flash).
> Клик ▶ Run отправляет POST `/api/v1/repos/workspace/run`, получает run_id, открывает Terminal Drawer и начинает живой стриминг шагов через SSE. URL синхронизируется через `replaceState`.

## ✅ DONE (2026-09-06 Boss) — WORKSPACE COMMITS HISTORY & TIMELINE API (PK-DIR-008 §3 / PK-C-006.15)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-116** | Boss | 6-8h | P2 | COS-113 | GET /api/v1/repos/workspace/commits: история коммитов ветки и таймлайн конкретного файла |

> **Scope:** (1) DTO `WorkspaceCommitSummary` (sha, short_sha, message, author_name, author_email, committed_at, parent_shas) и `WorkspaceCommitListResponse` (commits: list[WorkspaceCommitSummary], total, has_more) в `domain/workspace.py` (camelCase, extra="forbid");
> (2) Метод в `GiteaForgeAdapter` (`orchestrator/cosmo/adapters/forge_gitea.py`):
> `list_commits(owner, repo, branch?, path?, limit?, page?)` — запрос к Gitea API `/repos/{owner}/{repo}/commits` с маппингом полей автора, хэшей и сообщений;
> (3) Эндпоинт `GET /api/v1/repos/workspace/commits` в `orchestrator/cosmo/api/routes/workspace.py`:
> Параметры: `repo` (обязателен), `branch` (опционален, default HEAD), `path` (опционален для фильтра истории одного файла), `limit` (default 30, max 100), `offset` (default 0);
> (4) Безопасность: Bearer auth, domain ownership check через `_binding_for_repo`, 404 ghost-изоляция чужих репозиториев;
> (5) Unit + route тесты в `test_workspace_commits.py`.
>
> **Acceptance:** Web IDE может отображать список последних коммитов по ветке и историю изменений конкретного файла; пагинация и фильтр пути работают корректно; тесты проверяют DTO, адаптер, роут и ghost-изоляцию (404).

## ⏸️ BLOCKED — WORKSPACE FILE BLAME & ANNOTATION ENGINE (PK-DIR-008 §3 / PK-C-006.16)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-117** | Boss | 6-8h | P2 | Gitea ≥1.23 | GET /api/v1/repos/workspace/blame: построчная аннотация файла (git blame) для Web IDE |

> **Blocker note (2026-09-06 Boss):** В Gitea 1.22.6 эндпоинт `/repos/{owner}/{repo}/blame/{filepath}` отсутствует (blame REST API появился только в Gitea ≥1.23). Прямой вызов CLI `git blame` на хосте нарушает суверенный decoupled-контракт ForgeAdapter. Задача запаркована до инфраструктурного апгрейда Gitea до 1.23+. Boss переключён на **COS-120**.
>
> **Scope:** (1) DTO `WorkspaceBlamePart` (commitSha: str, commitShortSha: str, authorName: str, authorEmail: str, committedAt: datetime, lines: list[str]) и `WorkspaceBlameResponse` (path: str, branch: str, parts: list[WorkspaceBlamePart]) в `domain/workspace.py` (camelCase, extra="forbid");
> (2) Метод в `GiteaForgeAdapter` (`orchestrator/cosmo/adapters/forge_gitea.py`):
> `get_file_blame(owner, repo, filepath, ref)` — запрос к Gitea API `/repos/{owner}/{repo}/blame/{filepath}?ref={ref}` с разбором структуры блоков коммитов и строк;
> (3) Эндпоинт `GET /api/v1/repos/workspace/blame` в `orchestrator/cosmo/api/routes/workspace.py`:
> Параметры: `repo` (обязателен), `path` (обязателен), `branch` (опционален, default HEAD);
> Обработка краевых случаев: бинарный файл → 400 Bad Request, файл не найден → 404 Not Found;
> (4) Безопасность: Bearer auth, domain ownership check через `_binding_for_repo`, path traversal guard, 404 ghost-изоляция;
> (5) Unit + route тесты в `test_workspace_blame.py`.
>
> **Acceptance:** Web IDE при просмотре файла может получить построчную аннотацию коммитов (автор, хэш, дата, строки); тесты покрывают DTO, адаптер (включая мок Gitea blame API), роут, бинарные/отсутствующие файлы и ghost-изоляцию.

## ✅ DONE (2026-09-06 Luna) — WORKSPACE PIPELINE DISCOVERY & METADATA ENGINE (PK-DIR-008 §3 / PK-C-006.17)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-118** | Luna | 4h | P2 | COS-108 | GET /api/v1/repos/workspace/pipelines: обнаружение и валидация пайплайнов репозитория |

> **Scope:** (1) DTO `WorkspacePipelineSummary` (name, path, format, isDefault, stepNames) и `WorkspacePipelineListResponse` (pipelines, defaultPipeline) в `domain/workspace.py` (camelCase, extra="forbid");
> (2) Маршрут `GET /api/v1/repos/workspace/pipelines` в `orchestrator/cosmo/api/routes/workspace.py`:
> Параметры: `repo` (обязателен), `branch` (опционален, default HEAD);
> (3) Механизм обнаружения:
> - чтение дерева репозитория через `ForgeAdapter.get_tree`;
> - сканирование корня на `.woodpecker.yaml` / `.woodpecker.yml` / `.pipeline.yaml`;
> - сканирование папки `.woodpecker/*.yaml` и `.woodpecker/*.yml`;
> - чтение файлов через `ForgeAdapter.read_file`, безопасный парсинг `yaml.safe_load`, извлечение списка шагов (pipeline/steps);
> - толерантность к битым/невалидным YAML-файлам (не падать 500, возвращать `format: "invalid"`, `stepNames: []` или пропускать с логированием);
> (4) Безопасность: Bearer auth, domain ownership check, traversal guard, ghost 404;
> (5) Unit + route тесты в `test_workspace_pipelines.py` (21 passed, suite gate: 2748 passed / 0 failed).
>
> **Acceptance:** принято 6 сентября 2026 (Luna).
> 21 passed в `test_workspace_pipelines.py`. Suite gate: 2748 passed / 0 failed.

## ✅ DONE (2026-09-06 Flash) — WEB IDE BRANCH SWITCHER & CREATION FLOW (PK-DIR-008 §3 / PK-C-006.18)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-119** | Flash | 6-8h | P1 | COS-113, COS-115 | Web IDE: переключение веток, создание feature-ветки и удаление через Workspace API |

> **Scope:** (1) TypeScript типы в `D:\prettyk-ide\src\workspace\types.ts`: `WorkspaceBranchSummary` (name, sha, isDefault, isProtected), `WorkspaceBranchListResponse` (branches, defaultBranch);
> (2) Методы клиента в `D:\prettyk-ide\src\workspace\client.ts`:
> - `listBranches(repo: string): Promise<WorkspaceBranchListResponse>` (GET `/api/v1/repos/workspace/branches`);
> - `createBranch(repo: string, branch: string, baseBranch: string): Promise<WorkspaceBranchSummary>` (POST `/api/v1/repos/workspace/branches`);
> - `deleteBranch(repo: string, branch: string): Promise<void>` (DELETE `/api/v1/repos/workspace/branches`);
> (3) UI компонент `BranchSelector` в topbar (`D:\prettyk-ide\src\app\App.tsx`):
> - отображение текущей ветки в topbar с кликабельным дропдауном;
> - список веток с поиском/фильтрацией и бейджами `default` / `protected`;
> - переключение ветки с обновлением URL query param `?branch=...` и перезагрузкой дерева файлов;
> - диалог «Create branch» (ввод имени новой ветки, валидация, создание от текущей ветки и автоматический переход);
> - удаление не-default веток (кнопка ×), обработка 409 коллизий и 400 защиты default-ветки;
> (4) Vitest тесты: клиентские тесты в `client.test.ts` (14 passed) + `useRunLogsStream.test.tsx` (12 passed), всего 26/26 passed, `tsc -b` green.
>
> **Acceptance:** принято 6 сентября 2026 (Flash).
> Пользователь видит текущую ветку, открывает дропдаун, фильтрует, переключается (дерево перезагружается без полного ремаунта), создаёт и удаляет ветки.

## ✅ DONE (2026-09-06 Boss) — WORKSPACE FILE ACTIONS & MUTATOR API (PK-DIR-008 §3 / PK-C-006.19)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-120** | Boss | 6-8h | P2 | COS-107 | POST/DELETE /api/v1/repos/workspace/files & /move: прямое создание, удаление и перемещение файлов с CAS |

> **Scope:** (1) DTO `WorkspaceFileCreateRequest` (path, content, message?, baseBranch?, isBase64?), `WorkspaceFileDeleteRequest` (path, message?, branch?, lastCommitSha?), `WorkspaceFileMoveRequest` (sourcePath, targetPath, message?, branch?, lastCommitSha?) и `WorkspaceFileActionResponse` (commitSha, path, status) в `domain/workspace.py` (camelCase, extra="forbid");
> (2) Методы в `GiteaForgeAdapter` (`orchestrator/cosmo/adapters/forge_gitea.py`):
> `create_file`, `delete_file`, `move_file` — вызов Gitea Contents API `/repos/{owner}/{repo}/contents/{path}`;
> (3) Эндпоинты в `orchestrator/cosmo/api/routes/workspace.py`:
> `POST /api/v1/repos/workspace/files` (201/409/400),
> `DELETE /api/v1/repos/workspace/files` (200/404),
> `POST /api/v1/repos/workspace/files/move` (200/404/409);
> (4) Безопасность: Bearer auth, domain ownership check через `_binding_for_repo`, traversal guard до вызова адаптера, ghost 404;
> (5) Unit + route тесты в `test_workspace_files.py` (24/24 passed).
> **Баг, найденный тестами:** 4 DTO использовались в аннотациях route-обработчиков, но не были импортированы; `from __future__ import annotations` скрывал ошибку при импорте модуля, но FastAPI превращал body в query-параметр → 422. Добавлен импорт — все тесты зелёные.
>
> **Acceptance:** принято 6 сентября 2026 (Boss).
> 24/24 passed в `test_workspace_files.py`. Suite gate: 2821 passed / 1 failed / 17 skipped (единственный failure — pre-existing test_duplicate_trigger_no_duplicate_notification).

## ✅ DONE (2026-09-06 Flash) — WEB IDE CODE SEARCH & GREP PALETTE (PK-DIR-008 §3 / PK-C-006.20)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-121** | Flash | 8-10h | P1 | COS-114 | Web IDE: модальная палитра поиска Ctrl+Shift+F с подсветкой вхождений и мгновенным переходом к строке |

> **Scope:** (1) Метод клиента `client.searchWorkspace(repo, query, options)` с DTO `WorkspaceSearchResponse`;
> (2) React-компонент `SearchPalette.tsx` — шорткат `Ctrl+Shift+F`, debounced поиск (300ms), переключатели Match Case/Regex/Subpath,
> группировка по файлам с бейджем вхождений, сниппеты с подсветкой, клик → переход к строке в редакторе, индикатор «Showing 50 matches (more available)», красное сообщение при 400 (невалидный regex);
> (3) Vitest тесты — клиентские + компонентные.
>
> **Acceptance:** принято 6 сентября 2026 (Flash).
> 40/40 vitest passed, `tsc -b` green.

## ✅ DONE (2026-09-18 Flash) — WEB IDE PIPELINE RUNNER DIALOG (PK-DIR-008 §3 / PK-C-006.21)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-122** | Flash | 6-8h | P1 | COS-118, COS-115 | Web IDE: селектор пайплайнов по кнопке ▶ Run, инспектор шагов и передача pipelineName в запуск |

> **Scope:** (1) Метод клиента `client.listPipelines(repo, branch)` в `D:\prettyk-ide\src\workspace\client.ts` с DTO `WorkspacePipelineListResponse`;
> (2) UI модалка/поповер `PipelineRunModal.tsx` в `D:\prettyk-ide\src\cosmo\ide\`:
> - при клике на стрелку рядом с кнопкой `▶ Run` открывается селектор обнаруженных пайплайнов (из COS-118);
> - превью шагов выбранного пайплайна (названия шагов, тип);
> - выбор дефолтного пайплайна или любого из обнаруженных в `.woodpecker/*.yaml`;
> - кнопка запуска вызывает `client.runWorkspace(repo, branch, headSha, selectedPipelineName)`;
> - закрытие модалки с переходом в открывшийся Terminal Drawer;
> (3) Vitest тесты: проверка выбора пайплайна, передачи `pipelineName` в API и дефолтного fallback.
>
> **Acceptance:** принято 18 сентября 2026 (Flash).
> `tsc -b` — 0 ошибок; `vitest run` — 54/54 passed (4 файла).
>
> **Контрактный нюанс:** дефолтный `▶ Run` не отправляет `pipelineName` (`JSON.stringify` отбрасывает `undefined`) и сохраняет совместимость с текущим BE COS-108. Выбор конкретного pipeline через `▾` отправляет `pipelineName`; его исполнение требует отдельного BE-контракта COS-127.

## ✅ DONE (2026-09-06 Luna) — WORKSPACE PRE-FLIGHT QUALITY GATE VERDICT (PK-DIR-008 §3 / PK-C-006.22)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-123** | Luna | 5h | P2 | COS-110, COS-107 | POST /api/v1/repos/workspace/gate-check: пре-флайт сканирование черновиков на секреты и запрещённые паттерны |

> **Scope:** (1) DTO `WorkspaceGateCheckRequest`, `WorkspaceGateViolation`, `WorkspaceGateVerdictResponse` в `domain/workspace.py`;
> (2) Модуль `domain/gate_verdict.py` — verdict engine (7 BLOCK + 3 WARN rules: RSA/OPENSSH ключи, токены AWS/OpenBao/GitHub/Gitea, пароли, .env/.pem/.key/credentials.json);
> (3) Роут `POST /api/v1/repos/workspace/gate-check` в `routes/workspace.py` — сканирование diff/draft, вердикт PASS/WARN/BLOCK с точным указанием пути и строки;
> (4) Безопасность: Bearer auth, domain ownership check, traversal guard;
> (5) Unit + route тесты в `test_workspace_gate_check.py` (50/50 passed).
>
> **Acceptance:** принято 6 сентября 2026 (Luna).
> 50/50 passed. Suite gate: 2772/0.

## ✅ DONE (2026-09-18 Boss) — WORKSPACE COMMIT API: MULTI-FILE ATOMIC COMMIT (PK-DIR-008 §3 / PK-C-006.23)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-124** | Boss | 8-10h | P1 | COS-120, COS-123 | POST /api/v1/repos/workspace/commits: атомарный коммит нескольких файлов через bulk Contents API (Gitea 1.22.6) |

> **Scope:** (1) DTO `WorkspaceCommitRequest` (repo: str, branch: str, message: str, authorName: str | None, authorEmail: str | None, fileChanges: list[WorkspaceFileChange]) где `WorkspaceFileChange` = (path: str, content: str | None, action: Literal["create", "update", "delete"]) и `WorkspaceCommitResponse` (sha: str, htmlUrl: str, authoredAt: datetime, filesChanged: int) в `domain/workspace.py` (camelCase, extra="forbid");
> (2) Метод в `GiteaForgeAdapter` (`orchestrator/cosmo/adapters/forge_gitea.py`):
> `commit_changes(owner, repo, branch, message, fileChanges, authorName, authorEmail)` — реальный Gitea 1.22.6 bulk Contents API:
> POST `/repos/{owner}/{repo}/contents` с `ChangeFilesOptions` / `repoChangeFiles` (`operation ∈ {create, update, delete}`); content кодируется base64, `sha` обязателен для update/delete;
> ответ `FilesResponse` → `commit.{sha, created, html_url}` + `files[]`; create/update/delete выполняются одной атомарной операцией;
> (3) Эндпоинт `POST /api/v1/repos/workspace/commits` в `orchestrator/cosmo/api/routes/workspace.py`:
> - Параметры: body = WorkspaceCommitRequest;
> - Пре-флайт gate-check: вызов gate_verdict.check() на fileChanges перед деревом (если BLOCK → 422 с violations);
> - 400 при пустом fileChanges[] или path traversal;
> - 404 при несуществующей ветке;
> - 409 при конфликте ref (конкурентный коммит — передавать SHA для retry);
> (4) Безопасность: Bearer auth, domain ownership check, traversal guard на всех путях, ghost 404;
> (5) Unit + route тесты в `test_workspace_commits_api.py` (~25 тестов: DTO validation, create/update/delete комбинации, gate BLOCK, empty changes, traversal, ghost).
>
> **Acceptance:** принято 18 сентября 2026 (Boss).
> `test_workspace_commits_api.py`: 35 passed; legacy COS-107: 16 passed; 2 live skipped.
> Suite gate: 2857 passed / 0 failed / 17 skipped.
> Web IDE может за один запрос создать, изменить и удалить несколько файлов в одном атомарном коммите; gate BLOCK возвращает 422 до вызова forge; конкурентный commit/CAS drift возвращает 409.
>
> **Scope deviation:** Git Trees pipeline из исходной карточки невыполним в Gitea 1.22.6 (`POST /git/trees` → 404; подтверждено swagger v1.22.6). Принят эквивалентный атомарный bulk Contents API. Пустой репозиторий без commit остаётся честным `404`, как в legacy COS-107.

> **Файлы:** `domain/workspace.py`, `adapters/forge_gitea.py`, `api/routes/workspace.py`, `tests/cosmo/test_workspace_commits_api.py`, `tests/cosmo/test_workspace_commit.py` (renames).

## ✅ DONE (2026-09-18 Luna) — WORKSPACE COMPARE API: TREE SNAPSHOT DIFF (PK-DIR-008 §3 / PK-C-006.24)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-125** | Luna | 5-6h | P2 | COS-116 | GET /api/v1/repos/workspace/compare: сравнение двух Git tree snapshot-ов без server-side diff |

> **Scope:** (1) DTO `WorkspaceCompareFile` (path, oldPath?, status: `added | modified | deleted | renamed`, additions, deletions, patch?, isBinary) и `WorkspaceCompareResponse` (base, head, files, totalAdditions, totalDeletions, filesChanged) в `domain/workspace.py` (camelCase, extra="forbid");
> (2) Метод `GiteaForgeAdapter.compare_refs(owner, repo, base, head)`:
> - разрешить оба ref в commit SHA через существующий commit API;
> - получить recursive tree snapshot для каждого commit через `GET /api/v1/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1`;
> - сравнить `{path -> blob_sha}` локально;
> - загрузить содержимое только добавленных/удалённых/изменённых blob-ов через Git Blobs API либо существующий `contents/{path}?ref=` fallback;
> - построить unified patch локально через `difflib.unified_diff()`;
> - бинарные файлы вернуть с `isBinary=true` и `patch=null`; rename определить по совпадающему blob SHA (иначе `deleted + added`);
> (3) Эндпоинт `GET /api/v1/repos/workspace/compare` в `orchestrator/cosmo/api/routes/workspace.py`:
> параметры `repo` (обязателен), `base`, `head`; `404` для неизвестного ref, `400` для `base == head`;
> (4) Безопасность: Bearer auth, domain ownership check, ghost 404, traversal guard; лимиты — до 500 файлов и ограничение размера blob;
> (5) Unit + route тесты в `test_workspace_compare.py` (~20 тестов: snapshots, add/modify/delete, rename по SHA, binary, empty compare, unknown ref, limits, ghost).
>
> **Механизм (утв. Максимом):** client-side snapshot compare через Gitea Git API. Дополнительно к scope: поле `truncated` (blob >2 MiB не читается), fallback `contents/{path}?ref=` при отказе Git Blobs API.
>
> **Acceptance:** принято 18 сентября 2026 (Luna). 49/49 passed. Suite gate: 2906/0/17. Файлы: `domain/workspace.py`, `adapters/forge_gitea.py`, `api/routes/workspace.py`, `tests/cosmo/test_workspace_compare.py`.

## ✅ DELIVERED (2026-09-18 Flash; scope deviation recorded) — WEB IDE FILE SAVE & COMMIT FLOW (PK-DIR-008 §3 / PK-C-006.25)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-126** | Flash | 8-10h | P1 | COS-120, COS-124 | Web IDE: сохранение файлов по Ctrl+S, dirty-индикатор в табах, диалог коммита с multi-file stage |

> **Scope:** (1) Типы в `D:\prettyk-ide\src\workspace\types.ts`:
> `FileEditState` (path, originalContent, currentContent, isDirty, isNew),
> `WorkspaceCommitRequest` и `WorkspaceCommitResponse` из COS-124;
> (2) Методы клиента в `D:\prettyk-ide\src\workspace\client.ts`:
> `commitChanges(repo, branch, message, fileChanges, author?)` → POST `/api/v1/repos/workspace/commits`;
> (3) EditStateManager (React-контекст или хук `useEditState`):
> - отслеживание dirty-файлов (`textarea` onChange → сравнение с originalContent);
> - индикатор ● в заголовке таба редактора при грязном состоянии;
> - Ctrl+S → локальный `SAVE` → сброс dirty, обновление originalContent;
> (4) CommitDialog (`D:\prettyk-ide\src\cosmo\ide\CommitDialog.tsx`):
> - открывается по кнопке в тулбаре/через `Ctrl+Enter`;
> - список изменённых файлов с чекбоксами (stage/unstage);
> - поле commit message (обязательное, max 500 симв, валидация);
> - поля author name/email (опциональные, предзаполненные);
> - кнопка Commit → вызов `commitChanges()` → успех: закрыть диалог, сбросить dirty-стейт, обновить HEAD ref в topbar;
> - обработка 422 (gate BLOCK — показать список violations в диалоге);
> - обработка 409 (конфликт — предложить обновить и повторить);
> (5) Vitest тесты: `client.test.ts` (+4 теста: saveFile, commitChanges success/422/409), компонентные тесты `CommitDialog.test.tsx` (~8 тестов).
>
> **Acceptance:** принято 18 сентября 2026 (Flash).
> `tsc -b` — 0 ошибок; `vitest run` — 68/68 passed (5 файлов).
> Разработчик редактирует несколько файлов в `<textarea>`, видит ● на грязных табах, выполняет локальный Ctrl+S, открывает CommitDialog и атомарно коммитит выбранные изменения; gate BLOCK показывает violations без коммита.
>
> **Scope deviation:** Monaco в текущей кодовой базе отсутствует, поэтому использован `<textarea>`. Ctrl+S пока локальный и не вызывает PUT `/workspace/files`; сохранение в Gitea происходит атомарно через `commitChanges()` → COS-124. Monaco и отдельный remote-save flow не входят в принятие COS-126.

## ✅ DONE (2026-09-18 Boss) — WORKSPACE RUN PIPELINE SELECTION BE CONTRACT (PK-DIR-008 §3 / PK-C-006.26)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-127** | Boss | 20-24h | P1 | COS-108, COS-122 | Выбранный в Web IDE pipeline реально передаётся и исполняется backend/ Woodpecker; default Run сохраняет обратную совместимость |

> **Scope:** (1) Расширить `WorkspaceRunRequest` полем `pipelineName: str | None = None`, сохранив `extra="forbid"` для остальных полей и старое поведение при отсутствии поля;
> (2) Протянуть `pipeline_name` через `POST /api/v1/repos/workspace/run` → run manager → `WoodpeckerExecutionAdapter.submit_run`;
> (3) Проверить фактический API текущего Woodpecker и выбрать поддерживаемый механизм выбора pipeline-конфига; нельзя имитировать выбор только на FE или молча запускать default;
> (4) Добавить валидацию pipeline относительно discovery COS-118: unknown pipeline → честный `400/404`, invalid name → `400`;
> (5) Добавить route/adapter tests: legacy request без `pipelineName`, selected pipeline propagation, unknown pipeline, auth/ownership, submit failure, retry/timeout;
> (6) Обновить OpenAPI/контрактные fixtures и `PROGRESS.md`/research note с фактическим Woodpecker limitation.
>
> **Out of scope:** Web IDE UI COS-122/COS-126; Gitea compare COS-125; изменение pipeline YAML semantics.
>
> **Acceptance:** default `▶ Run` продолжает работать без `pipelineName`; выбор через `▾` запускает именно выбранный pipeline или возвращает честную ошибку; backend не принимает поле формально с последующим запуском другого pipeline. Минимум 20 новых unit/route/adapter тестов, suite gate без регрессий.
>
> **Acceptance:** принято 18 сентября 2026 (Boss).
> `test_workspace_run_pipeline_selection.py`: 32 passed (DTO 10 / adapter 14 / route 8); legacy `test_workspace_run.py` обновлён под сигнатуру, 45 passed.
> Suite gate: 2938 passed / 0 failed / 17 skipped.
> Запрос без `pipelineName` запускает default-конфиг Woodpecker (обратная совместимость); `pipelineName` валидируется против discovery COS-118 и при совпадении прокидывает путь конфига в `repo.config_file`; неизвестный pipeline → честный `400` со списком доступных, без молчаливого запуска default.
>
> **Scope deviation:** (1) run manager в кодовой базе отсутствует — `POST /workspace/run` сам оркестратор; `pipeline_name` протянут route → `WoodpeckerExecutionAdapter.submit_run` (пункт 2 карточки без промежуточного слоя).
> (2) Woodpecker v3.5 `PipelineOptions` = `{branch, variables}` — селектора имени pipeline НЕТ (верифицировано по `server/model/pipeline.go` тега v3.5.0). Конфиг берётся из `repo.config_file`; выбран `GET repo → PATCH config_file → POST pipeline (сервер читает конфиг синхронно) → PATCH restore` под module-level lock, restore в `finally`. Пустой original → default-порядок Woodpecker (`.woodpecker/`, `.woodpecker.yaml`, `.woodpecker.yml`); `.pipeline.yaml`/`.pipeline.yml` достижимы только явным выбором.
> (3) OpenAPI fixtures (`docs/cosmo-openapi.json`/`.yaml`) регенерированы из живого `app.openapi()` — прежняя версия не содержала даже COS-108 run-эндпоинта (124 → 156 схем); contract-гвард `test_openapi_contract.py` 13 passed.
> (4) Live-верификация PATCH `config_file` на живом Woodpecker не выполнена: нет токена с repo-admin правами; адаптер покрыт юнитами на моках сессии.
> (5) Некорректное имя (`""`, пробелы, `\`, `\n`, >200) отклоняется DTO-валидатором → `422`, а не `400`: тот же эндпоинт уже отдаёт `422` на `bad repo`/`short sha` (тесты `test_bad_repo_422`/`test_short_sha_422`), поэтому `422` консистентен внутри `POST /workspace/run`. Unknown (формально валидное, но отсутствующее в discovery) имя → `400` со списком доступных, как в карточке.

## ✅ DELIVERED (2026-09-18 Flash) — WEB IDE CHANGE REVIEW & STAGING SURFACE (PK-DIR-008 §3 / PK-C-006.27)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-128** | Flash | 20-24h | P1 | COS-124, COS-125, COS-126 | Панель изменений Web IDE: staged/unstaged files, compare preview и безопасный вход в CommitDialog |

> **Scope:** (1) FE-only surface в `D:\prettyk-ide`: `ChangesPanel`/`ChangeReviewPanel` без правок Airlock backend;
> (2) Показывать dirty-файлы из `useEditState`, разделять staged/unstaged, stage/unstage по файлам, discard с подтверждением;
> (3) Интегрировать `GET /workspace/compare` после готовности COS-125; до этого использовать typed fixture/mock adapter, не изобретать второй backend contract;
> (4) Для выбранного файла показывать unified patch, additions/deletions, binary marker и empty-state; ограничить UI для truncated/large files;
> (5) Кнопка `Commit selected` открывает существующий CommitDialog COS-126 с точным набором staged changes;
> (6) Keyboard/accessibility: `Ctrl+Shift+G` открыть панель, Escape закрыть, focus management, dirty/discard confirmation;
> (7) Vitest/component tests: stage/unstage, discard confirmation, compare loading/error/empty/binary, CommitDialog handoff, keyboard flow; `tsc -b` green.
>
> **Out of scope:** Monaco migration; remote Ctrl+S PUT; BE routes/adapters; изменение COS-124 commit contract.
>
> **Acceptance:** принято 18 сентября 2026 (Flash).
> `tsc -b` — 0 ошибок; `vitest run` — 97/97 passed (7 файлов).
> Файлы: `src/cosmo/ide/compare.ts`, `src/cosmo/ide/useEditState.ts`, `src/cosmo/ide/ChangeReviewPanel.tsx`, `src/app/App.tsx`, `src/app/app.css`.
> Разработчик видит секции staged/unstaged, управляет stage/unstage по файлам и bulk, выполняет discard с подтверждением, просматривает patch/binary/empty states и открывает CommitDialog (`Ctrl+Shift+G` / тулбар) строго с выбранными файлами.
> Diff на данном этапе изолирован через seam `createFixtureCompare()`; сквозная интеграция с живым эндпоинтом COS-125 передана в COS-130.

## ✅ DONE (2026-09-18 Boss) — GITEA FORGE ADAPTER COMMIT API UNIFICATION (PK-DIR-008 §3 / PK-C-006.28)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-129** | Boss | 20-24h | P1 | COS-096, COS-103, COS-116, COS-125 | Устранение дублирования и затенения list_commits в GiteaForgeAdapter, починка get_commit/get_tree против живого Gitea |

> **Scope:** (1) В `orchestrator/cosmo/adapters/forge_gitea.py` обнаружено два метода `list_commits`: legacy COS-096 (`ref: str = "", limit: int = 10`) на строке 460 затенён методом COS-116 (`branch: str | None = None, path: str | None = None, limit: int = 30, page: int = 1`) на строке 840;
> (2) В результате вызов `get_commit` (строка 484: `list_commits(..., ref=ref)`) падает с `TypeError: unexpected keyword argument 'ref'` против живого Gitea; ломаются `get_commit` и `get_tree` (затронуты COS-103/118 и `routes/apps.py:641`);
> (3) Объединить сигнатуры в единый непротиворечивый контракт `list_commits(self, owner: str, repo: str, ref: str = "", branch: str | None = None, path: str | None = None, limit: int = 30, page: int = 1) -> list[GiteaCommit | dict]` либо разделить на явный низкоуровневый `list_commits(...) -> list[GiteaCommit]` и расширенный `get_commit_history(...) -> list[dict]` с сохранением обратной совместимости для всех вызывающих мест;
> (4) Проверить и согласовать возвращаемые типы во всех точках использования: `get_commit`, `get_tree`, `routes/apps.py:641`, `routes/workspace.py:1222`, `compare_refs`;
> (5) Написать юнит-тесты на совмещённую сигнатуру и регрессионные тесты против живого/эмулированного Gitea (включая проверку, что `ref` и `branch` не конфликтуют);
> (6) Прогнать полный suite gate (`pytest orchestrator/tests/cosmo/ -q`), подтвердив отсутствие регрессий.
>
> **Out of scope:** переработка других адаптеров; изменения в Gitea API.
>
> **Acceptance:** вызовы `get_commit(owner, repo, ref)` и `get_tree(owner, repo, ref)` не падают с TypeError; `routes/apps.py` и `routes/workspace.py` корректно получают данные коммитов; suite gate ≥2938 passed, 0 failed.
>
> **Acceptance:** принято 18 сентября 2026 (Boss).
> `test_forge_gitea_commits_unified.py`: 20 passed (регрессия shadowing + обе проекции + resolve_ref); `test_workspace_commits.py` / `test_workspace_compare.py` / `test_forge_cycle.py` — 121 passed суммарно.
> Suite gate: 2958 passed / 0 failed / 17 skipped.
> `get_commit(ref=...)` и `get_tree(ref=...)` возвращают `GiteaCommit`/`GiteaTreeEntry` без `TypeError`; `GET /workspace/commits` сохраняет пагинацию (`offset→page`) и фильтры `branch`/`path`; `routes/apps.py` снова отдаёт recent-коммиты.
>
> **Стратегия унификации (вариант из карточки):** единый HTTP-слой `_fetch_commits(owner, repo, ref, path, limit, page)` (сырой ответ Gitea, 404 → LookupError), поверх него две явные проекции:
> - `list_commits(owner, repo, ref="", branch=None, path=None, limit=10, page=1) -> list[GiteaCommit]` — канонический (COS-096), `ref`/`branch` — алиасы Gitea-параметра `sha`; потребители `get_commit`/`get_tree`/`routes/apps.py`;
> - `list_commits_history(owner, repo, branch=None, path=None, limit=30, page=1) -> list[dict]` — COS-116-проекция; потребители `GET /workspace/commits` и `resolve_ref` (COS-125).
>
> **Scope deviation:** имена выбраны как `list_commits` (GiteaCommit) + `list_commits_history` (dict) вместо `get_commit_history` из примера карточки — так сохранён исторический COS-096-контракт и не тронут внешний REST `GET /workspace/commits`. Лимит `_fetch_commits` унифицирован на cap 100 (было 50 у COS-096 / 100 у COS-116); для `limit=1` и `limit=5` потребителей разницы нет.

## ✅ DONE (2026-09-18 Flash) — WEB IDE LIVE COMPARE WIRE-UP & TREE STATUS (PK-DIR-008 §3 / PK-C-006.29)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-130** | Flash | 20-24h | P1 | COS-125, COS-128 | Сквозное подключение реального GET /workspace/compare в Web IDE, индикация статусов файлов в дереве проводника |

> **Scope:** (1) В `D:\prettyk-ide\src\workspace\client.ts` реализовать метод `compare(repo: str, base: str, head: str): Promise<WorkspaceCompareResponse>`, полностью соответствующий DTO COS-125 (`GET /api/v1/repos/workspace/compare`);
> (2) В `D:\prettyk-ide\src\cosmo\ide\ChangeReviewPanel.tsx` заменить mock/fixture seam `createFixtureCompare()` на вызов реального `client.compare()`, передавая активный репозиторий и сравниваемые ref-ы (текущая ветка / base ref);
> (3) Корректно обрабатывать ответы сервера: 200 (список файлов с patch), 400 (base == head, сообщение "Ветки идентичны"), 404 (ref не найден), 413 (>500 файлов — предупреждение о лимите), сетевые ошибки;
> (4) Визуальная индикация в дереве файлов Web IDE (FileTree / Explorer): отображать маркеры статуса (● или цветные бейджи M/A/D) для изменённых и staged файлов на основе `useEditState`;
> (5) Компонентные и юнит-тесты Vitest: вызов `client.compare`, обработка ошибок/граничных случаев, отображение индикаторов в дереве; `tsc -b` 0 ошибок.
>
> **Out of scope:** Monaco editor; бекенд-изменения Airlock.
>
> **Acceptance:** принято 18 сентября 2026 (Flash).
> `tsc -b` — 0 ошибок; `vitest run` — 114 passed (8 файлов, +17 новых тестов).
> Панель вызывает реальный `client.compare()`, парсит и рендерит серверный patch; ошибки 400/404/413 выводятся понятным текстом с кнопкой Retry; в дереве проводника отображаются маркеры modified/staged файлов. Сравнение ведётся между base = default branch и head = активная ветка.
>
> **Follow-up:** серверный diff показывает committed-изменения между ref-ами; локальный in-memory diff для незакоммиченных dirty-файлов вынесен в COS-131.

## ✅ DONE (2026-09-18 Flash) — WEB IDE FILE OPERATIONS & LOCAL DIRTY DIFF ENGINE (PK-DIR-008 §3 / PK-C-006.30)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-131** | Flash | 20-24h | P1 | COS-120, COS-126, COS-130 | Операции над файлами в дереве проводника Web IDE (создание, удаление, переименование) и локальный diff для dirty-файлов |

> **Scope:** (1) В `D:\prettyk-ide\src\workspace\client.ts` реализовать вызовы File Mutator API (COS-120): `createFile(repo, branch, path, content)`, `deleteFile(repo, branch, path)`, `moveFile(repo, branch, fromPath, toPath)`;
> (2) В Explorer / дереве файлов добавить контекстное меню и панель действий: "Новый файл", "Новая папка", "Переименовать", "Удалить" (с модальным окном подтверждения удаления);
> (3) Локальный In-Memory Diff Engine в `ChangeReviewPanel.tsx`: для файлов с незакоммиченными правками вычислять и отображать клиентский unified diff (`originalContent` vs `currentContent`) без ожидания коммита на сервер (решает ограничение COS-130);
> (4) Защита от потери данных: предупреждающий диалог при попытке закрыть вкладку с несохранёнными изменениями или переключить ветку при наличии dirty-файлов;
> (5) Vitest компонентные тесты: создание/удаление/переименование файлов, подтверждение удаления, генерация локального diff, защита при переключении веток; `tsc -b` green, vitest ≥130 passed.
>
> **Out of scope:** Monaco editor; правки бекенда в `prettyk-airlock`.
>
> **Acceptance:** принято 18 сентября 2026 (Flash).
> `tsc -b` — 0 ошибок; `vitest run` — 155 passed (10 тестовых файлов, +41 новый тест, порог ≥130 перевыполнен); `vite build` — green.
> Реализованы: `client.ts` (createFile / deleteFile с JSON / moveFile по COS-120 API), `compare.ts` (in-memory LCS diff c защитой 2M ячеек), `ChangeReviewPanel.tsx` (локальный vs серверный diff с бейджем local · uncommitted / committed — ограничение COS-130 снято), `fileOps.ts` + `FileOpsDialogs.tsx` (New File / New Folder через `.gitkeep` / Rename / Delete с подтверждением), `guard.ts` (beforeunload, смен ветки и файлов с dirty).
>
> **Ограничения:** Monaco out of scope (остаётся textarea); рекурсивный rename папки не поддержан.

## ✅ DONE (2026-09-18 Luna) — WORKSPACE FULL REPOSITORY SECURITY SCAN & SARIF EXPORT API (PK-DIR-008 §3 / PK-C-006.31)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-132** | Luna | 20-24h | P1 | COS-123, COS-125 | Эндпоинт полного аудита безопасности репозитория и ветки с экспортом в SARIF 2.1.0 |

> **Scope:** (1) DTO в `orchestrator/cosmo/domain/workspace.py`: `WorkspaceGateScanRequest` (repo, ref?, maxFiles?, exportFormat: `json | sarif`), `WorkspaceGateScanResponse` (scannedFiles, cleanFiles, blockViolations, warnViolations, verdict: `PASS | WARN | BLOCK`, durationMs, violations: list[WorkspaceGateViolation]);
> (2) В `orchestrator/cosmo/domain/gate_verdict.py` добавить метод `scan_tree(tree_entries, blob_loader)` с потоковым сканированием содержимого файлов дерева Gitea; пропуск бинарных и больших файлов (>2 MiB);
> (3) SARIF 2.1.0 Serializer в `gate_verdict.py`: преобразование violations в стандартный JSON-отчёт SARIF (runs, tool.driver.rules, results с locations, physicalLocation, region, message);
> (4) Эндпоинт `POST /api/v1/repos/workspace/gate-scan` в `orchestrator/cosmo/api/routes/workspace.py`:
> - параметры repo, ref (по умолчанию default branch);
> - получение рекурсивного дерева через `GiteaForgeAdapter.get_tree_by_sha`;
> - сканирование файлов через `scan_tree`;
> - при `exportFormat == "sarif"` возвращает `application/sarif+json`;
> - аутентификация Bearer, domain ownership guard, лимит на сканирование (до 1000 файлов в репо, 413 при превышении);
> (5) Unit + route тесты в `test_workspace_gate_scan.py` (~25 тестов: полный скан дерева, вердикты BLOCK/WARN/PASS, генерация валидного SARIF 2.1.0, лимиты, ghost 404, auth).
>
> **Out of scope:** UI в Web IDE; мутация файлов в forge.
>
> **Acceptance:** принято 18 сентября 2026 (Luna). `POST /workspace/gate-scan` сканирует дерево репозитория, возвращает агрегированный вердикт и violations; при `exportFormat="sarif"` отдаётся валидный SARIF 2.1.0 (`application/sarif+json`); 413 при >maxFiles, ghost 404, unknown ref 404. 53/53 passed. Suite gate: 3011/0/17. Файлы: `domain/workspace.py`, `domain/gate_verdict.py`, `api/routes/workspace.py`, `tests/cosmo/test_workspace_gate_scan.py`.

## ✅ DONE (2026-09-18 Boss) — WORKSPACE RUN LIFECYCLE: DETAIL SYNC, CANCEL & RERUN API (PK-DIR-008 §3 / PK-C-006.32)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-133** | Boss | 20-24h | P1 | COS-108, COS-111, COS-127 | Детализация и управление жизненным циклом запусков Workspace: синхронизация статуса, отмена и перезапуск пайплайнов |

> **Scope:** (1) DTO в `orchestrator/cosmo/domain/workspace.py`: новый `WorkspaceRunStepSummary` (name, status, exitCode: int | None, durationMs: int | None, startedAt: str | None, finishedAt: str | None), `WorkspaceRunDetailResponse` (runId, repo, branch, commitSha, status, pipelineNumber, durationMs, startedAt, finishedAt, steps: list[WorkspaceRunStepSummary]), `WorkspaceRunCancelResponse`, `WorkspaceRunRerunResponse` (новый runId + originalRunId);
> (2) Методы в `WoodpeckerExecutionAdapter` (`orchestrator/cosmo/adapters/execution_woodpecker.py`):
> - `get_pipeline_detail(handle) -> dict`: получение актуального статуса, шагов и таймингов пайплайна;
> - `cancel_pipeline(handle) -> dict`: отмена запущенного пайплайна (`POST /repos/{repo_id}/pipelines/{number}/cancel`);
> - `rerun_pipeline(handle) -> dict`: повторный запуск (`POST /repos/{repo_id}/pipelines/{number}`);
> (3) Эндпоинты в `orchestrator/cosmo/api/routes/workspace.py`:
> - `GET /api/v1/repos/workspace/runs/{run_id}`: получение детальной информации по запуску; если статус `running`/`pending`, выполняет опрос Woodpecker и синхронизирует статус в `WorkspaceRunRow` в БД;
> - `POST /api/v1/repos/workspace/runs/{run_id}/cancel`: отмена выполняющегося запуска, перевод статуса в `killed` в БД; 400 если запуск уже завершён;
> - `POST /api/v1/repos/workspace/runs/{run_id}/rerun`: повторный запуск пайплайна, создание новой записи `WorkspaceRunRow` с `original_run_id = {run_id}`; для этого — новая nullable-колонка `original_run_id: String(64)` на `cosmo_workspace_runs` (`orchestrator/cosmo/db/models_execution.py`) + alembic-ревизия (`down_revision` = текущий head, `alembic heads`), upgrade добавляет колонку, downgrade её снимает;
> (4) Защита: Bearer auth, проверка принадлежности домену, 404 при неизвестном run_id;
> (5) Unit + route тесты в `test_workspace_run_lifecycle.py` (~27 тестов: получение деталей, синхронизация статуса с Woodpecker, отмена активного, ошибка отмены завершённого, перезапуск с сохранением `original_run_id`, upgrade/downgrade ревизии, auth/ghost guards).
>
> **Out of scope:** Web IDE UI (терминал логов уже есть в COS-110); изменение логики сборки пайплайнов.
>
> **Acceptance:** эндпоинт `GET /workspace/runs/{run_id}` отдаёт полные шаги и синхронизирует статус из Woodpecker в БД; `cancel` прерывает пайплайн и ставит `killed`; `rerun` перезапускает, возвращает новый run_id и `originalRunId` = исходный, связь сохраняется в `WorkspaceRunRow.original_run_id`; `alembic upgrade head` применяется без ошибок и `downgrade -1` откатывает колонку; suite gate ≥2958 passed, 0 failed.
>
> **Delivered (2026-09-18 Boss):** `test_workspace_run_lifecycle.py`: 35 passed (10 DTO + 25 route). Suite gate: 3046 passed / 0 failed / 17 skipped.
> `GET /workspace/runs/{run_id}` отдаёт шаги (`WorkspaceRunStepSummary`) и синхронизирует статус из Woodpecker в БД для незавершённых прогонов; `cancel` ставит `killed` и 400 на терминальном; `rerun` создаёт новую `WorkspaceRunRow` с `original_run_id` и возвращает новый run_id.
> Артефакты: `domain/workspace.py` (4 DTO), `adapters/execution_woodpecker.py` (`get_pipeline_detail`/`cancel_pipeline`/`rerun_pipeline`), `api/routes/workspace.py` (3 эндпоинта + `_run_row_for_domain`/`_step_summaries`), `db/models_execution.py` (`original_run_id`), `alembic/versions/f5a6b7c8d9e0_cos133_run_original_run_id.py`, `tests/cosmo/conftest.py` (idempotent ALTER для stale test-DB), `tests/cosmo/test_migration_reconciliation.py` (`_HEAD` → `f5a6b7c8d9e0`), `docs/cosmo-openapi.{json,yaml}` (127 путей / 162 схемы).
>
> **Scope deviation:** статус синхронизируется только для незавершённых прогонов (`running`/`pending`/`blocked`) — терминальный статус в БД источник истины; `_TERMINAL_RUN_STATUSES` расширен алиасами `succeeded`/`failed` (исторические строки COS-112). Рерун-линк — новая nullable-колонка `original_run_id`; миграция guarded (no-op на чистом alembic-скратче и на create_all-БД). Живой Woodpecker cancel/rerun не верифицирован (нет repo-admin токена) — адаптер покрыт юнитами на моках.

---

## ⬜ READY — SOVEREIGN WORKSPACE WAVE 3: WORKBENCH LIFECYCLE, SECURITY AUDIT LENS & HUB CONTRACT A

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-134** | Flash | 20-24h | P1 | COS-133, COS-111, COS-128 | ✅ DONE — Интеграция жизненного цикла запусков и управления пайплайнами в Web IDE (Cancel, Rerun, Step-Breakdown и тайминги в Terminal Drawer) |
| **COS-135** | Luna | 20-24h | P1 | COS-132, IDE-CORE-010, IDE-UI-003 | ✅ DONE — Панель аудита безопасности и инспектор SARIF в Web IDE: сканирование репозитория, навигация по violations и экспорт отчёта |
| **COS-136** | Boss | 20-24h | P1 | COS-101, PK-C-003, PK-DIR-008 | ✅ DONE — Contract A: Ingestion вердиктов PrettyK Hub в Cosmoport, крипто-связка с Evidence Ledger и закрытие чеклиста анти-паттернов PK-C-003 |

### Карточки волны

#### ✅ COS-134 · Flash · Web IDE: Cancel, Rerun & Step-Breakdown — DONE (2026-09-19)
> **Scope:**
> (1) В `D:\prettyk-ide\src\workspace\client.ts`: добавить типизированные вызовы жизненного цикла запусков:
>     - `getRunDetail(repo: string, runId: string): Promise<WorkspaceRunDetailResponse>` (`GET /api/v1/repos/workspace/runs/{run_id}`);
>     - `cancelRun(repo: string, runId: string): Promise<WorkspaceRunCancelResponse>` (`POST /api/v1/repos/workspace/runs/{run_id}/cancel`);
>     - `rerunRun(repo: string, runId: string): Promise<WorkspaceRunRerunResponse>` (`POST /api/v1/repos/workspace/runs/{run_id}/rerun`);
> (2) В `D:\prettyk-ide\src\workspace\types.ts`: зафиксировать интерфейсы DTO `WorkspaceRunStepSummary` (name, status, exit_code, duration_ms, started_at, finished_at), `WorkspaceRunDetailResponse`, `WorkspaceRunCancelResponse`, `WorkspaceRunRerunResponse` в соответствии с фактическим JSON бэкенда (snake_case);
> (3) В `D:\prettyk-ide\src\cosmo\ide\WebIDETerminalDrawer.tsx`:
>     - Добавить панель детализации шагов пайплайна (Steps breakdown): статусы шагов с цветовой индикацией (`running`, `success`, `failure`, `killed`, `pending`), длительность каждого шага и код завершения;
>     - Кнопка "Отменить запуск" (Cancel Pipeline): активна для незавершённых запусков (`running`/`pending`), при inline-подтверждении выполняет `cancelRun`;
>     - Кнопка "Перезапустить запуск" (Rerun Pipeline): активна для терминальных запусков, выполняет `rerunRun`, обновляет `runId` в URL/состоянии с сохранением связи `originalRunId`;
> (4) Vitest тесты: моки запросов `getRunDetail`, `cancelRun`, `rerunRun`, отображение шагов, состояния кнопок cancel/rerun при разных статусах; `tsc -b` green, vitest passed.
>
> **Acceptance:** принято 19 сентября 2026 (Flash). WebIDETerminalDrawer корректно отображает детализированные шаги с таймингами и статусами; кнопки Cancel и Rerun корректно управляют жизненным циклом; чистый редьюсер `useRunDetail` с 4s-поллингом пока прогон активен; `parseRunLifecycle` обрабатывает 400/404/502; `tsc -b` — 0 ошибок, vitest 182/182 passed.

#### ✅ COS-135 · Luna · Web IDE: Security Audit Lens & SARIF Inspector — DONE (2026-09-19)
> **Scope:**
> (1) В `D:\prettyk-ide\src\workspace\client.ts`: реализовать вызовы Quality Gate сканирования:
>     - `triggerGateScan(repo: string, ref?: string, maxFiles?: number): Promise<WorkspaceGateScanResponse>`;
>     - `exportGateScanSarif(repo: string, ref?: string, maxFiles?: number): Promise<Blob>`;
> (2) В `D:\prettyk-ide\src\workspace\types.ts`: объявить типизацию `WorkspaceGateScanRequest`, `WorkspaceGateScanResponse`, `WorkspaceGateViolation`;
> (3) Создать компонент `D:\prettyk-ide\src\cosmo\ide\SecurityLens.tsx` (и подключить в `App.tsx`):
>     - Кнопка "Security Audit" в панели инструментов/статус-баре;
>     - Карточка вердикта Quality Gate: бейдж `PASS` / `WARN` / `BLOCK`, количество файлов, время проверки;
>     - Список нарушений: категория правила, критичность (`error`, `warning`), путь к файлу, номер строки и сообщение;
>     - Клик по нарушению: переключение активного файла в редакторе на указанный путь и строку;
>     - Кнопка "Download SARIF": экспорт отчёта SARIF 2.1.0 (`cosmo-security-audit.sarif`);
> (4) Vitest тесты: моки ответов `gate-scan`, рендеринг вердиктов BLOCK/WARN/PASS, навигация по нарушениям, обработка ошибки 413; `tsc -b` green, vitest passed.
>
> **Acceptance:** принято 19 сентября 2026 (Luna). «Security Audit» в топбаре запускает `POST /workspace/gate-scan`; панель показывает бейдж вердикта PASS/WARN/BLOCK, счётчики файлов и время, список нарушений с фильтром All/Errors/Warnings; клик по нарушению открывает файл в редакторе и ставит каретку на строку; «Download SARIF» скачивает `cosmo-security-audit.sarif`; 413 → «Repository exceeds the scan limit (1000 files)», сетевые сбои — Retry. `tsc -b` 0 ошибок, vitest 221/221 passed.

#### ✅ COS-136 · Boss · Cosmoport: Contract A Hub Ingestion & PK-C-003 Hardening — DONE (2026-09-19)
> **Scope:**
> (1) В `orchestrator/cosmo/domain/hub_verdict.py`: Pydantic-модели:
>     - `HubVerdictIngestRequest` (run_id: str, box_verdict: str, hub_verdict: str, finding_ids: list[str], evidence_hashes: list[str], provenance_metadata: dict, idempotency_key: str);
>     - `HubVerdictIngestResponse` (accepted: bool, ledger_entry_id: str, run_id: str, status: str);
> (2) В `orchestrator/cosmo/api/routes/hub.py`: эндпоинт `POST /api/v1/hub/verdicts/ingest`:
>     - Валидация входного контракта Contract A (PrettyK Hub → Cosmoport);
>     - Идемпотентность по `idempotency_key` и хэшу `(run_id, hub_verdict)`;
>     - Формирование криптографической записи в `cosmo_evidence_ledger` с фиксацией provenance-хэша;
>     - Блокировка промоушена релиза при `hub_verdict == "BLOCK"`, разблокировка при `PASS`;
> (3) Канонизация требований чеклиста анти-паттернов PK-C-003:
>     - `docs/DEPLOYMENT.md`: формализация процедуры миграции (PK-C-003.3), ownership стенда и suite gate (PK-C-003.1), канонические digest-теги (PK-C-003.4);
>     - `docs/ARCHITECTURE-DIRECTION.md`: фиксация "Failover = Phase 3, not Phase 1" (PK-C-003.2);
>     - Обновление чеклиста в `docs/BACKLOG.md` (PK-C-003.1..003.6);
> (4) Unit + route тесты: `tests/cosmo/test_hub_verdict_ingest.py` (приём вердикта, дедупликация повторов, запись в ledger, блокировка промоушена); suite gate 3062 passed, 0 failed, 17 skipped.
>
> **Acceptance:** принято 19 сентября 2026 (Boss). `POST /api/v1/hub/verdicts/ingest` принимает и дедуплицирует вердикты Hub с крипто-записью в ledger; требования PK-C-003 формализованы в документации; 16/16 route tests pass; full suite gate 3062 passed / 0 failed.

---

## ⬜ READY — SOVEREIGN WORKSPACE WAVE 4: EDITOR SURFACE, SBOM ATTESTATION & HUB CONTRACT B

> **Правило разделения поверхностей (Zero-Collision Protocol):**
> 1. **Flash:** единоличный владелец `D:\prettyk-ide`. Ни Boss, ни Luna не трогают `prettyk-ide`.
> 2. **Luna:** изоляция в Supply Chain / SBOM подсистеме `prettyk-airlock` (`sbom_scan.py`, `sbom_gate.py`, `releases.py`, `test_sbom_gate.py`). Не трогает Hub и IDE.
> 3. **Boss:** изоляция в Quality Gate / Hub Evaluation подсистеме `prettyk-airlock` (`hub_evaluation.py`, `hub_client.py`, `hub_dispatcher.py`, `hub.py`, `test_hub_evaluation_dispatch.py`). Не трогает releases и IDE.
> Пересечение файлов между воркерами строго 0.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-137** | Flash | 20-24h | P1 | COS-131, COS-135 | ✅ DONE — Web IDE: Code Editor Surface — Line Numbers Gutter, Syntax Highlighting & Reveal Target Navigation |
| **COS-138** | Luna | 20-24h | P1 | COS-136, PK-C-003.6 | ✅ DONE — SBOM/Grype attestation gate: digest-сверка конверта/отчётов/артефакта, BLOCK при critical>0, крипто-якорь sha256(SBOM) в evidence ledger, attach/read API |
| **COS-139** | Boss | 20-24h | P1 | COS-136, PK-DIR-008 | ✅ DONE — Contract B: Control Plane → PrettyK Hub Evaluation Dispatcher & Clearance Gate |

### Карточки волны

#### ✅ COS-137 · Flash · Web IDE: Code Editor Surface with Line Gutter & Syntax Highlighting — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-ide`:
>     - Создать модуль `src/cosmo/ide/codeEditorUtils.ts`: чистые функции токенизации синтаксиса для основных языков (ts/js, python, yaml, json, markdown, shell), разметка строк, форматирование отступов (Tab/Shift-Tab 2/4 пробела);
>     - Создать компонент `src/cosmo/ide/CodeEditor.tsx`:
>       - Номера строк (Line gutter) слева с возможностью клика для выделения строки;
>       - Подсветка активной/текущей строки;
>       - Синхронизация скролла между gutter и текстовой областью;
>       - Интеграция с `revealTarget` (позиционирование каретки и скролл к строке при переходе из SecurityLens и Search);
>       - Поддержка шорткатов (Tab для отступов, Ctrl+S сохранение, Ctrl+Shift+G переход в review);
>     - В `src/app/App.tsx`: замена `<textarea className="editor-textarea">` на `<CodeEditor>`;
>     - В `src/app/app.css`: стили темной темы редактора (.cosmo-ide-root, monospace, gutter, active line, syntax tokens);
> (2) Vitest тесты в `src/cosmo/ide/codeEditorUtils.test.ts`: токенизация, вычисление номеров строк, отступы, позиционирование каретки;
> (3) Гейт: `tsc -b` — 0 ошибок, `npx vitest run` — 251/251 зелёные (14 файлов), `npm run build` — успешен.
>
> **Acceptance:** принято 19 сентября 2026 (Flash). CodeEditor заменяет базовый textarea в Web IDE; overlay-архитектура с gutter, номерами строк и подсветкой активной строки; синхронизация revealTarget скроллит к строке при навигации из SecurityLens и поиска; `tsc -b` 0 ошибок, vitest 251/251 passed.

#### ✅ COS-138 · Luna · Cosmoport: PK-C-003.6 Release Bundle SBOM & Grype Attestation Gate — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Supply Chain / SBOM):
>     - В `orchestrator/cosmo/domain/sbom_scan.py`: Pydantic-модели:
>       - `SbomPackage` (name, version, type, purl, license);
>       - `SbomReport` (format: Literal["spdx-json", "cyclonedx-json"], syft_version: str, artifact_digest: str, packages_count: int, packages: list[SbomPackage]);
>       - `GrypeFinding` (id, severity: Literal["critical", "high", "medium", "low", "negligible"], package_name, installed_version, fixed_version);
>       - `GrypeScanReport` (scanner_version: str, artifact_digest: str, critical_count: int, high_count: int, medium_count: int, low_count: int, findings: list[GrypeFinding]);
>       - `ReleaseSbomAttachRequest` (sbom: SbomReport, vulnerabilities: GrypeScanReport, artifact_digest: str);
>       - `ReleaseSbomAttestationResponse` (accepted: bool, release_id: str, artifact_digest: str, sbom_digest: str, clearance: str, gate_verdict: str);
>     - В `orchestrator/cosmo/ledger/sbom_gate.py`:
>       - `verify_and_attest_release_sbom(session, release_id, payload) -> ReleaseSbomAttestationResponse`;
>       - Проверка: `artifact_digest` в SBOM и Grype должен строго совпадать с хэшем артефакта релиза;
>       - Проверка порогов: если `critical_count > 0`, gate_verdict = `BLOCK`, иначе `PASS`;
>       - Запись аттестации в `cosmo_evidence_ledger` с привязкой к `release_id`;
>     - В `orchestrator/cosmo/api/routes/releases.py`:
>       - `POST /api/v1/releases/{release_id}/sbom/attach` — приём и аттестация SBOM + Grype;
>       - `GET /api/v1/releases/{release_id}/sbom` — чтение аттестации и статуса SBOM;
> (2) Тесты в `orchestrator/tests/cosmo/test_sbom_gate.py`:
>     - Успешная аттестация clean SBOM (gate PASS, запись в ledger);
>     - Отклонение при mismatch `artifact_digest` (422 Unprocessable Entity);
>     - Блокировка релиза при наличии critical vulnerabilities (gate BLOCK);
>     - 404 при неизвестном release_id;
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Contract B, файлы routes/hub.py.
> **Acceptance:** `POST /api/v1/releases/{release_id}/sbom/attach` валидирует Syft SBOM и Grype отчет, сверяет digest, пишет в ledger; critical > 0 блокирует релиз; suite gate зелёный.
> **Принято 19 сентября 2026 (Luna):** `domain/sbom_scan.py` (DTO Syft/Grype, sha256-валидация digest, canonical `sbom_content_hash`), `ledger/sbom_gate.py` (`verify_and_attest_release_sbom` + `latest_sbom_attestation`, критичный счёт честный: `max(заявленный, observed findings)`), маршруты `POST .../sbom/attach` + `GET .../sbom` (GATE_DECIDE). Focused `test_sbom_gate.py` — 13 passed; полный suite gate — 3114 passed / 0 failed / 17 skipped.

#### ✅ COS-139 · Boss · Cosmoport: Contract B Control Plane → PrettyK Hub Evaluation Dispatcher — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Quality Gate / Hub Evaluation):
>     - В `orchestrator/cosmo/domain/hub_evaluation.py`: Pydantic-модели Contract B по `docs/research/2026-09-02-cross-product-contract-bridge.md`:
>       - `HubSecurityExecution` (studio_run_id: str, verdict: str, act_ref: str, evidence_refs: list[str]);
>       - `HubEvaluationRequest` (contract_version: str = "1.0", request_id: str, evaluation_id: str, project_id: str, application_ids: list[str], release_id: str, run_id: str, build_id: str, artifact_digest: str, release_profile: str, target_zone: str, qualifying_context: bool, security_execution: HubSecurityExecution);
>       - `HubEvaluationDispatchResponse` (dispatched: bool, request_id: str, evaluation_id: str, status: str, dispatched_at: str);
>     - В `orchestrator/cosmo/adapters/hub_client.py`:
>       - `HubEvaluationClient`: HTTP-клиент к PrettyK Hub (`http://localhost:8000/api/v1/evaluations` по умолчанию, настраивается через `COSMO_HUB_URL`), таймаут 10с, retry c экспоненциальным backoff;
>     - В `orchestrator/cosmo/control_plane/hub_dispatcher.py`:
>       - Сервис `HubEvaluationDispatcher`: валидация обязательного контекста (`qualifying_context=True`, immutable digests), формирование запроса Contract B, запись события в `cosmo_audit_events`;
>     - В `orchestrator/cosmo/api/routes/hub.py`:
>       - `POST /api/v1/hub/evaluations/dispatch` — инициирование отправки оценки в Hub;
>       - `GET /api/v1/hub/evaluations/{evaluation_id}` — статус отправленной оценки;
> (2) Тесты в `orchestrator/tests/cosmo/test_hub_evaluation_dispatch.py`:
>     - Валидация схемы Contract B (все обязательные поля);
>     - Идемпотентность по `evaluation_id`;
>     - Успешная отправка и обработка сетевого сбоя / таймаута с фиксацией в аудите;
>     - Запрет отправки при `qualifying_context=False` для production профилей;
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Supply Chain / SBOM, файлы routes/releases.py.
> **Acceptance:** принято 19 сентября 2026 (Boss). `POST /api/v1/hub/evaluations/dispatch` валидирует и отправляет Contract B в PrettyK Hub; клиент защищён таймаутом 10с и bounded retry с экспоненциальным backoff (transport/таймаут/429/5xx; 4xx — без повторов); аудит фиксирует success/failed/duplicate; `GET /api/v1/hub/evaluations/{evaluation_id}` читает статус отправленной оценки; 39/39 тестов зелёные, suite gate 3101 passed / 0 failed / 17 skipped.
>
> **Scope deviation:** реестр отправок и audit-запись — in-memory (один процесс cosmo-api) — честная граница до появления durable-таблицы вне миграционного freeze; API-контракт от этого не зависит. Идемпотентность — по `evaluation_id` + сверка immutable-identity (release/run/build/digest): повтор с той же identity → `duplicate` без второй отправки, с другой → 400 (дрейф контекста). Clearance gate (Studio-вердикт `PASS`, `qualifying_context=True` для production-профилей) срабатывает до любого I/O.

---

## ✅ DONE — SOVEREIGN WORKSPACE WAVE 5: COMMAND PALETTE & BREADCRUMBS, HUB CLEARANCE CALLBACK (CONTRACT C) & DIGEST-PIN MANIFEST (PK-C-003.4)

> **Правило разделения поверхностей (Zero-Collision Protocol):**
> 1. **Flash:** единоличный владелец `D:\prettyk-ide`. Ни Boss, ни Luna не трогают `prettyk-ide`.
> 2. **Luna:** изоляция в подсистеме Supply Chain / Artifacts / Manifest (`domain/artifact_manifest.py`, `ledger/manifest_verifier.py`, `routes/artifacts.py`, `test_artifact_manifest.py`). Не трогает Hub, Releases и IDE.
> 3. **Boss:** изоляция в подсистеме Quality Gate / Hub Contracts (`domain/hub_clearance.py`, `ledger/hub_clearance_gate.py`, `routes/hub.py`, `test_hub_clearance.py`). Не трогает Artifacts, Releases и IDE.
> Пересечение файлов между воркерами строго 0.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-140** | Flash | 20-24h | P1 | COS-137 | ✅ DONE — Web IDE: Command Palette (Ctrl+P / Quick Open File), Breadcrumbs Navigation & File Actions |
| **COS-141** | Boss | 20-24h | P1 | COS-139, PK-DIR-008 | ✅ DONE — Contract C: PrettyK Hub Quality Gate Clearance Callback & Final Transfer Authorization Gate |
| **COS-142** | Luna | 20-24h | P1 | COS-138, PK-C-003.4 | ✅ DONE — Artifact Manifest Digest-Pin & Canonical Tag Validation: canonical tag-контракт (slug/semver/no-latest/sha256), детерминированный digest_pin, ledger-якорь, verify/read API |

### Карточки волны

#### ✅ COS-140 · Flash · Web IDE: Command Palette (Ctrl+P / Quick Open File), Breadcrumbs Navigation & File Actions — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-ide`:
>     - Создать модуль `src/cosmo/ide/commandPaletteUtils.ts`: чистые функции фильтрации и нечёткого поиска (fuzzy match) по путям файлов, подсветка совпадающих фрагментов, ранжирование результатов (недавние файлы, точные совпадения имени файла > совпадение в пути), утилиты копирования путей;
>     - Создать компонент `src/cosmo/ide/CommandPalette.tsx`:
>       - Модальное окно быстрого поиска файлов по шорткату `Ctrl+P` / `Cmd+P` (и по клику на поиск в header/breadcrumbs);
>       - Полнотекстовый ввод с автофокусом и очисткой;
>       - Список найденных файлов с поддержкой навигации с клавиатуры (ArrowUp, ArrowDown, Enter для открытия, Escape для закрытия);
>       - Отображение иконки файла, пути и совпавших символов;
>       - Быстрый список недавних / открытых файлов при пустом поисковом запросе;
>     - Создать компонент `src/cosmo/ide/Breadcrumbs.tsx`:
>       - Навигационная цепочка над редактором кода: репозиторий / ветка / сегменты пути файла;
>       - Интерактивные кликабельные сегменты (клик по сегменту каталога или вызов Command Palette);
>       - Панель действий с текущим файлом: кнопки «Copy Path», «Copy Relative Path», «Copy Content» с индикатором подтверждения (Copied!);
>     - В `src/app/App.tsx`: подключение `Breadcrumbs` над `CodeEditor`, глобальный слушатель `Ctrl+P`/`Cmd+P` для открытия `CommandPalette`;
>     - В `src/app/app.css`: стили для `CommandPalette` (overlay, backdrop-blur, dark theme, active item, highlight) и `Breadcrumbs` (compact toolbar, breadcrumb separator, action buttons);
> (2) Vitest тесты в `src/cosmo/ide/commandPaletteUtils.test.ts`: нечёткий поиск, ранжирование, подсветка совпадений, пустые запросы, обработка спецсимволов;
> (3) Гейт: `tsc -b` — 0 ошибок, `npx vitest run` — все тесты зелёные, `npm run build` — успешен.
>
> **Acceptance:** принято 19 сентября 2026 (Flash). Command Palette по `Ctrl+P` / `Cmd+P` и кнопке в тулбаре; ярусное ранжирование (exact name 1000 → name prefix 800 → name substring 600 → path prefix 500 → fuzzy 300) со штрафом за разрывы и бустом recentFiles (+40); Breadcrumbs над редактором с сегментами пути и действиями Copy Path / Relative Path / Content (2с toast badge); 45 vitest тестов в `commandPaletteUtils.test.ts`, общий vitest 296/296 passed across 15 files, `tsc -b` 0 ошибок, vite build 54 модуля green.
>
> **Out of scope:** Backend API, любые изменения в `D:\prettyk-airlock`.

#### ✅ COS-141 · Boss · Cosmoport: Contract C PrettyK Hub Quality Gate Clearance Callback & Final Transfer Authorization Gate — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Quality Gate / Hub Contracts):
>     - В `orchestrator/cosmo/domain/hub_clearance.py`: Pydantic-модели по спецификации Contract C (`docs/research/2026-09-02-cross-product-contract-bridge.md` §6):
>       - `HubClearanceIngestRequest`: `contract_version: Literal["1.0"] = "1.0"`, `evaluation_id: str`, `release_id: str`, `run_id: str`, `evaluated_at: str`, `policy_version: str`, `security_execution_verdict: Literal["PASS", "WARN", "FAIL", "ERROR"]`, `act_ref: str`, `qg_clearance: Literal["PASS_GRANTED", "BLOCKED", "REJECTED"]`, `verdict: Literal["PASS", "WARN", "FAIL", "ERROR"]`, `ready_for_transfer: bool`, `qualifying_context: bool`, `ok_to_transfer: bool`, `evidence_refs: list[str] = []`, `explanation_ref: str = ""`, `metadata: dict[str, Any] = {}`;
>       - `HubClearanceIngestResponse`: `status: Literal["accepted", "duplicate", "rejected"]`, `evaluation_id: str`, `release_id: str`, `clearance_status: Literal["PASS_GRANTED", "BLOCKED", "REJECTED"]`, `transfer_allowed: bool`, `ledger_entry_id: str`, `timestamp: str`;
>     - В `orchestrator/cosmo/ledger/hub_clearance_gate.py`:
>       - Сервис `HubClearanceGateManager`:
>         - Идемпотентность и защита от дрейфа: ключ дедупликации `(evaluation_id, release_id)` со сверкой неизменяемого контекста (`run_id`, `policy_version`);
>         - Криптографический якорь: вычисление SHA256 от clearance payload и запись в `cosmo_evidence_ledger` с типом `QG_CLEARANCE`;
>         - Правило авторизации: `transfer_allowed = True` СТРОГО если `qg_clearance == "PASS_GRANTED"` И `ok_to_transfer is True` И `security_execution_verdict in ("PASS", "WARN")`. При любом ином исходе — `transfer_allowed = False`, промоушен в sovereign transfers (`zt`/`zpe`) заблокирован;
>     - В `orchestrator/cosmo/api/routes/hub.py`:
>       - `POST /api/v1/hub/clearance/ingest` — приём вердикта клиренса Quality Gate от Hub;
>       - `GET /api/v1/hub/clearance/{release_id}` — чтение актуального статуса клиренса релиза;
>       - `GET /api/v1/hub/clearance/by-evaluation/{evaluation_id}` — чтение по ID оценки;
> (2) Тесты в `orchestrator/tests/cosmo/test_hub_clearance.py`:
>     - Валидация схемы Contract C (полнота полей, строгие enum);
>     - Идемпотентность и обнаружение конфликтов при дрейфе контекста (400 при расхождении `run_id`);
>     - Фиксация в `cosmo_evidence_ledger` и проверка вычисления хеша;
>     - Блокировка трансфера при `qg_clearance != "PASS_GRANTED"` или `ok_to_transfer is False`;
>     - Разрешение трансфера при полном согласии политик (`PASS_GRANTED`, `ok_to_transfer=True`);
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Supply Chain / Artifacts, файлы routes/releases.py и routes/artifacts.py.
> **Acceptance:** принято 19 сентября 2026 (Boss). `POST /api/v1/hub/clearance/ingest` принимает вердикт клиренса Contract C, дедуплицирует по `(evaluation_id, release_id)` и отклоняет дрейф неизменяемого контекста (`run_id`, `policy_version`) с 400; неизвестный `run_id` → 404; неполная/нестрогая схема → 422. Клиренс якорится в `evidence_ledger` (SHA256 от payload, `content_ref=hub://clearance/<release_id>/<evaluation_id>`, `source=prettyk-hub`), latest wins. Правило авторизации — fail-closed: `transfer_allowed=True` строго при `qg_clearance=="PASS_GRANTED"` И `ok_to_transfer is True` И `security_execution_verdict in ("PASS","WARN")`; положительный клиренс при `qualifying_context=False` принимается, но записывается как `rejected` с `transfer_allowed=False`. `GET /api/v1/hub/clearance/{release_id}` и `GET /api/v1/hub/clearance/by-evaluation/{evaluation_id}` читают актуальный статус (404 при отсутствии). 27/27 тестов зелёные, suite gate 3141 passed / 0 failed / 17 skipped; OpenAPI-фикстуры регенерированы (135 путей / 175 схем, чистые добавления, 0 удалений, shared-контент без изменений).
>
> **Scope deviation:** (1) Колонка `evidence_ledger.type` — PG ENUM `evidence_type_enum` (7 значений, включая `decision`), миграционная цепочка заморожена, поэтому литерал `QG_CLEARANCE` в колонку не пишется: запись идёт с `type='decision'`, а маркер `clearance_type="QG_CLEARANCE"` — в `provenance_json` вместе с `source='prettyk-hub'`, `contract='C'`. API-контракт и семантика клиренса от этого не зависят; при разморозке миграций маркер поднимается в колонку. (2) Enforcing-проводка в transfer (`routes/releases.py`) не делалась — файл вне поверхности карточки; поставлен сервисный хелпер `release_transfer_allowed()` (fail-closed) + read API, которые вызывающий контур промоушена обязан использовать. Это ограничение объёма, а не пропуск теста.

#### ✅ COS-142 · Luna · Cosmoport: PK-C-003.4 Artifact Manifest Digest-Pin & Canonical Tag Validation Service — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Supply Chain / Artifacts / Manifest):
>     - В `orchestrator/cosmo/domain/artifact_manifest.py`: Pydantic-модели по требованию PK-C-003.4:
>       - `CanonicalArtifactTag`: `name: str`, `version: str`, `digest: str` (валидация regex `^sha256:[a-f0-9]{64}$`). Валидатор: строгий запрет тега `latest` или версий, содержащих `latest`. Метод `canonical_ref() -> str` формирует каноническую строку вида `<name>:<version>@sha256:<digest>`;
>       - `ArtifactBundleManifest`: `bundle_id: str`, `release_version: str`, `profile: Literal["ordinary@1", "hardened@1", "airgap@1"]`, `artifacts: list[CanonicalArtifactTag]`, `expected_digest_pin: str | None = None`, `created_at: str`;
>       - `ManifestVerificationResult`: `valid: bool`, `bundle_id: str`, `digest_pin: str`, `artifacts_count: int`, `errors: list[str] = []`, `ledger_entry_id: str | None = None`;
>     - В `orchestrator/cosmo/ledger/manifest_verifier.py`:
>       - Сервис `BundleManifestVerifier`:
>         - Вычисление детерминированного `digest_pin` бандла: SHA256 от канонического представления профиля и отсортированных `canonical_ref` всех артефактов;
>         - Сверка с `expected_digest_pin` (при наличии);
>         - Запись проверенного манифеста в `cosmo_evidence_ledger` с типом записи `BUNDLE_MANIFEST`;
>         - Отклонение любых манифестов с незакрепленными версиями или тегом latest;
>     - В `orchestrator/cosmo/api/routes/artifacts.py`:
>       - `POST /api/v1/artifacts/manifest/verify` — верификация манифеста, расчет digest_pin и фиксация в ledger;
>       - `GET /api/v1/artifacts/manifest/{bundle_id}` — чтение подтвержденного манифеста;
> (2) Тесты в `orchestrator/tests/cosmo/test_artifact_manifest.py`:
>     - Валидация канонического формата тегов и отказ при наличии `latest`;
>     - Детерминированный расчёт `digest_pin` независимо от порядка артефактов в запросе;
>     - Обнаружение расхождения digest-pin;
>     - Фиксация в evidence ledger;
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Quality Gate / Hub, файлы routes/hub.py и routes/releases.py.
> **Acceptance:** `POST /api/v1/artifacts/manifest/verify` валидирует canonical tag-формат (slug/semver/no-latest/sha256), считает детерминированный `digest_pin` (порядок артефактов не влияет), сверяет `expected_digest_pin` (mismatch → `valid=false` + errors, не 5xx), фиксирует проверенный манифест в evidence ledger; `GET /api/v1/artifacts/manifest/{bundle_id}` читает подтверждённый манифест (404 иначе); suite gate зелёный.
> **Принято 19 сентября 2026 (Luna):** `domain/artifact_manifest.py` (DTO canonical tag/manifest/result, строгий slug + semver + `sha256:<64 lowercase hex>`, `canonical_ref()`, `manifest_content_hash`), `ledger/manifest_verifier.py` (`BundleManifestVerifier` + `compute_digest_pin`, ledger-якорь через `commit_evidence_entry`), маршруты `POST /manifest/verify` + `GET /manifest/{bundle_id}` в `routes/artifacts.py`. Focused `test_artifact_manifest.py` — 69 passed; полный suite gate — 3210 passed / 0 failed / 17 skipped.
>
> **Scope deviation:** (1) `type='decision'` + маркер `manifest_type="BUNDLE_MANIFEST"` в `provenance_json` вместо нового значения PG-ENUM `evidence_type` — цепочка миграций заморожена, конвенция гейтов COS-136/138/141; pinned-набор (`canonical_refs`) при этом durable в ledger. (2) Реестр подтверждённых манифестов для GET — in-memory (один процесс cosmo-api) до появления durable-таблицы вне freeze; API-контракт от этого не зависит. (3) `run_id` добавлен в манифест опциональным полем: он NOT NULL FK на `runs.id`, а у манифеста прогона нет — без него верификация валидна, но не якорится (`ledger_entry_id=None`).

---

## 🔄 ACTIVE — SOVEREIGN WORKSPACE WAVE 6: SOURCE CONTROL & DIAGNOSTICS (IDE), TRANSFER AUTHORIZATION & CAS GUARD (AIRLOCK), EVIDENCE ATTESTATION & AIRGAP BUNDLE (SUPPLY CHAIN)

> **Правило разделения поверхностей (Zero-Collision Protocol):**
> 1. **Flash:** единоличный владелец `D:\prettyk-ide`. Ни Boss, ни Luna не трогают `prettyk-ide`.
> 2. **Boss:** изоляция в подсистеме Quality Gate & Release Transfer (`orchestrator/cosmo/domain/transfer_authorization.py`, `orchestrator/cosmo/control_plane/transfer_guard.py`, `orchestrator/cosmo/api/routes/releases.py`, `orchestrator/tests/cosmo/test_transfer_authorization.py`). Не трогает artifacts.py, manifest, airgap и IDE.
> 3. **Luna:** изоляция в подсистеме Supply Chain / Attestation / Airgap (`orchestrator/cosmo/domain/evidence_attestation.py`, `orchestrator/cosmo/ledger/attestation_packager.py`, `orchestrator/cosmo/domain/airgap_bundle.py`, `orchestrator/cosmo/ledger/airgap_verifier.py`, `orchestrator/cosmo/api/routes/artifacts.py`, `orchestrator/tests/cosmo/test_evidence_attestation.py`, `orchestrator/tests/cosmo/test_airgap_bundle.py`). Не трогает releases.py, hub.py и IDE.
> Пересечение файлов между воркерами строго 0.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-143** | Flash | 12-14h | P1 | COS-140 | ✅ DONE — Web IDE: Source Control View, Staged/Unstaged Working Tree & Inline Diff Review |
| **COS-144** | Flash | 10-12h | P1 | COS-137, COS-140 | ✅ DONE — Web IDE: Diagnostics & Problems Drawer with Inline Squiggly Highlighting & Quick Navigation |
| **COS-149** | Flash | 12-14h | P1 | COS-143, COS-144 | ✅ DONE — Web IDE: Multi-File Tabs & Working Set Management |
| **COS-150** | Flash | 10-12h | P1 | COS-144, COS-149 | ✅ DONE — Web IDE: Status Bar & Notification Toast Center |
| **COS-145** | Boss | 12-14h | P1 | COS-138, COS-141 | ✅ DONE — Cosmoport: Release Transfer Authorization Enforcement & Fail-Closed Audit Gate |
| **COS-146** | Boss | 10-12h | P1 | COS-145 | ✅ DONE — Cosmoport: Transfer CAS Concurrency Guard & Idempotent State Machine Replay |
| **COS-147** | Luna | 12-14h | P1 | COS-138, COS-142 | ✅ DONE — Cosmoport: Release Evidence Attestation Bundle & Provenance Verifier: chain of custody (манифест+SBOM+clearance), `provenance_bundle_hash`, ledger-якорь, bundle/read API |
| **COS-148** | Luna | 10-12h | P1 | COS-142, COS-147 | ✅ DONE — Cosmoport: Airgap Export/Import Bundle Integrity & Offline Manifest Verification Service: офлайн missing/corrupted/unregistered, порядок-независимый `package_digest_pin`, verify/read API |
| **COS-151** | Boss | 6-8h | P1 | COS-147, COS-148 | ✅ DONE — Cosmoport: канонический топологический wipe-порядок (общий `_wipe_order.py`, 45 таблиц, потомок→родитель + обнуление циклических FK), порядконезависимость Wave 6 166+166, орфаны 0 |
| **COS-152** | Luna | 8-12h | P1 | COS-147, COS-148 | ✅ DONE — Cosmoport: Read-through durable для GET-поверхностей attestation/airgap/manifest — чтение из evidence_ledger вместо in-memory реестров, restart-survival |
| **COS-153** | Boss | 8-12h | P1 | COS-139, COS-151 | ✅ DONE — Cosmoport: Read-through durable для hub evaluation dispatch — GET статуса отправки из evidence_ledger вместо in-memory реестра, restart-survival |

### Карточки волны

#### ✅ COS-143 · Flash · Web IDE: Source Control View, Staged/Unstaged Working Tree & Inline Diff Review — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-ide`:
>     - Создать модуль `src/cosmo/ide/sourceControlUtils.ts`:
>       - Чтение и категоризация измененных файлов: unstaged vs staged;
>       - Статусные маркеры: Modified (`M`), Added (`A`), Deleted (`D`);
>       - Хелперы для stage/unstage/stage-all/unstage-all/discard;
>     - Создать компонент `src/cosmo/ide/SourceControl.tsx`:
>       - Панель Source Control в боковом сайдбаре (переключатель между File Tree и Source Control);
>       - Секция «Staged Changes» и «Changes» (unstaged) с количеством файлов;
>       - Быстрые действия у каждого файла: Stage (`+`), Unstage (`-`), Discard (`Undo`);
>       - Групповые действия: «Stage All Changes», «Unstage All Changes»;
>       - Поле ввода commit message с валидацией (не пустое) и шорткатом `Ctrl+Enter` для коммита;
>       - Интеграция с существующим `CommitDialog` / вызов коммита;
>       - При клике по файлу в списке изменений — открытие диффа через существующий `ChangeReviewPanel`;
>     - В `src/app/App.tsx`:
>       - Переключатель сайдбара (Explorer / Source Control) с бейджем количества измененных файлов;
>     - В `src/app/app.css`:
>       - Стили для панели Source Control, бейджей статуса, кнопок stage/unstage.
> (2) Vitest тесты в `src/cosmo/ide/sourceControlUtils.test.ts`:
>     - Категоризация изменений, операции staging/unstaging, discard, валидация commit message.
> (3) Гейт: `tsc -b` — 0 ошибок, `npx vitest run` — все тесты зелёные, `npm run build` — успешен.
>
> **Out of scope:** Backend API, любые изменения в `D:\prettyk-airlock`.
> **Acceptance:** принято 19 сентября 2026 (Flash). Панель Source Control интегрирована в сайдбар с переключателем в Activity Bar; отображает изменённые и застейдженные файлы со статус-маркерами M/A/D; чистые функции staging transforms, discard и валидации commit message; клик по файлу открывает ChangeReviewPanel; 22 vitest тестов в `sourceControlUtils.test.ts`, общий vitest 345/345 passed across 17 files, `tsc -b` 0 ошибок, vite build 58 модулей green.

#### ✅ COS-144 · Flash · Web IDE: Diagnostics & Problems Drawer with Inline Squiggly Highlighting & Quick Navigation — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-ide`:
>     - Создать модуль `src/cosmo/ide/diagnosticsUtils.ts`:
>       - Структуры данных `DiagnosticItem`: `id`, `file`, `line`, `col`, `severity` (`error`, `warning`, `info`), `source` (SARIF, linter, compiler), `message`;
>       - Фильтрация по файлу, severity, поиск по сообщению;
>       - Группировка проблем по файлам;
>     - Создать компонент `src/cosmo/ide/ProblemsDrawer.tsx`:
>       - Вкладка «Problems» в нижнем `WebIDETerminalDrawer` (или переключатель вкладок Logs / Terminal / Problems);
>       - Счётчики: `X Errors, Y Warnings`;
>       - Список проблем с иконками severity, именем файла, позицией `line:col` и описанием;
>       - Клик по проблеме вызывает переход: открытие файла (если не открыт) и позиционирование курсора/скролла через `revealTarget` в `CodeEditor`;
>     - В `src/cosmo/ide/CodeEditor.tsx`:
>       - Отображение маркеров диагностик в gutter (красная точка/иконка для error, желтая для warning) на соответствующих строках;
>       - Подчеркивание (squiggly underline или background tint) для проблемных строк;
>     - В `src/app/app.css`: стили для списка проблем, gutter-маркеров и подчеркиваний.
> (2) Vitest тесты в `src/cosmo/ide/diagnosticsUtils.test.ts`:
>     - Парсинг, группировка, фильтрация по severity, сортировка по номеру строки.
> (3) Гейт: `tsc -b` — 0 ошибок, `npx vitest run` — все тесты зелёные, `npm run build` — успешен.
>
> **Out of scope:** Backend API, любые изменения в `D:\prettyk-airlock`.
> **Acceptance:** принято 19 сентября 2026 (Flash). ProblemsDrawer с фильтрацией (Errors/Warnings/Info) и триггером по `Ctrl+Shift+M`; интеграция в CodeEditor (маркеры в gutter, подсветка и подчеркивание проблемных строк); переход к позиции по клику на диагностику через revealTarget; 26 vitest тестов в `diagnosticsUtils.test.ts`, общий vitest 345/345 passed, `tsc -b` 0, vite build green.

#### ✅ COS-149 · Flash · Web IDE: Multi-File Tabs & Working Set Management — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-ide`:
>     - Создать модуль `src/cosmo/ide/tabsUtils.ts`:
>       - Модель вкладки `TabItem`: `path: string`, `title: string`, `isDirty: boolean`, `isPinned?: boolean`;
>       - Чистые функции: `openTab(tabs, path)`, `closeTab(tabs, path)`, `closeOtherTabs(tabs, path)`, `closeAllTabs(tabs)`, `selectNextTab(tabs, currentPath)`, `selectPrevTab(tabs, currentPath)`, `pinTab(tabs, path)`;
>       - Хелперы для определения заголовка (имя файла) и тултипа (полный относительный путь);
>     - Создать компонент `src/cosmo/ide/TabBar.tsx`:
>       - Горизонтальная панель вкладок над `Breadcrumbs` / `CodeEditor`;
>       - Элемент вкладки: иконка файла, название файла, точка-индикатор изменений (`●` isDirty), кнопка закрытия (`✕`);
>       - Активная вкладка подсвечена; горизонтальный скролл при переполнении;
>       - Контекстное меню (ПКМ по вкладке): Close, Close Others, Close to the Right, Close All;
>       - Защита от потери несохранённых данных: закрытие грязной вкладки запрашивает подтверждение (или сбрасывает через discard/save guard);
>     - В `src/app/App.tsx`:
>       - Подключение `TabBar` в основной макет над редактором;
>       - Синхронизация `openTabs` при выборе файлов в File Explorer, Command Palette, Search Palette, Problems Drawer;
>       - Шорткаты: `Ctrl+W` / `Cmd+W` (закрыть активную вкладку), `Ctrl+Tab` / `Ctrl+Shift+Tab` (переключение между вкладками);
>     - В `src/app/app.css`: стили панели вкладок (compact tab strip, active tab, dirty dot, close button, context menu).
> (2) Vitest тесты в `src/cosmo/ide/tabsUtils.test.ts`:
>     - Добавление, удаление, переключение, закрытие соседних/всех, сохранение порядка.
> (3) Гейт: `tsc -b` — 0 ошибок, `npx vitest run` — все тесты зелёные, `npm run build` — успешен.
>
> **Out of scope:** Backend API, любые изменения в `D:\prettyk-airlock`.
> **Acceptance:** Вкладки файлов отображаются над редактором; открытие файла добавляет/активирует вкладку; `Ctrl+W` закрывает активную вкладку; грязные файлы помечаются точкой `●`; vitest зелёный, `tsc -b` 0, vite build green.
>
> **✅ Принято 19 сентября 2026 (Cosmo, PO):** `TabBar` — источник истины рабочего набора (`activePath → selectedPath`); открытие lossless (правки per-path в `useEditState`); закрытие грязной вкладки через существующий `guard-overlay` (не новый механизм потери данных); шорткаты `Ctrl+W` / `Ctrl+Tab` / `Ctrl+Shift+Tab`; контекст-меню Close/Close Others/Close to the Right/Close All; middle-click close; double-click pin; семантика закрытия (правая соседка → левая → null); дедуп при RENAME. Модуль `tabUtils.ts` DOM-free.
> **Мой независимый прогон:** `npx vitest run` — 397/397 (20 файлов), `tsc -b` 0, `vite build` 64 модуля — зелёные.
>
> **Scope deviation / caveat:** `Ctrl+W`/`Ctrl+Tab` браузер может перехватывать до обработчика (зарезервированные шорткаты); `preventDefault` стоит, но в обычной вкладке браузера срабатывает не всегда — внутри оболочки IDE (без браузерного chrome) работает. Браузерный smoke на приёмке не гонялся (стенд не поднят в этой сессии). Backend не трогался.

#### ✅ COS-150 · Flash · Web IDE: Status Bar & Notification Toast Center — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-ide`:
>     - Создать модуль `src/cosmo/ide/statusBarUtils.ts`:
>       - Форматирование индикаторов: курсор (`Ln X, Col Y`), кодировка (`UTF-8`), отступы (`Spaces: 2`), язык (`TypeScript`, `JSON`, `Markdown` etc.);
>       - Форматирование сводки проблем (`X Errors, Y Warnings`);
>     - Создать модуль `src/cosmo/ide/toastUtils.ts`:
>       - Модель `ToastMessage`: `id: string`, `title?: string`, `message: string`, `type: 'info' | 'success' | 'warning' | 'error'`, `timeoutMs?: number`;
>       - Чистые функции: `addToast`, `removeToast`, `clearToasts`;
>     - Создать компонент `src/cosmo/ide/StatusBar.tsx`:
>       - Фиксированная нижняя полоса статуса IDE;
>       - Слева: текущая ветка git (клик открывает селектор веток), сводка ошибок/предупреждений (клик открывает Problems Drawer);
>       - По центру: индикатор фоновых процессов (спиннер при активном прогоне pipeline);
>       - Справа: позиция курсора (Ln/Col), кодировка (UTF-8), режим отступов, текущий язык;
>     - Создать компонент `src/cosmo/ide/ToastNotification.tsx`:
>       - Контейнер тостов в правом нижнем углу;
>       - Анимация появления/исчезновения, автозакрытие по таймеру (3с), кнопка ручного закрытия;
>     - В `src/app/App.tsx`:
>       - Интеграция `StatusBar` внизу страницы;
>       - Хук тостов для отображения уведомлений (Save, Branch Created, Staged, Copied to clipboard);
>     - В `src/app/app.css`: стили статус-бара и всплывающих тостов.
> (2) Vitest тесты в `src/cosmo/ide/statusBarUtils.test.ts` и `src/cosmo/ide/toastUtils.test.ts`.
> (3) Гейт: `tsc -b` — 0 ошибок, `npx vitest run` — все тесты зелёные, `npm run build` — успешен.
>
> **Out of scope:** Backend API, любые изменения в `D:\prettyk-airlock`.
> **Acceptance:** Нижний StatusBar отображает ветку, ошибки/предупреждения, кодировку и курсор; клики открывают соответствующие панели; Toast-уведомления появляются при операциях и автоматически закрываются; vitest зелёный, `tsc -b` 0, vite build green.
>
> **✅ Принято 19 сентября 2026 (Cosmo, PO):** `StatusBar` внизу (ветка git → клик открывает селектор веток; сводка проблем → Problems Drawer; спиннер фонового прогона; справа курсор `Ln/Col`, кодировка `UTF-8`, отступы, язык) + `ToastContainer` (правый нижний угол, автозакрытие 3с, ручное закрытие, монотонный `seq`). Интеграция: тосты на Save/Branch created/Staged/Copied; курсор через `onCursorChange` из `CodeEditor`. Модули `statusBarUtils.ts`/`toastUtils.ts` DOM-free.
> **Мой независимый прогон:** `npx vitest run` — 397/397, `tsc -b` 0, `vite build` 64 модуля — зелёные. Backend не трогался.

#### ✅ COS-145 · Boss · Cosmoport: Release Transfer Authorization Enforcement & Fail-Closed Audit Gate — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Quality Gate / Release Transfer Enforcement):
>     - В `orchestrator/cosmo/domain/transfer_authorization.py`:
>       - Pydantic-модели `TransferAuthorizationDecision`:
>         - `authorized: bool`, `release_id: str`, `target_zone: str`, `clearance_status: str`, `sbom_attestation_status: str`, `reasons: list[str] = []`, `checked_at: str`;
>     - В `orchestrator/cosmo/control_plane/transfer_guard.py`:
>       - Сервис `ReleaseTransferGuard`:
>         - Проверка `release_transfer_allowed(session, release_id)` (из `ledger/hub_clearance_gate.py`): если вердикт Quality Gate не `PASS_GRANTED` или `ok_to_transfer is False` -> отказ;
>         - Проверка аттестации SBOM (из `ledger/sbom_gate.py`): если есть критические уязвимости (`critical_count > 0`) или SBOM не аттестован -> отказ;
>         - Fail-closed авторизация: при отсутствии записей клиренса или ошибке проверки — строгий отказ;
>         - Запись аудит-события `release_transfer_authorization` в `cosmo_audit_events` (success / denied с перечислением reasons);
>     - В `orchestrator/cosmo/api/routes/releases.py`:
>       - Интеграция `ReleaseTransferGuard` в эндпоинты трансфера (`POST /api/v1/releases/{release_id}/transfer` и `POST /api/v1/releases/{release_id}/transfer-v2`):
>         - Если `authorized is False` — возврат HTTP 403 Forbidden с детальным JSON описанием блокировки;
>         - Добавление опционального query/header флага bypass-проверки только для системного администратора в dev-режиме с обязательной аудит-фиксацией (`BYPASS_ATTEMPT`);
> (2) Тесты в `orchestrator/tests/cosmo/test_transfer_authorization.py`:
>     - Успешная авторизация при наличии `PASS_GRANTED` клиренса и чистого SBOM;
>     - Блокировка (HTTP 403) при отсутствии Hub clearance;
>     - Блокировка (HTTP 403) при `qg_clearance == 'BLOCKED'` или `'REJECTED'`;
>     - Блокировка (HTTP 403) при наличии `critical_count > 0` в SBOM;
>     - Фиксация событий в аудит-логе;
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Supply Chain / Artifacts, файлы routes/artifacts.py, domain/artifact_manifest.py.
> **Acceptance:** Трансфер релизов в ЗТ/ЗПЭ блокируется с HTTP 403 при отсутствии или отрицательном вердикте Quality Gate Hub либо критических уязвимостях в SBOM; разрешается строго при подтвержденном клиренсе; события фиксируются в аудите; suite gate зелёный.
>
> **✅ Verified (2026-09-19):** `domain/transfer_authorization.py` (`TransferAuthorizationDecision`, `TransferReplayResponse`, `TransferTransition`, константы), `control_plane/transfer_guard.py` (`ReleaseTransferGuard.authorize` — fail-closed по двум свидетельствам: `PASS_GRANTED` clearance COS-141 + `PASS` SBOM-аттестация COS-138; сбой чтения → `CHECK_FAILED` и отказ), `api/routes/releases.py` (dependency `enforce_release_transfer_authorization` на оба трансфер-маршрута → 403 с JSON-описанием блокировки; `bypass_authorization` только system-admin+dev с аудитом `BYPASS_ATTEMPT`).
> **Deviation:** audit-статус отказа — `blocked` (документированный словарь `success|failed|blocked`), а не `denied` из текста карточки; action-имя — `release_transfer_authorization` (карточка governs). `critical_count` из аттестации не экспонируется → эквивалент через `gate_verdict == "BLOCK"`.
> **Tests:** `orchestrator/tests/cosmo/test_transfer_authorization.py` — 37 passed. **Suite gate:** 3320 passed / 17 skipped / 0 failed (276.75s).

#### ✅ COS-146 · Boss · Cosmoport: Transfer CAS Concurrency Guard & Idempotent State Machine Replay — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Transfer State Machine Concurrency & CAS):
>     - В `orchestrator/cosmo/control_plane/transfer_guard.py` (или расширение):
>       - Compare-And-Swap (CAS) guard: атомарная проверка текущей зоны (`current_zone`) релиза перед промоушеном;
>       - Обнаружение конкурентных попыток трансфера одного релиза в разные или одинаковые зоны:
>         - Если текущая зона уже равна целевой (`current_zone == to_zone`) и в `transfer_history` есть завершенная запись — возврат идемпотентного ответа (HTTP 200) без создания дублирующих записей истории и без повторной эмиссии уведомлений;
>         - Если трансфер находится в промежуточном состоянии или зафиксирован конфликт перехода — HTTP 409 Conflict;
>     - В `orchestrator/cosmo/api/routes/releases.py`:
>       - Интеграция CAS-проверки и идемпотентного replay в маршруты трансфера;
> (2) Тесты в `orchestrator/tests/cosmo/test_transfer_authorization.py`:
>     - Идемпотентный повтор успешного трансфера (возврат 200 без дублирования history);
>     - Отклонение недопустимых обратных переходов (например, `zpe -> zr`);
>     - Конфликт версий / зон (HTTP 409 при расхождении expected state);
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Supply Chain / Artifacts, файлы routes/artifacts.py.
> **Acceptance:** Конкурентные или повторные вызовы трансфера идемпотентно возвращают текущий статус без гонок данных; недопустимые переходы возвращают 400/409; suite gate зелёный.
>
> **✅ Verified (2026-09-19):** `ReleaseTransferGuard.evaluate_transition` (PROCEED / REPLAY / CONFLICT) + `replay_payload`; `expected_current_zone` в `TransferRequest`/`TransferReleaseRequest`; CAS/replay-блок в оба трансфер-маршрута ПЕРЕД strict linear zone validation: расхождение expected state → 409, повтор уже достигнутой зоны → 200 `duplicate_success` без дублей `transfer_history` и без повторной эмиссии.
> **Tests:** `orchestrator/tests/cosmo/test_transfer_authorization.py` — 37 passed. **Suite gate:** 3320 passed / 17 skipped / 0 failed.
> **Note:** order-dependent флейки `_wipe` (FK apps↔pipeline_plans, runs↔pipeline_plans), наблюдавшиеся при изолированных прогонах, — предсуществующий дефект тестовой БД, воспроизводится и без новых тестов (1/8 baseline-прогонов), уже заведён отдельной карточкой **COS-151**; на зелёный suite gate не влияет.

#### ✅ COS-147 · Luna · Cosmoport: Release Evidence Attestation Bundle & Provenance Verifier — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Supply Chain / Attestation / Provenance):
>     - В `orchestrator/cosmo/domain/evidence_attestation.py`:
>       - Pydantic-модели:
>         - `EvidenceAttestationSubject`: `name: str`, `digest: str` (`sha256:...`);
>         - `EvidenceAttestationPredicate`:
>           - `release_id: str`, `bundle_id: str | None = None`, `profile: str`,
>           - `manifest_digest_pin: str | None = None`, `sbom_digest: str | None = None`,
>           - `hub_clearance_status: str | None = None`, `hub_evaluation_id: str | None = None`,
>           - `timestamp: str`;
>         - `EvidenceAttestationBundle`:
>           - `format: Literal["cosmo-attestation@1"] = "cosmo-attestation@1"`,
>           - `subject: EvidenceAttestationSubject`,
>           - `predicate: EvidenceAttestationPredicate`,
>           - `provenance_bundle_hash: str`,
>           - `verified: bool`;
>     - В `orchestrator/cosmo/ledger/attestation_packager.py`:
>       - Сервис `AttestationBundlePackager`:
>         - Сбор всех крипто-свидетельств из `evidence_ledger` для указанного `release_id`: манифест бандла (COS-142), аттестация SBOM (COS-138), вердикт клиренса Hub (COS-141);
>         - Расчет канонического `provenance_bundle_hash`: SHA256 от канонического представления субъекта и предиката;
>         - Сверка целостности цепочки (chain of custody): совпадение digest артефакта во всех свидетельствах;
>         - Запись сформированного бандла в `cosmo_evidence_ledger` (`type='decision'`, маркер `attestation_type="RELEASE_ATTESTATION_BUNDLE"`);
>     - В `orchestrator/cosmo/api/routes/artifacts.py`:
>       - `POST /api/v1/artifacts/attestation/bundle` — формирование и верификация полного attestation bundle для релиза;
>       - `GET /api/v1/artifacts/attestation/{release_id}` — чтение актуального аттестационного бандла;
> (2) Тесты в `orchestrator/tests/cosmo/test_evidence_attestation.py`:
>     - Формирование полного attestation bundle и расчет детерминированного хэша;
>     - Верификация непрерывности цепочки свидетельств;
>     - Определение расхождений (mismatch дайджестов между SBOM и манифестом);
>     - Фиксация в ledger;
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Quality Gate / Hub, файлы routes/hub.py, routes/releases.py.
> **Acceptance:** `POST /api/v1/artifacts/attestation/bundle` агрегирует криптографические свидетельства релиза (манифест, SBOM, clearance), считает канонический root hash бандла, валидирует целостность связей и фиксирует в ledger; `GET /api/v1/artifacts/attestation/{release_id}` читает бандл; suite gate зелёный.
> **Принято 19 сентября 2026 (Luna):** `domain/evidence_attestation.py` (DTO subject/predicate/bundle, `compute_provenance_bundle_hash` — SHA256 канонического `sort_keys+compact` представления subject+predicate), `ledger/attestation_packager.py` (`AttestationBundlePackager` — сбор свидетельств COS-142/138/141 из ledger, chain of custody по digest артефакта, ledger-якорь `type='decision'` + маркер `attestation_type="RELEASE_ATTESTATION_BUNDLE"`), маршруты `POST /attestation/bundle` (route-local `AttestationBundleRequest{release_id}`) + `GET /attestation/{release_id}` в `routes/artifacts.py`. Focused `test_evidence_attestation.py` — 32 passed. Полный suite gate: 3280 passed / 3 failed / 17 skipped — 3 падения вне поверхности COS-147/148 (территория Boss: инвариант `routes/releases.py` + order-dependent `test_hub_verdict_ingest.py`), вынесено PO.
>
> **Scope deviation:** (1) `verified` — это вердикт: `true` при ≥1 digest-bearing свидетельстве и отсутствии mismatch'ей; расхождение дайджестов → `verified=false` (не 5xx), детали durable в `provenance_json.chain_of_custody.mismatches`. (2) `type='decision'` + маркер `attestation_type` в `provenance_json` вместо нового PG-ENUM `evidence_type` (цепочка миграций заморожена, конвенция COS-136/138/141). (3) Реестр чтения бандлов для GET — in-memory (один процесс cosmo-api), root hash при этом durable в ledger. **[superseded COS-152: read-path переведён на ledger, реестр удалён]** (4) Якорь ledger — `release.run_ids[0]` (как COS-138): релиз без прогонов → 422, неизвестный релиз → 404, нет digest-bearing свидетельств → 422.

#### ✅ COS-148 · Luna · Cosmoport: Airgap Export/Import Bundle Integrity & Offline Manifest Verification Service — DONE (2026-09-19)
> **Scope:**
> (1) Поверхность строго в `D:\prettyk-airlock` (Supply Chain / Airgap Bundle Verification):
>     - В `orchestrator/cosmo/domain/airgap_bundle.py`:
>       - Pydantic-модели:
>         - `AirgapFileChecksum`: `filename: str`, `sha256: str`, `size_bytes: int`;
>         - `AirgapPackageManifest`: `package_id: str`, `release_id: str`, `created_at: str`, `files: list[AirgapFileChecksum]`, `package_digest_pin: str`;
>         - `AirgapVerifyRequest`: `manifest: AirgapPackageManifest`, `archive_files: list[AirgapFileChecksum]`;
>         - `AirgapVerifyResponse`: `verified: bool`, `package_id: str`, `missing_files: list[str] = []`, `corrupted_files: list[str] = []`, `unregistered_files: list[str] = []`, `errors: list[str] = []`;
>     - В `orchestrator/cosmo/ledger/airgap_verifier.py`:
>       - Сервис `AirgapBundleVerifier`:
>         - Офлайн-валидация целостности архива: сверка списка файлов архива со списком манифеста без сетевых вызовов;
>         - Проверка SHA256 каждого файла;
>         - Проверка `package_digest_pin` манифеста (SHA256 от отсортированных чексумм файлов);
>         - Фиксация проверенного airgap-пакета в `cosmo_evidence_ledger` (`type='decision'`, маркер `airgap_type="AIRGAP_VERIFIED"`);
>     - В `orchestrator/cosmo/api/routes/artifacts.py`:
>       - `POST /api/v1/artifacts/airgap/verify` — офлайн-верификация целостности airgap-бандла;
>       - `GET /api/v1/artifacts/airgap/{package_id}` — чтение статуса проверенного airgap-бандла;
> (2) Тесты в `orchestrator/tests/cosmo/test_airgap_bundle.py`:
>     - Успешная валидация корректного airgap-бандла;
>     - Обнаружение модифицированного файла (`corrupted_files`);
>     - Обнаружение недостающего файла (`missing_files`);
>     - Обнаружение недоверенного/лишнего файла (`unregistered_files`);
>     - Отсутствие внешних сетевых зависимостей (чистая автономная логика);
> (3) Гейт: `services/scripts/suite_gate.ps1` — green.
>
> **Out of scope:** Web IDE, Quality Gate / Hub, файлы routes/hub.py, routes/releases.py.
> **Acceptance:** `POST /api/v1/artifacts/airgap/verify` проводит полную автономную проверку целостности airgap-пакета по манифесту (missing, corrupted, unregistered files), проверяет package digest pin и фиксирует в ledger; `GET /api/v1/artifacts/airgap/{package_id}` возвращает статус; suite gate зелёный.
> **Принято 19 сентября 2026 (Luna):** `domain/airgap_bundle.py` (DTO `AirgapFileChecksum`/`AirgapPackageManifest`/`AirgapVerifyRequest`/`AirgapVerifyResponse`, `normalize_sha256`, traversal-guard имён файлов: reject `..`, absolute, `\`, NUL, пустых сегментов), `ledger/airgap_verifier.py` (`compute_package_digest_pin` — SHA256 отсортированных `filename:sha256:size`, порядок-независим; `compare_archive` — чистая логика без БД/сети; `AirgapBundleVerifier` + ledger-якорь `type='decision'` + маркер `airgap_type="AIRGAP_VERIFIED"`), маршруты `POST /airgap/verify` + `GET /airgap/{package_id}` в `routes/artifacts.py`. Focused `test_airgap_bundle.py` — 41 passed (итого 73 по пакету).
>
> **Scope deviation:** (1) `type='decision'` + маркер `airgap_type` в `provenance_json` вместо нового PG-ENUM (цепочка миграций заморожена). (2) Реестр статусов для GET — in-memory (один процесс cosmo-api). **[superseded COS-152: read-path переведён на ledger, реестр удалён]** (3) Честная граница офлайн-контура: `run_id` — NOT NULL FK на `runs.id`, у airgap-пакета прогона нет; якорь берётся у локального релиза (`release_id → run_ids[0]`); если релиза/прогонов локально нет — вердикт считается и возвращается, но ledger-запись не создаётся (якорить нечем). (4) Проваленные вердикты тоже фиксируются в ledger — проваленный импорт это ровно то, что должно остаться в журнале доказательств. (5) Digest новых DTO — `sha256:<64 lowercase hex>`; ledger `content_hash` — bare hex; `sbom_digest` проходит passthrough из COS-138 без переинтерпретации.

#### ✅ COS-151 · Boss · Cosmoport: Test-DB wipe order-dependence — FK-порядок очистки тестовой БД — DONE (2026-09-19)
> **Контекст (PO-приёмка Wave 6):** связка файлов Wave 6
> (`test_hub_clearance.py` + `test_transfer_authorization.py` + `test_hub_verdict_ingest.py`
> + `test_sbom_gate.py` + `test_evidence_attestation.py` + `test_airgap_bundle.py`)
> при полном прогоне даёт order-dependent сбои: очистка тестовой БД между
> тестами падает на нарушении внешних ключей. Ранее приёмка COS-147 уже
> зафиксировала «3 падения вне поверхности COS-147/148 (территория Boss:
> инвариант routes/releases.py + order-dependent test_hub_verdict_ingest.py)».

> **Зафиксированные PO симптомы (не решение, а стенки для локализации):**
> (1) `IntegrityError` в `evidence_ledger`: `Key (run_id)=(hubclrrun0001) is not
> present in table "runs"` — сидированные данные одного тест-файла стираются
> очисткой до того, как их использует следующий файл связки.
> (2) `ForeignKeyViolationError`: `update or delete on table "apps" violates
> foreign key constraint "pipeline_plans_app_id_fkey"` (`Key (id)=(hub-cos141-app)`).
> (3) `cosmo_deployments` ссылается на `releases`, но в порядке очистки
> `releases` идёт раньше.
> (4) В порядке очистки отсутствуют таблицы, ссылающиеся на releases/runs/apps:
> `scan_findings`, `scan_evidence`, `scan_results`, `release_batches`,
> `application_teams`, `application_kits_tags` — их строки переживают очистку
> между прогонами и порождают фантомы/конфликты.
> (5) Детерминированная регрессия теста-инварианта (НЕ order-dependent;
> заметила Luna при приёмке COS-147): вынос `require_capability(...)` в атрибут
> `_RELEASE_TRANSFER_GUARD` убрал литерал `require_capability(` из блоков
> `transfer_release` / `transfer_release_v2` — инвариант COS-091/092 проходит по
> литералу и падает; функционально guard на месте через `Depends(_RELEASE_TRANSFER_GUARD)`,
> тест — литеральный.

> **Scope:**
> (1) Привести порядок очистки тестовой БД к топологическому: child-таблицы
> (со ссылками на родителей) вычищаются строго раньше родительских —
> охватить ВСЕ таблицы со внешними ключами на releases/runs/apps/deployments,
> включая перечисленные отсутствующие; где связь циклическая — снять
> циклический FK явным обнулением до удаления.
> (2) Убедиться, что очистка выполняется и на setup, и на teardown тест-фикстуры,
> и не оставляет строк-сирот ни в одном файле связки.
> (3) Доказать отсутствие order-dependence: прогон связки Wave 6 в прямом и
> обратном порядке файлов даёт одинаковый зелёный результат.
> (4) Закрыть регрессию инварианта `transfer_release`/`transfer_release_v2`
> (симптом 5): либо вернуть литерал `require_capability(` в охранные блоки
> так, чтобы инвариант снова узнавал guard, либо научить инвариант распознавать
> вынесенную фабрику `_RELEASE_TRANSFER_GUARD` — выбор за владельцем поверхности,
> без ослабления самого guard'а (fail-closed обязателен).

> **Out of scope:** продуктовый код (transfer_guard/releases/hub/artifacts),
> Web IDE, миграционная цепочка (заморожена), отдельные per-worker scratch-БД.

> **Acceptance:**
> - Связка шести файлов Wave 6 в любом порядке: **0 failed**, повторно ×2.
> - Очистка не выбрасывает ForeignKeyViolation/IntegrityError ни на setup, ни
>   на teardown.
> - Инвариант releases.py (`test_domain_resolve_invariant`) снова зелёный, guard
>   остаётся fail-closed.
> - Полный suite gate: **0 failed** (все нарушения только вне поверхности
>   карточки, если таковые есть — точечно зафиксировать в отчёте).

> **Отчёт обратно:** изменённые поверхности; прогон связки прямом+обратном;
> результат suite gate; оставшиеся order-dependent сбои (если остались) с
> конкретикой таблица↔таблица; блокеры.

> **Acceptance (PO, 19 сентября 2026):** COS-151 закрыт. Канонический порядок
> вынесен в общий `_wipe_order.py` (45 таблиц, потомок→родитель) + явное
> обнуление циклических FK (`apps.pipeline_plan_id`, `runs.batch_id`);
> `conftest.py` и `integration/conftest.py` переведены на общий список.
> Полный прогон **3436 passed / 17 skipped / 0 failed**; порядконезависимость
> Wave 6 — **166 passed прямой + 166 passed обратный**; орфаны по всем 45
> доменным таблицам = 0.

> **Зафиксировано для Максима (не блокер COS-151):** таблицы `hub_*`
> (`hub_finding` и др.) не описаны в этом репо ни моделями, ни миграциями, ни
> SQL — приходят из другого репозитория, делящего `cosmo_test`. Их очистка вне
> COS-151; конкуренция параллельных наборов за общую БД — факт владельцу стенда.

#### ✅ COS-152 · Luna · Cosmoport: Read-through durable — GET surfaces attestation/airgap/manifest из evidence_ledger — DONE (2026-09-19)
> **Контекст (PO):** при приёмке COS-147/148 и COS-142 зафиксировано однородное
> scope deviation: POST-эндпоинты пишут якорь в `cosmo_evidence_ledger`
> (durable, PG), но GET-поверхности (`GET .../attestation/{release_id}`,
> `GET .../airgap/{package_id}`, `GET .../manifest/{bundle_id}`) читают из
> in-memory реестра процесса — рестарт cosmo-api теряет read-ответы. Данные
> для чтения УЖЕ durable в ledger (маркеры `attestation_type`, `airgap_type`,
> `manifest_type` + `content_ref`); не хватает read-through, а не нового хранилища.

> **Scope:**
> (1) Переписать GET-поверхности трёх ресурсов на чтение актуального якоря из
> `cosmo_evidence_ledger` по identity (`release_id` / `package_id` / `bundle_id`),
> правило «latest wins» — как уже принято в clearance-чтении. Никаких новых
> таблиц и правок миграционной цепочки (заморожена).
> (2) Удалить in-memory реестры-дубликаты; единственный источник истины —
> ledger.
> (3) Честный edge: сущность, которая НЕ была якорена в ledger (airgap-пакет
> без локального релиза — существующее отклонение COS-148), читается как
> non-durable и явно документируется, а не имитируется фейковым ответом.
> (4) Restart-survival доказать тестом: запись → свежий процесс/engine → GET
> видит актуальный durable-ответ.

> **Out of scope:** `conftest.py` вообще (поверхность COS-151, Boss),
> `routes/releases.py`, `routes/hub.py`, миграционная цепочка, Web IDE.

> **Acceptance:**
> - После `POST` (attestation/airgap/manifest) рестарт cosmo-api НЕ теряет
>   `GET`-ответ: читается из ledger.
> - `GET` без предшествующего `POST` в этом процессе отдаёт durable-ответ,
>   а не пустой «не видел» (для якорённых сущностей).
> - Отсутствует in-memory реестр в read-path (нет второго источника истины).
> - Focused тесты трёх GET-поверхностей + restart-survival: зелёные, сат-гейт
>   без регрессий вне поверхности.

> **Отчёт обратно:** изменённые поверхности; доказательство restart-survival;
> результат focused-сюит и suite gate; оставшиеся non-durable edge-случаи;
> блокеры.

> **Принято 19 сентября 2026 (Luna):** in-memory реестры чтения удалены во всех
> трёх ledger-модулях; GET-поверхности читают актуальный якорь из
> `evidence_ledger` (latest wins по `created_at desc, id desc`):
> - `ledger/manifest_verifier.py` — `latest_manifest(session, bundle_id)` +
>   `_manifest_from_provenance` (реконструкция из `provenance_json.artifacts`,
>   fallback — парсинг `canonical_refs`; integrity: `manifest_content_hash` ==
>   `manifest_hash`); в provenance добавлены `artifacts` + `expected_digest_pin`
>   (read без потерь);
> - `ledger/attestation_packager.py` — `latest_attestation_bundle(session,
>   release_id)` + `_bundle_from_provenance` (integrity: пересчёт
>   `compute_provenance_bundle_hash` и сверка `content_hash`);
> - `ledger/airgap_verifier.py` — `latest_airgap_status(session, package_id)` +
>   integrity-сверка `_provenance_hash` (якоря цепочки `_chain_*`, добавляемые
>   `evidence_writer.seal_entry` ПОСЛЕ подписи, при пересчёте исключаются);
> - `routes/artifacts.py` — 3 GET принимают `session` и зовут `latest_*`;
>   `_reset_manifest_state` / `_reset_attestation_state` / `_reset_airgap_state`
>   удалены.
> Focused (3 файла): **149 passed**. Restart-survival доказан тестом
> `orchestrator/tests/cosmo/_durable_probe.py`: subprocess поднимает свежий
> ASGI-app + свежий engine к той же БД и делает GET (attestation/manifest/
> airgap). Полный suite gate: **3335 passed / 0 failed / 17 skipped** (309.14s).
>
> **Scope deviation:** (1) `latest wins` по `(created_at desc, id desc)` —
> правило как в clearance-чтении COS-141. (2) Integrity-проверка при чтении:
> повреждённая/неполная запись → `None` → 404 (честный отказ вместо отдачи
> подделки). (3) Non-durable edges сохранены и документированы: manifest без
> `run_id` (верификация без якоря) → 404; airgap без локального релиза
> (отклонение COS-148) → 404. Фейковый in-memory ответ не имитируется.
> (4) Симметричная задача для hub-dispatch — COS-153 (Boss).

#### ✅ COS-153 · Boss · Cosmoport: Read-through durable — GET статуса hub evaluation dispatch из durable-источника — DONE (2026-09-19)
> **Контекст (PO):** при приёмке COS-139 зафиксировано scope deviation:
> `POST /hub/evaluations/dispatch` пишет статус отправки в in-memory реестр
> процесса, а `GET /hub/evaluations/{evaluation_id}` читает его из памяти —
> рестарт cosmo-api теряет статус. При этом факт отправки уже durable: событие
> `success/failed/duplicate` пишется в аудит (`cosmo_audit_events`). Симметрия
> COS-152 (Luna, поверхности Supply Chain): нужен read-through, а не новое
> хранилище.

> **Scope:**
> (1) Переписать `GET /hub/evaluations/{evaluation_id}` на чтение актуального
> статуса из durable-источника (аудит-записи по `evaluation_id`, правило
> latest wins) либо явный durable-якорь — на выбор владельца, но БЕЗ новых
> таблиц и правок миграционной цепочки (заморожена).
> (2) Убрать in-memory реестр-дубликат: единственный источник истины — durable.
> (3) Честная семантика: неизвестный/незаписаный `evaluation_id` → 404 (а не
> фантомный статус из памяти).
> (4) Restart-survival тестом: dispatch → свежий процесс/engine → GET видит
> durable-статус.

> **Out of scope:** Supply Chain/artifacts (COS-152, Luna), `routes/releases.py`
> enforcement (закрыт COS-145/146), миграционная цепочка, Web IDE.

> **Acceptance:**
> - После dispatch рестарт cosmo-api не теряет `GET /evaluations/{id}`.
> - `GET` без предшествующего dispatch в этом процессе отдаёт durable-статус
>   для известного id, 404 для неизвестного.
> - В read-path нет in-memory реестра.
> - Focused тесты + restart-survival зелёные; suite gate без регрессий.

> **Отчёт обратно:** изменённые поверхности; доказательство restart-survival;
> результат тестов и suite gate; оставшиеся edge-случаи; блокеры.

> **Принято 19 сентября 2026 (Boss):** in-memory реестр отправок удалён;
> `GET /hub/evaluations/{evaluation_id}` читает актуальный durable-якорь из
> `evidence_ledger` (latest wins по `created_at desc, id desc`). Выбран вариант
> «явный durable-якорь» (а не чтение аудита — см. отклонение 1):
> - NEW `ledger/hub_evaluation_ledger.py` — `HubEvaluationLedger` +
>   `DispatchRecord`; маркеры `provenance_json.source='prettyk-hub'`,
>   `evaluation_type='HUB_EVALUATION_DISPATCH'`, `outcome ∈ {dispatched, failed}`;
>   `record` / `latest_for_evaluation` (любой исход) /
>   `latest_dispatched_for_evaluation` (только успех — идемпотентность/дрейф);
>   крипто-якорь `evaluation_dispatch_hash(payload)` в `content_hash` и
>   `provenance_json.dispatch_hash`;
> - `control_plane/hub_dispatcher.py` — реестр (`_DISPATCH_REGISTRY`,
>   `_REGISTRY_LOCK`, `reset_dispatch_registry`, `threading`) удалён;
>   `dispatch(request, *, session, actor)` пишет якорь на успех и на честный
>   сбой; `get(session, evaluation_id)` читает из ledger;
> - `api/routes/hub.py` — dispatch/get принимают `db`; 404 на неизвестный run;
> - `domain/hub_evaluation.py` — `HUB_EVALUATION_LEDGER_TYPE` +
>   `evaluation_dispatch_hash`;
> - `tests/cosmo/test_hub_evaluation_dispatch.py` — unit через `_FakeLedger`,
>   route через seed-run, restart-survival через
>   `_durable_probe.get_in_fresh_process`.
> Focused: **47 passed**. Restart-survival доказан: dispatch → свежий
> процесс/engine к той же БД → GET видит durable-статус. Полный suite gate:
> **3335 passed / 0 failed / 17 skipped** (306.83s). OpenAPI без изменений —
> **141 путей / 187 схем**, `json==yaml==live`, contract-тест **13 passed**.
>
> **Scope deviation:** (1) аудит НЕ durable — `api/routes/audit.py` пишет в
> in-memory `_AUDIT_LOG_RECORDS`, поэтому посылка карточки о durable-аудите
> неверна; выбран явный якорь в `evidence_ledger` (конвенция гейтов
> COS-136/138/141/142/147/152). (2) `evidence_ledger.run_id` — NOT NULL FK на
> `runs.id`, поэтому dispatch теперь требует существующий run → 404 (ранее
> неизвестный run не проверялся). (3) `type='decision'` + маркер в
> `provenance_json` — колонка `type` ограничена frozen PG-ENUM `evidence_type`
> (миграционная цепочка заморожена). (4) Семантика: дубликат нового якоря не
> создаёт; сбой (`failed`) durable и виден в GET (latest wins), но retry не
> блокирует — идемпотентность по последнему *успешному* якорю.

---

---

# PK-C-003 — ЧЕКЛИСТ-ТРЕБОВАНИЯ 2.0 ИЗ АНТИ-ПАТТЕРНОВ ИНКУМБЕНТА

> Источник: D:\prettyk\control-plane\2026-09-02-cosmoport-1-recon.md (Vector).
> Формат MASTER: PO вносит карточки в свою surface, каждый пункт —
> проверяемое требование к 2.0 с Given/When/Then. PO отмечает галочки,
> evidence — ссылками в комментарий карточки MASTER.

## ⬜ PK-C-003.1 — HEALTH AS DAY-ONE + TEST CONTOUR OWNERSHIP

- [ ] Given ПУ развёрнута в любом контуре (dev/lab/prod), When выполняется
  `GET /ready`, Then ответ — честный компонент-мап (503 при down hard-dep,
  200+degraded при soft) до того, как через edge уходит пользовательский
  трафик; Given тестовый стенд, When он поднят, Then есть именованный
  владелец контура и единственная команда его здоровья (suite gate).
- Evidence: (заполняет PO при приёмке)

> Состояние: COS-090 (503+компонент-мап) + COS-089 (suite gate) + COS-089
> janitor + DEPLOYMENT §13.1 — ядро есть. Остаток: зафиксировать ownership
> тестового стенда как требование (кто владеет контуром и кто чинит /health
> первым), внести в DEPLOYMENT/CONCEPT как канон-строку.
> ✅ Канонизировано (COS-136): ownership контура + единственная команда
> здоровья (suite gate) зафиксированы в DEPLOYMENT.md §13.1.

## ⬜ PK-C-003.2 — FAILOVER = PHASE 3, NOT PHASE 1

- [ ] Given базовый контур нестабилен (рестарты, race, edge-деградации),
  When планируется спринт, Then ни одна карточка failover/HA не входит в
  фазы 1-2 — только после зелёного стабильного basеline (restart-first
  доказан suite gate + runtime acceptance).
- Evidence: (заполняет PO)

> Состояние: противоядие соблюдено — restart-first (COS-063) и durability
> (COS-077/081/082/088) идут раньше failover; failover-карточек в backlog
> нет, и это правильно. Зафиксировать строкой в ARCHITECTURE-DIRECTION.
> ✅ Канонизировано (COS-136): «Failover = Phase 3, not Phase 1» зафиксировано
> в ARCHITECTURE-DIRECTION.md §10.

## ⬜ PK-C-003.3 — MIGRATION AS REHEARSED PROCEDURE

- [ ] Given миграционная цепочка, When планируется перенос/апгрейд, Then
  миграция прогоняется как репетиция на scratch (перенос → verify → откат)
  до боевого применения, и ни один миграционный тест не зависит от
  состояния dev-БД.
- Evidence: (заполняет PO)

> Состояние: ядро есть — scratch-based verification + catalog-race
> isolation (COS-076), per-session БД (COSMO_TEST_SESSION_DB). Остаток:
> оформить «репетицию миграции» как явную процедуру (шаги: scratch →
> прогон → сверка → боевой upgrade) в DEPLOYMENT.md.
> ✅ Канонизировано (COS-136): процедура-репетиция (scratch → прогон →
> сверка → боевой upgrade) зафиксирована в DEPLOYMENT.md §10.2.

## ✅ PK-C-003.4 — ONE BUNDLE, CANONICAL TAGS

- [x] Given образ/артефакт собирается один раз, When он регистрируется, Then
  существует ровно один канонический tag-формат (version+digest, без
  latest) и один бандл-профиль поставки; расхождение версий ядро/стенд
  невозможно by construction (digest-pin в manifest).
- Evidence: Реализовано и зафиксировано в COS-142 (19.09.2026). Канонический tag-контракт `<name>:<version>@sha256:<digest>` (строгий slug имени, semver-версия, отказ при `latest` и неканоничном digest) и детерминированный `digest_pin` бандла (SHA256 профиля + отсортированных canonical_ref) в `orchestrator/cosmo/domain/artifact_manifest.py`, `ledger/manifest_verifier.py`, `api/routes/artifacts.py`. 69 тестов в `test_artifact_manifest.py`.

> Состояние: ✅ Реализовано (COS-142). Digest-pin доведён до контрактной
> поверхности: канонический tag-формат валидируется на границе (422 при
> нарушении), `digest_pin` считается детерминированно и сверяется с
> `expected_digest_pin`, проверенный манифест фиксируется в evidence ledger
> с pinned-набором `canonical_refs`.
> ✅ Канонизировано (COS-136): канонический tag-формат
> `<name>:<version>@sha256:<digest>` (без latest) + один бандл-профиль
> зафиксированы в DEPLOYMENT.md §5.5.

## ⬜ PK-C-003.5 — TRUNK DISCIPLINE, SMALL BATCHES

- [ ] Given рабочее дерево с активными воркерами, When изменения готовы, Then
  каждое изменение идёт мелким батчем в trunk (одна логическая партия = один
  commit), коммит-партии не пересекаются, мерж-заморозок на период демо нет.
- Evidence: (заполняет PO)

> Состояние: механика есть (COS-095: 12 партий, аудит-скрипт, разметка).
> Остаток: дисциплина исполнения — коммит-раунды регулярно, без копления
> недельного дерева; правило зафиксировать в worker-delegation-ops.

## ✅ PK-C-003.6 — SBOM IN BUNDLE (SYFT/GRYPE)

- [x] Given release-бандл собирается, When он проходит production freeze,
  Then в бандл входит сгенерированный SBOM (syft) и результат скана
  уязвимостей (grype), подписанный digest'ом бандла; без SBOM бандл не
  считается release-candidate.
- Evidence: Реализовано и зафиксировано в COS-138 (19.09.2026). Syft SBOM & Grype Attestation Gate в `orchestrator/cosmo/domain/sbom_scan.py`, `ledger/sbom_gate.py`, `api/routes/releases.py`. Аттестация бандла с SHA256 хешированием, запись в evidence ledger, блокировка промоушена при critical CVE. 13 тестов в `test_sbom_attestation_gate.py`.

> Состояние: ✅ Реализовано (COS-138). Аттестация SBOM (Syft) и Grype gate встроены в релизный цикл с крипто-фиксацией в evidence ledger.

---
