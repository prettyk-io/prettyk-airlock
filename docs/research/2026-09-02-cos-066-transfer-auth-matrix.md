# COS-066 — Transfer API Security & Contract Hardening: auth + error matrix

Дата: 2026-09-02 · Worker: Apex · Packet: COS-066 (SERIAL после принятого COS-058)

## 1. Что сделано

### 1.1 Anti-spoofing hardening (`routes/transfer.py`)

Найденная уязвимость собственного кода COS-058: `_caller_domain()` доверял
клиентски контролируемому заголовку `X-Cosmo-Domain` на read/ownership путях →
не-админ из домена `test` мог читать чужие планы с заголовком `alpha`.

Исправление (разделение identity vs context):

| Helper | Семантика |
|---|---|
| `_principal_domain(principal)` | домен аутентифицированного principal (identity, не спуфится) |
| `_context_domain(principal, header)` | домен-контекст ТОЛЬКО для создания: заголовок разрешён system admin; не-админ привязан к `principal.domain_id` |
| `_authorize_record_access(principal, record_domain_id, resource)` | доступ не-админа по `principal.domain_id` ТОЛЬКО; чужой/пустой домен → 404 NOT_FOUND (без раскрытия существования) |

Следствия:
- Заголовок `X-Cosmo-Domain` удалён из сигнатур всех 7 read/mutation
  эндпоинтов (стал мёртвым параметром — вводил в заблуждение). Остался только
  в `create_transfer_plan` (контекст создания для admin).
- Корреляция `/releases/{rid}/plans` для не-админа фильтрует по
  `principal.domain_id`, не по заголовку.
- Существующие 17 тестов COS-058 остались зелёными без правок: их сценарии
  (foreign user beta → 404, correlation → []) уже соответствуют identity-модели.

### 1.2 OpenAPI дополнение

`landing/{transition}`: задокументирован `404` (unknown transition / чужой item)
с примером `unknown-transition` — теперь спека покрывает все наблюдаемые коды.

## 2. Principal-классы матрицы

| Класс | Роль | `release:transfer` | Ожидание на мутациях |
|---|---|---|---|
| anonymous | — (нет Authorization) | — | 401 |
| user | `Role.USER` | нет | 403 |
| operator | `CBRRole.ZONE_OPERATOR_ZPE` | нет (ZPE_DEPLOY/ENVELOPE_*) | 403 |
| manager | `CBRRole.RELEASE_MANAGER` | да | 201/200 |
| admin_sec | `Role.ADMIN_SEC` (не system admin) | да (`_PERMISSIONS`, 15 caps) | 201/200 |
| system_admin | conftest-админ, `is_system_admin=True` | bypass | 201/200 |

Зона: все principals в `zr`; `release:transfer` ∈ `_ZONE_ZR_ACTIONS`.

## 3. Auth-матрица transfer endpoints

