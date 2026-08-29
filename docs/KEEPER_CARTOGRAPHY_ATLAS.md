# 🗺️ Атлас архитектуры Cosmoport 2.0 (Трехслойная картография для Keeper и Макса)

> **Статус:** Итоговая каноническая картография системы (29 августа 2026).  
> **Методология:** Строгое разделение на 3 слоя:  
> 1. `OBSERVED CODE` — что реально написано, проверено тестами и подключено в репозитории `D:\cosmoport2`.  
> 2. `IMPLEMENTED BUT INCOMPLETE` — что реализовано как рабочий скелет/модуль, но содержит плейсхолдеры, байпасы или моки.  
> 3. `CANONICAL DECISION` — утвержденная финальная модель, каноны и правила архитектуры Cosmoport 2.0.

---

# СЛОЙ 1: OBSERVED CODE (Реально лежит в файлах и подключено)

Все перечисленные компоненты физически присутствуют в `D:\cosmoport2`, покрыты **900+ автоматическими тестами** (100% PASS) и завязаны в единое приложение.

### 1.1. База данных и DDL (PostgreSQL 16, 0 SQLite)
- **`orchestrator/cosmo/db/models.py`** (12 SQLAlchemy 2 Declarative таблиц):
  - `domains` (КИТС), `apps` (L0/L1/L2), `groups` (папки), `repo_bindings` (Git-связки), `pipeline_bricks` (шаги), `pipeline_plans` (скомпилированные планы), `plan_bricks` (M:N связи), `batches` (пачки шагов), `gates` (контрольные точки), `runs` (прогоны), `evidence_ledger` (журнал улик), `releases` (релизы с JSONB `transfer_history`).
- **`orchestrator/cosmo/db/enums.py`**:
  - 8 нативных PostgreSQL ENUM-типов (`brick_type`, `batch_status`, `batch_type`, `run_trigger`, `run_status`, `gate_type`, `gate_decision`, `evidence_type`).
- **`alembic/versions/23b56529e15d_cosmo_initial.py`**:
  - Полная миграция на 12 таблиц, 8 ENUM, 10 GIN-индексов по JSONB-колонкам. Цикл `upgrade head → downgrade base → upgrade head` верифицирован.
- **`orchestrator/cosmo/db/session.py`**:
  - Чистый асинхронный движок `AsyncEngine` (`asyncpg`) + синхронный `get_sync_session()` для тестов и миграций. `pool_pre_ping=True`, `pool_recycle=1800`.

### 1.2. Доменные Pydantic v2 модели (`orchestrator/cosmo/domain/`)
- `domain_model.py` (`Domain`, `ForgeBinding`, `DomainQuota`).
- `app_graph.py` (`Application`, `Group`, `RepositoryBinding`, `AppGraph` с валидацией уровней L0-L3 и защитой от циклов).
- `pipeline_brick.py` (`PipelineBrick`, `BrickDefinition`, `BrickOverride`).
- `run_model.py` (`Run` с 8 состояниями, `Batch`).
- `gate_model.py` (`Gate`, `GatePolicy`, `GatePolicyRule`).
- `worker_lease.py` (`WorkerLease` с 9 состояниями, `FailureReason`, Docker labels).
- `release_model.py` (`Release`, `ReleaseApproval`, `TransferRecord`, `ReleaseZone`).
- `rbac.py` (5 ролей: `admin_sec`, `sec_expert`, `admin_abnormal`, `admin_service`, `user`, матрица 15 действий, наследование `merge`/`isolate`).

### 1.3. Ядро компиляции и стейт-машина (`orchestrator/cosmo/`)
- **`compiler/plan_compiler.py`**:
  - `PlanCompiler`: группировка bricks в батчи (`_DAG_ORDER`), топологическая сортировка Кана, детекция циклов, детерминированный SHA-256 `compiled_hash`.
  - `BatchDAGExecutor`: управление продвижением батчей (`next_ready`, `advance`, `all_passed`).
  - `brick_catalog.py`: `BrickCatalog` (регистрация и переопределение кирпичей КИТС).
- **`control_plane/run_control.py`**:
  - 8-стейт машина (`draft`→`pending`→`queued`→`running`→`succeeded`/`failed`/`blocked`/`cancelled`).
  - Изолированные очереди `_queue_by_domain`.
  - `recover_from_pg()`: автоматическое восстановление состояния очереди из PG при рестарте/сбросе Valkey.
- **`control_plane/lease.py`**:
  - `LeaseTracker`: учет воркеров, heartbeat с TTL, детекция мертвых воркеров, авто-requeue.
