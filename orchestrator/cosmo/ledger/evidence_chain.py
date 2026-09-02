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

    # ── COS-082: durable tamper detection (честная верификация) ──
    #
    # Проблема (открытие COS-080): verify_and_get пересчитывал хеши от
    # ТЕКУЩИХ строк БД — подмена любой строки (content_hash, content_ref,
    # provenance_json, type) становилась «легальной» головой цепочки, verify
    # всегда возвращал verified=True. Причина: durable-таблица вообще не
    # хранила chain-якорей — не с чем было сверять.
    #
    # Решение: якоря цепочки ЗАПЕЧАТЫВАЮТСЯ при записи в саму строку
    # (provenance_json["_chain_prev_hash"] / ["_chain_hash"]) — миграционная
    # цепочка заморожена, новых колонок нет. verify пересчитывает хеш
    # замороженного снапшота строки и сверяет его с СОХРАНЁННЫМ значением;
    # связность — stored prev_hash[i] == stored hash[i-1] (genesis "0"*64).
    # Подмена payload без пересчёта якоря → hash mismatch; удаление средней
    # строки → broken link у следующей; строка без якорей → unsealed
    # (честно: нет криптографического доказательства целостности).
    #
    # Threat model (честно): атакующий с полным доступом на запись может
    # пере-подписать весь суффикс цепочки — без внешнего якоря головы
    # (публикация last_hash вовне) это недетектируемо принципиально.
    # Детектируется всё, что не сопровождается полной переподписью.
    #
    # COS-087: граница закрыта — голова публикуется в append-only sink
    # (evidence_anchor, audit-file) ПОСЛЕ commit; verify сверяет фактическую
    # голову с внешним якорем: переподпись суффикса → head_mismatch
    # (отдельный статус), недоступный якорь → честный unknown_anchor.

    GENESIS_HASH = "0" * 64
    CHAIN_PREV_KEY = "_chain_prev_hash"
    CHAIN_HASH_KEY = "_chain_hash"

    @staticmethod
    def entry_snapshot(row: Any) -> dict[str, Any]:
        """Замороженный снапшот ORM-строки evidence — то, что подписывает якорь.

        Исключает сами якоря (иначе циклический хеш) и ВСЁ остальное берёт
        из сохранённых полей: подмена любого из них меняет снапшот.
        """
        provenance = dict(row.provenance_json) if row.provenance_json else {}
        provenance.pop(EvidenceLedger.CHAIN_PREV_KEY, None)
        provenance.pop(EvidenceLedger.CHAIN_HASH_KEY, None)
        return {
            "id": row.id,
            "run_id": row.run_id,
            "batch_id": row.batch_id,
            "type": row.type,
            "content_ref": row.content_ref,
            "content_hash": row.content_hash,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "provenance": provenance,
        }

    @staticmethod
    def compute_entry_hash(row: Any) -> str:
        """SHA-256 замороженного снапшота строки."""
        canonical = json.dumps(
            EvidenceLedger.entry_snapshot(row),
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def seal_entry(row: Any, prev_hash: str) -> str:
        """Запечатать строку: вписать якоря цепочки в provenance_json.

        Вызывать ПОСЛЕ установки всех payload-полей и ДО commit — якорь
        подписывает ровно то, что уйдёт в PG. Возвращает entry_hash.
        """
        provenance = dict(row.provenance_json) if row.provenance_json else {}
        provenance.pop(EvidenceLedger.CHAIN_PREV_KEY, None)
        provenance.pop(EvidenceLedger.CHAIN_HASH_KEY, None)
        row.provenance_json = provenance
        entry_hash = EvidenceLedger.compute_entry_hash(row)
        provenance[EvidenceLedger.CHAIN_PREV_KEY] = prev_hash
        provenance[EvidenceLedger.CHAIN_HASH_KEY] = entry_hash
        return entry_hash

    @staticmethod
    def verify_rows(rows: list[Any]) -> dict[str, Any]:
        """Верификация упорядоченных строк одного run против СОХРАНЁННЫХ якорей.

        Сверки (по порядку created_at, id):
          1. hash mismatch: sha256(снапшот строки) != stored _chain_hash
             → tampered (подмена payload без переподписи);
          2. link mismatch: stored _chain_prev_hash[i] != stored
             _chain_hash[i-1] (genesis для первой) → broken link
             (удаление/перестановка/вставка строки);
          3. unsealed: нет якорей → нет доказательства целостности.
        """
        tampered_entries: list[int] = []
        tampered_details: list[dict[str, Any]] = []
        broken_links: list[dict[str, Any]] = []
        unsealed_entries: list[str] = []
        seen_hashes: set[str] = set()
        replay_count = 0
        expected_prev = EvidenceLedger.GENESIS_HASH  # stored hash предыдущей строки

        for i, row in enumerate(rows):
            provenance = row.provenance_json or {}
            stored_prev = provenance.get(EvidenceLedger.CHAIN_PREV_KEY)
            stored_hash = provenance.get(EvidenceLedger.CHAIN_HASH_KEY)

            if stored_prev is None or stored_hash is None:
                unsealed_entries.append(row.id)
            else:
                recomputed = EvidenceLedger.compute_entry_hash(row)
                if recomputed != stored_hash:
                    tampered_entries.append(i)
                    tampered_details.append({
                        "index": i,
                        "entry_id": row.id,
                        "reason": "hash_mismatch",
                        "stored_hash": stored_hash,
                        "recomputed_hash": recomputed,
                    })

                if stored_prev != expected_prev:
                    broken_links.append({
                        "index": i,
                        "entry_id": row.id,
                        "expected_prev_hash": expected_prev,
                        "stored_prev_hash": stored_prev,
                    })

            # replay-детект: content-only fingerprint
            content_key = json.dumps({
                "type": row.type,
                "content_ref": row.content_ref or "",
                "content_hash": row.content_hash or "",
                "id": row.id,
            }, sort_keys=True, ensure_ascii=False)
            content_fp = hashlib.sha256(content_key.encode("utf-8")).hexdigest()
            if content_fp in seen_hashes:
                replay_count += 1
            seen_hashes.add(content_fp)

            expected_prev = stored_hash if stored_hash is not None else expected_prev

        return {
            "tampered_entries": tampered_entries,
            "tampered_details": tampered_details,
            "broken_links": broken_links,
            "unsealed_entries": unsealed_entries,
            "replay_count": replay_count,
        }

    # ── COS-060: verify_and_get ──

    @staticmethod
    def verify_and_get(
        db_session_factory: Any,
        run_id: str,
    ) -> dict[str, Any]:
        """Загрузить evidence-записи из PG и честно верифицировать (COS-082).

        Верификация идёт против СОХРАНЁННЫХ якорей цепочки (запечатаны при
        записи в provenance_json), а не пересчётом от текущих строк —
        подмена payload без переподписи детектируется.

        Returns dict:
          - chain: EvidenceLedger.to_dict() — rebuild-вид цепочки
          - verified: bool — якоря целы, связность не нарушена, все запечатаны,
            и (при включённом якоре) голова сходится с внешним якорем
          - integrity: "ok" | "tampered" | "unsealed" | "head_mismatch" (COS-087)
          - anchor: {enabled, status: ok|head_mismatch|unknown_anchor|disabled,
            anchored_head, computed_head, anchored_at, detail} — COS-087
          - head_mismatch: bool — расхождение с внешним якорем (COS-087)
          - tampered_entries: list[int] — индексы строк с hash mismatch
          - tampered_details: [{index, entry_id, reason, stored_hash,
            recomputed_hash}] — какое звено и чем расходится
          - broken_links: [{index, entry_id, expected_prev_hash,
            stored_prev_hash}] — нарушение связности (удаление/вставка)
          - unsealed_entries: list[str] — id строк без якорей
          - tampered_chain: bool — нарушена связность цепочки
          - replay_count: int — количество дубликатов
          - total_entries: int
        """
        from orchestrator.cosmo.db.models import EvidenceLedgerEntry as ELE
        from orchestrator.cosmo.ledger import evidence_anchor
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

        for i, row in enumerate(rows):
            content = (row.provenance_json or {}).copy()
            content.pop(EvidenceLedger.CHAIN_PREV_KEY, None)
            content.pop(EvidenceLedger.CHAIN_HASH_KEY, None)
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
            ledger._entries.append(EvidenceEntry(**entry_data, hash=entry_hash))
            ledger._last_hash = entry_hash

        # COS-082: верификация против СОХРАНЁННЫХ якорей (не от мутированных
        # строк): hash mismatch + broken link + unsealed + replay.
        report = EvidenceLedger.verify_rows(rows)

        tampered_chain = len(report["broken_links"]) > 0
        verified = (
            not tampered_chain
            and len(report["tampered_entries"]) == 0
            and len(report["unsealed_entries"]) == 0
        )

        # COS-087: computed head = СОХРАНЁННЫЙ _chain_hash последней
        # запечатанной строки (цепочка как она ЗАПЕЧАТАНА в PG, не rebuild-вид).
        computed_head = EvidenceLedger.GENESIS_HASH
        for row in rows:
            stored_hash = (row.provenance_json or {}).get(
                EvidenceLedger.CHAIN_HASH_KEY)
            if stored_hash:
                computed_head = stored_hash

        # COS-087: внешний якорь головы (append-only sink)
        anchor_info = evidence_anchor.read_head(run_id)
        anchor_status = anchor_info["status"]
        head_mismatch_flag = False
        if anchor_status == "ok":
            anchored_head = anchor_info.get("anchored_head")
            head_mismatch_flag = anchored_head != computed_head
            if head_mismatch_flag:
                # суффикс переподписан (или голова потеряна): internal
                # verify может быть чистым — внешнее доказательство расходится
                verified = False
                anchor_status = "head_mismatch"

        if report["tampered_entries"] or report["broken_links"]:
            integrity = "tampered"
        elif report["unsealed_entries"]:
            integrity = "unsealed"
        elif head_mismatch_flag:
            integrity = "head_mismatch"
        else:
            integrity = "ok"

        return {
            "chain": ledger.to_dict(),
            "verified": verified,
            "integrity": integrity,
            "tampered_entries": report["tampered_entries"],
            "tampered_details": report["tampered_details"],
            "broken_links": report["broken_links"],
            "unsealed_entries": report["unsealed_entries"],
            "tampered_chain": tampered_chain,
            "replay_count": report["replay_count"],
            "total_entries": len(ledger),
            # COS-087: внешний якорь головы
            "anchor": {
                "enabled": evidence_anchor.is_enabled(),
                "status": anchor_status,
                "anchored_head": anchor_info.get("anchored_head"),
                "computed_head": computed_head,
                "anchored_at": anchor_info.get("anchored_at"),
                "detail": anchor_info.get("detail"),
            },
            "head_mismatch": head_mismatch_flag,
        }

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> EvidenceEntry:
        return self._entries[index]