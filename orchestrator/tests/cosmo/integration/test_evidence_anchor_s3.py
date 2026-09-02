# -*- coding: utf-8 -*-
"""COS-093: S3/MinIO backend evidence-якоря — e2e против живого object-store.

Тот же контракт publish/verify, что и file-бэкенд (COS-087): цепочка
пишется через API, голова публикуется в MinIO (JSONL-объект на run,
версионирование бакета = append-only замена). Негативы:

  - подмена якорного объекта в MinIO (атакующий переписал внешний
    доказательство-объект на чужую голову) → head_mismatch;
  - object-store недоступен на чтении → честный unknown_anchor
    (internal вердикт не притворяется внешне подтверждённым).

Запуск: тестовый PG :5433 + живой cosmo-minio (host-канон :9100).
MinIO недоступен → честный skip (не падение).
"""
from __future__ import annotations

import os
import re
import urllib.parse
import uuid

import httpx
import pytest
import pytest_asyncio

from orchestrator.cosmo.ledger import evidence_anchor

from test_evidence_tamper_detection import (
    _get_evidence, _resign_suffix, _setup_run_with_chain,
)

pytestmark = pytest.mark.asyncio

MINIO_URL = os.getenv("PK_MINIO_URL", "http://127.0.0.1:9100").rstrip("/")
MINIO_ACCESS = os.getenv("PK_MINIO_ACCESS_KEY", "cosmo")
MINIO_SECRET = os.getenv("PK_MINIO_SECRET_KEY", "cosmo-minio-dev")


