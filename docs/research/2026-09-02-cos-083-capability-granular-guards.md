# COS-083 — Capability-Granular Guards Pass 2 + Domain Access Unification

> **Дата:** 2026-09-02 · **Apex** (worker-сессия, отчёт → Cosmo → Максим)
> **Deps:** COS-077 (закрыт, принят 2274/2/0 ×2)
> **Финальное состояние:** полный cosmo-суит **2224 passed / 2 skipped / 0 failed**
> (×2 детерминированно, изолированная test-БД).

---

## 1. Постановка

COS-077 закрыл transfer-wiring, но write-поверхности оставались с coarse-гвардом
«любой аутентифицированный principal», а доменный резолв caller'а был размазан
по route-файлам тремя разными паттернами. Карточка COS-083:

1. Capability-гранулярность guard'ов: builds/deployments, projects/groups,
   repo-binding, lifecycle-config.
2. Доменный scoping read-списков (не-админ видит только свой домен).
3. Единый резолв домена caller'а во всех route-файлах + тест-инвариант.
4. Регрессионный suite расширяется под всё это.

Out of scope: ledger (Luna COS-082), gate trail (Boss COS-081), notifications
(Flash COS-079), миграции (заморожены до админой воли).

## 2. Что сделано

### 2.1 Новые capability Actions (rbac.py)

| Action | Назначение | Бандлы | Зоны |
|---|---|---|---|
| `build:run` | запуск/аборт билдов | ADMIN_SERVICE, SERVICE_ADMIN, DEVELOPER_LEAD, DEVELOPER, QA_ENGINEER | ZR, ZT |
| `deploy:manage` | деплой/rollback | ADMIN_SERVICE, SERVICE_ADMIN, DEVELOPER_LEAD, RELEASE_MANAGER, ZONE_OPERATOR_ZPE | ZR, ZT, ZPE |
| `project:write` | CRUD проектов/групп | ADMIN_SERVICE, SERVICE_ADMIN, DEVELOPER_LEAD, PRODUCT_OWNER | только ZR |

