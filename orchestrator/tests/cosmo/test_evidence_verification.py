# -*- coding: utf-8 -*-
"""COS-060: тесты verify_and_get + tamper detection + replay protection."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger.evidence_chain import (
    EvidenceEntry,
    EvidenceLedger,
)


# ══════════════════════════════════════════════════════════════════
# verify_chain
# ══════════════════════════════════════════════════════════════════

class TestVerifyChain:
    def test_empty_chain_verified(self):
        ledger = EvidenceLedger()
        assert ledger.verify_chain() is True

    def test_single_entry_verified(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "High"}, "run-1/batch-1")
        assert ledger.verify_chain() is True

    def test_multiple_entries_verified(self):
        ledger = EvidenceLedger()
        for i in range(5):
            ledger.add_entry("log", {"msg": f"entry-{i}"}, "run-1/batch-1")
        assert ledger.verify_chain() is True

    def test_tampered_index_breaks_chain(self):
        ledger = EvidenceLedger()
        for i in range(3):
            ledger.add_entry("log", {"msg": str(i)}, "run-1/batch-1")
        ledger.tamper(1, "index", 99)
        assert ledger.verify_chain() is False

    def test_tampered_content_breaks_chain(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "Critical"}, "run-1/batch-1")
        ledger.tamper(0, "content", {"severity": "Low"})
        assert ledger.verify_chain() is False

    def test_tampered_type_breaks_chain(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "High"}, "run-1")
        ledger.tamper(0, "type", "tampered")
        assert ledger.verify_chain() is False

    def test_tampered_prev_hash_breaks_chain(self):
        ledger = EvidenceLedger()
        ledger.add_entry("log", {"msg": "a"}, "run-1")
        ledger.add_entry("log", {"msg": "b"}, "run-1")
        ledger.tamper(1, "prev_hash", "deadbeef")
        assert ledger.verify_chain() is False

    def test_tampered_hash_breaks_chain(self):
        ledger = EvidenceLedger()
        ledger.add_entry("log", {"msg": "a"}, "run-1")
        ledger.tamper(0, "hash", "00" * 32)
        assert ledger.verify_chain() is False

    def test_mid_chain_tamper_breaks(self):
        ledger = EvidenceLedger()
        for i in range(5):
            ledger.add_entry("log", {"msg": str(i)}, "run-1")
        ledger.tamper(2, "content", {"msg": "hacked"})
        assert ledger.verify_chain() is False

    def test_to_dict_includes_verified(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "Critical"}, "run-1")
        d = ledger.to_dict()
        assert d["verified"] is True
        assert d["length"] == 1
        assert len(d["entries"]) == 1
        assert d["entries"][0]["hash"] != ""
        assert d["entries"][0]["prev_hash"] == "0" * 64


# ══════════════════════════════════════════════════════════════════
# verify_and_get (PG-dependent)
# ══════════════════════════════════════════════════════════════════

def _make_orm_row(created_at_ts: float, run_id="run-1", batch_id="b1",
                   entry_id="e1", etype="finding", severity="High"):
    """Симулирует ORM-строку EvidenceLedgerEntry."""
    import datetime as dt
    from unittest.mock import MagicMock

    row = MagicMock()
    row.run_id = run_id
    row.batch_id = batch_id
    row.id = entry_id
    row.type = etype
    row.content_ref = f"minio://{entry_id}"
    row.content_hash = f"sha256-{entry_id}"
    row.provenance_json = {"severity": severity, "title": f"Finding {entry_id}"}
    row.created_at = dt.datetime.fromtimestamp(created_at_ts, tz=dt.timezone.utc)
    return row


class TestVerifyAndGet:
    def test_empty_run(self):
        from unittest.mock import MagicMock
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-empty")
        assert result["verified"] is True
        assert result["total_entries"] == 0
        assert result["tampered_entries"] == []
        assert result["replay_count"] == 0

    def test_single_entry_verified(self):
        from unittest.mock import MagicMock
        rows = [_make_orm_row(1.0, entry_id="e1")]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-1")
        assert result["verified"] is True
        assert result["total_entries"] == 1
        assert result["tampered_chain"] is False
        assert result["tampered_entries"] == []

    def test_multiple_entries_verified(self):
        from unittest.mock import MagicMock
        rows = [
            _make_orm_row(1.0, entry_id="e1", severity="Low"),
            _make_orm_row(2.0, entry_id="e2", severity="Medium"),
            _make_orm_row(3.0, entry_id="e3", severity="High"),
        ]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-1")
        assert result["verified"] is True
        assert result["total_entries"] == 3

    def test_replay_detection(self):
        """Два идентичных entry (same hash) → replay_count = 1."""
        from unittest.mock import MagicMock
        # Same timestamp + same content → same hash
        rows = [
            _make_orm_row(1.0, entry_id="e1", severity="Critical"),
            _make_orm_row(1.0, entry_id="e1", severity="Critical"),  # дубль
        ]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-1")
        assert result["replay_count"] == 1
        assert result["total_entries"] == 2

    def test_chain_in_response(self):
        from unittest.mock import MagicMock
        rows = [_make_orm_row(1.0, entry_id="e1")]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-1")
        chain = result["chain"]
        assert chain["length"] == 1
        assert chain["verified"] is True
        assert len(chain["entries"]) == 1
        assert chain["entries"][0]["type"] == "finding"
        assert "severity" in chain["entries"][0]["content"]

    def test_different_runs_same_ids(self):
        from unittest.mock import MagicMock
        rows = [_make_orm_row(1.0, entry_id="shared-id", run_id="run-a")]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-a")
        assert result["total_entries"] == 1
        assert result["verified"] is True


# ══════════════════════════════════════════════════════════════════
# to_dict after verify
# ══════════════════════════════════════════════════════════════════

class TestToDict:
    def test_empty_ledger_to_dict(self):
        d = EvidenceLedger().to_dict()
        assert d["length"] == 0
        assert d["entries"] == []
        assert d["verified"] is True
        assert d["last_hash"] == "0" * 64

    def test_populated_ledger_to_dict(self):
        ledger = EvidenceLedger()
        e1 = ledger.add_entry("finding", {"severity": "High"}, "run-1/b1")
        d = ledger.to_dict()
        assert d["length"] == 1
        assert d["entries"][0]["hash"] == e1.hash
        assert d["entries"][0]["prev_hash"] == "0" * 64

    def test_tampered_to_dict_false(self):
        ledger = EvidenceLedger()
        ledger.add_entry("log", {"msg": "a"}, "run-1")
        ledger.tamper(0, "content", {"msg": "hacked"})
        assert ledger.to_dict()["verified"] is False


# ══════════════════════════════════════════════════════════════════
# Replay protection
# ══════════════════════════════════════════════════════════════════

class TestReplayProtection:
    def test_verify_and_get_detects_replays(self):
        from unittest.mock import MagicMock
        rows = [
            _make_orm_row(1.0, entry_id="e1"),
            _make_orm_row(1.0, entry_id="e1"),  # replay
            _make_orm_row(2.0, entry_id="e2"),
        ]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-1")
        assert result["replay_count"] == 1
        assert result["total_entries"] == 3

    def test_unique_entries_no_replay(self):
        from unittest.mock import MagicMock
        rows = [
            _make_orm_row(1.0, entry_id="e1", severity="Low"),
            _make_orm_row(2.0, entry_id="e2", severity="Medium"),
            _make_orm_row(3.0, entry_id="e3", severity="High"),
        ]
        fake_s = MagicMock()
        fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        fake_factory = MagicMock(return_value=fake_s)

        result = EvidenceLedger.verify_and_get(fake_factory, "run-1")
        assert result["replay_count"] == 0