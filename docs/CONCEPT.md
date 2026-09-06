# 🏛️ Cosmoport 2.0 — Полный концепт платформы

> **Repo:** https://github.com/prettyk-io/prettyk-airlock · `D:\prettyk-airlock`  
> **Parent:** `D:\prettyk-dev` (Pure Box + планирование в `sanctuary/cosmoport2/`)  
> **Статус:** ✅ 2FA sealed 28 августа 2026. Gemini & GPT допущены к Алтарю.  
> **Discovery:** `D:\cosmo\` (3 цикла, 80+ таблиц, 97 сервисов, 14 томов ТЗ ЦБ).

---

## 1. Что такое Cosmoport 2.0

**Sovereign Run Control Plane** — суверенная платформа управления жизненным циклом и безопасностью разработки.

### Ключевое отличие от Cosmoport 1.0

| Старый (1.0) | Наш (2.0) |
|---|---|
| Паразитический клей над GitLab CI | Суверенный Control Plane |
| Статусы в Redis (теряются) | Статусы в PostgreSQL (durable) |
| GitLab CI YAML как движок | PlanCompiler + Batch DAG + State Machine |
| Нет Security Gates | Gates в PostgreSQL |
| Нет Evidence Chain | SHA-256 цепочка доказательств |
| 80+ таблиц, 97 сервисов | 8 чистых Pydantic-моделей |
| Ant Design + MobX | MUI Control Station + Inline Monaco Editor |

---

## 2. Архитектурный фундамент

### 2.1. Модульный монолит

```text
orchestrator/
├── cosmo/
│   ├── domain/             ← Pydantic-модели
│   ├── compiler/           ← DAGCompiler + HashCalculator
│   ├── control_plane/      ← StateMachine + RunManager
│   ├── capability/         ← Broker + Scheduler
│   ├── ledger/             ← EvidenceChain + S3Storage
│   ├── adapters/           ← ForgeAdapter + ExecutionAdapter
│   ├── api/                ← FastAPI routes (v1/)
│   └── db/                 ← SQLAlchemy + Alembic
├── adapters/               ← существующие (playwright, scanner, fuzzer)
├── browser/
├── core/
└── utils/
```

### 2.2. Доменная иерархия и 8 сущностей

**Каноническая 4-уровневая иерархия:**
```text
Кластер (Сеть / Инфра-контур: ЗР / ЗТ / ЗПЭ)
  └── КИТС (Бизнес-домен / Группа проектов по смыслу: «Цифровой рубль», «Платежи»)
        └── Проект (Система / Сервисный комплекс: «Платежный хаб», «Антифрод»)
              └── Приложения (с репозиториями, разных уровней):
                    ├── Level 0: Библиотеки / Конфиги (shared repo, lib-auth, без самостоятельного деплоя)
                    ├── Level 1: Атомарные сервисы (1 app = 1 git repo, auth-service, gateway-service)
                    └── Level 2: Композитные подсистемы / Групповые манифесты
