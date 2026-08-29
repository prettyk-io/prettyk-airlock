# -*- coding: utf-8 -*-
"""COS-073: MinIO Buffer Layer (Zero-Pressure Sink).

Воркеры после SAST-сканирования не ждут очередь публикации — заливают
артефакт в ArtifactStore и публикуют событие в Valkey Stream `sonar.ingest`.

MinIOBufferSink:
  - save_report(run_id, report_data, report_type) → ArtifactRef
  - get_report_stream(s3_uri) → bytes (потоковое чтение)
  - SHA-256 хеширование + s3_uri + Valkey Stream event
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from orchestrator.cosmo.ledger.artifact_store import ArtifactRef, ArtifactStore

logger = logging.getLogger("cosmoport.minio_buffer")


class MinIOBufferSink:
    """Буферный слой: артефакт → ArtifactStore → Valkey Stream.

    Zero-pressure: воркер вызывает save_report() и продолжает работу.
    Публикация в Valkey — best-effort (не блокирует жизненный цикл сканирования).
    """

    def __init__(
        self,
        store: ArtifactStore | None = None,
        bucket: str = "cosmo-evidence",
        valkey_url: str | None = None,
    ) -> None:
        self._store = store or ArtifactStore(base_dir=Path(bucket))
        self._bucket = bucket
        self._valkey_url = valkey_url
        self._valkey: Any = None

    # ── Public API ──

    def save_report(
        self,
        run_id: str,
        report_data: dict[str, Any],
        report_type: str = "sarif",
    ) -> ArtifactRef:
        """Сохранить отчёт в ArtifactStore и опубликовать событие в Valkey Stream.

        Алгоритм:
          1. Сериализовать report_data → bytes.
          2. SHA-256 хеш.
          3. Сохранить по пути runs/{run_id}/report.{ext}.
          4. Опубликовать событие в Valkey Stream sonar.ingest.

        Returns: ArtifactRef с s3_uri, sha256, размером.
        """
        ext = f"{report_type}.json" if report_type != "sarif" else f"{report_type}.json"
        content = json.dumps(report_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        sha256 = hashlib.sha256(content).hexdigest()

        s3_key = f"runs/{run_id}/report.{ext}"

        # Write directly to deterministic path under store base
        target_dir = Path(self._store._base) / "runs" / run_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"report.{ext}"
        target_file.write_bytes(content)

        ref = ArtifactRef(
            ref_id=sha256[:16],
            path=s3_key,
            content_type=report_type,
            size_bytes=len(content),
            sha256=sha256,
            provenance=f"{run_id}/sast",
        )

        self._publish_ingest_event(run_id, sha256, s3_key)
        logger.info(
            "Report saved: run=%s, sha256=%s, uri=s3://%s/%s, size=%d",
            run_id, sha256[:12], self._bucket, s3_key, ref.size_bytes,
        )
        return ref

    def get_report_stream(self, s3_uri: str) -> bytes:
        """Потоковое чтение отчёта из ArtifactStore по s3_uri.

        Args:
            s3_uri: s3://cosmo-evidence/runs/{run_id}/report.sarif

        Returns: bytes — содержимое отчёта.
        """
        path = self._parse_s3_uri(s3_uri)
        full_path = Path(self._store._base) / path
        if full_path.exists() and full_path.is_file():
            return full_path.read_bytes()
        raise FileNotFoundError(f"Report not found for s3_uri: {s3_uri}")

    # ── Internal: Valkey Stream ──

    def _publish_ingest_event(
        self, run_id: str, sha256: str, s3_key: str,
    ) -> None:
        """Публикует событие report_uploaded в Valkey Stream sonar.ingest."""
        event = {
            "event": "report_uploaded",
            "run_id": run_id,
            "s3_uri": f"s3://{self._bucket}/{s3_key}",
            "sha256": sha256,
            "timestamp": time.time(),
        }
        try:
            self._publish_to_stream("sonar.ingest", event)
        except Exception as exc:
            logger.warning(
                "Valkey publish failed for %s (best-effort): %s", run_id, exc,
            )

    def _publish_to_stream(self, stream: str, event: dict[str, Any]) -> None:
        """Публикация в Valkey Stream (XADD)."""
        v = self._get_valkey()
        if v is None:
            return
        payload = json.dumps(event, ensure_ascii=False, default=str)
        try:
            v.xadd(stream, {"data": payload}, maxlen=10000, approximate=True)
        except Exception as exc:
            logger.warning("Valkey XADD failed for stream %s: %s", stream, exc)

    def _get_valkey(self) -> Any:
        """Ленивый singleton Valkey-клиент."""
        if self._valkey is not None:
            return self._valkey

        import os
        url = self._valkey_url or os.getenv("COSMO_VALKEY_URL", "").strip()
        if not url:
            return None

        try:
            import valkey
            self._valkey = valkey.Valkey.from_url(url)
            self._valkey.ping()
            logger.info("MinIOBufferSink: Valkey connected to stream sonar.ingest")
            return self._valkey
        except Exception as exc:
            logger.warning("Valkey unavailable for buffer sink: %s", exc)
            self._valkey = None
        return None

    # ── Internal: URI parsing ──

    @staticmethod
    def _parse_s3_uri(s3_uri: str) -> str:
        """s3://bucket/key → key."""
        if s3_uri.startswith("s3://"):
            parts = s3_uri[5:].split("/", 1)
            return parts[1] if len(parts) > 1 else ""
        return s3_uri