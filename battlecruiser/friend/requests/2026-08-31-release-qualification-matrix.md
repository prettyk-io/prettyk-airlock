# Release qualification matrix — Regular, Security, Flexible and Hotfix

> **Статус:** friend-request / agreed direction / exact policy admission pending  
> **Цель:** fixed qualification lists вместо произвольного выбора release steps

## 1. Общие принципы

### ReleaseCandidate

```text
Release
  → logical release/version

ReleaseCandidate
  → конкретная immutable qualification proposition
  → commit/build/digest/profile/policy context

ScanRun
  → отдельная попытка scanner/job against Candidate
```

Retry scanner/job на том же candidate создаёт новый ScanRun, а не переписывает
старые findings/reports. Патч кода/manifest/artifact создаёт новый Build/digest и
новый ReleaseCandidate.

### Minimal identity/coverage checks

Не строить нестабильный комбайн проверок identity. Проверять только то, что
действительно защищает qualification:

```text
source → repository + commit SHA + tree identity + profile/rules version
container → exact image digest + scanner profile version
IaC → declared deployment bundle/rendered scope where it affects deployment
```

Partial/manual single-file scan не закрывает findings полного ReleaseCandidate.
История occurrences не удаляется только потому, что один последующий отчёт чист.

### KITS and context

KITS — optional tag/filter. Не является обязательным условием ReleaseCandidate,
tenant boundary или scanner scope.

---

## 2. Regular / Planned Release

### Scope

```text
source:
  full relevant repository at selected commit
  production source, build scripts, manifests, lockfiles, CI config
  test/generated/library/docs are scanned where relevant and labelled by context

container:
  Dockerfile/build context
  exact image@sha256:digest
  SBOM and relevant deployment manifests

IaC:
  only when IaC exists and affects the release deployment
```

### Fixed list

```text
source:
  Gitleaks
  SonarQube
  CodeScoring
  CycloneDX
  KICS when IaC exists
  SLSA provenance

container:
  Hadolint
  CycloneDX
  Trivy
  ClamAV
  KCS as final container scan
  KubeLinter for Kubernetes manifests

post-deploy:
  PrettyK SecOps Studio DAST
  final Studio Act
  Gatekeeper QG
```

### Zone path

```text
ЗР
→ qualified package for transfer
→ ЗТ instance with its own lifecycle
→ qualified package for transfer
→ ЗПЭ instance
→ deployment
→ Production / «В эксплуатации»
```

---

## 3. Security / Regulatory Release

### Scope

Full Regular scope plus strict scanner/policy configuration.

### Fixed list

```text
source:
  Gitleaks
  SonarQube with security profile
  CodeScoring with security policy
  CodeQL where language support is detected
  CycloneDX
  KICS when IaC exists
  SLSA

container:
  Hadolint
  CycloneDX
  Trivy
  ClamAV
  KCS final scan
  KubeLinter

post-deploy:
  full PrettyK SecOps Studio DAST
  final Act
  strict Gatekeeper QG
```

### CodeQL applicability

Application creation detects language/technology and stores it as card metadata.

```text
CodeQL supported language
→ CodeQL required in security/reulatory profile

CodeQL unsupported language
→ NOT_APPLICABLE with visible reason
→ no fake execution/no false PASS
```

`NOT_APPLICABLE` is not an arbitrary developer skip.

### QG

```text
new Critical → no go
new High     → no go
```

Both Critical and High may receive `wont_fix` resolution. Individual per-finding
Admin IB approval is not required. Scanner continues to honestly detect the
problem. Gatekeeper stores the resolution. Admin IB reviews and approves the
batch of resolutions during Act issuance under the applicable policy.

---

## 4. Flexible Release

### Purpose

Formal exception release for real operational cases. It is not a Development
Build and not an invisible shortcut.

```text
Flexible Release
→ concrete candidate
→ declared deviations
→ resolutions with decision maker
→ Admin IB approval
→ Act/exception record
→ may progress including to ЗПЭ under restrictive policy
```

### Creation and approval

```text
create:
  Admin KITS
  Admin IB

approve override:
  Admin IB
```

### Two explicit resolution families

