# -*- coding: utf-8 -*-
"""COS-055: Чистая логика Notification Manager (без БД и I/O).

Здесь живут решения, а не хранение:
  * V1 event taxonomy и aggregate types;
  * subscription policy (ALL / SELECTED / BLOCKLIST);
  * dedup key и backoff-математика;
  * scrubbing секретов из payload для логов;
  * recipient resolution policy (merge membership, explicit override).

Всё синхронно и детерминированно — unit-тесты без PostgreSQL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

# ── V1 event taxonomy (packet scope) ──

EVENT_TYPES_V1: frozenset[str] = frozenset({
    "run_failed",
    "run_succeeded",
    "batch_failed",
    "gate_blocked",
    "gate_passed",
    "release_approved",
    "transfer_completed",
    "transfer_failed",
    "status_change",   # только значимые переходы (решает вызывающая сторона)
})

AGGREGATE_TYPES_V1: frozenset[str] = frozenset({
    "run", "batch", "gate", "release", "transfer",
})

SEVERITIES_V1: frozenset[str] = frozenset({"critical", "high", "medium", "low", "info"})

# Наследуется от COS-065: дефолтная severity по типу события.
DEFAULT_SEVERITY: Dict[str, str] = {
    "gate_blocked": "critical",
    "run_failed": "high",
    "batch_failed": "high",
    "transfer_failed": "high",
    "gate_passed": "info",
    "run_succeeded": "info",
    "transfer_completed": "medium",
    "status_change": "info",
    "release_approved": "info",
}


# ── Subscription policy ──


@dataclass
class SubscriptionPolicy:
    """Per-user политика подписки. Отсутствие записи = ALL."""

    user_id: str
    mode: str = "all"                                   # all | selected | blocklist
    selected_event_types: List[str] = field(default_factory=list)
    blocked_event_types: List[str] = field(default_factory=list)

    def allows(self, event_type: str) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "selected":
            return event_type in self.selected_event_types
        if self.mode == "blocklist":
            return event_type not in self.blocked_event_types
        return False


def policy_from_row(user_id: str, policy: str,
                    selected: Sequence[str], blocked: Sequence[str]) -> SubscriptionPolicy:
    """Собрать политику из строки БД с валидацией mode."""
    mode = (policy or "all").strip().lower()
    if mode not in ("all", "selected", "blocklist"):
        mode = "all"
    return SubscriptionPolicy(
        user_id=user_id,
        mode=mode,
        selected_event_types=list(selected or []),
        blocked_event_types=list(blocked or []),
    )


# ── Dedup & backoff ──


def inbox_dedup_key(event_id: str, recipient_id: str, channel: str) -> str:
    """Устойчивый idempotency key доставки: event_id + recipient + channel."""
    return f"{event_id}::{recipient_id}::{channel}"


def next_backoff_seconds(attempt: int, base_s: float = 30.0, cap_s: float = 3600.0) -> float:
    """Экспоненциальный backoff: 30s, 60s, 120s, ... с потолком 1 час.

    attempt — номер ТЕКУЩЕЙ неудачной попытки (1-based).
    """
    if attempt < 1:
        attempt = 1
    return min(base_s * (2 ** (attempt - 1)), cap_s)


# ── Payload scrubbing (логи без секретов) ──

_SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|passwd|authorization|auth|api_key|apikey|signature|credential)",
    re.IGNORECASE,
)
_MAX_VALUE_LEN = 200
_REDACTED = "[REDACTED]"


def scrub_payload(payload: Any, max_value_len: int = _MAX_VALUE_LEN) -> Any:
    """Рекурсивно вычистить секреты и обрезать длинные значения.

    Ключи, совпадающие с _SENSITIVE_KEY_RE, заменяются на [REDACTED].
    Значения длиннее max_value_len обрезаются. Структуры (dict/list)
    сохраняются, но ограничиваются по глубине (защита от циклов).
    """
    return _scrub(payload, max_value_len, depth=0)


def _scrub(value: Any, max_len: int, depth: int) -> Any:
    if depth > 6:
        return "..."
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if _SENSITIVE_KEY_RE.search(key):
                out[key] = _REDACTED
            else:
                out[key] = _scrub(v, max_len, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(v, max_len, depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return value[:max_len] + ("..." if len(value) > max_len else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_len]


def safe_log_line(prefix: str, payload: Mapping[str, Any]) -> str:
    """Готовая строка для логгера: scrubbed payload, одна строка."""
    import json
    cleaned = scrub_payload(payload)
    try:
        return f"{prefix} {json.dumps(cleaned, ensure_ascii=False, default=str)}"
    except Exception:
        return f"{prefix} <unserializable payload>"


# ── Recipient resolution policy ──


def extract_member_ids(members: Optional[Sequence[Mapping[str, Any]]]) -> List[str]:
    """Достать идентификаторы участников из JSON-структуры команды.

    Понимает поля email / user_id / id; пустые и нестроковые значения
    пропускает. Порядок сохраняется, дубликаты убираются.
    """
    if not members:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for m in members:
        if not isinstance(m, Mapping):
            if isinstance(m, str) and m.strip():
                mid = m.strip()
                if mid not in seen:
                    seen.add(mid)
                    out.append(mid)
            continue
        mid = ""
        for field_name in ("user_id", "email", "id"):
            value = m.get(field_name)
            if isinstance(value, str) and value.strip():
                mid = value.strip()
                break
        if mid and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def merge_membership(
    inherited: Optional[Sequence[Mapping[str, Any]]],
    local: Optional[Sequence[Mapping[str, Any]]],
    exclusions: Optional[Sequence[str]],
) -> List[str]:
    """Merge команды: inherited + local − exclusions (по id, порядок сохранён)."""
    excluded = {e.strip() for e in (exclusions or []) if isinstance(e, str) and e.strip()}
    merged: List[str] = []
    seen: set[str] = set()
    for mid in extract_member_ids(inherited) + extract_member_ids(local):
        if mid in excluded or mid in seen:
            continue
        seen.add(mid)
        merged.append(mid)
    return merged


def resolve_recipients(
    explicit: Optional[Sequence[str]],
    project_members: Optional[List[str]] = None,
    app_members: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """Итоговые получатели события.

    Приоритет: explicit > project membership > app membership.
    None — получателей нет (вызывающая сторона обязана обработать явно,
    silently dropped event запрещён каноном).
    """
    if explicit:
        deduped: List[str] = []
        seen: set[str] = set()
        for r in explicit:
            r = (r or "").strip()
            if r and r not in seen:
                seen.add(r)
                deduped.append(r)
        return deduped or None
    if project_members:
        return list(project_members)
    if app_members:
        return list(app_members)
    return None


def looks_like_email(recipient_id: str) -> bool:
    """V1: email-канал доставляется только на адреса, похожие на email."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", recipient_id or ""))
