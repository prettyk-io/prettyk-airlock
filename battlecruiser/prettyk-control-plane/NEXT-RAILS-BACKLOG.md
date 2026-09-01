# Cosmoport 2.0 — NEXT RAILS backlog

> **Статус:** живой delivery backlog  
> **Старый backlog:** заморожен; следующие задачи ведём здесь  
> **Основной канон:** `D:\prettyk-control-plane\battlecruiser\ADMISSION.md`  
> **Текущий target:** Cosmoport ПлЦР / ЗР  
> **Экипаж:** Boss, Flash, Luna, Buddy  
> **Правило:** данные и ошибки честные; неизвестное помечается `UNKNOWN`; новые каноны проходят 2FA

---

## 1. Scope текущего инстанса

```text
одна airgap-сеть / один кластер / одна зона
→ один Cosmoport instance
→ собственная PostgreSQL
→ собственный Gitea
→ собственный registry
→ локальный PrettyK-контур
```

2. QG status snapshot, который ПУ читает от хаба для exact candidate:

```text
candidate identity
waiting / blocked / unlocked
status version
policy version
Act reference
resolutions references
flexible_override_obtained, if applicable
```

Текущий lifecycle:

```text
Project → Application → Git → Build → Run → scans → PrettyK QG
→ Gates → Release → Release Package → Ready for transfer
```

ЗТ/ЗПЭ, sovereign cross-zone transport и СОД bridge — отдельные будущие
инстансы/эпики. МЗП исключён и не должен вернуться в backlog.

КИТС — optional many-to-many tag. Domain не является business tenant boundary.

Project — основная операторская сущность. Приложения равноправны; связи строятся
графом, а не обязательными L0/L1/L2 semantics.

---

## 2. Accepted delivery — completed

| Пакет | Owner | Результат |
|---|---|---|
| `PURGE-01..04` | All | Вырезан legacy scanner/crypto overengineering, тесты очищены |
| `SAN-001..011` | Flash/Luna/Boss | Санитарная волна, security perimeter, UI cleanup |
| `SAN-012..017` | Luna/Flash/Buddy | Builds/Deployments, E2E, API wiring, lifecycle, CI |
| `SAN-008..009` | Boss | SoD и линейный zone transfer contract |
| `CLN-001..013` | All | Честный frontend/backend cleanup, 0 fake production data |
| `BRG-001..007` | Buddy | Registry abstraction, local OCI, Caddy, D: relocation |
| `LR-001..009` | Luna | Project/KITS/Teams/ReleaseBatch persistence/API |
| `FR-001..004` | Flash | Minimal UI foundation, Data Grid, Projects views |
| `BR-001..008` | Boss | Project graph, visibility, ReleaseType, ReleaseBatch, Package |
| `INT-012/013/016` | Luna | KITS contract, clean DB, persistence Steel Thread |
| `INT-011/016` | Boss | Hotfix security baseline и control-plane flow |
| `INT-012/015/016` | Flash | Live Projects workspace flow |
| `INT-013/014/016` | Buddy | Provider labeling, endpoint mapping, runtime smoke |
| `OWN-BOSS-001` | Boss | Release policy и batch core, 36 tests |
| `OWN-LUNA-001` | Luna | Domain transition, Sfera research, 236 tests |
| `OWN-BUDDY-001` | Buddy | Registry/Kubernetes/D: delivery, live local OCI |
| `FINAL-BOSS-001/002` | Boss | Orchestration core и persistent pipeline |
| `FINAL-FLASH-001` | Flash | Project workspace и frontend cleanup |
| `FINAL-LUNA-001` | Luna | Backend/provider cleanup |
| `POST-BOSS-001` | Boss | Persistent release core, 38 pipeline tests |
| `POST-LUNA-001` | Luna | M:N ProjectApplication, migration boundary, 294 total |
| `POST-FLASH-001/002` | Flash | Project composition, standalone app, public library |
| `POST-BUDDY-001` | Buddy | Registry delivery, Caddy, Kubernetes digest flow |
| `STACK-BOSS-001` | Boss | Build modes и initial scan profiles |
| `STACK-LUNA-001` | Luna | Scanner contracts/adapters, 342 total |
| `STACK-BUDDY-001` | Buddy | Offline scanner fabric, K8s Jobs, 28 tests |
| `CBR-BOSS-001/002` | Boss | CodeQL matrix correction, toolchain-neutral BuildMode |
| `CBR-LUNA-001/002` | Luna | Scanner persistence/data contract, 382 total |
| `CBR-FLASH-001` | Flash | Final operator journey, 56 tests |
| `CBR-BUDDY-001` | Buddy | Reproducible local OCI runtime, Caddy `8180`, D: `10/10` |

