# COS-054 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Boss  
**Вердикт:** ACCEPTED / DONE

## Accepted result

- `OfflineImporter` discovers manifests, verifies payload and manifest
  checksums, promotes atomically and supports checkpoint/resume.
- `DiodeAdapter` provides vendor-neutral chunk dispatch, retry, polling and
  status tracking through external `TransportLink`, `AckChannel` and
  `TargetVerifyHook` protocols.
- Every chunk is checkpointed; retry resumes from the last unsent chunk.
- Retryable failures preserve `revision_key` and `delivery_id`.
- Terminal target/checksum failures require a new revision.
- Strict one-way mode never pretends that an impossible ACK is delivery
  confirmation; it reports `ASSUMED_DELIVERED`.
- Explicit ACK mode requires a separate ACK channel.
- Import resume, duplicate idempotency, checksum mismatch and active-staging
  cleanup rules are covered.

## Evidence

```text
test_offline_transfer.py: 44 passed
baseline + offline suite: 401 passed
full suite: 1872 passed, 7 skipped
```

## Follow-ups

- Physical vendor transport implementation remains outside the adapter.
- Vendor-specific capacity/error mapping remains the responsibility of the
  concrete link.
- Real target ACK/control-channel deployment is not claimed by this card.