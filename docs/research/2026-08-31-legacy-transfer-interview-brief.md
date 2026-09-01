# Legacy Cosmoport: interview brief по transfer, СОД и МЗП

> **Статус:** research. Не канон, не инструкция копировать legacy-реализацию.
> **Цель:** собрать факты у разработчиков старого Космопорта, которые меняют
> requirements ПУ, release package и cross-zone flow.
>
> **Актуальное решение:** МЗП исключён из целевой архитектуры PrettyK и
> Cosmoport 2. Он остаётся в этом документе только как historical evidence.
> Default transport будет sovereign cross-zone transport PrettyK/Cosmoport;
> legacy СОД поддерживается Cosmoport 2 как bridge integration.

## 1. Что уже доказано исходниками

### 1.1. Route и transfer attempt

В legacy `ReleaseRoute` описывал маршрут атрибутами ИТС, segment, zone, contour
и transport. У маршрута был либо `sod_code`, либо `mzp_url`, но не оба.
Пользователь вручную выбирал один или несколько доступных маршрутов и
подтверждал перенос. Для каждой попытки создавался `PackageTransfer` со
статусами `pending`, `in_progress`, `success`, `failed` и audit history.

**Источники:**

- `app/models/release_route.rb`;
- `app/models/release_route/package_transfer.rb`;
- `LCZD 3.3`, §§ 5.1, 6.3.1.

### 1.2. Состав package ЗР → ЗТ

Legacy-последовательность формирования:

```text
create package record
→ clone repository and create Git bundle
→ archive release attachments
→ export resource attributes/files when applicable
→ download binary artifact when applicable
→ generate YAML metadata
→ make tar.gz package archive
→ upload to СОД
```

Metadata содержали project/release/build/repository данные, owners, runtime и
pipeline references, release type, resource attributes, environment profiles,
references to package contents and checksums. Source bundle фиксировал selected
release branch and commit, хотя clone забирал all refs.

**Источники:**

- `app/services/packages/transfer_release_to_test.rb`;
- `LCZD 3.3`, § 6.3.2.

### 1.3. СОД behaviour в legacy

Загрузка в СОД была multipart upload с размером, domain, MD5 checksum, subject и
файлом. В ответ сохранялся внешний package id. Наблюдаемый современный response
показывает внешний UUID, `type: OUT`, `protocol: QUIC`, `domain`, `systemId`,
payload name/size, `hex`, timestamps/expiry и историю state changes:

```text
PREPARED → SENT → RECEIVED → DELIVERED
```

ПУ поллил его status; legacy mapping:

```text
DELIVERED / RECEIVED → success
EXPIRED / REJECTED / LOST / BROKEN → failed
other/transport error → in_progress until timeout
```

В старом коде были пять retries отправки, по 60 секунд, и timeout наблюдения 10
минут. Это legacy implementation detail, не готовое правило ПУ 2.

**Источники:**

- `app/services/sod/package/release_route/upload.rb`;
- `app/services/sod/package/release_route/get_status.rb`;
- `app/services/release_routes/update_package_transfer_statuses.rb`;
- `app/services/packages/transfer_release_to_test.rb`.

### 1.3a. Наблюдаемый response СОД

В предоставленном ответе `sod-initial/?search` каждый исходящий package содержит
как минимум:

```text
id, type: OUT, state, domain, systemId, protocol: QUIC, subject,
payloadName, bytes, hex, createDate, processedDate, expiredDate,
details.stateChanges[]
```

Наблюдаемый happy path:

```text
PREPARED → SENT → RECEIVED → DELIVERED
```

`hex` содержит 32 шестнадцатеричных символа, но его алгоритм нельзя считать
подтверждённым только по форме поля. Legacy Cosmoport отправлял MD5; ПУ 2 должен
требовать собственный SHA-256-based manifest/integrity contract независимо от
того, что проверяет СОД bridge.

### 1.4. Приём в правой зоне

