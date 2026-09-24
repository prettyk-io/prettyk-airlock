"""COS-114: Vault Secret Reference Validator & Plaintext Leak Guard.

Pydantic-валидатор для ссылок vault:secret/path/to/key.
Детектор сырых токенов/паролей в запросах → HTTP 422.
Сканнер утечек для CI.

Двухслойная модель secret-refs (COS-174) — канон, чтобы слои не путали при
миграции. Есть ДВА разных класса ссылок под общим префиксом ``secret/cosmo/``:

**Layer 1 — runtime-токены** (операционные сервис-секреты Космопорта).
Читаются рантаймом ``cosmo-api`` через ``VaultClient`` (AppRole ``cosmo-app``,
COS-105) и ротационным дрилом; значения никогда не лежат в БД/моделях:
  - ``secret/cosmo/database``         — PG-креды
  - ``secret/cosmo/forge/gitea``      — Gitea admin-token (forge adapter)
  - ``secret/cosmo/ci/woodpecker``    — Woodpecker agent secret
  - ``secret/cosmo/minio``            — MinIO-креды
  - ``secret/cosmo/pipeline``         — pipeline-секреты
  - ``secret/cosmo/jwt-keys``         — JWT signing keypair (issuer COS-157 /
                                          verifier COS-156)

**Layer 2 — external-integration creds** (учётные данные ВНЕШНИХ систем).
Хранятся как **строковые значения** ``auth_ref`` в БД/конфиге (DB-default'ы
``forge_auth_ref``/``registry_auth_ref``/``prettyk_auth_ref`` в
``models_lr.py``, ``instance_config.py``, alembic) и резолвятся против
внешних систем при их онбординге — это НЕ runtime-токены Космопорта:
  - ``secret/cosmo/forge/credentials``    — креды внешнего Git-форджа
  - ``secret/cosmo/registry/credentials`` — креды артефактного реестра
  - ``secret/cosmo/prettyk/credentials``  — креды внешнего PrettyK/SecOps

Правило: Layer 1 живёт в ``_KNOWN_VAULT_PATHS`` и в OpenBao-read через
``VaultClient``; Layer 2 — только как reference-строки в моделях/БД, в
``_KNOWN_VAULT_PATHS`` их не добавляем.

Usage:
    from orchestrator.cosmo.domain.vault_ref import VaultSecretRef, validate_secret_reference

    class ForgeBinding(BaseModel):
        token_ref: str = Field(...)
        _validate_token = field_validator("token_ref")(validate_secret_reference)

FastAPI middleware:
    app.add_middleware(PlaintextLeakGuardMiddleware)
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import ValidationError, ValidationInfo
from pydantic_core import PydanticCustomError

try:
    from cosmo.domain.secret_ref import (
        VaultSecretRef,
        validate_vault_secret_ref,
        is_valid_vault_ref,
        IntegrationConfig,
    )
except ImportError:
    from orchestrator.cosmo.domain.secret_ref import (  # type: ignore
        VaultSecretRef,
        validate_vault_secret_ref,
        is_valid_vault_ref,
        IntegrationConfig,
    )

# ══════════════════════════════════════════════════════════════════════════════
# Canonical Vault reference format
# ══════════════════════════════════════════════════════════════════════════════

# Допустимые форматы:
#   vault:secret/cosmo/database       → ключ password
#   vault:secret/cosmo/forge/gitea    → ключ admin_token
#   vault:secret/cosmo/ci/woodpecker  → ключ agent_secret
#   vault:kv-v2/cosmo/data/db         → ключ password
_VAULT_REF_PATTERN = re.compile(
    r"^vault:(secret|kv-v2)/([a-zA-Z0-9_\-/]+)$"
)

# Известные пути OpenBao/Vault для Cosmo
_KNOWN_VAULT_PATHS = frozenset({
    "secret/cosmo/database",
    "secret/cosmo/forge/gitea",
    "secret/cosmo/ci/woodpecker",
    "secret/cosmo/minio",
    "secret/cosmo/pipeline",
})


def validate_secret_reference(value: str, info: Optional[ValidationInfo] = None) -> str:
    """Pydantic field_validator: проверить что строка — корректная ссылка на Vault.

    Вызывает PydanticCustomError если:
      - Строка похожа на сырой токен/пароль (не vault-ссылка)
      - Vault-ссылка не соответствует формату
      - Путь не входит в известные пути Cosmo

    Returns:
        Валидированная строка (без изменений).
    """
    if not value or not value.strip():
        raise PydanticCustomError(
            "vault_ref_required",
            "Secret reference is required. Use vault:secret/cosmo/... format, not raw tokens.",
            {"value": value},
        )

    # ── Plaintext token detection ──────────────────────────────────
    # Сырые токены/пароли не должны попадать в Pydantic-модели.
    # Если значение НЕ начинается с vault: — это подозрительно.
    if not value.startswith("vault:"):
        if _looks_like_token(value):
            raise PydanticCustomError(
                "plaintext_token_detected",
                "Raw token/password detected. All secrets MUST use vault:secret/cosmo/... references. "
                "Never pass plaintext credentials in API requests.",
                {"hint": "Replace with vault:secret/cosmo/<path> or vault:kv-v2/cosmo/data/<path>"},
            )
        # Не токен, но и не vault-ссылка. Разрешаем если это тестовый URL.
        if not value.startswith("http://") and not value.startswith("https://"):
            raise PydanticCustomError(
                "vault_ref_invalid_format",
                "Value must be a vault:secret/... reference or a valid URL.",
                {"value": value[:50], "expected_pattern": "vault:secret/cosmo/<path>"},
            )

        return value

    # ── Vault format validation ────────────────────────────────────
    match = _VAULT_REF_PATTERN.match(value)
    if not match:
        raise PydanticCustomError(
            "vault_ref_invalid_format",
            "Invalid vault reference format. Expected: vault:secret/cosmo/<path> or vault:kv-v2/cosmo/data/<path>",
            {"value": value, "expected_pattern": "vault:(secret|kv-v2)/..."},
        )

    engine = match.group(1)
    path = match.group(2)

    # Проверить что путь входит в known paths (или хотя бы имеет префикс cosmo)
    if not path.startswith("cosmo/") and path not in _KNOWN_VAULT_PATHS:
        raise PydanticCustomError(
            "vault_ref_unknown_path",
            f"Unknown vault path: {path}. Known paths: {sorted(_KNOWN_VAULT_PATHS)}. "
            "Contact security admin to register new vault paths.",
            {"path": path, "known_paths": sorted(_KNOWN_VAULT_PATHS)},
        )

    return value


# ── Token detection heuristics ────────────────────────────────────

# Паттерны которые НИКОГДА не должны быть в теле запроса
_PLAINTEXT_LEAK_PATTERNS = [
    # SonarQube / GitLab / GitHub tokens
    (re.compile(r"^squ_[a-zA-Z0-9]{20,}$"), "SonarQube token"),
    (re.compile(r"^glpat-[a-zA-Z0-9\-_]{20,}$"), "GitLab token"),
    (re.compile(r"^ghp_[a-zA-Z0-9]{20,}$"), "GitHub token"),
    (re.compile(r"^github_pat_[a-zA-Z0-9_]{20,}$"), "GitHub PAT"),
    # JWT / API keys
    (re.compile(r"^eyJ[a-zA-Z0-9\-_]{10,}\.[a-zA-Z0-9\-_]{10,}\.[a-zA-Z0-9\-_]{5,}$"), "JWT token"),
    (re.compile(r"^sk-[a-zA-Z0-9]{20,}$"), "OpenAI API key"),
    (re.compile(r"^xox[bpras]-[a-zA-Z0-9\-]{20,}$"), "Slack token"),
    # PostgreSQL / database URLs with passwords
    (re.compile(r"^postgres(ql)?://[^:]+:[^@]+@"), "PostgreSQL DSN"),
    # Bearer tokens
    (re.compile(r"^Bearer\s+[a-zA-Z0-9\-_\.]{20,}$", re.IGNORECASE), "Bearer token"),
    # OpenBao / Vault tokens
    (re.compile(r"^[hs]\.[a-zA-Z0-9]{20,}$"), "Vault token"),
    (re.compile(r"^hvs\.[a-zA-Z0-9]{20,}$"), "Vault token"),
]


def _looks_like_token(value: str) -> bool:
    """Heuristic: does this look like a raw token/password?"""
    # Vault references and env vars are never raw tokens
    if value.startswith("vault:") or value.startswith("${") or value.startswith("http"):
        return False
    for pattern, _ in _PLAINTEXT_LEAK_PATTERNS:
        if pattern.match(value):
            return True

    # Длиные случайные строки без пробелов (эвристика)
    if len(value) >= 20 and " " not in value and "\n" not in value:
        entropy = _estimate_entropy(value)
        if entropy > 3.5:  # high entropy → likely token
            return True

    return False


def _estimate_entropy(s: str) -> float:
    """Оценить информационную энтропию строки (Shannon, bits per char)."""
    import math
    if len(s) < 4:
        return 0.0
    from collections import Counter
    counter = Counter(s)
    total = len(s)
    entropy = 0.0
    for count in counter.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


# ── Plaintext Leak Scanner (CI script) ────────────────────────────────────

PLAINTEXT_PATTERNS_CI = [
    # Credentials in source files
    (re.compile(r"(password|passwd|pwd|secret|token|api_key|apikey)\s*[:=]\s*['\"]?(?![${\n\r])[\w!@#$%^&*()\-+=]{8,}['\"]?", re.IGNORECASE), "hardcoded credential"),
    (re.compile(r"postgresql://\w+:\w+@"), "database DSN with password"),
    (re.compile(r"squ_[a-zA-Z0-9]{20,}"), "SonarQube token in source"),
    (re.compile(r"ghp_[a-zA-Z0-9]{20,}"), "GitHub PAT in source"),
    (re.compile(r"glpat-[a-zA-Z0-9\-_]{20,}"), "GitLab PAT in source"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "API key in source"),
    (re.compile(r"eyJ[a-zA-Z0-9\-_]{50,}\.[a-zA-Z0-9\-_]{20,}\."), "JWT in source"),
    (re.compile(r"\b\d{16}\b"), "poteential card number"),
]


def scan_for_leaks(file_path: str, content: str) -> list[dict[str, Any]]:
    """Просканировать содержимое файла на утечки.

    Returns:
        list of {file, line, pattern, severity, finding}
    """
    findings = []
    for lineno, line in enumerate(content.splitlines(), 1):
        for pattern, label in PLAINTEXT_PATTERNS_CI:
            match = pattern.search(line)
            if match:
                # Skip false positives: env var default values, -dev/-test suffixes
                matched_text = match.group(0)
                if any(skip in matched_text.lower() for skip in ("dev-agent-secret", "cosmo-minio-dev", "cosmo-bao-root-dev", "change-me", "$cosmo_", "$cosmo_pg_", "${cosmo_")):
                    continue
                findings.append({
                    "file": file_path,
                    "line": lineno,
                    "pattern": label,
                    "severity": "CRITICAL" if "password" in label.lower() or "dsn" in label.lower() else "HIGH",
                    "finding": f"{label}: {matched_text[:60]}...",
                })
    return findings