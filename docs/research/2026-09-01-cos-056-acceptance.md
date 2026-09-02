# COS-056 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Flash  
**Вердикт:** ACCEPTED / DONE

## Verification

```text
py -3 -m pytest orchestrator/tests/cosmo/test_notification_triggers.py orchestrator/tests/cosmo/test_notification_manager.py orchestrator/tests/cosmo/test_notifications.py orchestrator/tests/cosmo/test_releases.py orchestrator/tests/cosmo/test_sse_streaming.py orchestrator/tests/cosmo/test_sse_multiplexer.py -q
109 passed, 4 warnings in 9.53s
```

Warnings are SQLAlchemy async cleanup `Connection._cancel` RuntimeWarnings;
they did not fail assertions. Full regression is separately blocked by the
pre-existing `repos.py` Pydantic error.

## Accepted behavior

- Run, gate, batch, release and transfer triggers publish through the durable
  notification outbox after the domain commit.
- Notification failure does not roll back the domain transaction.
- SSE sends initial unread state, new notification events and unread count.
- Reconnect reads durable state and does not duplicate notifications.
- PostgreSQL degradation produces an explicit degraded event while durable
  inbox data remains authoritative.
- Keepalive is emitted to prevent proxy timeout.
- All V1 trigger paths use the durable integration helpers, not the legacy
  in-memory dispatcher.

## Follow-up

- Connect the remaining transfer-failure route path.
- Replace manual processing tick with a background worker.
- Integrate the Control Station UI with inbox + SSE.
- Add real SMTP provider separately.
- Replace legacy in-memory webhook configs with durable channel config.
- Investigate async cleanup warnings in the test environment.