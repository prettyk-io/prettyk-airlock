# Cosmoport 2.0 — полноценное развёртывание контуров

> **Статус:** рабочий deployment-plan для ревью Gemini. Это план сборки и ввода
> Cosmoport 2.0, а не утверждение, что все перечисленные компоненты уже готовы.
>
> **Источники:** `CONCEPT.md`, `STACK.md`, `PERSISTENCE.md`, `TRANSFER.md`,
> `BACKLOG.md`, `INVENTORY.md`, а также `D:\prettyk-dev\services\` и
> `D:\prettyk-dev\sanctuary\cosmoport2\`.

---

## 1. Назначение документа

Документ фиксирует, как из уже существующих наработок Pure Box собрать
самостоятельные контуры Cosmoport 2.0:

- что переносится в репозиторий `D:\prettyk-airlock` как исходный код;
- что остаётся в Pure Box и вызывается только по внешнему контракту;
- какие инфраструктурные компоненты Buddy собирает заново;
- как разворачиваются локальный, интеграционный, enterprise и airgap-контуры;
- как Cosmo общается с отдельным Pure Box runtime;
- как запускаются и изолируются security-сессии;
- какие health, backup, recovery и acceptance gates обязательны.

Это **не** план копирования всего `prettyk-dev`. Cosmoport — отдельный продукт и
отдельный runtime-контур. Из Pure Box берутся только разрешённые исходники,
контракты и проверенные инфраструктурные паттерны.

---

## 2. Непересматриваемые решения

### 2.1. Граница продуктов

```text
Cosmoport 2.0
  ├── владеет доменами, приложениями, pipeline-планами, runs, batches
  ├── владеет gates, findings, evidence metadata и аудитом
  ├── владеет Control Station и Inline Editor
  └── вызывает Pure Box через REST / Webhook / SSE

Pure Box
  ├── владеет Playwright runtime
  ├── владеет scanner Demon
  ├── владеет Fuzzer и Discovery Engine
  ├── владеет Live compatibility runtime на переходном этапе
  └── исполняет security-capabilities по внешнему контракту
