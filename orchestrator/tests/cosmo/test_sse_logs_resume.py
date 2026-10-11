# -*- coding: utf-8 -*-
"""COS-180: SSE resume логов прогона — event id + backlog replay.

Покрытие acceptance COS-180:
  - каждое data-событие лог-стрима несёт SSE ``id`` (инвариант COS-088:
    SSE id == backlog id), первым идёт ``stream_backlog``-флаг;
  - реконнект с ``last_event_id``: недоставленные события реплеятся из окна
    backlog в порядке, уже доставленные строки повторно не отдаются
    (курсоры (batch, step) восстанавливаются из окна);
  - gap / недоступность backlog → ``resync``-событие, не тишина;
  - свежий коннект по-прежнему делает полный catch-up (совместимость COS-109);
  - ``run_finish`` не дублируется на реконнекте, если уже лежит в backlog.

Живой Gitea/Woodpecker не требуется: DB и WoodpeckerAdapter мокаются
(паттерн COS-109), backlog — реальный модуль в memory-режиме.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api import sse_backlog  # noqa: E402
from orchestrator.cosmo.api.routes import sse as sse_mod  # noqa: E402
from orchestrator.cosmo.api.routes.sse import (  # noqa: E402
    _LOG_BACKLOG_KIND,
    _run_logs_stream,
    _seed_log_cursors,
)

RUN_ID = "run-cos180"
SM_PATH = "orchestrator.cosmo.api.routes.sse.get_sessionmaker"
WP_PATH = "orchestrator.cosmo.adapters.execution_woodpecker.WoodpeckerAdapter"


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """Поллинг-тик стрима — 10 мс: тесты не ждут реальные секунды."""
    monkeypatch.setattr(sse_mod, "_LOGS_POLL_S", 0.01)


@pytest.fixture()
def memory_backlog(monkeypatch):
    """Реальный sse_backlog в memory-режиме (детерминированно, без valkey)."""
    monkeypatch.setattr(sse_backlog, "_valkey_client", None)
    monkeypatch.setattr(sse_backlog, "_get_valkey", lambda: None)
    sse_backlog.reset_backlog()
    yield sse_backlog
    sse_backlog.reset_backlog()


# ── Stubs (паттерн COS-109) ───────────────────────────────────────────


class _StubRequest:
    def __init__(self, checks_before_disconnect: int = 20) -> None:
        self._checks_left = checks_before_disconnect
        self.headers: dict[str, str] = {}

    async def is_disconnected(self) -> bool:
        if self._checks_left <= 0:
            return True
        self._checks_left -= 1
        return False


def _stub_run(status: str = "running"):
    r = MagicMock()
    r.id = RUN_ID
    r.status = status
    r.plan_id = "plan-cos180"
    r.trigger = "manual"
    r.domain_id = "d-cos180"
    r.started_at = None
    r.finished_at = None
    return r


def _stub_handle(batch_id: str = "batch-1", number: int = 1):
    h = MagicMock()
    h.batch_id = batch_id
    h.run_id = RUN_ID
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
            "job_id": h.wp_pipeline_id, "number": h.wp_number, "repo_id": h.repo_id,
            "repo_owner": h.repo_owner, "repo_name": h.repo_name, "branch": h.branch,
        }

    h.as_handle_dict = _as_handle_dict
    return h


def _simple_pipeline(status: str = "running", steps: list | None = None):
    wf_steps = steps or [{"id": 1, "pid": 0, "name": "build", "state": "running"}]
    return {"status": status, "workflows": [{"name": "default", "steps": wf_steps}]}


def _flatten_steps(pipeline: dict) -> list[dict]:
    out = []
    for wf in pipeline.get("workflows", []):
        for st in wf.get("steps", []):
            out.append({
                "id": st.get("id"), "pid": st.get("pid", 0),
                "name": st.get("name", "unknown"),
                "state": st.get("state", "pending"),
                "workflow": wf.get("name"),
            })
    return out


def _setup_db_mock(mock_sm, *, run_status="running", handles=None):
    run = _stub_run(status=run_status)
    handle_list = handles or []
    mock_session = MagicMock()

    async def _execute(_stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = run
        result.scalars.return_value.all.return_value = list(handle_list)
        return result

    mock_session.execute = _execute
    mock_sm.return_value.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_sm.return_value.return_value.__aexit__ = AsyncMock(return_value=False)
    return run, handle_list


def _setup_wp_mock(mock_wp_cls, pipeline, fetch_logs_fn=None):
    ma = MagicMock()
    ma.get_pipeline.return_value = pipeline
    ma._flatten_steps = _flatten_steps
    ma._fetch_step_logs = MagicMock(
        side_effect=fetch_logs_fn if fetch_logs_fn else (lambda h, s: [])
    )
    ma.close = MagicMock()
    mock_wp_cls.return_value = ma
    return ma


def _collect(gen_coro, timeout: float = 5.0) -> list[dict]:
    """Сырые SSE-items генератора (comments пропущены)."""
    events: list[dict] = []

    async def _drive():
        async for item in gen_coro:
            if "comment" in item:
                continue
            events.append(item)

    asyncio.run(asyncio.wait_for(_drive(), timeout=timeout))
    return events


def _lines(events: list[dict]) -> list[str]:
    out: list[str] = []
    for e in events:
        if e.get("event") == "log_chunk":
            out.extend(json.loads(e["data"]).get("lines") or [])
    return out


def _drive_conn(logs: list[str], last_event_id: str = "",
                checks: int = 8) -> list[dict]:
    """Одна SSE-сессия лог-стрима против замоканных DB/Woodpecker."""
    with patch(SM_PATH) as mock_sm, patch(WP_PATH) as mock_wp:
        _setup_db_mock(mock_sm, run_status="running", handles=[_stub_handle()])
        _setup_wp_mock(mock_wp, _simple_pipeline(),
                       fetch_logs_fn=lambda h, s: list(logs))
        return _collect(
            _run_logs_stream(RUN_ID, _StubRequest(checks_before_disconnect=checks),
                             last_event_id)
        )


def _last_data_id(events: list[dict]) -> str:
    ids = [e["id"] for e in events if e.get("id")]
    assert ids, f"no backlog ids in events: {events}"
    return ids[-1]


# ── Флаг и id ─────────────────────────────────────────────────────────


class TestFlagAndIds:

    def test_flag_first_and_data_events_carry_unique_ids(self, memory_backlog):
        events = _drive_conn(["a\n", "b\n"])

        assert events[0]["event"] == "stream_backlog"
        assert "id" not in events[0]

        data_events = [
            e for e in events
            if e["event"] in ("step_start", "log_chunk", "step_finish", "run_finish")
        ]
        assert data_events, "step lifecycle must be emitted"
        ids = [e.get("id") for e in data_events]
        assert all(ids), "каждое data-событие лог-стрима обязано нести backlog id"
        assert len(set(ids)) == len(ids), "ids уникальны"
        # id принадлежат backlog-стриму runlog (инвариант SSE id == backlog id)
        window_ids = {
            r.id for r in memory_backlog.read_window(_LOG_BACKLOG_KIND, RUN_ID)
        }
        assert set(ids) <= window_ids

    def test_fresh_connect_still_catches_up_full_log(self, memory_backlog):
        """Совместимость COS-109: без last_event_id — полный catch-up."""
        events = _drive_conn(["x\n", "y\n", "z\n"])
        assert _lines(events) == ["x\n", "y\n", "z\n"]


# ── Реконнект: replay + позиция курсоров ──────────────────────────────


class TestResumeReplay:

    def test_missed_replayed_once_and_no_duplicate_lines(self, memory_backlog):
        """Ядро COS-180: пропуск доставлен, обработанное не дублируется."""
        logs = ["a\n", "b\n", "c\n"]
        events1 = _drive_conn(logs)
        last_id = _last_data_id(events1)

        # «офлайн»: другой поток доставил строку d и записал чанк в backlog
        logs.append("d\n")
        missed_id = memory_backlog.publish(
            _LOG_BACKLOG_KIND, RUN_ID, "log_chunk",
            json.dumps({"run_id": RUN_ID, "batch_id": "batch-1",
                        "step_name": "build", "lines": ["d\n"]}),
        )
        assert missed_id
        # после реконнекта появляется ещё строка
        logs.append("e\n")

        events2 = _drive_conn(logs, last_event_id=last_id)

        assert events2[0]["event"] == "stream_backlog"
        # пропущенный чанк доставлен ровно один раз и с исходным id
        replayed = [e for e in events2 if e.get("id") == missed_id]
        assert len(replayed) == 1, f"missed chunk must be replayed once: {events2}"
        assert replayed[0]["event"] == "log_chunk"
        # уже доставленные a..c повторно НЕ отдаются, новые строки доезжают
        conn2_lines = _lines(events2)
        assert "d\n" in conn2_lines
        assert "e\n" in conn2_lines
        assert "a\n" not in conn2_lines
        assert "b\n" not in conn2_lines
        assert "c\n" not in conn2_lines
        # без потерь и дублей: a..e ровно по одному разу на обеих сессиях
        combined = _lines(events1) + conn2_lines
        for line in ("a\n", "b\n", "c\n", "d\n", "e\n"):
            assert combined.count(line) == 1, f"{line!r} must appear exactly once"
        # step_start уже известного шага не пере-выводится
        assert not [e for e in events2 if e["event"] == "step_start"]

    def test_multiple_missed_events_replayed_in_order(self, memory_backlog):
        logs = ["a\n"]
        events1 = _drive_conn(logs)
        last_id = _last_data_id(events1)

        missed_ids = [
            memory_backlog.publish(
                _LOG_BACKLOG_KIND, RUN_ID, "log_chunk",
                json.dumps({"run_id": RUN_ID, "batch_id": "batch-1",
                            "step_name": "build", "lines": [f"{c}\n"]}),
            )
            for c in ("b", "c", "d")
        ]
        logs.extend(["b\n", "c\n", "d\n"])

        events2 = _drive_conn(logs, last_event_id=last_id, checks=4)

        replayed_ids = [e["id"] for e in events2 if e.get("id") in set(missed_ids)]
        assert replayed_ids == missed_ids, "replay сохраняет порядок публикации"

    def test_gap_triggers_resync_then_catch_up(self, memory_backlog):
        logs = ["a\n"]
        _drive_conn(logs)

        events2 = _drive_conn(logs, last_event_id="9999999999999-0", checks=4)

        resyncs = [e for e in events2 if e["event"] == "resync"]
        assert len(resyncs) == 1, f"gap must trigger exactly one resync: {events2}"
        assert json.loads(resyncs[0]["data"])["reason"] == "gap"
        # после resync — обычный catch-up, не тишина
        assert _lines(events2) == logs

    def test_backlog_unavailable_triggers_resync(self, memory_backlog, monkeypatch):
        logs = ["a\n"]
        events1 = _drive_conn(logs)
        last_id = _last_data_id(events1)

        monkeypatch.setattr(sse_backlog, "read_window", lambda *a, **k: None)

        events2 = _drive_conn(logs, last_event_id=last_id, checks=4)

        resyncs = [e for e in events2 if e["event"] == "resync"]
        assert len(resyncs) == 1
        assert json.loads(resyncs[0]["data"])["reason"] == "backlog_unavailable"
        assert _lines(events2) == logs  # честный catch-up, не тишина

    def test_replayed_run_finish_is_not_duplicated(self, memory_backlog):
        logs = ["a\n"]
        events1 = _drive_conn(logs)
        last_id = _last_data_id(events1)

        rf_id = memory_backlog.publish(
            _LOG_BACKLOG_KIND, RUN_ID, "run_finish",
            json.dumps({"run_id": RUN_ID, "status": "passed"}),
        )

        with patch(SM_PATH) as mock_sm:
            _setup_db_mock(mock_sm, run_status="passed", handles=[])
            events2 = _collect(
                _run_logs_stream(RUN_ID, _StubRequest(checks_before_disconnect=2),
                                 last_id)
            )

        finals = [e for e in events2 if e["event"] == "run_finish"]
        assert len(finals) == 1, f"run_finish must not be duplicated: {events2}"
        assert finals[0]["id"] == rf_id


# ── Восстановление курсоров ───────────────────────────────────────────


class TestCursorSeed:

    def test_seed_reconstructs_state_and_line_count(self, memory_backlog):
        def _pub(event: str, payload: dict) -> None:
            memory_backlog.publish(_LOG_BACKLOG_KIND, RUN_ID, event, json.dumps(payload))

        _pub("step_start", {"run_id": RUN_ID, "batch_id": "b1",
                            "step_name": "build", "step_id": 1})
        _pub("log_chunk", {"run_id": RUN_ID, "batch_id": "b1",
                           "step_name": "build", "lines": ["1", "2", "3"]})
        _pub("log_chunk", {"run_id": RUN_ID, "batch_id": "b1",
                           "step_name": "build", "lines": ["4", "5"]})
        _pub("step_finish", {"run_id": RUN_ID, "batch_id": "b1",
                             "step_name": "build", "exit_code": 0, "state": "success"})

        cursors: dict = {}
        _seed_log_cursors(cursors, memory_backlog.read_window(_LOG_BACKLOG_KIND, RUN_ID))
        assert cursors[("b1", "build")] == ("success", 5)

    def test_seed_marks_running_step(self, memory_backlog):
        memory_backlog.publish(
            _LOG_BACKLOG_KIND, RUN_ID, "log_chunk",
            json.dumps({"run_id": RUN_ID, "batch_id": "b1",
                        "step_name": "lint", "lines": ["x"]}),
        )
        cursors: dict = {}
        _seed_log_cursors(cursors, memory_backlog.read_window(_LOG_BACKLOG_KIND, RUN_ID))
        assert cursors[("b1", "lint")] == ("running", 1)