В старой схеме приём проходил этапы `metadata → metadata_loaded → artifacts →
finished`. В production-specific implementation приемник запускал отдельные
GitLab pipelines для metadata и artifacts, поллил их, затем создавал либо
обновлял project/release по полученным metadata. Metadata pipeline сначала
применял metadata, затем запускал artifact pipeline. Для `raw_docker` artifact
pipeline metadata применялись повторно с retry `10, 20, 40, 80, 160` секунд,
если источник ещё не был готов.

Legacy loader искал уже существующий project по code или source id и release по
tag/source id. Это **не совпадает автоматически** с принятой direction ПУ 2:
после ЗР→ЗТ мы хотим новый самостоятельный ЗТ context/repository skeleton, а не
неявный update прежней сущности.

**Источники:**

- `app/models/release_reception.rb`;
- `app/services/release_receptions/start_metadata_transfer.rb`;
- `app/services/release_receptions/start_artifact_transfer.rb`;
- `app/services/packages/load_releases_from_test_kcoi.rb`.

### 1.5. Legacy ЗТ → ЗПЭ

В LCZD описан отдельный сценарий: в ЗПЭ нет обычного СОД path; ПУ запускал
GitLab pipeline/runner, который обращался к Т1‑Сфере ЗТ. После доставки ПУ ЗПЭ
загружал metadata и создавал/обновлял карточку. Фактический code подтверждает,
что `TransferReleaseToProd` повторно формировал почти тот же `tar.gz` package,
что и путь ЗР→ЗТ. В ЗПЭ затем создавался `ReleaseReception`; metadata и
artifacts доставлялись отдельными GitLab pipelines. Успех означал готовность
target space, а не отдельный deployment record ПУ.

Это важный исторический факт, но не доказательство будущей архитектуры. Наша
принятая direction: ЗПЭ находится в cluster ЗТ, использует ЗТ repository и уже
квалифицированный Build/package, а ПУ делает deployment без новой сборки,
DAST или QG.

**Источник:** `LCZD 3.3`, § 6.3.3.

### 1.6. МЗП в legacy — исключённый historical path

МЗП был альтернативным transport для `ReleaseRoute`, а не дополнением к СОД.
Для запуска legacy создавал impersonation token пользователя и передавал его в
GitLab pipeline МЗП вместе с URL репозитория, commit hash, URL МЗП и типами
поставки. Поддерживаемые типы: `B01` (source), `D01` (container images), `A01`
(binaries), `A11` (npm dependencies), `A21` (mixed files). Callback считал
delivery успешной при наличии `supply_id`; после завершения всех deliveries
legacy отзывал impersonation token.

Путь неполон: `last_git_commit_hash` оставлен `TODO`. Он также пишет credentials
и transfer variables в pipeline surface. Это evidence существовавшего
операционного маршрута, но не готовый security или idempotency contract для ПУ
2.

**Источники:**

- `app/services/transfers/mzp_transfer_release.rb`;
- `app/services/transfers/mzp_delivery_run.rb`;
- `app/services/transfers/mzp_delivery_handler.rb`.

## 2. Что из legacy нельзя копировать автоматически

- MD5 вместо SHA-256 для integrity;
- raw credentials в pipeline variables/configuration surface;
- неявное create-or-update target project по code/source id;
- GitLab/Sidekiq как неотделимая transport implementation;
- fixed retries/timeouts без evidence о реальном SLA;
- отсутствие CI coverage для transfer subsystem;
- `TODO` для last commit hash в МЗП path;
- МЗП в active/new product paths: он исключён product decision.
- success callback только по наличию внешнего `supply_id`, без доказанного
  immutable package-manifest verification.

## 3. Decision-changing gaps для ПУ 2

### A. СОД и package transport

1. Какая реально используемая версия/API СОД, authentication, size limits,
   checksum/signature requirements, idempotency behaviour и callback/polling
   semantics?
2. Какие terminal/intermediate statuses СОД действительно возвращает и какие
   из них требуют retry, human action или запрещают повторную отправку?
3. Может ли один transfer package быть доставлен повторно без дублей в target,
   и какой key связывает retries одной попытки?
4. Как target узнаёт, что package уже полностью доставлен и не частично?

### B. Package contract и reconstruction

5. Какой минимальный состав package обязателен для реального deployment, а что
   legacy таскал «на всякий случай»?
