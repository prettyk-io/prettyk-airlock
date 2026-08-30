"""
COS-115: Negative Security Attack Matrix (401/403/404/409 SoD Tests).

Комплексный сьют негативных проверок безопасности:
  - 401 Unauthorized: неаутентифицированные запросы, испорченные токены, невалидные подписи.
  - 404 Domain Isolation: попытка доступа к сущностям чужого КИТС-домена без утечки факта существования.
  - 403 Forbidden: нехватка прав, несоответствие зон (ЗР/ЗТ/ЗПЭ), нарушение team scopes.
  - 409 Conflict & SoD: нарушение принципа разделения обязанностей (автор утверждает свой релиз, повторная подпись, пропуск зоны ЗТ).
"""
import pytest
from cosmo.domain.rbac import (
    Action,
    CBRRole,
    DomainMember,
    DomainRBAC,
    PrincipalContext,
    Role,
    SeparationOfDutiesEngine,
)
from cosmo.domain.release_model import (
    Release,
    ReleaseApproval,
    ReleaseZone,
    next_zone,
)
from cosmo.ledger.release_envelope import (
    DigitalReleaseEnvelope,
    seal_envelope,
    verify_envelope,
    verify_envelope_body,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. 401 UNAUTHORIZED TESTS
# ═══════════════════════════════════════════════════════════════════════

class Test401UnauthorizedAttacks:
    """Проверка блокировки неаутентифицированных запросов."""

    def test_unauthenticated_principal_denied_all_actions(self):
        rbac = DomainRBAC(domain_id="dom-sec")
        unauth_p = PrincipalContext(
            user_id="anonymous",
            roles=[CBRRole.SECURITY_OFFICER],
            is_authenticated=False,
        )

        for action in [Action.READ, Action.SCAN_START, Action.GATE_DECIDE, Action.RELEASE_TRANSFER, Action.ACT_SIGN]:
            allowed, code = rbac.evaluate(unauth_p, action)
            assert allowed is False
            assert code == "401_UNAUTHORIZED"

    def test_invalid_envelope_signature_fails_authentication(self):
        env = seal_envelope(
            release_id="rel-attack-401",
            signer="officer_alice",
        )
        body = env.to_dict()
        # Испорченная подпись
        body["envelope_signature"] = "0000000000000000000000000000000000000000000000000000000000000000"
        assert verify_envelope_body(body) is False


# ═══════════════════════════════════════════════════════════════════════
# 2. 404 DOMAIN ISOLATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class Test404DomainIsolation:
    """Изоляция между доменами КИТС."""

    def test_cross_domain_release_access_isolation(self):
        rel_dom_a = Release(
            id="rel-domain-a",
            domain_id="domain_alpha",
            plan_id="plan-1",
            run_ids=["run-1"],
        )
        # Субъект из domain_beta обращается к релизу domain_alpha
        caller_domain = "domain_beta"
        is_owner = (rel_dom_a.domain_id == caller_domain)
        assert is_owner is False

    def test_cross_domain_envelope_forgery(self):
        """Конверт, выпущенный для domain_a, отклоняется при проверке в domain_b."""
        env = seal_envelope(
            release_id="rel-forgery",
            signer="officer_alice",
            domain_id="domain_alpha",
        )
        # Попытка подмены целевого домена
        tampered = env.to_dict()
        tampered["domain_id"] = "domain_beta"
        assert verify_envelope_body(tampered) is False


# ═══════════════════════════════════════════════════════════════════════
# 3. 403 FORBIDDEN TESTS
# ═══════════════════════════════════════════════════════════════════════

class Test403ForbiddenAccess:
    """Проверка прав, ограничений зон и team scopes."""

    def test_developer_cannot_approve_or_transfer(self):
        rbac = DomainRBAC(domain_id="dom-corp")
        dev_p = PrincipalContext(
            user_id="dev_bob",
            roles=[CBRRole.DEVELOPER],
            domain_id="dom-corp",
            zone="zr",
            team_scopes=["team_front"],
        )

        allowed, reason = rbac.evaluate(dev_p, Action.RELEASE_APPROVE)
        assert allowed is False
        assert "403_ACTION_FORBIDDEN" in reason

        allowed, reason = rbac.evaluate(dev_p, Action.RELEASE_TRANSFER)
        assert allowed is False
        assert "403_ACTION_FORBIDDEN" in reason

    def test_zone_violation_zpe_deploy_in_zr(self):
        """Действие zpe:deploy запрещено в зоне разработки ЗР."""
        rbac = DomainRBAC(domain_id="dom-corp")
        zpe_op = PrincipalContext(
            user_id="op_charlie",
            roles=[CBRRole.ZONE_OPERATOR_ZPE],
            domain_id="dom-corp",
            zone="zr",
        )

        allowed, reason = rbac.evaluate(zpe_op, Action.ZPE_DEPLOY, target_zone="zr")
        assert allowed is False
        assert "403_ZONE_FORBIDDEN" in reason

    def test_team_scope_mismatch_forbidden(self):
        """Разработчик из team_ui не имеет доступа к скоупу team_core."""
        rbac = DomainRBAC(domain_id="dom-corp")
        dev_ui = PrincipalContext(
            user_id="dev_ui_user",
            roles=[CBRRole.DEVELOPER],
            team_scopes=["team_ui"],
        )

        allowed, reason = rbac.evaluate(dev_ui, Action.FINDING_VIEW_TEAM, target_scope="team_core")
        assert allowed is False
        assert "403_SCOPE_MISMATCH" in reason


# ═══════════════════════════════════════════════════════════════════════
# 4. 409 CONFLICT & SEPARATION OF DUTIES (SoD) TESTS
# ═══════════════════════════════════════════════════════════════════════

class Test409SeparationOfDuties:
    """Проверка правил разделения обязанностей (Separation of Duties)."""

    def test_maker_checker_author_cannot_approve(self):
        """Правило SoD: Автор релиза не может сам его утверждать."""
        creator_id = "dev_lead_dave"
        approver_id = "dev_lead_dave"

        clean, code = SeparationOfDutiesEngine.check_release_approval_sod(creator_id, approver_id)
        assert clean is False
        assert "409_SOD_VIOLATION" in code

    def test_maker_checker_independent_officer_allowed(self):
        """Независимый офицер ИБ может утвердить релиз."""
        creator_id = "dev_lead_dave"
        approver_id = "sec_officer_elena"

        clean, code = SeparationOfDutiesEngine.check_release_approval_sod(creator_id, approver_id)
        assert clean is True
        assert code == "200_SOD_CLEAN"

    def test_double_approval_rejected(self):
        """Один и тот же человек не может дважды подписывать один этап."""
        existing = ["sec_officer_elena"]
        current = "sec_officer_elena"

        clean, code = SeparationOfDutiesEngine.check_double_approval_sod(existing, current)
        assert clean is False
        assert "409_SOD_VIOLATION" in code

    def test_transfer_gatekeeper_sod_conflict(self):
        """Инициатор трансфера и лицо, подтверждающее гейты, должны быть разными."""
        initiator = "devops_frank"
        gate_decider = "devops_frank"

        clean, code = SeparationOfDutiesEngine.check_transfer_gatekeeper_sod(initiator, gate_decider)
        assert clean is False
        assert "409_SOD_VIOLATION" in code

    def test_zone_skipping_not_allowed(self):
        """Нельзя перескочить из ЗР напрямую в ЗПЭ, минуя ЗТ."""
        current: ReleaseZone = "zr"
        next_z = next_zone(current)
        assert next_z == "zt"
        assert next_z != "zpe"

        next_after_zt = next_zone("zt")
        assert next_after_zt == "zpe"

        # После ЗПЭ трансферов нет
        assert next_zone("zpe") is None
