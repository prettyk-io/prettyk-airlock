# Инвентаризация — что уже есть для Cosmoport 2.0

## Боевое (production-ready в prettyk-dev, доступно через API)

| Компонент | Статус | Где |
|---|---|---|
| Playwright Adapter (55+ методов) | ✅ 8/8 тестов | `orchestrator/adapters/playwright_adapter.py` |
| Smart Locator Engine (11 стратегий) | ✅ боевое | `orchestrator/browser/` |
| Sugar Parser (16 алиасов) | ✅ боевое | `orchestrator/core/` |
| scanner Demon API (:8080) | ✅ боевое | Docker-контейнер |
| Fuzzer Engine | ✅ боевое | `orchestrator/fuzzer/` |
| Discovery Engine | ✅ 41/41 | `orchestrator/utils/discovery_*.py` |
| MethodId + wire-parser | ✅ канон | `orchestrator/models/wired.py` |
| Monaco sugar (10 алиасов) | ✅ 19/19 | `frontend/src/monaco/` |
| Gutter runner [▶] | ✅ 5/5 | `frontend/src/monaco/` |
| PostgreSQL 16 | ✅ боевое | Docker (Buddy) |
| Valkey 8 | ✅ боевое | Docker (Buddy) |
| Better Auth + OpenBao (identity/KMS) | ❌ не реализовано | target: `frontend/src/auth/` (Flash) + BE JWT-verify (Boss/Flash) |
| Docker Compose | ✅ Pure Box + lab | `services/docker-compose.*.yml` (Buddy) |

## Cosmo-специфичное (уже сделано в prettyk-dev)

| Компонент | Кто | Статус | Где |
|---|---|---|---|
| Pydantic: app_graph, domain_model | Luna L1-L2 | ✅ 39 тестов | `orchestrator/cosmo/domain/` |
| Pydantic: pipeline_brick, run_model | Luna L3-L4 | ✅ 39 тестов | `orchestrator/cosmo/domain/` |
| Pydantic: gate_model | Luna L5 | ✅ 39 тестов | `orchestrator/cosmo/domain/` |
| PlanCompiler (Python) | Boss | ✅ prototype | `orchestrator/cosmo/compiler/` |
| Batch DAG Executor | Boss | ✅ prototype | `orchestrator/cosmo/compiler/` |
| Gitea ForgeAdapter | Luna L6 | 🔨 в работе | `orchestrator/cosmo/adapters/` |
| EvidenceChain SHA-256 | Luna | ✅ 14 тестов | `orchestrator/cosmo/ledger/` |
| ГОСТ-Акт (модель + HTML + SARIF) | Luna | ✅ 21 тест | `orchestrator/cosmo/ledger/` |
| Full-cycle integration test | Luna | ✅ 62 теста | `orchestrator/tests/` |
| PipelineDAG (прототип SVG) | Flash COS-F5 | ✅ | `frontend/src/cosmo/` |
| RunControlPanel (прототип) | Flash COS-F6 | ✅ | `frontend/src/cosmo/` |
| GateConfigPanel + AdmissionPanel | Flash COS-F7/F8 | ✅ | `frontend/src/cosmo/` |
| CosmoDashboard | Flash COS-F3 | ✅ | `frontend/src/cosmo/` |
| BrickCatalog | Flash COS-F4 | ✅ | `frontend/src/cosmo/` |
| AppGraphExplorer | Flash COS-F2 | ✅ | `frontend/src/cosmo/` |
| GostActPreview | Flash COS-F9 | ✅ | `frontend/src/cosmo/` |
| MUI Minimal UI template | Flash | ✅ | `frontend/src/design-admin/` |

## Что нужно достроить (P0 — steel thread)

| Слой | Что | Оценка |
|---|---|---|
| Backend Core | SQLAlchemy ORM + Alembic миграции | 4-6h |
| | PlanCompiler (порт TS→Python + DB) | 3-5h |
| | RunControlPlane (state machine в PG) | 5-7h |
| | CapabilityBroker (аллокатор портов) | 3-4h |
| | EvidenceLedger (Merkle chain) | 4-6h |
| Adapters | Gitea ForgeAdapter + тесты | 2-4h |
| | Woodpecker ExecutionAdapter | 3-5h |
| | scanner ctl + Playwright ctl | 2-3h |
| Frontend | FastAPI routes + Pydantic schemas | 5-7h |
| | SSE стриминг (Valkey→Frontend) | 3-4h |
| | Порт фронтенда с localStorage на REST | 3-4h |
| | Control Station shell (MUI + Meta Light) | 4-6h |
| | Control Station core views | 6-8h |
| | Inline Monaco Editor | 4-6h |
| Infra | Docker Compose (Gitea, Woodpecker, MinIO) | 2-3h |
| | Caddy reverse proxy | 1h |
| Tests | Интеграционный smoke-тест | 4-6h |

## Что отложено (Wave 2/3)

- AppGraph hierarchy (Level 0-3, каскадная пересборка) — после реального заказчика
- QWEN Factory (NL→domain) — после steel thread
- Findings Correlation (нормализация 4+ сканеров) — SIEM-продукт, не v1
- Signature Rewind — research, не инженерная
- Jenkins Adapter — опция по спросу
- ГОСТ-Акт авто — при реальном заказчике с регуляторными требованиями