# PureK / PrettyK — будущая архитектура и границы интеграций

> **Статус:** рабочее архитектурное направление, принятое PO 1 сентября 2026 года.
> **Назначение:** фиксировать будущую архитектуру PureK/PrettyK и границу с Cosmoport 2, чтобы legacy-инвентаризация не превращалась в список обязательных зависимостей.
> **Правило:** наличие системы в старом ТЗ или коде не означает, что она входит в PureK.

## 1. Архитектурный принцип

PureK строится от собственных пользовательских сценариев и capability-контрактов,
а не как перенос старого Cosmoport один к одному.

Внешние продукты подключаются через отдельные адаптеры и setup/install profiles:

```text
PureK core
  → provider-neutral contract
  → external adapter
  → customer-managed или bundled provider
```

Наш default — это не один hard-coded transport, а multi-option transfer framework.
Заказчик выбирает профиль под свою network/gap barrier:

```text
A. direct authenticated mTLS API       — nongap
B. immutable offline package import   — airgap
C. controlled transfer gateway/relay  — managed gap
D. one-way diode/relay                — strict isolation
E. SODTransferAdapter                 — Cosmoport 2 option
```

Options A–D используют один PureK package contract, одну idempotency model и один
pre-transfer/landing validation flow. Меняется канал, а смысл package и state
machine не меняются. Подробная matrix: `docs/TRANSFER-OPTIONS.md`.

Внешний продукт не становится источником истины PureK и не встраивается в core
через его внутренние модули.

### 1.1. HTTP boundary для интеграций

PureK нужен внутренний backend HTTP client layer для вызова provider API. Это
не пользовательский Postman и не встроенный API-клиент в интерфейсе.

```text
FastAPI / worker
  → ProviderHttpClient
  → Forge / CI / Registry / Splunk / Pure Box API
```

Новый adapter использует общий client layer, который обеспечивает:

- timeout, retry/backoff и circuit state;
- HTTP proxy и `NO_PROXY`;
- TLS/private CA;
- secret reference без попадания credentials в logs;
- `request_id`, `trace_id`, `run_id` и `traceparent`;
- redacted request/response diagnostics;
- idempotency headers/keys, где это поддерживает provider;
- allowlisted provider base URL и SSRF-safe resolution.

Postman/Newman не встраиваются в PureK runtime. Для разработчиков и интеграционных
тестов достаточно OpenAPI и optional exported Postman collection. Оператор вместо
произвольного HTTP-запроса использует controlled «Test connection»/probe в Pretty
Health, который вызывает capability-specific health operation adapter'а.

### 1.2. Sfera / ДиБ как внешний Cosmoport bridge

Локальный discovery scrape `D:\cosmo\cosmo-frontend-to-scrape\Sfera_OpenAPI`
подтверждает отдельную Sfera/ДиБ API-поверхность по
`/ppdl/administration/openapi`. Это discovery evidence, но не machine-readable
OpenAPI contract: UI bundles нельзя принимать за подтверждённые endpoint/schema
semantics. Полный разбор и список gaps: `docs/research/2026-09-01-sfera-openapi-and-registry-boundary.md`.

Cosmoport 2 закладывает optional `SferaProviderAdapter` seam для Sfera/ДиБ как
artifact provider: provisioning area/repositories, raw push/pull и OCI
push/pull. Legacy backend уже даёт достаточно evidence для этого базового
контракта. Реальный OpenAPI export нужен не как предварительное условие, а для
точной live-проверки и дополнительных операций (listing/exists, promotion,
jobs/status, quotas, signatures и version-specific auth/errors). Sfera не
становится источником истины Cosmoport и не меняет PureK internal stack.

Если позднее подтвердится, что Sfera также координирует межзонный transport,
это будет отдельный optional `SferaTransportAdapter`; не смешивать его с
artifact provider и общим Connected/Offline/Diode transport layer.

## 2. Runtime и виртуализация

PureK закладывает универсальную границу для временных окружений и виртуализации:

```text
VirtualizationAdapter / EnvironmentProvisioner
  ├── capabilities()
  ├── provision(request)
  ├── get_status(environment_id)
  ├── get_connection(environment_id)
  └── destroy(environment_id)
```

Контракт должен включать idempotency key, timeout/cancellation, secret
references, image/template reference, network references, readiness и cleanup.

Сейчас не выбирается конкретный VM provider и не реализуется vRA-specific path.
Когда появится реальный use case, контракт будет расширен отдельным provider
adapter. Для этого будет создан friend request с конкретным сценарием, provider,
API и acceptance criteria.

