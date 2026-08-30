# -*- coding: utf-8 -*-
"""
COS-219: Строгий банковский compliance-сьют (CBR 834-P / 701-P, M-of-N Threshold, SLSA in-toto).

Только три боевых модуля:
  CBR Provision Validator — Положения ЦБ РФ № 834-П и № 701-П
  Threshold M-of-N Approval — пороговое подписание релизов (SoD / 4 глаза)
  SLSA Level 4 Provenance — in-toto аттестация герметичной сборки
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_orch = Path(__file__).resolve().parents[2]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane.threshold_approval import (
    ThresholdPolicy, ThresholdQuorumSession,
)
from orchestrator.cosmo.ledger.cbr_validator import (
    CBRProvisionValidator,
)
from orchestrator.cosmo.ledger.slsa_verifier import (
    SLSAMaterial, SLSAProvenance, SLSAProvenanceVerifier,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CBR 834-P: Безопасность платёжных систем (ГОСТ ЭЦП, MFA, Audit Chain)
# ══════════════════════════════════════════════════════════════════════════════

class TestCBR834P:

    @pytest.mark.parametrize("gost,mfa,audit,crits,expected", [
        pytest.param(True,  True,  True,  0, True,  id="full-compliance"),
        pytest.param(False, True,  True,  0, False, id="no-gost-sign"),
        pytest.param(True,  False, True,  0, False, id="no-mfa"),
        pytest.param(True,  True,  False, 0, False, id="broken-audit-chain"),
        pytest.param(True,  True,  True,  1, False, id="open-critical"),
        pytest.param(True,  True,  True,  5, False, id="many-critical"),
        pytest.param(False, False, False, 2, False, id="total-failure"),
    ])
    def test_834_p_rule_matrix(self, gost, mfa, audit, crits, expected):
        """Матрица выполнения 834-П: 4 правила, каждое должно быть PASS."""
        report = CBRProvisionValidator.validate_834_p(
            domain_id="d1",
            has_gost_signing=gost,
            mfa_enforced=mfa,
            audit_chain_verified=audit,
            open_critical_findings=crits,
        )
        assert report.is_compliant == expected
        assert report.passed_count + report.failed_count == 4

    def test_834_p_counters(self):
        """Счётчики passed/failed для полного комплаенса."""
        report = CBRProvisionValidator.validate_834_p("d1")
        assert report.is_compliant
        assert report.passed_count == 4
        assert report.failed_count == 0

    def test_834_p_individual_rules_present(self):
        """Каждое правило имеет корректный rule_id."""
        report = CBRProvisionValidator.validate_834_p("d1")
        rule_ids = {r.rule_id for r in report.rules}
        assert rule_ids == {"834-P-01", "834-P-02", "834-P-03", "834-P-04"}

    def test_834_p_gost_detail(self):
        """При отсутствии ГОСТ-подписи поле detail содержит причину."""
        report = CBRProvisionValidator.validate_834_p("d1", has_gost_signing=False)
        gost_rule = next(r for r in report.rules if r.rule_id == "834-P-01")
        assert not gost_rule.passed
        assert "Отсутствует" in gost_rule.detail

    def test_834_p_critical_detail(self):
        """При наличии Critical дефектов detail показывает их количество."""
        report = CBRProvisionValidator.validate_834_p("d1", open_critical_findings=3)
        crit_rule = next(r for r in report.rules if r.rule_id == "834-P-04")
        assert not crit_rule.passed
        assert "3" in crit_rule.detail


# ══════════════════════════════════════════════════════════════════════════════
# 2. CBR 701-P: Бесперебойность (RTO, DR, SLA, Monitoring)
# ══════════════════════════════════════════════════════════════════════════════

class TestCBR701P:

    @pytest.mark.parametrize("rto_h,dr,sla_pct,auto_mon,expected", [
        pytest.param(1.5,  True, 99.995, True, True,  id="full-uptime"),
        pytest.param(0.5,  True, 99.999, True, True,  id="gold-standard"),
        pytest.param(2.5,  True, 99.995, True, False, id="rto-exceeded"),
        pytest.param(1.0,  False, 99.995, True, False,id="no-dr"),
        pytest.param(1.0,  True, 99.800, True, False,id="sla-low"),
        pytest.param(0.1,  True, 99.995, False, False,id="no-monitoring"),
        pytest.param(3.0,  False, 95.000, False, False,id="total-outage"),
    ])
    def test_701_p_rule_matrix(self, rto_h, dr, sla_pct, auto_mon, expected):
        """Матрица бесперебойности 701-П: 4 правила (RTO, DR, SLA, Monitoring)."""
        report = CBRProvisionValidator.validate_701_p(
            domain_id="d1",
            rto_hours=rto_h,
            has_disaster_recovery=dr,
            sla_uptime_percent=sla_pct,
            has_automated_monitoring=auto_mon,
        )
        assert report.is_compliant == expected
        assert report.passed_count + report.failed_count == 4

    def test_701_p_counters(self):
        """При полном комплаенсе — 4/4 passed."""
        report = CBRProvisionValidator.validate_701_p(
            "d1", rto_hours=1.0, has_disaster_recovery=True,
            sla_uptime_percent=99.999, has_automated_monitoring=True,
        )
        assert report.is_compliant
        assert report.passed_count == 4

    def test_701_p_individual_rules_present(self):
        """Каждое правило имеет корректный rule_id."""
        report = CBRProvisionValidator.validate_701_p("d1")
        rule_ids = {r.rule_id for r in report.rules}
        assert rule_ids == {"701-P-01", "701-P-02", "701-P-03", "701-P-04"}

    def test_701_p_rto_minutes_backward_compat(self):
        """Обратная совместимость: rto_minutes как позиционный аргумент."""
        report = CBRProvisionValidator.validate_701_p("d1", 90)
        assert report.is_compliant

    def test_701_p_rto_minutes_exceeded(self):
        """RTO > 120 минут — FAIL."""
        report = CBRProvisionValidator.validate_701_p("d1", 180)
        assert not report.is_compliant
        rto_rule = next(r for r in report.rules if r.rule_id == "701-P-01")
        assert not rto_rule.passed
        assert "180" in rto_rule.detail

    def test_701_p_sla_ratio_param(self):
        """SLA через sla_ratio (0..1) вместо sla_uptime_percent."""
        report = CBRProvisionValidator.validate_701_p(
            "d1", sla_ratio=0.99995, has_automated_monitoring=True,
        )
        assert report.is_compliant


# ══════════════════════════════════════════════════════════════════════════════
# 3. Threshold M-of-N: SoD, ролевое разнообразие, криптографический кворум
# ══════════════════════════════════════════════════════════════════════════════

class TestThresholdApproval:

    ALL_ROLES = ["security_officer", "admin_sec", "developer_lead", "qa_lead"]

    @pytest.mark.parametrize("m,n,roles_count,expected_seal", [
        pytest.param(2, 3, 2, True,  id="2-of-3-sealed"),
        pytest.param(2, 3, 1, False, id="1-of-3-short"),
        pytest.param(3, 4, 3, True,  id="3-of-4-sealed"),
        pytest.param(3, 4, 2, False, id="2-of-4-short"),
        pytest.param(2, 2, 2, True,  id="2-of-2-unanimous"),
    ])
    def test_m_of_n_threshold_matrix(self, m, n, roles_count, expected_seal):
        """Различные комбинации порогов M-of-N с distinct_roles."""
        chosen = self.ALL_ROLES[:roles_count]
        policy = ThresholdPolicy("p", required_m=m, total_n=n,
                                 required_roles=self.ALL_ROLES,
                                 require_distinct_roles=True)
        session = ThresholdQuorumSession("s", "rel", "digest-abc", policy)
        for i, role in enumerate(chosen):
            session.add_signature(f"user_{i}", role, f"secret_{i}")
        assert session.is_sealed == expected_seal
        if expected_seal:
            assert session.verify_quorum()

    def test_duplicate_signer_rejected(self):
        """Повторное голосование тем же подписантом — 409."""
        policy = ThresholdPolicy("p", 2, 3)
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        session.add_signature("alice", "security_officer", "secret")
        ok, msg = session.add_signature("alice", "security_officer", "secret")
        assert not ok
        assert "409_DUPLICATE_SIGNER" in msg

    def test_distinct_roles_required_rejected(self):
        """Две подписи от одной роли не дают кворум при require_distinct_roles=True."""
        policy = ThresholdPolicy("p", 2, 3, require_distinct_roles=True)
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        session.add_signature("sec1", "security_officer", "s1")
        session.add_signature("sec2", "security_officer", "s2")
        assert not session.is_sealed
        assert not session.verify_quorum()

    def test_unauthorized_role_rejected(self):
        """Роль вне списка required_roles — 403."""
        policy = ThresholdPolicy("p", 2, 3,
                                 required_roles=["admin_sec", "security_officer"])
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        ok, msg = session.add_signature("dev_user", "developer", "secret")
        assert not ok
        assert "403_INELIGIBLE_ROLE" in msg

    def test_tampered_signature_fails_verify(self):
        """Подмена агрегированной подписи делает verify_quorum=False."""
        policy = ThresholdPolicy("p", 2, 3, require_distinct_roles=False)
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        session.add_signature("u1", "admin_sec", "s1")
        session.add_signature("u2", "admin_sec", "s2")
        assert session.is_sealed
        session.final_aggregated_signature = "bad_signature"
        assert not session.verify_quorum()

    def test_insufficient_votes_not_sealed(self):
        """Меньше M подписей — сессия не запечатана."""
        policy = ThresholdPolicy("p", 3, 4)
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        session.add_signature("u1", "security_officer", "s1")
        session.add_signature("u2", "admin_sec", "s2")
        assert not session.is_sealed
        assert not session.verify_quorum()

    def test_aggregated_signature_hex_length(self):
        """Агрегированная подпись — 64 hex символа (SHA-256)."""
        policy = ThresholdPolicy("p", 2, 3, require_distinct_roles=False)
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        session.add_signature("u1", "admin_sec", "s1")
        session.add_signature("u2", "admin_sec", "s2")
        assert len(session.final_aggregated_signature) == 64

    def test_sealed_session_rejects_new_votes(self):
        """После запечатывания новые голоса — 409_SESSION_ALREADY_SEALED."""
        policy = ThresholdPolicy("p", 2, 3, require_distinct_roles=False)
        session = ThresholdQuorumSession("s", "rel", "digest", policy)
        session.add_signature("u1", "admin_sec", "s1")
        session.add_signature("u2", "admin_sec", "s2")
        assert session.is_sealed
        ok, msg = session.add_signature("u3", "admin_sec", "s3")
        assert not ok
        assert "ALREADY_SEALED" in msg

    def test_deterministic_signature(self):
        """Одинаковые входы дают одинаковую агрегированную подпись."""
        def make_session():
            policy = ThresholdPolicy("p", 2, 3, require_distinct_roles=False)
            session = ThresholdQuorumSession("s", "rel", "digest", policy)
            session.add_signature("a", "admin_sec", "sec_a")
            session.add_signature("b", "admin_sec", "sec_b")
            return session
        assert make_session().final_aggregated_signature == make_session().final_aggregated_signature

    def test_distinct_sessions_differ(self):
        """Разные release_digest дают разные подписи."""
        policy = ThresholdPolicy("p", 2, 2, require_distinct_roles=False)
        s1 = ThresholdQuorumSession("s", "rel", "digest-A", policy)
        s2 = ThresholdQuorumSession("s", "rel", "digest-B", policy)
        s1.add_signature("a", "admin_sec", "sec_a")
        s1.add_signature("b", "admin_sec", "sec_b")
        s2.add_signature("a", "admin_sec", "sec_a")
        s2.add_signature("b", "admin_sec", "sec_b")
        assert s1.final_aggregated_signature != s2.final_aggregated_signature


# ══════════════════════════════════════════════════════════════════════════════
# 4. SLSA Level 4 Provenance: герметичность, воспроизводимость, 4 глаза
# ══════════════════════════════════════════════════════════════════════════════

class TestSLSAProvenance:

    def _base_prov(self, **overrides) -> SLSAProvenance:
        kwargs = {
            "build_id": "build-1",
            "builder_id": "https://kits.cosmo/builders/isolated-runner@v2",
            "materials": [SLSAMaterial("git+https://gitea/app.git", "sha256:abc")],
            "artifact_name": "cosmo-api:2.0",
            "artifact_sha256": "sha256:def123",
            "is_hermetic": True,
            "is_reproducible": True,
            "two_person_reviewed": True,
            "builder_signature": "sig-ok",
            **overrides,
        }
        return SLSAProvenance(**kwargs)

    def test_slsa_l4_full_compliance(self):
        """Все флаги True — SLSA_BUILD_LEVEL_4."""
        report = SLSAProvenanceVerifier.verify_slsa_level_4(self._base_prov())
        assert report.achieved_level == "SLSA_BUILD_LEVEL_4"
        assert report.is_level_4_compliant
        assert len(report.violations) == 0

    def test_slsa_no_materials_fails_l1(self):
        """Пустые materials — уровень 0."""
        prov = self._base_prov(materials=[])
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_0"
        assert not report.is_level_4_compliant

    def test_slsa_no_artifact_sha_fails_l1(self):
        """Пустой artifact_sha256 — уровень 0."""
        prov = self._base_prov(artifact_sha256="")
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_0"

    def test_slsa_no_builder_sig_fails_l2(self):
        """Нет builder_signature — уровень 1."""
        prov = self._base_prov(builder_signature="")
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_1"

    def test_slsa_untrusted_builder_fails_l2(self):
        """Раннер не из kits.cosmo — уровень 1."""
        prov = self._base_prov(builder_id="https://evil-ci.com/runner")
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_1"

    def test_slsa_no_two_person_review_fails_l3(self):
        """Нет two_person_reviewed — уровень 2."""
        prov = self._base_prov(two_person_reviewed=False)
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_2"

    def test_slsa_non_hermetic_fails_l4(self):
        """Негерметичная сборка — уровень 3, violation про hermetic."""
        prov = self._base_prov(is_hermetic=False)
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_3"
        assert not report.is_level_4_compliant
        assert any("герметич" in v or "hermetic" in v for v in report.violations)

    def test_slsa_non_reproducible_fails_l4(self):
        """Невоспроизводимая сборка — уровень 3."""
        prov = self._base_prov(is_reproducible=False)
        report = SLSAProvenanceVerifier.verify_slsa_level_4(prov)
        assert report.achieved_level == "SLSA_BUILD_LEVEL_3"
        assert not report.is_level_4_compliant

    def test_slsa_in_toto_statement_structure(self):
        """in-toto Statement содержит обязательные поля."""
        prov = self._base_prov()
        stmt = SLSAProvenanceVerifier.generate_in_toto_statement(prov)
        assert stmt["_type"] == "https://in-toto.io/Statement/v0.1"
        assert stmt["predicateType"] == "https://slsa.dev/provenance/v1"
        assert len(stmt["subject"]) == 1
        assert stmt["subject"][0]["name"] == "cosmo-api:2.0"
        assert stmt["predicate"]["metadata"]["hermetic"] is True
        assert stmt["predicate"]["metadata"]["reproducible"] is True

    def test_slsa_in_toto_multiple_materials(self):
        """Несколько материалов корректно сериализуются в in-toto."""
        prov = self._base_prov(materials=[
            SLSAMaterial("git+https://gitea/lib-a.git", "sha256:aaa"),
            SLSAMaterial("git+https://gitea/lib-b.git", "sha256:bbb"),
        ])
        stmt = SLSAProvenanceVerifier.generate_in_toto_statement(prov)
        mats = stmt["predicate"]["materials"]
        assert len(mats) == 2
        uris = {m["uri"] for m in mats}
        assert "git+https://gitea/lib-a.git" in uris
        assert "git+https://gitea/lib-b.git" in uris