# -*- coding: utf-8 -*-
"""COS-148: офлайн-верификатор целостности airgap-бандла.

Проверка полностью автономна: два списка чексумм (манифест и наблюдаемый
архив) сравниваются в памяти, **без сетевых вызовов**. Вердикт:

  - ``missing_files`` — файлы манифеста, отсутствующие в архиве;
  - ``corrupted_files`` — SHA256 или размер разошлись;
  - ``unregistered_files`` — файлы архива вне манифеста;
  - ``errors`` — расхождение ``package_digest_pin`` и дубли имён.

``package_digest_pin`` пересчитывается из ``manifest.files`` (SHA256 от
отсортированных ``filename:sha256:size``) и сверяется с заявленным в
манифесте — порядок файлов на pin не влияет.

**Крипто-якорь:** вердикт фиксируется в ``evidence_ledger`` (``type='decision'``,
маркер ``provenance_json.airgap_type='AIRGAP_VERIFIED'``). Записывается и
проваленный вердикт: проваленная проверка импорта — это ровно то, что должно
остаться в журнале доказательств.

Честная граница: ``run_id`` — NOT NULL FK на ``runs.id``, а у airgap-пакета
прогона нет. Якорь берётся у локального релиза пакета (``release_id`` →
``run_ids[0]``); если релиза/прогонов локально нет (чистый офлайн-контур),
вердикт считается, но ledger-запись не создаётся — якорить нечем, и такой
пакет **не читается** через GET (честный non-durable edge, без фейкового
ответа).

Read-path (``latest_airgap_status``) — durable: актуальный вердикт берётся из
``evidence_ledger`` по ``package_id`` (latest wins), in-memory реестра нет.
Рестарт cosmo-api не теряет read-ответ.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import (
    EvidenceLedgerEntry,
    Release as ReleaseModel,
    Run,
)
from orchestrator.cosmo.domain.airgap_bundle import (
    AirgapFileChecksum,
    AirgapVerifyRequest,
    AirgapVerifyResponse,
    normalize_sha256,
)
from orchestrator.cosmo.ledger.evidence_chain import EvidenceLedger
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

#: Маркер источника записи в provenance_json.
AIRGAP_SOURCE = "cosmo-airgap-verifier"

#: Маркер типа записи (``provenance_json.airgap_type``).
AIRGAP_TYPE = "AIRGAP_VERIFIED"

#: Контракт, которому подчиняется пакет.
AIRGAP_CONTRACT = "PK-C-003.4"


def compute_package_digest_pin(files: list[AirgapFileChecksum]) -> str:
    """Детерминированный digest-pin пакета.

    ``sha256(",".join(sorted("filename:sha256:size")))`` в каноническом виде
    ``sha256:<hex>``. Сортировка внутри — порядок файлов на pin не влияет.
    """
    entries = sorted(
        f"{f.filename}:{f.normalized_sha256()}:{f.size_bytes}" for f in files
    )
    payload = ",".join(entries)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provenance_hash(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compare_archive(
    manifest_files: list[AirgapFileChecksum],
    archive_files: list[AirgapFileChecksum],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Чистое сравнение манифеста и архива (без БД и сети).

    Возвращает ``(missing, corrupted, unregistered, errors)``.
    """
    errors: list[str] = []
    expected = {f.filename: f for f in manifest_files}
    observed = {f.filename: f for f in archive_files}
    if len(expected) != len(manifest_files):
        errors.append("duplicate filenames in manifest")
    if len(observed) != len(archive_files):
        errors.append("duplicate filenames in archive")

    missing = sorted(set(expected) - set(observed))
    unregistered = sorted(set(observed) - set(expected))
    corrupted = sorted(
        name
        for name in set(expected) & set(observed)
        if expected[name].normalized_sha256() != observed[name].normalized_sha256()
        or expected[name].size_bytes != observed[name].size_bytes
    )
    return missing, corrupted, unregistered, errors


