# Control Plane → Gatekeeper supply contract

> **Статус:** friend-request / architecture workbench / no implementation yet  
> **Цель:** определить, какие сущности и факты Control Plane поставляет Gatekeeper,
> чтобы Findings/QG работали на реальных Project/Application/Build/Release context

## 1. Ownership

### PrettyK Control Plane owns

```text
Instance/zone
Project
KITS tags
Application
Project/Application Team
Repository
Build
Artifact digest
ReleaseType
Release
ReleaseBatch
Deployment
required-step execution state
```

### PrettyK SecOps Studio owns

```text
security session request
scanner/browser/DAST execution
raw result
raw Evidence
final DAST PASS/FAIL
final Act
```

### Gatekeeper owns

```text
Finding
FindingOccurrence
TriageDecision
Baseline
GateEvaluation
QG explanation/clearance
```

Gatekeeper does not duplicate lifecycle ownership of Project/Application/Build or
Release. It stores immutable external references and context snapshots.

---

## 2. Context hierarchy

```text
Instance / zone
  → Project
    → Application
      → Repository
      → Build
        → Artifact digest
        → ScanRun
      → Release
        → Release Candidate / Attempt
          → QG evaluation
```

KITS is orthogonal:

```text
Application ←→ KITS tags
```

KITS controls filtering and visibility. It is not a Gatekeeper tenant boundary
and not a replacement for Project/Application ownership.

## 3. Context projection

Gatekeeper needs current labels for the operator, but must not own or mutate
Control Plane entities.

For every intake/evaluation it receives a context snapshot:

```text
instance id / zone
project id + display name
application id + app code + display name
KITS tags at observation time
repository reference
build id + commit SHA
artifact registry + immutable digest
release id + release type + profile version
release batch id, if any
deployment/environment reference
```

The immutable snapshot protects historical explanations after a Project/Application
is renamed, re-tagged or moved. A separate read-only sync/query contract may later
refresh current display labels; it does not rewrite history.

---

## 4. Three supply paths

### A. Qualifying Release Scan

```text
Release Candidate
→ required profile steps complete
→ qualifying deployment
→ PrettyK SecOps Studio DAST/AppSec
→ findings/Evidence/Act
→ Gatekeeper QG
→ clearance to Control Plane
```

This is the only path capable of contributing to `OK_TO_TRANSFER`.

### B. Development Build Scan

```text
Development Build
→ selected checks
→ findings/Evidence
→ Gatekeeper Registry
```

It is useful for developers and testers, but:

```text
not a Release
not a qualified scan
not a ReleaseBatch member
not transfer evidence
```

### C. Ad-hoc Inspection Request

```text
file/archive/image/repository/manifest
→ PrettyK SecOps Studio inspection profile
→ execution result
→ Gatekeeper Finding/Occurrence/Evidence
```

It is diagnostic. It may create important Findings, but cannot replace mandatory
release pipeline checks or manufacture `PASS_GRANTED`.

---

## 5. One observation envelope, explicit qualification

All three paths send one versioned observation envelope. It must explicitly say:

```text
origin:
  release_pipeline | development_build | ad_hoc_inspection | post_deploy_dast

qualification_scope:
  release_required | diagnostic
```

The envelope also carries:

```text
event id / schema version / producer
scan id / execution status
context snapshot
tool/ruleset versions
raw report reference
evidence references
findings
QWEN suggestion, if present
act reference, if present
idempotency key
```

No direct DB writes from Control Plane/Studio into Gatekeeper.

---

## 6. Release Candidate / Attempt

An enormous pool of findings cannot be evaluated against an abstract release name
alone. QG must operate on a concrete candidate:

```text
Release 1.8.0
├── Candidate A
│   ├── Build B1
│   ├── artifact digest D1
│   ├── scan runs / findings
│   └── BLOCKED
└── Candidate B
    ├── Build B2
    ├── artifact digest D2
    ├── scan runs / findings
    └── PASS_GRANTED
```

The candidate/attempt becomes the exact scope for:

- required steps;
- Studio verdict and Act;
- Findings Occurrences;
- QG evaluation;
- clearance;
- Release Package.

Old candidates are not overwritten. They remain audit history and can be marked
failed, superseded or abandoned.

Exact naming (`ReleaseCandidate`, `ReleaseRevision`, `ReleaseAttempt`) requires
separate decision before implementation.

### Proposed decision: ReleaseCandidate

`ReleaseCandidate` is the recommended name. It describes a concrete candidate
for admission rather than a mutable release label or an arbitrary retry.

```text
Release
  → logical business release/version

ReleaseCandidate
  → immutable qualification proposition
  → specific source/build/artifact/policy context

ScanRun
  → one execution attempt against that candidate
```

### Candidate identity

A ReleaseCandidate is bound to an immutable context:

```text
release id
application id
commit SHA / source tree identity
build id
artifact digest, if artifact exists
deployment/environment context
ReleaseType profile snapshot
scanner profile/ruleset versions
QG policy version
```

Changing code, build output, artifact digest, deployment target or qualifying
policy creates a new candidate. Existing candidates remain history.

---

## 6a. Scan retries, absence and false resolution

### Same candidate: new ScanRun, never report overwrite

An execution/transport retry against the same immutable candidate creates a new
ScanRun:

```text
Candidate A / digest D1
├── ScanRun 1 → ERROR
├── ScanRun 2 → PASS, Finding F observed
└── ScanRun 3 → PASS, Finding F not observed
```

