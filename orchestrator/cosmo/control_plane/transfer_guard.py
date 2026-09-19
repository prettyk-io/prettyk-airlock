# -*- coding: utf-8 -*-
"""COS-145/COS-146: guard межзонного трансфера — авторизация, CAS, replay.

Сервис между маршрутами трансфера и крипто-свидетельствами релиза. Собирает
два независимых вердикта (Quality Gate Hub clearance + SBOM/Grype attestation)
и решает, допустим ли промоушен ЗР → ЗТ → ЗПЭ.

Правила:

  - **fail-closed:** отсутствие клиренса, отсутствие SBOM-аттестации или сбой
    чтения — это отказ. Молчаливого «нет данных → пропускаем» нет;
  - **объяснимость:** каждая причина отказа попадает в ``reasons`` решения и
    в audit-событие ``release_transfer_authorization``;
  - **CAS (COS-146):** переход проверяется против фактической ``current_zone``
    релиза. Клиент может прислать ``expected_current_zone`` — расхождение
    даёт :attr:`TransferTransition.CONFLICT` (HTTP 409), а повтор уже
    выполненного перехода — :attr:`TransferTransition.REPLAY` (HTTP 200
    ``duplicate_success`` без дублей в ``transfer_history``);
  - **row-lock:** ``lock_release`` берёт ``SELECT … FOR UPDATE`` на строку
    релиза, сериализуя конкурентные трансферы одного релиза в рамках
    транзакции запроса;
  - **bypass:** обход авторизации доступен только системному администратору
    в dev-окружении (``COSMO_ENV`` ∈ {test, dev, local}) или при явном
    операторском опт-ине ``COSMO_TRANSFER_BYPASS=1``; каждая попытка (в том
    числе отклонённая) фиксируется в аудите как ``BYPASS_ATTEMPT``.

Граница durability: audit trail — in-memory (тот же surface, что COS-096/139),
честная граница до появления durable-таблицы вне миграционного freeze.
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import Release as ReleaseModel
from orchestrator.cosmo.domain.release_model import next_zone
from orchestrator.cosmo.domain.transfer_authorization import (
    CLEARANCE_AUTHORIZED_STATUS,
    SBOM_AUTHORIZED_VERDICT,
    STATUS_CHECK_FAILED,
    STATUS_MISSING,
    TRANSFER_AUTHORIZATION_AUDIT_ACTION,
    TRANSFER_AUTHORIZATION_RESOURCE_TYPE,
    TRANSFER_BYPASS_AUDIT_ACTION,
    TransferAuthorizationDecision,
    TransferReplayResponse,
    TransferTransition,
)
from orchestrator.cosmo.ledger.hub_clearance_gate import HubClearanceGateManager
from orchestrator.cosmo.ledger.sbom_gate import latest_sbom_attestation

#: Окружения, в которых допустим admin-bypass авторизации трансфера.
BYPASS_ENV_VALUES = frozenset({"test", "dev", "local"})

#: Переменная окружения — имя окружения.
ENV_NAME_VAR = "COSMO_ENV"

#: Явный операторский опт-ин обхода (значение ``1``).
BYPASS_OPT_IN_VAR = "COSMO_TRANSFER_BYPASS"


def _default_clock() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _record_audit(
    *,
    actor: str,
    action: str,
    release_id: str,
    status: str,
    details: dict[str, Any],
) -> None:
    """Записать событие в audit trail (lazy import — без цикла импортов)."""
    from orchestrator.cosmo.api.routes.audit import record_system_event

    record_system_event(
        user_id=actor,
        action=action,
        resource_type=TRANSFER_AUTHORIZATION_RESOURCE_TYPE,
        resource_id=release_id,
        status=status,
        details=details,
    )


def _history_zones(rel: ReleaseModel) -> list[str]:
    """Зоны ``to_zone`` из transfer_history (устойчиво к dict/моделям)."""
    zones: list[str] = []
    for record in rel.transfer_history or []:
        if isinstance(record, dict):
            zone = record.get("to_zone")
        else:
            zone = getattr(record, "to_zone", None)
        if isinstance(zone, str) and zone:
            zones.append(zone)
    return zones


def bypass_permitted(
    is_system_admin: bool,
    *,
    env: Optional[str] = None,
    opt_in: Optional[str] = None,
) -> bool:
    """Допустим ли admin-bypass: system admin + dev-окружение (или явный опт-ин)."""
    if not is_system_admin:
        return False
    if opt_in is None:
        opt_in = os.getenv(BYPASS_OPT_IN_VAR, "")
    if opt_in.strip() == "1":
        return True
    if env is None:
        env = os.getenv(ENV_NAME_VAR, "")
    return env.strip().lower() in BYPASS_ENV_VALUES


class ReleaseTransferGuard:
    """Авторизация трансфера (COS-145) + CAS/replay перехода (COS-146)."""

    def __init__(
        self,
        *,
        clearance_gate: HubClearanceGateManager | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._clearance_gate = clearance_gate or HubClearanceGateManager()
        self._clock = clock or _default_clock

    # ── COS-146: CAS / lock / replay ────────────────────────────────────

    async def lock_release(
        self, session: AsyncSession, release_id: str,
    ) -> Optional[ReleaseModel]:
        """Прочитать релиз под ``SELECT … FOR UPDATE`` (сериализация трансферов).

        Строка блокируется до конца транзакции запроса: два конкурентных
        трансфера одного релиза не могут оба прочитать одну и ту же
        ``current_zone`` и продвинуть релиз дважды.
        """
        stmt = (
            select(ReleaseModel)
            .where(ReleaseModel.id == release_id)
            .with_for_update()
        )
        return (await session.execute(stmt)).scalars().first()

    @staticmethod
    def evaluate_transition(
        rel: ReleaseModel,
        *,
        target_zone: Optional[str] = None,
        expected_current_zone: Optional[str] = None,
    ) -> TransferTransition:
        """CAS-вердикт перехода: PROCEED / REPLAY / CONFLICT (pure-функция)."""
        current = rel.current_zone or "zr"

        # Оптимистичный CAS: клиент заявил ожидаемую текущую зону.
        if (
            expected_current_zone is not None
            and expected_current_zone != current
        ):
            return TransferTransition.CONFLICT

        target = target_zone or next_zone(current)
        # REPLAY: переезд уже зафиксирован (цель совпадает с текущей зоной и
        # она есть в истории; либо явной цели нет, а финальная зона уже
        # достигнута). Дубль истории и повторные уведомления не создаются.
        if (target is None or target == current) and current in _history_zones(rel):
            return TransferTransition.REPLAY
        return TransferTransition.PROCEED

    @staticmethod
    def replay_payload(rel: ReleaseModel) -> TransferReplayResponse:
        """Идемпотентный ответ на повтор уже выполненного перехода."""
        return TransferReplayResponse(
            release_id=rel.id,
            current_zone=rel.current_zone or "zr",
            transfer_history_count=len(rel.transfer_history or []),
        )

    # ── COS-145: авторизация ────────────────────────────────────────────

    async def authorize(
        self,
        session: AsyncSession,
        release_id: str,
        *,
        target_zone: Optional[str] = None,
        actor: str = "system",
    ) -> TransferAuthorizationDecision:
        """Собрать решение о допуске трансфера (fail-closed) и записать аудит."""
        reasons: list[str] = []

        clearance_status = STATUS_MISSING
        try:
            clearance = await self._clearance_gate.latest_for_release(
                session, release_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed на любом сбое
            clearance = None
            clearance_status = STATUS_CHECK_FAILED
            reasons.append(
                "Quality Gate clearance check failed "
                f"({type(exc).__name__}: {exc})"
            )

        if clearance is None:
            if clearance_status == STATUS_MISSING:
                reasons.append(
                    "no Quality Gate clearance recorded for release"
                )
        else:
            clearance_status = clearance.clearance_status
            if (
                clearance_status != CLEARANCE_AUTHORIZED_STATUS
                or not clearance.transfer_allowed
            ):
                reasons.append(
                    "Quality Gate clearance "
                    f"{clearance_status} does not authorize transfer"
                )

        sbom_status = STATUS_MISSING
        try:
            attestation = await latest_sbom_attestation(session, release_id)
        except Exception as exc:  # noqa: BLE001 — fail-closed на любом сбое
            attestation = None
            sbom_status = STATUS_CHECK_FAILED
            reasons.append(
                f"SBOM attestation check failed ({type(exc).__name__}: {exc})"
            )

        if attestation is None:
            if sbom_status == STATUS_MISSING:
                reasons.append("no SBOM attestation recorded for release")
        else:
            sbom_status = attestation.gate_verdict
            if attestation.gate_verdict != SBOM_AUTHORIZED_VERDICT:
                reasons.append(
                    "SBOM attestation "
                    f"{attestation.gate_verdict} (critical vulnerabilities) "
                    "does not authorize transfer"
                )

        decision = TransferAuthorizationDecision(
            authorized=not reasons,
            release_id=release_id,
            target_zone=target_zone or "unknown",
            clearance_status=clearance_status,
            sbom_attestation_status=sbom_status,
            reasons=reasons,
            checked_at=self._clock().isoformat(),
        )
        _record_audit(
            actor=actor,
            action=TRANSFER_AUTHORIZATION_AUDIT_ACTION,
            release_id=release_id,
            status="success" if decision.authorized else "blocked",
            details={
                "authorized": decision.authorized,
                "target_zone": decision.target_zone,
                "clearance_status": decision.clearance_status,
                "sbom_attestation_status": decision.sbom_attestation_status,
                "reasons": decision.reasons,
            },
        )
        return decision

    def record_bypass(
        self,
        *,
        actor: str,
        release_id: str,
        target_zone: Optional[str],
        permitted: bool,
    ) -> None:
        """Зафиксировать попытку обхода авторизации (включая отклонённую)."""
        _record_audit(
            actor=actor,
            action=TRANSFER_BYPASS_AUDIT_ACTION,
            release_id=release_id,
            status="success" if permitted else "blocked",
            details={
                "bypass_authorization": True,
                "permitted": permitted,
                "target_zone": target_zone or "unknown",
            },
        )


#: Процессный инстанс guard'а (дефолт для FastAPI-зависимостей).
_GUARD = ReleaseTransferGuard()


def get_transfer_guard() -> ReleaseTransferGuard:
    """FastAPI-зависимость: процессный :class:`ReleaseTransferGuard`."""
    return _GUARD


__all__ = [
    "BYPASS_ENV_VALUES",
    "BYPASS_OPT_IN_VAR",
    "ENV_NAME_VAR",
    "ReleaseTransferGuard",
    "bypass_permitted",
    "get_transfer_guard",
]
