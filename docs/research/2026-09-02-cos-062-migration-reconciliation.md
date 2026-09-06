# COS-062 — Database Migration Reconciliation: acceptance evidence

Worker: Luna · Date: 2026-09-02 · Status: DELIVERED (awaiting Максим's acceptance)
Scope: `D:\prettyk-airlock` (SERIAL после принятого COS-060)

## Проблема (из COS-059 acceptance, PARTIAL/BLOCKED)

1. Fresh `alembic upgrade head` падал на `71a2b3c4d5e6`:
   `UndefinedTable: relation "releases" does not exist` — миграции создают
   `cosmo_deployments` с FK → `releases.id`, но таблицу `releases` не создаёт
   ни одна миграция (подтверждено воспроизведением на scratch-БД).
2. Initial-миграция stale: без `ix_domains_created_at` / `ix_domains_label`.
3. `b8c9d0e1f2a3` (COS-055) никогда не выполнялся — до него всегда падали;
   содержал невалидный API `sa.Comment(...)` (в SQLAlchemy его нет).
4. `93d4e5f6a7b8`: backfill VIEW звал `jsonb_array_elements_text` по колонке
   типа `json` (ORM `models_lr` декларирует `sa.JSON`) → `UndefinedFunction`.
5. Системный drift между цепочкой миграций и `Base.metadata`:
   колонки (`builds.title`, `deployments.runtime_name`), имена/состав
   индексов (~25 шт: `ix_cosmo_*` vs ORM `ix_builds_*`/`ix_deploys_*`, плюс
   полностью отсутствующие), ondelete у FK builds/deployments,
   nullable JSONB-колонок.

## Что сделано

### Новые миграции
- `c1d2e3f4a5b6_cos062_releases_table.py` — таблица `releases` строго по ORM
  `models.py::Release` (JSONB, 3 btree + 1 GIN индекс, комментарий).
  Вставлена между initial и builds/deployments (закрывает blocker #1).
- `d2e3f4a5b6c7_cos062_schema_reconciliation.py` — новый head:
  1) guarded-добавление домен-индексов (для БД, застампованных на старый initial);
  2) drift-верификация: каждая таблица ORM `Base.metadata` обязана существовать
  в БД, иначе честный `RuntimeError` со списком отсутствующих. Ловит будущий
  дрейф «добавили ORM без миграции» при каждом `upgrade head`.

### Исправленные миграции
- `23b56529e15d_cosmo_initial.py`: +18 недостающих ORM-индексов
  (apps ×3, groups ×2, pipeline_plans ×2, plan_bricks ×2, repo_bindings,
  batches.status, gates ×2, runs ×3, evidence ×2), переименование
  `ix_evidence_ledger_provenance_json` → `ix_evidence_provenance_json`
  (ORM-имя), +2 домен-индекса; downgrade зеркально.
- `71a2b3c4d5e6`: down_revision → `c1d2e3f4a5b6`; +колонки `title`,
  `runtime_name`; `sa.JSON` → `postgresql.JSONB` (3 колонки); nullable
  выровнены по ORM; индексы переименованы в ORM-имена
  (`ix_builds_*` ×5 вкл. GIN, `ix_deploys_*` ×6), лишний
  `ix_cosmo_builds_commit_sha` удалён (ORM не декларирует);
  FK ondelete убран (ORM декларирует NO ACTION); `target_zone` String(16)→String(8).
- `93d4e5f6a7b8`: явные `::jsonb` касты в backfill-INSERT (колонка — `json`
  по ORM).
- `b8c9d0e1f2a3` (файл Flash, COS-055): `sa.Comment(...)` → kwarg `comment=`
  (×4); `notification_inbox.message` nullable=False (по ORM).

## Верификация

- `alembic heads` → ровно один head `d2e3f4a5b6c7`; цепочка линейна (0 branch points).
- Fresh cycle на изолированной scratch-БД: `upgrade head` → `downgrade base`
  → `upgrade head` — все шаги чистые (PG transactional DDL, откат полный).
- Inspector-diff (alembic-schema vs `Base.metadata`): **0 расхождений** по
  таблицам (31), колонкам (имя/тип/nullable), индексам, FK (включая ondelete
  через `pg_get_constraintdef` — inspector psycopg2 читает ondelete неверно).
- Основная dev-БД `cosmo` была застампована на `b8c9d0e1f2a3` → живой
  `upgrade head` довёл её до `d2e3f4a5b6c7` (verification пройдена,
  32 таблицы). Stamp-путь для legacy create_all-БД подтверждён вживую.
- Import app — OK (27 маршрутов); startup-путь (`COSMO_AUTO_MIGRATE=1`) —
  тот же `alembic upgrade head`, что верифицирован выше.

### Тесты
`orchestrator/tests/cosmo/test_migration_reconciliation.py` — 10 passed:
- структура: один head, линейность, releases раньше builds/deployments (offline, без PG);
- fresh upgrade == ORM (полный diff: колонки/типы/nullable/индексы/FK);
- repeat `upgrade head` — no-op (миграции не перезапускаются);
- notification-таблицы (4) + `payload` JSONB NOT NULL;
- домен-индексы; `deployments` FK → `releases.id`;
- legacy stamp-путь (drop alembic_version → `stamp b8c9d0e1f2a3` → upgrade head);
- replay после частичного downgrade (82c3d4e5f6a7 → upgrade head) — чисто.
Тесты изолированы от общей dev-БД (scratch `cosmo_mig_recon`), skip при
недоступном PG.

## Известные границы (не дрейф)

1. `server_default`: миграции выставляют server-side defaults, ORM —
   python-side `default=`. Функционально эквивалентно (значение всегда
   подставляется), в строгий diff не включено — косметический класс, ~60 колонок.
2. Индексы, автоматически создаваемые PG для PK/UNIQUE-констрейнтов
   (`uq_*`, `*_key`) — не ORM `Index()`; фильтруются в diff честно.
3. `domain_project_mapping` — VIEW из `93d4e5f6a7b8`, вне Base.metadata (by design).
4. COS-089 `migration_verifier.py`/`test_migrations.py` (чужой packet):
   `alembic_cycle()` делает `downgrade base` на **общей** dev-БД — запускать
   осознанно, параллельные воркеры пострадают. Оффлайн-структурные тесты
   COS-089 — 5 passed. Рекомендация: перевести cycle-тесты COS-089 на scratch-БД
   (владелец — COS-089 worker).

## Файлы

- Новые: `alembic/versions/c1d2e3f4a5b6_cos062_releases_table.py`,
  `alembic/versions/d2e3f4a5b6c7_cos062_schema_reconciliation.py`,
  `orchestrator/tests/cosmo/test_migration_reconciliation.py`.
- Изменены: `alembic/versions/23b56529e15d_cosmo_initial.py`,
  `alembic/versions/71a2b3c4d5e6_add_builds_and_deployments.py`,
  `alembic/versions/93d4e5f6a7b8_post_luna_001_project_apps.py`,
  `alembic/versions/b8c9d0e1f2a3_cos055_notification_manager.py`.
- Не тронуто: ORM-файлы, `env.py`, API/сервисы, чужие WIP-файлы
  (transfer/, notifications/ и пр.).
- Main dev-БД `cosmo`: доведена до `d2e3f4a5b6c7` (неразрушающе).