class MinIOAdmin:
    """Минимальный S3-клиент для фикстуры: bucket create/versioning/
    raw PUT/GET/versions cleanup (вне anchor-контракта — тестовый tool).
    Все запросы подписываются SigV4 (MinIO Basic auth не принимает)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(10.0),
        )
        self.access = MINIO_ACCESS
        self.secret = MINIO_SECRET

    def _req(self, method: str, path: str,
             params: dict[str, str] | None = None,
             content: bytes | None = None) -> httpx.Response:
        # ВАЖНО: urllib.parse.urlsplit, НЕ httpx.URL — httpx.URL(...).netloc
        # возвращает bytes, и b'...' попадает в canonical headers SigV4
        # → детерминированный SignatureDoesNotMatch.
        host = urllib.parse.urlsplit(self.base_url).netloc
        sig = evidence_anchor.s3_sigv4_headers(
            method, host, path, params, self.access, self.secret,
            content=content,
        )
        return self.client.request(
            method, path, params=params or None, content=content, headers=sig,
        )

    def reachable(self) -> bool:
        try:
            self._req("HEAD", "/minio")
        except httpx.HTTPError:
            return False
        return True  # любой статус — сервер жив (даже 403/404)

    def ensure_bucket(self, bucket: str) -> None:
        r = self._req("HEAD", f"/{bucket}")
        if r.status_code == 200:
            return
        r = self._req("PUT", f"/{bucket}")
        assert r.status_code in (200, 201, 409), r.text

    def enable_versioning(self, bucket: str) -> None:
        body = (
            '<VersioningConfiguration '
            'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            "<Status>Enabled</Status></VersioningConfiguration>"
        )
        r = self._req("PUT", f"/{bucket}",
                      params={"versioning": ""}, content=body.encode())
        assert r.status_code in (200, 201), r.text

    def put_object(self, bucket: str, key: str, body: str) -> None:
        r = self._req("PUT", f"/{bucket}/{key}", content=body.encode())
        assert r.status_code in (200, 201), r.text

    def cleanup_bucket(self, bucket: str) -> None:
        """Удалить все версии объектов + сам бакет (best-effort)."""
        try:
            r = self._req("GET", f"/{bucket}", params={"versions": ""})
            if r.status_code == 200:
                keys = re.findall(r"<Key>([^<]+)</Key>", r.text)
                vids = re.findall(r"<VersionId>([^<]+)</VersionId>", r.text)
                for key, vid in zip(keys, vids):
                    self._req("DELETE", f"/{bucket}/{key}",
                              params={"versionId": vid})
            self._req("DELETE", f"/{bucket}")
        except httpx.HTTPError:
            pass


@pytest_asyncio.fixture
async def minio_anchor(monkeypatch):
    """Живой MinIO + выделенный версионированный бакет на сессию теста.

    backend=s3 на время теста (monkeypatch восстановит file-режим).
    """
    bucket = f"cosmo-evidence-anchor-test-{os.getpid()}"
    admin = MinIOAdmin(MINIO_URL)
    if not admin.reachable():
        pytest.skip(f"live MinIO not available at {MINIO_URL}")

    admin.ensure_bucket(bucket)
    admin.enable_versioning(bucket)

    monkeypatch.setenv(evidence_anchor.BACKEND_ENV, "s3")
    monkeypatch.setenv("PK_MINIO_URL", MINIO_URL)
    monkeypatch.setenv(evidence_anchor.S3_BUCKET_ENV, bucket)
    monkeypatch.setattr(evidence_anchor, "_S3_SINK_CACHE", None)

    yield admin, bucket

    monkeypatch.delenv(evidence_anchor.BACKEND_ENV, raising=False)
    monkeypatch.delenv(evidence_anchor.S3_BUCKET_ENV, raising=False)
    monkeypatch.setattr(evidence_anchor, "_S3_SINK_CACHE", None)
    admin.cleanup_bucket(bucket)


def _run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def test_s3_anchor_e2e_publish_and_verify(steel_thread, minio_anchor):
    """Сквозной: цепочка через API → голова в MinIO → verify anchor ok,
    объект — накопленный JSONL (строка на каждую публикацию)."""
    h = steel_thread
    admin, bucket = minio_anchor
    run_id = _run_id("s3an-ok")
    await _setup_run_with_chain(h, run_id, n_entries=3)

    ev = await _get_evidence(h, run_id)
    assert ev["integrity"] == "ok"
    assert ev["verified"] is True
    assert ev["anchor"]["enabled"] is True
    assert ev["anchor"]["status"] == "ok"
    assert ev["anchor"]["anchored_head"] == ev["anchor"]["computed_head"]
    assert ev["anchor"]["anchored_head"] != "0" * 64

    key = f"evidence-anchor/{run_id}.jsonl"
    r = admin._req("GET", f"/{bucket}/{key}")
    assert r.status_code == 200, r.text
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lines) == 3  # публикация на каждую запечатанную строку
    import json
    rec = json.loads(lines[-1])
    assert rec["chain_hash"] == ev["anchor"]["anchored_head"]
    assert rec["run_id"] == run_id


async def test_s3_anchor_tamper_object_detected(steel_thread, minio_anchor):
    """ФЛАГМАН COS-093: атакующий ПОДМЕНЯЕТ якорный объект в MinIO
    (кладёт чужую голову). Внешнее доказательство расходится с фактической
    головой PG → head_mismatch, verified=False."""
    h = steel_thread
    admin, bucket = minio_anchor
    run_id = _run_id("s3an-tamper")
    await _setup_run_with_chain(h, run_id, n_entries=3)

    ev = await _get_evidence(h, run_id)
    assert ev["anchor"]["status"] == "ok"
    real_head = ev["anchor"]["anchored_head"]

    # атака: переписать внешний якорь на фальшивую голову
    forged = (
        '{"chain_hash": "' + "f" * 64 + '", "entry_id": "forged", '
        '"run_id": "' + run_id + '", "ts": "2026-01-01T00:00:00+00:00"}\n'
    )
    admin.put_object(bucket, f"evidence-anchor/{run_id}.jsonl", forged)

    ev2 = await _get_evidence(h, run_id)
    assert ev2["integrity"] == "head_mismatch"
    assert ev2["verified"] is False
    assert ev2["head_mismatch"] is True
    assert ev2["anchor"]["status"] == "head_mismatch"
    assert ev2["anchor"]["anchored_head"] == "f" * 64
    assert ev2["anchor"]["computed_head"] == real_head


async def test_s3_anchor_head_loss_detected(steel_thread, minio_anchor):
    """Голова удалена из PG, якорь в MinIO цел → head_mismatch."""
    h = steel_thread
    admin, bucket = minio_anchor
    run_id = _run_id("s3an-loss")
    entry_ids = await _setup_run_with_chain(h, run_id, n_entries=3)

    ev = await _get_evidence(h, run_id)
    assert ev["anchor"]["status"] == "ok"

    await h.sync_exec(
        "DELETE FROM evidence_ledger WHERE id = :eid", eid=entry_ids[-1],
    )

    ev2 = await _get_evidence(h, run_id)
    assert ev2["anchor"]["status"] == "head_mismatch"
    assert ev2["head_mismatch"] is True
    assert ev2["verified"] is False


async def test_s3_anchor_suffix_resign_detected(steel_thread, minio_anchor):
    """COS-087 флагман поверх S3-бэкенда: атакующий пере-подписывает весь
    суффикс цепочки в PG, якорный объект в MinIO хранит СТАРУЮ голову →
    head_mismatch, internal verify при этом чист."""
    h = steel_thread
    admin, bucket = minio_anchor
    run_id = _run_id("s3an-resign")
    await _setup_run_with_chain(h, run_id, n_entries=3)

    ev = await _get_evidence(h, run_id)
    assert ev["integrity"] == "ok"
    assert ev["anchor"]["status"] == "ok"
    old_head = ev["anchor"]["anchored_head"]

    await _resign_suffix(run_id)

    ev2 = await _get_evidence(h, run_id)
    assert ev2["integrity"] == "head_mismatch"
    assert ev2["verified"] is False
    assert ev2["head_mismatch"] is True
    assert ev2["tampered_entries"] == []  # internal чист — расхождение внешнее
    assert ev2["broken_links"] == []
    assert ev2["anchor"]["status"] == "head_mismatch"
    assert ev2["anchor"]["anchored_head"] == old_head
    assert ev2["anchor"]["computed_head"] != old_head


async def test_s3_anchor_unreachable_is_honest(steel_thread, monkeypatch):
    """Object-store недоступен на чтении (мёртвый endpoint) → честный
    unknown_anchor: internal verify чист и НЕ притворяется внешне
    подтверждённым; head_mismatch НЕ выдумывается.

    Запись ведётся через file-бэкенд (steel_thread env), мёртвый S3
    включается только на read-стороне — недоступность sink'а на чтении
    это unknown_anchor, а не фейл.
    """
    h = steel_thread
    run_id = _run_id("s3an-dead")
    await _setup_run_with_chain(h, run_id, n_entries=2)

    monkeypatch.setenv(evidence_anchor.BACKEND_ENV, "s3")
    monkeypatch.setenv("PK_MINIO_URL", "http://127.0.0.1:59999")
    monkeypatch.setenv(evidence_anchor.S3_BUCKET_ENV, "cosmo-evidence")
    monkeypatch.setattr(evidence_anchor, "_S3_SINK_CACHE", None)

    ev = await _get_evidence(h, run_id)
    assert ev["integrity"] == "ok"       # internal чист
    assert ev["verified"] is True        # verified — internal вердикт
    assert ev["anchor"]["enabled"] is True
    assert ev["anchor"]["status"] == "unknown_anchor"
    assert ev["head_mismatch"] is False