Универсальная граница — это extension seam, а не заявление о готовой поддержке
всех гипервизоров.

## 3. Registry и артефакты

### 3.1. Принятая схема

```text
Harbor
  → container images
  → OCI registry
  → staging образов

Nexus
  → dependencies и package repositories
  → build artifacts
  → proxy/cache
  → generic artifacts

MinIO/S3
  → raw scan outputs
  → reports
  → evidence blobs
  → большие immutable objects
```

Harbor и Nexus дополняют друг друга. Nexus — обязательный baseline provider,
а не отложенная интеграция.

### 3.2. Исключённые решения

```text
Artifactory — исключён из PureK и active Cosmoport paths.
Собственный registry — не создаём.
```

В Build, Release и Evidence фиксируются provider, repository, artifact reference,
immutable digest, SBOM reference и доступные signature/attestation references.
Секреты представлены только secret references.

### 3.3. Release metadata и artifact planes

Найденный legacy release package показал важное разделение: release package может
быть только **control/metadata envelope**, а source, build outputs и deployable
artifacts идут отдельными каналами. Поэтому PureK не должен подразумевать, что
весь релизный payload пересекает gap одним архивом или через СОД.

```text
Release metadata / control plane
  → project/application graph
  → release/build identity
  → build/deployment order
  → artifact references by immutable digest
  → transfer/landing/bootstrap intent

Source plane
  → Git refs, repository bundles или provider-specific mirror

OCI plane
  → image manifests/layers, indexes, signatures, attestations, SBOM
  → source-zone Harbor
  → approved registry transfer path
  → target-zone Harbor

Package/dependency plane
  → coordinates, packages, generic artifacts и metadata
  → source-zone Nexus
  → approved repository transfer path
  → target-zone Nexus

Evidence plane
  → reports, raw scan outputs и evidence blobs
  → MinIO/S3 или отдельный approved object transfer
```

Каждая зона может иметь собственные локальные Harbor и Nexus. Это не означает
«запустить один Harbor/Nexus в каждом application deployment» и не означает
обычную horizontal replica одного кластера: речь идёт о zone-local registry/
repository instances и о promotion/replication между ними через разрешённый
route, relay, offline bundle или customer bridge.

Harbor отвечает за OCI content и его digest-preserving promotion. В scope входят
также multi-arch indexes, signatures/attestations и SBOM references, если они
являются частью supply-chain policy. Nexus отвечает за package coordinates,
dependencies и generic artifacts; его перенос моделируется отдельным
`RepositoryTransferAdapter`, а не предполагается идентичным Harbor replication.

Release metadata содержит ссылки на эти planes, но не подменяет их. Для каждого
релиза должны быть видны как минимум:

```text
artifact_ref
artifact_kind: source | oci | package | generic | evidence
provider: gitlab | harbor | nexus | s3
source_location
target_location (если известен)
immutable_digest/checksum
transfer_status
```

`SODTransferAdapter` может перевозить metadata envelope или конкретный payload,
если это подтверждено фактической схемой. Он не должен автоматически считаться
каналом для Git, OCI, Nexus и evidence одновременно. Transfer plan обязан
указывать plane, выбранный transport, correlation id, readiness и отдельный
recovery path по каждому payload.

## 4. Observability и аудит

Splunk входит в PureK сразу как first-class внешний sink:

```text
PureK
  → structured logs
  → audit events
  → run/batch/gate events
  → security events и finding references
  → Splunk
```

Нужен `ObservabilityExportAdapter` с `SplunkAdapter`, включающий HEC, TLS/CA,
secret reference, index/sourcetype mapping, batching, retry/backoff, health и
ошибки доставки.

Splunk не заменяет PostgreSQL, Evidence Ledger или Valkey. Canonical state и
доказательства остаются внутри PureK.

Метрики остаются на Prometheus/OpenMetrics-compatible contract. VictoriaMetrics
не входит в baseline до подтверждения реального обязательного use case.

### 4.1. Метрики, трассировка и эксплуатационный профиль

PureK публикует OpenMetrics-совместимые метрики. Prometheus может разворачиваться
как non-mandatory deployment profile через Kubernetes или Compose и собирать эти
метрики. Grafana не получает «поток» напрямую: она читает Prometheus как datasource
и показывает dashboards. Alertmanager может поставляться в том же operational
profile.