### Последние принятые контрольные цифры

```text
Boss orchestration:  38 pipeline + 36 orchestration tests
Luna scanner/API:    382 reported passed, 0 failed
Buddy runtime:       local OCI live push/pull/digest PASS
Flash frontend:      56/56 tests, 0 TS errors
```

Счётчики разных сьютов не складываются в один «total» без единого повторного
acceptance run.

---

## 3. Accepted stack direction

### Artifact registry

```text
PureK/PrettyK:
  Nexus + Harbor

Cosmoport:
  старый Nexus → mirror/staging → Т1-Сфера
```

Artifactory не используется ни в одном active path.

### Scanner baseline

```text
Gitleaks   → secret_scan
Hadolint   → Dockerfile/build-context lint
KubeLinter → Kubernetes manifest lint
KICS       → IaC policy scan
ClamAV     → artifact content/malware scan
SonarQube  → source quality/security
CodeScoring → SCA/license
Trivy      → container vulnerability scan
KCS        → последний container scan по Build digest
```

### Contract choices

```text
SLSA      → provenance capability
CycloneDX → canonical SBOM format
```

`in-toto` не является отдельным business step. `Syft` не является отдельным
business step; он может быть генератором CycloneDX.

### CodeQL profiles

```text
PureK ordinary source:
  SonarQube + CodeQL

Cosmoport ordinary source:
  SonarQube + CodeScoring, без CodeQL до bridge

Cosmoport security/regulatory source:
  SonarQube + CodeScoring + CodeQL после bridge

Container:
  без CodeQL, SonarQube и CodeScoring
```

### Build modes

```text
Development Build:
  свободные чекбоксы, работа/отладка, не Release

Release Build:
  immutable profile, qualification/QG/Gates/Act
```

---

## 4. Findings Control Station — next architectural spine

```text
PrettyK / scanners
  → raw reports + findings + QWEN suggestions

Findings Control Station
  → canonical Finding store
  → occurrences
  → triage
  → baseline
  → approvals
  → QG evaluation

Cosmoport
  → consumes QG verdict
  → release/package readiness
```

Обязательные сущности:

```text
Finding
FindingOccurrence
TriageDecision
GateEvaluation
```

QWEN только предлагает. Человек принимает решение. Для Critical/High требуется
security approval по policy. `wont_fix` не удаляет finding и не гарантирует
разрешение релиза без действующей policy.

PrettyK остаётся execution plane и может держать summary/raw evidence refs. Детали
triage и release effect принадлежат Findings Station.

UI:

```text
MUI X Data Grid → Findings Registry
Drawer/Page       → Finding Detail
Cards/Charts      → Dashboard
React Flow        → вторичная provenance/dependency view
```

---

## 5. Open tails

| ID | Owner | Статус | Хвост |
|---|---|---|---|
| `FND-001` | Cosmo + Max | friend-request | Контракт Findings Station и QG Triage Engine |
| `FND-002` | TBD | future | Реализация Finding/Occurrence/Decision/GateEvaluation |
| `KCS-001` | TBD | friend-request | KCS как последний scan exact Build artifact digest |
| `REG-010` | Luna/Buddy | provisional | clean/dirty/raw/docs и роль KCS |
| `SFERA-001` | Max | waiting | Ответ вендора Т1-Сферы по API/урезанной поставке |
| `CODEQL-001` | TBD | future | Licensing/offline/query bundle/bridge |
| `X-STEEL-001` | All | pending | Один полный cross-stream run без смешения config-only/skipped/live |
| `STACK-001` | TBD | low | Финальная оценка Semgrep/CodeQL/Grype/cosign по явной пользе |

