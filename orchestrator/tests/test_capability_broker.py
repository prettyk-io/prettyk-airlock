# -*- coding: utf-8 -*-
"""COS-004: CapabilityBroker tests (cosmoport2)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_orch_root = Path(__file__).resolve().parents[1]
if str(_orch_root) not in sys.path:
    sys.path.insert(0, str(_orch_root))


from cosmo.capability.broker import (
    Capability, CapabilityBroker, ResourceHealth, get_broker,
)


# ═══════════════════════════════════════════════════════════════════════════
# COS-004: CapabilityBroker
# ═══════════════════════════════════════════════════════════════════════════

class TestCapabilityBrokerAcquire:
    def test_acquire_returns_port(self):
        b = CapabilityBroker()
        a = b.acquire("run-1", Capability.SCANNER)
        assert a is not None
        assert a.port == 8080
        assert a.run_id == "run-1"

    def test_acquire_idempotent_same_run(self):
        b = CapabilityBroker()
        a1 = b.acquire("run-1", Capability.SCANNER)
        a2 = b.acquire("run-1", Capability.SCANNER)
        assert a1.port == a2.port

    def test_two_runs_different_ports(self):
        b = CapabilityBroker()
        a1 = b.acquire("run-1", Capability.SCANNER)
        a2 = b.acquire("run-2", Capability.SCANNER)
        assert a1.port != a2.port

    def test_different_capabilities_different_ports(self):
        b = CapabilityBroker()
        scanner = b.acquire("run-1", Capability.SCANNER)
        pw = b.acquire("run-1", Capability.PLAYWRIGHT)
        assert scanner.port == 8080
        assert pw.port == 9222
        assert scanner.port != pw.port


class TestCapabilityBrokerRelease:
    def test_release_frees_port(self):
        b = CapabilityBroker()
        b.acquire("run-1", Capability.SCANNER)
        count = b.release("run-1", Capability.SCANNER)
        assert count == 1
        a = b.acquire("run-2", Capability.SCANNER)
        assert a.port == 8080

    def test_release_all_capabilities(self):
        b = CapabilityBroker()
        b.acquire("run-1", Capability.SCANNER)
        b.acquire("run-1", Capability.PLAYWRIGHT)
        count = b.release("run-1")
        assert count == 2

    def test_release_all_broker(self):
        b = CapabilityBroker()
        b.acquire("run-1", Capability.SCANNER)
        b.acquire("run-2", Capability.PLAYWRIGHT)
        total = b.release_all()
        assert total == 2


class TestCapabilityBrokerHealth:
    def test_health_default_healthy(self):
        b = CapabilityBroker()
        assert b.get_health(Capability.SCANNER) == ResourceHealth.HEALTHY

    def test_set_health(self):
        b = CapabilityBroker()
        b.set_health(Capability.SCANNER, ResourceHealth.DEGRADED)
        assert b.get_health(Capability.SCANNER) == ResourceHealth.DEGRADED

    def test_health_snapshot(self):
        b = CapabilityBroker()
        snap = b.health_snapshot()
        assert "scanner" in snap
        assert snap["scanner"] == "healthy"


class TestCapabilityBrokerLease:
    def test_lease_expiry_recovery(self):
        b = CapabilityBroker(lease_seconds=0.01)
        b.acquire("run-stale", Capability.SCANNER)
        time.sleep(0.05)
        expired = b.recover_expired()
        assert len(expired) == 1
        assert expired[0].run_id == "run-stale"

    def test_lease_renewed_on_reacquire(self):
        b = CapabilityBroker(lease_seconds=1.0)
        a1 = b.acquire("run-1", Capability.SCANNER)
        time.sleep(0.01)
        b.acquire("run-1", Capability.SCANNER)
        assert a1.lease_expires_at > time.time()

    def test_is_leased(self):
        b = CapabilityBroker()
        b.acquire("run-1", Capability.SCANNER)
        assert b.is_leased("run-1", Capability.SCANNER)
        assert not b.is_leased("run-2", Capability.SCANNER)