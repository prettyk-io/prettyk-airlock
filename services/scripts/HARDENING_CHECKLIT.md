# Cosmoport 2.0 — Pre-Production Hardening Checklist

> **Gate:** COS-103 — обязателен перед каждым production deploy  
> **Скрипт:** `services/scripts/verify-hardening.ps1` (Windows) / `.sh` (Linux)  
> **Владелец:** Buddy (DevOps)  
> **Последнее обновление:** 2 сентября 2026 (COS-073: MinIO host-канон 9100/9101, тестовый PG :5433)

---

## Как использовать

```powershell
# Dev-проверка (локально, HTTP)
.\services\scripts\verify-hardening.ps1

# Production-проверка
.\services\scripts\verify-hardening.ps1 -Mode production -BaseUrl https://cosmoport.company.ru

# Частичная проверка (только секреты и порты)
.\services\scripts\verify-hardening.ps1 -SkipCaddyCheck -SkipHealthProbe
```

Скрипт возвращает `Exit 0` при всех зелёных проверках и `Exit 1` с перечнем уязвимостей.

---

## 1. Порты: политика экспозиции

### 1.1. Production (ЖЕЛЕЗОБЕТОН)

| Порт | Сервис | Production | Причина |
|---|---|---|---|
| **443** | Caddy (TLS) | ✅ **Разрешён** | Единственная точка входа |
| 80 | Caddy (HTTP→HTTPS redirect) | ✅ Разрешён | Редирект на 443 |
| 5432 | PostgreSQL | ❌ **Запрещён** | Только internal Docker network |
| 6379 | Valkey | ❌ Запрещён | Только internal |
| 8200 | OpenBao | ❌ Запрещён | Никогда не публиковать |
| 9000 | MinIO S3 API | ❌ Запрещён | Доступ через Caddy `/artifacts/*` (host-канон dev: **9100**) |
| 9001 | MinIO Console | ❌ Запрещён | Никогда в production (host-канон dev: **9101**) |
| 3000 | Gitea | ❌ Запрещён | Доступ через Caddy `/forge/*` |
| 8000 | Woodpecker | ❌ Запрещён | Internal only |
| 8100 | Cosmo API | ❌ Запрещён | Доступ через Caddy `/api/*` |
| 5173 | Frontend dev | ❌ Запрещён | Только для разработки |

### 12. Dev (local development)

Все порты выше разрешены для локальной диагностики. Компас для прод-конфигурации:

```yaml
# В production заменить ports на expose:
services:
  cosmo-postgres:
    # ports:   ← убрать в production
    #   - "5432:5432"
    expoe:       ← оставить только внутренний доступ
      - "5432"
```

### 13. Проверка в бою

```powershell
# Список все портов привязанных к 0.0.0 (публичных)
netstat -ano | findstr "LISTENING" | findstr "0.0.0.0"
```

В продакшене должны быть только порты из PROD_ALLOWED.

### 1.3. Тестовый PG и stand-lock (COS-073)

| Порт | Сервис | Правило |
|---|---|---|
| 5432 | cosmo-postgres (dev-stand) | **Тестам запрещён.** Только стенд/gate |
| 5433 | cosmo-test-pg (изолированный тестовый PG) | Только pytest/alembic-проверки. Волен стираться тестами |

```powershell
# Поднять тестовый PG для pytest:
docker compose -f services\docker-compose.test-pg.yml up -d

# Stand-lock: стенд — сериализованный ресурс (один агент на стенде):
services\scripts\stand-lock.ps1 status
services\scripts\stand-lock.ps1 acquire -Owner buddy -Purpose "gate run"
services\scripts\stand-lock.ps1 release -Owner buddy
```

runtime-gate.ps1 берёт lock сам (exit 3, если стенд занят). pytest lock не
нужен: тесты идут только на :5433 и никогда не трогают dev-stand БД.

---

## 2. Секреты и пароли

### 2.1. Запрщённые дефолтные пароли

| Пароль | Где найден | Заменить на |
|---|---|---|
| `cosmo-minio-dev` | compose L96 | `$COSMO_MINIO_PASWORD` из OpenBao |
| `dev-agent-secret-change-me` | compose L168 | `$COSMO_WODPECKER_AGENT_SECRET` из OpenBao |
| `cosmo-bao-root-dev` | compose L73 | `$COSMO_BAO_ROT_TOKEN` из защищённого хранилища |
| `cosmo` (как пароль P) | compose L35 | `$COSMO_PG_PASWORD` из OpenBao |

### 2.2. Проверка в бою

```powershell
# Искать дефолтные секреты в кодовой базе
Select-String -Path "services\**\*.yml","services\**\*.env" -Pattern "prettyk-minio-dev|dev-agent-secret|cosmo-bao-root-dev"
```

