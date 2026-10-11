# Airlock — обзор системы: сущности, исполнители, зависимости, технологии

> **Вопрос документа:** какие сущности есть в Airlock, где они живут, чем исполняются,
> какие зависимости у контура и на каких технологиях собран продукт.
> **Дата снимка:** 2026-10-05. **Статус:** живой обзор (меняется волнами; при расхождении
> приоритет — код и карточки, затем `MAP.md`/`STACK.md`).
> **См. также:** [`MAP.md`](MAP.md) (data-flow Steel Thread), [`STACK.md`](STACK.md) (стек-канон),
> [`DEPLOYMENT.md`](DEPLOYMENT.md) (развёртывание), [`PERSISTENCE.md`](PERSISTENCE.md) (хранение),
> [`BACKLOG.md`](BACKLOG.md) (текущие волны), [`INDEX.md`](INDEX.md) (навигация).

---

## 1. Что такое Airlock

Airlock (бывший «Космопорт 2.0») — **Sovereign Run Control Plane**: суверенный оркестратор
жизненного цикла безопасной поставки ПО в закрытом контуре (банковская специфика, airgap-prone).
Продукт **владеет истиной** (сущности, статусы, решения, улики) и **оркестрирует исполнение**,
но не исполняет тяжёлые процессы «в себе»: сборка, сканирование и пользовательские сессии
делегируются внешним исполнителям (CI, сканеры, sandbox, Docker) — это осознанная граница
безопасности, зафиксированная в каноне (BAN.md, ARCHITECTURE-DIRECTION §9).

**Канонический контур (8 сущностей):** Domain → Pipeline → Compile → Run → Batch → Gate →
Evidence → Transfer. Поверх них — прикладные поверхности: Releases, Builds, Deployments,
Workspace API (для IDE), Findings/Scans, Notifications, Hub-контракты, аудит.

---

## 2. Канонические сущности: где живут и чем исполняются

| # | Сущность | Где живёт (таблицы / хранилище) | Чем исполняется / кто владеет | Ключевые контракты |
|---|---|---|---|---|
| 1 | **Domain** (и проектные связи: Project/App/Groups/Kits/Teams) | `domains`, `apps`, `groups`, `repo_bindings`, `projects`, `project_applications`, `kits_tags`, `application_kits_tags`, `project_teams`, `application_teams` (PG) | `cosmo-api` (routes: domains/projects/apps); привязка к Gitea — forge-adapter, webhook HMAC | `PUT /api/v1/apps/{id}/repo-binding`, `POST /api/v1/webhooks/gitea`; секреты — OpenBao `secret/cosmo/*` |
| 2 | **Pipeline** (кирпичи и планы) | `pipeline_bricks`, `pipeline_plans` (+`compiled_hash`), `plan_bricks` (PG) | Компилятор `compiler/plan_compiler.py` (детерминированный DAG); каталог кирпичей — API; политики `build_modes.py` (PUREK/SECURITY_COSMO) | `POST /api/v1/plans/compile*`; BrickType: build / sast / sca / deploy / dast / autotest / gate |
| 3 | **Run / Batch** (прогоны и шаги) | `runs`, `batches`, `cosmo_execution_handles`, `cosmo_workspace_runs` (PG); логи-события — Valkey Streams | `RunControlPlane` (8-статусная машина, классы отказов) + `BatchExecutor` → **Woodpecker CI** (submit/poll/cancel, логи); SSE-мультиплексор | `POST /api/v1/runs`, `GET /runs/{id}/logs/stream` (SSE, resume по `id`); findings прогона — `runs.findings_refs` (канон dict-findings, DTO `FindingRef`) |
| 4 | **Gate** (гейты и решения) | `gates`, `gate_decision_trail` (PG); вердикты сканов — `evidence_ledger` | `GatePolicyEngine` (Critical→BLOCK, High→WARN-порог), SoD-guard, финализация прогона; durable trail пишется в одной транзакции с ответом | `POST /api/v1/gates/{id}/decision`; trivy/SBOM-гейты: `artifact_scan_gate`, `artifact_sbom` |
| 5 | **Evidence** (улики) | `evidence_ledger` (SHA-256-цепочка, tamper-detect, anchor); байты артефактов — локальный FS-кэш + **durable MinIO-зеркало** (`artifact://…`, `_refs/{ref_id}`) | `EvidenceLedger` + `gost_assembler` (ГОСТ-акт JSON/HTML); `artifact_store` (COS-202: зеркало в S3/MinIO, SigV4); захват артефактов из логов CI-шагов | `POST /runs/{id}/evidence`, `GET /runs/{id}/gost-act[/html]`; контракты `artifact://…` и `content_hash` стабильны |
| 6 | **Transfer** (межзонный трансфер) | `transfer_plans`, `transfer_items`, `transfer_landing_states`, `transfer_received_revisions` (PG); evidence-based promotion — ledger | `transfer/*` (PackageBuilder, landing FSM, offline importer, DiodeAdapter, gateway lease); ZR→ZT→ZPE promotion | `POST /api/v1/releases/{id}/transfer-v2`, `/promote`, `/promote/land`; digest-pin канон `name:version@sha256:` |
| 7 | **Release / Build / Deploy** | `releases`, `release_types`, `release_batches`, `cosmo_builds`, `cosmo_deployments`, `artifact_records`, `instance_configuration` (PG) | Build — шаг Woodpecker (`docker build` + push в registry по каноническому digest-тегу); сканы образа — бинарники в образе `cosmo-api` (trivy/syft/grype); Deploy — `DeployRuntime` (docker pull/run/healthy, честный rollback); release-deploy гейтится trivy PASS | `POST /apps/{id}/builds`, `POST /releases/{id}/deploy`, `POST /releases/{id}/trivy/attach`; digest-истина — в `artifact_records` + ledger |
| 8 | **Workspace** (для Web IDE; не в цикле 8, но сервисный слой) | Черновики — Valkey (TTL); коммиты/деревья — Gitea; прогоны — `cosmo_workspace_runs` | Workspace API (`routes/workspace.py`) поверх forge-adapter; CAS-записи, ref-readonly snapshot по commit, typed 409 | `GET /repos/workspace/{bootstrap,tree,file}`, `POST /repos/workspace/commits`, `POST /repos/workspace/run`, `POST /runs/{id}/tty` |