```text
ExecutionDeviationResolution
  → required step failed/unavailable/skipped
  → exact step/run/error/evidence
  → reason, owner, expiry, decision maker

RiskDeviationResolution
  → QG finding/baseline/accepted risk/wont fix deviation
  → affected findings and QG effect
  → reason, owner, expiry, decision maker
```

They cannot be replaced by one vague release comment.

### Restrictions

- candidate/build/digest must still be explicit;
- all deviations visible in UI and Release Package;
- no automatic carry-over: a new candidate needs new or explicitly renewed
  resolutions;
- Admin IB review is recorded with the Act/exception decision;
- QG explanation names each deviation and its owner/expiry;
- Control Plane displays the release as flexible/exception-based.

### Studio authority for Flexible Release

Flexible Release **may** override other execution/QG conditions and Studio FAIL,
but **cannot** bypass the absence of an Act.

```text
Studio FAIL
→ Flexible Exception Act is issued
   with visible critical resolution record
   owner/reason/expiry
   Admin IB approval
→ Gatekeeper records and explains
→ Control Plane permits restricted transfer
```

The Flexible Exception Act is a documented exception, not a silent override.
The underlying Studio FAIL remains in Evidence and candidate history.

### Qualified Act

An Act for ZPE always requires a full Studio scan. PrettyK Baseline DAST may
produce evidence for diagnostic or pre-qualification purposes, but only a full
Studio-scan-verified Act qualifies a ReleaseCandidate for Gatekeeper clearance
toward ZPE under any ReleaseType.

---

## 5. Hotfix Release

### Scope

Hotfix starts from scratch at an explicitly selected commit or branch.

```text
selected commit/branch
→ full Build
→ new artifact digest
→ fixed Hotfix profile
→ new ReleaseCandidate
```

Hotfix does not use a diff shortcut for qualification. Lightweight re-runs inside
the same candidate are allowed only after coverage is proven by policy.

### Fixed list

```text
source:
  Gitleaks
  Semgrep
  CodeScoring where applicable
  CycloneDX
  KICS when IaC exists

container:
  Hadolint
  CycloneDX
  Trivy
  ClamAV
  KCS final scan
  KubeLinter

post-deploy:
  PrettyK Baseline DAST
  final result/Act according to Studio contract
  Gatekeeper QG
```

SonarQube is not in the Hotfix fixed list. Semgrep is the selected fast source
analysis step for Hotfix, subject to a real future integration bridge.

### PrettyK DAST split

```text
prettyk-baseline
  → baseline DAST profile
  → URL list and go
  → no per-release custom configuration
  → produces evidence for Hotfix diagnostic/pre-qualification

prettyk-studio-scan
  → configured/full SecOps Studio session
  → authentication/setup/custom context where required
  → required for any Act that qualifies a candidate toward ZPE
```

Hotfix in ЗР may run `prettyk-baseline` for speed. The qualifying Act for ЗПЭ
always comes from the combined regular+/security candidate in ЗТ with full
Studio scan.

### Zone path and merge

```text
ЗР:
  Hotfix ReleaseCandidate
  → full Hotfix profile
  → package for transfer

ЗТ:
  Hotfix arrives
  → merges into the target Release already present in ЗТ
  → combined candidate goes through regular+ (or security if extended since ЗР)
  → full Studio scan + Act
  → QG
  → qualification toward ЗПЭ
```

Hotfix never enters ЗПЭ as a standalone Release. Once merged into the target
ЗТ Release, the combined candidate follows the normal ЗТ qualification path.

---

## 6. Development Build remains separate

```text
Development Build
→ developer/tester selects allowed checks
→ diagnostic result only
→ no ReleaseCandidate qualification
→ no ReleaseBatch qualification
→ no transfer permission
```

---

## 7. Future affected-scope optimisation

Intelligent affected-scope computation is useful, but must begin as an
optimisation, not as a security truth engine.

Future eligibility for targeted re-run may require all of:

```text
known change set
known dependency graph
no changes to lockfiles/build/IaC/Dockerfile/security configuration
bounded affected closure under policy threshold
scanner supports scoped analysis
coverage manifest is attached
```

If evidence is incomplete, the release returns to its fixed full profile. The
system does not guess that one changed file represents the complete security
scope.
