# COS-094: Prod edge + airgap profile hardening — Acceptance Report

**Дата:** 2026-09-02
**Карточка:** BACKLOG.md COS-094 (Boss, 8-12h, P1, dep COS-063)
**Статус:** DONE. Не закоммичено. App-код не тронут (только edge-конфиги + доки + тесты).

## Решение по каноническому edge-пути (п.1 карточки)

Канонический внешний entry point — **Caddy** (:8180; rate limit COS-067,
TLS-профили, /forge /artifacts /registry /metrics) — остаётся единственным
production-путём.

`cosmo-frontend` (nginx, :5174) — **same-origin front door SPA**: React зовёт
относительный `/api/v1/...`, поэтому тот же origin обязан обслуживать API —
иначе браузер получает SPA-HTML/405 (исходный дефект карточки). Это не второй
production edge: без rate limit и TLS; назначение — прямая работа со SPA и
приёмка «как увидит браузер». Решение зафиксировано в DEPLOYMENT.md §7.0.

## Изменения

- `frontend/nginx.conf` — переписан (same-origin API edge):
  - `/api/` → `cosmo-api:8100` (путь сохраняется), `client_max_body_size 256m`
    (ingest-пейлоады больше nginx-дефолта 1m → был бы 413);
  - SSE (`runs/*/stream`, `domains/*/events/stream`, `notifications/stream`
    — AlertHUD живёт постоянно): `proxy_buffering off`, HTTP/1.1 keepalive,
    read/send timeout 3600s;
  - `/live` `/ready` `/health` — честный passthrough (503 при PG down);
  - `resolver 127.0.0.11 valid=10s` + переменная upstream: cosmo-api
    перерезолвливается, переживает пересоздание контейнера API без reload;
    внешних DNS нет (airgap-безопасно);
  - SPA fallback и кэш /assets/ сохранены.
- `frontend/Dockerfile` — заголовок: актуальный порт 5174 + роль same-origin edge.
- `services/docker-compose.yml` — НЕ менялся (зависимости/сети достаточны).
- `docs/DEPLOYMENT.md` — §7.0 (edge-решение), §5.5 (airgap-чеклист).
- `orchestrator/tests/cosmo/test_prod_edge_config.py` — НОВЫЙ, 9 статических
  контрактов: API проксирован (fallback не съедает /api), SSE unbuffered +
  3600s, health passthrough, нет внешних DNS, body-limit, SPA fallback,
  Caddy flush_interval -1 + rate limit + ordering health-до-api.

## Верификация (acceptance)

**Smoke через 5174** (curl — wire-эквивалент браузера; браузерный прогон не
делался, честно отмечено):
- REST authed (JWT `ey...`, COS-085): `GET /api/v1/domains` → **JSON, 200**
  (было: SPA-HTML); неавторизованный → JSON 401 — тоже API-ответ, не SPA;
- SSE: `POST /api/v1/notifications/sse-ticket` через edge → ticket;
  `GET /api/v1/notifications/stream?ticket=...` → `stream_backlog` +
  `notification_initial` приходят немедленно, `text/event-stream`, 200 —
  **байт-в-байт как напрямую 8100**, буферизации нет;
- `/ready` через edge: **200** `{"status":"ok",...}`; `docker stop
  cosmo-postgres` → **503** с честным компонент-мапом (COS-090 passthrough);
  recovery → 200;
- SPA root → 200 text/html, React Router не задет.

**Airgap (acceptance: cold start без внешней сети):**
- инвентарь: `docker compose --profile full config --images` → 10 образов,
  все локальны, теги закреплены (не latest);
- **cold start**: `compose --profile full down` → `up -d --profile full
  --pull never` → **EXIT=0**, 10/10 Up (9 healthy + woodpecker: distroless,
  healthcheck disabled by design, внешний probe :8000/api/health = 200);
- после пересоздания контейнеров nginx сам перерезолвил cosmo-api
  (проверка resolver-конфига) — edge работает без reload;
- healthchecks: все probe localhost/внутренний compose-DNS; тяги в compose
  нет; ACME в airgap-профиле Caddy отсутствует.
- Digest-pin — TODO при production freeze (заглушки в compose) —
  зарегистрировано в чеклисте §5.5 как обязательное действие перед
  поставкой.

**Сюит**: suite gate → **2322 passed / 2 skipped / 0 failed, PASS, exit 0**
(+10 тестов к COS-090-му прогону: 9 edge + чужие воркеры).

## Грабли сессии
- Auth: opaque `gate-agent:admin_sec` закрыт COS-085 → токен минтился
  JWT-формой (`eyJ<header>.<payload-b64>.<sig>`, claims sub/roles/is_admin).
- Тело SSE-тикета/домены: PowerShell curl.exe `-d` калечит JSON-кавычки →
  422; приёмка через curl с файлами/ConvertFrom-Json.
- Третий SSE-эндпоинт (`notifications/stream`) не имел явной SSE-локации —
  упал бы в generic /api/ с 300s timeout; включён в combined SSE-локацию.

## Границы
- TLS-терминация (отдельная карточка), app-код (backend/frontend) не тронут,
  миграционная цепочка — вне скоупа. Caddyfile не менялся (уже соответствовал).
- Commit/push — только по явной команде.