---

## 3. Прикладные поверхности

| Поверхность | Где живёт | Чем исполняется | Примечание |
|---|---|---|---|
| **Findings / Scans** | Канонический носитель — `runs.findings_refs`; поиск — `findings.py`; legacy-таблицы `scan_results`/`scan_findings`/`scan_evidence` | Мост COS-101 (`findings_bridge`), ingest SARIF/CE (`sast_ingest`), source-SAST — шаг Woodpecker (`sonar-scanner-cli`) против SonarQube CE; контейнер-сканы — trivy, SBOM — syft, grype-визор | v1: security-findings; Quality/coverage — опция позже; scanner-таблицы — исторический модуль, не канонический носитель |
| **Notifications** | `notification_events`, `notification_inbox`, `notification_subscriptions`, `notification_channel_configs` (PG) | Outbox-worker внутри `cosmo-api`; каналы: in-app + email; DLQ/retry; SSE-проекция через Valkey | Taxonomy включает `run_blocked` (гейт), `transfer_*` и т.п.; dedup + redaction |
| **Hub-контракты (A/B/C)** | Durable — `evidence_ledger` (read-through реестры) | `adapters/hub_client.py` + `hub_dispatcher`, маршруты `routes/hub.py` | A: приём вердиктов Hub; B: dispatch оценки прогона в Hub; C: clearance-callback → fail-closed transfer authorization |
| **Аудит** | In-memory журнал процесса (`routes/audit.py`), экспорт CSV | `record_system_event` (webhook и системные события) | Честная граница: durable-таблица — follow-up вне миграционного freeze |
| **PTY / sandbox** | Сессии — эфемерные контейнеры; аудит — JSONL (volume) | Отдельный сервис `pty-sandbox` (профиль `pty`, default-off; :8190), не в PG | Канон: PTY — не замена безопасному runner'у; wire с Vector не согласован (PTY-SERVER-2 ждёт) |
| **Демо-цель (dogfooding)** | `apps/cosmo-testapp` (репозиторий-приложение) | Собирается и деплоится тем же контуром (build → registry → deploy) | Используется в живых e2e (COS-161…170, COS-166) |

---

## 4. Реестр таблиц PostgreSQL (38)

