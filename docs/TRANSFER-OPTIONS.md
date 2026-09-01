# PureK / Cosmoport 2 — варианты передачи через network/gap barrier

> **Статус:** рабочий план архитектуры, 1 сентября 2026 года.
> **Принцип:** PureK не навязывает заказчику один transport. Мы даём набор
> совместимых options, а заказчик заранее выбирает подходящий профиль по своей
> сетевой схеме, режиму изоляции и требованиям безопасности.
> **Важно:** СОД — только одна из options для Cosmoport 2, а не основа PureK.

## 1. Общая модель

Все options используют один PureK-owned transfer kernel:

```text
Release Snapshot
  → PackageBuilder
  → PreTransferValidator
  → immutable package revision
  → TransportAdapter
  → target staging/import
  → LandingPreflight / TargetCheckup
  → target bootstrap
  → reconcile
  → smoke/acceptance
```

### 1.1. Package envelope не равен всему release payload

`PackageBuilder` собирает прежде всего control/metadata envelope: graph проекта,
release/build identity, build/deployment order, policy и ссылки на immutable
artifacts. Source, OCI images, Nexus packages и evidence могут пересекать
границу отдельными transfer flows.

```text
metadata envelope
  → selected control transport

source refs/content
  → Git/provider transfer

OCI images
  → Harbor-to-Harbor или approved registry bridge

packages/dependencies
  → Nexus repository transfer

reports/evidence
  → S3/object transfer или отдельный evidence route
```

Один релиз может иметь несколько `TransferItem`, связанных общим
`release_id`/`transfer_plan_id`, но с собственными:

- `artifact_kind`;
- source/target provider и location;
- immutable digest/checksum;
- selected transport option;
- status, retry и recovery state;
- readiness/target checkup.

Таким образом, metadata envelope может пройти через SOD или offline media, а OCI
образы — через T1-Сфера/registry bridge. Это не противоречие, а multi-plane
transfer. Пока фактическая схема Т1-Сфера не подтверждена, она считается
Cosmoport 2 customer bridge, а не PureK core dependency.

Для одного `TransferItem` меняется канал доставки. Не меняются:

- package contract;
- manifest и checksum;
- package/revision identity;
- idempotency;
- retry и recovery rules;
- target checkup;
- audit и Evidence references;
- target bootstrap state machine.

На уровне всего release transfer может использовать несколько каналов. Общими
остаются release identity, correlation, manifest references, idempotency и
overall reconciliation; transport retry и readiness ведутся отдельно по
metadata/source/OCI/package/evidence plane.

PureK не переносит в эту модель Kafka, SOD-specific statuses, GitLab pipelines
или внутренние механизмы legacy СОД.

## 2. Option A — direct authenticated API

### Сценарий

Для nongap или разрешённого соединения между зонами:

```text
source Control Plane
  → mTLS HTTPS Transfer API
  → target Control Plane
```

### Что нужно заказчику

- сетевой маршрут source → target;
- allowlisted HTTPS endpoint;
- mTLS/private CA или согласованный TLS;
- target Transfer API;
- DNS/NTP;
- лимиты размера и времени соединения;
- обратный статусный или callback path;
- policy, разрешающая такой обмен.

### Что даём мы

- source/target transfer endpoints;
- session/idempotency contract;
- streaming/resume;
- PreTransferValidator;
- TargetCheckup;
- audit/status/recovery;
- Pretty Health probe.

### Плюсы и ограничения

- самый простой и быстрый вариант;
- подходит как nongap default;
- легко делать automatic retry;
- не подходит для настоящего one-way gap без разрешённого канала.

## 3. Option B — offline package import

### Сценарий

```text
source export
  → offline package
  → approved media/staging procedure
  → target import
  → target-side checkup
```

### Что нужно заказчику

- approved way to move files;
- operator/import station в target;
- локальный storage для временного package;
- процедура approval;
- target-side import command или portal action;
- способ вернуть ACK, если он нужен.

### Что даём мы

- versioned package format;
- `manifest.json`;
- package/object checksum;
- optional signature по policy;
- SBOM/provenance;
- `verify` и `import` commands;
- TargetCheckup без side effects;
- resume/reconcile после partial import;
- cleanup временного staging;
- exportable audit result.

### Плюсы и ограничения

- не требует сетевого отверстия;
- подходит для строгого airgap;
- понятен для removable media и controlled file exchange;
- ACK и operator workflow надо спроектировать отдельно.

