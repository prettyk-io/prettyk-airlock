# Prepared box for Boss — CP-OWN-001A

> **Статус:** подготовка к запуску worker-сессии; не канон и не implementation
> **Owner:** Boss
> **PO:** Cosmo
> **Scope:** доменный контракт ПУ для ReleaseCandidate и Observation Envelope

## Context

ПУ уже содержит несколько исторических release-поверхностей:

```text
orchestrator/cosmo/domain/release_model.py
orchestrator/cosmo/control_plane/release_orchestration.py
orchestrator/cosmo/ledger/release_envelope.py
```

`DigitalReleaseEnvelope` — существующий межзонный подписанный transport bundle. Его
нельзя переименовывать или использовать как intake-модель Findings Station:
межзонный bundle и Observation Envelope имеют разные ownership, lifecycle и
security semantics.

## Objective

Добавить production-ready domain contract для:

```text
ReleaseCandidate
  → immutable qualification proposition

ObservationEnvelope
  → versioned outbound observation/intake event

QGStatusSnapshot
  → versioned inbound status snapshot from hub for one exact candidate
```

Контракт должен быть независим от Gatekeeper Findings-моделей. Findings внутри
envelope являются наблюдениями/DTO payload, а не канонической доменной сущностью
ПУ или реализацией triage.

## Required candidate semantics

`ReleaseCandidate` фиксирует при создании:

```text
candidate_id
release_id
application_id
project_id, if applicable
build_id
commit_sha and source tree identity
artifact digest, if applicable
deployment/environment context
release type/profile id and version
resolved qualification profile snapshot
QG policy version
release origin and qualification scope
```

Правила:

- поле, влияющее на qualification, immutable после создания;
- повтор scanner/job на том же build/digest не создаёт новый candidate;
- retry создаёт новый `ScanRun`/observation attempt;
- изменение source, build, digest, deployment context или qualifying policy
  требует нового candidate;
- Development Build не создаёт ReleaseCandidate: он может создать только
  diagnostic ObservationEnvelope без candidate qualification authority;
- отсутствие artifact digest допустимо только для source-only кандидата, если это
  явно подтверждено artifact/profile semantics;
- candidate не вычисляет affected scope в V1.

## Required envelope semantics

`ObservationEnvelope` должен быть versioned и детерминированно валидируемым.
Минимальная форма:

```text
event_id
schema_version
producer
created_at
observation_id / scan_id
candidate_id, if qualification-related
origin: release_pipeline | development_build | ad_hoc_inspection | post_deploy_dast
qualification_scope: release_required | diagnostic
execution_status: PASS | FAIL | ERROR | UNAVAILABLE
context_snapshot
tool/ruleset versions
coverage_attestation
raw_report_ref
evidence_refs[]
findings[]
qwen_suggestion, optional and non-authoritative
act_ref, optional
idempotency_key
```

`context_snapshot` должен сохранять historical labels and identity, как минимум:

```text
instance/zone
project
application
repository
build + commit
artifact registry + digest
release + release type + profile version
release batch, if any
deployment/environment
```

`coverage_attestation` должен отличать `full` от `partial` и связывать coverage с
subject identity, paths/manifest hash и scanner profile/ruleset version. Partial
diagnostic observation не может сама закрыть qualifying finding.

## Validation requirements

Добавить детерминированные проверки минимум для:

- обязательной identity candidate;
- корректности origin/qualification scope pair;
- запрета `origin=development_build + qualification_scope=release_required`;
- запрета отсутствующего candidate context для qualifying observation;
- корректной связи execution status и required qualification;
- корректного `waiting | blocked | unlocked` status только для exact candidate;
- запрета PУ на трактовку status snapshot как самостоятельного QG calculation;
- непустого idempotency key;
- валидного digest формата, когда artifact digest объявлен;
- non-authoritative QWEN slot;
- immutable/snapshot semantics через model construction и serialization tests.

Не добавлять scanner-specific business branching. Scanner names и raw report
formats остаются extensible data, а не условными ветками domain engine.

## Implementation boundary

В этом пакете:

- Pydantic v2 domain models;
- enums/literals и validation;
- deterministic serialization/hash helper только если он нужен contract;
- contract-level tests, минимум 40 business/core tests;
- экспорт из domain package при необходимости.

Вне этого пакета:

- SQLAlchemy/Alembic/PostgreSQL;
- FastAPI routes и auth;
- Valkey, MinIO и callback delivery;
- Gatekeeper Findings, triage, baseline и QG engine;
- изменение старого `DigitalReleaseEnvelope`;
- изменение release orchestration/state machine без отдельного согласования.

## Acceptance

Работа принята, если:

1. Boss показывает модели `ReleaseCandidate`, `ObservationEnvelope` и
   `QGStatusSnapshot` с versioned contract и deterministic validation.
2. Тесты покрывают release, development, ad-hoc и post-deploy origins, invalid
   combinations, retry-vs-new-candidate semantics и context snapshots.
3. Contract не требует импорта из PrettyK Box или Gatekeeper.
4. Existing release and cross-zone envelope tests остаются зелёными.
5. В финальном отчёте отдельно перечислены unresolved policy questions, которые
   нельзя выдавать за решённые implementation details.

## Verification command

Из корня репозитория:

```text
python -m pytest orchestrator/tests/cosmo -q
```

Если полный suite затрагивает внешние сервисы, Boss должен отдельно показать
targeted contract test command и явно отметить skipped/UNKNOWN проверки.

## Required inbound QG status semantics

ПУ не вычисляет QG сам. Для одного exact ReleaseCandidate он читает версионируемый
`QGStatusSnapshot` от хаба:

```text
candidate identity
status: waiting | blocked | unlocked
status version
evaluated_at
policy id and version
Act reference
resolution references
flexible_override_obtained, if applicable
```

Это пассивный derived status, не команда хаба и не право хаба управлять transfer.
ПУ может начать ручной transfer только после свежего `unlocked`; затем фиксирует
snapshot в immutable Release Package evidence. Поздние факты не переписывают уже
начатый transfer package: они создают новый candidate/qualification scope.