Реестр `orchestrator/cosmo/db/models*.py`, снимок 2026-10-05; миграционная цепочка — Alembic
(часть поверхностей живёт на отдельных `Base` вне frozen-цепочки — gate trail, transfer, execution).

| Группа | Таблицы | Кол-во |
|---|---|---|
| Ядро (домен/план/прогон/гейт/улики/релиз) | `domains`, `groups`, `pipeline_bricks`, `apps`, `repo_bindings`, `pipeline_plans`, `plan_bricks`, `batches`, `gates`, `runs`, `releases`, `evidence_ledger`, `cosmo_builds`, `cosmo_deployments` | 14 |
| Project/App-связи, типы релизов, артефакты | `projects`, `project_applications`, `kits_tags`, `application_kits_tags`, `project_teams`, `application_teams`, `release_types`, `release_batches`, `artifact_records`, `instance_configuration` | 10 |
| Transfer | `transfer_plans`, `transfer_items`, `transfer_landing_states`, `transfer_received_revisions` | 4 |
| Уведомления | `notification_events`, `notification_inbox`, `notification_subscriptions`, `notification_channel_configs` | 4 |
| Scanner (legacy) | `scan_results`, `scan_findings`, `scan_evidence` | 3 |
| Execution | `cosmo_execution_handles`, `cosmo_workspace_runs` | 2 |
| Gate trail (отдельный Base) | `gate_decision_trail` | 1 |

---

## 5. Сервисы и порты (стенд)

**Профили Compose:** `core` (по умолчанию) · `full` (forge/CI/storage) · `pty` (sandbox) ·
companion-файлы: `registry`, `openbao`, `sonarqube`, `test-pg`, `dev` (override для разработки).

| Сервис | Контейнер | Порт (host) | Профиль | Роль |
|---|---|---|---|---|
| PostgreSQL 16 | `cosmo-postgres` | 5432 | core | Durable SoT (38 таблиц) |
| Valkey 8 | `cosmo-valkey` | 6379 | core | SSE-блог, черновики, тикеты, очередь |
| API (FastAPI) | `cosmo-api` | 8100 | core | Ядро: REST/SSE, оркестрация, сканы-бинари |
| Frontend | `cosmo-frontend` | 5174→80 | core | Control Station + встроенная Surface B |
| Caddy (edge) | `cosmo-caddy` | 8180→80 | core | Единый вход: SPA + `/api` + `/registry/*` |
| MinIO | `cosmo-minio` | 9100 / 9101 | full | S3-хранилище артефактов и evidence-зеркала |
| Gitea 1.22.6 | `cosmo-gitea` | 3100→3000 | full | Forge: исходники, вебхуки, коммиты |
| Woodpecker v3.5 (server) | `cosmo-woodpecker` | 8000 | full | CI-сервер (submit/status/logs) |
| Woodpecker agent | `cosmo-woodpecker-agent` | — | full | Исполнитель шагов (docker backend, docker.sock) |
| Registry ЗР (distribution) | `cosmo-registry-zr` | 5100→5000 | companion `registry` | OCI-реестр зоны разработки (+health-sidecar) |
| Registry ЗТ | `cosmo-registry-zt` | 5200→5000 | companion (`replicas: 0`) | Зона тестирования — off by design |
| OpenBao | `prettyk-openbao` | 127.0.0.1:8200 | companion `openbao` (платформенный) | Секреты `secret/cosmo/*`, AppRole `cosmo-app` |
| SonarQube CE | `cosmo-sonarqube` (+db) | 9000 | companion `sonarqube` | Source-SAST (сканер — шаг Woodpecker) |
| Test-PG | `cosmo-test-pg` | 5433→5432 | companion `test-pg` | Изолированный тестовый PG (никогда не dev-БД) |
| PTY sandbox | `pty-sandbox` | 127.0.0.1:8190 | `pty` (default-off) | Эфемерные сессии, allowlist, аудит |

**Сети:** `cosmo-net` (собственная, изоляция контура) + `pk-infra` (внешняя — только к
платформенному OpenBao). **Volumes:** данные PG/Valkey/MinIO/Gitea/Woodpecker/Caddy,
кэши сканеров (trivy/grype), аудит sandbox.

---

## 6. Исполнители: кто что реально исполняет

