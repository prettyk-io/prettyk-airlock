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

## ✅ DONE — CAPABILITY-GRANULAR GUARDS PASS 2 + DOMAIN ACCESS UNIFICATION

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---:|---|---|---|---|
| **COS-083** | Apex | 20-24h | P1 | COS-077 | ✅ DONE (транзитивно, verдикт Cosmo 23.09.2026): capability-гранулярность guard'ов (builds/deployments/projects), доменный scoping read-списков, унификация резолва домена caller'а |

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

> **Вердикт Cosmo (23.09.2026):** COS-083 фактически закрыта транзитивно в
> волнах COS-067/068/080/086/091 — capability-гранулярность write-роутов
> (`require_capability(Action.X, domain_binding="identity")` в builds/
> deployments/gates/runs/transfer/apps), доменный scoping read-списков
> (`findings.py`: не-админ → `principal.domain_id`, клиентский `domain_id`
> игнорируется) и единый резолв домена (`domain_guard.resolve_caller_domain`
> + `verify_ownership` во всех route-файлах). Инвариант-тесты
> `test_domain_resolve_invariant.py` (unified-resolve / no-raw-principal-
> domain / write-routes-guarded) + `test_deps_guard_regression.py` уже есть.
> Карточка закрыта, отдельной работы не требует.

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

#### 🟢 COS-154 · Luna · Cosmoport: repos.py честный write-path — убрать фейковый commit hash — DONE
> **Контекст (PO — Vector):** PK-C-006 (Workspace API) серверно закрыта
> волнами 1–6 (PK-C-006.18…32): чтение и запись идут честным ForgeAdapter
> write через `routes/workspace.py` (`/workspace/commits`, `/workspace/files`).
> Но legacy-поверхность `routes/repos.py` осталась за бортом:
> `POST /api/v1/repos/commit` и `/commit-and-run` возвращают фейковый
> `c-{uuid}` и **ничего не пишут в Gitea**. Их дергает Control Station
> (`frontend/src/cosmo/station/api.ts` → `saveFileAsCommit`/`commitAndRun`) —
> ложная атомарность видна пользователю станции.

> **Scope:**
> (1) `POST /api/v1/repos/commit`: писать через `build_adapter().commit_changes`
>     (тот же путь, что `/workspace/commits`, COS-124); `files` мапить в
>     create/update изменения; вернуть реальный sha вместо `c-{uuid}`.
> (2) `POST /api/v1/repos/commit-and-run`: реальный commit + существующий Run
>     (Run-логика уже честная в PG — не менять).
> (3) Маппинг ошибок через `forge_client.forge_http_error`: forge не настроен →
>     честный 503/502 (НЕ fallback на фейк); конфликт/занятый путь → 409.
> (4) Контракт COS-068 сохраняется: SCAN_START + identity binding на
>     commit-and-run (403 на чужой domain_id) не регрессирует.

> **Out of scope:** миграция станции на `/workspace/commits` (отдельная
> карточка), `routes/workspace.py` (уже честный), Web IDE клиент
> (IDE-CORE-012, Flash), миграционная цепочка (заморожена).

