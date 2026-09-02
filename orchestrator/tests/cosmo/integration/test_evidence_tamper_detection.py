"""COS-082/087: честный tamper-детект на durable evidence ledger.

Подмена/удаление evidence-строки в PG (в обход API) детектируется verify:
верификация сверяет СОХРАНЁННЫЕ якоря цепочки (запечатаны при записи),
а не пересчитывает хеши от мутированных строк (ограничение COS-080 закрыто).

COS-087: граница threat model закрыта внешним append-only якорем головы —
переподпись суффикса (payload + якоря вместе) детектируется как
head_mismatch: internal verify чист, но фактическая голова расходится
с внешним доказательством (evidence_anchor, audit-file sink).

Запуск: тестовый PG :5433 (docker compose -f services/docker-compose.test-pg.yml up -d).
"""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select, text

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.db.session import get_sessionmaker
from orchestrator.cosmo.ledger.evidence_chain import EvidenceLedger
from orchestrator.cosmo.ledger import evidence_anchor

from test_steel_thread_integration import (
    DOM, _H, _add_evidence, _compile, _create_app, _create_bricks,
    _create_domain, _create_run,
)

pytestmark = pytest.mark.asyncio


async def _ensure_domain(h) -> None:
    """Идемпотентное создание домена сьюта (201 или уже существует 409)."""
    r = await h.client.post("/api/v1/domains", json={
        "id": DOM,
        "label": "Integration Steel Thread Domain",
        "forge_binding": {
            "forge_type": "gitea",
            "url": "https://gitea.integration.example",
            "token_ref": "vault://integration/token",
        },
        "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
    })
    assert r.status_code in (201, 409), r.text


async def _setup_run_with_chain(h, run_id: str, n_entries: int = 3) -> list[str]:
    """Домен → app → bricks → compile → run → n запечатанных evidence-строк.

    Возвращает id созданных evidence-строк в порядке цепочки.
    """
    await _ensure_domain(h)
    app_id = f"{run_id}-app"
    await _create_app(h, DOM, app_id)
    brick_ids = await _create_bricks(h, prefix=run_id)
    await _compile(h, app_id, brick_ids, plan_id=f"{run_id}-plan")
    await _create_run(h, DOM, f"{run_id}-plan", run_id=run_id)

    entry_ids: list[str] = []
    for i in range(n_entries):
        entry = await _add_evidence(
            h, run_id, None, "log", f"minio://{run_id}/art-{i}",
            f"payload-{i}".encode(),
        )
        entry_ids.append(entry.id)
    return entry_ids


async def _get_evidence(h, run_id: str) -> dict:
    r = await h.client.get(f"/api/v1/runs/{run_id}/evidence", headers=_H())
    assert r.status_code == 200, r.text
    return r.json()


# ══════════════════════════════════════════════════════════════════
# Positive: запечатанная цепочка верифицируется
# ══════════════════════════════════════════════════════════════════


async def test_sealed_chain_verifies_ok(steel_thread):
    """Каноническая запись (append_evidence_entry) → integrity=ok."""
    h = steel_thread
    await _setup_run_with_chain(h, "td-ok-run", n_entries=3)

    ev = await _get_evidence(h, "td-ok-run")
    assert ev["integrity"] == "ok"
    assert ev["verified"] is True
    assert ev["total_entries"] == 3
    assert ev["tampered_entries"] == []
    assert ev["broken_links"] == []
    assert ev["unsealed_entries"] == []
    assert ev["replay_count"] == 0
    # COS-087: внешний якорь головы опубликован и сходится
    assert ev["anchor"]["status"] == "ok"
    assert ev["anchor"]["enabled"] is True
    assert ev["anchor"]["anchored_head"] == ev["anchor"]["computed_head"]
    assert ev["anchor"]["anchored_head"] != "0" * 64
    # якоря реально в БД, genesis у головы
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            text("SELECT provenance_json FROM evidence_ledger "
                 "WHERE run_id = 'td-ok-run' ORDER BY created_at, id")
        )).scalars().all()
    assert rows[0]["_chain_prev_hash"] == "0" * 64
    assert all("_chain_hash" in row for row in rows)
    assert rows[-1]["_chain_hash"] == ev["anchor"]["anchored_head"]


