"""COS-011 / COS-101: SSE streaming — single-run + domain-wide multiplexer.

Endpoints:
  GET /api/v1/runs/{run_id}/stream                  — single-run SSE (COS-011)
  GET /api/v1/domains/{domain_id}/events/stream     — multiplexed SSE (COS-101)

Events: run_created, status_change, batch_complete, gate_decision, finding,
        release_transferred.
Rate-limited to 2 Hz (500ms tick).
Keepalive ping every 15s against proxy timeout.
Reconnect-safe: client reconnects -> replay last known state.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse
from sqlalchemy import select

from orchestrator.cosmo.db.session import get_sessionmaker
from orchestrator.cosmo.db.models import Run, Batch, Gate, EvidenceLedgerEntry, Domain

router = APIRouter(tags=["sse"])

_TICK_S = 0.5
_KEEPALIVE_S = 15.0


def _snapshot_hash(snap: dict) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(snap, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


async def _sse_formatter(
    generator: AsyncIterator[dict[str, Any]]
) -> AsyncIterator[str]:
    async for item in generator:
        if "comment" in item:
            yield f": {item['comment']}\n\n"
        else:
            event = item.get("event", "message")
            data = item.get("data", "")
            yield f"event: {event}\ndata: {data}\n\n"


def _sse_response(generator, extra_headers: dict = None) -> StreamingResponse:
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if extra_headers:
        headers.update(extra_headers)
    return StreamingResponse(
        _sse_formatter(generator),
        media_type="text/event-stream",
        headers=headers,
    )


# ── Single-run stream (COS-011) ────────────────────────────────────────

async def _fetch_run_snapshot(run_id: str) -> dict[str, Any] | None:
    sm = get_sessionmaker()
    async with sm() as db:
        run = await db.execute(select(Run).where(Run.id == run_id))
        run = run.scalar_one_or_none()
        if run is None:
            return None
        batches = await db.execute(
            select(Batch).where(Batch.plan_id == run.plan_id).order_by(Batch.id)
        )
        batches = list(batches.scalars().all())
        gates = await db.execute(
            select(Gate).where(Gate.plan_id == run.plan_id).order_by(Gate.position)
        )
        gates = list(gates.scalars().all())
        evidence = await db.execute(
            select(EvidenceLedgerEntry)
            .where(EvidenceLedgerEntry.run_id == run_id)
            .order_by(EvidenceLedgerEntry.created_at.desc())
            .limit(50)
        )
        evidence = list(evidence.scalars().all())
        return {
            "run": {
                "id": run.id,
                "status": run.status,
                "trigger": run.trigger,
                "domain_id": run.domain_id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            },
            "batches": [
                {"id": b.id, "type": b.type, "status": b.status}
                for b in batches
            ],
            "gates": [
                {
                    "id": g.id, "type": g.type, "position": g.position,
                    "decision": g.decision,
                    "decided_by": g.decided_by,
                    "decided_at": g.decided_at.isoformat() if g.decided_at else None,
                }
                for g in gates
            ],
            "findings_count": sum(1 for e in evidence if e.type == "finding"),
            "evidence_count": len(evidence),
        }


async def _run_stream(
    run_id: str, request: Request
) -> AsyncIterator[dict[str, Any]]:
    last_hash: str | None = None
    last_keepalive = time.monotonic()

    snap = await _fetch_run_snapshot(run_id)
    if snap is None:
        yield {"event": "error", "data": json.dumps({"error": "run_not_found", "run_id": run_id})}
        return

    last_hash = _snapshot_hash(snap)
    yield {
        "event": "status_change",
        "data": json.dumps({
            "status": snap["run"]["status"],
            "run": snap["run"],
            "batches": snap["batches"],
            "gates": snap["gates"],
            "findings_count": snap["findings_count"],
        }),
    }

    while True:
        if await request.is_disconnected():
            break

        await asyncio.sleep(_TICK_S)
        now = time.monotonic()

        # COS-101: keepalive ping
        if now - last_keepalive >= _KEEPALIVE_S:
            yield {"comment": "keepalive"}
            last_keepalive = now
            continue

        new_snap = await _fetch_run_snapshot(run_id)
        if new_snap is None:
            yield {"event": "error", "data": json.dumps({"error": "run_disappeared", "run_id": run_id})}
            break

        new_hash = _snapshot_hash(new_snap)
        if new_hash == last_hash:
            continue

        old_run = snap["run"]
        new_run = new_snap["run"]

        if old_run.get("status") != new_run["status"]:
            yield {
                "event": "status_change",
                "data": json.dumps({
                    "status": new_run["status"],
                    "previous": old_run.get("status"),
                    "started_at": new_run.get("started_at"),
                    "finished_at": new_run.get("finished_at"),
                }),
            }

        old_batches = {b["id"]: b["status"] for b in snap.get("batches", [])}
        for b in new_snap.get("batches", []):
            if old_batches.get(b["id"]) != b["status"] and b["status"] in ("passed", "failed"):
                yield {
                    "event": "batch_complete",
                    "data": json.dumps({"batch_id": b["id"], "type": b["type"], "status": b["status"]}),
                }

        old_gates = {g["id"]: g.get("decision") for g in snap.get("gates", [])}
        for g in new_snap.get("gates", []):
            new_dec = g.get("decision")
            if old_gates.get(g["id"]) != new_dec and new_dec is not None:
                yield {
                    "event": "gate_decision",
                    "data": json.dumps({
                        "gate_id": g["id"], "decision": new_dec,
                        "decided_by": g.get("decided_by"), "decided_at": g.get("decided_at"),
                    }),
                }

        old_fc = snap.get("findings_count", 0)
        new_fc = new_snap.get("findings_count", 0)
        if new_fc > old_fc:
            yield {
                "event": "finding",
                "data": json.dumps({
                    "count": new_fc, "delta": new_fc - old_fc,
                    "total_evidence": new_snap.get("evidence_count", 0),
                }),
            }

        snap = new_snap
        last_hash = new_hash


# ── Domain-wide multiplexer (COS-101) ──────────────────────────────────

async def _fetch_domain_snapshots(domain_id: str) -> dict[str, Any]:
    """Fetch all run snapshots for a domain."""
    sm = get_sessionmaker()
    async with sm() as db:
        runs = await db.execute(
            select(Run).where(Run.domain_id == domain_id).order_by(Run.created_at.desc())
        )
        runs = list(runs.scalars().all())
        result: dict[str, Any] = {}
        for run in runs:
            batches = await db.execute(
                select(Batch).where(Batch.plan_id == run.plan_id).order_by(Batch.id)
            )
            batches_list = list(batches.scalars().all())
            gates = await db.execute(
                select(Gate).where(Gate.plan_id == run.plan_id).order_by(Gate.position)
            )
            gates_list = list(gates.scalars().all())
            evidence = await db.execute(
                select(EvidenceLedgerEntry)
                .where(EvidenceLedgerEntry.run_id == run.id)
                .order_by(EvidenceLedgerEntry.created_at.desc())
                .limit(10)
            )
            evidence_list = list(evidence.scalars().all())
            result[run.id] = {
                "status": run.status,
                "trigger": run.trigger,
                "plan_id": run.plan_id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "batches": [
                    {"id": b.id, "type": b.type, "status": b.status}
                    for b in batches_list
                ],
                "gates": [
                    {
                        "id": g.id, "type": g.type, "position": g.position,
                        "decision": g.decision,
                        "decided_by": g.decided_by,
                    }
                    for g in gates_list
                ],
                "findings_count": sum(1 for e in evidence_list if e.type == "finding"),
            }
        return result


async def _domain_stream(
    domain_id: str, request: Request
) -> AsyncIterator[dict[str, Any]]:
    """Multiplexed SSE stream for ALL runs in a KITS domain."""
    sm = get_sessionmaker()
    async with sm() as db:
        dom = await db.get(Domain, domain_id)
        if dom is None:
            yield {"event": "error", "data": json.dumps({"error": "domain_not_found", "domain_id": domain_id})}
            return

    last_snaps: dict[str, str] = {}       # run_id -> json.dumps(snap)
    last_keepalive = time.monotonic()
    seen_run_ids: set[str] = set()

    while True:
        if await request.is_disconnected():
            break

        await asyncio.sleep(_TICK_S)
        now = time.monotonic()

        if now - last_keepalive >= _KEEPALIVE_S:
            yield {"comment": "keepalive"}
            last_keepalive = now
            continue

        new_snaps = await _fetch_domain_snapshots(domain_id)

        # run_created detection
        for rid in new_snaps:
            if rid not in seen_run_ids:
                seen_run_ids.add(rid)
                yield {
                    "event": "run_created",
                    "data": json.dumps({
                        "run_id": rid,
                        "status": new_snaps[rid]["status"],
                        "domain_id": domain_id,
                    }),
                }

        for run_id, snap in new_snaps.items():
            new_hash = _snapshot_hash(snap)
            old_raw = last_snaps.get(run_id)
            old_hash = _snapshot_hash(json.loads(old_raw)) if old_raw else None
            if old_hash == new_hash:
                continue

            old_snap: dict[str, Any] = json.loads(old_raw) if old_raw else {}

            # status_change
            old_status = old_snap.get("status")
            new_status = snap.get("status")
            if old_status and old_status != new_status:
                yield {
                    "event": "status_change",
                    "data": json.dumps({
                        "run_id": run_id,
                        "status": new_status,
                        "previous": old_status,
                        "domain_id": domain_id,
                    }),
                }

            # batch_complete
            old_batches = {b["id"]: b["status"] for b in old_snap.get("batches", [])}
            for b in snap.get("batches", []):
                if old_batches.get(b["id"]) != b["status"] and b["status"] in ("passed", "failed"):
                    yield {
                        "event": "batch_complete",
                        "data": json.dumps({
                            "run_id": run_id, "batch_id": b["id"],
                            "type": b["type"], "status": b["status"],
                            "domain_id": domain_id,
                        }),
                    }

            # gate_decision
            old_gates = {g["id"]: g.get("decision") for g in old_snap.get("gates", [])}
            for g in snap.get("gates", []):
                new_dec = g.get("decision")
                if old_gates.get(g["id"]) != new_dec and new_dec is not None:
                    yield {
                        "event": "gate_decision",
                        "data": json.dumps({
                            "run_id": run_id, "gate_id": g["id"],
                            "decision": new_dec, "domain_id": domain_id,
                        }),
                    }

            # finding
            old_fc = old_snap.get("findings_count", 0)
            new_fc = snap.get("findings_count", 0)
            if new_fc > old_fc:
                yield {
                    "event": "finding",
                    "data": json.dumps({
                        "run_id": run_id, "count": new_fc,
                        "delta": new_fc - old_fc, "domain_id": domain_id,
                    }),
                }

            last_snaps[run_id] = json.dumps(snap)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/api/v1/runs/{run_id}/stream")
async def stream_run_events(run_id: str, request: Request):
    return _sse_response(_run_stream(run_id, request))


@router.get("/api/v1/domains/{domain_id}/events/stream")
async def stream_domain_events(domain_id: str, request: Request):
    """SSE multiplexer: all run events for a KITS domain (COS-101).

    One connection = all runs in the domain.
    Events: run_created, status_change, batch_complete, gate_decision, finding.
    Keepalive ping every 15s.
    """
    return _sse_response(_domain_stream(domain_id, request))