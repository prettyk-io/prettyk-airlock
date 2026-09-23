# -*- coding: utf-8 -*-
"""COS-163: durable write + read-through метаданных артефакта (build → registry).

Закрывает гэп «build → artifact metadata в никуда»: канонический push образа
фиксируется неизменяемой записью в Evidence Ledger (``type='decision'``),
которая охватывает digest + OCI-manifest + SBOM-ссылку. Чтение — только из
durable-источника (``latest_artifact_record``), in-memory реестра нет: ответ
переживает рестарт cosmo-api.

Конвенции (не новый PG-ENUM — миграционная цепочка заморожена):
  - ``type='decision'`` (вид evidence: гейт/вердикт/запись);
  - ``provenance_json.source == 'cosmo-artifact-record'``;
  - ``provenance_json.artifact_type == 'ARTIFACT_RECORD'``;
  - крипто-якорь ``content_hash`` = ``artifact_record_content_hash``.

Якорь пишется строго через канонический ``commit_evidence_entry``
(append → seal → commit → publish_head) — запись переживает рестарт и
верифицируется ``evidence_chain.verify_rows``. ``run_id`` — NOT NULL FK на
``runs.id``: без прогона запись якорить нечем (честная граница COS-142/148).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry, Run
from orchestrator.cosmo.domain.artifact_record import (
    ArtifactRecord,
    artifact_record_content_hash,
)

#: Маркер источника записи в ``provenance_json``.
ARTIFACT_RECORD_SOURCE = "cosmo-artifact-record"

#: Маркер типа записи (``provenance_json.artifact_type``).
ARTIFACT_RECORD_TYPE = "ARTIFACT_RECORD"


async def record_artifact_record(
    session: AsyncSession,
    record: ArtifactRecord,
) -> str:
    """Зафиксировать durable-метаданные артефакта в Evidence Ledger.

    Возвращает entry id. Требует ``record.run_id`` (NOT NULL FK на ``runs.id``):
    без прогона якорить нечем — честно поднимаем ``ValueError``, а не пишем
    «в никуда» (this is the batch-loop closure: metadata never falls apart).
    """
    from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

    if not record.run_id:
        raise ValueError(
            "artifact record requires run_id to anchor the ledger entry "
            "(not in-memory, not a puddle)"
        )
    run = await session.get(Run, record.run_id)
    if run is None:
        raise ValueError(
            f"run '{record.run_id}' not found to anchor artifact record"
        )

    content_hash = artifact_record_content_hash(record)
    entry = EvidenceLedgerEntry(
        run_id=record.run_id,
        batch_id=record.batch_id,
        type="decision",
        content_ref=f"oci://{record.qualified_image()}@{record.digest}",
        content_hash=content_hash,
        provenance_json={
            "source": ARTIFACT_RECORD_SOURCE,
            "artifact_type": ARTIFACT_RECORD_TYPE,
            "name": record.name,
            "version": record.version,
            "digest": record.digest,
            "canonical_ref": record.canonical_ref(),
            "registry": record.registry,
            "repository": record.repository,
            "namespace": record.namespace,
            "manifest": record.manifest or {},
            "sbom_ref": record.sbom_ref,
            "record_hash": content_hash,
            "run_id": record.run_id,
            "batch_id": record.batch_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return await commit_evidence_entry(session, entry)


def _record_from_provenance(provenance: dict) -> ArtifactRecord | None:
    """Реконструировать запись из ledger-provenance с проверкой целостности.

    Возвращает ``None``, если запись неполна/испорчена или крипто-якорь
    (``content_hash``) не сходится с пересчитанным — чтение честно отказывает
    вместо отдачи непроверенных данных.
    """
    try:
        record = ArtifactRecord(
            name=provenance["name"],
            version=provenance["version"],
            digest=provenance["digest"],
            registry=provenance["registry"],
            repository=provenance.get("repository", "cosmoport"),
            namespace=provenance.get("namespace", "zr"),
            manifest=provenance.get("manifest") or None,
            sbom_ref=provenance.get("sbom_ref"),
            run_id=provenance.get("run_id"),
            batch_id=provenance.get("batch_id"),
        )
    except (KeyError, TypeError, ValidationError):
        return None
    if artifact_record_content_hash(record) != provenance.get("record_hash"):
        return None
    return record


async def latest_artifact_record(
    session: AsyncSession,
    name: str,
    version: str,
) -> ArtifactRecord | None:
    """Актуальная durable-запись артефакта из ledger (latest wins).

    Единственный read-path: in-memory реестра нет, поэтому ответ переживает
    рестарт cosmo-api. ``None`` — записи нет (non-durable edge).
    """
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == ARTIFACT_RECORD_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["artifact_type"].astext
            == ARTIFACT_RECORD_TYPE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["name"].astext == name
        )
        .where(
            EvidenceLedgerEntry.provenance_json["version"].astext == version
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
    return _record_from_provenance(dict(row.provenance_json or {}))


async def artifact_records_for_run_ids(
    session: AsyncSession,
    run_ids: list[str],
) -> list[ArtifactRecord]:
    """Durable-артефакты, собранные в конкретных прогонах (COS-165 source).

    Deploy резолвит образ по ``run_id``-ссылке (записанной runtime-hook'ом
    COS-164) — ровно тот digest, что реально собрался/запушился в этих
    прогонах, а не «последний в зоне». Целостность: повреждённый
    ``record_hash`` отсеивается ``_record_from_provenance`` (None → пропуск).

    COS-167 dedupe: SBOM-шаг перезаписывает запись артефакта (проставляя
    ``sbom_ref``) и создаёт тем самым вторую строку с тем же
    ``(name, version, digest)``. Возвращаем latest-per-``(name, version)`` —
    deploy не материализует образ дважды.
    """
    if not run_ids:
        return []
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext
            == ARTIFACT_RECORD_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["artifact_type"].astext
            == ARTIFACT_RECORD_TYPE
        )
        .where(EvidenceLedgerEntry.run_id.in_(run_ids))
        .order_by(
            EvidenceLedgerEntry.created_at.desc(),
            EvidenceLedgerEntry.id.desc(),
        )
    )
    rows = (await session.execute(stmt)).scalars().all()
    records: list[ArtifactRecord] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        record = _record_from_provenance(dict(row.provenance_json or {}))
        if record is None:
            continue
        identity = (record.name, record.version)
        if identity in seen:
            continue
        seen.add(identity)
        records.append(record)
    return records


__all__ = [
    "ARTIFACT_RECORD_SOURCE",
    "ARTIFACT_RECORD_TYPE",
    "record_artifact_record",
    "latest_artifact_record",
    "artifact_records_for_run_ids",
]