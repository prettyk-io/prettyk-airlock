# Cross-product contract bridge — Control Plane ↔ PrettyK SecOps ↔ QGFCS

> Status: research / contract-planning brief. Not canon and not an API freeze.
> Date: 2026-09-02
> Owner: Cosmo / PrettyK Control Plane
> Review partners: Keeper (PrettyK SecOps), Vector (QGFCS; current local
> documents call this PO Arbiter/Gatekeeper)

## 1. Why start now

The Control Plane Steel Thread is now integration-tested through
`Domain → Application → Bricks → Compile → Run → Batch → Gate → Evidence`.
The latest accepted evidence is:

- COS-080: 12 integration tests, three consecutive runs;
- COS-077: durable transfer API, lease/failure semantics, 40 focused tests;
- latest reported full test snapshot: 2274 passed / 2 skipped;
- test data is isolated on `:5433/cosmo_test`.

The internal orchestration boundary is mature enough to draft external wire
contracts. The external bridge is **not implemented yet**: there is no accepted
Studio adapter or QGFCS client in this repository. Therefore this document
separates facts, proposals, and open questions.

## 2. Authority and ownership

```text
PrettyK SecOps Studio / execution
  owns DAST/AppSec execution, raw findings, Evidence, final Studio PASS/FAIL,
  and Act production.

QGFCS / Vector (Arbiter/Gatekeeper)
  owns Finding, Occurrence, triage, baseline, approvals, GateEvaluation,
  QG policy, and explainable QG clearance.

PrettyK Control Plane / Cosmo
  owns Project, Application, Build, Run, Release, ReleaseBatch,
  pre-check orchestration, package readiness, and transfer.
```

Hard boundary:

- separate repositories, databases, and runtime contours;
- REST, webhook, SSE, SARIF/JSON/CycloneDX and object references only;
- no shared DB, internal imports, or copied mutable state;
- Control Plane consumes QGFCS verdict and does not recompute findings/QG;
- QGFCS does not create releases or perform transfer;
- QGFCS cannot turn Studio FAIL or missing Act into PASS_GRANTED.

## 3. Proposed end-to-end flow

```text
Control Plane
  → release/build/artifact/precheck context
QGFCS
  → current findings/baseline/policy pre-evaluation (if applicable)
Control Plane
  → qualifying deployment
PrettyK SecOps Studio
  → post-deployment DAST/AppSec
  → Studio result + Act + findings/Evidence refs
QGFCS
  → intake, correlation, triage, policy evaluation, explanation
  → PASS_GRANTED or BLOCKED
Control Plane
  → consumes clearance
  → OK_TO_TRANSFER only when all required conditions hold
```

Required execution failure is separate from QG:

```text
required build/registry/scanner step fails
  → no qualifying deployment
  → no expected DAST run
  → Release BLOCKED before QG
  → no transfer
```

An explicitly authorised diagnostic deployment may produce findings, but never
creates a qualified release, `PASS_GRANTED`, or `OK_TO_TRANSFER`.

## 4. Contract A — PrettyK/Studio → QGFCS intake

The existing QGFCS `INTAKE-CONTRACT.md` is the starting semantic contract.
Proposed minimum envelope (field names remain subject to joint 2FA):

```json
{
  "contract_version": "1.0",
  "scan_id": "scan-...",
  "studio_run_id": "studio-...",
  "build_id": "build-...",
  "run_id": "run-...",
  "release_id": "release-...",
  "commit_sha": "...",
  "artifact_digest": "sha256:...",
  "target_environment": "zr",
  "scanner": "prettyk-secops-studio",
  "scanner_version": "...",
  "ruleset_version": "...",
  "security_execution_verdict": "PASS",
  "act_ref": "artifact://...",
  "evidence_refs": ["artifact://..."],
  "findings": [
    {
      "fingerprint": "...",
      "fingerprint_scheme": "prettyk-v1",
      "title": "...",
      "severity": "Critical",
      "rule_id": "...",
      "type": "dast",
      "location": "...",
      "component": "...",
      "evidence_ref": "artifact://...",
      "qwen_suggestion": null
    }
  ]
}
```

Invariants:

- `scan_id` is the idempotency key; replay does not create duplicate
  occurrences;
- PrettyK/Studio is the authority for the fingerprint, QGFCS does not silently
  recompute it;
- every finding has an evidence reference;
- `artifact_digest`, when present, is immutable identity, never a mutable tag;
- QWEN is advisory only and cannot alter disposition or release state;
- raw reports and large evidence remain object references, not inline triage
  blobs;
- intake acceptance/rejection is explicit and machine-readable.

Open details for Keeper + Vector: actual Studio output shapes, exact
fingerprint schemes, SARIF mapping, Act mandatory fields, partial/batch intake,
auth/signature, retry and idempotency semantics.

## 5. Contract B — Control Plane → QGFCS evaluation

The existing QGFCS `QG-CONTRACT.md` is semantically correct but must be joined
to the actual Control Plane release context. Proposed request:

```json
{
  "contract_version": "1.0",
  "request_id": "qg-request-...",
  "evaluation_id": "qg-eval-...",
  "project_id": "project-...",
  "application_ids": ["app-..."],
  "release_id": "release-...",
  "run_id": "run-...",
  "build_id": "build-...",
  "artifact_digest": "sha256:...",
  "release_profile": "ordinary@1",
  "target_zone": "zr",
  "qualifying_context": true,
  "security_execution": {
    "studio_run_id": "studio-...",
    "verdict": "PASS",
    "act_ref": "artifact://...",
    "evidence_refs": ["artifact://..."]
  }
}
```

