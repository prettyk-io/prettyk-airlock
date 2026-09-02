# Cosmo PO TODO

> Владелец: Cosmo.
> Дата актуализации: 1 сентября 2026 года.
> Это рабочий список решений и вопросов PO. Он не заменяет application backlog
> и не означает, что legacy-система автоматически входит в PureK.

## P0 — узнать у коллег завтра

### 1. СОД: контракт второго transport option

> Source inspection выполнен 1 сентября 2026: `docs/research/2026-09-01-sod-source-inspection-worksheet.md`.
> Acceptance-разбор: `docs/research/2026-09-01-legacy-source-inspection-acceptance.md`.

- [ ] Получить фактическую версию и deployment manifest СОД.
- [ ] Получить API/OpenAPI/Postman и redacted request/response examples.
- [ ] Зафиксировать auth, TLS/CA, endpoints, size limits и network topology.
- [ ] Получить полный lifecycle статусов и разделение terminal/retryable states.
- [ ] Понять семантику `RECEIVED`, `DELIVERED`, timeout и partial delivery.
- [ ] Узнать idempotency key, duplicate/retry behaviour и правила recovery.
- [ ] Подтвердить checksum/signature/manifest contract и смысл legacy `hex`.
- [ ] Понять, кто и как подтверждает target bootstrap после доставки package.
- [ ] Получить trace одного реального non-sensitive package source → target.
- [ ] Получить два-три дорогих production incident и фактический operator runbook.
- [ ] Отделить обязательные ограничения СОД от деталей legacy реализации.
- [ ] Не смешивать этот discovery с PureK default transport: СОД — только внешний
      Cosmoport 2 bridge и вторая transport option.
- [x] Установить роль Kafka в реальном gap flow: local event bus СОД, cross-gap
      bridge или только внутренняя механика relay; не считать Kafka transport'ом
      без доказанного broker-to-broker/gateway flow. Код СОД: Kafka — только
      state change notifications (профиль KafkaNotifications), не data transport.
      Осталось интервью: что реально использовалось в prod — Kafka или polling.
- [x] Узнать, есть ли отдельный return control/ACK channel или ACK происходит через
      operator / отдельный разрешённый канал. Код: обратный InfoDiode с
      meta-packets + опционально Kafka. Подтверждает diode profile №2 baseline.
- [x] Понять связь data diode с Kafka в СОД: Kafka как event bus для transfer events
      или как часть relay orchestration. Код: Kafka — уведомления о смене состояния,
      не участвует в data path и не оркестрирует relay.
- [x] Изучить принцип data diode / InfoDiod и однонаправленных шлюзов. Результат:
      `docs/research/2026-09-01-data-diode-infodiod.md`. Data diode — физически
      однонаправленный канал; ACK невозможен без отдельного control-канала.
      Российские производители: InfoDiode, Цифровые решения, Инконтрол.
- [ ] Узнать, какой конкретно тип устройства используется в СОД: строгий data diode
      (InfoDiod/аналог) или controlled bidirectional gateway. Кто производитель.
      Код даёт частичный ответ: два раздельных однонаправленных FTP-канала
      (InfoDiode IN/OUT dirs); vendor и модель устройства — интервью.
- [x] Понять protocol: TCP/UDP/raw, staging/spool с обеих сторон,
      throughput/latency. Код: FTP поверх диода с обеих сторон, staging-каталоги
      на локальных PVC, файлы удаляются после sync; throughput/latency — интервью.
- [ ] Получить production-факты, недоступные из кода: актуальная топология зон
      и число инстансов СОД, реальные размеры пакетов и latency, production
      incidents, была ли альтернатива FTP в реальных deployment'ах.
- [ ] Получить схему одного реального cross-gap transfer: source staging → gap
      gateway/relay → target staging → target checkup → bootstrap → cleanup.

**Результат:** contract для `SODTransferAdapter` в Cosmoport 2. СОД остаётся
вторым маршрутом после нашего sovereign/default transport.

### 2. Airgap delivery и лицензии

