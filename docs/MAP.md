# Карта архитектуры и потоков данных Cosmoport 2.0 (MAP)

> Вопрос документа: **Каковы точные маршруты данных (Data-Flow), DTO, функции, таблицы БД и переходы состояний в Steel Thread платформы?**

---

## 1. Таблица потоков данных Steel Thread (Data-Flow по коду)

Сквозной жизненный цикл платформы разложен на 8 фаз. Каждый шаг привязан к конкретным файлам, DTO и таблицам БД:

| Фаза | Входной артефакт / DTO / Запрос | Файл и функция-обработчик | Куда пишет (БД / Память / Очередь) | Выходной артефакт / DTO / Ответ |
|---|---|---|---|---|
| **1. Domain & Binding** | `Domain`, `RepositoryBinding`<br>`PUT /api/v1/apps/{id}/repo-binding` | `orchestrator/cosmo/api/routes/apps.py::bind_repository()`<br>`orchestrator/cosmo/adapters/forge_gitea.py::ensure_webhook()` | Таблицы `cosmo_domains`, `cosmo_applications`, `cosmo_repository_bindings`. Секрет в OpenBao (`:8200`). | DTO `RepositoryBindingResponse`<br>Webhook в Gitea (`:3100`) с HMAC-секретом |
| **2. Forge Push** | `POST /api/v1/webhooks/gitea`<br>Headers: `X-Gitea-Signature`, `X-Gitea-Event: push`<br>Тело: `GiteaPushPayload` (JSON) | `orchestrator/cosmo/api/routes/webhooks.py::gitea_webhook()`<br>`orchestrator/cosmo/adapters/forge_gitea.py::verify_webhook_signature()` | Кэш `orchestrator/cosmo/api/forge_events.py::_LAST_PUSH`<br>Аудит в памяти `record_system_event()` | HTTP 200 `{"bound": true, "repo": "org/repo"}`<br>(или 202 `{"bound": false}` если репо не привязан) |
| **3. Plan Compile** | `POST /api/v1/plans/compile-from-source`<br>DTO `CompileFromSourceRequest`<br>(`app_id`, `ref`, `source_path`) | `orchestrator/cosmo/api/routes/pipelines.py::compile_from_source()`<br>↓ `GiteaForgeAdapter.read_file()`<br>↓ `orchestrator/cosmo/compiler/plan_compiler.py::PlanCompiler.compile()` | Таблицы `cosmo_pipeline_plans` (колонка `compiled_hash`), `cosmo_plan_bricks` (`sort_order`) | DTO `PipelinePlanSchema`<br>Детерминированный DAG батчей (`compiled_hash` SHA-256) |
| **4. Run Init** | `POST /api/v1/runs`<br>DTO `CreateRunRequest`<br>(`plan_id`, `domain_id`, `trigger`, `initiator_user_id`) | `orchestrator/cosmo/api/routes/runs.py::create_run()`<br>↓ `orchestrator/cosmo/control_plane/run_control.py::RunControlPlane.create_run()` | Таблица `cosmo_runs` (`status='pending'`, `initiator`), таблица `cosmo_batches` (`status='pending'`) | DTO `Run`<br>Событие `run_created` в Valkey Stream `cosmo:events` (`api/sse_backlog.py`) |
| **5. Batch Exec** | Диспетч из очереди FIFO:<br>`RunControlPlane.dispatch_next()`<br>↓ `BatchExecutor.execute_batch()` | `orchestrator/cosmo/control_plane/executor.py::BatchExecutor`<br>↓ `orchestrator/cosmo/adapters/execution_woodpecker.py::WoodpeckerExecutionAdapter` | Таблица `cosmo_batches` (`status='running' → 'passed'/'failed'`), таблица `cosmo_runs` (`status='running'`) | Запуск контейнеров в Woodpecker (`:8000`). Поток логов шагов. Событие `status_change` в SSE. |
| **6. Security Gate** | `POST /api/v1/gates/{id}/decision`<br>DTO `GateDecisionRequest`<br>(`decision: pass\|fail\|waived`, `reason`) | `orchestrator/cosmo/api/routes/gates.py::submit_decision()`<br>↓ `orchestrator/cosmo/control_plane/sod_guard.py`<br>↓ `orchestrator/cosmo/db/gate_trail_repo.py` | Таблица `cosmo_gates` (`status`), таблица `cosmo_gate_decisions` (аудит-след). При отказе: `cosmo_runs.status = 'blocked'`. | DTO `GateStatusSnapshot`<br>Событие `gate_decision` в Valkey Stream / SSE |
| **7. Evidence Ledger** | Завершение батчей/прогона<br>`POST /api/v1/runs/{id}/evidence`<br>DTO `RecordEvidenceRequest` | `orchestrator/cosmo/ledger/evidence_writer.py`<br>↓ `orchestrator/cosmo/ledger/evidence_chain.py::EvidenceLedger.add_entry()`<br>↓ `orchestrator/cosmo/ledger/gost_act.py` | Таблица `cosmo_evidence_ledger` (`index`, `hash`, `prev_hash`, `content` JSONB). Сырые логи и ГОСТ-акт в MinIO (`:9100`). | DTO `EvidenceChainResult` (integrity/verified). Endpoint `GET /api/v1/runs/{id}/gost-act/html`. |
| **8. Release Transfer** | `POST /api/v1/releases/{id}/transfer-v2`<br>DTO `TransferReleaseRequest`<br>(`target_zone: 'zt'\|'zpe'`, `package_mode`) | `orchestrator/cosmo/transfer/builder.py::PackageBuilder.build()`<br>↓ `orchestrator/cosmo/transfer/landing.py::LandingCheckReport` | Таблица `cosmo_releases` (`status='deployed'`, `current_zone`), таблицы `cosmo_transfer_plans`, `cosmo_transfer_items` | Запечатанный `DigitalReleaseEnvelope` с SHA-256 манифестом. Доставка через DiodeAdapter/SOD. |

