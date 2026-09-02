# COS-090: /ready honest signaling (K8s readiness) — Acceptance Report

**Дата:** 2026-09-02
**Карточка:** BACKLOG.md COS-090 (Boss, 2-4h, P2, dep COS-089 пп.1-2)
**Статус:** DONE (решение Максима по п.3 COS-089 реализовано). Не закоммичено.

## Решение (PO, 2 сентября)
K8s readiness-семантика: `/ready` = 200 только когда ядро способно
обслуживать запросы; недоступный PostgreSQL (hard-dep) → **503 + честный
компонент-мап в теле**, чтобы Caddy/upstream вывел инстанс из ротации.
Мягкие деградации (Valkey → SSE in-memory fallback COS-088; anchor sink →
честный `unknown_anchor` на verify COS-087) НЕ роняют readiness — видны в
теле (`cache/anchor: "unavailable"`, сводный `status="degraded"`) и в
`X-Cosmo-Backlog` на SSE-ручках (не тронуто, вне скоупа).

## Изменения
- `orchestrator/cosmo/api/health.py`:
  - `ReadyResponse` + поле `anchor` ("connected" | "disabled" |
    "unavailable"); обратно совместим — database/cache сохранены.
  - Новая проба `_probe_anchor` (soft): sink не трогает (append-only!),
    проверяет только наличие/доступность директории и файла; env не задан
    → `disabled` (не деградация). Ошибки — sanitized, путь sink не
    раскрывается.
  - `ready()`: PG unavailable → `JSONResponse(503, компонент-мап)`
    (не HTTPException — тело не заворачивается в `{"detail": ...}`);
    PG available → 200, `status = ok|degraded` по soft-компонентам.
- `docs/DEPLOYMENT.md` §13.1 — семантика переписана, закрывает известное
  отклонение COS-063 (`/ready=200 degraded` при падении PG).
- `services/scripts/runtime-gate.ps1` — dep-failure: ветка 200+unavailable
  теперь DEVIATION-регрессия (было «known, pending PO»); 503 = PASS
  (ветка существовала с COS-064).
- `docs/cosmo-openapi.json` + `cosmo-openapi.yaml` — ReadyResponse:
  добавлен `anchor` в properties+required, description обновлён.

## Тесты (4 новых, `test_api_routes.py`)
`test_ready_pg_up_valkey_down_is_200_degraded`,
`test_ready_pg_down_is_503_with_component_map` (+ `"detail" not in body`),
`test_ready_both_soft_ok_and_anchor_healthy_is_200_ok`,
`test_ready_anchor_sink_broken_does_not_drop_readiness`.

Грабля: тесты, ходящие РЕАЛЬНОЙ PG-пробой, падали в full-file прогоне
(`Event loop is closed`) — глобальный синглтон engine от предыдущего теста
привязан к закрытому лупу (COS-075). Фикс — opt-in фикстура
`loop_safe_engine_reset` в сигнатуре всех четырёх ready-тестов.

## Верификация (всё acceptance-критерии)
- **Живьём** (стенд docker, cosmo-api пересобран — код в образе, не volume):
  - baseline: **200** `{"status":"ok","database":"connected","cache":"connected","anchor":"disabled"}`;
  - `docker stop cosmo-postgres` → **503** с телом
    `{"status":"not_ready","database":"unavailable","cache":"connected","anchor":"disabled"}`;
  - PG down + Valkey down → 503;
  - recovery PG, Valkey down → **200** `status="degraded"`, `cache="unavailable"`;
  - полный recovery → 200 ok.
- **docker healthcheck** cosmo-api бьёт в `/live` (не /ready) — при падении
  PG контейнер API остаётся healthy, ротацию выводит upstream через 503 —
  противоречий нет. **Caddy** — reverse_proxy pass-through, тело 503
  доходит клиенту. **K8s** readinessProbe `/ready`: не-2xx выводит pod из
  ротации — семантика совпадает.
- **Полный сет**: suite gate → **2312 passed / 2 skipped / 0 failed,
  SUITE GATE: PASS, exit 0** (2312 > 2239 — чужие воркеры добавили тесты;
  новых падений нет). OpenAPI-контракт 12/12.
- Файл-грабля PS5.1: `-replace` с литеральным `` `n `` в одинарных кавычках
  НЕ разворачивается в newline — правка через `.Replace("``n", [Environment]::NewLine)`.

## Границы
- Не тронуто: миграционная цепочка, integration/conftest (Luna), rbac/deps
  (Apex), SSE-ручки (флаг X-Cosmo-Backlog уже соответствует семантике),
  smoke-delivery.ps1 (чек «/ready = 200 status ok» остаётся верным для
  полного стенда).
- Commit/push — только по явной команде.
