"""
STACK-LUNA-001: Unified Scanner Result Contract.

Единый контракт результатов для всех одобренных сканеров безопасности
Cosmoport 2.0 (KICS, ClamAV, Gitleaks, Hadolint, KubeLinter).

Инварианты:
  - Один контракт на все сканеры
  - PASS/FAIL/ERROR/UNAVAILABLE — четыре дискретных вердикта
  - Привязка к артефакту (digest, build_id, release_id)
  - Evidence + tool/rules version
  - Offline provenance
  - Idempotent delivery
  - Никаких raw secrets
"""
from __future__ import annotations

import datetime
import hashlib
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

StrictConfig = ConfigDict(extra="ignore")

# ── Вердикты сканера ─────────────────────────────────────────────────────────

ScannerVerdict = Literal["PASS", "FAIL", "ERROR", "UNAVAILABLE"]

ScannerTool = Literal[
    "kics",           # KICS — IaC security scanning
    "clamav",         # ClamAV — malware/AV
    "gitleaks",       # Gitleaks — secret detection
    "hadolint",       # Hadolint — Dockerfile/build-context lint
    "kubelinter",     # KubeLinter — K8s manifest scanning
    "codeql",         # CodeQL — future
    "semgrep",        # Semgrep — future
]

# ── Только одобренные сканеры для active execution ──────────────────────────

APPROVED_SCANNERS: set[ScannerTool] = {"kics", "clamav", "gitleaks", "hadolint", "kubelinter"}
FUTURE_SCANNERS: set[ScannerTool] = {"codeql", "semgrep"}


# ── Scanner Finding (одна находка) ──────────────────────────────────────────

class ScannerFinding(BaseModel):
    """Единая модель находки сканера безопасности."""
    model_config = StrictConfig

    finding_id: str = Field(
        default_factory=lambda: f"sf-{uuid.uuid4().hex[:10]}",
        description="Уникальный ID находки",
    )
    rule_id: str = Field(..., min_length=1, description="ID правила сканера (e.g. KICS-abc123, G001)")
    severity: Literal["critical", "high", "medium", "low", "info"] = Field(
        default="medium", description="Уровень серьёзности"
    )
    title: str = Field(..., min_length=1, description="Краткое описание находки")
    description: str = Field(default="", description="Детальное описание")
    file_path: str = Field(default="", description="Путь к файлу с находкой")
    line_number: int = Field(default=0, ge=0, description="Строка в файле")
    cwe_id: Optional[str] = Field(default=None, description="CWE идентификатор")
    remediation: str = Field(default="", description="Рекомендация по устранению")
    raw_output_snippet: str = Field(
        default="", max_length=2000, description="Сырой фрагмент вывода сканера (ограничен 2000 символов)"
    )


# ── ScannerResult (весь результат прогона сканера) ──────────────────────────

