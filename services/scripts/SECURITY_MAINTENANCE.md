# Cosmoport 2.0 — Security Maintenance & Secret Rotation

> **Статус:** утверждён (COS-088)  
> **Ответственный:** Buddy (DevOps)  
> **Связанные скрипты:** `rotate-secrets.ps1`, `verify-airgap-checksums.sh`

---

## 1. Регламент ротации секретов

### 1.1. Периодичность

| Секрет | Период | Плановое окно | Влияние на сервис |
|---|---|---|---|
| PostgreSQL password | 90 дней | вторник 03:00 МСК | **0 downtime** (ALTER USER без рестарта) |
| Gitea admin token | 60 дней | среда 03:00 МСК | кратковременная недоступность Gitea API (30с) |
| Woodpecker agent secret | 30 дней | четверг 03:00 МСК | рестарт агента (5-10с перерыва) |
| MinIO access/secret keys | 90 дней | понедельник 02:00 МСК | рестарт cosmo-api (2-3с) |
| OpenBao root token | 180 дней | ручная операция | нет |

### 1.2. Внеплановая ротация (инцидент)

Внеплановая ротация выполняется немедленно при:

- Обнаружении секрета в логах, коде или публичном канале
- Компрометации учётной записи
- Увольнении сотрудника, имевшего доступ к секретам
- По результатам security audit

---

## 2. Процедура ротации (пошагово)

### 2.1. Подготовка

```powershell
# 1. Убедиться что OpenBao запущен
docker ps --filter name=cosmo-openbao

# 2. Убедиться что есть доступ к OpenBao
curl http://127.0.0.1:8200/v1/sys/health

# 3. Запустить ротацию (сначала dry-run)
.\services\scripts\rotate-secrets.ps1 -DryRun
```

### 2.2. Исполнение

```powershell
# Запустить полную ротацию
.\services\scripts\rotate-secrets.ps1

# ИЛИ выборочно:
# Только PostgreSQL:
.\services\scripts\rotate-secrets.ps1 -RotatePgOnly

# С кастомным токеном OpenBao:
$env:COSMO_BAO_ROOT_TOKEN = "hvs.xxx..."
.\services\scripts\rotate-secrets.ps1
```

### 2.3. Верификация после ротации

Скрипт автоматически выполняет smoke-тесты:

1. `cosmo-api` → `GET /live` → ожидается `{"status":"ok"}`
2. `cosmo-gitea` → `GET /api/v1/version` → ожидается HTTP 200
3. `Caddy` → `GET /live` → ожидается `{"status":"ok"}`

**Ручная проверка** (дополнительно):

```powershell
# Полный health-check
curl http://127.0.0.1:8080/api/v1/status/dashboard

# Проверка подключения к PG
docker exec cosmo-api python -c "
from sqlalchemy import create_engine, text
e = create_engine('postgresql+psycopg2://cosmo:NEWPASSWORD@cosmo-postgres:5432/cosmo')
with e.connect() as c: print(c.execute(text('SELECT 1')).scalar())
"
```

### 2.4. Откат при неудаче

Скрипт автоматически сохраняет старые секреты в OpenBao с суффиксом `_prev`:

- `secret/cosmo/database` → `password_prev`
- `secret/cosmo/forge/gitea` → `admin_token_prev`
- `secret/cosmo/ci/woodpecker` → `agent_secret_prev`

**Ручной откат:**

```powershell
# 1. Прочитать старый секрет из OpenBao
$oldPgPassword = Invoke-BaoRead -Path "database" -Key "password_prev"

# 2. Вернуть старый пароль
psql -h 127.0.0.1 -U cosmo -d cosmo -c "ALTER USER cosmo WITH PASSWORD '$oldPgPassword'"

# 3. Обновить compose + рестарт если нужно
docker compose up -d cosmo-api cosmo-gitea cosmo-woodpecker

# 4. Перезаписать основной секрет
Invoke-BaoWrite -Path "database" -Key "password" -Value $oldPgPassword
```

---

## 3. Верификация целостности airgap-бандла

### 3.1. Проверка перед установкой

```bash
# На airgap-машине, после распаковки бандла
./scripts/verify-airgap-checksums.sh /path/to/bundle

# Проверка загруженных Docker-образов
./scripts/verify-airgap-checksums.sh /path/to/bundle --loaded
```

### 3.2. Периодическая проверка (на работающем стенде)