```

**8 сущностей вместо 80+ таблиц старого Cosmoport:**
```text
cosmo_domains        ← КИТС (Бизнес-домены / Направления)
cosmo_applications   ← Проекты и Приложения (Level 0-2 с repo_binding)
cosmo_pipelines      ← Описания пайплайнов (граф шагов)
cosmo_runs           ← Прогоны: статус, compiled_plan, inputs_hash
cosmo_batches        ← Пачки шагов в прогоне (Build / Static / Deploy / Dynamic)
cosmo_findings       ← Находки (связаны с run_id)
cosmo_evidence_ledger ← Неизменяемый журнал улик (SHA-256)
cosmo_audit_events   ← Аудит-события (кто, когда, что сделал)
```

### 2.3. Графовая модель связей и релизов (BEMR/BEWS Synthesis)

Вместо старой жесткой вложенности («группирующее пространство 2 уровня → 2 → 1 → 0») Cosmoport 2.0 использует **типизированный ориентированный граф (DAG)**:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               App & Release Graph (DAG)                                │
│                                                                                        │
│   [ Lib: common-auth (L0) ] ──────── uses_lib ────────┐                               │
│                                                       ▼                                │
│   [ App: payment-api (L1) ] ────── runtime_link ──> [ App: gateway (L1) ]              │
│               │                                           │                            │
│           contains                                    contains                         │
│               ▼                                           ▼                            │
│   ┌──────────────────────────────────────────────────────────────┐                     │
│   │   Subsystem / Composite Project: Payment Hub (Level 2)       │                     │
│   │   • Release Snapshot: v2.4.0 (SHA pins + DAG dependencies)   │                     │
│   │   • Release Type: "Hotfix" | "Standard" | "Quarterly"        │                     │
│   │   • Selective Rebuild: [x] Auto-rebuild changed dependencies │                     │
│   └──────────────────────────────────────────────────────────────┘                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

**Ключевые принципы графовой модели:**
1. **Типизированные связи:** `contains` (включение в подсистему), `uses_lib` (зависимость от L0 библиотеки/конфига), `depends_on` (порядок сборки/деплоя), `runtime_link` (сетевая интеграция).
2. **Типы релизов (BEMR):** каждый тип релиза (`Hotfix`, `Обычный`, `Квартальный`) имеет собственный жизненный цикл и набор обязательных Security Gates. После использования тип релиза неизменяем.
3. **Релиз как неизменяемый снимок графа:** Релиз L2/L1 — это зафиксированный JSON-снимок состояния нод (git commit SHA, теги L0/L1 компонентов, хеши плана и правил гейтов).
4. **Управляемый каскад пересборки:** опция селективного перезапуска сборок дочерних зависимостей при сборке композитного релиза («Перезапускать сборку»).
5. **Экспорт / Импорт конфигурации:** поддержка сериализации состава релиза в чистый JSON-манифест для переноса между контурами (ЗР → ЗТ → ЗПЭ).

### 2.4. Steel Thread

```text
Cluster/Env → КИТС → Проект → Приложение → Pipeline → Compile → Run → Batch → Gate → Evidence
```

---

## 3. Технологический стек

| Слой | Выбор |
|---|---|
| Backend | Python/FastAPI/Pydantic/SQLAlchemy + PostgreSQL 16 + Valkey 8 |
| Frontend | React 18 + TS + Vite + **MUI Minimal UI + MUI X Data Grid · Meta Light (белая) default, тёмная — опционально** |
| Pipeline Graph | @xyflow/react (MIT, бесплатный) + dagre |
| Inline Code Editor | Monaco Editor + Tailwind (только внутри Control Station, по deep-link из Gate/Finding) |
| Auth/KMS | Better Auth + OpenBao |

---

## 4. Control Station — единая поверхность оператора

Cosmoport 2.0 имеет **одну поверхность** — Control Station. Это рабочее место оператора ИБ и релиз-менеджера. **Meta Light (белая) — default.** Тёмная тема — опциональный переключатель.

- **Overview** — активные runs, gates, failed deployments
- **Applications** — иерархия Domain→Project→App, MUI X Data Grid с Tree Data
- **Application detail** — вкладки: Builds, Deployments, Releases, Pipelines, LC, Members, Evidence
- **Pipeline Studio** — DAG-граф на @xyflow/react + dagre
- **Run Control** — запуск, cancel, retry, live SSE
- **Security Gates** — ручной approve/reject
- **Findings / Evidence** — severity, chain, SHA-256
- **Releases / Transfers** — dev→test→prod, transfer status
- **Catalog** — bricks, adapters, capabilities, runtimes
- **Graph Topology** — визуальный редактор графа связей L0/L1/L2

## 5. Inline Code Editor (не отдельный продукт)

Встроенный Monaco-редактор открывается **только по deep-link** из Gate Inspector или Finding. Не является отдельной поверхностью, не имеет собственной навигации, не показывается на лендинге. Используется для быстрой правки `.yaml`/`.wire`/`.json` конфигов:

- Открывается из Security Gate: «Исправить в редакторе» → Monaco на нужной строке
- Diff viewer перед коммитом
- Commit & Push / Commit & Run
- НЕ замена VS Code / JetBrains. НЕ отдельный продукт. НЕ на лендинг.

## 7. Deep-Linking

- Gate Inspector → строка кода в редакторе
- Commit & Run → Live DAG в Control Station
- LC Config → JSON/YAML редактор

## 8. Профили поставки

| Pure Box | Enterprise |
|---|---|
| 1 Docker Compose | PG Cluster |
| Локальный Gitea + Woodpecker | Внешние Gitea/GitLab |
| Локальный MinIO | MinIO/Ceph Cluster |
| Airgap | Distributed Workers |

## 9. Что НЕ делаем

- ❌ Не пишем полноценную IDE / замену VS Code (Monaco-редактор только для лайтовых правок по deep-link)
- ❌ Не клонируем старый Rails-портал
- ❌ Не покупаем React Flow Pro
- ❌ Не смешиваем Tailwind и MUI внутри одной поверхности
- ❌ Не делаем Cosmoport тёмным по умолчанию (Meta Light — default, тёмная — опционально)
- ❌ Не пишем свой Git-сервер (Gitea через адаптер)
- ❌ Не тащим RabbitMQ/Kafka/Celery
- ❌ Не делаем микросервисы
