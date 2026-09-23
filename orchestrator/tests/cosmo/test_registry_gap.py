# -*- coding: utf-8 -*-
"""COS-163: GAP-режим — честная ошибка вместо молчания/лужи.

Покрытие:
  - ``enforce_gap_push``: локальный local-oci → ок; внешний публичный
    registry → ``RegistryGapError`` (code/message); не-local-oci провайдер
    → блокировка; неподдерживаемая операция → блокировка.
  - ``OciRegistry.push_artifact``: внешний endpoint → RegistryGapError
    (до сетевого вызова), локальный — не блокирует (совместимость).
  - ``generate_pipeline_yaml`` (docker_build шаг): registry=docker.io
    → честная ошибка на генерации, не молчаливый пайплайн.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_och = Path(__file__).resolve().parents[1]
if str(_och) not in sys.path:
    sys.path.insert(0, str(_och))

from orchestrator.cosmo.adapters.artifact_registry import (  # noqa: E402
    RegistryConfig,
    RegistryProvider,
)
from orchestrator.cosmo.adapters.oci_registry import OciRegistry  # noqa: E402
from orchestrator.cosmo.adapters.registry_gap import (  # noqa: E402
    CODE_EXTERNAL_REGISTRY,
    CODE_PROVIDER_NOT_ALLOWED,
    RegistryGapError,
    enforce_gap_push,
)


class TestEnforceGapPush:
    def test_local_oci_localhost_allowed(self):
        enforce_gap_push("local-oci", "http://localhost:5100")

    def test_local_oci_internal_host_allowed(self):
        enforce_gap_push("local-oci", "registry-zr:5000")

    def test_external_docker_io_blocked(self):
        with pytest.raises(RegistryGapError) as exc:
            enforce_gap_push("local-oci", "docker.io/library/alpine")
        assert exc.value.code == CODE_EXTERNAL_REGISTRY
        assert "blocked" in exc.value.message

    def test_ghcr_blocked(self):
        with pytest.raises(RegistryGapError):
            enforce_gap_push("local-oci", "ghcr.io/org/image")

    def test_quay_blocked(self):
        with pytest.raises(RegistryGapError):
            enforce_gap_push("local-oci", "quay.io/org/image")

    def test_provider_nexus_blocked(self):
        with pytest.raises(RegistryGapError) as exc:
            enforce_gap_push("nexus", "http://nexus.local:8082")
        assert exc.value.code == CODE_PROVIDER_NOT_ALLOWED

    def test_provider_t1_sfera_blocked(self):
        with pytest.raises(RegistryGapError):
            enforce_gap_push("t1_sfera", "https://sfera-zpe.kits.bank.corp")

    def test_pull_allowed_operation(self):
        # pull из локального registry разрешён в GAP.
        enforce_gap_push("local-oci", "http://localhost:5100", operation_type="pull")

    def test_delete_operation_blocked(self):
        with pytest.raises(RegistryGapError):
            enforce_gap_push("local-oci", "http://localhost:5100", operation_type="delete")

    def test_error_carries_endpoint_and_provider(self):
        with pytest.raises(RegistryGapError) as exc:
            enforce_gap_push("nexus", "http://nexus.local")
        assert exc.value.endpoint == "http://nexus.local"
        assert exc.value.provider == "nexus"
        assert exc.value.code and exc.value.message


class TestOciRegistryGap:
    def test_push_external_raises_before_network(self):
        cfg = RegistryConfig(
            provider=RegistryProvider.LOCAL_OCI,
            endpoint="https://docker.io",
        )
        reg = OciRegistry(cfg)
        import asyncio
        with pytest.raises(RegistryGapError) as exc:
            asyncio.run(reg.push_artifact("x", "0.1.0", "/tmp/nonexistent"))
        assert exc.value.code == CODE_EXTERNAL_REGISTRY

    def test_push_local_not_gap_blocked_upfront(self):
        # Локальный реестр не должен блокироваться на самом GAP-гейте (падёт
        # на сетевом, если offline — здесь только контракт гейта).
        from orchestrator.cosmo.adapters.registry_gap import enforce_gap_push
        enforce_gap_push("local-oci", "http://localhost:5100")


class TestPipelineYamlGap:
    def test_docker_build_external_registry_raises(self):
        from orchestrator.cosmo.adapters.execution_woodpecker import (
            WoodpeckerAdapter,
        )

        adapter = WoodpeckerAdapter()
        batch = {
            "bricks": [
                {
                    "name": "build",
                    "definition": {
                        "type": "docker_build",
                        "image_name": "cosmo-testapp",
                        "version": "0.1.0",
                        "registry": "docker.io",
                    },
                },
            ],
        }
        with pytest.raises(RegistryGapError) as exc:
            adapter.generate_pipeline_yaml(batch)
        assert exc.value.code == CODE_EXTERNAL_REGISTRY

    def test_docker_build_local_registry_ok(self):
        from orchestrator.cosmo.adapters.execution_woodpecker import (
            WoodpeckerAdapter,
        )

        adapter = WoodpeckerAdapter()
        batch = {
            "bricks": [
                {
                    "name": "build",
                    "definition": {
                        "type": "docker_build",
                        "image_name": "cosmo-testapp",
                        "version": "0.1.0",
                        "registry": "registry-zr:5000",
                    },
                },
            ],
        }
        out = adapter.generate_pipeline_yaml(batch)
        assert "docker push" in out