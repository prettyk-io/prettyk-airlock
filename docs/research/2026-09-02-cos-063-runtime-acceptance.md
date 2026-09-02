# COS-063 — Infrastructure Runtime Acceptance (Buddy, infra scope)

Дата: 2026-09-02. Статус: **ACCEPTED** (инфра-часть). Коммит не выполнялся (ждёт команды PO).

## 1. Результат

| Проверка | Результат |
|---|---|
| Clean-slate cold start (wipe volumes + rebuild) до /ready=ok | **16.3 s** |
| Полная цепочка миграций на чистой БД | **8 шагов, 32 таблицы, head d2e3f4a5b6c7** |
| Smoke delivery | **9/9, exit 0** |
| Full profile (10 контейнеров) | **9 healthy + woodpecker server (hc by design)** |
| Restart-preserves-state (domain через API) | **PASS**, API recovery 3.3 s |
| Dependency failure (PG down) | /live 200, /ready 200 `degraded` — см. §4 отклонение |
| SSE keepalive через Caddy | PASS: `: keepalive` на ~15 s, без буферизации |
| cosmo-start.ps1 -Full (idempotent rerun) | 5.7 s, всё зелёное |

## 2. Миграции (Luna, COS-062)

Luna починила цепочку в working tree (файлы 00:41–00:55): новая миграция
`c1d2e3f4a5b6_cos062_releases_table` (после initial, до builds/deployments FK) +
`d2e3f4a5b6c7_cos062_schema_reconciliation` (guarded indexes + drift verification —
падает с явным списком при расхождении Base.metadata ↔ БД).

Верифицировано на чистой БД из образа: полный `upgrade head` без ошибок.

Entrypoint переписан (services/entrypoint.sh):
- `FRESH` (0 таблиц) → `alembic upgrade head`;
- `LEGACY` (таблицы есть, alembic_version нет — create_all-эра) → `alembic stamp head` (гайд Luna);
- `STAMPED` → `alembic upgrade head`.

## 3. Инфра-фиксы delivery-профиля

| Проблема | Фикс |
|---|---|
| Gitea ждёт install wizard, /api/v1/version → 404 → unhealthy | `GITEA__security__INSTALL_LOCK: "true"` + idempotent admin-create в cosmo-start.ps1 (`gitea admin user create -u git`) |
| Gitea host :3000 занят PureK juice-shop | host-port **3100** (внутренний 3000, Caddy-роут не меняется) |
| Woodpecker agent: auth DeadlineExceeded loop | **`WOODPECKER_SERVER=passthrough:///cosmo-woodpecker:9000`** — grpc-go dns resolver вешается на Docker embedded DNS (SRV/TXT дропаются). Доказательство: минимальный Go-клиент — dns → 5.00 s DeadlineExceeded, passthrough → 0.02 s OK (python grpcio работал всегда) |
| Woodpecker server: distroless (нет sh/curl/wget), healthcheck 127 | healthcheck disable; внешний probe в smoke (HTTP :8000). Server-side `WOODPECKER_AGENT_SECRET` pin (иначе random → агент никогда не авторизуется) |
| Agent persisted agent.conf после wipe серверной БД | deadlock «AgentID not found» → **stateless re-register** (без volume; лог-error «could not persist» — ожидаемый cosmetic) |
| Чистый volume не создаёт side-DB (Gitea/Woodpecker ждут install/init) | `services/postgres-init/01-cosmo-side-dbs.sql` (docker-entrypoint-initdb.d) |

## 4. Отклонение от критерия (для Luna/Cosmo)

Критерий COS-063: dependency failure → `/ready` **503**.
Факт: PG down → `/ready` **HTTP 200** `{"status":"degraded","database":"unavailable"}`.

health.py отдаёт 200 всегда, факты в теле. Для локального dev — ок, но для
K8s-доставки (helm из OWN-BUDDY-001) это риск: `readinessProbe` считает non-2xx
fail → при БД down под остаётся в балансировщике.

**Рекомендация**: `/ready` → 503 при `status != ok` (для `degraded` — по решению PO:
либо 503 всегда, либо degraded=200 только для cache-loss, 503 при db-loss).
health.py — продуктовая зона, в infra-скоупе не менялось.

## 5. Изменённые файлы (working tree, без коммита)

- `services/entrypoint.sh` — migration-aware bootstrap (FRESH/LEGACY/STAMPED)
- `services/docker-compose.yml` — gitea INSTALL_LOCK + :3100, woodpecker secret + passthrough + hc, agent deps, postgres-init mount
- `services/postgres-init/01-cosmo-side-dbs.sql` — новый
- `services/scripts/cosmo-start.ps1` — шаг gitea admin bootstrap (idempotent)
- `services/.env.example` — template (из COS-059)

## 6. Порт-канон (полный профиль)

| Сервис | Хост:порт |
|---|---|
| Caddy edge (frontend/API/SSE) | 8180 |
| API direct | 8100 |
| PostgreSQL | 5432 |
| Valkey | 6379 |
| Registry (ЗР, distribution) | 5100 |
| Gitea | **3100** (внутр. 3000; host :3000 = PureK juice-shop — никогда) |
| Woodpecker server | 8000 |
| MinIO | 9000/9001 |
| OpenBao | 8200 |