The old report and occurrence remain immutable. A later report never deletes or
rewrites historical FindingOccurrence.

### Why one clean report cannot resolve everything

A report with zero findings can be incomplete, narrowed to one file, based on a
different ruleset, or produced from another source scope. It cannot silently
claim that all historical findings are fixed.

Every ScanRun must therefore carry a coverage attestation:

```text
subject identity
scope: full | partial
source tree/artifact digest
paths or manifest hash
scanner profile/ruleset version
execution status
```

```text
partial diagnostic scan
→ may create Findings
→ may not resolve/close a qualifying Finding

full qualifying rescan of the expected candidate scope
→ may confirm absence for that candidate
→ does not erase older occurrence history
```

### Remediation produces a new candidate

Fixing a finding means changing code, manifest or artifact:

```text
Candidate A / commit C1 / digest D1
→ patch
→ Candidate B / commit C2 / digest D2
→ full relevant qualifying scans
→ absence confirmation for Candidate B
```

`resolved_for_candidate` is a scoped conclusion. It does not mean the same
Finding is resolved in old builds, other applications or other releases.

---

## 6b. ReleaseType, scanner profiles and policy snapshots

ReleaseType is not a loose label. It resolves to a versioned qualification
profile:

```text
ReleaseType
→ Lifecycle Profile
→ Scanner Profile bindings by artifact kind
→ tool/ruleset configuration versions
→ QG policy version
→ approval policy
→ Evidence/Act requirements
```

Each candidate stores the complete resolved snapshot.

### Examples

```text
ordinary source profile
  → SonarQube + CodeScoring + approved source steps

security/regulatory source profile
  → SonarQube + CodeScoring + CodeQL after bridge

container profile
  → Hadolint + CycloneDX + Trivy + ClamAV + KCS + KubeLinter
```

The same scanner may have different configuration/ruleset bindings per ReleaseType.
For example, a security release can use a stricter Sonar profile and different
QG thresholds than an ordinary release.

### When policy change creates a new candidate

New candidate required when any qualifying input changes:

```text
required scanner set
scanner rules/profile version
QG threshold or severity policy
approval requirements
Evidence/Act requirements
artifact scope
deployment/environment context
source/build/digest
```

No new candidate is needed for cosmetic display fields or a non-qualifying
development-only setting.

A stricter/new policy may reuse the same Build digest but still creates a new
ReleaseCandidate, because it is a new qualification proposition and requires its
own scan/QG evidence.

---

## 7. Remediation and re-run model

Finding is not patched. Code, manifest or artifact is patched.

```text
Finding in Candidate A
→ developer remediation / linked commit/work item
→ new Build
→ new digest
→ Candidate B
→ rerun only relevant required checks
→ new Occurrences/Evidence/Act
→ QG evaluates Candidate B
```

Rules:

- old occurrence remains immutable;
- `resolved` is not inferred from a user click;
- a resolution is confirmed by applicable rescan on the new candidate;
- a changed digest always receives a new artifact context;
- QG uses occurrences in the candidate scope, not stale findings from unrelated
  old builds;
- an old Finding can remain open in other builds/releases/projects.

For Project Release Batch, the affected Application release receives a new
candidate. Whether and how downstream dependent applications requalify requires
explicit policy based on graph dependency and ReleaseType.

---

## 8. Required execution versus QG

```text
required release step failed/unavailable
→ Control Plane marks candidate blocked before QG
→ qualifying deployment does not start
→ DAST is not expected
→ Gatekeeper may receive execution status, but does not turn it into triage
```

Only after required execution has completed does Control Plane request QG
evaluation for the candidate.

```text
Control Plane → QG Evaluation Request
  release candidate id
  release type/profile snapshot
  qualifying context
  required-step completion evidence

Gatekeeper → QG Evaluation Response
  Studio security verdict
  Act reference
  blockers
  baseline summary
  approvals/expiry
  PASS_GRANTED | BLOCKED
```

---

## 9. Operator presentation in Gatekeeper

Gatekeeper V1 keeps three operator surfaces, not dozens:

```text
Findings Registry
  → global/project/application/release/build filters

Finding Detail
  → all occurrences, context snapshots, Evidence, triage history

Release QG Explanation
  → one candidate, exact blockers and clearance state
```

Project, Application, KITS, Build and Release are filter/context lenses in these
surfaces. They are not reimplemented as a second Control Plane UI.

---

## 10. Questions to resolve before DTO/implementation

1. Is the correct name `ReleaseCandidate`, `ReleaseRevision` or `ReleaseAttempt`?
2. Does every release retry create a new candidate, or can a candidate contain
   multiple scans for the same Build digest?
3. Which ReleaseType profile changes require a new candidate?
4. When one app is patched in ReleaseBatch, which graph dependents must requalify?
5. Which diagnostic/ad-hoc result may be attached as supplementary Evidence?
6. Which required step completion facts does Control Plane attest to Gatekeeper?
7. Is Studio PASS scoped to candidate, build digest, deployment environment, or
   all of them?
8. How are renames/deleted applications represented in historical context?
9. Which current labels can Gatekeeper refresh read-only after intake?
10. Which `wont_fix`/baseline scope is valid: finding, application, release type,
    artifact digest, project, or release candidate?

No stack, ORM or API implementation starts until these questions have a documented
answer and the envelope has passed 2FA.
