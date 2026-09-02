# COS-061 acceptance

**Дата:** 1 сентября 2026  
**Исполнитель:** Flash  
**Вердикт:** ACCEPTED / DONE

## Accepted result

- Control Station reads notifications from the durable inbox API instead of
  synthesizing alerts from runs/gates.
- In-memory 15-second polling was removed from the active notification path.
- Read and read-all actions call durable backend mutations.
- EventSource consumes the notification SSE stream with initial state,
  new-notification, unread-count, degraded and reconnect behavior.
- Client-side deduplication is by notification id.
- Loading, empty, API error, disconnected and degraded states are visible to
  the operator and API errors have a retry action.
- Bell, unread indicator, cards, close and mark-all actions have accessible
  labels/keyboard behavior.

## Evidence

- Frontend API and component surfaces were updated.
- Vitest/jsdom component/API coverage was reported green.
- The built frontend bundle was produced successfully.

## Follow-ups

- Replace V1 fixed `recipient_id=operator` after auth/RBAC user identity is
  available.
- Playwright browser-level happy path remains a separate test card.
- EventSource query-param authentication is a V1 compromise because native
  EventSource does not provide custom headers.
- Full regression remains affected by the pre-existing `repos.py` issue and
  unrelated parallel failures; it is not a COS-061 defect.