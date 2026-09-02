# -*- coding: utf-8 -*-
"""COS-055: Provider-neutral email interface.

Семантика нотификаций (dedup, retry, DLQ) живёт в manager.py —
провайдер только отвечает на один вопрос: принят ли email, и если нет,
то это временная проблема или постоянная.

Результат провайдера:
  accepted=True                      → sent
  accepted=False, transient=True     → retryable_failure (retry по backoff)
  accepted=False, transient=False    → failed (DLQ)

V1: production SMTP не подключается (packet out-of-scope) — интерфейс
готов, дефолтный провайдер пишет в лог (deliver-into-log честно
возвращается как принятый).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from orchestrator.cosmo.notifications.policy import safe_log_line

logger = logging.getLogger("cosmoport.notifications.email")


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Ответ провайдера. transient различает retry и DLQ."""

    accepted: bool
    transient: bool = False
    error: str = ""


class EmailProvider(Protocol):
    """Provider-neutral контракт. Никакой notification semantics внутри."""

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        ...


class LoggingEmailProvider:
    """Дефолтный V1 провайдер: структурированный лог, всегда accepted.

    Payload лога scrubbed (без секретов и чувствительных данных).
    """

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        logger.info(
            safe_log_line(
                "[EMAIL:accepted]",
                {"to": to, "subject": subject[:120], "body_len": len(body)},
            )
        )
        return EmailDeliveryResult(accepted=True)


class ConfiguredEmailProvider:
    """Обёртка над настраиваемым результатом — для ops-проверок и тестов.

    В production конструируется поверх реального SMTP-клиента, когда тот
    будет добавлен отдельной карточкой; до этого интерфейс фиксирует
    границу: провайдер не знает про event_id, recipients-резолвинг, retry.
    """

    def __init__(self, result: EmailDeliveryResult) -> None:
        self._result = result

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        logger.warning(
            safe_log_line(
                "[EMAIL:configured-provider]",
                {"to": to, "subject": subject[:120], "accepted": self._result.accepted},
            )
        )
        return self._result


def default_provider() -> EmailProvider:
    """Провайдер по умолчанию для V1."""
    return LoggingEmailProvider()