В production ВСЕ пароли должны быть вынесены в переменные окружения или OpenBao, а не прописаны в compose/конфигах.

### 2.3. Решение

- `.env` файл — **не в git** (`.gitignore`)
- `docker compose` запускается с `--env-file /secure/path/production.env`
- Все секреты ротируются черз `rotate-secrets.ps1` (см. SECURITY_MAINTENANCE.md)

---

## 3. Caddy: TLS и Rate Limiting

### 3.1. Минимальные требования

| Проверка | Production | Airgap |
|---|---|---|
| TLS (HTTPS) | ✅ Обязательно | ✅ Пре-выданный сертификат |
| Rate limit (`/pi*` → 100 req/min) | ✅ Обязательно | ✅ Обязательно |
| Health probes БЕЗ лимита | ✅ | ✅ |
| X-Forvarded-Proto header | ✅ | ✅ |

### 3.2. Проверка Caddyfile

```powerhell
# TLS настроен?
Select-String -Path "servicse\Caddyfile" -Pattern "tls\s+|:443"

# Rate limit настроен?
Select-String -Path "servicse\Caddyfile" -Pattern "rate_limit" -Context 2
```

### 3.3. Проверка в бою

```bash
# TEDT: /live без лимита (должен возвращть 200 всегда)
for i in $(seq 1 50); do curl -sk -o /dev/null -w "%{http_code}\n" https://localhost/live; done | grep -v 200

# TEDT: /api/* с лимитом (должен дать 429 после 100 запросов)
for i in $(seq 1 120); do curl -sk -o /dev/null -w "%{http_code}\n" https://localhost/api/v1/domains; done | sort | uniq -c
```

---

## 4. Health Probe Sanitization

### 4.1. Что НЕ должно быть в `/api/health`

- ❌ DSN / connection strings (`postgresql://user:pass@host/db`)
- ❌ Токены (SonarQube `squ_...`, API-ключи)
- ❌ Пароли
- ❌ Стектрейсы (`Traceback (most recent call last)`)
- ❌ Пут к файлам исходного кода
- ❌ Приватные ключи

### 4.2. Проверка в бою

```powerhell
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 5
$j = $r | ConvertTo-Json -Depth 4 -Compress
if ($j -match 'postgresql://|token|password|squ_|BEGIN PRIVATE') {
    Write-Host "FAIL: sensitive data in health response" -ForegroundColor Red
} else {
    Write-Host "PASS: health response clean" -ForegroundColor Green
}
```

### 4.3. Проверка в CI

```yaml
- name: Health probe sanitization
  run: |
    HEATH=$(curl -s http://localhost:8100/health)
    echo "$HEATH" | grep -qE 'postgresql://|token|password' && exit 1 || exit 0
```

---

## 5. Pre-Production Runbook

### Порядок перед каждим деплоем

1. **Запустить hardening gate:**

```powerhell
.\services\scripts\verify-hardening.ps1 -Mode production
```

2. **Проверить все FAIL-ы** — исправить до следющего запуска

3. **Уедиться что скрипт вернул Exit 0**

4. **Задокументировать резлуьтат** в `reports/hardening-gate-YYYY-MM-DD.log`

```powerhell
.\services\scripts\verify-hardening.ps1 -Mode production *> reports\hardening-gate-$(Get-Date -Format 'yyyy-MM-dd').log
```

5. **Только после этого — деплой**

---

## 6. Автоматизация (CI)

Добавить в `.githu/workflows/ci.yml` перед e2e job:

```yaml
hardening:
  name: Security Hardening Gate
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Port scan
      run: |
        chmod +x services/scripts/verify-hardening.sh
        ./services/scripts/verify-hardening.sh production
```

---

## 7. ЧаВо

### Q: В дев-режиме все порты открыты — это нормально?
**A:** Да. `-Mode local` проверяет что порты слушаются. Это дев-режим. В продакшене используй `-Mode production`.

### Q: Как проверить один аспект?
**A:** Используй флаги: `-SkipPortScan`, `-SkipSecretScan`, `-SkipCaddyCheck`, `-SkipHealthProbe`.

### Q: Что если CI не имеет доступа к портам?
**A:** В CI порты не сканируются (`netstat` не применим). Используй `-SkipPortScan` в CI, но секреты и health probe проверяются в CI обяательно.

### Q:Как добавить новый дефолтный пароль для проверки?
**A:** Дбавить в массив `$DEFAUL_SECRETS` в `verify-hardening.ps1` и `DEFAUL_SECRETS=()` в `.sh`. Не забыть обновить этот чеклист.