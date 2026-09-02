# COS-055 worker collision incident

**Дата:** 1 сентября 2026  
**Статус:** resolved routing incident; implementation in progress  
**PO owner:** Cosmo

## Incident

`COS-055` был объявлен `REFACTOR-SERIAL`, но worker dispatch допустил два
параллельных потока записи в один notification module. Один поток был выдан
Apex, второй фактически выполнялся Luna. Workers перезаписывали shared files.

## Decision

- COS-055 owner: **Flash** (the worker already actively finishing the card).
- Apex is withdrawn from COS-055 and owns COS-058 instead.
- Luna is withdrawn from COS-055 and must not modify notification surfaces.
- Flash is the only worker allowed to continue COS-055.
- Existing WIP is preserved; no destructive cleanup by Luna.

## Reported breakage

- `db/models_notifications.py` and `notifications/models.py` both declare
  `notification_inbox` on the same SQLAlchemy Base.
- Alembic contains two migrations with the same `down_revision`, producing
  multiple heads.
- Domain callers reference notification helpers that are not currently present.
- Legacy notification tests fail at collection because application import fails.

## Required recovery order

1. Freeze writes from all non-owner workers.
2. Apex snapshots the current tree and chooses one canonical model schema.
3. Remove/merge duplicate table declarations so the application imports.
4. Resolve Alembic to one valid linear head; do not leave an inert migration.
5. Restore or remove all domain caller references as one coherent change.
6. Run collection/import smoke before feature work.
7. Run focused notification tests, then full regression.

No acceptance claim is made yet. The card remains in progress until Flash reports
a clean import, one migration head and tests. The collision blocker itself is
resolved by the ownership correction above.