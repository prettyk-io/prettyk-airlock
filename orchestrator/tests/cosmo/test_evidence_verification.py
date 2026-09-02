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
# verify_and_get (COS-082: sealed-anchor контракт)
# ══════════════════════════════════════════════════════════════════

def _make_orm_row(created_at_ts: float, run_id="run-1", batch_id="b1",
                   entry_id="e1", etype="finding", severity="High"):
    """Симулирует ORM-строку EvidenceLedgerEntry (БЕЗ якорей — unsealed)."""
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


def _sealed_rows(*specs):
    """Строки, запечатанные каноническим путём (prev-linked chain)."""
    from orchestrator.cosmo.ledger.evidence_chain import EvidenceLedger

    rows = [_make_orm_row(**spec) for spec in specs]
    prev = EvidenceLedger.GENESIS_HASH
    for row in rows:
        prev = EvidenceLedger.seal_entry(row, prev)
    return rows


def _fake_factory(rows):
    from unittest.mock import MagicMock
    fake_s = MagicMock()
    fake_s.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
    return MagicMock(return_value=fake_s)


class TestVerifyAndGet:
    def test_empty_run(self):
        result = EvidenceLedger.verify_and_get(_fake_factory([]), "run-empty")
        assert result["verified"] is True
        assert result["integrity"] == "ok"
        assert result["total_entries"] == 0
        assert result["tampered_entries"] == []
        assert result["replay_count"] == 0

    def test_single_entry_verified(self):
        rows = _sealed_rows(dict(created_at_ts=1.0, entry_id="e1"))
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is True
        assert result["integrity"] == "ok"
        assert result["total_entries"] == 1
        assert result["tampered_chain"] is False
        assert result["tampered_entries"] == []

    def test_multiple_entries_verified(self):
        rows = _sealed_rows(
            dict(created_at_ts=1.0, entry_id="e1", severity="Low"),
            dict(created_at_ts=2.0, entry_id="e2", severity="Medium"),
            dict(created_at_ts=3.0, entry_id="e3", severity="High"),
        )
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is True
        assert result["integrity"] == "ok"
        assert result["total_entries"] == 3

    def test_tampered_content_detected_with_link(self):
        """Подмена payload после запечатывания → hash_mismatch на звене
        И broken link у следующей строки (prev подписывал оригинал)."""
        rows = _sealed_rows(
            dict(created_at_ts=1.0, entry_id="e1"),
            dict(created_at_ts=2.0, entry_id="e2"),
        )
        rows[0].content_ref = "minio://forged"  # подмена в обход API
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is False
        assert result["integrity"] == "tampered"
        assert result["tampered_entries"] == [0]
        detail = result["tampered_details"][0]
        assert detail["entry_id"] == "e1"
        assert detail["reason"] == "hash_mismatch"
        assert detail["stored_hash"] != detail["recomputed_hash"]

    def test_deleted_middle_row_detected_as_broken_link(self):
        """Удаление средней строки → broken link у следующей (prev указывает
        на хеш удалённой)."""
        rows = _sealed_rows(
            dict(created_at_ts=1.0, entry_id="e1"),
            dict(created_at_ts=2.0, entry_id="e2"),
            dict(created_at_ts=3.0, entry_id="e3"),
        )
        del rows[1]  # e2 удалена из PG
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is False
        assert result["integrity"] == "tampered"
        assert result["tampered_chain"] is True
        link = result["broken_links"][0]
        assert link["entry_id"] == "e3"
        assert link["expected_prev_hash"] != link["stored_prev_hash"]

    def test_unsealed_row_is_not_verified(self):
        """Строка без якорей → честный unsealed: нет доказательства целостности."""
        rows = [
            _sealed_rows(dict(created_at_ts=1.0, entry_id="e1"))[0],
            _make_orm_row(2.0, entry_id="e2"),  # вставлена в обход контракта
        ]
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is False
        assert result["integrity"] == "unsealed"
        assert result["unsealed_entries"] == ["e2"]

    def test_replay_detection(self):
        """Два идентичных entry (same id/content) → replay_count = 1."""
        rows = _sealed_rows(
            dict(created_at_ts=1.0, entry_id="e1", severity="Critical"),
            dict(created_at_ts=1.0, entry_id="e1", severity="Critical"),
        )
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["replay_count"] == 1
        assert result["total_entries"] == 2

    def test_chain_in_response(self):
        rows = _sealed_rows(dict(created_at_ts=1.0, entry_id="e1"))
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        chain = result["chain"]
        assert chain["length"] == 1
        assert chain["verified"] is True
        assert len(chain["entries"]) == 1
        assert chain["entries"][0]["type"] == "finding"
        assert "severity" in chain["entries"][0]["content"]

    def test_different_runs_same_ids(self):
        rows = _sealed_rows(dict(created_at_ts=1.0, entry_id="shared-id", run_id="run-a"))
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-a")
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
        rows = _sealed_rows(
            dict(created_at_ts=1.0, entry_id="e1"),
            dict(created_at_ts=1.0, entry_id="e1"),  # replay
            dict(created_at_ts=2.0, entry_id="e2"),
        )
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["replay_count"] == 1
        assert result["total_entries"] == 3

    def test_unique_entries_no_replay(self):
        rows = _sealed_rows(
            dict(created_at_ts=1.0, entry_id="e1", severity="Low"),
            dict(created_at_ts=2.0, entry_id="e2", severity="Medium"),
            dict(created_at_ts=3.0, entry_id="e3", severity="High"),
        )
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["replay_count"] == 0