# Cosmoport 2.0 — Architecture & Onboarding

> **Статус:** 2FA sealed 28 августа 2026. 277 тестов, 0 skipped.  
> **Repo:** https://github.com/prettyk-io/prettyk-airlock  
> **Parent:** `D:\prettyk-dev` (Pure Box + планирование в `sanctuary/cosmoport2/`)

---

## 1. Что такое Cosmoport 2.0

**Sovereign Run Control Plane** — суверенная платформа управления жизненным циклом безопасности разработки.

Оркестрирует пайплайны (SAST → SCA → Build → Deploy → DAST → Fuzzer), управляет Security Gates, собирает Evidence Chain с SHA-256, контролирует релизы и деплой.

### Ключевое отличие от Cosmoport 1.0

| Старый (1.0) | Наш (2.0) |
|---|---|
| Паразитический клей над GitLab CI | Суверенный Control Plane |
| Статусы в Redis (теряются) | Статусы в PostgreSQL (durable) |
| GitLab CI YAML как движок | PlanCompiler + Batch DAG + State Machine |
| Нет Security Gates | Gates в PostgreSQL с ручным/автоматическим решением |
| Нет Evidence Chain | SHA-256 цепочка доказательств |
| 80+ таблиц, 97 сервисов | 8 чистых Pydantic-моделей |
| Ant Design + MobX | MUI Control Station + Inline Monaco Editor |

---

## 2. Стек

| Слой | Выбор | Запрещено |
|---|---|---|
| **Backend Core** | Python 3.12+ / FastAPI / Pydantic v2 | Rails, Node.js, Go |
| **Durable Truth** | PostgreSQL 16 (JSONB + GIN) | MongoDB, Redis как SoT |
| **Queue/Transport** | Valkey 8 (Streams + PubSub) | RabbitMQ, Kafka, Celery |
| **Artifact Storage** | S3-контракт (MinIO / Local FS) | BLOB в PostgreSQL |
| **Auth/KMS** | Better Auth + OpenBao | Keycloak, Blitz OIDC |
| **Surface (Control Station)** | React 18 + TS + Vite + MUI Core + MUI X Data Grid + @xyflow/react · Meta Light default | AntD, React Admin |
| **Inline Editor** | Monaco + Tailwind (внутри Control Station, только по deep-link из Security Gate / Finding) | Отдельная IDE-поверхность |

### Архитектурные границы

```text
┌──────────────────────────────────────────────────────────────┐
│                     Cosmoport 2.0                            │
│  (FastAPI + Pydantic + SQLAlchemy + PostgreSQL)              │
│                                                              │
│  CapabilityBroker.acquire("scanner")                         │
│  ──────────────────────────────────▶                        │
│                                      Pure Box                │
│                                      ┌───────────────────┐   │
│                                      │ scanner + PW CDP   │   │
│                                      │ (внутреннее дело)  │   │
│                                      └───────────────────┘   │
│  ◀──────────────────────────────────                        │
│  webhook / SSE (результаты)                                  │
└──────────────────────────────────────────────────────────────┘
```

**Cosmo НЕ управляет процессами ZAP/Playwright.** Он только триггерит сессию через `CapabilityBroker.acquire()` и получает результаты через webhook/SSE. `ScannerCtl`, `PlaywrightCtl`, `tool_ctl` — **BANNED** (COS-040, BAN.md).

---

## 3. Модульный монолит

```text
orchestrator/
├── cosmo/
│   ├── domain/             ← Pydantic-модели (8 сущностей)
│   ├── compiler/           ← PlanCompiler + BrickCatalog + BatchDAGExecutor
│   ├── control_plane/      ← RunControlPlane (PG-backed state machine)
│   ├── capability/         ← CapabilityBroker (портовая аллокация по run_id)
│   ├── ledger/             ← EvidenceChain + ArtifactStore + ГОСТ-Акт + SARIF
│   ├── adapters/           ← GiteaForgeAdapter + WoodpeckerExecutionAdapter
│   ├── api/                ← FastAPI routes (9 префиксов: domains, apps, groups, bricks, plans, runs, batches, gates, releases, preferences, sse)
│   └── db/                 ← SQLAlchemy ORM (11 таблиц)
├── tests/
│   └── cosmo/              ← 277 тестов (0 skipped)
└── frontend/src/cosmo/     ← Control Station (MUI) + Inline Editor (Monaco + Tailwind)
```