### Не считать blocker’ом

```text
Nexus live smoke → SKIPPED, пока нет разрешённого endpoint
T1-Sfera        → UNKNOWN, пока нет vendor/live capability proof
```

Это честные внешние зависимости, не PASS и не FAIL.

---

## 6. Следующая волна после текущего checkpoint

Следующую реализацию режем только после обсуждения/2FA контракта Findings Station.
Предварительные направления:

1. Intake API PrettyK → Findings Station.
2. Triage/baseline/QG policy.
3. Findings Control Station UI.
4. Integration с Release/ReleaseBatch.

Нельзя начинать отдельный dashboard, пока не определены Finding, Decision и
GateEvaluation.

---

## 7. Acceptance gates

### Бизнес

- ИТ-лидер может создать Project;
- Project допускает отсутствие KITS;
- drag-and-drop создаёт N applications и опциональный Project Manifest;
- standalone Application создаётся без Project;
- Public Library имеет access profile;
- приложение можно подключить к нескольким проектам без копирования репозитория;
- ReleaseType выбирается отдельно для каждого приложения;
- batch не теряет успешных siblings.

### Security/QG

- новый Critical блокирует;
- действующий разрешённый baseline не звенит без причины;
- expired decision переоткрывает блокировку;
- QWEN не принимает финальное решение сам;
- PrettyK QG и Act обязательны для package readiness;
- raw secrets отсутствуют.

### Runtime

- Build artifact фиксируется digest;
- KCS получает exact Build digest;
- Kubernetes тянет image по digest;
- GAP не ходит во внешний registry;
- Caddy Cosmoport не занимает `8080`;
- все наши env/cache/runtime пути проверены на `D:`.

### Process

- unknown не маскируется под PASS;
- skipped не маскируется под live;
- новая семантика сначала friend-request;
- канон только после второго 2FA;
- Cosmo не запускает субагентов;
- `prettyk-dev` для Cosmo readonly.

---

## 8. FINDINGS CONTROL STATION — four implementation packages

> **Статус:** next feature wave / first 2FA direction agreed
> **Цель:** собственная станция Findings и QG Triage поверх реальных результатов
> PrettyK и scanner adapters.

### Boss — FND-BOSS-001: Findings/QG domain engine

**Оценка:** 22–30 часов
**Owner:** Boss

Реализовать бизнес-модель:

```text
Finding
FindingOccurrence
TriageDecision
GateEvaluation
Baseline
```

Правила:

- stable fingerprint и dedup;
- отдельные occurrences по scanner/scan/build/release/digest;
- immutable triage history;
- statuses: `detected`, `acknowledged`, `in_progress`, `resolved`, `reopened`;
- dispositions: `false_positive`, `wont_fix`, `accepted_risk`, `suppressed`, `duplicate`;
- reason/owner/expiry/approval;
- `model_suggestion_ref` и model version;
- baseline для известных findings;
- new finding отдельно от approved baseline;
- expired decision → reopen/block;
- changed finding → reopen;
- QG effect отдельно от Finding status;
- explanation object с blockers, baseline и missing approvals.

QWEN только предлагает. Разработчик triage/propose. Critical/High approval
определяется policy. Cosmoport получает QG verdict и не пересчитывает findings.

**DoD for CP-OWN-001A:** 40+ business/core tests, deterministic dedup, baseline/new/expired
cases, QG explanation object, no scanner-specific business branching.

### Luna — FND-LUNA-001: Findings persistence and intake API

**Оценка:** 22–30 часов
**Owner:** Luna

Реализовать PostgreSQL/API:

- Finding/Occurrence/Decision/GateEvaluation/Baseline persistence;
- внешний PrettyK intake contract;
- SARIF/JSON import;
- CycloneDX linkage;
- raw report/evidence references;
- idempotent import;
- external scan id/fingerprint;
- build/run/release/artifact digest linkage;
- provider/tool/ruleset version;
- `PASS/FAIL/ERROR/UNAVAILABLE`;
- query/filter/pagination;
- triage/approval API;
- QG response с объяснением.

