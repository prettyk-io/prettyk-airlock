# -*- coding: utf-8 -*-
"""FINAL-BOSS-002: Persistent Release Orchestration Pipeline.

Survives restarts, idempotent, explicit blockage reasons.
Uses existing ORM (models.py + models_lr.py) — no new tables.
Connects ReleaseOrchestrator to PostgreSQL persistence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Blockage Reasons ──

class BlockageReason(str, Enum):
    BLOCKED_BY_DEPENDENCY = "blocked_by_dependency"
    MISSING_ARTIFACT_DIGEST = "missing_artifact_digest"
    MISSING_PRETTYK_VERDICT = "missing_prettyk_verdict"
    MISSING_ACT = "missing_act"
    GATE_NOT_PASSED = "gate_not_passed"
    BUILD_NOT_FOUND = "build_not_found"
    RELEASE_TYPE_NOT_FOUND = "release_type_not_found"
    BATCH_ALREADY_CLOSED = "batch_already_closed"


class ReleasePipelineStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_PRETTYK = "awaiting_prettyk"
    GATES_EVALUATING = "gates_evaluating"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


# ── Pipeline State Models ──

class AppReleaseState(BaseModel):
    """Per-app state within a batch (serialized to ReleaseBatch.app_release_states JSON)."""
    model_config = ConfigDict(extra="ignore")
    app_id: str
    release_id: str
    build_id: Optional[str] = None
    artifact_digest: Optional[str] = None
    status: ReleasePipelineStatus = ReleasePipelineStatus.DRAFT
    gate_decisions: dict[str, str] = Field(default_factory=dict)
    prettyk_verdict: Optional[bool] = None
    act_attached: bool = False
    blockage: Optional[BlockageReason] = None
    blockage_detail: str = ""
    retry_count: int = 0
    completed_at: Optional[str] = None


class PersistentReleasePipeline:
    """FINAL-BOSS-002: Release pipeline backed by PostgreSQL.

    Idempotent — create-or-get for batches. Survives restarts by reading state from PG.
    """

    def __init__(self, db_session_factory: Callable[[], Any] | None = None):
        self._db = db_session_factory

    # ── Public API ──

    def create_or_get_batch(
        self,
        project_id: str,
        batch_name: str,
        release_type_id: str,
        app_ids: list[str],
    ) -> dict[str, Any]:
        """Idempotent: create a ReleaseBatch or return existing.

        Returns: {batch, is_new, blockage_reasons: {app_id: reason_or_none}}.
        """
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            # Idempotency: same project + name + release_type → return existing
            existing = (
                s.query(RB)
                .filter(RB.project_id == project_id, RB.name == batch_name, RB.release_type_id == release_type_id)
                .order_by(RB.created_at.desc())
                .first()
            )
            if existing is not None:
                return self._to_batch_dict(existing, is_new=False)

            batch_id = f"batch-{hashlib.sha256(f'{project_id}|{batch_name}|{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:12]}"

            orm = RB(
                id=batch_id, project_id=project_id, release_type_id=release_type_id,
                name=batch_name, status="draft", app_ids=app_ids,
            )
            s.add(orm)
            s.commit()
            # Re-query to get default values
            batch = s.query(RB).filter(RB.id == batch_id).first()
            return self._to_batch_dict(batch, is_new=True)
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def start_batch(self, batch_id: str) -> dict[str, Any]:
        """Transition batch to running. Initializes per-app states."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            if batch is None:
                return {"error": "not_found", "batch_id": batch_id}
            if batch.status != "draft":
                return {"error": "batch_already_closed", "status": batch.status}

            # Initialize app states
            app_states = {}
            blockage_reasons = {}
            for aid in batch.app_ids or []:
                blockage = self._check_app_blockage(aid, batch.release_type_id, s)
                app_states[aid] = AppReleaseState(
                    app_id=aid,
                    release_id=f"rel-{aid}-{batch_id[:8]}",
                    status=ReleasePipelineStatus.BLOCKED if blockage else ReleasePipelineStatus.QUEUED,
                    blockage=blockage,
                    blockage_detail=str(blockage.value) if blockage else "",
                ).model_dump()
                blockage_reasons[aid] = blockage.value if blockage else None

            batch.status = "running"
            batch.started_at = datetime.now(timezone.utc)
            # Store app_states in app_ids JSON (extend the field usage)
            setattr(batch, 'app_release_states', app_states)
            s.commit()

            return {
                "batch_id": batch.id,
                "status": batch.status,
                "app_states": app_states,
                "blockage_reasons": blockage_reasons,
            }
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def record_build_and_digest(
        self, batch_id: str, app_id: str, build_id: str, digest_sha256: str,
    ) -> dict[str, Any]:
        """Link a build + immutable artifact digest to an app in the batch."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            if batch is None:
                return {"error": "not_found"}

            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id) or {"app_id": app_id, "release_id": f"rel-{app_id}-{batch_id[:8]}"}
            state["build_id"] = build_id
            state["artifact_digest"] = digest_sha256

            # Resolve blockage: if was blocked by missing digest, unblock
            if state.get("blockage") == BlockageReason.MISSING_ARTIFACT_DIGEST.value:
                state["blockage"] = None
                state["blockage_detail"] = ""
                # Re-check all blockages
                remaining = self._check_app_blockage(app_id, batch.release_type_id, s)
                if remaining is None:
                    state["status"] = ReleasePipelineStatus.QUEUED.value

            states[app_id] = state
            setattr(batch, 'app_release_states', states)
            s.commit()

            return {"app_id": app_id, "build_id": build_id, "digest_sha256": digest_sha256,
                    "blockage_resolved": state.get("blockage") is None}
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def record_prettyk_verdict(
        self, batch_id: str, app_id: str, verdict: bool,
    ) -> dict[str, Any]:
        """Record PrettyK QG result for an app."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            if batch is None:
                return {"error": "not_found"}

            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id, {"app_id": app_id, "release_id": f"rel-{app_id}-{batch_id[:8]}"})
            state["prettyk_verdict"] = verdict

            if not verdict:
                state["blockage"] = BlockageReason.MISSING_PRETTYK_VERDICT.value
                state["blockage_detail"] = "PrettyK QG returned FAIL"
                state["status"] = ReleasePipelineStatus.BLOCKED.value
            elif state.get("blockage") == BlockageReason.MISSING_PRETTYK_VERDICT.value:
                state["blockage"] = None
                state["blockage_detail"] = ""

            states[app_id] = state
            setattr(batch, 'app_release_states', states)
            s.commit()

            return {"app_id": app_id, "verdict": verdict, "status": state["status"]}
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def record_act(self, batch_id: str, app_id: str, act_ref: str) -> dict[str, Any]:
        """Record GOST Act attachment."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id, {"app_id": app_id, "release_id": f"rel-{app_id}-{batch_id[:8]}"})
            state["act_attached"] = True
            state["act_ref"] = act_ref

            if state.get("blockage") == BlockageReason.MISSING_ACT.value:
                state["blockage"] = None
                state["blockage_detail"] = ""

            states[app_id] = state
            setattr(batch, 'app_release_states', states)
            s.commit()
            return {"app_id": app_id, "act_ref": act_ref}
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def record_gate_decision(
        self, batch_id: str, app_id: str, gate_id: str, decision: str,
    ) -> dict[str, Any]:
        """Record gate pass/block for an app."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id, {"app_id": app_id, "release_id": f"rel-{app_id}-{batch_id[:8]}"})
            gd = state.setdefault("gate_decisions", {})
            gd[gate_id] = decision

            if decision != "pass":
                state["blockage"] = BlockageReason.GATE_NOT_PASSED.value
                state["blockage_detail"] = f"Gate {gate_id}: {decision}"
                state["status"] = ReleasePipelineStatus.BLOCKED.value

            states[app_id] = state
            setattr(batch, 'app_release_states', states)
            s.commit()
            return {"app_id": app_id, "gate_id": gate_id, "decision": decision}
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def complete_app_release(self, batch_id: str, app_id: str, success: bool) -> dict[str, Any]:
        """Mark an individual app release as completed."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id, {})

            if success:
                state["status"] = ReleasePipelineStatus.SUCCEEDED.value
            else:
                state["status"] = ReleasePipelineStatus.FAILED.value
            state["completed_at"] = datetime.now(timezone.utc).isoformat()

            states[app_id] = state
            setattr(batch, 'app_release_states', states)

            # Compute batch status
            all_states = list(states.values())
            if all(s.get("status") == "succeeded" for s in all_states):
                batch.status = "completed"
            elif any(s.get("status") == "succeeded" for s in all_states) and any(
                s.get("status") in ("failed", "blocked") for s in all_states
            ):
                batch.status = "partially_succeeded"
            elif all(s.get("status") == "failed" for s in all_states):
                batch.status = "failed"

            s.commit()
            return {"app_id": app_id, "success": success, "batch_status": batch.status}
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def retry_app_release(self, batch_id: str, app_id: str) -> dict[str, Any]:
        """Retry a failed/blocked app release without losing sibling results."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id, {})
            state["status"] = ReleasePipelineStatus.QUEUED.value
            state["retry_count"] = state.get("retry_count", 0) + 1
            state["completed_at"] = None
            states[app_id] = state

            setattr(batch, 'app_release_states', states)
            if batch.status == "failed":
                batch.status = "running"
            elif batch.status == "partially_succeeded":
                batch.status = "running"
            s.commit()

            return {"app_id": app_id, "retry_count": state["retry_count"], "batch_status": batch.status}
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def check_readiness(self, batch_id: str, app_id: str) -> dict[str, Any]:
        """Check if an app release is ready (all conditions met)."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            states = getattr(batch, 'app_release_states', {}) or {}
            state = states.get(app_id, {})

            reasons = []
            if not state.get("build_id"):
                reasons.append(BlockageReason.BUILD_NOT_FOUND.value)
            if not state.get("artifact_digest"):
                reasons.append(BlockageReason.MISSING_ARTIFACT_DIGEST.value)
            if state.get("prettyk_verdict") is not True:
                reasons.append(BlockageReason.MISSING_PRETTYK_VERDICT.value)
            if not state.get("act_attached"):
                reasons.append(BlockageReason.MISSING_ACT.value)
            gates = state.get("gate_decisions", {})
            if any(v != "pass" for v in gates.values()):
                reasons.append(BlockageReason.GATE_NOT_PASSED.value)

            # Dependency check
            dep_order = list(states.keys())
            app_idx = dep_order.index(app_id) if app_id in dep_order else -1
            for i in range(app_idx):
                upstream = states.get(dep_order[i], {})
                if upstream.get("status") != "succeeded":
                    reasons.insert(0, BlockageReason.BLOCKED_BY_DEPENDENCY.value)
                    break

            ready = len(reasons) == 0
            return {"app_id": app_id, "ready": ready, "blockages": reasons, "status": state.get("status")}
        finally:
            s.close()

    def get_batch_state(self, batch_id: str) -> dict[str, Any]:
        """Full batch state — survives restarts (reads from PG)."""
        from orchestrator.cosmo.db.models_lr import ReleaseBatch as RB

        s = self._db()
        try:
            batch = s.query(RB).filter(RB.id == batch_id).first()
            if batch is None:
                return {"error": "not_found"}
            return self._to_batch_dict(batch, is_new=False)
        finally:
            s.close()

    def is_ready_for_transfer(self, batch_id: str) -> dict[str, Any]:
        """Check if the entire batch is ready for transfer to next zone."""
        batch = self.get_batch_state(batch_id)
        if "error" in batch:
            return batch

        states = batch.get("app_release_states", {})
        all_ready = True
        blockages = {}
        for aid, st in states.items():
            r = self.check_readiness(batch_id, aid)
            if not r["ready"]:
                all_ready = False
                blockages[aid] = r["blockages"]

        batch_ok = batch.get("status") in ("completed", "partially_succeeded")
        return {
            "batch_id": batch_id,
            "ready_for_transfer": all_ready and batch_ok,
            "all_apps_ready": all_ready,
            "batch_status_ok": batch_ok,
            "per_app_blockages": blockages,
        }

    # ── Internal ──

    def _check_app_blockage(self, app_id: str, release_type_id: str, session) -> Optional[BlockageReason]:
        """Check initial blockages when starting a batch."""
        from orchestrator.cosmo.db.models_lr import ReleaseType as RT, ArtifactRecord as AR

        rt = session.query(RT).filter(RT.id == release_type_id).first()
        if rt is None:
            return BlockageReason.RELEASE_TYPE_NOT_FOUND

        # Check for existing artifact digest
        artifact = session.query(AR).filter(AR.app_id == app_id).order_by(AR.created_at.desc()).first()
        if artifact is None or not artifact.digest_sha256:
            return BlockageReason.MISSING_ARTIFACT_DIGEST

        return None

    def _to_batch_dict(self, batch, is_new: bool) -> dict[str, Any]:
        states = getattr(batch, 'app_release_states', None) or {}
        blockage_reasons = {}
        for aid, st in states.items():
            blockage_reasons[aid] = st.get("blockage") if isinstance(st, dict) else None

        return {
            "batch_id": batch.id,
            "project_id": batch.project_id,
            "release_type_id": batch.release_type_id,
            "name": batch.name,
            "status": batch.status,
            "app_ids": batch.app_ids or [],
            "app_release_states": states,
            "blockage_reasons": blockage_reasons,
            "started_at": str(batch.started_at) if batch.started_at else None,
            "finished_at": str(batch.finished_at) if batch.finished_at else None,
            "is_new": is_new,
        }