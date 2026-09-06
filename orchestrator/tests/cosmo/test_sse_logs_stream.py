"""COS-109: Contract tests for GET /api/v1/runs/{run_id}/logs/stream — SSE step log streaming."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.cosmo.api.routes.sse import _run_logs_stream


# ── Stubs ────────────────────────────────────────────────────────────────────


class _StubRequest:
    """Mock Starlette Request for driving SSE generators."""

    def __init__(self, checks_before_disconnect: int = 20) -> None:
        self._checks_left = checks_before_disconnect
        self.headers: dict[str, str] = {}

    async def is_disconnected(self) -> bool:
        if self._checks_left <= 0:
            return True
        self._checks_left -= 1
        return False


# ── Helpers ──────────────────────────────────────────────────────────────────


def _stub_run(status: str = "pending"):
    """Return a stub Run row."""
    r = MagicMock()
    r.id = "run-test-1"
    r.status = status
    r.plan_id = "plan-test-1"
    r.trigger = "manual"
    r.domain_id = "d-test"
    r.started_at = None
    r.finished_at = None
    return r


def _stub_handle(batch_id: str = "batch-1", run_id: str = "run-test-1", number: int = 1):
    """Return a stub ExecutionHandleRow."""
    h = MagicMock()
    h.batch_id = batch_id
    h.run_id = run_id
    h.repo_owner = "owner"
    h.repo_name = "repo"
    h.repo_id = 1
    h.wp_number = number
    h.wp_pipeline_id = 9000 + number
    h.branch = "main"
    h.last_status = "running"
    h.degraded = False

    def _as_handle_dict():
        return {
            "job_id": h.wp_pipeline_id,
            "number": h.wp_number,
            "repo_id": h.repo_id,
            "repo_owner": h.repo_owner,
            "repo_name": h.repo_name,
            "branch": h.branch,
        }

    h.as_handle_dict = _as_handle_dict
    return h


def _simple_pipeline(status: str = "running", steps: list | None = None):
    """Return a fake pipeline dict that WoodpeckerAdapter.get_pipeline would return."""
    wf_steps = steps or [
        {"id": 1, "pid": 0, "name": "build", "state": "running"},
    ]
    return {"status": status, "workflows": [{"name": "default", "steps": wf_steps}]}


def _flatten_steps(pipeline: dict) -> list[dict]:
    """Replicate WoodpeckerAdapter._flatten_steps."""
    out = []
    for wf in pipeline.get("workflows", []):
        for st in wf.get("steps", []):
            out.append({
                "id": st.get("id"),
                "pid": st.get("pid", 0),
                "name": st.get("name", "unknown"),
                "state": st.get("state", "pending"),
                "workflow": wf.get("name"),
            })
    return out


def _collect_events(gen_coro, max_events: int = 30, timeout: float = 5.0):
    """Drive async generator and collect non-comment events.

    Returns list of (event_type, data_dict).
    Uses asyncio.run() for clean event loop isolation (no cross-test contamination).
    """
    events: list[tuple[str, dict]] = []

    async def _drive():
        async for item in gen_coro:
            if "comment" in item:
                continue
            ev = item.get("event", "message")
            raw = item.get("data", "{}")
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = {"_raw": raw}
            events.append((ev, data))

    asyncio.run(asyncio.wait_for(_drive(), timeout=timeout))
    return events


# ── Patch targets ────────────────────────────────────────────────────────────

_SM_PATH = "orchestrator.cosmo.api.routes.sse.get_sessionmaker"
_WP_PATH = "orchestrator.cosmo.adapters.execution_woodpecker.WoodpeckerAdapter"


def _setup_db_mock(mock_sm, *, run_status="running", handles=None):
    """Configure get_sessionmaker mock with controlled Run + handle(s).

    Every DB query returns a MagicMock that can respond to both
    scalar_one_or_none() (for Run lookups) and scalars().all()
    (for ExecutionHandleRow queries)."""
    run = _stub_run(status=run_status)
    handle_list = handles or []

    mock_session = MagicMock()

    async def _execute(_stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = run
        result.scalars.return_value.all.return_value = list(handle_list)
        return result

    mock_session.execute = _execute
    mock_sm.return_value.return_value.__aenter__ = AsyncMock(
        return_value=mock_session,
    )
    mock_sm.return_value.return_value.__aexit__ = AsyncMock(return_value=False)

    return run, handle_list, mock_session


def _setup_wp_mock(mock_wp_cls, pipeline, fetch_logs_fn=None):
    """Configure WoodpeckerAdapter mock with controlled pipeline + log responses."""
    ma = MagicMock()
    ma.get_pipeline.return_value = pipeline
    ma._flatten_steps = _flatten_steps
    if fetch_logs_fn:
        ma._fetch_step_logs = MagicMock(side_effect=fetch_logs_fn)
    else:
        ma._fetch_step_logs = MagicMock(return_value=[])
    ma.close = MagicMock()
    mock_wp_cls.return_value = ma
    return ma


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRunNotFound:
    """Run doesn't exist → error event, stream closes."""

    def test_run_not_found(self):
        req = _StubRequest(checks_before_disconnect=2)

        with patch(_SM_PATH) as mock_sm:
            run_result = MagicMock()
            run_result.scalar_one_or_none.return_value = None
            mock_session = MagicMock()
            mock_session.execute = AsyncMock(return_value=run_result)
            mock_sm.return_value.return_value.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            mock_sm.return_value.return_value.__aexit__ = AsyncMock(return_value=False)

            gen = _run_logs_stream("bad-run-id", req)
            events = _collect_events(gen, max_events=5)

        assert len(events) == 1
        ev_type, data = events[0]
        assert ev_type == "error"
        assert data["error"] == "run_not_found"