Минимальный PrettyK payload:

```text
scan_id
build_id
run_id
commit_sha
artifact_digest
scanner
findings[]
evidence_refs[]
qwen_suggestion
verdict
act_ref
```

Raw reports и attachments идут в object storage references, не в secret refs и не
в бесконтрольное поле PostgreSQL.

**DoD for CP-OWN-001B:** 40+ API/integration tests, clean Alembic migration, idempotent intake,
fresh-session recovery, no internal PrettyK imports, no external aggregator dependency.

### Flash — FND-FLASH-001: Findings Control Station UI

**Оценка:** 22–32 часа
**Owner:** Flash

Сделать Minimal UI/Data Grid:

#### Findings Registry

- project/application;
- release/build;
- scanner/source;
- severity;
- new/known baseline;
- disposition;
- owner;
- expiry;
- QG effect;
- filters/server-side pagination.

#### Finding Detail

- description/location;
- occurrences;
- artifact digest;
- commit/build/release;
- source scanner;
- Evidence;
- QWEN suggestion;
- triage history;
- approval;
- expiry;
- related issue/commit.

#### QG Explanation

Показывать причину решения:

```text
New Critical: 1
New High: 2
Approved baseline: 16 Critical
Expired decisions: 1
Missing approval: 1
Ready for transfer: false
```

Разработчик должен уметь acknowledge, in progress, resolved, propose
false-positive/wont-fix, comment и link commit.

**DoD:** 40+ UI/contract tests, real API errors, loading/empty/error states,
Minimal UI/Data Grid, no synthetic findings, no React Flow as primary findings UI.

### Buddy — FND-BUDDY-001: Findings runtime and evidence fabric

**Оценка:** 20–28 часов
**Owner:** Buddy

Подготовить runtime слой:

- object storage layout для raw SARIF/JSON/screenshots/logs/Act;
- immutable evidence references;
- upload/download permissions;
- retention policy;
- checksums;
- health/readiness;
- PrettyK event delivery;
- callback retry/dead-letter semantics;
- offline/GAP operation;
- MinIO/S3 config;
- Prometheus metrics;
- Compose/Helm hooks;
- Caddy route без конфликта с `8080`;
- D: cache/runtime paths.

Разделение:

```text
raw report/evidence → object storage
normalized findings → PostgreSQL
QG verdict          → API contract
```

Сразу микросервис не выделять. Внешний API boundary спроектировать так, чтобы
позже слой можно было вынести без переписывания контракта.

**DoD:** 25+ runtime/integration tests, evidence survives restart, checksums
verified, callback retry proven, GAP blocks external dependencies, no raw secrets,
no fake PrettyK events.

### Joint acceptance

```text
PrettyK scan
→ intake
→ raw evidence object
→ normalize
→ Finding + Occurrence
→ QWEN suggestion
→ developer triage
→ Admin IB approval for Critical/High
→ baseline/new comparison
→ GateEvaluation
→ QG explanation
→ Cosmoport Release readiness
```

Обязательно доказать:

- известные Critical не создают вечную сирену;
- новый Critical блокирует;
- expired `wont_fix` снова блокирует;
- QWEN не принимает решение сам;
- duplicate occurrences не плодят findings;
- raw report и Evidence не теряются.

---

## 9. CONTROL PLANE DELIVERY — stop dreaming, start shipping

> **Статус:** next implementation wave  
> **Причина:** мы напланировали три слоя Findings Station для Gatekeeper, а сами ещё не выкатили Production-ready Observation Envelope и ReleaseCandidate. Пора строить свою базу, а не раздавать теории соседу.

### Boss — CP-OWN-001A: ReleaseCandidate and qualification contract

**Оценка:** 8–10 часов
**Owner:** Boss

**Scope boundary:** domain semantics, versioned envelope shape, validation rules,
and contract-level tests. No persistence or API implementation in this packet.

Построить реальный работающий contract между Control Plane и внешним consumer
(сейчас это будет Gatekeeper/Findings Station, позже любой другой):