- **`control_plane/lock.py`**:
  - `DistributedLock` & `ConcurrencyGuard`: защита от race conditions через Valkey SET NX EX Lua-скрипт с fallback на `pg_try_advisory_lock`.
- **`control_plane/gate_engine.py`**:
  - `GatePolicyEngine`: автоматическая оценка findings по правилам (Critical→BLOCK, High→WARN с порогом `max_count`), ручные гейты с подписью.

### 1.4. Скоростной конвейер и воркер-пул SonarQube (`SONAR-POOL`)
- **`capability/sonar_pool.py`**:
  - `SonarWorkerPool` + `PortLeaseTracker`: тред-безопасная аллокация портов, детерминированные лейблы `com.prettyk.run_id`, опрос статуса по `ceTaskId`, `reconcile_orphans()` (зачистка зомби-контейнеров).
- **`ledger/sarif_merger.py`**:
  - `StreamingSarifMerger`: потоковое слияние 50 SARIF-шардов в 1 мастер-отчет. Память $O(1)$ (не растет от числа шардов), дедупликация правил с выбором высшего severity.
- **`ledger/minio_buffer.py`**:
  - `MinIOBufferSink`: асинхронный сброс отчетов в S3 `cosmo-evidence` + публикация события в Valkey Stream `sonar.ingest` (MAXLEN 10000).
- **`capability/ingest_controller.py`**:
  - `IngestTokenBucket`: считывание потока `sonar.ingest` и скармливание в SonarQube CE батчами по 1–2 с экспоненциальным backoff при перегрузке `/api/ce/activity`.
- **`ledger/fast_ingest.py`**:
  - `FastEvidenceIngest`: прямой парсинг 50 SARIF-отчетов за 0.01с в базу `cosmo_findings` в обход очереди SonarQube.
- **`capability/chaos_runner.py`**:
  - `ChaosRunner`: прогон 7 негативных сценариев с инъекцией сбоев (OOM, port conflict, timeout, crash) — 100% PASS.

### 1.5. Улики, ГОСТ и аудит (`orchestrator/cosmo/ledger/`)
- `evidence_chain.py`: `EvidenceLedger` — иммутабельная SHA-256 цепочка, `verify_and_get()` с детектированием tamper и replay-атак.
- `gost_assembler.py` & `gost_renderer.py`: сборка ГОСТ-Акта (ГОСТ Р 56939, 683-П / 757-П) в JSON и HTML.
- `gost_validator.py`: валидатор комплаенса по ГОСТ Р 56939-2016, 71207-2024 и положениям ЦБ.
- `sla_tracker.py`: SLA монитор сроков устранения (Critical 24h, High 7d, Medium 30d).
- `retention.py`: `ArtifactRetentionManager` — политики хранения и ротации артефактов в S3 с защитой релизных данных.
- `finding_search.py`: `FindingSearchEngine` — быстрый полнотекстовый поиск и GIN-фильтрация уязвимостей.

### 1.6. API-монолит (FastAPI, 16 роутеров, 78+ эндпоинтов)
- Подключены в `api/main.py`: `health`, `domains`, `apps`, `pipelines`, `runs`, `gates`, `releases`, `preferences`, `sse`, `evidence`, `artifacts`, `notifications`, `status`, `metrics`, `repos`, `audit`.
- `domain_guard.py`: отсечка несанкционированного доступа к чужим КИТС через заголовок `X-Cosmo-Domain` (HTTP 404).

### 1.7. Frontend Control Station (`frontend/src/cosmo/`)
- React 18 / TypeScript / Vite / MUI Minimal UI Meta Light (12 экранов):
  - `Overview.tsx` (Executive Security Posture Widget Grade A-F, KPI, Alert HUD).
  - `Applications.tsx` (MUI X Data Grid, L0/L1/L2, привязка Git).
  - `AppGraph.tsx` (Интерактивный DAG Canvas на `@xyflow/react` с типизированными ребрами `contains`, `uses_library`, `depends_on`, `runtime_link`).
  - `RunControl.tsx` (Таблица прогонов с Bulk Actions, прогресс-бары батчей).
  - `RunComparison.tsx` (Side-by-side сравнение двух прогонов: +New / -Fixed / =Same уязвимости).
  - `Gates.tsx` & `GatePolicyBuilder.tsx` (Инспектор гейтов, конструктор политик с правилами по CWE и порогам CVSS).
  - `Evidence.tsx` (Цепочка улик SHA-256, экспорт ГОСТ-Акта и SARIF).
  - `Releases.tsx` & `ReleaseTransferWizard.tsx` (3-шаговый визард трансфера ЗР→ЗТ→ЗПЭ с 2FA/подписью).
  - `Catalog.tsx` (Каталог Pipeline Bricks).
  - `Analytics.tsx` (Графики трендов, спарклайны Pass Rate, тепловая карта уязвимостей).
  - `AuditLog.tsx` (Журнал аудита с фильтрами и экспортом в CSV/JSON).
  - `WebIDEShell.tsx` (Встроенный Monaco-редактор с Diff-вьювером ⌘D и Gutter [▶] раннером, открываемый строго по deep-link).