---

## 4. 8 сущностей доменной модели

### 4.1. Domain (`domain_model.py`)
Верхнеуровневая сущность. Один Domain = один клиент/проект Космопорта.
- `id`, `label`, `forge_binding` (Gitea/Jenkins), `rbac_config`, `quota`
- `ForgeBinding.token_ref` — **VAULT-ссылка**, НЕ реальный токен

### 4.2. Application + AppGraph (`app_graph.py`)
Приложения и библиотеки внутри Domain. Уровни:
- **Level 0** — библиотеки (shared repo, без самостоятельного деплоя)
- **Level 1** — атомарные сервисы (1 app = 1 git repo)
- **Level 2** — композитные подсистемы
- **Level 3** — агрегатные приложения

`AppGraph` связывает Domain → Groups → Applications → RepositoryBindings. Валидирует циклы в иерархии групп.

### 4.3. Group (`app_graph.py`)
Группа/папка приложений с parent/child иерархией. `level ∈ [0..3]`.

### 4.4. PipelineBrick + BrickOverride (`pipeline_brick.py`)
Атомарный шаг пайплайна: SAST, SCA, Build, Deploy, DAST, Autotest, Gate.
- `BrickDefinition` — рантайм-конфиг (image, timeout, inputs/outputs)
- `BrickOverride` — per-domain переопределение

### 4.5. Plan + Batch (`run_model.py`)
Скомпилированный план и группы шагов (batches):
- `Batch` — группа кирпичей одного типа (build, static_scan, deploy, dynamic_test)
- `BatchStatus` — pending → running → passed/failed/blocked

### 4.6. Run (`run_model.py`)
Один запуск пайплайна. 8 состояний:
```text
draft → pending → queued → running → succeeded
                                    → failed
                                    → blocked
                                    → cancelled
```
- `RunTrigger`: scheduled, pre_release, emergency, manual
- Атомарные переходы через `RunControlPlane._transition()`

### 4.7. Gate (`gate_model.py`)
Security Gate — контрольная точка:
- `automatic` — автоматический (не может быть `manual_required`)
- `manual` — требует `decided_by` (человеческое решение)
- `GatePolicy(rules)` — правила по типу находки: block/warn/pass

### 4.8. Release (`release_model.py`)
Релизный пакет — связка прошедших Gate прогонов:
```text
draft → pending_review → approved → deploying → deployed
                        → rejected
                        → rollback
```
- `ReleaseApproval` — история решений (decided_by + signature)
- До 7 статусов: draft, pending_review, approved, rejected, deploying, deployed, rollback

---

## 5. Steel Thread — сквозной сценарий

```text
1. Domain создан (CRUD через /api/v1/domains)
2. AppGraph зарегистрирован (apps + groups + repo_binding)
3. PipelineBricks скомпилированы в Plan (PlanCompiler + BrickCatalog)
4. Run запущен (POST /api/v1/runs → state machine: draft → running → succeeded)
5. Batches выполняются (build → static_scan → deploy → dynamic_test)
6. Gates оцениваются (automatic: pass/block; manual: требует decided_by)
7. Findings записаны в EvidenceLedger (SHA-256 chain)
8. Release сформирован (run_ids прошедших gate → approve → deploy)
9. SSE-поток оповещает Control Station (status_change, batch_complete, gate_decision, finding)
```

**Статистика:** 277 тестов, 0 skipped (6 файлов исключены — требуют httpx/pytest-asyncio/PG/Valkey, не портированы).

---

## 6. Иерархия и контуры

### Безопасность (Security)

- `token_ref` — VAULT/GITEA_TOKEN ссылка, не реальный токен
- Все 56 эндпоинтов без аутентификации (dev/CI). Bearer token placeholder (COS-017)
- `COS-018: Security Leak Check` — 25 тестов (SSE, evidence, compiled plan, API)
- `COS-012: Preferences` — через REST `/api/v1/preferences`, 0 × localStorage

### SSE (Live Monitoring)

```
GET /api/v1/runs/{run_id}/stream

События:
  status_change   — run status transitions
  batch_complete  — batch finished (build/static_scan/deploy/dynamic_test)
  gate_decision   — gate evaluated (pass/block/manual_required)
  finding         — new security finding count

Rate limit: 2 Hz (500ms). Reconnect-safe — snapshot hash.
```

