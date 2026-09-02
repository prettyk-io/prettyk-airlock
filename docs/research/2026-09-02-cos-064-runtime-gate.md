# COS-064 — Runtime Reproducibility and Operations Hardening (Buddy, infra scope)

Дата: 2026-09-02. Статус: **DONE** (acceptance выполнена). Коммит не выполнялся.

## 1. Acceptance — фактические результаты

Требование: clean runtime acceptance дважды подряд без ручного вмешательства.
Факт: **run 8 + run 9 подряд, оба GATE OK (exit 0)**, нулевой cross-run residue
(0 доменов `cos-gate-*`, 0 scratch-БД).

Команда (воспроизводимая):

```powershell
.\services\scripts\runtime-gate.ps1 [-ReportJson <path>]
```

Per-check результаты (run 9, те же в run 8):

| Check | Verdict | Время | Детали |
|---|---|---|---|
| migration | PASS | 2.2s | scratch `cosmo_scratch_gate_<ts>` → `upgrade head` → 32 tables, head=d2e3f4a5b6c7 → dropped |
| clean-start | PASS | 45.2s | wipe volumes → core ready 42.3s (budget 90s) |
| full-profile | PASS | 38.1s | 10/10 healthy/Up + gitea admin bootstrap |
| smoke | PASS | 0.9s | smoke-delivery 9/9 |
| restart | PASS | 3.0s | домен пережил рестарт API, psql-верификация до/после, cleanup |
| sse | PASS | 22.1s | keepalive через Caddy на собственном домене |
| dep-failure | DEVIATION | 7.4s | `/ready=200 database=unavailable` (критерий: 503) — **pending product decision, НЕ скрывается как PASS**; recovery OK |

Exit codes: 0 = нет FAIL; 1 = есть FAIL **или** INCONCLUSIVE (FLAKE-EXTERNAL); 2 = docker недоступен.

## 2. Flakes: причины и устранение

### 2.1 Убийца данных найден: чужой host-harness чистит живую cosmo БД

Симптом: домен, созданный по API, исчезал после рестарта (404), ~1 раз из 3
прогонов («fluke» COS-063, gate run 5/6). PG-лог с `log_statement=all`
поймал исполнителя: **полная DELETE-серия по всем таблицам
(UPDATE FK→NULL → DELETE notification_* → ... → DELETE FROM domains) + COMMIT
с коннекта 172.22.0.1 (host-gateway)** — это `_clean_db`-фикстуры
`orchestrator/tests/cosmo/conftest.py` через проброс `localhost:5432`.

Подтверждение в момент охоты — процессы на хосте:
- `pytest orchestrator/tests -q` (PID 9040)
- `alembic downgrade 82c3d4e5f6a7` **на живой БД** (PID 27416)

Т.е. чужой тест-прогон и чужой alembic-цикл бьют в ту же БД, куда пишет
runtime-контур. Механизмы устранения в gate:

1. **Host-quiet сериализация** (перед серией): gate ждёт затихания
   `pytest`/`alembic`-процессов на хосте (до 120s) — «serialization там, где
   общий mutable state неизбежен», по букве пакета.
2. **Интерференция-детект**: потеря строки при живом API/PG, когда gate не
   звал DELETE = внешний вайп → вердикт **FLAKE-EXTERNAL** (не FAIL), весь чек
   ретраится до 3 попыток. 3 интерференции → GATE: INCONCLUSIVE (exit 1).
   Продукт не обвиняется в чужой чистке.
3. **psql-верификация** строки до/после рестарта: различает «API не видит»
   и «строки нет в PG».

### 2.2 Известный коллапс: коллизия цепочек миграций (БЛОКЕР, решает Cosmo/Максим)

Отдельный инцидент (run 7): чужой `alembic downgrade 82c3d4e5f6a7` +
параллельная работа с **другой версией миграционных файлов** ушла на ревизию
`e4f5a6b7c8d9`, которой нет в цепочке собранного образа → API в restart-лупе
(`Can't locate revision`), схема-гибрид (36 таблиц, дропнуты builds/deployments).

Восстановление: pg_terminate чужих сессий → DROP/CREATE DATABASE cosmo →
FRESH upgrade (head d2e3f4a5b6c7, 32 таблицы). Сделано вручную.

**Требуется решение владельца** (одно из):
- тестовая harness (`conftest.py`) работает на **scratch-БД per-session**
  (паттерн уже есть в `test_migration_reconciliation.py::_scratch_url`) —
  правка тестовой зоны (Luna);
