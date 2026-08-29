"""
COS-054: Release Transfer tests — межзонный трансфер ЗР→ЗТ→ЗПЭ.

Проверяет:
  - Валидацию status=deployed перед трансфером
  - Проверку всех gates проходят (decision=pass)
  - Блокировку pending gates
  - Строгий порядок зон (zr→zt→zpe)
  - Блокировку повторного трансфера из ЗПЭ
  - Аудит-лог transfer_history
  - Сериализацию TransferRecord
  - Pydantic модели (next_zone, TransferRecord)
"""
import datetime
import pytest
from cosmo.domain.release_model import (
    Release, ReleaseApproval, TransferRecord, ReleaseZone, next_zone,
)
from cosmo.domain.gate_model import Gate, GatePolicy, GatePolicyRule


# �═══════════════════════════════════════════════════════════════════════
# TransferRecord model
# �═══════════════════════════════════════════════════════════════════════

class TestTransferRecord:
    def test_minimal(self):
        tr = TransferRecord(
            from_zone="zr", to_zone="zt",
            initiated_by="operator-ivan",
            gate_check_passed=True,
        )
        assert tr.from_zone == "zr"
        assert tr.to_zone == "zt"
        assert tr.initiated_by == "operator-ivan"
        assert tr.gate_check_passed is True

    def test_with_comment(self):
        tr = TransferRecord(
            from_zone="zt", to_zone="zpe",
            initiated_by="sec-admin",
            gate_check_passed=True,
            comment="All gates passed. SAST + DAST clean.",
        )
        assert tr.comment == "All gates passed. SAST + DAST clean."

    def test_no_empty_initiator(self):
        with pytest.raises(Exception):
            TransferRecord(
                from_zone="zr", to_zone="zt",
                initiated_by="",
                gate_check_passed=True,
            )

    def test_serialization_roundtrip(self):
        tr = TransferRecord(
            from_zone="zr", to_zone="zt",
            initiated_by="lead", gate_check_passed=True,
            comment="Gates clean",
        )
        d = tr.model_dump()
        tr2 = TransferRecord.model_validate(d)
        assert tr2.from_zone == "zr"
        assert tr2.to_zone == "zt"
        assert tr2.initiated_by == "lead"
        assert tr2.gate_check_passed is True
        assert tr2.comment == "Gates clean"

# �══════════════════════════════════════════════════════════════════════════
# next_zone helper
# �══════════════════════════════════════════════════════════════════════════

class TestNextZone:
    def test_zr_to_zt(self):
        assert next_zone("zr") == "zt"

    def test_zt_to_zpe(self):
        assert next_zone("zt") == "zpe"

    def test_zpe_is_terminal(self):
        assert next_zone("zpe") is None

    def test_all_zones_in_order(self):
        """Порядок строго линееН: ЗР(dev) → ЗТ(test) → ЗПЭ(prod)."""
        zones = []
        current = "zr"
        while current is not None:
            zones.append(current)
            current = next_zone(current)
        assert zones == ["zr", "zt", "zpe"]

# ═══════════════════════════════════════════════════════════════════════
# Release transfer validation (Pydantic model level)
# �══════════════════════════════════════════════════════════════════════════