```text
PureK / exporters
  → Prometheus
  → Grafana dashboards
  → Alertmanager alerts
```

OpenTelemetry включается сразу как стандарт instrumentation/correlation path.
OpenTelemetry Collector остаётся deployable optional service, а не обязательной
зависимостью доменного core:

```text
API / workers / adapters / runtime sensors
  → trace_id + request_id + run_id
  → OpenTelemetry Collector (если профиль включён)
  → Splunk или другой разрешённый telemetry backend
```

Польза для PureK:

- оператор видит путь Run через API, queue, execution provider, Pure Box и callback;
- разработчик и тестировщик находят конкретный медленный или упавший участок;
- security-команда связывает действие, finding, gate и Evidence по correlation IDs;
- администратор получает latency, saturation, retries и stuck-run signals.

### 4.2. Аудит без отдельного микросервиса

Audit остаётся модулем внутри Cosmo/PureK:

```text
business mutation
  + append-only audit event
  + transactional outbox record
  → одна PostgreSQL transaction
  → delivery в Splunk/Valkey
```

Принятые обязательные паттерны:

- retry и idempotency на всех внешних operations;
- transactional outbox для надёжной публикации событий;
- append-only audit events без обычного update/delete;
- hash/checkpoint и immutable export audit/evidence в S3/MinIO;
- correlation через actor, request_id, trace_id, run_id и target resource.

## 5. Nongap и airgap

### 5.1. Nongap

В nongap installer/setup profile скачивает зафиксированные версии зависимостей,
проверяет digest/signature, разворачивает PureK и конфигурирует внешние системы.

Поддерживаются:

- pinned versions;
- health/readiness checks;
- private CA и TLS;
- secret references;
- repeatable upgrade;
- конфигурация через setup bundle.

### 5.2. Airgap

Airgap — не урезанный режим, а полноценный delivery flow:

```text
connected staging host
  → download/pull pinned packages и images
  → verify checksum/digest/signature
  → собрать manifest и offline bundle
  → передать в airgap
  → import в локальные Harbor/Nexus/runtime
  → install/configure/health-check
```

Bundle может содержать:

- OCI images;
- Helm charts и manifests;
- package repositories/cache;
- PureK images и configuration layers;
- Splunk offline package, если его допускает лицензия;
- redacted configuration templates;
- checksums, signatures и SBOM;
- installation, upgrade и recovery metadata.

Volume/mount используется для конфигурации, данных, сертификатов, plugin payload
и offline cache. Container images импортируются как OCI archive или через локальный
registry; volume не заменяет image layers.

Если лицензия внешнего продукта не позволяет нам распространять его дистрибутив,
airgap installer принимает лицензированный offline package заказчика, проверяет
его и всё равно автоматически выполняет установку, конфигурацию и health checks.
Это считается полноценной поддержкой airgap, а не исключением продукта из
архитектуры.

## 6. Надёжность и эксплуатация

### 6.1. Управление выполнением

Scheduler и workers используют leases, heartbeat и concurrency limits. Повторная
доставка webhook или перезапуск worker не должны создавать второй side effect.

Обязательны:

- idempotency keys;
- lease/lock ownership;
- safe retry с backoff и jitter;
- reconciliation после падения API/worker;
- orphan cleanup;
- capacity limits и backpressure;
- состояния `queued`, `deferred`, `retrying`, `blocked` и
  `operator_action_required`.

Kafka, Consul и отдельный scheduler product для этого не требуются.

### 6.2. Webhook и PKI

Все inbound callbacks проходят:

- signature verification;
- timestamp/replay protection;
- provider secret reference;
- idempotency и correlation;
- audit успешного и отклонённого callback.

TLS/PKI contract включает private CA, certificate expiry monitoring, rotation без
простогоев, airgap CA import и ротацию webhook signing keys.

### 6.3. Backup, recovery и Pretty Health

Backup/disaster recovery — обязательная часть эксплуатации, даже если часть
похожих эпиков уже была в PureK или Cosmoport. Нельзя считать её закрытой без
проверенного restore run.

Минимум:

```text
PostgreSQL  → backup + WAL/PITR + restore test
MinIO/S3    → versioning/retention + object recovery
OpenBao     → encrypted snapshot + recovery/unseal procedure
Config      → manifests + provider bindings + bundle metadata
```

Нужны RPO, RTO, backup frequency и acceptance restore.

Пользовательская операционная поверхность называется **Pretty Health**:

