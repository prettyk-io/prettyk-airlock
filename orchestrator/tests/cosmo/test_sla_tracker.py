import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))
from orchestrator.cosmo.ledger.sla_tracker import calculate_deadline, calculate_sla_status, check_breached_slas, sla_summary, VulnerabilitySLA

NOW = datetime(2025, 6, 1, 12, 0, 0)

class TestCalculateDeadline:
    def test_critical_24h(self):
        d = calculate_deadline("Critical", NOW)
        assert d == NOW + timedelta(hours=24)
    def test_high_7d(self):
        d = calculate_deadline("High", NOW)
        assert d == NOW + timedelta(hours=7*24)
    def test_medium_30d(self):
        d = calculate_deadline("Medium", NOW)
        assert d == NOW + timedelta(hours=30*24)
    def test_low_90d(self):
        d = calculate_deadline("Low", NOW)
        assert d == NOW + timedelta(hours=90*24)
    def test_info_180d(self):
        d = calculate_deadline("Info", NOW)
        assert d == NOW + timedelta(hours=180*24)
    def test_unknown_defauults_180d(self):
        d = calculate_deadline("GARBAGE", NOW)
        assert d == NOW + timedelta(hours=180*24)

class TestCalculateSLAStatus:
    def test_within_sla(self):
        det = NOW
        assert calculate_sla_status("High", det, now=NOW) == "within_sla"
    def test_breached(self):
        det = NOW - timedelta(days=10)
        assert calculate_sla_status("High", det, now=NOW) == "sla_breached"
    def test_resolved_in_time(self):
        det = NOW - timedelta(days=3)
        res = NOW - timedelta(days=2)
        assert calculate_sla_status("High", det, res, now=NOW) == "resolved"
    def test_resolved_late(self):
        det = NOW - timedelta(days=10)
        res = NOW - timedelta(days=1)
        assert calculate_sla_status("High", det, res, now=NOW) == "sla_breached"
    def test_critical_breached_after_25h(self):
        det = NOW - timedelta(hours=25)
        assert calculate_sla_status("Critical", det, now=NOW) == "sla_breached"
    def test_critical_within_23h(self):
        det = NOW - timedelta(hours=23)
        assert calculate_sla_status("Critical", det, now=NOW) == "within_sla"

class TestCheckBreached:
    def test_empty(self):
        assert check_breached_slas([], now=NOW) == []
    def test_all_within(self):
        f = [{"id":"f1","severity":"High","detected_at":NOW-timedelta(days=1)}]
        assert check_breached_slas(f, now=NOW) == []
    def test_one_breached(self):
        f = [{"id":"f2","severity":"Critical","detected_at":NOW-timedelta(hours=25)}]
        r = check_breached_slas(f, now=NOW)
        assert len(r) == 1
        assert r[0].finding_id == "f2"
        assert r[0].status == "sla_breached"
    def test_mixed(self):
        f = [
            {"id":"f3","severity":"Critical","detected_at":NOW-timedelta(hours=25)},
            {"id":"f4","severity":"High","detected_at":NOW-timedelta(days=1)},
        ]
        r = check_breached_slas(f, now=NOW)
        assert len(r) == 1
        assert r[0].finding_id == "f3"

class TestSLASummary:
    def test_empty(self):
        s = sla_summary([])
        assert s["total"] == 0
        assert s["overall_pct"] == 100.0
    def test_all_clean(self):
        from unittest.mock import patch
        fn = "orchestrator.cosmo.ledger.sla_tracker.calculate_sla_status"
        with patch(fn, return_value="within_sla"):
            f = [{"id":"f1","severity":"High","detected_at":NOW}]
            s = sla_summary(f)
            assert s["breached"] == 0
            assert s["overall_pct"] > 90
    def test_one_breached(self):
        from unittest.mock import patch
        fn = "orchestrator.cosmo.ledger.sla_tracker.calculate_sla_status"
        with patch(fn, return_value="sla_breached"):
            f = [{"id":"f2","severity":"Critical","detected_at":NOW}]
            s = sla_summary(f)
            assert s["breached"] == 1
            assert s["overall_pct"] < 100

class TestVulnerabilitySLA:
    def test_model_creation(self):
        v = VulnerabilitySLA(finding_id="f1", severity="Critical", detected_at=NOW, sla_deadline=NOW+timedelta(hours=24), status="within_sla")
        assert v.finding_id == "f1"
    def test_model_breached(self):
        v = VulnerabilitySLA(finding_id="f99", severity="High", detected_at=NOW, sla_deadline=NOW-timedelta(days=1), status="sla_breached", resolution="Fixed by patch")
        assert v.status == "sla_breached"
        assert v.resolution == "Fixed by patch"