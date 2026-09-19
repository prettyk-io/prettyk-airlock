# -*- coding: utf-8 -*-
"""COS-147: упаковщик attestation bundle релиза (chain of custody).

``AttestationBundlePackager`` собирает крипто-свидетельства релиза из
``evidence_ledger`` и запечатывает единый provenance-конверт:

  1. **манифест бандла** (COS-142) — запись ``source='cosmo-manifest-verifier'``,
     ``manifest_type='BUNDLE_MANIFEST'``: pinned-набор ``canonical_refs`` и
     ``digest_pin``;
  2. **аттестация SBOM** (COS-138) — ``source='cosmo-sbom-gate'``:
     ``artifact_digest`` + content-hash SBOM + gate-вердикт;
  3. **клиренс Quality Gate** (COS-141) — ``source='prettyk-hub'``,
     ``clearance_type='QG_CLEARANCE'``: статус клиренса и ``evaluation_id``.

**Chain of custody:** digest артефакта-субъекта обязан присутствовать в
``canonical_refs`` манифеста и совпасть с ``artifact_digest`` SBOM-аттестации.
Расхождение → ``verified=False`` (вердикт, не 5xx): сам факт расхождения
durable-фиксируется в ``provenance_json.chain_of_custody`` ledger-записи.

**Крипто-якорь:** ``provenance_bundle_hash`` (root конверта) запечатывается в
``content_hash``, маркер ``attestation_type='RELEASE_ATTESTATION_BUNDLE'`` — в
provenance (enum ``evidence_type`` заморожен; конвенция гейтов COS-136/138/141).

Честные границы:
  - якорь ledger-записи — первый прогон релиза (``run_ids[0]``); у релиза без
    прогонов якорить нечем → 422;
  - ``profile`` берётся из манифеста бандла; без манифеста — ``"unknown"``;
  - read-path (``latest_attestation_bundle``) — durable: актуальный конверт
    берётся из ``evidence_ledger`` по ``release_id`` (latest wins), in-memory
    реестра нет. Рестарт cosmo-api не теряет read-ответ.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import (
    EvidenceLedgerEntry,
    Release as ReleaseModel,
    Run,
)
from orchestrator.cosmo.domain.evidence_attestation import (
    ATTESTATION_FORMAT,
    EvidenceAttestationBundle,
    EvidenceAttestationPredicate,
    EvidenceAttestationSubject,
    bare_hex,
    compute_provenance_bundle_hash,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry
from orchestrator.cosmo.ledger.hub_clearance_gate import HubClearanceGateManager
from orchestrator.cosmo.ledger.manifest_verifier import (
    MANIFEST_SOURCE,
    MANIFEST_TYPE,
)
from orchestrator.cosmo.ledger.sbom_gate import (
    SBOM_SOURCE,
    latest_sbom_attestation,
)

#: Маркер источника записи бандла в provenance_json.
ATTESTATION_SOURCE = "cosmo-attestation-packager"

#: Маркер типа записи (``provenance_json.attestation_type``).
ATTESTATION_TYPE = "RELEASE_ATTESTATION_BUNDLE"

#: Контракт, которому подчиняется конверт.
ATTESTATION_CONTRACT = "PK-C-003.4"


class AttestationEvidenceError(ValueError):
    """Не удалось собрать конверт; ``status_code`` — HTTP-маппинг."""

    status_code = 422


class ReleaseNotFoundError(AttestationEvidenceError):
    """Релиз не найден."""

    status_code = 404


def _ref_digest(ref: str) -> str:
    """Bare-hex digest из canonical_ref ``<name>:<version>@sha256:<hex>``."""
    return bare_hex(ref.rsplit("@", 1)[-1])


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _release_artifacts(rel: ReleaseModel) -> list[tuple[str, str]]:
    """Пinned-артефакты релиза как ``(name, bare-hex digest)``, детерминированно."""
    out: list[tuple[str, str]] = []
    for art in rel.artifacts or []:
        if isinstance(art, dict):
            name = str(art.get("name") or "")
            for key in ("sha256", "digest", "checksum", "content_hash"):
                raw = art.get(key)
                if not raw:
                    continue
                candidate = bare_hex(str(raw))
                if _is_hex64(candidate):
                    out.append((name, candidate))
                    break
        elif isinstance(art, str):
            candidate = bare_hex(art)
            if _is_hex64(candidate):
                out.append(("", candidate))
    return sorted(out, key=lambda item: (item[0], item[1]))


def _provenance_hash(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AttestationBundlePackager:
    """Сборка и фиксация attestation bundle релиза.

    Сервис stateless: единственный источник истины для чтения — ledger
    (``latest_attestation_bundle``), in-memory реестра нет.
    """

    # ── сбор свидетельств ────────────────────────────────────────────────

    async def _latest_manifest(
        self, session: AsyncSession, rel: ReleaseModel, release_digests: set[str],
    ) -> Optional[EvidenceLedgerEntry]:
        """Последний манифест COS-142, относящийся к релизу.

        Приоритет: pinned-набор манифеста покрывает digest артефакта релиза;
        иначе — манифест, заякоренный на один из прогонов релиза.
        """
        stmt = (
            select(EvidenceLedgerEntry)
            .where(EvidenceLedgerEntry.type == "decision")
            .where(
                EvidenceLedgerEntry.provenance_json["source"].astext
                == MANIFEST_SOURCE
            )
            .where(
                EvidenceLedgerEntry.provenance_json["manifest_type"].astext
                == MANIFEST_TYPE
            )
            .order_by(
                EvidenceLedgerEntry.created_at.desc(),
                EvidenceLedgerEntry.id.desc(),
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        run_ids = set(rel.run_ids or [])
        for row in rows:
            prov = row.provenance_json or {}
            row_run = prov.get("run_id") or row.run_id
            if row_run and run_ids and row_run not in run_ids:
                continue
            refs = [str(r) for r in (prov.get("canonical_refs") or [])]
            ref_hexes = {_ref_digest(r) for r in refs}
            if release_digests and ref_hexes & release_digests:
                return row
            if row_run and row_run in run_ids:
                return row
        return None

    async def _sbom_ledger_id(
        self, session: AsyncSession, release_id: str,
    ) -> Optional[str]:
        """ID последней SBOM-записи релиза (для audit-цепочки конверта)."""
        stmt = (
            select(EvidenceLedgerEntry.id)
            .where(EvidenceLedgerEntry.type == "decision")
            .where(
                EvidenceLedgerEntry.provenance_json["source"].astext
                == SBOM_SOURCE
            )
            .where(
                EvidenceLedgerEntry.provenance_json["release_id"].astext
                == release_id
            )
            .order_by(
                EvidenceLedgerEntry.created_at.desc(),
                EvidenceLedgerEntry.id.desc(),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

    # ── сборка ───────────────────────────────────────────────────────────

    async def build(
        self, session: AsyncSession, release_id: str,
    ) -> EvidenceAttestationBundle:
        """Собрать, верифицировать и зафиксировать attestation bundle релиза.

        Raises:
            ReleaseNotFoundError: релиз не существует (404).
            AttestationEvidenceError: нет digest'а субъекта или у релиза нет
                прогонов для якоря ledger-записи (422).
        """
        rel = await session.get(ReleaseModel, release_id)
        if rel is None:
            raise ReleaseNotFoundError(f"Release '{release_id}' not found")

        release_artifacts = _release_artifacts(rel)
        release_digests = {digest for _, digest in release_artifacts}

        manifest_row = await self._latest_manifest(session, rel, release_digests)
        manifest_prov: dict[str, Any] = (
            dict(manifest_row.provenance_json or {}) if manifest_row else {}
        )
        manifest_refs = [str(r) for r in (manifest_prov.get("canonical_refs") or [])]
        manifest_hexes = {_ref_digest(r) for r in manifest_refs}

        sbom = await latest_sbom_attestation(session, release_id)
        sbom_artifact_hex = (
            bare_hex(sbom.artifact_digest) if sbom and sbom.artifact_digest else None
        )

        clearance = await HubClearanceGateManager().latest_for_release(
            session, release_id,
        )

        # 1. Субъект: артефакт релиза → первый pinned артефакт манифеста → SBOM.
        subject_name: Optional[str] = None
        subject_hex: Optional[str] = None
        if release_artifacts:
            subject_name, subject_hex = release_artifacts[0]
        elif manifest_refs:
            head = manifest_refs[0]
            subject_hex = _ref_digest(head)
            subject_name = head.split(":", 1)[0]
        elif sbom_artifact_hex:
            subject_name, subject_hex = release_id, sbom_artifact_hex
        if not subject_hex or not _is_hex64(subject_hex):
            raise AttestationEvidenceError(
                f"Release '{release_id}' has no artifact digest to attest "
                "(no pinned artifact, no manifest, no SBOM attestation)"
            )
        if not subject_name:
            subject_name = release_id

        # 2. Chain of custody: digest субъекта обязан совпасть во всех
        #    собранных свидетельствах.
        mismatches: list[str] = []
        if manifest_refs and subject_hex not in manifest_hexes:
            mismatches.append(
                f"manifest canonical_refs do not cover subject digest "
                f"{subject_hex}"
            )
        if sbom_artifact_hex is not None and sbom_artifact_hex != subject_hex:
            mismatches.append(
                f"sbom artifact_digest {sbom_artifact_hex} != subject digest "
                f"{subject_hex}"
            )
        verified = bool(manifest_refs or sbom_artifact_hex) and not mismatches

        # 3. Конверт.
        subject = EvidenceAttestationSubject(
            name=subject_name, digest=f"sha256:{subject_hex}",
        )
        predicate = EvidenceAttestationPredicate(
            release_id=release_id,
            bundle_id=(manifest_prov.get("bundle_id") or None),
            profile=(manifest_prov.get("profile") or "unknown"),
            manifest_digest_pin=(manifest_prov.get("digest_pin") or None),
            sbom_digest=(sbom.sbom_digest if sbom else None),
            hub_clearance_status=(clearance.clearance_status if clearance else None),
            hub_evaluation_id=(clearance.evaluation_id if clearance else None),
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        root = compute_provenance_bundle_hash(subject, predicate)

        # 4. Крипто-якорь: первый прогон релиза (FK evidence_ledger.run_id).
        run_ids = [r for r in (rel.run_ids or []) if r]
        if not run_ids:
            raise AttestationEvidenceError(
                f"Release '{release_id}' has no runs to anchor attestation bundle"
            )
        run_id = run_ids[0]
        if await session.get(Run, run_id) is None:
            raise AttestationEvidenceError(
                f"Run '{run_id}' of release '{release_id}' not found to anchor "
                "attestation bundle"
            )

        bundle = EvidenceAttestationBundle(
            subject=subject,
            predicate=predicate,
            provenance_bundle_hash=root,
            verified=verified,
        )

        provenance: dict[str, Any] = {
            "source": ATTESTATION_SOURCE,
            "contract": ATTESTATION_CONTRACT,
            "attestation_type": ATTESTATION_TYPE,
            "release_id": release_id,
            "bundle_id": predicate.bundle_id,
            "profile": predicate.profile,
            "format": bundle.format,
            "subject": subject.model_dump(mode="json"),
            "predicate": predicate.model_dump(mode="json"),
            "provenance_bundle_hash": root,
            "verified": verified,
            "chain_of_custody": {
                "subject_digest": subject_hex,
                "manifest_ref_digests": sorted(manifest_hexes),
                "sbom_artifact_digest": sbom_artifact_hex,
                "mismatches": mismatches,
            },
            "evidence_ledger_ids": {
                "manifest": manifest_row.id if manifest_row else None,
                "sbom": await self._sbom_ledger_id(session, release_id),
                "clearance": clearance.ledger_entry_id if clearance else None,
            },
        }
        provenance["provenance_hash"] = _provenance_hash(provenance)

        entry = EvidenceLedgerEntry(
            run_id=run_id,
            batch_id=None,
            type="decision",
            content_ref=f"attestation://release/{release_id}/{root}",
            content_hash=bare_hex(root),
            provenance_json=provenance,
        )
        await commit_evidence_entry(session, entry)

        return bundle


def _bundle_from_provenance(
    provenance: dict, content_hash: Optional[str],
) -> EvidenceAttestationBundle | None:
    """Реконструировать attestation-конверт из ledger-provenance.

    Возвращает ``None``, если запись неполна/испорчена или root-хэш не
    сходится с пересчитанным ``compute_provenance_bundle_hash`` (и с durable
    ``content_hash``) — чтение честно отказывает вместо отдачи подделки.
    """
    try:
        bundle = EvidenceAttestationBundle(
            format=provenance.get("format", ATTESTATION_FORMAT),
            subject=EvidenceAttestationSubject.model_validate(
                provenance["subject"]
            ),
            predicate=EvidenceAttestationPredicate.model_validate(
                provenance["predicate"]
            ),
            provenance_bundle_hash=provenance["provenance_bundle_hash"],
            verified=bool(provenance["verified"]),
        )
    except (KeyError, TypeError, ValidationError):
        return None
    recomputed = compute_provenance_bundle_hash(bundle.subject, bundle.predicate)
    if recomputed != bundle.provenance_bundle_hash:
        return None
    if content_hash and content_hash != bare_hex(bundle.provenance_bundle_hash):
        return None
    return bundle


async def latest_attestation_bundle(
    session: AsyncSession, release_id: str,
) -> EvidenceAttestationBundle | None:
    """Актуальный attestation bundle релиза из ledger (latest wins).

    Единственный read-path: in-memory реестра нет, поэтому ответ переживает
    рестарт cosmo-api. ``None`` — конверт для релиза не собран.
    """
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == ATTESTATION_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["attestation_type"].astext
            == ATTESTATION_TYPE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["release_id"].astext == release_id
        )
        .order_by(
            EvidenceLedgerEntry.created_at.desc(),
            EvidenceLedgerEntry.id.desc(),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    return _bundle_from_provenance(
        dict(row.provenance_json or {}), row.content_hash,
    )