| Деятельность | Исполнитель | Как это устроено |
|---|---|---|
| Шаги прогонов (build, sast, произвольные шаги) | **Woodpecker** server + agent | Шаги — контейнеры в `cosmo-net`; фактическая конфигурация — в репозитории (`.woodpecker.yml`); каталог кирпичей и аудит-YAML — сверочная форма; агент работает через `docker.sock` |
| Сборка образа и push | Woodpecker-шаг (`docker:24-cli`) | `docker build` под qualified-тегом → `docker push` в registry зоны; manifest-digest снимается с ответа push (канон COS-162/166) |
| Контейнер/артефакт-сканы, SBOM, grype | Бинарники **trivy / syft / grype** внутри образа `cosmo-api` (subprocess) | Offline DB в volumes (`cosmo_trivy_cache`, `cosmo_grype_cache`); insecure — только через allowlist registry |
| Source-SAST | **SonarQube CE** + шаг Woodpecker (`sonar-scanner-cli`) | Отчёт (CE API) захватывается как durable evidence, findings авто-ингестятся в гейт (SAST-GATE-3) |
| Деплой (материализация) | **Docker** через `DeployRuntime` (docker CLI) | `pull` по immutable digest → `run` в `cosmo-net` → healthy-check; статус `deployed` — только по факту healthy, иначе честный rollback; зависимость: доступ к Docker (dev — хост; прод-профиль — агент с docker.sock) |
| Реестр образов | **distribution** (`local-oci`) | Зоны; ЗР живой, ЗТ/ЗПЭ — по готовности |
| Секреты и ключи | **OpenBao** | AppRole `cosmo-app` → `secret/cosmo/*` (PG/MinIO/Gitea/Woodpecker/JWT-ключи/Sonar-токен); fail-closed |
| Аутентификация | Собственный issuer в `cosmo-api` | RS256 JWT + JWKS, PBKDF2-креденшелы, роли/кэпабилити; verify — crypto, fail-closed |
| SSE-логи и события | **Valkey Streams** | Backlog с `id` + replay; обрыв SSE не теряет события (resync при gap) |
| Уведомления | Outbox-worker в `cosmo-api` | Внутренний торговый цикл: retry/DLQ, in-app + email, redaction |
| PTY-сессии (опция) | Сервис `pty-sandbox` (default-off) | Эфемерный контейнер на сессию: allowlist, network none, ro-rootfs, лимиты, TTL |

---

## 7. Зависимости

### 7.1 Внутренние (внутри контура)

```text
cosmo-frontend → cosmo-caddy → cosmo-api → { PG, Valkey, MinIO, OpenBao, Gitea, Woodpecker, Docker, registry }
cosmo-woodpecker(-agent) → PG, Gitea, Docker(docker.sock)
cosmo-gitea → PG
сканы/SAST → registry (образы/отчёты) + Sonar CE
deploy → registry (pull) + Docker
```

**Поведение при отказах (fail-closed / честная деградация):**
- нет OpenBao → login/JWKS fail-closed (503), секреты не подставляются;
- нет Valkey → SSE в degraded-режиме (in-memory), черновики недоступны честно;
- нет MinIO → durable-зеркало артефактов деградирует видимо (`degraded_reason`), локальная копия цела; evidence-anchor `disabled`;
- нет Sonar CE / сканера → шаг/скан честно падает, гейт не пропускает без вердикта;
- нет Docker → deploy не материализуется (честная ошибка, без «success»).

### 7.2 Межпродуктовые (линия PrettyK)

| Контур | Статус стыка | Что ходит |
|---|---|---|
| **PrettyK Hub** (ранее QGFCS) | Contract A/B/C приняты и работают на стороне Airlock; read-through durable | Мы шлём оценку (B), принимаем вердикт/клиренс (A/C); transfer fail-closed без `PASS_GRANTED` |
| **Коробка / SecOps** | Канон передачи — StudioRunOutput → Hub; прямой adapter в Airlock не строится | DAST-факты приходят через Hub-контур (не прямым импортом) |
| **Web IDE** | Внешний продукт `prettyk-ide` ходит в Workspace API; встроенная Surface B — переходный контур | REST/same-origin через Airlock; токен не в URL (контракт согласуется) |
| **OpenBao (платформа)** | Потребляем как capability | `secret/cosmo/*`, AppRole; root-token в рантайме нет |
| **Сфера (T1)** | Legacy provider seam + capability matrix; live-верификация без доступа | Push/pull/provisioning по код-подтверждённой карте; UNKNOWN честно |
| **Airgap/зоны** | Bundle/import + immutable-теги (COS-195), ЗТ/ЗПЭ по готовности | Offline-пакеты, digest-сверка, evidence на каждой зоне |