Для собственной стерильной metadata quarantine не является обязательной частью.
Staging нужен для атомарности, resume, проверки целостности и recovery.

## 4. Option C — controlled transfer gateway / relay

### Сценарий

```text
source Control Plane
  → source staging
  → approved Gap Gateway / Relay
  → target staging
  → target Control Plane
```

У transfer есть lease:

```text
request session
  → policy decision
  → session_id + TTL + direction + limits
  → transfer
  → target ACK
  → close session
  → cleanup
```

### Что нужно заказчику

- transfer gateway или relay в согласованной network boundary;
- route/ACL до gateway с обеих сторон;
- direction и protocol policy;
- source/target staging storage;
- session TTL и byte limits;
- certificates/keys;
- owner, который контролирует opening/closing sessions;
- monitoring и audit gateway.

### Что даём мы

- provider-neutral `TransferSession` contract;
- session lease и one-active-transfer policy;
- package streaming/resume;
- target ACK/reconciliation;
- Pretty Health checks;
- gateway adapter, но не управление чужим firewall из application code.

### Плюсы и ограничения

- лучший универсальный вариант для controlled cross-zone exchange;
- можно реализовать как отдельный relay service/appliance;
- не требует Kafka;
- dynamic port opening из PureK запрещён;
- конкретный gateway остаётся customer/network responsibility или отдельным
  approved deployment profile.

## 5. Option D — one-way data diode / unidirectional relay

### Сценарий

```text
source staging
  → one-way transfer gateway/data diode
  → target staging
  → target-side checkup/import
```

### Что нужно заказчику

- физический или логический one-way channel;
- source-side sender;
- target-side receiver;
- подтверждённая direction;
- target-side staging;
- отдельный return control channel или operator ACK, если нужен feedback;
- policy для размера, TTL и удаления package.

### Ограничение ACK

Настоящий data diode не может вернуть ACK по тому же data path:

```text
A → B: package
B → A: только отдельный разрешённый control path
```

Если используется полноценное `A ↔ B`, это уже controlled bidirectional gateway,
а не строгий diode. Оба варианта допустимы, но это разные security models.

### Плюсы и ограничения

- максимальная изоляция направления data flow;
- подходит для наиболее строгих gap barriers;
- сложнее recovery и подтверждение результата;
- не надо пытаться «открывать дыру» из PureK-приложения.

## 6. Option E — СОД bridge

```text
PureK/Cosmo package contract
  → SODTransferAdapter
  → legacy/external СОД
```

Это option для Cosmoport 2. Она не меняет PureK-owned kernel.

Нужны факты о конкретном СОД:

- API/auth;
- statuses;
- package limits;
- callback/polling;
- idempotency;
- retry/recovery;
- target acknowledgement;
- actual gap gateway/relay topology.

Если СОД использует Kafka, это ещё не означает, что Kafka — его data transport.
Kafka может быть локальным event bus, broker bridge или частью relay orchestration.
Роль нужно подтвердить фактической схемой.

## 7. Единая матрица выбора

| Option | Сеть | Для чего | Главный риск |
|---|---|---|---|
| Direct API | Разрешённый HTTPS | Nongap, connected zones | route/TLS availability |
| Offline import | Нет live network | Строгий airgap | operator/import workflow |
| Gateway/relay | Controlled route | Управляемый cross-zone | gateway/session policy |
| Data diode | One-way | Максимальная изоляция | обратный ACK/recovery |
| СОД bridge | External legacy path | Cosmoport 2 compatibility | чужой contract/semantics |

## 8. Что планировать заказчику заранее

Для каждой пары зон заказчик должен выбрать:

```text
source zone
target zone
selected option
direction
network owner
staging owner
authentication/CA owner
package size limit
session TTL
ACK path
retention/cleanup
operator approval
```

Мы должны показывать это как deployment/route profile, а не заставлять заказчика
разбираться в реализации конкретного СОД.

## 9. PureK-first правило

Релизный package и его pre-transfer validation принадлежат PureK. Конкретная
технология crossing выбирается по customer network и security requirements.

Если реальная СОД-реализация окажется неудобной, неполной или legacy-only, это не
ограничивает PureK. Мы сохраняем собственные options A–D и подключаем СОД только
там, где он действительно нужен заказчику Cosmoport 2.
