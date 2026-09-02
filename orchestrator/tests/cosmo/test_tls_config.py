# -*- coding: utf-8 -*-
"""
COS-060: TLS/mTLS configuration verification tests.

Проверяет:
  - valid конфигурации (system trust, private CA, mTLS pair);
  - invalid: tls_verify=False без явного allow; cert без key; plaintext PEM;
    неподдерживаемая схема ссылки;
  - insecure_explicit: явный dev-downgrade помечен, не молчит;
  - лог-безопасность: to_logsafe_dict не содержит секретных ссылок;
  - интеграция с SferaProviderConfig и RegistryConfig (BRG-001).
"""
from __future__ import annotations

import pytest

from orchestrator.cosmo.adapters.tls_config import (
    TLSConfig,
    TLSVerificationStatus,
    tls_config_from_registry,
    verify_tls_config,
)
from orchestrator.cosmo.adapters.sfera_provider import SferaProviderConfig


class TestValidTLSConfigurations:
    def test_system_trust_store_is_valid(self):
        v = verify_tls_config(TLSConfig(tls_verify=True))
        assert v.ok
        assert v.status == TLSVerificationStatus.VALID
        assert any("system trust store" in n for n in v.notes)

    def test_private_ca_reference_is_valid(self):
        v = verify_tls_config(TLSConfig(
            tls_verify=True,
            ca_cert_ref="vault:secret/sfera/private-ca",
        ))
        assert v.ok
        assert not v.problems

    def test_mtls_pair_is_valid(self):
        v = verify_tls_config(TLSConfig(
            tls_verify=True,
            ca_cert_ref="vault:secret/sfera/private-ca",
            client_cert_ref="file:/etc/cosmo/tls/client.crt",
            client_key_ref="vault:secret/sfera/client-key",
        ))
        assert v.ok
        assert v.problems == []

    def test_mtls_without_ca_is_valid(self):
        """mTLS pair без private CA — валидно (system store для server verify)."""
        v = verify_tls_config(TLSConfig(
            tls_verify=True,
            client_cert_ref="file:/etc/tls/client.crt",
            client_key_ref="file:/etc/tls/client.key",
        ))
        assert v.ok


class TestInvalidTLSConfigurations:
    def test_tls_verify_false_without_allow_is_invalid(self):
        """Молчаливый downgrade запрещён — INVALID, не valid и не warning."""
        v = verify_tls_config(TLSConfig(tls_verify=False))
        assert not v.ok
        assert v.status == TLSVerificationStatus.INVALID
        assert any("downgrade" in p for p in v.problems)

    def test_cert_without_key_is_invalid(self):
        v = verify_tls_config(TLSConfig(
            tls_verify=True, client_cert_ref="file:/etc/tls/client.crt",
        ))
        assert v.status == TLSVerificationStatus.INVALID
        assert any("BOTH" in p for p in v.problems)

    def test_key_without_cert_is_invalid(self):
        v = verify_tls_config(TLSConfig(
            tls_verify=True, client_key_ref="vault:secret/tls/key",
        ))
        assert v.status == TLSVerificationStatus.INVALID

    def test_plaintext_pem_in_reference_is_invalid(self):
        """PEM body вместо ссылки — запрещено (секреты только по ссылкам)."""
        v = verify_tls_config(TLSConfig(
            tls_verify=True,
            ca_cert_ref="-----BEGIN CERTIFICATE-----\nMIIB...",
        ))
        assert v.status == TLSVerificationStatus.INVALID
        assert any("PEM" in p for p in v.problems)

    def test_unsupported_reference_scheme_is_invalid(self):
        v = verify_tls_config(TLSConfig(
            tls_verify=True, ca_cert_ref="http://insecure.example/ca.pem",
        ))
        assert v.status == TLSVerificationStatus.INVALID
        assert any("unsupported reference format" in p for p in v.problems)


class TestInsecureExplicit:
    def test_allow_insecure_is_explicit_not_valid(self):
        """tls_verify=False + allow_insecure → помечен, НЕ проходит как valid."""
        v = verify_tls_config(TLSConfig(tls_verify=False, allow_insecure=True))
        assert not v.ok
        assert v.status == TLSVerificationStatus.INSECURE_EXPLICIT
        assert any("dev-only" in n for n in v.notes)
        assert any("zpe" in n for n in v.notes)


class TestLogSafety:
    def test_logsafe_dict_contains_no_secret_references(self):
        config = TLSConfig(
            tls_verify=True,
            ca_cert_ref="vault:secret/sfera/private-ca-prod",
            client_cert_ref="file:/etc/cosmo/tls/client.crt",
            client_key_ref="vault:secret/sfera/client-key-prod",
            server_name_override="sfera.internal",
        )
        logsafe = config.to_logsafe_dict()
        serialized = str(logsafe)
        assert "sfera/private-ca-prod" not in serialized
        assert "client-key-prod" not in serialized
        assert "/etc/cosmo/tls/client.crt" not in serialized
        # схема + отпечаток сохранены для корреляции:
        assert logsafe["ca_cert_ref"].startswith("vault:")
        assert logsafe["client_key_ref"].startswith("vault:")

    def test_fingerprint_is_stable_and_short(self):
        config = TLSConfig(tls_verify=True, ca_cert_ref="vault:secret/sfera/ca")
        f1 = config.to_logsafe_dict()["ca_cert_ref"]
        f2 = config.to_logsafe_dict()["ca_cert_ref"]
        assert f1 == f2
        assert len(f1) < 30

    def test_empty_refs_are_empty_in_logsafe(self):
        logsafe = TLSConfig(tls_verify=True).to_logsafe_dict()
        assert logsafe["ca_cert_ref"] == ""


class TestIntegrationSeams:
    def test_registry_config_mapping(self):
        """RegistryConfig (BRG-001) → TLSConfig без потери семантики."""
        cfg = tls_config_from_registry(tls_verify=True, tls_ca_cert="/etc/ca.pem")
        # Путь без схемы → INVALID: честная находка миграции на ссылочный формат
        v = verify_tls_config(cfg)
        assert v.status == TLSVerificationStatus.INVALID

    def test_registry_config_with_vault_ca_is_valid(self):
        cfg = tls_config_from_registry(tls_verify=True, tls_ca_cert="vault:secret/harbor/ca")
        assert verify_tls_config(cfg).ok

    def test_sfera_config_accepts_tls_seam(self):
        """SferaProviderConfig принимает TLSConfig (back-compat: None допустим)."""
        config = SferaProviderConfig(
            base_url="https://sfera.example",
            tls=TLSConfig(tls_verify=True, ca_cert_ref="vault:secret/sfera/ca"),
        )
        assert config.tls is not None
        assert verify_tls_config(config.tls).ok

        legacy = SferaProviderConfig(base_url="https://sfera.example")
        assert legacy.tls is None  # back-compat
