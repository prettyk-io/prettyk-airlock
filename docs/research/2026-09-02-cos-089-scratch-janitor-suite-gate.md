# COS-089: Scratch janitor CLI + suite gate — Acceptance Report

**Дата:** 2026-09-02
**Карточка:** BACKLOG.md COS-089 (Boss, 8-12h, P2, dep COS-076)
**Статус:** DONE пп. 1-2; п. 3 (/ready 503) — **не выполнялся, ждёт утверждения Максима** (карточка: «при утверждении Максима»; известная девиация из COS-063, product decision pending). Не закоммичено.

## Что сделано

### 1. Scratch janitor CLI — `services/scripts/cleanup_scratch_pg.py`
- Цель — изолированный test PG (по умолчанию 127.0.0.1:5433); one-shot, не демон.
- **Dry-run по умолчанию** (план), `--apply` — явный дроп; `--json` для машинного чтения.
- Кандидаты ТОЛЬКО: `cosmo_test_s*` (per-session БД, COS-076) и
  `cosmo_scratch_*` (миграционные scratch, COS-078) **без активных
  соединений** (orphan — SIGKILL'нутая сессия, atexit-промах, падение мимо teardown).
- Живые сессии (conns>0) — **skip** с отчётом; защищённые имена
  (`postgres`, `cosmo` dev, `cosmo_test`, templates) — никогда кандидаты;
  не-префиксные имена — вне зоны видимости.
- Guard: отказ обслуживать хост-порт 5432 (dev-стенд), exit 2.
- Технически: psycopg2 c `autocommit=True` (DROP DATABASE запрещён внутри
  транзакционного блока — ActiveSqlTransaction).

### 2. Suite gate — `services/scripts/suite_gate.ps1` (+ docs/DEPLOYMENT.md §14 Gate G)
Одна команда: поднять тестовый PG → `COSMO_TEST_SESSION_DB=1` (прогон в
собственной БД `cosmo_test_s<hex>`, atexit-дроп, общий `cosmo_test` не
трогается) → `pytest orchestrator/tests/cosmo -q` → вердикт
`SUITE GATE: PASS/FAIL`, exit-code pytest возвращается как exit-code скрипта.
- Идемпотентен с чистого состояния (session-БД создаётся per-run).
- Python-резолв: `-PyPath` > PATH > канонический dev-путь.
- Скрипт **ASCII-only намеренно**: PS5.1 читает BOM-less .ps1 как ANSI —
  многобайтный em-dash (0x94) парсится как кавычка и роняет парсер.
- Вердикт «test PG поднялся» — TCP-проба, не exit-code compose (PS5.1
  заворачивает stderr-ворнинги docker — orphan containers — и ломает
  проверку).

### 3. /ready degraded → 503 — НЕ ВЫПОЛНЕН
Требует утверждения Максима (см. шапку). После аппрува — отдельным ходом.

## Верификация
- **Dry-run на чистом инстансе**: «no scratch-prefixed databases», exit 0.
- **Guard**: `--port 5432` → отказ, exit 2.
- **Orphan-демо** (seeds: `cosmo_scratch_cycle_deadbeef`,
  `cosmo_test_s_deadbeef`, живая `cosmo_scratch_cycle_alive` с
  удерживаемым соединением, защищённое `cosmo_test_precious`):
  - dry-run показал план ровно по 3 кандидатам, precious не в списке;
  - `--apply`: 2 orphan'а дропнуты, **живая сессия skip (conns=1)**, exit 0;
  - после смерти холдера повторный `--apply` дропнул и её; побочно
    подтверждено на живом scratch чужого параллельного прогона
    (`cosmo_scratch_cycle_bb8e3214`, conns=1 — skip);
  - `cosmo_test_precious` не тронут (дропнут вручную вне janitor'а).
- **Suite gate**: `SUITE GATE: PASS`, **2239 passed / 2 skipped / 0 failed**,
  exit 0 (2239 > 2224 из карточки — параллельные воркеры добавили тесты в
  общий пул; падений нет). После выхода: session-БД дропнуты
  (leftover пусто), общий `cosmo_test` нетронут (domains=0).

## Чужой WIP-хвост (flagged, тронут минимально)
Воркер оставил `orchestrator/cosmo/api/routes/pipelines.py`
несобирающимся: 4 использования `require_principal` без импорта (приложение
не импортировалось ~10 минут, процессов воркера не было). Восстановлен
**один импорт** в строке 16 — чисто механический фикс собираемости, логика
WIP не тронута. Прошу сверить с автором поверхности (deps.py/COS-068 зона).

## Границы
- Не тронуто: миграционная цепочка (FROZEN), integration/conftest (Luna),
  rbac/deps (Apex), prod-nginx (Buddy), e2e (Flash).
- Известный gap janitor'а: БД, чей процесс убит SIGKILL'ом до atexit,
  остаётся до следующего запуска janitor'а — это и есть его работа; авто-гонка
  «угадай мёртвую сессию» не делается намеренно.
- Commit/push — только по явной команде.