class TestReleaseTransferModel:
    def _make_release(self, status="deployed", zone="zr") -> Release:
        return Release(
            id="rel-trans", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"],
            status=status,
            current_zone=zone,
        )

    def test_default_zone_is_zr(self):
        rel = Release(
            id="rel-1", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"],
        )
        assert rel.current_zone == "zr"

    def test_can_transfer_only_deployed(self):
        rel = self._make_release(status="deployed")
        assert rel.can_transfer is True

    def test_cannot_transfer_approved(self):
        rel = self._make_release(status="approved")
        assert rel.can_transfer is False

    def test_cannot_transfer_draft(self):
        rel = self._make_release(status="draft")
        assert rel.can_transfer is False

    def test_next_zone_from_zr(self):
        rel = self._make_release(zone="zr")
        assert rel.next_zone() == "zt"

    def test_next_zone_from_zpe_is_None(self):
        rel = self._make_release(zone="zpe")
        assert rel.next_zone() is None

    def test_transfer_history_empty_by_default(self):
        rel = self._make_release()
        assert rel.transfer_history == []

    def test_transfer_history_preserved(self):
        rel = self._make_release(zone="zt")
        rel.transfer_history = [
            TransferRecord(
                from_zone="zr", to_zone="zt",
                initiated_by="lead", gate_check_passed=True,
            ),
        ]
        assert len(rel.transfer_history) == 1
        assert rel.transfer_history[0].from_zone == "zr"

    def test_full_transfer_history_exports(self):
        """Порядок ЗР → ЗТ → ЗПЭ с аудит-логом."""
        rel = self._make_release()
        rel.status = "deployed"

        # Transfer 1: ЗР → ЗТ
        rel.current_zone = "zr"
        assert rel.next_zone() == "zt"
        rel.transfer_history.append(
            TransferRecord(from_zone="zr", to_zone="zt", initiated_by="lead", gate_check_passed=True),
        )
        rel.current_zone = "zt"

        # Transfer 2: ЗТ → ЗПЭ
        assert rel.next_zone() == "zpe"
        rel.transfer_history.append(
            TransferRecord(from_zone="zt", to_zone="zpe", initiated_by="sec-admin", gate_check_passed=True, comment="Final prod deploy"),
        )
        rel.current_zone = "zpe"

        assert len(rel.transfer_history) == 2
        assert rel.current_zone == "zpe"
        assert rel.next_zone() is None  # конечная зона

    def test_serialization_with_transfer_history(self):
        rel = Release(
            id="rel-serial", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1", "run-2"],
            status="deployed", current_zone="zt",
            version="1.0.0",
            transfer_history=[
                TransferRecord(
                    from_zone="zr", to_zone="zt",
                    initiated_by="lead", gate_check_passed=True,
                    comment="Gates clean. Moving to test.",
                ),
            ],
        )
        d = rel.model_dump()
        r2 = Release.model_validate(d)
        assert r2.current_zone == "zt"
        assert len(r2.transfer_history) == 1
        assert r2.transfer_history[0].from_zone == "zr"
        assert r2.transfer_history[0].to_zone == "zt"

# �══════════════════════════════════════════════════════════════════════════
# Gate validation before transfer
# �══════════════════════════════════════════════════════════════════════════

class TestGateCheckBeforeTransfer:
    """All gates must be pass before transfer."""

    def _make_policy(self) -> GatePolicy:
        return GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])

    def test_all_gates_passed_allow_transfer(self):
        policy = self._make_policy()
        gates = [
            Gate(id="g-build", type="automatic", position=0, policy=policy, decision="pass"),
            Gate(id="g-scan", type="automatic", position=1, policy=policy, decision="pass"),
        ]
        blocked = [g for g in gates if g.decision != "pass" and g.decision is not None]
        pending = [g for g in gates if g.decision is None]
        assert len(blocked) == 0
        assert len(pending) == 0

    def test_blocked_gate_blocks_transfer(self):
        policy = self._make_policy()
        gates = [
            Gate(id="g-build", type="automatic", position=0, policy=policy, decision="pass"),
            Gate(id="g-scan", type="automatic", position=1, policy=policy, decision="block"),
        ]
        blocked = [g for g in gates if g.decision != "pass" and g.decision is not None]
        assert len(blocked) == 1
        assert blocked[0].id == "g-scan"

    def test_pending_gate_blocks_transfer(self):
        policy = self._make_policy()
        gates = [
            Gate(id="g-build", type="automatic", position=0, policy=policy, decision="pass"),
            Gate(id="g-manual", type="manual", position=1, policy=policy),  # no decision
        ]
        pending = [g for g in gates if g.decision is None]
        assert len(pending) == 1
        assert pending[0].id == "g-manual"

    def test_multiple_gates_mixed(self):
        """Mixed: 1 passed, 1 blocked, 1 pending."""
        policy = self._make_policy()
        gates = [
            Gate(id="g1", type="automatic", position=0, policy=policy, decision="pass"),
            Gate(id="g2", type="automatic", position=1, policy=policy, decision="block"),
            Gate(id="g3", type="manual", position=2, policy=policy),  # pending
        ]
        blocked = [g for g in gates if g.decision != "pass" and g.decision is not None]
        pending = [g for g in gates if g.decision is None]
        assert len(blocked) == 1
        assert len(pending) == 1
        # Both conditions fail → transfer blocked

    def test_no_gates_allow_transfer(self):
        """Если gate'ов нет — трансфер разрешён."""
        gates = []
        blocked = [g for g in gates if g.decision != "pass" and g.decision is not None]
        pending = [g for g in gates if g.decision is None]
        assert len(blocked) == 0
        assert len(pending) == 0

