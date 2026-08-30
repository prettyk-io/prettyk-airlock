"""
SAN-011 [COS-037]: Negative Security Perimeter Matrix (401 / 403 / 404 / 409 / 422).

Сквозной сьют негативных тестов безопасности:
  - 401 Unauthorized: отсутствие токена, битый/просроченный Bearer, пустые креды.
  - 404 Not Found (Anti-Enumeration): изоляция мультитенантности КИТС, скрытие факта существования чужих ресурсов.
  - 403 Forbidden: RBAC и зональные ограничения (ЗР/ЗТ/ЗПЭ), team scopes изоляция.
  - 409 Conflict (Separation of Duties): Maker-Checker SoD (автор утверждает свой релиз), повторное подписание.
  - 422 Unprocessable Entity (Plaintext Secrets Ban): запрет сохранения открытых токенов/паролей в моделях.
"""
import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError

from cosmo.api.deps import get_current_principal
from cosmo.api.domain_guard import verify_ownership
from cosmo.domain.domain_model import ForgeBinding
from cosmo.domain.rbac import (
    Action,
    CBRRole,
    DomainMember,
    DomainRBAC,
    PrincipalContext,
    Role,
    SeparationOfDutiesEngine,
    require_role,
    require_scoped_role,
)
from cosmo.domain.secret_ref import (
    IntegrationConfig,
    RepositoryBinding,
    VaultSecretRef,
    validate_vault_secret_ref,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. ТЕСТЫ 401 UNAUTHORIZED (Authentication Barrier)
# ═══════════════════════════════════════════════════════════════════════

class Test401UnauthorizedPerimeter:
    """Проверка отсечки 401 при любых проблемах с аутентификацией."""

    @pytest.mark.asyncio
    async def test_missing_authorization_header_raises_401(self):
        """Запрос без заголовка Authorization и кук отсекается с кодом 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_principal(authorization=None, cookie_token=None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "401_UNAUTHORIZED" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_empty_bearer_token_raises_401(self):
        """Запрос с пустым токеном 'Bearer ' вызывает 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_principal(authorization="Bearer ")

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "401_UNAUTHORIZED" in exc_info.value.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_token", [
        "invalid", "expired", "corrupted", "0000", "null", "none"
    ])
    async def test_invalid_tokens_rejected_with_401(self, invalid_token):
        """Все варианты невалидных и просроченных токенов вызывают 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_principal(authorization=f"Bearer {invalid_token}")

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "401_UNAUTHORIZED" in exc_info.value.detail

    def test_domain_rbac_evaluate_unauthenticated_is_401(self):
        """DomainRBAC.evaluate возвращает 401_UNAUTHORIZED для неаутентифицированного субъекта."""
        rbac = DomainRBAC(domain_id="dom-banking")
        anon_p = PrincipalContext(user_id="anonymous", is_authenticated=False)

        allowed, reason = rbac.evaluate(anon_p, Action.READ)
        assert allowed is False
        assert reason == "401_UNAUTHORIZED"


# ═══════════════════════════════════════════════════════════════════════
# 2. ТЕСТЫ 404 NOT FOUND (Anti-Enumeration / Domain Boundary)
# ═══════════════════════════════════════════════════════════════════════

class Test404AntiEnumerationPerimeter:
    """Изоляция доменов: доступ к ресурсам чужого КИТС возвращает 404 без раскрытия существования."""

    def test_cross_domain_resource_access_raises_404(self):
        """Пользователь из kits_alpha пытается запросить ресурс kits_beta -> строго 404."""
        resource_domain = "kits_beta"
        caller_domain = "kits_alpha"

        with pytest.raises(HTTPException) as exc_info:
            verify_ownership(
                resource_domain,
                caller_domain,
                "Release 'rel-secret-01'",
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in exc_info.value.detail.lower()
        # Гарантируем, что факт существования чужого ресурса скрыт
        assert "forbidden" not in exc_info.value.detail.lower()

    def test_same_domain_access_passes_verification(self):
        """Запрос в рамках своего домена успешно проходит верификацию."""
        # Не должно выбрасывать исключений
        verify_ownership(
            "kits_alpha",
            "kits_alpha",
            "Release 'rel-01'",
        )


# ═══════════════════════════════════════════════════════════════════════
# 3. ТЕСТЫ 403 FORBIDDEN (RBAC, Zone Enforcement, Team Scopes)
# ═══════════════════════════════════════════════════════════════════════

class Test403ForbiddenAccessPerimeter:
    """Проверка прав RBAC, зональных ограничений и изоляции команд."""

    @pytest.mark.asyncio
    async def test_developer_cannot_sign_gate_decision_raises_403(self):
        """Разработчик пытается подписать допуск к гейту (gate:decide) -> 403 Forbidden."""
        dev_principal = PrincipalContext(
            user_id="dev_user",
            roles=[CBRRole.DEVELOPER],
            domain_id="dom-secops",
            zone="zr",
            is_authenticated=True,
        )

        guard = require_role(
            allowed_roles=[CBRRole.SECURITY_OFFICER, Role.ADMIN_SEC, CBRRole.ABNORMAL_ADMIN],
            action=Action.GATE_DECIDE,
        )

        with pytest.raises(HTTPException) as exc_info:
            await guard(principal=dev_principal)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "403_ACTION_FORBIDDEN" in exc_info.value.detail

    def test_zone_enforcement_zpe_deploy_forbidden_in_zr(self):
        """Попытка выполнить деплой в ЗПЭ (Пром) из зоны разработки ЗР -> 403 Forbidden."""
        rbac = DomainRBAC(domain_id="dom-banking")
        principal = PrincipalContext(
            user_id="operator_1",
            roles=[CBRRole.ZONE_OPERATOR_ZPE],
            domain_id="dom-banking",
            zone="zr",  # Текущая зона - ЗР
            is_authenticated=True,
        )

        allowed, reason = rbac.evaluate(
            principal=principal,
            action=Action.ZPE_DEPLOY,
            target_zone="zr",  # Действие ЗПЭ запрошено в ЗР
        )
        assert allowed is False
        assert "403_ZONE_FORBIDDEN" in reason

    @pytest.mark.asyncio
    async def test_team_scope_mismatch_raises_403(self):
        """Пользователь со скоупом 'payments' пытается изменить ресурс скоупа 'auth' -> 403 Forbidden."""
        principal = PrincipalContext(
            user_id="dev_payments_lead",
            roles=[CBRRole.DEVELOPER_LEAD],
            domain_id="dom-banking",
            team_scopes=["payments"],
            is_authenticated=True,
        )

        guard = require_scoped_role(
            allowed_roles=[CBRRole.DEVELOPER_LEAD],
            scope="auth",  # Требуется скоуп auth
        )

        with pytest.raises(HTTPException) as exc_info:
            await guard(principal=principal)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Scope" in exc_info.value.detail or "scope" in exc_info.value.detail

    def test_developer_cannot_approve_release_or_transfer(self):
        """Разработчик не имеет прав на утверждение релиза или трансфер."""
        rbac = DomainRBAC(domain_id="dom-banking")
        dev = PrincipalContext(
            user_id="dev_junior",
            roles=[CBRRole.DEVELOPER],
            is_authenticated=True,
        )

        allowed_app, reason_app = rbac.evaluate(dev, Action.RELEASE_APPROVE)
        assert allowed_app is False
        assert "403_ACTION_FORBIDDEN" in reason_app

        allowed_tr, reason_tr = rbac.evaluate(dev, Action.RELEASE_TRANSFER)
        assert allowed_tr is False
        assert "403_ACTION_FORBIDDEN" in reason_tr


# ═══════════════════════════════════════════════════════════════════════
# 4. ТЕСТЫ 409 CONFLICT (Separation of Duties - SoD)
# ═══════════════════════════════════════════════════════════════════════

class Test409SeparationOfDutiesPerimeter:
    """Проверка принципа разделения обязанностей (SoD / Maker-Checker)."""

    def test_release_creator_cannot_approve_own_release_sod(self):
        """Автор релиза (initiator_user_id == 'user-1') пытается сам утвердить свой релиз -> 409 SoD."""
        initiator = "user-1"
        approver = "user-1"

        clean, code = SeparationOfDutiesEngine.check_release_approval_sod(
            release_created_by=initiator,
            approver_id=approver,
        )
        assert clean is False
        assert "409_SOD_VIOLATION" in code
        assert "creator cannot approve" in code

    def test_independent_officer_approval_sod_passed(self):
        """Независимый офицер ИБ может утвердить релиз автора."""
        initiator = "user-1"
        approver = "sec_officer_independent"

        clean, code = SeparationOfDutiesEngine.check_release_approval_sod(
            release_created_by=initiator,
            approver_id=approver,
        )
        assert clean is True
        assert code == "200_SOD_CLEAN"

    def test_double_approval_by_same_user_sod_rejected(self):
        """Один и тот же субъект не может дважды подписывать один этап релиза -> 409 SoD."""
        existing_signers = ["officer_alex"]
        current_signer = "officer_alex"

        clean, code = SeparationOfDutiesEngine.check_double_approval_sod(
            existing_approvers=existing_signers,
            current_approver=current_signer,
        )
        assert clean is False
        assert "409_SOD_VIOLATION" in code

    def test_transfer_initiator_cannot_be_gate_decider_sod(self):
        """Инициатор трансфера не может сам принимать решение по гейту -> 409 SoD."""
        initiator = "devops_sergey"
        gate_decider = "devops_sergey"

        clean, code = SeparationOfDutiesEngine.check_transfer_gatekeeper_sod(
            transfer_initiator=initiator,
            gate_decider=gate_decider,
        )
        assert clean is False
        assert "409_SOD_VIOLATION" in code


# ═══════════════════════════════════════════════════════════════════════
# 5. ТЕСТЫ 422 UNPROCESSABLE ENTITY (Plaintext Secrets Ban)
# ═══════════════════════════════════════════════════════════════════════

class Test422PlaintextSecretsBanPerimeter:
    """Полный запрет открытых токенов и паролей в моделях данных."""

    @pytest.mark.parametrize("plaintext_token", [
        "ghp_123456789012345678901234567890",
        "squ_1234567890abcdef1234567890abcdef",
        "glpat-1234567890abcdef1234",
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "sk-proj-1234567890abcdef1234567890",
        "my_plaintext_insecure_password",
        "admin123",
        "postgresql://admin:super_secret@localhost:5432/db",
    ])
    def test_forge_binding_rejects_plaintext_token_raises_422(self, plaintext_token):
        """ForgeBinding блокирует открытые токены и пароли с ValidationError (HTTP 422)."""
        with pytest.raises(ValidationError) as exc_info:
            ForgeBinding(
                forge_type="gitea",
                url="https://gitea.corp",
                token_ref=plaintext_token,
            )

        assert "Plaintext secrets are forbidden" in str(exc_info.value)

    def test_repository_binding_rejects_raw_webhook_secret_raises_422(self):
        """RepositoryBinding блокирует открытый webhook secret."""
        with pytest.raises(ValidationError) as exc_info:
            RepositoryBinding(
                forge_id="f1",
                repo_path="org/repo",
                webhook_secret_ref="raw_webhook_token_secret_123",
            )

        assert "Plaintext secrets are forbidden" in str(exc_info.value)

    def test_integration_config_rejects_raw_api_tokens_raises_422(self):
        """IntegrationConfig блокирует открытые API-ключи JIRA / SonarQube."""
        with pytest.raises(ValidationError) as exc_info:
            IntegrationConfig(
                integration_id="jira-corp",
                provider_type="jira",
                base_url="https://jira.corp",
                api_token_ref="ghp_plaintext_token_not_vault_ref",
            )

        assert "Plaintext secrets are forbidden" in str(exc_info.value)

    def test_valid_vault_secret_references_accepted_200(self):
        """Корректные Vault-ссылки успешно принимаются всеми моделями."""
        fb = ForgeBinding(
            forge_type="gitea",
            url="https://gitea.corp",
            token_ref="vault:secret/cosmo/forge/gitea",
        )
        assert fb.token_ref == "vault:secret/cosmo/forge/gitea"

        rb = RepositoryBinding(
            forge_id="f1",
            repo_path="org/repo",
            webhook_secret_ref="vault:secret/cosmo/webhooks/gitea",
        )
        assert rb.webhook_secret_ref == "vault:secret/cosmo/webhooks/gitea"

        ic = IntegrationConfig(
            integration_id="sonar-corp",
            provider_type="sonarqube",
            base_url="https://sonar.corp",
            api_token_ref="openbao:secret/cosmo/sonarqube/token",
        )
        assert ic.api_token_ref == "openbao:secret/cosmo/sonarqube/token"
