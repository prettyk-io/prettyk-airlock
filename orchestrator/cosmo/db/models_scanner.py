"""
CBR-LUNA-001: ScannerResult / ScannerFinding / Evidence Persistence (SQLAlchemy 2 + Alembic).

Хранит результаты сканирования и находки в PostgreSQL:
  - scan_results: прогоны сканеров (PASS/FAIL/ERROR/UNAVAILABLE)
  - scan_findings: индивидуальные находки (CWE, severity, file_path, remediation)
  - scan_evidence: evidence linkage (artifacts к scan_results)
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.cosmo.db.session import Base


def _uid():
    return uuid.uuid4().hex[:12]


# ══════════════════════════════════════════════════════════════════════════════
# scan_results — результаты прогонов сканеров безопасности
# ══════════════════════════════════════════════════════════════════════════════

class ScanResult(Base):
    """Сканеры — независимая reference-таблица, связь через строгий external identity contract (FK + digest)."""
    __tablename__ = "scan_results"
    __table_args__ = (
        Index("ix_scan_results_app", "app_id"),
        Index("ix_scan_results_build", "build_id"),
        Index("ix_scan_results_release", "release_id"),
        Index("ix_scan_results_run", "run_id"),
        Index("ix_scan_results_tool", "tool"),
        Index("ix_scan_results_verdict", "verdict"),
        Index("ix_scan_results_artifact_digest", "artifact_digest_sha256"),
        {"comment": "Результаты сканеров безопасности — FK + digest identity (CBR-LUNA-002)"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    scan_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_version: Mapped[str] = mapped_column(String(64), default="latest", nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # PASS/FAIL/ERROR/UNAVAILABLE
    findings_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    artifact_digest_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artifact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # CBR-LUNA-002: FK referential integrity
    app_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("apps.id", ondelete="SET NULL"), nullable=True)
    build_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("cosmo_builds.id", ondelete="SET NULL"), nullable=True)
    release_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("releases.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)

    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    evidence_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    sarif_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    provenance_hash: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    findings: Mapped[list["ScanFinding"]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    evidence_links: Mapped[list["ScanEvidence"]] = relationship(back_populates="scan", cascade="all, delete-orphan")


# ══════════════════════════════════════════════════════════════════════════════
# scan_findings — индивидуальные находки
# ══════════════════════════════════════════════════════════════════════════════

class ScanFinding(Base):
    """Индивидуальная находка сканера безопасности."""
    __tablename__ = "scan_findings"
    __table_args__ = (
        Index("ix_scan_findings_scan", "scan_id"),
        Index("ix_scan_findings_severity", "severity"),
        Index("ix_scan_findings_cwe", "cwe_id"),
        {"comment": "Находки сканеров безопасности — STACK-LUNA-001"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    scan_id: Mapped[str] = mapped_column(String(64), ForeignKey("scan_results.scan_id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cwe_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    remediation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_output_snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    scan: Mapped["ScanResult"] = relationship(back_populates="findings")


# ══════════════════════════════════════════════════════════════════════════════
# scan_evidence — evidence linkage к scan_result
# ══════════════════════════════════════════════════════════════════════════════

class ScanEvidence(Base):
    """Связь evidence с результатом сканирования (по ГОСТ / in-toto)."""
    __tablename__ = "scan_evidence"
    __table_args__ = (
        Index("ix_scan_evidence_scan", "scan_id"),
        {"comment": "Связь доказательств с результатами сканирования — CBR-LUNA-001"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uid)
    scan_id: Mapped[str] = mapped_column(String(64), ForeignKey("scan_results.scan_id", ondelete="CASCADE"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), default="scan_result", nullable=False)
    content_ref: Mapped[str] = mapped_column(String(512), nullable=False)  # vault:secret/... or MinIO key
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attestation_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # in-toto attestation
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    scan: Mapped["ScanResult"] = relationship(back_populates="evidence_links")