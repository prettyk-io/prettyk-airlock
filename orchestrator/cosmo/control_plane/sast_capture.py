# -*- coding: utf-8 -*-
"""SAST-STEP-1: durable-захват отчёта source-SAST из логов CI-шага.

Зеркало COS-164 (``artifact_capture``): когда batch с ``sast``-кирпичом
завершается, его РЕАЛЬНЫЕ логи прогона сканируются на канонический маркер
(``domain.sast_report``); отчёт сохраняется durable (ArtifactStore,
``cosmo-evidence``) и якорится ``EvidenceLedgerEntry`` (type=``raw_response``,
tamper-evident цепочка COS-082/087). Ref на отчёт переживает рестарт: источник
истины — evidence ledger (+ файл в artifact store).

Честность:
  - нет ``sast``-кирпича в batch'е → no-op (не каждая пачка — source-скан);
  - кирпич есть, канонического маркера нет (шаг упал / не дошёл) →
    ``MissingSastReportError`` — вызывающий пишет alert-след, отчёт не
    выдумывается;
  - маркер не сходится с payload (bytes/sha256) → ``InvalidSastReportError``.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.domain.sast_report import (
    SAST_REPORT_MARKER_PREFIX,
    find_sast_report_marker,
    verify_sast_report_marker,
)
from orchestrator.cosmo.ledger.artifact_store import ArtifactRef, ArtifactStore
from orchestrator.cosmo.ledger.evidence_writer import append_evidence_entry

#: Дом artifact-store для отчётов source-SAST (как SARIF master-отчёты, COS-075).
SAST_EVIDENCE_BASE_DIR = "cosmo-evidence"


class MissingSastReportError(RuntimeError):
    """sast-шаг завершился без канонического маркера отчёта в логах."""

    def __init__(self, batch_id: str) -> None:
        super().__init__(
            f"sast batch '{batch_id}' produced no canonical report marker "
            f"({SAST_REPORT_MARKER_PREFIX}) — report not captured"
        )
        self.batch_id = batch_id


class InvalidSastReportError(RuntimeError):
    """Маркер отчёта не сходится с payload (битый/подменённый отчёт)."""

    def __init__(self, batch_id: str, problem: str) -> None:
        super().__init__(
            f"sast batch '{batch_id}' report marker is inconsistent: {problem}"
        )
        self.batch_id = batch_id
        self.problem = problem


def sast_report_bricks(bricks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Кирпичи source-SAST: ``brick.type == "sast"`` или ``definition.type == "sast"``.

    ``batch.bricks_refs`` хранит ``{name, definition, ...}``; канонический
    BrickType — ``sast`` (domain/pipeline_brick), legacy-дефиниции могли нести
    маркер в ``definition.type``.
    """
    out: list[dict[str, Any]] = []
    for brick in bricks or []:
        definition = brick.get("definition") or {}
        if brick.get("type") == "sast" or definition.get("type") == "sast":
            out.append(brick)
    return out


def _report_ext(fmt: str) -> str:
    return "json" if fmt == "ce-issues" else "sarif"


async def capture_sast_reports(
    session: AsyncSession,
    *,
    run_id: str,
    batch_id: str,
    bricks: list[dict[str, Any]],
    logs: dict[str, list[str]],
    store: Optional[ArtifactStore] = None,
) -> list[str]:
    """Захватить отчёт source-SAST из логов → durable (store + ledger).

    Возвращает id записанных ``EvidenceLedgerEntry`` (пустой список — в batch'е
    нет sast-кирпичей). Запись идёт в текущую сессию без commit (решает caller —
    тот же контракт, что у ``artifact_capture``/``write_run_evidence``).

    Raises:
        MissingSastReportError: sast-кирпич есть, валидного маркера нет.
        InvalidSastReportError: маркер не сходится с payload.
    """
    brick_list = sast_report_bricks(bricks)
    if not brick_list:
        return []

    marker = find_sast_report_marker(logs)
    if marker is None:
        raise MissingSastReportError(batch_id)
    problem = verify_sast_report_marker(marker)
    if problem:
        raise InvalidSastReportError(batch_id, problem)

    artifact_store = store or ArtifactStore(base_dir=SAST_EVIDENCE_BASE_DIR)
    ref: ArtifactRef = artifact_store.store(
        marker.payload,
        provenance=f"{run_id}/{batch_id}/sast-report",
        content_type="response",
        ext=_report_ext(marker.format),
    )
    degraded_reason = getattr(ref, "degraded_reason", None)

    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=batch_id,
        type="raw_response",
        content_ref=f"artifact://{ref.path}",
        content_hash=marker.sha256,
        provenance_json={
            "source": "sonarqube",
            "format": marker.format,
            "brick_names": [str(b.get("name") or "") for b in brick_list],
            "artifact_ref_id": ref.ref_id,
            "artifact_path": ref.path,
            "bytes": marker.bytes_len,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "degraded": bool(degraded_reason),
            "degraded_reason": degraded_reason,
        },
    )
    await append_evidence_entry(session, entry)
    return [entry.id]


__all__ = [
    "InvalidSastReportError",
    "MissingSastReportError",
    "SAST_EVIDENCE_BASE_DIR",
    "capture_sast_reports",
    "sast_report_bricks",
]