```

В Cosmoport запрещены:

- импорты из внутренних модулей Pure Box;
- прямые вызовы `live_server.py` и порта `:8767`;
- общая база данных с Pure Box;
- прямые вызовы внутренних модулей scanner, browser или fuzzer;
- превращение Cosmo в копию Pure Box;
- перенос Pure Box Admin, Pure Box shell, Allure и внутреннего Studio.

### 2.2. Хранилища Cosmo

Для всех Cosmo-контуров фиксируется одна схема:

```text
PostgreSQL 16+ — единственный durable Source of Truth
Valkey 8      — queue, Streams, PubSub, cache и live transport
MinIO / S3    — большие неизменяемые артефакты
OpenBao       — секреты и ключи
```

Cosmo имеет **отдельные инстансы PostgreSQL, Valkey и MinIO**. Они не являются
shared-инфраструктурой Pure Box. В одновузловом профиле несколько логических
баз Gitea/Woodpecker могут находиться на том же выделенном PostgreSQL-инстансе,
но сам инстанс принадлежит Cosmo и не используется Pure Box.

### 2.3. Два уровня исполнения

```text
Cosmo Batch ──> ExecutionAdapter ──> Woodpecker Job
Cosmo Run   ──> CapabilityBroker ──> Pure Box security session
```

`Batch` не равен `Job`. Cosmo управляет смыслом жизненного цикла, а внешний
execution engine исполняет отдельные jobs. Security-раннеры требуют отдельной
изоляции, привязки к `run_id`, health check и гарантированного teardown.

---

## 3. Инвентарь передачи

### 3.1. Переносится в `D:\prettyk-airlock` как исходный код

Исходники портируются и становятся частью Cosmoport. После переноса они не
должны импортировать Pure Box и не должны тянуть его внутренние зависимости.

| Источник в Pure Box | Назначение в Cosmoport 2.0 | Владелец |
|---|---|---|
| `orchestrator/cosmo/domain/` — Pydantic app/domain graph | `orchestrator/cosmo/domain/` | Luna |
| `orchestrator/cosmo/domain/` — pipeline brick/run/gate models | `orchestrator/cosmo/domain/` | Luna |
| `orchestrator/cosmo/compiler/` — PlanCompiler prototype | `orchestrator/cosmo/compiler/` | Boss |
| `orchestrator/cosmo/compiler/` — Batch DAG Executor prototype | `orchestrator/cosmo/compiler/` | Boss |
| `orchestrator/cosmo/ledger/` — EvidenceChain | `orchestrator/cosmo/ledger/` | Luna/Boss |
| `orchestrator/cosmo/ledger/` — ГОСТ-Акт model/HTML/SARIF | `orchestrator/cosmo/ledger/` | Luna |
| `orchestrator/cosmo/adapters/` — Gitea ForgeAdapter | `orchestrator/cosmo/adapters/` | Luna |
| `orchestrator/tests/` — Cosmo integration tests | `orchestrator/tests/` | Luna |
| `frontend/src/cosmo/` — все COS-F* prototypes | `frontend/src/cosmo/control-station/` | Flash |
| `frontend/src/design-admin/` — MUI Minimal UI theme | Control Station theme | Flash |
| `frontend/package.json` — согласованные frontend-версии | Cosmo frontend package | Flash |

Отдельно: Inline Monaco Editor — встроенный редактор внутри Control Station, открывается только по deep-link.
кода. Это не перенос Pure Box shell, Admin, Studio или `frontend/src/monaco/`
целиком. Inline Editor реализован внутри Control Station на Tailwind/Monaco, не отдельная поверхность.

### 3.2. Не переносится: вызывается через API

Эти компоненты остаются в Pure Box и предоставляются как capability-сервисы:

| Компонент Pure Box | Вызов из Cosmo | Контракт |
|---|---|---|
| Playwright Adapter | CapabilityBroker → Playwright ctl | REST + callback/SSE |
| scanner Demon | CapabilityBroker → scanner ctl | REST API |
| Fuzzer Engine | CapabilityBroker → fuzzer ctl | REST + события |
| Discovery Engine | Cosmo API → discovery session | REST |
| Smart Locator Engine | внутри Playwright runtime | через Playwright ctl |
| Sugar Parser / wire-parser | DSL contract | typed payload, не внутренний import |
| Live `:8767` | временная совместимость | постепенно заменяется Cosmo API/SSE |
| Allure | ссылка на внешний отчёт | URL/link, не перенос сервиса |

Канонический поток интеграции:

```text
Cosmo → REST → Pure Box capability endpoint
Cosmo ← Webhook ← Pure Box завершил операцию
Cosmo ← SSE ← Pure Box live telemetry
```

Перед реализацией adapters необходимо зафиксировать версии payload, correlation
ID, `run_id`, auth headers, retry semantics и idempotency key. Нельзя подменять
этот контракт локальным Python import.

### 3.3. Никогда не передаётся

Остаются только в Pure Box:

```text
orchestrator/adapters/     browser/       fuzzer/       core/
live_server.py              frontend/src/admin/
frontend/src/shell/         frontend/src/results/
frontend/src/studio/        services/allure*
sanctuary/pure/             CBR-specific пакет
```

Cosmo читает каноны Pure Box, но не копирует их в свой runtime.

---

## 4. Целевая топология Cosmo

### 4.1. Полный поток

```text
                              оператор / инженер
                                      │
                                      ▼
                              Caddy :443
                                      │
                   ┌──────────────────┼──────────────────┐
                   ▼                  ▼                  ▼
             Frontend             Cosmo API           Forge UI/API
         Control Station +          FastAPI :8100        Gitea :3000
         Inline Editor                   │                  │
                                       │                  ▼
                                       │           Woodpecker :8000
                                       │                  │
              ┌────────────────────────┼──────────────────┘
              ▼                        ▼
       Cosmo PostgreSQL          Cosmo Valkey
       durable entities         queue / PubSub / SSE
       state / audit             ephemeral transport
              │
              ▼
       Cosmo MinIO / S3
       evidence / reports / traces / build artifacts
              │
              ▼
       OpenBao
       secrets / signing / credentials

Cosmo API ── REST/Webhook/SSE ──> отдельный Pure Box runtime
                                  ├── Playwright
                                  ├── scanner Demon
                                  ├── Fuzzer
                                  └── Discovery
```

### 4.2. Владение данными и иерархия

**Каноническая иерархия:** `Кластер (сеть) → КИТС (домен) → Проект (система) → Приложения (репозитории разных уровней)`.

| Данные | Владелец | Правило |
|---|---|---|
| КИТС / Проекты / Приложения / Pipelines | Cosmo PostgreSQL | durable, FK, audit |
| Run / Batch / Gate / Finding | Cosmo PostgreSQL | состояние переживает рестарт |
| Evidence metadata и hashes | Cosmo PostgreSQL | immutable ledger metadata |
| Screenshots, video, raw traffic, SARIF | Cosmo MinIO/S3 | object key + checksum + provenance |
| Queue, retry, PubSub, progress | Cosmo Valkey | можно полностью пересоздать |
| Репозитории | Gitea | через ForgeAdapter |
| CI jobs | Woodpecker | через ExecutionAdapter |
| Security session runtime | Pure Box | управляется CapabilityBroker |

**COS-096: Gitea webhook delivery на ПУ.** Gitea 1.22 по умолчанию
(`ALLOWED_HOST_LIST=external`) блокирует доставку webhook'ов на
RFC-private хосты — включая `cosmo-api:8100` внутри docker-сети:
push-события молча не доходят до ПУ (последний пуш честно пуст).
Compose задаёт `GITEA__webhook__ALLOWED_HOST_LIST: "private"` (docker-сеть).
Для production при freeze сузить до явного CIDR сети Cosmo; при
edge-маршрутизации webhook'ов через внешний hostname — проверить,
что он резолвится и разрешён. Проверка доставки: push в привязанный
репо → `GET /api/v1/apps/{id}/forge/last-push` должен показать
`last_push` (source=webhook_cache) в течение секунд.

### 4.3. MinIO buckets

Минимальный набор бакетов Cosmo:

```text
cosmo-evidence   — screenshots, raw request/response, logs, traces, video
cosmo-artifacts  — SARIF, ГОСТ-Акты, reports, generated documents
cosmo-builds     — build outputs и package artifacts при необходимости
```

Каждый объект получает PostgreSQL record с `object_key`, content type,
checksum, размером, provenance и retention policy. Нельзя считать наличие
объекта в S3 достаточным доказательством без durable metadata.

---

## 5. Профили и контуры

Термин «контур» используется в двух смыслах:

1. технические зоны жизненного цикла: **ЗР → ЗТ → ЗПЭ**;
2. инфраструктурные профили: local, enterprise, airgap.

Они связаны, но не являются одним и тем же. Каждый технический контур имеет
свой deployment boundary и не получает доступ к чужой базе напрямую.

### 5.1. Local Development

Назначение: разработка COS-кода и быстрый smoke.

```text
docker compose
  ├── cosmo-postgres
  ├── cosmo-valkey
  ├── cosmo-openbao
  ├── cosmo-minio
  ├── cosmo-gitea
  ├── cosmo-woodpecker
  ├── cosmo-api
  ├── cosmo-frontend
  └── cosmo-caddy
