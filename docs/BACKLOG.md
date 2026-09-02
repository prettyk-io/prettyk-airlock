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

## ⬜ READY — SBOM & VULNERABILITY REPORT IN RELEASE BUNDLE (PK-C-003.6)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-099** | Boss | 12-16h | P2 | COS-053 + COS-096 | Автоматическая генерация и включение SBOM (SPDX/CycloneDX via syft) и vulnerability report (grype) в TransferPlan/PackageBuilder с SHA-256 digest pinning |

> **Scope:** (1) Расширение `PackageBuilder` и `DigitalReleaseEnvelope`: генерация
> машиночитаемого SBOM (формат SPDX JSON / CycloneDX) из дерева репозитория и
> артефактов сборки; (2) интеграция утилиты `syft` (CLI/docker wrapper с graceful
> fallback на internal AST/dependency parser при отсутствии binary в airgap);
> (3) формирование отчёта уязвимостей через `grype` (offline DB snapshot);
> (4) сохранение digests SBOM и security report в манифест пакета с tamper-proof
> проверкой при landing; (5) тесты: валидность схемы SBOM, фиксация digest,
> landing-верификация в airgap без сетевого egress.
>
> **Acceptance:** при сборке пакета через PackageBuilder генерируется валидный
> SBOM; манифест пакета содержит sha256 хэш SBOM-файла; PreTransferValidator
> и LandingCheckReport отвергают пакет с модифицированным SBOM; 100% offline-ready.
>
> **Out of scope:** live vulnerability enrichment из внешних NVD/OSV в runtime.

## ⬜ READY — WEB IDE SURFACE B: MONACO & WORKSPACE SHELL (COS-023 PORT)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-100** | Flash | 14-18h | P2 | COS-020 + COS-098 | Web IDE (Surface B) ядро: Tailwind v4 + Radix + Monaco editor mount в изолированном `.cosmo-ide-root`, дерево файлов репозитория, переключение поверхностей |

> **Scope:** (1) Изоляция стилей: проверка границы `.cosmo-ide-root` (Tailwind
> Preflight строго внутри, MUI CssBaseline не протекает); (2) WebIDEShell:
> дерево файлов (интеграция с `/api/v1/repos/tree` и `/api/v1/repos/file`);
> (3) Monaco Editor: подсветка `.cosmo/pipeline.yaml` и DSL-скриптов, автосохранение
> черновика в local/session, сохранение на бэкенд через PUT `/api/v1/repos/file`;
> (4) переключение между Control Station (Surface A, Meta Light) и Web IDE
> (Surface B, Dark default) по URL query param `?surface=ide` и переключателю в хедере;
> (5) unit/vitest + component smoke тесты.
>
> **Acceptance:** переход в IDE открывает тёмную тему без поломки глобальных стилей MUI;
> дерево файлов отображает реальную структуру репозитория через API; Monaco монтируется
> и редактирует файлы; vitest и tsc -b зелёные.
>
> **Out of scope:** xterm pty-сокет к живому контейнеру (следующий шаг), Git branch diff.

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

## ⬜ PK-C-003.2 — FAILOVER = PHASE 3, NOT PHASE 1

- [ ] Given базовый контур нестабилен (рестарты, race, edge-деградации),
  When планируется спринт, Then ни одна карточка failover/HA не входит в
  фазы 1-2 — только после зелёного стабильного basеline (restart-first
  доказан suite gate + runtime acceptance).
- Evidence: (заполняет PO)

> Состояние: противоядие соблюдено — restart-first (COS-063) и durability
> (COS-077/081/082/088) идут раньше failover; failover-карточек в backlog
> нет, и это правильно. Зафиксировать строкой в ARCHITECTURE-DIRECTION.

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

## ⬜ PK-C-003.4 — ONE BUNDLE, CANONICAL TAGS

- [ ] Given образ/артефакт собирается один раз, When он регистрируется, Then
  существует ровно один канонический tag-формат (version+digest, без
  latest) и один бандл-профиль поставки; расхождение версий ядро/стенд
  невозможно by construction (digest-pin в manifest).
- Evidence: (заполняет PO)

> Состояние: частично — airgap-чеклист COS-094 фиксирует «все образы
> локальны, не latest», но digest-pin — TODO при production freeze.
> Карточка: довести digest-pin + канонический tag-формат до контрактной
> строки в DEPLOYMENT/ARCHITECTURE-DIRECTION.

## ⬜ PK-C-003.5 — TRUNK DISCIPLINE, SMALL BATCHES

- [ ] Given рабочее дерево с активными воркерами, When изменения готовы, Then
  каждое изменение идёт мелким батчем в trunk (одна логическая партия = один
  commit), коммит-партии не пересекаются, мерж-заморозок на период демо нет.
- Evidence: (заполняет PO)

> Состояние: механика есть (COS-095: 12 партий, аудит-скрипт, разметка).
> Остаток: дисциплина исполнения — коммит-раунды регулярно, без копления
> недельного дерева; правило зафиксировать в worker-delegation-ops.

## ⬜ PK-C-003.6 — SBOM IN BUNDLE (SYFT/GRYPE)

- [ ] Given release-бандл собирается, When он проходит production freeze,
  Then в бандл входит сгенерированный SBOM (syft) и результат скана
  уязвимостей (grype), подписанный digest'ом бандла; без SBOM бандл не
  считается release-candidate.
- Evidence: (заполняет PO)

> Состояние: нет ни кода, ни карточки до сих пор — дифференциатор не
> реализован. Требуется карточка реализации (bundle build step + digest
> связка) — нарезка в следующем PO-цикле.

---