---

## 2. Статусная машина жизненного цикла прогона (Run State Machine)

Код валидации и переходов: `orchestrator/cosmo/control_plane/run_control.py` (класс `RunState`, словарь `_VALID_TRANSITIONS`).

### Состояния (8 канонических статусов)
1. `draft` — прогон только создан, план не валидирован или требует подтверждения параметров.
2. `pending` — план скомпилирован и проверен, прогон готов к помещению в очередь исполнения.
3. `queued` — находится в FIFO-очереди диспетчера, ожидает доступного воркера нужной capability.
4. `running` — исполняется раннером (Woodpecker), контейнеры запущены, логи стримятся.
5. `succeeded` — терминальный статус: все батчи и обязательные гейты успешно пройдены.
6. `failed` — терминальный статус: критическая ошибка сборки, тестов или таймаут исполнения.
7. `blocked` — заблокирован: сработал Security Gate (найдены уязвимости) или ручной hold оператора ИБ.
8. `cancelled` — терминальный статус: принудительно остановлен оператором.

### Матрица допустимых переходов и прав

| Текущее состояние | Разрешённые следующие состояния | Инициатор перехода | Файл / Функция валидации | Условие / Поведение при отказе |
|---|---|---|---|---|
| `draft` | `pending`, `cancelled` | Пользователь / API | `run_control.py::transition()` | Проверка валидности `plan_id` и прав `Action.RUN_TRIGGER` |
| `pending` | `queued`, `cancelled` | Планировщик / Dispatcher | `run_control.py::enqueue_run()` | Наличие свободных слотов в квоте домена |
| `queued` | `running`, `cancelled` | Диспетчер воркеров | `run_control.py::dispatch_next()` | Выделение worker lease, совпадение capabilities |
| `running` | `succeeded`, `failed`, `blocked`, `cancelled`, `queued` | Раннер / Gate Engine / Watchdog | `executor.py::on_batch_complete()`<br>`run_control.py::reap_stale()` | При `infra` failure → requeue (`attempt < max_retries`). При `gate` failure → `blocked`. |
| `blocked` | `queued`, `cancelled` | Оператор ИБ (Approval) | `api/routes/gates.py::submit_decision()` | Снятие блокировки требует подписи с ролью `sec_admin` (SOD Guard) |
| `succeeded` | *(терминальное, переходы запрещены)* | — | `_VALID_TRANSITIONS` | Запись неизменяема |
| `failed` | *(терминальное, переходы запрещены)* | — | `_VALID_TRANSITIONS` | Запись неизменяема |
| `cancelled` | *(терминальное, переходы запрещены)* | — | `_VALID_TRANSITIONS` | Запись неизменяема |

