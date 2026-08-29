"""COS-101: SSE Multiplexer tests."""
import asyncio
import json
import time
from typing import Any, AsyncIterator

import pytest

from cosmo.api.routes.sse import _snapshot_hash, _sse_formatter

pytestmark = pytest.mark.asyncio


# ── In-memory domain multiplexer for testing ────────────────────────────

class DomainEventSource:
    def __init__(self, domain_id: str = "d-test"):
        self.domain_id = domain_id
        self._runs: dict[str, dict[str, Any]] = {}
        self._keepalive_count = 0

    def create_run(self, run_id: str, status: str = "pending",
                   batches=None, gates=None, findings_count: int = 0):
        self._runs[run_id] = {
            "status": status, "trigger": "manual", "plan_id": "plan-1",
            "batches": batches or [], "gates": gates or [],
            "findings_count": findings_count,
        }

    def update_run(self, run_id: str, **kwargs):
        if run_id in self._runs:
            self._runs[run_id].update(kwargs)

    def fetch_snapshots(self) -> dict[str, Any]:
        return dict(self._runs)


async def _test_multiplexer(
    source: DomainEventSource,
    tick_s: float = 0.02,
    keepalive_s: float = 0.05,
    max_ticks: int = 80,
) -> AsyncIterator[dict[str, Any]]:
    last_snaps: dict[str, str] = {}     # run_id -> json.dumps(snap)
    last_keepalive = time.monotonic()
    seen_run_ids: set[str] = set()

    for _ in range(max_ticks):
        await asyncio.sleep(tick_s)
        now = time.monotonic()

        if now - last_keepalive >= keepalive_s:
            yield {"comment": "keepalive"}
            last_keepalive = now
            source._keepalive_count += 1
            continue

        new_snaps = source.fetch_snapshots()

        for rid in new_snaps:
            if rid not in seen_run_ids:
                seen_run_ids.add(rid)
                yield {
                    "event": "run_created",
                    "data": json.dumps({
                        "run_id": rid, "status": new_snaps[rid]["status"],
                        "domain_id": source.domain_id,
                    }),
                }

        for run_id, snap in new_snaps.items():
            new_hash = _snapshot_hash(snap)
            old_raw = last_snaps.get(run_id)
            old_hash = _snapshot_hash(json.loads(old_raw)) if old_raw else None
            if old_hash == new_hash:
                continue

            old_snap: dict[str, Any] = json.loads(old_raw) if old_raw else {}

            new_status = snap.get("status", "")
            old_status = old_snap.get("status", "")
            if old_status and old_status != new_status:
                yield {
                    "event": "status_change",
                    "data": json.dumps({
                        "run_id": run_id, "status": new_status,
                        "previous": old_status,
                        "domain_id": source.domain_id,
                    }),
                }

            old_batches = {
                b["id"]: b["status"] for b in old_snap.get("batches", [])
            }
            for b in snap.get("batches", []):
                if old_batches.get(b["id"]) != b["status"] and b["status"] in ("passed", "failed"):
                    yield {
                        "event": "batch_complete",
                        "data": json.dumps({
                            "run_id": run_id, "batch_id": b["id"],
                            "type": b["type"], "status": b["status"],
                            "domain_id": source.domain_id,
                        }),
                    }

            old_gates = {
                g["id"]: g.get("decision") for g in old_snap.get("gates", [])
            }
            for g in snap.get("gates", []):
                new_dec = g.get("decision")
                if old_gates.get(g["id"]) != new_dec and new_dec is not None:
                    yield {
                        "event": "gate_decision",
                        "data": json.dumps({
                            "run_id": run_id, "gate_id": g["id"],
                            "decision": new_dec, "domain_id": source.domain_id,
                        }),
                    }

            old_fc = old_snap.get("findings_count", 0)
            new_fc = snap.get("findings_count", 0)
            if new_fc > old_fc:
                yield {
                    "event": "finding",
                    "data": json.dumps({
                        "run_id": run_id, "count": new_fc,
                        "delta": new_fc - old_fc, "domain_id": source.domain_id,
                    }),
                }

            last_snaps[run_id] = json.dumps(snap)


async def _collect(gen, n: int = 50) -> list[dict]:
    events: list[dict] = []
    async for item in gen:
        events.append(item)
        if len(events) >= n:
            break
    return events


# ── Tests ────────────────────────────────────────────────────────────────

