# -*- coding: utf-8 -*-
"""COS-162: durable-якорь docker_build dig'est (registry_audit Evidence).

Канонический push собранного образа фиксируется в Evidence Ledger неизменяемой
записью: digest — immutable identity образа, chain-of-custody от push до
deploy. Это закрывает «digest durable + переживает рестарт» в COS-162.

Полная durable-схема digest/manifest/SBOM (отдельные PG-таблицы + GAP-режим)
— COS-163 (следующий packet); здесь только Evidence-якорь push по образцу
``registry_audit``: ``type='decision'`` + маркер в ``provenance_json``
(конвенция COS-138/141/142 — цепочка миграций заморожена, ``evidence_type``
не расширяем).

Якорь пишется строго через канонический ``commit_evidence_entry``
(append → seal → commit → publish_head) — запись переживает рестарт
cosmo-api и верифицируется ``evidence_chain.verify_rows``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.domain.docker_build import DockerBuildResult

#: Маркер provenance для registry_audit (не новый PG-ENUM — заморожен).
REGISTRY_AUDIT_SOURCE = "cosmo-registry-audit"


def _audit_content_hash(result: DockerBuildResult) -> str:
    """SHA-256 канонического представления push-события (detерминированный).

    sort_keys + compact — тот же приём, что ``manifest_content_hash`` (COS-142)
    и ``sbom_content_hash`` (COS-138): подпись замороженного представления.
    """
    payload = json.dumps(
        {
            "image_name": result.image_name,
            "version": result.version,
            "digest": result.digest,
            "registry": result.registry,
            "repository": result.repository,
            "namespace": result.namespace,
            "metadata": result.metadata or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def record_registry_push(
    session: AsyncSession,
    result: DockerBuildResult,
    *,
    run_id: str,
    batch_id: Optional[str] = None,
) -> str:
    """Зафиксировать docker_build push в Evidence Ledger (durable).

    Возвращает entry id. ``run_id`` — NOT NULL FK на ``runs.id``; без
    прогона запись якорить нечем (честная граница COS-142/148).
    """
    from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry

    content_hash = _audit_content_hash(result)
    entry = EvidenceLedgerEntry(
        run_id=run_id,
        batch_id=batch_id,
        type="decision",
        content_ref=f"oci://{result.qualified_image()}@{result.digest}",
        content_hash=content_hash,
        provenance_json={
            "source": REGISTRY_AUDIT_SOURCE,
            "audit_type": "registry_push",
            "image_name": result.image_name,
            "version": result.version,
            "digest": result.digest,
            "canonical_ref": result.canonical_ref(),
            "registry": result.registry,
            "repository": result.repository,
            "namespace": result.namespace,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "metadata": result.metadata or {},
        },
    )
    return await commit_evidence_entry(session, entry)