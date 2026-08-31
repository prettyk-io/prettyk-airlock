# SecOps Studio → Gatekeeper → PrettyK Control Plane flow

> **Статус:** friend-request / cross-layer contract candidate  
> **Участники:** Максим ↔ Cosmo; Gatekeeper/keeper review required  
> **Контуры:** PrettyK SecOps Studio, PrettyK Findings Control Station, PrettyK Control Plane

## Product flow

```text
PrettyK Control Plane
→ sends Release/Build/artifact/required-step context
→ Gatekeeper QG Center processes security context
→ qualifying deployment
→ PrettyK SecOps Studio executes post-deployment DAST/AppSec
→ Studio returns final PASS/FAIL + Act + raw findings/Evidence
→ Gatekeeper ingests, triages, applies policy and registers clearance
→ PrettyK Control Plane receives clearance
→ Release Package becomes OK_TO_TRANSFER only when allowed
```

## Authority boundary

```text
PrettyK SecOps Studio
  = final DAST execution authority
  = final DAST PASS/FAIL authority
  = final Act producer

Gatekeeper QG Center
  = finding/triage/baseline/approval/policy authority
  = records PASS_GRANTED only from Studio PASS + Act + policy

PrettyK Control Plane
  = release/package orchestration
  = consumes clearance, never recomputes DAST QG itself
```

Neither Gatekeeper nor Control Plane may silently override a Studio FAIL.

## Required execution versus QG

```text
required Build/registry/scanner step fails or is unavailable
→ required step not completed
→ qualifying deploy does not start
→ DAST is not expected
→ Release BLOCKED before QG
→ no transfer
```

This is execution failure, not an accepted-risk decision or QG warning.

QG evaluates completed findings and human decisions. It never turns failed
execution into PASS.

## Diagnostic exception

An explicitly authorised diagnostic deployment may exist for investigation:

```text
failed/non-complete prechecks
→ non-qualifying deployment
→ limited SecOps investigation
→ findings/Evidence
```

It cannot:

```text
qualify a Release
create PASS_GRANTED
create OK_TO_TRANSFER
replace a required pipeline scan
```

## Remediation loop

```text
DAST finding
→ remediation/human triage
→ new Build
→ qualifying deployment
→ new Studio DAST run
→ new Act/result
→ repeat until current Studio PASS
→ Gatekeeper clearance
→ Control Plane OK_TO_TRANSFER
```

Every cycle creates new ScanRun/FindingOccurrence/Evidence. Previous facts and
decisions remain auditable.

## Clearance response

Control Plane requires:

```text
security_execution_verdict
act_ref
qg_clearance
blockers
baseline_summary
expired_decisions
missing_approvals
qualifying_context
ok_to_transfer
```

Exact API names and enum values require joint 2FA with Gatekeeper.
