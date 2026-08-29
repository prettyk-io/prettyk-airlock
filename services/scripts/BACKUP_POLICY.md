# Cosmoport 2.0 — Политика резервного копирования (Backup Policy)

> **Владелец:** Buddy (DevOps)
> **Скрипт:** `services/scripts/daily-backup.ps1` (Win) / `.sh` (Linux)
> **Расписание:** ежедневно в 03:00 (Windows Task Scheduler / cron)

---

## 1. Что бэкапируем

| Источник | Формат | Размер (оценка) | Метод |
|---|---|---|---|
| **PostgreSQL** | `pg_dump -Fc` (custom compressed) | 50 MB — 2 GB | `docker exec cosmo-postgres pg_dump` |
| **MinIO S3** — `cosmo-evidence` | `mc mirror` (полная копия бакета) | 500 MB — 50 GB | `mc mirror` (MinIO Client) |
| **SHA-256 checksums** | Файл `.sha256` | < 1 KB | `sha256sum` / `Get-FileHash` |

Не бэкапируем:
- MinIO бакет `cosmo-builds` — пересобираемый CI-артефактами
- MinIO бакет `cosmo-artifacts` — регенерируемый из evidence
- Valkey — данные эфемерны, восстанавливаются из PG
- Docker-образы — хранятся в закрытом реестре / airgap-бандле

---

## 2. Расписание

### Ежедневно (03:00)

```powershell
# Windows Task Scheduler
schtasks /create /tn "CosmoDailyBackup" /tr "powershell -File D:\cosmoport2\services\scripts\daily-backup.ps1" /sc daily /st 03:00
```

```bash
# Linux cron
0 3 * * * /opt/cosmoport2/services/scripts/daily-backup.sh >> /var/log/cosmo-backup.log 2>&1
```

### По воскресеньям

Еженедельный бэкап выполняется тем же скриптом — но файл получает тег `_weekly` и хранится по отдельной квоте (4 недельных).

---

## 3. Политика хранения (Retention)

| Тип | Хранить | Очистка |
|---|---|---|
| **Ежедневный PG dump** | 7 последних | Удаляются дампы старше 7-го |
| **Еженедельный PG dump** (воскресенье) | 4 последних | Удаляются дампы старше 4-го воскресенья |
| **Ежедневный MinIO mirror** | 7 последних | Удаляются каталоги старше 7-го |
| **Еженедельный MinIO mirror** (воскресенье) | 4 последних | Удаляются каталоги старше 4-го воскресенья |

### Структура каталогов

```text
backups/
├── pg/
│   ├── pg_cosmo_2026-08-25_daily.dump
│   ├── pg_cosmo_2026-08-26_daily.dump
│   ├── pg_cosmo_2026-08-27_daily.dump
│   ├── pg_cosmo_2026-08-28_daily.dump
│   ├── pg_cosmo_2026-08-29_daily.dump
│   ├── pg_cosmo_2026-08-30_daily.dump
│   ├── pg_cosmo_2026-08-31_daily.dump          ← 7 daily kept
│   ├── pg_cosmo_2026-08-24_weekly.dump          ← Sunday #1
│   ├── pg_cosmo_2026-08-17_weekly.dump          ← Sunday #2
│   ├── pg_cosmo_2026-08-10_weekly.dump          ← Sunday #3
│   └── pg_cosmo_2026-08-03_weekly.dump          ← Sunday #4 (oldest kept)
├── minio_2026-08-31_daily/
├── minio_2026-08-30_daily/
├── ...
├── minio_2026-08-24_weekly/
├── ...
└── checksums/
    ├── pg_cosmo_2026-08-31_daily.dump.sha256
    └── ...
```

---

## 4. Проверка целостности

### 4.1. Проверить конкретный бэкап

```powershell
# PG
$expected = Get-Content "backups\checksums\pg_cosmo_2026-08-31_daily.dump.sha256" -Raw
$actual = (Get-FileHash "backups\pg\pg_cosmo_2026-08-31_daily.dump" -Algorithm SHA256).Hash.ToLower()
if ($expected -eq $actual) { "OK" } else { "CORRUPTED" }
```

### 4.2. Проверить все бэкапы

```powershell
Get-ChildItem "backups\checksums\*.sha256" | ForEach-Object {
    $dumpName = $_.Name -replace '\.sha256$', ''
    $dump = Get-ChildItem "backups\pg\$dumpName" -ErrorAction SilentlyContinue
    if ($dump) {
        $expected = (Get-Content $_.FullName -Raw).Trim()
        $actual = (Get-FileHash $dump.FullName -Algorithm SHA256).Hash.ToLower()
        Write-Host "$dumpName : $(if ($expected -eq $actual) { 'OK' } else { 'CORRUPTED' })"
    }
}
```

---

## 5. Восстановление из бэкапа

### 5.1. PostgreSQL