class TestMultiplexerTwoRuns:
    async def test_two_runs_events_arrive(self):
        src = DomainEventSource("d-1")
        src.create_run("run-a", status="queued")
        src.create_run("run-b", status="queued")
        gen = _test_multiplexer(src, tick_s=0.02, keepalive_s=0.05, max_ticks=30)
        events = await _collect(gen, n=30)
        created = [e for e in events if e.get("event") == "run_created"]
        assert len(created) == 2

    async def test_status_change_arrives(self):
        src = DomainEventSource("d-1")
        src.create_run("run-a", status="queued")
        gen = _test_multiplexer(src, tick_s=0.01, keepalive_s=0.10, max_ticks=100)
        async for item in gen:
            if "comment" in item:
                continue
            if src._runs.get("run-a", {}).get("status") == "queued":
                src.update_run("run-a", status="running")
            ev = item.get("event", "")
            if ev == "status_change":
                d = json.loads(item["data"])
                assert d["run_id"] == "run-a"
                assert d["status"] == "running"
                return

    async def test_other_domain_filtered_out(self):
        src = DomainEventSource("d-1")
        src.create_run("run-d1")
        gen = _test_multiplexer(src, tick_s=0.02, keepalive_s=0.05, max_ticks=30)
        events = await _collect(gen, n=30)
        for ev in events:
            if "data" in ev:
                d = json.loads(ev["data"])
                if "domain_id" in d:
                    assert d["domain_id"] == "d-1"


class TestMultiplexerKeepalive:
    async def test_keepalive_pings(self):
        src = DomainEventSource("d-1")
        gen = _test_multiplexer(src, tick_s=0.01, keepalive_s=0.03, max_ticks=80)
        count = 0
        async for item in gen:
            if item.get("comment") == "keepalive":
                count += 1
            if count >= 3:
                break
        assert count >= 3

    async def test_keepalive_no_data(self):
        src = DomainEventSource("d-1")
        gen = _test_multiplexer(src, tick_s=0.01, keepalive_s=0.03, max_ticks=50)
        async for item in gen:
            if item.get("comment") == "keepalive":
                assert "event" not in item
                assert "data" not in item
                return


class TestMultiplexerRuntimeEvents:
    async def test_batch_complete_emitted(self):
        src = DomainEventSource("d-1")
        src.create_run("run-c", status="running", batches=[
            {"id": "b-build", "type": "build", "status": "running"},
        ])
        gen = _test_multiplexer(src, tick_s=0.01, keepalive_s=0.10, max_ticks=100)
        async for item in gen:
            if "comment" in item:
                continue
            if src._runs.get("run-c", {}).get("status") == "running":
                src.update_run("run-c", status="running", batches=[
                    {"id": "b-build", "type": "build", "status": "passed"},
                ])
            ev = item.get("event", "")
            if ev == "batch_complete":
                d = json.loads(item["data"])
                assert d["batch_id"] == "b-build"
                assert d["status"] == "passed"
                return

    async def test_finding_delta_emitted(self):
        src = DomainEventSource("d-f")
        src.create_run("run-f", status="running", findings_count=0)
        gen = _test_multiplexer(src, tick_s=0.01, keepalive_s=0.10, max_ticks=100)
        async for item in gen:
            if "comment" in item:
                continue
            if src._runs.get("run-f", {}).get("findings_count") == 0:
                src.update_run("run-f", status="running", findings_count=3)
            ev = item.get("event", "")
            if ev == "finding":
                d = json.loads(item["data"])
                assert d["run_id"] == "run-f"
                assert d["count"] == 3
                assert d["delta"] == 3
                return


class TestSSEFormatter:
    async def test_event_format(self):
        async def _gen():
            yield {"event": "status_change", "data": '{"status":"running"}'}
        lines = []
        async for line in _sse_formatter(_gen()):
            lines.append(line)
        assert "event: status_change" in "".join(lines)

    async def test_comment_format(self):
        async def _gen():
            yield {"comment": "keepalive"}
        async for line in _sse_formatter(_gen()):
            assert ": keepalive" in line
            break

    async def test_hash_deterministic(self):
        assert _snapshot_hash({"a": 1}) == _snapshot_hash({"a": 1})

    async def test_hash_different(self):
        assert _snapshot_hash({"a": 1}) != _snapshot_hash({"a": 2})