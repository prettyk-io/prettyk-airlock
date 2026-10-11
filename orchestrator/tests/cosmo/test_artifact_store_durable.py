# -*- coding: utf-8 -*-
"""COS-202: durable-зеркало артефактов (S3/MinIO) — recreate-инвариант, деградация, идемпотентность."""
from __future__ import annotations

import hashlib

import pytest

from orchestrator.cosmo.ledger.artifact_store import (
    ArtifactRef,
    ArtifactStore,
    build_s3_backend,
)


class FakeS3:
    """Duck-typed S3: put/exists/get + учёт записей."""

    def __init__(self, fail: bool = False):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.fail = fail

    def put(self, key: str, data: bytes) -> None:
        if self.fail:
            raise RuntimeError("s3 down")
        self.puts.append(key)
        self.objects[key] = data

    def exists(self, key: str) -> bool:
        return key in self.objects

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)


def test_store_mirrors_and_survives_local_loss(tmp_path):
    """Recreate-инвариант: байты читаются по ссылке после потери локального FS."""
    s3 = FakeS3()
    store = ArtifactStore(base_dir=tmp_path / "cosmo-evidence", s3=s3)
    payload = b'{"report": "durable"}'

    ref = store.store(payload, "run-1/batch-1/sast-report",
                      content_type="response", ext="json")

    assert ref.degraded_reason is None
    assert s3.objects[ref.path] == payload
    assert s3.objects[f"_refs/{ref.ref_id}"] == ref.path.encode("utf-8")

    # «Пересоздание контейнера»: свежий локальный FS, тот же durable backend.
    fresh = ArtifactStore(base_dir=tmp_path / "fresh", s3=s3)
    got = fresh.retrieve(ref)
    assert got == payload
    assert hashlib.sha256(got).hexdigest() == ref.sha256


def test_idempotent_same_content_reuses_path(tmp_path):
    """Повторный store того же содержимого переиспользует путь; объект не переиздаётся."""
    s3 = FakeS3()
    store = ArtifactStore(base_dir=tmp_path, s3=s3)
    payload = b"same-bytes"

    first = store.store(payload, "run-1/b1", content_type="response", ext="json")
    puts_after_first = len(s3.puts)
    second = store.store(payload, "run-2/b2", content_type="response", ext="json")

    assert second.ref_id == first.ref_id
    assert second.path == first.path           # идемпотентность по хешу содержимого
    assert len(s3.puts) == puts_after_first    # S3 не перезаписывался


def test_s3_failure_degrades_honestly_and_keeps_local(tmp_path):
    """Недоступное хранилище: захват не молчит (причина видима), локальная копия цела."""
    s3 = FakeS3(fail=True)
    store = ArtifactStore(base_dir=tmp_path, s3=s3)

    ref = store.store(b"bytes", "run-1/b1", content_type="log", ext="json")

    assert ref.degraded_reason and "mirror failed" in ref.degraded_reason
    assert (tmp_path / ref.path).read_bytes() == b"bytes"  # факт не потерян
    assert store.retrieve(ref) == b"bytes"                 # локальный read работает


def test_retrieve_hash_mismatch_raises(tmp_path):
    """Подмена объекта в durable-хранилище — честный ValueError, не молчаливая выдача."""
    s3 = FakeS3()
    store = ArtifactStore(base_dir=tmp_path / "a", s3=s3)
    ref = store.store(b"original", "run-1/b1", content_type="response", ext="json")

    s3.objects[ref.path] = b"tampered"
    fresh = ArtifactStore(base_dir=tmp_path / "b", s3=s3)
    with pytest.raises(ValueError, match="hash mismatch"):
        fresh.retrieve(ref)


def test_retrieve_by_ref_id_from_s3_index(tmp_path):
    """Чтение по ref_id после потери локального FS — через durable ref-индекс."""
    s3 = FakeS3()
    store = ArtifactStore(base_dir=tmp_path / "a", s3=s3)
    payload = b"indexed-content"
    ref = store.store(payload, "run-1/b1", content_type="response", ext="json")

    fresh = ArtifactStore(base_dir=tmp_path / "b", s3=s3)
    assert fresh.retrieve_by_ref_id(ref.ref_id) == payload
    assert fresh.retrieve_by_ref_id("0000000000000000") is None


def test_no_s3_backend_is_local_only(tmp_path, monkeypatch):
    """S3 не сконфигурирован — прежнее локальное поведение, деградации нет."""
    monkeypatch.delenv("PK_MINIO_URL", raising=False)
    assert build_s3_backend(tmp_path) is None

    store = ArtifactStore(base_dir=tmp_path, s3=None)
    ref = store.store(b"local-only", "run-1/b1", content_type="log", ext="json")
    assert ref.degraded_reason is None
    assert store.retrieve(ref) == b"local-only"
