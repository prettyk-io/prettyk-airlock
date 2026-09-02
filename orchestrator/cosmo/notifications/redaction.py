"""
COS-055: Redaction — безопасная очистка чувствительных данных перед логами.

Правило пакета: в логах нет секретов и полного чувствительного payload.
Durable storage (PostgreSQL) хранит payload как есть — source of truth;
redaction применяется к logger-выводу и к last_error.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

_REDACTED = "***redacted***"

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)password|passwd|secret|token|authorization|auth|api[_-]?key|"
    r"apikey|cookie|credential|private[_-]?key|session[_-]?id|bearer"
)

# COS-079: sensitive key WITH its value ("password=hunter2", "token: abc xyz").
# Value may contain spaces until the next key-like token / separator / end.
_SENSITIVE_KV_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|auth|api[_-]?key|"
    r"apikey|cookie|credential|private[_-]?key|session[_-]?id|bearer)\b"
    r"\s*[:=]\s*[^\s;,&]+(?:\s+[^\s;,&]+)*"
)

_MAX_TEXT_LEN = 2000


def is_sensitive_key(key: str) -> bool:
    """True, если имя поля выглядит чувствительным."""
    return bool(_SENSITIVE_KEY_RE.search(key or ""))


def hash_identifier(value: str) -> str:
    """COS-079: стабильный короткий хеш идентификатора для логов.

    recipient_id/email/user_id не должны появляться в логах в открытом виде;
    хеш сохраняет корреляцию между строками лога без раскрытия значения.
    """
    if not value:
        return ""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def redact_details(details: Any, _depth: int = 0) -> Any:
    """Глубокая очистка dict/list структур от чувствительных полей.

    Строки обрезаются до _MAX_TEXT_LEN (лог не раздувается payload'ом).
    Не мутирует вход — возвращает копию.
    """
    if _depth > 8:  # защита от циклических/глубоких структур
        return _REDACTED
    if isinstance(details, dict):
        out: dict[str, Any] = {}
        for k, v in details.items():
            if is_sensitive_key(str(k)):
                out[str(k)] = _REDACTED
            else:
                out[str(k)] = redact_details(v, _depth + 1)
        return out
    if isinstance(details, (list, tuple)):
        return [redact_details(v, _depth + 1) for v in details]
    if isinstance(details, str):
        return details[:_MAX_TEXT_LEN]
    return details


def redact_text(text: str, max_len: int = _MAX_TEXT_LEN) -> str:
    """Очистка произвольного текста (например, текста исключения) для лога/last_error.

    COS-079: маскируется пара key=value целиком (раньше маскировался только
    ключ — значение утекало в лог), затем остаются голые упоминания ключей.
    """
    if not text:
        return ""
    cleaned = _SENSITIVE_KV_RE.sub("[sensitive]", text)
    cleaned = _SENSITIVE_KEY_RE.sub("[sensitive]", cleaned)
    return cleaned[:max_len]
