# -*- coding: utf-8 -*-
"""COS-005 + COS-202: Evidence Artifact Store (local FS + durable S3/MinIO mirror).

Хранение артефактов (скриншоты, RAW request/response, логи, отчёты) с
иерархической структурой: {run_id}/{batch_id}/{job_id}/{step_id}/{type}_{ts}.{ext}

COS-202: байты дублируются в durable-хранилище контура (MinIO/S3, канон
``PK_MINIO_URL``/``PK_MINIO_ACCESS_KEY``/``PK_MINIO_SECRET_KEY``) — пересоздание
контейнера API не теряет артефакты. Контракты ``artifact://…``, пути и хеши в
ledger не меняются: S3-зеркало прозрачно (read-путь падает на S3, если локальной
копии нет). Честная деградация: S3 недоступен → захват не молчит
(``ArtifactRef.degraded_reason`` + лог), локальная копия остаётся.
Идемпотентность: объект и ref-индекс ``_refs/{ref_id}`` пишутся один раз,
повторный store того же содержимого переиспользует существующий путь.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger("cosmo.artifact_store")

#: COS-202: env-канон платформенного S3/MinIO (как startup.py/backup).
S3_URL_ENV = "PK_MINIO_URL"
S3_ACCESS_KEY_ENV = "PK_MINIO_ACCESS_KEY"
S3_SECRET_KEY_ENV = "PK_MINIO_SECRET_KEY"

#: Бакеты контура; первый — primary для базы store, остальные — кандидаты чтения.
KNOWN_BUCKETS: tuple[str, ...] = ("cosmo-evidence", "cosmo-artifacts")

_BUCKET_FOR_BASE: dict[str, str] = {
    "cosmo-evidence": "cosmo-evidence",
    "cosmo-artifacts": "cosmo-artifacts",
}


@dataclass
class ArtifactRef:
    """Ссылка на сохранённый артефакт."""
    ref_id: str
    path: str
    content_type: str
    size_bytes: int
    sha256: str
    provenance: str  # run_id, batch_id, step_id
    #: COS-202: причина деградации durable-зеркала (None — всё ок/зеркало выключено).
    degraded_reason: str | None = field(default=None)


class _S3Backend:
    """S3/MinIO backend (SigV4, stdlib): put/exists/get по bucket-кандидатам."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        buckets: list[str],
        timeout: float = 10.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._host = urllib.parse.urlsplit(self._endpoint).netloc
        self._access_key = access_key
        self._secret_key = secret_key
        self._buckets = [b for b in bucket_list(buckets) if b]
        self._timeout = timeout

    def _request(
        self, method: str, bucket: str, key: str, content: bytes | None = None
    ) -> tuple[int | None, bytes]:
        from orchestrator.cosmo.ledger.evidence_anchor import s3_sigv4_headers

        path = f"/{bucket}/{urllib.parse.quote(key)}"
        headers = s3_sigv4_headers(
            method, self._host, path, None,
            self._access_key, self._secret_key, content=content,
        )
        request = urllib.request.Request(
            self._endpoint + path, method=method, headers=headers, data=content)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = b"" if method == "HEAD" else response.read()
                return response.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, b""
        # URLError (conn refused/timeout) пробрасывается — это деградация.

    def put(self, key: str, data: bytes) -> None:
        status, _ = self._request("PUT", self._buckets[0], key, data)
        if status not in (200, 201):
            raise RuntimeError(f"S3 PUT {self._buckets[0]}/{key}: HTTP {status}")

    def exists(self, key: str) -> bool:
        status, _ = self._request("HEAD", self._buckets[0], key)
        return status == 200

    def get(self, key: str) -> bytes | None:
        for bucket in self._buckets:
            status, body = self._request("GET", bucket, key)
            if status == 200:
                return body
            if status == 404:
                continue
            raise RuntimeError(f"S3 GET {bucket}/{key}: HTTP {status}")
        return None


def bucket_list(primary: list[str] | tuple[str, ...]) -> list[str]:
    """Primary + известные бакеты (dedup, порядок сохранён)."""
    ordered: list[str] = []
    for name in list(primary) + list(KNOWN_BUCKETS):
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def build_s3_backend(base_dir: str | Path) -> _S3Backend | None:
    """Собрать S3-backend из env-канона; None — S3 не сконфигурирован."""
    endpoint = os.getenv(S3_URL_ENV, "").strip().rstrip("/")
    if not endpoint:
        return None
    access_key = os.getenv(S3_ACCESS_KEY_ENV, "cosmo")
    secret_key = os.getenv(S3_SECRET_KEY_ENV, "cosmo-minio-dev")
    primary = _BUCKET_FOR_BASE.get(Path(base_dir).name, "cosmo-evidence")
    return _S3Backend(endpoint, access_key, secret_key, [primary])