6. Что должно быть в metadata для однозначной reconstruction Project,
   Application, repository, Build, artifact digest, release type и route?
7. Какие settings/env/resource/RBAC данные допустимо переносить, какие должны
   быть заново заданы в ЗТ и какие никогда не должны покидать ЗР?
8. Как гарантируется соответствие source, Build, binary/image and deployment
   artifact — особенно после retry?

### C. ЗТ / ЗПЭ lifecycle

9. Какая фактическая последовательность после приема package в ЗТ: repository,
   artifact registry, Build record, deployment, lifecycle steps, human action?
10. Какие объективные ограничения отличают ЗТ→ЗПЭ от ЗР→ЗТ сегодня: cluster,
     network, registry, СОД, T1‑Сфера?
11. Какие facts нужны для публикации «В эксплуатации» во всех ПУ zone contexts,
    и кто их подтверждает?

### D. Route, recovery и security

12. Какие маршруты допустимы для одного release и почему legacy разрешал
    multiple route selection? Для ПУ 2 нужна линейная цепочка либо реальная
    fan-out модель?
13. Что происходило при частично созданном target repository, частично
    загруженном artifact или повторной доставке metadata? Как операторы это
    чинили в реальности?
14. Какие реальные инциденты transfer были самыми дорогими и что разработчик
    переписал бы первым?
15. Какие legacy МЗП constraints могут оставаться нормативными для СОД bridge
    (если такие есть)? МЗП как новый path исключён и не проектируется.

### E. Evidence checklist для встречи с DevOps СОД

На встрече не нужны raw secrets. Нужны разрешённые для просмотра или экспорта
артефакты, которые позволяют построить adapter contract:

1. deployment manifests: Helm/Kustomize/Compose, image names and versions,
   entrypoints, mounted configuration;
2. API surface: OpenAPI/Swagger, Postman/Newman collection, endpoint list,
   auth mode and redacted examples request/response;
3. network topology: client/acceptor addresses, ports, QUIC/TLS/certificate
   ownership, ingress/egress constraints between clusters;
4. Kafka contract: cluster/topic names, producer/consumer ownership, key,
   schema/headers, retention, consumer group, retry/DLQ semantics;
5. package contract: accepted content types, limits, manifest, `hex` algorithm,
   checksum/signature verification, expiry and cleanup;
6. operation trace of one real non-sensitive package from source submission to
   target bootstrap, including correlated identifiers and logs;
7. target bootstrap: controller/job/worker, idempotency key, project/repository
   creation, integration setup, RBAC/quota rules and success/failure callback;
8. recovery: retry behaviour, duplicate delivery, partial package, acceptor
   downtime, Kafka replay, expiry, operator runbook and monitoring/alerts.

Kafka здесь относится только к внутренностям внешнего СОД. Это не разрешение
добавлять Kafka в stack ПУ: внутри ПУ остаётся утверждённый Valkey contract.

## 4. Вопросы по ролям legacy-команды

| К кому | Нужные факты, не мнение |
|---|---|
| Разработчик transfer/СОД | Раздел 3 целиком; sequence, contracts, failure/retry, real incidents. |
| Backend lifecycle/release | State-machine invariants, Release/Package/Build identities, dependency batch semantics, source of status after target reception. |
| QA | Реальные test cases, untested boundary, regression history, fixtures, production defects, expected recovery assertions. |
| Frontend | Operator-critical screens: route selection, confirmation, disabled states, progress/history/error detail, notifications and RBAC visibility. |
| Аналитик | Нормативные/бизнесовые требования, definitions of zone/route/package, actor permissions, what is a current contractual requirement versus obsolete implementation. |

## 5. Interview principle

Не спрашивать «как у вас устроено вообще». Для каждого ответа нужно получить:

```text
real current behaviour
source of proof: service/API/schema/test/log/document
why the constraint exists
what breaks if ignored
whether it is mandatory for a future system or legacy-only
```

ПУ 2 берёт confirmed constraints and operator pain. Он не обязан наследовать
legacy data model, raw-secret handling, Rails jobs или transport details.