"""
COS-005: Evidence Artifact Store.

Сохранение артефактов (скриншоты, RAW request/response, логи)
с иерархической структурой: {run_id}/{batch_id}/{job_id}/{step_id}/{type}_{timestamp}.{ext}
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class ArtifactRef:
    """Ссылка на сохранённый артефакт."""
    ref_id: str
    path: str
    content_type: str
    size_bytes: int
    sha256: str
    provenance: str  # run_id, batch_id, step_id


class ArtifactStore:
    """Сохранение и извлечение артефактов evidence."""

    def __init__(self, base_dir: str | Path = "evidence_artifacts"):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        content: bytes,
        provenance: str,  # "run_id/batch_id/step_id"
        content_type: Literal["screenshot", "request", "response", "log"] = "log",
        ext: str = "json",
    ) -> ArtifactRef:
        """Сохраняет артефакт и возвращает ссылку."""
        sha = hashlib.sha256(content).hexdigest()
        ts = str(int(time.time() * 1000))

        rel_dir = Path(provenance.replace("/", os.sep))
        filename = f"{content_type}_{ts}.{ext}"
        full_dir = self._base / rel_dir
        full_dir.mkdir(parents=True, exist_ok=True)

        filepath = full_dir / filename
        filepath.write_bytes(content)

        return ArtifactRef(
            ref_id=sha[:16],
            path=str(filepath.relative_to(self._base)),
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha,
            provenance=provenance,
        )

    def retrieve(self, ref: ArtifactRef) -> bytes:
        """Извлекает артефакт по ссылке."""
        full_path = self._base / ref.path
        if not full_path.exists():
            raise FileNotFoundError(f"Artifact not found: {ref.path}")
        return full_path.read_bytes()

    def retrieve_by_ref_id(self, ref_id: str) -> bytes | None:
        """Поиск артефакта по ref_id (первые 16 символов SHA-256)."""
        for root, _, files in os.walk(self._base):
            for f in files:
                fpath = Path(root) / f
                content = fpath.read_bytes()
                sha = hashlib.sha256(content).hexdigest()
                if sha[:16] == ref_id:
                    return content
        return None

    def list_artifacts(self, provenance: str) -> list[ArtifactRef]:
        """Список артефактов для заданного provenance (run_id/...)."""
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
        """Удаляет артефакты для заданного provenance. Возвращает число удалённых."""
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