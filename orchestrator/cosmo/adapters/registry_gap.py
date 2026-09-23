# -*- coding: utf-8 -*-
"""COS-163: GAP-режим enforce — честная ошибка вместо молчания/лужи.

Closed network (GAP): push разрешён только в локальный registry (local-oci);
внешние публичные registry (docker.io / ghcr.io / quay.io / gcr.io) и
не-local-oci провайдеры (nexus / t1_sfera) в GAP-режиме блокируются с
понятной ошибкой ``RegistryGapError`` (code + message) — не молчание, не
частичный push.

Политика — ``registry_audit.GapModePolicy.is_allowed_operation`` (уже
существовала, не дублируем). Здесь — только её обвязка в исключение с кодом.
"""
from __future__ import annotations

from typing import Optional

from orchestrator.cosmo.adapters.registry_audit import GapModePolicy

#: Код блокировки внешнего registry (публичный интернет).
CODE_EXTERNAL_REGISTRY = "GAP_EXTERNAL_REGISTRY_BLOCKED"
#: Код блокировки провайдера (не local-oci).
CODE_PROVIDER_NOT_ALLOWED = "GAP_PROVIDER_NOT_ALLOWED"
#: Код блокировки типа операции.
CODE_OPERATION_NOT_ALLOWED = "GAP_OPERATION_NOT_ALLOWED"


class RegistryGapError(RuntimeError):
    """Честная ошибка GAP-режима: операция с registry заблокирована.

    ``code`` — стабильный машинный код, ``message`` — человекочитаемая
    причина. Наличие обоих — часть контракта acceptance («понятный
    code/message», не пустой HTTP-500).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        endpoint: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.endpoint = endpoint
        self.provider = provider

    def __str__(self) -> str:  # pragma: no cover - диагностика
        return f"{self.code}: {self.message}"


def _classify(reason: str) -> str:
    """Сопоставить причину блокировки со стабильным кодом."""
    if "external registry blocked" in reason:
        return CODE_EXTERNAL_REGISTRY
    if "provider" in reason and "not allowed" in reason:
        return CODE_PROVIDER_NOT_ALLOWED
    return CODE_OPERATION_NOT_ALLOWED


def enforce_gap_push(
    provider: str,
    endpoint: str,
    *,
    operation_type: str = "push",
) -> None:
    """Проверить операцию на соответствие GAP-режиму; иначе — RegistryGapError.

    :param provider: значение ``RegistryProvider`` (``"local-oci"`` и т.п.).
    :param endpoint: endpoint registry (host:port или полный URL).
    :param operation_type: ``push`` / ``pull`` / ``manifest`` / ``health``.
    :raises RegistryGapError: если операция запрещена в GAP-режиме.
    """
    allowed, reason = GapModePolicy.is_allowed_operation(
        operation_type, provider, endpoint
    )
    if not allowed:
        raise RegistryGapError(
            code=_classify(reason),
            message=reason,
            endpoint=endpoint,
            provider=provider,
        )


__all__ = [
    "RegistryGapError",
    "enforce_gap_push",
    "CODE_EXTERNAL_REGISTRY",
    "CODE_PROVIDER_NOT_ALLOWED",
    "CODE_OPERATION_NOT_ALLOWED",
]