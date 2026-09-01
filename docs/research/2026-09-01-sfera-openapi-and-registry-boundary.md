# Sfera OpenAPI и registry boundary

> **Статус:** рабочее исследование / planning input, 1 сентября 2026.
> **Решение:** Sfera/ДиБ закладывается в Cosmoport 2 как внешний optional bridge;
> PureK получает provider-neutral registry boundary с Harbor + Nexus + MinIO/S3.

## 1. Что фактически есть в discovery

Источник:

```text
D:\cosmo\cosmo-frontend-to-scrape\Sfera_OpenAPI
```

Это локальный browser scrape, а не экспортированный OpenAPI JSON/YAML. Снимок
сделан с:

```text
https://sfera.apps.dh5.dev.ppod.cbr.ru/ppdl/administration/openapi
```

В наборе есть страницы/ресурсы для `API`, `Search`, `job`, `conf` и `sec`, общий
Sfera shell и microfrontend bundles (`sfera_core_container` и
`sfera_home_page_container`). В HTML виден authenticated user context и Sfera
application base path. Это достаточно, чтобы подтвердить существование
операторской API-поверхности и использовать scrape как discovery evidence.

Из этого набора **нельзя честно извлечь подтверждённый provider contract**:

- endpoint paths, schemas и security schemes не зафиксированы как machine-readable
  OpenAPI document;
- UI JavaScript — minified frontend implementation, не контракт интеграции;
- не подтверждены transfer semantics, job/status lifecycle, idempotency, checksum,
  limits, callback/polling и error mapping;
- не подтверждено, является ли Sfera тем же самым СОД bridge или соседней
  системой ДиБ.

## 2. Решение для Cosmoport 2

Cosmoport получает отдельный внешний provider seam:

```text
Cosmoport ProviderBinding / ArtifactRef
  → SferaProviderAdapter
  → Sfera REST / OCI registry / raw repositories
```

Рабочее имя — `SferaProviderAdapter`. Отдельный `SferaTransferAdapter` появится
только если фактическая Сфера действительно является cross-zone transport
coordinator, а не только artifact platform. Adapter остаётся optional customer
integration и не проникает во внутренние модули Sfera. Внутренний Cosmoport
contract не меняется:

- immutable package revision, manifest и SHA-256 integrity;
- correlation/idempotency key;
- отдельные delivery, import, verification и bootstrap states;
- bounded retry/recovery и audit/evidence references;
- provider-specific credentials только через secret references.

В Control Station в будущем показываем не произвольный HTTP client, а controlled
provider setup, `Test connection`, capability status и artifact/repository
operations. Transfer history относится к Cosmoport transport layer, а не
автоматически к Sfera.

## 3. Что нужно получить до implementation contract

Для Sfera нужны redacted и разрешённые артефакты:

1. OpenAPI JSON/YAML или Swagger export с версией и base URL;
2. auth/TLS/private CA scheme и scope/role matrix;
3. один non-sensitive request/response для create/submit;
4. job или transfer status schema и terminal/intermediate states;
5. polling/callback/webhook semantics, timeout и rate/size limits;
6. idempotency, duplicate submission и correlation rules;
7. checksum/signature/package envelope requirements;
8. redacted trace одного успешного и одного failed transfer;
9. recovery behaviour для partial import, provider downtime и expired job.

Для базового push/pull и provisioning этого уже достаточно, чтобы сделать
adapter с contract tests и fake/live boundary. COS-049 нужен для аккуратной
фиксации evidence и дальнейшей проверки версии/совместимости, но не является
implementation blocker. Реальный OpenAPI нужен только для операций, которых
нет в legacy client или которые требуют точной live-семантики: repository
listing/exists, copy/promotion, job/status, quotas, signatures, pagination и
точного auth/error contract.

## 4. PureK artifact/provider boundary

Для PureK baseline достаточно и правильно оставить четыре plane:

| Plane | Provider | Ответственность |
|---|---|---|
| Source | Git provider (Gitea/GitLab adapter) | refs, bundles, source identity |
| OCI | Harbor | images, manifests/layers, multi-arch, SBOM/signatures/attestations |
| Package | Nexus | dependencies, package coordinates, proxy/cache, generic artifacts |
| Evidence/blob | MinIO/S3 | scan outputs, reports, evidence и большие immutable objects |

Следовательно, PureK не нужен ещё один registry provider на baseline. Artifactory
и собственный registry не добавляем. Дополнительная работа нужна не в виде
третьего registry, а в capability contracts и adapters:

- digest-preserving Harbor promotion/transfer;
- Nexus repository/package transfer с отдельной семантикой от Harbor;
- MinIO/S3 object transfer и verification;
- Git source transfer;
- SBOM/signature/attestation references;
- multi-plane transfer plan, где metadata envelope, source, OCI, package и
  evidence имеют собственный status/recovery path.

Если заказчик позже предъявит другой обязательный provider, это отдельный
provider requirement и adapter, а не причина размывать PureK baseline.

## 5. Как передаём release между ЗР и ЗТ