```

Характеристики:

- все данные принадлежат отдельному Cosmo stack;
- допускаются mock Forge/Execution/Pure Box adapters для unit и integration tests;
- реальные Pure Box capability calls включаются отдельным профилем;
- внутренние порты не публикуются за пределами developer host без необходимости;
- каждое состояние Run/Batch/Gate пишется в PostgreSQL.

### 5.2. Integration / ЗР

Назначение: проверка настоящих контрактов между Cosmo, Gitea, Woodpecker и
Pure Box.

Обязательно:

- отдельный PostgreSQL-инстанс Cosmo;
- отдельный Valkey и отдельный MinIO;
- реальный Gitea и Woodpecker либо согласованный external endpoint;
- тестовый Pure Box runtime через REST/Webhook/SSE;
- отдельные OpenBao paths и test credentials;
- migration job перед запуском API;
- integration smoke: Domain → Pipeline → Compile → Run → Batch → Gate → Evidence.

### 5.3. ЗТ / stage-test

Назначение: прогон production-like security lifecycle на тестовом deploy target.

Характеристики:

- конфигурация максимально близка к production;
- реальные security-capabilities Pure Box;
- обязательный auth-профиль и проверка scope доступа;
- тестовые, но не mock findings/evidence;
- проверка restart/recovery, replay и идемпотентности;
- никаких production secrets и production repositories.

### 5.4. ЗПЭ / production

Назначение: эксплуатация и принятие решений о допуске.

Минимальная production-схема:

```text
Caddy / ingress
  → Cosmo API replicas
  → Cosmo frontend replicas
  → external/HA PostgreSQL
  → managed/HA Valkey
  → MinIO/Ceph S3
  → OpenBao
  → Gitea и Woodpecker по утверждённому Forge/Execution profile
  → Pure Box runtime по внешнему контракту
```

В production:

- наружу открыт только Caddy/Ingress;
- PostgreSQL, Valkey, MinIO API, OpenBao и execution services не публикуются
  напрямую;
- Admission Gate требует явного human decision;
- все административные и security-действия попадают в audit и Evidence Chain;
- backup и restore проверяются до допуска системы к эксплуатации.

### 5.5. Airgap

Airgap — это профиль доставки, применимый к локальному или enterprise-контру.
Он не меняет доменную модель и не вводит другой database backend.

В bundle входят:

- Cosmo API image;
- Cosmo frontend image;
- Gitea, Woodpecker, MinIO и supporting images;
- миграции и schema checks;
- Compose или Helm manifests;
- `manifest.json`, checksums, SBOM CycloneDX;
- подпись bundle и инструкция проверки;
- локальные образы Pure Box, если security runtime поставляется рядом.

В airgap запрещены runtime pull из внешнего registry и фоновые network calls.
Все образы digest-pinned, заранее загружены и проверены до установки.

**Airgap-чеклист (проверен 2026-09-02, COS-094):**

1. **Инвентарь образов** — 10 сервисов (full-профиль), все локальны, теги
   закреплены (не `latest`): `postgres:16-alpine`, `valkey/valkey:8-alpine`,
   `openbao/openbao:2.2`, `minio/minio:RELEASE.2025-03-12T18-04-18Z`,
   `gitea/gitea:1.22.6`, `woodpeckerci/woodpecker-{server,agent}:v3.5`,
   `cosmo-{api,frontend,caddy}:local`. Проверка:
   `docker compose --profile full config --images` + `docker images`.
2. **Digest-pin — TODO при production freeze**: в compose стоит
   комментарий-заглушка «digest-pin: sha256» у каждого внешнего образа;
   перед поставкой зафиксировать @sha256:... и перегенерить bundle.
   Build-time базовые образы (`node:22-alpine`, `nginx:alpine`, база Caddy)
   тоже входят в bundle как собранные `:local`-образы — тяги при `up` нет.
3. **Cold start без тяги** (проверено):
   `docker compose -f services/docker-compose.yml --profile full down`
   затем `... up -d --profile full --pull never` → EXIT=0, 10/10
   контейнеров Up (9 healthy + woodpecker: distroless, healthcheck
   disabled by design, liveness — внешний probe :8000/api/health).
4. **Healthchecks не зависят от DNS наружу**: все probe — `localhost`
   внутри контейнера или внутренний сервисный DNS compose-сети
   (`cosmo-postgres` и т.п. через 127.0.0.11); nginx edge резолвит
   cosmo-api через Docker DNS (valid=10s), внешних имён нет; woodpecker-agent
   использует `passthrough:///` (COS-063) — SRV/TXT наружу не ходит.
