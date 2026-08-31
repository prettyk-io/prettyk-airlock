# Что передаём из Pure Box в Cosmoport 2.0

> **Для:** Cosmo · **Принцип:** Cosmo НЕ импортирует Pure Box. Только REST/Webhook/SSE.  
> Ниже — что копируем как исходники, что подключаем как сервисы, что Buddy должен собрать с нуля.

---

## 1. Копируем как ИСХОДНИКИ (портировать в `D:\prettyk-control-plane`)

### Backend (`orchestrator/cosmo/`)

| Что | Где в prettyk-dev | Кто делал | Статус | Куда в cosmoport2 |
|---|---|---|---|---|
| Pydantic: app_graph, domain_model | `orchestrator/cosmo/domain/` | Luna L1-L2 | ✅ 39 тестов | `orchestrator/cosmo/domain/` |
| Pydantic: pipeline_brick, run_model | `orchestrator/cosmo/domain/` | Luna L3-L4 | ✅ 39 тестов | `orchestrator/cosmo/domain/` |
| Pydantic: gate_model | `orchestrator/cosmo/domain/` | Luna L5 | ✅ 39 тестов | `orchestrator/cosmo/domain/` |
| PlanCompiler Python | `orchestrator/cosmo/compiler/` | Boss | ✅ prototype | `orchestrator/cosmo/compiler/` |
| Batch DAG Executor | `orchestrator/cosmo/compiler/` | Boss | ✅ prototype | `orchestrator/cosmo/compiler/` |
| EvidenceChain SHA-256 | `orchestrator/cosmo/ledger/` | Luna | ✅ 14 тестов | `orchestrator/cosmo/ledger/` |
| ГОСТ-Акт (модель + HTML + SARIF) | `orchestrator/cosmo/ledger/` | Luna | ✅ 21 тест | `orchestrator/cosmo/ledger/` |
| Full-cycle integration test | `orchestrator/tests/` | Luna | ✅ 62 теста | `orchestrator/tests/` |
| Gitea ForgeAdapter | `orchestrator/cosmo/adapters/` | Luna L6 | 🔨 в работе | `orchestrator/cosmo/adapters/` |

### Frontend (прототипы Flash — портировать в `frontend/src/cosmo/`)

| Что | Где в prettyk-dev | Кто | Куда в cosmoport2 |
|---|---|---|---|
| PipelineDAG + DAG-виз | `frontend/src/cosmo/` | Flash COS-F5 | `frontend/src/cosmo/control-station/` |
| RunControlPanel | `frontend/src/cosmo/` | Flash COS-F6 | `frontend/src/cosmo/control-station/` |
| GateConfigPanel + AdmissionPanel | `frontend/src/cosmo/` | Flash COS-F7/F8 | `frontend/src/cosmo/control-station/` |
| CosmoDashboard | `frontend/src/cosmo/` | Flash COS-F3 | `frontend/src/cosmo/control-station/` |
| GostActPreview | `frontend/src/cosmo/` | Flash COS-F9 | `frontend/src/cosmo/control-station/` |
| BrickCatalog | `frontend/src/cosmo/` | Flash COS-F4 | `frontend/src/cosmo/control-station/` |
| AppGraphExplorer | `frontend/src/cosmo/` | Flash COS-F2 | `frontend/src/cosmo/control-station/` |
| CosmoLadderFields | `frontend/src/cosmo/` | Flash COS-F1 | `frontend/src/cosmo/control-station/` |

### Shared между Pure Box и Cosmo (лицензия, тема, стили)

| Что | Откуда | Примечание |
|---|---|---|
| MUI Minimal UI template | `frontend/src/design-admin/` | Лицензия общая с Pure Box Admin. Копируем тему, палитры, провайдер. |
| `design-admin/` showcase | `frontend/src/design-admin/` | Референс-галерея компонентов |
| Frontend-зависимости | `frontend/package.json` | MUI, Data Grid, xyflow, Monaco, xterm — те же версии |

---

## 2. НЕ копируем — подключаем как СЕРВИСЫ (REST/Webhook/SSE)

Эти компоненты остаются в Pure Box. Cosmo вызывает их через API:

| Сервис | Где в Pure Box | Как Cosmo подключается |
|---|---|---|
| Playwright Adapter (55+ методов) | `orchestrator/adapters/playwright_adapter.py` | CapabilityBroker → Playwright ctl (COS-009) |
| scanner Demon API | Docker, порт :8080 | CapabilityBroker → scanner ctl (COS-009) |
| Fuzzer Engine | `orchestrator/fuzzer/` | CapabilityBroker → fuzzer ctl |
| Discovery Engine | `orchestrator/utils/discovery_*.py` | REST API → discovery sessions |
| Smart Locator Engine (11 стратегий) | `orchestrator/browser/` | Внутри Playwright adapter |
| Sugar Parser (16 алиасов) | `orchestrator/core/` | Через DSL-контракт |
| MethodId + wire-parser | `orchestrator/models/wired.py` | Канонический контракт — читать, не копировать |
| Live :8767 | `orchestrator/utils/live_server.py` | Временный compatibility facade → заменить на Cosmo API/SSE |
| Allure reports | `services/allure3-secops/` | URL/link из Cosmo Control Station |

### Контракт (как Cosmo вызывает Pure Box)

