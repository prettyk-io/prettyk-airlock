# -*- coding: utf-8 -*-
"""COS-087: внешний append-only якорь головы evidence-цепочки.

Юниты sink-контракта: publish (append-only, last-wins), read-статусы
(ok / unknown_anchor при недоступном якоре / disabled), сверка головы
в verify_and_get (head_mismatch отдельным статусом).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.ledger import evidence_anchor
from orchestrator.cosmo.ledger.evidence_chain import EvidenceLedger


H1 = "a" * 64
H2 = "b" * 64


# ══════════════════════════════════════════════════════════════════
# Sink: publish / read
# ══════════════════════════════════════════════════════════════════

class TestAnchorSink:
    def test_disabled_when_env_unset(self, monkeypatch, tmp_path):
        monkeypatch.delenv(evidence_anchor.ANCHOR_FILE_ENV, raising=False)
        assert evidence_anchor.is_enabled() is False
        # publish — честный no-op
        evidence_anchor.publish_head("run-1", H1)
        assert evidence_anchor.read_head("run-1")["status"] == "unknown_anchor"

    def test_publish_then_read_ok(self, monkeypatch, tmp_path):
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))
        evidence_anchor.publish_head("run-1", H1, entry_id="e1")
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "ok"
        assert info["anchored_head"] == H1
        assert info["anchored_at"]

    def test_last_anchor_wins(self, monkeypatch, tmp_path):
        """Несколько публикаций головы → читается последняя (эволюция цепочки)."""
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))
        evidence_anchor.publish_head("run-1", H1)
        evidence_anchor.publish_head("run-1", H2)
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "ok"
        assert info["anchored_head"] == H2  # последняя публикация
        # append-only: обе строки физически в файле
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_other_run_not_anchored(self, monkeypatch, tmp_path):
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))
        evidence_anchor.publish_head("run-a", H1)
        info = evidence_anchor.read_head("run-b")
        assert info["status"] == "unknown_anchor"
        assert "no anchor" in info["detail"]

    def test_missing_sink_is_unknown(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            evidence_anchor.ANCHOR_FILE_ENV, str(tmp_path / "nope.jsonl"))
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "unknown_anchor"
        assert "does not exist" in info["detail"]

    def test_publish_failure_is_visible(self, monkeypatch, tmp_path):
        """Sink недоступен на записи → исключение (fail visible), не тишина."""
        monkeypatch.setenv(
            evidence_anchor.ANCHOR_FILE_ENV, str(tmp_path / "anchor.jsonl"))
        # создаём на месте файла директорию → open() падает
        bad = tmp_path / "anchor.jsonl"
        bad.mkdir()
        try:
            evidence_anchor.publish_head("run-1", H1)
        except OSError:
            return  # честный фейл — ок
        pytest.fail("publish_head должен упасть при невозможности записи")


# ══════════════════════════════════════════════════════════════════
# verify_and_get: externally-anchored режим (COS-087)
# ══════════════════════════════════════════════════════════════════

def _make_orm_row(created_at_ts: float, run_id="run-1", batch_id="b1",
                  entry_id="e1", etype="finding", severity="High"):
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


class TestVerifyAndGetAnchored:
    def test_disabled_anchoring_internal_verdict_only(self, monkeypatch):
        """Якорь не сконфигурирован → anchor.status=disabled, internal вердикт."""
        monkeypatch.delenv(evidence_anchor.ANCHOR_FILE_ENV, raising=False)
        rows = []
        prev = EvidenceLedger.GENESIS_HASH
        for i, ts in enumerate((1.0, 2.0)):
            row = _make_orm_row(ts, entry_id=f"e{i+1}")
            prev = EvidenceLedger.seal_entry(row, prev)
            rows.append(row)
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is True
        assert result["integrity"] == "ok"
        assert result["anchor"]["enabled"] is False
        assert result["head_mismatch"] is False

    def test_anchor_ok_when_head_matches(self, monkeypatch, tmp_path):
        """Голова сходится с внешним якорем → integrity ok, anchor ok."""
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))

        rows = []
        prev = EvidenceLedger.GENESIS_HASH
        for i, ts in enumerate((1.0, 2.0, 3.0)):
            row = _make_orm_row(ts, entry_id=f"e{i+1}")
            prev = EvidenceLedger.seal_entry(row, prev)
            rows.append(row)
        # write-path публикует именно фактическую голову
        evidence_anchor.publish_head("run-1", prev)

        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["verified"] is True
        assert result["integrity"] == "ok"
        assert result["anchor"]["status"] == "ok"
        assert result["anchor"]["anchored_head"] == result["anchor"]["computed_head"]
        assert result["head_mismatch"] is False

    def test_suffix_resign_detected_as_head_mismatch(self, monkeypatch, tmp_path):
        """ФЛАГМАН COS-087: атакующий пере-подписывает ВЕСЬ суффикс цепочки.

        Internal verify при этом чист (якоря переподписаны вместе с payload),
        но внешний append-only якорь хранит СТАРУЮ голову → head_mismatch,
        verified=False. Раньше это была принципиально недетектируемая атака.
        """
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))

        rows = []
        prev = EvidenceLedger.GENESIS_HASH
        for i, ts in enumerate((1.0, 2.0, 3.0)):
            row = _make_orm_row(ts, entry_id=f"e{i+1}")
            prev = EvidenceLedger.seal_entry(row, prev)
            rows.append(row)
        evidence_anchor.publish_head("run-1", prev)

        # атака: подменить payload И корректно переподписать всю цепочку
        attacker_prev = EvidenceLedger.GENESIS_HASH
        for row in rows:
            row.provenance_json = {"severity": "Low", "title": "Rewritten"}
            row.content_ref = "minio://forged"
            attacker_prev = EvidenceLedger.seal_entry(row, attacker_prev)

        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["integrity"] == "head_mismatch"
        assert result["verified"] is False
        assert result["head_mismatch"] is True
        assert result["tampered_entries"] == []  # internal verify чист
        assert result["broken_links"] == []
        assert result["anchor"]["status"] == "head_mismatch"
        assert result["anchor"]["anchored_head"] is not None
        assert result["anchor"]["computed_head"] != result["anchor"]["anchored_head"]

    def test_unavailable_anchor_is_honestly_unknown(self, monkeypatch, tmp_path):
        """Sink сконфигурирован, но файл отсутствует → честный unknown_anchor:
        internal вердикт не притворяется внешне подтверждённым."""
        monkeypatch.setenv(
            evidence_anchor.ANCHOR_FILE_ENV, str(tmp_path / "gone.jsonl"))
        rows = []
        prev = EvidenceLedger.GENESIS_HASH
        for ts in (1.0, 2.0):
            row = _make_orm_row(ts, entry_id=f"e{int(ts)}")
            prev = EvidenceLedger.seal_entry(row, prev)
            rows.append(row)
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        # internal чист, но якорь недоступен — integrity остаётся internal-вердиктом
        assert result["integrity"] == "ok"
        assert result["verified"] is True
        assert result["anchor"]["status"] == "unknown_anchor"
        assert result["head_mismatch"] is False
        assert result["anchor"]["enabled"] is True

    def test_anchor_mismatch_after_head_loss(self, monkeypatch, tmp_path):
        """Голова потеряна в PG (последняя строка удалена), якорь цел →
        head_mismatch: внешнее доказательство расходится с фактическим."""
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))

        rows = []
        prev = EvidenceLedger.GENESIS_HASH
        for i, ts in enumerate((1.0, 2.0, 3.0)):
            row = _make_orm_row(ts, entry_id=f"e{i+1}")
            prev = EvidenceLedger.seal_entry(row, prev)
            rows.append(row)
        evidence_anchor.publish_head("run-1", prev)  # голова e3

        del rows[2]  # голова удалена из PG
        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        # внутренне цепочка 2 строк целa, но внешняя голова (e3) отсутствует
        assert result["anchor"]["status"] == "head_mismatch"
        assert result["head_mismatch"] is True
        assert result["integrity"] == "head_mismatch"
        assert result["verified"] is False


# ══════════════════════════════════════════════════════════════════
# COS-093: S3/MinIO backend (fake S3 на httpx.MockTransport)
# ══════════════════════════════════════════════════════════════════

import httpx


class _FakeS3:
    """Минимальный fake S3: объекты в dict, versioning-PUT фиксируется,
    настраиваемые фейлы (GET/PUT статус, connection error, corrupt body)."""

    def __init__(self, *, get_status=None, put_status=None, drop=False,
                 corrupt=False):
        self.objects: dict[str, str] = {}
        self.versioning_calls = 0
        self.get_status = get_status
        self.put_status = put_status
        self.drop = drop
        self.corrupt = corrupt

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.drop:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if request.url.params.get("versioning") is not None:
            self.versioning_calls += 1
            return httpx.Response(200)
        if request.method == "GET":
            if self.get_status is not None:
                return httpx.Response(self.get_status)
            if path not in self.objects:
                return httpx.Response(404)
            body = self.objects[path]
            if self.corrupt:
                body = "{not json at all\n"
            return httpx.Response(200, text=body)
        if request.method == "PUT":
            if self.put_status is not None:
                return httpx.Response(self.put_status, text="err")
            self.objects[path] = request.content.decode("utf-8")
            return httpx.Response(200)
        return httpx.Response(405)

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url="http://fake-minio:9000",
            transport=httpx.MockTransport(self.handler),
        )


def _s3_env(monkeypatch, bucket="cosmo-evidence"):
    monkeypatch.setenv(evidence_anchor.BACKEND_ENV, "s3")
    monkeypatch.setenv("PK_MINIO_URL", "http://fake-minio:9000")
    monkeypatch.setenv(evidence_anchor.S3_BUCKET_ENV, bucket)
    monkeypatch.setattr(evidence_anchor, "_S3_SINK_CACHE", None)


def _inject_fake(monkeypatch, fake):
    sink = evidence_anchor.S3AnchorSink(
        "http://fake-minio:9000", "cosmo", "secret",
        bucket="cosmo-evidence", prefix="evidence-anchor/",
        client=fake.client(),
    )
    monkeypatch.setattr(evidence_anchor, "_build_s3_sink", lambda cfg: sink)


class TestS3BackendDispatch:
    def test_default_backend_is_file(self, monkeypatch):
        monkeypatch.delenv(evidence_anchor.BACKEND_ENV, raising=False)
        assert evidence_anchor.backend() == "file"

    def test_backend_env_selects_s3(self, monkeypatch):
        monkeypatch.setenv(evidence_anchor.BACKEND_ENV, "s3")
        assert evidence_anchor.backend() == "s3"

    def test_s3_without_endpoint_is_disabled(self, monkeypatch):
        monkeypatch.setenv(evidence_anchor.BACKEND_ENV, "s3")
        monkeypatch.delenv("PK_MINIO_URL", raising=False)
        assert evidence_anchor.is_enabled() is False
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "unknown_anchor"
        assert "not configured" in info["detail"]

    def test_s3_misconfigured_publish_fails_visible(self, monkeypatch):
        """backend=s3 без endpoint → publish RAISE (fail visible),
        тихо потерять якорь нельзя."""
        monkeypatch.setenv(evidence_anchor.BACKEND_ENV, "s3")
        monkeypatch.delenv("PK_MINIO_URL", raising=False)
        with pytest.raises(RuntimeError, match="PK_MINIO_URL"):
            evidence_anchor.publish_head("run-1", H1)

    def test_s3_mode_ignores_file_env(self, monkeypatch, tmp_path):
        """s3-бэкенд: ANCHOR_FILE_ENV не применим — sink_path вернёт None,
        а read/publish идут в object-store."""
        path = tmp_path / "anchor.jsonl"
        monkeypatch.setenv(evidence_anchor.ANCHOR_FILE_ENV, str(path))
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        evidence_anchor.publish_head("run-1", H1)
        assert not path.exists()  # файловая ветка не тронута
        assert evidence_anchor.read_head("run-1")["status"] == "ok"


class TestS3AnchorSink:
    def test_publish_then_read_ok(self, monkeypatch):
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        evidence_anchor.publish_head("run-1", H1, entry_id="e1")
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "ok"
        assert info["anchored_head"] == H1
        assert info["anchored_at"]
        # объект по ключу prefix/{run_id}.jsonl
        assert "/cosmo-evidence/evidence-anchor/run-1.jsonl" in fake.objects

    def test_last_anchor_wins_jsonl_accumulates(self, monkeypatch):
        """Несколько публикаций → JSONL накапливается (GET-append-PUT),
        читается последняя голова."""
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        evidence_anchor.publish_head("run-1", H1)
        evidence_anchor.publish_head("run-1", H2, entry_id="e2")
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "ok"
        assert info["anchored_head"] == H2
        lines = fake.objects["/cosmo-evidence/evidence-anchor/run-1.jsonl"].strip().splitlines()
        assert len(lines) == 2  # история голов сохранена в объекте

    def test_versioning_attempted_once(self, monkeypatch):
        """Append-only замена: publish пытается включить versioning бакета
        (best-effort, один раз на sink-инстанс)."""
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        evidence_anchor.publish_head("run-1", H1)
        evidence_anchor.publish_head("run-1", H2)
        assert fake.versioning_calls == 1

    def test_missing_object_is_unknown(self, monkeypatch):
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        info = evidence_anchor.read_head("run-404")
        assert info["status"] == "unknown_anchor"
        assert "no anchor object" in info["detail"]

    def test_s3_unreadable_is_honestly_unknown(self, monkeypatch):
        """S3 недоступен на чтении → честный unknown_anchor (не ok)."""
        fake = _FakeS3(drop=True)
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "unknown_anchor"
        assert "unreadable" in info["detail"]

    def test_http_500_on_read_is_unknown(self, monkeypatch):
        fake = _FakeS3(get_status=500)
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "unknown_anchor"
        assert "HTTP 500" in info["detail"]

    def test_corrupt_object_is_unknown(self, monkeypatch):
        """Объект подменён мусором → unknown_anchor, не притворяемся ok."""
        fake = _FakeS3(corrupt=True)
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        fake.objects["/cosmo-evidence/evidence-anchor/run-1.jsonl"] = "garbage"
        info = evidence_anchor.read_head("run-1")
        assert info["status"] == "unknown_anchor"
        assert "corrupt" in info["detail"]

    def test_publish_failure_is_visible(self, monkeypatch):
        """S3 недоступен на записи / 500 → RuntimeError (fail visible)."""
        fake = _FakeS3(drop=True)
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        with pytest.raises(RuntimeError, match="read-before-append|publish failed"):
            evidence_anchor.publish_head("run-1", H1)

    def test_publish_500_is_visible(self, monkeypatch):
        fake = _FakeS3(put_status=500)
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            evidence_anchor.publish_head("run-1", H1)

    def test_other_run_not_anchored(self, monkeypatch):
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)
        evidence_anchor.publish_head("run-a", H1)
        info = evidence_anchor.read_head("run-b")
        assert info["status"] == "unknown_anchor"
        assert "no anchor" in info["detail"]


class TestS3VerifyAndGet:
    """verify_and_get поверх S3-якоря: контракт head_mismatch не меняется."""

    def test_tamper_detected_through_s3_anchor(self, monkeypatch):
        """COS-093 сквозной (fake S3): цепочка пере-подписана, якорь в S3
        хранит старую голову → head_mismatch, verified=False."""
        fake = _FakeS3()
        _s3_env(monkeypatch)
        _inject_fake(monkeypatch, fake)

        rows = []
        prev = EvidenceLedger.GENESIS_HASH
        for i, ts in enumerate((1.0, 2.0, 3.0)):
            row = _make_orm_row(ts, entry_id=f"e{i+1}")
            prev = EvidenceLedger.seal_entry(row, prev)
            rows.append(row)
        evidence_anchor.publish_head("run-1", prev)

        attacker_prev = EvidenceLedger.GENESIS_HASH
        for row in rows:
            row.provenance_json = {"severity": "Low", "title": "Rewritten"}
            attacker_prev = EvidenceLedger.seal_entry(row, attacker_prev)

        result = EvidenceLedger.verify_and_get(_fake_factory(rows), "run-1")
        assert result["integrity"] == "head_mismatch"
        assert result["verified"] is False
        assert result["anchor"]["status"] == "head_mismatch"
        assert result["anchor"]["anchored_head"] == prev
        assert result["anchor"]["computed_head"] == attacker_prev