```bash
# Раз в месяц — проверка digest'ов всех 10 образов
./scripts/verify-airgap-checksums.sh --loaded

# При обновлении — полная проверка
./scripts/verify-airgap-checksums.sh /path/to/new-bundle --loaded
```

### 3.3. Что проверяется

| Уровень | Скрипт | Что проверяет |
|---|---|---|
| Файлы бандла | `verify-airgap-checksums.sh` | SHA-256 всех файлов vs `checksums.sha256` |
| Docker-образы | `verify-airgap-checksums.sh --loaded` | Digest каждого образа vs `manifest.json` |
| Состав бандла | `verify-bundle.sh` | Наличие `images/`, `compose/`, `scripts/` |
| Внешние ссылки | `verify-bundle.sh` | Отсутствие `https?://` в compose |

---

## 4. Аудит и журналирование

### 4.1. Аудит-лог ротации

Скрипт `rotate-secrets.ps1` пишет все шаги в:

```text
reports/secret-rotation-audit.log
```

Формат:

```text
[2026-08-29 03:00:01] === Secret Rotation Drill started ===
[2026-08-29 03:00:02] DryRun=False | BaoUrl=http://127.0.0.1:8200 | PgUser=cosmo
[2026-08-29 03:00:03] OpenBao health: initialized=True sealed=False
[2026-08-29 03:00:04] Old PostreSQL password backed up in OpenBao (password_prev)
[2026-08-29 03:00:05] PostgreSQL password rotated (ALTER USER cosmo)
[2026-08-29 03:00:08] Gitea token created: sha1:abc123...
[2026-08-29 03:00:10] Woodpecker agent restarted with new secret
[2026-08-29 03:00:15] cosmo-api /live: ok
[2026-08-29 03:00:16] cosmo-gitea /api/v1/version: OK
[2026-08-29 03:00:17] Caddy /live: ok
[2026-08-29 03:00:17] === Secret Rotation Drill Complete ===
[2026-08-29 03:00:17] Smoke check: PASSED
```

### 4.2. Хранение секретов

- **Все секреты хранятся ТОЛЬКО в OpenBao**
- Значения по умолчанию в `docker-compose.yml` — **только для dev-среды**
- В production: `.env` файл не должен содержать пароли; compose получает их через `docker compose --env-file` из защищённого хранилища
- OpenBao root token — **ротируется раз в 180 дней**, НЕ хранится в git

### 4.3. Принципы

1. **Никаких секретов в коде** — даже в тестах (тесты используют `os.getenv`)
2. **Никаких секретов в логах** — скрипты не выводят значения секретов
3. **Никаких секретов в git** — `.env` и `sonar-access.md` в `.gitignore`
4. **Все ротации — атомарны** — старый секрет сохраняется до успешной верификации нового
5. **Все ротации — проверяются** — пост-ротационный smoke-test обязателен

---

## 5. Инцидент: компрометация секрета

### 5.1. Признаки

- Секрет обнаружен в: логах Docker, ответах API, исходном коде, публичном репозитории
- Неавторизованный доступ к сервисам
- Подозрительная активность в Gitea/Woodpecker

### 5.2. Немедленные действия

1. **Остановить ротацию по расписанию** если она запущена
2. **Запустить внеплановую ротацию** скомпрометированного секрета:

```powershell
.\services\scripts\rotate-secrets.ps1 -EmergencyMode
```

3. **Проверить аудит-логи** Gitea / Woodpecker / PostgreSQL на предмет неавторизованных действий
4. **Обновить все секреты**, которые могли использовать тот же пароль (не переиспользовать!)
5. **Задокументировать инцидент** в `reports/SECURITY-INCIDENT-YYYY-MM-DD.md`

### 5.3. Пост-инцидент

- Проверить `manifest.json` и SHA-256 всех образов
- Проверить целостность SBOM и лицензий
- Обновить процедуру, если инцидент выявил пробел

---

## 6. Контрольный список (checklist)

### Ежемесячно

- [ ] Проверка digest'ов Docker-образов: `verify-airgap-checksums.sh --loaded`
- [ ] Ротация Woodpecker agent secret (автоматически или вручную)
- [ ] Проверка аудит-логов ротации

### Ежеквартально

- [ ] Полная ротация PostgreSQL
- [ ] Ротация Gitea token
- [ ] Проверка целостности SBOM
- [ ] Security аудит кода (`sonar_pipeline.ps1`)

### Раз в полгода

- [ ] Ротация OpenBao root token
- [ ] Полный security audit стенда
- [ ] Penetration test
- [ ] Обновление процедур по результатам аудита