5. **Тяги в compose нет**: только `image:`/`build:` — registry не указан;
   при `--pull never` старт проходит.
6. **Volumes** (сохраняются при down/up): `cosmo_postgres`, `cosmo_valkey`,
   `cosmo_openbao`, `cosmo_minio`, `cosmo_gitea`, `cosmo_woodpecker`,
   `cosmo_caddy_data`, `cosmo_caddy_config`.
7. **TLS без ACME**: airgap-профиль Caddy — pre-issued сертификат/internal CA
   (§7.2); ACME-запросов наружу нет.
8. **Проверка поставки**: `manifest.json` + checksums + SBOM CycloneDX +
   подпись bundle (§5.5 выше).

**Канонический tag-формат (PK-C-003.4, канон COS-136):**

- **Один образ — один канонический тег** формата `<name>:<version>@sha256:<digest>`
  (version — semver или release-идентификатор, **никогда не `latest`**);
- расхождение версий ядро/стенд невозможно by construction: manifest
  фиксирует `@sha256:<digest>`, а не плавающий тег; при production freeze
  digest-pin из TODO (§5.5 п.2) становится обязательным полем manifest;
- **один бандл-профиль поставки** (`full` airgap-bundle) — не допускается
  несколько конкурирующих профилей с разными наборами образов.

---

## 6. Docker Compose: финальная схема

### 6.1. Сервисы