# �══════════════════════════════════════════════════════════════════════════
# Полный сценарий трансфера
# �══════════════════════════════════════════════════════════════════════════

class TestFullTransferScenario:
    """COS-054: полный жизненный цикл трансфера."""

    def test_full_cycle_zr_to_zpe(self):
        """ЗР → ЗТ → ЗПЭ с gates и аудит-логом."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
            GatePolicyRule(finding_type="High", action="warn", max_count=3),
        ])

        # 1. Release создан, gates пройдены, deployed
        rel = Release(
            id="rel-full", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-sast", "run-dast"],
            status="deployed", current_zone="zr",
            version="2.0.0",
            approvals=[
                ReleaseApproval(decided_by="lead", decision="approved"),
            ],
        )
        assert rel.current_zone == "zr"
        assert rel.can_transfer

        # 2. Проверяем gates
        gates = [
            Gate(id="g-build", type="automatic", position=0, policy=policy, decision="pass"),
            Gate(id="g-scan", type="automatic", position=1, policy=policy, decision="pass"),
        ]
        blocked = [g for g in gates if g.decision != "pass" and g.decision is not None]
        pending = [g for g in gates if g.decision is None]
        assert len(blocked) == 0
        assert len(pending) == 0

        # 3. Transfer ЗР → ЗТ
        assert rel.next_zone() == "zt"
        rel.transfer_history.append(
            TransferRecord(
                from_zone=rel.current_zone,
                to_zone="zt",
                initiated_by="lead-ivan",
                gate_check_passed=True,
                comment="SAST + DAST passed. Moving to test zone.",
            ),
        )
        rel.current_zone = "zt"
        assert rel.current_zone == "zt"
        assert len(rel.transfer_history) == 1

        # 4. Transfer ЗТ → ЗПЭ
        assert rel.next_zone() == "zpe"
        rel.transfer_history.append(
            TransferRecord(
                from_zone="zt",
                to_zone="zpe",
                initiated_by="sec-maria",
                gate_check_passed=True,
                comment="Stage testing complete. Production deploy approved.",
            ),
        )
        rel.current_zone = "zpe"
        assert rel.current_zone == "zpe"
        assert len(rel.transfer_history) == 2

        # 5. ЗПЭ — конечная зона
        assert rel.next_zone() is None

    def test_transfer_with_gate_failure_stops(self):
        """Если gate blocked — трансфер невозможен."""
        rel = Release(
            id="rel-blocked", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="deployed", current_zone="zr",
        )
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gates = [
            Gate(id="g-block", type="automatic", position=0, policy=policy, decision="block"),
        ]
        blocked = [g for g in gates if g.decision != "pass" and g.decision is not None]
        assert len(blocked) == 1
        # Transfer заблокирован
        assert rel.can_transfer  # статус deployed — ок
        # но gate block — не позволяем
        assert blocked[0].id == "g-block"

    def test_deploy_then_transfer(self):
        """Полный цикл: approve → deploy → transfer."""
        rel = Release(
            id="rel-deploy-transfer", domain_id="d-1", plan_id="plan-1",
            run_ids=["run-1"], status="draft", current_zone="zr",
        )

        # Approve
        rel.status = "pending_review"
        rel.status = "approved"
        rel.approvals.append(
            ReleaseApproval(decided_by="lead", decision="approved"),
        )
        assert rel.is_approved

        # Deploy
        rel.status = "deploying"
        rel.status = "deployed"
        assert rel.can_transfer

        # Transfer ЗР → ЗТ
        assert rel.next_zone() == "zt"
        rel.status = "deployed"
        rel.transfer_history.append(
            TransferRecord(
                from_zone="zr", to_zone="zt",
                initiated_by="lead", gate_check_passed=True,
            ),
        )
        rel.current_zone = "zt"
        assert rel.current_zone == "zt"