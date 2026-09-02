"""COS-082: async write-path для durable evidence с запечатыванием цепочки.

Единственный канонический способ создать EvidenceLedgerEntry: якоря цепочки
(``_chain_prev_hash`` / ``_chain_hash`` в provenance_json) вычисляются при
записи и подписывают замороженный снапшот строки. Верификация потом сверяет
сохранённые якоря (evidence_chain.verify_rows) — подмена payload без
переподписи детектируется.

Миграционная цепочка заморожена — якоря живут в JSONB, новых колонок нет.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.ledger.evidence_anchor import publish_head
from orchestrator.cosmo.ledger.evidence_chain import EvidenceLedger


async def last_chain_hash(session: AsyncSession, run_id: str) -> str:
    """Последний запечатанный hash цепочки run'а (genesis, если пусто).

    Порядок тот же, что у verify: created_at asc, id asc — берём последнюю
    строку с якорем.
    """
    result = await session.execute(
        select(EvidenceLedgerEntry)
        .where(EvidenceLedgerEntry.run_id == run_id)
        .order_by(EvidenceLedgerEntry.created_at.desc(), EvidenceLedgerEntry.id.desc())
    )
    for row in result.scalars():
        stored_hash = (row.provenance_json or {}).get(EvidenceLedger.CHAIN_HASH_KEY)
        if stored_hash:
            return stored_hash
    return EvidenceLedger.GENESIS_HASH


async def append_evidence_entry(
    session: AsyncSession,
    entry: EvidenceLedgerEntry,
) -> str:
    """Запечатать и добавить evidence-строку в сессию (без commit — решает caller).

    Порядок критичен: flush применяет Python-side дефолты модели (id,
    created_at) — якорь подписывает снапшот ровно в том виде, в каком
    строка ляжет в PG. Изменение provenance_json после flush уйдёт в PG
    вторым statement'ом на commit. Возвращает entry_hash.
    """
    prev_hash = await last_chain_hash(session, entry.run_id)
    session.add(entry)
    await session.flush()  # id/created_at применены до подписи
    entry_hash = EvidenceLedger.seal_entry(entry, prev_hash)
    return entry_hash


async def commit_evidence_entry(
    session: AsyncSession,
    entry: EvidenceLedgerEntry,
) -> str:
    """Канонический write-path с внешним якорем головы (COS-087).

    append → flush → seal → commit → publish_head. Якорь публикуется
    ТОЛЬКО после commit: sink дополняется только durable-головами.
    Фейл публикации → исключение (якорь — часть контракта записи,
    fail visible; иначе verify потом честно скажет unknown_anchor).
    """
    entry_hash = await append_evidence_entry(session, entry)
    await session.commit()
    from orchestrator.cosmo.ledger.evidence_anchor import publish_head
    publish_head(entry.run_id, entry_hash, entry.id)
    return entry_hash