# ══════════════════════════════════════════════════════════════════
# Negative: подмена/удаление в PG детектируется
# ══════════════════════════════════════════════════════════════════


async def test_tampered_content_ref_detected(steel_thread):
    """UPDATE content_ref средней строки → hash_mismatch с указанием звена."""
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-ref-run", n_entries=3)

    await h.sync_exec(
        "UPDATE evidence_ledger SET content_ref = 'minio://forged/path' "
        "WHERE id = :eid", eid=entry_ids[1],
    )

    ev = await _get_evidence(h, "td-ref-run")
    assert ev["integrity"] == "tampered"
    assert ev["verified"] is False
    assert ev["tampered_entries"] == [1]
    detail = ev["tampered_details"][0]
    assert detail["entry_id"] == entry_ids[1]
    assert detail["reason"] == "hash_mismatch"
    assert detail["stored_hash"] != detail["recomputed_hash"]
    # факт подмены виден оператору в rebuild-виде цепочки
    assert ev["chain"]["entries"][1]["content"]["content_ref"] == "minio://forged/path"


async def test_tampered_content_hash_detected(steel_thread):
    """UPDATE content_hash → детект."""
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-hash-run", n_entries=2)

    await h.sync_exec(
        "UPDATE evidence_ledger SET content_hash = 'sha256:forged' "
        "WHERE id = :eid", eid=entry_ids[0],
    )

    ev = await _get_evidence(h, "td-hash-run")
    assert ev["integrity"] == "tampered"
    assert ev["verified"] is False
    assert ev["tampered_entries"] == [0]
    assert ev["tampered_details"][0]["entry_id"] == entry_ids[0]


async def test_tampered_provenance_json_detected(steel_thread):
    """UPDATE provenance_json (payload) → детект."""
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-prov-run", n_entries=2)

    await h.sync_exec(
        "UPDATE evidence_ledger SET provenance_json = "
        "provenance_json || '{\"severity\": \"Low\"}'::jsonb "
        "WHERE id = :eid", eid=entry_ids[1],
    )

    ev = await _get_evidence(h, "td-prov-run")
    assert ev["integrity"] == "tampered"
    assert ev["verified"] is False
    assert ev["tampered_entries"] == [1]


async def test_tampered_type_detected(steel_thread):
    """UPDATE type на другой валидный enum → детект (enum CHECK не спасает)."""
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-type-run", n_entries=2)

    await h.sync_exec(
        "UPDATE evidence_ledger SET type = 'finding' "
        "WHERE id = :eid", eid=entry_ids[0],
    )

    ev = await _get_evidence(h, "td-type-run")
    assert ev["integrity"] == "tampered"
    assert ev["verified"] is False
    assert ev["tampered_entries"] == [0]


async def test_deleted_middle_row_detected_as_broken_link(steel_thread):
    """DELETE средней строки → broken link у следующей (prev указывает
    на хеш удалённой)."""
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-del-run", n_entries=3)

    await h.sync_exec(
        "DELETE FROM evidence_ledger WHERE id = :eid", eid=entry_ids[1],
    )

    ev = await _get_evidence(h, "td-del-run")
    assert ev["integrity"] == "tampered"
    assert ev["verified"] is False
    assert ev["tampered_chain"] is True
    assert ev["tampered_entries"] == []  # payload оставшихся цел
    link = ev["broken_links"][0]
    assert link["entry_id"] == entry_ids[2]
    assert link["expected_prev_hash"] != link["stored_prev_hash"]
    assert ev["total_entries"] == 2


# ══════════════════════════════════════════════════════════════════
# Unsealed: вставка в обход контракта запечатывания
# ══════════════════════════════════════════════════════════════════