```text
Pretty Health
  → PostgreSQL
  → Valkey
  → MinIO/S3
  → OpenBao
  → Caddy/TLS
  → Registry
  → Splunk
  → Pure Box
  → webhooks
  → migrations
  → certificates
  → capacity/quota signals
```

Она включает API/CLI checks, понятные причины failure и remediation hints, но не
показывает секреты.

### 6.4. Upgrade и rollback

Upgrade/rollback делается сервисно и минимально: schema preflight, backup before
upgrade, migration compatibility, health gate и documented rollback/recovery.
Частые автоматические обновления внешних продуктов не являются целевым сценарием,
особенно в airgap. Не строим отдельную платформу управления версиями.

### 6.5. Что уже доказано в PrettyK Box

Health, lease, capability и runtime patterns не нужно изобретать повторно. В
PrettyK Box уже реализованы и протестированы:

```text
ServiceHealth
  → /live /ready /health
  → named dependency checks
  → draining

LeaseController
  → heartbeat
  → fencing generation
  → grace period
  → zombie GC
  → recovery

CapabilityBroker
  → idempotent resource allocation
  → health states
  → lease recovery

RuntimeProvider
  → Compose/Kubernetes strategy boundary

EventBus
  → Valkey PubSub или Pure Box fallback
  → sequence/replay
  → SSE heartbeat

Profiles
  → Pure Box / Enterprise feature boundary
```

Для Cosmoport/PureK эти patterns переиспользуются, но не копируются буквально:

- Pure Box может использовать filesystem/in-memory fallback;
- Enterprise Control Plane использует PostgreSQL как durable SoT, Valkey как
  transport и собственные persistence boundaries;
- Docker labels могут помогать восстановлению локального runtime, но не заменяют
  durable Run/Batch/Lease state в Enterprise;
- EventBus replay не заменяет PostgreSQL timeline и audit;
- DSL self-heal не заменяет transfer LandingCheckup и reconciliation.

По отчёту Keeper Run Control Plane, полноценный Edge и сквозная Telemetry в
PrettyK Box пока спроектированы, но не реализованы. Это совпадает с нашими
оставшимися архитектурными gaps и не требует второго параллельного набора
паттернов.

## 7. Quota и integration control

Квотирование входит в будущую архитектуру как capability-based control, а не как
набор жёстких предположений о конкретном Git provider.

В интерфейсе карточки ресурса выделяются две отдельные вкладки:

```text
Квотирование
Интеграции
```

### 7.1. Квотирование

Поддерживаются:

- CPU и memory для execution/runtime environments;
- storage и artifact size;
- concurrency/runs/batches;
- quota для security sessions и worker pool;
- hierarchical quotas по Domain → Project/Application;
- hard limit и soft warning mode;
- проверка суммы дочерних quotas против родительской;
- quota usage, threshold и exhausted state.

PureK хранит desired quota и observed usage/status. Provider adapter сообщает
capabilities и применяет только поддерживаемые типы ограничений. Нельзя обещать
одинаковый quota API для каждого Git/CI продукта.

### 7.2. Интеграции

Для каждой интеграции отображаются отдельно:

```text
configured
enabled / disabled
pending
running
online / healthy
failed
not_active
stale
```

Статус сопровождается provider, last check, reason, capabilities и временем
последней проверки. «Online» не означает, что provider поддерживает все quota или
все операции PureK.

## 8. Runtime sensors и IAST

IAST можно заложить как optional capability для deployment/runtime target:

```text
IAST / RuntimeSensorAdapter
  → instrumentation или sidecar/agent
  → runtime trace/data-flow signals
  → Run / Finding / Evidence
```

Это не означает монтирование `docker.sock` в security service. Docker socket даёт
практически root-level control над host и не является допустимым default path.

Для Kubernetes предпочтительны:

- language/runtime agent или sidecar;
- namespace-scoped RBAC;
- admission/instrumentation profile;
- stdout/log/trace collection через разрешённый collector;
- teardown вместе с deployment/run.

Для VM/Compose возможен отдельный SSH/host collector с short-lived credentials,
command allowlist и audit, но это отдельный provider/runtime capability. Он не
входит в baseline без подтверждённого сценария.

IAST полезен разработчику и тестировщику, когда одного внешнего DAST finding мало:
он помогает связать запрос с runtime call path, data flow и конкретным участком
приложения. Для оператора это дополнительная runtime telemetry, а не замена DAST.

## 9. Поддерживаемые внешние интеграции

### PureK first-class

