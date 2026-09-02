# -*- coding: utf-8 -*-
"""
COS-060: Adapter-level TLS/mTLS configuration verification.

Правила карточки:
  - tls_verify / private CA reference / mTLS certificate+key reference —
    конфигурируются и ВЕРИФИЦИРУЮТСЯ до сетевых операций;
  - в логах нет секретов: только префикс + отпечаток ссылки;
  - invalid CA/certificate configuration → честный FAIL, не молчаливый downgrade.

Формат ссылок (COS-055/FACT канон): секреты — ТОЛЬКО через
vault:secret/... | openbao:secret/... | file: (путь без содержимого).
Плейнтекст-материал (PEM body, пароль, токен) в конфиге запрещён.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

_SECRET_REF_SCHEMES = ("vault:", "openbao:", "file:")
_REDACTED = "[REDACTED]"


class TLSVerificationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"           # конфигурация не может быть использована безопасно
    INSECURE_EXPLICIT = "insecure_explicit"  # tls_verify=False — явный dev-downgrade


@dataclass
class TLSConfig:
    """TLS/mTLS конфигурация provider adapter. Только ссылки, не материал."""
    tls_verify: bool = True
    ca_cert_ref: str = ""          # private CA: vault:/openbao:/file: ссылка
    client_cert_ref: str = ""      # mTLS certificate reference
    client_key_ref: str = ""       # mTLS private key reference
    server_name_override: str = "" # SNI (опционально, без секретов)
    allow_insecure: bool = False   # явное разрешение tls_verify=False (dev-only)

    def to_logsafe_dict(self) -> dict[str, Any]:
        """Лог-безопасное представление: секретные ссылки маскируются.

        В лог не попадает ни материал, ни полная ссылка — только префикс
        схемы + короткий отпечаток для корреляции.
        """
        def fingerprint(ref: str) -> str:
            if not ref:
                return ""
            scheme = ref.split(":", 1)[0] if ":" in ref else "raw"
            digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:8]
            return f"{scheme}:.../{digest}"

        return {
            "tls_verify": self.tls_verify,
            "ca_cert_ref": fingerprint(self.ca_cert_ref),
            "client_cert_ref": fingerprint(self.client_cert_ref),
            "client_key_ref": fingerprint(self.client_key_ref),
            "server_name_override": self.server_name_override or None,
            "allow_insecure": self.allow_insecure,
        }


@dataclass
class TLSVerification:
    """Результат верификации TLS-конфигурации."""
    status: TLSVerificationStatus
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    logsafe_config: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == TLSVerificationStatus.VALID


def _validate_ref_format(field_name: str, ref: str, problems: list[str]) -> bool:
    """Ссылка должна быть схемной (vault/openbao/file) — не плейнтекст-материал."""
    if not ref:
        return True
    lowered = ref.lower()
    if lowered.startswith("-----begin"):  # PEM body вместо ссылки
        problems.append(f"{field_name}: plaintext PEM material is forbidden, use file: reference")
        return False
    if any(lowered.startswith(s) for s in _SECRET_REF_SCHEMES):
        return True
    problems.append(
        f"{field_name}: unsupported reference format — use vault:secret/..., "
        f"openbao:secret/... or file:/path (got masked as {ref.split(':', 1)[0]}:...)"
    )
    return False


def verify_tls_config(config: TLSConfig) -> TLSVerification:
    """Честная верификация. Не даёт молчаливого downgrade:

    - tls_verify=False БЕЗ allow_insecure → INVALID (явно запрещено);
    - mTLS: cert без key или key без cert → INVALID;
    - плейнтекст PEM в ссылках → INVALID;
    - неправильный формат ссылки → INVALID;
    - tls_verify=True без CA → VALID + note (system trust store).
    """
    problems: list[str] = []
    notes: list[str] = []

    if not config.tls_verify:
        if config.allow_insecure:
            notes.append("tls_verify=False explicitly allowed (dev-only); "
                         "forbidden for zpe/production profiles")
            status_insecure = True
        else:
            problems.append("tls_verify=False without allow_insecure — "
                            "silent downgrade refused")
            status_insecure = False
    else:
        status_insecure = False

    for name, ref in (("ca_cert_ref", config.ca_cert_ref),
                      ("client_cert_ref", config.client_cert_ref),
                      ("client_key_ref", config.client_key_ref)):
        _validate_ref_format(name, ref, problems)

    has_cert = bool(config.client_cert_ref)
    has_key = bool(config.client_key_ref)
    if has_cert != has_key:
        problems.append("mTLS requires BOTH client_cert_ref and client_key_ref "
                        f"(cert={has_cert}, key={has_key})")

    if config.tls_verify and not config.ca_cert_ref:
        notes.append("no private CA configured — system trust store will be used")

    if problems:
        status = TLSVerificationStatus.INVALID
    elif status_insecure:
        status = TLSVerificationStatus.INSECURE_EXPLICIT
    else:
        status = TLSVerificationStatus.VALID

    return TLSVerification(
        status=status, problems=problems, notes=notes,
        logsafe_config=config.to_logsafe_dict(),
    )


def tls_config_from_registry(tls_verify: bool, tls_ca_cert: Optional[str],
                             allow_insecure: bool = False) -> TLSConfig:
    """Маппинг существующей RegistryConfig (BRG-001) на TLSConfig."""
    return TLSConfig(
        tls_verify=tls_verify,
        ca_cert_ref=tls_ca_cert or "",
        allow_insecure=allow_insecure,
    )