### 5.1. Один логический package set, не обязательно один физический архив

Правильная единица передачи — **immutable release package set**:

```text
release_id (logical identity)
  + package_revision
  + transfer_plan_id
  + manifest.json
  + TransferItem[]
```

`manifest.json` и release/project graph metadata должны быть частью одного
подписанного/захешированного control envelope. Payload planes могут пересекать
границу отдельными items или потоками, но обязаны ссылаться на ту же
`package_revision` и иметь собственные digest, provider, target и receipt.

Минимум, который всегда должен быть логически связан:

- release snapshot, project/application graph и build/deployment order;
- target landing mode и lifecycle policy;
- source commit/repository identity и список artifact references;
- `TransferItem` для каждого ожидаемого source/OCI/package/evidence payload;
- SHA-256 manifest/checksums, correlation и idempotency keys;
- secret references и integration declarations, но **не секреты**.

Не обязательно физически держать в одном архиве:

- Git bundle;
- OCI images/layers;
- Nexus packages/generic artifacts;
- reports/evidence blobs.

Большие payloads лучше передавать отдельными resumable items. Один package set
сохраняет атомарный смысл и audit correlation, но не превращается в гигантский
монолитный tarball.

### 5.2. Payload modes

Нельзя одним флагом `deployable` скрывать разные сценарии. Нужны явные режимы:

```text
rebuild_in_target
  envelope + Git bundle + required build inputs/references
  → target lifecycle starts at SAST → Build

promote_existing_build
  envelope + exact immutable OCI/package artifacts + provenance/evidence
  → target may verify/import and continue by policy

metadata_only
  envelope only
  → skeleton/context landing; never silently deployable
```

Для обычного ЗР → ЗТ default рекомендуем `rebuild_in_target`: source bundle
передаётся, target materializes repository, затем создаёт новый target Build и
начинает локальный lifecycle с SAST + Build. Source artifacts из Harbor/Nexus в
этом режиме могут быть build inputs/cache или provenance references, но не должны
молча считаться результатом target build.

`promote_existing_build` остаётся отдельным policy-approved режимом для случаев,
когда повторная сборка запрещена или бессмысленна. Тогда Git bundle может быть
нужен для audit/reproducibility, но не обязан быть runtime input. Ни один режим не
разрешает target принимать только metadata и считать релиз готовым.

### 5.3. Landing и split

Предлагаемый порядок на target:

```text
receive package set
  → verify transport framing + manifest + item digests
  → LandingPreflight / detailed LandingCheckReport
  → isLandingApproved (derived verdict, not the whole report)
  → split by payload plane
   → import/promote Git, Harbor, Nexus, MinIO and optional Sfera provider items
  → reconstruct target context and integration bindings
  → target-side receipts/reconcile
  → ready_for_lifecycle
  → SAST → Build → next target stages
```

`split` может начинаться технически в staging после integrity verification, но
никаких внешних side effects до `isLandingApproved` быть не должно. После approval
репозиторий действительно можно отстыковать от общего landing path и передать в
target Gitea/Git provider; то же относится к OCI, Nexus и evidence. Landing
остаётся durable coordinator, а не обязательным местом хранения всех байтов.

Важно: в target не импортируется сырая строка из PostgreSQL. Переносится
семантический release snapshot, после чего создаётся target-side release context
с ссылкой на `source_release_id`, `package_revision` и receipts. Так сохраняются и
сквозная трассировка, и самостоятельный ЖЦ ЗТ.

Integration reconstruction должна разрешить все bindings отдельно:

```text
target release context
  ├── target Git repository / Gitea
  ├── target Harbor repository или approved promotion
  ├── target Nexus repository/package coordinates
  ├── MinIO/S3 evidence objects
  └── Sfera/ДиБ — только если этот provider назначен route policy
```

Sfera в этом flow может быть optional artifact provider для raw/OCI/package.
Она не считается автоматически transport coordinator. Если deployment окажется
через Sfera-controlled cross-zone job, это добавляется отдельным transport
adapter после подтверждения фактов.

## 6. Три transport profiles, которые стоит поддерживать

Наружу лучше показывать три профиля, а не плодить отдельный option для каждого
gateway/vendor:

1. **Connected Gateway** — direct mTLS API или customer-controlled relay. Это
   основной быстрый nongap/managed-gap путь; мы сами полируем session lease,
   resume, ACK, retry, reconciliation и `TransferItem` contract.
2. **Offline Package** — signed/checksummed export → approved media/staging →
   target import. Это основной строгий airgap путь; мы сами полируем builder,
   verifier, importer, preflight и recovery.
3. **One-way Diode Gateway** — source spool → customer-installed physical diode /
   unidirectional gateway → target spool. Это отдельная security model, поэтому
   её стоит оставить третьим профилем. Физический diode не строим; делаем
   vendor-neutral `DiodeAdapter` с chunk framing, sequence, per-item digest,
   replay/idempotency и внешним status/ACK channel.

