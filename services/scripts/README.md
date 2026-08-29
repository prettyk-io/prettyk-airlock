# Cosmoport 2.0 — Scripts Reference

## Быстрый старт

```powershell
cd D:\cosmoport2

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