Мутации (POST /plans, /validate, /landing/*): guard `require_capability`
→ `require_domain` (400 нет заголовка / 404 домена нет в БД) → RBAC → handler
→ identity-ownership.

| Endpoint | anon | user | operator | manager | admin_sec | sysadmin |
|---|---|---|---|---|---|---|
| POST /plans | 401 | 403 | 403 | 201 | 201 | 201 |
| POST /items/{id}/validate | 401 | 403 | 403 | 200 | 200 | 200 |
| POST /items/{id}/landing/{t} | 401 | 403 | 403 | 200 | 200 | 200 |
| GET /plans/{id} | 401 | 200* | 200* | 200* | 200* | 200 |
| GET /plans/{id}/items | 401 | 200* | 200* | 200* | 200* | 200 |
| GET /items/{id} | 401 | 200* | 200* | 200* | 200* | 200 |
| GET /items/{id}/landing | 401 | 200* | 200* | 200* | 200* | 200 |
| GET /items/{id}/recovery | 401 | 200* | 200* | 200* | 200* | 200 |
| GET /releases/{rid}/plans | 401 | свой домен | свой домен | свой домен | свой домен | все |

\* для записей своего домена; чужие → 404 (см. §4).

## 4. Domain ownership / anti-spoofing результаты

| Сценарий | Результат |
|---|---|
| USER beta + заголовок `test` читает план домена test | 404 NOT_FOUND, конверт error (заголовок не даёт доступ) |
| Manager test + заголовок `alpha` создаёт план | 201, план в домене **test** (контекст создания не подделать; guard пропускает — alpha существует и capability есть; handler привязывает к identity) |
| Manager beta мутации item домена test (заголовок `test`) | 404 NOT_FOUND после guard'а (capability есть, ownership — нет) |
| System admin создаёт план с заголовком `beta` | 201 в beta; beta user видит, test user не видит (легитимный context switch) |
| Корреляция beta по чужому release | 200 `[]` (фильтр по identity) |

## 5. Error-contract matrix (route-level → `{"error": {code, message, details}}`)

| Endpoint / случай | HTTP | code |
|---|---|---|
| POST /plans, duplicate plan_id | 409 | CONFLICT |
| POST /plans, невалидный JSON | 422 | FastAPI `{"detail": [...]}` (граница) |
| POST /plans, нет обязательных полей | 422 | FastAPI `{"detail": [...]}` (граница) |
| GET plan/item — не найден или чужой | 404 | NOT_FOUND |
| POST landing, unknown transition | 404 | NOT_FOUND (+ allowed в details) |
| POST landing, invalid transition | 409 | INVALID_TRANSITION (state не меняется — проверено) |
| POST landing/verify, checksum mismatch | 409 | CHECKSUM_MISMATCH (state → checksum_mismatch) |
| POST landing/receive, cross-item duplicate | 409 | DUPLICATE_REVISION (+ existing_item_id) |
| POST /validate, failure | 422 | VALIDATION_FAILURE (+ issues/error_codes) |

Deps-level (guard) ошибки — FastAPI HTTPException `{"detail": ...}`
(документированная граница, не конверт transfer):

| Случай | HTTP | detail |
|---|---|---|
| Не-админ мутация без `X-Cosmo-Domain` | 400 | "X-Cosmo-Domain header or domain_id query parameter required" |
| Не-админ мутация, домена нет в БД | 404 | "Domain … not found" (`_load_domain_rbac`) |
| Не-админ мутация, домен есть, capability нет | 403 | "Action '…' forbidden for roles …" |
| Anonymous | 401 | "Missing or invalid credentials" |

## 6. Идемпотентность

| Повтор | Результат |
|---|---|
| re-validate validated item | 200, тело идентично первому ответу |
| re-receive received item | 409 INVALID_TRANSITION (state machine, НЕ duplicate-revision — тот же item), state `received` сохранён |
| duplicate plan_id | 409 CONFLICT |

## 7. OpenAPI верификация

- Все 9 путей присутствуют в `/openapi.json`.
- Документированные коды соответствуют наблюдаемым: POST /plans — 409;
  landing/{transition} — 404/409/422; GET plan — 404.
- Error enum (NOT_FOUND, INVALID_TRANSITION, VALIDATION_FAILURE,
  CHECKSUM_MISMATCH, DUPLICATE_REVISION, CONFLICT) присутствует в спеке.
- `/openapi.json` собирается в **чистом процессе** (subprocess,
  `app.openapi()`, rc=0) — регрессия repos.py forward-ref.
- `FileTreeNode.model_json_schema()` содержит `$defs.FileTreeNode` —
  регрессия model_rebuild.

## 8. Cross-route regression (починка deps._guard, COS-058)

`test_deps_guard_regression.py`, 10 маршрутов вне transfer:

```
POST /api/v1/plans/compile          (PIPELINE_CONFIGURE)
POST /api/v1/releases               (RELEASE_CREATE)
POST /api/v1/releases/{id}/transfer      (RELEASE_TRANSFER)
POST /api/v1/releases/{id}/transfer-v2   (RELEASE_TRANSFER)
POST /api/v1/gates/{id}/decision    (GATE_DECIDE)
POST /api/v1/apps                   (BRICK_MANAGE)
PUT  /api/v1/apps/{id}              (BRICK_MANAGE)
DELETE /api/v1/apps/{id}            (BRICK_MANAGE)
POST /api/v1/runs                   (SCAN_START)
POST /api/v1/runs/{id}/cancel       (SCAN_STOP)
```

Для всех: USER без заголовка → 400; USER + существующий домен → 403
("forbidden"); anonymous → 401; USER + несуществующий домен → 404.
**Ни одного 500.**

## 9. Security findings для Cosmo

1. **FIXED (в COS-066):** header-spoofing на transfer reads — заголовок больше
   не участвует в авторизационных решениях для не-админов.
2. **FINDING (guard-level, вне transfer):** `deps._guard` НЕ связывает заголовок
   `X-Cosmo-Domain` с `principal.domain_id` для не-админов: не-админ с
   capability проходит guard под ЛЮБЫМ существующим доменом. Для transfer
   запись всё равно создаётся в identity-домене (handler-level binding), но
   для остальных guarded маршрутов контекст домена определяет обработчик —
   нужен per-route аудит. Рекомендация: binding на уровне deps
   (`header == principal.domain_id` для не-админов, admin — исключение) как
   отдельная карточка (затрагивает COS-031/COS-061 semantics, нужны
   приёмочные решения).
3. **UX-заметка:** не-админ обязан нести заголовок на каждой мутации (guard),
   при этом handler игнорирует его в пользу identity. Безопасно, но избыточно;
   вариант — авто-подстановка из principal в guard'е (решение за Cosmo).

## 10. Регрессионные прогоны

```
.venv\Scripts\python.exe -m pytest orchestrator\tests\cosmo\test_transfer_api.py \
  orchestrator\tests\cosmo\test_transfer_kernel.py \
  orchestrator\tests\cosmo\test_transfer_security_matrix.py \
  orchestrator\tests\cosmo\test_deps_guard_regression.py \
  orchestrator\tests\cosmo\test_rbac*.py orchestrator\tests\cosmo\test_sanitary_rbac.py \
  orchestrator\tests\cosmo\test_route_enforcement.py \
  orchestrator\tests\cosmo\test_security_perimeter_negative.py \
  orchestrator\tests\cosmo\test_negative_security_matrix.py \
  orchestrator\tests\cosmo\test_persistent_release_pipeline.py -q
→ 262 passed

.venv\Scripts\python.exe -m pytest orchestrator\tests\cosmo -q
→ 1902 passed, 6 failed (известный фон, вне следа), 7 skipped
```

Известный фон (не связан с COS-066, подтверждён прогонами до/после):
4 table-count теста (Luna: ожидают 23/27 таблиц, в БД 31 — 4 таблицы
уведомлений COS-055 Flash), `test_int_registry_smoke::test_caddy_uses_8180`
(инфра-Caddyfile), `test_notification_triggers::test_run_failed_trigger_persists`
("Event loop is closed", notifications/integration.py:284).

## 11. Изменённые поверхности

| Файл | Изменение |
|---|---|
| `orchestrator/cosmo/api/routes/transfer.py` | anti-spoofing: `_principal_domain`/`_context_domain`/`_authorize_record_access` (3-арг), заголовок удалён из 7 read/mutation сигнатур; OpenAPI 404 для landing/{transition} |
| `orchestrator/tests/cosmo/test_transfer_security_matrix.py` | НОВЫЙ: 24 теста (auth/ownership/error/idempotency/OpenAPI матрицы) |
| `orchestrator/tests/cosmo/test_deps_guard_regression.py` | НОВЫЙ: 6 тестов (10 guarded маршрутов × 4 сценария) |
| Kernel/`transfer/*`, `deps.py`, `repos.py` | БЕЗ изменений (regression-only подтверждён) |