Вендор оборудования (InfoDiod или другой approved product; на рынке есть разные
промышленные и enterprise решения) не должен попадать в PureK core. На уровне
product contract нам нужен наш sender/receiver protocol и adapter seam, а
конкретная appliance/API/file-spool интеграция — deployment profile заказчика.

## 7. Что нашлось в legacy Cosmoport backend

После просмотра `D:\cosmo\cosmoport\backend` гипотеза подтвердилась, но с
важной поправкой: Sfera и СОД в legacy — **разные вещи**.

### 7.1. Реальный Sfera client и создание ресурсов

`backend/lib/sfera/client.rb` содержит рабочий REST client:

```text
POST   /api/auth/login
REST   /app/ppdl/api/rest
CORE   /app/ppdl/api/rest/core
SEC    /app/ppdl/api/rest/security-service/v1
PUT    <repo_url>/raw/<repo>/<path>
```

В client есть операции:

- `create_area(key:, name:)` — создание проектной области;
- `create_repository(format:, type:, name:, area_key:, blob_store_ids:, options:)`;
- delete area/repository;
- raw tree/file download и raw file upload;
- Docker tree listing/detail/delete;
- Bearer authentication.

`Integrations::EstablishSfera` — именно тот «создающий» orchestration, который
искали: он создаёт area, затем `docker`, `dirty_docker`, `raw`, `docs`, при
необходимости service users/roles, делает rollback уже созданных объектов и
пишет audit event `create`. Это сильное evidence для будущего Cosmoport
`ProvisionIntegration`/`ProviderSetup`, но не повод копировать Ruby flow.

### 7.2. Sfera умеет быть artifact platform

Legacy использует Sfera не только для UI-ссылки. Найдены:

- `Sfera::BinaryPusher` — загрузка Docker tar как OCI blobs + manifest через
  `/v2/...`;
- `Sfera::BinaryFetcher` — скачивание Docker manifest/config/layers с range/resume
  retry;
- `GetDockerImageChecksums` — чтение checksum из Docker tree;
- raw repository для release metadata, Git bundle, docs и бинарных файлов;
- Maven repository names `trusted`/`closed` в lifecycle parameters.

Значит, в Cosmoport Sfera можно моделировать как optional **artifact provider**
(`raw`, `oci`, `package` capabilities), а не только как transfer bridge. Однако
для PureK baseline остаётся Harbor + Nexus + MinIO/S3 + Git; Sfera — customer /
Cosmoport integration, пока не подтверждён её обязательный статус.

### 7.3. Реальный legacy release flow

`Packages::TransferReleaseToSfera` (комментарий: ЗТ → ЗПЭ без прямого канала)
делает практически ровно то, о чём ты говорил:

```text
generate Git bundle
archive attachments/resources/exports
download binary artifact from Sfera
generate release metadata
build package archive
upload Git bundle to Sfera raw
upload package archive to Sfera raw
upload metadata last
```

Метаданные публикуются последними как **readiness sentinel**: наличие metadata
означает, что bundle/archive уже загружены. Это полезный legacy pattern, но в
Cosmoport 2 его надо усилить manifest + per-item checksums + package revision +
target receipts; порядок загрузки metadata last сам по себе не является
атомарностью.

Для обычного ЗР → ЗТ legacy `TransferReleaseToTest` формирует Git bundle,
attachments, resources, exports, binary artifact и YAML metadata, после чего
отправляет архив через `Sod::Package::ReleaseRoute::Upload`. На target
`LoadReleasesFromDev` распаковывает его, может положить bundle/metadata в Sfera,
а затем создаёт или обновляет Project/Release и создаёт Build.

### 7.4. Где реально находится event

Отдельного доказанного `Sfera create release event` в просмотренных файлах нет.

`ReleaseEvents::Create`:

1. создаёт локальную запись `release_events`;
2. для non-dev отправляет JSON через `Portal::Client` на
   `/external/package/release_events` в другую инсталляцию Cosmoport.

То есть event — это **Portal-to-Portal release lifecycle event**, а не Sfera
API call. В Sfera есть create area/repository и raw object uploads. Это важно не
смешать в новом дизайне:

```text
release lifecycle event → Control Plane / target API
artifact/resource setup  → Sfera or Harbor/Nexus adapter
cross-zone transport    → Connected / Offline / Diode profile
```

`SFAS_*` в `repository_params.rb` — runtime variables для build/lifecycle
инструментов (`SFAS_URL`, `SFAS_REPO_URL`, `SFAS_RAW_REPO`, Maven и credentials),
а не название самостоятельного transfer protocol. Возможно, SFAS — внутреннее
legacy naming для Sfera integration, но это не доказывает отдельную систему.

### 7.5. Что не переносим

Legacy backend содержит опасные для нового дизайна shortcuts:

- MD5 в общем `Packages::Base#checksum`;
- SSL verification disabled вне production в Sfera client и registry clients;
- credentials в lifecycle/pipeline variables;
- create-or-update target project по legacy IDs;
- Sfera metadata-last sentinel без set-level atomic commit;
- SOD retry/timeouts как жёсткие правила.

Берём оттуда sequence и capability evidence, но не эти security/state
семантики.