### Классификация отказов (`FailureClass` в `run_control.py`)
- `INFRA` (сеть, рестарт воркера, таймаут связи) → автоматический повтор (`RunState.RUNNING → QUEUED`, инкремент `attempt`).
- `VALIDATION` (битый YAML, циклы в depends_on) → мгновенный перевод в `RunState.FAILED`.
- `TARGET` (недоступен целевой тестовый стенд) → мгновенный перевод в `RunState.FAILED`.
- `GATE` (нарушены критерии приемки по безопасности) → перевод в `RunState.BLOCKED`.

---

## 3. Инженерная Data-Flow схема (Mermaid с кодом и DTO)

```mermaid
flowchart TD
    subgraph Forge["1. Исходники и триггер"]
        GiteaClient["Gitea Server (:3100)"]
    end

    subgraph API_Webhooks["2. Входной шлюз вебхуков"]
        WH_Route["orchestrator/cosmo/api/routes/webhooks.py\nPOST /api/v1/webhooks/gitea"]
        ForgeAdapter["orchestrator/cosmo/adapters/forge_gitea.py\nverify_webhook_signature()"]
        EventsCache["orchestrator/cosmo/api/forge_events.py\n_LAST_PUSH cache"]
    end

    subgraph Compiler["3. Компилятор пайплайнов"]
        PipeRoute["orchestrator/cosmo/api/routes/pipelines.py\nPOST /api/v1/plans/compile-from-source"]
        PlanCompiler["orchestrator/cosmo/compiler/plan_compiler.py\nPlanCompiler.compile() & compile_hash()"]
        TablePlans[("orchestrator/cosmo/db/models.py\nTable: cosmo_pipeline_plans\n(compiled_hash SHA-256)")]
    end

    subgraph ControlPlane["4. Машина состояний и диспетчер"]
        RunsRoute["orchestrator/cosmo/api/routes/runs.py\nPOST /api/v1/runs"]
        RunControl["orchestrator/cosmo/control_plane/run_control.py\nRunControlPlane.create_run() & transition()"]
        TableRuns[("orchestrator/cosmo/db/models.py\nTable: cosmo_runs\n(status: pending -> running)")]
        ValkeyStream[("Valkey 8 (:6379)\nStream: cosmo:events\n(SSE Backlog COS-088)")]
    end

    subgraph Execution["5. Исполнение шагов"]
        Executor["orchestrator/cosmo/control_plane/executor.py\nBatchExecutor.execute_batch()"]
        WoodpeckerAdapter["orchestrator/cosmo/adapters/execution_woodpecker.py\nstart_pipeline() & poll_status()"]
        WoodpeckerServer["Woodpecker Server (:8000)\nDocker container steps"]
    end

    subgraph Gates["6. Контроль безопасности"]
        GatesRoute["orchestrator/cosmo/api/routes/gates.py\nPOST /api/v1/gates/{id}/decision"]
        SODGuard["orchestrator/cosmo/control_plane/sod_guard.py\nverify_separation_of_duty()"]
        TableGates[("orchestrator/cosmo/db/models.py\nTable: cosmo_gate_decisions")]
    end

    subgraph Ledger["7. Журнал улик и ГОСТ"]
        EvidenceChain["orchestrator/cosmo/ledger/evidence_chain.py\nEvidenceLedger.add_entry()"]
        GostRenderer["orchestrator/cosmo/ledger/gost_act.py\nrender_gost_act_html()"]
        TableEvidence[("orchestrator/cosmo/db/models.py\nTable: cosmo_evidence_ledger")]
        MinIOStore[("MinIO S3 (:9100)\nBucket: cosmo-artifacts")]
    end

    subgraph UI["8. Клиентская витрина"]
        FE_SSE["frontend/src/cosmo/shared/useLiveDomain.ts\nEventSource -> Domain SSE"]
        FE_View["frontend/src/cosmo/station/views/ReleaseReadiness.tsx\nReleaseReadiness Component"]
    end

    %% Потоки данных с точными типами
    GiteaClient -->|HTTP POST + X-Gitea-Signature\nBody: GiteaPushPayload| WH_Route
    WH_Route -->|raw bytes + secret| ForgeAdapter
    WH_Route -->|PushEvent DTO| EventsCache

    EventsCache -.->|Триггер компиляции| PipeRoute
    PipeRoute -->|App ID + ref + .cosmo/pipeline.yaml| PlanCompiler
    PlanCompiler -->|PlanModel + PlanBricks| TablePlans
    PlanCompiler -->|DTO: PipelinePlanSchema| RunsRoute

    RunsRoute -->|DTO: CreateRunRequest| RunControl
    RunControl -->|INSERT status='pending'| TableRuns
    RunControl -->|Event: run_created| ValkeyStream

    RunControl -->|dispatch RunRecord| Executor
    Executor -->|generate Woodpecker YAML| WoodpeckerAdapter
    WoodpeckerAdapter -->|gRPC / REST start| WoodpeckerServer
    WoodpeckerServer -->|poll status: running/success| WoodpeckerAdapter
    WoodpeckerAdapter -->|BatchResult| Executor
    Executor -->|UPDATE status='running'/'succeeded'| TableRuns
    Executor -->|Event: status_change| ValkeyStream

    Executor -->|проверка политик гейтов| GatesRoute
    GatesRoute -->|DTO: GateDecisionRequest| SODGuard
    SODGuard -->|INSERT audit decision| TableGates

    Executor -->|артефакты логов и проверок| EvidenceChain
    EvidenceChain -->|SHA-256 chain node: prev_hash -> hash| TableEvidence
    EvidenceChain -->|генерировать ГОСТ-Акт| GostRenderer
    GostRenderer -->|HTML & SARIF bytes| MinIOStore

    ValkeyStream -->|SSE events: status_change, run_created| FE_SSE
    FE_SSE -->|React State Update| FE_View
    FE_View -->|REST GET /api/v1/runs/{id}/evidence| TableEvidence
```

