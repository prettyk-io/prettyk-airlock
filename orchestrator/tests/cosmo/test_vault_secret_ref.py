"""
SAN-010 [COS-035]: Tests for Vault Secret Reference Validator & Plaintext Ban.

Проверяет:
  1. Блокировку любых открытых токенов и паролей (ghp_..., squ_..., Bearer ..., glpat-..., sk-..., JWT, DSN, plaintext).
  2. Успешную валидацию ссылок с префиксами vault:secret/..., openbao:secret/..., vault:data/..., vault:kv-v2/...
  3. Интеграцию VaultSecretRef в доменные модели ForgeBinding, RepositoryBinding, IntegrationConfig.
  4. Выбрасывание HTTP 422 / ValidationError при передаче открытого секрета.
"""
import pytest
from pydantic import BaseModel, ValidationError

from cosmo.domain.secret_ref import (
    ForgeBinding,
    IntegrationConfig,
    RepositoryBinding,
    VaultSecretRef,
    is_valid_vault_ref,
    validate_vault_secret_ref,
)


class SampleModel(BaseModel):
    secret_field: VaultSecretRef


# ═══════════════════════════════════════════════════════════════════════
# 1. Plaintext Secrets Rejection Tests (CWE-798 / Hardcoded Credentials)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw_secret", [
    "ghp_123456789012345678901234567890",              # GitHub PAT
    "github_pat_11AAAAAAA012345678901234567890123456",  # GitHub Fine-grained PAT
    "squ_abcdef12345678901234567890123456",             # SonarQube token
    "glpat-1234567890abcdef1234",                       # GitLab token
    "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig12345",     # Bearer token
    "sk-proj-1234567890abcdef1234567890",               # OpenAI key
    "xoxb-1234567890-abcdef123456",                     # Slack token
    "postgresql://user:secret_password@db.corp:5432/db",# DSN with password
    "password123",                                      # Raw password
    "admin",                                            # Weak password
    "root",                                             # Weak password
    "123456",                                           # Weak password
    "hvs.CAESIL999999999999999999999999",               # Vault root token
    "s.CAESIL999999999999999999999999",                 # Vault token
    "",                                                 # Empty string
    "   ",                                              # Whitespace
])
def test_reject_plaintext_tokens_and_passwords(raw_secret):
    """Все открытые токены и пароли строго отклоняются валидатором."""
    assert is_valid_vault_ref(raw_secret) is False

    with pytest.raises(ValueError, match="Plaintext secrets are forbidden"):
        validate_vault_secret_ref(raw_secret)

    with pytest.raises(ValidationError) as exc_info:
        SampleModel(secret_field=raw_secret)

    assert "Plaintext secrets are forbidden" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════
# 2. Valid Vault / OpenBao Secret Reference Tests
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("valid_ref", [
    "vault:secret/cosmo/database",
    "vault:secret/cosmo/forge/gitea",
    "vault:secret/cosmo/ci/woodpecker",
    "vault:secret/banking/core/api_key",
    "openbao:secret/cosmo/minio",
    "openbao:secret/cosmo/pipeline",
    "vault:data/cosmo/prod/hsm_key",
    "openbao:data/cosmo/certs/root_ca",
    "vault:kv-v2/cosmo/secrets/db_password",
    "vault:cosmo/credentials/jira_token",
    "openbao:cosmo/keys/signing_key_01",
])
def test_accept_valid_vault_secret_references(valid_ref):
    """Корректные ссылки на секреты OpenBao/Vault успешно принимаются."""
    assert is_valid_vault_ref(valid_ref) is True
    validated = validate_vault_secret_ref(valid_ref)
    assert validated == valid_ref

    model = SampleModel(secret_field=valid_ref)
    assert model.secret_field == valid_ref


# ═══════════════════════════════════════════════════════════════════════
# 3. Domain Model Integration Tests (ForgeBinding, RepositoryBinding, IntegrationConfig)
# ═══════════════════════════════════════════════════════════════════════

def test_forge_binding_vault_ref_validation():
    """ForgeBinding: успешное создание с vault-ссылкой и блокировка открытого токена."""
    # Успешное создание
    fb = ForgeBinding(
        forge_type="gitea",
        url="https://gitea.internal.corp",
        token_ref="vault:secret/cosmo/forge/gitea",
    )
    assert fb.token_ref == "vault:secret/cosmo/forge/gitea"

    # Отсечка открытого токена Gitea
    with pytest.raises(ValidationError) as exc_info:
        ForgeBinding(
            forge_type="gitea",
            url="https://gitea.internal.corp",
            token_ref="ghp_abcdef12345678901234567890123456",
        )
    assert "Plaintext secrets are forbidden" in str(exc_info.value)


def test_repository_binding_webhook_secret_ref():
    """RepositoryBinding: валидация webhook_secret_ref."""
    rb = RepositoryBinding(
        forge_id="f1",
        repo_path="payments/core",
        webhook_secret_ref="vault:secret/cosmo/webhooks/payments",
    )
    assert rb.webhook_secret_ref == "vault:secret/cosmo/webhooks/payments"

    # Блокировка сырого webhook secret
    with pytest.raises(ValidationError) as exc_info:
        RepositoryBinding(
            forge_id="f1",
            repo_path="payments/core",
            webhook_secret_ref="my_secret_webhook_password_123",
        )
    assert "Plaintext secrets are forbidden" in str(exc_info.value)


def test_integration_config_enterprise_credentials():
    """IntegrationConfig: валидация учетных данных JIRA, SonarQube, Confluence."""
    # 1. JIRA интеграция с Vault-ссылкой
    jira_cfg = IntegrationConfig(
        integration_id="jira-banking",
        provider_type="jira",
        base_url="https://jira.bank.corp",
        api_token_ref="vault:secret/integrations/jira/api_token",
        client_secret_ref="vault:secret/integrations/jira/oauth_secret",
    )
    assert jira_cfg.api_token_ref == "vault:secret/integrations/jira/api_token"
    assert jira_cfg.client_secret_ref == "vault:secret/integrations/jira/oauth_secret"

    # 2. Попытка передать открытый SonarQube токен
    with pytest.raises(ValidationError) as exc_info:
        IntegrationConfig(
            integration_id="sonar-core",
            provider_type="sonarqube",
            base_url="https://sonar.bank.corp",
            api_token_ref="squ_1234567890abcdef1234567890abcdef",
        )
    assert "Plaintext secrets are forbidden" in str(exc_info.value)