class ArtifactStore:
    """Сохранение и извлечение артефактов evidence (local FS + опц. S3-зеркало)."""

    def __init__(
        self,
        base_dir: str | Path = "evidence_artifacts",
        *,
        s3: object | None = None,
    ) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        #: COS-202: backend-зеркало; None — durable выключен/не сконфигурирован.
        self._s3 = s3 if s3 is not None else build_s3_backend(self._base)

    # ── COS-202: durable-зеркало ──────────────────────────────────────────

    def _mirror(self, ref_id: str, rel_path: str, content: bytes) -> tuple[str, str | None]:
        """Зеркалировать в S3; вернуть (эффективный путь, degraded_reason).

        Идемпотентно: повтор того же содержимого (ref_id = sha[:16]) переиспользует
        ранее записанный путь; объект и индекс пишутся один раз.
        """
        if self._s3 is None:
            return rel_path, None
        try:
            indexed = self._s3.get(f"_refs/{ref_id}")
            if indexed:
                return indexed.decode("utf-8"), None
            if not self._s3.exists(rel_path):
                self._s3.put(rel_path, content)
            self._s3.put(f"_refs/{ref_id}", rel_path.encode("utf-8"))
            return rel_path, None
        except Exception as exc:  # noqa: BLE001 — честная деградация, не потеря факта
            logger.error("COS-202: artifact mirror failed (%s): %s", rel_path, exc)
            return rel_path, f"durable mirror failed: {exc}"

    def store(
        self,
        content: bytes,
        provenance: str,  # "run_id/batch_id/step_id"
        content_type: Literal["screenshot", "request", "response", "log"] = "log",
        ext: str = "json",
    ) -> ArtifactRef:
        """Сохраняет артефакт и возвращает ссылку (local + durable S3)."""
        sha = hashlib.sha256(content).hexdigest()
        ts = str(int(time.time() * 1000))

        rel_dir = Path(provenance.replace("/", os.sep))
        filename = f"{content_type}_{ts}.{ext}"
        rel_path = str(rel_dir / filename).replace(os.sep, "/")

        effective_path, degraded_reason = self._mirror(sha[:16], rel_path, content)

        full_path = self._base / effective_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)

        return ArtifactRef(
            ref_id=sha[:16],
            path=effective_path,
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha,
            provenance=provenance,
            degraded_reason=degraded_reason,
        )

    def retrieve(self, ref: ArtifactRef) -> bytes:
        """Извлекает артефакт: локальная копия → durable S3 (после recreate)."""
        full_path = self._base / ref.path
        if full_path.exists():
            return full_path.read_bytes()
        if self._s3 is not None:
            data = self._s3.get(ref.path)
            if data is not None:
                sha = hashlib.sha256(data).hexdigest()
                if ref.sha256 and sha != ref.sha256:
                    raise ValueError(
                        f"Artifact hash mismatch for {ref.path}: "
                        f"{sha[:12]}… != {ref.sha256[:12]}…")
                return data
        raise FileNotFoundError(f"Artifact not found: {ref.path}")

    def retrieve_by_ref_id(self, ref_id: str) -> bytes | None:
        """Поиск артефакта по ref_id: локальный скан → ref-индекс в S3."""
        for root, _, files in os.walk(self._base):
            for f in files:
                fpath = Path(root) / f
                content = fpath.read_bytes()
                sha = hashlib.sha256(content).hexdigest()
                if sha[:16] == ref_id:
                    return content
        if self._s3 is not None:
            indexed = self._s3.get(f"_refs/{ref_id}")
            if indexed:
                data = self._s3.get(indexed.decode("utf-8"))
                if data is not None and hashlib.sha256(data).hexdigest()[:16] == ref_id:
                    return data
        return None

    def list_artifacts(self, provenance: str) -> list[ArtifactRef]:
        """Список артефактов для заданного provenance (локальный кэш)."""
        refs: list[ArtifactRef] = []
        rel_dir = Path(provenance.replace("/", os.sep))
        full_dir = self._base / rel_dir
        if not full_dir.exists():
            return refs
        for fpath in full_dir.iterdir():
            if fpath.is_file():
                content = fpath.read_bytes()
                sha = hashlib.sha256(content).hexdigest()
                parts = fpath.stem.split("_", 1)
                ct = parts[0] if parts else "log"
                refs.append(ArtifactRef(
                    ref_id=sha[:16],
                    path=str(fpath.relative_to(self._base)),
                    content_type=ct,
                    size_bytes=fpath.stat().st_size,
                    sha256=sha,
                    provenance=provenance,
                ))
        return refs

    def cleanup(self, provenance: str) -> int:
        """Удаляет локальные артефакты (S3-объекты чистит lifecycle бакета)."""
        rel_dir = Path(provenance.replace("/", os.sep))
        full_dir = self._base / rel_dir
        if not full_dir.exists():
            return 0
        count = 0
        for fpath in full_dir.iterdir():
            if fpath.is_file():
                fpath.unlink()
                count += 1
        try:
            full_dir.rmdir()
        except OSError:
            pass
        return count
