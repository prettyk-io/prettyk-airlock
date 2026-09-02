# COS-059 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Buddy  
**Вердикт:** PARTIAL ACCEPTANCE / BLOCKED

## Accepted infrastructure slice

- Caddy SSE routes disable buffering and rate limiting for event streams.
- Caddy healthcheck targets the existing `/live` route.
- Core and full Compose profiles are separated correctly.
- Core services can be selected without full provider stack.
- `.env.example` contains configuration placeholders without secrets.
- Start script waits for readiness and exits non-zero on failure.
- Stop script preserves state; destructive wipe requires explicit confirmation.
- Smoke script has nine checks and non-zero failure behavior.
- PostgreSQL and Valkey health/volume wiring is present.
- Caddy configuration validates successfully.

## Blocking evidence

Smoke result: **1/9 passed, 8 failed** because the API is unhealthy and the
frontend/upstream checks cannot proceed.

Root cause is outside Buddy's infrastructure scope:

1. `releases` is referenced by a deployment FK but no migration creates the
   table, although the ORM model exists.
2. Initial `domains` migration creates stale flat columns while current ORM
   expects the newer binding/quota columns.
3. A failed mid-chain migration leaves replay behavior vulnerable to
   `DuplicateTable` on restart.

## Follow-up

- **COS-062 / Luna:** reconcile Alembic chain with current ORM/Base metadata.
- **COS-063 / Buddy:** after COS-062, run full 9/9 smoke and restart/state
  preservation acceptance.

COS-059 is not marked done until the runtime path is live.