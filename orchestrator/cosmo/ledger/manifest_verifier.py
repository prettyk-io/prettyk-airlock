# -*- coding: utf-8 -*-
"""COS-142: PK-C-003.4 — верификация bundle manifest и digest-pin якорь.

Сервис ``BundleManifestVerifier``:

  1. считает детерминированный ``digest_pin`` бандла — SHA256 от канонического
     представления профиля и **отсортированных** ``canonical_ref`` всех
     артефактов (порядок артефактов в запросе на pin не влияет);
  2. сверяет pin с ``expected_digest_pin`` (если он задан);
  3. фиксирует проверенный манифест в ``evidence_ledger`` — запись
     ``type='decision'`` с маркером ``provenance_json.source`` и
     ``provenance_json.manifest_type == 'BUNDLE_MANIFEST'`` (конвенция гейтов
     COS-136/COS-138: enum ``evidence_type`` описывает *вид* evidence, а
     гейт-вердикты живут как ``decision`` + маркер источника);
  4. отклоняет манифесты с незакреплёнными версиями / тегом ``latest``.

Честные границы (документируем, не прячем):
  - ``run_id`` — NOT NULL FK на ``runs.id``, а у манифеста нет прогона; якорь
    приходит контекстом (``manifest.run_id``). Без него верификация валидна,
    но ledger-запись не создаётся (``ledger_entry_id=None``) — нечем якорить,
    и такой манифест **не читается** через GET (non-durable edge);
  - read-path (``latest_manifest``) — durable: актуальный якорь берётся из
    ``evidence_ledger`` по ``bundle_id`` (latest wins), in-memory реестра нет.
    Рестарт cosmo-api не теряет read-ответ.
"""
from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry, Run
from orchestrator.cosmo.domain.artifact_manifest import (
    FORBIDDEN_TAG,
    ArtifactBundleManifest,
    CanonicalArtifactTag,
    ManifestVerificationResult,
    manifest_content_hash,
    normalize_digest_pin,
)
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Маркер источника записи в ``provenance_json``.
MANIFEST_SOURCE = "cosmo-manifest-verifier"

#: Маркер типа записи (``provenance_json.manifest_type``) — «тип записи
#: BUNDLE_MANIFEST» из PK-C-003.4.
MANIFEST_TYPE = "BUNDLE_MANIFEST"

#: Контракт, которому подчиняется манифест.
MANIFEST_CONTRACT = "PK-C-003.4"