- [ ] Уточнить, какие images/packages можно включать в официальный offline bundle.
- [ ] Уточнить, как передаётся лицензированный Splunk package.
- [ ] Получить допустимые версии Splunk, Harbor и Nexus.
- [ ] Подтвердить локальные Harbor/Nexus в целевых airgap-зонах.
- [ ] Зафиксировать image/package import procedure и signature verification.
- [ ] Уточнить private CA, internal DNS, NTP, proxy и egress restrictions.
- [ ] Определить upgrade/recovery flow для offline installation.

**Результат:** delivery contract для nongap и airgap без ложного правила
«третьи продукты не поставляются».

### 2a. Artifact planes и zone-local registries

- [ ] Подтвердить у DevOps, что release package является metadata envelope, а
      source, OCI images, packages и evidence передаются отдельными flows.
- [ ] Получить фактическую схему GitLab instance-to-instance transfer: repository
      mirror, bundle/import, API export/import или другой механизм.
- [ ] Получить фактический T1-Сфера flow для image promotion между Harbor
      instances: source/target registry, digest preservation, multi-arch indexes,
      signatures/attestations и SBOM.
- [ ] Подтвердить, сколько Harbor/Nexus instances живёт в каждой зоне и где
      проходит граница HA replica против zone-local copy/promotion.
- [ ] Получить Nexus flow для dependencies, package repositories и generic
      artifacts: repository type, coordinates, checksum, metadata и retry.
- [ ] Узнать, где передаются CI artifacts, Helm charts, manifests и evidence, если
      они не являются OCI image или Nexus package.
- [ ] Определить, какой correlation связывает metadata release с каждым artifact
      transfer и где находится authoritative status.
- [ ] Не предполагать, что СОД переносит весь payload: зафиксировать отдельно его
      scope для metadata, Git, OCI, Nexus и evidence.

**Результат:** multi-plane `ReleaseTransferPlan` и отдельные contracts для
metadata, source, OCI/Harbor, Nexus/package и evidence transfer.

### 3. Splunk integration facts

- [ ] Подтвердить HEC или другой разрешённый ingestion path.
- [ ] Узнать нужные index/sourcetype/source и retention requirements.
- [ ] Уточнить owner Splunk, TLS/CA и credential provisioning.
- [ ] Определить обязательные audit/security/run fields и correlation IDs.
- [ ] Проверить требования к batching, retry, offline buffering и alerting.

**Результат:** acceptance contract для `SplunkAdapter`; Splunk не становится
source of truth PureK.

### 4. Legacy factual checks

- [ ] Ansible: есть ли active production flow, кто его вызывает и без чего он
      перестанет работать.
- [ ] Istio: используется ли сейчас, какие именно функции обязательны и в каком
      runtime path.
- [ ] VictoriaMetrics: кто пишет/читает данные, для каких операций и нужна ли
      совместимость именно с VictoriaMetrics.
- [ ] Не собирать дополнительные сведения по уже исключённым GlusterFS/Heketi,
      Artemis/MQ и TCP/ТСР, если коллеги сами не предъявят current production
      evidence.
- [ ] Если у коллег есть достоверные сведения: подтвердить, что GlusterFS/Heketi,
      Artemis/MQ и TCP/ТСР действительно не входят в текущий обязательный path.

Для каждого ответа нужен источник: API, manifest, schema, test, log, document
или production incident. Одного упоминания в старом ТЗ недостаточно.

### 5. Проверка уже существующих recovery-эпиков

- [x] Получить от Keeper baseline по health, lease, broker, runtime provider,
      event bus, profiles и session recovery в PrettyK Box.
- [ ] Сопоставить их с текущим контрактом и не создавать дубли.
- [ ] Если эпики были только в PureK Box, перенести нужный pattern в Cosmoport 2
      как отдельную реализацию с собственными PostgreSQL/MinIO/OpenBao.
- [ ] Отдельно подтвердить, были ли реально сделаны backup/restore и disaster
      recovery. Session recovery и zombie GC не закрывают database/object recovery.
- [ ] Не переносить Docker-label/in-memory fallback в Enterprise как durable SoT:
      там остаются PostgreSQL и собственные persistence boundaries.

### 6. Capacity и квотирование

- [ ] Зафиксировать для PureK quota types: CPU, memory, storage, artifact size,
      concurrent runs, worker pool и security sessions.