- Стили: `global.css` (41 CSS-токен), `control-station.css` (MUI Scoped), `web-ide.css` (Tailwind Scoped).

### 1.8. Инфраструктура (`services/`)
- `docker-compose.yml`: 10 сервисов в сети `cosmo-net` (Postgres, Valkey, OpenBao, MinIO, Gitea, Woodpecker, Agent, API, Frontend, Caddy).
- `Caddyfile`: Reverse proxy :443 с модулем `rate_limit` (100 r/m для `/api*`, unlimited для `/live`, `/ready`, `/health`, `/metrics`).
- `helm/cosmo/`: Helm chart (12 манифестов, ClusterIP, Ingress, NetworkPolicy default-deny, migration hook).
- Скрипты: `run-e2e-pipeline.ps1` (8 фаз, 30 вызовов API), `verify-hardening.ps1` (4 гейта безопасности), `daily-backup.ps1` (ротация 7d/4w), `rotate-secrets.ps1` (OpenBao zero-downtime).

---

# СЛОЙ 2: IMPLEMENTED BUT INCOMPLETE (Скелеты, плейсхолдеры и моки)

Компоненты, которые логически спроектированы и работают в тестах, но содержат плейсхолдеры или ждут боевого окружения:

### 2.1. Аутентификация пользователей и сессионные токены (Auth Enforcement)
- **Где лежит:** `orchestrator/cosmo/domain/rbac.py`, `api/deps.py`, `domain_guard.py`.
- **Что есть:** 5-ролевая матрица, иерархия КИТС, `require_role()` зависимость, изоляция `X-Cosmo-Domain`.
- **В чём незавершенность:** В `api/deps.py` проверка токенов пользователей пока работает через плейсхолдер `get_current_user_stub()` (принимает заголовок пользователя или мокает `admin_sec`). Требуется боевая привязка к JWT / Better Auth / OIDC сессиям банка.

### 2.2. Запуск живых DAST/Playwright проверок в Pure Box
- **Где лежит:** `orchestrator/cosmo/capability/broker.py`.
- **Что есть:** `CapabilityBroker` выделяет изолированные порты и сессии по `run_id`, очищает ресурсы при `teardown()`. `BAN.md` запрещает прямое управление процессами сканера из Cosmo.
- **В чём незавершенность:** Cosmo делает вызов наружу через абстрактный HTTP-контракт. Фактический запуск тяжелого браузера Playwright и MITM-прокси происходит на стороне отдельного стенда SecOps Lab (Pure Box) и возвращает результаты через Webhook/SSE.

### 2.3. Живые вебхуки внешних Git-форжей (Gitea / Woodpecker в бою)
- **Где лежит:** `orchestrator/cosmo/adapters/forge_gitea.py`, `execution_woodpecker.py`.
- **Что есть:** Полные клиенты API (создание репо, установка статуса коммита, верификация HMAC подписи вебхука, парсинг пушей, генерация `.woodpecker.yml`).
- **В чём незавершенность:** В тестах адаптеры проверяются на моках HTTP-сессий. В локальном Compose они подключаются к контейнерам `cosmo-gitea:3000` и `cosmo-woodpecker:8000`. Для работы с внешним банковским GitLab/DjiGit потребуется переключение `ForgeBinding.forge_type = "gitlab"`.

### 2.4. S3 Storage Provider под нагрузкой
- **Где лежит:** `orchestrator/cosmo/ledger/artifact_store.py`, `minio_buffer.py`.
- **Что есть:** `ArtifactStore` сохраняет файлы с расчетом SHA-256 хэшей и иерархией каталогов; `MinIOBufferSink` делает асинхронную выгрузку и стриминг через S3 URI.
- **В чём незавершенность:** В локальном режиме `ArtifactStore` пишет на локальный диск по путям, зеркалирующим структуру S3 бакетов (`cosmo-evidence`, `cosmo-artifacts`). В боевом режиме требуется инициализированный MinIO/Ceph кластер.

