"""
COS-055: Recipient resolution V1 — только Control Plane auth и membership.

Карточка: LDAP/PIS/legacy recipient directory НЕ переносятся. Источники
получателей:
  1. Explicit recipients в payload события (логины Control Plane);
  2. Membership: ProjectTeam / ApplicationTeam (LR-003) по aggregate_id;
  3. Subscription policy (ALL / SELECTED / allow / blocklist).

Нет получателей / все заблокированы → событие остаётся в outbox без
deliveries (не блокирует обработку, не исчезает).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models_lr import ApplicationTeam, ProjectTeam
from orchestrator.cosmo.db.models_notifications import NotificationSubscription

logger = logging.getLogger("cosmoport.notifications.recipients")

VALID_POLICIES = frozenset({"all", "selected", "allow", "block"})


def _member_ids(members: list[dict[str, Any]] | None) -> set[str]:
    """Из JSON-списка членов [{user_id, role}] → set user_id."""
    out: set[str] = set()
    for member in members or []:
        user_id = member.get("user_id") if isinstance(member, dict) else None
        if user_id:
            out.add(str(user_id))
    return out


async def _members_for_aggregate(
    session: AsyncSession,
    aggregate_type: str,
    aggregate_id: str,
) -> set[str]:
    """Члены команды по aggregate. Не LDAP — только LR-003 таблицы."""
    members: set[str] = set()

    if aggregate_type == "project":
        rows = (
            (await session.execute(
                select(ProjectTeam).where(ProjectTeam.project_id == aggregate_id)
            )).scalars().all()
        )
        for team in rows:
            members |= _member_ids(team.inherited_members)
            members |= _member_ids(team.local_additions)
            members -= set(team.local_exclusions or [])

    elif aggregate_type == "app":
        rows = (
            (await session.execute(
                select(ApplicationTeam).where(ApplicationTeam.app_id == aggregate_id)
            )).scalars().all()
        )
        for team in rows:
            members |= _member_ids(team.inherited_from_project)
            members |= _member_ids(team.local_members)
            members -= set(team.local_exclusions or [])
        # Project-команды наследуются приложениями только если приложение
        # не имеет собственной team-записи с жёстким exclusion — V1:
        # берём union project-команд тех проектов, к которым привязано приложение.
        for team in rows:
            prows = (
                (await session.execute(
                    select(ProjectTeam).where(ProjectTeam.project_id == team.project_id)
                )).scalars().all()
            )
            for pteam in prows:
                members |= _member_ids(pteam.inherited_members)
                members |= _member_ids(pteam.local_additions)
                members -= set(pteam.local_exclusions or [])
            members -= set(team.local_exclusions or [])

    # run/gate/release/transfer aggregates: membership не определён —
    # только explicit recipients из payload (см. resolve_recipients).
    return members


async def _apply_subscription_policy(
    session: AsyncSession,
    recipients: set[str],
    event_type: str,
) -> set[str]:
    """V1 policy: block wins; allow/selected сужают; all — пропускает.

    Получатель без записей в подписках считается подписанным на всё
    (default из legacy NOT: auto-create default ALL subscription).
    """
    if not recipients:
        return set()

    rows = (
        (await session.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.recipient.in_(recipients),
                NotificationSubscription.enabled.is_(True),
            )
        )).scalars().all()
    )

    blocked: set[str] = set()
    restricted: dict[str, set[str]] = {}  # recipient → allowed event_types
    for sub in rows:
        types = {sub.event_type}
        if sub.event_type == "*":
            types = {"*"}
        if sub.policy == "block":
            if sub.event_type == "*" or sub.event_type == event_type:
                blocked.add(sub.recipient)
        elif sub.policy in ("allow", "selected"):
            restricted.setdefault(sub.recipient, set()).update(types)
        elif sub.policy != "all":
            logger.warning("Unknown subscription policy %r for %s — treated as all",
                           sub.policy, sub.recipient)

    result: set[str] = set()
    for recipient in recipients:
        if recipient in blocked:
            continue
        allowed_types = restricted.get(recipient)
        if allowed_types is None or "*" in allowed_types or event_type in allowed_types:
            result.add(recipient)
    return result


async def resolve_recipients(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> list[str]:
    """Полный pipeline resolution: explicit + membership + subscription policy.

    Возвращает отсортированный список уникальных получателей.
    """
    explicit = {
        str(r) for r in (payload.get("recipients") or []) if r
    }
    members = await _members_for_aggregate(session, aggregate_type, aggregate_id)
    candidates = explicit | members

    if not candidates:
        logger.info(
            "resolve_recipients: no recipients for %s/%s (%s)",
            aggregate_type, aggregate_id, event_type,
        )
        return []

    resolved = await _apply_subscription_policy(session, candidates, event_type)
    dropped = candidates - resolved
    if dropped:
        logger.info("resolve_recipients: %d blocked/filtered: %s", len(dropped), sorted(dropped))
    return sorted(resolved)