- [ ] Описать hierarchical quota: Domain → Project/Application.
- [ ] Зафиксировать hard-limit и soft-warning modes.
- [ ] Развести в карточке две вкладки: «Квотирование» и «Интеграции».
- [ ] Для каждой интеграции показывать enabled/disabled, pending, running,
      online/healthy, failed, not_active и stale.
- [ ] Не обещать quota capability, которой конкретный Git/CI provider не имеет;
      сначала получать capability matrix от adapter.
- [ ] Использовать legacy ADR только как источник требований, не переносить
      GitLab/Deckhouse/T1-Сфера semantics в PureK автоматически.

**Найденные legacy-факты:** старое ТЗ описывает quota для CPU/RAM, storage и
artifact size, иерархические quotas, hard/soft режимы и status lifecycle
интеграций `pending → running → success/failed/not_active`. Это полезный input
для нашего generic contract, но не готовая PureK-модель.

### 7. Notification delivery — решение принято

> Source inspection выполнен: `docs/research/2026-09-01-notification-service-source-inspection-worksheet.md`.
> Facts/insights/legacy-only разложены в acceptance-записи. Legacy-стек (Kafka
> binder, PIS, Blitz, Consul, Single-SPA) не переносится; функциональность
> оценивается отдельно.

- [x] Notification Manager — portal-local bounded module внутри Cosmoport, не
      отдельный deployable service и не межзонный transport.
- [x] Источник событий — PostgreSQL transactional outbox; Kafka в PureK не
      используется. Valkey — только live/SSE projection.
- [x] МУ владеет policy, taxonomy, recipients, dedup, journal, retry/DLQ и
      audit reference; libraries являются только delivery providers.
- [x] V1 channels: in-app/BELL и email adapter. Webhook — отдельный optional
      provider profile, не обязательный канал.
- [x] Subscription V1: `ALL` или `SELECTED` + allow/blocklist. Digest,
      quiet-hours и сложная multi-tenant policy отложены.
- [x] Межзонные события идут через transfer/reconcile; каждый портал локально
      порождает собственные notifications. МУ не входит в transport matrix.
- [x] Recipient resolution V1 использует существующие Control Plane auth и
      domain/project membership; LDAP и legacy PIS не переносятся.
- [x] Каноническое событие V1: durable outbox event с event id, aggregate,
      event type, timestamp, payload и correlation id.
- [x] Delivery semantics V1: PostgreSQL inbox write = delivered; email provider
      accept = sent; retryable failure → retry/DLQ; read receipt не обещаем.
- [x] V1 taxonomy ограничена run/gate/batch/release/transfer failure и approval;
      полный legacy каталог 22+ событий не переносим.

## P1 — оформить после интервью

- [x] Выбрать multi-option PureK sovereign transfer framework: direct authenticated
      mTLS HTTPS для nongap, immutable offline package import для airgap,
      controlled gateway/relay и one-way diode/relay для gap barriers; это не
      адаптация протокола СОД.
- [x] Изучить принцип data diode / InfoDiod: однонаправленный физический канал,
      protocol break, необходимость отдельного ACK-канала. Зафиксировано в
      `docs/research/2026-09-01-data-diode-infodiod.md`.
- [ ] Оформить `DiodeAdapter` contract: send(package, session_lease), track_status,
      verify_on_target, no immediate ACK semantics. Учесть физический protocol break.
- [ ] Оформить `SODTransferAdapter` как optional второй Cosmoport 2 transport
      после общего transfer kernel; не делать СОД blocker'ом sovereign profiles.
- [ ] Реализовать Notification Manager V1 как portal-local module: outbox,
      in-app journal, email provider, dedup, retry/DLQ и SSE projection.
- [ ] Оформить `VirtualizationAdapter / EnvironmentProvisioner` с provider-neutral
      контрактом и честными `NotImplemented` capability paths.
- [ ] Подготовить friend request для VM provider только после появления реального
      use case и владельца интеграции.
- [ ] Оформить provider matrix для TeamCity, Azure DevOps и Bitbucket.
- [ ] Оформить `RegistryAdapter` для Nexus и Harbor.
- [ ] Описать multi-plane `ReleaseTransferPlan`/`TransferItem`: metadata envelope
      может иметь один transport, а Git/OCI/Nexus/evidence — отдельные approved
      transports с общей release correlation и независимым recovery.
