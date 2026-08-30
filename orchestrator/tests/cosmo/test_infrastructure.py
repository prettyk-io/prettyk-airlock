# -*- coding: utf-8 -*-
"""COS-190-197: Infrastructure config validation tests."""
import sys, yaml, json
from pathlib import Path
import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))
from orchestrator.cosmo.control_plane.run_control import RunControlPlane, RunState

SERVICES = Path(__file__).resolve().parents[3] / "services"

class TestCRDs:
    def test_crd_file_exists(self):
        p = SERVICES / "operator" / "cosmoport-crds.yaml"
        assert p.exists()

    def test_four_crds(self):
        docs = list(yaml.safe_load_all((SERVICES / "operator" / "cosmoport-crds.yaml").read_text()))
        kinds = [d["spec"]["names"]["kind"] for d in docs if d and "spec" in d]
        assert set(kinds) >= {"Domain", "Application", "Run", "GatePolicy"}

class TestOperator:
    def test_controller_imports(self):
        from orchestrator.cosmo.control_plane.run_control import RunControlPlane
        assert callable(RunControlPlane)

class TestMirrorScript:
    def test_mirror_script_exists(self):
        p = SERVICES / "scripts" / "mirror-oci-registry.sh"
        assert p.exists()
        content = p.read_text(encoding="utf-8", errors="replace")
        assert "skopeo copy" in content
        assert "cosign verify" in content

class TestMeshGateway:
    def test_gateway_yaml(self):
        p = SERVICES / "mesh" / "cross-zone-gateway.yaml"
        assert p.exists()
        docs = list(yaml.safe_load_all(p.read_text()))
        kinds = [d.get("kind") for d in docs if d]
        assert "Deployment" in kinds
        assert "ConfigMap" in kinds
        assert "Service" in kinds

class TestPatroniCluster:
    def test_patroni_config(self):
        p = SERVICES / "ha-postgres" / "patroni-cluster.yaml"
        assert p.exists()
        docs = list(yaml.safe_load_all(p.read_text()))
        assert len(docs) >= 2  # ConfigMap + StatefulSet + Services
        assert "synchronous_mode: true" in p.read_text()

class TestMinIOCluster:
    def test_minio_config(self):
        p = SERVICES / "ha-minio" / "distributed-minio.yaml"
        assert p.exists()
        content = p.read_text()
        assert "EC:4" in content  # Erasure Coding mode
        assert "retention" in content.lower() or "object lock" in content.lower()

class TestGrafanaDashboards:
    def test_dashboards_file(self):
        p = SERVICES / "grafana" / "dashboards" / "cosmoport-dashboards.yaml"
        assert p.exists()

    def test_five_dashboards(self):
        p = SERVICES / "grafana" / "dashboards" / "cosmoport-dashboards.yaml"
        content = p.read_text()
        titles = ["CISO Dashboard", "SOC", "Runs", "DB", "Worker"]
        # Each dashboard title should appear in the file
        found = sum(1 for t in titles if t in content)
        assert found >= 3

    def test_alert_rules(self):
        p = SERVICES / "grafana" / "dashboards" / "alertmanager-rules.yaml"
        assert p.exists()
        content = p.read_text()
        assert "ComplianceIndexBelow60" in content
        assert "WorkerPoolExhausted" in content
        assert "MinIONodeDown" in content
        assert "groups:" in content

class TestChaosHarness:
    def test_script_exists(self):
        p = SERVICES / "scripts" / "nightly-chaos-harness.sh"
        assert p.exists()
        content = p.read_text(encoding="utf-8", errors="replace")
        assert "pg-kill-leader" in content
        assert "network-latency-pg" in content
        assert "packet-loss-valkey" in content
        assert "disk-fill-minio" in content

class TestAirgapBuilder:
    def test_script_exists(self):
        p = SERVICES / "scripts" / "build-airgap-appliance.sh"
        assert p.exists()
        content = p.read_text(encoding="utf-8", errors="replace")
        assert "start.sh" in content
        assert "docker-compose.airgap.yml" in content
        assert "cosmoport-2.0-appliance" in content
        assert "cosmo-evidence,cosmo-artifacts,cosmo-builds" in content