# -*- coding: utf-8 -*-
"""COS-080: Steel Thread integration suite — сквозной сет через API-уровень
на изолированном тестовом PG (:5433/cosmo_test, _testpg).

Сценарии (карточка COS-080):
  1. Happy-path: Domain → App → Bricks → Compile → Run → Batch → Gate →
     Evidence — все 8 сущностей через реальный app (httpx ASGI), никакого
     ORM-вмешательства кроме записи evidence (единственный контракт записи —
     ORM; API отдаёт цепочку и верификацию через GET /runs/{id}/evidence).
  2. Идемпотентность: повторные create-вызовы → 409, не дубли; те же inputs
     → предсказуемый результат; evidence без дублей.
  3. Recovery: рестарт «процесса» между шагами (dispose engine/сессий,
     новые соединения) — стейты восстанавливаются из PG, без дублей.
  4. Негативные кейсы: невалидный pipeline (цикл/несуществующие кирпичи),
     gate-reject → run blocked, битая evidence-запись (FK/CHECK/подмена).

Фикстуры — собственный conftest.py этой директории (общий не тронут).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from orchestrator.cosmo.db.models import EvidenceLedgerEntry
from orchestrator.cosmo.ledger.evidence_writer import commit_evidence_entry
from orchestrator.cosmo.db.session import get_sessionmaker


# ── API-шаги Steel Thread (чистый API-уровень) ─────────────────────────

# COS-061/067 контракт: read-пути резолвят домен вызывающего из заголовка
# X-Cosmo-Domain (system admin без заголовка видит "default" → честный 404),
# evidence-путь сверяет run.domain_id с principal.domain_id. Все сущности
#suite живёт в одном домене = домену integration-админа.
DOM = "it-integration"


def _H() -> dict:
    return {"X-Cosmo-Domain": DOM}


async def _create_domain(h, domain_id: str = DOM) -> dict:
    r = await h.client.post("/api/v1/domains", json={
        "id": domain_id,
        "label": "Integration Steel Thread Domain",
        "forge_binding": {
            "forge_type": "gitea",
            "url": "https://gitea.integration.example",
            "token_ref": "vault://integration/token",
        },
        "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _create_app(h, domain_id: str, app_id: str = "it-app") -> dict:
    r = await h.client.post("/api/v1/apps", json={
        "id": app_id,
        "domain_id": domain_id,
        "level": 1,
        "repo_binding": {
            "forge_id": "gitea",
            "repo_path": f"{domain_id}/{app_id}",
            "default_branch": "main",
        },
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _create_bricks(h, *, cycle: bool = False, prefix: str = "it") -> list[str]:
    """build + sast (+ опционально gate) кирпичи; cycle=True → взаимный depends_on."""
    bricks = [
        {"id": f"{prefix}-build", "name": "Build", "type": "build",
         "source": f"repos/{prefix}",
         "definition": {"image": "golang:1.22", "executor": "woodpecker"}},
        {"id": f"{prefix}-sast", "name": "SAST", "type": "sast",
         "source": f"repos/{prefix}",
         "definition": {"image": "sonarsource/sonar-scanner-cli:latest",
                        "executor": "woodpecker"}},
    ]
    if cycle:
        bricks[0]["depends_on"] = [f"{prefix}-sast"]
        bricks[1]["depends_on"] = [f"{prefix}-build"]
    for b in bricks:
        r = await h.client.post("/api/v1/bricks", json=b)
        assert r.status_code == 201, r.text
    return [b["id"] for b in bricks]


async def _compile(h, app_id: str, brick_ids: list[str], plan_id: str = "it-plan") -> dict:
    r = await h.client.post("/api/v1/plans/compile", json={
        "plan_id": plan_id,
        "app_id": app_id,
        "brick_ids": brick_ids,
        "level": "app",
    })
    return r


async def _create_run(h, domain_id: str, plan_id: str, run_id: str = "it-run-1") -> dict:
    r = await h.client.post("/api/v1/runs", json={
        "id": run_id,
        "plan_id": plan_id,
        "trigger": "manual",
        "initiator_user_id": "integration-admin",
        "initiator_role": "admin_sec",
        "domain_id": domain_id,
    })
    return r


def _policy() -> dict:
    return {"policy": {"rules": [
        {"finding_type": "Critical", "action": "block"},
        {"finding_type": "High", "action": "warn"},
    ]}}


async def _create_gate(h, plan_id: str, gate_id: str = "it-gate-1",
                       gate_type: str = "automatic", position: int = 0) -> dict:
    body = {"id": gate_id, "plan_id": plan_id, "type": gate_type,
            "position": position, **_policy()}
    r = await h.client.post("/api/v1/gates", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _add_evidence(h, run_id: str, batch_id: str | None, etype: str,
                        content_ref: str, payload: bytes) -> EvidenceLedgerEntry:
    """Канонический контракт записи evidence (COS-082/087): ORM-сущность +
    запечатывание цепочки + commit + публикация внешнего якоря головы
    (commit_evidence_entry). content_hash — sha256 payload."""
    async with get_sessionmaker()() as s:
        entry = EvidenceLedgerEntry(
            run_id=run_id, batch_id=batch_id, type=etype,
            content_ref=content_ref,
            content_hash="sha256:" + hashlib.sha256(payload).hexdigest(),
            provenance_json={"bytes": len(payload), "source": "cos-080"},
        )
        await commit_evidence_entry(s, entry)
        await s.refresh(entry)
        return entry


# ══════════════════════════════════════════════════════════════════════
# 1. Happy-path: полный Steel Thread через API-уровень
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_steel_thread_happy_path(steel_thread):
    """Domain → App → Bricks → Compile → Run → Batch → Gate → Evidence.

    Каждый шаг — реальный HTTP-вызов; состояние проверяется чтением через API.
    """
    h = steel_thread

    # 1. Domain
    domain = await _create_domain(h, DOM)
    assert domain["id"] == DOM

    # 2. App
    app = await _create_app(h, DOM, "hp-app")
    assert app["domain_id"] == DOM

    # 3. Bricks
    brick_ids = await _create_bricks(h, prefix="hp")
    r = await h.client.get("/api/v1/bricks")
    assert r.status_code == 200
    listed = {b["id"] for b in r.json()}
    assert set(brick_ids) <= listed

    # 4. Compile → plan + batches
    r = await _compile(h, "hp-app", brick_ids, plan_id="hp-plan")
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["id"] == "hp-plan"
    assert plan["brick_ids"] == brick_ids
    # compile_hash = детерминированный sha256-hexdigest (plan_compiler.compile_hash)
    import re as _re
    assert _re.fullmatch(r"[0-9a-f]{64}", plan["compiled_hash"]) is not None

    # Batches скомпилированы по DAG: build → static_scan
    r = await h.client.get("/api/v1/batches?plan_id=hp-plan", headers=_H())
    assert r.status_code == 200
    batches = {b["type"]: b for b in r.json()}
    assert "build" in batches and "static_scan" in batches
    assert batches["build"]["bricks"] == ["hp-build"]
    assert batches["static_scan"]["bricks"] == ["hp-sast"]

    # 5. Run
    r = await _create_run(h, DOM, "hp-plan", run_id="hp-run-1")
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "pending"

    # 6. Run → running; Batches прогон
    r = await h.client.patch("/api/v1/runs/hp-run-1/status", json={"status": "running"}, headers=_H())
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert r.json()["started_at"] is not None

    for batch_id in (batches["build"]["id"], batches["static_scan"]["id"]):
        r = await h.client.patch(f"/api/v1/batches/{batch_id}/status",
                                 json={"status": "running"}, headers=_H())
        assert r.status_code == 200, r.text
        r = await h.client.patch(f"/api/v1/batches/{batch_id}/status",
                                 json={"status": "passed"}, headers=_H())
        assert r.status_code == 200, r.text

    # 7. Gate (automatic) → pass
    gate = await _create_gate(h, "hp-plan", gate_id="hp-gate-1")
    assert gate["id"] == "hp-gate-1"
    r = await h.client.post("/api/v1/gates/hp-gate-1/decision",
                            json={"decision": "pass"})
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "pass"
    assert r.json()["decided_at"] is not None

    # 8. Run → succeeded
    r = await h.client.patch("/api/v1/runs/hp-run-1/status", json={"status": "succeeded"}, headers=_H())
    assert r.status_code == 200
    assert r.json()["finished_at"] is not None

    # 9. Evidence: 3 записи (log/finding/decision) → API-верификация цепочки
    await _add_evidence(h, "hp-run-1", batches["build"]["id"], "log",
                        "minio://hp/build.log", b"build log bytes")
    await _add_evidence(h, "hp-run-1", batches["static_scan"]["id"], "finding",
                        "minio://hp/sast.json", b'{"issues": []}')
    await _add_evidence(h, "hp-run-1", None, "decision",
                        "gate://hp-gate-1/verdict", b"gate pass")

    r = await h.client.get("/api/v1/runs/hp-run-1/evidence", headers=_H())
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["total_entries"] == 3
    assert ev["verified"] is True
    assert ev["tampered_entries"] == []
    assert ev["tampered_chain"] is False
    assert ev["replay_count"] == 0
    types = [e["type"] for e in ev["chain"]["entries"]]
    assert types == ["log", "finding", "decision"]
    # content_hash в цепочке — sha256 фактического payload
    first = ev["chain"]["entries"][0]
    assert first["content"]["content_hash"].startswith("sha256:")
    assert first["prev_hash"] == "0" * 64  # genesis

    # 10. Финальное состояние run через API: все связи на месте
    r = await h.client.get("/api/v1/runs/hp-run-1", headers=_H())
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "succeeded"
    assert {b["status"] for b in run["batches"]} == {"passed"}
    assert "hp-gate-1" in run["gates"]


# ══════════════════════════════════════════════════════════════════════
# 2. Идемпотентность повторных прогонов
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_repeated_compiles_and_runs_are_rejected_not_duplicated(steel_thread):
    """Повторные create с тем же id → 409, никаких тихих дублей."""
    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "idem-app")
    brick_ids = await _create_bricks(h, prefix="idem")
    r = await _compile(h, "idem-app", brick_ids, plan_id="idem-plan")
    assert r.status_code == 201
    first_hash = r.json()["compiled_hash"]

    # Повторный compile с тем же plan_id → 409 (не дублируется план/batches)
    r = await _compile(h, "idem-app", brick_ids, plan_id="idem-plan")
    assert r.status_code == 409, r.text

    # Повторный run с тем же id → 409
    r = await _create_run(h, DOM, "idem-plan", run_id="idem-run")
    assert r.status_code == 201
    r = await _create_run(h, DOM, "idem-plan", run_id="idem-run")
    assert r.status_code == 409, r.text

    # Те же inputs (те же кирпичи) → детерминированный результат: новый план
    # на клоне приложения с теми же brick_ids даёт предсказуемый результат
    # (тот же состав batch-типов и тот же топологический порядок кирпичей).
    await _create_app(h, DOM, "idem-app-2")
    r = await _compile(h, "idem-app-2", brick_ids, plan_id="idem-plan-2")
    assert r.status_code == 201
    r = await h.client.get("/api/v1/batches?plan_id=idem-plan-2", headers=_H())
    batches2 = r.json()
    # Предсказуемый результат: те же inputs → тот же состав batch-типов
    # и тот же топологический порядок кирпичей.
    assert [b["type"] for b in batches2] == ["build", "static_scan"]
    assert batches2[0]["bricks"] == ["idem-build"]
    assert batches2[1]["bricks"] == ["idem-sast"]


@pytest.mark.asyncio
async def test_same_inputs_no_evidence_duplicates(steel_thread):
    """Те же inputs на повторном прогоне → предсказуемый результат,
    evidence-цепочка каждого run без дублей."""
    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "evd-app")
    brick_ids = await _create_bricks(h, prefix="evd")
    r = await _compile(h, "evd-app", brick_ids, plan_id="evd-plan")
    assert r.status_code == 201
    r = await h.client.get("/api/v1/batches?plan_id=evd-plan", headers=_H())
    batches = r.json()

    run_ids = ["evd-run-1", "evd-run-2"]
    for run_id in run_ids:
        r = await _create_run(h, DOM, "evd-plan", run_id=run_id)
        assert r.status_code == 201
        r = await h.client.patch(f"/api/v1/runs/{run_id}/status",
                                 json={"status": "succeeded"}, headers=_H())
        assert r.status_code == 200

    # Одинаковый набор evidence на каждый прогон → ровно N записей, без дублей
    for run_id in run_ids:
        await _add_evidence(h, run_id, batches[0]["id"], "log",
                            "minio://evd/build.log", b"same build log")
        await _add_evidence(h, run_id, None, "decision",
                            "gate://evd/verdict", b"same verdict")
        r = await h.client.get(f"/api/v1/runs/{run_id}/evidence", headers=_H())
        assert r.status_code == 200
        ev = r.json()
        assert ev["total_entries"] == 2, run_id   # ровно N — дубли не расползаются
        assert ev["verified"] is True
        assert ev["replay_count"] == 0

    # Прогон идемпотентен по входу: оба runs succeeded на одном плане
    r = await h.client.get("/api/v1/runs?plan_id=evd-plan", headers=_H())
    runs = r.json()
    assert {run["id"] for run in runs} == set(run_ids)
    assert all(run["status"] == "succeeded" for run in runs)


# ══════════════════════════════════════════════════════════════════════
# 3. Recovery: рестарт процесса между шагами
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_restart_between_steps_restores_state_from_pg(steel_thread):
    """Рестарт между каждым шагом: in-memory сброшен (новые engine/сессии/
    клиент), состояние живёт в PG и восстанавливается честно."""
    h = steel_thread

    # Шаг 1: domain + app + bricks
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "rec-app")
    brick_ids = await _create_bricks(h, prefix="rec")

    await h.restart()

    # Шаг 2 (после рестарта): compile — плана ещё нет, кирпичи из PG
    r = await _compile(h, "rec-app", brick_ids, plan_id="rec-plan")
    assert r.status_code == 201, r.text
    compiled_hash = r.json()["compiled_hash"]

    await h.restart()

    # Шаг 3 (после рестарта): план и batches восстановлены из PG
    r = await h.client.get("/api/v1/plans/rec-plan", headers=_H())
    assert r.status_code == 200, r.text
    assert r.json()["compiled_hash"] == compiled_hash
    r = await h.client.get("/api/v1/batches?plan_id=rec-plan", headers=_H())
    batches = {b["type"]: b for b in r.json()}
    assert "build" in batches and "static_scan" in batches

    # Шаг 4 (после рестарта): run создаётся, уходит в running
    r = await _create_run(h, DOM, "rec-plan", run_id="rec-run")
    assert r.status_code == 201, r.text
    r = await h.client.patch("/api/v1/runs/rec-run/status", json={"status": "running"}, headers=_H())
    assert r.status_code == 200

    await h.restart()

    # Шаг 5 (после рестарта): running сохранён, продолжаем с середины
    r = await h.client.get("/api/v1/runs/rec-run", headers=_H())
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "running"
    assert run["started_at"] is not None

    for batch_id in (batches["build"]["id"], batches["static_scan"]["id"]):
        r = await h.client.patch(f"/api/v1/batches/{batch_id}/status",
                                 json={"status": "passed"}, headers=_H())
        assert r.status_code == 200, r.text

    gate = await _create_gate(h, "rec-plan", gate_id="rec-gate-1")
    assert gate["id"] == "rec-gate-1"

    await h.restart()

    # Шаг 6 (после рестарта): gate из PG, решение, терминальный статус, evidence
    r = await h.client.get("/api/v1/gates/rec-gate-1", headers=_H())
    assert r.status_code == 200, r.text
    r = await h.client.post("/api/v1/gates/rec-gate-1/decision",
                            json={"decision": "pass"}, headers=_H())
    assert r.status_code == 200, r.text

    await _add_evidence(h, "rec-run", batches["build"]["id"], "log",
                        "minio://rec/build.log", b"recovered build log")
    r = await h.client.patch("/api/v1/runs/rec-run/status", json={"status": "succeeded"}, headers=_H())
    assert r.status_code == 200

    await h.restart()

    # Финал: 5 рестартов — состояние целостно, дублей нет
    assert h.restarts == 5
    r = await h.client.get("/api/v1/runs/rec-run", headers=_H())
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"
    r = await h.client.get("/api/v1/runs/rec-run/evidence", headers=_H())
    ev = r.json()
    assert ev["total_entries"] == 1
    assert ev["verified"] is True
    assert ev["replay_count"] == 0
    r = await h.client.get("/api/v1/runs?plan_id=rec-plan", headers=_H())
    assert len(r.json()) == 1  # рестарты не плодят дубли прогонов


# ══════════════════════════════════════════════════════════════════════
# 4. Негативные кейсы: честные ошибки контракта
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_invalid_pipeline_cycle_detected(steel_thread):
    """Цикл в depends_on → 400 с описанием цикла, план не создаётся."""
    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "neg-app")
    brick_ids = await _create_bricks(h, prefix="neg", cycle=True)
    r = await _compile(h, "neg-app", brick_ids, plan_id="neg-plan")
    assert r.status_code == 400, r.text
    assert "Cycle" in r.json()["detail"]
    # План не должен был создаться:
    r = await h.client.get("/api/v1/plans/neg-plan", headers=_H())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_compile_with_missing_bricks_is_404(steel_thread):
    """Compile с несуществующим brick_id → 404 с перечнем недостающих."""
    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "miss-app")
    brick_ids = await _create_bricks(h, prefix="miss")
    r = await _compile(h, "miss-app", brick_ids + ["ghost-brick"],
                       plan_id="miss-plan")
    assert r.status_code == 404, r.text
    assert "ghost-brick" in r.json()["detail"]
    r = await h.client.get("/api/v1/plans/miss-plan", headers=_H())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_run_on_missing_plan_and_app_on_missing_domain(steel_thread):
    """404 по FK-контракту: run без плана, app без домена."""
    h = steel_thread
    await _create_domain(h, DOM)
    r = await h.client.post("/api/v1/runs", json={
        "id": "neg-run", "plan_id": "no-such-plan", "trigger": "manual",
        "domain_id": DOM,
    })
    assert r.status_code == 404, r.text
    assert "no-such-plan" in r.json()["detail"]

    r = await h.client.post("/api/v1/apps", json={
        "id": "neg-app", "domain_id": "no-such-domain", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "x/y",
                         "default_branch": "main"},
    })
    assert r.status_code == 404, r.text

    # run в несуществующем домене → 404 (проверяется раньше плана);
    # валидный домен уже создан выше — app/plan на нём
    await _create_app(h, DOM, "neg2-app")
    brick_ids = await _create_bricks(h, prefix="neg2")
    await _compile(h, "neg2-app", brick_ids, plan_id="neg2-plan")
    r = await h.client.post("/api/v1/runs", json={
        "id": "neg-run-ghost-domain", "plan_id": "neg2-plan", "trigger": "manual",
        "domain_id": "no-such-domain",
    })
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_gate_reject_blocks_run(steel_thread):
    """Gate-reject: decision=block → gate заблокирован; run → blocked
    (терминальный честный стейт с finished_at)."""
    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "rej-app")
    brick_ids = await _create_bricks(h, prefix="rej")
    await _compile(h, "rej-app", brick_ids, plan_id="rej-plan")
    r = await _create_run(h, DOM, "rej-plan", run_id="rej-run")
    assert r.status_code == 201

    gate = await _create_gate(h, "rej-plan", gate_id="rej-gate-1")
    r = await h.client.post("/api/v1/gates/rej-gate-1/decision",
                            json={"decision": "block"}, headers=_H())
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "block"
    assert r.json()["decided_at"] is not None

    r = await h.client.patch("/api/v1/runs/rej-run/status", json={"status": "blocked"}, headers=_H())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["finished_at"] is not None

    # Evidence фиксирует решение: decision-запись с hash вердикта
    verdict = json.dumps({"gate": "rej-gate-1", "decision": "block"}).encode()
    await _add_evidence(h, "rej-run", None, "decision",
                        "gate://rej-gate-1/verdict", verdict)
    r = await h.client.get("/api/v1/runs/rej-run/evidence", headers=_H())
    assert r.status_code == 200
    ev = r.json()
    assert ev["total_entries"] == 1
    assert ev["chain"]["entries"][0]["content"]["content_ref"] == "gate://rej-gate-1/verdict"


@pytest.mark.asyncio
async def test_evidence_on_missing_run_is_404(steel_thread):
    """GET evidence несуществующего run → 404 (не пустая цепочка-обманка)."""
    h = steel_thread
    r = await h.client.get("/api/v1/runs/ghost-run/evidence")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_evidence_fk_violation_is_honest_contract_error(steel_thread):
    """Evidence-запись на несуществующий run → FK IntegrityError (не тихий успех)."""
    from sqlalchemy.exc import IntegrityError

    h = steel_thread
    async with get_sessionmaker()() as s:
        entry = EvidenceLedgerEntry(
            run_id="no-such-run", type="log",
            content_ref="minio://x/y", content_hash="sha256:" + "0" * 64,
        )
        s.add(entry)
        with pytest.raises(IntegrityError):
            await s.commit()


@pytest.mark.asyncio
async def test_evidence_invalid_type_rejected_by_check_constraint(steel_thread):
    """Битый type (вне enum) → честная ошибка контракта БД. PG отдаёт
    invalid input value for enum evidence_type (asyncpg мапит в DBAPIError,
    у psycopg2-пути это было бы IntegrityError) — либо way запись отвергнута."""
    from sqlalchemy.exc import DBAPIError, IntegrityError

    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "bad-app")
    brick_ids = await _create_bricks(h, prefix="bad")
    await _compile(h, "bad-app", brick_ids, plan_id="bad-plan")
    await _create_run(h, DOM, "bad-plan", run_id="bad-run")

    async with get_sessionmaker()() as s:
        entry = EvidenceLedgerEntry(
            run_id="bad-run", type="screenshot-forged",
            content_ref="minio://bad/x", content_hash="sha256:" + "1" * 64,
        )
        s.add(entry)
        with pytest.raises((IntegrityError, DBAPIError), match="evidence_type"):
            await s.commit()


@pytest.mark.asyncio
async def test_tampered_content_hash_is_visible_in_chain(steel_thread):
    """Подмена content_hash в PG в обход API: верификация честно показывает
    ФАКТИЧЕСКОЕ (подменённое) значение в content — оператор видит данные как
    есть. Известное ограничение verify_and_get (hash пересчитывается от
    текущих строк, а не сравнивается с записанным) зафиксировано как
    находка COS-080; тест фиксирует реальный контракт, не выдумывая детект."""
    h = steel_thread
    await _create_domain(h, DOM)
    await _create_app(h, DOM, "tmp-app")
    brick_ids = await _create_bricks(h, prefix="tmp")
    await _compile(h, "tmp-app", brick_ids, plan_id="tmp-plan")
    await _create_run(h, DOM, "tmp-plan", run_id="tmp-run")

    payload = b"evidence artifact bytes"
    await _add_evidence(h, "tmp-run", None, "log", "minio://tmp/artifact", payload)

    # Подмена в обход API (прямой SQL):
    await h.sync_exec(
        "UPDATE evidence_ledger SET content_hash = 'sha256:tampered' "
        "WHERE run_id = 'tmp-run'"
    )

    r = await h.client.get("/api/v1/runs/tmp-run/evidence", headers=_H())
    assert r.status_code == 200, r.text
    ev = r.json()
    # Факт подмены виден в цепочке — данные не подменяются молча:
    assert ev["chain"]["entries"][0]["content"]["content_hash"] == "sha256:tampered"
    # COS-082: подмена payload детектируется — verify сверяет СОХРАНЁННЫЙ
    # якорь с пересчётом от снапшота строки, integrity=tampered с указанием
    # звена (бывшее ограничение COS-080 закрыто).
    assert ev["integrity"] == "tampered"
    assert ev["verified"] is False
    assert ev["tampered_entries"] == [0]
    assert ev["tampered_details"][0]["reason"] == "hash_mismatch"