---

## 4. Внешние продуктовые контуры (PK-DIR-008 §1 naming)

Платформа PrettyK — три отдельных продукта; границы только по wire-контрактам
(REST / Webhook / SSE), cross-repo imports запрещены. Направление
security-qualification flow (канон: `docs/RELEASE-QUALIFICATION-FLOW-DRAFT.md` §1):

```text
Cosmoport (ПУ, эта репа)
  → Build / required checks / qualifying deployment
  → Коробка (PrettyK SecOps, D:\prettyk-secops): DAST + Evidence + execution verdict + Act
  → Hub (PrettyK Hub, D:\prettyk-hub; ранее QGFCS): intake findings, triage, baseline, QG assessment
  → Hub публикует candidate status: waiting | blocked | unlocked
  → ПУ монитори́т статус и выполняет transfer только при unlocked
```

- **Коробка** — execution-слой: raw results, Evidence, Act (первичные отчёты).
- **Hub (PrettyK Hub, ранее QGFCS)** — source of truth Findings/triage/baseline,
  вычисляет и публикует QG status `waiting|blocked|unlocked`; ПУ статус
  потребляет, не пересчитывает.
- **Cosmoport** — единственный оркестратор сборки, пакета, transfer и deployment.

Реализация моста в этом репозитории пока отсутствует (external bridge не
создан — только wire-контракты в drafts).

---

## 5. Контрольные точки стенда и порты

| Сервис | Порт | Протокол | Точка входа в коде | Назначение в Data-Flow |
|---|---|---|---|---|
| `cosmo-frontend` | `:5174` | HTTP | `frontend/nginx.conf` | Единый шлюз SPA, проксирует `/api/` на `:8100` |
| `cosmo-caddy` | `:8180` | HTTP/S | `services/caddy/Caddyfile` | Production TLS Reverse-proxy и Rate limiter |
| `cosmo-api` | `:8100` | HTTP | `orchestrator/cosmo/api/main.py` | Ядро FastAPI, обработка REST и SSE |
| `cosmo-gitea` | `:3100` | HTTP | Docker image `gitea/gitea:1.22` | Источник исходников и эмиттер вебхуков |
| `cosmo-woodpecker`| `:8000` | HTTP | Docker image `woodpeckerci/woodpecker-server` | Исполнитель контейнерных шагов CI |
| `cosmo-postgres` | `:5432` | TCP | `orchestrator/cosmo/db/session.py` | Главное хранилище (35 durable таблиц) |
| `cosmo-valkey` | `:6379` | TCP | `orchestrator/cosmo/api/sse_backlog.py` | Буфер SSE-событий (Valkey Streams) |
| `cosmo-minio` | `:9100` | S3 API| `orchestrator/cosmo/ledger/artifact_store.py` | Неизменяемое хранение артефактов и логов |
| `cosmo-openbao` | `:8200` | HTTP | `orchestrator/cosmo/adapters/tls_config.py` | Хранилище секретов и токенов Forge |

---