class TestRunAlreadyFinished:
    """Run status is terminal → immediate run_finish, stream closes."""

    def test_already_finished_emits_run_finish(self):
        req = _StubRequest(checks_before_disconnect=2)
        run = _stub_run(status="passed")

        with patch(_SM_PATH) as mock_sm:
            run_result = MagicMock()
            run_result.scalar_one_or_none.return_value = run
            mock_session = MagicMock()
            mock_session.execute = AsyncMock(return_value=run_result)
            mock_sm.return_value.return_value.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            mock_sm.return_value.return_value.__aexit__ = AsyncMock(return_value=False)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=5)

        assert len(events) == 1
        ev_type, data = events[0]
        assert ev_type == "run_finish"
        assert data["run_id"] == "run-test-1"
        assert data["status"] == "passed"


class TestNoHandleYet:
    """Run exists but no ExecutionHandleRow — stream waits (emits only keepalive)."""

    def test_no_handle_waits(self):
        req = _StubRequest(checks_before_disconnect=3)

        with patch(_SM_PATH) as mock_sm:
            _setup_db_mock(mock_sm, run_status="running", handles=[])

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=10)

        # Only keepalive comments, no step events
        non_keepalive = [(t, d) for t, d in events if t not in ("message",)]
        assert len(non_keepalive) == 0