def compute_digest_pin(profile: str, canonical_refs: list[str]) -> str:
    """Детерминированный digest-pin бандла.

    ``sha256("profile=<profile>;artifacts=<sorted refs, comma-joined>")`` в
    каноническом виде ``sha256:<hex>``. Сортировка внутри — поэтому порядок
    артефактов в запросе на pin не влияет.
    """
    payload = f"profile={profile};artifacts={','.join(sorted(canonical_refs))}"
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provenance_hash(payload: dict) -> str:
    """Канонический sha256 provenance (sort_keys, compact) — тампер-якорь."""
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class BundleManifestVerifier:
    """Верификация манифеста бандла + фиксация вердикта в evidence ledger.

    Сервис stateless: единственный источник истины для чтения — ledger
    (``latest_manifest``), in-memory реестра нет.
    """

    async def verify(
        self,
        session: AsyncSession,
        manifest: ArtifactBundleManifest,
    ) -> ManifestVerificationResult:
        """Проверить манифест, посчитать digest_pin и зафиксировать вердикт."""
        refs = manifest.canonical_refs()
        digest_pin = compute_digest_pin(manifest.profile, refs)
        errors: list[str] = []

        # 1. Defence-in-depth поверх DTO-валидаторов: плавающие теги.
        for tag in manifest.artifacts:
            if FORBIDDEN_TAG in tag.version.lower():
                errors.append(
                    f"unpinned artifact '{tag.name}': floating tag "
                    f"'{tag.version}' is forbidden"
                )
        if FORBIDDEN_TAG in manifest.release_version.lower():
            errors.append(
                f"unpinned release_version '{manifest.release_version}'"
            )

        # 2. Сверка с ожидаемым digest-pin (расхождение → вердикт, не 5xx).
        if manifest.expected_digest_pin is not None:
            expected = normalize_digest_pin(manifest.expected_digest_pin)
            if expected != digest_pin:
                errors.append(
                    f"digest_pin mismatch: expected={expected} "
                    f"computed={digest_pin}"
                )

        if errors:
            return ManifestVerificationResult(
                valid=False,
                bundle_id=manifest.bundle_id,
                digest_pin=digest_pin,
                artifacts_count=len(manifest.artifacts),
                errors=errors,
                ledger_entry_id=None,
            )

        # 3. Якорь ledger — только при наличии прогона (FK NOT NULL).
        ledger_entry_id: str | None = None
        if manifest.run_id is not None:
            run = await session.get(Run, manifest.run_id)
            if run is None:
                return ManifestVerificationResult(
                    valid=False,
                    bundle_id=manifest.bundle_id,
                    digest_pin=digest_pin,
                    artifacts_count=len(manifest.artifacts),
                    errors=[
                        f"run '{manifest.run_id}' not found to anchor "
                        "ledger entry"
                    ],
                    ledger_entry_id=None,
                )

            content_hash = manifest_content_hash(manifest)
            provenance = {
                "source": MANIFEST_SOURCE,
                "contract": MANIFEST_CONTRACT,
                "manifest_type": MANIFEST_TYPE,
                "bundle_id": manifest.bundle_id,
                "release_version": manifest.release_version,
                "profile": manifest.profile,
                # Полный набор артефактов + ожидаемый pin: read-path
                # реконструирует манифест из ledger без потерь.
                "artifacts": [
                    art.model_dump(mode="json") for art in manifest.artifacts
                ],
                "expected_digest_pin": manifest.expected_digest_pin,
                "digest_pin": digest_pin,
                "artifacts_count": len(manifest.artifacts),
                "canonical_refs": refs,
                "manifest_hash": content_hash,
                "run_id": manifest.run_id,
                "created_at": manifest.created_at,
            }
            provenance["provenance_hash"] = _provenance_hash(provenance)

            entry = EvidenceLedgerEntry(
                run_id=manifest.run_id,
                batch_id=None,
                type="decision",
                content_ref=f"bundle://{manifest.bundle_id}/manifest/{digest_pin}",
                content_hash=content_hash,
                provenance_json=provenance,
            )
            await commit_evidence_entry(session, entry)
            ledger_entry_id = entry.id

        return ManifestVerificationResult(
            valid=True,
            bundle_id=manifest.bundle_id,
            digest_pin=digest_pin,
            artifacts_count=len(manifest.artifacts),
            errors=[],
            ledger_entry_id=ledger_entry_id,
        )


def _tag_from_ref(ref: str) -> CanonicalArtifactTag:
    """Восстановить canonical tag из ``<name>:<version>@sha256:<hex>``.

    Fallback для ledger-записей, сделанных до появления ``artifacts`` в
    provenance. Формат строгий (slug без ``:``), поэтому разбор однозначен.
    """
    left, _, digest = ref.rpartition("@")
    name, _, version = left.partition(":")
    return CanonicalArtifactTag(name=name, version=version, digest=digest)


def _manifest_from_provenance(
    provenance: dict,
) -> ArtifactBundleManifest | None:
    """Реконструировать подтверждённый манифест из ledger-provenance.

    Возвращает ``None``, если запись неполна/испорчена или крипто-якорь
    (``content_hash``) не сходится с пересчитанным ``manifest_content_hash``
    — чтение честно отказывает вместо отдачи непроверенных данных.
    """
    try:
        raw_artifacts = provenance.get("artifacts")
        if raw_artifacts:
            artifacts = [
                CanonicalArtifactTag.model_validate(art) for art in raw_artifacts
            ]
        else:
            artifacts = [
                _tag_from_ref(str(ref))
                for ref in (provenance.get("canonical_refs") or [])
            ]
        manifest = ArtifactBundleManifest(
            bundle_id=provenance["bundle_id"],
            release_version=provenance["release_version"],
            profile=provenance["profile"],
            artifacts=artifacts,
            expected_digest_pin=provenance.get("expected_digest_pin"),
            created_at=provenance["created_at"],
            run_id=provenance.get("run_id"),
        )
    except (KeyError, TypeError, ValidationError):
        return None
    if manifest_content_hash(manifest) != provenance.get("manifest_hash"):
        return None
    return manifest


async def latest_manifest(
    session: AsyncSession, bundle_id: str,
) -> ArtifactBundleManifest | None:
    """Актуальный подтверждённый манифест бандла из ledger (latest wins).

    Единственный read-path: in-memory реестра нет, поэтому ответ переживает
    рестарт cosmo-api. ``None`` — манифест не якорён (non-durable edge).
    """
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext == MANIFEST_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["manifest_type"].astext
            == MANIFEST_TYPE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["bundle_id"].astext == bundle_id
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
    return _manifest_from_provenance(dict(row.provenance_json or {}))
