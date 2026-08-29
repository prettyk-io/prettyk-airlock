"""COS-005: Тесты EvidenceChain."""
import json
import pytest
from cosmo.ledger import EvidenceEntry, EvidenceLedger


class TestEvidenceLedger:
    def test_genesis_empty(self):
        ledger = EvidenceLedger()
        assert ledger.length == 0
        assert len(ledger.entries) == 0
        assert ledger.verify_chain()

    def test_add_entry_returns_entry(self):
        ledger = EvidenceLedger()
        entry = ledger.add_entry("screenshot", {"url": "http://example.com"}, "run-1/batch-1/step-1")
        assert entry.index == 0
        assert entry.type == "screenshot"
        assert entry.provenance == "run-1/batch-1/step-1"
        assert len(entry.hash) == 64  # SHA-256 hex

    def test_chain_verifies_after_add(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "Critical"}, "run-1")
        ledger.add_entry("log", {"line": "scan complete"}, "run-1")
        assert ledger.verify_chain()

    def test_chain_breaks_on_tamper(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "High"}, "run-1")
        ledger.add_entry("log", {"line": "ok"}, "run-1")
        assert ledger.verify_chain()

        ledger.tamper(0, "type", "tampered")
        assert not ledger.verify_chain()

    def test_chain_breaks_on_content_change(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"count": 1}, "run-1")
        assert ledger.verify_chain()

        ledger.tamper(0, "content", {"count": 999})
        assert not ledger.verify_chain()

    def test_index_must_match(self):
        ledger = EvidenceLedger()
        ledger.add_entry("log", {}, "run-1")
        ledger.add_entry("log", {}, "run-1")
        assert ledger.verify_chain()

        ledger.tamper(0, "index", 5)
        assert not ledger.verify_chain()

    def test_prev_hash_chain(self):
        ledger = EvidenceLedger()
        e1 = ledger.add_entry("log", {"step": 1}, "run-1")
        e2 = ledger.add_entry("log", {"step": 2}, "run-1")

        assert e1.hash == e2.prev_hash
        assert ledger.verify_chain()

    def test_to_dict(self):
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "Critical"}, "run-1")
        d = ledger.to_dict()
        assert d["length"] == 1
        assert len(d["entries"]) == 1
        assert d["verified"] is True
        assert len(d["last_hash"]) == 64


class TestArtifactStore:
    def test_store_and_retrieve(self, tmpdir):
        from cosmo.ledger.artifact_store import ArtifactStore

        store = ArtifactStore(base_dir=str(tmpdir))
        content = b"hello evidence"
        ref = store.store(content, "run-1/batch-1/step-1", "log", "txt")
        assert ref.sha256
        assert ref.size_bytes == len(content)
        assert ref.content_type == "log"

        retrieved = store.retrieve(ref)
        assert retrieved == content

    def test_retrieve_by_ref_id(self, tmpdir):
        import hashlib
        from cosmo.ledger.artifact_store import ArtifactStore

        store = ArtifactStore(base_dir=str(tmpdir))
        content = b"test content"
        sha = hashlib.sha256(content).hexdigest()

        store.store(content, "run-1", "log")
        result = store.retrieve_by_ref_id(sha[:16])
        assert result == content

    def test_list_artifacts(self, tmpdir):
        from cosmo.ledger.artifact_store import ArtifactStore

        store = ArtifactStore(base_dir=str(tmpdir))
        store.store(b"a", "run-1/batch-1", "log")
        store.store(b"b", "run-1/batch-1", "request")

        refs = store.list_artifacts("run-1/batch-1")
        assert len(refs) == 2

    def test_cleanup(self, tmpdir):
        from cosmo.ledger.artifact_store import ArtifactStore

        store = ArtifactStore(base_dir=str(tmpdir))
        store.store(b"x", "run-old", "log")
        assert store.cleanup("run-old") == 1
        assert store.list_artifacts("run-old") == []

    def test_retrieve_missing_raises(self, tmpdir):
        from cosmo.ledger.artifact_store import ArtifactRef, ArtifactStore

        store = ArtifactStore(base_dir=str(tmpdir))
        ref = ArtifactRef(ref_id="xx", path="ghost/file.txt", content_type="log",
                          size_bytes=0, sha256="", provenance="x")
        with pytest.raises(FileNotFoundError):
            store.retrieve(ref)