class TestStepLifecycle:
    """Full step lifecycle: step_start → log_chunk → step_finish."""

    def test_step_start_and_log_chunk(self):
        """Single step running: emits step_start and log_chunk."""
        req = _StubRequest(checks_before_disconnect=8)
        pipeline = _simple_pipeline(
            status="running",
            steps=[{"id": 101, "pid": 0, "name": "build", "state": "running"}],
        )

        def _fetch_logs(_handle, _step):
            return ["$ cargo build\n", "   Compiling\n", "   Finished\n"]

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            handle = _stub_handle()
            _setup_db_mock(mock_sm, run_status="running", handles=[handle])
            _setup_wp_mock(mock_wp_cls, pipeline, fetch_logs_fn=_fetch_logs)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=15)

        start_events = [d for t, d in events if t == "step_start"]
        log_events = [d for t, d in events if t == "log_chunk"]

        assert len(start_events) >= 1
        assert start_events[0]["step_name"] == "build"
        assert start_events[0]["batch_id"] == "batch-1"

        assert len(log_events) >= 1
        assert log_events[0]["step_name"] == "build"
        assert "cargo build" in "".join(log_events[0]["lines"])

    def test_step_finish_on_completion(self):
        """Step transitions running→success: emits step_finish, then run_finish."""
        req = _StubRequest(checks_before_disconnect=8)
        pipeline = _simple_pipeline(
            status="success",  # terminal Woodpecker status
            steps=[{"id": 101, "pid": 0, "name": "build", "state": "success"}],
        )
        logs = ["$ cargo build\n", "   Compiling\n", "   Finished\n"]

        def _fetch_logs(_handle, _step):
            return list(logs)

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            handle = _stub_handle()
            # Run is still "running" — enters poll loop, detects terminal Woodpecker
            _setup_db_mock(mock_sm, run_status="running", handles=[handle])
            _setup_wp_mock(mock_wp_cls, pipeline, fetch_logs_fn=_fetch_logs)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=15)

        start = [d for t, d in events if t == "step_start"]
        finish = [d for t, d in events if t == "step_finish"]
        final = [d for t, d in events if t == "run_finish"]

        assert len(start) >= 1
        assert len(finish) >= 1
        assert finish[0]["step_name"] == "build"
        assert finish[0]["exit_code"] == 0
        assert finish[0]["state"] == "success"
        assert len(final) == 1
        assert final[0]["run_id"] == "run-test-1"


class TestMultiStepMultiBatch:
    """Multiple batches with multiple steps — events are tagged with batch_id."""

    def test_two_batches_independent_steps(self):
        """Two batches, each with one step — events carry correct batch_id."""
        req = _StubRequest(checks_before_disconnect=8)
        pipeline_a = _simple_pipeline(
            status="running",
            steps=[{"id": 11, "pid": 0, "name": "lint", "state": "running"}],
        )
        pipeline_b = _simple_pipeline(
            status="running",
            steps=[{"id": 21, "pid": 0, "name": "test", "state": "running"}],
        )

        def _get_pipeline(handle_dict):
            n = handle_dict.get("number")
            return pipeline_a if n == 1 else pipeline_b

        def _fetch_logs(handle_dict, _step):
            n = handle_dict.get("number")
            return (
                ["$ eslint .\n", "  no errors\n"]
                if n == 1
                else ["$ pytest\n", "  15 passed\n"]
            )

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            handle_a = _stub_handle(batch_id="batch-a", number=1)
            handle_b = _stub_handle(batch_id="batch-b", number=2)
            _setup_db_mock(mock_sm, run_status="running", handles=[handle_a, handle_b])
            ma = _setup_wp_mock(mock_wp_cls, pipeline_a, fetch_logs_fn=_fetch_logs)
            ma.get_pipeline = MagicMock(side_effect=_get_pipeline)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=20)

        start_events = [d for t, d in events if t == "step_start"]
        log_events = [d for t, d in events if t == "log_chunk"]

        batch_ids_start = {e["batch_id"] for e in start_events}
        batch_ids_logs = {e["batch_id"] for e in log_events}

        assert "batch-a" in batch_ids_start
        assert "batch-b" in batch_ids_start
        assert "batch-a" in batch_ids_logs
        assert "batch-b" in batch_ids_logs