async def test_unsealed_row_is_reported(steel_thread):
    """Сырая ORM-вставка без append_evidence_entry → integrity=unsealed,
    verified=False: нет криптографического доказательства целостности."""
    h = steel_thread
    await _setup_run_with_chain(h, "td-unsealed-run", n_entries=1)

    async with get_sessionmaker()() as s:
        entry = EvidenceLedgerEntry(
            run_id="td-unsealed-run", type="log",
            content_ref="minio://unsealed", content_hash="sha256:" + "9" * 64,
            provenance_json={"source": "bypass"},
        )
        s.add(entry)  # НАМЕРЕННО без append_evidence_entry
        await s.commit()

    ev = await _get_evidence(h, "td-unsealed-run")
    assert ev["integrity"] == "unsealed"
    assert ev["verified"] is False
    assert len(ev["unsealed_entries"]) == 1
    assert ev["tampered_entries"] == []


# ══════════════════════════════════════════════════════════════════
# Детерминизм: подмена детектируется ×3 (acceptance)
# ══════════════════════════════════════════════════════════════════


async def test_tamper_detection_is_deterministic(steel_thread):
    """Три независимых tamper-цикла на трёх run'ах — детект каждый раз."""
    h = steel_thread
    for i, run_id in enumerate(["td-det-1", "td-det-2", "td-det-3"]):
        entry_ids = await _setup_run_with_chain(h, run_id, n_entries=2)
        await h.sync_exec(
            "UPDATE evidence_ledger SET content_ref = :ref WHERE id = :eid",
            ref=f"minio://forged-{i}", eid=entry_ids[0],
        )
        ev = await _get_evidence(h, run_id)
        assert ev["integrity"] == "tampered", f"run {run_id}: {ev['integrity']}"
        assert ev["tampered_details"][0]["entry_id"] == entry_ids[0]
        # recalc честно отличается от stored
        assert ev["tampered_details"][0]["recomputed_hash"] != \
            ev["tampered_details"][0]["stored_hash"]


# ══════════════════════════════════════════════════════════════════
# COS-087: внешний append-only якорь головы (head_mismatch)
# ══════════════════════════════════════════════════════════════════


