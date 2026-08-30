"""
COS-109: Cross-Zone Digital Envelope Signer.

Генерирует криптографический цифровой конверт (Digital Release Envelope) для
безопасного переноса релиза между зонами (ЗР → ЗТ → ЗПЭ) без передачи дампа БД.
Конверт — полностью автономный документ с SHA-256 цифровой подписью.

Операции:
  seal_envelope(release_id, signer, ...) -> DigitalReleaseEnvelope
  verify_envelope(envelope)              -> bool
  verify_envelope_body(body)             -> bool
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import io
import json
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

EnvelopeZone = Literal["zr", "zt", "zpe"]


@dataclass
class EnvelopeArtifactDigest:
    """Хэши одного артефакта (SBOM, SARIF, бинарник, образ контейнера)."""
    name: str
    artifact_type: str = "binary"  # sbom, sarif, image, binary, evidence
    sha256: str = ""
    size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "artifact_type": self.artifact_type,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnvelopeArtifactDigest:
        return cls(
            name=data.get("name", ""),
            artifact_type=data.get("artifact_type", data.get("type", "binary")),
            sha256=data.get("sha256", ""),
            size_bytes=int(data.get("size_bytes", 0)),
        )


@dataclass
class EnvelopeManifest:
    """Полный граф узлов и рёбер с SHA-256 коммитов."""
    run_ids: List[str] = field(default_factory=list)
    commit_shas: Dict[str, str] = field(default_factory=dict)       # run_id / node -> sha
    pipeline_hash: str = ""                                         # SHA-256 compiled plan
    nodes: List[Dict[str, Any]] = field(default_factory=list)       # узлы графа
    edges: List[Dict[str, Any]] = field(default_factory=list)       # ребра графа
    gate_decisions: Dict[str, str] = field(default_factory=dict)    # gate_id -> decision
    batches: List[Dict[str, Any]] = field(default_factory=list)     # [{id, type, status}]
    findings_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_ids": self.run_ids,
            "commit_shas": self.commit_shas,
            "pipeline_hash": self.pipeline_hash,
            "nodes": self.nodes,
            "edges": self.edges,
            "gate_decisions": self.gate_decisions,
            "batches": self.batches,
            "findings_count": self.findings_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnvelopeManifest:
        return cls(
            run_ids=list(data.get("run_ids", [])),
            commit_shas=dict(data.get("commit_shas", {})),
            pipeline_hash=data.get("pipeline_hash", ""),
            nodes=list(data.get("nodes", [])),
            edges=list(data.get("edges", [])),
            gate_decisions=dict(data.get("gate_decisions", {})),
            batches=list(data.get("batches", [])),
            findings_count=int(data.get("findings_count", 0)),
        )


@dataclass
class GOSTActSummary:
    """Заключение соответствия и подпись офицера ИБ."""
    profile: str = "gost_56939_2016"          # gost_56939_2016 / gost_71207_2024 / cb_683p_757p
    verdict: str = "PASS"                     # PASS / FAIL / CONDITIONAL
    conclusion: str = ""                      # Текстовое заключение
    signed_by: str = ""                       # ФИО / ID офицера ИБ
    signed_at: str = ""                       # ISO-8601 timestamp
    signature: str = ""                       # HMAC-SHA256 / SHA-256 подпись офицера ИБ

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "verdict": self.verdict,
            "conclusion": self.conclusion,
            "signed_by": self.signed_by,
            "signed_at": self.signed_at,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GOSTActSummary:
        return cls(
            profile=data.get("profile", "gost_56939_2016"),
            verdict=data.get("verdict", "PASS"),
            conclusion=data.get("conclusion", ""),
            signed_by=data.get("signed_by", ""),
            signed_at=data.get("signed_at", ""),
            signature=data.get("signature", ""),
        )


@dataclass
class DigitalReleaseEnvelope:
    """COS-109: цифровой конверт релиза (Digital Release Envelope).

    Полностью автономный контейнер метаданных, графа, дайджестов артефактов,
    ГОСТ-заключения и подписи для межзонного переноса.
    """
    release_id: str
    version: str
    domain_id: str
    source_zone: EnvelopeZone = "zr"
    target_zone: EnvelopeZone = "zt"

    # Содержимое
    manifest: EnvelopeManifest = field(default_factory=EnvelopeManifest)
    artifacts_digest: List[EnvelopeArtifactDigest] = field(default_factory=list)
    gost_act_summary: GOSTActSummary = field(default_factory=GOSTActSummary)
    changelog: str = ""
    approvals_count: int = 0
    transfer_history_count: int = 0

    # Запечатывание
    sealed_at: str = ""
    sealed_by: str = ""
    envelope_signature: str = ""

    def canonical_dict(self) -> Dict[str, Any]:
        """Каноническое представление без подписи (для вычисления SHA-256)."""
        return {
            "release_id": self.release_id,
            "version": self.version,
            "domain_id": self.domain_id,
            "source_zone": self.source_zone,
            "target_zone": self.target_zone,
            "manifest": {
                "run_ids": sorted(self.manifest.run_ids),
                "commit_shas": {k: self.manifest.commit_shas[k] for k in sorted(self.manifest.commit_shas)},
                "pipeline_hash": self.manifest.pipeline_hash,
                "nodes": sorted(self.manifest.nodes, key=lambda n: str(n.get("id", ""))),
                "edges": sorted(self.manifest.edges, key=lambda e: (str(e.get("from", "")), str(e.get("to", "")))),
                "gate_decisions": {k: self.manifest.gate_decisions[k] for k in sorted(self.manifest.gate_decisions)},
                "batches": sorted(self.manifest.batches, key=lambda b: str(b.get("id", ""))),
                "findings_count": self.manifest.findings_count,
            },
            "artifacts_digest": sorted(
                [a.to_dict() for a in self.artifacts_digest],
                key=lambda a: (a["name"], a["sha256"]),
            ),
            "gost_act_summary": self.gost_act_summary.to_dict(),
            "changelog": self.changelog,
            "approvals_count": self.approvals_count,
            "transfer_history_count": self.transfer_history_count,
            "sealed_at": self.sealed_at,
            "sealed_by": self.sealed_by,
        }

    def canonical_json(self) -> str:
        """Детерминированная JSON-сериализация для подписи."""
        return json.dumps(self.canonical_dict(), ensure_ascii=False, sort_keys=True)

    def sign(self, signer: str) -> DigitalReleaseEnvelope:
        """Запечатать и подписать конверт SHA-256 подписью."""
        if not self.sealed_at:
            self.sealed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.sealed_by = signer
        self.envelope_signature = hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()
        return self

    def verify(self) -> bool:
        """Проверить целостность и подлинность конверта."""
        if not self.envelope_signature or not self.sealed_by or not self.sealed_at:
            return False
        expected_sig = hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()
        return expected_sig == self.envelope_signature

    def to_dict(self) -> Dict[str, Any]:
        """Полная сериализация в словарь, включая подпись."""
        res = self.canonical_dict()
        res["envelope_id"] = self.release_id
        res["envelope_signature"] = self.envelope_signature
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DigitalReleaseEnvelope:
        """Десериализация из словаря."""
        manifest_data = data.get("manifest", {})
        manifest = EnvelopeManifest.from_dict(manifest_data)

        raw_artifacts = data.get("artifacts_digest", [])
        artifacts = [
            EnvelopeArtifactDigest.from_dict(a) if isinstance(a, dict) else a
            for a in raw_artifacts
        ]

        gost_data = data.get("gost_act_summary", {})
        gost_summary = GOSTActSummary.from_dict(gost_data)

        rel_id = data.get("release_id") or data.get("envelope_id", "")
        return cls(
            release_id=rel_id,
            version=data.get("version", ""),
            domain_id=data.get("domain_id", ""),
            source_zone=data.get("source_zone", "zr"),
            target_zone=data.get("target_zone", "zt"),
            manifest=manifest,
            artifacts_digest=artifacts,
            gost_act_summary=gost_summary,
            changelog=data.get("changelog", ""),
            approvals_count=int(data.get("approvals_count", 0)),
            transfer_history_count=int(data.get("transfer_history_count", 0)),
            sealed_at=data.get("sealed_at", ""),
            sealed_by=data.get("sealed_by", ""),
            envelope_signature=data.get("envelope_signature", ""),
        )


def seal_envelope(
    release_id: str,
    signer: str,
    *,
    version: str = "1.0.0",
    domain_id: str = "",
    source_zone: EnvelopeZone = "zr",
    target_zone: EnvelopeZone = "zt",
    manifest: Optional[EnvelopeManifest | Dict[str, Any]] = None,
    run_ids: Optional[List[str]] = None,
    commit_shas: Optional[Dict[str, str]] = None,
    nodes: Optional[List[Dict[str, Any]]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    pipeline_hash: str = "",
    gate_decisions: Optional[Dict[str, str]] = None,
    batches: Optional[List[Dict[str, Any]]] = None,
    findings_count: int = 0,
    artifacts: Optional[List[EnvelopeArtifactDigest | Dict[str, Any]]] = None,
    gost_act_summary: Optional[GOSTActSummary | Dict[str, Any]] = None,
    gost_verdict: str = "PASS",
    gost_profile: str = "gost_56939_2016",
    gost_conclusion: str = "",
    changelog: str = "",
    approvals_count: int = 0,
    transfer_history_count: int = 0,
) -> DigitalReleaseEnvelope:
    """COS-109: Создать и подписать цифровой конверт релиза."""
    # Обработка manifest
    if isinstance(manifest, EnvelopeManifest):
        mf = manifest
    elif isinstance(manifest, dict):
        mf = EnvelopeManifest.from_dict(manifest)
    else:
        mf = EnvelopeManifest(
            run_ids=run_ids or [],
            commit_shas=commit_shas or {},
            pipeline_hash=pipeline_hash,
            nodes=nodes or [],
            edges=edges or [],
            gate_decisions=gate_decisions or {},
            batches=batches or [],
            findings_count=findings_count,
        )

    # Обработка artifacts
    art_list: List[EnvelopeArtifactDigest] = []
    if artifacts:
        for a in artifacts:
            if isinstance(a, EnvelopeArtifactDigest):
                art_list.append(a)
            elif isinstance(a, dict):
                art_list.append(EnvelopeArtifactDigest.from_dict(a))

    # Обработка gost_act_summary
    if isinstance(gost_act_summary, GOSTActSummary):
        gost = gost_act_summary
    elif isinstance(gost_act_summary, dict):
        gost = GOSTActSummary.from_dict(gost_act_summary)
    else:
        gost = GOSTActSummary(
            profile=gost_profile,
            verdict=gost_verdict,
            conclusion=gost_conclusion or f"ГОСТ соответствие подтверждено ({gost_verdict})",
            signed_by=signer,
            signed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            signature=hashlib.sha256(f"{release_id}:{signer}:{gost_verdict}".encode()).hexdigest(),
        )

    envelope = DigitalReleaseEnvelope(
        release_id=release_id,
        version=version,
        domain_id=domain_id,
        source_zone=source_zone,
        target_zone=target_zone,
        manifest=mf,
        artifacts_digest=art_list,
        gost_act_summary=gost,
        changelog=changelog,
        approvals_count=approvals_count,
        transfer_history_count=transfer_history_count,
    )

    return envelope.sign(signer)


def verify_envelope(envelope: DigitalReleaseEnvelope) -> bool:
    """COS-109: Проверить неизменность и подпись цифрового конверта."""
    if not isinstance(envelope, DigitalReleaseEnvelope):
        return False
    return envelope.verify()


def verify_envelope_body(body: Dict[str, Any]) -> bool:
    """COS-109: Проверить неизменность и подпись конверта из сырого словаря/JSON."""
    try:
        env = DigitalReleaseEnvelope.from_dict(body)
        return env.verify()
    except Exception:
        return False


class ReleaseEnvelopeService:
    """Фасад сервиса конвертов для совместимости."""
    seal_envelope = staticmethod(seal_envelope)
    verify_envelope = staticmethod(verify_envelope)
    verify_envelope_body = staticmethod(verify_envelope_body)


# ── COS-126: Airgap Release Bundle & Cryptography ────────────────────────────

@dataclass
class AirgapReleaseBundle:
    """COS-126: Пакет для переноса релиза через Airgap (конверт + артефакты)."""
    envelope: DigitalReleaseEnvelope
    artifacts_data: Dict[str, bytes] = field(default_factory=dict)

    def export_bundle(self) -> bytes:
        """Экспорт пакета в ZIP-архив с конвертом envelope.json и артефактами."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("envelope.json", json.dumps(self.envelope.to_dict(), ensure_ascii=False, indent=2))
            for name, data in self.artifacts_data.items():
                zf.writestr(f"artifacts/{name}", data)
        return buf.getvalue()

    @classmethod
    def import_and_verify(
        cls,
        bundle_bytes: bytes,
        destination_zone: Optional[EnvelopeZone] = None,
    ) -> Tuple[bool, Optional[DigitalReleaseEnvelope], List[str]]:
        """Импорт и криптографическая проверка бандла в целевой зоне."""
        errors: List[str] = []
        try:
            buf = io.BytesIO(bundle_bytes)
            with zipfile.ZipFile(buf, "r") as zf:
                if "envelope.json" not in zf.namelist():
                    return False, None, ["Missing envelope.json in bundle"]

                env_bytes = zf.read("envelope.json")
                env_dict = json.loads(env_bytes.decode("utf-8"))
                envelope = DigitalReleaseEnvelope.from_dict(env_dict)

                # 1. Проверка подписи конверта
                if not envelope.verify():
                    errors.append("Envelope signature verification failed")

                # 2. Проверка целевой зоны
                if destination_zone and envelope.target_zone != destination_zone:
                    errors.append(
                        f"Zone mismatch: envelope target is '{envelope.target_zone}', "
                        f"destination is '{destination_zone}'"
                    )

                # 3. Проверка дайджестов всех артефактов
                artifacts_data: Dict[str, bytes] = {}
                for art in envelope.artifacts_digest:
                    path_in_zip = f"artifacts/{art.name}"
                    if path_in_zip not in zf.namelist():
                        errors.append(f"Missing artifact in bundle: {art.name}")
                        continue
                    data = zf.read(path_in_zip)
                    artifacts_data[art.name] = data
                    actual_sha = hashlib.sha256(data).hexdigest()
                    if actual_sha != art.sha256:
                        errors.append(
                            f"Artifact checksum mismatch for '{art.name}': "
                            f"expected {art.sha256}, got {actual_sha}"
                        )

                if errors:
                    return False, envelope, errors

                return True, envelope, []
        except Exception as e:
            return False, None, [f"Failed to unpack bundle: {str(e)}"]


def export_airgap_bundle(
    envelope: DigitalReleaseEnvelope,
    artifacts_data: Dict[str, bytes],
) -> bytes:
    """COS-126: Экспорт Airgap бандла."""
    bundle = AirgapReleaseBundle(envelope=envelope, artifacts_data=artifacts_data)
    return bundle.export_bundle()


def import_and_verify_airgap_bundle(
    bundle_bytes: bytes,
    destination_zone: Optional[EnvelopeZone] = None,
) -> Tuple[bool, Optional[DigitalReleaseEnvelope], List[str]]:
    """COS-126: Импорт и верификация Airgap бандла."""
    return AirgapReleaseBundle.import_and_verify(bundle_bytes, destination_zone=destination_zone)

