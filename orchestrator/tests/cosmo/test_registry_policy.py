# -*- coding: utf-8 -*-
"""COS-171/172: тесты registry_policy — точечный insecure-allow.

Покрытие:
  - ``registry_host`` вытаскивает host[:port] из scheme/plain/диgest-рефов;
  - ``load_insecure_hosts``: env → дефолт ``{cosmo-registry-zr:5000}``;
  - ``allows_insecure``: True только для allowlisted хоста, False для прочих.

Запуск:  pytest .../test_registry_policy.py -q
"""
from __future__ import annotations

from orchestrator.cosmo.scanner.registry_policy import (
    DEFAULT_INSECURE_REGISTRY_HOSTS,
    allows_insecure,
    load_insecure_hosts,
    registry_host,
)


class TestRegistryHost:
    def test_plain(self):
        assert registry_host("cosmo-registry-zr:5000/x") == "cosmo-registry-zr:5000"

    def test_scheme(self):
        assert registry_host("http://cosmo-registry-zr:5000/x") == \
            "cosmo-registry-zr:5000"

    def test_digest_ref(self):
        assert registry_host("registry.example.com/x@sha256:abc") == \
            "registry.example.com"

    def test_bare_image(self):
        assert registry_host("redis:7") == "redis:7"


class TestLoadInsecureHosts:
    def test_default_when_empty(self):
        assert load_insecure_hosts("") == DEFAULT_INSECURE_REGISTRY_HOSTS
        assert load_insecure_hosts(None) == DEFAULT_INSECURE_REGISTRY_HOSTS

    def test_env_list(self):
        hosts = load_insecure_hosts("cosmo-registry-zr:5000,other:5000")
        assert hosts == {"cosmo-registry-zr:5000", "other:5000"}


class TestAllowsInsecure:
    def test_allowlisted_host(self):
        assert allows_insecure(
            "cosmo-registry-zr:5000/cosmoport/zr/x",
            DEFAULT_INSECURE_REGISTRY_HOSTS,
        )

    def test_external_host_not_allowed(self):
        assert not allows_insecure(
            "registry.example.com/x", DEFAULT_INSECURE_REGISTRY_HOSTS,
        )

    def test_scheme_prefix_still_matches(self):
        assert allows_insecure(
            "http://cosmo-registry-zr:5000/x", DEFAULT_INSECURE_REGISTRY_HOSTS,
        )