### CSS Style Boundaries (COS-020)

- Tailwind Preflight изолирован внутри `.cosmo-ide-root`
- MUI CssBaseline изолирован внутри `.cosmo-control-station`
- Единые CSS-переменные: `--pk-status-*`, `--pk-bg-*`, `--pk-border-*`
- Meta Light — default для Control Station

### Deep-Linking (COS-024)

Три сценария навигации без перезагрузки страницы:
```text
Gate Inspector → код:        ?surface=ide&repo=payments/api&file=scenarios/auth.wire&line=7
Commit & Run → Live DAG:     ?surface=station&view=runs&run_id=1043
LC Config → редактор:        ?surface=ide&repo=core/config&file=.cosmo/pipeline.yaml
```
`useDeepLink()` — URL-based, без localStorage.

---

## 7. API-контракт

[OpenAPI 3.1 Contract](cosmo-openapi.yaml) — 56 эндпоинтов, 41 схема.

| Префикс | Ресурс | CRUD + экшены |
|---|---|---|
| `/api/v1/domains` | Domain | create, list, get, update, delete, graph |
| `/api/v1/apps` | Application | create, list, get, update, delete, repo-binding |
| `/api/v1/groups` | Group | create, list, get, delete |
| `/api/v1/bricks` | PipelineBrick | create, list, get, update, delete |
| `/api/v1/plans` | PipelinePlan | create, list, get, delete, compile |
| `/api/v1/runs` | Run | create, list, get, update_status, cancel, **SSE stream** |
| `/api/v1/batches` | Batch | create, list, get, update_status |
| `/api/v1/gates` | Gate | create, list, get, update, delete, **decision** |
| `/api/v1/releases` | Release | create, list, get, delete, **submit, approve, reject, deploy** |
| `/api/v1/preferences` | Preferences | get, update (REST, in-memory, без localStorage) |
| `/api/v1/runs/{id}/stream` | SSE | Server-Sent Events, rate-limit 2 Hz |

### Health

```
GET /live    — процесс жив (без проверок зависимостей)
GET /ready   — процесс готов (зависимости проверены)
GET /health  — полный health-контракт
```

---

## 8. Портированные карточки

| COS | Название | Статус |
|---|---|---|
| COS-002 | PlanCompiler + BatchDAGExecutor + BrickCatalog | 30 тестов |
| COS-005 | EvidenceLedger + ArtifactStore + ГОСТ-Акт + SARIF | 44 теста |
| COS-007 | Gitea ForgeAdapter | 17 тестов |
| COS-008 | Woodpecker ExecutionAdapter | 9 тестов |
| COS-009 | tool_ctl (забанен COS-040) | удалён |
| COS-012 | localStorage → REST Preferences | 13 тестов |
| COS-018 | Security Leak Check | 25 тестов |
| COS-020 | CSS Style Boundaries | 15 тестов |
| COS-024 | Deep-Linking | 9 тестов |
| COS-025 | SSE Consumer (useLiveRun) | ~120 строк |
| COS-035 | OpenAPI Contract | 12 тестов |
| COS-036 | Release API | 18 тестов |
| COS-040 | BAN tool_ctl | BAN.md |
| COS-048 | E2E Integration Tests | 50 тестов |

---

## 9. Ссылки

```
Repo:          https://github.com/prettyk-io/prettyk-airlock
OpenAPI:       docs/cosmo-openapi.yaml (2917 строк)
Концепт:       docs/CONCEPT.md
Стек:          docs/STACK.md
Discovery:     docs/DISCOVERY.md
Deployment:    docs/DEPLOYMENT.md
Граф/Релизы:   docs/GRAPH_RELEASE_ARCHITECTURE.md
Persist:       docs/PERSISTENCE.md
Backlog:       docs/BACKLOG.md
Inventory:     docs/INVENTORY.md
Future direction: docs/ARCHITECTURE-DIRECTION.md
Transfer options:  docs/TRANSFER-OPTIONS.md
PO TODO:          docs/PO-TODO.md

Режимы работы: Sanctuary (канон/2FA), Plan (исследование), Dev (исполнение)
Движок:        DeepSeek V4 Pro (тяжёлое) + Gemini 3.7 Flash (discovery/vision)
```
