"""COS-011 / COS-101 / COS-056 / COS-088: SSE streaming — run + domain + notification.

Endpoints:
  GET /api/v1/runs/{run_id}/stream                  — single-run SSE (COS-011)
  GET /api/v1/domains/{domain_id}/events/stream     — multiplexed SSE (COS-101)
  GET /api/v1/notifications/stream                  — notification inbox SSE (COS-056)

Events: run_created, status_change, batch_complete, gate_decision, finding,
        release_transferred, notification_new.
Rate-limited to 2 Hz (500ms tick).
Keepalive ping every 15s against proxy timeout.
Reconnect-safe: client reconnects -> replay last known state.

COS-088: каждый yielded event несёт SSE ``id`` и дублируется в backlog
(sse_backlog — Valkey Stream с TTL, fallback in-memory ring). Reconnect с
Last-Event-ID (стандартный заголовок EventSource или last_event_id query)
→ resample backlog после этого id; пропущенные события доставляются, а при
неподтверждённой непрерывности (TTL-вытеснение / рестарт в memory-режиме)
— resync-снапшот, не тишина. Без Valkey поведение прежнее + наблюдаемый
флаг деградации (event stream_backlog + заголовок X-Cosmo-Backlog).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse
from sqlalchemy import select

from orchestrator.cosmo.api import sse_backlog
from orchestrator.cosmo.db.session import get_sessionmaker
from orchestrator.cosmo.db.models import Run, Batch, Gate, EvidenceLedgerEntry, Domain
from orchestrator.cosmo.db.models_execution import ExecutionHandleRow, TERMINAL_STORED_STATUSES

router = APIRouter(tags=["sse"])

_TICK_S = 0.5
_KEEPALIVE_S = 15.0


def _snapshot_hash(snap: dict) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(snap, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _resolve_last_event_id(request: Request, last_event_id: str) -> str:
    """last_event_id: query-параметр сильнее стандарного заголовка.

    Стандартный SSE reconnect шлёт заголовок Last-Event-ID; клиенты с
    ручным reconnect (fresh ticket на каждую попытку) передают явный
    last_event_id query-параметром.
    """
    if last_event_id:
        return last_event_id.strip()
    header_id = request.headers.get("last-event-id")
    return header_id.strip() if header_id else ""


def _backlog_item(
    kind: str, key: str, event: str, data: str
) -> dict[str, Any]:
    """SSE-событие с id из backlog (publish + id-инвариант COS-088)."""
    event_id = sse_backlog.publish(kind, key, event, data)
    item: dict[str, Any] = {"event": event, "data": data}
    if event_id:
        item["id"] = event_id
    return item


def _backlog_flag_event(mode: str) -> dict[str, Any]:
    """Наблюдаемый флаг деградации backlog (COS-088). Не несёт id."""
    return {
        "event": "stream_backlog",
        "data": json.dumps({"mode": mode}),
    }


async def _sse_formatter(
    generator: AsyncIterator[dict[str, Any]]
) -> AsyncIterator[str]:
    async for item in generator:
        if "comment" in item:
            yield f": {item['comment']}\n\n"
        else:
            event = item.get("event", "message")
            data = item.get("data", "")
            event_id = item.get("id")
            lines = []
            if event_id:
                lines.append(f"id: {event_id}")
            lines.append(f"event: {event}")
            lines.append(f"data: {data}")
            yield "\n".join(lines) + "\n\n"


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


# в”Ђв”Ђ Single-run stream (COS-011) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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


def _run_initial_payload(snap: dict[str, Any]) -> str:
    """Полный state-снапшот прогона (initial / resync — COS-088)."""
    return json.dumps({
        "status": snap["run"]["status"],
        "run": snap["run"],
        "batches": snap["batches"],
        "gates": snap["gates"],
        "findings_count": snap["findings_count"],
    })


async def _run_stream(
    run_id: str, request: Request, last_event_id: str = ""
) -> AsyncIterator[dict[str, Any]]:
    last_hash: str | None = None
    last_keepalive = time.monotonic()

    # COS-088: наблюдаемый флаг режима backlog
    yield _backlog_flag_event(sse_backlog.backlog_mode())

    snap = await _fetch_run_snapshot(run_id)
    if snap is None:
        yield {"event": "error", "data": json.dumps({"error": "run_not_found", "run_id": run_id})}
        return

    last_hash = _snapshot_hash(snap)
    initial_payload = _run_initial_payload(snap)

    # COS-088: resample по last-event-id (replay backlog; gap → resync, не тишина)
    if last_event_id:
        replayed = sse_backlog.replay("run", run_id, last_event_id)
        if replayed is None:
            # backlog недоступен (valkey сбой) → честная деградация: снапшот
            yield {"event": "resync", "data": initial_payload}
        else:
            for rec in replayed.records:
                yield {"event": rec.event_type, "data": rec.data, "id": rec.id}
            if replayed.gap:
                yield {"event": "resync", "data": initial_payload}

    yield _backlog_item("run", run_id, "status_change", initial_payload)

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
            yield _backlog_item(
                "run", run_id, "status_change",
                json.dumps({
                    "status": new_run["status"],
                    "previous": old_run.get("status"),
                    "started_at": new_run.get("started_at"),
                    "finished_at": new_run.get("finished_at"),
                }),
            )

        old_batches = {b["id"]: b["status"] for b in snap.get("batches", [])}
        for b in new_snap.get("batches", []):
            if old_batches.get(b["id"]) != b["status"] and b["status"] in ("passed", "failed"):
                yield _backlog_item(
                    "run", run_id, "batch_complete",
                    json.dumps({"batch_id": b["id"], "type": b["type"], "status": b["status"]}),
                )

        old_gates = {g["id"]: g.get("decision") for g in snap.get("gates", [])}
        for g in new_snap.get("gates", []):
            new_dec = g.get("decision")
            if old_gates.get(g["id"]) != new_dec and new_dec is not None:
                yield _backlog_item(
                    "run", run_id, "gate_decision",
                    json.dumps({
                        "gate_id": g["id"], "decision": new_dec,
                        "decided_by": g.get("decided_by"), "decided_at": g.get("decided_at"),
                    }),
                )

        old_fc = snap.get("findings_count", 0)
        new_fc = new_snap.get("findings_count", 0)
        if new_fc > old_fc:
            yield _backlog_item(
                "run", run_id, "finding",
                json.dumps({
                    "count": new_fc, "delta": new_fc - old_fc,
                    "total_evidence": new_snap.get("evidence_count", 0),
                }),
            )

        snap = new_snap
        last_hash = new_hash


# ── Run step logs stream (COS-109) ───────────────────────────────────────────

_LOGS_POLL_S = 1.0
_LOGS_KEEPALIVE_S = 15.0

# Woodpecker step states considered "active" (generating log output)
_ACTIVE_STEP_STATES = frozenset({"running", "pending"})

# Woodpecker step states considered terminal
_TERMINAL_STEP_STATES = frozenset({"success", "failure", "killed", "skipped", "error", "declined"})

# COS-180: backlog-пространство лог-стрима (key = run_id). Отдельный kind —
# иначе replay логов смешался бы с run-событиями на общем ключе.
_LOG_BACKLOG_KIND = "runlog"

# События лог-стрима, попадающие в backlog и несущие SSE id.
_LOG_ID_EVENTS = frozenset({"step_start", "log_chunk", "step_finish", "run_finish"})


def _seed_log_cursors(
    step_cursors: dict[tuple[str, str], tuple[str, int]],
    records: list[sse_backlog.EventRecord],
) -> None:
    """COS-180: восстановить позицию клиента из удержанного окна backlog.

    Реконнект не должен повторно отдавать уже доставленные строки лога:
    для каждого (batch, step) считаем сумму строк во всех чанках окна
    (acked + missed), состояние шага берём из последней записи окна.
    Дальше live-loop догоняет только строки, которых в окне ещё не было.

    Честная граница: если store успел вытеснить записи ДО last-event-id
    (TTL/MAXLEN), счётчик занижен — часть логов может прийти повторно;
    потерь при этом нет, а непрерывность вне окна не подтверждается (gap).
    """
    per_state: dict[tuple[str, str], str] = {}
    per_lines: dict[tuple[str, str], int] = {}
    for rec in records:
        if rec.event_type not in _LOG_ID_EVENTS:
            continue
        try:
            payload = json.loads(rec.data or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        key = (str(payload.get("batch_id") or ""), str(payload.get("step_name") or ""))
        if key == ("", ""):
            continue
        if rec.event_type == "log_chunk":
            lines = payload.get("lines")
            if isinstance(lines, list):
                per_lines[key] = per_lines.get(key, 0) + len(lines)
            per_state.setdefault(key, "running")
        elif rec.event_type == "step_start":
            per_state[key] = "running"
        elif rec.event_type == "step_finish":
            per_state[key] = str(payload.get("state") or "success")
    for key, state in per_state.items():
        step_cursors[key] = (state, per_lines.get(key, 0))


async def _run_logs_stream(
    run_id: str, request: Request, last_event_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """COS-109 + COS-180: SSE multiplexer — live Woodpecker step logs for Web IDE drawer.

    Polls Woodpecker API for each batch's pipeline: detects step transitions
    (step_start / step_finish) and streams new log chunks (log_chunk) with
    xterm.js-compatible formatting. Emits run_finish when all pipelines
    reach terminal state, then closes.

    COS-180: каждое data-событие публикуется в backlog (kind ``runlog``,
    key = run_id) и несёт SSE ``id`` (инвариант COS-088). Реконнект с
    last_event_id: недоставленные события реплеятся из окна backlog, оно же
    восстанавливает курсоры (batch, step) — уже доставленные строки логов
    повторно не отдаются. Gap/недоступность backlog → ``resync`` (не тишина).
    """
    # ── DB handles: resolve Woodpecker pipeline handles for this run ──
    from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter

    adapter: WoodpeckerAdapter | None = None
    last_keepalive = time.monotonic()

    # Per-step cursor tracking: (batch_id, step_name) -> (state, lines_seen_count)
    step_cursors: dict[tuple[str, str], tuple[str, int]] = {}

    # Known batch_ids to detect new batches
    known_batches: set[str] = set()

    # COS-088/180: наблюдаемый флаг режима backlog
    yield _backlog_flag_event(sse_backlog.backlog_mode())

    try:
        # ── Validate run exists ──
        sm = get_sessionmaker()
        async with sm() as db:
            run_row = await db.execute(select(Run).where(Run.id == run_id))
            run_row = run_row.scalar_one_or_none()
        if run_row is None:
            yield {"event": "error", "data": json.dumps({"error": "run_not_found", "run_id": run_id})}
            return

        # ── COS-180: resume — replay недоставленных + позиция курсоров ──
        # Выполняется ДО терминальной отсечки: пропущенный финал доставляется
        # даже если прогон уже закрыт.
        run_finish_in_backlog = False
        if last_event_id:
            window = sse_backlog.read_window(_LOG_BACKLOG_KIND, run_id)
            if window is None:
                yield {"event": "resync", "data": json.dumps({
                    "run_id": run_id, "reason": "backlog_unavailable"})}
            else:
                idx = next(
                    (i for i, rec in enumerate(window) if rec.id == last_event_id),
                    -1,
                )
                if idx < 0:
                    # Непрерывность не подтверждена (TTL-вытеснение/триминг/
                    # рестарт в memory-режиме) → resync, не тишина.
                    yield {"event": "resync", "data": json.dumps({
                        "run_id": run_id, "reason": "gap"})}
                else:
                    run_finish_in_backlog = any(
                        rec.event_type == "run_finish" for rec in window
                    )
                    for rec in window[idx + 1:]:
                        yield {"event": rec.event_type, "data": rec.data, "id": rec.id}
                    _seed_log_cursors(step_cursors, window)

        # ── If run is already terminal, emit run_finish and close ──
        if run_row.status in ("passed", "failed", "blocked"):
            if not run_finish_in_backlog:
                yield _backlog_item(
                    _LOG_BACKLOG_KIND, run_id, "run_finish",
                    json.dumps({"run_id": run_id, "status": run_row.status}),
                )
            return

        adapter = WoodpeckerAdapter()

        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(_LOGS_POLL_S)
            now = time.monotonic()

            # Keepalive ping
            if now - last_keepalive >= _LOGS_KEEPALIVE_S:
                yield {"comment": "keepalive"}
                last_keepalive = now
                continue

            # ── Refresh handles from DB (new batches may appear mid-run) ──
            async with sm() as db:
                handles = await db.execute(
                    select(ExecutionHandleRow).where(
                        ExecutionHandleRow.run_id == run_id,
                    )
                )
                handles = list(handles.scalars().all())

            if not handles:
                # No Woodpecker pipeline dispatched yet — keep waiting
                continue

            all_terminal = True
            had_events = False

            for h in handles:
                handle_dict = h.as_handle_dict()
                bid = h.batch_id
                known_batches.add(bid)

                # ── Poll pipeline state ──
                try:
                    pipeline = await asyncio.to_thread(
                        adapter.get_pipeline, handle_dict,
                    )
                except Exception:
                    # Woodpecker unreachable / pipeline not found — skip this tick
                    if h.last_status and h.last_status not in TERMINAL_STORED_STATUSES:
                        all_terminal = False
                    continue

                p_status = pipeline.get("status", "pending")
                if p_status not in TERMINAL_STORED_STATUSES:
                    all_terminal = False

                # ── Flatten steps and detect transitions ──
                steps = await asyncio.to_thread(
                    adapter._flatten_steps, pipeline,
                )

                for step in steps:
                    step_name = step.get("name", "unknown")
                    step_state = step.get("state", "pending")
                    cursor_key = (bid, step_name)
                    prev = step_cursors.get(cursor_key)
                    prev_state, lines_seen = prev if prev else (None, 0)

                    # ── step_start: first time we see this step (running or terminal) ──
                    emit_start = False
                    if prev_state is None:
                        # First encounter — always announce the step
                        emit_start = True
                    elif step_state == "running" and prev_state != "running":
                        # Transition: pending/skipped → running
                        emit_start = True

                    if emit_start:
                        yield _backlog_item(
                            _LOG_BACKLOG_KIND, run_id, "step_start",
                            json.dumps({
                                "run_id": run_id,
                                "batch_id": bid,
                                "step_name": step_name,
                                "step_id": step.get("id"),
                            }),
                        )
                        had_events = True
                        last_keepalive = now

                    # ── log_chunk: fetch new log lines for active/terminal steps ──
                    need_logs = (
                        step_state in ("running", "success", "failure")
                        or (prev_state is None and step_state in _TERMINAL_STEP_STATES)
                    )
                    if need_logs:
                        try:
                            all_lines = await asyncio.to_thread(
                                adapter._fetch_step_logs, handle_dict, step,
                            )
                        except Exception:
                            all_lines = []
                        if len(all_lines) > lines_seen:
                            new_lines = all_lines[lines_seen:]
                            yield _backlog_item(
                                _LOG_BACKLOG_KIND, run_id, "log_chunk",
                                json.dumps({
                                    "run_id": run_id,
                                    "batch_id": bid,
                                    "step_name": step_name,
                                    "lines": new_lines,
                                }),
                            )
                            had_events = True
                            last_keepalive = now
                            lines_seen = len(all_lines)

                    # ── step_finish: transition to terminal OR catch-up ──
                    if step_state in _TERMINAL_STEP_STATES:
                        if prev_state is None or prev_state == "running":
                            exit_code = (
                                0 if step_state == "success"
                                else (1 if step_state == "failure" else None)
                            )
                            yield _backlog_item(
                                _LOG_BACKLOG_KIND, run_id, "step_finish",
                                json.dumps({
                                    "run_id": run_id,
                                    "batch_id": bid,
                                    "step_name": step_name,
                                    "exit_code": exit_code,
                                    "state": step_state,
                                }),
                            )
                            had_events = True
                            last_keepalive = now

                    # Update cursor
                    step_cursors[cursor_key] = (step_state, lines_seen)

                # Update last_status in handle
                h.last_status = p_status

            if not had_events:
                continue

            # ── Check run status: if all handles are terminal, emit run_finish ──
            if all_terminal and handles:
                async with sm() as db:
                    run_final = await db.execute(select(Run).where(Run.id == run_id))
                    run_final = run_final.scalar_one_or_none()
                final_status = run_final.status if run_final else "unknown"
                yield _backlog_item(
                    _LOG_BACKLOG_KIND, run_id, "run_finish",
                    json.dumps({"run_id": run_id, "status": final_status}),
                )
                return

    except asyncio.CancelledError:
        # Client disconnected — clean exit, no error
        pass
    finally:
        if adapter is not None:
            try:
                await asyncio.to_thread(adapter.close)
            except Exception:
                pass


@router.get("/api/v1/runs/{run_id}/logs/stream")
async def stream_run_logs(
    run_id: str, request: Request, ticket: str = "", last_event_id: str = "",
):
    """COS-109 + COS-180: SSE stream of Woodpecker step logs (step_start, log_chunk, step_finish, run_finish).

    Клиент Web IDE получает живой лог шага за шагом. При завершении прогона
    соединение закрывается. Формат чанков совместим с xterm.js.
    COS-180: события несут SSE ``id``; reconnect с ``last_event_id`` (query
    сильнее заголовка Last-Event-ID) получает недоставленное из backlog без
    дублей уже отданных строк лога.

    Ticket-аутентификация — аналог COS-079 для существующих SSE-эндпоинтов.
    """
    from fastapi import HTTPException

    from orchestrator.cosmo.api.sse_tickets import validate_ticket

    if not ticket or validate_ticket(ticket) is None:
        raise HTTPException(status_code=401, detail="invalid or expired sse ticket")
    last_id = _resolve_last_event_id(request, last_event_id)
    return _sse_response(
        _run_logs_stream(run_id, request, last_id),
        extra_headers={"X-Cosmo-Backlog": sse_backlog.backlog_mode()},
    )


# в”Ђв”Ђ Domain-wide multiplexer (COS-101) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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


def _domain_resync_payload(domain_id: str, snaps: dict[str, Any]) -> str:
    """Полный state-снапшот домена (resync — COS-088)."""
    return json.dumps({
        "domain_id": domain_id,
        "runs": {
            rid: {
                "status": s.get("status"),
                "findings_count": s.get("findings_count", 0),
            }
            for rid, s in snaps.items()
        },
    })


async def _domain_stream(
    domain_id: str, request: Request, last_event_id: str = ""
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

    # COS-088: наблюдаемый флаг режима backlog + resample по last-event-id.
    yield _backlog_flag_event(sse_backlog.backlog_mode())

    if last_event_id:
        replayed = sse_backlog.replay("domain", domain_id, last_event_id)
        fresh = await _fetch_domain_snapshots(domain_id)
        if replayed is None:
            # backlog недоступен → честная деградация: снапшот, не тишина
            yield {
                "event": "resync",
                "data": _domain_resync_payload(domain_id, fresh),
            }
            for rid, s in fresh.items():
                seen_run_ids.add(rid)
                last_snaps[rid] = json.dumps(s)
        else:
            for rec in replayed.records:
                yield {"event": rec.event_type, "data": rec.data, "id": rec.id}
            if replayed.gap:
                yield {"event": "resync", "data": _domain_resync_payload(domain_id, fresh)}
            # Reconnect с подтверждённым/неподтверждённым last-event-id:
            # базовый state уже у клиента (replay или resync) — pre-seed,
            # чтобы live-цикл не пере-выводил run_created/batch_complete
            # для уже известных прогонов.
            for rid, s in fresh.items():
                seen_run_ids.add(rid)
                last_snaps[rid] = json.dumps(s)

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
                yield _backlog_item(
                    "domain", domain_id, "run_created",
                    json.dumps({
                        "run_id": rid,
                        "status": new_snaps[rid]["status"],
                        "domain_id": domain_id,
                    }),
                )

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
                yield _backlog_item(
                    "domain", domain_id, "status_change",
                    json.dumps({
                        "run_id": run_id,
                        "status": new_status,
                        "previous": old_status,
                        "domain_id": domain_id,
                    }),
                )

            # batch_complete
            old_batches = {b["id"]: b["status"] for b in old_snap.get("batches", [])}
            for b in snap.get("batches", []):
                if old_batches.get(b["id"]) != b["status"] and b["status"] in ("passed", "failed"):
                    yield _backlog_item(
                        "domain", domain_id, "batch_complete",
                        json.dumps({
                            "run_id": run_id, "batch_id": b["id"],
                            "type": b["type"], "status": b["status"],
                            "domain_id": domain_id,
                        }),
                    )

            # gate_decision
            old_gates = {g["id"]: g.get("decision") for g in old_snap.get("gates", [])}
            for g in snap.get("gates", []):
                new_dec = g.get("decision")
                if old_gates.get(g["id"]) != new_dec and new_dec is not None:
                    yield _backlog_item(
                        "domain", domain_id, "gate_decision",
                        json.dumps({
                            "run_id": run_id, "gate_id": g["id"],
                            "decision": new_dec, "domain_id": domain_id,
                        }),
                    )

            # finding
            old_fc = old_snap.get("findings_count", 0)
            new_fc = snap.get("findings_count", 0)
            if new_fc > old_fc:
                yield _backlog_item(
                    "domain", domain_id, "finding",
                    json.dumps({
                        "run_id": run_id, "count": new_fc,
                        "delta": new_fc - old_fc, "domain_id": domain_id,
                    }),
                )

            last_snaps[run_id] = json.dumps(snap)


# в”Ђв”Ђ Endpoints в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@router.get("/api/v1/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str, request: Request, ticket: str = "", last_event_id: str = "",
):
    from fastapi import HTTPException

    from orchestrator.cosmo.api.sse_tickets import validate_ticket

    # COS-079: SSE endpoint без auth — закрыт. EventSource не умеет custom
    # headers, поэтому клиент получает short-TTL ticket под bearer-аутой
    # и передаёт его в query-параметре. Recipient/run scope не расширяется.
    # COS-079 acceptance: missing ticket → 401 (не 422).
    if not ticket or validate_ticket(ticket) is None:
        raise HTTPException(status_code=401, detail="invalid or expired sse ticket")
    last_id = _resolve_last_event_id(request, last_event_id)
    return _sse_response(
        _run_stream(run_id, request, last_id),
        extra_headers={"X-Cosmo-Backlog": sse_backlog.backlog_mode()},
    )


@router.get("/api/v1/domains/{domain_id}/events/stream")
async def stream_domain_events(
    domain_id: str, request: Request, ticket: str = "", last_event_id: str = "",
):
    """SSE multiplexer: all run events for a KITS domain (COS-101).

    One connection = all runs in the domain.
    Events: run_created, status_change, batch_complete, gate_decision, finding.
    Keepalive ping every 15s.
    """
    from fastapi import HTTPException

    from orchestrator.cosmo.api.sse_tickets import validate_ticket

    # COS-079: guard, аналогично run stream — ticket обязателен (401).
    if not ticket or validate_ticket(ticket) is None:
        raise HTTPException(status_code=401, detail="invalid or expired sse ticket")
    last_id = _resolve_last_event_id(request, last_event_id)
    return _sse_response(
        _domain_stream(domain_id, request, last_id),
        extra_headers={"X-Cosmo-Backlog": sse_backlog.backlog_mode()},
    )


# в”Ђв”Ђ Notification stream (COS-056) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

_NOTIFICATION_POLL_S = 2.0


async def _notification_unread(db, recipient_id: str) -> int:
    """РўРµРєСѓС‰РёР№ unread count РїРѕР»СѓС‡Р°С‚РµР»СЏ (in_app). Р’С‹Р·С‹РІР°РµС‚СЃСЏ РІ РіРѕС‚РѕРІРѕР№ СЃРµСЃСЃРёРё."""
    from sqlalchemy import func

    from orchestrator.cosmo.db.models_notifications import NotificationRow

    count = await db.execute(
        select(func.count(NotificationRow.id)).where(
            NotificationRow.recipient_id == recipient_id,
            NotificationRow.channel == "in_app",
            NotificationRow.read_at.is_(None),
        )
    )
    return count.scalar_one()


async def _notification_poll_once(
    db,
    recipient_id: str,
    last_known_ids: set[str],
    last_seen_created: str | None,
) -> list[dict[str, Any]]:
    """РћРґРёРЅ poll РЅРѕРІС‹С… СѓРІРµРґРѕРјР»РµРЅРёР№ РІ РіРѕС‚РѕРІРѕР№ СЃРµСЃСЃРёРё.

    Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє SSE-payload'РѕРІ (notification_new / notification_unread_count).
    Р¤СѓРЅРєС†РёСЏ С‡РёСЃС‚Р°СЏ РїРѕ СЃРµСЃСЃРёРё вЂ” РїРµСЂРµРёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ СЃС‚СЂРёРјРѕРј Рё С‚РµСЃС‚Р°РјРё.
    """
    from orchestrator.cosmo.db.models_notifications import NotificationRow

    payloads: list[dict[str, Any]] = []

    stmt = (
        select(NotificationRow)
        .where(
            NotificationRow.recipient_id == recipient_id,
            NotificationRow.channel == "in_app",
        )
        .order_by(NotificationRow.created_at.desc())
        .limit(20)
    )
    if last_seen_created:
        stmt = stmt.where(NotificationRow.created_at > last_seen_created)
    rows = (await db.execute(stmt)).scalars().all()

    fresh: list[NotificationRow] = []
    for row in reversed(rows):
        if row.id in last_known_ids:
            continue
        last_known_ids.add(row.id)
        fresh.append(row)
        ts = row.created_at
        if ts and (last_seen_created is None or ts.isoformat() > last_seen_created):
            last_seen_created = ts.isoformat()

    if fresh:
        for row in fresh:
            payloads.append({
                "event": "notification_new",
                "data": json.dumps({
                    "id": row.id,
                    "event_id": row.event_id,
                    "notification_type": row.notification_type,
                    "severity": row.severity,
                    "title": row.title,
                    "message": row.message,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }),
            })
        unread = await _notification_unread(db, recipient_id)
        payloads.append({
            "event": "notification_unread_count",
            "data": json.dumps({"unread_count": unread}),
        })
    return payloads


async def _notification_stream(
    recipient_id: str, request: Request, last_event_id: str = ""
) -> AsyncIterator[dict[str, Any]]:
    """SSE РґР»СЏ notification inbox РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ (COS-056).

    Polling-based (durable PG вЂ” source of truth, SSE вЂ” projection).
    Reconnect-safe: initial connection С€Р»С‘С‚ С‚РµРєСѓС‰РёР№ unread count;
    РґР°Р»РµРµ вЂ” С‚РѕР»СЊРєРѕ РЅРѕРІС‹Рµ notification СЃ created_at > last_seen.

    Delivery Hardening: РћР”РќРђ long-lived PG-СЃРµСЃСЃРёСЏ РЅР° SSE-СЃРѕРµРґРёРЅРµРЅРёРµ
    (commit РїРѕСЃР»Рµ РєР°Р¶РґРѕРіРѕ С‚РёРєР° вЂ” Р±РµР· idle-in-transaction), РІРјРµСЃС‚Рѕ
    checkout'Р° РґРІСѓС… СЃРµСЃСЃРёР№ РЅР° РєР°Р¶РґС‹Р№ 2s poll. РџСЂРё PG down вЂ”
    notification_degraded + РїРµСЂРµСЃРѕР·РґР°РЅРёРµ СЃРµСЃСЃРёРё РЅР° СЃР»РµРґСѓСЋС‰РµРј С‚РёРєРµ;
    РїРѕСЃР»Рµ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ СЃРѕРµРґРёРЅРµРЅРёСЏ С€Р»С‘С‚СЃСЏ notification_initial Р·Р°РЅРѕРІРѕ
    (РєР»РёРµРЅС‚ РІРѕР·РІСЂР°С‰Р°РµС‚СЃСЏ РІ connected, РґСѓР±Р»Рё РёСЃРєР»СЋС‡РµРЅС‹ last_known_ids).

    Р’РђР–РќРћ: Р»РѕРІРёС‚СЃСЏ Exception (Р° РЅРµ С‚РѕР»СЊРєРѕ SQLAlchemyError) вЂ” asyncpg РїСЂРё
    РјС‘СЂС‚РІРѕРј TCP-РєРѕРЅРЅРµРєС‚Рµ (docker stop PG, РѕР±СЂС‹РІ СЃРµС‚Рё) РїСЂРѕР±СЂР°СЃС‹РІР°РµС‚ raw
    OSError/ConnectionError, SQLAlchemy РµРіРѕ РЅРµ РѕР±РѕСЂР°С‡РёРІР°РµС‚. Р›СЋР±РѕР№ СЃР±РѕР№
    I/O в†’ degraded + РїРµСЂРµСЃРѕР·РґР°РЅРёРµ СЃРµСЃСЃРёРё; happy path РЅРµ РјРµРЅСЏРµС‚СЃСЏ.
    """
    sm = get_sessionmaker()
    last_keepalive = time.monotonic()
    last_seen_created: str | None = None
    last_known_ids: set[str] = set()

    # COS-088: наблюдаемый флаг режима backlog (до resample, чтобы клиент
    # знал режим до первого события).
    yield _backlog_flag_event(sse_backlog.backlog_mode())

    # COS-088: resample по last-event-id — replay notification_new из backlog.
    # gap/недоступность backlog здесь НЕ требует отдельного resync-события:
    # durable PG inbox — source of truth, notification_initial ниже (unread
    # count) по построению выполняет роль resync-снапшота; последующий poll
    # пере-доставит последние 20 нотификаций (клиент дедуплицирует по id).
    if last_event_id:
        replayed = sse_backlog.replay("notif", recipient_id, last_event_id)
        if replayed is not None:
            for rec in replayed.records:
                yield {"event": "notification_new", "data": rec.data, "id": rec.id}
                try:
                    last_known_ids.add(str(json.loads(rec.data).get("id", "")))
                except Exception:  # noqa: BLE001 — replay-запись без id не дедуплицируется
                    pass

    db = None
    degraded = False
    try:
        db = sm()
        # Initial connection: РѕС‚РїСЂР°РІРёС‚СЊ unread count
        try:
            unread = await _notification_unread(db, recipient_id)
            await db.commit()
            degraded = False
            yield {
                "event": "notification_initial",
                "data": json.dumps({"unread_count": unread, "recipient_id": recipient_id}),
            }
        except Exception:  # noqa: BLE001 — asyncpg raises raw ConnectionError on dead socket
            degraded = True
            yield {
                "event": "notification_degraded",
                "data": json.dumps({"error": "db_unavailable", "recipient_id": recipient_id}),
            }

        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(_NOTIFICATION_POLL_S)
            now = time.monotonic()

            if now - last_keepalive >= _KEEPALIVE_S:
                yield {"comment": "keepalive"}
                last_keepalive = now
                continue

            # PG РЅРµРґРѕСЃС‚СѓРїРµРЅ: РЅР° РєР°Р¶РґРѕРј С‚РёРєРµ РїСЂРѕР±СѓРµРј РІРѕСЃСЃС‚Р°РЅРѕРІРёС‚СЊСЃСЏ.
            if degraded:
                try:
                    unread = await _notification_unread(db, recipient_id)
                    await db.commit()
                except Exception:  # noqa: BLE001 — asyncpg raises raw ConnectionError on dead socket
                    # Р•С‰С‘ РЅРµРґРѕСЃС‚СѓРїРµРЅ: РїРµСЂРµСЃРѕР·РґР°С‚СЊ СЃРµСЃСЃРёСЋ (РјС‘СЂС‚РІС‹Р№ РєРѕРЅРЅРµРєС‚)
                    try:
                        await db.close()
                    except Exception:  # noqa: BLE001
                        pass
                    db = sm()
                    yield {
                        "event": "notification_degraded",
                        "data": json.dumps({"error": "db_unavailable", "recipient_id": recipient_id}),
                    }
                    continue
                # Р’РѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРѕ
                degraded = False
                yield {
                    "event": "notification_initial",
                    "data": json.dumps({"unread_count": unread, "recipient_id": recipient_id}),
                }

            # Poll РЅРѕРІС‹С… СѓРІРµРґРѕРјР»РµРЅРёР№ (РѕРґРЅР° СЃРµСЃСЃРёСЏ, commit РїРѕСЃР»Рµ С‚РёРєР°)
            try:
                payloads = await _notification_poll_once(
                    db, recipient_id, last_known_ids, last_seen_created
                )
                await db.commit()
            except Exception:  # noqa: BLE001 — asyncpg raises raw ConnectionError on dead socket
                degraded = True
                try:
                    await db.close()
                except Exception:  # noqa: BLE001
                    pass
                db = sm()
                yield {
                    "event": "notification_degraded",
                    "data": json.dumps({"error": "db_unavailable", "recipient_id": recipient_id}),
                }
                continue

            for payload in payloads:
                if payload.get("event") == "notification_new":
                    # COS-088: event в backlog ДО yield — SSE id == backlog id.
                    item = _backlog_item("notif", recipient_id, "notification_new", payload["data"])
                    if item is not None:
                        payload = {**payload, "id": item["id"]}
                yield payload
    finally:
        if db is not None:
            try:
                await db.close()
            except Exception:  # noqa: BLE001
                pass


@router.get("/api/v1/notifications/stream")
async def stream_notifications(
    request: Request,
    ticket: str,
    last_event_id: str = "",
):
    """COS-056/075: SSE stream для notification inbox текущего principal.

    Auth без компромисса (COS-075): EventSource не поддерживает custom
    headers, поэтому bearer в URL запрещён. Клиент сначала POST
    /api/v1/notifications/sse-ticket (обычная bearer-аутентификация) —
    сервер возвращает short-TTL HMAC-ticket, привязанный к principal.user_id.
    Stream резолвит recipient ИЗ TICKET — client-asserted recipient_id
    из query-параметра убран (V1 compromise закрыт).

    Reconnect: клиент переподключается с НОВЫМ ticket (старый истёк за 60s);
    initial connection шлёт текущий unread_count, новые события — только
    после last_seen. Durable inbox — source of truth; SSE — projection.
    Graceful degradation: PG недоступен → keepalive, уведомления не теряются.
    COS-088: last_event_id (query > Last-Event-ID header) — resample
    notification_new из backlog; notification_initial служит resync.
    """
    from fastapi import HTTPException

    from orchestrator.cosmo.api.sse_tickets import validate_ticket

    recipient_id = validate_ticket(ticket)
    if recipient_id is None:
        raise HTTPException(
            status_code=401,
            detail="invalid or expired sse ticket",
        )
    last_id = _resolve_last_event_id(request, last_event_id)
    return _sse_response(
        _notification_stream(recipient_id, request, last_id),
        extra_headers={"X-Cosmo-Backlog": sse_backlog.backlog_mode()},
    )
