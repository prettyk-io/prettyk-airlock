"""
COS-005: EvidenceChain — иммутабельный append-only криптографический лог.

EvidenceLedger — append-only лог с SHA-256 хешированием каждой записи
и возможностью проверки целостности всей цепочки.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceEntry:
    """Одна запись в Evidence Ledger — иммутабельна."""
    index: int
    timestamp: float
    type: str
    content: dict[str, Any]
    provenance: str  # источник (run_id, batch_id, module)
    prev_hash: str
    hash: str


class EvidenceLedger:
    """Иммутабельный append-only лог с SHA-256."""

    def __init__(self) -> None:
        self._entries: list[EvidenceEntry] = []
        self._last_hash = "0" * 64  # genesis hash

    @property
    def entries(self) -> tuple[EvidenceEntry, ...]:
        """Все записи (read-only)."""
        return tuple(self._entries)

    @property
    def length(self) -> int:
        """Количество записей."""
        return len(self._entries)

    def add_entry(
        self, type: str, content: dict[str, Any], provenance: str,
    ) -> EvidenceEntry:
        """Добавляет запись в лог с хешированием."""
        ts = time.time()
        entry_data = {
            "index": len(self._entries),
            "timestamp": ts,
            "type": type,
            "content": content,
            "provenance": provenance,
            "prev_hash": self._last_hash,
        }
        entry_hash = self._hash_entry(entry_data)

        entry = EvidenceEntry(
            index=entry_data["index"],
            timestamp=ts,
            type=type,
            content=content,
            provenance=provenance,
            prev_hash=self._last_hash,
            hash=entry_hash,
        )
        self._entries.append(entry)
        self._last_hash = entry_hash
        return entry

    def verify_chain(self) -> bool:
        """Проверяет целостность всей цепочки."""
        expected_prev = "0" * 64
        for i, entry in enumerate(self._entries):
            if entry.index != i:
                return False
            if entry.prev_hash != expected_prev:
                return False
            recalc_data = {
                "index": entry.index,
                "timestamp": entry.timestamp,
                "type": entry.type,
                "content": entry.content,
                "provenance": entry.provenance,
                "prev_hash": entry.prev_hash,
            }
            recalc_hash = self._hash_entry(recalc_data)
            if recalc_hash != entry.hash:
                return False
            expected_prev = entry.hash
        return True

    def tamper(self, index: int, field: str, value: Any) -> None:
        """Только для тестирования: портит запись для проверки verify_chain."""
        if 0 <= index < len(self._entries):
            entry = self._entries[index]
            modified = dict(vars(entry))
            modified[field] = value
            self._entries[index] = EvidenceEntry(**modified)

    @staticmethod
    def _hash_entry(data: dict) -> str:
        """SHA-256 хеш записи."""
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """Сериализация в dict (для экспорта/API)."""
        return {
            "entries": [
                {
                    "index": e.index,
                    "timestamp": e.timestamp,
                    "type": e.type,
                    "content": e.content,
                    "provenance": e.provenance,
                    "prev_hash": e.prev_hash,
                    "hash": e.hash,
                }
                for e in self._entries
            ],
            "length": len(self._entries),
            "verified": self.verify_chain(),
            "last_hash": self._last_hash,
        }

    # ── COS-060: verify_and_get ──

    @staticmethod
    def verify_and_get(
        db_session_factory: Any,
        run_id: str,
    ) -> dict[str, Any]:
        """Загрузить evidence-записи из PG, перестроить цепочку, проверить.

        Returns dict:
          - chain: EvidenceLedger.to_dict()
          - verified: bool
          - tampered_entries: list[int] — индексы записей с нарушенным хешем
          - tampered_chain: bool — нарушена целостность цепочки (prev_hash mismatch)
          - replay_count: int — количество дубликатов
          - total_entries: int
        """
        from orchestrator.cosmo.db.models import EvidenceLedgerEntry as ELE
        import datetime as dt

        s = db_session_factory()
        try:
            rows = (
                s.query(ELE)
                .filter(ELE.run_id == run_id)
                .order_by(ELE.created_at.asc(), ELE.id.asc())
                .all()
            )
        finally:
            s.close()

        ledger = EvidenceLedger()
        tampered_entries: list[int] = []
        tampered_chain = False
        seen_hashes: set[str] = set()
        replay_count = 0

        for i, row in enumerate(rows):
            content = row.provenance_json.copy() if row.provenance_json else {}
            content["content_ref"] = row.content_ref or ""
            content["content_hash"] = row.content_hash or ""
            content["type"] = row.type

            provenance = f"{row.run_id}/{row.batch_id or 'no-batch'}/{row.id}"

            entry_data = {
                "index": i,
                "timestamp": row.created_at.timestamp() if row.created_at else 0.0,
                "type": row.type,
                "content": content,
                "provenance": provenance,
                "prev_hash": ledger._last_hash,
            }
            entry_hash = EvidenceLedger._hash_entry(entry_data)

            # Replay detection: content-only (без index/prev_hash) — одинаковый
            # контент с одинаковым provenance = replay
            content_key = json.dumps({
                "type": row.type,
                "content_ref": row.content_ref or "",
                "content_hash": row.content_hash or "",
                "provenance": provenance,
            }, sort_keys=True, ensure_ascii=False)
            content_fp = hashlib.sha256(content_key.encode("utf-8")).hexdigest()
            if content_fp in seen_hashes:
                replay_count += 1
            seen_hashes.add(content_fp)

            ledger._entries.append(EvidenceEntry(**entry_data, hash=entry_hash))
            ledger._last_hash = entry_hash

        # Verify chain integrity
        expected_prev = "0" * 64
        for i, entry in enumerate(ledger._entries):
            if entry.index != i:
                tampered_chain = True
                break
            if entry.prev_hash != expected_prev:
                tampered_chain = True
                break
            recalc = EvidenceLedger._hash_entry({
                "index": entry.index,
                "timestamp": entry.timestamp,
                "type": entry.type,
                "content": entry.content,
                "provenance": entry.provenance,
                "prev_hash": entry.prev_hash,
            })
            if recalc != entry.hash:
                tampered_entries.append(i)
            expected_prev = entry.hash

        verified = not tampered_chain and len(tampered_entries) == 0

        return {
            "chain": ledger.to_dict(),
            "verified": verified,
            "tampered_entries": tampered_entries,
            "tampered_chain": tampered_chain,
            "replay_count": replay_count,
            "total_entries": len(ledger),
        }

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> EvidenceEntry:
        return self._entries[index]