```text
ReleaseCandidate
→ source identity
→ Build identity
→ artifact digest
→ ReleaseType snapshot
→ deployment/environment context
→ required-step execution proof
```

И два версионируемых contract DTO:

1. Observation Envelope для отдачи в хаб:

```text
event id
schema version
producer
scan id
execution status
context snapshot
tool/ruleset versions
raw report reference
Evidence refs
findings
QWEN suggestion slot
Act reference
idempotency key
origin: release_pipeline / development_build / ad_hoc_inspection / post_deploy_dast
qualification_scope: release_required / diagnostic
```

В V1 считать ReleaseCandidate scope через фиксацию всего необходимого контекста при создании, а не через вычисление affected scope потом. Различить `Development Build` и `Release Build` в API и в persistence.

**DoD:**

- domain model ReleaseCandidate + Observation Envelope + QG status snapshot;
- versioned contract and deterministic validation;
- contract tests: creation, different origin/qualification context, invalid candidate;
- ReleaseCandidate и Observation не смешиваются с Gatekeeper Findings;
- Gatekeeper ещё не пишет implementation — мы даём ему реальный intake, а не теорию.

### Luna — CP-OWN-001B: Observation Envelope persistence and API

**Оценка:** 8–12 часов
**Owner:** Luna

**Dependency:** CP-OWN-001A accepted by Boss/PO. Luna consumes the accepted
domain contract and does not redefine its semantics in the persistence layer.

**Scope:** PostgreSQL persistence, versioned API exposure, idempotency and
integration tests for the ReleaseCandidate and Observation Envelope contract.

**Out of scope:** domain redesign, Gatekeeper Findings implementation, or
unrelated release orchestration.

**DoD for CP-OWN-001B:**

- PostgreSQL persistence and clean versioned API;
- 25+ persistence/API tests including invalid and idempotent cases;
- ReleaseCandidate and Observation remain separate from Gatekeeper Findings;
- Gatekeeper receives a real intake contract, not a theory document.

### Flash — CP-OWN-002A: Project Composition and Development Build UI

**Оценка:** 10–14 часов
**Owner:** Flash

**Scope boundary:** operator-facing Project Composition and Development Build
flow. No registry runtime or scanner execution changes in this packet.

Довести уже начатое до рабочего product surface:

```text
Project Composition:
  → drag-and-drop N folders
  → proposed N applications + dependencies
  → KITS (optional) + optional Project Manifest
  → создание N/N+1 repositories


Development Build UI:
  → свободный выбор шагов
  → diagnostic result
  → явное отличие от Release Build
```

**DoD:**

- Project создания flow доходит до материализации репозиториев и result;

- Development Build и Release Build явно различимы;
- 40+ UI/contract tests;
- 0 TS errors;
- UI показывает честные loading/empty/error states и не создаёт fake scanner data.

### Buddy — CP-OWN-002B: Build, Registry and Scanner runtime

**Оценка:** 8–12 часов
**Owner:** Buddy

**Scope boundary:** runtime/registry path and scanner capability references. No
Project Composition UI edits in this packet.

**Scope:**

```text
source Build → source checks
container Build → image push → digest
registry artifact record
Kubernetes deployment manifest by digest
scanner capability matrix for source/container/IaC
```

**Out of scope:** UI shell, drag-and-drop interaction, and unrelated findings
triage semantics.

**DoD for CP-OWN-002B:**

- image pushed by digest and Kubernetes manifest references exact digest;
- scanner profile matrix is available through the runtime/API boundary;
- 20+ runtime/contract checks;
- live non-skipped OCI push/pull passes with the registry available;
- no fake adapters and no external registry dependency in GAP mode.

### Joint acceptance

```text
Project
→ drag-and-drop composition
→ optional KITS + optional Manifest
→ N applications/repositories

Build (source/container)
→ registry digest
→ Kubernetes deploy manifest

ReleaseCandidate
→ фиксация context
→ готовность отдать Observation Envelope
```

Мы доказываем свой Production path **до того**, как режем реализацию Findings Station для Gatekeeper.
