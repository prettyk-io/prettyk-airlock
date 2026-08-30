"""
SAN-010 [COS-035]: Vault Secret Reference Validator & Plaintext Ban.

Строгий валидатор ссылок на секреты OpenBao / HashiCorp Vault.
Гарантирует, что в API и моделях базы данных невозможно сохранить или передать открытый токен / пароль.

Допустимые форматы ссылок:
  - vault:secret/...
  - openbao:secret/...
  - vault:data/...
  - openbao:data/...
  - vault:kv-v2/...
  - vault:cosmo/...

При попытке передать открытый токен (ghp_..., squ_..., Bearer ..., glpat-..., пароль, JWT) —
выбрасывается ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.") -> HTTP 422.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.functional_validators import BeforeValidator

StrictConfig = ConfigDict(extra="ignore")

# Допустимые префиксы ссылок на секреты в OpenBao / Vault
VALID_VAULT_PREFIXES = (
    "vault:secret/",
    "openbao:secret/",
    "vault:data/",
    "openbao:data/",
    "vault:kv-v2/",
    "vault:cosmo/",
    "openbao:cosmo/",
    "vault:",
    "openbao:",
)

# Паттерны открытых секретов, запрещенных в моделях
_PLAINTEXT_SECRET_PATTERNS = [
    re.compile(r"^squ_[a-zA-Z0-9]{20,}$"),                                                        # SonarQube token
    re.compile(r"^glpat-[a-zA-Z0-9\-_]{20,}$"),                                                   # GitLab PAT
    re.compile(r"^ghp_[a-zA-Z0-9]{20,}$"),                                                        # GitHub PAT
    re.compile(r"^github_pat_[a-zA-Z0-9_]{20,}$"),                                                # GitHub Fine-Grained PAT
    re.compile(r"^sk-[a-zA-Z0-9]{20,}$"),                                                         # OpenAI Key
    re.compile(r"^xox[bpras]-[a-zA-Z0-9\-]{20,}$"),                                               # Slack Token
    re.compile(r"^eyJ[a-zA-Z0-9\-_]{10,}\.[a-zA-Z0-9\-_]{10,}\.[a-zA-Z0-9\-_]{5,}$"),            # JWT Token
    re.compile(r"^postgres(ql)?://[^:]+:[^@]+@"),                                                 # PostgreSQL DSN with password
    re.compile(r"^Bearer\s+[a-zA-Z0-9\-_\.]{10,}$", re.IGNORECASE),                               # Bearer token
    re.compile(r"^hvs\.[a-zA-Z0-9]{20,}$"),                                                       # Vault root token
    re.compile(r"^[hs]\.[a-zA-Z0-9]{20,}$"),                                                      # Vault token
]

_COMMON_RAW_PASSWORDS = frozenset({
    "password", "password123", "admin", "admin123", "root", "secret", "123456", "qwerty", "letmein", "toor"
})


def validate_vault_secret_ref(value: Any) -> str:
    """Валидирует ссылку на секрет Vault/OpenBao.

    Бросает ValueError при попытке передачи открытого токена / некорректного формата.
    """
    if not isinstance(value, str):
        raise ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.")

    val = value.strip()
    if not val:
        raise ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.")

    # 1. Проверка на открытые пароли и известные токены
    if val.lower() in _COMMON_RAW_PASSWORDS:
        raise ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.")

    for pattern in _PLAINTEXT_SECRET_PATTERNS:
        if pattern.match(val):
            raise ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.")

    # 2. Проверка валидности префикса Vault/OpenBao
    if not any(val.startswith(p) for p in VALID_VAULT_PREFIXES):
        raise ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.")

    # 3. Длина и формат пути после префикса
    if len(val) < 8:
        raise ValueError("Plaintext secrets are forbidden. Use 'vault:secret/...' reference.")

    return val


def is_valid_vault_ref(value: Any) -> bool:
    """Предикат для быстрой проверки валидности Vault-ссылки."""
    try:
        validate_vault_secret_ref(value)
        return True
    except (ValueError, TypeError):
        return False


# Pydantic Annotated тип для использования в полях моделей
VaultSecretRef = Annotated[str, BeforeValidator(validate_vault_secret_ref)]


# ── Интеграция в доменные модели (SAN-010) ───────────────────────────────────

class ForgeBinding(BaseModel):
    """Привязка Domain к forge с обязательной ссылкой на токен в Vault."""
    model_config = StrictConfig

    forge_type: Literal["gitea", "jenkins", "gitlab"] = Field(default="gitea")
    url: str = Field(..., min_length=1, description="URL forge-инстанса")
    token_ref: VaultSecretRef = Field(..., description="Ссылка на токен в OpenBao (vault:secret/...)")


class RepositoryBinding(BaseModel):
    """Привязка приложения к Git репозиторию."""
    model_config = StrictConfig

    forge_id: str = Field(..., min_length=1)
    repo_path: str = Field(..., min_length=1)
    default_branch: str = Field(default="main")
    webhook_id: Optional[str] = None
    webhook_secret_ref: Optional[VaultSecretRef] = Field(
        default=None,
        description="Ссылка на webhook secret в OpenBao (vault:secret/...)",
    )


class IntegrationConfig(BaseModel):
    """Конфигурация интеграции с внешними enterprise-системами (JIRA, SonarQube, etc.)."""
    model_config = StrictConfig

    integration_id: str = Field(..., min_length=1)
    provider_type: Literal["jira", "confluence", "sonarqube", "woodpecker", "gitea", "defectdojo"]
    base_url: str = Field(..., min_length=1)
    api_token_ref: VaultSecretRef = Field(..., description="Ссылка на API токен в Vault")
    client_secret_ref: Optional[VaultSecretRef] = Field(
        default=None,
        description="Ссылка на Client Secret в Vault",
    )
    is_active: bool = Field(default=True)
