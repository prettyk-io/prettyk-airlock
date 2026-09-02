# COS-058 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Apex  
**Вердикт:** ACCEPTED / DONE

## Accepted result

- Transfer API exposes plan creation, plan/item lookup, release correlation,
  validation, landing state, transitions and recovery.
- The API uses one structured error contract with correct HTTP status mapping.
- Domain ownership and mutation capabilities are enforced.
- Cross-domain reads do not disclose object existence.
- Kernel transition invariants are preserved through the HTTP boundary.
- Multi-plane and metadata-only skeleton plans are represented without adding
  SOD-specific enum values.
- OpenAPI exposes the real kernel schemas and all nine transfer paths.
- Recoverable failures and checksum/duplicate/invalid-transition conditions are
  observable as first-class API results.

## Evidence

```text
Transfer API + transfer kernel: 68 passed
RBAC/security/persistence set: 171 passed
full suite: 1872 passed, 7 skipped
```

The reported six full-suite failures were unchanged with or without the new
transfer API file and were attributed to unrelated table-count, Caddy,
notification-trigger and parallel-state issues.

The incidental `deps.py` and `repos.py` repairs are accepted as enabling fixes
for this API surface, not as closure of every guarded-route or regression
requirement in the repository.

## Follow-ups

- Replace in-memory `TransferRegistry` with the durable persistence boundary.
- Implement physical SOD/FTP/diode/gateway adapters separately.
- Add gateway lease/TTL and live Harbor/Nexus/MinIO integrations when their
  contracts are evidenced.
- Run a separate acceptance over all non-admin guarded routes after the
  `deps.py` repair.