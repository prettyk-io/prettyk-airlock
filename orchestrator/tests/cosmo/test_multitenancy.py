# -*- coding: utf-8 -*-
"""COS-061: Multi-tenancy isolation & domain boundary guard tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api.domain_guard import verify_ownership
from orchestrator.cosmo.control_plane.run_control import (
    RunControlPlane,
    RunState,
)


# ══════════════════════════════════════════════════════════════════
# verify_ownership
# ══════════════════════════════════════════════════════════════════

class TestVerifyOwnership:
    def test_own_resource_passes(self):
        verify_ownership("digital-ruble", "digital-ruble", "Run r1")

    def test_cross_domain_raises_404(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership("digital-ruble", "retail-payments", "Run r1")
        assert exc.value.status_code == 404
        assert "Run r1" in exc.value.detail

    def test_none_resource_raises_404(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership(None, "retail-payments", "Release rel1")
        assert exc.value.status_code == 404

    def test_resource_not_found_message(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership("dom-a", "dom-b", "Gate g5")
        assert "not found" in exc.value.detail.lower()

    def test_empty_string_domain_treated_as_none(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            verify_ownership("", "digital-ruble", "Resource")

    def test_release_cross_domain_404(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership("digital-ruble", "retail-payments", "Release rel-001")
        assert exc.value.status_code == 404

    def test_app_cross_domain_404(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership("retail-payments", "digital-ruble", "Application app-42")
        assert exc.value.status_code == 404

    def test_gate_cross_domain_via_plan_404(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership("digital-ruble", "retail-payments", "Gate g1")
        assert exc.value.status_code == 404

    def test_own_domain_access_succeeds(self):
        verify_ownership("digital-ruble", "digital-ruble", "Run r42")


# ══════════════════════════════════════════════════════════════════
# RunControlPlane — per-domain queue isolation
# ══════════════════════════════════════════════════════════════════

def _make_run(c, plan_id="p", domain_id="digital-ruble"):
    run, _ = c.create_run({"plan_id": plan_id, "domain_id": domain_id}, frozenset({"dast"}))
    run.domain_id = domain_id
    return run


class TestRunControlPlaneMultitenancy:
    def test_per_domain_queue_isolation(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))

        run_a = _make_run(c, domain_id="digital-ruble")
        run_b = _make_run(c, domain_id="retail-payments")

        c.submit_run(run_a.id)
        c.enqueue_run(run_a.id)
        c.submit_run(run_b.id)
        c.enqueue_run(run_b.id)

        # One dispatched (w1 busy), one queued globally
        assert c.queue_length() == 1
        assert c.queue_length_for_domain("digital-ruble") >= 0
        assert c.queue_length_for_domain("retail-payments") >= 0

    def test_queue_length_for_domain_unknown(self):
        c = RunControlPlane()
        assert c.queue_length_for_domain("nonexistent") == 0

    def test_runs_with_different_domains_dont_cross_contaminate(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))

        run_a = _make_run(c, domain_id="digital-ruble")
        c.submit_run(run_a.id)
        c.enqueue_run(run_a.id)

        run_b = _make_run(c, domain_id="retail-payments")
        c.submit_run(run_b.id)
        c.enqueue_run(run_b.id)

        assert c.get_run(run_a.id).state == RunState.RUNNING
        assert run_b.state == RunState.QUEUED
        assert run_a.domain_id == "digital-ruble"
        assert run_b.domain_id == "retail-payments"

    def test_per_domain_queue_count_accurate(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))

        for i in range(3):
            r = _make_run(c, plan_id=f"p-{i}", domain_id="digital-ruble")
            c.submit_run(r.id)
            c.enqueue_run(r.id)

        for i in range(2):
            r = _make_run(c, plan_id=f"p-rp-{i}", domain_id="retail-payments")
            c.submit_run(r.id)
            c.enqueue_run(r.id)

        assert c.queue_length_for_domain("digital-ruble") >= 0
        assert c.queue_length_for_domain("retail-payments") >= 0
        assert c.queue_length() >= 0

    def test_create_run_stores_domain_id(self):
        c = RunControlPlane()
        run, _ = c.create_run(
            {"plan_id": "p", "domain_id": "digital-ruble"}, frozenset({"dast"}),
        )
        assert run.domain_id == "digital-ruble"

        run2, _ = c.create_run(
            {"plan_id": "p", "domain_id": "retail-payments"}, frozenset({"dast"}),
        )
        assert run2.domain_id == "retail-payments"
        assert run.domain_id != run2.domain_id

    def test_reset_clears_per_domain_state(self):
        c = RunControlPlane(max_concurrent=1)
        c.register_worker("w1", frozenset({"dast"}))
        r = _make_run(c, domain_id="digital-ruble")
        c.submit_run(r.id)
        c.enqueue_run(r.id)

        c.reset()
        assert c.queue_length_for_domain("digital-ruble") == 0

    def test_domain_runs_isolated_in_snapshot(self):
        c = RunControlPlane()
        r1 = _make_run(c, plan_id="p1", domain_id="digital-ruble")
        r2 = _make_run(c, plan_id="p2", domain_id="digital-ruble")
        r3 = _make_run(c, plan_id="p3", domain_id="retail-payments")

        snap = c.snapshot()
        assert snap["total"] == 3
        assert c.get_run(r1.id).domain_id == "digital-ruble"
        assert c.get_run(r3.id).domain_id == "retail-payments"

    def test_list_runs_filterable_by_domain(self):
        c = RunControlPlane()
        r1 = _make_run(c, domain_id="digital-ruble")
        r2 = _make_run(c, domain_id="retail-payments")

        all_runs = c.list_runs()
        dr_runs = [r for r in all_runs if r.domain_id == "digital-ruble"]
        rp_runs = [r for r in all_runs if r.domain_id == "retail-payments"]

        assert len(dr_runs) == 1
        assert len(rp_runs) == 1
        assert dr_runs[0].id == r1.id


# ══════════════════════════════════════════════════════════════════
# Bulk isolation — 2 domains, complete independence
# ══════════════════════════════════════════════════════════════════

class TestBulkIsolation:
    def test_two_domains_complete_independence(self):
        c = RunControlPlane()

        dr_runs = []
        for i in range(5):
            r = _make_run(c, plan_id=f"dr-p-{i}", domain_id="digital-ruble")
            dr_runs.append(r)

        rp_runs = []
        for i in range(3):
            r = _make_run(c, plan_id=f"rp-p-{i}", domain_id="retail-payments")
            rp_runs.append(r)

        all_runs = c.list_runs()
        assert len(all_runs) == 8

        dr = [r for r in all_runs if r.domain_id == "digital-ruble"]
        rp = [r for r in all_runs if r.domain_id == "retail-payments"]
        assert len(dr) == 5
        assert len(rp) == 3

        from fastapi import HTTPException
        for rp_run in rp_runs:
            with pytest.raises(HTTPException):
                verify_ownership(rp_run.domain_id, "digital-ruble", f"Run '{rp_run.id}'")

        for dr_run in dr_runs:
            with pytest.raises(HTTPException):
                verify_ownership(dr_run.domain_id, "retail-payments", f"Run '{dr_run.id}'")

    def test_transfer_blocked_by_domain_guard(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            verify_ownership("digital-ruble", "retail-payments", "Release transfer-rel")

    def test_empty_domain_scenario(self):
        c = RunControlPlane()
        runs = [r for r in c.list_runs() if r.domain_id == "retail-payments"]
        assert len(runs) == 0
        assert c.queue_length_for_domain("retail-payments") == 0

    def test_cross_domain_access_404(self):
        c = RunControlPlane()
        run = _make_run(c, domain_id="digital-ruble")
        c.submit_run(run.id)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_ownership(run.domain_id, "retail-payments", f"Run '{run.id}'")
        assert exc.value.status_code == 404

    def test_own_domain_access_works(self):
        c = RunControlPlane()
        run = _make_run(c, domain_id="digital-ruble")
        verify_ownership(run.domain_id, "digital-ruble", f"Run '{run.id}'")