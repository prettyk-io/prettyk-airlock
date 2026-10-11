# Индекс файлов Cosmoport 2.0 (INDEX)

> Вопрос документа: **В каком файле репозитория искать ответ на конкретный инженерный или архитектурный вопрос?**

---

## 1. Документация и каноны (`docs/`)

| Файл | Вопрос, на который отвечает документ |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | Кто такой Cosmo, каковы границы ответственности, стек и правила диспетча? |
| [`PROGRESS.md`](../PROGRESS.md) | Каково текущее состояние репозитория, последние действия и следующие шаги? |
| [`docs/ONBOARDING.md`](ONBOARDING.md) | Как новому агенту или инженеру погрузиться в контекст проекта по шагам 1–7? |
| [`docs/MAP.md`](MAP.md) | Какова общая схема сервисов, портов, контрактов и Steel Thread жизненного цикла? |
| [`docs/SYSTEM-OVERVIEW.md`](SYSTEM-OVERVIEW.md) | Какие сущности есть в Airlock, где они живут, чем исполняются, какие зависимости и технологии используются на проекте? |
| [`docs/INDEX.md`](INDEX.md) | В каком файле кодовой базы или документации искать нужный компонент? |
| [`docs/CONCEPT.md`](CONCEPT.md) | В чём концепция Cosmoport 2.0 как Sovereign Control Plane и отличие от 1.0? |
| [`docs/BACKLOG.md`](BACKLOG.md) | Какие карточки задач открыты, находятся в работе и уже приняты PO? |
| [`docs/STACK.md`](STACK.md) | Какой технологический стек утверждён платформой и что категорически запрещено? |
| [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) | Как развернуть сервисы, настроить Caddy/Nginx edge, переменные окружения и порты? |
| [`docs/PERSISTENCE.md`](PERSISTENCE.md) | Как устроены уровни хранения (PostgreSQL, MinIO, Valkey, OpenBao/Vault)? |
| [`docs/DISCOVERY.md`](DISCOVERY.md) | Что было исследовано в коде старого портала 1.0 и почему отказались от Redis? |
| [`docs/PO-TODO.md`](PO-TODO.md) | Какие вопросы и архитектурные решения находятся на согласовании со смежниками? |

---

## 2. Бэкенд и ядро (`orchestrator/cosmo/`)

| Директория / Файл | Вопрос, на который отвечает код |
|---|---|
| `orchestrator/cosmo/domain/` | Где описаны чистые Pydantic v2 модели 8 ключевых доменных сущностей? |
| `orchestrator/cosmo/compiler/` | Как `.cosmo/pipeline.yaml` компилируется в детерминированный граф шагов и хэш? |
| `orchestrator/cosmo/control_plane/` | Где реализована машина состояний прогонов (RunManager) и DAG-батчей? |
| `orchestrator/cosmo/ledger/` | Как формируется неизменяемая SHA-256 цепочка улик и ГОСТ-акт? |
| `orchestrator/cosmo/adapters/forge_gitea.py` | Как устроен адаптер к Gitea (привязка репозитория, вебхуки, чтение веток)? |
| `orchestrator/cosmo/adapters/execution_woodpecker.py` | Как устроен адаптер к Woodpecker (запуск шагов в контейнерах, сбор логов)? |
| `orchestrator/cosmo/domain/artifact_record.py` | Где определена durable-запись артефакта (digest + manifest + sbom_ref, canonical_ref)? |
| `orchestrator/cosmo/ledger/artifact_record.py` | Как digest артефакта durable-пишется и читается из PG (latest wins, restart-survival)? |
| `orchestrator/cosmo/domain/artifact_sbom.py` + `ledger/artifact_sbom.py` | Как снимается и якорится SBOM поверх образа (COS-167, sbom_ref → Evidence Ledger)? |
| `orchestrator/cosmo/domain/artifact_scan.py` + `ledger/artifact_scan_gate.py` | Как триви-скан образа аттестуется в gate decision=pass/block (COS-168, deploy-blocker)? |
| `orchestrator/cosmo/domain/promotion.py` + `ledger/promotion_ledger.py` | Как упаковывается и лендится transfer-пакет promotion ЗР→ЗТ→ЗПЭ (COS-169/170, digest-matching + Evidence per-zone)? |
| `orchestrator/cosmo/adapters/runtime_docker.py` | Как происходит реальный materialize deploy (pull по digest + run + healthcheck)? |
| `orchestrator/cosmo/db/models.py` | Где определены SQLAlchemy 2.0 Async ORM-модели 35 таблиц PostgreSQL? |
| `orchestrator/cosmo/api/main.py` | Где конфигурируется FastAPI приложение, middleware и подключение роутов? |
| `orchestrator/cosmo/api/deps.py` | Как валидируются JWT-токены, сессионные куки и роли в RBAC-системе? |
| `orchestrator/cosmo/api/routes/` | Где находятся обработчики HTTP-маршрутов (`/domains`, `/runs`, `/gates`, `/releases`)? |
| `orchestrator/cosmo/api/sse_backlog.py` | Как события прогона сохраняются в Valkey Stream для надежного реконнекта SSE? |

---

## 3. Фронтенд Dual-Surface (`frontend/src/`)

| Директория / Файл | Вопрос, на который отвечает код |
|---|---|
| `frontend/src/App.tsx` | Как устроен корень приложения и маршрутизация между Surface A и Surface B? |
| `frontend/src/cosmo/station/` | Где находятся компоненты Surface A (Control Station на MUI Meta Light)? |
| `frontend/src/cosmo/station/views/ReleaseReadiness.tsx` | Где отображается статус готовности релизов, гейты качества и Evidence? |
| `frontend/src/cosmo/ide/` | Где находятся компоненты Surface B (Web IDE на Tailwind v4 и Monaco Editor)? |
| `frontend/src/cosmo/shared/useLiveDomain.ts` | Как работает SSE-подписка на события домена с автоматической дочиткой бэклога? |
| `frontend/src/cosmo/api.ts` | Где описаны функции обращений к бэкенду с типизацией запросов и ответов? |
| `frontend/src/styles/` | Где определены базовые CSS-переменные статусов и стилевые границы поверхностей? |

---

## 4. Инфраструктура и скрипты автоматизации

| Файл | Вопрос, на который отвечает компонент |
|---|---|
| `docker-compose.yml` | Как поднять полный локальный стенд всех сервисов и баз данных? |
| `services/caddy/Caddyfile` | Как настроены правила терминирования TLS и обратного проксирования в Caddy? |
| `services/scripts/suite_gate.ps1` | Как запустить полный регрессионный сьют тестов бэкенда и фронтенда одной командой? |
| `services/scripts/cleanup_scratch_pg.py` | Как безопасно очистить временные тестовые базы данных PostgreSQL? |