Buddy собирает отдельный Cosmo Compose в `D:\prettyk-airlock\services\`.
Файл `D:\prettyk-dev\services\docker-compose.cosmo.yml` используется как
референс, но не считается готовым переносом.

Целевой состав:

| Сервис | Назначение | Persistence |
|---|---|---|
| `cosmo-postgres` | Cosmo entities, states, audit | named volume / external disk |
| `cosmo-valkey` | Streams, PubSub, queue, cache | optional volume, не SoT |
| `cosmo-openbao` | secrets/KMS | encrypted volume |
| `cosmo-minio` | S3 artifacts | named volume / external disk |
| `cosmo-gitea` | forge | named volume + Cosmo ForgeBinding |
| `cosmo-woodpecker` | execution server | named volume / PG database |
| `cosmo-woodpecker-agent` | execution worker | ephemeral or managed |
| `cosmo-api` | FastAPI modular monolith | stateless |
| `cosmo-frontend` | built SPA | stateless |
| `cosmo-caddy` | single entry point | config + TLS state |

### 6.2. Сети и публикация портов

Финальный stack использует отдельную сеть Cosmo, например `cosmo-net`. Нельзя
подключать Cosmo к shared `pk-net` только ради удобства.

В local допустимы localhost bindings для диагностики:

```text
3000  Gitea
8000  Woodpecker
8100  Cosmo API
9000  MinIO S3
9001  MinIO console — только local/admin profile
5432  PostgreSQL — только local/admin profile
6379  Valkey — только local/admin profile
8200  OpenBao — только local/admin profile
443   Caddy — внешний entry point
```

В enterprise и production наружу публикуется только `443`. Внутренние сервисы
доступны по service DNS и policy-controlled network paths.

### 6.3. Зависимости старта

Порядок запуска:

```text
1. Network и volumes
2. cosmo-postgres, cosmo-valkey, cosmo-openbao, cosmo-minio
3. migration/init jobs
4. cosmo-gitea и cosmo-woodpecker
5. cosmo-api
6. cosmo-frontend
7. cosmo-caddy
8. readiness smoke
```

`depends_on` не заменяет readiness. API начинает принимать traffic только после
успешной проверки миграций и обязательных зависимостей.

### 6.4. Что исправить относительно текущего prototype

Текущий `prettyk-dev/services/docker-compose.cosmo.yml` полезен как черновой
референс, но перед использованием требует:

- отдельного Cosmo PostgreSQL вместо shared `prettyk-postgres`;
- отдельного Cosmo Valkey;
- отдельной Cosmo network;
- отсутствующего `cosmo-api.Dockerfile`;
- Cosmo frontend service/image;
- отдельного worker/agent profile для Woodpecker;
- секретов через OpenBao или injected runtime secrets;
- pinned image digests вместо floating `latest`;
- migrations/init job и bucket provisioning;
- проверки, что health endpoint действительно реализован;
- Caddy service в самом Compose stack.

---

## 7. Edge-архитектура: Caddy (канонический) + nginx same-origin

### 7.0. Канонический edge-путь (COS-094)

Канонический внешний entry point — **Caddy** (`cosmo-caddy`, host :8180 → 80):
rate limiting (COS-067), TLS-профили, /forge, /artifacts, /registry, /metrics.
Все внешние клиенты и production-трафик идут через него.

`cosmo-frontend` (nginx, host :5174 → 80) — **same-origin front door SPA**:
React-приложение зовёт относительный `/api/v1/...`, поэтому тот же origin
обязан обслуживать API — иначе браузер получает SPA-HTML/405 вместо JSON
(дефект, закрытый COS-094). Это НЕ второй production edge: без rate limit и
TLS; назначение — прямая работа с SPA и приёмка «как увидит браузер».

Правила nginx same-origin edge (`frontend/nginx.conf`):

- `/api/` → `cosmo-api:8100` (путь сохраняется); `client_max_body_size 256m`
  (ingest-пейлоады больше nginx-дефолта 1m);
- SSE-ручки (`runs/*/stream`, `domains/*/events/stream`,
  `notifications/stream`) — `proxy_buffering off`, read timeout 1h, HTTP/1.1
  keepalive (поток живой, чанки без задержки);
- `/live` `/ready` `/health` — честный passthrough (`/ready` = 503 при
  падении hard-dep, COS-090);
- cosmo-api резолвится через Docker DNS (127.0.0.11, valid=10s) — переживает
  пересоздание контейнера API без reload nginx; никаких внешних DNS
  (airgap-безопасно);
- остальное — SPA fallback → index.html (React Router).

### 7.1. Маршруты Caddy

```text
/api/*        → cosmo-api:8100
/forge/*      → cosmo-gitea:3000
/artifacts/*  → cosmo-minio:9000
/*            → cosmo-frontend
```

Caddy должен сохранять WebSocket и SSE-соединения, прокидывать необходимые
headers и не обрывать долгие telemetry streams.

### 7.2. Профили Caddy

- local: HTTP/localhost, `auto_https off`;
- integration: internal TLS или controlled ingress;
- production: реальный hostname, ACME/internal CA по политике заказчика;
- airgap: заранее выданный сертификат или internal CA, без ACME наружу.

Admin endpoint Caddy (`:2019`) не является пользовательским API и не должен быть
доступен из внешней сети.

---

## 8. Kubernetes

### 8.1. Что уже есть и как это использовать

`D:\prettyk-dev\services\helm\prettyk\` — готовый Helm-паттерн для Pure Box
session workloads: session deployment, labels, RBAC и default-deny
NetworkPolicy.

Он **не является Cosmo control-plane chart**. Его можно использовать как
референс для изоляции security sessions, но Cosmo chart собирается отдельно.

### 8.2. Целевая структура namespace

```text
cosmo-system
  ├── cosmo-api Deployment
  ├── cosmo-frontend Deployment
  ├── cosmo-caddy Ingress/Deployment
  ├── migration Job
  ├── cosmo worker Deployments, если нужны
  └── ServiceAccount + RBAC

cosmo-forge
  ├── Gitea StatefulSet или external binding
  └── persistent storage

cosmo-execution
  ├── Woodpecker server
  └── Woodpecker agents

cosmo-run-<run_id> или контролируемый run pool
  ├── security session resources
  ├── scanner
  ├── Playwright
  ├── Fuzzer ctl/session
  └── target binding
```

PostgreSQL, Valkey, MinIO/Ceph и OpenBao в enterprise предпочтительно
подключаются как managed/external services. Если разворачиваются в кластере,
они всё равно остаются отдельными Cosmo-owned инстансами с отдельными policy,
backup и credentials.

### 8.3. Security sessions в Kubernetes

Переносится паттерн из `session-deployment.yaml` и `networkpolicy.yaml`:

- уникальный `run_id`/session label;
- отсутствие фиксированных имён, конфликтующих с другими runs;
- отдельный Service DNS;
- default-deny между сессиями;
- доступ к session workloads только от Cosmo control/broker;
- resource requests/limits и `shmSize` для browser;
- teardown после terminal Run state;
- cleanup orphaned sessions после рестарта control plane.

### 8.4. Минимальный Cosmo Helm chart

Buddy создаёт отдельный chart, например `services/helm/cosmo/`, с:

```text
Chart.yaml
values.yaml
templates/
  api-deployment.yaml
  api-service.yaml
  frontend-deployment.yaml
  frontend-service.yaml
  caddy-ingress.yaml
  migration-job.yaml
  configmap.yaml
  secret-reference.yaml
  networkpolicy.yaml
  serviceaccount.yaml
  rbac.yaml
```

Чарт должен поддерживать как минимум `dev`, `integration`, `stage` и `prod`
values, а secrets получать из OpenBao/cluster secret integration, не из git.

---

## 9. Сессионный runtime и CapabilityBroker

### 9.1. Compose-паттерн

Существующий `session-template.yml` переносится не как Pure Box backend, а как
референс управляемого runtime:

```text
CapabilityBroker.acquire(run_id)
  ├── session network: cosmo-run-<run_id>
  ├── scanner / internal :8080
  ├── Playwright / internal CDP
  ├── target / internal DNS
  └── optional API lab

Run executes

CapabilityBroker.teardown(run_id)
  ├── stop sessions
  ├── persist final evidence
  ├── release ports/leases
  ├── remove network
  └── verify no orphan resources
```

Инварианты Pure Box session template сохраняются:

- нет фиксированных `container_name`;
- нет жёстких host ports внутри session;
- ресурсы именуются через session/run identity;
- health checks обязательны;
- teardown идемпотентен;
- повторный teardown безопасен;
- capability lease связан с `run_id` и владельцем.

### 9.2. Kubernetes-паттерн

В Kubernetes тот же контракт реализуется через namespace/deployment/service
или через контролируемый run pool. Выбор между namespace на Run и пулом не
меняет внешнего контракта CapabilityBroker.

Broker не должен знать внутренние Python-классы Pure Box. Он знает только:

- capability endpoint;
- session handle;
- health/status contract;
- teardown endpoint;
- event correlation.

---

## 10. PostgreSQL, миграции и recovery

### 10.1. Состав базы

Cosmo DDL/Alembic фиксирует восемь доменных объектов:

```text
cosmo_domains
cosmo_applications
cosmo_pipelines
cosmo_runs
cosmo_batches
cosmo_findings
cosmo_evidence_ledger
cosmo_audit_events
```

Начальный Steel Thread может вводиться поэтапной миграцией, но omission
`findings` или `audit_events` нельзя маскировать сокращением списка. Перед
freeze миграций Boss и Luna должны сверить DDL с Pydantic-контрактами и
зафиксировать FK, unique constraints, JSONB и GIN indexes.

### 10.2. Migration lifecycle

```text
build image
  → wait for postgres ready
    → alembic upgrade head
      → schema check
        → seed only non-secret reference data
          → start API
```

Миграции:

- versioned и forward-only;
- запускаются отдельным job/entrypoint;
- не содержат credentials и production data;
- проверяются на empty database и upgrade from previous release;
- имеют backup/restore procedure до destructive migration.

**Репетиция миграции (PK-C-003.3, канон COS-136).** Перенос/апгрейд
выполняется как явная процедура-репетиция ДО боевого применения:

```text
1. scratch    — поднять пустой PG (per-session БД, COSMO_TEST_SESSION_DB)
2. прогон     — alembic upgrade head на scratch + schema check
3. сверка     — catalog-сверка (migration_verifier) + reconciliation-тест
                head-ревизии; ноль расхождений
4. боевой     — только после зелёной репетиции: upgrade на целевом контуре
```

Ни один миграционный тест не зависит от состояния dev-БД: тесты работают
на изолированном test-PG (:5433) и per-session БД; scratch-based
verification и catalog-race isolation (COS-076) — несущее ядро этой
процедуры. Скрипты: `services/scripts/suite_gate.ps1`,
`services/scripts/cleanup_scratch_pg.py`.

### 10.3. Recovery

При полном сбросе Valkey:

```text
Valkey empty
  → API читает Run/Batch/Gate из PostgreSQL
  → восстанавливает pending leases и queue projections
  → повторно публикует только актуальную telemetry
```

Потеря Valkey не должна:

- удалять Run;
- менять terminal status;
- удалять Gate decision;
- уничтожать Evidence metadata;
- делать невозможным аудит.

---

## 11. Secrets, identity и конфигурация

### 11.1. Секреты

В git не хранятся:

- PostgreSQL passwords;
- Valkey auth, если включён;
- MinIO access/secret keys;
- Gitea/Woodpecker tokens;
- Pure Box API tokens;
- Better Auth secrets;
- OpenBao root/unseal material;
- signing keys и production certificates.

Non-secret defaults разрешены только в `.env.example`/values example. Реальные
значения inject'ятся из OpenBao или deployment secret manager.

### 11.2. Конфигурационные группы

Минимально нужны:

```text
COSMO_ENV
COSMO_PG_DSN
COSMO_VALKEY_URL
COSMO_MINIO_ENDPOINT
COSMO_MINIO_BUCKET_* 
COSMO_GITEA_URL
COSMO_WOODPECKER_URL
PUREBOX_API_URL
PUREBOX_WEBHOOK_BASE_URL
PUREBOX_SSE_URL
AUTH_*
OPENBAO_*
```

Имена и payload должны быть утверждены до адаптеров; этот список — архитектурная
группа конфигурации, а не готовый секретный файл.

### 11.3. Отдельные identity boundaries

Cosmo auth и Pure Box auth не смешиваются внутренней базой. Cosmo использует
Better Auth + OpenBao и внешний OIDC contract при необходимости. Pure Box
вызывается service-to-service credentials, scoped на нужные capabilities и
domain/run, с rotation и audit.

---

## 12. Порядок реализации и ввода

### Этап 0. Transfer freeze

**Результат:** утверждённый список файлов и границ.

1. Перенести только разрешённые backend/frontend исходники.
2. Проверить отсутствие Pure Box imports.
3. Заморозить Pydantic ↔ ORM mapping.
4. Заморозить REST/Webhook/SSE contracts.
5. Выделить Cosmo-owned config и secrets.

### Этап 1. Backend Steel Thread

**Карточки:** `COS-001`…`COS-006`.

1. PostgreSQL ORM + Alembic.
2. PlanCompiler и compiled hashes.
3. RunControlPlane и durable state machine.
4. CapabilityBroker с leases/health/teardown.
5. EvidenceLedger с MinIO ArtifactStore.
6. Integration smoke на mock adapters.

### Этап 2. Реальные адаптеры

**Карточки:** `COS-007`…`COS-009`.

1. Gitea ForgeAdapter.
2. Woodpecker ExecutionAdapter.
3. scanner ctl и Playwright/Fuzzer ctl через внешние API.
4. Webhook signature/correlation/retry.
5. Реальная security session и teardown.

### Этап 3. API и frontend integration

**Карточки:** `COS-010`…`COS-012`.

1. FastAPI routes.
2. Valkey PubSub → SSE.
3. REST вместо local state/mock.
4. Control Station читает durable history.

### Этап 4. Deployment packaging

**Карточки:** `COS-013`…`COS-015` плюс инфраструктурный scope этого документа.

1. `cosmo-api.Dockerfile`.
2. frontend image.
3. Cosmo Compose с отдельными PG/Valkey/MinIO.
4. migration/init jobs.
5. MinIO bucket provisioning.
6. Caddy entry point.
7. `/live`, `/ready`, `/health`.
8. local/integration values и secret injection.

### Этап 5. Kubernetes и airgap

1. Отдельный Cosmo Helm chart.
2. NetworkPolicy, RBAC, service accounts.
3. External database/object storage bindings.
4. Dynamic security session deployment.
5. Helm lint/template/upgrade dry-run.
6. Airgap bundle with digest/SBOM/signature.
7. Offline install и offline restore drill.

### Этап 6. Приёмка и promotion

**Карточки:** `COS-016`…`COS-018`.

1. Full smoke на настоящих adapters.
2. Idempotency/recovery.
3. Security leak check.
4. Backup/restore.
5. Promote artifact bundle по утверждённым контурам.
6. Только после этого — отключать старый Live compatibility path.

---

## 13. Health, observability и эксплуатация

### 13.1. Health endpoints

| Endpoint | Смысл | Проверяет зависимости |
|---|---|---|
| `/live` | процесс жив | нет, только process health |
| `/ready` | ядро способно обслуживать трафик (K8s readiness) | PostgreSQL (hard), Valkey + anchor (soft) |
| `/health` | расширенная диагностика | PG, Valkey, MinIO, adapters, versions |

**Семантика `/ready` (COS-090, K8s readiness-семантика):**

- **200** — только когда ядро способно обслуживать запросы: PostgreSQL
  доступен. Тело — компонент-мап: `database`, `cache`, `anchor` +
  сводный `status` (`ok` | `degraded`).
- **503** — недоступен hard-dep PostgreSQL: upstream (Caddy/K8s) выводит
  инстанс из ротации. Тело — честный компонент-мап `status="not_ready"`.
- **Мягкие деградации НЕ роняют readiness**: Valkey недоступен → SSE
  fallback на in-memory (COS-088); anchor sink недоступен → честный
  `unknown_anchor` на verify-стороне (COS-087). Оба видны в теле как
  `cache/anchor: "unavailable"` и сводном `status="degraded"`.
- Anchor не сконфигурирован (env не задан) → `anchor: "disabled"`, не
  деградация.

Это закрывает известное отклонение COS-063 (`/ready=200 degraded` при
падении PG — «ложь балансировщику»). Раньше: PG down + Valkey up → 200;
теперь → 503.

`/health` не должен раскрывать credentials, tokens или внутренние stack traces.

**Ownership тестового контура и suite gate (PK-C-003.1, канон COS-136).**

- У тестового стенда есть **именованный владелец контура** — инженер,
  отвечающий за его здоровье; при деградации `/health`/`/ready` он чинит
  первым (не «кто-нибудь из команды»).
- **Единственная команда здоровья** контура —
  `services/scripts/suite_gate.ps1`: она поднимает зависимости, гоняет
  бэкенд- и фронт-сьюты и печатает итог. Любая локальная вариация прогона
  не считается приёмкой.
- `/ready` — day-one контракт: честный компонент-мап (503 при down
  hard-dep, 200+`degraded` при soft) до того, как через edge уходит
  пользовательский трафик (COS-090).

### 13.2. Наблюдаемость

Каждая операция коррелируется через:

```text
domain_id → run_id → batch_id → job_id → step_id → evidence_id
```

В логах и событиях не должны появляться секреты, auth cookies, raw credentials
или чувствительные headers. Сырые большие payloads уходят в ArtifactStore, а в
Valkey/SSE идут агрегаты и progress ticks не чаще двух раз в секунду.

### 13.3. Backup

Обязательные backup targets:

- PostgreSQL full + point-in-time strategy по профилю;
- MinIO metadata/object backup;
- Gitea repository/data backup;
- OpenBao backup по его operational policy;
- deployment manifests и image manifest;
- миграционная версия.

Restore проверяется не декларацией, а отдельным drill с восстановлением Run,
Gate, Evidence metadata и выбранных artifacts.

---

## 14. Acceptance gates развёртывания

### Gate A — Transfer compliance

- перенесены только разрешённые исходники;
- нет `import` из Pure Box runtime;
- forbidden directories не появились в Cosmo;
- все COS-F* лежат в Cosmo Control Station scope;
- Inline Editor не тащит Pure Box shell/Admin.

### Gate B — Compose

- отдельные PG/Valkey/MinIO поднимаются с чистого хоста;
- migrations применяются автоматически и повторно безопасны;
- buckets создаются и проверяются;
- API, frontend и Caddy проходят readiness;
- внутренние порты не открыты в production profile.

### Gate C — Steel Thread

```text
Domain → Pipeline → Compile → Run → Batch → Gate → Evidence
```

Проход проверяется с mock adapters, затем с реальными Gitea/Woodpecker и Pure
Box contracts.

### Gate D — Recovery

- Valkey полностью очищен;
- API восстановил history из PostgreSQL;
- terminal statuses и Gate decisions не изменились;
- evidence metadata и object checksums валидны;
- orphan security sessions обнаружены и удалены.

### Gate E — Security

- secrets не попадают в plan snapshot, logs, SSE, frontend или evidence;
- domain boundaries и RBAC проверены;
- service tokens scoped и ротируются;
- admission не может быть принят AI без разрешённого human decision;
- Caddy admin и внутренние сервисы не доступны извне.

### Gate F — Kubernetes/Airgap

- Helm lint и template проходят;
- NetworkPolicy не допускает cross-session traffic;
- session teardown не оставляет зомби;
- airgap bundle проверяет подпись, digest, SBOM и checksum;
- установка не требует внешней сети;
- restore drill успешно пройден.

### Gate G — Suite gate + scratch hygiene (COS-089)

Одна команда — весь cosmo-суит в изолированной тестовой БД:

```powershell
.\services\scripts\suite_gate.ps1
```

- поднимает тестовый PG (:5433, `services/docker-compose.test-pg.yml`);
- ставит `COSMO_TEST_SESSION_DB=1` — прогон получает собственную БД
  `cosmo_test_s<hex>` на том же инстансе (COS-076): bootstrap схемы, данные
  и wipe не касаются общего `cosmo_test`; БД дропается при выходе процесса
  (atexit);
- запускает `python -m pytest orchestrator/tests/cosmo -q` и возвращает
  exit-code pytest как свой; вердикт `SUITE GATE: PASS/FAIL`;
- идемпотентен с чистого состояния.

Гигиена scratch-БД (дроп сирот после SIGKILL'нутых сессий/падений мимо
teardown):

```powershell
python services\scripts\cleanup_scratch_pg.py            # dry-run: план
python services\scripts\cleanup_scratch_pg.py --apply    # дроп только orphan
```

- кандидаты только с префиксами `cosmo_test_s*` / `cosmo_scratch_*`;
- дропается только БД без активных соединений (живая сессия воркера —
  skip);
- `postgres`, `cosmo` (dev), `cosmo_test`, templates — защищены; хост-порт
  5432 (dev-стенд) отказывается обслуживать (guard).

---

## 15. Открытые решения для ревью Gemini

Эти вопросы не разрешают менять стек, но должны быть уточнены до production
freeze:

1. Точная схема multi-Gitea: отдельный instance на Domain или управляемый
   isolated tenant в bootstrap-профиле.
2. Будет ли Woodpecker agent жить рядом с Cosmo или предоставляться external
   ExecutionAdapter.
3. Какие PostgreSQL/MinIO/Valkey компоненты в Enterprise managed, а какие
   поставляются Helm/Compose.
4. Финальная форма Pure Box REST/Webhook/SSE contract и версия payload.
5. Как именно передаются artifacts между ЗР, ЗТ и ЗПЭ без общей базы.
6. Стратегия namespace-per-run против bounded session pool в Kubernetes.
7. Где проходит граница Cosmo API и background worker при сохранении
   модульного монолита.
8. Точная нормативная версия профиля ГОСТ-Акт для конкретного deployment.

До решения этих вопросов нельзя делать скрытые assumptions в adapters,
network policies или production values.

---

## Итоговая схема

```text
Разрешённые исходники Pure Box
  → D:\prettyk-airlock\orchestrator\cosmo + frontend\src\cosmo

Cosmo-owned infrastructure
  → dedicated PostgreSQL + Valkey + MinIO + OpenBao
  → Gitea + Woodpecker + Cosmo API + frontend + Caddy

Pure Box capabilities
  → Playwright + scanner Demon + Fuzzer + Discovery
  → только REST / Webhook / SSE

RunControlPlane
  → PlanCompiler
  → Batch DAG
  → CapabilityBroker
  → Security Gates
  → Evidence Chain

Deployment profiles
  → local Compose
  → integration / ЗР
  → stage-test / ЗТ
  → production / ЗПЭ
  → airgap overlay
  → Kubernetes для enterprise и изолированных sessions
```

Критерий готовности простой: Cosmoport должен подняться как отдельная система,
пережить рестарт Valkey, провести один доказуемый Run от Domain до Evidence,
вызвать Pure Box только через внешний контракт и безопасно удалить все ресурсы
его security session.