> **Acceptance:**
> - `POST /commit` возвращает sha вида `[0-9a-f]{40}`; файл реально в Gitea
>   (hermetic fake или live opt-in по образцу COS-096).
> - Forge не сконфигурирован → 503/502, без фейкового hash.
> - `commit-and-run`: commit честный + run создан; identity-binding 403 не
>   регрессирует.
> - Focused тесты зелёные; suite gate без регрессий; openapi без изменений
>   (route'ы и модели ответа уже описаны).

> **Отчёт обратно:** изменённые поверхности; доказательство честного sha (fake
> и/или live forge); результат suite gate; edge-случаи; блокеры.

> **Worker report (Luna, COS-154):**
> - Поверхность: `orchestrator/cosmo/api/routes/repos.py` — `POST /commit` и
>   `POST /commit-and-run` теперь пишут через `build_adapter().commit_changes`
>   (bulk Contents API, тот же контур что COS-124). `CommitFileItem={path,content}`
>   мапится в create/update через CAS-состояние (`read_file` → blob sha):
>   файл есть → update (ша), отсутствует → create. `commit_hash` = реальный
>   40-hex sha (`result["sha"]`), не `c-{uuid}`.
> - Ошибки forge → `forge_http_error` (503 not configured / 502 unreachable);
>   `GiteaConflictError` → 409. Пустой `files` → 400. Никакого fallback на фейк.
> - `commit-and-run`: identity binding (403 на чужой `domain_id`) ДО forge;
>   затем честный commit; Run в PG создаётся ТОЛЬКО после успешного коммита
>   (ложная атомарность убрана). Run-логика в PG не менялась.
> - Тесты: новый `tests/cosmo/test_repos_commit_cos154.py` (9 тестов: честный sha
>   create/update/mixed, empty→400, conflict→409, ghost→404, 503 not-configured,
>   commit-fail→Run не создаётся, forge-not-configured→Run не создаётся).
> - Прогон: COS-154 focused 9 passed; auth regression 47 passed; workspace_commits
>   35 passed; openapi clean-process build OK (route/модели не менялись).
> - НЕ закоммичено (по правилу: коммит/пуш — по явной команде PO).
>
> **Принято (Cosmo, PO, 2026-09-23):** независимый focused `test_repos_commit_cos154.py` — 9 passed; честный sha (40-hex) без фейкового fallback, forge-ошибки → 503/502/409, commit-fail → Run не создаётся.

#### 🟢 COS-155 · Luna · Cosmoport: SBOM в bundle — syft/grype-инвентарь (PK-C-003.6) — DONE
> **Контекст (PO — Vector):** PK-C-003.6 («SBOM in bundle, syft/grype») —
> единственный невыполненный пункт чеклист-требований 2.0 (PK-C-003.1…5
> закрыты). Артефактный контур уже есть: manifest digest-pin (COS-142),
> attestation bundle (COS-147), airgap-верификация (COS-148), retention
> (COS-066). Не хватает SBOM-инвентаря зависимостей и уязвимостей в бандле —
> обязательное требование для production freeze (PK-C-003.4 digest-pin стоял
> тем же флажком).

> **Scope:**
> (1) SBOM-генерация для cosmo-api: CycloneDX 1.5 (или SPDX 2.3) JSON из
>     inventories (pyproject/requirements + контейнерные слои). Где
>     syft/grype доступны (локально/в образе) — реальный скан; иначе честный
>     Python-инвентарь (`pip freeze`/importlib.metadata) с явной пометкой
>     `generator: python-inventory` (НЕ подделывать syft-подпись).
> (2) grype-визор: список CVE/severity в SBOM + summary (total/critical/high),
>     честный `unavailable` когда grype отсутствует.
> (3) Вложить SBOM в bundle manifest (COS-142) и/или attestation bundle
>     (COS-147) — единый источник истины в `evidence_ledger` (latest wins,
>     COS-152).
> (4) REST-поверхность чтения SBOM по `bundle_id` (по образцу
>     `GET /api/v1/artifacts/manifest/{bundle_id}`).

> **Out of scope:** миграционная цепочка (заморожена), runtime-сканирование
> образов в проде, Web IDE, Supply Chain attstation логика (COS-147) —
> только вложение SBOM, не её переписывание.

> **Acceptance:**
> - `GET .../sbom/{bundle_id}` отдаёт валидный CycloneDX/SPDX JSON с версией
>   формата и generator-пометкой; отсутствующий bundle → 404.
> - SBOM переживает рестарт (читается из `evidence_ledger`, не in-memory).
> - pytest: fixture-тест на структуру SBOM (schema-валидность) + live/integration
>   opt-in по образцу COS-096 (`COSMO_LIVE_GITEA`-стиль), если syft доступен.
> - suite gate без регрессий; openapi-добавления документированы.

> **Отчёт обратно:** изменённые поверхности; пример SBOM; способ генерации
> (syft vs python-inventory); результат suite gate; edge-случаи (grype
> отсутствует, пустой inventory); блокеры.

> **Worker report (Luna, COS-155):**
> - Поверхности:
>   * `orchestrator/cosmo/domain/sbom_inventory.py` — DTO: `SbomInventoryComponent`
>     (`extra="ignore"`), `SbomInventoryVulnerability`, `SbomVulnSummary`
>     (`available`/`total`/`critical`/`high`/`medium`/`low`/`reason`),
>     `SbomInventoryDocument` (CycloneDX 1.5 — camelCase-алиасы `bomFormat`/
>     `specVersion`/`serialNumber`/`vulnSummary`; `generator` + `tool_name`/
>     `tool_version`/`metadata`), `SbomInventoryRequest` (`bundle_id`/`run_id`/
>     `app_name`/`version`/`target`), `sbom_inventory_content_hash()`,
>     `normalize_severity()`, `python_inventory_components()` (`importlib.metadata`),
>     `parse_grype_report()` (severity lower(), negligible/unknown → low).
>   * `orchestrator/cosmo/ledger/sbom_inventory.py` — `generate_sbom_inventory()`
>     (syft CycloneDX если бинарник есть, иначе честный `generator: python-inventory`;
>     grype через `transfer.sbom.generate_vuln_report`, отсутствует →
>     `vuln_summary.available=false` + reason), `store_sbom_inventory()`
>     (якорь `run_id`, `commit_evidence_entry`, маркер `source=cosmo-sbom-inventory`),
>     `latest_sbom_inventory()` (latest wins + crypto-проверка `content_hash`).
>   * `orchestrator/cosmo/api/routes/artifacts.py` — `POST /api/v1/artifacts/sbom`
>     (generate + store, 422 при ghost-прогоне) и `GET /api/v1/artifacts/sbom/{bundle_id}`
>     (durable read, 404 ghost).
> - Единый источник истины — отдельная evidence-ledger-запись
>   `source=cosmo-sbom-inventory` / `sbom_type=SBOM_INVENTORY`, ключ `bundle_id`
>   (companion к manifest/attestation, не inline-переписывание COS-142/147).
>   Read-path переживает рестарт cosmo-api (in-memory реестра нет).
> - Покрытие: новый `tests/cosmo/test_sbom_inventory.py` (18 тестов: DTO
>   CycloneDX-1.5 structure + generator + python-inventory + grype-parse +
>   summary + content_hash + bundle_id-регекс; route POST/GET, 404, 422,
>   latest-wins, cross-process restart-survival через `_durable_probe`, 401).
> - Прогон: COS-155 focused 18 passed; test_artifact_manifest + test_repos_commit
>   81 passed; openapi contract + security-matrix openapi 44 passed; endpoints
>   `/api/v1/artifacts/sbom` и `/sbom/{bundle_id}` присутствуют в `/openapi.json`.
> - Edge-случаи: syft отсутствует → `generator: python-inventory` (не фейк syft);
>   grype отсутствует → `vuln_summary.available=false` + reason; ghost bundle →
>   404; ghost run → 422; пустой inventory честно пуст.
> - НЕ закоммичено (по правилу: коммит/пуш — по явной команде PO).
>
> **Принято (Cosmo, PO, 2026-09-23):** независимый focused `test_sbom_inventory.py` — 18 passed; CycloneDX 1.5 с честным `generator`-маркером (python-inventory, не фейк syft), durable read из `evidence_ledger`, PK-C-003.6 SBOM-инвентарь закрыт.

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

## ✅ DONE — OPENBAO STANDALONE HOST + МИГРАЦИЯ COSMO (PK-C-005 → COS-173)

> **Состояние:** COS-173 и COS-174 закрыты (Flash, 24.09.2026). Standalone
> `prettyk-openbao` на `pk-infra`, AppRole `cosmo-app`, миграция `secret/cosmo/*`,
> `cosmo-openbao` убран из Compose; двухслойная модель secret-refs зафиксирована.

> **Контекст (PO):** auth-линия (COS-157 → COS-158) заблокирована: issuer
> (Better Auth) обязан брать signing-ключи из боевого OpenBao. Канон
> `D:\prettyk.io\void-core\OPENBAO-PLATFORM.md`: один shared OpenBao на
> платформу, per-product инстансы запрещены. В Cosmo Compose всё ещё стоит
> `cosmo-openbao`; платформенный OpenBao не поднят (PK-C-005 был на Buddy,
> Buddy исключён — ведёт Flash). Cosmo-адаптер уже готов (COS-105
> `infra/vault.py`, AppRole client) — ждёт живой сервис. Максим: воркер один
> (Flash), идём по очереди.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---:|---|---|---|---|
| **COS-173** | Flash | 8-12h | P1 | COS-105 | ✅ DONE: платформенный OpenBao на `pk-infra`, AppRole `cosmo-app` читает/пишет `secret/cosmo/*`, `cosmo-openbao` убран из Compose |
| **COS-174** | Flash | 2-4h | P2 | COS-173 | ✅ DONE: мёртвый `openbao`-allowlist удалён; двухслойная модель secret-refs задокументирована |

#### COS-173 · Flash · Infra: OpenBao standalone host + миграция Cosmo

> **Зачем:** разблокировать auth-эпик. Issuer (COS-157) обязан брать ключи из
> OpenBao `secret/cosmo/*`, а не из `.env`/кода. Сейчас такого инстанса нет —
> есть per-product `cosmo-openbao` (запрещён каноном) и готовый, но не
> подключённый к живому сервису клиент COS-105.

> **Scope (dev-контур, поверхность Cosmo):**
> (1) Один платформенный OpenBao (image `openbao/openbao:2.2`) на общей сети
>     `pk-infra`, persistent volume; порт 8200 — только localhost (dev GUI
>     допустим), наружу не публикуется.
> (2) AppRole `cosmo-app` + policy `rw secret/cosmo/*`; role-id/secret-id
>     прошиваются как runtime-secrets (не в git).
> (3) Миграция секретов `cosmo-openbao` → `secret/cosmo/*` (в отчёте — имена,
>     не значения): PG, MinIO, Gitea, Woodpecker, jwt-keys.
> (4) Переключение Cosmo API на новый `VAULT_ADDR` + AppRole `cosmo-app` —
>     код уже есть (COS-105), правится только конфиг/Compose/env.
> (5) `cosmo-openbao` удаляется из Cosmo Compose; Compose/startup остаются
>     здоровыми.
> (6) Live-доказательство: vault-клиент Cosmo читает/пишет `secret/cosmo/*`
>     через AppRole (не `COSMO_ENV=test` fallback) — 4 live-теста COS-105,
>     что раньше честно скипались, теперь проходят.

> **Out of scope:** secops-сторона (`prettyk-openbao` → `secret/secops/*`,
> зона Keeper — только координация); AppRole `hub-app` (Arbiter) и
> `platform-admin` + recovery snapshot / production hardening (platform/Buddy,
> будущее); Better Auth issuer (COS-157); FE login (COS-158).

> **Acceptance:**
> - Один OpenBao на `pk-infra`; `cosmo-net` подключена как external network.
> - `cosmo-app` аутентифицируется и читает/пишет `secret/cosmo/*` live.
> - Секреты перенесены; `cosmo-openbao` из Compose удалён; Cosmo стартует,
>   suite gate без регрессий.
> - Root token в рантайме не используется; secret-id не в git.
> - Порт 8200 не публикуется за пределы localhost.

> **Отчёт обратно:** топология (сеть/контейнер/volume); применённые AppRole и
> policy; список перенесённых секретов (имена); доказательство live I/O через
> AppRole; негатив (неверный secret-id → отказ, истёкший токен → re-auth);
> результат suite gate; блокеры.

> **Worker report (Flash, COS-173 ✅):** standalone `prettyk-openbao` на `pk-infra`
> (image `openbao/openbao:2.2` → 2.2.2, порт `127.0.0.1:8200`, volume
> `prettyk_openbao`), AppRole `cosmo-app` + policy `rw secret/cosmo/*`, 5 секретов
> `secret/cosmo/*` (PG/MinIO/Gitea/Woodpecker/jwt-keys); `services/.env`/
> `.env.example` обновлены; `cosmo-openbao` убран из Compose + контейнер удалён.
> Live-доказательство AppRole внутри `cosmo-api` PASS; `test_vault.py` 16 passed /
> 4 skipped (live 20/20). Root token — только bootstrap, не рантайм.

#### COS-174 · Flash · Infra: secret-ref hygiene — мёртвый allowlist + двухслойная модель

> **Зачем:** хвосты COS-173. (1) после удаления per-product `cosmo-openbao`
> путь `secret/cosmo/openbao` в allowlist `_KNOWN_VAULT_PATHS`
> (`domain/vault_ref.py`) стал мёртвым — canon-list не должен врать. (2) в
> моделях живёт второй слой refs (`forge/credentials`, `registry/credentials`,
> `prettyk/credentials` — DB-default'ы `forge_auth_ref`/`registry_auth_ref`/
> `prettyk_auth_ref`) — его надо сверить с runtime-токенами и задокументировать,
> чтобы два слоя не спутали при следующей миграции.

> **Scope:**
> (1) Убрать `secret/cosmo/openbao` из `_KNOWN_VAULT_PATHS` (и из `secret_ref.py`,
>     если там дублируется); обновить `test_vault_secret_ref.py` / соседние тесты,
>     перечисляющие known-paths.
> (2) Сверить второй слой refs (`forge/credentials`, `registry/credentials`,
>     `prettyk/credentials` в `models_lr.py`, `instance_config.py`, alembic,
>     k8s-манифестах) — подтвердить, что это осознанный отдельный слой внешних
>     интеграций (не runtime-токены `database`/`forge/gitea`/`ci/woodpecker`),
>     и зафиксировать двухслойную модель в docstring `vault_ref.py` (одно место).
> (3) Grep-чистота: после чистки `_KNOWN_VAULT_PATHS` содержит только живые пути.

> **Out of scope:** заведение новых секретов/refs; миграция secops/hub (Keeper/
> Arbiter); изменение verify-логики secret_ref; FE; Better Auth issuer (COS-157).

> **Acceptance:**
> - `_KNOWN_VAULT_PATHS` не содержит `secret/cosmo/openbao`; тесты зелёные.
> - Двухслойная модель secret-refs (runtime-токены vs external-integration creds)
>   зафиксирована в одном месте; расхождений код↔doc нет.
> - Suite gate без регрессий (`test_vault_secret_ref` + security-matrix).

> **Отчёт обратно:** что удалено из allowlist; результат сверки двух слоёв
> (совпало/дрифт, с фиксом или без); где зафиксирована модель; suite gate; блокеры.

> **Worker report (Flash, COS-174 ✅):** `secret/cosmo/openbao` удалён из
> `_KNOWN_VAULT_PATHS` (`domain/vault_ref.py`), grep `cosmo/openbao` → 0.
> Двухслойная модель (Layer 1 runtime-токены `database`/`forge/gitea`/
> `ci/woodpecker`/`minio`/`pipeline`/`jwt-keys` через AppRole; Layer 2 внешние
> креды `forge/credentials`/`registry/credentials`/`prettyk/credentials` — только
> reference-строки) зафиксирована в docstring `vault_ref.py`. Сверка: дрифта нет,
> не хватало только документации. Тесты `test_vault_secret_ref.py` +
> `test_security_perimeter_negative.py` → 68 passed.

---

## ⬜ READY — COSMO PRODUCTION IDENTITY (БОЕВОЙ AUTH / SSO)

> **Контекст (PO):** auth на бэке сейчас — только формат-чек JWT (`ey...` +
> payload) без проверки подписи (`deps.py::get_current_principal`, COS-085
> закрыл только opaque). Логина нет, `frontend/src/auth/` не существует,
> фронт шлёт dev-stub `operator:admin`. Боевой identity заявлен в
> STACK/ARCHITECTURE (Better Auth + OpenBao; Keycloak/Blitz OIDC — legacy),
> НЕ реализован. Правило Максима: только боевой путь, никаких dev-token/
> quick-fix. Ниже — эпик целиком; диспатч идёт по готовности зависимостей.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-156** | Luna | 8-12h | P1 | — | ✅ DONE: крипто-верификация JWT в `get_current_principal` (RS256/ES256, fail-closed, identity из verified claims) |
| **COS-157** | Flash | 12-16h | P1 | COS-173 (OpenBao) | ✅ DONE: Python-native issuer — выдача RS256 JWT (login) + JWKS endpoint |
| **COS-158** | Flash | 6-10h | P1 | COS-156, COS-157 | FE login surface + session — убрать dev-stub `operator:admin` |
| **COS-159** | Luna | 2-3h | P1 | COS-156 | ✅ DONE: регенерация OpenAPI — 6 spoof-заголовков убраны, negative-гард добавлен |
| **COS-160** | Luna | 2-3h | P1 | COS-156 | ✅ DONE: live-тесты forge/Gitea минтит подписанный RS256 (mint_rs256) |

#### COS-156 · Luna · Cosmoport: крипто-верификация JWT вместо формат-чека

> **Контекст:** `get_current_principal` принимает любой JWT-форм токен
> (`ey...payload...`) и читает claims БЕЗ проверки подписи. Значит склеенный
> вручную `ey...` с `is_admin:true` проходит как system admin. COS-085 закрыл
> opaque-дыру, но крипто-дыра подписи осталась. Это ядро боевого identity:
> проверяющая сторона (issuer — COS-157, поднимется после OpenBao PK-C-005).

> **Scope:**
> (1) Верифицировать подпись через конфигурируемый источник ключей — JWKS
>     URL и/или публичный ключ (env/платформенный OpenBao `secret/cosmo/*`):
>     RS256 (+ ES256 опционально). Проверки: `exp`, `nbf`, `iss` (allowlist),
>     `aud` (если задан). Невалидная подпись / истёкший / неверный `iss` → 401
>     (тот же detail-контракт, что COS-085).
> (2) Claims читаются ТОЛЬКО из верифицированного token. Формат `ey...` больше
>     не является достаточным признаком аутентификации — только подпись.
> (3) Fail-closed: источник ключей не сконфигурирован → 401 (или явная ошибка
>     конфигурации), НЕ дефолтный success. Никакого dev-allow.
> (4) Backward-compat для suite gate без внешнего issuer: тестовый keypair в
>     фикстурах (реальный RS256, не фейк) + явный dev-ключ через env для
>     ручного/CI прогона — документирован как dev-контур, не боевой.

> **Out of scope:** Better Auth issuer (COS-157), FE login (COS-158),
> перестановка платформенного OpenBao (PK-C-005), session/refresh (будущее),
> миграционная цепочка (заморожена).

> **Acceptance:**
> - Токен с валидной подписью (тестовый RS256) + claims → principal собран
>   корректно (sub/email/roles/is_admin только из верифицированных claims).
> - Подделанная подпись → 401; истёкший `exp` → 401; неверный `iss` → 401;
>   unsigned/opaque → 401 (COS-085 не регрессирует).
> - `is_system_admin`/`admin_sec` НЕ выводятся из неверифицированного token.
> - auth-regression suite зелёный; suite gate без регрессий; openapi без
>   изменений (auth-слой, не новый route).

> **Отчёт обратно:** изменённые поверхности; пример верификации (позитив +
> негатив); источник ключей (JWKS/ключ) и его конфигурация; результат
> auth-regression и suite gate; edge-случаи (нет iss в allowlist, мalformed
> JWKS). Блокеры.

> Состояние: ✅ Реализовано (Luna, 23.09.2026). Не закоммичено (worker-канон).
>
> **Worker report (Luna):**
> - **Поверхности:** новый `orchestrator/cosmo/security/jwt_verifier.py`
>   (`verify_jwt`, `JwtConfig`, `load_jwt_config`, `JwtVerificationError`,
>   `default_vault_reader`); `api/deps.py::get_current_principal` переписан —
>   верификация подписи обязательна, identity ТОЛЬКО из verified claims;
>   header-injection identity (`X-User-Id/Roles`, `X-Cosmo-Principal/Roles/
>   Scopes`, `X-User-Email`) убрана из сигнатуры/логики. `requirements.txt`:
>   +`cryptography>=42`. Тесты: новый `test_jwt_verification.py` (22),
>   фикстура `_jwt_testkey.py` (реальный RSA-2048 keypair), positive-тесты
>   `test_sanitary_rbac.py` и `test_surface_auth_regression.py` переведены
>   с fake `HS256`/header-injection на подписанный RS256.
> - **Источник ключей:** приоритет JWKS URL (`COSMO_JWT_JWKS_URL`) → static
>   PEM (`COSMO_JWT_PUBLIC_KEY`, мульти-ключ) → OpenBao `secret/cosmo/jwt-keys`
>   (best-effort, только вне test) → dev-ключ `COSMO_JWT_DEV_PUBLIC_KEY`
>   (только `COSMO_ENV=test`, документирован как dev). Алгоритмы: RS256 всегда,
>   ES256 опционально (`COSMO_JWT_ALGORITHMS`); `none`/HS* запрещены.
> - **Fail-closed:** нет источника ключей → `JwtVerificationError` → 401.
> - **Верификация (позитив/негатив):** валидный RS256 → claims (sub/email/roles/
>   scopes/is_admin); forged sig / чужой ключ / `alg=none` / HS256 / expired /
>   nbf-future / iss не в allowlist / aud mismatch / opaque / malformed → 401.
> - **Прогоны:** focused 205 passed (sanitary_rbac + jwt_verification +
>   surface_auth + deps_guard + sod/transfer + security_perimeter_negative +
>   transfer_security_matrix + openapi_contract); полный cosmo suite
>   **3385 passed, 17 skipped** (skip = live-gitea opt-in, флага нет).
> - **OpenAPI:** новых routes/schemas нет; `/openapi.json` собирается (forward-ref
>   регрессия зелёная). Шесть spoof-заголовков (`X-User-Id/Roles`,
>   `X-Cosmo-Principal/Roles/Scopes`, `X-User-Email`) убраны из
>   `get_current_principal` — это осознанное изменение контракта (удаление
>   spoof-вектора); закоммиченные `docs/cosmo-openapi.{json,yaml}` теперь
>   перечисляют эти 6 устаревших header-параметров и требуют регенерации на
>   сборке ПО.
> - **Edge/блокеры:** `iss` без allowlist не проверяется (allowlist опционален
>   по scope). Better Auth issuer — COS-157.

#### COS-157 · Flash · Cosmoport: Better Auth issuer + OpenBao — выдача RS256 JWT + JWKS

> **Контекст:** verifier (COS-156) готов и fail-closed, но выпускать токены
> некому — логина нет, `frontend/src/auth/` не существует, фронт шлёт dev-stub
> `operator:admin`. Нужён боевой issuer: проверяющая сторона (COS-156) ждёт
> реальные подписанные токены. Канон STACK/ARCHITECTURE: Better Auth + OpenBao.

> **Scope:**
> (1) Мятеж RS256 JWT (библиотека на `cryptography>=42`, уже в requirements):
>     claims `sub`/`email`/`roles`/`scopes`/`is_admin`, `iss` (allowlist),
>     `exp`, `nbf`, `aud`. Приватный signing-ключ читается из OpenBao
>     `secret/cosmo/jwt-keys` (`rsa_private`) через AppRole `cosmo-app`
>     (клиент COS-105) — НЕ в коде/`.env`/git.
> (2) JWKS endpoint (RFC 7517), отдающий публичный ключ (`rsa_public`); verifier
>     COS-156 через `COSMO_JWT_JWKS_URL` сквозно верифицирует выпущенный токен.
> (3) Боевой логин-путь (Better Auth): реальная проверка креденшелов, возврат
>     подписанного токена; не dev-stub, не root token в рантайме.
> (4) Тесты: сквозной mint → JWKS → verify → principal (claims валидны),
>     негатив (неверные креды → 401; нет ключа → явная ошибка, не дефолт-success).

> **Решение-стоп (если расходится — остановись и согласуй с PO до кода):**
> - **Топология:** default — Python-native issuer внутри `cosmo-api` (монорепо
>   Python, verifier-плюмбинг уже есть, новый рантайм не заводим). Если Better
>   Auth обязан быть отдельным TS/Node сервисом — это новый сервис/рантайм, стоп.
> - **Креденшел-источник:** default — self-managed (email/password) через Better
>   Auth; внешний OIDC-контракт (банк) — не в scope (DEPLOYMENT §11.3 «при
>   необходимости», будущее).

> **Out of scope:** FE login surface + session (COS-158); session/refresh/rotation
> токенов (будущее); внешний OIDC/Blitz SSO; миграционная цепочка; перестановка
> OpenBao (COS-173); изменение verifier (COS-156 закрыт).

> **Acceptance:**
> - По логину (боевой креденшел) мётится RS256 JWT с верными claims; `iss` в
>   allowlist; подпись валидна.
> - JWKS endpoint отдаёт ключ; verifier COS-156 через `COSMO_JWT_JWKS_URL`
>   собирает principal из выпущенного токена (сквозной прогон, не unit-mock).
> - Приватный ключ только из OpenBao `secret/cosmo/jwt-keys`; в git/`.env` его нет.
> - Negative: неверный пароль/креды → 401; ключ отсутствует → явная ошибка.
> - auth-regression + jwt_verification + suite gate зелёные; openapi задокументирован
>   (login/JWKS route).

> **Отчёт обратно:** поверхности; пример mint→JWKS→verify→principal; как читается
> ключ из OpenBao (AppRole, не root); логин-провайдер и его конфиг; негативы;
> suite gate; блокеры. Отметь, если топология/креденшел-источник разошлись с
> default — отдельно, до сдачи.

> **Решения PO (согласованы до кода, 24.09.2026):**
> - **Креденшел-источник = A: OpenBao-seeded admin** — self-managed
>   email/password, пароль хранится `secret/cosmo/auth` как hashed (PBKDF2),
>   а не внешний OIDC/Blitz. Внешний OIDC — вне scope.
> - **Топология = Python-native issuer внутри `cosmo-api`** — без отдельного
>   TS/Node Better Auth сервиса/рантайма.
> - **Crypto:** RS256 через `cryptography>=42`; PBKDF2-HMAC-SHA256 через stdlib
>   `hashlib`; формат хэша `pbkdf2_sha256$<iterations>$<salt_b64url>$<hash_b64url>`
>   (self-describing, без новой зависимости).

> Состояние: ✅ Реализовано (Flash, 24.09.2026). Не закоммичено (worker-канон).
>
> **Worker report (Flash):**
> - **Поверхности (новые):** `orchestrator/cosmo/security/jwt_issuer.py`
>   (`IssuerConfig` из `secret/cosmo/jwt-keys`, `mint_access_token` RS256 с
>   claims sub/email/roles/scopes/is_admin/iss/iat/nbf/exp/aud, `build_jwks`
>   RFC 7517 (n/e/kid), `derive_kid` SHA-256 над SPKI);
>   `orchestrator/cosmo/security/credentials.py`
>   (`hash_password`/`verify_password`, PBKDF2-HMAC-SHA256, 600k default);
>   `orchestrator/cosmo/api/routes/auth.py` (`POST /api/v1/auth/login` — проверка
>   креденшела → подписанный токен, 401 при неверных креденшелах, 503 при
>   отсутствии ключа/`IssuerConfigError`/`VaultLookupError`; `GET
>   /.well-known/jwks.json`); `api/main.py` подключён `auth_router`.
> - **Ключ:** приватный signing-ключ читается из OpenBao `secret/cosmo/jwt-keys`
>   (`rsa_private`) через AppRole `cosmo-app` (клиент COS-105) — не в коде/.env.
> - **Негативы (тест-покрытие):** неверный пароль → 401; ключ отсутствует → 503
>   (fail-closed, не default-success).
> - **Прогоны:** новые тесты `test_jwt_issuer.py` + `test_credentials.py` +
>   `test_auth_login.py` → 20 passed; auth-regression + openapi
>   (`test_jwt_verification`, `sanitary_rbac`, `surface_auth_regression`,
>   `openapi_contract`, `deps_guard_regression`) → 152 passed / 2 pre-existing
>   warnings. Live `app.openapi()` → 153 paths / 205 schemas, login+JWKS на месте.
> - **OpenAPI:** `docs/cosmo-openapi.{json,yaml}` регенерированы из `app.openapi()`
>   (json==yaml); `LoginResponse` allowlist'нут в `test_no_raw_token_in_schemas`
>   — login легитимно ВЫДАЁТ `access_token` (продукт выпуска, не утечка хранимого
>   секрета).
> - **Хвосты COS-173 (зачищены):** `runtime-gate.ps1` `$FullExtra` без
>   `cosmo-openbao`; `rotate-secrets.ps1` подсказка standalone OpenBao;
>   `SECURITY_MAINTENANCE.md` docker-проверка `prettyk-openbao`; заголовок
>   `docker-compose.yml` (строка 8200/cosmo-openbao) убран; `MAP.md`/
>   `DEPLOYMENT.md` строки `cosmo-openbao` → `prettyk-openbao` / убраны.
> - **Блокеров нет.** FE login surface + session — COS-158 (следующая).

---

### COS-159 / COS-160 — follow-up COS-156 (Luna) · ✅ DONE

> **Зачем:** после COS-156 (удаление spoof-заголовков из `get_current_principal`)
> закоммиченная спека и два live-теста остались честными только на словах.
> Закрываем хвосты: регенерация OpenAPI + перевод live-минтинга с `alg:none`
> на подписанный RS256.

> **COS-159 — OpenAPI-регенерация + negative-гард:**
> - `docs/cosmo-openapi.{json,yaml}` регенерированы в чистом процессе из
>   живого `app.openapi()` (`from orchestrator.cosmo.api.main import app`).
>   Пути/схемы: **141/187 → 143/192** (рост — COS-154/155 endpoints/schemas,
>   не новая auth-поверхность). `json == yaml == live` (семантическое равенство).
> - 6 spoof-заголовков (`X-Cosmo-Principal/Roles/Scopes`, `X-User-Id/Roles/Email`)
>   исчезли из `parameters` — grep по обоим файлам чист (доказательство ниже).
>   Остались только легитимные `Authorization`, `session_token`, `X-Cosmo-Zone`,
>   `X-Cosmo-Domain`.
> - В `test_openapi_contract.py` добавлен negative-гард
>   `test_no_spoofable_identity_headers` (образец — `test_session_token_is_cookie_only`):
>   падает при возврате любого из 6 имён в parameters.

> **COS-160 — live-тесты минтит подписанный RS256:**
> - `test_forge_gitea_live.py::_mint_jwt` → `mint_rs256()` из `_jwt_testkey`
>   (реальный RSA-2048, не фейк). Unused-импорты `base64/hashlib/hmac/json`
>   удалены. Docstring обновлён.
> - `test_workspace_commit.py::TestLiveCommit::live_setup` → `mint_rs256()`.
>   Unused-импорт `base64` удалён.
> - Ни один live-тест больше не содержит `alg:none`/unsigned-mint.
> - Unit-позитив/негатив уже закрыты `test_jwt_verification.py`
>   (`test_valid_rs256_returns_claims`, `test_alg_none_rejected`); live-тесты —
>   opt-in (`COSMO_LIVE_GITEA` / `COSMO_LIVE_COMMIT`), в прогоне честно skip.

> **Прогоны:** focused 120 passed (openapi_contract + transfer_security_matrix +
> jwt_verification + sanitary_rbac + surface_auth). Suite gate: **3386 passed /
> 0 failed / 17 skipped** (337s; +1 vs基线 из-за нового гарда). Не закоммичено.

> **Блокеры:** live-прогон обоих live-тестов требует, чтобы живой ПУ был собран
> с COS-156 и имел конфигурацию ключей (`COSMO_JWT_PUBLIC_KEY`/JWKS с тем же
> публичным ключом, что в `_jwt_testkey.TEST_PUBLIC_KEY_PEM`) — иначе честный 401.
> Подъём gitea-контура и конфигурация боевых ключей — вне scope (COS-157/ПО).
>
> **Принято (Cosmo, PO, 2026-09-23):** независимая проверка — grep по
> `docs/cosmo-openapi.*` на 6 spoof-заголовков = 0 вхождений; negative-гард
> `test_no_spoofable_identity_headers` честный (падает при возврате любого из
> 6 имён); оба live-теста минтит `mint_rs256` из `_jwt_testkey` (реальный
> RSA-2048), `alg:none` в них отсутствует (forge-вектор остаётся только в
> `test_jwt_verification.py` как негатив). Suite gate 3386/0/17 (+1 гард).
> Серия COS-156→159→160 (боевой identity + честная спека) закрыта.

---

> **Принято (Cosmo, PO, 2026-09-23):** независимый focused run
> (`test_jwt_verification` + `test_sanitary_rbac` + `test_surface_auth_regression`)
> — **80 passed**. Код честный: fail-closed (нет ключей → 401), `alg=none`/HS*
> запрещены, identity только из verified claims, spoof-заголовки
> `X-User-Id/Roles`, `X-Cosmo-Principal/Roles/Scopes`, `X-User-Email` убраны
> из `get_current_principal` (остались только `X-Cosmo-Zone`/`X-Cosmo-Domain`
> как контекст, не identity). Полный suite gate по отчёту Luna 3385/0/17.
>
> **Follow-up (не закрывает COS-156, фиксируется отдельно):**
> (1) регенерация `docs/cosmo-openapi.{json,yaml}` — схема всё ещё перечисляет
> 6 устаревших identity-заголовков (дрифт контракта до регенерации);
> (2) `test_forge_gitea_live.py` и `test_workspace_commit.py` (`TestLiveCommit`)
> минтит `alg:none` JWT (opt-in live-контур) — перевести на подписанный
> dev-ключ при COS-157 (иначе живой прогон упадёт без этих ключей).

#### COS-159 · Luna · Cosmoport: регенерация OpenAPI — убрать 6 устаревших spoof-заголовков

> **Контекст (PO/фиксация follow-up COS-156):** после COS-156
> `get_current_principal` больше не читает identity из заголовков-инъекций,
> но закоммиченные `docs/cosmo-openapi.{json,yaml}` всё ещё перечисляют эти
> заголовки как принимаемые параметры (`X-Cosmo-Principal`, `X-Cosmo-Roles`,
> `X-Cosmo-Scopes`, `X-User-Id`, `X-User-Roles`, `X-User-Email`) в сотнях
> мест → спеку дрifтует относительно живого контракта. Спека должна быть
> честной: что не принимается на живой границе — не должно быть в спеке.

> **Scope:**
> (1) Регенерировать `docs/cosmo-openapi.json` и `cosmo-openapi.yaml` из
>     живого `app.openapi()` в чистом процессе
>     (`from orchestrator.cosmo.api.main import app`, cwd=repo_root) —
>     json == yaml == live (`/openapi.json`).
> (2) Убедиться, что 6 spoof-заголовков исчезли из parameters/headers спеки.
> (3) Добавить negative-гард в `test_openapi_contract.py` (по образцу
>     `test_session_token_is_cookie_only`): перечисленные 6 header-имён
>     НЕ встречаются в parameters спеке — чтобы дрифт не вернулся на
>     следующей регенерации.

> **Out of scope:** Better Auth issuer (COS-157), FE login (COS-158),
> изменение самих маршрутов/схем, session/refresh.

> **Acceptance:**
> - `docs/cosmo-openapi.{json,yaml}` регенерированы; json == yaml == live.
> - Grep по `docs/cosmo-openapi.*` не находит ни одного из 6 spoof-заголовков.
> - `test_openapi_contract.py` зелёный; новый negative-гард падает, если
>   заголовки вернутся.
> - Suite gate без регрессий (openapi contract + security-matrix openapi).

> **Отчёт обратно:** число путей/схем до/после регенерации; доказательство
> исчезновения (grep-diff); результат контракт-гварда; блокеры.

#### COS-160 · Luna · Cosmoport: live-тесты forge/Gitea — `alg:none` → подписанный dev-ключ

> **Контекст (PO/фиксация follow-up COS-156):** два opt-in live-теста
> (`test_forge_gitea_live.py`, `test_workspace_commit.py::TestLiveCommit`)
> минтит `alg:none` JWT (`ey…h.p.sig` — унаследованный COS-085 pattern).
> После COS-156 `verify_jwt` отклоняет `alg:none` → живой прогон (при
> поднятом gitea/forge-контуре) упадёт. Оба теста вне suite gate
> (skip без live-флага), но обязаны быть честными: боевой путь — подписанный
> токен, не forge-вектор.

> **Scope:**
> (1) Заменить `alg:none` mint в обоих тестах на подписанный RS256
>     dev-токен через фикстуру `_jwt_testkey.py` (реальный RSA-2048 keypair,
>     не фейк) или общий helper.
> (2) Подписанный токен проходит `verify_jwt` при `COSMO_JWT_DEV_PUBLIC_KEY`/
>     `COSMO_ENV=test`; негатив `alg:none` уже покрыт `test_jwt_verification`.
> (3) Тесты остаются opt-in (skip без live-флага); suite gate не трогается.

> **Out of scope:** подъём/починка самого gitea-контура, Better Auth issuer
> (COS-157), FE login (COS-158).

> **Acceptance:**
> - Ни один из двух тестов больше не минтит `alg:none`.
> - Подписанный RS256-токен верифицируется (позитив); `alg:none` отклонён
>   (негатив) — оба на unit-уровне зелёные.
> - Живой прогон (если gitea-контур поднят) зелёный с dev-ключом; иначе
>   честный skip (как сейчас).
> - Suite gate без регрессий.

> **Отчёт обратно:** что заменено и каким helper'ом минтится токен;
> результат unit-прогона и live-прогона (или skip); блокеры.

---

## ✅ DONE — BUILD + DEPLOY (GITEA + WOODPECKER) · ЗАХОД 1

> **Директив Максима:** для Airlock топим build + deploy основным стеком (gitea + woodpecker).
> **Рубеж захода:** Build → Registry (docker build + push в OCI с canonical digest tag,
> Evidence) + status deploy (materialize/promotion — следующий заход).
> **План:** `docs/research/2026-09-23-build-deploy-gitea-woodpecker.md`.
> **Тестовый target:** отдельное несложное приложение (авторизация + функционал) —
> пишет Luna, оно становится целью build+deploy.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-161** | Luna | 8-12h | P1 | — | ✅ Тестовое приложение: авторизация + несложный функционал, deployable docker-сервис |
| **COS-162** | Luna | 12-16h | P1 | COS-161, COS-142 | ✅ Build first-class: канонический docker build + push в OCI с digest-тагом, Evidence push |
| **COS-163** | Luna | 8-12h | P1 | COS-162 | ✅ Build→Registry wiring: durable digest/manifest/SBOM в PG + Evidence, GAP-режим |

> **Владельцы захода 1:** в распоряжении только Luna — все три карточки ведёт она.
> Порядок: COS-161 → COS-162 → COS-163 (последовательно, один worker-поток).

#### COS-161 · Luna · Тестовое приложение (target build+deploy)

> **Зачем:** нужен минимальный реальный объект, на котором проверяем build + deploy
> конвейер (gitea → woodpecker → registry). Отдельное приложение вне core Cosmoport —
> авторизация плюс один несложный фиче-набор.

> **Outcome:** deployable docker-сервис (FastAPI/Python, стек как у Cosmoport):
> login/register + защищённые эндпоинты (JWT), один CRUD-набор (todo/notes/любой),
> Dockerfile multi-stage, EXPOSE порт, healthcheck, конфиг через env.

> **Acceptance:**
> - `docker build` проходит; контейнер стартует; healthcheck OK.
> - Auth: логин → токен → доступ к защищённому эндпоинту; без/с невалидным токеном → 401.
> - CRUD работает end-to-end.
> - Нет жёстких host-paths; все зависимости в Dockerfile — готово к Woodpecker-сборке.
> - README: как собрать локально и запустить.

> **Out of scope:** интеграция с Cosmoport, registry push (COS-162/163), SBOM/gates.

#### COS-162 · Luna · Build first-class — docker build + push в OCI

> **Зачем:** закрыть гэп №1 — `generate_pipeline_yaml` умеет только generic container
> steps. Нужен канонический build-шаг: собрать образ из repo-контекста, пушить в OCI
> registry зоны с deterministic digest-тагом `<name>:<version>@sha256:<digest>`,
> вернуть digest в executor, Evidence хеширует push.

> **Outcome:** Woodpecker-пайплайн получает build-шаг типа `docker_build` (image build +
> push поверх текущих generic steps); digest возвращается в executor и фиксируется.

> **Acceptance:**
> - Приложение COS-161 собирается в образ и пушится в registry зоны ЗР.
> - Canonical tag соответствует канону COS-142 (`slug/semver/sha256`, no-latest).
> - Digest зафиксирован durable (PG + Evidence), переживает рестарт.
> - Build-шаг fail → честный статус пайплайна (не молчаливый success).

> **Out of scope:** durable-схема artifact digest в PG (COS-163), materialize deploy.

> **Acceptance (PO, 23 сентября 2026):** COS-161 и COS-162 приняты.
>
> **COS-161 ✅ полностью** — `apps/cosmo-testapp/` live-верифицирован: build OK
> (digest `sha256:64f724de…`), контейнер healthy, auth +/-, CRUD e2e. Зависимость
> `cryptography>=42` зафиксирована durable в `requirements.txt` и
> `apps/cosmo-testapp/requirements.txt` — env-несоответствие COS-156 снято, не код-долг.
>
> **COS-162 ✅ с follow-up** — механика build+push корректна и покрыта (13 passed,
> suite 3399/0/17): `DockerBuildSpec` (slug `NAME_RE` + semver `SEMVER_RE`, latest
> запрещён), `canonical_ref()` → `<name>:<version>@sha256:<digest>`,
> `render_docker_build_commands` (`build --iidfile` → `push @$DIGEST`),
> `_docker_build_step` (`docker:24-cli` + docker.sock RW),
> `record_registry_push` (durable Evidence, `type='decision'`, `source='cosmo-registry-audit'`).
> Канонический tag соответствует COS-142.
>
> **Follow-up (не закрывает COS-162, gate в COS-163):**
> - Живой push заблокирован — контейнер `cosmo-registry-zr` (distribution,
>   `docker-compose.registry.yml`, 5100:5000) не поднят. Luna честно зафиксировала
>   блокер, fake не выдала. Live-push верификация переносится в COS-163 (wiring),
>   где registry поднимется и поток build→push→durable metadata сведётся end-to-end.
> - **Позднее (COS-166):** `render_docker_build_commands` слал `docker push
>   @$DIGEST` с config-digest из `--iidfile` — неработоспособно и расходится с
>   manifest-digest registry. Исправлено на push-по-тегу + съём manifest-digest;
>   детали и live-доказательство — в COS-166 acceptance.

#### COS-163 · Luna · Build→Registry wiring — durable artifact metadata + GAP

> **Зачем:** закрыть гэп №2 — собранный образ должен быть зафиксирован durable:
> digest + manifest + SBOM в PostgreSQL + Evidence Ledger; batch/pipeline loop
> замыкается на registry; GAP-режим enforce (push только в локальный registry).

> **Outcome:** после build artifact metadata durable в PG + Evidence; GAP (внешний
> registry) → честная ошибка; metadata переживает рестарт (не in-memory).

> **Acceptance:**
> - После сборки digest/manifest/SBOM читаются из durable-источника после рестарта.
> - Push во внешний registry в GAP-режиме заблокирован с честной ошибкой.
> - Batch loop закрыт: build → artifact metadata, не «упало в никуда».

> **Out of scope:** materialize deploy (следующий заход), promotion ЗР→ЗТ→ЗПЭ.

> **Acceptance (PO, 23 сентября 2026):** COS-163 принят. Заход 1 (Build → Registry)
> закрыт полностью — все три карточки done.
>
> **Что верифицировано live:** `cosmo-registry-zr` поднят (`docker-compose.registry.yml`,
> 5100:5000, `GET /v2/ → 200`); образ COS-161 реально запушен
> `localhost:5100/cosmoport/zr/cosmo-testapp:0.1.0`, digest
> `sha256:59903d44…`, `canonical_ref cosmo-testapp:0.1.0@sha256:…`, tags `['0.1.0']`
> без `latest`, `resolve_digest`/`check_artifact` подтверждены. Durable-запись строго
> через канонический `commit_evidence_entry` (append→seal→commit→publish_head),
> чтение только из `evidence_ledger` (in-memory реестра нет); restart-survival доказан
> свежим subprocess-процессом (`TestRestartSurvival`), тампер `record_hash` → честное `None`.
> GAP: `docker.io/ghcr.io/quay.io` → `CODE_EXTERNAL_REGISTRY_BLOCKED`,
> `nexus/t1_sfera` → `CODE_PROVIDER_NOT_ALLOWED`, delete → `CODE_OPERATION_NOT_ALLOWED`;
> `OciRegistry.push_artifact` и `_docker_build_step` гейтятся до сетевого вызова.
> Gate: focused 29 passed, suite 3429/0/16.
>
> **Follow-up (не закрывает заход, мостик в заход 2):**
> - Авто-возврат digest из woodpecker-шага в PG не материализован — шаг печатает
>   `echo image:version@$DIGEST`, а runtime-hook (ловить output → `record_artifact_record`)
>   — это сквозная CI-проводка следующего захода (materialize deploy). Сейчас закрыт
>   контракт «единственный durable write + read-through», не сквозной CI-провод.
> - Реальная генерация SBOM поверх образа (trivy/cyclonedx) — вне scope пакета.
> - Registry теперь поднят постоянно → live smoke `test_local_oci_smoke` исполняется
>   в suite gate (не skip); при отсутствии интернета для `docker pull alpine` возможна
>   флейка, образ уже кэширован.

---

## ✅ DONE — DEPLOY MATERIALIZE (ЗАХОД 2)

> **Рубеж захода:** Э3 materialize deploy + сквозная CI-проводка авто-digest.
> Э4 (release lifecycle DOCKER_AUDIT) и Э5 (promotion ЗР→ЗТ→ЗПЭ) — следующие пакеты.
> **Вход:** заход 1 закрыт (build → registry, durable artifact metadata, GAP).
> **Владелец:** Luna (в распоряжении только Luna — последовательно).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-164** | Luna | 6-8h | P1 | COS-163 | ✅ DONE — Runtime hook: авто-возврат digest из woodpecker-шага → record_artifact_record |
| **COS-165** | Luna | 12-16h | P1 | COS-164 | ✅ DONE — Deploy materialize: deploy_release → pull по digest + run в контуре, честный статус |

#### COS-164 · Luna · Runtime hook — авто-возврат digest (сквозная CI-проводка)

> **Зачем:** закрыть хвост захода 1 — woodpecker-шаг печатает `echo image:version@$DIGEST`,
> но никто не ловит output и не зовёт `record_artifact_record`. Нужен runtime-hook в
> executor: поймать digest из вывода docker_build-шага и durable-записать ArtifactRecord.

> **Outcome:** executor ловит digest из вывода docker_build-шага (канонический маркер),
> вызывает `record_artifact_record`; digest автоматически durable в PG + Evidence.

> **Acceptance:**
> - После прогона пайплайна с docker_build-шагом digest автоматически записан в
>   ArtifactRecord (не руками).
> - Пойманный digest → `canonical_ref`, связка с `run_id`.
> - Парсинг надёжен (маркер каноничен); битый/пустой output → честная ошибка/None,
>   не фейк-запись.
> - Suite gate без регрессий.

> **Out of scope:** materialize deploy (COS-165), генерация SBOM поверх образа.

> **Acceptance (Luna, 23 сентября 2026):** `domain/docker_build.py` дополнен
> каноническим маркер-парсером (`DOCKER_BUILD_MARKER_RE`, `parse_docker_build_marker`,
> `find_docker_build_digest`, `iter_docker_build_markers`). Новый
> `control_plane/artifact_capture.py` (`docker_build_specs` по `batch.bricks_refs`,
> `capture_artifact_records`, `MissingDockerBuildDigestError`); `execution_service.write_run_evidence`
> ловит digest из логов docker_build-шага → durable `record_artifact_record`
> (run_id + batch_id + canonical_ref). Битый/пустой output → честный alert
> `source='cosmo-artifact-record-missing'`, не выдуманный digest. Тесты
> `test_artifact_capture.py` — 13 passed. Suite gate 3448/0/16.

#### COS-165 · Luna · Deploy materialize (Э3) — pull по digest + run

> **Зачем:** `deploy_release` сейчас только status flip (`approved → deploying`). Нужен
> реальный materialize: pull образа по digest из Registry ЗР + запуск в целевом контуре,
> статус `deployed` только после фактической проверки.

> **Outcome:** `deploy_release` тянет образ по digest (источник — ArtifactRecord / resolve_digest),
> поднимает в контуре ЗР, статус `deployed` после факт. проверки; fail → честный rollback-статус.

> **Acceptance:**
> - `deploy_release` → реальный `docker pull` по digest + контейнер Up (healthy).
> - Статус `deployed` только после факт. проверки (не сразу по флагу).
> - Fail (нет образа / не стартовал / unhealthy) → честный статус (`failed`/rollback),
>   не молчаливый `deployed`.
> - Digest-источник — ArtifactRecord (durable), не пересбор.
> - Контур ЗР определяется существующим стеком (compose); без выдуманного k8s.

> **Out of scope:** promotion ЗР→ЗТ→ЗПЭ (Э5), release lifecycle DOCKER_AUDIT (Э4),
> авто-возврат digest (COS-164).

> **Acceptance (Luna, 23 сентября 2026):** `ledger/artifact_record.py` дополнен
> `artifact_records_for_run_ids(session, run_ids)` — источник digest (durable, не пересбор).
> Новый `adapters/runtime_docker.py` (`DockerDeployError`, `DeployRuntime`: pull/run/
> inspect_health/wait_healthy/remove/deploy, сеть `cosmo-net`, injectable runner) +
> `control_plane/deploy_runtime.py` (`get_deploy_runtime`/`set_deploy_runtime`, seam для тестов)
> + `ledger/release_deploy.py` (`record_release_deployed` decision `source='cosmo-release-deploy'` /
> `record_release_deploy_failed` alert `source='cosmo-release-deploy-failed'`).
> `api/routes/releases.py::deploy_release` переписан: резолв digest по `rel.run_ids` →
> `deploying` → `runtime.deploy(...)` в `asyncio.to_thread` → только после healthy
> `status='deployed'` + `artifacts`; `DockerDeployError` → `status='rollback'` + alert +
> HTTP 502; нет artifact record → HTTP 409. Контур ЗР = существующий compose-стек
> (`services/docker-compose.registry.yml`), без выдуманного k8s. Тесты
> `test_deploy_release.py` — 6 passed. Suite gate 3448/0/16.

> **Acceptance (PO, 23 сентября 2026):** COS-164 и COS-165 приняты.
>
> **COS-164 ✅** — авто-возврат digest закрыт честно: маркер-парсер каноничен
> (`DOCKER_BUILD_MARKER_RE`), битый/пустой → alert `cosmo-artifact-record-missing`,
> не фейк-digest. Durable связка run_id + canonical_ref.
>
> **COS-165 ✅ с follow-up (live-materialize)** — механика deploy корректна и покрыта:
> `artifact_records_for_run_ids` (durable digest-источник), `DeployRuntime` (sync
> subprocess-стиль, injectable runner, сеть `cosmo-net`), `deploy_release` переписан
> (резолв → deploying → `asyncio.to_thread(deploy)` → healthy → deployed; fail → rollback
> + alert + 502; нет artifact → 409). Контур ЗР = compose, k8s не выдумывался.
>
> **Честный edge:** живой materialize (реальный docker pull+run против поднятого
> registry-zr :5100) в этом пакете не гонялся — покрыт юнитами на fake-runner. Это не
> выдано за live. Живой E2E-прогон всего Steel Thread выносится отдельной карточкой
> **COS-166** — там flow build→push→capture→deploy→run сведётся против живого registry
> и compose.

---

## ✅ DONE — LIVE E2E SMOKE (STEEL THREAD)

> **Рубеж:** живой прогон всей цепочки build → push → capture → deploy → run против
> реального registry-zr (:5100) и compose, с durable Evidence на каждом шаге.
> **Вход:** заходы 1-2 механически готовы, юнитами покрыты; не хватает живого materialize.
> **Владелец:** Luna.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---:|---|---|---|---|
| **COS-166** | Luna | 6-8h | P1 | COS-164, COS-165 | ✅ DONE — Live E2E smoke против живого registry + compose + code-фикс COS-162 render |

#### COS-166 · Luna · Live E2E smoke Steel Thread

> **Зачем:** заходы 1-2 закрыты по механике (юниты + fake-runner), но живой materialize
> не гонялся. Нужен один сквозной live-прогон, доказывающий что вся цепочка реально
> работает против поднятого registry-zr и compose-контура ЗР.

> **Outcome:** один наблюдаемый live-проход: docker_build-пайплайн COS-161 собирает образ
> → push в registry-zr (digest) → runtime-hook авто-capture → deploy_release реально
> pull+run → контейнер up (healthy) → статус `deployed`, Evidence durable на каждом шаге.

> **Acceptance:**
> - Live-прогон полного цикла: build → push (digest) → авто-capture → deploy → run,
>   каждый статус реальный (не мок).
> - Evidence durable: `registry_push` + `artifact_record` + `release_deployed` читаются
>   из ledger, canonical_ref консистентен по всей цепочке.
> - Финальный результат: контейнер `cosmo-testapp` Up (healthy) в контуре ЗР, релиз `deployed`.
> - Negative: битый/отсутствующий digest → честный `rollback`/`failed`, не `deployed`.
> - Suite gate без регрессий.

> **Out of scope:** promotion ЗР→ЗТ→ЗПЭ (Э5), release lifecycle DOCKER_AUDIT (Э4),
> генерация SBOM поверх образа.

> **Acceptance (Luna, 23 сентября 2026):** COS-166 закрыт — полный live-проход
> steel thread выполнен против живого registry-zr (:5100) + compose (сеть
> `cosmo-net`), каждый статус реальный (не мок). Новый тест
> `tests/cosmo/test_int_cos166_deploy_steel_thread.py` (2 теста, self-skip при
> оффлайн-стенде): build → push → авто-capture → deploy_release (реальный
> `docker pull` по digest → `run` → healthy → `deployed`); negative (битый digest
> → `docker pull` manifest unknown → `DockerDeployError` → 502 + `rollback` +
> alert `cosmo-release-deploy-failed`, контейнера нет). Durable Evidence:
> `cosmo-artifact-record` (capture) и `cosmo-release-deploy` (deploy) читаются из
> как ledgers; `canonical_ref` консистентен end-to-end (digest в ArtifactRecord ==
> digest deploy == manifest-digest registry). Suite gate 3566/0/16.
>
> **Найден и закрыт реальный баг (code-фикс COS-162 `render_docker_build_commands`):**
> старый render слал `docker build --iidfile` (→ **CONFIG** digest, image id
> `sha256:64f724de…`) и затем `docker push <qualified>@$DIGEST`, который docker
> отвергает — «cannot push a digest reference». Хуже того: config-digest
> (`64f724…`) ≠ **MANIFEST**-digest (`sha256:59903d…`, тот что хранит registry и
> по которому идёт `pull`). Юниты не ловили (проверяли строки, не docker).
> Исправлено: push только по тегу (`<qualified>:<version>`, no-`latest`),
> manifest-digest снимается из строки `digest: sha256:...` ответа push →
> канонический маркер. Живой прогон подтверждает: build → push → `@sha256:59903d…`
> → capture → deploy healthy. Обновлён `test_docker_build.py` (assert нового
> контракта: build под qualified-тегом, push по тегу, `--iidfile`/push-`@$DIGEST`
> запрещены).

> **Acceptance (PO, 23 сентября 2026):** COS-166 принят. Steel Thread live закрыт —
> весь контур build → push → capture → deploy → run работает против реального registry
> и compose, Evidence durable, canonical_ref консистентен end-to-end.
>
> **Значимость:** live-smoke вскрыл реальный contract-drift, который юниты не ловили
> (проверяли строки, не docker): `docker push @$DIGEST` с **config**-digest из
> `--iidfile` неработоспособен и расходится с **manifest**-digest registry. Фикс —
> push строго по тегу (no-`latest`), manifest-digest снимается из ответа push. Это
> подтверждает канон COS-162/163: юнит-зелёный ≠ live-рабочий; сквозной live-прогон —
> обязательный gate, а не опция.

---

## ⬜ READY — RELEASE LIFECYCLE DOCKER_AUDIT (ЗАХОД 3)

> **Рубеж:** Э4 — release lifecycle `DOCKER_AUDIT` (build_image → sbom → trivy → deploy)
> как честный pipeline: SBOM поверх образа + trivy container scan + gate decision=pass
> перед materialize deploy. **Вход:** Steel Thread live закрыт (заходы 1-2 + COS-166).
> **Владелец:** Luna.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-167** | Luna | 8-12h | P1 | COS-166 | ✅ DONE — SBOM поверх образа (syft/CycloneDX) + durable evidence, связка sbom_ref |
| **COS-168** | Luna | 8-12h | P1 | COS-167 | ✅ DONE — Trivy container scan + gate decision=pass перед deploy (block critical>0) |

#### COS-167 · Luna · SBOM поверх образа (DOCKER_AUDIT: sbom)

> **Зачем:** `DOCKER_AUDIT` профиль требует шаг sbom (`evidence_required=True`) между
> build_image и trivy. Сейчас `ArtifactRecord.sbom_ref` есть, но реальной генерации
> SBOM поверх собранного образа нет (follow-up захода 1). Нужно снять SBOM (syft →
> CycloneDX 1.5) и крипто-якорить его в Evidence Ledger, связав с ArtifactRecord.

> **Outcome:** после build образ сканируется syft → CycloneDX 1.5 SBOM; blob запечатывается
> в Evidence (канонический `commit_evidence_entry`), `ArtifactRecord.sbom_ref` указывает на
> якорь; read-through durable, restart-survival.

> **Acceptance:**
> - После build генерится честный SBOM (syft, если доступен; иначе честный
>   `python-inventory` — как COS-155, не фейк).
> - SBOM запечатан durable (hash-якорь в ledger), `ArtifactRecord.sbom_ref` читается
>   после рестарта.
> - Связка digest-сверки: SBOM относится к тому же manifest-digest, что и ArtifactRecord.
> - Suite gate без регрессий.

> **Out of scope:** trivy scan/gate (COS-168), promotion ЗР→ЗТ→ЗПЭ (Э5).

> **Acceptance (Luna, 23 сентября 2026):** COS-167 закрыт. Новые `domain/artifact_sbom.py`
> (`ArtifactSbomRequest`/`ArtifactSbomResponse`, реюз `SbomInventoryDocument` COS-155),
> `ledger/artifact_sbom.py` (durable SBOM поверх образа: `anchor_artifact_sbom` →
> `store_artifact_sbom` → `commit_evidence_entry`, `source='cosmo-artifact-sbom'`;
> `latest_artifact_sbom` read-through durable (restart-survival), sbom-якорь несёт
> `document.model_dump(mode="json", by_alias=True)` + `content_hash`-сверка). Digest-сверка
> by-construction: SBOM-запись несёт `artifact_digest` актуального `ArtifactRecord`;
> `ArtifactRecord.sbom_ref` проставляется durable-перезаписью (latest wins). Эндпоинты
> `POST /api/v1/artifacts/sbom/image` (generate+anchor) и
> `GET /api/v1/artifacts/sbom/image/{name}/{version}` (durable read). Генерация по канону
> COS-155: syft → `python-inventory` fallback (честный `generator`). Live smoke
> (`test_int_cos167_cos168_steel_thread.py`) снимает SBOM с реально запушенного
> `cosmo-testapp:0.1.0` (generator `python-inventory`), read-back после рестарта,
> sbom_ref == `oci://localhost:5100/cosmoport/zr/cosmo-testapp@sha256:…#sbom`.

> **Deviation (без новой миграции):** SBOM генерации/хранения — без нового PG-ENUM/таблицы:
> `type='decision'` + маркер `source='cosmo-artifact-sbom'`/`artifact_type='ARTIFACT_SBOM'`
> в `provenance_json` (канон COS-138/152). syft-мишень с pinned-digest:
> `<qualified>@sha256:<digest>`.

#### COS-168 · Luna · Trivy container scan + gate (DOCKER_AUDIT: trivy)

> **Зачем:** `DOCKER_AUDIT` профиль требует trivy step (`gates_required=True`) между
> sbom и deploy. Нужен container scan образа с gate-решением: блок deploy при
> critical>0 (канон COS-138 Grype-gate), digest-сверка конверта/отчёта/образа.

> **Outcome:** trivy сканирует собранный образ (или SBOM из COS-167), gate-решение
> (decision=pass/block) durable в Evidence Ledger и в release gates; deploy разрешён
> только при pass (critical=0).

> **Acceptance:**
> - Образ просканирован (trivy или честный fallback `unavailable` — не фейк).
> - Gate decision durable; block при critical>0; digest-сверка (manifest-digest образа
>   == digest отчёта) до принятия решения.
> - materialize deploy (COS-165) блокируется без pass decision.
> - Suite gate без регрессий.

> **Out of scope:** promotion ЗР→ЗТ→ЗПЭ (Э5), source-SAСТ (SonarQube/CodeScoring — это
> SOURCE_AUDIT, не docker).

> **Acceptance (Luna, 23 сентября 2026):** COS-168 закрыт. Новые `domain/artifact_scan.py`
> (`TrivyFinding`/`TrivyScanReport`/`TrivyGateAttachRequest`/`TrivyGateAttestationResponse`,
> `trivy_scan_content_hash`, `observed_severity_count`, `resolve_normalized_digests`),
> `ledger/artifact_scan_gate.py`: `run_trivy_scan` (честный `TrivyRunResult`, `unavailable`
> при отсутствии бинаря — не фейк), `parse_trivy_report` (counts пересчитываются из findings,
> severity-нормализация), `verify_and_attest_trivy_gate` (digest-сверка конверта/отчёта/образа
> против durable `ArtifactRecord`, порог `critical = max(заявленный, наблюдаемый)`,
> `critical>0 → BLOCK/DENIED`, иначе `PASS/CLEARED`; decision якорится в Evidence Ledger через
> `commit_evidence_entry`, `source='cosmo-trivy-gate'`), `latest_trivy_gate`,
> `trivy_blocker_for_records` (deploy enforcement). Эндпоинты:
> `POST /api/v1/releases/{release_id}/trivy/attach` (GATE_DECIDE, 201) и
> `GET /api/v1/releases/{release_id}/trivy` (latest decision, 404 если нет).
> `deploy_release` после резолва artifact-records зовёт `trivy_blocker_for_records` →
> BLOCK/отсутствие вердикта → HTTP 409 (статус остаётся `approved`). Live smoke:
> trivy PASS → deploy 200 (реальный `docker pull` по digest → `run` → healthy → `deployed`);
> BLOCK (critical>0) → 409, статус не покидает `approved`.

> **Decision (верифицировано PO-каноном COS-138):** trivy gate вердикт якорится в Evidence
> Ledger ТОЛЬКО (`type='decision'` + маркер `source='cosmo-trivy-gate'`), gates-таблицу НЕ
> пишем — deploy читает Evidence Ledger через `trivy_blocker_for_records`. Мотивация: не
> контаминировать per-release gate решением plan-level цикл transfer-гейтов (COS-145/146);
> формулировка «в release gates» трактуется как durable gate-решение в release evidence.

> **Out of scope (сохранено):** фактический прогон trivy-бинаря на стенде (на хосте бинаря
> нет) — gate считает вердикт по attach-контракту; run_trivy_scan честно возвращает
> `unavailable`. promotion ЗР→ЗТ→ЗПЭ (Э5).

> **Acceptance (PO, 23 сентября 2026):** COS-167 и COS-168 приняты. Заход 3 (Э4 DOCKER_AUDIT)
> закрыт. SBOM поверх образа + trivy gate — честно, durable, с digest-сверкой; deploy
> enforcement через Evidence Ledger.
>
> **Архитектурное решение подтверждаю:** trivy gate вердикт якорится ТОЛЬКО в Evidence
> Ledger (`type='decision'` + `source='cosmo-trivy-gate'`), gates-таблицу не пишем. Это
> точно канон COS-138/152 («не плодить PG-ENUM/таблицы, конвенция type='decision' +
> provenance_json маркер») и не контаминирует plan-level transfer-гейты (COS-145/146).
> Deviation «без новой миграции» — согласуется с заморозкой цепочки миграций.
>
> **Честность:** syft → `python-inventory` fallback, trivy-бинар отсутствует на хосте →
> `unavailable` (не фейк). Это фиксируем как infra follow-up (установить trivy в раннер),
> не как код-долг.
>
> **Follow-up (не блокирует заход):**
> - Фактический прогон trivy-бинаря на стенде/раннере — сейчас честный `unavailable`.

---

## ✅ DONE — PROMOTION ЗР→ЗТ→ЗПЭ (ЗАХОД 4 · Э5)

> **Рубеж:** Э5 — promotion релиза между зонами: transfer-пакет (образ digest-pin + SBOM +
> trivy gate + evidence) → landing в целевой зоне с digest-matching → promoted; сквозной
> multi-zone проход ЗР→ЗТ→ЗПЭ + live smoke. **Вход:** build→registry→deploy→gate live закрыты
> (заходы 1-3). Transfer kernel (COS-050/053/054/136-148) уже готов как фундамент.
> **Владелец:** Luna.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---:|---|---|---|---|
| **COS-169** | Luna | 10-14h | P1 | COS-168 | ✅ DONE — Promotion packing + landing ЗР→ЗТ: transfer-пакет + digest-matching → promoted |
| **COS-170** | Luna | 10-14h | P1 | COS-169 | ✅ DONE — Multi-zone promotion ЗР→ЗТ→ЗПЭ + live smoke, Evidence durable на каждой зоне |

#### COS-169 · Luna · Promotion packing + landing (ЗР→ЗТ)

> **Зачем:** Э5 — релиз должен переезжать в следующую зону как пакет (не голый образ):
> digest-pin + SBOM + trivy gate + evidence, с digest-matching при landing. Фундамент
> transfer kernel уже есть (TransferItem/Plan, PackageBuilder, landing, offline_importer).

> **Outcome:** promotion релиза в ЗТ упаковывает артефакт в transfer-пакет (idempotent
> PackageRevision), целевая landing верифицирует manifest-digest == пакетный digest,
> SBOM + gate pass → статус promoted; fail/mismatch → честный LandingCheckReport.

> **Acceptance:**
> - Promotion ЗР→ЗТ собирает пакет (digest-pin + SBOM + trivy gate + evidence), idempotent.
> - Landing в ЗТ: manifest-digest совпадает с пакетным → promoted; mismatch/missing →
>   честный fail-отчёт (не молчаливый promoted).
> - Gate pass обязателен: блок promo при BLOCK/отсутствии trivy-вердикта.
> - Durable Evidence на обеих зонах (отправка + landing), restart-survival.
> - Suite gate без регрессий.

> **Out of scope:** multi-zone ЗР→ЗТ→ЗПЭ live smoke (COS-170), source-SAST.

> **Acceptance (Luna, 23 сентября 2026):** COS-169 реализована, НЕ закоммичено.
> Новый `domain/promotion.py` (DTO `PromotionPackage`/`PromotionLandRequest`/
> `PromotionLandResponse`/`PromotionLandResponse` + `build_promotion_manifest` без
> timestamp → детерминированный `compute_package_digest` SHA-256 canonical JSON +
> `promotion_content_fingerprint` idempotency-key), `ledger/promotion_ledger.py`
> (`pack_release_promotion` — гейт trivy PASS + `sbom_ref` обязателен, идемпотентный
> no-op `duplicate`; `land_release_promotion` — idempotent replay → CAS → digest-match →
> линейная проверка зоны → belt-and-suspenders trivy/SBOM re-read → перевод зоны +
> `transfer_history` + durable evidence; crypto-проверяемые read-back
> `latest_promotion_package`/`latest_promotion_landing`). Роуты `routes/releases.py`:
> `POST /{id}/promote`, `POST /{id}/promote/land`, `GET /{id}/promotion`,
> `GET /{id}/promotion/land` (все под `_RELEASE_TRANSFER_GUARD`). Durable через
> `source='cosmo-promotion-package'` / `cosmo-promotion-landing` без новых таблиц.
> `test_promotion.py` 12 passed.

#### COS-170 · Luna · Multi-zone promotion ЗР→ЗТ→ЗПЭ + live smoke

> **Зачем:** последний рубеж плана (Э5) — сквозной promotion релиза через все зоны
> (ЗР→ЗТ→ЗПЭ) с живым подтверждением, Evidence durable на каждом переходе.

> **Outcome:** живой сквозной проход promotion ЗР→ЗТ→ЗПЭ: на каждой зоне landing +
> digest-matching + gate pass → promoted; Evidence durable по всем переходам,
> canonical_ref консистентен end-to-end.

> **Acceptance:**
> - Лив-проход promotion через ЗР→ЗТ→ЗПЭ (или честный self-skip при оффлайн-контуре).
> - На каждой зоне digest-matching держится, gate pass обязателен, статус promoted.
> - Negative: mismatch/нарушенный пакет на любой зоне → честный fail, промо остановлено.
> - Evidence durable per-zone, переживает рестарт.
> - Suite gate без регрессий.

> **Out of scope:** установка trivy-бинаря в раннер (infra follow-up захода 3).

> **Acceptance (Luna, 23 сентября 2026):** COS-170 реализована, НЕ закоммичено.
> Live steel-thread smoke `test_int_cos169_cos170_promotion_steel_thread.py` — сквозной
> build→push→capture→sbom→trivy→deploy→promote/land ЗР→ЗТ→ЗПЭ, дурабл Evidence на каждой
> зоне (`zpe:packed`, `zt:packed`, `zpe:promoted`, `zt:promoted`), финализация промо →
> 400 в `zpe`; negative mismatch-digest на landing → 422, промо остановлено, Evidence
> landing не пишется. Self-skip при оффлайн-контуре (docker / cosmo-net /
> registry-zr:5100). Suite gate **3607 passed / 0 failed / 16 skipped** (392s). OpenAPI
> регенерирован (151 путь / 202 схемы, json==yaml==live).

> **Acceptance (PO, 23 сентября 2026):** COS-169 и COS-170 приняты. **Э5 закрыт — весь
> build+deploy план (Э1-Э5) завершён.**
>
> **COS-169 ✅** — promotion ЗР→ЗТ: `pack_release_promotion` (trivy PASS + `sbom_ref`
> обязательны, идемпотентный `duplicate`), `land_release_promotion` (replay → CAS 409 →
> digest-match 422 → линейная зона 409 → trivy/SBOM re-read → перевод зоны + durable
> evidence), детерминированный `compute_package_digest` (canonical JSON без timestamp) +
> idempotency-fingerprint. Durable через `source='cosmo-promotion-*'` без новых таблиц —
> канон соблюдён.
> **COS-170 ✅** — multi-zone live: сквозной build→push→capture→sbom→trivy→deploy→
> promote/land ЗР→ЗТ→ЗПЭ, Evidence durable per-zone, mismatch→422 negative (промо
> остановлено, landing-запись не пишется).
>
> **Бай-кат принят:** регрессия `test_domain_resolve_invariant` (ожидал
> `require_capability(` в сигнатурах новых write-роутов) закрыта комментарием-маркером
> той же конвенцией, что `transfer_release` — новые роуты под составным
> `_RELEASE_TRANSFER_GUARD` (require_capability внутри), SoD не нарушен.

---

## ✅ BUILD + DEPLOY — ПОЛНЫЙ CYCLE ЗАКРЫТ (2026-09-23)

> **Steel Thread собран целиком и live-верифицирован:**
> Domain → Gitea (source) → Woodpecker (docker build) → Registry ЗР (canonical
> digest-tag) → capture (auto-digest) → SBOM + trivy gate → deploy materialize →
> promotion ЗР→ЗТ→ЗПЭ. Evidence durable на каждом шаге, digest-matching и GAP enforce
> на всех переходах.
>
> **Карточки:** COS-161…COS-170 (заходы 1-4). Suite gate **3607/0/16**.
> **План:** `docs/research/2026-09-23-build-deploy-gitea-woodpecker.md`.
>
> **Остаточные follow-ups (не карточки, зафиксировано):**
> - trivy-бинарь в раннере (сейчас честный `unavailable`);
> - боевой syft вместо `python-inventory` fallback.

---

## ✅ DONE — INFRA: TRIVY/SYFT В СКАН-РАННЕРЕ (ЗАХОД 5)

> **Директив Максима:** боевой `trivy`-бинарь в раннере + `syft` вместо
> `python-inventory` fallback — режь для Boss. Это закрывает два остаточных follow-up
> захода 3 (зафиксированы в «BUILD + DEPLOY — ПОЛНЫЙ CYCLE» и в out-of-scope COS-167/168).
>
> **Трактование «раннера» (допущение, поправь одним словом если нет):** сканы исполняются
> субпроцессом **внутри контейнера `cosmo-api`** (`run_trivy_scan`, `generate_artifact_sbom`
> / `generate_sbom_inventory`), а не в Woodpecker agent (тот делает только docker build+push,
> COS-162/163). Значит бинарики/DB ставятся в образ `cosmo-api` (`python:3.12-slim`,
> `services/cosmo-api.Dockerfile`). Отдельный security-runner контейнер НЕ заводим —
> это был бы новый сервис вне поверхности.
>
> **Ключевой риск:** локальный registry `cosmo-registry-zr:5000` — plain HTTP (distribution,
> без TLS). trivy/syft по умолчанию отказываются от insecure-registry — нужен явный allow
> для этого хоста, иначе реальный скан честно упадёт. Решение — на владельце поверхности
> (env-флаг/`--insecure`/registry-config), но обязано быть точечным (только локальный
> registry, не глобально).
>
> **Владелец:** Boss (единственный поток; карточки идут последовательно, одна поверхность).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-171** | Boss | 8-12h | P1 | COS-168 | ✅ DONE — боевой `trivy` 0.74.0 + offline DB (1.4G, seed) в образе: `source=trivy`, 203 findings |
| **COS-172** | Boss | 8-12h | P1 | COS-167, COS-155 | ✅ DONE — боевой `syft` 1.20.0 в образе: `generator=syft`, 2820 components |

> **Пересечение поверхностей:** 0 (обе карточки — один worker, общая Dockerfile/airgap
> поверхность ведётся им последовательно). Скан-код (`artifact_scan_gate.py`,
> `artifact_sbom.py`, `sbom_inventory.py`) меняется минимально и только ради plumbing
> (insecure-registry + cache-dir), если это реально требуется — логика гейтов не трогается.

### Карточки

#### ✅ COS-171 · Boss · Infra: боевой trivy-бинарь + offline DB в скане-раннере — DONE (2026-09-24)

> **Зачем:** `run_trivy_scan` честно возвращает `unavailable` — на хосте и в образе
> trivy-бинаря нет, а реальный прогон `trivy image --skip-db-update` требует бинарь +
> предзагруженную offline DB. Это закрывает последний честный `unavailable` захода 3
> (COS-168 out-of-scope) и переводит DOCKER_AUDIT на реальный скан.

> **Scope:**
> (1) Образ `cosmo-api` (`services/cosmo-api.Dockerfile`) получает рабочий trivy-бинарь в
>     PATH (детерминированная версия, не `latest`; digest-pin где возможно).
> (2) Offline trivy DB предзагружается и попадает в контейнер как смонтированный кэш
>     (без сетевого `--download-db-only` в рантайме — airgap-канон: 0 внешних запросов).
>     `run_trivy_scan` продолжает держать `--skip-db-update`: без DB → честный `unavailable`, не фейк.
> (3) Реальный прогон по локально запушенному образу (`cosmo-registry-zr:5000` HTTP):
>     точечный insecure-allow строго для этого registry; digest-образ сканируется, JSON-отчёт
>     парсится `parse_trivy_report` в реальные findings.
> (4) `services/docker-compose.yml` + `airgap-bundle.ps1`: env/volumes для DB-кэша, а в бандл
>     попадают бинарь + DB-снапшот (в образе либо отдельным артефактом) — установка
>     остаётся без внешней сети.
> (5) Тесты: focused-юнит на plumbing (бинарь есть/нет, DB есть/нет, insecure-allow) +
>     live opt-in smoke против registry-zr (self-skip при оффлайн-стенде, как COS-166).

> **Out of scope:** логика гейта (`verify_and_attest_trivy_gate`, порог `critical>0`,
> digest-сверка — уже принято COS-168), promotion (закрыт COS-169/170), source-SAST,
> syft (COS-172), миграционная цепочка (заморожена).

> **Acceptance:**
> - Внутри контейнера `trivy --version` отвечает; DB-кэш на месте и не тянется из сети в прогоне.
> - `run_trivy_scan(<qualified>@sha256:digest)` на локально запушенном образе возвращает
>   `source='trivy'` с реальным JSON (findings > 0 или честно пусто, но не `unavailable`).
> - `verify_and_attest_trivy_gate` принимает тот отчёт: `content_hash` считается, decision
>   якорится durable; `trivy_blocker_for_records` видит PASS для чистого `cosmo-testapp:0.1.0`.
> - Negative: registry недоступен / DB нет / бинарь убран → честный `unavailable` (не фейк, не 5xx).
> - Airgap-бандл собран: бинарь + DB-снапшот присутствуют, установка без сети.
> - Suite gate без регрессий.

> **Отчёт обратно:** как поставили бинарь + DB (версия, digest); как разрешили insecure-HTTP
> registry точечно; прогон реального скана (источник + findings-count); negative-кейсы;
> состав airgap-бандла; bumped-версии/дрифты; блокеры.

#### ✅ COS-172 · Boss · Infra: боевой syft-бинарь вместо python-inventory fallback — DONE (2026-09-24)

> **Зачем:** `generate_sbom_inventory` / `generate_artifact_sbom` / `transfer.sbom.generate_sbom`
> честно падают в `python-inventory`/`internal`, потому что syft отсутствует в образе.
> Закрываем follow-up COS-167/COS-155: SBOM поверхности снимается реальным syft (CycloneDX 1.5).

> **Scope:**
> (1) Образ `cosmo-api` получает рабочий syft-бинарь в PATH (детерминированная версия,
>     digest-pin где возможно) — та же Dockerfile-поверхность, что COS-171.
> (2) Реальный скан OCI-образа: `generate_artifact_sbom` передаёт
>     `<qualified>@sha256:digest`; syft снимает SBOM с локально запушенного образа
>     (`cosmo-registry-zr:5000` HTTP → точечный insecure-allow, как COS-171), документ
>     возвращается с `generator=syft` (НЕ `python-inventory`).
> (3) SBOM запечатывается durable (`store_artifact_sbom` / `store_sbom_inventory`),
>     `ArtifactRecord.sbom_ref` проставляется, read-through переживает рестарт (уже есть
>     в COS-167/152 — не переписывать, только подтвердить на реальном syft-документе).
> (4) `airgap-bundle.ps1`: syft-бинарь попадает в бандл (в образе).
> (5) Тесты: focused-юнит (бинарь есть/нет → generator-маркер) + live opt-in smoke
>     против registry-zr (self-skip при оффлайн).

> **Out of scope:** grype-визор (остаётся честный `available=false` при отсутствии grype —
> в scope этой карточки не входит), trivy (COS-171), promotion, миграционная цепочка,
> source-SAST.

> **Acceptance:**
> - Внутри контейнера `syft version` отвечает.
> - SBOM поверх реально запушенного `cosmo-testapp:0.1.0` отдаётся с `generator=syft`,
>   валидный CycloneDX 1.5 (schema-проверка), не `python-inventory`.
> - SBOM durable в Evidence Ledger, `ArtifactRecord.sbom_ref` проставлен, GET видит после рестарта.
> - Negative: registry недоступен / бинарь убран → честный `python-inventory` fallback (не фейк syft).
> - Airgap-бандл несёт syft-бинарь.
> - Suite gate без регрессий.

> **Отчёт обратно:** версия/digest syft; как разрешили insecure-registry; пример SBOM с
> `generator=syft` (компоненты); доказательство durable-read после рестарта; negative-кейсы;
> состав airgap-бандла; блокеры.

> **Исполнено (Boss, 2026-09-24, live smoke из контейнера cosmo-api):**
> - Бинари в образе (digest-pin sha256): trivy `0.74.0` (`2ae6fe3e…`), syft `1.20.0` (`689e12c5…`).
> - Offline trivy DB: `/var/lib/trivy/db/trivy.db` = 1.4G, seed-тарбол `/opt/trivy-db-seed.tar.gz`
>   (entrypoint идемпотентно раскатывает в volume `services_cosmo_trivy_cache`).
> - Insecure точечно: trivy `--insecure` и syft `SYFT_REGISTRY_INSECURE_USE_HTTP=true` —
>   только при host ∈ allowlist `INSECURE_REGISTRY_HOSTS` (`registry_policy.py`).
> - Live: `run_trivy_scan(cosmo-registry-zr:5000/…cosmo-testapp:0.1.0)` → `source=trivy`, 203 findings;
>   `generate_sbom_inventory(…)` → `generator=syft`, 2820 components, CycloneDX.
> - Negative: пустой cache → `source=none` (честно); unreachable registry → `python-inventory` (честно).
> - Баг закрыт: syft plumbing ставил несуществующий `--insecure-skip-tls-verify` (флаг grype)
>   + гейт `"://" in target` → заменён на env по allowlist; +3 юнита `TestGenerateSyftDocument`.
> - Suite gate: `pytest orchestrator/tests/cosmo/` → **3476 passed, 16 skipped, 0 failed**.
> - Блокер: коммит + push — ждёт команды Максима (не выполнен). grype вне scope → `available=false`.

---

## 🔄 ACTIVE — AUTH-ЭПИК (FLASH, ОДИН ПОТОК, ПО ОЧЕРЕДИ)

> **Статус (24.09.2026):** auth-эпик **закрыт полностью** — COS-156 (verifier) → COS-157
> (issuer, suite gate 3526/16/0) → COS-175 (auth-bootstrap + live-smoke) → COS-158
> (FE login, e2e 4/4). Пласт закоммичен в `dev` и запушен в `origin/dev` + `origin/main`
> (HEAD `8409d8b`, 5 коммитов). COS-176 — выдана Flash (2026-09-25).

**Очередь Flash:**
1. ✅ **COS-157-CLOSE** — полный suite gate по auth-коду (закрыто, 24.09.2026).
2. ✅ **COS-175** — OpenBao auth-bootstrap + сквозной live-smoke (принято, 24.09.2026).
3. ✅ **COS-158** — FE login surface + session, dev-stub удалён (принято, 24.09.2026).
4. 🔄 **COS-176** — e2e auth-mint миграция: `alg:none` → реальный login (follow-up приёмки COS-158). **Выдана Flash (25.09.2026).**

> **Follow-up (найден при приёмке COS-158):** остальные e2e-спеки (notifications/web-ide/
> degraded/release-readiness) минтят `alg:none` через `helpers/e2e_auth.ts` — verifier COS-156
> теперь отвергает их → e2e-линия красная вне login-флоу. Идёт в COS-176.

> Коммит+push пласта — **сделано** (5 коммитов, HEAD `8409d8b`, dev + main). Кандидаты после auth-линии: grype
> follow-up (честный `available=false`), source-SAST (SonarQube/CodeScoring) для
> SOURCE_AUDIT; серверные IDE follow-up от Vector (SSE resume лог-стрима; typed 409
> `expected_head_sha`; PTY exec).

#### ✅ COS-157-CLOSE · Flash · Полный suite gate по auth-коду (acceptance №5)

> **Зачем:** acceptance COS-157 №5 требует «auth-regression + jwt_verification + suite
> gate зелёные». Flash прогнал только фокус (20 новых + 152 regression); полный сет
> (~3476+) по новому боевому `auth_router`/`Depends(get_vault)` не прогонялся. Это
> единственный незакрытый критерий приёмки COS-157.

> **Acceptance:**
> - Полный suite gate (`pytest orchestrator/tests/cosmo/`) зелёный; либо все красные
>   зоны — чужие поверхности с явным владельцем (не auth).
> - passed/skipped/failed зафиксированы в отчёте.
> - Боевого кода не менять — gate только показывает наличие/отсутствие регрессий.

> **Принято (24.09.2026):** полный сет **3526 passed / 16 skipped / 0 failed** (358s),
> красных зон нет. auth-поверхности COS-157 (jwt_issuer, credentials, auth_login) в сете
> зелёные; `test_openapi_contract` с allowlist `LoginResponse` прошёл; регрессионные
> auth-наборы зелёные. 16 skipped — опциональный live-контур (`COSMO_LIVE_*` не подняты),
> ожидаемый класс. Боевой код не менялся. **COS-157 закрыт полностью** (acceptance 1–5).

> **Отчёт обратно:** команда, длительность, passed/skipped/failed; красные зоны и их
> владелец (если есть); подтверждение, что auth-поверхность не регрессирует.

#### ✅ COS-175 · Flash · OpenBao auth-bootstrap + сквозной live-smoke

> **Зачем:** issuer (COS-157) и verifier (COS-156) в коде готовы, но в standalone
> OpenBao (`prettyk-openbao`, AppRole `cosmo-app`) НЕ засидированы
> `secret/cosmo/jwt-keys` (RSA-пара подписи) и `secret/cosmo/auth` (email + PBKDF2-хэш
> админа). Без этого живой прогон «login → mint → JWKS → verify» невозможен, а COS-158
> (FE login) нельзя верифицировать живьём. Сидирования в репозитории нет нигде
> (grep по скриптам/ps1/sh пуст).

> **Scope:**
> (1) Скрипт/процедура сидирования в standalone OpenBao: `jwt-keys` → `{rsa_private,
>     rsa_public, issuers:[...], audience:"cosmo-api"}` (RSA-2048+); `auth` → `{email,
>     password_hash (PBKDF2, self-describing формат COS-157), sub, roles, is_admin}`.
> (2) Идемпотентность: повторный запуск не плодит дубли и не роняет существующие секреты.
> (3) Сквозной live-smoke: AppRole-read ключа → POST `/api/v1/auth/login` (верные/неверные
>     креды) → выпуск RS256 JWT → GET `/.well-known/jwks.json` → `verify_jwt` собирает
>     principal (sub/roles/is_admin) сквозь реальный JWKS (не mock-fetcher).
> (4) Fail-closed проверка: без сидирования → 503 (не default-success).

> **Out of scope:** сам issuer/verifier код (COS-156/157 готовы); FE login (COS-158);
> session/refresh/rotation; внешний OIDC; миграционная цепочка.

> **Acceptance:**
> - Живой login→mint→JWKS→verify→principal зелёный «глазами» (не unit-mock).
> - Приватный ключ только в OpenBao, в git/`.env` не попадает.
> - Неверный пароль → 401; отсутствие секретов → 503.
> - Сидирование идемпотентно и задокументировано (скрипт + секция/readme).

> **Принято (24.09.2026):** `services/scripts/seed-auth-secrets.py` (идемпотентный, AppRole
> `cosmo-app`, kv-v2 `secret/cosmo/{jwt-keys,auth}`, `--rotate`). `jwt-keys` → реальный
> RSA-2048 (PKCS#8/SPKI), `issuers=["cosmoport"]`, `audience="cosmo-api"`; `auth` →
> `admin@cosmoport.local` / PBKDF2 / sub=admin / roles=[admin_sec] / is_admin=true.
> Live-smoke глазами: login до seed → **503**, JWKS → 200 (kid совпал), верный пароль →
> **200 + RS256 JWT** (header kid == JWKS kid), неверный → **401**, host-side `verify_jwt`
> через реальный JWKS URL → principal `{sub=admin, roles=[admin_sec], is_admin=true}`,
> tampered → rejected. Идемпотентность: второй запуск → PRESERVED (тот же kid/hash).
> Приватный ключ только в OpenBao. Известный факт: старый образ cosmo-api отдавал 404 на
> auth-роуты → потребовался rebuild/recreate (auth-маршруты вошли в образ). Dev-креды админа
> переопределяются оператором для прод-контура.

> **Отчёт обратно:** скрипт/команда сидирования; live-smoke лог (шаги + результаты);
> подтверждение прохождения verify→principal; блокеры.

> **Принято (24.09.2026, Flash):**
> - **Скрипт:** `services/scripts/seed-auth-secrets.py` — идемпотентный seed через
>   AppRole `cosmo-app` (клиент COS-105, не root token). Читает/пишет kv-v2
>   `secret/cosmo/{jwt-keys,auth}`; `--rotate` форсирует перегенерацию ключа.
> - **jwt-keys:** placeholder `DEV-ONLY-PLACEHOLDER-COS-157` заменён живой RSA-2048
>   (PKCS#8 private / SPKI public), `issuers=["cosmoport"]`, `audience="cosmo-api"`,
>   `kid=WOvAMAJ-eukgrtc9knBkew`. auth: `email=admin@cosmoport.local`,
>   `sub=admin`, `roles=["admin_sec"]`, `is_admin=true`, PBKDF2-hash
>   (`pbkdf2_sha256$…` via `credentials.hash_password`).
> - **Fail-closed:** до сидирования `POST /api/v1/auth/login` → **503**
>   `{"detail":"auth secret not bootstrapped (secret/cosmo/auth not seeded)"}`.
> - **Live-smoke «глазами»:** JWKS → **200** (RSA JWK, kid совпал); login верный →
>   **200** + RS256 JWT (header kid = JWKS kid); login неверный → **401**
>   `invalid credentials`; host-side `verify_jwt` сквозь реальный
>   `COSMO_JWT_JWKS_URL=http://localhost:8100/.well-known/jwks.json` → principal
>   `{sub=admin, roles=[admin_sec], is_admin=true, iss=cosmoport, aud=cosmo-api}`;
>   tampered-токен отвергнут (signature failed).
> - **Идемпотентность:** второй запуск → `PRESERVED` (тот же kid, тот же hash).
> - Приватный ключ только в OpenBao (в git/.env/вывод скрипта не попадает).
> - **Заметка:** пересобран `cosmo-api:local` (в старом образе auth-роуты 404) +
>   recreate container. Без rebuild старые 404 на `/login`/`/jwks` неизбежны.

#### COS-158 · Flash · FE login surface + session — убрать dev-stub `operator:admin`

> **Зачем:** фронт сейчас шлёт dev-stub `operator:admin` (заголовочный контракт до
> COS-156). Нужен боевой login surface: форма логина → `POST /api/v1/auth/login` →
> подписанный токен → хранение сессии → `Authorization: Bearer` на все API-вызовы.

> **Scope:**
> (1) `frontend/src/auth/` — login-форма (email/password), вызов `POST /api/v1/auth/login`,
>     хранение `access_token` (сессия), `Bearer` в Authorization.
> (2) Логаут; обработка 401 (истёкший/неверный токен) → редирект на login.
> (3) Убрать dev-stub `operator:admin` (и старый заголовочный контракт) из всех вызовов.
> (4) Честные состояния: loading, 401 (неверные креды), 503 (issuer не готов), network
>     error; никакого дефолт-успеха.

> **Out of scope:** session refresh/rotation; внешний OIDC/Blitz SSO; парольный reset;
> сам issuer/verifier (приняты).

> **Acceptance:**
> - Логин с валидными креденшелами (засидированный админ COS-175) → токен → доступ к
>   guarded-поверхностям; неверный пароль → честный 401 на форме.
> - Ни одного dev-stub `operator:admin` в клиентском коде (grep пуст).
> - tsc/vitest/build зелёные; e2e login-флоу зелёный (если есть линия).

> **Отчёт обратно:** поверхности FE; как хранится/передаётся токен; логаут и 401-флоу;
> результат tsc/vitest/build; подтверждение удаления stub'а; блокеры.

**Worker report (Flash):**
- **Поверхности FE:** `frontend/src/cosmo/auth/authStore.ts` (reactive store: `localStorage['cosmo_auth_token']` → `useSession()`, `login`/`logout`/`clearSessionOnUnauthorized`, user display-only из payload без проверки подписи) + `LoginView.tsx` (MUI форма email/password → `POST /api/v1/auth/login`, честные idle/submitting/401/503/network, без дефолт-успеха). `App.tsx` — gate за `useSession()` (нет сессии → LoginView); `ControlStationShell.tsx` — `header-user` + logout.
- **Хранение/передача токена:** `cosmo_auth_token` в localStorage; `api.ts` `getCosmoAuthToken()` → `Authorization: Bearer`; на любой 401 `clearSessionOnUnauthorized()` → App сам возвращает на login.
- **Checks:** vitest 81/81 passed; `tsc -b` + `vite build` green; `grep operator:admin` в `frontend/` = 0 (dev-stub и старый заголовочный контракт удалены); e2e `frontend/e2e/login.spec.ts` (новый) 4/4 green против live `:5175+:8100` (реальный RS256 из issuer; no-session/wrong-password/empty-fields/success+logout).
- **Блокеры:** нет. **Finding (не блокер COS-158):** остальные e2e-спеки (notifications/web-ide/degraded/release-readiness) минтят `alg:none` через `helpers/e2e_auth.ts` — COS-156 теперь отвергает их на бэке; миграция на реальный логин = **COS-176** (follow-up, нарезана ниже).

> **Принято (Cosmo, PO, 24.09.2026):** acceptance COS-158 закрыта — e2e `login.spec.ts` 4/4
> green против live `:5175+:8100` (реальный RS256 из issuer: no-session→login, empty-fields,
> wrong-password→честный 401, success→Control Station→logout); `grep operator:admin` в
> `frontend/` = 0; vitest 81/81, `tsc -b` + `vite build` green. Хранение токена — localStorage
> (`cosmo_auth_token`), `Authorization: Bearer` через `getCosmoAuthToken()`, 401 →
> `clearSessionOnUnauthorized()` → возврат на login. **Finding зачтён как follow-up COS-176**
> (e2e-хелпер `e2e_auth.ts` отстал от verifier COS-156; вне scope COS-158, но разбивает
> остальную e2e-линию — must-fix до коммита пласта).

---

#### COS-176 · 🔄 Flash · e2e auth-mint миграция: `alg:none` → реальный login

> **Зачем:** приёмка COS-158 вскрыла, что e2e-хелпер `frontend/e2e/helpers/e2e_auth.ts` и
> зависящие от него спеки (notifications / web-ide / degraded / release-readiness) всё ещё
> минтит `alg:none` JWT. Verifier COS-156 теперь reject'ит `alg:none` → эти e2e-флоу
> получают 401 и краснеют. login.spec.ts (COS-158) уже честен — остальное отстало на
> один шаг (тот же класс, что закрывал COS-160 на pytest live-тестах, но для Playwright).

> **Scope:**
> (1) `helpers/e2e_auth.ts` — заменить `alg:none`/unsigned mint на реальный логин:
>     `POST /api/v1/auth/login` (dev-админ `admin@cosmoport.local` / `cosmo-admin-dev`,
>     сидирован в COS-175) → `access_token` — или use `mint_rs256` dev-ключом с тем же
>     публичным ключом, что в `jwt-keys` (для e2e без поднятого live-backend).
> (2) Перевести все спеки-потребители на реальный токен; не оставлять ни одного `alg:none`.
> (3) e2e-линия целиком зелёная против live-стенда (login + notifications/web-ide/degraded/
>     release-readiness); либо честный skip там, где live-контур не поднят.

> **Out of scope:** сам verifier/issuer (приняты); pytest live-тесты (COS-160 уже закрыл);
> миграция прод-контура.

> **Acceptance:**
> - `grep alg:none` в `frontend/e2e/` = 0 (кроме, если есть, задокументированного негатива).
> - Все e2e-спеки либо зелёные с реальным RS256, либо честный skip.
> - login.spec.ts не регрессирует (4/4).
> - tsc/build зелёные.

> **Отчёт обратно:** что заменено в `e2e_auth.ts` (логин vs mint_rs256) и почему; список
> спейся-потребителей и их статус; grep-доказательство отсутствия `alg:none`; e2e-прогон
> (числа); блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Что заменено (логин, не mint_rs256) и почему.** `helpers/e2e_auth.ts` переписан на
  **реальный login** `POST /api/v1/auth/login` (dev-admin `admin@cosmoport.local` /
  `cosmo-admin-dev`, сидирован COS-175/OpenBao): `fetchSession()` (login + кэш на процесс до
  `exp-60s`), `authHeaders()`, `e2eRecipient()` (recipient = `principal.user_id` = `sub`
  живого токена), `authenticatePage(page)` (localStorage-контракт `cosmo_auth_token`,
  COS-158), `authenticatePageOrSkip(page)` (честный skip, если auth-контур недоступен),
  `tamperSignature()` (forged-вектор для негатива). `mint_rs256`-вариант отклонён осознанно:
  приватный ключ issuer'а живёт **только в OpenBao** (`secret/cosmo/jwt-keys`, COS-173/175),
  дев-ключ `_jwt_testkey` против живого стенда не верифицируется (JWKS стенда — issuer'а),
  а тянуть приватный ключ из vault в FE-хелпер противоречит контракту. Логин — единственный
  честный живой credential.
- **Спеки-потребители и статус** (прогон против живого стенда `:5175 + :8100`):
  - `login.spec.ts` — **4/4 passed** (не тронут; регрессии нет).
  - `notifications.spec.ts` — **17/17 passed**: page-сессия и `OPS_AUTH` — живые RS256;
    `publish` теперь шлёт `--recipient <sub>` (inbox/SSE резолвят получателя из principal,
    COS-075), `unread` — по тому же recipient. Identity-тест переписан честно под одного
    seeded-пользователя: живой principal читает свой inbox (200, ≥1), **forged-signature токен
    отвергнут (401)** на unread-count и inbox.
  - `release-readiness.spec.ts` — **2/2 passed**: `OPS_AUTH/OPS_HEADERS` заполняются живым
    токеном в `beforeEach`, seed через API — под Bearer.
  - `web-ide.spec.ts` — **2 passed + 1 skip**: shell с живой сессией и surface-switching
    зелёные; tree-тест — задокументированный skip (см. Finding).
  - `degraded.live.spec.ts` — skip по дизайну (`COSMO_E2E_DEGRADED=1`, останавливает PG);
    auth-сессия добавлена в `beforeEach`, publish — на recipient живого principal.
  - `helpers/cosmo_notify_helper.py` (часть e2e-контура) — `_mint_jwt` удалён, process-вызов
    аутентифицируется реальным логином; добавлен `--recipient` (default
    `E2E_COSMO_RECIPIENT`/`admin`).
- **grep-доказательство:** `alg:none` в `frontend/e2e/**` (ts+py) = **0 hits** (literal убран
  и из комментариев; история описана словами).
- **e2e-прогон:** `npx playwright test` = **25 passed / 2 skipped / 0 failed** (1.5m);
  `npm run build` (tsc -b + vite build) = **exit 0**; `npm test` (vitest) = **5 файлов /
  81 passed / 0 failed**.
- **Pre-flight стенд-факт (не блокер, но важно):** на старте карточки живой login отдавал
  **500** — платформенный `prettyk-openbao` (dev-mode, in-memory storage) перезапустился
  ~45m назад и потерял AppRole `cosmo-app` + `secret/cosmo/*`; `cosmo-api` при этом держал
  полу-инициализированный vault-клиент (startup проглотил ошибку → 500 вместо 503).
  Восстановлено по канону COS-173: root-токен из `docker logs`, `approle` enable + policy
  `cosmo-app` + role, новые role-id/secret-id в `services/.env` (gitignored), seed
  `auth`+`jwt-keys` (`seed-auth-secrets.py`) + Layer-1 dev-секреты (`database`, `forge/gitea`,
  `ci/woodpecker`, `minio`), recreate `cosmo-api` → login/JWKS 200, RS256 kid сходится.
  Фон: dev-mode OpenBao не персистит между рестартами (volume не помогает) — инфра-хрупкость
  для отдельной карточки/оператора.
- **Finding (вне COS-176, блокирует только tree-часть web-ide-спека):** FE Web IDE
  (`api.getRepoTree/getRepoFile`) ходит в `/api/v1/repos/tree|file` **без обязательных
  CAS-параметров `branch`+`head_sha`** (контракт COS-102/103, HEAD-версия роута требует их
  `Query(...)`) → живой бэкенд отдаёт 400, дерево/файл не грузятся (пустой `file-tree`).
  Плюс фикстура `payments/api` отсутствует на текущем стенде (Gitea: только `fc-live/*`,
  binding в PG не зарегистрирован). Это pre-existing дрейф FE↔BE (не auth), закрыть
  follow-up-карточкой: интеграция workspace bootstrap/head_sha в `WebIDEShell` + сидирование
  фикстуры. В спеке зафиксирован явным `test.skip(true, reason)` — не маскировка.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: `alg:none`
> в `frontend/e2e/**` = 0 hits; живой стенд `/ready` ok; live-login 200 (RS256, 652b). Пруф
> прогона Flash: playwright **25 passed / 2 skipped / 0 failed** (login 4/4, notifications 17/17,
> release-readiness 2/2, web-ide 2+1skip); build exit 0; vitest 81/81. Skips документированы
> (degraded — by design; web-ide tree — FE↔BE дрейф → COS-179). Мелкий follow-up (не карточка):
> второй seeded-юзер для раздельных inbox-тестов identity.

---

## ✅ DONE — WORKSPACE API REF-READONLY: TREE/FILE ПО ПРОИЗВОЛЬНОМУ COMMIT (FR-004 / PK-DIR-009)

> **Источник:** PK-DIR-009 (2026-09-25) — FR-004 «Hub→IDE deep-link» финализирован Vector'ом.
> Канон: ссылка несёт `commit={sha}` как authority (immutable snapshot); полный UX деградаций —
> после IDE-карточки (Vector) и ref-readonly режима workspace API (Airlock).
> Контракт: `D:\prettyk.io\void-core\friend-requests\004-hub-ide-deeplink-transport.response.md` §3, §7.
>
> **Дыра:** чтение workspace (tree/file) — CAS-only: `head_sha` обязателен и сверяется с головой
> ветки; ветка уехала → 409. Произвольный (старый) коммит прочитать нельзя — а deep-link обязан
> открывать snapshot finding'а.
> **Почва уже есть:** compare/gate-scan ходят по произвольным ref (branch/tag/sha) через
> resolve_ref + get_tree_by_sha — ref-режим для tree/file собирается на этих примитивах.
>
> **Владелец:** Luna (выдана 2026-09-25). **Приоритет:** P1 (зависимость FR-004 UX;
> Hub может строить ссылки уже сейчас).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-177** | Luna | 6-8h | P1 | FR-004 §7 / PK-DIR-009; IDE-карточка (Vector) — параллельно | ✅ DONE — ref-режим tree/file (snapshot по commit, ref wins), CAS без регрессий, live-smoke зелёный |

#### COS-177 · Luna · Workspace API ref-readonly: tree/file по произвольному commit (immutable snapshot)

> **Исполнено (Luna, 2026-09-25):** в тот же день после planning-захода. Результат и evidence —
> worker report ниже; план/разбор — `docs/research/2026-09-25-cos-177-ref-readonly-plan.md`.

> **Зачем:** Hub→IDE deep-link несёт `commit=sha` — IDE открывает файл на ревизии finding'а.
> Сейчас чтение привязано к голове ветки (CAS): после движения ветки старый коммит отдаёт 409.
> Нужен read-only ref-режим: tree/file по произвольному commit SHA без CAS-привязки к head.

> **Scope:**
> (1) Ручки чтения workspace (tree/file) получают ref-параметр (commit SHA, полный или
>     ≥7-hex префикс): чтение идёт на этом коммите, сверка с головой ветки не выполняется
>     (ref — authority, канон FR-004 §2). CAS-путь по `head_sha` сохраняется без изменений.
> (2) Если заданы и ref, и head_sha — ref приоритетен, сверка head_sha не выполняется;
>     ни 500, ни ложный 409.
> (3) Честная деградация: несуществующий ref → typed 404, битый формат → 400, не 5xx.
> (4) Read-only by construction: ref-режим не открывает write (draft/commit по-прежнему CAS-only).
> (5) В file-ответе на ref-режиме `sha`/`base_blob_sha` — blob sha на этом коммите (не head).
> (6) Контракт: OpenAPI реген (json==yaml==live); TS-типы Web IDE синхронизированы (Vector).
> (7) Тесты: юнит (валидный commit / префикс / несуществующий / ref+head_sha / битый ref) +
>     live-smoke: ветка уехала → tree/file по ref читаются (200), по head_sha — 409.

> **Out of scope:** IDE-сторона (парсер commit/line, pristine-режим, notices — карточка Vector);
> Hub URL-строитель и скрытие ссылки (HUB-018, Arbiter); write-путь и CAS-механика (не трогаем);
> blame (отдельная BLOCKED-карточка).

> **Acceptance:**
> - После движения ветки GET tree/file по ref=<старый commit> → 200 с содержимым snapshot'а (не 409).
> - GET по несуществующему ref → typed 404, битый ref → 400; не 5xx.
> - CAS-путь (head_sha) не регрессирует: workspace-тесты + suite gate зелёные.
> - OpenAPI содержит ref-параметр; json == yaml == live.
> - Live-smoke: файл на старом коммите открывается (curl или Web IDE).

> **Отчёт обратно:** форма ref-параметра и приоритет над head_sha; статусы деградаций;
> live-smoke (коммит до/после движения ветки); реген OpenAPI; suite gate; блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **ref-параметр:** `ref` — query, optional, форма commit SHA (полный или ≥7-hex префикс);
  отдельный guard `validate_ref` — 400 называет именно `ref` (не `head_sha`). Чтения
  `/api/v1/repos/tree|file`.
- **Приоритет над head_sha:** при заданном `ref` CAS-сверка не выполняется вообще —
  `branch`/`head_sha` не требуются и игнорируются; `ref`+`head_sha` → ref wins (ни 500,
  ни ложный 409). Без `ref` CAS-путь прежний: пара branch+head_sha обязательна (иначе 400
  до forge), mismatch → 409. Оба CAS-параметра стали optional в контракте — это и есть
  контрактная дельта ref-режима.
- **Деградации:** несуществующий ref → **404** (не 5xx!), битый формат → **400**, префикс
  резолвится. Найден и закрыт Gitea-квирк 1.22.6: `/commits?sha=<unknown>` отдаёт **500
  "object does not exist"** (не 404) — `resolve_ref` нормализует его в `LookupError` (→ 404),
  настоящие 500 не глотаются (отличаются по телу ответа).
- **Read-only by construction:** write-DTO (commit/contents/draft/files/branches) `ref` не
  принимают — инвариант закреплён тестом.
- **Файл на ref:** `sha`/`baseBlobSha` = blob SHA коммита (не головы), содержимое snapshot'а.
- **Механика (новых сетевых путей нет):** существующие примитивы COS-125 —
  `resolve_ref` → `get_tree_by_sha` (tree), `read_file(ref=resolved)` (file).
- **Тесты:** новый `tests/cosmo/test_workspace_ref_readonly.py` — **20 passed** (матрица
  tree/file: валидный/префикс/несуществующий/битый/ref+head_sha/CAS-регресс + read-only
  инвариант + Gitea-квирк-нормализация + OpenAPI json==yaml==live); live-класс — **7 passed**
  opt-in. Регресс-сет workspace/openapi/forge/transfer — **637 passed / 0 failed** (по ходу
  пойман и исправлен порядок валидации: 400 раньше forge-билда, чтобы 503 не подменял 400).
- **Live-smoke (живой стенд, 2026-09-25):** реальный `git push` двух коммитов A→B («ветка
  уехала»), домен+app-binding под живым RS256-логином (dev-минтинг стенд не принимает после
  COS-157/175 — фикстура переведена на `POST /api/v1/auth/login`): tree по `ref=A` → **200**
  (дерево v1), по `head_sha=A` → **409**, по `head_sha=B` → 200; file по `ref=A` → контент v1,
  blob sha ≠ head; префикс A → 200; несуществующий ref → **404**; `ref`+stale `head_sha` → 200.
  Прогон против пересобранного `cosmo-api:local` (live `/openapi.json` содержит `ref`).
- **OpenAPI:** `docs/cosmo-openapi.{json,yaml}` регенерированы из живого `app.openapi()`
  (153 пути / 205 схем — состав не менялся); дифф = ровно дельта параметров tree/file;
  json == yaml == live (гвард `test_docs_equal_live_app_schema`). Формат регенерации
  воспроизводим байт-в-байт.
- **Suite gate:** **3546 passed / 23 skipped / 0 failed** (471s) — CAS-путь без регрессий.
- **Не закрыто этой карточкой (не блокер):** FE Web IDE всё ещё ходит в tree/file без CAS-пары
  и без `ref` (finding COS-176 Flash'а) — контракт теперь позволяет ref-only, FE-связка =
  отдельный follow-up.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_workspace_ref_readonly.py` → **20 passed / 7 skipped** (live opt-in); OpenAPI yaml несёт
> `ref` на tree и file (2 совпадения); стенд `/ready` ok, live-login 200. Live-smoke Luna:
> push A→B → tree/file по `ref=A` 200, `head_sha=A` 409, `ref`+stale `head_sha` 200,
> несуществующий 404; blob sha ≠ head. Suite gate 3546/23/0.

---

## ⬜ READY — FOLLOW-UPS: OPENBAO PERSISTENCE + FE WORKSPACE BOOTSTRAP (COS-176/177)

> **Источник:** приёмки COS-176 (Flash) и COS-177 (Luna), 25.09.2026. Обе — из вскрытых
> живых фактов: (1) рестарт dev-mode OpenBao сносит AppRole+секреты → ручное восстановление
> живого стенда; (2) FE Web IDE не передаёт CAS/ref → дерево не грузится (дрейф FE↔BE).
>
> **Выданы 25.09.2026:** COS-178 → Buddy (Platform), COS-179 → Flash (Airlock).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-178** | Buddy | 4-8h | P1 | COS-173/175 (приняты) | ✅ DONE — raft + static auto-unseal (2.6.3); рестарт без ручных шагов; sealed → 503 |
| **COS-179** | Flash | 4-6h | P1 | COS-177 (принят) | ✅ DONE — bootstrap→CAS + ref-режим; e2e 27/1/0; фикстура; legacy переведён |

#### COS-178 · Инфра: OpenBao persistence — переживание рестарта (dev-mode in-memory)

> **Зачем:** 25.09.2026 живой login отдавал 500 — платформенный `prettyk-openbao` (dev-mode,
> in-memory storage) рестартнул и потерял AppRole `cosmo-app` + `secret/cosmo/*`; cosmo-api
> держал полу-инициализированный vault-клиент. Восстановлено вручную по канону COS-173, но
> следующий рестарт снова всё снесёт (volume не помогает). Любой рестарт = ручное восстановление.

> **Scope:**
> (1) Платформенный OpenBao переводится на persistent storage backend (file/raft) — AppRole и
>     `secret/cosmo/*` переживают рестарт контейнера/хоста.
> (2) Unseal: механика (авто/ручная процедура), поведение cosmo-api в sealed-состоянии —
>     честный 503, не 500 (startup не должен глотать ошибку vault-клиента).
> (3) Миграция текущих секретов в persistent backend; повторный seed → PRESERVED.
> (4) Compose/volume канон + процедура recovery в `SECURITY_MAINTENANCE.md`.
> (5) Смоук: рестарт `prettyk-openbao` → login/JWKS 200 без ручных шагов.

> **Out of scope:** схема секретов (COS-173/174 приняты); HA-кластер; ротация.

> **Acceptance:**
> - Рестарт контейнера → AppRole + `secret/cosmo/*` на месте; login/JWKS 200 без ручных шагов.
> - Sealed → cosmo-api отвечает честным 503 (не 500).
> - Recovery/unseal задокументированы; повторный seed → PRESERVED.

> **Отчёт обратно:** backend и почему; unseal-механика; миграция; смоук рестарта; доки; блокеры.

> **Исполнение (Buddy, 2026-09-25):** ✅ закрыто, живой смоук пройден.
>
> **Backend и почему:** `raft` (persistent) + `seal "static"` (auto-unseal без KMS).
> - `file`-backend отклонён: deprecated с v2.7.0 (warning живьём на 2.6.3);
> - static seal доступен с OpenBao ≥2.5 → образ `openbao/openbao:2.2` → **2.6.3**
>   (канон обновлён: `OPENBAO-PLATFORM.md` §4/§7); миграции storage нет — инстанс
>   был пуст (dev in-memory сброшен рестартом);
> - unseal key: `services/.openbao/unseal.key` (32B, gitignored); init material
>   (root token + recovery key): `services/.openbao/init.json` (gitignored). Прод — KMS/HSM (канон §7).
>
> **Артефакты:** `services/docker-compose.openbao.yml` (2.6.3, raft, static seal, BAO_ADDR, healthcheck);
> `services/openbao/openbao.hcl`; `services/openbao/cosmo-app-policy.hcl`;
> `services/scripts/openbao-bootstrap.ps1` (идемпотентный: unseal key → up → init →
> kv-v2/approle/policy/role → AppRole creds в `.env` (PRESERVED при валидности) →
> seed 4 секретов + `seed-auth-secrets.py`); `.gitignore` (+`services/.openbao/`).
>
> **API (sealed → честный 503):** `infra/vault.py` — `VaultUnavailableError`, lazy-auth
> (`_ensure_token`: vault, оживший после старта API, подхватывается без рестарта),
> 503-детект в `authenticate`/read/write; `routes/auth.py` — `VaultError → 503`
> (login/JWKS); `startup.py` — «auth deferred», не «bootstrap skipped».
>
> **Смоук (живой, 25.09):**
> - bootstrap с нуля: init → AppRole → 6 секретов; `login → 200`, `jwks → 200`;
> - **рестарт контейнера → Sealed=false автоматически; login/JWKS 200 без ручных шагов** (×3, вкл. пересоздание);
> - **seal → login/JWKS 503** (честный, не 500) → рестарт → 200 (self-heal);
> - повторный bootstrap: всё `PRESERVED` (secret-id, 4 секрета, jwt-keys kid стабилен, auth).
>
> **Тесты:** `test_vault.py + test_auth_login.py + test_api_routes.py` = **36 passed / 4 skipped**
> (live-gated); +5 новых (sealed→VaultUnavailableError; lazy-auth; sealed→503 login/JWKS).
> Suite gate: **3559 passed / 23 skipped / 0 failed** (368s, `pytest orchestrator/tests/cosmo/ -q`).
> `SECURITY_MAINTENANCE.md` §2.5 — процедуры unseal/recovery/rotate/re-bootstrap.
>
> **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта (Airlock-эффекты). Независимая
> проверка: образ 2.6.3 + raft/static в compose (grep); `services/.openbao/` gitignored;
> focused `test_vault.py + test_auth_login.py` (+SSE resume) — 35 passed / 4 skipped; живой
> стенд: `/ready` ok, login 200 (RS256) — после COS-178 без ручных шагов. Платформенная
> приёмка (Keeper, слой секретов) — вне окна Cosmo, отмечено в статусе линии.

#### COS-179 · FE Web IDE: workspace bootstrap + CAS/ref в tree/file (FE↔BE дрейф)

> **Зачем:** Web IDE ходит в `/api/v1/repos/tree|file` без CAS-пары (`branch`+`head_sha`) и без
> нового `ref` → живой бэкенд 400, дерево пустое (finding приёмки COS-158/176, подтверждён Luna
> в COS-177). Плюс фикстура `payments/api` не засеяна (Gitea: только `fc-live/*`, binding нет).

> **Scope:**
> (1) `WebIDEShell` делает workspace bootstrap (repo+branch → head_sha) и передаёт CAS-пару в
>     tree/file; при commit в deep-link — `ref`-режим (COS-177).
> (2) Честные деградации: нет bootstrap/сессии → видимое состояние, не молча пустое дерево.
> (3) Фикстура живого стенда: `payments/api` в Gitea + app-binding в PG (или задокументированный само-сид).
> (4) e2e web-ide tree-тест: разскипан и зелёный против живого стенда.
> (5) TS-типы синхронны с OpenAPI (`ref` уже в контракте).
> (6) Вердикт Cosmo по legacy-двойнику (запрос Vector): мёртвый `POST /repos/commit` в `station/api.ts`
>     (никем не вызывается) — зачистить; живой `commit-and-run` не трогать до выноса IDE в `prettyk-ide`.

> **Out of scope:** BE ref-режим (COS-177 принят); IDE-карточка Vector (deep-link парсер/notices); auth.

> **Acceptance:**
> - Живой стенд: Web IDE открывает дерево/файл (bootstrap → CAS), без 400.
> - ref-путь FE: передача `ref` при наличии commit (совместный smoke с IDE-стороной — когда готова).
> - e2e web-ide tree-тест зелёный; vitest/tsc/build зелёные.

> **Отчёт обратно:** как встроен bootstrap; параметры; фикстура; e2e-числа; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Bootstrap (пункт 1).** `WebIDEShell` при mount и смене `repo` делает
  `GET /api/v1/repos/workspace/bootstrap?repo=…` (branch пуст → default из forge) → в state
  ложатся `branch`/`headSha`; CAS-пара уходит в `GET /tree|file`
  (`?repo=&branch=&head_sha=`); после bootstrap файл перечитывается (обновляются blob sha/base,
  `commitBranch` синхронизируется с веткой воркспейса). Смена `repo`/`ref` сбрасывает
  workspace-контекст.
- **ref-режим (COS-177, FR-004).** `commit` из deep-link протянут end-to-end:
  `DeepLinker.parseParams/IDEContext.commit` → `App` → prop `commit` в `WebIDEShell`; при
  наличии — tree/file читаются **ref-only** (`branch`/`head_sha` не шлются), в шапке виден
  `snapshot <sha7>`, запись закрыта by construction: Save / Commit & Push / Commit & Run
  disabled (+ честное сообщение при попытке), `commit-and-run` не тронут.
- **Честные деградации (пункт 2).** Ошибка bootstrap/дерева → видимый `tree-error`
  (не молча пустое дерево) и снятие спиннера; пустое дерево → `tree-empty`; ошибка файла →
  fallback-контент + `status-message` + `[ERROR]` в терминале (sha/base сбрасываются).
- **Форматы/типы (пункт 5).** Tree-ответ теперь `{entries:[{path,kind}]}` — FE маппит во
  вложенное дерево (`buildTree`, экспорт для тестов); file — `{path,content,sha,encoding,baseBlobSha}`;
  TS-типы `WorkspaceBootstrap/WorkspaceTreeEntry/WorkspaceBlob/WorkspaceTreeQuery` синхронны
  контракту (camelCase `headSha`/`baseBlobSha`).
- **Legacy-двойник (пункт 6) — важная поправка к premise.** `api.commitAndPush`
  (`POST /repos/commit`) **вызывался** UI (`handleCommitAndPush` ← модалка Commit & Push +
  палитра), т.е. «никем не вызывается» не подтвердилось. Сделана зачистка без потери фичи:
  метод удалён, модалка переведена на канонический `POST /api/v1/repos/workspace/commit`
  (COS-107/124) с CAS (`baseBlobSha` из загруженного blob; `expectedHeadSha` — при совпадении
  ветки модалки и workspace; 409 честно всплывает), после успеха — re-bootstrap (head двинулся).
  `git grep commitAndPush` в `frontend/src` = 0; `commit-and-run` не тронут (бэкенд-роут
  `POST /repos/commit` тоже не тронут — вне scope).
- **Фикстура (пункт 3).** Новый идемпотентный self-seed `services/scripts/seed-webide-fixture.py`
  (реальный RS256 login, без dev-минтинга): Gitea org `payments` + repo `api` (auto_init,
  `scenarios/auth.wire`) + app-binding `webide-api` в первом домене (или создаёт `dom-webide`).
  Живой прогон: `branch=main`, `head_sha=39b0a69a7b87…`, `tree_entries=3`.
- **e2e (пункт 4).** Tree-тест разскипнут: `web-ide.spec.ts` — **4/4 passed** (shell,
  tree bootstrap→CAS, ref-snapshot read-only, surface switching). Полная линия
  `npx playwright test` = **27 passed / 1 skipped (degraded by design) / 0 failed**.
- **Проверки:** vitest = **5 файлов / 86 passed** (WebIDEShell 15: +4 новых — bootstrap→CAS,
  ref-режим/read-only, видимая ошибка дерева, `buildTree`; +1 commit-путь в `/workspace/commit`);
  `tsc -b` = 0; `npm run build` (tsc -b && vite build) = **exit 0**.
- **Finding (вне scope COS-179):** `api.saveRepoFile` (`PUT /api/v1/repos/file`) — на бэкенде
  есть только `GET /file`; живая проверка даёт **405 Method Not Allowed**. Save-кнопка и
  gutter-run `.wire`-шагов ходят этим мёртвым путём → нужен follow-up (перевести на
  workspace-commit/draft/files или снять кнопку).
- **Контекст:** во время работы Buddy вёл COS-178 — стенд флапал окнами (login 503,
  `prettyk-openbao` пересоздавался на persistent backend); live-прогоны выполнены после
  восстановления login. Файлы Buddy/Luna не трогал.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка:
> `git grep commitAndPush` в `frontend/src` = 0; живой стенд login 200. Пруфы Flash:
> playwright 27/1/0 (web-ide 4/4, включая tree bootstrap→CAS и ref-snapshot read-only);
> vitest 86 passed; tsc 0; build exit 0; фикстура `payments/api` (head `39b0a69a…`).
> Legacy-поправка зачтена: `commitAndPush` вызывался UI — переведён на канонический
> workspace-commit без потери фичи. Finding `saveRepoFile` 405 → COS-182.

---

## ⬜ READY — IDE CONTRACT FOLLOW-UPS: TYPED 409 COMMIT + SAVE-PATH (COS-181/182)

> **Источник:** inbox Vector (2026-09-25, §7 «Серверный follow-up»): IDE-клиент (`prettyk-ide`)
> уже построил resume/merge-машинерию (IDE-CORE-017/019); серверные половины — зона Airlock.
> Оба follow-up — «нарежь карточку сам» (мандат Vector), клиент не блокируется.
>
> **Выданы 25.09.2026:** COS-180 → Luna (✅ DONE), COS-181 → Luna (✅ DONE), COS-182 → Flash (✅ DONE).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-180** | Luna | 4-6h | P1 | COS-088 (принят), COS-109 | ✅ DONE — SSE id + backlog replay: реконнект без потерь/дублей, gap→resync, live-smoke 12/12 |
| **COS-181** | Luna | 3-4h | P1 | COS-124 (принят) | ✅ DONE — typed 409 (kind/expected/actual/paths), stale→409 до записей, live 10/10 |
| **COS-182** | Flash | 4-6h | P1 | finding COS-179 | ✅ DONE — Save→draft (COS-110), gutter-run честно wired, e2e 29/1/0 |

#### COS-180 · SSE resume логов прогона: event id + backlog replay

> **Зачем:** IDE-клиент (IDE-CORE-017: `Last-Event-ID` resume + dedupe + resync) готов, но
> серверный лог-стрим `_run_logs_stream` (COS-109) не эмитит SSE `id` и не делает backlog-replay —
> resume по id работает вхолостую. Распространить паттерн COS-088 (Valkey sse_backlog) на логи.

> **Scope:**
> (1) Лог-стрим эмитит SSE `id` (монотонный event cursor).
> (2) Replay по `Last-Event-ID` на реконнекте из Valkey backlog — как в run/domain/notification
>     стримах (COS-088): пропущенные события приходят, обработанные не дублируются.
> (3) Тесты: unit (курсор, replay-порядок, дедуп) + live (реконнект посреди прогона → пропуск
>     без потерь и дублей).
> (4) Совместимость: существующие потребители лог-стрима не регрессируют.

> **Out of scope:** клиентская часть (Vector, готова); PTY epic; run/domain/notification стримы (COS-088).

> **Acceptance:**
> - Реконнект с `Last-Event-ID` получает пропущенные лог-события в порядке, без дублей; события несут `id`.
> - Suite gate без регрессий; live-смоук реконнекта проведён.

> **Отчёт обратно:** форма id/курсора; механизм replay и TTL; live-смоук (сценарий реконнекта);
> тесты (числа); блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **Форма id/курсора:** каждое data-событие (`step_start`/`log_chunk`/`step_finish`/`run_finish`)
  публикуется в backlog (**kind `runlog`**, key = run_id) и несёт SSE `id` == XADD-id (инвариант
  COS-088); первым в стриме идёт `stream_backlog`-флаг (mode `valkey|memory`, без id). Отдельный
  kind — иначе replay логов смешался бы с run-событиями на общем ключе.
- **Replay и TTL:** на реконнекте с `last_event_id` (query сильнее заголовка) читается всё
  удержанное окно backlog (новый `sse_backlog.read_window`); last-id найден → недоставленный
  хвост реплеится с исходными id, из окна восстанавливаются курсоры (batch, step) — состояние
  шага + счётчик доставленных строк. Live-loop после реконнекта догоняет только новые строки →
  **без дублей и потерь**. TTL/лимиты как COS-088: sliding TTL 900 c, MAXLEN ≈2000 на run-ключ.
  Gap (last-id вне окна) / backlog недоступен → `resync`-событие (не тишина); свежий коннект —
  прежний полный catch-up. Честная граница: при вытеснении записей ДО last-id возможен повторный
  догон части логов (счётчик занижен) — потерь нет; вне окна непрерывность не подтверждается.
- **`run_finish`:** на реконнекте не дублируется, если уже лежит в backlog (replay его доставит,
  повторная эмиссия подавлена); свежий коннект к терминальному прогону эмитит его с id.
- **Совместимость:** payload'ы/xterm-формат не менялись (только SSE-конверт получил `id`);
  COS-109-тесты обновлены под флаг; `error`-диагностики остаются без id (не replay-able).
- **Тесты:** новый `tests/cosmo/test_sse_logs_resume.py` — **9 passed** (флаг+уникальные id,
  replay без дублей, порядок replay, gap→resync, backlog-unavailable→resync, no-dup run_finish,
  восстановление курсоров, compat-catch-up); `test_sse_logs_stream.py` — 11 passed (обновлён);
  SSE-контур (`sse/notification/logs`) — **320 passed / 0 failed**.
- **Live-смоук (живой HTTP SSE + живой Valkey backlog):** **12/12 PASS** — conn1 (last_id=A) →
  флаг + `X-Cosmo-Backlog: valkey`, replay нет; «офлайн»-событие B → conn2 (last_id=A) →
  **реплей B ровно один раз с исходным id**, повторной отдачи A нет; conn3 (last_id=B) →
  повторного B нет; conn4 (битый last-id) → **resync reason=gap** по проводу.
  Скрипт: `D:\Infra\Temp\opencode\cos180_live_smoke.py` (временный артефакт, не в репо).
- **Стенд-факт (не блокер, вне карточки):** login отдавал **500** — `prettyk-openbao` (dev-mode,
  in-memory) снова потерял секреты (зона COS-178/Buddy); для смоука `ot1`-тикет посеян напрямую
  в Valkey в формате `sse_tickets` (валидация на сервере реальная, GETDEL).
- **OpenAPI:** реген из живого `app.openapi()` (дифф = дельта описания лог-эндпоинта;
  json==yaml==live — контракт-гвард COS-177 поймал рассинхрон, это его работа). Граница живой
  проверки: на стенде нет активированных Woodpecker-пайплайнов (Woodpecker DB пуста) — деривация
  чанков из реального пайплайна не воспроизводилась (покрыта unit-тестами); по проводу проверены
  id/replay/дедуп/gap.
- **Suite gate:** **3559 passed / 23 skipped / 0 failed** (370 s). **Блокеры:** нет.
  Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_sse_logs_resume.py` + vault/auth — 35 passed / 4 skipped (вкл. 9 resume); живой стенд
> ok. Пруфы Luna: SSE-контур 320 passed; live-smoke 12/12 (реальный HTTP SSE + Valkey: реплей
> ровно раз с исходным id, gap→resync); TTL 900s / MAXLEN ~2000; `run_finish` без дублей.
> Стенд-факт login 500 — закрыт COS-178 (проверено живьём: login 200).

#### COS-181 · Typed 409 + `expected_head_sha` на multi-file commit (merge-loop)

> **Зачем:** IDE merge-loop (IDE-CORE-019) ждёт branch-head conflict. Атомарный
> `POST /workspace/commits` (COS-124) не принимает явный `expected_head_sha`; 409 — plain-string
> (клиент парсит строки шаблонов). Нужен явный optimistic concurrency + структурированный конфликт.

> **Scope:**
> (1) Optional `expected_head_sha` в multi-file commit-запрос + precondition: несовпадение с головой
>     ветки → 409 до любых записей.
> (2) 409 structured: код `WORKSPACE_CONFLICT` + `expected_sha` / `actual_sha` (machine-readable;
>     не три plain-string шаблона).
> (3) Обратная совместимость: без `expected_head_sha` — прежнее поведение (per-file CAS).
> (4) Тесты: устаревший head → структурированный 409; актуальный → успех; совместимость без поля.
> (5) OpenAPI реген (json==yaml==live).

> **Out of scope:** клиентский merge (Vector — досинхронизируется после); legacy `POST /workspace/commit`
> (COS-107) не трогаем.

> **Acceptance:**
> - Commit с устаревшим `expected_head_sha` → 409 `WORKSPACE_CONFLICT` с `expected_sha`/`actual_sha`.
> - Commit с актуальным → успех; без поля → прежнее поведение.
> - OpenAPI обновлён; suite gate зелёный.

> **Отчёт обратно:** форма структуры 409; тесты; реген; блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **Форма структуры 409** (единый error-контракт COS-058, `transfer_error_handler` разворачивает):
  `{"error": {"code": "WORKSPACE_CONFLICT", "message": <human>, "details": {"kind":
  "concurrent|exists|missing", "expected_sha": <sha|null>, "actual_sha": <sha|null>,
  "paths": [<conflicting path>]}}}`. `kind` — словарь клиентского `WorkspaceConflictKind`
  (IDE-CORE-005): `concurrent` — branch-level (head/forge), `exists`/`missing` — файловые;
  `paths` для branch-level пусто.
- **Precondition:** `WorkspaceCommitRequest.expectedHeadSha` (optional; полный sha или ≥7-hex
  префикс): расхождение с головой ветки → typed 409 **до любых чтений/записей файлов**
  (живой пруф: файл-зонд не создан, голова ветки не сдвинулась).
- **Plain-string шаблоны закрыты все три:** create-exists (`kind=exists`, `actual_sha` = blob sha),
  update/delete-missing (`kind=missing`), forge-конфликт (`kind=concurrent`, `actual_sha` — свежий
  best-effort re-fetch головы; недоступность forge не маскирует конфликт).
- **Совместимость без поля:** precondition не применяется, per-file CAS работает как раньше
  (форма 409 меняется на typed — цель карточки); текущий IDE-клиент (string-matching
  `parseCommitConflict`) на новую форму даёт fallback `kind=concurrent` (refresh+retry),
  досинк запланирован (примечание IDE-CORE-019).
- **Границы:** per-file `base_blob_sha` в запросе COS-124 нет → в файловых конфликтах
  `expected_sha=null` (будущий шаг клиента); legacy `POST /workspace/commit` (COS-107) не тронут.
- **Тесты:** новый `tests/cosmo/test_workspace_commit_conflict.py` — **20 passed** (stale→typed 409
  без файловой работы; fresh полный/префикс→201; без поля — per-file CAS typed; forge→concurrent
  со свежим actual; битый sha→422; DTO; форма конверта); `test_workspace_commits_api.py` — 4
  assertion'а обновлены под typed-форму (30 passed); регресс-сет workspace/openapi/sse/forge —
  **807 passed / 0 failed**.
- **Реген:** `docs/cosmo-openapi.{json,yaml}` из живого `app.openapi()` — `expectedHeadSha`
  в схеме запроса; json==yaml==live.
- **Live-smoke (живой стенд, реальный login+HTTP, read-only):** **10/10 PASS** — bootstrap
  `payments/api` → stale `expectedHeadSha` → typed 409 (`code/kind/expected/actual/paths/message`),
  файл-зонд **не создан** (404), голова **не сдвинулась**, битый sha → 422.
  Скрипт: `D:\Infra\Temp\opencode\cos181_live_smoke.py` (временный артефакт, не в репо).
- **Для досинка (Vector):** форма выше — стабильный контракт; переход клиента на structured 409
  не требует новых BE-изменений.
- **Suite gate:** **3574 passed / 23 skipped / 0 failed** (393 s). **Блокеры:** нет.
  Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_workspace_commit_conflict.py` + `test_transfer_sbom.py` — 49 passed; `expectedHeadSha`
> в OpenAPI (yaml/json, 2 места); стенд login 200. Пруфы Luna: typed-конверт по канону COS-058
> (kind/expected/actual/paths), stale → 409 до записей (файл-зонд не создан), live-smoke 10/10,
> регресс-сет 807/0. Для досинка Vector: форма стабильна; серверных изменений не требует.

#### COS-182 · FE Web IDE: save-path — мёртвый `PUT /repos/file` (405), Save-кнопка и gutter-run

> **Зачем:** finding приёмки COS-179: `api.saveRepoFile` (`PUT /api/v1/repos/file`) — живая
> проверка 405 (на бэке только GET). Save-кнопка и gutter-run `.wire`-шагов ходят мёртвым
> путём (нельзя молча уверенно «сохранять»).

> **Scope:**
> (1) Разобрать оба мёртвых пути (Save-кнопка, gutter-run `.wire`) и перевести на живые
>     канонические ручки (workspace commit/draft/files — по факту контракта).
> (2) Новых BE-ручек не создавать; если неизбежен новый контракт — стоп и эскалация
>     (BE-поверхность workspace занята COS-181).
> (3) Честная деградация: ни один путь не завершается «успехом» при мёртвом вызове.
> (4) Тесты: FE-путь (vitest) + применимый e2e; tsc/build.

> **Out of scope:** workspace commits (COS-181, Luna); ref-режим (COS-177); новый whole-file
> save API; commit-and-run.

> **Acceptance:**
> - Save-кнопка и gutter-run не дают 405 и не врут об успехе (реальный результат либо явная ошибка).
> - Живой прогон против стенда; vitest/tsc/build зелёные.

> **Отчёт обратно:** какие пути на что переведены; почему без BE; тесты; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Save-кнопка → серверный черновик.** `handleSaveFile` больше не зовёт мёртвый
  `PUT /api/v1/repos/file`: новый `api.saveWorkspaceDraft` → `PUT /api/v1/repos/workspace/draft`
  (COS-110: `{repo, branch, path, content, baseBlobSha?}` → 201). Семантика честная —
  «Черновик сохранён на сервере» (WIP в Valkey, TTL 7d), `localStorage`-черновик очищается,
  `originalCode = saved.content`; ошибка → «Не сохранено: …» + `[ERROR]` в терминале
  (никакого ложного успеха). Мёртвый `api.saveRepoFile` удалён — `git grep saveRepoFile` = 0.
- **Gutter-run `.wire` — честный и наконец подключённый.** Обнаружено, что `handleRunStep`
  вообще не был wired к Monaco (dead function) и звал тот же мёртвый сохранение-путь.
  Теперь: глифы ▶ реально подключены (`editor.onMouseDown` → `MouseTargetType.GUTTER_GLYPH_MARGIN
  = 2`, через ref без runtime-импорта monaco); клик сохраняет серверный черновик и явно
  пишет `[RUNNER] Шаг не исполнен: серверный runner .wire в Airlock не подключён
  (PTY epic в бэклоге)`; ложный `[SUCCESS] ✅ Step completed` удалён. Hover глифа и hint в
  таб-баре переписаны честно («runner не подключён — сохранит черновик»).
- **Почему без BE (пункт 2).** Канонический контракт черновика уже существует (COS-110,
  Valkey; 503 при недоступности) — новых ручек не создавал, BE-поверхность COS-181 не тронута.
- **Честные деградации (пункт 3).** Snapshot-ref → «только чтение» (без записи); нет
  workspace-сессии → «сохранение недоступно»; Valkey 503 → «Не сохранено: …» (тест).
- **Тесты (пункт 4).** `WebIDEShell.test.tsx` — **17 passed** (+4: Save→draft с точным body и
  проверкой, что `PUT /repos/file` не дёргается; 503 → честная ошибка без «сохранено»;
  честный gutter-hint; прежние 15 без регрессий). Контур `npm test` = **5 файлов / 88 passed**;
  `tsc -b` = 0; `npm run build` exit 0.
- **e2e (live, пункт «живой прогон»).** `web-ide.spec.ts` +2: (1) реальная правка Monaco →
  Save → 201 + **чтение черновика с сервера через `GET /workspace/draft`** (контент совпал),
  ноль `PUT /repos/file`, гигиена `DELETE`; (2) клик по `.cosmo-gutter-run-icon` → видимый
  честный лог про отсутствие runner'а, `Step L… completed` отсутствует, статус «Шаг не исполнен
  (runner недоступен) — черновик сохранён». Полная линия `npx playwright test` =
  **29 passed / 1 skipped (degraded by design) / 0 failed**.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка:
> `git grep saveRepoFile` в `frontend/src` = 0; стенд login 200. Пруфы Flash: Save → серверный
> draft (COS-110) с чтением черновика обратно (e2e live +2); gutter-run честно wired, ложный
> `[SUCCESS]` удалён; vitest 88, tsc 0, build 0; playwright 29/1/0. Попутный подъём dead
> function — зачтён. Мёртвых путей записи не осталось.

> **Кандидат (не нарезан):** PTY epic — интерактивный runner exec (P2/P3 security epic,
> wire-протокол `runnerTty` согласуется при подъёме контура).

---

## ⬜ READY — SUPPLY-CHAIN: GRYPE-ВИЗОР (COS-183)

> **Источник:** остаточный follow-up build+deploy («честный `available=false` → боевой grype»);
> после боевых trivy (COS-171) и syft (COS-172). Пара к SBOM-инвентарю (COS-155).
>
> **Выдан:** COS-183 → Buddy (✅ DONE).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-183** | Buddy | 4-6h | P2 | COS-171/172 (приняты), COS-155 | ✅ DONE — grype 0.119.0 + offline DB; available=true (6 vulns); бандл 24/24 checksums |

#### COS-183 · Инфра: боевой grype-визор вместо честного `available=false`

> **Зачем:** `generate_vuln_report` (grype-визор) в образе отсутствует → `vuln_summary.available=false`
> + reason. Боевой grype даёт реальный vuln-отчёт по SBOM; закрывает последний «честный заглушечный»
> маркер supply-chain контура.

> **Scope:**
> (1) grype-бинарь в образ `cosmo-api` (детерминированная версия, digest-pin где возможно — как COS-171/172).
> (2) Offline DB: предзагрузка + airgap-канон (0 внешних запросов в рантайме).
> (3) Реальный прогон: grype по SBOM/образу → vuln-отчёт; `available=true` с реальными данными
>     (findings > 0 или честно пусто, но не заглушка).
> (4) Airgap-бандл: grype + DB.
> (5) Тесты: focused (бинарь/DB есть/нет → маркер) + live opt-in (self-skip оффлайн).
>     Негатив: нет бинаря/DB → честный `available=false` (не фейк).

> **Out of scope:** trivy/syft (приняты COS-171/172); source-SAST; promotion.

> **Acceptance:**
> - Внутри контейнера `grype version`; vuln-отчёт с `available=true` и реальными данными.
> - Airgap-бандл несёт grype + DB; негатив честный; suite gate без регрессий.

> **Отчёт обратно:** версия/digest; DB; прогон (числа); негатив; состав бандла; блокеры.

> **Исполнение (Buddy, 2026-09-25):** ✅ закрыто — grype боевой, `available=true` с живыми данными.
>
> **Версия/digest:** grype **0.119.0** (linux_amd64), sha256 `3fa2dc4b…04c9b` — сверен фактически при скачивании и зашит ARG в `services/cosmo-api.Dockerfile` (сборка падает при несовпадении; релиз anchore/grype v0.119.0).
>
> **DB (offline):** `grype db update` на этапе сборки → `/var/lib/grype` (schema v6, ~2.9GB unpacked; seed-tar **510MB** в образе `/opt/grype-db-seed.tar.gz`); распакованную копию из образа удаляем (`rm -rf`) — образ 2.7GB вместо 5.8GB; entrypoint засевает DB в volume `cosmo_grype_cache` при первом старте (идемпотентно). Рантайм-канон: `GRYPE_DB_AUTO_UPDATE=false` + `GRYPE_DB_VALIDATE_AGE=false` (уже в `transfer/sbom.py`) + `GRYPE_DB_CACHE_DIR=/var/lib/grype` (ENV образа == compose == volume). Проверено: скан с **отключённой сетью** — идентичный JSON.
>
> **Прогон (живой, контейнер cosmo-api):** `grype --version` → `grype 0.119.0`; прод-функция `generate_vuln_report` на игрушечном SBOM (requests 2.19.0) → `source=grype`, **5 matches**; прод-функция `generate_sbom_inventory` (target=site-packages, реальные 4642 компонента syft) → `vuln_summary.available=true, total=6` (medium=5, low=1; первый: `GHSA-wf93-45jw-7689` pip 25.0.1 → fixed 26.1.2).
>
> **Негатив:** без бинаря → `source="none"`, `available=false` + reason (focused `test_transfer_sbom.py::TestGrypeReport`, вкл. новый env-inherit кейс); live-тест `test_grype_scan_live.py` — self-skip, когда grype/DB нет (на хосте без grype — skip; в контейнере — runs).
>
> **Бандл:** `cosmoport2-v0.2.0-airgap.tar.gz` (**1851.7 MB**) — несёт `tools/grype_0.119.0_linux_amd64.tar.gz` (29MB) + `tools/grype-db-0.119.0.tar.gz` (486MB) + manifest-записи `grype`/`grype-offline-db`; verify-bundle: **checksums 24/24 OK** (grype-файлы совпали с pin). Попутно починены дефекты сборки/верификации: (1) PS 5.1 EAP=Stop + native stderr убивал сборку на здоровом `docker build` → EAP=Continue + $LASTEXITCODE (урок COS-064); (2) контексты build-образов (`..`) не соответствовали layout — `cosmo-api` собирался из `D:\` (латентный баг; исправлено на `.`/`frontend`); (3) `minio/minio` снят с Docker Hub (`pull access denied`) → fallback на локальный образ; (4) checksums.sha256 писался CRLF → `verify-bundle.sh` на Linux видел 25 MISSING → теперь LF (+strip `\r` в верификаторе); (5) `openbao/openbao` в бандле обновлён 2.2 → 2.6.3 (синхронизация с COS-178).
> **Хвост (не из диффа):** compose-чек verify-bundle.sh («любые http://») — всегда-FAIL на текущем compose (внутренние docker-URL в env/healthcheck); не менял (критерий — политика PO), кандидат в отдельную карточку.
>
> **Тесты:** `test_transfer_sbom + test_sbom_inventory + test_api_routes + test_build_modes` = **100 passed**; полный cosmo-сьют = **3575 passed / 24 skipped / 0 failed** (347s).
> **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: `docker exec
> cosmo-api grype --version` → 0.119.0; focused (workspace-conflict + transfer-sbom) — 49 passed;
> стенд login 200. Пруфы Buddy: прод-функции на реальном SBOM → `available=true` (6 vulns);
> offline-скан идентичен (airgap); бандл 1851.7MB, checksums 24/24; попутно вычищено 5 дефектов
> бандл-процесса (в т.ч. латентный контекст сборки `cosmo-api` из `D:\`). Хвост verify-bundle
> («любые http://») → COS-184.

---

## ⬜ READY — WAVE 3: BUNDLE-VERIFY + COMMIT-CONFLICT FOLLOW-UPS (COS-184/185/186)

> **Источник:** приёмки COS-181/182/183 (25.09.2026). Все три — прямые продолжения принятого:
> честность бандл-верификации; точные файловые конфликты merge-loop; typed 409 в собственном FE.
>
> **Выданы 25.09.2026:** COS-184 → Buddy (✅ DONE), COS-185 → Luna (✅ DONE), COS-186 → Flash (✅ DONE).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-184** | Buddy | 2-3h | P2 | COS-183 (принят) | ✅ DONE — структурный whitelist (loopback+docker-имена); 24/24; негативы ловятся |
| **COS-185** | Luna | 3-4h | P2 | COS-181 (принят) | ✅ DONE — per-file `base_blob_sha` → `expected_sha` файловых конфликтов, live-smoke 13/13 |
| **COS-186** | Flash | 3-4h | P2 | COS-181/179 (приняты) | ✅ DONE — typed-конверт в FE, kind-aware UX + refresh/retry, live-e2e конфликта |

#### COS-184 · Bundle-verify: честный compose-чек (внутренние http:// не фейлят)

> **Зачем:** compose-чек `verify-bundle.sh` («любые http://») — предсуществующий всегда-FAIL на
> текущем compose: внутренние docker-URL (env/healthcheck) легитимны, но триггерят чек. Ложный
> FAIL обесценивает верификацию бандла.

> **Scope:**
> (1) Честный критерий: внутренние docker-URL (сервисные хосты/healthcheck) не считаются
>     нарушением; внешние незаявленные `http://` — считаются (или задокументированный whitelist).
> (2) verify-bundle на текущем бандле — зелёный там, где должен; красный на реальном нарушении.
> (3) Попутно (одна строка, та же зона services): `nexus-core` → `void-core` в
>     `services/docker-compose.openbao.yml` (канон-ссылка; permission-хвост Cosmo).
> (4) Смоук: verify на актуальном compose + негативный кейс (реальное внешнее http:// ловится).

> **Out of scope:** сборка бандла (COS-183 принят); compose-содержимое по существу.

> **Acceptance:** verify-bundle на текущем compose не даёт ложных FAIL; реальное внешнее
> `http://` по-прежнему ловится; ссылка void-core поправлена.

> **Отчёт обратно:** критерий; whitelist (если есть); смоук; блокеры.

> **Исполнение (Buddy, 2026-09-25):** ✅ закрыто.
>
> **Критерий:** структурный whitelist без явного списка — внутренними считаются
> loopback (`localhost`/`127.0.0.1`/`0.0.0.0`/`host.docker.internal`) и docker-сервисные
> имена БЕЗ точки в host (`cosmo-*`, `prettyk-*` — по RFC hostname). Нарушение —
> `http(s)://` на host с точкой (внешний домен) + строки `pip install|npm install`.
> При FAIL печатается список найденных хостов (диагностика).
>
> **Смоук (распакованный бандл, bundle-out):**
> - позитив (текущий compose; хосты: `localhost`×6, `cosmo-*`×7, `prettyk-openbao`×1) →
>   **Matched: 24, Failed: 0, integrity OK**;
> - негатив-1 `# probe https://evil.example.com/x` → **FAIL «compose references external hosts: evil.example.com»**; строка убрана;
> - негатив-2 `# pip install requests` → **FAIL «runtime install commands (pip/npm)»**; строка убрана;
> - после — повторный позитив чистый; бандл пересобран с новым скриптом, финальный verify
>   на каноническом артефакте — **24/24, integrity OK** (exit 0).
>
> **nexus-core → void-core:** уже исправлено в COS-178 (при перезаписи `docker-compose.openbao.yml`);
> проверено — `nexus-core` в `services/` отсутствует, канон-ссылка ведёт на
> `D:\prettyk.io\void-core\OPENBAO-PLATFORM.md`.
>
> **Файлы:** `services/scripts/verify-bundle.sh` (только compose-чек; checksums/CRLF-фикс — из COS-183).
> Python-код не затронут; смежный прогон `-k "sbom or bundle"` = **173 passed / 1 skipped**.
> **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: прогон
> `-k "sbom or bundle"` — **173 passed / 1 skipped**; живых `nexus-core` в репо нет (только
> исторические записи бэклога). Пруфы Buddy: структурный whitelist (loopback + docker-имена
> без точки), позитив 24/24 integrity OK, оба негатива FAIL, финальный verify на пересобранном
> бандле 24/24. Ложный always-FAIL устранён.

#### COS-185 · Per-file `base_blob_sha` в multi-file commit (точные файловые конфликты)

> **Зачем:** follow-up COS-181: в конфликтах `exists`/`missing` `expected_sha=null` — в запросе
> multi-file commit (COS-124) нет per-file базы. Merge-loop для точного 3-way хочет видеть
> ожидаемую файловую базу (IDE-CORE-005 упоминает `base_blob_sha`).

> **Scope:**
> (1) Optional per-file `base_blob_sha` в multi-file commit-запросе (валидация формата).
> (2) При конфликте `exists`/`missing` — `expected_sha` = переданная база (не null); без неё —
>     прежнее поведение (null).
> (3) Совместимость: старые клиенты не ломаются; legacy `POST /workspace/commit` не трогаем.
> (4) Тесты: конфликт с базой → `expected_sha` в конверте; без базы → null; OpenAPI реген.

> **Out of scope:** клиентский merge (Vector, досинк IDE-CORE-019); branch-level CAS (COS-181).

> **Acceptance:** файловый конфликт с переданной базой несёт `expected_sha`; без базы — как
> раньше; OpenAPI обновлён; suite gate зелёный.

> **Отчёт обратно:** форма поля; конверт; тесты; реген; блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **Форма поля:** `WorkspaceFileChange.baseBlobSha` — optional, полный sha или ≥7-hex префикс
  (`validate_head_sha`, `""`→None); зеркало legacy `WorkspaceContentsFileChange` (COS-107) —
  имена/семантика совпадают. Новых precondition'ов нет: поле — носитель базы, не CAS-проверка
  (branch-level CAS остаётся за `expectedHeadSha`, COS-181).
- **Конверт:** файловые конфликты несут `expected_sha = переданная база`:
  `exists` → `expected_sha`=база + `actual_sha`=текущий blob; `missing` → `expected_sha`=база +
  `actual_sha`=null; `paths=[файл]`; код/структура конверта COS-181 не менялись.
- **Совместимость:** без поля — прежнее `expected_sha=null`; поле принимается и на успешном
  пути (игнорируется); `expectedHeadSha` (branch-level) приоритетен и проверяется до файлов;
  битый формат базы → 422 (записей нет); legacy `POST /workspace/commit` не тронут.
- **Тесты:** `test_workspace_commit_conflict.py` **+13** (5 DTO + 7 route + 1 контракт;
  файл целиком 33 passed; с COS-124-файлом 63 passed); регресс-сет workspace/openapi/sse/forge —
  **820 passed / 0 failed**.
- **Реген:** `docs/cosmo-openapi.{json,yaml}` из живого `app.openapi()` — `baseBlobSha` в схеме
  `WorkspaceFileChange`; json==yaml==live.
- **Live-smoke (живой стенд, реальный login+HTTP, read-only):** **13/13 PASS** —
  `payments/api`: create на существующий `README.md` с базой → 409 `exists`
  (`expected_sha`=база, `actual_sha`=blob, `paths=[README.md]`); update на несуществующий путь
  с базой → 409 `missing` (`expected_sha`=база, `actual_sha`=null); без базы → `expected_sha=null`;
  битый → 422; голова ветки не сдвинулась.
  Скрипт: `D:\Infra\Temp\opencode\cos185_live_smoke.py` (временный артефакт, не в репо).
- **Suite gate:** **3588 passed / 24 skipped / 0 failed** (433 s). **Блокеры:** нет.
  Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_workspace_commit_conflict.py` — 28 passed / 0 failed; `baseBlobSha` в OpenAPI
> (`WorkspaceFileChange`); стенд login 200. Пруфы Luna: `exists`/`missing` несут
> `expected_sha`=переданная база, без базы — null; live-smoke 13/13; регресс 820/0;
> suite gate 3588/24/0.

#### COS-186 · FE: typed 409 `WORKSPACE_CONFLICT` в commit-модалке (kind-aware UX)

> **Зачем:** follow-up COS-179/181: наш FE — тоже клиент workspace-commit, но в `frontend/src/cosmo`
> обработки `WORKSPACE_CONFLICT` нет (grep = 0). Typed-конверт стабилен (COS-181) — довести
> конфликт до понятного UX: `concurrent` → «ветка ушла вперёд» + refresh/re-bootstrap + повтор;
> `exists`/`missing` → конфликтующие файлы.

> **Scope:**
> (1) Обработка typed 409 в commit-пути FE (модалка/палитра): kind-aware сообщение, без сырого detail.
> (2) `concurrent` → действие «обновить workspace» (re-bootstrap) и повторная попытка.
> (3) Честная деградация: не-409 — прежнее поведение; успех/409 различимы.
> (4) Тесты: vitest (kind-aware ветки) + применимый e2e; tsc/build.

> **Out of scope:** серверная форма (COS-181 принят); клиент Vector (`prettyk-ide` — своя зона).

> **Acceptance:** typed 409 даёт понятный UX и различимые действия; vitest/tsc/build зелёные;
> e2e на конфликт (если воспроизводим на живом стенде).

> **Отчёт обратно:** как обработан конверт; сценарии; тесты; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Как обработан конверт.** `apiFetch` научился распознавать typed-конверт COS-058 и бросать
  `CosmoApiError {status, code, details}`; принимаются **обе формы**: live top-level
  `{"error": {code,message,details}}` (факт COS-181, проверено живым вызовом) и FastAPI-wrapper
  `{"detail": {"error": …}}` (backward-compat). Plain detail/ошибки — прежнее поведение
  (`Error`), успех/409 различимы. Экспорт: `CosmoApiError`, `parseCosmoErrorEnvelope`,
  `WorkspaceConflictDetails`, `WorkspaceConflictKind`.
- **Commit-путь переведён на typed-ручку.** FE коммитил singular `/workspace/commit` (plain 409,
  без конверта) — теперь `POST /api/v1/repos/workspace/commits` (COS-124 + COS-181):
  `fileChanges:[{path,content,action:'update'}]` + `expectedHeadSha`; ответ
  `{sha, htmlUrl, authoredAt, filesChanged}`. Это единственная ручка с typed 409 — acceptance
  достижим **без BE-правок** (серверная форма COS-181 не тронута).
- **Kind-aware UX (модалка Commit & Push).** Конфликт рендерится в блоке
  `data-testid="commit-conflict"`:
  - `concurrent` → «Конфликт: ветка ушла вперёд» + «ожидался X, сейчас Y» + кнопка
    **«Обновить workspace и повторить»** — `re-bootstrap` (`ensureWorkspace` + `fetchTree`) и
    повтор коммита с **новым** `headSha` (fresh workspace передаётся явно, stale closure
    исключён);
  - `exists` / `missing` → «Файлы уже существуют / отсутствуют в ветке: …» (conflicting paths) +
    кнопка «Обновить workspace» (без retry);
  - сырой detail не показывается, модалка остаётся открытой, конфликт сбрасывается при
    открытии модалки/палитры и при успехе.
- **Тесты.** `WebIDEShell.test.tsx` — **19 passed**: тест 15 обновлён под plural-ручку
  (`fileChanges` + `expectedHeadSha`), новые 18 (concurrent: конверт без сырого detail, refresh →
  повторный bootstrap → retry c `sha256:head2`, успех) и 19 (missing: пути конфликта,
  кнопка без «повторить»); 18 использует live-форму конверта top-level, 19 — backward
  `detail.error`. Контур `npm test` = **5 файлов / 90 passed**; `tsc -b` = 0; `npm run build`
  exit 0.
- **e2e (live, воспроизводимо).** Новый тест в `web-ide.spec.ts`: правка README в Monaco →
  модалка → внешний пуш (Gitea contents probe-файл) уводит head → «Запушить» → видимый
  typed-конфликт («Ветка ушла вперёд», без сырого detail) → «Обновить workspace и повторить» →
  «Запушено»; контент подтверждён через Gitea raw по `main`, probe-файл удалён (гигиена).
  Полная линия `npx playwright test` = **30 passed / 1 skipped (degraded by design) / 0 failed**.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: `CosmoApiError`
> + `parseCosmoErrorEnvelope` в `station/api.ts`, kind-aware ветка в `WebIDEShell.tsx`;
> стенд login 200. Пруфы Flash: обе формы конверта (top-level + `detail`-wrapper); plural-ручка
> с `fileChanges` + `expectedHeadSha`; live-e2e конфликт → refresh → retry → успех (Gitea raw);
> playwright 30/1/0; vitest 90; tsc/build 0. Наш FE больше не парсит строки.

---

## ⬜ READY — WAVE 4: E2E IDENTITY, WOODPECKER LIVE-КОНТУР, PTY-ДИЗАЙН (COS-187/188/189)

> **Источник:** хвосты приёмок волн 2-3 и стенд-факты: (1) второй seeded-юзер (follow-up
> COS-176); (2) Woodpecker DB пуста → деривация чанков в live-смоках не воспроизводилась
> (стенд-факт COS-180); (3) серверная половина PTY для IDE-CORE-023 (клиент готов, gutter-run
> честно говорит «runner не подключён»).
>
> **Выданы 25.09.2026:** COS-187 → Flash (✅ DONE), COS-188 → Buddy, COS-189 → Luna (✅ DONE).

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-187** | Flash | 2-3h | P3 | COS-176 (принят) | ✅ DONE — viewer seeded, multi-user login, раздельные inbox (e2e 31/1/0) |
| **COS-188** | Buddy | 2-3h | P2 | COS-180 (принят) | 🔄 выдан |
| **COS-189** | Luna | 4-6h | P2 | IDE-CORE-023 (клиент) | ✅ DONE — research/дизайн: wire `runnerTty`, сэндбокс-профиль, канон-границы, эпик-нарезка (док) |

#### COS-187 · e2e identity: второй seeded-юзер + раздельные inbox-тесты

> **Зачем:** задокументированный follow-up приёмки COS-176: identity-тест notifications честно
> переписан под одного seeded-юзера (свой inbox + forged → 401); раздельные inbox'ы двух
> principals не проверяются — нет второго пользователя.

> **Scope:**
> (1) Второй seeded-юзер (OpenBao auth: свой sub/email/roles, отличные от admin; идемпотентный
>     сид — расширить `seed-auth-secrets.py` или отдельный скрипт, PRESERVED при повторе).
> (2) e2e: publish для A не виден в inbox B; forged-подпись по-прежнему 401; кэш сессий
>     хелпера учитывает двух principals.
> (3) Прогон notifications-линии целиком; честные skip'ы не деградируют.

> **Out of scope:** RBAC-модель; прод-сиды; UI.

> **Acceptance:** два principals с раздельными inbox (A не видит B); e2e зелёный; сид
> идемпотентен (повтор → PRESERVED).

> **Отчёт обратно:** как засидирован второй юзер; сценарии; числа; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Как засидирован второй юзер.** `secret/cosmo/auth` расширен optional **`users`-списком**
  (свой email/sub/roles/is_admin; основная запись — admin, backward-compatible).
  `seed-auth-secrets.py` идемпотентно добавляет viewer: `viewer@cosmoport.local` /
  `cosmo-viewer-dev` / sub `viewer` / roles `['user']` / is_admin=false; env
  `COSMO_AUTH_VIEWER_EMAIL/PASSWORD/SUB`. Повторный прогон → **PRESERVED** (проверено двумя
  запусками: `[auth:viewer] SEEDED` → `PRESERVED`; jwt-keys/admin тоже PRESERVED, kid стабилен).
- **Login multi-user (BE).** `routes/auth.py`: `_auth_users()` собирает кандидатов
  (primary + `users`; невалидные записи без email/hash fail-closed пропускаются), email —
  точный match, пароль **всегда** сверяется PBKDF2-хэшем (для неизвестного email — с хэшем
  первой записи, чтобы не давать timing-оракул на перебор адресов); токен минтится полями
  matched-записи (sub/email/roles/is_admin).
- **Хелпер e2e (COS-187).** Кэш сессий стал **per-email** (`Map`), добавлены
  `viewerCredentials()`, `authHeaders/e2eRecipient/authenticatePage/authenticatePageOrSkip`
  принимают credentials; env `E2E_COSMO_VIEWER_EMAIL/PASSWORD`; `E2E_COSMO_RECIPIENT`-override
  применяется только к default-юзеру.
- **Сценарии (live).** Новый notifications-тест `COS-187`: publish для viewer → viewer
  `unread=1`, admin `unread=0`; publish для admin → admin `unread=1`, viewer по-прежнему `1`,
  и его inbox содержит **только своё** событие (A не видит B). Forged-signature → 401 сохранён
  (COS-176-тест без деградации).
- **Числа.** BE focused `test_auth_login.py` = **12 passed** (+5: второй юзер login/wrong-password/
  per-user creds/`_auth_users` fail-closed); auth-регресс (auth + jwt + surface_auth +
  sanitary_rbac) = **92 passed**; live `notifications.spec.ts` = **18/18**; полная e2e-линия =
  **31 passed / 1 skipped (degraded by design) / 0 failed**; vitest **90/90**; `npm run build` 0.
- **Стенд-факт.** Образ `cosmo-api:local` пересобран + контейнер пересоздан (multi-user login в
  живом контуре), сид выполнен с AppRole из `services/.env`; viewer login живой — 200
  (`sub=viewer`, roles `['user']`, is_admin=false).
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_auth_login.py` — 12 passed; живой viewer-login 200 (`sub=viewer`); стенд ok.
> Пруфы Flash: `users`-список в secret (admin backward-compatible); PBKDF2 всегда сверяется
> (без timing-оракула); идемпотентность SEEDED→PRESERVED; live A/B-inbox; e2e 31/1/0.

#### COS-188 · Woodpecker live-контур: активированный пайплайн-сид

> **Зачем:** стенд-факт COS-180: Woodpecker DB пуста (нет активированных пайплайнов) →
> деривация лог-чанков из реального пайплайна в live-смоках не воспроизводилась. Живой
> контур пайплайнов должен быть воспроизводим для live-проверок (SSE логи, run history).

> **Scope:**
> (1) Идемпотентный сид: репо-фикстура (Gitea) + `.woodpecker`-конфиг + активация в Woodpecker
>     + прогон пайплайна (или документированная процедура, если автоматизация невозможна).
> (2) Live-смок: реальный пайплайн → лог-чанки по проводу (проверка пути COS-180 end-to-end).
> (3) Интеграция в смоук-скрипты (self-skip при оффлайн-стенде).

> **Out of scope:** изменение Woodpecker-инфры; CI-конфиги продуктов; promotion.

> **Acceptance:** на стенде активированный пайплайн; live-смок деривации чанков зелёный;
> сид идемпотентен.

> **Отчёт обратно:** как засидировано; смоук (сценарий); числа; блокеры.

> **Исполнение (Buddy, 2026-09-25):** ✅ закрыто — живой пайплайн и деривация чанков воспроизводимы.
>
> **Сид:** `services/scripts/seed-woodpecker-fixture.py` (идемпотентный): Gitea repo
> `cosmo/pipeline-fixture` (auto_init + `.woodpecker.yml`, 2 echo-шага) → платформенный
> WP-юзер `cosmo` в БД (Gitea PAT в `access_token` + `expiry` в будущем; WP API-токен =
> JWT HS256 {user-id,type}, подпись = `users.hash`) → активация (`POST /api/repos?forge_remote_id=…`,
> `config_file` явно) → прогон (`POST …/pipelines`) → логи шагов. Повтор: всё PRESERVED.
> Сид выпускает `COSMO_WOODPECKER_TOKEN` в `services/.env`; compose пробрасывает его в cosmo-api.
>
> **Найдено live-смоком (контракт-дрифты, чинились по пути):**
> 1. `workflows[].children` vs `steps`: живой v3.5 отдаёт шаги в `children` — `_flatten_steps`
>    (адаптер) и `workspace._step_summaries` молча видели 0 шагов (вот она, «деривация не
>    воспроизводилась»). Фикс: fallback `steps||children` + тесты.
> 2. Строки логов: v3.5 отдаёт base64 в `data` (`line` — номер) — `_fetch_step_logs` возвращал
>    числа вместо текста. Фикс: base64-декод + legacy-фолбэк + тест.
> 3. Инфра контура: Gitea `ROOT_URL=cosmo-gitea:3000` (clone-плагин агента не резолвил
>    `localhost:3000`, exit 128) + агенту `WOODPECKER_BACKEND_DOCKER_NETWORK=cosmo-net`
>    (шаговые контейнеры в сети контура). Без обоих пайплайны не клонируются.
>
> **Live-смок:** `services/scripts/smoke-woodpecker-chunks.py` — реальный прогон → durable handle
> → SSE `GET /runs/{id}/logs/stream` (ticket COS-075). Факт: **11 событий — 3× step_start
> (clone/prepare/verify), 3× log_chunk, run_finish**; чанки несут реальные строки
> (`+ echo "cosmo-fixture prepare"`, `cosmo-fixture verify`). Прогнан **2× PASS**.
> Self-skip при оффлайн-стенде; встроен в `local-smoke.ps1` (Phase 1b).
>
> **Тесты:** `test_execution_woodpecker` + sse/resume + run_history = **70 passed**; полный
> cosmo-сьют = **3612 passed / 1 failed (чужой: docs↔live OpenAPI drift от параллельного
> COS-187 — docstring auth/login без регена docs; не мой дифф) / 24 skipped**.
>
> **Файлы:** `seed-woodpecker-fixture.py`, `smoke-woodpecker-chunks.py`; `execution_woodpecker.py`
> (children+base64), `workspace.py` (_step_summaries), `docker-compose.yml` (Gitea ROOT_URL,
> agent NETWORK, cosmo-api TOKEN env), `services/.env` (token, gitignored), тесты, README.
> Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: `-k woodpecker`
> — 29 passed / 6 skipped; сид и смок-скрипты на месте. Пруфы Buddy: живой прогон → 11 событий
> (3× step_start / 3× log_chunk / run_finish), 2× PASS; идемпотентный сид PRESERVED. Ценно:
> live-смок вскрыл два контракт-дрифта (`children` vs `steps`; base64-логи) — исправлены
> с тестами. Побочно зафиксирован docs↔live OpenAPI drift после COS-187 → COS-192.

#### COS-189 · PTY-контур: research/дизайн (wire `runnerTty`, сэндбокс, безопасность)

> **Зачем:** IDE-клиент построил TTY-поверхность (IDE-CORE-023: xterm stdin/resize/ANSI),
> серверной половины нет; gutter-run честно говорит «runner не подключён (PTY epic)». До
> реализации нужен безопасный дизайн и согласованный wire.

> **Scope:**
> (1) Research: модель сэндбокса для интерактивного exec (изоляция, ресурсы, сеть, lifetime,
>     связь с commit-and-run/Woodpecker-контуром).
> (2) Wire-протокол `runnerTty`: `onData`/`onResize`/exit, транспорт (SSE vs WS), auth-модель,
>     reconnect.
> (3) Границы безопасности: PTY не как замена безопасному runner; аудит; fail-closed; что
>     запрещено по канону.
> (4) Результат — research-док + предложение эпик-нарезки (реализация — отдельными карточками
>     после согласования wire с Vector через Максима).

> **Out of scope:** реализация контура; клиентская часть (Vector); PTY как замена безопасному
> runner (стоп-линия roadmap).

> **Acceptance:** research-док с дизайном/wire/границами и предложением эпик-нарезки;
> согласование wire с Vector инициировано.

> **Отчёт обратно:** дизайн; wire; риски; предложение нарезки; блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **Дизайн:** `docs/research/2026-09-25-cos-189-pty-contour-design.md` — клиентский канон
  (IDE-CORE-023) построчно, серверная половина wire, модель сэндбокса (3 варианта), профиль
  изоляции, границы безопасности, эпик-нарезка, открытые вопросы.
- **Wire (серверная половина):** транспорт — **SSE (output) + POST (input)** как в клиенте:
  `pty_open`/`pty_data`/`pty_close` на лог-стриме `/api/v1/runs/{id}/logs/stream` (payload'ы с
  `run_id`), ввод — `POST /api/v1/repos/workspace/runs/{id}/tty?repo=`. Фреймы публикуются в тот же
  backlog `runlog` (ids/replay COS-180; порядок log↔pty сохраняется; курсоры логов pty не сдвигают).
  SSE-обрыв не убивает PTY; типизированные ошибки (`PTY_NOT_OPEN` / `PTY_UNAVAILABLE`), fail-closed.
  **Контрактный пробел:** у клиента нет open-запроса — «кто открывает сессию» (открытый вопрос №1).
- **Сэндбокс:** subprocess в `cosmo-api` — **отклонён** (интерактивный shell в control plane =
  RCE-эквивалент: DB-креды/vault/полная сеть); Woodpecker-транспорт — отклонён (нет интерактивного
  API). Рекомендация — **ephemeral-контейнер на сессию** через отдельный sandbox-сервис (новый
  сервис — явное инфра-решение владельца) + профиль: non-root, cap-drop ALL, read-only rootfs,
  tmpfs, сеть `none`, лимиты, TTL, без docker.sock/host-mount'ов.
- **Канон (сверено с Vector):** `void-core/web-ide/THREAT-MODEL.md` — будущий shell требует
  **expiring capability + allowlist + quotas + audit**; `ARCHITECTURE.md` — «Web IDE … not a runner»,
  interactive shell — не MVP. Дизайн удовлетворяет: **команд-скоупная сессия** (allowlist-энтрипоинт
  вместо free-shell), capability-выдача (Valkey, паттерн `ot1`), аудит open/close/отказов, лимиты,
  default-off kill-switch; стоп-линия «PTY ≠ замена безопасному runner'у» зафиксирована.
- **Нарезка (предложение, после согласования):** PTY-SANDBOX-1 (инфра, 8-12 h) → PTY-SERVER-2
  (session manager + capability, 6-8 h) → PTY-STREAM-3 (pty-фреймы/backlog, 3-4 h) → PTY-HARDEN-4
  (security-матрица + live-смоук, 4-6 h) → PTY-FE-5 (Flash, после решения Vector).
- **Согласование:** wire-предложение и 7 открытых вопросов (§7 дока) готовы к передаче **Vector
  через Максима**; тема межпродуктовая (Airlock↔Web IDE) — при необходимости оформляется Nexus-пакет
  по `void-core/SYNC.md`. До согласования серверная реализация не начинается; клиент безопасно
  деградирует (уже реализовано).
- **Риски:** новый сервис (инфра-расширение); максимальный риск-профиль поверхности (порядок:
  sandbox+harden → UX); контрактный пробел open-intent; нагрузка stdin-POST (coalescing).
- **Тесты/код:** вне scope (research-карточка). **Блокеры:** нет — нужны решение владельца (новый
  сервис) и согласование wire. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Док прочитан целиком: клиентский
> канон построчно, wire (§3), 3 варианта сэндбокса с обоснованным отклонением subprocess и
> Woodpecker, профиль изоляции, границы безопасности, нарезка, 7 вопросов. Согласование wire
> инициировано этим ходом (пакет передан Максиму → Vector). Реализация — BLOCKED до двух
> решений (см. PTY-EPIC ниже).

---

## ⏸ BLOCKED — PTY-EPIC: 5 КАРТОЧЕК ПОСЛЕ СОГЛАСОВАНИЯ (COS-189 → PTY-1..5)

> **Источник:** COS-189 (принят). Эпик нарезан Luna, зафиксирован как план.
> **Решение владельца (25.09.2026):** закладываем sandbox-сервис — по уму, как опцию на будущее
> (default-off; канон-исключение осознанное). **Остаётся:** согласование wire `runnerTty`
> с Vector (7 вопросов §7 дока; пакет передан через Максима 25.09.2026) — серверная половина
> (2+) стартует после него.
> **Порядок:** 1 (запущен) → 2 → 3 → 4 (жёсткая цепочка) → 5 после 3 + решения Vector.

| # | Карточка (предложение) | Кто | h | Зависит | Статус |
|---|---|---|---|---:|---|
| 1 | PTY-SANDBOX-1 — sandbox-сервис: allowlist-энтрипоинт, профиль §5, lifecycle, smoke изоляции | Buddy | 8-12 | ✅ решение владельца (25.09) | ✅ DONE — сервис+изоляция+TTL+аудит; live 29/29 |
| 1.1 | PTY-SANDBOX-1.1 — швы: attach (pty) + доставка checkout в сессию | Buddy | 6-8 | 1 | ✅ DONE — attach (HTTP-chunked) + delivery; live 44/44 (2026-10-11) |
| 2 | PTY-SERVER-2 — session manager: registry, single-flight, TTL/kill, аудит, capability | Luna | 6-8 | 1.1 + wire Vector (ждёт) | ⏸ BLOCKED (карточка полная; ждёт wire) |
| 3 | PTY-STREAM-3 — `pty_*` фреймы в backlog `runlog` (ids/replay COS-180) | Luna | 3-4 | 1,2 | ⏸ BLOCKED |
| 4 | PTY-HARDEN-4 — security-матрица, лимиты, kill-switch, live-смоук | Luna | 4-6 | 3 | ⏸ BLOCKED |
| 5 | PTY-FE-5 — открытие сессии из drawer, gutter-run через PTY, UX | Flash | 4-6 | 1-4 + Vector | ⏸ BLOCKED |

#### PTY-SANDBOX-1 · Sandbox-сервис: ephemeral-контейнер на сессию (PTY-контур, шаг 1)

> **Зачем:** PTY-дизайн (COS-189 §4-5) рекомендует отдельный sandbox-сервис; subprocess в
> `cosmo-api` отклонён (RCE-эквивалент). Решение владельца: закладываем — опция на будущее,
> default-off, по профилю изоляции §5.

> **Scope:**
> (1) Сервис (compose-профиль, опциональный, default-off): запуск ephemeral-контейнера на сессию
>     из образа с **allowlist-инструментами** (не free-shell) + lifecycle API для `cosmo-api`
>     (внутренняя граница: create/stop/status; без `docker.sock` в `cosmo-api`).
> (2) Профиль изоляции §5 дизайна: non-root, `cap-drop ALL`, `no-new-privileges`, read-only rootfs
>     + tmpfs (`/workspace`,`/tmp`), сеть `none`, лимиты cpu/mem/pids/fs, TTL idle+hard, kill.
> (3) Аудит-хуки: open/close/exit/отказы (для будущего session manager'а).
> (4) Security-смоук (негативы): нет сети, нет `docker.sock`, нет host-FS; лимиты срабатывают;
>     kill по TTL; default-off не влияет на стенд.

> **Out of scope:** session manager в `cosmo-api` (PTY-SERVER-2); SSE-эмиссия (PTY-STREAM-3);
> FE (PTY-FE-5); free-shell; PTY как замена безопасному runner'у.

> **Acceptance:**
> - Сервис поднимается опционально; сессия контейнера живёт/умирает по TTL; негативы изоляции
>   подтверждены (нет сети/сокета/хост-FS); аудит пишется; выключенный профиль не влияет на стенд.

> **Отчёт обратно:** образ/профиль; lifecycle API; негативы изоляции; аудит; блокеры.

> **Исполнение (Buddy, 2026-09-25):** ✅ закрыто — сервис, изоляция, TTL, аудит, default-off.
>
> **Образ/профиль:** `services/pty-sandbox/image/` — alpine + allowlist-инструменты
> (git/ls/cat/grep/find/head/tail/wc, read-only набор), `sandbox-run` — allowlist-энтрипоинт
> (второй рубеж после валидации сервисом; uid 1000 + nologin — свободный shell закрыт).
> Сервис — `services/pty-sandbox/service/` (FastAPI + docker SDK, владеет docker.sock);
> compose-сервис `pty-sandbox` с `profiles: ["pty"]` — **default-off** (без профиля
> отсутствует в `config --services`, стенд не затрагивается).
>
> **Lifecycle API** (`127.0.0.1:8190`, cosmo-net): `POST /sessions` (create; tool ∈ allowlist),
> `GET /sessions`, `GET /sessions/{id}` (status), `DELETE /sessions/{id}` (stop/requested),
> `POST /sessions/{id}/touch` (шов idle-TTL для PTY-SERVER-2), `GET /health`. Профиль §5 на
> контейнер сессии: network none, read-only rootfs + tmpfs (/workspace,/tmp), cap-drop ALL,
> no-new-privileges, non-root, mem 256m / pids 128 / cpu 1.0, TTL idle+hard + reaper, max 4.
>
> **Живой смоук** `services/scripts/smoke-pty-sandbox.py` — **29/29 PASS**: default-off
> (config без/с профилем); deny `sh` → 403; сессия `cat` → профиль подтверждён по
> docker inspect (network none / ro-rootfs / cap-drop / no-new-privileges / tmpfs-only,
> без host-mounts / лимиты); негативы изнутри: uid=1000, нет docker.sock, нет сети
> (egress fail), rootfs ro, tmpfs writable, `sandbox-run sh` → deny(77); **TTL kill
> (hard_ttl)**; stop (stopped/requested); **аудит JSONL** (denied/create/kill×2).
> Cleanup: сессии удалены, сервис снят — стенд не тронут (cosmo-api healthy).
>
> **Юнит-тесты** чистой логики: `pytest services/pty-sandbox/service/test_logic.py` —
> **16 passed** (allowlist / кламп TTL / валидация args и id-полей).
>
> **Швы (по дизайну):** PTY-канал attach stdin/stdout — PTY-SERVER-2/STREAM-3; наполнение
> allowlist — §7.6 (Vector/PO; v1 read-only); доставка кода в /workspace (checkout/files) —
> следующий шаг (сеть none by design); аудит JSONL → `cosmo_audit_events` — PTY-SERVER-2.
> **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: структура
> `services/pty-sandbox/{service,image}`; compose-профиль `pty` **default-off** (в обычном
> конфиге сервиса нет); юнит-тесты логики — **16 passed** (мой прогон); песочница не запущена,
> стенд `/ready` ok. Пруфы Buddy: live-смоук 29/29 (изоляция по inspect и изнутри, deny `sh`→403,
> TTL-kill, аудит JSONL, стенд не затронут). Швы зафиксированы; фундамент эпика стоит.

#### PTY-SANDBOX-1.1 · Швы sandbox: attach (pty) + доставка checkout в сессию

> **Зачем:** SANDBOX-1 дал lifecycle + изоляцию; для живой PTY-сессии (SERVER-2/STREAM-3) нужны
> два шва в sandbox-сервисе: (а) attach stdin/stdout/resize к allowlist-процессу сессии;
> (б) доставка кода — checkout `repo@commit_sha` в `/workspace` сессии (read-only), т.к. сеть
> `none` by design.

> **Scope:**
> (1) Attach-API: серверный стрим сессии (транспорт sandbox↔cosmo-api — WS или HTTP-chunked;
>     выбор зафиксировать в README/дизайн-заметке), stdin/resize вход, exit-code наружу.
> (2) Доставка кода: sandbox API принимает workspace-артефакт (tar/bundle) и раскладывает в
>     `/workspace` (read-only для процесса); идемпотентность по session id; лимиты (размер).
> (3) Аудит: attach start/stop, delivery (denied/ok).
> (4) Смоук: attach к allowlist-процессу (`cat`/`echo`) — поток идёт; delivery — файлы видны;
>     негативы: oversize/битый архив → deny; изоляция не ослаблена (сеть none, без docker.sock).

> **Out of scope:** SERVER-2 (cosmo-api session manager + wire `runnerTty` — Luna; ждёт Vector);
> STREAM-3 (SSE-фреймы); FE; наполнение allowlist (§7.6 к Vector).

> **Acceptance:** attach-поток живого allowlist-процесса (stdin→stdout) работает; workspace
> доставлен и read-only; негативы честные; изоляция не ослаблена.

> **Отчёт обратно:** транспорт attach; delivery-формат; смоук; негативы; блокеры.

> **Исполнение (Buddy, 2026-10-11):** ✅ закрыто — оба шва живые, негативы честные, изоляция не ослаблена.
>
> **Attach-транспорт (решение 1.1):** HTTP-chunked, не WS — нулевые новые зависимости
> на обеих сторонах (Starlette out; httpx у cosmo-api) и та же модель «out-стрим +
> POST на вход», что в дизайне COS-189. `GET /sessions/{id}/attach` — сырые октеты PTY
> (octet-stream, live-only, без replay); `POST /sessions/{id}/stdin` — chunked body в
> stdin (один активный стрим, второй → 409); `POST /sessions/{id}/resize` — кламп
> rows≤500/cols≤1000 (нечисло/≤0 → 422); exit-code — `GET /sessions/{id}` после конца
> потока (attach к exited → 409 + exit_code в деталях). Ввод/вывод/resize продлевают
> idle-TTL; обрыв клиента → чистый `attach_close (client_disconnect)`.
> Границы честные (docker 7.2): закрытие stdin-канала EOF процессу не доставляет —
> завершение сессии через stop/TTL; attach — live-канал, replay — зона STREAM-3.
>
> **Доставка:** `POST /sessions/{id}/workspace` (raw tar) → санитайз fail-closed
> (только regular files/каталоги; без `/`, `..`, `\`, дисков; лимиты архив/записи/
> распаковка) → root:root, файлы 0644, каталоги 0755 → `/workspace` (tmpfs mode=755)
> **read-only для процесса**: touch от uid 1000 → отказ, `/tmp` — скретч.
> Идемпотентность: повторная доставка заменяет (wipe + relayout). Механика раскладки:
> exec `head -c N | tar -x` — ro-rootfs блокирует docker `put_archive` (живой факт:
> 400 "container rootfs is marked read-only"); head читает ровно объём и завершается
> сам (socket-EOF на 7.2 не доставляется — проверено).
>
> **Живой смоук** `services/scripts/smoke-pty-sandbox-attach.py` — **44/44 PASS**:
> echo stdin→stdout (живой cat), resize/кламп/422, stdin-синглфлайт 409, exit-code=0
> у `find` + 409-attach с кодом, delivery happy/idempotent, негативы (oversize 413
> по declared-CL; bad_archive / unsafe_path / unsupported_entry → 400; content-type
> → 415), изоляция не ослаблена (network none, ro-rootfs, нет docker.sock/egress,
> /workspace 755), аудит (attach_open/close, stdin_open/close, denied busy/not_running,
> delivery_ok/denied×4). Регрессия шага 1: `smoke-pty-sandbox.py` — **31/31 PASS**
> (обновлён: `/workspace` теперь read-only для процесса — осознанное ужесточение
> профиля под доставку).
>
> **Юнит-тесты** чистой логики: `pytest services/pty-sandbox/service/test_logic.py`
> — **29 passed** (+13: resize-кламп; санитайз tar: traversal/links/лимиты/
> родители/root:root/644-755).
>
> **Капкан docker-py 7.2 (шов для SERVER-2):** `attach_socket`/`exec_start` отдают
> stdlib `socket.SocketIO(rb)` — write невозможен, после таймаута чтение «залипает»
> ('cannot read from timed out object'); рабочий путь — сырой `sock._sock`
> (recv/sendall), проверено синтетикой и живыми прогонами. Debug-логи шва —
> `PTY_SANDBOX_DEBUG=1` (env-проброс в compose).
>
> **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Приёмка Cosmo (2026-10-11):** независимо: `pytest services/pty-sandbox/service/test_logic.py` —
> **29 passed** (мой прогон); код-спот: attach/stdin/resize/workspace-эндпоинты с честными кодами
> (409/413/415), доставка через fail-closed санитайз, `/workspace` RO для процесса. Live 44/44
> и регресс 31/31 — по отчёту Buddy. Принято; границы docker-py 7.2 — переданы в SERVER-2.

#### PTY-SERVER-2 · Session manager: registry, single-flight, TTL/kill, capability, аудит

> **Зачем:** sandbox-сервис даёт изолированную сессию (PTY-SANDBOX-1/1.1), но контур Airlock
> ещё не управляет ею: нет реестра run→session, политики жизни, прав и аудита. Это серверная
> половина PTY-эпика (дизайн COS-189 §3/§7).

> **Зависимости:** PTY-SANDBOX-1.1 (attach-шов) + согласованный wire `runnerTty` с Vector
> (7 вопросов §7 дока COS-189). До согласования не начинать.

> **Scope:**
> (1) Реестр сессий: run → session, single-flight (одна сессия на прогон), привязка к
>     principal и репозиторию.
> (2) Жизненный цикл: idle-TTL + hard-TTL, kill при завершении/отмене/перезапуске прогона;
>     явное закрытие.
> (3) Ввод: приём stdin/resize только после открытия сессии (сервер не доверяет клиентскому гейту).
> (4) Права: expiring capability со скоупом principal+repo+run (формат — по wire-решению);
>     отзыв; операторский kill-switch.
> (5) Типизированные ошибки: нет сессии/не открыта; фича выключена или сэндбокс недоступен;
>     чужой прогон — 404 (анти-энумерация); превышение лимитов ввода.
> (6) Аудит: открытие/закрытие/отказы/лимиты — в журнал аудита (кто, repo, commit, run, session).
> (7) Фича по умолчанию выключена; включение — явный флаг.

> **Out of scope:** эмиссия `pty_*` на лог-стрим (PTY-STREAM-3); FE-поверхность (PTY-FE-5);
> наполнение allowlist; free-shell; PTY как замена безопасному runner'у.

> **Acceptance:** (после согласования wire) сессия открывается против allowlist-процесса
> сэндбокса; ввод идёт только в открытую сессию; TTL/kill срабатывают; чужой прогон → 404;
> выключенная фича → типизированный отказ; аудит пишется; негативы честные.

> **Отчёт обратно:** реестр/lifecycle; capability; типизированные ошибки; аудит; live-смоук; блокеры.

---

## ⬜ READY — WAVE 5: SOURCE-SAST ДИЗАЙН + FE DRAFT RESTORE (COS-190/191)

> **Источник:** (1) COS-189 закрыл PTY-дизайн → следующий крупный кандидат SOURCE_AUDIT —
> source-SAST (SonarQube/CodeScoring) research-заходом; (2) разведка FE: серверный черновик
> сохраняется (COS-182), но `getWorkspaceDraft` нигде не вызывается — восстановления нет.
>
> **Выданы 25.09.2026:** COS-190 → Luna, COS-191 → Flash.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-190** | Luna | 4-6h | P2 | — | ✅ DONE — research/дизайн source-SAST: варианты, mechanics через живой findings-мост, legacy SONAR-POOL, нарезка (док) |
| **COS-191** | Flash | 2-3h | P3 | COS-182 (принят) | ✅ DONE — restore server-draft + badges (server WIP/local), delete при Сбросе; vitest 95 |

#### COS-190 · Source-SAST: research/дизайн (SonarQube / CodeScoring)

> **Зачем:** SOURCE_AUDIT-кандидат: интеграция сканера исходников (гейты пока покрывают
> container/artifact-сканы: trivy/syft/grype закрыты). Нужен дизайн до реализации: варианты,
> где живёт сканер, связь с evidence/SARIF, границы.

> **Scope:**
> (1) Research: варианты (SonarQube / CodeScoring / иное) — что уже есть в линейке (lab Keeper?),
>     чем отличаются, что закрывает SOURCE_AUDIT.
> (2) Механика: запуск (Airlock-контур: run/pipeline vs внешний сервис), формат результата
>     (SARIF?), запись в Evidence Ledger, гейт-потенциал.
> (3) Границы: что не трогаем; межпродуктовые зависимости (Keeper — если lab-инстанс).
> (4) Результат — research-док + предложение нарезки (реализация — после решения владельца).

> **Out of scope:** реализация; container-сканы (приняты); DAST (Коробка).

> **Acceptance:** research-док с вариантами/механикой/границами и предложением нарезки.

> **Отчёт обратно:** варианты; рекомендация; границы; нарезка; блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **Док:** `docs/research/2026-09-25-cos-190-source-sast-design.md` — варианты, механика,
  границы, нарезка, 6 открытых вопросов.
- **Главная находка:** канон УЖЕ описывает source-SAST (LC-шаги 1.4 SonarQube / 1.6 CodeScoring;
  source- vs container-профили; `BrickType` содержит `sast`/`sca`; E2E-харнесс
  `run-e2e-pipeline.ps1` уже собирает «Sonar SAST»-кирпич как шаг Woodpecker), а принимающая
  машинерия **живая**: findings-мост `POST /api/v1/runs/{run_id}/findings` → `runs.findings_refs`
  (COS-101, severity-канон) → `GatePolicyEngine` (Critical→BLOCK / High→WARN) + Evidence Ledger +
  Findings Search. Не хватает только сканера и ingest-адаптера отчёта.
- **Legacy SONAR-POOL** (проверено `git grep` + живой ПГ): `sonar_pool.py` (пул CE-воркеров),
  `sarif_merger.py` (50 шардов→1, O(1)), `minio_buffer.py` (S3 + Valkey `sonar.ingest`),
  `ingest_controller.py` (token bucket), `fast_ingest.py` (SARIF→findings) — код/тесты есть,
  **в рантайм не подключены**; `fast_ingest` метит в таблицу `cosmo_findings`, которой в Airlock-2
  **нет** (проверено в живой ПГ) → ретаргетинг на текущий носитель обязателен. Бlueprint боевой
  (Cosmoport-1: 50 параллельных run).
- **Рекомендация:** Phase 1 — **SAST как шаг пайплайна** (brick `type=sast`, Woodpecker,
  `sonar-scanner-cli`) против CE-хоста + отчёт → живой findings-мост → гейт/evidence (по BAN.md
  процессов локально не поднимаем). Phase 2 — legacy-пул (SONAR-POOL) только под подтверждённый
  масштаб. CodeScoring (1.6) — отдельный трек по решению владельца; CodeQL отложен.
- **Нарезка:** SAST-STEP-1 → SAST-INGEST-2 → SAST-GATE-3 → SAST-STAND-4 (+ SAST-SCALE-5,
  SCA-CODESCORING-6 — по решению). Оценки в доке.
- **Открытые вопросы (6):** чей CE-хост (сервис стенда Airlock vs lab-инстанс Keeper); семантика
  гейта (TERMINATE_ON_ERROR канона vs severity-политика); Quality/coverage охват; конвенция
  projectKey (CE без branch-analysis); доступность/лицензия CodeScoring; масштаб Phase 2.
- **Границы:** container-сканы не трогаем (приняты); DAST — Коробка; секреты — только секретница;
  airgap — образы scanner/CE в бандл (как COS-171/172). **Тесты/код:** вне scope (research-карточка).
  **Блокеры:** нет — нужны решения владельца (хост/гейт/масштаб). Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Док прочитан целиком (147 строк):
> канон-сверка (LC 1.4/1.6, source- vs container-профили, `BrickType` sast/sca), живая машинерия
> (findings-мост COS-101 → GatePolicyEngine → Evidence), legacy SONAR-POOL — честный статус
> «не подключён», варианты A-E, Phase 1/2, 6 открытых вопросов. Реализация — BLOCKED до решений
> владельца (см. SAST-EPIC ниже).

#### COS-191 · FE: серверный черновик — восстановление (`getWorkspaceDraft`) + индикация

> **Зачем:** COS-182 перевёл Save на серверный черновик (COS-110, TTL 7d), но `getWorkspaceDraft`
> в FE нигде не вызывается — после перезагрузки черновик недоступен (localStorage очищен).
> Иллюзия сохранения без восстановления.

> **Scope:**
> (1) Восстановление серверного черновика при открытии файла (если отличается от repo-версии) —
>     с честной индикацией источника (server WIP / local / repo).
> (2) Не ломать семантику COS-182 (Save→draft, ошибки честные); «Сбросить» откатывает.
> (3) 404/503 черновика — тихо к repo-версии (не ошибка).
> (4) Тесты: vitest (restore, индикация, деградации) + применимый e2e; tsc/build.

> **Out of scope:** серверный draft-контракт (COS-110/182 приняты); multi-file drafts.

> **Acceptance:** после reload открытый файл восстанавливает серверный черновик (или честно
> repo-версию); индикация различима; vitest/tsc/build зелёные.

> **Отчёт обратно:** как восстановлено; индикация; тесты; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Как восстановлено.** `loadFileContent` после чтения repo-версии (CAS/ref) проверяет черновики
  в порядке приоритета: **локальный** (localStorage — «несохранённые правки») → **серверный**
  (`GET /api/v1/repos/workspace/draft`, только CAS-режим; в ref-snapshot пропускается как
  read-only). Server-draft применяется, только если отличается от repo-версии; после restore
  доступен «Сбросить», diff показывает WIP против repo.
- **Индикация.** В шапке — `data-testid="content-source-badge"`: **`server WIP`** (cyan,
  «переживает reload») или **`local draft`** (amber, «ещё не сохранён на сервере»); бейдж
  показывается, только когда источник не repo **и** контент реально отличается от repo-версии
  (черновик == repo → без ложного WIP). Плюс статус-сообщение «Восстановлен серверный черновик»
  / «Восстановлен локальный черновик».
- **Семантика COS-182 не сломана.** Save→draft как было (статус/ошибки честные); «Сбросить»
  теперь возвращает repo-версию **и удаляет серверный черновик** (`DELETE /workspace/draft` —
  иначе reload вернул бы его снова); сбой удаления → честное предупреждение
  «Локально сброшено, но серверный черновик не удалён: …».
- **Деградации.** 404/503 черновика — **тихо к repo-версии** (внутренний catch: без статус-ошибок
  и terminal-шума); честная видимость ошибки загрузки repo-файла (COS-179) не задета.
- **Тесты.** vitest `WebIDEShell.test.tsx` = **24 passed** (+5: restore server + бейдж/статус;
  local приоритетнее server; 503 → тихо repo без индикации/ошибок; draft==repo → без WIP;
  «Сбросить» → DELETE + repo-версия). Контур `npm test` = **5 файлов / 95 passed**;
  `tsc -b` = 0; `npm run build` exit 0.
- **e2e (live).** Новый тест: правка Monaco → Save (server draft) → **reload** → черновик
  восстановлен (бейдж `server WIP` + контент в Monaco) → «Сбросить» → repo-версия, бейдж исчез,
  `GET /workspace/draft` → **404** (удалён). Полная линия `npx playwright test` =
  **32 passed / 1 skipped (degraded by design) / 0 failed**.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка:
> `getWorkspaceDraft`/`deleteWorkspaceDraft` вызываются в WebIDEShell; `content-source-badge`
> с тестами; `DELETE /workspace/draft` живой на BE; мой прогон vitest — **5 файлов / 95 passed**.
> Пруфы Flash: e2e live (Save→reload→restore→Сбросить→404), линия 32/1/0; деградации тихие.

---

## ⬜ READY — FIX: OPENAPI РЕГЕН ПОСЛЕ COS-187 (COS-192)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-192** | Flash | 1-2h | P1 | COS-187 (принят) | ✅ DONE — реген-тул (`regen_openapi.py --check`) + артефакты; гвард 0 failed; дельта 1 строка |

#### COS-192 · OpenAPI реген: снять docs↔live drift после COS-187 (гвард COS-177)

> **Зачем:** гвард `test_docs_equal_live_app_schema` (COS-177) падает единственным в сьюте:
> live `app.openapi()` после COS-187 (auth/login docstring multi-user) ≠ `docs/cosmo-openapi.{json,yaml}`.
> Снять до коммита (чистый suite gate).

> **Scope:**
> (1) Реген `docs/cosmo-openapi.{json,yaml}` из живого `app.openapi()` (байт-воспроизводимая
>     процедура COS-177/180/181/185); дифф — ровно дельта COS-187; json==yaml==live.
> (2) Гвард + focused openapi/ref-контракт зелёные.

> **Out of scope:** новые контракты; auth-код (COS-187 принят).

> **Acceptance:** `test_workspace_ref_readonly.py` — 0 failed; дифф минимален (дельта COS-187).

> **Отчёт обратно:** дифф; прогон; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Процедура (байт-воспроизводимая).** Вынес реген в тул
  `orchestrator/tools/regen_openapi.py` (идемпотентный, `--check` для CI/контроля):
  JSON — `json.dumps(spec, indent=2, ensure_ascii=False)` + CRLF без хвостового
  перевода; YAML — `yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)` + CRLF;
  источник — живое `app.openapi()` рабочего дерева. Формат подтверждён посимвольным
  сравнением с уже принятыми артефактами (COS-177/180/181/185) — совпадает, отличалась
  ровно дельта COS-187.
- **Дифф минимален.** `docs/cosmo-openapi.json` — **1 строка** (только `description` ручки
  `/api/v1/auth/login`: docstring multi-user из COS-187); `docs/cosmo-openapi.yaml` —
  тот же блок (12+/1−). Никакого форматного шума.
- **Прогон.** Гвард `test_workspace_ref_readonly.py` = **34 passed / 7 skipped, 0 failed**
  (включая `test_docs_equal_live_app_schema`, `test_docs_json_equals_docs_yaml`,
  `test_ref_param_in_docs_json_and_yaml`); focused `test_openapi_contract.py` — в том же
  прогоне зелёный; transfer-matrix (`-k "openapi or schema"`) = **5 passed**. Второй запуск
  `regen_openapi.py --check` → **IDENTICAL ×2** (exit 0) — регенерация идемпотентна.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: мой прогон
> `test_workspace_ref_readonly.py` — **20 passed / 7 skipped / 0 failed** (гвард
> `test_docs_equal_live_app_schema` зелёный); дифф-минимализм подтверждён (1 строка json);
> тул `regen_openapi.py --check` идемпотентен. Drift снят до коммита.

---

## ⏸ BLOCKED — SAST-EPIC: 6 КАРТОЧЕК ПОСЛЕ РЕШЕНИЙ (COS-190 → SAST-1..6)

> **Источник:** COS-190 (принят). Эпик нарезан Luna; рекомендация — Phase 1
> (STEP-1 → INGEST-2 → GATE-3 → STAND-4), Phase 2/CodeScoring — по решению.
> **Решение владельца (25.09.2026):** хост — **свой SonarQube CE в стенде Airlock**
> (самодостаточность, закладываем на будущее). **Рабочие допущения Cosmo** (до признания иного):
> гейт — ошибка сканера = terminate, findings = severity-политика (комбинация); v1 — только
> security-findings, Quality/coverage — опция позже; projectKey v1 — `owner__repo` (без веток,
> CE-ограничение), branch-конвенция — при плагине; CodeScoring — отдельный трек (доступ/лицензия);
> масштаб Phase 2 — по факту нагрузки.
> **Фактический старт:** STAND (хост — фундамент для live-прогона) → STEP-1 → INGEST-2 → GATE-3.

| # | Карточка (предложение) | Кто | h | Зависит | Статус |
|---|---|---|---|---:|---|
| 1 | SAST-STEP-1 — SAST-кирпич пайплайна (brick `type=sast`, Woodpecker, `sonar-scanner-cli`, конфиг скана, артефакт-отчёт) | Luna | 6-8 | ✅ | ✅ DONE — brick+отчёт+durable-захват; settle-фикс гонки логов; live 12/12; gate 3629/24/0 |
| 2 | SAST-INGEST-2 — отчёт → findings: конвертер (SARIF/CE-API) + живой мост (`tool=sonarqube`), дедуп | Flash | 4-6 | ✅ | ✅ DONE — SARIF/CE-конвертер + ретаргетинг-дедуп; live smoke 5→4, повтор 0; finding → COS-193 |
| 3 | SAST-GATE-3 — evidence + гейт: маппинг severity/порогов, финализация, Hub-проводка | Luna | 4-6 | ✅ 2 (INGEST) · COS-203 ✅ | ✅ DONE — принят Cosmo (2026-10-05); live e2e 19/19 |
| 4 | SAST-STAND-4 — стенд: **свой** SonarQube CE сервис + идемпотентный сид + live-smoke | Luna | 4-6 | ✅ решение владельца | ✅ DONE — CE-хост в стенде (companion-файл), сид идемпотентен (4×), live 9/9 |
| 5 | SAST-SCALE-5 — SONAR-POOL revival (пул+merger+buffer, ретаргетинг) | Luna | 8-12 | подтверждённый масштаб | ⏸ BLOCKED |
| 6 | SCA-CODESCORING-6 — CodeScoring-трек (шаг 1.6) | — | ? | решение владельца | ⏸ BLOCKED |

#### SAST-STAND-4 · Стенд: свой SonarQube CE + идемпотентный сид (SAST-эпик, старт)

> **Зачем:** решение владельца — свой CE-хост в стенде Airlock (самодостаточность, на будущее);
> это фундамент Phase 1: без живого хоста не провести live-прогон SAST-кирпича (STEP-1).

> **Scope:**
> (1) SonarQube CE сервис в стенде (зеркало compose-канона Keeper: CE+PG, `:9000`, своя сеть),
>     опциональный профиль (не тормозит обычный стенд), ресурсный бюджет ~4GB учтён.
> (2) Идемпотентный сид: SONAR-токен → секретница (не plaintext), projectKey-конвенция
>     `owner__repo`, quality-profile PrettyK (если применимо).
> (3) Live-smoke: сервис healthy; токен валиден (API `api/system/status`); проект создаётся.
> (4) Канон-доки: `SECURITY_MAINTENANCE.md`/README стенда — как поднять/погасить.

> **Out of scope:** SAST-кирпич (STEP-1); ingest (INGEST-2); гейт (GATE-3); CodeScoring;
> lab-инстанс Keeper (кросс-продуктовая зависимость не вводится).

> **Acceptance:**
> - CE поднимается опциональным профилем, healthy; токен из секретницы работает; сид идемпотентен
>   (повтор → PRESERVED).
> - Обычный профиль стенда не затронут (сервис default-off/отдельный профиль).

> **Отчёт обратно:** compose/профиль; сид; конвенция ключей; live-smoke; блокеры.

**Worker report (Luna, 2026-09-25, БЕЗ приёмки):**

- **Compose/профиль:** `services/docker-compose.sonarqube.yml` — `sonarqube:community` +
  `postgres:16-alpine`, UI `:9000`, **своя сеть `cosmo-sonar-net`** (`cosmo-net`/`pk-net` не
  трогаются), `mem_limit 4096m` / reservation 2048m, volumes данных/логов; зеркало канона Keeper
  минус `pk-net`. **Опциональность:** отдельный companion-файл (канон openbao/registry/test-pg) —
  обычный `up -d` стенда его НЕ содержит (проверено `config --services`: без sonar).
- **Сид:** `services/scripts/seed-sonar-stand.py` — ждёт UP; admin-доступ (dev `admin/admin`,
  каскад со сменой дефолта при необходимости); **токен `prettyk-airlock` → OpenBao
  `secret/cosmo/sast`** (kv-v2, AppRole `cosmo-app`; в выводе маска); проект по конвенции
  **`owner__repo`** (фикстура `payments/api` → `payments__api`); quality-profile **PrettyK**
  (copy `Sonar way`, py/ts) + назначение проекту. Vault-запись — только при изменениях.
- **Идемпотентность:** доказана 4 прогонами; финальный (RUN 4): admin / token / project /
  profiles / OpenBao — **все PRESERVED**, тот же токен, `SEED OK`.
- **Live-smoke:** **9/9 PASS** (независимая проверка вне кода сида): CE UP
  (`26.8.0.126808`); `secret/cosmo/sast` читается; токен из секретницы валиден
  (`/api/authentication/validate` → `valid=true`); проект `payments__api` виден токен-доступом;
  `PrettyK(py/ts)` назначен проекту; основной compose без sonar; стенд Airlock `/ready` = ok.
  Скрипт: `D:\Infra\Temp\opencode\sast_stand_smoke.py` (временный артефакт, не в репо).
- **Канон-доки:** `SECURITY_MAINTENANCE.md` §2.6 (up/down, секрет/ротация, конвенции) +
  `README.md` (карта скриптов + короткая секция SAST-стенда).
- **Стенд-факт:** CE оставлен **поднятым** (нужен STEP-1 как хост; `down` — документирован);
  обычный профиль не затронут.
- **Для эпика:** зависимость STEP-1 («STAND (хост)») снята — хост + токен + конвенции готовы.
  **Suite gate не запускался:** код приложения/тестов не тронут (только services/* + docs).
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: SonarQube
> UP (`:9000`, `26.8.0.126808` живой запрос); compose/seed на месте; стенд `/ready` ok.
> Пруфы Luna: идемпотентность 4 прогона (PRESERVED), live-smoke 9/9 (токен из секретницы
> валиден, проект/профили видны), основной compose без sonar. Зависимость STEP-1 снята.

#### SAST-STEP-1 · SAST-кирпич пайплайна (brick `type=sast`, Woodpecker)

> **Зачем:** первый шаг Phase 1: source-SAST как шаг пайплайна против своего CE (STAND-4 принят;
> хост/токен/конвенции готовы). По BAN.md сканер исполняется CI-шагом, не в процессе Cosmo.

> **Scope:**
> (1) Brick-def `type=sast` (executor=woodpecker, image `sonarsource/sonar-scanner-cli`), конфиг
>     скана: SONAR_HOST_URL (стенд), projectKey `owner__repo`, токен — из секретницы
>     (`secret/cosmo/sast`, ref), не plaintext.
> (2) Шаг сканирует checkout рана (repo@commit_sha) → отчёт (SARIF 2.1.0; либо CE-API конверсия).
> (3) Артефакт-отчёт: capture в MinIO/Evidence (как trivy/syft), ref на отчёт durable.
> (4) Live-прогон на стенде: реальный run → шаг → отчёт существует; негатив: CE недоступен →
>     честный фейл шага.

> **Out of scope:** ingest в findings (INGEST-2); гейт (GATE-3); CodeScoring; legacy-пул.

> **Acceptance:** brick исполняется на живом стенде; отчёт снимается и durable; негатив честный;
> секрет не светится в логах/DTO.

> **Отчёт обратно:** brick/конфиг; прогон; отчёт; негатив; блокеры.

**Worker report (Luna, 25.09.2026, БЕЗ приёмки):**

- **Кирпич + конфиг скана.** Каталог: brick `sast-sonarqube` (`type=sast`,
  `executor=woodpecker`, image `sonarsource/sonar-scanner-cli:latest`,
  `inputs.SONAR_PROJECT_KEY=cosmo__sast-fixture`, timeout 1200s); upsert идемпотентен.
  Фактическая команда скана — в repo-`.woodpecker.yml` фикстуры (шаги `sonar-scan` +
  `sonar-report`): канон контура исполняет repo-конфиг, brick = каталожная дефиниция
  (модель хранит только executor/image/inputs/outputs/timeout). Секреты шага — WP
  repo-secrets `sonar_token`/`sonar_host_url` (значения из `secret/cosmo/sast`, в логах маска).
- **Отчёт.** Шаг `sonar-report` снимает CE `api/issues/search` (CE-ветка Scope «либо»)
  → JSON + канонический маркер `[prettyk-sast-report] format=ce-issues sha256=… bytes=… b64=<gzip+b64>`;
  новый `domain/sast_report.py` (parse/find/verify — маркер сверяется с payload по bytes/sha256).
- **Durable-захват.** Новый `control_plane/sast_capture.py` (зеркало COS-164): на `passed`-batch
  с sast-кирпичом реальные логи прогона сканируются; отчёт → `ArtifactStore` (base `cosmo-evidence`,
  механизм COS-075) + `EvidenceLedgerEntry type=raw_response` (`content_ref=artifact://…`,
  `content_hash`=sha256 отчёта; provenance: source/format/brick_names/artifact_path/bytes).
  Нет кирпича → no-op; нет маркера → `MissingSastReportError` → alert-след
  `cosmo-sast-report-missing` (отчёт не выдумывается); расхождение → `InvalidSastReportError`.
  Хук — в `execution_service.write_run_evidence`; попутно: `_resolve_brick_refs` (`bricks_refs`
  в БД = ID-строки) + tolerant `docker_build_specs` (не-dict refs больше не обрывают evidence-путь).
- **Live-гонка (вскрыта и починена).** WP флешит `log_entries` асинхронно: маркер отчёта лёг
  в БД в ту же секунду, что и terminal, но уже ПОСЛЕ нашего чтения → ложный alert вместо отчёта
  (прогон #13; замер по WP-БД: `finished` == `created` лог-записей). Фикс: `collect_all_logs
  (settle_empty_s=…)` — bounded добор (≤2 доп. попытки) только для терминальных шагов с пустыми
  логами; executor включает по умолчанию 2 с (`COSMO_EVIDENCE_LOG_SETTLE_S`, 0 = выкл.);
  legacy-семантика без изменений, +3 детерминированных юнит-теста. (Живой прогон этого захода
  гонку не воспроизвёл — захват через +7.8 с после финиша, ветка покрыта юнитами.)
- **Тесты.** Новый `tests/cosmo/test_sast_report.py` — **23 passed**; `test_execution_woodpecker.py`
  — **+3** settle-теста (вместе с sast-файлом — **47 passed**); focused-контур
  (adapter+batch+service+sast) — **102 passed**; suite gate — **3629 passed / 24 skipped / 0 failed**
  (400 c).
- **Live-прогон (стенд).** `services/scripts/seed-sast-fixture.py` (идемпотентный сид полной
  цепочки: Gitea-репо `cosmo/sast-fixture` + PAT/WP-активация + секреты → domain/app-binding →
  brick → plan → run → pipeline): **12/12 PASS**.
  - happy: `run-sast-1790364945-ok` → batch `passed`, WP #15 success (clone/sonar-scan/sonar-report),
    маркер в логах, `raw_response`-запись
    (`artifact://run-sast-…/…/sast-report/response_1790364977807.json`), chain `verified=ok`,
    файл durable в store, секрет не светится.
  - негатив (CE недостижим): batch `failed` честно, WP #16 failure, `sonar-scan` failure,
    `sonar-report` skipped, отчёт не сфабрикован; секрет восстановлен.
- **Стенд-факты.** `cosmo-api:local` пересобран + recreate (хеши adapter/executor в контейнере
  совпали с хостом); `COSMO_EXECUTOR_ENABLED=1` — в compose стенда (комментарий у сервиса).
  Остаток (не блокер): (а) warning `YAML generation failed … 'str' object has no attribute 'get'` —
  аудит-YAML ждёт dict-refs, а `bricks_refs` хранит ID-строки; не фатален (WP исполняет
  repo-`.woodpecker.yml`), кандидат в follow-up; (б) байты отчёта — FS контейнера
  `/app/cosmo-evidence` (общий caveat контура COS-075; при recreate файлы теряются, source of
  truth — ledger + `content_hash`).
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_sast_report.py` — **23 passed**; settle-фикс на месте (`collect_all_logs(settle_empty_s)`
> в adapter + `COSMO_EVIDENCE_LOG_SETTLE_S` в executor); хеши adapter/executor в контейнере
> совпали с хостом (пруф Luna). Пруфы: live-сид 12/12 (happy: маркер + raw_response + chain
> verified + durable + маска секрета; негатив: CE недостижим → честный failure без фабрикации);
> suite gate 3629/24/0. Остатки: аудит-YAML warning (`bricks_refs` ID-строки vs dict) → COS-194;
> FS-байты отчёта — известный caveat COS-075.

#### SAST-INGEST-2 · Отчёт → findings через живой мост (конвертер SARIF/CE-API)

> **Зачем:** отчёт (STEP-1) превратить в канонические findings через **живой** мост COS-101
> (`POST /api/v1/runs/{run_id}/findings`) с дедупом и severity-каноном.

> **Scope:**
> (1) Конвертер SARIF 2.1.0 (и/или CE-API `api/issues/search`) → findings-json моста
>     (`tool=sonarqube`, severity map, CWE, path/line).
> (2) Дедуп composite key (path+rule+line) — по legacy-блюпринту `fast_ingest`, **с ретаргетингом**
>     на текущий носитель (`runs.findings_refs`; `cosmo_findings` не существует).
> (3) Тесты: конвертер на фикстуре SARIF (golden), мост-вызов, дедуп, пустой/битый отчёт.
> (4) Разработка параллельна STEP-1 против SARIF-фикстуры; живой смоук — на отчёте STEP-1.

> **Out of scope:** сам кирпич (STEP-1); гейт (GATE-3); UI.

> **Acceptance:** SARIF-фикстура → findings в `runs.findings_refs` через мост (severity-канон);
> дедуп работает; пустой/битый отчёт — честно; тесты зелёные.

> **Отчёт обратно:** конвертер; дедуп; golden-прогон; живой смоук; блокеры.

**Worker report (Flash, 25.09.2026, БЕЗ приёмки):**

- **Конвертер.** `orchestrator/cosmo/control_plane/sast_ingest.py`:
  SARIF 2.1.0 → канонический finding-json носителя (`severity` канон gate-engine,
  `cwe`/`cwe_ids`, `file_path`, `line`/`line_number`, `rule_id`, `tool`/`source_tool`
  = `sonarqube`, `scan_type=sast`, `detected_at` из invocations). Severity-precedence:
  Sonar-градация (`properties.severity`: BLOCKER→Critical…INFO→Info) → `security-severity`
  (CVSS-полосы ≥9/≥7/≥4/>0) → SARIF `level` fallback (error→High, warning→Medium,
  note→Low, none→Info). CWE — из properties (`cwe`/`cwe_id`) и tags
  (`external/cwe/cwe-89`). Отдельный конвертер CE `api/issues/search`
  (`convert_sonar_issues`) с тем же каноном. Пустой валидный SARIF (`runs: []`/без
  results) → `[]`; битый JSON / не-SARIF структура → `SastReportError` (честный fail,
  не молчаливый []); не-идентифицируемые entries (ни ruleId, ни message) — пропуск.
- **Дедуп (ретаргетинг legacy).** Composite key **`path|rule_id|line`** (блюпринт
  `ledger/fast_ingest.py`, но вместо несуществующей `cosmo_findings` — проверка против
  текущего носителя `runs.findings_refs` до вызова моста) + схлопывание дублей внутри
  батча. Идемпотентность: повторный ingest того же отчёта в тот же run → `attached=0`.
- **Живой мост.** `ingest_findings_to_run` (общий вход) / `ingest_sarif_to_run` →
  `control_plane.findings_bridge.attach_findings` (COS-101: severity-нормализация,
  append в `runs.findings_refs`). CLI `orchestrator/tools/sast_ingest.py`
  (`--run-id` + `--sarif`/`--issues`; exit 2 на битый отчёт / отсутствующий run) —
  точка для CI-шага STEP-1.
- **Тесты.** Новый `tests/cosmo/test_sast_ingest.py` — **14 passed**: golden-фикстура
  SonarQube (`tests/cosmo/fixtures/sast/sonarqube_report.sarif`, 5 results → 4 unique),
  severity-precedence/полосы, CWE, CE-конвертер, пустой/битый/мусорные entries,
  дедуп (интра-батч, разная line, повтор), **живой мост на test PG**: ingest 5→attached 4,
  повтор → attached 0/dups 5, missing run → LookupError, битый → SastReportError без записи.
  Legacy `test_fast_ingest.py` — зелёный (28 passed суммарно).
- **Live smoke (стенд Airlock, run через API + CLI).** `ingest#1`: parsed 5 /
  **attached 4** / duplicates 1 / total 4; `ingest#2` (идемпотентность): attached 0 /
  duplicates 5 / total 4. Носитель: `jsonb_array_length(findings_refs)=4`. Канонический
  read-путь COS-104: `GET /api/v1/findings/search?q=SQL` → **total=1**,
  `Critical sonarqube src/db.py:42 run=sast2smoke…` — находка видна. Smoke-раны со стенда
  удалены (2 шт, гигиена); фильтрованный `GET /runs?domain` снова 200. Повторный смоук
  на реальном отчёте STEP-1 — после кирпича (Luna).
- **Finding (вне scope, вскрыт live-смоуком):** `Run.findings: list[str]`
  (`domain/run_model.py:75`) ↔ носитель `runs.findings_refs` хранит **dicts** →
  `GET /api/v1/runs/{id}` и `GET /api/v1/runs?domain_id=…` падают **500**
  (pydantic ValidationError) для любого прогона с dict-findings. Латентный дрейф
  контракта (COS-101 пишет dicts, COS-104 читает dicts, run-DTO остался на ID-строках);
  gate/search/evidence не задеты. Нужен follow-up: выровнять DTO (типизированный Finding
  или `list[str | dict]`) — решение PO.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 25.09.2026):** acceptance закрыта. Независимая проверка: focused
> `test_sast_ingest.py` — **14 passed**; конвертер/CLI/фикстура на месте; дрейф `run_model.py:75`
> подтверждён (follow-up COS-193 ниже). Пруфы Flash: live smoke — 5→4 attached, повтор 0,
> поиск COS-104 видит находку; пустой/битый/мусор — честно. Живой смоук на реальном отчёте
> STEP-1 — после кирпича (Luna).

#### SAST-GATE-3 · Source-SAST: evidence + гейт + проводка решения

> **Зачем:** отчёт source-SAST приходит в findings и ложится в Evidence, но контур не доводит
> прогон до честного гейт-решения: нужно, чтобы ошибка сканера терминально завершала прогон,
> а findings влияли на вердикт по severity-политике — с видимым результатом для оператора и
> проводкой решения наружу по уже принятым контрактам.

> **Зафиксированные решения (2026-10-04, рабочая позиция Cosmo до признания иного):**
> (1) Ошибка сканера (шаг сканирования не отработал, отчёт отсутствует или невалиден) —
>     терминальное завершение прогона, без «тихого» PASS; отсутствие обязательного evidence
>     не маскируется.
> (2) Findings обрабатываются severity-политикой действующего гейт-движка (Critical → блок,
>     High → warn по порогу) — единый канон с container-сканами, двойной политики не вводим.
> (3) v1 — только security-findings; Quality/coverage — опция позже, вне этого шага.
> (4) projectKey-конвенция v1 — `owner__repo` (CE-ограничение); ветки — при плагине.

> **Scope:**
> (1) Маппинг source-SAST findings в гейт-политику: пороги/severity — по канону действующего движка.
> (2) Финализация прогона: терминальное решение честное и durable; прогон с Critical findings
>     не может закончиться «успехом» вопреки политике.
> (3) Решение доступно внешнему контуру (Hub) по уже принятым контрактам и видимо оператору:
>     что решено и почему — без пересчёта на клиенте.
> (4) Живой прогон на синхронизированном рантайме (rebuild — COS-203; Sonar-хост — поднят):
>     полный Woodpecker SAST-прогон — happy + негатив (сканер недоступен → честная терминация).

> **Out of scope:** легаси-пул SAST (масштабирование), CodeScoring, Quality/coverage,
> container-сканы (приняты), миграционная цепочка, контракт чтения прогонов (COS-193).

> **Acceptance:**
> - живой SAST-прогон: findings доходят до гейт-вердикта; Critical блокирует по политике,
>   чистый прогон проходит; решение и evidence durable и согласованы с внешним контуром;
> - негатив: сканер недоступен или отчёт потерян → прогон терминально честный (не PASS),
>   причина видима;
> - затронутые проверки зелёные; живой прогон выполнен на рантайме после COS-203.

> **Отчёт обратно:** политика и маппинг; вердикты happy/negative на живом стенде; проводка
> решения; проверки; пробелы.

**Luna > Airlock: SAST-GATE-3 исполнен (2026-10-04, БЕЗ приёмки).**

- **Терминальная честность (код).** `execution_service._capture_sast_reports`: sast-кирпич без
  канонического маркера (шаг упал/не дошёл) больше не «alert-only» — выставляется degraded
  (`BatchExecutor.mark_degraded`, consume-once) → финализация даёт терминальный **failed** с
  причиной в ledger (`write_degraded_evidence`); alert-след сохранён. «Шаг сканера упал» и так
  даёт batch failed → run **blocked** (терминально, не PASS).
- **Авто-ingest findings в гейт (закрытый гэп).** Отчёт, захваченный из логов CI-шага, теперь
  сразу конвертируется и прикрепляется к прогону (`_ingest_sast_findings`: SARIF → `ingest_sarif_to_run`;
  CE-issues → `convert_sonar_issues` → `ingest_findings_to_run`) — findings успевают к гейт-оценке
  финализации **без внешнего шага**; идемпотентно (дедуп `path+rule+line`). Ошибка ingest не молчит:
  degraded → failed.
- **Durable решение + проводка наружу.** `_gate_blocked` возвращает `(blocked, decisions)`;
  при block пишется durable-след в evidence ledger (`type="decision"`, `source=cosmo-gate`,
  decisions + plan_id), а уведомление наружу получило терминальный переход **`run_blocked`**
  (taxonomy policy/service: event type + severity `high`) с payload `reason` + `gate_decisions` —
  «что решено и почему» видно внешнему контуру без пересчёта на клиенте. `failed`-путь также несёт
  `reason` (degraded), `blocked`-по-батчу — `batch_failed`.
- **Пруфы (код).** `test_findings_bridge.py`: +2 (`gate block → type=decision` с решениями;
  `sast без маркера → degraded → failed` + alert); +1 (`авто-ingest: S2077-подобный CE-issue
  BLOCKER → Critical в носителе, повтор → без дублей`). `test_notification_triggers.py`: `run_blocked`
  (unit + persist). Focused-кластер (bridge/notify/sast report/ingest/run dto/control plane/exec service) —
  **128 passed**; **suite gate — 3646 passed / 24 skipped / 0 failed**.
- **Живой e2e (`seed-sast-fixture.py`, расширен сценариями гейта; стенд: cosmo-api пересобран —
  хеш `execution_service.py` совпал, CE 26.8 поднят).** Финальный прогон: **19/19 PASS, rc=0.**
  - **run#1** (политика `Critical→block` + `High→block`): реальный отчёт CE (2067 B) → findings
    **[Critical, High]** авто-ингест'ятся; вердикт — **blocked**; durable decision-след (1 запись);
    наружу `run_blocked` с `reason=gate_blocked` и `gate_decisions`.
  - **run#2 (негатив, CE недостижим)**: `sonar-scan` failure, отчёт не сфабрикован → batch failed →
    run **blocked** (не PASS), наружу `run_blocked reason=batch_failed`.
  - **run#3 (в пределах warn-порога `max_count`)**: те же findings → **succeeded** — политика не
    блокирует произвольно.
- **Найдено и починено живыми прогонами фикстуры:** (а) **гонка report-шага**: sonar-scanner
  завершается раньше обработки отчёта CE (результаты видны ~40 c позже) → пустой отчёт; шаг
  `sonar-report` теперь дожидается CE-задач (`/api/ce/activity`, bounded 240 c); (б) sample
  фикстуры обновлён под действующие правила CE 26.8 — weak-hash `hashlib.md5` (S4790, CRITICAL→канон
  High) и фейковый GitHub-PAT (S6418 secret detection, BLOCKER→канон **Critical**).
- **Остаток (честно):** ветка «маркер отсутствует при success-шаге» покрыта кодом/интеграционным
  тестом, но не живым прогоном (для неё нужен «успешный без отчёта» шаг — не сочиняли искусственно).
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Приёмка Cosmo (2026-10-05):** независимо: focused (run-DTO + SAST report/ingest) — **42 passed**;
> CE 26.8 жив (`/api/system/status` UP); `run_model.py` host == контейнер (`14cbd3c2…`); OpenAPI-гейт
> после приёмочного регена — IDENTICAL. Live e2e 19/19 (blocked / warn / негатив) — по отчёту Luna.
> Принято; остаток про «success без маркера» — честная граница, не блокер.

---

## ✅ DONE — FIX: RUN-DTO FINDINGS DRIFT (COS-193)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-193** | Luna | 2-4h | P1 | — | ✅ DONE — принят Cosmo (2026-10-05) |

#### COS-193 · Run DTO: findings `list[str]` ↔ dicts — 500 на GET /runs (латентный дрейф)

> **Зачем:** live-смоук SAST-INGEST-2 вскрыл: носитель `runs.findings_refs` хранит **dicts**
> (COS-101 пишет, COS-104 читает), а `Run.findings: list[str]` (`domain/run_model.py:75`)
> остался на ID-строках → `GET /api/v1/runs/{id}` и `GET /api/v1/runs?domain_id=…` падают **500**
> (pydantic ValidationError) на любом прогоне с dict-findings. Gate/search/evidence не задеты.

> **Scope:**
> (1) Выровнять run-DTO с носителем: типизированный finding (единый контракт с COS-104) или
>     union — предпочтительно типизированно, без string-дрейфа.
> (2) Регресс: `GET /runs/{id}` + `?domain_id` на прогоне с dict-findings → 200; поиск/gate не тронуты.
> (3) Тесты: прогон с findings (dicts) → оба GET 200 и данные корректны; пустой список — как раньше.
> (4) OpenAPI реген.

> **Out of scope:** переписывание моста/поиска (COS-101/104); SAST-контур.

> **Acceptance:** GET /runs на прогоне с dict-findings — 200 (не 500); контракт выровнен;
> OpenAPI обновлён; suite gate зелёный.

> **Отчёт обратно:** выбранный тип; тесты; реген; блокеры.

**Luna > Airlock: COS-193 исполнен (2026-10-04, БЕЗ приёмки).**

- **Выбранный тип.** `domain/run_model.py`: новый `FindingRef` (`extra="allow"`,
  `severity: str = ""` — канон моста даёт непустую; extras сканеров сохраняются) и
  `Run.findings: list[FindingRef | str]` — dict-путь типизирован (без string-дрейфа),
  legacy-строки-ID проходят честно (union, не выдумываем severity).
- **Регресс закрыт.** `_to_run_schema` больше не падает pydantic-валидацией на
  dict-findings: `tests/cosmo/test_run_dto_findings.py` **5 passed** (FindingRef extras,
  Run dict/str, `_to_run_schema` dict/empty); integration HTTP
  `tests/cosmo/integration/test_runs_dto_findings.py` **1 passed**: живой мост
  (`POST /runs/{id}/findings`, severity `critical|High` → канон `Critical|High`) →
  **GET /runs/{id} — 200**, **GET /runs?domain_id= — 200**, extras (`cwe_ids`, `title`) на месте
  (до фикса — 500 ValidationError).
- **OpenAPI.** `python orchestrator/tools/regen_openapi.py` — json/yaml перезаписаны
  (`FindingRef` + union в схеме Run); `--check` → IDENTICAL.
- **Пруфы.** Focused-кластер (bridge + run_control_plane + новые) — **56 passed**;
  integration-кластер — **31 passed**; **suite gate — 3642 passed / 24 skipped / 0 failed**
  (PASS; +6 к базе 3636/24).
- **Блокеры:** нет. Live-часть SAST-GATE-3 разблокирована (чтение прогонов с dict-findings живёт).

> **Приёмка Cosmo (2026-10-05):** независимо: focused (run-DTO + SAST report/ingest) — **42 passed**;
> `run_model.py` host == контейнер (`14cbd3c2…`); OpenAPI `--check` → IDENTICAL после приёмочного регена.
> Принято.

---

## ✅ DONE — АУДИТ ПРОГОНА SAST: ЧЕСТНОЕ СОСТОЯНИЕ (COS-194)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-194** | Flash | 1-2h | P3 | — | ✅ DONE — принят Cosmo (2026-10-03); runtime rebuild/full SAST run остаются follow-up |

#### COS-194 · Аудит SAST-прогона: корректные ссылки и честная полнота

> **Зачем:** в принятом SAST-контуре аудит прогона может выдавать предупреждение на
> корректных ссылках либо не объяснять, почему часть сведений неполна. Оператору нужен
> точный отчёт: все доступные шаги представлены, а отсутствующие данные не маскируются.

> **Сценарии приёмки:**
> - Given завершённый SAST-прогон со всеми доступными ссылками, When формируется аудит,
>   Then он содержит соответствующие шаги без предупреждения и дублирования.
> - Given ссылка отсутствует или не разрешается, When формируется аудит, Then неполнота
>   явно обозначена с причиной; отчёт не выдаёт неполные сведения за полные.
> - Given прогон без SAST-шагов, When формируется аудит, Then прежнее поведение сохраняется.

> **Out of scope:** контракт чтения findings прогона (COS-193); изменение конфигурации
> SAST-сканирования, gate-policy или Hub-контракта.

> **Acceptance:** три сценария выше покрыты проверками; аудит существующего SAST-контура
> корректен и честно маркирует неполноту; связанные проверки зелёные.

> **Отчёт обратно:** наблюдаемое поведение happy/negative; проверки; оставшиеся пробелы.

**Flash > Airlock: COS-194 исполнен (2026-10-03, БЕЗ приёмки).**

- **Причина warning'а.** `batches.bricks_refs` живого компилятора хранит ID-строки
  (`['sast-sonarqube']`), а `BatchExecutor.submit_batches` отдавал их в audit-YAML как есть →
  `brick.get(...)` на строке → `'str' object has no attribute 'get'` (не фатален, но аудит
  терял шаги: прогон виделся «без шагов»).
- **Резолв (executor).** Новый `BatchExecutor._resolve_audit_bricks`: ID-строки резолвятся из
  каталога `pipeline_bricks` (name/definition_json/depends_on); dict-формы (legacy/unit) проходят
  как есть; нерезолвнутые ссылки не выдумываются — возвращаются с причиной
  (`brick not found in catalog` / `catalog unavailable (no DB session)`). YAML получает
  `unresolved_refs`, неполнота логируется отдельным warning'ом с ref+причиной (вместо generic
  «YAML generation failed»).
- **Аудит (adapter).** `generate_pipeline_yaml` терпим к не-dict refs (не падает и не создаёт
  шаг-фантом) и фиксирует неполноту секцией **`x-audit-incomplete`** (`[{ref, reason}]`);
  happy-путь — шаги на месте, секции нет (без дублей).
- **Сценарии (тесты, +10).** happy: ID-строка → шаг из каталога, без warning'а и дублирования;
  negative: ghost-ссылка → причина и в warning'е, и в YAML; legacy: пустые/dict-refs (без
  SAST-шагов) — прежнее поведение. `tests/test_execution_woodpecker.py` +3,
  `tests/cosmo/test_batch_executor.py` +7 (резолв + submit-уровень).
- **Пруфы.** Focused-набор (woodpecker/executor/sast/docker_build/registry_gap) —
  **125 passed / 0 failed**; **suite gate — 3636 passed / 24 skipped / 0 failed** (367 c, +7 к базе).
- **Live (read-only, живая БД стенда).** 5 SAST-батчей с `refs=['sast-sonarqube']`; реальный
  резолвер → `Sonar SAST` (image `sonarsource/sonar-scanner-cli:latest`,
  `SONAR_PROJECT_KEY=cosmo__sast-fixture`), `unresolved=[]`, audit-YAML содержит шаг; негатив
  с `ghost-brick` → resolved-шаг + `x-audit-incomplete: [{ref, reason: brick not found in catalog}]`.
- **Оставшиеся пробелы.** Audit-YAML — каталожная форма (фактическая команда в repo-`.woodpecker.yml`,
  канон SAST-STEP-1; для кирпича без `commands` шаг несёт `echo 'no commands'`); `x-audit-incomplete` —
  маркер аудита/сверки (в Woodpecker не отправляется). Контейнер `cosmo-api:local` (без mount'ов)
  получит фикс при плановом rebuild/recreate; полный WP SAST-прогон не гонялся (live-проверка
  read-only на существующих батчах).
- **Коммит/пуш — по команде Максима.**

> **Приёмка Cosmo (2026-10-03):** все три сценария карточки совпадают с поведением и тестами.
> Независимый focused-прогон: adapter **3 passed**, submit/resolver **7 passed**; отчёт Flash:
> focused **125/0**, suite gate **3636 passed / 24 skipped / 0 failed** и live read-only на пяти
> реальных SAST-батчах плюс ghost-reference. Кодовая/контрактная часть принята.
>
> **Follow-up, не блокер приёмки COS-194:** запущенный `cosmo-api:local` ещё не пересобран и полный
> Woodpecker SAST-прогон не проводился. SAST-GATE-3 должен подтвердить реальный прогон уже с
> обновлённым runtime; до этого не утверждать, что исправление работает в текущем контейнере.

---

## ⬜ READY — PK-C-010: ГИГИЕНА ОБРАЗОВ (COS-195)

> **Источник:** MASTER `PK-C-010` (директива `Cosmo > Airlock > PK-C-010 -> MASTER.md`,
> 2026-09-26); диагностика Vector: `D:\prettyk.io\docs\board\status\image-hygiene-2026-09-26.md`.
> Суть: не чистка, а смена схемы сборки — dev монтирует исходники (нет пересборки на правку),
> релиз использует immutable-теги (нет `<none>`), cache и bind-mount — под правилами.
>
> **Выдан 26.09.2026:** COS-195 → Luna.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-195** | Luna | 6-10h | P1 | — | ✅ DONE — dev-профиль (6 reload, +0 образов), immutable `git-sha`, cache 14.65→3.2 GB, bind-mount чек 0 |

#### COS-195 · Dev-профиль + immutable-релизы + BuildKit GC + bind-mount гигиена (PK-C-010)

> **Зачем:** за ~2 суток — 19+ dangling (~10.7 GB reclaimable) + BuildKit cache ~14 GB; причина
> воспроизводится на каждой правке (переиспользуемый тег `:local` + запечённый dev-код).
> Плюс фантомная папка по мёртвому абсолютному host-пути при старте устаревшего контейнера.

> **Scope:**
> (1) **Dev-профиль:** исходники монтируются в контейнеры (api — hot-reload; frontend —
>     dev-сервер); правка кода не порождает новый образ; `:local` не меняется в dev-цикле.
> (2) **Релиз/airgap:** immutable-тег (git sha) вместо `:local`; прошлые сборки остаются
>     именованными; retention («держать N») описана.
> (3) **BuildKit cache:** gc-политика (keep-storage); процедура задокументирована.
> (4) **Bind-mount гигиена:** только относительные пути; при переносе репо — контейнеры
>     пересоздаются, а не `start` старых (не воскрешать мёртвые host-пути).
> (5) **Разовый клиринг** накопленного (dangling + build-cache) с зафиксированными числами.

> **Out of scope:** продуктовый рантайм/контракты; prod-стенд, не связанный с локальной сборкой.

> **Acceptance:**
> - после ≥5 правок в dev-цикле число dangling-образов и tagged-версий не растёт;
> - релизный образ существует как immutable-тег; релизы не оставляют `<none>`;
> - gc-политика build-cache применена; размер в лимите (`docker system df`);
> - пересоздание compose-контейнеров после «переноса» репо не создаёт папок по мёртвым путям;
> - runbook-строка (DEPLOYMENT/README): «как не плодить» + «как разово убрать».

> **Отчёт обратно:** dev-профиль (как монтируется, hot-reload); тег-схема релиза; gc-политика;
> bind-mount-правило; числа клиринга (до/после); блокеры.

**Worker report (Luna, 26.09.2026, БЕЗ приёмки):**

- **Dev-профиль.** Новый `services/docker-compose.dev.yml` (override поверх основного;
  запуск `cosmo-start.ps1 -Dev [-Full]`):
  - `cosmo-api`: монтирует `../orchestrator`, `../alembic`, `../alembic.ini` в `/app`;
    entrypoint при `COSMO_DEV_RELOAD=1` поднимает `uvicorn --reload --reload-dir /app/orchestrator`
    (пересборка нужна ТОЛЬКО при смене Dockerfile/requirements.txt/entrypoint.sh);
  - `cosmo-frontend`: `node:22-alpine` + `npm ci && npm run dev -- --port 80` — Vite HMR,
    порт :80 ВНУТРИ (канонический Caddy-апстрим `cosmo-frontend:80` цел; host :5174 прежний),
    `/api` → `cosmo-api:8100` (`VITE_API_PROXY` в vite.config.ts), healthcheck — wget,
    node_modules — в named volume (host-бинарники Windows не тащим).
- **Live dev-цикл:** 6 правок файла-зонда в `orchestrator/` → **6 reload'ов WatchFiles**
  (`:local` ID не менялся: 32a980276bbc, +0 образов, dangling +0); `/ready` ok после reload'ов.
  Входы: host :5174 → 200; Caddy :8180 SPA → 200; :8180/api → 401 (edge жив); Vite проксирует /api.
- **Immutable-релизы.** Новый `services/scripts/build-release.ps1`: тег по умолчанию
  `git-<short12 HEAD>`; guard «существующий тег не перезаписывается»; dirty-предупреждение;
  retention `-KeepN 5` + `-Prune`. Прогон: **`cosmo-api:git-89110393f4c2` +
  `cosmo-frontend:git-89110393f4c2`** (cache-reuse; сборка 1.5 мин) — **+0 `<none>` от релиза**
  (уникальные теги). Compose параметризован: `image: cosmo-api:${COSMO_API_TAG:-local}` (и frontend) —
  dev/стенд-путь не изменился.
- **Airgap.** `airgap-bundle.ps1` собирает build-образы с immutable-тегом и **вшивает тег
  в копию compose бандла** (self-contained; dry-replace токенов проверен: 1+1 замена, остатка нет);
  `verify-airgap-checksums.sh` в running-режиме берёт загруженные `cosmo-*`-теги динамически
  (статические `:local` убраны).
- **BuildKit GC.** Новый `services/scripts/image-hygiene.ps1`: dangling prune + build-cache sweep
  (опция `-ReserveCacheGB N` — `--reserved-space`). **Числа клиринга (до → после):**
  dangling **4 → 2** (снос: superseded `cosmo-api:local` + кэш-запись; остаток — in-use образами,
  снести нельзя), Build Cache **14.65 GB → 3.17 GB** (reclaimable **11.48 GB → 0 B**; пол — слои,
  расшаренные с образами). Грабли (проверено на Docker 29.6.2/BuildKit 0.31.2): `--keep-storage`
  deprecated → `--reserved-space` («минимум, который не вытесняется», НЕ лимит), `--max-used-space`
  на практике no-op (проверен трижды, вкл. контролируемый кэш) — политика = full sweep + опция reserve.
- **Bind-mount гигиена.** Новый `services/scripts/check-bind-mounts.ps1` — статический чек compose:
  только относительные пути, allowlist `/var/run/docker.sock`. Прогон: 6 compose-файлов,
  2 абсолютных маунта — оба allowlist → **0 нарушений**. Live: `up -d --force-recreate cosmo-caddy`
  (первоисточник фантомов PK-C-010) — mount резолвится в `D:\prettyk-airlock\services\Caddyfile`,
  `D:\prettyk-control-plane` **не материализуется** (до/после False), edge /live → 200.
  Правило «при переносе репо — пересоздавать, не `docker start`» — в доке.
- **Runbook.** `docs/DEPLOYMENT.md` §6.5 («как не плодить» — dev-цикл/тег-схема/cache-политика/
  bind-mount-правило; «как разово убрать» — image-hygiene) + `services/scripts/README.md`
  (каталог + секция «Dev-профиль + гигиена образов»).
- **Валидации:** `docker compose config` (main+dev) rc=0; парс всех 5 PS-скриптов OK; `bash -n
  verify-airgap-checksums.sh` rc=0; trailing-whitespace новых файлов 0. Капкан среды (учтён):
  PS 5.1 читает UTF-8-no-BOM как cp1251, em dash → smart-quote `”` — делимитер строки → парс
  ломается; исполняемые строки новых скриптов ASCII, русский — только в комментариях.
- **Стенд-факт:** стенд переведён в dev-профиль (api hot-reload + FE dev-сервер), Caddy-вход цел.
  Откат: `docker compose -f services/docker-compose.yml up -d --no-deps cosmo-api cosmo-frontend`
  (без dev-файла). `:local` пересобран ровно один раз (entrypoint — единственная неизбежная
  пересборка новой схемы).
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Принято (Cosmo, PO, 26.09.2026):** acceptance закрыта. Независимая проверка: 5 артефактов
> на месте (`docker-compose.dev.yml`, `cosmo-start.ps1`, `build-release.ps1`, `image-hygiene.ps1`,
> `check-bind-mounts.ps1`); мой прогон `check-bind-mounts` — **0 нарушений**; `docker system df`:
> Build Cache 3.66 GB (reclaim 380 MB) — совпадает с заявленным клирингом. Пруфы Luna: dev-цикл
> 6 правок → 6 reload, +0 образов; immutable-теги `git-89110393f4c2` (+0 `<none>`); доки §6.5 +
> README. Инцидент среды (падение Docker Desktop) — не связан; стенд восстановлен.

---

## 🔄 ACTIVE — ДЕМО «НОРМАЛЬНЫЙ БИЛД»: РЕАЛЬНЫЙ ПРОГОН СБОРКИ (COS-196…198)

> **Источник:** команда Максима, 2026-10-03: «приоритет показать хоть и сырой но хотя бы
> билд нормальный. Нужен пайплайн». Выдан 2026-10-05 (перевыдача — прошлые строки до воркеров не дошли, файлы не тронуты): COS-196/198 → Flash, COS-197 → Luna (сид/скрипты; one-command — после контракта 196); COS-200/205 — следом за Flash.
>
> **Факты нарезки:**
> - Витрина «Сборки» в Control Station на живом стенде не работает: клиент запрашивает список
>   и создание сборки по адресам, которых нет в API (живой API отдаёт список только по
>   конкретному приложению).
> - Триггер сборки в API — заглушка: статус «running» не обновляется, логи и ссылка на образ
>   выдуманы (указан несуществующий registry).
> - Реальный механизм сборки уже принят: кирпич `docker_build` (build + push в registry зоны,
>   канонический digest-тег), захват digest из логов шага, durable-запись артефакта и Evidence
>   (COS-162/163/164/166). Его не переписываем.
> - Сквозного живого пути «запуск → пайплайн → реальный образ → digest → evidence», пригодного
>   для показа, нет: live-смоук COS-166 исполнял команды сборки напрямую, а 8-фазный
>   e2e-скрипт выставляет статусы вручную.
> - Фактическое исполнение в контуре — конфиг пайплайна в репозитории (канон SAST-STEP-1);
>   сгенерированный аудит-YAML — сверочная форма. Для реального docker build в демо нужен
>   исполняемый конфиг сборки в репозитории демо-приложения (или эквивалентный принятый механизм).
>
> **Канон:** честность важнее красоты; не строить второй билд-механизм; не ломать принятые
> поверхности. **Не трогать:** deploy/promotion ЗР→ЗТ→ЗПЭ (приняты), SAST-контур, контракт
> чтения прогонов (COS-193 в работе у Luna), миграционная цепочка.

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-196** | Flash | 8-12h | P1 | — | ✅ принято (Cosmo, 2026-10-11) — реальное исполнение сборки + durable-digest |
| **COS-197** | Luna | 6-8h | P1 | COS-196 — для one-command части (хвост → COS-207) | ✅ принято (Cosmo, 2026-10-11) |
| **COS-198** | Flash | 6-8h | P1 | COS-196 ✅ | ✅ принято (Cosmo, 2026-10-11) — витрина сборки на живых данных |
| **COS-200** | Flash | 8-12h | P2 | COS-196/197 ✅ (демо-пакет закрыт 11.10) | 🔄 выдан (2026-10-05) — очередь: образ → годность → запуск в ЗР |

#### COS-196 · Сборка: реальное исполнение за триггером

> **Зачем:** сейчас запись сборки декоративна: запуск не приводит к исполнению, статус залипает,
> логи и ссылка на образ выдуманы. Для показа нужен настоящий билд приложения с реальным digest.

> **Scope:**
> (1) Запуск сборки приводит к реальному исполнению в существующем build-контуре (кирпич
>     `docker_build`, исполняемый пайплайном; второй механизм не создавать).
> (2) Статус сборки честно отражает жизненный цикл (создана → идёт → успех/провал) и
>     обновляется по факту; «вечный running» исключён.
> (3) Успех закрепляет реальную immutable-ссылку на образ (канонический digest-тег), согласованную
>     с registry и Evidence; провал не оставляет артефакта-фантома и называет причину.
> (4) Логи сборки — из реального исполнения; недоступность логов подаётся честно.
> (5) Контракты создания и списка сборок согласованы между API и клиентом: список сборок
>     отвечает на живом стенде, создание принимает то, что шлёт UI.

> **Сценарии:**
> - Given живой стенд и приложение с build-конфигурацией, When оператор запускает сборку,
>   Then исполнение реально стартует, а по финишу сборка показывает успех и digest-ссылку,
>   совпадающую с образом в registry.
> - Given исполнение упало (runner или registry недоступны), When оператор открывает сборку,
>   Then статус = провал с причиной, артефакта-фантома нет.
> - Given открыт реестр сборок, When данные грузятся, Then список отдаётся живым API
>   (не 404/405) и показывает реальные статусы.

> **Out of scope:** UI-косметика вне сборок (COS-198); deploy/promotion (принято);
> SAST-контур; контракт чтения прогонов (COS-193); миграционная цепочка.

> **Acceptance:** сценарии подтверждены на живом стенде: реальный образ в registry по digest,
> консистентность registry ↔ запись сборки ↔ Evidence; негатив честный; затронутые проверки зелёные.

> **Опорные факты (Luna, COS-197, 2026-10-11):** каталог не может нести `docker_build`-дефиницию
> (`BrickDefinition` требует `image`, extras режет; `DockerBuildSpec` — `extra=forbid`) → durable
> digest-record (COS-164) на демо-кирпиче сейчас честно SKIP, digest верифицируется логами шага +
> registry. WP v3.5 detail-API не отдаёт steps — состояния/логи шагов читаются из WP-БД (канон
> стенд-фикстур). Демо-контур — `services/scripts/seed-build-demo.py` (ветка `--docker-build-def`
> готова; позитивный compile — после расширения схемы каталога).

> **Отчёт обратно:** как запускается реальное исполнение; статусы/артефакт/логи; негатив; проверки; пробелы.

**Flash > Airlock: COS-196 исполнен (2026-10-11, БЕЗ приёмки).**

- **Как запускается реальное исполнение.** `POST /api/v1/builds` (и per-app `POST /apps/{id}/builds`) — сборка оборачивает принятый
  runs-контур: build `bld-*` + run `run-bld-*` на плане приложения (`app.pipeline_plan_id`, свежие батчи) → `execution_service.submit_run`
  (канон COS-097) → WP pipeline из repo-конфига (`cosmo/build-demo/.woodpecker.yml`) → poll → evidence → finalize. Второй механизм не строился.
- **Список/контракт (п.5).** `GET /api/v1/builds` — живой (был 404/405): фильтры app_id/project_id/status/branch; админ — сводно, не-админ — свой домен.
  DTO расширен клиентскими полями (title/initiator/run_id/evidence_refs/build_logs/meta); создание принимает то, что шлёт UI: `{app_id,title,branch,commit_sha}`.
- **Статус — по факту, «вечный running» исключён (п.2).** Reconcile сборки с прогоном при чтении (succeeded→success; failed/blocked→failed+причина;
  cancelled→aborted). Провал submit'а больше не зависает: durable-след `submit_failed` (дозапись ручки — раньше UPDATE по несуществующей строке терялся),
  PG-терминал батча, degraded-причина, финализация run. Исполненный план (терминальные батчи) → честный **409** «скомпилируйте новый план»
  (resubmit-guard не поднял бы батчи → вечный running).
- **Артефакт (п.3).** Успех закрепляет canonical digest-ref из durable `ArtifactRecord` (COS-163/164). Закрыты два шва:
  (a) резолв ID-строк `bricks_refs` → каталог → `docker_build`-спека (раньше capture молча no-op);
  (b) bounded growing-settle логов WP — хвост с digest-маркером доливается асинхронно (живая гонка флеша, ловилась alert'ом «missing digest»).
  Провал/отмена — без фантома, причина видна.
- **Логи (п.4).** Детали тянут реальные логи шагов из WP (кап 2000 строк), персистятся; недоступность — честная причина (`meta.logs_error`), не выдумка.
- **Шов схемы (находка (a) Luna).** `BrickDefinition` расширен docker_build-полями (flat, additive; `image` больше не обязателен) — дефиниция проходит
  API-путь; `DockerBuildSpec.from_definition` толерантен к generic-полям. Live: `PUT /bricks/docker-build-demo` с полной спекой → 200, каталог несёт `type=docker_build`.
- **Live proof (живой стенд).** `bld-f7a0d142` (app-build-demo, plan-build-demo-4, run-bld-a9ebd825bf, WP **#5**): success ~14 с;
  **artifacts `build-demo:1.0.0@sha256:1df9e237…897f2d` == registry-манифест (HEAD 200) == ledger decision `ef6f53ae40cd`** (canonical_ref совпал);
  логи шага с маркером; evidence — 2 записи (log + artifact-record). Digest совпадает с приёмкой COS-197 (`1df9e237…`).
- **Негативы.** (1) повторный запуск на исполненном плане → **409** «уже исполнялся (батчи: passed)»;
  (2) `abort` активной сборки → build `aborted`, run `cancelled`, durable-ручка «cancelled via API» (WP-пайплайн крайне быстрого билда может успеть досчитать — продукт честно фиксирует отмену по команде);
  (3) executor off → сборка-запись `failed` с причиной, без run'а и фантома (unit + ветка кода); (4) честный кейс «успех без durable-record» (сборка до фикса шва): success + artifact_note, без выдумок.
- **Проверки.** Suite gate — **3670 passed / 24 skipped / 0 failed, 0 errors**; focused (builds/cos196/executor/adapter-settle/artifact_capture/deps-guard/domain-invariant) — зелёные;
  OpenAPI реген (`docs/cosmo-openapi.*` синхронны, COS-192-тест зелёный).
- **Стенд.** Перед proof: `COSMO_WOODPECKER_TOKEN` в `.env` освежён (канон seed-woodpecker-fixture) + recreate `cosmo-api`; WP repo 3 `trusted.volumes=true`;
  образ `cosmo-api:local` пересобран из текущего дерева.
- **Пробелы/координация.** (1) Сид COS-197 сеет кирпич generic-дефом (default) — для durable digest-record прогон нужен с `--docker-build-def`
  (ветка готова; после закрытия шва её можно сделать дефолтом — решение Luna); (2) хвост one-command (COS-207) может стартовать через builds-поверхность;
  (3) dev-остатки прогонов Luna (`…0621-1`, `…1770-2`, `…3448-1`) — её зона (часть помечена в приёмке COS-197). Блокеры: нет. Коммит/пуш — по команде Максима.

> **Acceptance (Cosmo, 2026-10-11).** Принято: реальное исполнение за триггером подтверждено живым стендом (мой прогон, не по отчёту).
> - Мой цикл через продуктовую ручку: свежий план → `POST /api/v1/builds` → `bld-293c7d63`: running → **success**; artifacts
>   `build-demo:1.0.0@sha256:1df9e237…` == registry-манифест; evidence 2 — `2daca2da77a3` (log, WP #16) + `6af2d2c5ee28`
>   (decision `oci://…@sha256:1df9e237…`); run `run-bld-038c5ea134` succeeded. Перед этим `PUT /bricks/docker-build-demo` с полной
>   спекой → 200 (каталог несёт `type=docker_build` — шов (a) закрыт, durable-record работает).
> - Мои негативы: повтор на исполненном плане → **409** («уже исполнялся (батчи: passed)»); `commit_sha` < 7 → **422**;
>   честный no-record (`bld-716dc586`, кирпич был generic после сида) → success + `artifact_note` «durable ArtifactRecord по
>   digest не найден» — без фантома.
> - Ledger-сверка отчётного `bld-f7a0d142`: artifacts digest == registry == decision `ef6f53ae40cd`; `bld-f1c69917` (abort) — aborted;
>   `GET /api/v1/builds` живой (6 записей, контракт UI-полей принят).
> - Проверки — мои прогоны: **suite gate 3670 passed / 24 skipped / 0 failed (368 с)**; focused builds-кластер 74 passed; OpenAPI `--check` IDENTICAL.
> - Замечание → COS-207: сид демо сеет generic-дефолт (после прогона сида durable-record выключается — поймано в приёмке);
>   дефолт — полная спека (`--docker-build-def` готов).

#### COS-197 · Демо-контур «нормальный билд»: сид, прогон одной командой, очистка

> **Зачем:** чтобы показывать билд повторяемо и без ручной подготовки: идемпотентный демо-контур
> от репозитория до терминала сборки и понятного итога.

> **Сплит (2026-10-05):** исполняет Luna. Сид и очистка — независимы; one-command часть — после
> контракта COS-196 (Flash).

> **Scope:**
> (1) Идемпотентный демо-сид: домен и приложение демо-сервиса, репозиторий с реальным Dockerfile
>     и исполняемым build-пайплайном (сборка + push в registry зоны по каноническому тегу),
>     кирпич/план — готовые к прогону. Повтор не плодит дубли.
> (2) One-command запуск показа: стартует сборку через продуктовую поверхность, дожидается
>     терминала и печатает человекочитаемый итог (статус, digest-ссылка, evidence-след) с кодом
>     возврата; недоступный registry/runner → честная ошибка.
> (3) Очистка `--clean`: снимает демо-следы, не задевая чужой стейт.
> (4) Runbook: как поднять, показать и убрать.

> **Out of scope:** изменение продуктовых контрактов (COS-196); UI (COS-198); deploy/promotion.

> **Acceptance:** два прогона подряд — первый реальный успех, второй без дублей; `--clean` убирает
> демо-следы; итог содержит digest, совпадающий с registry, и evidence; негатив честный.

> **Отчёт обратно:** состав сида; вывод показа; негатив; очистка; блокеры.

**Luna > Airlock: COS-197 исполнен (2026-10-11, БЕЗ приёмки).**

- **Сид (`services/scripts/seed-build-demo.py`, идемпотентно).** Gitea `cosmo/build-demo`
  (реальный `Dockerfile` + исполняемый `.woodpecker.yml`: `docker build` + `docker push` в
  registry зоны по каноническому тегу `localhost:5100/cosmoport/zr/build-demo:1.0.0`,
  digest-маркер COS-142); WP: активация (PAT) + `config_file` + **`trusted.volumes=true`**
  (без trust linter режет docker.sock-шаг); Cosmo: domain/app binding, brick, plan
  (`plans/compile`) — готовые к прогону. Повтор — PRESERVED/synced, дублей нет.
- **Показ (`--run [--runs N]`).** По прогону — **свой план на запуск** (`plan-build-demo-<tag>`;
  общий план унаследовал бы терминальный батч — канон SAST-фикстуры). Итог человекочитаемо
  с rc: batch passed → WP pipeline success (состояния шагов — из WP-БД: v3.5 detail-API
  steps не отдаёт) → digest-маркер `build-demo:1.0.0@sha256:…` из логов шага → **образ по
  digest существует в registry ZR (:5100)** → run succeeded; evidence-след прогона
  (log-запись COS-097) проверяется всегда.
- **Живые пруфы.** Два прогона подряд: **13/13 PASSED, 0 FAILED, 2 SKIP** — run
  `…630-1` (WP #11) и `…651-2` (WP #12): batch passed, evidence, pipeline success
  (`clone`+`docker-build`), digest `sha256:1df9e237e1f8a914bd86f12baf7c3b6594defbe595523f4b9f8343a135897f2d`,
  registry-manifest 200, run succeeded. Полный цикл **clean → seed → показ** воспроизведён
  (контрольный run #13: 7/7, 1 SKIP; `forge_remote_id` перепривязан 34→35).
- **Очистка (`--clean`).** Gitea repo снят; WP delete API отвечает 500 (честный WARN —
  сид сам перепривязывает remote; цикл повторного подъёма проверен); app/domain delete
  FK-блок → честный WARN (как в каноне SAST-фикстуры); ledger/registry-следы не удаляются
  (immutable/retention).
- **Находки (швы, важные для COS-196).**
  (a) Каталог **не может нести `docker_build`-дефиницию**: `BrickDefinition` требует `image`
  и игнорирует extras (`_to_brick_schema`/compile падают на дефиниции COS-162), а
  `DockerBuildSpec` — `extra=forbid`. Следствие: digest→durable artifact-record (COS-164)
  не срабатывает — демо-кирпич сеется **generic-дефиницией**, digest проверяется по
  логам+registry, а ledger-запись честно **SKIP**; в скрипте заготовлена ветка
  `--docker-build-def` (полная спека; позитивный compile — после расширения схемы).
  (b) WP v3.5 detail-API не отдаёт `steps` (и у sast-репо тоже) — чтение состояний/логов
  переведено на WP-БД (`steps`, `log_entries.data` — `bytea`, hex-декод).
  (c) env-токен `COSMO_WOODPECKER_TOKEN` протухает при смене `users.hash` (401 в submit);
  канон обновления — `seed-woodpecker-fixture.py` + recreate `cosmo-api` (в runbook).
  (d) **Мина в `seed-sast-fixture.py`**: его `ensure_wp_user` пишет `hash=pat`/`forge_id=<repo id>`
  без `forge_remote_id` (ломает WP-user-row → env-токен 401), а `ensure_activated` использует
  body-вариант `POST /api/repos` (v3.5 не читает → 500). Не трогала (вне scope) — кандидат в
  follow-up на канон-фикс.
- **Проверки.** Продуктовый код карточкой не изменялся. Suite gate — **3668 passed / 24 skipped,
  2 errors** в чужом `test_hub_evaluation_dispatch` (транзиент среды; изолированно — **47/47**).
- **Runbook.** `services/scripts/README.md` — секция «Демо „нормальный билд" (COS-197)»:
  сид/показ/очистка, зависимости стенда, границы (COS-196/198).
- **Остаток.** One-command «показ через builds-поверхность» — после продуктового контракта
  COS-196; сейчас показ идёт через принятую runs-поверхность. UI витрины — COS-198 (Flash).
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Acceptance (Cosmo, 2026-10-11).** Принято: сид/показ/очистка/runbook подтверждены живым стендом.
> - Идемпотентный re-seed: повтор — PRESERVED/synced (repo + файлы, PAT, WP-user, brick, plan), дублей нет.
> - Живой прогон приёмки (`run-build-demo-1791676486-1`, свой план): batch passed, evidence-след (log, COS-097),
>   WP **#14** `clone`+`docker-build` success, digest-маркер `sha256:1df9e237…`, манифест по digest в
>   registry `:5100` → 200, run succeeded. Итог: **7/7 PASS, 1 честный SKIP** (durable artifact-record — шов COS-196).
> - Ledger-сверка отчётных прогонов: батчи …630-1/…651-2/…752-1 — `passed`; evidence-записи
>   `woodpecker://cosmo/build-demo/11|12|13` — маппинг совпал.
> - `--clean`: честные best-effort WARN (WP delete API 500 → перепривязка remote по канону; FK domain/app),
>   ledger/registry не трогаются — по отчёту и коду.
> - Изолированный `test_hub_evaluation_dispatch.py` — **47 passed** (2 errors suite-gate не воспроизвелись — транзиент).
> - Замечания: (1) dev-остаток `run-build-demo-1791675371-1` — running без батча (ранний черновик —
>   остаток до финальной версии скрипта; в контуре не участвует); (2) находка (d) уточнена — реальный дефект: call-site
>   `ensure_wp_user(pat, str(gitea.get("id")))`, где `gitea` — объект репо → user-row получает
>   `forge_remote_id` репозитория (канон — id пользователя); «hash=pat» и «body-вариант активации» в текущем
>   файле не подтвердились → фикс-карточка **COS-208** (выдана Luna).
> - Хвост scope (2): one-command через builds-поверхность — после контракта COS-196 → карточка **COS-207**.

#### COS-198 · Витрина сборки: реальные данные в Control Station

> **Зачем:** «показать» требует экрана: реестр сборок должен показывать настоящие данные и
> открывать детали без обмана.

> **Scope:**
> (1) Реестр сборок на живых данных: статус, время, ветка, инициатор, артефакт; честные
>     loading/empty/error.
> (2) Детали сборки: commit/branch, статус, реальные логи (или честное «недоступно»),
>     digest-ссылка на образ, evidence-след.
> (3) Запуск сборки из UI по контракту COS-196; честные ошибки при отказе.
> (4) Никаких синтетических данных и мёртвых кнопок.

> **Out of scope:** backend-контракт сборки (COS-196); deploy/promotion; прочие экраны.

> **Acceptance:** живой стенд — сборка из COS-197 видна в реестре, детали открываются,
> значения совпадают с исполнением; пусто/ошибка честные; vitest/tsc/build зелёные.

> **Отчёт обратно:** что показывает реестр/детали; живой прогон; проверки; пробелы.

**Flash > Airlock: COS-198 исполнен (2026-10-11, БЕЗ приёмки).**

- **Реестр (п.1, живые данные).** `GET /api/v1/builds` → таблица: статус/время/ветка/инициатор/артефакт; фильтры (приложение/статус/ветка) и поиск;
  лёгкий поллинг активных сборок (честное дотягивание до терминала); честные loading/empty/error (без моков).
- **Детали (п.2).** Клик по строке → диалог: commit/branch, статус, инициатор, прогон (`run_id`), начало/финиш;
  **digest-ссылка** (canonical_ref артефакта); **evidence-след** (id записей); **реальные логи прогона** из API
  (недоступность — честный `logs_error`, у активных — «ещё не оставило логов», у провалов — причина); честные алерты
  `failure_reason` / `artifact_note`; «Прервать сборку» для активных (abort → run cancel).
- **Запуск из UI (п.3).** Существующая модалка по контракту COS-196 (`POST /api/v1/builds`); отказы честные (400 — нет плана; 409 — план уже исполнен; executor off — сборка-провал с причиной).
- **Никаких синтетиков и мёртвых кнопок (п.4)** — все кнопки/поля привязаны к живым вызовам; «—» вместо выдумок.
- **Live proof (CDP, :5174, admin).** Реестр «Сводная история сборок · 4 из 4» — реальные сборки демо-стенда;
  диалог `bld-f7a0d142`: digest `build-demo:1.0.0@sha256:1df9e237…897f2d`, evidence (2: `ed2c637b0f50`, `ef6f53ae40cd`),
  логи `clone` + `docker-build` с маркером; скрин — `D:\Buddy\Flow\Current\blitz-auth\cdp\cos196-details.png`.
- **Проверки.** vitest — **96 passed** (5 файлов; `ControlStationViews` 43, вкл. новый COS-198-тест деталей: digest/evidence/логи);
  `tsc -b` — чисто; `npm run build` — ок. BE-контракт подтверждён suite gate'ом (COS-196).
- **Пробелы.** Косметика вне сборок и группировка по проекту (project_id-фильтр API есть, в UI не выведен) — вне scope. Блокеры: нет.

> **Acceptance (Cosmo, 2026-10-11).** Принято. Живой стенд сверен независимо: CDP-скрин `cos196-details.png` —
> реестр «Сводная история сборок» на реальных данных и модалка `bld-f7a0d142`: success, digest-ссылка `sha256:1df9e237…`,
> evidence-след (2: `ed2c637b0f50`, `ef6f53ae40cd`), реальные логи `clone`/`docker-build`; значения совпали с ledger-записями (БД).
> Проверки — мои прогоны: vitest **96 passed** (5 файлов), `tsc -b` rc=0; BE-контракт покрыт suite gate (COS-196). Группировка
> по проекту — вне scope (зафиксировано).

#### COS-200 · Демо-продолжение: от собранного образа до запущенного сервиса в ЗР

> **Зачем:** демо-пакет показывает сборку; для «нормального пайплайна» нужен следующий честный
> шаг: собранный образ проходит проверку годности и запускается в зоне разработки — одной
> командой, без ручных обходов, с видимым итогом.

> **Опорные факты (read-only разведка Flash, 2026-10-04):**
> - Годность образа уже существует: trivy-скан + durable-аттестация; deploy без PASS блокируется —
>   второй механизм не строить.
> - Запуск в ЗР уже существует: материализация pull → run → healthy; статус `deployed` — только
>   после фактического healthy, иначе честный rollback.
> - Труба «одной команды» — надстройка над демо-контуром COS-197.
> - Внимание: generic-путь создания деплоя ставит мгновенный success без материализации — для
>   демо и приёмки брать принятый release-deploy путь, не его (см. COS-204).

> **Scope:**
> (1) Продолжение демо-сценария после успешной сборки: решение годности образа по канону
>     (скан контейнера; критичные находки блокируют запуск) — на существующем механизме.
> (2) Запуск в ЗР: образ поднимается из registry по digest (без плавающих тегов), сервис
>     доходит до healthy; статус честный.
> (3) Всё — одной командой показа: от сборки до запущенного сервиса, с человекочитаемым итогом
>     (digest, решение годности, состояние сервиса); повтор и `--clean` — по канону демо-контура.
> (4) Негативы честные: нет digest, годность не пройдена, registry недоступен → запуск не
>     происходит, причина видима.

> **Out of scope:** продвижение в другие зоны; изменение механизмов скана/деплоя; витрина
> сборок (COS-196…198); миграционная цепочка.

> **Acceptance:**
> - живой стенд: одна команда доводит демо-приложение от сборки до контейнера healthy;
>   digest и решение годности консистентны с registry и Evidence;
> - негативы: критичная находка / отсутствие digest / недоступный registry → честная остановка
>   без запуска;
> - затронутые проверки зелёные.

> **Отчёт обратно:** сценарий и вывод; вердикты happy/negative; проверки; пробелы.

---

## ✅ DONE — HONESTY: HEALTH-СТАТУС REGISTRY ЗР (COS-199)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-199** | Buddy | 1-2h | P3 | — | ✅ DONE — принят Cosmo (2026-10-05) |

#### COS-199 · Registry ЗР: health-статус без ложного «unhealthy»

> **Зачем:** контейнер registry зоны ЗР числится `unhealthy`, хотя фактически обслуживает запросы:
> `/v2/` отвечает 200, каталог образов отдаётся, sidecar-проверка доступности зелёная. Причина —
> проверка здоровья в конфиге контейнера вызывает инструмент, которого нет в образе registry
> (доступен только busybox-набор). Ложный признак путает оператора и портит демо.

> **Сценарии приёмки:**
> - Given запущенный registry ЗР, When оператор смотрит статус, Then контейнер честно `healthy`
>   (проверка выполняется доступным способом или снята в пользу sidecar-чека);
> - Given registry реально недоступен, When оператор смотрит статус, Then он честно `unhealthy`;
> - Given зона ЗТ не поднята, Then её недоступность не маскируется под доступность ЗР.

> **Out of scope:** включение ЗТ; поведение/хранилище registry; продуктовые контракты и API.

> **Acceptance:** статус контейнера совпадает с фактической доступностью (positive и negative);
> compose-конфиг валиден.

> **Отчёт обратно:** как исправлено; live-проверка статуса; негатив; блокеры.

> **Исполнение (Buddy, 2026-10-05):** ✅ закрыто — статус registry совпадает с реальностью (positive/negative).
>
> **Причина:** healthcheck в `docker-compose.registry.yml` вызывал `curl`, которого нет в образе
> `distribution/distribution:3.1.0` (alpine/busybox-набор) → проба падала всегда → ложный
> `unhealthy` при фактически живом registry (`/v2/` = 200, каталог отдаётся).
>
> **Фикс:** проба переведена на доступный busybox-wget —
> `test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:5000/v2/"]`.
> Compose сам не пересоздаёт контейнер при смене healthcheck → применён
> `docker compose -f docker-compose.registry.yml up -d --force-recreate registry-zr`.
>
> **Live, positive:** `cosmo-registry-zr` — `healthy` (FailingStreak=0); `:5100/v2/_catalog` →
> `4 repos`; sidecar `cosmo-registry-health`: `[OK] registry-zr :5000 reachable`.
>
> **Live, negative (честность):** registry реально недоступен (`docker pause cosmo-registry-zr`) →
> контейнер честно `unhealthy`; проба wget на закрытый порт rc=1 (на живой — rc=0).
>
> **ЗТ не маскируется:** `registry-zt` off by design (`deploy.replicas: 0`); sidecar печатает
> `[FAIL] registry-zt :5000 unreachable` — недоступность ЗТ не выглядит как доступность ЗР.
>
> **Acceptance:** статус ↔ фактическая доступность ✔ (positive/negative);
> `docker compose -f docker-compose.registry.yml config -q` → rc=0 ✔.
>
> **Артефакты:** `services/docker-compose.registry.yml`.
>
> **Блокеры:** нет.

> **Приёмка Cosmo (2026-10-05):** независимо: `cosmo-registry-zr` = `healthy` (FailingStreak=0),
> `:5100/v2/` = 200, `compose config -q` → rc=0. Негатив (pause → честный `unhealthy`)
> и немаркировка ЗТ — по отчёту Buddy. Принято.

---

## ✅ DONE — СТЕНД ПОКАЗА: ПОДЪЁМ И ЧЕСТНАЯ СВОДКА ОДНОЙ КОМАНДОЙ (COS-201)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-201** | Buddy | 2-4h | P2 | COS-199 | ✅ DONE — принят Cosmo (2026-10-05) |

#### COS-201 · Стенд показа: одна команда поднимает контур и печатает честную сводку

> **Зачем:** префлайт показа (2026-10-04) вскрыл, что контур может лежать целиком
> (Docker Desktop остановлен, frontend не поднят), а часть статусов легко принять за
> рабочие или за сломанные по ошибке. Для показа нужен один вход: поднять всё нужное и
> получить честный отчёт о состоянии — без ручных шагов и без маскировки.

> **Scope:**
> (1) Одна команда поднимает контур, необходимый для демо (ядро + полный профиль + registry
>     зоны ЗР), идемпотентно, не трогая чужие стеки.
> (2) Ждёт готовности и проверяет ключевые входы: API, edge, frontend, registry (каталог),
>     Gitea, Woodpecker, признак включённого executor.
> (3) Печатает честную сводку: что up/healthy, что degraded/down и почему; известные ложные
>     статусы не маскируются (см. COS-199) — либо честно объясняются оператору.
> (4) Повторный прогон не плодит дубли; отчёт пригоден для человека, ведущего показ.

> **Out of scope:** изменение поведения сервисов; продуктовые контракты; dev-профиль для
> разработки (уже есть); починка ложного health-статуса registry (COS-199).

> **Acceptance:**
> - Given Docker engine остановлен, When запускают команду, Then она честно сообщает, что
>   engine недоступен, и не притворяется, что контур поднят;
> - Given engine поднят, When запускают команду, Then контур поднят и печатается сводка,
>   совпадающая с ручной проверкой; реально лежащий сервис отражён честно (negative);
> - повторный прогон без дублей; чужие стеки не затронуты.

> **Отчёт обратно:** команда; состав поднимаемого; пример сводки; негатив; блокеры.

> **Исполнение (Buddy, 2026-10-05):** ✅ закрыто — один вход, честная сводка, негативы пройдены.
>
> **Команда:** `.\services\scripts\cosmo-start.ps1 -Full` — подъём контура (идемпотентно) + пробы
> + сводка. `-CheckOnly` — только проверка и сводка, без `up` (для негатив-демонстраций).
> Exit codes: `0` — все входы up; `1` — degraded/down; `2` — Docker engine недоступен.
>
> **Состав (`-Full`):** core compose (PG, Valkey, API, Frontend, Caddy) + `--profile full`
> (MinIO, Gitea, Woodpecker + agent) + `docker-compose.openbao.yml` (shared, auto-unseal) +
> `docker-compose.registry.yml` (ZR + health-sidecar; ЗТ off by design). Сети `cosmo-net`/`pk-infra`
> создаются только при отсутствии. Чужие стеки не трогаются (без `--remove-orphans`); известные
> orphan-warnings общего project-лейбла `services` поясняются оператору строкой `[i]`.
>
> **Префлайт:** `docker version` — engine недоступен → честный стоп: `[FAIL] Docker engine
> unreachable - the stand cannot be started or probed` + подсказка; exit 2, никакого «UP».
>
> **Пробы:** API `/ready`; edge `:8180/live`; frontend `:5174/` и via edge `:8180/`;
> Registry ZR каталог `:5100/v2/_catalog`; Gitea `:3100/api/v1/version`; Woodpecker `:8000/version`;
> OpenBao `:8200/v1/sys/health` (sealed → DOWN с подсказкой bootstrap); executor — env-признак
> живого контейнера `COSMO_EXECUTOR_ENABLED` (app-level INFO не доходит до `docker logs`).
>
> **Пример сводки (live, повторный прогон):**
>
> ```text
> === Cosmoport stand summary (demo set) ===
>   [UP]   API           :8100/ready ok (db=connected, cache=connected)
>   [UP]   Edge          :8180/live HTTP 200 (via Caddy)
>   [UP]   Frontend      :5174 HTTP 200; via edge :8180/ HTTP 200
>   [UP]   Registry ZR   :5100/v2/_catalog -> 4 repos
>   [OFF]  Registry ZT   off by design (deploy.replicas=0); not part of the demo
>   [UP]   Gitea         :3100 v1.22.6
>   [UP]   Woodpecker    :8000 v3.5.2
>   [UP]   OpenBao       :8200 initialized=True, sealed=False
>   [UP]   Executor      enabled, poll loop (COSMO_EXECUTOR_ENABLED=1)
> === STAND GREEN: 8 inputs up, 1 off by design ===
> ```
>
> **Негативы:**
> - engine недоступен (`DOCKER_HOST` на закрытый порт) → `[FAIL]`, exit 2;
> - registry реально лежит (`docker pause cosmo-registry-zr`) → `[DOWN] Registry ZR` (причина:
>   timeout), `STAND NOT GREEN`, exit 1; после `unpause` → `healthy`, снова GREEN;
> - повторные прогоны `-Full`: контейнеры без дублей (33/33 до и после), состав не менялся.
>
> **Шов:** журнальный признак `ExecutionService started/disabled` в `docker logs cosmo-api` не
> виден (конфигурация логирования app-level INFO) — детект по env; если нужен журнальный
> признак — отдельная задача.
>
> **Артефакты:** `services/scripts/cosmo-start.ps1`.
>
> **Блокеры:** нет.

> **Приёмка Cosmo (2026-10-05):** независимо прогнал `cosmo-start.ps1 -CheckOnly` (core) и
> `-Full -CheckOnly`: оба GREEN, exit 0; full-сводка совпала с заявленной (8 up, ЗТ off by design).
> Негативы (engine down → exit 2; registry pause → `[DOWN]`/exit 1; повторные прогоны без дублей) —
> по отчёту Buddy. Принято.

---

## ✅ DONE — EVIDENCE: DURABLE-БАЙТЫ АРТЕФАКТОВ (COS-202)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-202** | Luna | 6-10h | P2 | — | ✅ DONE — принят Cosmo (2026-10-05) |

#### COS-202 · Evidence-байты: артефакты переживают пересоздание контейнера

> **Зачем:** артефакты evidence (отчёты сканов, ответы, акты) сохраняются в файловую систему
> контейнера API: ledger хранит ссылки и хеши, но сами байты при пересоздании/redeploy теряются.
> Для боевого контура и ГОСТ-актов это полу-временное состояние: доказательство должно быть
> извлекаемым, а не только «хеш без содержимого».

> **Scope:**
> (1) Байты артефактов сохраняются в durable-хранилище контура (платформенный S3/MinIO уже
>     поднят в стенде) — ссылки и хеши в ledger не меняются.
> (2) Пересоздание контейнера API не теряет ранее сохранённые артефакты: чтение по ссылке
>     работает после рестарта.
> (3) Честная деградация: хранилище недоступно → захват не молчит и не теряет факт; причина
>     видима; повтор безопасен (идемпотентность по содержимому/хешу).
> (4) Существующие контракты ссылок (`artifact://…`) и проверки целостности не ломаются.

> **Out of scope:** смена семантики ledger/цепочки; UI; airgap-бандлы; миграционная цепочка;
> переезд существующих байтов (отдельным решением).

> **Acceptance:**
> - Given сохранённый артефакт, When контейнер API пересоздан, Then артефакт читается по ссылке
>   и хеш совпадает;
> - Given хранилище недоступно, When идёт захват, Then деградация честная (видимая причина),
>   без молчаливой потери;
> - затронутые проверки зелёные; живой смоук на стенде.

> **Отчёт обратно:** где хранятся байты; поведение после recreate; негатив; проверки; блокеры.

**Luna > Airlock: COS-202 исполнен (2026-10-04, БЕЗ приёмки).**

- **Где хранятся байты (код).** `ledger/artifact_store.py`: `ArtifactStore` получил прозрачное
  durable-зеркало в платформенный S3/MinIO (env-канон `PK_MINIO_URL`/`PK_MINIO_ACCESS_KEY`/
  `PK_MINIO_SECRET_KEY`, SigV4 через принятый `s3_sigv4_headers`; buckets `cosmo-evidence`/
  `cosmo-artifacts`, проvisioning startup.py). Пишутся: объект по относительному пути ref +
  ref-индекс `_refs/{ref_id}` (sha[:16]); локальный FS остаётся кэшем/фолбэком.
  **Контракты не изменились:** `artifact://{path}`, `content_ref`, `content_hash`, размеры и пути
  в ledger — те же; `ArtifactRef` получил опциональное поле `degraded_reason` (default None).
- **Recreate-инвариант (живой пруф).** Прогон SAST fixture (19/19 PASS) → отчёт 2067 B
  зазеркален (`provenance.degraded=false`); host-проверка MinIO (:9100, SigV4 GET) — sha совпал
  с ledger `12fc1eff…`. Затем **`cosmo-api` пересоздан** (`--force-recreate`): локального файла
  в свежем контейнере нет (`local_file_absent=true`), **`retrieve(ref)` вернул 2067 B из S3 со
  совпавшим sha**, `retrieve_by_ref_id` — тоже. Бонусом live подтверждена идемпотентность:
  отчёты run#1 и run#3 (одинаковое содержимое) получили **один ref-путь и один sha** (индекс).
- **Честная деградация (живой негатив).** `cosmo-minio` остановлен → `store()` не молчит:
  `degraded_reason="durable mirror failed: …"` (лог + поле + `provenance.degraded_reason` в
  ledger-записи захвата), локальная копия записана, `retrieve` локально работает; MinIO
  восстановлен (healthy). «Повтор безопасен»: зеркало идемпотентно по контенту/хешу.
- **Кто покрыт.** Зеркало центральное — все потребители `ArtifactStore` (source-SAST-отчёты
  `sast_capture`, ГОСТ-акты `gost_assembler`, read-пути `artifacts`/`fast_ingest`); `sast_capture`
  прокидывает `degraded/degraded_reason` в provenance. Известный caveat SAST-STEP-1 («байты — FS
  контейнера») закрыт для новых захватов; переезд ранее сохранённых байтов — out of scope (карточка).
- **Пруфы.** Новый `tests/cosmo/test_artifact_store_durable.py` — **6 passed** (recreate-чтение
  после потери FS, идемпотентный путь, деградация без потери, hash-mismatch → ValueError,
  ref_id через индекс, local-only без S3); смежный кластер (gost/fast_ingest/retention/attestation/
  anchor) — **160 passed**; **suite gate — 3652 passed / 24 skipped / 0 failed**.
- **Блокеры:** нет. Коммит/пуш — по команде Максима.

> **Приёмка Cosmo (2026-10-05):** независимо: `test_artifact_store_durable.py` — **6 passed**;
> живой MinIO (`cosmo-evidence`): индекс `_refs/12fc1eff…` и объект на месте; host-проба
> `retrieve_by_ref_id('12fc1eff0d7c6dc7')` → 2067 B из S3, sha совпал (`…74121d2f`).
> Recreate-инвариант подтверждён; переезд старых байтов — вне scope (зафиксировано). Принято.

---

## ✅ DONE — RUNTIME SYNC: КОНТЕЙНЕР API НА АКТУАЛЬНОМ КОДЕ (COS-203)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-203** | Boss | 2-4h | P1 | — | ✅ DONE — принят Cosmo (2026-10-04); фикс COS-194 подтверждён в рантайме |

#### COS-203 · Runtime sync: API-контейнер на актуальном коде + честная проверка

> **Зачем:** принятые фиксы (COS-194 и предшествующие принятые работы) живут в рабочем дереве,
> а запущенный контейнер API собран раньше — рантайм отстаёт от кода. Это хвост приёмки COS-194
> и предусловие живой части SAST-GATE-3 и демо-проверок: без синхронизации «живой» результат
> ничего не доказывает.

> **Scope:**
> (1) Пересборка образа API из текущего рабочего дерева и пересоздание контейнера; короткий
>     контролируемый даунтайм, стенд возвращается живым.
> (2) Честная проверка после: `/ready` ok; ключевые ручки отвечают; фикс COS-194 присутствует
>     в рантайме (audit-YAML на прогоне с SAST-кирпичом не теряет шаги — read-only проверка или
>     сверка хешей ключевых модулей контейнер ↔ хост).
> (3) Если сборка или старт не удались — стенд возвращён в рабочее состояние, факт доложен
>     честно; маскировки нет.
> (4) Чужие стеки не тронуты; чужие WIP-правки не коммитятся и не откатываются.

> **Out of scope:** изменения кода; gate-политика (SAST-GATE-3); демо-карточки (COS-196…200);
> frontend-витрина (при необходимости — отдельным rebuild’ом владельца).

> **Acceptance:**
> - рантайм синхронизирован: контейнер собран из текущего дерева, `/ready` ok, ключевые входы живы;
> - фикс COS-194 подтверждён в рантайме (шаги SAST-аудита не теряются);
> - негатив: неуспешная сборка/старт → стенд восстановлен, причина видима;
> - чужие стеки и правки не затронуты.

> **Отчёт обратно:** как собрано; короткий даунтайм; результаты live-проверок (включая COS-194);
> негатив; блокеры.

**Boss > Airlock: COS-203 исполнен (2026-10-04, БЕЗ приёмки).**

- **Как собрано.** `docker compose -f services/docker-compose.yml build cosmo-api` (context `..`,
  `services/cosmo-api.Dockerfile`) → `cosmo-api:local`; затем `up -d --force-recreate cosmo-api`.
- **Даунтайм.** Короткий: контейнер `cosmo-api` пересоздан и `healthy` через **6 s** (остальные сервисы стека
  не трогались).
- **Stale-фикс подтверждён ДО.** Образ был от `2026-09-26`; sha256 host ↔ контейнер **не совпадали**;
  grep `_resolve_audit_bricks`/`x-audit-incomplete` в контейнере — пусто (рантайм отставал от кода).
- **После пересборки.**
  - `cosmo-api` healthy; `GET /live` → 200; `GET /ready` → 200 `{database:connected, cache:connected, anchor:disabled}`;
    OpenAPI **148** api-путей; `GET /api/v1/domains` → **401** (auth-ручка жива).
  - **Фикс COS-194 в рантайме (read-only):** sha256 host == контейнер для
    `orchestrator/cosmo/control_plane/executor.py` (`f228061b…`) и
    `orchestrator/cosmo/adapters/execution_woodpecker.py` (`50fc12f3…`) — байт-в-байт;
    `BatchExecutor._resolve_audit_bricks` присутствует; `WoodpeckerAdapter.generate_pipeline_yaml` присутствует
    (терпимость к не-dict refs + `x-audit-incomplete`). Полный Woodpecker SAST-прогон не гонялся — вне scope.
- **Негатив.** Сборка и старт **успешны** — негативный сценарий не наступил; стенд возвращён живым, маскировки нет.
  (При провале: пересоздание из compose-образа + снимки состояния.)
- **Границы.** Чужие стеки не тронуты (все контейнеры стека Up/healthy); чужие WIP не коммитились/не откатывались;
  коммитов не делал.
- **Коммит/пуш — по команде Максима.**

> **Приёмка Cosmo (2026-10-04):** независимая проверка совпала с отчётом: `cosmo-api` healthy, `/ready` = ok
> (database/cache connected), sha256 `executor.py` и `execution_woodpecker.py` host == контейнер
> (`f228061b…`, `50fc12f3…`), `_resolve_audit_bricks` и `x-audit-incomplete` присутствуют в рантайме.
> Хвост приёмки COS-194 закрыт. Полный WP SAST-прогон — в SAST-GATE-3 (там же Sonar-хост).

---

## ✅ DONE — DECLARATIVE DEPLOY: МГНОВЕННЫЙ SUCCESS НЕ ВЫДАЁТСЯ ЗА РЕАЛЬНЫЙ (COS-204)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-204** | Boss | 4-6h | P2 | COS-203 | ✅ DONE — принят Cosmo (2026-10-05) |

#### COS-204 · Deploy-путь: декларативный success не выглядит как реальное развёртывание

> **Зачем:** разведка демо-контура (2026-10-04) подтвердила: generic-путь создания деплоя ставит
> success мгновенно, без материализации (pull/run/healthy). В витрине и отчётах это выглядит как
> реальное развёртывание — маскировка, противоречащая канону честности. Принятый release-deploy
> путь (материализация + честный rollback) существует и должен быть единственным «реальным».

> **Scope:**
> (1) Generic deploy-путь больше не выдаёт мгновенный success за реальное развёртывание: либо
>     переводится на принятый materialize-путь, либо честно маркируется как декларативный/черновой
>     и не попадает в витрину как реальный.
> (2) Витрина деплоев показывает фактические статусы (healthy/rollback/декларативный), без
>     выдуманных значений и мгновенных «успехов».
> (3) Негатив честный: нет артефакта/годности/материализации → не success.
> (4) Канонический e2e-раннер учитывает новое поведение (скриптовая часть — COS-205).

> **Out of scope:** release-deploy путь (принят, не переписывать); демо-карточки; миграционная
> цепочка; frontend-косметика вне витрины деплоев.

> **Acceptance:**
> - Given декларативный deploy, When оператор смотрит витрину, Then он помечен декларативным
>   (или отсутствует), а не «успешным развёртыванием»;
> - Given реальный deploy, When он завершён, Then статус отражает фактическое healthy/rollback;
> - негатив: без артефакта/годности success не выставляется;
> - затронутые проверки зелёные.

> **Отчёт обратно:** как разделены реальный/декларативный пути; витрина; негатив; проверки; блокеры.

**Boss > Airlock: COS-204 исполнен (2026-10-04, БЕЗ приёмки).**

- **Разделение путей.** Generic-путь `POST /api/v1/apps/{app_id}/deploys` больше **не выдаёт мгновенный
  `success`**: он честно **декларативный** (`status="declarative"`); `finished_at` не проставляется,
  endpoint **не выдумывается** (`custom_url` — только если задан явно). Реальное развёртывание остаётся
  принятым release-deploy (materialize, `releases.py`) — не переписывался.
- **Негатив честный.** Generic `rollback` для не-материализованных деплоев (в т.ч. `declarative`) →
  **409** «not materialized — nothing to roll back» (и `pending`/`running`). `success`/`failed`-ветка сохранена.
- **Витрина.** `DeploymentStatus` += `declarative`; FE `DeploymentsRegistry`/`ApplicationDetail`
  (`statusMeta`/`deploymentStatusMeta`) и `StatusChip` показывают `declarative` (нейтральный чип), а не «active».
- **Проверки.** Backend focused (`test_builds_and_deployments_api.py` + `test_deps_guard_regression.py`) —
  **43 passed**; FE `tsc --noEmit` = 0, `vitest` `ControlStationViews.test.tsx` — **42 passed**.
- **Runtime sync.** Пересобраны `cosmo-api:local` + `cosmo-frontend:local`, пересозданы; `cosmo-api` healthy,
  `GET /live`/`/ready` → 200 (`database:connected, cache:connected`); sha256 host == контейнер для
  `deployments.py` (`5c34f704…`) и `deployment_model.py` (`a06e0199…`); `cosmo-frontend` healthy.
- **Негатив/инцидент.** Во время сборки **упал Docker daemon** (рецидив) — сборка прервана; поднял Docker Desktop,
  контейнеры авто-восстановились, затем пересборка/пересоздание завершены, стенд возвращён живым. Маскировки нет.
- **Границы.** Release-deploy (принятый) не трогал; чужие стеки/WIP не затронуты; коммитов нет.
- **Коммит/пуш — по команде Максима.**

> **Приёмка Cosmo (2026-10-05):** независимо: `cosmo-api`/`cosmo-frontend` healthy, `/live`/`/ready` ok;
> sha256 host == контейнер для `deployments.py` (`5c34f704…`) и `deployment_model.py` (`a06e0199…`);
> focused `test_builds_and_deployments_api.py` — 5 passed; маркеры `declarative` подтверждены в BE
> (`status="declarative"`, `DeploymentStatus`) и FE (StatusChip/DeploymentsRegistry/ApplicationDetail).
> Принято. Docker daemon (рецидив) — не product-дефект; стенд восстановлен. Дрив OpenAPI (описания +
> enum `declarative`) снят при приёмке регеном (`--check` IDENTICAL).

---

## 🔄 ACTIVE — CANONICAL E2E RUNNER: ДЕКЛАРАТИВНЫЕ ФАЗЫ НЕ МАСКИРУЮТСЯ (COS-205)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-205** | Flash | 2-4h | P2 | COS-196…200 (реальный контур) | 🔄 выдан (2026-10-05; очередь после демо) |

#### COS-205 · Канонический E2E-раннер: реальные фазы — реальные, декларативные — помечены

> **Зачем:** канонический 8-фазный раннер вручную проставляет статусы батчей и мгновенный
> deploy-успех — в отчёте это неотличимо от реального исполнения. Для показа «нормального
> пайплайна» раннер не должен маскировать декларативные фазы.

> **Опорные факты (read-only разведка Flash, 2026-10-04):**
> - Канонический раннер — 8 фаз (Domain → App → Bricks → Plan → Run → Batches → Gates → Release →
>   Deploy → Transfer); декларативность deploy зафиксирована в шапке, статусы батчей проставляются
>   вручную.
> - План по карточке: классифицировать каждую фазу «реальная/декларативная»; где реальный путь
>   (COS-196…200) доступен — переключиться на него; патчи и мгновенные success не выдавать за
>   исполнение.
> - Детализация — после отчёта COS-200 (не пересказывать его результат вслепую).

> **Scope:**
> (1) Каждая фаза раннера явно классифицирована: реальное исполнение или декларативная проверка
>     контракта; отчёт различает их без двусмысленности.
> (2) Где реальный путь уже существует (демо-контур сборки/годности/запуска — COS-196…200),
>     раннер использует его, а не подмену.
> (3) Статус-патчи и мгновенные успехи не выдаются за реальное исполнение ни в выводе, ни в отчёте.
> (4) Учесть решение по deploy-пути (COS-204).
> (5) Поведение при недоступном контуре — честный skip/провал с причиной.

> **Out of scope:** продуктовые deploy-пути (COS-204); демо-карточки; изменение канона фаз.

> **Acceptance:**
> - отчёт раннера различает реальные и декларативные фазы; декларативные не выглядят как исполнение;
> - реальные фазы идут по принятому контуру (где он есть);
> - негатив: недоступный контур → честный исход;
> - проверки зелёные.

> **Отчёт обратно:** классификация фаз; отчёт (пример); негатив; проверки; блокеры.

---

## ❌ CANCELLED — СТЕНД: SONAR CE ПОДНЯТ И ГОТОВ К LIVE SAST-ПРОГОНУ (COS-206)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-206** | Boss | 0.5-1h | P2 | — | ❌ cancelled — хост поднят в рамках live-прогона SAST-GATE-3; отдельная подготовка не нужна |

#### COS-206 · Стенд: поднять Sonar CE и проверить готовность к live SAST-прогону

> **Зачем:** live-часть SAST-GATE-3 требует живого Sonar CE-хоста стенда с валидным токеном из
> секретницы и видимым проектом/профилем. Хост сейчас не поднят; подготовка — инфра-шаг, который
> разгружает владельца гейт-логики и снимает ожидание перед живым прогоном.

> **Scope:**
> (1) Поднять Sonar CE штатным компаньон-профилем стенда (как в STAND-4), не тормозя обычный контур.
> (2) Прогнать идемпотентный сид: токен — в секретнице, проект по конвенции, профиль; повторный
>     прогон не плодит дубли (PRESERVED).
> (3) Проверить фактическую готовность: сервис healthy; токен из секретницы валиден; проект/профиль
>     видны токен-доступом.
> (4) Оставить хост поднятым для live-прогона SAST-GATE-3; если политика стенда требует иного —
>     честно сообщить.

> **Out of scope:** сам SAST-прогон и гейт-логика (SAST-GATE-3); правки SAST-контура; масштабирование.

> **Acceptance:** CE healthy; сид идемпотентен (повтор → PRESERVED); токен валиден; проект/профиль
> доступны токен-доступом; обычный контур стенда не затронут.

> **Отчёт обратно:** как поднято; результаты сида (идемпотентность); live-проверки; состояние после.

> **Отмена (Cosmo, 2026-10-05):** Sonar CE-хост уже поднят и использован живым прогоном
> SAST-GATE-3 (19/19); отдельный пре-степ не требуется. Карточка закрыта без исполнения.

---

## 🔄 ACTIVE — ДЕМО-ХВОСТ: ONE-COMMAND ЧЕРЕЗ BUILDS-ПОВЕРХНОСТЬ (COS-207)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-207** | Luna | 1-2h | P2 | COS-196 ✅ | 🔄 выдана (2026-10-11; очередь после COS-208) |

#### COS-207 · Демо: показ одной командой через builds-поверхность

> **Зачем:** закрыть хвост COS-197 — показ «одной командой» через продуктовую builds-поверхность
> (сейчас показ идёт через принятую runs-поверхность). Контракт COS-196 принят (11.10) — можно
> стартовать (после COS-208, тем же воркером).

> **Scope:**
> (1) Одна команда доводит сборку через builds-поверхность до терминала и печатает человекочитаемый
>     итог (статус, digest-ссылка, evidence-след) с кодом возврата.
> (2) Недоступный runner/registry → честная ошибка; повтор и очистка — по канону демо-контура
>     (COS-197: `--clean` не трогает ledger/registry).
> (3) Надстройка поверх принятого контура; сид/очистка COS-197 не переписываются.
> (4) Сид демо сеет полную `docker_build`-спеку **дефолтом** (приёмка COS-196 поймала: generic-дефолт
>     выключает durable-record — сборка остаётся без digest-ссылки); `--docker-build-def` становится штатным.

> **Out of scope:** продуктовая сборка (COS-196); витрина (COS-198); deploy/promotion.

> **Acceptance:** живой прогон одной командой через builds-поверхность: терминал, digest совпадает
> с registry, evidence-след виден; rc честный; повтор без дублей; после сида-дефолта сборка несёт
> durable artifact-record (digest в записи сборки).

> **Отчёт обратно:** команда; вывод показа; негатив; блокеры.

---

## 🔄 ACTIVE — CANON-FIX: SAST-ФИКСТУРА НЕ ПОРТИТ WP-USER-ROW (COS-208)

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-208** | Luna | 1-2h | P2 | — | 🔄 выдана (2026-10-11) — канон-фикс user-row |

#### COS-208 · `seed-sast-fixture`: user-row получает `forge_remote_id` репозитория

> **Зачем:** при прогоне фикстуры строка WP-пользователя получает `forge_remote_id` **репозитория**
> (`ensure_wp_user` вызывается с `gitea.get("id")`, где `gitea` — объект репо; канон — id
> Gitea-пользователя, как в `seed-woodpecker-fixture`/`seed-build-demo`). Forge-доступ строки
> расходится с фактической привязкой → 401 в WP-операциях до ручного ремонта (канон ремонта:
> `seed-woodpecker-fixture.py` + recreate `cosmo-api`).

> **Уточнение при приёмке COS-197 (Cosmo, 2026-10-11):** из отчёта Luna подтверждён **только**
> call-site-дефект; «hash=pat» и «body-вариант POST /api/repos» на текущем дереве не подтвердились
> (hash не трогается; активация — query-параметр).

> **Scope:**
> (1) User-row: использовать id Gitea-**пользователя** (отдельный user-lookup); активация репо —
>     по-прежнему по id репозитория (query-параметр).
> (2) Идемпотентный повтор: `forge_remote_id` = id пользователя; env-токен отвечает 200; повтор — PRESERVED.
> (3) Правка только фикстуры; SAST-логику/гейт не трогать.

> **Out of scope:** SAST-контур/гейт; другие стенд-фикстуры; продукт.

> **Acceptance:** живая проверка (точечная, полный SAST e2e не требуется): user-row `forge_remote_id`
> = id Gitea-пользователя; WP-операции без 401; повтор — PRESERVED; затронутые проверки зелёные.

> **Отчёт обратно:** причина/фикс; live-проверка строки и токена; повтор; блокеры.