```powershell
# Остановить API (чтобы не было записи во время восстановления)
docker compose -f services/docker-compose.yml stop cosmo-api cosmo-gitea cosmo-woodpecker

# Восстановить
docker exec -i cosmo-postgres pg_restore -U cosmo -d cosmo --clean --if-exists < backups\pg\pg_cosmo_2026-08-31_daily.dump

# Перезапустить
docker compose -f services/docker-compose.yml start cosmo-api cosmo-gitea cosmo-woodpecker
```

### 5.2. MinIO

```powershell
mc mirror --overwrite backups\minio_2026-08-31_daily\ cosmo-local/cosmo-evidence\
```

Или вручную скопировать файлы на том MinIO и перезапустить `cosmo-minio`.

---

## 6. Dry-run

```powershell
# Проверить что бэкап сработает без реальной записи
.\services\scripts\daily-backup.ps1 -DryRun

# Только PostgreSQL
.\services\scripts\daily-backup.ps1 -SkipMinIO

# Только MinIO
.\services\scripts\daily-backup.ps1 -SkipPG
```

---

## 7. Мониторинг и алерты

### 7.1. Проверить последний бэкап

```powershell
Get-Content "reports\backup-audit.log" -Tail 10
```

Ожидаемая последняя строка: `=== Cosmo Daily Backup Complete ===`.

### 7.2. Размер бэкапов

```powershell
Get-ChildItem "backups\pg" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, Length, LastWriteTime
```

### 7.3. Prometheus метрика

Добавить в `metrics.py` (COS-039):

```python
# cosmo_backup_last_success_timestamp — Unix timestamp последнего успешного бэкапа
```

### 7.4. Критические алерты

| Условие | Действие |
|---|---|
| Бэкап не выполнялся > 27 часов | Уведомление в Discord / email |
| Размер последнего бэкапа < 10% от среднего | Проверить PG — возможно повреждение |
| SHA-256 checksum mismatch | **НЕМЕДЛЕННО** — бэкап повреждён, проверить диск |

---

## 8. Аудит-лог

Формат: `reports/backup-audit.log`

```text
[2026-08-31 03:00:01] === Cosmo Daily Backup started ===
[2026-08-31 03:00:01]   Date=2026-08-31  Weekly=False  DryRun=False
[2026-08-31 03:00:01] --- PostgreSQL Backup ---
[2026-08-31 03:00:01]   Dumping PostgreSQL: cosmo
[2026-08-31 03:00:05]   OK: pg_cosmo_2026-08-31_daily.dump (1.2 GB)
[2026-08-31 03:00:05]   SHA256: a1b2c3...
[2026-08-31 03:00:05] --- MinIO Backup ---
[2026-08-31 03:00:15]   OK: mc mirror completed
[2026-08-31 03:00:15]   Files: 847, Size: 3.4 GB
[2026-08-31 03:00:15]   Combined SHA256: d4e5f6...
[2026-08-31 03:00:15] --- Retention Policy ---
[2026-08-31 03:00:15]   Keep: 7 daily + 4 weekly
[2026-08-31 03:00:15]   PG dailies to delete: 2 (keeping newest 7)
[2026-08-31 03:00:15]     Deleted: pg_cosmo_2026-08-23_daily.dump
[2026-08-31 03:00:15]     Deleted: pg_cosmo_2026-08-22_daily.dump
[2026-08-31 03:00:15] === Cosmo Daily Backup Complete ===
```

Никакие пароли, токены или секреты не пишутся в лог.

---

## 9. Восстановление после инцидента (Disaster Recovery)

### 9.1. Полное восстановление с нуля

```powershell
# 1. Поднять инфрструктуру (только PG + MinIO)
docker compose -f services/docker-compose.yml up -d cosmo-postgres cosmo-minio

# 2. Восстановить PG
docker exec -i cosmo-postgres pg_restore -U cosmo -d cosmo --clean --if-exists < backups\pg\pg_cosmo_LATEST.dump

# 3. Восстановить MinIO
mc mirror --overwrite backups\minio_LATEST\ cosmo-local\cosmo-evidence\

# 4. Поднять всё
docker compose -f services/docker-compose.yml up -d
```

### 9.2. Point-in-time recovery (PITR)

PostgreSQL WAL-архивирование не настроено в dev-режиме. Для production:

```ini
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /var/lib/postgresql/data/pg_wal/%f'
```

Добавить бэкап WAL-файлов в скрипт.

---

## 10. Чеклист (ежемесячно)

- [ ] Выполнить `daily-backup.ps1 -SkipMinIO` — проверить PG dump
- [ ] Выполнить `daily-backup.ps1 -SkipPG` — проверить MinIO mirror
- [ ] Проверить SHA-256 всех бэкапов (п 4.2)
- [ ] Проверить retention: нет файлов старше политики
- [ ] Проверить `backup-audit.log` на ошибки
- [ ] Провести тестовое восстановление PG на отдельном инстансе
- [ ] Проверить свободное место на диске (> 30% свободно)
- [ ] Обновить этот документ если политика изменилась