## 6. Release lifecycle DOCKER_AUDIT (SBOM + Trivy gate → deploy) — COS-167/168

Профиль `DOCKER_AUDIT` (Э4): `build_image → sbom → trivy → deploy`. Два шага,
закрытые COS-167 (SBOM поверх образа) и COS-168 (trivy container scan + gate),
материализуют **честный** аудит перед deploy. Единый источник вердикта — Evidence
Ledger (канон COS-138: gates-таблицу per-release НЕ пишем).

| Шаг | DTO / эндпоинт | Файл и функция | Куда пишет | Вердикт |
|---|---|---|---|---|
| **sbom** (COS-167) | `POST /api/v1/artifacts/sbom/image`<br>`GET /api/v1/artifacts/sbom/image/{name}/{version}` | `ledger/artifact_sbom.py::anchor_artifact_sbom()` / `latest_artifact_sbom()`<br>`domain/artifact_sbom.py` (DTO) | `evidence_ledger` (`source='cosmo-artifact-sbom'`, `document` + `content_hash`); `ArtifactRecord.sbom_ref` durable latest wins | CycloneDX 1.5 (syft → `python-inventory` fallback, честный `generator`); digest by-construction == ArtifactRecord |
| **trivy** (COS-168) | `POST /api/v1/releases/{id}/trivy/attach`<br>`GET /api/v1/releases/{id}/trivy` | `ledger/artifact_scan_gate.py::verify_and_attest_trivy_gate()`<br>`domain/artifact_scan.py` (DTO) — `run_trivy_scan` честный `unavailable` при отсутствии бинаря | `evidence_ledger` (`source='cosmo-trivy-gate'`) | `critical = max(заявленный, наблюд.)`; `>0 → BLOCK/DENIED`, иначе `PASS/CLEARED`; digest-сверка конверта/отчёта/образа |
| **deploy** (COS-165) | `POST /api/v1/releases/{id}/deploy` | `routes/releases.py::deploy_release()` → `trivy_blocker_for_records()` | `releases.status` `deploying → deployed / rollback` | materialize ТОЛЬКО при trivy PASS каждого образа; BLOCK/нет вердикта → 409 |

Канонический ref образа: `<name>:<version>@sha256:<manifest-digest>` (COS-142/162);
`sbom_ref`: `oci://<registry>/<repo>/<ns>/<name>@<digest>#sbom`.

---

## 7. Release promotion ЗР→ЗТ→ЗПЭ (packing + landing) — COS-169/170

Поверх `deployed`-релиза: упаковка в transfer-пакет (digest-pin + SBOM + trivy gate),
затем landing в следующей зоне с digest-matching → `promoted`. Единый источник вердикта —
Evidence Ledger (без новых таблиц, канон COS-138): `source='cosmo-promotion-package'`
(pack) / `source='cosmo-promotion-landing'` (landing).

| Шаг | DTO / эндпоинт | Файл и функция | Куда пишет | Вердикт |
|---|---|---|---|---|
| **pack** (COS-169) | `POST /api/v1/releases/{id}/promote`<br>`GET /api/v1/releases/{id}/promotion` | `ledger/promotion_ledger.py::pack_release_promotion()` / `latest_promotion_package()`<br>`domain/promotion.py` (`PromotionPackage`) | `evidence_ledger` (`source='cosmo-promotion-package'`) | idempotent (`duplicate` на совпадении `content_fingerprint`); gate trivy PASS + `sbom_ref` обязательны; нет → 409 |
| **land** (COS-169) | `POST /api/v1/releases/{id}/promote/land`<br>`GET /api/v1/releases/{id}/promotion/land` | `ledger/promotion_ledger.py::land_release_promotion()` / `latest_promotion_landing()`<br>`domain/promotion.py` (`PromotionLandRequest`/`PromotionLandResponse`) | `releases.current_zone` + `transfer_history`; `evidence_ledger` (`source='cosmo-promotion-landing'`) | replay `duplicate` → CAS 409 → digest-mismatch 422 → линейная зона 409 → trivy/SBOM re-read → `promoted` |

Порядок в `land_release_promotion`: idempotent replay (уже `promoted` → `duplicate`)
→ CAS `expected_current_zone` → manifest-digest match → линейный путь `next_zone` →
belt-and-suspenders trivy/SBOM re-read → перевод зоны + durable evidence.
`package_digest` = SHA-256 канонического JSON манифеста без timestamp (детерминирован).
