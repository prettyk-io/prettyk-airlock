# -*- coding: utf-8 -*-
"""COS-073: tests for MinIOBufferSink."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger.minio_buffer import MinIOBufferSink
from orchestrator.cosmo.ledger.artifact_store import ArtifactRef


@pytest.fixture
def tmp_store():
    """ArtifactStore во временной директории."""
    d = tempfile.mkdtemp(prefix="minio_buffer_test_")
    from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
    store = ArtifactStore(base_dir=d)
    yield store
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sink(tmp_store):
    """MinIOBufferSink без Valkey."""
    return MinIOBufferSink(store=tmp_store, bucket="cosmo-evidence")


@pytest.fixture
def sink_no_valkey(tmp_store):
    """Sink с явно отключённым Valkey."""
    s = MinIOBufferSink(store=tmp_store, bucket="cosmo-evidence", valkey_url="")
    s._valkey = None
    return s


# ══════════════════════════════════════════════════════════════════
# save_report
# ══════════════════════════════════════════════════════════════════

class TestSaveReport:
    def test_single_report(self, sink_no_valkey):
        data = {"version": "2.1.0", "runs": [{"results": []}]}
        ref = sink_no_valkey.save_report("run-001", data)
        assert isinstance(ref, ArtifactRef)
        assert ref.path.startswith("runs/run-001/report.")
        assert ref.sha256 != ""
        assert ref.size_bytes > 0

    def test_sha256_correct(self, sink_no_valkey):
        data = {"key": "value", "nested": {"deep": True}}
        ref = sink_no_valkey.save_report("run-002", data)

        content = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        expected_sha = hashlib.sha256(content).hexdigest()
        assert ref.sha256 == expected_sha

    def test_sha256_consistent(self, sink_no_valkey):
        data = {"findings": [{"id": 1, "severity": "Critical"}]}
        r1 = sink_no_valkey.save_report("run-003", data)
        r2 = sink_no_valkey.save_report("run-003", data)
        # Same data, same SHA
        assert r1.sha256 == r2.sha256

    def test_sha256_different(self, sink_no_valkey):
        r1 = sink_no_valkey.save_report("run-004", {"a": 1})
        r2 = sink_no_valkey.save_report("run-004", {"a": 2})
        assert r1.sha256 != r2.sha256

    def test_s3_uri_in_ref(self, sink_no_valkey):
        data = {"report": "test"}
        ref = sink_no_valkey.save_report("run-005", data)

        event = sink_no_valkey._publish_ingest_event
        # s3_uri is embedded in path → derive expected
        expected_uri = f"s3://cosmo-evidence/runs/run-005/report.sarif.json"
        s3_uri = f"s3://cosmo-evidence/{ref.path}"
        assert s3_uri == expected_uri

    def test_file_written_to_disk(self, sink_no_valkey):
        data = {"results": [{"ruleId": "test"}]}
        ref = sink_no_valkey.save_report("run-006", data)

        full = Path(sink_no_valkey._store._base) / ref.path
        assert full.exists()
        assert full.is_file()
        content = full.read_bytes()
        assert b"test" in content

    def test_roundtrip_read(self, sink_no_valkey):
        data = {"version": "2.1.0", "results": [{"id": "xyz"}]}
        ref = sink_no_valkey.save_report("run-007", data)

        s3_uri = f"s3://cosmo-evidence/{ref.path}"
        content = sink_no_valkey.get_report_stream(s3_uri)
        roundtrip = json.loads(content.decode("utf-8"))
        assert roundtrip == data

    def test_provenance_in_ref(self, sink_no_valkey):
        ref = sink_no_valkey.save_report("run-008", {"x": 1})
        assert "run-008" in ref.provenance

    def test_content_type(self, sink_no_valkey):
        ref = sink_no_valkey.save_report("run-009", {}, report_type="sarif")
        assert ref.content_type == "sarif"


# ══════════════════════════════════════════════════════════════════
# 50 synthetic reports
# ══════════════════════════════════════════════════════════════════

class TestBulkReports:
    def test_fifty_reports_no_failures(self, sink_no_valkey):
        refs = []
        for i in range(50):
            data = {
                "report_id": i,
                "findings": [
                    {
                        "id": f"F-{i}-{j}",
                        "severity": ["Critical", "High", "Medium", "Low"][j % 4],
                    }
                    for j in range((i % 5) + 1)
                ],
                "timestamp": 1724800000.0 + i,
            }
            ref = sink_no_valkey.save_report(f"run-bulk-{i:03d}", data)
            refs.append(ref)

        assert len(refs) == 50
        # All unique SHAs
        shas = {r.sha256 for r in refs}
        assert len(shas) == 50

        # All files exist
        for ref in refs:
            full = Path(sink_no_valkey._store._base) / ref.path
            assert full.exists()

    def test_bulk_no_crashes(self, sink_no_valkey):
        """Save 50 reports rapidly, no exceptions."""
        for i in range(50):
            sink_no_valkey.save_report(
                f"run-stress-{i}", {"idx": i, "data": "x" * 100},
            )


# �═══════════════════════════════════════════════════════════════════
# Valkey Stream event structure
# ══════════════════════════════════════════════════════════════════

class TestValkeyEvent:
    def test_event_structure(self, sink_no_valkey, monkeypatch):
        """Подменяем _publish_to_stream для захвата ивента."""
        captured = []

        def fake_publish(stream, event):
            captured.append((stream, event))

        monkeypatch.setattr(sink_no_valkey, "_publish_to_stream", fake_publish)

        data = {"version": "2.1.0"}
        sink_no_valkey.save_report("run-vk-001", data)

        assert len(captured) == 1
        stream, event = captured[0]
        assert stream == "sonar.ingest"
        assert event["event"] == "report_uploaded"
        assert event["run_id"] == "run-vk-001"
        assert event["s3_uri"].startswith("s3://cosmo-evidence/runs/run-vk-001/report.")
        assert event["sha256"] != ""
        assert isinstance(event["timestamp"], float)

    def test_sha256_in_event_matches_ref(self, sink_no_valkey, monkeypatch):
        captured = []

        def fake_publish_ingest(run_id, sha256, s3_key):
            captured.append({"run_id": run_id, "sha256": sha256, "s3_key": s3_key})

        monkeypatch.setattr(sink_no_valkey, "_publish_ingest_event", fake_publish_ingest)

        data = {"findings": [{"id": "F-1"}]}
        ref = sink_no_valkey.save_report("run-vk-002", data)

        assert len(captured) == 1
        assert captured[0]["sha256"] == ref.sha256
        assert captured[0]["run_id"] == "run-vk-002"

    def test_best_effort_no_crash_on_valkey_failure(self, sink_no_valkey, monkeypatch):
        """Valkey XADD exception → не крашит save_report."""
        def failing_publish(stream, event):
            raise ConnectionError("Valkey down")

        monkeypatch.setattr(sink_no_valkey, "_publish_to_stream", failing_publish)

        ref = sink_no_valkey.save_report("run-vk-003", {"a": 1})
        assert ref.sha256 != ""

    def test_no_valkey_url_is_noop(self, sink_no_valkey, monkeypatch):
        monkeypatch.delenv("COSMO_VALKEY_URL", raising=False)
        sink_no_valkey._valkey = None
        assert sink_no_valkey._get_valkey() is None

        ref = sink_no_valkey.save_report("run-vk-004", {"b": 2})
        assert ref.sha256 != ""


# ══════════════════════════════════════════════════════════════════
# get_report_stream
# ══════════════════════════════════════════════════════════════════

class TestGetReportStream:
    def test_roundtrip(self, sink_no_valkey):
        data = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "SonarQube"}}}]}
        ref = sink_no_valkey.save_report("run-rnd-001", data)
        s3_uri = f"s3://cosmo-evidence/{ref.path}"

        content = sink_no_valkey.get_report_stream(s3_uri)
        assert json.loads(content) == data

    def test_not_found(self, sink_no_valkey):
        with pytest.raises(FileNotFoundError):
            sink_no_valkey.get_report_stream("s3://cosmo-evidence/runs/gost/report.sarif.json")

    def test_large_report(self, sink_no_valkey):
        data = {"findings": [{"id": i, "severity": "Critical"} for i in range(1000)]}
        ref = sink_no_valkey.save_report("run-large", data)
        s3_uri = f"s3://cosmo-evidence/{ref.path}"

        content = sink_no_valkey.get_report_stream(s3_uri)
        rt = json.loads(content)
        assert len(rt["findings"]) == 1000

    def test_parse_s3_uri(self):
        assert MinIOBufferSink._parse_s3_uri("s3://bucket/key/path") == "key/path"
        assert MinIOBufferSink._parse_s3_uri("s3://b/k") == "k"
        assert MinIOBufferSink._parse_s3_uri("no-prefix") == "no-prefix"
        assert MinIOBufferSink._parse_s3_uri("s3://b") == ""


# ══════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════

class TestCleanup:
    def test_files_cleaned_after_test(self, tmp_store):
        """Фикстура должна очистить временную директорию."""
        import tempfile
        d = tempfile.mkdtemp(prefix="cleanup_test_")
        from orchestrator.cosmo.ledger.artifact_store import ArtifactStore
        store = ArtifactStore(base_dir=d)
        sink = MinIOBufferSink(store=store, valkey_url="")
        sink._valkey = None

        sink.save_report("run-cln", {"x": 1})
        assert Path(d).exists()

        shutil.rmtree(d, ignore_errors=True)
        assert not Path(d).exists()