Замороженный baseline RBAC-матрицы обновлён в `test_rbac_regression.py`
(+23 assignment'а: base 37→40, cbr 116→127, zones 105→114, total 258→281).

### 2.2 Guard'ы по route-файлам

| Файл | Изменения |
|---|---|
| `builds.py` | trigger/abort: `require_capability(BUILD_RUN)`; scoping read'ов по `app.domain_id` через resolve |
| `deployments.py` | create/rollback: `require_capability(DEPLOY_MANAGE)`; list — `get_current_principal` (аноним → 401), scoping не-админа |
| `projects.py` | create/update: `PROJECT_WRITE`; get/list/update — non-admin scoping через `_caller_domain_app_ids` + redaction `application_ids`; ghost-404 |
| `apps.py` (551 стр.) | repo-binding PUT: `BRICK_MANAGE`; groups: create `BRICK_MANAGE` + non-admin binding 403, list `require_principal` + scoping, get `require_principal` + verify, **delete_group был ANONYMOUS WRITE → закрыт**; **lc-config PUT был ANONYMOUS WRITE → закрыт** (`BRICK_MANAGE`), get `require_principal` + verify; update/delete app — non-admin wrapper через resolve |
| `evidence.py` | 3 handler'а: header + non-admin verify через resolve |
| `gates.py` | 4 verify-сайта → header + resolve; `record_gate_decision` резолвит домен ресурса по цепочке gate → plan → app |
| `runs.py` | `cancel_run` → header + resolve |
| `releases.py` | `transfer_release` + v2 → header + resolve |
| `pipelines.py` | `compile_plan` → header + resolve |

Попутно закрыты 3 adjacent-дыры (delete_group, lc-config PUT — оба были
анонимными записями; get_group/get_lifecycle_config — анонимные чтения).

### 2.3 Единый резолв-контракт (`domain_guard.resolve_caller_domain`)

```text
system admin : X-Cosmo-Domain (легитимный context switch)
              → principal.domain_id (identity fallback)
              → "default"
не-админ     : principal.domain_id (заголовок НЕ расширяет доступ)
              → legacy-fallback requested_domain → "default"
```

- **Ghost-контракт:** чужой ресурс → 404 (не раскрываем существование),
  одинаковый для не-админа и для админа вне резолвнутого домена. Админ
  кросс-доменно работает через `X-Cosmo-Domain`.
- Прямой вызов хендлера (unit-стиль) даёт дефолт FastAPI — объект `Header`
  вместо строки; resolve трактует не-`str` как отсутствующий (coercion).
- **Тест-инвариант** `test_domain_resolve_invariant.py` (3 passed): source-scan —
  рядом с каждым `verify_ownership` импортирован `resolve_caller_domain`; в окне
  300 символов после `verify_ownership` нет raw `principal.domain_id`; shape
  контракта зафиксирован.

### 2.4 Flavour policy в apps.py (осознанное решение)

Item reads/mutations — non-admin-only verify (админ bypass) для сохранения
админ-тестов без заголовков; create_group/delete_group/lc-config/repo-binding —
capability + verify после fetch (в т.ч. безусловный verify для не-админ-веток
через единый resolve).

## 3. Баги, найденные fallout'ом (prod-код)

1. **builds.py trigger** — `cosmo_builds.title` NOT NULL: создание билда падало
   в БД. Fix: `title=f"Build {app.id}@{commit_sha[:8]}"`.
2. **builds.py / deployments.py** — обращение к `app.name`, которого нет в
   `ApplicationModel` (только id/domain_id/level/group_id). Fix: `app.id`.
3. **domain_guard.resolve_caller_domain** — AttributeError `'Header' object has
   no attribute 'strip'` при прямом unit-вызове хендлера (3 legacy-сюиты так
   тестируют). Fix: coercion не-str → None.

## 4. Тестовая хирургия

| Файл | Что |
|---|---|
| `test_deps_guard_regression.py` | GUARDED_ROUTES 10→22; GUARD_PASS_MATRIX +12 строк (svc/dev/relmgr/owner); `_set_role(kind, domain_id, zone)`; классы **TestCapabilityGranularity** (7: ролевая гранулярность + zone-матрица ZR/ZT/ZPE) и **TestDomainScopingReads** (5: projects/groups/build-deploy scoping, ghost-404, redaction); seed-хелперы чинить под ghost-контракт (кросс-доменные админ-операции с заголовком) |
| `test_domain_resolve_invariant.py` | **новый**, 3 passed |
| `test_rbac.py` + `test_rbac_regression.py` | замороженный baseline +3 Actions по инструкции самого теста («update both rbac.py AND this test») |
| `test_final_luna_001.py` | инвариант «domain-free» смягчён корректно: caller_domain разрешён как **опциональный** параметр (identity — первичный резолв), обязательным быть не должен |
| `test_lr_persist_api_visiblity.py`, `test_post_luna_001_semantic_boundary.py` | мок-приложениям проставлен `domain_id="default"` под ghost-контракт |
| `test_nx_luna_integration.py` | admin-principal в тесте обновления проекта явно `is_system_admin=True` (scoping-ветка не-админа требует доменных данных) |
| `test_api_routes.py` | PUT repo-binding — заголовок `X-Cosmo-Domain` |
| `conftest.py` `_wipe` | + LR-таблицы: cosmo_deployments, cosmo_builds, project_applications, project_teams, projects, kits_tags |

## 5. Детектив: «мистерия app-alpha»

Симптом: строка `apps` существует (raw SQL и ORM видят), `GET /api/v1/apps/app-alpha`
→ 404, при этом compile (db.get) находит приложение. Зонд внутрь хендлера
показал: `found=True` **внутри** get_application, а 404 приходит после — из
`verify_ownership` (ghost-ветка). Это **не баг, а спроектированное поведение**:
админ без заголовка резолвится в свой домен (`test`), приложение в `alpha` →
честный ghost-404; админ получает доступ кросс-доменно через `X-Cosmo-Domain`.
Падавшие тесты не несли заголовок в seed'ах — тест-fallout, исправлен.

## 6. Изоляция прогонов (паттерн COS-077)

Общий test-PG нестабилен из-за параллельных worker-сессий (4 чужих соединения
с COMMIT 1-3с назад, «Domain test not found» сразу после 409). Поднята
scratch-БД **`cosmo_test_apex`** на том же инстансе (:5433):

```powershell
$env:COSMO_TEST_DATABASE_URL="postgresql+asyncpg://cosmo:cosmo@127.0.0.1:5433/cosmo_test_apex"
python -m pytest orchestrator\tests\cosmo -q
```

conftest читает env `COSMO_TEST_DATABASE_URL`. Все прогоны этой карточки — в ней.

## 7. Результаты

| Сьют | Результат |
|---|---|
| `test_deps_guard_regression.py` | **22 passed** |
| `test_domain_resolve_invariant.py` | **3 passed** |
| `test_api_routes.py` + builds/deployments | 14 passed |
| **Полный cosmo-суит** | **2224 passed / 2 skipped / 0 failed ×2** (2:32 и 2:43) |
| py_compile | OK на всех затронутых файлах |

Наблюдение: счётчик коллекции тестов зависит от состояния БД на момент
collection (+3 теста, параметризация от данных) — детерминированно при
стабильном состоянии, не блокер.

## 8. Follow-ups (в backlog, не в этой карточке)

1. **bricks CRUD + POST /plans** — остаются anonymous writes (та же семья, что
   закрытые здесь delete_group/lc-config; отдельная карточка).
2. **`_wipe`: transfer_*-таблицы** — сознательно не тронуты, зона Boss
   COS-078; скоординировать, чтобы не пересечь поверхность.
3. **ProjectTeam `team`** — без доменного якоря; кандидат на доменный scoping
   в следующем guard-pass.
4. **Collection-time параметризация от состояния БД** — грязная test-БД меняет
   число собираемых тестов; добавить фиксацию снапшота коллекции.
