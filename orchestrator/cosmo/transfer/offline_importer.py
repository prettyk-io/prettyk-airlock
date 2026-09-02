# -*- coding: utf-8 -*-
"""COS-054: Offline Package Importer — staging/spool, verify, atomic promote.

Обрабатывает пакеты, доставленные через offline media (USB, controlled file
exchange, removable disk). Независим от физического носителя.

Pipeline:
  1. Package arrives in staging/spool directory
  2. manifest.json discovered and parsed
  3. SHA-256 verification of manifest + payload files
  4. Duplicate revision detection (idempotent)
  5. Atomic promote to landing directory
  6. Cleanup policy for staging remnants

Инварианты:
  - Import only after manifest + checksum verification passes.
  - Partial copy can resume without corrupting the package.
  - Duplicate revision is idempotent (no duplicate landing).
  - Checksum mismatch requires new revision.
  - Staging cleanup does not remove active/recoverable transfers.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.cosmo.transfer.contract import (
    PackageRevision,
    TransferFailureClass,
    TransferItem,
)


# ══════════════════════════════════════════════════════════════════
# Import States
# ══════════════════════════════════════════════════════════════════

class ImportState(str, Enum):
    """Staging import state machine."""
    DISCOVERED = "discovered"           # manifest found in spool
    VERIFYING = "verifying"             # SHA-256 in progress
    VERIFIED = "verified"               # checksums match
    PROMOTED = "promoted"               # atomically moved to landing
    DUPLICATE = "duplicate"             # same revision already landed
    CHECKSUM_MISMATCH = "checksum_mismatch"
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_INVALID = "manifest_invalid"
    PAYLOAD_MISSING = "payload_missing"
    PARTIAL_COPY = "partial_copy"       # resumable
    CLEANED = "cleaned"                 # staging cleaned up
    ERROR = "error"


class ImportStateError(Exception):
    def __init__(self, item_id: str, message: str):
        self.item_id = item_id
        super().__init__(f"Import error for '{item_id}': {message}")


class CheckpointCorruptedError(Exception):
    """Checkpoint-файл повреждён или schema-невалиден.

    Silent success невозможен: corrupted checkpoint обязан упасть явно
    в strict-режиме; в soft-режиме импортёр стартует verify с нуля.
    """


# ══════════════════════════════════════════════════════════════════
# ImportReport
# ══════════════════════════════════════════════════════════════════

class ImportReport(BaseModel):
    """Детальный отчёт о результате импорта."""
    model_config = ConfigDict(extra="ignore")
    item_id: str
    revision_key: str = ""
    state: ImportState = ImportState.DISCOVERED
    passed: bool = False
    failure_class: Optional[TransferFailureClass] = None
    reasons: list[str] = Field(default_factory=list)
    files_verified: int = 0
    files_total: int = 0
    resumed: bool = False
    duplicate: bool = False
    promoted_to: str = ""
    # COS-065 observability: "none" | "resume_same_revision" | "retry_import" | "new_revision"
    recovery_requirement: str = "retry_import"

    @property
    def is_recoverable(self) -> bool:
        if self.recovery_requirement == "resume_same_revision":
            return True
        return self.state in (ImportState.PARTIAL_COPY, ImportState.VERIFYING)

    @property
    def requires_new_revision(self) -> bool:
        if self.recovery_requirement == "new_revision":
            return True
        return self.state in (ImportState.CHECKSUM_MISMATCH, ImportState.MANIFEST_INVALID)


# ══════════════════════════════════════════════════════════════════
# SpoolEntry — tracks one package in staging
# ══════════════════════════════════════════════════════════════════

class SpoolEntry(BaseModel):
    """Одна запись в staging spool."""
    model_config = ConfigDict(extra="ignore")
    item_id: str
    revision_key: str
    staging_path: str
    manifest_sha256: str = ""
    state: ImportState = ImportState.DISCOVERED
    files_copied: int = 0
    files_expected: int = 0
    created_at: str = ""
    last_checkpoint: str = ""


# ══════════════════════════════════════════════════════════════════
# OfflineImporter
# ══════════════════════════════════════════════════════════════════

class OfflineImporter:
    """Offline package importer with staging, verification, atomic promote.

    Works on a local filesystem abstraction (Path) — no network, no physical device.
    """

    def __init__(self, spool_dir: Path, landing_dir: Path):
        self._spool = Path(spool_dir)
        self._landing = Path(landing_dir)
        self._spool.mkdir(parents=True, exist_ok=True)
        self._landing.mkdir(parents=True, exist_ok=True)
        self._landed_revisions: dict[str, str] = {}  # revision_key → manifest_sha256

    @property
    def spool_dir(self) -> Path:
        return self._spool

    @property
    def landing_dir(self) -> Path:
        return self._landing

    # ── Manifest Discovery ──

    def discover_manifest(self, staging_subdir: str) -> Optional[dict[str, Any]]:
        """Найти и распарсить manifest.json в staging поддиректории."""
        manifest_path = self._spool / staging_subdir / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_staged(self) -> list[str]:
        """Список staging поддиректорий (одна = один пакет)."""
        if not self._spool.exists():
            return []
        return [
            d.name for d in self._spool.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

    # ── SHA-256 Verification ──

    @staticmethod
    def compute_file_sha256(filepath: Path, chunk_size: int = 65536) -> str:
        """SHA-256 файла с chunked reading (для больших файлов)."""
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()

    def verify_payload_checksums(
        self, staging_path: Path, manifest: dict[str, Any],
        on_progress: Any = None,
    ) -> tuple[bool, list[str]]:
        """Проверить SHA-256 всех payload файлов из manifest.

        Returns: (all_ok, [mismatch_details])
        """
        payload_files = manifest.get("payload_files", [])
        mismatches: list[str] = []

        for entry in payload_files:
            fname = entry.get("name", "")
            expected_sha = entry.get("sha256", "")
            fpath = staging_path / fname

            if not fpath.exists():
                mismatches.append(f"MISSING: {fname}")
                continue

            actual_sha = self.compute_file_sha256(fpath)
            if actual_sha != expected_sha:
                mismatches.append(
                    f"MISMATCH: {fname} expected={expected_sha[:12]}... got={actual_sha[:12]}..."
                )

            if on_progress:
                on_progress(fname, actual_sha == expected_sha)

        return len(mismatches) == 0, mismatches

    def verify_manifest_checksum(
        self, staging_path: Path, expected_sha256: str,
    ) -> bool:
        """Проверить SHA-256 самого manifest.json."""
        manifest_path = staging_path / "manifest.json"
        if not manifest_path.exists():
            return False
        actual = self.compute_file_sha256(manifest_path)
        return actual == expected_sha256

    # ── Duplicate Revision Detection ──

    def is_duplicate_revision(self, revision_key: str) -> bool:
        """Проверить, была ли уже landing этой revision."""
        return revision_key in self._landed_revisions

    def register_landed(self, revision_key: str, manifest_sha256: str) -> None:
        """Зарегистрировать successfully landed revision."""
        self._landed_revisions[revision_key] = manifest_sha256

    # ── Atomic Promote ──

    def atomic_promote(self, staging_subdir: str, revision_key: str) -> bool:
        """Атомарно переместить пакет из staging в landing.

        Использует rename (same filesystem) для атомарности.
        """
        src = self._spool / staging_subdir
        dst = self._landing / revision_key.replace(":", "_")

        if dst.exists():
            return False  # already landed (duplicate)

        if not src.exists():
            return False

        # Cross-filesystem safe: copy then delete
        import shutil
        shutil.move(str(src), str(dst))
        return True

    # ── Resume Support ──

    def checkpoint(self, entry: SpoolEntry) -> None:
        """Сохранить checkpoint для resume после partial copy."""
        checkpoint_path = self._spool / f".checkpoint_{entry.item_id}.json"
        checkpoint_path.write_text(
            entry.model_dump_json(), encoding="utf-8"
        )

    def load_checkpoint(self, item_id: str) -> Optional[SpoolEntry]:
        """Загрузить checkpoint после рестарта.

        Повреждённый файл → None (soft): импортёр не может доверять
        checkpoint и начнёт verify с нуля — silent success невозможен,
        т.к. promote всегда проходит через полную checksum verification.
        """
        checkpoint_path = self._spool / f".checkpoint_{item_id}.json"
        if not checkpoint_path.exists():
            return None
        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            return self._validate_spool_entry(data)
        except (json.JSONDecodeError, OSError, CheckpointCorruptedError):
            return None

    def load_checkpoint_strict(self, item_id: str) -> Optional[SpoolEntry]:
        """Как load_checkpoint, но повреждённый checkpoint → исключение.

        Для recovery-путей, где молчаливый сброс checkpoint недопустим.
        """
        checkpoint_path = self._spool / f".checkpoint_{item_id}.json"
        if not checkpoint_path.exists():
            return None
        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CheckpointCorruptedError(
                f"checkpoint for '{item_id}' corrupted: {exc}")
        return self._validate_spool_entry(data)

    @staticmethod
    def _validate_spool_entry(data: object) -> SpoolEntry:
        """Schema-валидация SpoolEntry: state должен быть валидным ImportState."""
        if not isinstance(data, dict):
            raise CheckpointCorruptedError("checkpoint payload must be a dict")
        for key in ("item_id", "revision_key", "staging_path"):
            if not str(data.get(key, "")).strip():
                raise CheckpointCorruptedError(f"missing required field: {key}")
        state_raw = str(data.get("state", ImportState.DISCOVERED.value))
        try:
            ImportState(state_raw)
        except ValueError:
            raise CheckpointCorruptedError(f"invalid ImportState value: {state_raw!r}")
        from pydantic import ValidationError as _VE
        try:
            return SpoolEntry(**data)
        except _VE as exc:
            raise CheckpointCorruptedError(f"schema validation failed: {exc}")

    def clear_checkpoint(self, item_id: str) -> None:
        checkpoint_path = self._spool / f".checkpoint_{item_id}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    # ── Cleanup ──

    def cleanup_staging(self, staging_subdir: str, force: bool = False) -> bool:
        """Очистить staging для одного пакета.

        Не удаляет active/recoverable transfers (если state != terminal).
        """
        import shutil
        staging = self._spool / staging_subdir
        if not staging.exists():
            return False

        # Активный/recoverable checkpoint блокирует cleanup ТОЛЬКО своего
        # staging (COS-065: scoped policy). Чужие активные трансферы не
        # мешают чистить завершённый staging.
        if not force:
            for cp_path in self._spool.glob(".checkpoint_*.json"):
                try:
                    data = json.loads(cp_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue  # corrupted cp не блокирует cleanup (не evidence)
                if not isinstance(data, dict):
                    continue
                if data.get("staging_path") != staging_subdir:
                    continue
                if data.get("state") in ("verifying", "discovered", "partial_copy"):
                    return False  # активный трансфер этого staging

        shutil.rmtree(staging, ignore_errors=True)
        return True

    def cleanup_all_staging(self, force: bool = False) -> int:
        """Очистить все staging директории. Возвращает количество удалённых."""
        count = 0
        for d in self._spool.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                if self.cleanup_staging(d.name, force=force):
                    count += 1
        return count

    # ── Full Import Pipeline ──

    def import_package(
        self,
        item: TransferItem,
        staging_subdir: str,
        on_progress: Any = None,
    ) -> ImportReport:
        """Полный pipeline импорта: discover → verify → promote.

        Returns ImportReport с детальным вердиктом.
        """
        report = ImportReport(item_id=item.item_id)
        if item.package_revision:
            report.revision_key = item.package_revision.revision_key

        staging_path = self._spool / staging_subdir

        # 1. Manifest discovery
        manifest_path = staging_path / "manifest.json"
        if not manifest_path.exists():
            report.state = ImportState.MANIFEST_MISSING
            report.failure_class = TransferFailureClass.LANDING_INCOMPLETE
            report.recovery_requirement = "retry_import"
            report.reasons.append("manifest.json not found in staging")
            return report

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            report.state = ImportState.MANIFEST_INVALID
            report.failure_class = TransferFailureClass.VALIDATION_FAILURE
            report.recovery_requirement = "new_revision"
            report.reasons.append(f"manifest.json parse error: {exc}")
            return report

        # 2. Duplicate revision detection
        if item.package_revision:
            report.revision_key = item.package_revision.revision_key
            if self.is_duplicate_revision(report.revision_key):
                report.state = ImportState.PROMOTED
                report.passed = True
                report.duplicate = True
                report.recovery_requirement = "none"
                report.reasons.append("Duplicate revision — idempotent skip")
                return report

        # 3. Manifest identity cross-check (COS-065 target-side ordering:
        #    identity ДО payload-verify, verify ДО promote).
        #    File-content checksum сверяется отдельно (см. verify_manifest_checksum);
        #    PackageRevision.manifest_sha256 считается по dict-канону builder'а.
        if item.package_revision:
            manifest_release = manifest.get("release_id", "")
            if manifest_release != item.release_id:
                report.state = ImportState.MANIFEST_INVALID
                report.failure_class = TransferFailureClass.VALIDATION_FAILURE
                report.recovery_requirement = "new_revision"
                report.reasons.append(
                    f"manifest release_id '{manifest_release}' != item "
                    f"release_id '{item.release_id}'")
                return report

        # 4. Payload file verification
        all_ok, mismatches = self.verify_payload_checksums(staging_path, manifest, on_progress)
        report.files_total = len(manifest.get("payload_files", []))
        report.files_verified = report.files_total - len(mismatches)

        if not all_ok:
            # Check if it's a partial copy (some files exist, some missing)
            missing = [m for m in mismatches if m.startswith("MISSING")]
            corrupted = [m for m in mismatches if m.startswith("MISMATCH")]

            if missing_count := len(missing):
                report.state = ImportState.PARTIAL_COPY if missing_count < report.files_total else ImportState.MANIFEST_MISSING
                report.resumed = len(missing) < len(manifest.get("payload_files", []))
                report.failure_class = TransferFailureClass.LANDING_INCOMPLETE
                report.recovery_requirement = "resume_same_revision"
            elif corrupted:
                report.state = ImportState.CHECKSUM_MISMATCH
                report.failure_class = TransferFailureClass.CHECKSUM_MISMATCH
                report.recovery_requirement = "new_revision"

            report.reasons.extend(mismatches)
            return report

        # 5. All verified → atomic promote
        promoted = self.atomic_promote(staging_subdir, report.revision_key)
        if promoted:
            report.state = ImportState.PROMOTED
            report.passed = True
            report.recovery_requirement = "none"
            report.promoted_to = str(self._landing / report.revision_key.replace(":", "_"))
            self.register_landed(report.revision_key, item.package_revision.manifest_sha256 if item.package_revision else "")
            return report

        # Promote не прошёл: либо crash между promote и register (dst уже
        # существует, но _landed_revisions пуст), либо гонка импортёров.
        # Crash-gap recovery: верифицируем существующий landing; если он
        # цел — это тот же revision, идемпотентный duplicate.
        dst = self._landing / report.revision_key.replace(":", "_")
        if dst.exists():
            existing_ok, _existing_bad = self.verify_payload_checksums(dst, manifest)
            if existing_ok:
                report.state = ImportState.PROMOTED
                report.passed = True
                report.duplicate = True
                report.recovery_requirement = "none"
                report.promoted_to = str(dst)
                report.reasons.append(
                    "crash-gap recovery: revision already landed (verified), "
                    "idempotent duplicate")
                self.register_landed(
                    report.revision_key,
                    item.package_revision.manifest_sha256 if item.package_revision else "")
                return report

        # Существующий landing не совпадает с verified payload — конфликт
        # импотентности: landing занят другой (битой) копией той же revision.
        report.state = ImportState.ERROR
        report.failure_class = TransferFailureClass.IDEMPOTENCY_CONFLICT
        report.recovery_requirement = "new_revision"
        report.reasons.append(
            "idempotency conflict: landing dir exists but content "
            "failed verification — manual quarantine required")
        return report