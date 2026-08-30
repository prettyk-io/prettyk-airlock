# -*- coding: utf-8 -*-
"""COS-131: Multi-Zone Network Isolation & Firewall Policy Tests.

Tests:
  - Strict segment isolation: ZR vs ZT vs ZPE
  - Zone boundary permissions: direct cross-zone forbidden
  - Controlled transfer gateway: envelope-only ingress to ZT and ZPE
  - Docker compose multi-zone topology structure validation
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest
import yaml

_repo_root = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.domain.rbac import (
    Action,
    DomainRBAC,
    PrincipalContext,
    Role,
    _ZONE_ALLOWED_ACTIONS,
)
from orchestrator.cosmo.domain.release_model import next_zone


class TestMultiZoneIsolation:
    """Проверка политик сетевой и логической изоляции 3 зон ЦБ."""

    def test_zone_progression_order(self):
        """Зоны идут строго: zr → zt → zpe → None."""
        assert next_zone("zr") == "zt"
        assert next_zone("zt") == "zpe"
        assert next_zone("zpe") is None

    def test_zr_cannot_deploy_zpe(self):
        """В зоне разработки (ZR) невозможно выполнить деплой в ЗПЭ."""
        zr_actions = _ZONE_ALLOWED_ACTIONS["zr"]
        assert Action.ZPE_DEPLOY not in zr_actions
        assert Action.ZPE_ROLLBACK not in zr_actions

    def test_zpe_is_strictly_locked_down(self):
        """ЗПЭ разрешает только безопасные прод-операции, сканирование и конфигурация запрещены."""
        zpe_actions = _ZONE_ALLOWED_ACTIONS["zpe"]
        # Запрещено в проме:
        assert Action.SCAN_START not in zpe_actions
        assert Action.SCAN_STOP not in zpe_actions
        assert Action.PIPELINE_CONFIGURE not in zpe_actions
        assert Action.BRICK_MANAGE not in zpe_actions
        assert Action.DOMAIN_CONFIGURE not in zpe_actions
        # Разрешено в проме:
        assert Action.ZPE_DEPLOY in zpe_actions
        assert Action.ZPE_ROLLBACK in zpe_actions
        assert Action.READ in zpe_actions
        assert Action.ENVELOPE_IMPORT in zpe_actions

    def test_zt_allows_scanning_and_testing(self):
        """Зона Тестирования разрешает сканирование и верификацию."""
        zt_actions = _ZONE_ALLOWED_ACTIONS["zt"]
        assert Action.SCAN_START in zt_actions
        assert Action.GATE_DECIDE in zt_actions
        assert Action.ENVELOPE_VERIFY in zt_actions
        assert Action.ZPE_DEPLOY not in zt_actions

    def test_multizone_compose_topology_valid(self):
        """Проверка YAML-конфигурации docker-compose.multizone.yml."""
        compose_path = _repo_root / "services" / "docker-compose.multizone.yml"
        assert compose_path.exists(), "docker-compose.multizone.yml must exist"

        content = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert "services" in content
        assert "networks" in content
        assert "volumes" in content

        networks = content["networks"]
        assert "cosmo-zr-net" in networks
        assert "cosmo-zt-net" in networks
        assert "cosmo-zpe-net" in networks
        assert "cosmo-firewall-net" in networks

        services = content["services"]
        # Gitea & Woodpecker in ZR
        assert "cosmo-zr-net" in services["cosmo-gitea-zr"]["networks"]
        assert "cosmo-zr-net" in services["cosmo-woodpecker-zr"]["networks"]
        assert "cosmo-zpe-net" not in services["cosmo-gitea-zr"]["networks"]

        # Scanner & Target in ZT
        assert "cosmo-zt-net" in services["cosmo-scanner-zt"]["networks"]
        assert "cosmo-zt-net" in services["cosmo-target-zt"]["networks"]
        assert "cosmo-zr-net" not in services["cosmo-scanner-zt"]["networks"]

        # Postgres, OpenBao, MinIO in ZPE
        assert "cosmo-zpe-net" in services["cosmo-postgres-zpe"]["networks"]
        assert "cosmo-zpe-net" in services["cosmo-openbao-zpe"]["networks"]
        assert "cosmo-zpe-net" in services["cosmo-minio-zpe"]["networks"]
        assert "cosmo-zr-net" not in services["cosmo-postgres-zpe"]["networks"]
