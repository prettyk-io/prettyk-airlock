# -*- coding: utf-8 -*-
"""COS-011: SSE streaming — юнит-тесты hashing и format (no DB required)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.api.routes.sse import (
    _snapshot_hash,
    _sse_formatter,
)


class TestSnapshotHash:
    def test_hash_is_deterministic(self):
        snap = {"run": {"status": "running"}, "batches": [], "gates": []}
        assert _snapshot_hash(snap) == _snapshot_hash(snap)

    def test_hash_changes_on_status_change(self):
        snap1 = {"run": {"status": "running"}, "batches": [], "gates": []}
        snap2 = {"run": {"status": "succeeded"}, "batches": [], "gates": []}
        assert _snapshot_hash(snap1) != _snapshot_hash(snap2)

    def test_hash_changes_on_batch_complete(self):
        snap1 = {"run": {"status": "running"}, "batches": [
            {"id": "b1", "type": "build", "status": "running"}], "gates": []}
        snap2 = {"run": {"status": "running"}, "batches": [
            {"id": "b1", "type": "build", "status": "passed"}], "gates": []}
        assert _snapshot_hash(snap1) != _snapshot_hash(snap2)


class TestSseFormatter:
    @pytest.mark.asyncio
    async def test_formats_status_change(self):
        async def gen():
            yield {"event": "status_change", "data": '{"status":"running"}'}
        combined = ""
        async for line in _sse_formatter(gen()):
            combined += line
        assert "event: status_change" in combined
        assert '{"status":"running"}' in combined

    @pytest.mark.asyncio
    async def test_formats_keepalive_comment(self):
        async def gen():
            yield {"comment": ""}
        lines = []
        async for line in _sse_formatter(gen()):
            lines.append(line)
        assert lines[0] == ": \n\n"

    @pytest.mark.asyncio
    async def test_sse_ends_with_double_newline(self):
        async def gen():
            yield {"event": "status_change", "data": "ok"}
        lines = []
        async for line in _sse_formatter(gen()):
            lines.append(line)
        assert lines[0].endswith("\n\n")

    @pytest.mark.asyncio
    async def test_multiple_events(self):
        async def gen():
            yield {"event": "status_change", "data": "running"}
            yield {"event": "batch_complete", "data": '{"id":"b1"}'}
        lines = []
        async for line in _sse_formatter(gen()):
            lines.append(line)
        assert len(lines) == 2
        assert "status_change" in lines[0]
        assert "batch_complete" in lines[1]