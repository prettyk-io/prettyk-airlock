# COS-060 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Luna  
**Вердикт:** ACCEPTED / DONE

## Accepted result

- Provider capability serialization now preserves `doc_reference`.
- Sfera adapter supports optional backward-compatible TLS configuration and
  normalizes transport responses.
- TLS configuration accepts only references to vault/OpenBao/file sources.
- Unsafe TLS downgrade is rejected unless explicitly marked for development.
- TLS logs expose schema and short fingerprint, never full secret references.
- Provider result mapping translates adapter outcomes into kernel statuses and
  failure semantics without mutating transfer kernel models.
- Conformance coverage spans Gitea, Harbor, Nexus, MinIO and Sfera.
- All 19 capabilities have explicit status and unsupported/unknown capabilities
  cannot produce a false success.
- Digest identity distinguishes server-confirmed, computed and missing digest.
- Sfera raw/OCI push-pull and health/bearer behavior are covered.

## Evidence

Focused provider/TLS/Sfera suite: **221 passed**.  
COS-050/COS-053 transfer-kernel regression: passed.

The full Cosmo regression reported **1860 passed, 18 failed, 7 skipped**.
The failures were triaged as unrelated existing or parallel-wave failures:

- stale table-count and Caddy encoding follow-ups;
- COS-055 notification trigger surface;
- COS-054 offline transfer surface;
- shared-PostgreSQL parallel flakes, green in isolated execution.

They do not block COS-060 acceptance because the focused contract and kernel
regression evidence is green and the package did not modify those surfaces.

## Follow-ups

- Live TLS/mTLS against a real private CA.
- Live Sfera raw/OCI execution.
- COS-049 Sfera CORE OpenAPI before provisioning/exists/resolve/promote/quota.
- Move unrelated full-regression failures into separately owned backlog cards.
- Avoid concurrent workers sharing one mutable PostgreSQL test state; isolate
  databases or serialize affected integration suites.