```text
Cosmo → REST API → Pure Box scanner demon (:8080)
Cosmo → REST API → Pure Box Playwright (через CapabilityBroker)
Cosmo → REST API → Pure Box Fuzzer
Cosmo → REST API → Pure Box Discovery engine
Cosmo → Webhook ← Pure Box (callback о завершении scan/run)
Cosmo ← SSE ← Pure Box (live telemetry)
```

Запрещено: `from orchestrator.adapters.playwright_adapter import ...` — такого в коде Cosmo быть не должно.

---

## 3. Инфраструктура — Buddy собирает с нуля в prettyk-control-plane

| Что | Кто | Что делать |
|---|---|---|
| Docker Compose | Buddy | Один стек: Gitea :3000, Woodpecker :8000, MinIO :9000, Cosmo API :8100 |
| PostgreSQL 16 | Buddy | Отдельный инстанс для Cosmo (не общий с Pure Box) |
| Valkey 8 | Buddy | Отдельный инстанс, Streams + PubSub |
| MinIO | Buddy | S3-совместимое хранилище артефактов |
| Caddy | Buddy | Reverse proxy: Frontend :5173, API :8100, Gitea :3000, MinIO :9000 |
| Better Auth + OpenBao | Flash | Отдельный auth/KMS для Cosmo |
| Health endpoints | Boss | /live, /ready, /health |

### Что Buddy HE делает с нуля — использует готовые паттерны из Pure Box:

| Паттерн | Откуда брать |
|---|---|
| Docker Compose структура | `services/docker-compose.infra.yml` (референс) |
| PostgreSQL настройка | `services/docker-compose.infra.yml` |
| Valkey настройка | `services/docker-compose.infra.yml` |
| MinIO настройка | `services/docker-compose.minio.yml` |
| Health check паттерны | `orchestrator/tools/infra_health.py` |
| Bundle/sign/verify (airgap) | `services/scripts/bundle-v2.ps1` (референс) |

---

## 4. Что НЕ передаём (остаётся ТОЛЬКО в Pure Box)

- ❌ `orchestrator/adapters/` — playwright, selenium, scanner (вызываются через API)
- ❌ `orchestrator/browser/` — browser runtime (вызывается через API)
- ❌ `orchestrator/fuzzer/` — fuzzer engine (вызывается через API)
- ❌ `orchestrator/core/` — DSL core, wire-parser (контракт, не код)
- ❌ `orchestrator/utils/live_server.py` — Live :8767 (заменяется на Cosmo Control Plane)
- ❌ `frontend/src/admin/` — Pure Box Admin shell
- ❌ `frontend/src/monaco/` — Editor (портируется как Inline Monaco Editor внутри Control Station, не как отдельный продукт)
- ❌ `frontend/src/shell/` — Pure Box shell
- ❌ `frontend/src/results/` — Pure Box results
- ❌ `frontend/src/studio/` — Pure Box Studio
- ❌ `services/allure*` — отчёты (Cosmo только ссылается)
- ❌ `sanctuary/pure/` — каноны Pure Box (читать, не копировать)
- ❌ `docs/backlog.md` — основной бэклог (у Cosmo свой)

---

## 5. Итого: что уже лежит в D:\prettyk-control-plane

```text
D:\prettyk-control-plane\
├── AGENTS.md                    ← ✅ готово
├── .opencode\agent\             ← ✅ готово (cosmo/dev/plan)
├── docs\                        ← ✅ готово (CONCEPT, BACKLOG, DISCOVERY, INVENTORY, STACK, PERSISTENCE)
├── .git\                        ← ✅ готово
│
├── orchestrator\cosmo\          ← ⬜ портировать п.1 (Pydantic-модели, PlanCompiler, EvidenceChain, GiteaAdapter)
├── orchestrator\tests\          ← ⬜ портировать integration test
├── frontend\src\cosmo\          ← ⬜ портировать прототипы Flash
├── frontend\package.json        ← ⬜ собрать (MUI, Data Grid, xyflow, Monaco, xterm)
├── services\docker-compose.yml  ← ⬜ Buddy собирает
└── services\Caddyfile           ← ⬜ Buddy собирает
```

---

## 6. Порядок передачи (что делать Cosmo)

1. **Boss/Luna: скопировать backend.** Pydantic-модели → `orchestrator/cosmo/domain/`, PlanCompiler → `orchestrator/cosmo/compiler/`, EvidenceChain → `orchestrator/cosmo/ledger/`, GiteaAdapter → `orchestrator/cosmo/adapters/`. Тесты → `orchestrator/tests/`.

2. **Flash: скопировать frontend-прототипы.** Все COS-F* компоненты → `frontend/src/cosmo/control-station/`.

3. **Flash: собрать package.json.** MUI, Data Grid, xyflow, Monaco, xterm — те же версии что в prettyk-dev.

4. **Buddy: Docker Compose.** Gitea + Woodpecker + MinIO + Cosmo API. Отдельные инстансы PG и Valkey. Caddy reverse proxy.

5. **Boss: Health endpoints.** /live, /ready, /health для Cosmo API.

**Не ждать «большой миграции».** Копировать по мере Фазы 1. Сначала бэкенд (COS-001..COS-005), потом адаптеры (COS-007..COS-009), потом фронтенд (COS-020..COS-025).
