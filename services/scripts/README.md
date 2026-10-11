# Cosmoport 2.0 — Scripts Reference

## Быстрый старт

```powershell
cd D:\prettyk-airlock

# Поднять стек
docker compose -f services/docker-compose.yml up -d cosmo-postgres cosmo-valkey cosmo-api cosmo-caddy

# Ждать API: curl http://127.0.0.1:8100/live → {"status":"ok"}

# E2E pipeline test
.\services\scripts\run-e2e-pipeline.ps1

# Rate limit verification
.\services\scripts\test-rate-limit.ps1

# Secret rotation (dry-run first!)
.\services\scripts\rotate-secrets.ps1 -DryRun
.\services\scripts\rotate-secrets.ps1
```

---

## Полный каталог скриптов

| Скрипт | Назначение | Платформа |
|---|---|---|
| `run-e2e-pipeline.ps1` / `.sh` | **E2E release pipeline** (COS-091) | Win/Linux |
| `test-rate-limit.ps1` | Rate-limit verification (COS-067) | Win |
| `rotate-secrets.ps1` | Secret rotation via OpenBao (COS-088) | Win |
| `verify-bundle.sh` | Airgap bundle integrity check (COS-038) | Linux |
| `verify-airgap-checksums.sh` | Image digest verification (COS-088) | Linux |
| `airgap-bundle.ps1` | Airgap bundle builder (COS-038) | Win |
| `install.ps1` / `install.sh` | Airgap installer (COS-038) | Win/Linux |
| `openbao-bootstrap.ps1` | OpenBao dev bootstrap: raft + static seal, AppRole, seed (COS-178) | Win |
| `seed-woodpecker-fixture.py` | Woodpecker pipeline-fixture сид: repo + config + activation + прогон (COS-188) | Python |
| `smoke-woodpecker-chunks.py` | Live-смок: реальный пайплайн → SSE log_chunk по проводу, self-skip (COS-188) | Python |
| `seed-sonar-stand.py` | SonarQube CE стенда: токен→OpenBao, проект `owner__repo`, профили PrettyK — идемпотентно (SAST-STAND-4) | Python |
| `build-release.ps1` | Immutable-релизы образов `git-<sha>` + retention (COS-195) | Win |
| `image-hygiene.ps1` | Docker-гигиена: dangling prune + BuildKit keep-storage (COS-195) | Win |
| `check-bind-mounts.ps1` | Compose-чек: только относительные bind-mount'ы (COS-195) | Win |

---

## E2E Pipeline Runner (`run-e2e-pipeline`)

### Что проверяет

Полный боевой сценарий за 8 фаз:

```text
Phase 1: Domain + App L0 + App L1
Phase 2: Bricks (Build, SAST, DAST) + Plan Compilation
Phase 3: Run + Batch Lifecycle (running → passed)
Phase 4: Security Gates (automatic + manual PASS)
Phase 5: GOST-Act (JSON + HTML) + Evidence Chain
Phase 6: Release (create → submit → approve → deploy)
Phase 7: Inter-zone Transfer (ZR → ZT)
Phase 8: Final Verification (domain graph, runs, release, dashboard)
```

### Запуск

```powershell
# Windows
.\services\scripts\run-e2e-pipeline.ps1

# Dry-run (не выполняет запросы — показывает что будет вызвано)
.\services\scripts\run-e2e-pipeline.ps1 -DryRun

# Кастомный URL
.\services\scripts\run-e2e-pipeline.ps1 -BaseUrl http://127.0.0.1:8080
```

```bash
# Linux
./services/scripts/run-e2e-pipeline.sh

# Кастомный URL
./services/scripts/run-e2e-pipeline.sh http://127.0.0.1:8080
```

### Отчёт

После прогона генерируется JSON-отчёт:

```json
{
  "pipeline": "cosmoport2-e2e",
  "timestamp": "2026-08-29 14:30:00",
  "target": "http://127.0.0.1:8080",
  "elapsed": 12.3,
  "passed": 28,
  "failed": 0,
  "total": 28,
  "success": true,
  "steps": [
    {"step": "Create Domain", "status": "PASS", "httpCode": 201},
    ...
  ],
  "entities": {
    "domain": "e2e-steel-domain",
    "plan": "e2e-plan-143000",
    "run": "e2e-run-143000",
    "release": "e2e-rel-143000",
    "transfer_zone": "zt"
  }
}
```

