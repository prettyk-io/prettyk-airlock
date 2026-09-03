# -*- coding: utf-8 -*-
"""COS-053 Phase 3: Landing Kernel — target-side state machine.

Стадии landing: received → verified → landing_approved → imported → bootstrapped → reconciled
Negative states: rejected, incomplete, checksum_mismatch, capacity_failure, bootstrap_failure, reconcile_failure

Инварианты:
  - Нельзя перейти к bootstrap до verified и landing_approved.
  - Post-import checksum verification обязательна.
  - Повторная доставка той же revision не создаёт duplicate landing.
  - Recovery path отдельный по каждому TransferItem.
  - COS-074: transfer_failed — честный терминал транспортного провала
    (NOT_RECEIVED → TRANSFER_FAILED); недостижим после RECEIVED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.cosmo.transfer.contract import (
    PackageRevision,
    TransferFailureClass,
    TransferItem,
)


# ══════════════════════════════════════════════════════════════════
# Landing States
# ══════════════════════════════════════════════════════════════════

class LandingState(str, Enum):
    """Target-side landing state machine."""
    NOT_RECEIVED = "not_received"           # ещё не пришло
    RECEIVED = "received"                    # пакет получен, checksum проверен
    VERIFIED = "verified"                    # manifest verified, schema OK
    LANDING_APPROVED = "landing_approved"    # policy/preflight прошёл
    IMPORTED = "imported"                    # данные импортированы в target
    BOOTSTRAPPED = "bootstrapped"            # bootstrap применён
    RECONCILED = "reconciled"                # финальное состояние: всё OK

    # Negative states
    REJECTED = "rejected"                    # preflight отказал
    INCOMPLETE = "incomplete"                # partial import
    CHECKSUM_MISMATCH = "checksum_mismatch"  # post-import verification fail
    CAPACITY_FAILURE = "capacity_failure"    # target нет места
    BOOTSTRAP_FAILURE = "bootstrap_failure"  # bootstrap упал
    RECONCILE_FAILURE = "reconcile_failure"  # reconcile не прошёл

    # COS-074: terminal transfer-side failure — пакет НЕ доехал до target
    # (transport FAILED_TERMINAL: max_attempts, диода умерла навсегда).
    # Честный терминал: не маскировать FAILED_RETRYABLE (ещё жив) и не
    # оставлять терминальную смерть выглядящей как NOT_RECEIVED.
    TRANSFER_FAILED = "transfer_failed"


class LandingTransition(str, Enum):
    """Имена переходов для timeline/audit."""
    RECEIVE = "receive"
    VERIFY = "verify"
    APPROVE_LANDING = "approve_landing"
    IMPORT = "import"
    BOOTSTRAP = "bootstrap"
    RECONCILE = "reconcile"
    REJECT = "reject"
    MARK_INCOMPLETE = "mark_incomplete"
    MARK_CHECKSUM_MISMATCH = "mark_checksum_mismatch"
    MARK_CAPACITY_FAILURE = "mark_capacity_failure"
    MARK_BOOTSTRAP_FAILURE = "mark_bootstrap_failure"
    MARK_RECONCILE_FAILURE = "mark_reconcile_failure"
    MARK_TRANSFER_FAILED = "mark_transfer_failed"
    RETRY = "retry"


# ── Valid transitions ──

_LANDING_TRANSITIONS: dict[LandingState, frozenset[LandingState]] = {
    LandingState.NOT_RECEIVED: frozenset({LandingState.RECEIVED, LandingState.REJECTED,
                                           LandingState.TRANSFER_FAILED}),
    LandingState.RECEIVED: frozenset({LandingState.VERIFIED, LandingState.CHECKSUM_MISMATCH}),
    LandingState.VERIFIED: frozenset({LandingState.LANDING_APPROVED, LandingState.REJECTED}),
    LandingState.LANDING_APPROVED: frozenset({LandingState.IMPORTED, LandingState.CAPACITY_FAILURE}),
    LandingState.IMPORTED: frozenset({LandingState.BOOTSTRAPPED, LandingState.BOOTSTRAP_FAILURE,
                                       LandingState.INCOMPLETE}),
    LandingState.BOOTSTRAPPED: frozenset({LandingState.RECONCILED, LandingState.RECONCILE_FAILURE}),
    # Negative states can retry back to appropriate stage
    LandingState.REJECTED: frozenset(),
    LandingState.INCOMPLETE: frozenset({LandingState.IMPORTED}),  # resume import
    LandingState.CHECKSUM_MISMATCH: frozenset(),  # requires new revision
    LandingState.CAPACITY_FAILURE: frozenset({LandingState.LANDING_APPROVED}),  # after capacity freed
    LandingState.BOOTSTRAP_FAILURE: frozenset({LandingState.IMPORTED}),  # retry bootstrap
    LandingState.RECONCILE_FAILURE: frozenset({LandingState.BOOTSTRAPPED}),  # retry reconcile
    LandingState.RECONCILED: frozenset(),  # terminal
    # COS-074: transfer died on the wire (FAILED_TERMINAL) — nothing arrived,
    # so there is no landing to retry; recovery = fresh dispatch, new SM.
    LandingState.TRANSFER_FAILED: frozenset(),  # terminal
}


class LandingStateError(Exception):
    """Недопустимый переход в landing state machine."""

    def __init__(self, item_id: str, from_state: LandingState, to_state: LandingState):
        self.item_id = item_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid landing transition for '{item_id}': "
            f"{from_state.value} → {to_state.value}"
        )


# ══════════════════════════════════════════════════════════════════
# LandingCheckReport
# ══════════════════════════════════════════════════════════════════

class LandingCheckReport(BaseModel):
    """Детальный отчёт проверки landing — не просто boolean."""
    model_config = ConfigDict(extra="ignore")
    item_id: str
    release_id: str
    revision_key: str = ""
    state: LandingState = LandingState.NOT_RECEIVED
    passed: bool = False
    checks: list[dict[str, Any]] = Field(default_factory=list)
    failure_class: Optional[TransferFailureClass] = None
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "passed": passed, "detail": detail})
        if not passed:
            self.reasons.append(f"{name}: {detail}" if detail else name)

    @property
    def is_recoverable(self) -> bool:
        """Можно ли retry без новой revision."""
        return self.state in (
            LandingState.INCOMPLETE,
            LandingState.CAPACITY_FAILURE,
            LandingState.BOOTSTRAP_FAILURE,
            LandingState.RECONCILE_FAILURE,
        )

    @property
    def requires_new_revision(self) -> bool:
        """Нужна ли новая revision (checksum mismatch, rejected)."""
        return self.state in (
            LandingState.CHECKSUM_MISMATCH,
            LandingState.REJECTED,
        )


# ══════════════════════════════════════════════════════════════════
# LandingStateMachine
# ══════════════════════════════════════════════════════════════════

class LandingStateMachine:
    """Target-side landing state machine для одного TransferItem.

    Tracks: current state, transition history, failure details.
    Идемпотентность: состояние хранится по revision_key.
    """

    def __init__(self, item: TransferItem):
        self._item = item
        self._state = LandingState.NOT_RECEIVED
        self._history: list[dict[str, Any]] = []
        self._revision_key = item.revision_key

    @property
    def state(self) -> LandingState:
        return self._state

    @property
    def revision_key(self) -> str:
        return self._revision_key

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def transition(self, to_state: LandingState, reason: str = "") -> LandingState:
        """Атомарный переход в landing state machine."""
        if to_state not in _LANDING_TRANSITIONS.get(self._state, frozenset()):
            raise LandingStateError(self._item.item_id, self._state, to_state)

        entry = {
            "from": self._state.value,
            "to": to_state.value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._history.append(entry)
        self._state = to_state
        return self._state

    def check_report(self) -> LandingCheckReport:
        """Текущий отчёт о состоянии landing."""
        report = LandingCheckReport(
            item_id=self._item.item_id,
            release_id=self._item.release_id,
            revision_key=self._revision_key,
            state=self._state,
            passed=self._state == LandingState.RECONCILED,
        )

        # Add checks based on state
        if self._state == LandingState.RECONCILED:
            report.add_check("received", True)
            report.add_check("verified", True)
            report.add_check("landing_approved", True)
            report.add_check("imported", True)
            report.add_check("bootstrapped", True)
            report.add_check("reconciled", True)
        elif self._state in (LandingState.REJECTED, LandingState.CHECKSUM_MISMATCH):
            report.failure_class = (
                TransferFailureClass.LANDING_REJECTED
                if self._state == LandingState.REJECTED
                else TransferFailureClass.CHECKSUM_MISMATCH
            )
        elif self._state == LandingState.BOOTSTRAP_FAILURE:
            report.failure_class = TransferFailureClass.BOOTSTRAP_FAILURE
        elif self._state == LandingState.TRANSFER_FAILED:
            # COS-074: пакет не доехал — транспортный терминальный провал,
            # не landing-провал: target ничего не получил.
            report.failure_class = TransferFailureClass.TRANSPORT_FAILURE
            report.add_check(
                "transfer_failed", False,
                "delivery terminally failed before target receipt")

        return report

    def is_recoverable(self) -> bool:
        """Можно ли retry без новой revision."""
        return self._state in (
            LandingState.INCOMPLETE,
            LandingState.CAPACITY_FAILURE,
            LandingState.BOOTSTRAP_FAILURE,
            LandingState.RECONCILE_FAILURE,
        )

    def requires_new_revision(self) -> bool:
        return self._state in (
            LandingState.CHECKSUM_MISMATCH,
            LandingState.REJECTED,
        )

    def is_terminal(self) -> bool:
        return self._state in (LandingState.RECONCILED, LandingState.REJECTED,
                                LandingState.CHECKSUM_MISMATCH,
                                LandingState.TRANSFER_FAILED)

    def detect_duplicate(self, incoming_revision_key: str) -> bool:
        """Идемпотентность: если та же revision уже получена — duplicate."""
        return (
            self._revision_key == incoming_revision_key
            and self._state in (
                LandingState.RECEIVED, LandingState.VERIFIED,
                LandingState.LANDING_APPROVED, LandingState.IMPORTED,
                LandingState.BOOTSTRAPPED, LandingState.RECONCILED,
            )
        )

    # ── COS-099: receive + tamper-evidence для pinned security payloads ──

    def receive_and_verify(self, payloads: dict[str, bytes]) -> LandingCheckReport:
        """Получить пакет и проверить manifest checksum + pinned digests SBOM.

        Отвергает пакет с модифицированным SBOM: sha256 фактических байтов
        обязан совпасть с manifest.security pin (COS-099). Любое несовпадение
        → CHECKSUM_MISMATCH (требуется новая revision). Успех → VERIFIED.

        payloads: {ref: bytes} — фактические payload-байты по refs из манифеста.
        """
        if self._state is not LandingState.NOT_RECEIVED:
            raise LandingStateError(
                self._item.item_id, self._state, LandingState.RECEIVED)
        self.transition(LandingState.RECEIVED, "payload received")

        from orchestrator.cosmo.transfer.sbom import extract_security, sha256_hex

        report = LandingCheckReport(
            item_id=self._item.item_id,
            release_id=self._item.release_id,
            revision_key=self._revision_key,
            state=LandingState.RECEIVED,
        )
        ok = True

        # 1. Manifest checksum (existing invariant)
        if self._item.package_revision and self._item.manifest:
            computed = PackageRevision.compute_manifest_sha256(self._item.manifest)
            expected = self._item.package_revision.manifest_sha256
            if computed != expected:
                ok = False
                report.add_check(
                    "manifest_checksum", False,
                    f"expected {expected[:12]}..., got {computed[:12]}...")
            else:
                report.add_check("manifest_checksum", True)

        # 2. Pinned security digests против фактических байтов
        security = extract_security(self._item.manifest) if self._item.manifest else None
        if security is not None:
            data = payloads.get(security.sbom.ref)
            if data is None:
                ok = False
                report.add_check(
                    "sbom_payload_present", False,
                    f"pinned sbom payload '{security.sbom.ref}' not provided")
            else:
                actual = sha256_hex(data)
                if actual != security.sbom.sha256:
                    ok = False
                    report.add_check(
                        "sbom_digest", False,
                        f"modified SBOM '{security.sbom.ref}': pinned "
                        f"{security.sbom.sha256[:12]}..., got {actual[:12]}...")
                else:
                    report.add_check("sbom_digest", True,
                                     f"'{security.sbom.ref}' ({security.sbom.source})")
            vr = security.vulnerability_report
            if vr is not None and vr.ref and vr.source == "grype":
                vdata = payloads.get(vr.ref)
                if vdata is None:
                    ok = False
                    report.add_check(
                        "vulnerability_report_payload_present", False,
                        f"pinned report payload '{vr.ref}' not provided")
                else:
                    vactual = sha256_hex(vdata)
                    if vactual != vr.sha256:
                        ok = False
                        report.add_check(
                            "vulnerability_report_digest", False,
                            f"modified report '{vr.ref}': pinned "
                            f"{vr.sha256[:12]}..., got {vactual[:12]}...")
                    else:
                        report.add_check("vulnerability_report_digest", True,
                                         f"'{vr.ref}'")

        if not ok:
            self.transition(LandingState.CHECKSUM_MISMATCH,
                            "manifest/security digest mismatch")
            report.state = LandingState.CHECKSUM_MISMATCH
            report.failure_class = TransferFailureClass.CHECKSUM_MISMATCH
            report.passed = False
        else:
            self.transition(LandingState.VERIFIED,
                            "manifest checksum + pinned digests verified")
            report.state = LandingState.VERIFIED
            report.passed = True
        return report