"""COS-055: Portal-local Notification Manager — durable core.

Модули:
  service.py     — legacy in-memory dispatcher (COS-065, live projection);
  manager.py     — durable NotificationManager (outbox/journal/inbox/retry);
  recipients.py  — V1 recipient resolution (membership + subscription policy);
  providers.py   — provider-neutral email interface + redaction;
  integration.py — publish-хелперы для run/gate/batch/release/transfer событий.
"""