async def _resign_suffix(run_id: str) -> None:
    """Атакующий с полным доступом на запись в PG: подменяет payload ВСЕХ
    строк И корректно переподписывает всю цепочку (тот же канонический
    алгоритм хеширования). Internal verify после этого чист."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(EvidenceLedgerEntry)
            .where(EvidenceLedgerEntry.run_id == run_id)
            .order_by(EvidenceLedgerEntry.created_at.asc(), EvidenceLedgerEntry.id.asc())
        )).scalars().all()
        prev = EvidenceLedger.GENESIS_HASH
        for row in rows:
            row.content_ref = f"minio://rewritten/{row.id}"
            row.provenance_json = {"source": "attacker"}
            prev = EvidenceLedger.seal_entry(row, prev)
        await s.commit()


async def test_suffix_resign_detected_by_external_anchor(steel_thread):
    """ФЛАГМАН COS-087: суффикс-переподпись → head_mismatch end-to-end.

    Атакующий (полный write-доступ к PG, но не к якорному файлу) переподписывает
    весь суффикс: internal verify чист, но внешний якорь хранит СТАРУЮ голову
    → integrity=head_mismatch, verified=False.
    """
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-anchor-run", n_entries=3)

    # до атаки: всё чисто, якорь сходится с фактической головой
    ev = await _get_evidence(h, "td-anchor-run")
    assert ev["integrity"] == "ok"
    assert ev["anchor"]["status"] == "ok"
    assert ev["anchor"]["anchored_head"] == ev["anchor"]["computed_head"]
    async with get_sessionmaker()() as s:
        head = (await s.execute(text(
            "SELECT provenance_json FROM evidence_ledger "
            "WHERE run_id = 'td-anchor-run' ORDER BY created_at DESC, id DESC LIMIT 1"
        ))).scalars().one()
    assert head["_chain_hash"] == ev["anchor"]["anchored_head"]

    # атака: payload + переподпись всей цепочки
    await _resign_suffix("td-anchor-run")

    ev = await _get_evidence(h, "td-anchor-run")
    assert ev["integrity"] == "head_mismatch"
    assert ev["verified"] is False
    assert ev["head_mismatch"] is True
    assert ev["tampered_entries"] == []  # internal verify чист
    assert ev["broken_links"] == []
    assert ev["anchor"]["status"] == "head_mismatch"
    assert ev["anchor"]["computed_head"] != ev["anchor"]["anchored_head"]


async def test_head_loss_detected_by_external_anchor(steel_thread):
    """Голова удалена из PG (последняя строка), якорь цел → head_mismatch."""
    h = steel_thread
    entry_ids = await _setup_run_with_chain(h, "td-headloss-run", n_entries=2)

    await h.sync_exec(
        "DELETE FROM evidence_ledger WHERE id = :eid", eid=entry_ids[-1],
    )

    ev = await _get_evidence(h, "td-headloss-run")
    assert ev["anchor"]["status"] == "head_mismatch"
    assert ev["head_mismatch"] is True
    assert ev["integrity"] == "head_mismatch"
    assert ev["verified"] is False
    # внутренние проверки оставшихся строк чисты — расхождение только внешнее
    assert ev["tampered_entries"] == []
    assert ev["broken_links"] == []


async def test_unavailable_anchor_is_honest(steel_thread, monkeypatch, tmp_path):
    """Sink недоступен (env → несуществующий файл) → честный unknown_anchor,
    internal вердикт не притворяется внешне подтверждённым."""
    h = steel_thread
    await _setup_run_with_chain(h, "td-unknown-run", n_entries=1)

    monkeypatch.setenv(
        evidence_anchor.ANCHOR_FILE_ENV, str(tmp_path / "gone.jsonl"))
    ev = await _get_evidence(h, "td-unknown-run")
    assert ev["anchor"]["enabled"] is True
    assert ev["anchor"]["status"] == "unknown_anchor"
    assert "does not exist" in ev["anchor"]["detail"]
    assert ev["integrity"] == "ok"       # internal чист
    assert ev["verified"] is True        # verified — internal вердикт
    assert ev["head_mismatch"] is False


async def test_anchor_disabled_internal_verdict_only(steel_thread, monkeypatch):
    """Якорь выключен (env снят) → поведение COS-082 как было, anchor.status
    unknown_anchor + enabled=False."""
    h = steel_thread
    monkeypatch.delenv(evidence_anchor.ANCHOR_FILE_ENV, raising=False)
    await _setup_run_with_chain(h, "td-disabled-run", n_entries=2)

    ev = await _get_evidence(h, "td-disabled-run")
    assert ev["integrity"] == "ok"
    assert ev["verified"] is True
    assert ev["anchor"]["enabled"] is False
    assert ev["head_mismatch"] is False


async def test_suffix_resign_is_deterministic(steel_thread):
    """Acceptance ×3: переподпись суффикса → head_mismatch каждый раз."""
    h = steel_thread
    for i, run_id in enumerate(["td-ares-1", "td-anchor-2", "td-anchor-3"]):
        await _setup_run_with_chain(h, run_id, n_entries=2)
        ev = await _get_evidence(h, run_id)
        assert ev["integrity"] == "ok", f"pre-attack {run_id}: {ev['integrity']}"
        assert ev["anchor"]["status"] == "ok"

        await _resign_suffix(run_id)

        ev = await _get_evidence(h, run_id)
        assert ev["integrity"] == "head_mismatch", f"run {run_id}: {ev['integrity']}"
        assert ev["verified"] is False
        assert ev["head_mismatch"] is True
        assert ev["tampered_entries"] == []
