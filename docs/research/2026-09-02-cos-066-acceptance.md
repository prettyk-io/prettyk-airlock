# COS-066 acceptance

**Verdict:** ACCEPTED / DONE  
**Worker:** Apex  
**Date:** 2 September 2026

Transfer API, kernel, RBAC/security/persistence and new security matrices passed
**262 tests**. The client-controlled domain header no longer grants read or
ownership access: non-admin identity is bound to `principal.domain_id`; context
switch remains restricted to system admin. Route/auth/ownership, error,
idempotency and OpenAPI matrices passed, including the regression suite for all
ten other guarded routes.

The broader `deps._guard` context-binding finding is recorded as a follow-up;
it is not silently treated as resolved by handler-level transfer protection.