class TestEventSchema:
    """Event payloads follow the expected schema."""

    def test_step_start_schema(self):
        """step_start has required fields."""
        req = _StubRequest(checks_before_disconnect=3)
        pipeline = _simple_pipeline(
            status="running",
            steps=[{"id": 1, "pid": 0, "name": "build", "state": "running"}],
        )

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            _setup_db_mock(mock_sm, run_status="running", handles=[_stub_handle()])
            _setup_wp_mock(mock_wp_cls, pipeline)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=10)

        start = [d for t, d in events if t == "step_start"]
        assert len(start) >= 1
        d = start[0]
        assert d["run_id"] == "run-test-1"
        assert d["batch_id"] == "batch-1"
        assert d["step_name"] == "build"
        assert isinstance(d["step_id"], int)

    def test_log_chunk_schema(self):
        """log_chunk has required fields."""
        req = _StubRequest(checks_before_disconnect=3)
        pipeline = _simple_pipeline(
            status="running",
            steps=[{"id": 1, "pid": 0, "name": "build", "state": "running"}],
        )

        def _fetch_logs(_h, _s):
            return ["line 1\n", "line 2\n"]

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            _setup_db_mock(mock_sm, run_status="running", handles=[_stub_handle()])
            _setup_wp_mock(mock_wp_cls, pipeline, fetch_logs_fn=_fetch_logs)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=10)

        log_chunks = [d for t, d in events if t == "log_chunk"]
        assert len(log_chunks) >= 1
        d = log_chunks[0]
        assert d["run_id"] == "run-test-1"
        assert d["batch_id"] == "batch-1"
        assert isinstance(d["lines"], list)
        assert len(d["lines"]) == 2

    def test_step_finish_schema(self):
        """step_finish has exit_code and state."""
        req = _StubRequest(checks_before_disconnect=3)
        pipeline = _simple_pipeline(
            status="success",
            steps=[{"id": 1, "pid": 0, "name": "build", "state": "success"}],
        )

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            # Run still "running" — enters poll loop
            _setup_db_mock(mock_sm, run_status="running", handles=[_stub_handle()])
            _setup_wp_mock(mock_wp_cls, pipeline)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=10)

        finish = [d for t, d in events if t == "step_finish"]
        assert len(finish) >= 1
        d = finish[0]
        assert d["run_id"] == "run-test-1"
        assert d["batch_id"] == "batch-1"
        assert d["step_name"] == "build"
        assert d["exit_code"] == 0
        assert d["state"] == "success"

    def test_run_finish_schema(self):
        """run_finish has run_id and status."""
        req = _StubRequest(checks_before_disconnect=2)
        run = _stub_run(status="passed")

        with patch(_SM_PATH) as mock_sm:
            run_result = MagicMock()
            run_result.scalar_one_or_none.return_value = run
            mock_session = MagicMock()
            mock_session.execute = AsyncMock(return_value=run_result)
            mock_sm.return_value.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sm.return_value.return_value.__aexit__ = AsyncMock(return_value=False)

            gen = _run_logs_stream("run-test-1", req)
            events = _collect_events(gen, max_events=5)

        final = [d for t, d in events if t == "run_finish"]
        assert len(final) == 1
        assert final[0]["run_id"] == "run-test-1"
        assert final[0]["status"] == "passed"


class TestClientDisconnect:
    """Clean unsubscribe when client disconnects."""

    def test_disconnect_stops_stream(self):
        """After disconnect, no more events and adapter is closed."""
        req = _StubRequest(checks_before_disconnect=0)  # immediate disconnect

        with (
            patch(_SM_PATH) as mock_sm,
            patch(_WP_PATH) as mock_wp_cls,
        ):
            _setup_db_mock(mock_sm, run_status="running", handles=[_stub_handle()])
            ma = _setup_wp_mock(mock_wp_cls, _simple_pipeline())

            gen = _run_logs_stream("run-test-1", req)

            async def _drive():
                events = []
                async for item in gen:
                    events.append(item)
                return events

            events = asyncio.run(
                asyncio.wait_for(_drive(), timeout=3.0),
            )

        # No step events emitted (disconnect before first tick)
        non_comment = [e for e in events if "comment" not in e]
        assert len(non_comment) == 0
        # Adapter.close() was called
        ma.close.assert_called()