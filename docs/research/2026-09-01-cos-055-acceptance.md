# COS-055 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Flash  
**Вердикт:** ACCEPTED / DONE

## Verification

Command executed from `orchestrator`:

```text
py -3 -m pytest tests/cosmo/test_notification_manager.py tests/cosmo/test_notifications.py tests/cosmo/test_releases.py tests/cosmo/test_api_routes.py -q
80 passed in 8.17s
```

The four suites contain 26 manager tests, 30 legacy compatibility tests, 12
release tests and 12 API route tests.

## Accepted behavior

- Notification events are durable in PostgreSQL.
- Transfer notification is written in the same transaction as the transfer.
- Outbox processing uses row locking with `FOR UPDATE SKIP LOCKED`.
- In-app inbox has durable read/unread operations.
- Duplicate event processing is idempotent.
- Retryable provider errors are retried; exhausted attempts are visible as
  failed/DLQ.
- Recipient policy and redaction are provider-neutral and do not require
  legacy LDAP/PIS.
- Email provider is an interface; V1 default is a safe logging provider.
- Existing COS-065 in-memory dispatcher remains backward-compatible and does
  not replace the durable manager.
- API exposes inbox, unread count, read, read-all, outbox inspection and
  processing operations.

## Follow-up

- Connect run/gate/batch/release failure/approval triggers, not only transfer
  completion.
- Replace manual `POST /process` tick with a background worker profile.
- Add real SMTP provider separately from the domain manager.
- Add Valkey/SSE projection in COS-056.
- Replace legacy in-memory webhook configuration with durable channel config.

These are follow-ups, not acceptance blockers for COS-055 V1.