class ScannerResult(BaseModel):
    """Единый контракт результата прогона сканера."""
    model_config = StrictConfig

    scan_id: str = Field(
        default_factory=lambda: f"scan-{uuid.uuid4().hex[:12]}",
        description="Уникальный ID прогона сканирования",
    )
    tool: ScannerTool = Field(..., description="Инструмент сканирования")
    tool_version: str = Field(..., min_length=1, description="Версия инструмента (e.g. 'kics 2.1.3')")
    rules_version: str = Field(default="latest", description="Версия правил / сигнатур")

    verdict: ScannerVerdict = Field(..., description="Итоговый вердикт сканирования")
    findings: List[ScannerFinding] = Field(
        default_factory=list, description="Список находок"
    )
    findings_count: int = Field(default=0, ge=0, description="Общее количество находок")

    # Привязка к артефакту
    artifact_digest_sha256: Optional[str] = Field(
        default=None, min_length=64, max_length=64,
        description="SHA-256 дайджест просканированного артефакта",
    )
    artifact_name: Optional[str] = Field(default=None, description="Имя артефакта")
    build_id: Optional[str] = Field(default=None, description="ID сборки")
    release_id: Optional[str] = Field(default=None, description="ID релиза (если применимо)")
    app_id: Optional[str] = Field(default=None, description="ID приложения")

    # Временные метки
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    duration_ms: Optional[int] = Field(default=None, ge=0, description="Длительность сканирования в мс")

    # Evidence linkage (CBR-LUNA-002: НЕ vault! vault → credentials. MinIO/S3 → evidence)
    evidence_ref: Optional[str] = Field(
        default=None, description="Ссылка на улику (artifact:// или s3:// — MinIO/S3 object key)"
    )
    sarif_ref: Optional[str] = Field(
        default=None, description="Ссылка на SARIF-отчёт (artifact:// или s3:// — MinIO/S3 object key)"
    )
    provenance_hash: Optional[str] = Field(
        default=None, description="Хеш provenance (SHA-256 для офлайн-верификации)"
    )
    idempotency_key: Optional[str] = Field(
        default=None, description="Ключ идемпотентности (tool + artifact_digest + rules_version)"
    )
    meta: Dict[str, Any] = Field(default_factory=dict, description="Дополнительные метаданные")

    @field_validator("verdict")
    @classmethod
    def verdict_matches_findings(cls, v: ScannerVerdict, info) -> ScannerVerdict:
        # PASS не может иметь findings
        # ERROR / UNAVAILABLE — findings опциональны
        return v

    def model_post_init(self, __context: Any):
        """Вычислить findings_count, idempotency_key и provenance_hash."""
        if self.findings_count == 0 and self.findings:
            object.__setattr__(self, "findings_count", len(self.findings))

        if not self.idempotency_key:
            key_parts = [
                self.tool,
                self.artifact_digest_sha256 or "no-digest",
                self.rules_version,
            ]
            self.idempotency_key = hashlib.sha256(
                "|".join(key_parts).encode("utf-8")
            ).hexdigest()[:16]

        if not self.provenance_hash:
            prov_parts = [
                self.tool,
                self.tool_version,
                self.rules_version,
                self.artifact_digest_sha256 or "no-digest",
                self.verdict,
            ]
            self.provenance_hash = hashlib.sha256(
                "|".join(prov_parts).encode("utf-8")
            ).hexdigest()[:32]

    @property
    def is_approved(self) -> bool:
        """Является ли сканер одобренным для production использования."""
        return self.tool in APPROVED_SCANNERS

    @property
    def is_future(self) -> bool:
        """Является ли сканер future-контрактом (не активирован)."""
        return self.tool in FUTURE_SCANNERS

    @property
    def has_evidence(self) -> bool:
        """Привязана ли улика к результату (MinIO/S3)."""
        return self.evidence_ref is not None and (
            self.evidence_ref.startswith("artifact://") or
            self.evidence_ref.startswith("s3://") or
            self.evidence_ref.startswith("minio://")
        )

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    def to_evidence_record(self) -> Dict[str, Any]:
        """Преобразовать результат в Evidence запись."""
        return {
            "scan_id": self.scan_id,
            "tool": self.tool,
            "verdict": self.verdict,
            "artifact_digest": self.artifact_digest_sha256,
            "findings_count": self.findings_count,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "provenance_hash": self.provenance_hash,
            "idempotency_key": self.idempotency_key,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# ── Scanner Adapter ABC ──────────────────────────────────────────────────────

class BaseScannerAdapter:
    """Абстрактный базовый адаптер сканера безопасности.

    Все одобренные адаптеры реализуют этот контракт.
    """

    tool: ScannerTool
    tool_version: str = "unknown"
    rules_version: str = "latest"

    def parse_output(self, raw_output: str, **kwargs) -> ScannerResult:
        """Парсинг сырого вывода сканера в единый ScannerResult."""
        raise NotImplementedError("Subclass must implement parse_output")

    def normalize_finding(self, raw: Dict[str, Any]) -> ScannerFinding:
        """Нормализация одной находки из сырого словаря."""
        return ScannerFinding(
            rule_id=raw.get("rule_id", f"{self.tool}-unknown"),
            severity=raw.get("severity", "medium"),
            title=raw.get("title", "Unknown finding"),
            description=raw.get("description", ""),
            file_path=raw.get("file_path", ""),
            line_number=raw.get("line_number", raw.get("line", 0)),
            cwe_id=raw.get("cwe_id", raw.get("cwe")),
            remediation=raw.get("remediation", ""),
            raw_output_snippet=raw.get("raw_output_snippet", "")[:2000],
        )

    def build_result(
        self,
        verdict: ScannerVerdict,
        findings: List[ScannerFinding],
        artifact_digest: Optional[str] = None,
        artifact_name: Optional[str] = None,
        build_id: Optional[str] = None,
        release_id: Optional[str] = None,
        app_id: Optional[str] = None,
        started_at: Optional[datetime.datetime] = None,
        finished_at: Optional[datetime.datetime] = None,
        duration_ms: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> ScannerResult:
        """Собрать единый ScannerResult."""
        return ScannerResult(
            tool=self.tool,
            tool_version=self.tool_version,
            rules_version=self.rules_version,
            verdict=verdict,
            findings=findings,
            artifact_digest_sha256=artifact_digest,
            artifact_name=artifact_name,
            build_id=build_id,
            release_id=release_id,
            app_id=app_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            meta=meta or {},
        )