### 2.5. Фоновый планировщик SLA и Periodic Compliance
- **Где лежит:** `orchestrator/cosmo/ledger/sla_tracker.py`, `compliance_auditor.py`.
- **Что есть:** Математика и API-эндпоинты расчета просрочек SLA (24ч/7д/30д) и 5-факторного индекса комплаенса КИТС (0-100%).
- **В чём незавершенность:** Расчет происходит по запросу к API (`GET /metrics/sla`, `GET /compliance/audit`). Для фонового автоматического оповещения нужен периодический таймер (cron/worker), который шлет нотификации без ручного запроса в API.

---

# СЛОЙ 3: CANONICAL DECISION (Финальная модель Cosmoport 2.0)

Фундаментальные решения, запечатанные 2FA и не подлежащие пересмотру:

### 3.1. Sovereign Run Control Plane (Суверенный центр управления)
- Cosmoport 2.0 — это **не надстройка над GitLab CI** и не админка. Это центр управления безопасностью разработки для CISO, офицеров ИБ, релизников и разработчиков.
- Он отвечает на вопрос: *«Можно ли выпустить релиз в пром, на основании каких доказательств и чьей подписи?»*.

### 3.2. Контракт разделения с Pure Box (split-canon)
- Cosmoport 2.0 **НЕ импортирует** внутренние модули Pure Box (`orchestrator/adapters/`, `browser/`, `fuzzer/`, `core/`).
- Взаимодействие — строго по трем внешним протоколам: **REST API, Webhook, SSE**.
- У Cosmoport отдельная база данных, отдельные инстансы Postgres/Valkey/MinIO и своя сеть `cosmo-net`.

### 3.3. Долговечная истина (Durable Source of Truth)
- **PostgreSQL 16+** — единственный источник истины. Все сущности, статусы, решения гейтов, цепочки улик и аудит хранятся транзакционно.
- **Valkey 8** — строго ephemeral транспорт (PubSub, очереди задач, Streams, rate-limiting, кэш). Потеря или сброс Valkey не уничтожает ни одного прогона или гейта — состояние на 100% восстанавливается из PostgreSQL.
- **MinIO S3** — хранилище неизменяемых бинарных объектов (SARIF, видео, скриншоты, дампы, ГОСТ-Акты).

### 3.4. Графовая топология вместо жесткого дерева (`plan_correct_lifecycle.md`)
- Отказ от старой чопорной вложенности `2 группирующий > 2 > 1 > 0`:
  ```text
  Кластер (Сеть: ЗР / ЗТ / ЗПЭ)
    └── КИТС (Бизнес-домен / Команда / Квоты / RBAC)
          └── Проект (Система / Комплекс сервисов)
                └── Приложения (L0: библиотеки, L1: микросервисы, L2: подсистемы)
  ```
- Связи между приложениями задаются **типизированными ребрами ориентированного графа (DAG)**:
  - `contains` (включение в подсистему).
  - `uses_library` (зависимость от L0 библиотеки/конфига).
  - `depends_on` (порядок сборки/деплоя).
  - `runtime_link` (сетевой вызов для проброса контекста DAST).
- **Релиз как неизменяемый слепок графа (BEMR):**
  - Релиз — это криптографически зафиксированный JSON-манифест с хэшами коммитов нод, типами релизов (`Hotfix`, `Standard`, `Major`), селективной пересборкой (`rebuild_on_trigger`) и историей трансфера `ЗР → ЗТ → ЗПЭ`.
  - После первого использования тип релиза становится неизменяемым (`sealed`).

### 3.5. Нулевое доверие к секретам (Zero Plaintext Secrets)
- **OpenBao** — единственный владелец реальных ключей и паролей.
- В PostgreSQL хранятся только ссылки: `forge_token_ref = "vault:secret/data/..."`.
- Никаких открытых паролей в коде, логах, бэкапах или git.

### 3.6. Скоростной безнапорный конвейер SAST (Zero-Pressure Ingestion)
- 50 воркеров льют SARIF в MinIO buffer → `FastEvidenceIngest` за < 0.01с раскладывает findings в базу `cosmo_findings` → Security Gates принимают решение **мгновенно**.
- Центральный Standalone SonarQube получает задачи плавно через `IngestTokenBucket` (по 1–2 задачи), не забивая свою очередь и не роняя базу дедлоками.

### 3.7. Единый UI Control Station + Встроенный легковесный редактор
- **Control Station**: React 18 + MUI Minimal UI + Meta Light (чистый белый корпоративный default, Grafana/Bloomberg плотность).
- **Inline Code Editor**: легковесный встроенный Monaco-редактор, открываемый **строго по deep-link** из гейта/уязвимости для быстрой правки 5 строк YAML/.wire/JSON конфига. Без претензий на замену VS Code.
