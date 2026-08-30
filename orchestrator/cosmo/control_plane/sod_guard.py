# -*- coding: utf-8 -*-
"""COS-113: Separation of Duties (SoD) Server-Side Enforcement.

Запрещает автору релиза подписывать свои же гейты допуска.
Правило: release.initiator != gate.decided_by → HTTP 409 Conflict.
"""
from __future__ import annotations

from fastapi import HTTPException, status


def verify_sod(release_initiated_by: str, gate_decided_by: str, resource: str = "Release") -> None:
    """Separation of Duties check.

    Если инициатор релиза = тот кто подписал gate → 409 Conflict.
    """
    if release_initiated_by and gate_decided_by and release_initiated_by == gate_decided_by:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{resource}: initiator cannot approve own gates "
                   f"(initiated_by={release_initiated_by}, decided_by={gate_decided_by})",
        )


def verify_sod_batch(release_meta: dict, gate_decisions: list[dict]) -> None:
    """Пакетная проверка SoD для всех gate-решений релиза."""
    initiated_by = release_meta.get("initiated_by") or release_meta.get("initiator_user_id", "system")
    for gate in gate_decisions:
        decided_by = gate.get("decided_by", "")
        verify_sod(initiated_by, decided_by, f"Release {release_meta.get('id', '?')}")