```text
Forge / SCM:
  GitLab, GitHub, Bitbucket, Gitea/Forgejo

Execution / CI:
  Woodpecker, Jenkins, TeamCity, Azure DevOps, GitLab CI,
  GitHub Actions, GitVerse CI, Native execution

Deployment / GitOps:
  generic Kubernetes, OpenShift, Argo CD

Registry:
  Harbor, Nexus

Observability:
  Splunk
```

SCM, CI и CD не связываются жёсткими парами. Например, Bitbucket может работать
с Jenkins, TeamCity или Native execution, а GitHub — с Argo CD.

### Отложенные или исключённые провайдеры

```text
Gerrit
  P4/future; отдельную first-class интеграцию сейчас не строим.

Flux CD
  не входит в текущий first-class scope.

Deckhouse
  только bridge для Cosmoport 2.

GitVerse
  только option для Cosmoport 2; в PureK first-class scope не входит.
```

## 10. Граница Cosmoport 2

Следующие системы и маршруты относятся к Cosmoport 2, а не к PureK baseline:

```text
Deckhouse
Т1-Сфера
legacy transfer bridge
СОД
```

Для передачи данных и release packages направление такое:

```text
1. PureK sovereign/default transport — основной путь.
2. СОД — второй transport option и внешний bridge Cosmoport 2.
```

МЗП исключён из новой архитектуры.

СОД не диктует внутренний stack PureK. Внутренние Kafka/MQ-механизмы СОД, если
они подтвердятся, остаются внутри СОД bridge.

Source inspection (1 сентября 2026, non-binding:
`docs/research/2026-09-01-sod-source-inspection-worksheet.md`) подтвердил из
кода: СОД — FTP/InfoDiode transport с state machine
PREPARED→SENT→RECEIVED→DELIVERED, ZIP+MD5 packages, client-UUID idempotency;
Kafka внутри СОД — только state notifications. Обратный ACK-канал — отдельный
InfoDiode с meta-packets. Это подтверждает наш diode profile (one-way data +
отдельный control/ACK channel) и multi-plane модель (legacy уже разделял
транспорты: СОД для metadata/reports, МЗП для source/images), но не меняет
решений этого раздела.

## 11. Landing preflight и gap adaptation

### 11.1. Pre-transfer validation

После сборки release package источник обязан выполнить собственный
`PreTransferValidator`. Этот слой не принадлежит СОД и не зависит от его API.

```text
release snapshot
  → generate package
  → generate manifest
  → calculate package/object checksums
  → validate graph closure и artifact references
  → validate payload sufficiency for the declared landing mode
  → validate schema/policy/secret-leak rules
  → freeze immutable package revision
  → transfer
```

`manifest + checksum` — часть pre-transfer validation. После import target повторно
проверяет тот же checksum как дешёвый integrity invariant. Для стерильной нашей
metadata обязательный quarantine не нужен.

Metadata-only package может быть разрешён для skeleton/context landing, но не
должен молча считаться deployable release. Validator обязан различать
`metadata_only`, `deployable` и `incomplete/invalid` package modes.

Retry не означает бездумно пересобирать всё:

```text
transport timeout / temporary provider failure
  → retry same immutable package revision

package invalid / source state changed / artifact changed
  → generate new package revision
  → new manifest/checksum
  → new validation
```

Ошибки классифицируются детерминированными правилами, а не «магическим AI»:

```text
transient_network       → bounded retry/backoff
provider_unavailable    → retry, then operator-visible failure
quota_exceeded          → no blind retry; remediation или new plan
missing_integration     → block until configured
state_conflict          → reconcile или operator decision
schema/policy_invalid   → stop and report
partial_import          → resume/reconcile by idempotency key
```

Такой failure classifier и repair/retry plan — обязательная часть flaky-protected
transfer, а не логика конкретного СОД adapter'а.

### 11.2. Landing preflight и target checkup

Для стерильных PureK/Cosmo metadata не нужен обязательный quarantine или
antimalware inspection stage. Signature включается только там, где её требуют
route, policy или trust boundary.

Главная проблема при переносе между зонами — не вирус в нашей metadata, а
семантическая несовместимость target: quotas, connections, registry, RBAC,
capacity и отсутствующие integrations.

Перед фактическим применением нужен `LandingPreflight`/`TargetCheckup`:

```text
source portal
  → prepare package
  → call target checkup API, если target доступен
  → получить detailed verdict
  → approve/transfer

airgap
  → import package в target staging
  → запустить target-side checkup без side effects
  → approve/apply
```

