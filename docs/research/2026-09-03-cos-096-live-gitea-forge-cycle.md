# COS-096 — Live Gitea Forge Cycle (acceptance)

Дата: 2026-09-03 · Worker: Dev · Статус: готово к приёмке

## Что требовалось (карточка Boss, 16-24h, P1, dep COS-094)

ForgeAdapter → bind repo → webhook → read source → compile от живого
дерева. Никаких фейков на forge-слое: если Gitea недоступен — честный
502/404, не выдуманные коммиты.

## Что сделано

### 1. Адаптер (orchestrator/cosmo/adapters/forge_gitea.py)
- basic auth (`PK_GITEA_USER`/`PK_GITEA_PASSWORD`) рядом с token;
- `_request` с retry на транзиентах (502/503/504, ConnError, Timeout;
  3 попытки, backoff);
- `read_file(owner, repo, path, ref) -> (content, sha)`; 404 →
  LookupError; **Гите-квирк: пустой репо → 200 + `[]` вместо 404** —
  лист-ответ честно транслируется в LookupError (нашёл live-тест);
- `list_commits(...) -> [GiteaCommit]` (newest first);
- `ensure_webhook(owner, repo, url, secret) -> (hook_id, created)` —
  идемпотентный: reuse существующего hook по URL, патч секрета при
  ротации, без дублей.

### 2. API-слой
- `api/forge_client.py` — единый резолвер адаптера из env +
  нормализация ошибок forge в честный HTTP: ConnError/Timeout/5xx →
  502; auth rejected (401/403) → 502 «rejected credentials» (токен не
  светится); missing repo/file → 404; битый source → 400; no env →
  503 «forge not configured».
- `api/forge_events.py` — in-memory кэш последних пушей по repo_path.
  Честная граница: переживает только процесс; после рестарта пусто =
  пусто (durable-трейл — follow-up, миграционная цепочка frozen).
- `routes/webhooks.py` — `POST /api/v1/webhooks/gitea`: HMAC-SHA256
  подпись (`X-Gitea-Signature`, секрет = тот же, что в ensure_webhook)
  → 401 при плохой; push привязанного репо → кэш + audit → 200; push
  непривязанного → 200 `{"bound": false}` + audit (не тихо); ping/не-push
  → `{"handled": false}`; битый JSON с валидной подписью → 400.
- `routes/audit.py`: `record_system_event()` — системные audit-записи
  (role=forge) в существующий in-memory surface, видны в /api/v1/audit.
- `routes/apps.py`: `GET /api/v1/apps/{id}/forge/last-push` — честный
  статус: last_push из кэша (null = пушей не было), recent_commits из
  живого Gitea, `forge_unreachable` с причиной при недоступности (200,
  не 500 — деградация честно названа); `POST .../forge/webhook-setup` —
  идемпотентный setup hook'а со стороны ПУ (binding.webhook_id
  персистится).
- `routes/pipelines.py`: `POST /api/v1/plans/compile-from-source`
  {plan_id, app_id, source_path=".cosmo/pipeline.yaml", ref} — живой
  source → stages[].brick → резолв в каталоге БД (незнакомый brick —
  404 со списком) → общая персистенция с /plans/compile (вынесена в
  `_compile_and_persist`, без дубля логики).

### 3. Инфраструктура
- `requirements.txt`: + `requests>=2.31` (адаптер — реальная
  зависимость API-образа; без него контейнер падал ModuleNotFoundError).
- compose: `PK_GITEA_URL/USER/PASSWORD/WEBHOOK_SECRET`, `PK_PUBLIC_API_URL`
  для cosmo-api; **`GITEA__webhook__ALLOWED_HOST_LIST: "private"`** —
  дефолт Gitea `external` молча блокирует доставку на cosmo-api:8100
  (корневая причина «пуш не доходит»; для prod — сузить до CIDR при
  freeze; задокументировано в DEPLOYMENT.md §4.2).

### 4. Тесты
- Offline `test_forge_cycle.py` — 26: webhook (bad/missing signature
  401, bound/unbound, ping, битый JSON), last-push (404 unknown app /
  no binding, честная пустота, кэш виден, forge down → 200 +
  unreachable), webhook-setup идемпотентность, compile-from-source
  (happy / ghost-brick 404 / пустые stages 400 / file missing 404 /
  forge down 502 / no binding 404 / duplicate plan 409), маппинг
  ошибок forge (7 юнит-кейсов).
- Live opt-in `test_forge_gitea_live.py` (env `COSMO_LIVE_GITEA=1`,
  паттерн registry-smoke) — 6 против живого Gitea :3100 и живого ПУ:
  read_file roundtrip, list_commits видит живой коммит, bad credentials
  → 401, ensure_webhook ×2 → один hook (created=False), полный цикл
  binding → webhook-setup (из контейнера) → Gitea test-delivery →
  last-push показывает push (source=webhook_cache), compile-from-source
  от живого дерева → план заперсистен и читается обратно. Коммит в
  репо — реальным `git push` (contents API этой сборки Gitea 1.22.6
  требует sha даже на создание и не умеет nested-пути).
- **×2 стабильность: 32/32 × 2 подряд.**

### 5. Frontend (thin)
- `api.ts`: `ForgeLastPush` тип + `getAppForgeLastPush()`;
- `ApplicationDetail.tsx`: карточка «Git-активность (live forge)» в
  Info-табе — последний push (sha/branch/pusher/время), честное «пушей
  не было», честный warning при forge_unreachable, топ-3 живых
  коммитов, refresh-кнопка. tsc чисто, vitest 66/66.

### 6. Контракты/доки
- `docs/cosmo-openapi.json`+`.yaml` пересгенерированы (4 новых пути,
  3 схемы); test_openapi_contract зелёный на моём surface.
- `docs/DEPLOYMENT.md` §4.2 — блок про ALLOWED_HOST_LIST и проверку
  доставки.

## Верификация

| Проверка | Результат |
|---|---|
| Offline forge-тесты | 26/26 |
| Live opt-in (живой Gitea + живой ПУ) | 6/6, ×2 подряд |
| Полный live-цикл руками (webhook → last-push) | подтверждён до/после фиксов |
| vitest | 66/66 |
| tsc -b | 0 ошибок |
| Suite gate | 2366 passed / 3 failed / 3 skipped — **3 фейла НЕ мои**: `test_batch_executor.py` ×2 (чужой WIP в execution_woodpecker.py, +212 строк: появились terminal-статусы skipped/declined, тесты ждут старый сет) и `test_openapi_contract.py::test_no_raw_token_in_parameters` (чужой WIP в domains.py: query-параметр `session_token`). Мой surface зелёный; cosmo-api/cosmo-frontend пересобраны и healthy |

## Честные границы / follow-up
- Кэш last-push и audit — in-memory: рестарт ПУ сбрасывает (пусто =
  пусто); durable-трейл — follow-up вне миграционного freeze.
- Коммит от имени тестов через git push с dev-кредами; prod-секреты —
  через env при freeze.
- Пуш-событие НЕ запускает автокомпиляцию — это следующий шаг после
  приёмки (карточка ограничивалась «ПУ видит коммиты» + compile от
  живого дерева по явному запросу).
- Чужой WIP (execution_woodpecker.py, domains.py) не тронут; 3 красных
  теста полного сета — на нём.