- [ ] Оформить Harbor promotion contract с digest-preserving transfer и
      multi-arch/signature/SBOM handling.
- [ ] Оформить Nexus repository transfer contract для hosted/proxy/generic
      artifacts; не считать его автоматически Harbor replication.
- [ ] Оформить `ObservabilityExportAdapter` для Splunk.
- [ ] Описать offline manifest, OCI import, package cache, signatures и license
      boundary для airgap.
- [ ] Добавить Squid как среднесрочный optional outbound-proxy bridge/profile;
      не делать его core-зависимостью.
- [ ] Заложить Prometheus deployment profile, Grafana datasource/dashboards и
      OpenMetrics contract; Alertmanager оставить в том же operational profile.
- [ ] Включить OpenTelemetry instrumentation/correlation path; Collector сделать
      deployable optional service.
- [ ] Оформить Pretty Health как пользовательскую health-check surface/API/CLI.
- [ ] Зафиксировать quota/integration tabs и provider capability matrix.
- [ ] Заложить `IAST / RuntimeSensorAdapter` как optional capability без
      `docker.sock` в security service.
- [ ] Описать `LandingPreflight / TargetCheckup` с detailed verdict, а не одним
       boolean `isLandingSafe`.
- [ ] Подготовить network/deployment matrix для каждой transfer option: topology,
       direction, ACL/TLS, staging, ACK, TTL, owner, cleanup и recovery.
- [ ] Развести delivery, import, target bootstrap, reconcile и deployment как
       разные observable stages.
- [x] Зафиксировать обязательный baseline `manifest + checksum` в
       `PreTransferValidator`; после import checksum проверяется повторно.
       Signature и quarantine не обязательны для стерильной собственной metadata.
- [ ] Добавить target-side dry-run, quota/capacity/integration/network/RBAC checks
       и disposable smoke там, где target profile это позволяет.
- [ ] Добавить failure classifier и repair/retry plan: повторять тот же immutable
       package revision при transient transport failure, а новую revision создавать
       только при изменении/невалидности package или source state.
- [x] Получить реальный release package для примера `2+1+0` и описать его
       фактический состав, не принимая legacy format как обязательный PureK format.
- [ ] Проверить с коллегами, является ли metadata-only package нормальным режимом
       для skeleton landing или этот конкретный архив неполный из-за exporter/
       fixture behaviour.
- [ ] Зафиксировать в PreTransferValidator проверку payload sufficiency: metadata-only
       допустим только для явно заявленного skeleton/context landing, но не должен
       считаться deployable release.
- [ ] Не переносить в PureK Kafka/SOD mechanics; использовать разговор с DevOps
       как discovery доступных gap-barrier patterns и выбрать самый простой
       sovereign implementation.

## P2 — позже, только при доказанной ценности

- [ ] Gerrit: держать в самом низу backlog; не делать first-class adapter сейчас.
- [ ] Istio: рассмотреть generic traffic-policy capability только при подтверждённом
      customer runtime scenario.
- [ ] VictoriaMetrics: открыть отдельное решение только при доказанном active use.
- [ ] VM provider: выбрать конкретный adapter после фактического discovery.
- [ ] SSH/host collector для VM/Compose рассматривать только после конкретного
      runtime scenario; нужны short-lived credentials, command allowlist и audit.

## Закрыто и не переоткрывать без нового evidence

```text
ABAC         — не нужен PureK
Consul       — не нужен PureK
Kafka        — не входит во внутренний PureK stack
Artifactory  — исключён
vRA          — не переносим; используем универсальную VM boundary
GlusterFS    — исключён
Artemis/MQ   — исключён
TCP/ТСР      — исключён
МЗП          — исключён из новой архитектуры
Deckhouse    — только Cosmoport 2 bridge
```

## Напоминание PO

- [ ] Не превращать legacy inventory в PureK backlog.
- [ ] Не называть adapter «поддержкой», пока нет contract, setup, health, errors,
      recovery и acceptance.
- [ ] Не делать пустые Kafka/Consul/ABAC/Gerrit seams «на всякий случай».
- [ ] После получения фактов сначала обновить этот TODO и архитектурное направление,
      затем сортировать backlog и готовить worker packets.