---

## 8. Технологии

### Backend (`orchestrator/`, корневой `requirements.txt`)

- **Python 3.12+**, **FastAPI ≥0.115** (REST + SSE), **Pydantic v2**, **SQLAlchemy 2 (async)** + **asyncpg**,
  **Alembic** (миграции), **valkey-py**, **httpx/requests**, **cryptography ≥42** (RS256 JWT/JWKS, SigV4),
  pytest + pytest-asyncio; стиль — чистые DTO (domain/), адаптеры (adapters/), оркестрация (control_plane/),
  реестры-цепочки (ledger/), маршруты (api/routes/).

### Frontend (`frontend/`, `package.json`)

- **React 19.1** + **TypeScript 5.8** + **Vite 6**;
- **MUI 9** (Core + X Data Grid 9, шаблон Meta Light) — Control Station;
- **Monaco 0.56**, **@xterm/xterm 5.5**, **@xyflow/react 12** — редактор/терминал/графы Surface B;
- **Tailwind v4** (изолирован внутри `.cosmo-ide-root`), **zundo** (undo-стор);
- тесты: **Vitest 4** + Testing Library (unit), **Playwright 1.62** (e2e, live-стенд).

> STACK.md в части FE-версий слегка отстаёт (там React 18/MUI «Core»); фактические версии — в `package.json`.

### Инфраструктура (`services/`)

- **PostgreSQL 16** (JSONB + GIN) — durable SoT; **Valkey 8** (Streams/PubSub) — транспорт;
  **MinIO** (S3-контракт) — артефакты; **Caddy** — единый edge; **Gitea 1.22.6** — forge;
  **Woodpecker v3.5** (server+agent, docker backend) — CI; **distribution** — OCI-реестр;
  **OpenBao** — секреты; **SonarQube CE 26.8** — source-SAST; **Docker Compose** — профили
  `core/full/pty` + companion-файлы.

### Инженерные практики

- Suite gate одной командой (`services/scripts/suite_gate.ps1`), runtime-gate и smoke-скрипты,
  идемпотентные сиды фикстур, immutable-релизы образов (`build-release.ps1`), Docker-гигиена
  (`image-hygiene.ps1`, `check-bind-mounts.ps1`), OpenAPI-гвард `json == yaml == live`
  (`regen_openapi.py --check`).
- **Канон live-проверки:** юнит-зелёный ≠ live-рабочий — для build/deploy-контура обязателен
  сквозной live-smoke (урок COS-166: config-digest ≠ manifest-digest).

---

## 9. Карта правды (Source of Truth)

| Что | Где истина |
|---|---|
| Сущности, статусы, решения | PostgreSQL (38 таблиц) |
| Улики | `evidence_ledger` (цепочка + хеши) + MinIO (байты) + внешний anchor (file/S3) |
| Образы | Registry (immutable digest) |
| Исходники | Gitea (коммиты/ветки) |
| Секреты | OpenBao (`secret/cosmo/*`) |
| Логи/SSE | Valkey Streams (+ терминальный след в ledger/evidence) |
| Аудит | In-memory процесс API (durable — follow-up) |

---

## 10. Честные границы (на 2026-10-05)

- Прямой мост «Коробка → Airlock» не строится — intake идёт через Hub-контур (Contract A/B/C).
- PTY: серверная половина (PTY-SERVER-2+) ждёт согласования wire `runnerTty` с Vector; sandbox — опция, default-off.
- Аудит-журнал живёт в процессе API (durable-таблица — вне миграционного freeze).
- Деплой-материализация требует доступа к Docker; в контейнере `cosmo-api` socket не монтируется (by design) — посадка прод-профиля через агента.
- Переезд ранее сохранённых evidence-байтов на durable-хранилище — вне scope (новые захваты уже durable).
- Sfera live-контракт — без доступа к контуру (UNKNOWN честно).
- SAST: v1 — security-findings; Quality/coverage, масштабирование пула и CodeScoring — по решениям владельца.