`isLandingSafe` может быть вычисляемым итогом, но API возвращает не один boolean,
а отчёт:

```text
LandingCheckReport
  verdict: safe | unsafe | conditional
  checks[]:
    quota
    capacity
    repository/registry
    required integrations
    network/DNS/TLS
    secret references
    RBAC/service accounts
    dependencies
    manifest/schema/policy
  plan_hash
  remediation hints
```

Последовательность десантной операции:

```text
prepare
  → target preflight / dry-run
  → operator approval, если требуется
  → transfer/import
  → target bootstrap
  → reconcile
  → smoke/acceptance
```

Индустриальный паттерн — именно такой: Helm lint/template, Kubernetes server-side
dry-run, policy/admission checks и Argo CD diff перед apply/sync. Это не обещает
идеальную симуляцию runtime, но ловит большую часть ошибок конфигурации до
побочного эффекта. Для реальных зависимостей дополнительно нужен disposable
canary/smoke в target, если профиль это допускает.

### 11.3. Что такое target bootstrap

`Target bootstrap` — не просто факт, что файл доехал, и не обязательно финальный
deployment. Это материализация target-side контекста:

```text
received package
  → target Project/Application/Repository context
  → artifact references by digest
  → quota/resource bindings
  → integration bindings
  → allowed secret references
  → target IDs и durable state
```

После этого target может перейти к deployment. Успешная доставка package сама по
себе не означает, что приложение развернуто или готово к эксплуатации.

## 12. Legacy-системы, не входящие в PureK

Следующие элементы legacy не переносятся в PureK:

| Система или механизм | Решение |
|---|---|
| ABAC | Не нужен. Используем identity, RBAC, resource scoping, gates и policies |
| Ansible | Не входит в PureK; factual check только |
| vRA | Не входит. Используем универсальный VM adapter без vRA-specific semantics |
| Consul | Не нужен. Kubernetes service discovery и OpenBao закрывают baseline |
| Kafka | Не входит во внутренний PureK stack; Valkey Streams/PubSub остаются baseline |
| GlusterFS/Heketi | Исключены; storage boundary — PVC и S3/MinIO |
| Artemis/MQ | Исключены из PureK |
| TCP/ТСР runtime paths | Исключены из PureK |
| VictoriaMetrics | Factual check only; baseline — Prometheus/OpenMetrics |
| Istio | Factual check only; не является runtime dependency PureK |
| Artifactory | Исключён |
| Sfera / ДиБ | Не входит в PureK core; optional external bridge для Cosmoport 2 |


## 13. Proxy и сетевые границы

Входящий edge остаётся за Caddy. Для nongap допускается corporate outbound proxy:

```text
PureK adapters
  → HTTP_PROXY / HTTPS_PROXY / NO_PROXY
  → customer network proxy
```

Squid можно добавить как среднесрочный bridge/profile для controlled outbound
traffic, но он не входит в обязательный core и не заменяет Caddy, scanner Demon
или Kubernetes NetworkPolicy. Не добавляем Nginx, Traefik, Envoy или отдельный
service-mesh stack.

Если фактическое расследование обнаружит обязательный customer use case, сначала
формулируется отдельный requirement и capability contract. Legacy-название само
по себе не открывает интеграцию.


## 1.3. Notification Manager (МУ)

Notification Manager — собственный **portal-local bounded module** внутри
Cosmoport Control Plane. Это не отдельный deployable microservice и не
межзонный transport. На один портал/Control Plane приходится один logical МУ.

```text
Cosmo domain changes
  → PostgreSQL transaction
  → transactional outbox
  → local Notification Manager
  ├── in-app/BELL journal
  ├── email/webhook provider adapters (если включены profile'ом)
  └── SSE live projection через Valkey
```

МУ владеет notification policy, event taxonomy, recipient resolution,
idempotency/dedup, delivery journal, retry/DLQ и audit reference. Provider
libraries выполняют только доставку и не становятся источником истины.

Межзонные события не доставляются через МУ. Source и target Control Plane
передают transfer/reconcile state через выбранный transport profile; после
локальной фиксации события каждый портал сам создаёт свои уведомления.

Baseline V1: in-app notifications и email adapter; subscription policy —
`ALL` или `SELECTED` с allow/blocklist, без digest/quiet-hours/multi-tenant
complexity. Kafka, standalone Notification Service и ad-hoc SMTP paths в
PureK не входят.