Rules:

- QGFCS evaluates the exact release/build/digest context, not a floating
  project-wide latest result;
- evaluation is idempotent by `evaluation_id` plus immutable context identity;
- a missing/failed required execution fact is not converted into a QG warning
  or PASS;
- `qualifying_context=false` can never produce `PASS_GRANTED` or
  `ok_to_transfer=true`;
- QGFCS returns the policy/profile version it actually applied.

## 6. Contract C — QGFCS → Control Plane clearance

Proposed response, extending the existing QG response and SecOps flow:

```json
{
  "contract_version": "1.0",
  "evaluation_id": "qg-eval-...",
  "release_id": "release-...",
  "run_id": "run-...",
  "evaluated_at": "2026-09-02T12:00:00Z",
  "policy_version": "qg-policy@1",
  "security_execution_verdict": "PASS",
  "act_ref": "artifact://...",
  "qg_clearance": "PASS_GRANTED",
  "verdict": "PASS",
  "ready_for_transfer": true,
  "qualifying_context": true,
  "ok_to_transfer": true,
  "summary": {
    "total_findings": 0,
    "new_critical": 0,
    "new_high": 0,
    "expired_decisions": 0,
    "missing_approvals": 0
  },
  "blockers": [],
  "warnings": [],
  "baseline_summary": {},
  "evidence_refs": ["artifact://..."],
  "explanation_ref": "artifact://..."
}
```

Control Plane acceptance rules:

1. accept only the matching `release_id`, `run_id`, build and digest context;
2. require current Studio PASS, Act, Evidence and `qualifying_context=true`;
3. require `qg_clearance=PASS_GRANTED` and `ok_to_transfer=true`;
4. persist the external verdict, explanation and references as an audit fact;
5. on BLOCK, FAIL, missing Act, stale context, timeout or malformed response:
   keep the release blocked and show the reason;
6. never reconstruct QG from a partial findings copy;
7. a later remediation cycle creates a new scan/occurrence/evaluation and
   cannot silently overwrite the old decision.

## 7. Delivery and failure semantics

The first accepted bridge should support both request/response and callback
delivery without coupling the products to one transport:

```text
REST request → explicit response
Webhook      → signed event / delivery id / replay-safe handling
SSE          → operator telemetry only, not durable authority
```

Required common mechanics:

- `contract_version` on every envelope;
- opaque correlation IDs and immutable context IDs;
- idempotency key and replay-safe response;
- timeout is `UNKNOWN/BLOCKED`, never PASS;
- authentication and message integrity are explicit open fields, not assumed;
- no raw secret or credential in payload, logs, or evidence refs;
- object references are authorised separately from metadata.

## 8. Known current gaps in Control Plane

- no accepted external QGFCS client/adapter yet;
- no accepted PrettyK SecOps Studio launch/result adapter yet;
- current internal gate decision trail (COS-081) is worker WIP, not external QG;
- internal `Gate` model (`pass|block|manual_required`) is not the same as the
  external QGFCS clearance (`PASS_GRANTED|BLOCKED`);
- current run model carries IDs and evidence refs but does not itself define the
  external Studio/QGFCS wire contract;
- `/ready` degraded status and `pg_client._wipe` transfer-table cleanup remain
  unrelated local follow-ups.

## 9. Questions requiring joint answer

### Keeper / PrettyK SecOps

1. What is the real Studio run/result JSON and real Act schema?
2. Is Studio PASS scoped to release, build digest, deployment, environment, or
   the tuple of all four?
3. Which raw outputs are stable object references and which are safe metadata?
4. Which fingerprint schemes and versions are actually emitted by DAST/fuzzer/
   scanner paths?
5. What callback/auth/signature/retry contract can Studio support in airgap?

### Vector / QGFCS

1. Confirm the exact intake and evaluation endpoint paths and DTO naming.
2. Confirm QG response enums, policy versioning and stale-context handling.
3. Define evaluation idempotency and whether a new evaluation is required after
   every new occurrence, decision, Act or digest.
4. Define which approvals are required for Critical/High and how approval refs
   are represented without copying identity secrets.
5. Define webhook delivery, replay, signature, timeout and `UNKNOWN` semantics.
6. Confirm whether QGFCS accepts Studio results directly or only through the
   PrettyK execution layer.

### Joint with Maxim

- final product name/identity `Vector` versus current `Arbiter/Gatekeeper`
  terminology;
- exact 2FA admission of the shared wire contract;
- initial transport (REST first, webhook callback, or both);
- whether the contract is v1 mandatory scope or provisional research.

## 10. Recommended next sequence

```text
1. Keeper: inventory real Studio outputs and Act/evidence references.
2. Vector: produce formal QGFCS Intake + QG Contract Draft from real inputs.
3. Cosmo: map the accepted DTO to Release/Run/Build/Batch readiness.
4. Joint review: resolve identity, auth, idempotency, timeout and scope.
5. 2FA + friend-request admission.
6. Only then: separate implementation packets for CP adapter, Studio adapter,
   and QGFCS intake/evaluation.
```

This is compatible with parallel work: Keeper can discover real Studio output
while Vector drafts the QGFCS side, but neither side should freeze production
DTOs or implement a cross-product adapter before the shared contract is admitted.