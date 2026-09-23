# -*- coding: utf-8 -*-
"""COS-169/170: Promotion packing + landing (ЗР→ЗТ→ЗПЭ) — DTO и каноны.

Промоушен релиза между зонами идёт как **transfer-пакет**, а не голый образ:

  - pack (исходная зона) собирает idempotent пакет из durable
    ``ArtifactRecord`` прогонов релиза: digest-pin + SBOM (``sbom_ref``) +
    trivy gate (PASS) + evidence; пакетный digest — детерминированный
    sha256 канонического manifest (не зависит от времени → idempotent).
  - land (целевая зона) верифицирует ``incoming_manifest_digest`` == пакетный
    digest, перечитывает SBOM + trivy gate из ledger (belt-and-suspenders) и
    только потом переводит релиз в следующую зону → статус ``promoted``.

Честная граница: любой mismatch/missing/blocked → явный честный fail (никогда
молчаливый ``promoted``). Digest-канон наследуется из COS-142/163: sha256
нижний регистр, ``canonical_ref`` консистентен end-to-end.

Сепарация канона (не дублируем):
  - durable запись/чтение пакета → ``ledger/promotion_ledger.py``;
  - сбор SBOM → ``ledger/artifact_sbom.py`` (sbom_ref, COS-167);
  - trivy gate → ``ledger/artifact_scan_gate.py`` (COS-168);
  - арфакт-записи → ``ledger/artifact_record.py`` (COS-163);
  - линейные зоны → ``domain/release_model.next_zone`` (COS-054).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Strict = ConfigDict(extra="forbid")

#: Итоговый статус пакета/landing промоушена.
PromotionStatus = Literal[
    "packed", "promoted", "mismatch", "blocked", "missing", "duplicate",
]

#: Вердикт trivy gate внутри пакета (MISSING — вердикт не вынесен).
TrivyGateVerdict = Literal["PASS", "BLOCK", "MISSING"]

#: Зоны промоушена (строгий линейный порядок ЗР→ЗТ→ЗПЭ, COS-054).
PromotionZone = Literal["zr", "zt", "zpe"]


class PromotionArtifact(BaseModel):
    """Один артефакт релиза в пакете: digest-pin + SBOM + trivy gate."""

    model_config = Strict

    name: str
    version: str
    digest: str = Field(..., description="immutable sha256:<hex64>")
    canonical_ref: str
    sbom_ref: str = Field(..., min_length=1, description="oci://...#sbom якорь")
    trivy_verdict: TrivyGateVerdict = "PASS"


class PromotionPackage(BaseModel):
    """Idempotent transfer-пакет релиза для одной зоны-перехода."""

    model_config = Strict

    release_id: str
    source_zone: PromotionZone
    target_zone: PromotionZone
    revision: int = Field(default=1, ge=1)
    artifacts: list[PromotionArtifact]
    package_digest: str = Field(..., description="sha256 канонического manifest")
    content_fingerprint: str = Field(..., description="sha256 артефактного контента")
    status: PromotionStatus = "packed"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PromotionLandRequest(BaseModel):
    """Запрос на landing пакета в целевой зоне."""

    model_config = Strict

    target_zone: PromotionZone
    incoming_manifest_digest: str = Field(..., min_length=64, max_length=71,
                                          description="digest доставленного manifest")
    expected_current_zone: Optional[PromotionZone] = Field(
        default=None, description="CAS: ожидаемая текущая зона релиза")


class PromotionLandResponse(BaseModel):
    """Честный отчёт landing: promoted / mismatch / blocked / missing / duplicate."""

    model_config = Strict

    release_id: str
    target_zone: PromotionZone
    package_digest: str
    status: PromotionStatus
    gate_pass: bool = True
    sbom_present: bool = True
    current_zone: PromotionZone
    reasons: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
# Manifest + digest (детерминированный, НЕ зависит от времени)
# ══════════════════════════════════════════════════════════════════

def _artifact_dict(artifact: PromotionArtifact) -> dict:
    return {
        "name": artifact.name,
        "version": artifact.version,
        "digest": artifact.digest,
        "canonical_ref": artifact.canonical_ref,
        "sbom_ref": artifact.sbom_ref,
        "trivy_verdict": artifact.trivy_verdict,
    }


def sorted_artifacts(artifacts: list[PromotionArtifact]) -> list[PromotionArtifact]:
    """Канонический порядок артефактов (по canonical_ref) — idempotency."""
    return sorted(artifacts, key=lambda a: a.canonical_ref)


def build_promotion_manifest(
    release_id: str,
    source_zone: str,
    target_zone: str,
    revision: int,
    artifacts: list[PromotionArtifact],
) -> dict:
    """Канонический manifest пакета (без временных полей — idempotent digest)."""
    return {
        "release_id": release_id,
        "revision": revision,
        "source_zone": source_zone,
        "target_zone": target_zone,
        "artifacts": [_artifact_dict(a) for a in sorted_artifacts(artifacts)],
    }


def compute_package_digest(manifest: dict) -> str:
    """Детерминированный sha256 канонического JSON manifest."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def promotion_content_fingerprint(artifacts: list[PromotionArtifact]) -> str:
    """sha256 чисто артефактного контента — ключ idempotency пака.

    Не включает zone/revision: тот же контент в другой зоне или той же зоне
    при идентичном составе сойдётся в один fingerprint.
    """
    payload = [_artifact_dict(a) for a in sorted_artifacts(artifacts)]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "PromotionStatus",
    "TrivyGateVerdict",
    "PromotionZone",
    "PromotionArtifact",
    "PromotionPackage",
    "PromotionLandRequest",
    "PromotionLandResponse",
    "sorted_artifacts",
    "build_promotion_manifest",
    "compute_package_digest",
    "promotion_content_fingerprint",
]