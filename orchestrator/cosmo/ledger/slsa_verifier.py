"""
COS-218: SLSA Level 4 Supply-Chain Provenance & in-toto Attestations.

Реализует:
  1. Генерацию и проверку SLSA Provenance v1.0 и in-toto аттестаций сборки.
  2. Верификацию требований SLSA Level 4:
     - Герметичность сборки (Hermetic Build: без доступа в интернет во время компиляции)
     - Воспроизводимость артефактов (Reproducible Build)
     - Контроль двух лиц (Two-Person Code Review / Four-Eyes Principle)
     - Неизменяемость среды сборки на изолированных воркерах
"""
from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SLSAMaterial:
    uri: str
    sha256_digest: str


@dataclass
class SLSAProvenance:
    """SLSA Provenance v1.0 Аттестация сборки."""
    build_id: str
    builder_id: str                   # e.g. "https://kits.cosmo/builders/isolated-runner@v2"
    build_type: str = "https://slsa.dev/provenance/v1"
    materials: List[SLSAMaterial] = field(default_factory=list)
    artifact_name: str = ""
    artifact_sha256: str = ""
    is_hermetic: bool = True          # Сборка без внешнего сетевого доступа
    is_reproducible: bool = True      # Битовая воспроизводимость
    two_person_reviewed: bool = True  # Принцип четырех глаз
    builder_signature: str = ""
    built_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def canonical_json(self) -> str:
        data = {
            "build_id": self.build_id,
            "builder_id": self.builder_id,
            "build_type": self.build_type,
            "artifact_name": self.artifact_name,
            "artifact_sha256": self.artifact_sha256,
            "is_hermetic": self.is_hermetic,
            "is_reproducible": self.is_reproducible,
            "two_person_reviewed": self.two_person_reviewed,
            "materials": [
                {"uri": m.uri, "sha256": m.sha256_digest}
                for m in sorted(self.materials, key=lambda x: x.uri)
            ],
            "built_at": self.built_at,
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    def sign_in_toto(self, builder_secret: str) -> SLSAProvenance:
        payload = self.canonical_json().encode("utf-8")
        self.builder_signature = hashlib.sha256((builder_secret.encode("utf-8") + payload)).hexdigest()
        return self

    def verify_in_toto(self, builder_secret: str) -> bool:
        if not self.builder_signature:
            return False
        payload = self.canonical_json().encode("utf-8")
        expected = hashlib.sha256((builder_secret.encode("utf-8") + payload)).hexdigest()
        return expected == self.builder_signature


@dataclass
class SLSAVerificationResult:
    achieved_level: str
    is_level_4_compliant: bool
    violations: List[str]


class SLSAProvenanceVerifier:
    """COS-218: Валидатор соответствия SLSA Level 4."""

    @classmethod
    def evaluate_slsa_level(
        cls,
        provenance: SLSAProvenance,
    ) -> Tuple[int, List[str]]:
        """Оценивает достигнутый уровень SLSA (Level 1..4).

        Returns:
            (achieved_level, non_compliance_reasons)
        """
        reasons: List[str] = []

        # Level 1: Наличие базовой сборки и артефакта
        if not provenance.artifact_sha256 or not provenance.materials:
            reasons.append("SLSA-1: Отсутствуют материалы сборки или контрольная сумма артефакта.")
            return 0, reasons

        # Level 2: Доверенный hosted builder + цифровая подпись
        if not provenance.builder_signature or not provenance.builder_id.startswith("https://kits.cosmo"):
            reasons.append("SLSA-2: Сборка не подписана доверенным изолированным раннером.")
            return 1, reasons

        # Level 3: Контроль двух лиц (Two-Person Review)
        if not provenance.two_person_reviewed:
            reasons.append("SLSA-3: Отсутствует подтверждение двух независимых рецензентов (Two-Person Review).")
            return 2, reasons

        # Level 4: Герметичность и Воспроизводимость (Hermetic + Reproducible)
        if not provenance.is_hermetic:
            reasons.append("SLSA-4: Сборка не является герметичной (hermetic: false).")
            return 3, reasons

        if not provenance.is_reproducible:
            reasons.append("SLSA-4: Сборка не является детерминированно воспроизводимой.")
            return 3, reasons

        return 4, []

    @classmethod
    def verify_slsa_level_4(cls, provenance: SLSAProvenance) -> SLSAVerificationResult:
        lvl, violations = cls.evaluate_slsa_level(provenance)
        level_str = f"SLSA_BUILD_LEVEL_{lvl}"
        return SLSAVerificationResult(
            achieved_level=level_str,
            is_level_4_compliant=(lvl == 4),
            violations=violations,
        )

    @classmethod
    def generate_in_toto_statement(cls, provenance: SLSAProvenance) -> Dict[str, Any]:
        return {
            "_type": "https://in-toto.io/Statement/v0.1",
            "subject": [
                {
                    "name": provenance.artifact_name,
                    "digest": {"sha256": provenance.artifact_sha256},
                }
            ],
            "predicateType": provenance.build_type,
            "predicate": {
                "builder": {"id": provenance.builder_id},
                "buildType": provenance.build_type,
                "materials": [
                    {"uri": m.uri, "digest": {"sha256": m.sha256_digest}}
                    for m in provenance.materials
                ],
                "metadata": {
                    "buildInvocationId": provenance.build_id,
                    "completeness": {
                        "parameters": True,
                        "environment": True,
                        "materials": True,
                    },
                    "reproducible": provenance.is_reproducible,
                    "hermetic": provenance.is_hermetic,
                },
            },
        }