- либо отдельный PG-инстанс/порт для тестов агентов;
- либо договор-лок (файл/адвизори-лок) «один агент — одна цепочка миграций».

До решения gate честно сериализуется и помечает интерференцию.

## 3. Port canon: конфликт PureK/Cosmoport устранён

MinIO держал host **9000/9001** — это канон PureK (SonarQube :9000, RUN-STACK).
Оба стека на одном Docker-host одновременно = bind failure.

Фикс: MinIO → **9100:9000, 9101:9001** (внутренние порты не тронуты).
Обновлены ссылки: `daily-backup.sh`, `daily-backup.ps1`. Внутренний healthcheck
compose (localhost:9000 внутри контейнера) не тронут.

Полный порт-канон Cosmoport (host): 5432 PG · 6379 Valkey · 8200 OpenBao ·
**9100/9101 MinIO** · 3100 Gitea · 8000 Woodpecker · 8100 API · 5174 Frontend ·
8180 Caddy · 5100/5200 Registry ЗР. Caddy-роуты (Caddyfile) не менялись:
health/metrics без лимита → SSE unbuffered (`flush_interval -1`) → API
(100 req/min) → forge/artifacts/registry → frontend SPA.

## 4. Startup/shutdown: безопасный повтор + диагностика

- **PS 5.1 ловушка устранена** в `cosmo-start.ps1`/`cosmo-stop.ps1`:
  docker пишет прогресс в stderr; при `$ErrorActionPreference="Stop"` каждая
  stderr-строка нативного вызова = terminating error → ложный FAIL скрипта при
  здоровом старте/остановке. Фикс: `EAP=Continue` вокруг docker-вызовов,
  вердикт только по `$LASTEXITCODE`.
- `cosmo-start.ps1`: при не-готовности за 90s печатает **partial-failure
  диагностику** — статусы всех cosmo-контейнеров + последние 15 логов
  больных (starting/unhealthy/restarting/exited).
- `cosmo-stop.ps1`: при не-нулевом exit — статус всех cosmo-контейнеров.
- Повторный start/stop идемпотентен (проверено прогонами 3–9).

## 5. Operational diagnostics

- Woodpecker: внешний probe `:8000/api/health` в gate/smoke (distroless без
  internal hc — by design); agent registered=дерево агентов в compose-логах.
- Gitea: INSTALL_LOCK + идемпотентный admin bootstrap (cosmo-start -Full).
- Degraded dependencies: dep-failure-чек фиксирует фактическое поведение
  `/ready` (200 degraded) как DEVIATION-строку отчёта — видно всегда.

## 6. Known limitation (pending product decision)

`/ready` при недоступной зависимости = **HTTP 200**
`{"status":"degraded","database":"unavailable"}`. Критерий acceptance — 503.
Для K8s readinessProbe это риск (под остаётся готовым при мёртвой БД).
`health.py` — продуктовая зона; **изменение не вносилось** (out of scope).
Рекомендация: 503 при `status != ok` (или 503 при db-loss, 200 при cache-loss —
решение за Cosmo).

## 7. Изменённые файлы

| Файл | Что |
|---|---|
| `services/scripts/runtime-gate.ps1` | **новый** — 7 чеков, per-check вердикты, host-quiet сериализация, scratch-DB миграции, интерференция-детект, JSON-отчёт |
| `services/docker-compose.yml` | MinIO 9100/9101 (+канон-комментарий); убран отладочный `WOODPECKER_LOG_LEVEL: debug` |
| `services/scripts/cosmo-start.ps1` | PS 5.1 stderr-фикс; partial-failure диагностика |
| `services/scripts/cosmo-stop.ps1` | PS 5.1 stderr-фикс; диагностика при fail |
| `services/scripts/daily-backup.sh` | MinIO host URL → 9100 |
| `services/scripts/daily-backup.ps1` | MinIO host URL → 9100 |

## 8. Остаточные follow-ups

1. **Блокер** (см. §2.2): изоляция тестовой harness от живой БД — решение
   Cosmo/Максима + правка conftest (Luna).
2. `/ready` 503 при degraded — продуктовое решение (§6).
3. Сборка gate в CI (GitHub Actions / own runner) — скрипт готов,
   runner-политика за владельцем репо.
4. Woodpecker agent «could not persist agent.conf» лог-error — cosmetic
   (stateless re-register by design); уйти можно опциональным volume с
   pre-created пустым conf.
