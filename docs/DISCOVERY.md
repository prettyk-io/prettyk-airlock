# Discovery — что выжали из старого Cosmoport

> **Исходники:** `D:\cosmo\` (3 цикла discovery, Keeper + Gemini, 27 авг 2026).  
> **Индекс:** `D:\prettyk-dev\sanctuary\cosmoport2\discovery\index.md`

---

## Ключевые находки (читать перед работой)

### 1. Масштаб старого Cosmoport
- **80+ таблиц** PostgreSQL, **97 сервисных классов** Ruby, **537 строк routes.rb**
- **12 типов интеграций** (GitLab, Jenkins, OpenShift, Confluence, Jira, Artifactory, Vault, Nexus, внешний SARIF-агрегатор ❌ не наш, etc.)
- **65+ core service codes** (JenkinsService, GitlabService, SonarQubeService, etc.)
- **15 типов приложений (kind'ов):** ppod, allocated, pis, legacy, service_subsystem, service, ehd, epvv_po/spo, universal_app, library, report_templates, configuration_templates, universal_lib, data_transfer_lib
- **15 статусов проектов:** draft→developing→...→active→...→archived (7 активных + 5 архивных + 3 прерывания)

### 2. Что мы из этого сделали
- **80+ таблиц → 8 чистых Pydantic-моделей**
- Старые статусные машины → референс для нашего RunControlPlane
- Старые эндпоинты → замаплены на наши `/api/v1/...`
- 12 типов интеграций → адаптерный паттерн (ForgeAdapter + ExecutionAdapter)

### 3. Ключевые расхождения (спецификация vs код)

| # | Что | ТЗ | Код | ГАП |
|---|---|---|---|---|
| 1 | Роли | 11 ролей (ИТ-лидер, АИБ, НШР...) | 4 роли (admin, manager, operator, guest) | RBAC плоский |
| 2 | Уровни | 4 уровня + Grouping | Level 0/1, нет Level 3 | Нет ограничения "1 grouping" |
| 3 | SAST | 9 инструментов | 9 в GitLab CI, только 2 в тестах | 7 инструментов без тестов |
| 4 | Трансфер релизов | Полная подсистема | Есть в коде | **0 тестов (CRITICAL GAP)** |
| 5 | CI тесты | — | rspec, rubocop установлены | **0 тестов в CI pipeline** |
| 6 | ГОСТ/нормативы | 5 ГОСТов, 4 положения ЦБ | **НЕТ в коде** | Зона PrettyK |
| 7 | Kafka/PUNS | 22 события | Реализовано частично | **0 тестов** |

### 4. Что Cosmoport 1.0 делает хорошо (забираем как референс)
- Полноценная N:M иерархия проектов с self-reference связями
- Межзонный трансфер релизов (dev→test→prod) через СОД/MZP с полным аудитом
- Гибкая LC-конфигурация (14+ шагов, версионирование, per-project override)
- Каталог пайплайнов и рантаймов
- Интеграция с 12+ внешними сервисами через единый паттерн

### 5. Что Cosmoport 1.0 НЕ делает (наша зона)
- Нет Plan Compiler / Batch DAG
- Нет Security Gates как durable entity
- Нет Evidence Chain
- Нет браузерного рантайма (Playwright)
- Нет фаззера по словарям
- Нет ГОСТ-Акта
- Нет Domain RBAC
- Нет multi-Gitea per domain
- Нет нормативной базы в коде

---

## Файлы discovery (читать при необходимости)

| Файл | Содержание |
|---|---|
| `D:\cosmo\discovery-final-deliverable.md` | **Сводка — читать первым** |
| `D:\cosmo\discovery-cycle-1-tz-docs-api.md` | ТЗ, документы, API surface |
| `D:\cosmo\discovery-cycle-2-codebase-db-services.md` | Кодовая база, БД, сервисы |
| `D:\cosmo\discovery-cycle-3-specs-docs.md` | Тесты, спеки, CI |
| `D:\cosmo\cosmo-dump.sql` | DDL-схема PostgreSQL |

---

## Конвертированные ТЗ (14 документов)

`D:\cosmo\documentation\_converted\`:
- `10_rukovodstvo_razrabotchika.md` (1.5 МБ) — главный документ
- BEWS/BELS v2.13 — Уровни рабочих пространств (4 уровня + Grouping)
- IN v2.10 — Интеграции (9 сервисов, внешний SARIF-агрегатор ❌ не наш — было в старом Cosmoport, у нас свой SARIF-экспортёр)
- BEMR v3.8 — Схема управления релизами
- LCBE v2.11 — Жизненный цикл бизнес-сущностей (14 шагов ЗР)
- LCZD v3.3 — Зоны и трансфер
- ADR v2.2 — Квоты (9 типов)
- NOT v2.2 — Уведомления (22 события)
- RM v3.2 — Ролевая модель (11 ролей)

---

## API-маппинг (старый → новый)

| Старый Cosmoport | Наш Cosmo 2.0 |
|---|---|
| `GET /api/projects` | `GET /api/v1/applications` |
| `GET /api/projects/:id/builds` | `GET /api/v1/applications/:id/builds` |
| `POST /api/projects/:id/builds` | `POST /api/v1/applications/:id/builds` |
| `GET /api/projects/:id/releases` | `GET /api/v1/applications/:id/releases` |
| `PUT /api/releases/:id/status` | `PUT /api/v1/releases/:id/status` |
| `GET /api/application_pipelines` | `GET /api/v1/catalog/pipelines` |
| `GET /api/application_runtimes` | `GET /api/v1/catalog/runtimes` |
| `POST /api/oauth` | `POST /api/v1/auth/oidc` |

## Статусы (референс)

| Сущность | Статусы |
|---|---|
| Project | draft→developing→active→inactive→archived |
| Build | pending→running→success/failed/aborted |
| Deployment | pending→running→success→failed→deleted |
| Release (dev) | draft→developing→developed |
| Release (test) | transferred_to_test→testing→tested/testing_failed |
| Release (prod) | transferred_to_prod→production→archived |
| Integration | pending→running→success/failed/not_active |
| Transfer | not_transferred→processing→building_package→transferring→success/failed |