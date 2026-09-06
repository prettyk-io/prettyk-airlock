# COS-067 Research: deps._guard Domain Binding Hardening

- **Дата:** 2026-09-02
- **Пакет:** deps._guard Domain Binding Hardening
- **Worker:** Apex (DeepSeek V4 Pro)
- **PO:** Cosmo
- **База:** COS-066 (accepted) — transfer.py hardening, `test_transfer_security_matrix.py`
- **Статус:** реализация завершена, acceptance выполнен

---

## 1. Проблема

COS-066 зафиксировал finding: `deps.require_capability._guard` для не-админа
берёт домен операции из заголовка `X-Cosmo-Domain` и **не связывает его с
`principal.domain_id`**. Обход 10 guarded маршрутов (вне transfer/) показал:

1. **Все 10 хендлеров игнорируют заголовок** — домен операции берётся из
   клиентского ввода (`body.domain_id` или домен целевого ресурса) без
   ownership-проверки.
2. **6 read/PATCH-путей** резолвят контекст через
   `Depends(require_domain)` → заголовок мог расширить чтение на чужой
   домен (spoof).
3. **UX-инверсия:** хендлеры заголовок игнорируют, но guard его требует
   (400 без заголовка) — обязательный, но бесполезный параметр.
4. Мёртвые импорты `verify_ownership` (gates.py, projects.py) при полном
   отсутствии ownership-чеков в этих маршрутах.

## 2. Решение: `domain_binding` — три режима

`require_capability(action, target_scope=None, domain_binding="header")`:

| Режим | Поведение | Где применяется |
|---|---|---|
| `"header"` (default) | Legacy COS-058: 400 нет заголовка / 404 ghost / RBAC. Без binding. | transfer/ (не тронут, COS-066) |
| `"header_bound"` | 400 нет → **403 mismatch ДО проверки существования** (без утечки существования доменов) → 404 ghost | зарезервирован |
| `"identity"` | Контекст = `principal.domain_id`; заголовок не нужен и игнорируется | все 10 маршрутов |

### 2.1. Миграция 10 маршрутов на identity

| Маршрут | Action | Ownership/binding |
|---|---|---|
| `POST /plans/compile` | PIPELINE_CONFIGURE | `verify_ownership(app.domain_id)` |
| `POST /releases` | RELEASE_CREATE | binding 403: `body.domain_id != principal.domain_id` |
| `POST /releases/{id}/transfer(-v2)` | RELEASE_TRANSFER | `verify_ownership(rel.domain_id)` |
| `POST /gates/{id}/decision` | GATE_DECIDE | ownership по цепочке **gate → plan → app** |
| `POST /apps` | BRICK_MANAGE | binding 403 |
| `PUT /apps/{id}` | BRICK_MANAGE | `verify_ownership(app.domain_id)` |
| `DELETE /apps/{id}` | BRICK_MANAGE | `verify_ownership(app.domain_id)` |
| `POST /runs` | SCAN_START | binding 403 |
| `POST /runs/{id}/cancel` | SCAN_STOP | `verify_ownership(run.domain_id)` |

Ownership-чеки **условные** (`if not principal.is_system_admin`) — admin
тест-флоу создаёт ресурсы в чужих доменах при `principal.domain_id="test"`.

### 2.2. Read-пути: `resolve_caller_domain`

Новый helper в `domain_guard.py`:

- не-админ → `principal.domain_id` (заголовок не может расширить чтение);
- system admin → заголовок (легитимный context switch), `None → "default"`.

6 read/PATCH-сайтов (releases list/get/envelope, runs list/get/patch-status)
переведены с `Depends(require_domain)` на
`Header(None, alias="X-Cosmo-Domain")` — **заголовок больше не обязателен**,
spoof через заголовок для не-админа невозможен.

### 2.3. Gate ownership через цепочку

Модель `Gate` **не имеет колонки domain_id** (прямое чтение `gate.domain_id`
дало бы AttributeError → 500). Домен резолвится:
`gate.plan_id → PipelinePlan.app_id → Application.domain_id`.
Заодно закрыт слепой spot: `POST /gates` создаёт gate без домена вообще
(зарегистрировано как finding, см. §5).

## 3. Сопутствующие баги, вскрытые seed'ом

Позитивный сценарий (создание app → plan → run → release) вскрыл два 500
на валидных телах:

1. **`create_release` передаёт `trigger=` и `changelog=`**, которых нет у
   `Release`-модели → TypeError → 500. Фикс: поля убраны из конструктора
   (Pydantic-схема сохранила контракт; `trigger`/`changelog` в ответе —
   defaults через `getattr`).
2. До этого `envelope`-путь и `record_gate_decision` (`_guard` → `principal`)
   уже были починены в рамках пакета.

## 4. Тесты

