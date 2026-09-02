# -*- coding: utf-8 -*-
"""COS-058: Transfer Registry — API-side runtime store for the transfer kernel.

In-memory V1 store поверх принятого kernel (COS-050/COS-053):
  - TransferPlan / TransferItem с domain ownership (kernel не знает о доменах).
  - Per-item LandingStateMachine (ленивая инициализация).
  - Глобальный индекс полученных revision keys для кросс-item idempotency.

Инварианты:
  - Kernel contract files не изменяются — registry только оборачивает их.
  - Персистентная граница — declared follow-up (см. acceptance COS-050/053);
    здесь сознательно in-memory, новая архитектура хранения вне scope COS-058.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.cosmo.transfer.contract import (
    TransferFailureClass,
    TransferItem,
    TransferPlan,
)
from orchestrator.cosmo.transfer.landing import (
    LandingState,
    LandingStateMachine,
)


class DuplicateRevisionError(Exception):
    """Та же package revision уже получена другим TransferItem (idempotency conflict)."""

    def __init__(self, revision_key: str, existing_item_id: str, incoming_item_id: str):
        self.revision_key = revision_key
        self.existing_item_id = existing_item_id
        self.incoming_item_id = incoming_item_id
        super().__init__(
            f"Package revision '{revision_key}' already received by item "
            f"'{existing_item_id}' (incoming: '{incoming_item_id}')"
        )


@dataclass
class PlanEntry:
    """Plan + domain ownership + landing state machines по каждому item."""
    plan: TransferPlan
    domain_id: str
    landing: Dict[str, LandingStateMachine] = field(default_factory=dict)

    def landing_for(self, item: TransferItem) -> LandingStateMachine:
        """Ленивая инициализация landing state machine для item."""
        sm = self.landing.get(item.item_id)
        if sm is None:
            sm = LandingStateMachine(item)
            self.landing[item.item_id] = sm
        return sm


class TransferRegistry:
    """Thread-safe in-memory registry: plans, items, landing states, revisions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._plans: Dict[str, PlanEntry] = {}
        self._items: Dict[str, Tuple[str, TransferItem]] = {}  # item_id -> (plan_id, item)
        self._received_revisions: Dict[str, str] = {}  # revision_key -> item_id
        self._transfer_events: List[Dict] = []  # COS-074: runtime failure log

    # ── lifecycle ────────────────────────────────────────────────────

    def reset(self) -> None:
        """Полная очистка (тестовая изоляция / restart semantics)."""
        with self._lock:
            self._plans.clear()
            self._items.clear()
            self._received_revisions.clear()
            self._transfer_events.clear()

    # ── writes ───────────────────────────────────────────────────────

    def register_plan(self, plan: TransferPlan, domain_id: str) -> PlanEntry:
        """Зарегистрировать план с items. Коллизии plan_id/item_id → ValueError."""
        with self._lock:
            if plan.plan_id in self._plans:
                raise ValueError(f"Transfer plan '{plan.plan_id}' already exists")
            for item in plan.items:
                if item.item_id in self._items:
                    raise ValueError(f"Transfer item '{item.item_id}' already exists")
            entry = PlanEntry(plan=plan, domain_id=domain_id)
            self._plans[plan.plan_id] = entry
            for item in plan.items:
                self._items[item.item_id] = (plan.plan_id, item)
            return entry

    def register_received_revision(self, revision_key: str, item_id: str) -> None:
        """Зафиксировать получение revision.

        Кросс-item дубликат той же revision → DuplicateRevisionError.
        Повторная регистрация тем же item — idempotent no-op.
        """
        with self._lock:
            existing = self._received_revisions.get(revision_key)
            if existing is not None and existing != item_id:
                raise DuplicateRevisionError(revision_key, existing, item_id)
            self._received_revisions[revision_key] = item_id

    # ── COS-074: transfer failure path ───────────────────────────────

    def _item_ref(self, item_id: str) -> Tuple[PlanEntry, TransferItem]:
        ref = self._items.get(item_id)
        if ref is None:
            raise KeyError(f"Transfer item '{item_id}' is not registered")
        plan_id, item = ref
        entry = self._plans[plan_id]
        return entry, item

    def _log_event(self, event: str, item_id: str, failure_class: Any,
                   detail: str, sm: LandingStateMachine) -> None:
        self._transfer_events.append({
            "event": event,
            "item_id": item_id,
            "failure_class": failure_class.value if failure_class else None,
            "detail": detail,
            "from_state": sm.state.value,
            "to_state": sm.state.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_transfer_retryable(self, item_id: str,
                                  failure_class: Optional[TransferFailureClass],
                                  detail: str = "") -> int:
        """Retryable transport failure: retry_count+1, состояние НЕ меняется.

        Возвращает новый retry_count. Неизвестный item → KeyError.
        """
        with self._lock:
            entry, item = self._item_ref(item_id)
            sm = entry.landing_for(item)
            item.retry_count += 1
            item.failure_class = failure_class
            item.failure_detail = detail
            self._log_event("transfer_retryable", item_id, failure_class, detail, sm)
            return item.retry_count

    def record_transfer_failed(self, item_id: str,
                               failure_class: Optional[TransferFailureClass],
                               detail: str = "") -> LandingState:
        """Терминальный transfer_failed: NOT_RECEIVED → TRANSFER_FAILED.

        Идемпотентен: уже TRANSFER_FAILED → no-op. Иначе недопустимый
        переход (например после RECEIVED) → LandingStateError — target
        что-то получил, «транспортный провал» лгать не может.
        """
        with self._lock:
            entry, item = self._item_ref(item_id)
            sm = entry.landing_for(item)
            if sm.state is LandingState.TRANSFER_FAILED:
                return sm.state  # idempotent terminal no-op
            prev = sm.state
            sm.transition(LandingState.TRANSFER_FAILED, reason=detail)
            item.failure_class = failure_class
            item.failure_detail = detail
            self._log_event("transfer_failed", item_id, failure_class, detail, sm)
            event = self._transfer_events[-1]
            event["from_state"] = prev.value
            return sm.state

    def transfer_events(self, item_id: Optional[str] = None) -> List[Dict]:
        """Runtime failure log (опционально отфильтрованный по item)."""
        with self._lock:
            events = list(self._transfer_events)
        if item_id is not None:
            events = [e for e in events if e["item_id"] == item_id]
        return events

    # ── reads ────────────────────────────────────────────────────────

    def get_plan(self, plan_id: str) -> Optional[PlanEntry]:
        with self._lock:
            return self._plans.get(plan_id)

    def get_item(self, item_id: str) -> Optional[Tuple[PlanEntry, TransferItem]]:
        with self._lock:
            ref = self._items.get(item_id)
            if ref is None:
                return None
            plan_id, item = ref
            entry = self._plans.get(plan_id)
        if entry is None:  # pragma: no cover — item всегда ссылается на план
            return None
        return entry, item

    def plans_for_release(self, release_id: str) -> List[PlanEntry]:
        with self._lock:
            return [e for e in self._plans.values() if e.plan.release_id == release_id]


# ── singleton accessor ───────────────────────────────────────────────

_registry: Optional[TransferRegistry] = None
_registry_lock = threading.Lock()


def get_transfer_registry() -> TransferRegistry:
    """Process-wide singleton (in-memory V1)."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = TransferRegistry()
        return _registry
