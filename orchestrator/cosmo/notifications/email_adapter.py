# -*- coding: utf-8 -*-
"""
COS-057: Email provider adapter против provider-neutral seam (COS-055).

Границы карточки:
  - manager.py / routes НЕ меняются: adapter — реализация EmailProvider
    Protocol (providers.py), семантика dedup/retry/DLQ остаётся в manager;
  - production SMTP транспорт НЕ выдумывается: транспорт инжектируется
    (EmailTransport seam), без live-подключения adapter тестируется офлайн;
  - фейл доставки наблюдаем: transient (retry) vs permanent (DLQ)
    различимы по SMTP-семантике кодов ответа;
  - redaction: ни получатели, ни секреты не попадают в логи и в error-строки.

Классификация SMTP-исходов (честная, документированная):
    2xx                → accepted
    4xx / 3xx          → transient (retry по backoff manager'а)
    5xx                → permanent → DLQ
    exception транспорта → transient (сеть/timeout; manager ограничит attempts)
    код неизвестен     → transient (письмо не теряется молча; DLQ после
                         исчерпания attempts — фейл всё равно наблюдаем)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Union

from orchestrator.cosmo.notifications.policy import looks_like_email, safe_log_line
from orchestrator.cosmo.notifications.providers import EmailDeliveryResult
from orchestrator.cosmo.notifications.redaction import redact_text

logger = logging.getLogger("cosmoport.notifications.email")

# Адреса получателей вычищаются из error-строк: они могут попасть в
# произвольные лог-сinks через last_error; durable source of truth —
# notification_inbox.recipient_id, дублирование не нужно.
_EMAIL_RE = re.compile(r"[^<>\s]+@[^<>\s]+\.[^<>\s]+")

# redact_text (COS-055) маскирует только КЛЮЧ (token=x → [sensitive]=x) —
# значение остаётся. Adapter вычищает и значение: belt-and-suspenders
# в своём модуле, контракт чужого файла не меняется.
_KV_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|api[_-]?key|"
    r"apikey|cookie|credential|private[_-]?key|session[_-]?id|bearer)\b"
    r"(\s*[:=]\s*)(\S+)"
)


def _scrub_recipients(text: str) -> str:
    if not text:
        return ""
    return _EMAIL_RE.sub("[recipient]", text)


def _scrub_secret_values(text: str) -> str:
    if not text:
        return ""
    return _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def safe_error_text(raw: str, max_len: int = 500) -> str:
    """Error-строка провайдера: секреты + получатели вычищены, длина ограничена."""
    if not raw:
        return ""
    return redact_text(_scrub_recipients(_scrub_secret_values(str(raw))))[:max_len]


# ── Transport seam (офлайн) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class TransportOutcome:
    """Сырой ответ транспорта. code=None — транспорт не вернул SMTP-код
    (соединение не установлено / протокол не SMTP) → классифицируется
    как transient, не маскируется."""

    code: Optional[int] = None
    message: str = ""


class EmailTransport(Protocol):
    """Инжектируемый транспорт (SMTP-клиент появится отдельной карточкой).

    Реализация НЕ должна бросать исключения для SMTP-отказов — они
    возвращаются как TransportOutcome с кодом. Бросок исключения
    допустим только для транспортных сбоев (сеть/timeout) — adapter
    классифицирует их как transient честно.
    """

    def deliver(self, to: str, subject: str, body: str) -> TransportOutcome:  # noqa: D401
        ...


# ── Adapter ─────────────────────────────────────────────────────────────────


class SmtpEmailProvider:
    """Email provider adapter: транспорт-агностик, классификация + redaction.

    Реализует EmailProvider Protocol из COS-055. Ответственность adapter'а:
      1) отвалидировать адрес получателя (permanent до транспорта);
      2) классифицировать SMTP-исход в accepted/transient/permanent;
      3) вычистить recipients/secrets из error-строк;
      4) логировать БЕЗ получателей и секретов.
    Никакой notification semantics (retry/DLQ/dedup) внутри — это manager.
    """

    def __init__(
        self,
        transport: EmailTransport,
        *,
        provider_id: str = "smtp",
    ) -> None:
        self._transport = transport
        self.provider_id = provider_id

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        if not looks_like_email(to):
            # permanent: неверный адрес не починит retry; адрес в лог не пишем.
            logger.warning(safe_log_line("[EMAIL:adapter] invalid recipient format", {
                "provider": self.provider_id,
                "outcome": "permanent",
                "reason": "invalid_recipient_format",
                "subject_len": len(subject or ""),
            }))
            return EmailDeliveryResult(
                accepted=False,
                transient=False,
                error="invalid recipient address format",
            )

        try:
            outcome = self._transport.deliver(to=to, subject=subject, body=body)
        except Exception as exc:  # транспортный сбой → transient (не маскируем detail)
            error = safe_error_text(str(exc))
            logger.warning(safe_log_line("[EMAIL:adapter] transport failure", {
                "provider": self.provider_id,
                "outcome": "transient",
                "reason": "transport_exception",
                "subject_len": len(subject or ""),
                "body_len": len(body or ""),
            }))
            return EmailDeliveryResult(accepted=False, transient=True, error=error)

        code = outcome.code
        message = safe_error_text(outcome.message)

        if code is not None and 200 <= code < 300:
            logger.info(safe_log_line("[EMAIL:adapter] accepted", {
                "provider": self.provider_id,
                "outcome": "accepted",
                "code": code,
                "subject_len": len(subject or ""),
                "body_len": len(body or ""),
            }))
            return EmailDeliveryResult(accepted=True)

        if code is not None and 500 <= code < 600:
            # 5xx — permanent → DLQ-видимость у manager.
            logger.error(safe_log_line("[EMAIL:adapter] permanent refusal", {
                "provider": self.provider_id,
                "outcome": "permanent",
                "code": code,
                "subject_len": len(subject or ""),
            }))
            return EmailDeliveryResult(
                accepted=False, transient=False,
                error=f"smtp {code}" + (f": {message}" if message else ""),
            )

        # 3xx/4xx и неизвестные коды (включая None) — temporary ситуация:
        # retry, потом DLQ при исчерпании. Письмо не теряется молча.
        logger.warning(safe_log_line("[EMAIL:adapter] transient refusal", {
            "provider": self.provider_id,
            "outcome": "transient",
            "code": code,
            "subject_len": len(subject or ""),
        }))
        detail = message if message else (
            "transport returned no code" if code is None else ""
        )
        return EmailDeliveryResult(
            accepted=False, transient=True,
            error=f"smtp {code}" + (f": {detail}" if detail else ""),
        )


# ── Fake provider (тесты + ops-проверки) ────────────────────────────────────


class FakeEmailProvider:
    """Детерминированный fake против того же seam — для тестов контракта.

    Скрипт: последовательность EmailDeliveryResult или исключений; после
    исчерпания возвращается default (accepted). Все вызовы фиксируются
    в calls (in-memory test double — это НЕ лог-синк, redaction-правила
    применяются к логам/ошибкам, а не к структуре тест-дабла).
    """

    def __init__(
        self,
        script: Optional[List[Union[EmailDeliveryResult, Exception]]] = None,
        *,
        default: Optional[EmailDeliveryResult] = None,
    ) -> None:
        self._script = list(script or [])
        self._default = default or EmailDeliveryResult(accepted=True)
        self.calls: List[dict] = []

    @staticmethod
    def accepted() -> EmailDeliveryResult:
        return EmailDeliveryResult(accepted=True)

    @staticmethod
    def transient(error: str = "smtp transient code 451") -> EmailDeliveryResult:
        return EmailDeliveryResult(accepted=False, transient=True, error=error)

    @staticmethod
    def permanent(error: str = "smtp permanent code 550") -> EmailDeliveryResult:
        return EmailDeliveryResult(accepted=False, transient=False, error=error)

    def send(self, to: str, subject: str, body: str) -> EmailDeliveryResult:
        self.calls.append({
            "to": to, "subject": subject, "body_len": len(body or ""),
        })
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self._default

    @property
    def call_count(self) -> int:
        return len(self.calls)