Отчёт сохраняется в `reports/e2e-pipeline-report.json`.

### Требования к окружению

- Docker Compose стек с как минимум: `cosmo-postgres`, `cosmo-valkey`, `cosmo-api`, `cosmo-caddy`
- Caddy на порту 8080 (или прямой доступ к API на 8100)
- `curl` / `Invoke-RestMethod` доступен

### Идемпотентность

Каждый запуск использует уникальные ID сущностей (timestamp suffix). При повторном запуске:

- Domain может вернуть 409 (already exists) — безопасно повторно используется
- Приложения, bricks, план, run, release — всегда новые
- Предыдущие тестовые данные не удаляются — ручная очистка при необходимости

---

## Rate Limit Test (`test-rate-limit`)

```powershell
.\services\scripts\test-rate-limit.ps1 -BaseUrl http://127.0.0.1:8080
```

Проверяет:
1. Health endpoints (/live, /ready, /health) — безлимитные
2. /api/* — 100 req/min → HTTP 429 после лимита
3. HTTP 429 содержит заголовок Retry-After

---

## Secret Rotation (`rotate-secrets`)

```powershell
# Dry-run (без изменений)
.\services\scripts\rotate-secrets.ps1 -DryRun

# Полная ротация
.\services\scripts\rotate-secrets.ps1
```

Ротирует:
- PostgreSQL пароль (`ALTER USER` без остановки)
- Gitea admin token (через API)
- Woodpecker agent secret (restart агента)

Аудит-лог: `reports/secret-rotation-audit.log`.

---

## Woodpecker live-контур (`seed-woodpecker-fixture` + `smoke-woodpecker-chunks`)

```powershell
# 1. Идемпотентный сид: Gitea repo-фикстура + .woodpecker.yml + активация в WP
#    + реальный прогон + выпуск COSMO_WOODPECKER_TOKEN в services/.env
python .\services\scripts\seed-woodpecker-fixture.py

# 2. Подхватить токен (иначе SSE-логи/executor ходят в WP анонимно)
docker compose -f services/docker-compose.yml up -d cosmo-api

# 3. Live-смок: реальный пайплайн → SSE log_chunk по проводу (self-skip оффлайн)
python .\services\scripts\smoke-woodpecker-chunks.py
```

Смоук встроен в `local-smoke.ps1` (Phase 1b, COS-188) — при оффлайн-стенде шаг честно SKIP.

---

## Демо «нормальный билд» (`seed-build-demo`, COS-197)

```powershell
# Сид (идемпотентно): домен/приложение, Gitea-репо cosmo/build-demo (реальный
# Dockerfile + исполняемый .woodpecker.yml: docker build + push в registry зоны),
# WP-активация+trust, кирпич/план — готовые к прогону
python .\services\scripts\seed-build-demo.py

# Живой показ: реальная сборка через runs-поверхность (по прогону на запуск)
python .\services\scripts\seed-build-demo.py --run --runs 2

# Снять демо-следы (Gitea-репо; best-effort WP-запись/domain/app — честные WARN)
python .\services\scripts\seed-build-demo.py --clean
```

- Итог показа (человекочитаемо, rc): batch passed → WP pipeline success (шаг
  `docker-build`, состояние — из WP-БД: v3.5 detail-API не отдаёт steps) →
  канонический digest-маркер `build-demo:1.0.0@sha256:…` из логов шага →
  образ по digest существует в registry ZR (`:5100`) → run succeeded;
  evidence-след прогона (log-запись COS-097) проверяется всегда.
- Зависимости стенда: свежий `COSMO_WOODPECKER_TOKEN` в `services/.env`
  (канон: `seed-woodpecker-fixture.py` + `docker compose … up -d cosmo-api`),
  `trusted.volumes=true` на демо-репо (ставит сид — нужен для docker.sock шага),
  registry ZR (`cosmo-registry-zr`, host `:5100`).
- Границы: durable artifact-record (COS-164) требует, чтобы каталог нёс
  `definition.type=docker_build`; продуктовая схема `BrickDefinition` сейчас
  extras не носит (шов **COS-196**) — демо-кирпич сеется generic-дефиницией,
  digest проверяется по логам+registry, а ledger-запись честно **SKIP**.
  `--docker-build-def` сеет полную спеку (позитивный compile — после 196).
  Ledger/registry-следы `--clean` не удаляет (immutable/retention).

---

## Airgap Bundle Integrity (`verify-bundle` + `verify-airgap-checksums`)

```bash
# Проверка файлов бандла (checksums.sha256)
./scripts/verify-bundle.sh

# Проверка Docker-образов (digest vs manifest.json)
./scripts/verify-airgap-checksums.sh /path/to/bundle --loaded
```

---

## Airgap Bundle Builder (`airgap-bundle`)

```powershell
.\services\scripts\airgap-bundle.ps1 -Version 0.2.0
```

Собирает полный offline-бандл:
- 10 Docker-образов (8 внешних + 2 build)
- SBOM CycloneDX 1.5
- License report
- manifest.json + checksums.sha256

Бандл несёт **immutable-теги** (`git-<sha>`) для build-образов (COS-195);
compose-копия в бандле уже ссылается на них — airgap-машина ничего не досчитывает.

---

## Dev-профиль + гигиена образов (COS-195, PK-C-010)

```powershell
# Стенд в dev-режиме: api — hot-reload (исходники монтируются), frontend — Vite dev server.
# Правка кода НЕ пересобирает образы и НЕ плодит <none>.
.\services\scripts\cosmo-start.ps1 -Full -Dev

# Immutable-релиз (уникальный git-тег; прошлые сборки сохраняют имена):
.\services\scripts\build-release.ps1
.\services\scripts\build-release.ps1 -KeepN 5 -Prune   # retention: держим 5 последних

# Рутина гигиены: dangling prune + полный sweep build cache (или -ReserveCacheGB N):
.\services\scripts\image-hygiene.ps1

# Проверка bind-mount правила (только относительные пути; allowlist — docker.sock):
.\services\scripts\check-bind-mounts.ps1
```

Правила: пересборка в dev не нужна; релиз — всегда новый immutable-тег; при переносе
репо контейнеры пересоздаются (`up -d --force-recreate`), не `docker start` старых.
Полный контекст — `docs/DEPLOYMENT.md` §6.5.

---

## Порядок при развёртывании с нуля

```powershell
# 1. Поднять инфраструктуру
docker compose -f services/docker-compose.yml up -d cosmo-postgres cosmo-valkey

# 2. Поднять API
docker compose -f services/docker-compose.yml up -d cosmo-api

# 3. Миграции (автоматически — или вручную)
docker exec cosmo-api alembic -c /app/alembic.ini upgrade head

# 4. Поднять Caddy
docker compose -f services/docker-compose.yml up -d cosmo-caddy

# 5. E2E smoke
.\services\scripts\run-e2e-pipeline.ps1

# 6. Rate-limit check
.\services\scripts\test-rate-limit.ps1
```

---

## SonarQube CE (SAST-стенд, SAST-STAND-4)

Source-SAST-хост стенда (SAST-эпик): SonarQube Community + PostgreSQL, UI `:9000`,
своя сеть `cosmo-sonar-net`. Опциональный профиль — **отдельный compose-файл**
(обычный `up` стенда его не поднимает).

```powershell
# Поднять (первый boot 2-5 мин, ~4 GB)
docker compose -f services/docker-compose.sonarqube.yml up -d

# Идемпотентный сид: токен → OpenBao (secret/cosmo/sast), проект owner__repo, профили PrettyK
# (нужны VAULT_APPROLE_ROLE_ID/SECRET_ID из services/.env; повтор → PRESERVED)
python services/scripts/seed-sonar-stand.py

# Погасить (volumes сохраняются)
docker compose -f services/docker-compose.sonarqube.yml down
```

Секреты, ротация, конвенции ключей — `SECURITY_MAINTENANCE.md` §2.6.