- `test_deps_guard_regression.py` — переписан (10 тестов):
  - матрица guard: USER → 403 (заголовок не нужен; ghost не течёт),
    anonymous → 401, holders (SERVICE_ADMIN / RELEASE_MANAGER /
    ADMIN_SEC по матрице caps) проходят guard без заголовка;
  - acceptance-ядро: spoof чужого **существующего** домена → 403 binding
    (create-пути) / 404 ownership (resource-пути), read не расширяется
    заголовком, ghost-заголовок не блокирует и не утечает;
  - admin context switch через заголовок сохранён;
  - полный own-domain workflow без единого заголовка
    (BRICK_MANAGE → SCAN_START → RELEASE_CREATE → GATE_DECIDE → reads).
- `test_sod_and_transfer_linear.py` — прямые (unit) вызовы хендлеров
  дополнены `principal=_api_principal()` (system-admin): ownership-чек —
  новый контракт тела хендлера; SoD тестируется через `decided_by` /
  `initiator` как раньше. Также заменён устаревший `_guard=` kwarg.
- `test_release_envelope.py` — `get_release_envelope` unit-вызов получил
  principal (не-админ `dom-corp`, заодно покрывает identity-путь reads).

### 4.1. Роли в матрице (RBAC COS-096/110)

`Role.MANAGER` не существует. Покрытие caps по маршрутам:

- `CBRRole.SERVICE_ADMIN` → PIPELINE_CONFIGURE, BRICK_MANAGE, SCAN_START
- `CBRRole.RELEASE_MANAGER` → RELEASE_CREATE, RELEASE_TRANSFER
- `Role.ADMIN_SEC` → GATE_DECIDE, SCAN_STOP (SERVICE_ADMIN не имеет SCAN_STOP)

## 5. Findings (вне scope, зарегистрированы для Cosmo)

1. **Unauthenticated surfaces:** `repos.py`, `audit.py`, `domains.py`
   (POST/PUT/DELETE), `notifications.py`, `metrics.py`, `status.py`,
   `evidence.py`, `findings.py`, `artifacts.py` — нет principal-dependency;
   мутации (POST /api/v1/domains, запись файлов repos) доступны анонимно.
   Починка = контрактное изменение → отдельная карточка.
2. **`POST /gates` без capability-guard и без domain_id:** gate создаётся
   без домена (ownership decision-чек решает через цепочку, но привязка
   gate→домен на момент создания отсутствует).
3. **Notification Manager** — без `require_capability` (контракт
   COS-055/056, зона Flash; не тронут).
4. **Миграционный тест-кластер нестабилен:** `test_migrations` /
   `test_migration_reconciliation` ждут scratch-БД `cosmo_mig_recon`
   (createdb/dropdb через subprocess); после рестарта PG дают переменный
   состав падений (6↔9) независимо от кода API. Рекомендуется отдельная
   карточка на стабилизацию (идемпотентный bootstrap scratch-БД).
5. SAWarning в `test_steel_thread` ссылается на путь `D:\cosmoport2\...`
   (stale-путь предупреждения; тест зелёный, пакеты резолвятся из
   `D:\prettyk-airlock`).

## 6. Acceptance

- Матрица principal-class × guarded route: держатель capability **не может
  оперировать под чужим существующим доменом** — ни read, ни mutation. ✅
- Отказы явные: 403 (binding) / 404 (ownership, анти-дисклеймер), **0 × 500**. ✅
- Transfer-набор (COS-066 header-режим) не тронут: `test_transfer_api` +
  `test_transfer_security_matrix` + `test_transfer_kernel` + SoD + envelope +
  steel_thread — **135 passed**. ✅
- Полный suite: `2020 passed / 6 failed / 2 skipped` — фон (миграционный
  кластер нестабилен независимо от пакета; caddy-порт; notification
  trigger). Поверхности пакета — зелёные. ✅

## 7. Изменённые поверхности

```
orchestrator/cosmo/api/deps.py                  — require_capability: 3 режима
orchestrator/cosmo/api/domain_guard.py          — resolve_caller_domain
orchestrator/cosmo/api/routes/apps.py           — 3 хендлера (identity + ownership)
orchestrator/cosmo/api/routes/pipelines.py      — compile_plan (identity + ownership)
orchestrator/cosmo/api/routes/releases.py       — create/transfer×2/reads (identity, Header optional); фикс 500 create_release
orchestrator/cosmo/api/routes/gates.py          — decision (identity, ownership через цепочку)
orchestrator/cosmo/api/routes/runs.py           — create/cancel/reads (identity, Header optional)
orchestrator/tests/cosmo/test_deps_guard_regression.py      — переписан
orchestrator/tests/cosmo/test_sod_and_transfer_linear.py    — principal в unit-вызовах
orchestrator/tests/cosmo/test_release_envelope.py           — principal в unit-вызове
```

Не тронуто: `transfer.py` (COS-066-паттерн), `notifications/**`, миграции,
модели БД (кроме чтения).
