# -*- coding: utf-8 -*-
"""Durable Transfer Registry — PostgreSQL repository за TransferRegistry контрактом.

In-memory TransferRegistry (orchestrator/cosmo/transfer/registry.py) остаётся
API-side runtime store; этот модуль добавляет персистентную реализацию того же
поведенческого контракта поверх transfer_plans / transfer_items /
transfer_landing_states / transfer_received_revisions (models_transfer.py).

Контракт (повторяет in-memory):
  - register_plan: дубликат plan_id или item_id → ValueError.
  - register_received_revision: та же revision другим item → DuplicateRevisionError;
    повтор тем же item — idempotent no-op.
  - get_plan / get_item / plans_for_release / reset — как в in-memory.
  - Persistence-specific: save_landing_state / get_landing_state — durable
    snapshot LandingStateMachine (state + history) для restart-survival.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, Tuple

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from orchestrator.cosmo.db.models_transfer import (
    TransferItemRow,
    TransferLandingStateRow,
    TransferPlanRow,
    TransferReceivedRevisionRow,
    TransferRegistryBase,
)
from orchestrator.cosmo.transfer.contract import (
    TransferFailureClass,
    TransferItem,
    TransferPlan,
)
from orchestrator.cosmo.transfer.landing import (
    LandingState,
    LandingStateMachine,
    LandingStateError,
)
from orchestrator.cosmo.transfer.registry import DuplicateRevisionError, PlanEntry


class TransferRegistryRepository(Protocol):
    """Поведенческий контракт durable-хранилища (супермножество in-memory API)."""

    def register_plan(self, plan: TransferPlan, domain_id: str) -> PlanEntry: ...

    def register_received_revision(self, revision_key: str, item_id: str) -> None: ...

    def get_plan(self, plan_id: str) -> Optional[PlanEntry]: ...

    def get_item(self, item_id: str) -> Optional[tuple[PlanEntry, TransferItem]]: ...

    def plans_for_release(self, release_id: str) -> list[PlanEntry]: ...

    def save_landing_state(self, item_id: str, sm: LandingStateMachine) -> None: ...

    def get_landing_state(self, item_id: str) -> Optional[LandingStateMachine]: ...

    def record_transfer_retryable(
        self, item_id: str, failure_class: Optional[TransferFailureClass],
        detail: str = "",
    ) -> int: ...

    def record_transfer_failed(
        self, item_id: str, failure_class: Optional[TransferFailureClass],
        detail: str = "",
    ) -> LandingState: ...

    def reset(self) -> None: ...


class PgTransferRegistryRepository:
    """PostgreSQL-реализация TransferRegistryRepository (sync, session-per-call).

    Потокобезопасность обеспечивают PG-транзакции + PK/UNIQUE ограничения;
    RLock защищает только конкуренцию python-обёртки в одном процессе.
    """

    def __init__(self, engine: Engine | str) -> None:
        if isinstance(engine, str):
            engine = create_engine(engine)
        self._engine = engine
        self._factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        self._lock = threading.RLock()

    # ── session helper ───────────────────────────────────────────────

    def _session(self) -> Session:
        return self._factory()

    # ── reconstruction ───────────────────────────────────────────────

    @staticmethod
    def _plan_from_payload(payload: dict, items: list[TransferItem]) -> TransferPlan:
        data = dict(payload)
        data["items"] = [i.model_dump(mode="json") for i in items]
        return TransferPlan.model_validate(data)

    @staticmethod
    def _landing_from_row(row: TransferLandingStateRow, item: TransferItem) -> LandingStateMachine:
        sm = LandingStateMachine(item)
        sm._state = LandingState(row.state)
        sm._history = list(row.history or [])
        return sm

    def _load_landing(self, session: Session, item_ids: list[str]) -> dict[str, LandingStateMachine]:
        if not item_ids:
            return {}
        rows = session.execute(
            select(TransferLandingStateRow).where(
                TransferLandingStateRow.item_id.in_(item_ids)
            )
        ).scalars().all()
        out: dict[str, LandingStateMachine] = {}
        for row in rows:
            items = session.execute(
                select(TransferItemRow).where(TransferItemRow.item_id == row.item_id)
            ).scalar_one_or_none()
            if items is None:  # pragma: no cover — FK CASCADE гарантирует наличие
                continue
            item = TransferItem.model_validate(items.payload)
            out[row.item_id] = self._landing_from_row(row, item)
        return out

    def _entry_for_plan_row(
        self, session: Session, plan_row: TransferPlanRow
    ) -> PlanEntry:
        item_rows = session.execute(
            select(TransferItemRow)
            .where(TransferItemRow.plan_id == plan_row.plan_id)
            .order_by(TransferItemRow.created_at, TransferItemRow.item_id)
        ).scalars().all()
        items = [TransferItem.model_validate(r.payload) for r in item_rows]
        plan = self._plan_from_payload(plan_row.payload, items)
        landing = self._load_landing(session, [r.item_id for r in item_rows])
        return PlanEntry(plan=plan, domain_id=plan_row.domain_id, landing=landing)

    # ── writes ───────────────────────────────────────────────────────

    def register_plan(self, plan: TransferPlan, domain_id: str) -> PlanEntry:
        session = self._session()
        try:
            if session.get(TransferPlanRow, plan.plan_id) is not None:
                raise ValueError(f"Transfer plan '{plan.plan_id}' already exists")
            for item in plan.items:
                existing = session.execute(
                    select(TransferItemRow.item_id).where(
                        TransferItemRow.item_id == item.item_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    raise ValueError(f"Transfer item '{item.item_id}' already exists")

            plan_payload = plan.model_dump(mode="json", exclude={"items"})
            session.add(TransferPlanRow(
                plan_id=plan.plan_id,
                release_id=plan.release_id,
                domain_id=domain_id,
                correlation_id=plan.correlation_id,
                source_zone=plan.source_zone,
                target_zone=plan.target_zone,
                status=plan.status.value,
                payload=plan_payload,
            ))
            # UoW не знает о зависимости item→plan (нет relationship()) —
            # явный flush гарантирует, что родительская строка вставлена раньше.
            session.flush()
            for item in plan.items:
                session.add(TransferItemRow(
                    item_id=item.item_id,
                    plan_id=plan.plan_id,
                    release_id=item.release_id,
                    correlation_id=item.correlation_id,
                    artifact_plane=item.artifact_plane.value,
                    package_mode=item.package_mode.value,
                    transport_profile=item.transport_profile.value,
                    status=item.status.value,
                    revision_key=item.revision_key,
                    retry_count=item.retry_count,
                    payload=item.model_dump(mode="json"),
                ))
            session.commit()
            plan_row = session.get(TransferPlanRow, plan.plan_id)
            return self._entry_for_plan_row(session, plan_row)
        except IntegrityError as exc:
            session.rollback()
            # Backstop гонки: PK/UNIQUE constraints — те же ошибки контракта.
            raise ValueError(f"Transfer plan/ item conflict: {plan.plan_id}") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def register_received_revision(self, revision_key: str, item_id: str) -> None:
        session = self._session()
        try:
            existing = session.execute(
                select(TransferReceivedRevisionRow).where(
                    TransferReceivedRevisionRow.revision_key == revision_key
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.item_id != item_id:
                    raise DuplicateRevisionError(revision_key, existing.item_id, item_id)
                session.commit()  # idempotent no-op
                return
            session.add(TransferReceivedRevisionRow(revision_key=revision_key, item_id=item_id))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_landing_state(self, item_id: str, sm: LandingStateMachine) -> None:
        """Durable snapshot состояния LandingStateMachine (restart-survival)."""
        session = self._session()
        try:
            if session.get(TransferItemRow, item_id) is None:
                raise ValueError(f"Transfer item '{item_id}' does not exist")
            row = session.get(TransferLandingStateRow, item_id)
            if row is None:
                row = TransferLandingStateRow(item_id=item_id)
                session.add(row)
            row.state = sm.state.value
            row.revision_key = sm.revision_key
            row.history = [dict(h) for h in sm.history]
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── COS-074: transfer failure path (durable mirrors) ─────────────

    @staticmethod
    def _apply_failure_payload(payload: dict, failure_class: Optional[TransferFailureClass],
                               detail: str) -> dict:
        data = dict(payload)
        data["failure_class"] = failure_class.value if failure_class else None
        data["failure_detail"] = detail
        return data

    def record_transfer_retryable(
        self, item_id: str, failure_class: Optional[TransferFailureClass],
        detail: str = "",
    ) -> int:
        """Retryable failure: retry_count+1 в transfer_items, state НЕ меняется."""
        session = self._session()
        try:
            item_row = session.get(TransferItemRow, item_id)
            if item_row is None:
                raise KeyError(f"Transfer item '{item_id}' is not registered")
            item_row.retry_count += 1
            item_row.payload = self._apply_failure_payload(
                item_row.payload, failure_class, detail)
            session.commit()
            return item_row.retry_count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record_transfer_failed(
        self, item_id: str, failure_class: Optional[TransferFailureClass],
        detail: str = "",
    ) -> LandingState:
        """Durable терминал: NOT_RECEIVED → transfer_failed в transfer_landing_states.

        Идемпотентный no-op если уже transfer_failed; недопустимый переход
        (после received и т.п.) → LandingStateError. История перехода и
        failure-поля item'а персистентны (restart-survival).
        """
        session = self._session()
        try:
            item_row = session.get(TransferItemRow, item_id)
            if item_row is None:
                raise KeyError(f"Transfer item '{item_id}' is not registered")
            row = session.get(TransferLandingStateRow, item_id)
            if row is not None:
                current = LandingState(row.state)
                if current is LandingState.TRANSFER_FAILED:
                    session.commit()  # idempotent terminal no-op
                    return LandingState.TRANSFER_FAILED
                if current is not LandingState.NOT_RECEIVED:
                    raise LandingStateError(item_id, current,
                                            LandingState.TRANSFER_FAILED)
                history = list(row.history or [])
            else:
                history = []
            history.append({
                "from": LandingState.NOT_RECEIVED.value,
                "to": LandingState.TRANSFER_FAILED.value,
                "reason": detail,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if row is None:
                row = TransferLandingStateRow(item_id=item_id)
                session.add(row)
            row.state = LandingState.TRANSFER_FAILED.value
            row.revision_key = item_row.revision_key
            row.history = history
            item_row.payload = self._apply_failure_payload(
                item_row.payload, failure_class, detail)
            session.commit()
            return LandingState.TRANSFER_FAILED
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── COS-077: API wiring persistence ──────────────────────────────

    def save_item(self, item: TransferItem) -> None:
        """Персист полного состояния item (status/revision_key/retry_count/payload).

        Вызывается API-слоем после мутаций item'а (validate, landing transition,
        dispatch): индексные колонки и JSONB payload держим согласованными.
        """
        session = self._session()
        try:
            row = session.get(TransferItemRow, item.item_id)
            if row is None:
                raise ValueError(f"Transfer item '{item.item_id}' does not exist")
            row.status = item.status.value
            row.revision_key = item.revision_key
            row.retry_count = item.retry_count
            row.payload = item.model_dump(mode="json")
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_plan(self, plan: TransferPlan) -> None:
        """Персист payload + status плана (после compute_status в API-слое)."""
        session = self._session()
        try:
            row = session.get(TransferPlanRow, plan.plan_id)
            if row is None:
                raise ValueError(f"Transfer plan '{plan.plan_id}' does not exist")
            row.status = plan.status.value
            row.payload = plan.model_dump(mode="json", exclude={"items"})
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def reset(self) -> None:
        """Полная очистка (тестовая изоляция / restart semantics)."""
        session = self._session()
        try:
            session.execute(delete(TransferReceivedRevisionRow))
            session.execute(delete(TransferLandingStateRow))
            session.execute(delete(TransferItemRow))
            session.execute(delete(TransferPlanRow))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── reads ────────────────────────────────────────────────────────

    def get_plan(self, plan_id: str) -> Optional[PlanEntry]:
        session = self._session()
        try:
            plan_row = session.get(TransferPlanRow, plan_id)
            if plan_row is None:
                return None
            return self._entry_for_plan_row(session, plan_row)
        finally:
            session.close()

    def get_item(self, item_id: str) -> Optional[tuple[PlanEntry, TransferItem]]:
        session = self._session()
        try:
            item_row = session.get(TransferItemRow, item_id)
            if item_row is None:
                return None
            plan_row = session.get(TransferPlanRow, item_row.plan_id)
            if plan_row is None:  # pragma: no cover — FK гарантирует план
                return None
            entry = self._entry_for_plan_row(session, plan_row)
            item = next(i for i in entry.plan.items if i.item_id == item_id)
            return entry, item
        finally:
            session.close()

    def plans_for_release(self, release_id: str) -> list[PlanEntry]:
        session = self._session()
        try:
            rows = session.execute(
                select(TransferPlanRow)
                .where(TransferPlanRow.release_id == release_id)
                .order_by(TransferPlanRow.created_at, TransferPlanRow.plan_id)
            ).scalars().all()
            return [self._entry_for_plan_row(session, r) for r in rows]
        finally:
            session.close()

    def get_landing_state(self, item_id: str) -> Optional[LandingStateMachine]:
        session = self._session()
        try:
            row = session.get(TransferLandingStateRow, item_id)
            if row is None:
                return None
            item_row = session.get(TransferItemRow, item_id)
            if item_row is None:  # pragma: no cover — FK CASCADE
                return None
            return self._landing_from_row(row, TransferItem.model_validate(item_row.payload))
        finally:
            session.close()