class AirgapBundleVerifier:
    """Офлайн-верификация целостности airgap-пакета + фиксация вердикта.

    Сервис stateless: единственный источник истины для чтения — ledger
    (``latest_airgap_status``), in-memory реестра нет.
    """

    async def _anchor_run(
        self, session: AsyncSession, release_id: str,
    ) -> Optional[str]:
        """Прогон для якоря ledger-записи (первый прогон локального релиза)."""
        rel = await session.get(ReleaseModel, release_id)
        if rel is None:
            return None
        for run_id in (rel.run_ids or []):
            if run_id and await session.get(Run, run_id) is not None:
                return run_id
        return None

    async def verify(
        self, session: AsyncSession, request: AirgapVerifyRequest,
    ) -> AirgapVerifyResponse:
        """Проверить целостность архива по манифесту и зафиксировать вердикт."""
        manifest = request.manifest

        expected_pin = f"sha256:{normalize_sha256(manifest.package_digest_pin)}"
        computed_pin = compute_package_digest_pin(manifest.files)
        errors: list[str] = []
        if expected_pin != computed_pin:
            errors.append(
                f"package_digest_pin mismatch: manifest={expected_pin} "
                f"computed={computed_pin}"
            )

        missing, corrupted, unregistered, compare_errors = compare_archive(
            manifest.files, request.archive_files,
        )
        errors.extend(compare_errors)

        verified = not (missing or corrupted or unregistered or errors)
        response = AirgapVerifyResponse(
            verified=verified,
            package_id=manifest.package_id,
            missing_files=missing,
            corrupted_files=corrupted,
            unregistered_files=unregistered,
            errors=errors,
        )

        run_id = await self._anchor_run(session, manifest.release_id)
        if run_id is not None:
            provenance = {
                "source": AIRGAP_SOURCE,
                "contract": AIRGAP_CONTRACT,
                "airgap_type": AIRGAP_TYPE,
                "package_id": manifest.package_id,
                "release_id": manifest.release_id,
                "manifest_created_at": manifest.created_at,
                "package_digest_pin": expected_pin,
                "computed_digest_pin": computed_pin,
                "verified": verified,
                "files_expected": len(manifest.files),
                "files_observed": len(request.archive_files),
                "missing_files": missing,
                "corrupted_files": corrupted,
                "unregistered_files": unregistered,
                "errors": errors,
            }
            provenance["provenance_hash"] = _provenance_hash(provenance)

            entry = EvidenceLedgerEntry(
                run_id=run_id,
                batch_id=None,
                type="decision",
                content_ref=(
                    f"airgap://{manifest.package_id}/{computed_pin}"
                ),
                content_hash=normalize_sha256(computed_pin),
                provenance_json=provenance,
            )
            await commit_evidence_entry(session, entry)

        return response


async def latest_airgap_status(
    session: AsyncSession, package_id: str,
) -> AirgapVerifyResponse | None:
    """Актуальный вердикт проверки airgap-пакета из ledger (latest wins).

    Единственный read-path: in-memory реестра нет, поэтому ответ переживает
    рестарт cosmo-api. ``None`` — пакет не якорён (non-durable edge: у пакета
    не было локального релиза/прогона, якорить нечем).
    """
    stmt = (
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.type == "decision")
        .where(
            EvidenceLedgerEntry.provenance_json["source"].astext == AIRGAP_SOURCE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["airgap_type"].astext
            == AIRGAP_TYPE
        )
        .where(
            EvidenceLedgerEntry.provenance_json["package_id"].astext == package_id
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
    prov = dict(row.provenance_json or {})
    # Integrity: пересобрать provenance_hash без самого поля и без якорей
    # цепочки (evidence_writer.seal_entry добавляет _chain_* ПОСЛЕ подписи).
    stored = prov.pop("provenance_hash", None)
    if stored:
        payload = {
            k: v
            for k, v in prov.items()
            if k not in (EvidenceLedger.CHAIN_HASH_KEY, EvidenceLedger.CHAIN_PREV_KEY)
        }
        if _provenance_hash(payload) != stored:
            return None
    try:
        return AirgapVerifyResponse(
            verified=bool(prov["verified"]),
            package_id=str(prov.get("package_id") or package_id),
            missing_files=[str(x) for x in (prov.get("missing_files") or [])],
            corrupted_files=[str(x) for x in (prov.get("corrupted_files") or [])],
            unregistered_files=[
                str(x) for x in (prov.get("unregistered_files") or [])
            ],
            errors=[str(x) for x in (prov.get("errors") or [])],
        )
    except (KeyError, TypeError):
        return None
