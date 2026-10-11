# -*- coding: utf-8 -*-
"""SAST-STEP-1: юнит-тесты маркера отчёта и durable-захвата.

Покрытие:
  - маркер: emit→parse→verify round-trip (sarif / ce-issues), payload == исходник;
  - битый ввод: не-маркер, битый base64/gzip → None (не выдумываем отчёт);
  - find: последний валидный маркер среди шагов/шума; нет маркера → None;
  - verify: bytes/sha/format несоответствия → честная причина;
  - sast_report_bricks: только sast-кирпичи (brick.type / definition.type);
  - capture: no-op без sast; Missing без маркера; Invalid при подмене sha;
    валидный — store + EvidenceLedgerEntry(raw_response) без PG (fake append).

Живой прогон (pipeline → логи → захват) — в seed-sast-fixture.py; здесь —
DOM-free/без-PG логика контракта.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from orchestrator.cosmo.control_plane import sast_capture  # noqa: E402
from orchestrator.cosmo.control_plane.sast_capture import (  # noqa: E402
    InvalidSastReportError,
    MissingSastReportError,
    capture_sast_reports,
    sast_report_bricks,
)
from orchestrator.cosmo.domain.sast_report import (  # noqa: E402
    SAST_REPORT_MARKER_PREFIX,
    SastReportMarker,
    emit_sast_report_marker,
    find_sast_report_marker,
    parse_sast_report_marker,
    verify_sast_report_marker,
)
from orchestrator.cosmo.ledger.artifact_store import ArtifactStore  # noqa: E402

REPORT = json.dumps({"issues": [{"rule": "python:S2068", "line": 3}]}).encode("utf-8")
SAST_BRICK = {"name": "Sonar SAST", "type": "sast",
              "definition": {"executor": "woodpecker", "image": "sonarsource/sonar-scanner-cli"}}


# ── Маркер: round-trip ────────────────────────────────────────────────────

class TestMarkerRoundTrip:
    @pytest.mark.parametrize("fmt", ["sarif", "ce-issues"])
    def test_emit_parse_verify(self, fmt: str):
        line = emit_sast_report_marker(REPORT, fmt=fmt)
        assert line.startswith(SAST_REPORT_MARKER_PREFIX)
        marker = parse_sast_report_marker(line)
        assert marker is not None
        assert marker.format == fmt
        assert marker.bytes_len == len(REPORT)
        assert marker.payload == REPORT
        assert verify_sast_report_marker(marker) == ""

    def test_unknown_format_rejected(self):
        with pytest.raises(ValueError):
            emit_sast_report_marker(REPORT, fmt="xml")

    def test_empty_report_is_valid(self):
        """Чистый скан (0 findings) — это отчёт, не отсутствие отчёта."""
        line = emit_sast_report_marker(b'{"issues": []}', fmt="ce-issues")
        marker = parse_sast_report_marker(line)
        assert marker is not None and marker.payload == b'{"issues": []}'
        assert verify_sast_report_marker(marker) == ""


class TestMarkerNegative:
    def test_non_marker_line(self):
        assert parse_sast_report_marker("sonar-scanner INFO done") is None

    def test_broken_base64(self):
        assert parse_sast_report_marker(
            f"{SAST_REPORT_MARKER_PREFIX} format=sarif sha256={'0' * 64} "
            f"bytes=10 b64=@@@not-base64@@@"
        ) is None

    def test_broken_gzip(self):
        import base64
        payload = base64.b64encode(b"not gzip at all").decode()
        assert parse_sast_report_marker(
            f"{SAST_REPORT_MARKER_PREFIX} format=sarif sha256={'0' * 64} "
            f"bytes=15 b64={payload}"
        ) is None

    def test_bytes_mismatch(self):
        marker = SastReportMarker(format="sarif", sha256="0" * 64,
                                  bytes_len=999, payload=b"x")
        assert "bytes mismatch" in verify_sast_report_marker(marker)

    def test_sha_mismatch(self):
        marker = SastReportMarker(format="sarif", sha256="0" * 64,
                                  bytes_len=1, payload=b"x")
        assert "sha256 mismatch" in verify_sast_report_marker(marker)

    def test_unknown_format_in_marker(self):
        marker = SastReportMarker(format="xml", sha256="0" * 64,
                                  bytes_len=1, payload=b"x")
        assert "unknown format" in verify_sast_report_marker(marker)


class TestFindMarker:
    def test_finds_latest_valid_marker(self):
        line1 = emit_sast_report_marker(b'{"scan": 1}')
        line2 = emit_sast_report_marker(REPORT, fmt="ce-issues")
        logs = {
            "sonar-scan": ["INFO scan done", line1],
            "sonar-report": ["noise", line2, "trailing noise"],
        }
        marker = find_sast_report_marker(logs)
        assert marker is not None and marker.payload == REPORT

    def test_no_marker(self):
        assert find_sast_report_marker({"sonar-scan": ["INFO only"]}) is None


# ── Кирпичи ───────────────────────────────────────────────────────────────

class TestSastBricks:
    def test_selects_brick_type_sast(self):
        assert sast_report_bricks([SAST_BRICK]) == [SAST_BRICK]

    def test_selects_definition_type_sast(self):
        legacy = {"name": "L", "definition": {"type": "sast"}}
        assert sast_report_bricks([legacy]) == [legacy]

    def test_ignores_other_bricks(self):
        other = {"name": "Build", "type": "build", "definition": {"type": "docker_build"}}
        assert sast_report_bricks([other]) == []


class TestDockerBuildSpecsRefTolerance:
    """SAST-STEP-1: bricks_refs живого компилятора — ID-строки; спеки — только dict.

    Найдено живым прогоном: AttributeError в docker_build_specs обрывал
    write_run_evidence ДО SAST-капчура; не-dict refs должны пропускаться.
    """

    def test_string_refs_do_not_crash(self):
        from orchestrator.cosmo.control_plane.artifact_capture import docker_build_specs
        assert docker_build_specs(["sast-sonarqube"]) == []
        assert docker_build_specs(None) == []

    def test_dict_refs_still_parsed(self):
        from orchestrator.cosmo.control_plane.artifact_capture import docker_build_specs
        brick = {"name": "b", "definition": {
            "type": "docker_build", "image_name": "app", "version": "1.0.0",
            "registry": "reg:5000",
        }}
        specs = docker_build_specs([brick, "sast-sonarqube"])
        assert len(specs) == 1
        assert specs[0].image_name == "app"


class TestGeneratePipelineYamlSastStep:
    """SAST-STEP-1: аудит-форма кирпича (generate_pipeline_yaml) несёт entrypoint/inputs."""

    @staticmethod
    def _adapter():
        from orchestrator.cosmo.adapters.execution_woodpecker import WoodpeckerAdapter
        return WoodpeckerAdapter(base_url="http://wp.local", token="t")

    def test_entrypoint_and_env_passthrough(self):
        import yaml
        batch = {"bricks": [{
            "name": "Sonar SAST",
            "definition": {
                "type": "sast",
                "executor": "woodpecker",
                "image": "sonarsource/sonar-scanner-cli:latest",
                "entrypoint": [""],
                "commands": ["sonar-scanner -Dsonar.host.url=$SONAR_HOST_URL"],
                "inputs": {"SONAR_PROJECT_KEY": "cosmo__sast-fixture"},
            },
        }]}
        parsed = yaml.safe_load(self._adapter().generate_pipeline_yaml(batch))
        step = parsed["steps"]["Sonar SAST"]
        assert step["entrypoint"] == [""]
        assert step["image"].startswith("sonarsource/")
        assert step["environment"] == {"SONAR_PROJECT_KEY": "cosmo__sast-fixture"}

    def test_entrypoint_absent_by_default(self):
        import yaml
        batch = {"bricks": [{"name": "plain", "definition": {"image": "alpine:3.20"}}]}
        parsed = yaml.safe_load(self._adapter().generate_pipeline_yaml(batch))
        assert "entrypoint" not in parsed["steps"]["plain"]


# ── Capture (fake append, без PG) ────────────────────────────────────────

@pytest.fixture()
def captured_entries(monkeypatch):
    captured: list = []

    async def _fake_append(session, entry):
        if not entry.id:
            entry.id = "ev-test-entry"
        captured.append(entry)
        return "chain-hash"

    monkeypatch.setattr(sast_capture, "append_evidence_entry", _fake_append)
    return captured


class TestCapture:
    @pytest.mark.asyncio
    async def test_noop_without_sast_bricks(self, captured_entries):
        out = await capture_sast_reports(
            None, run_id="run-1", batch_id="b-1",
            bricks=[{"name": "Build", "type": "build"}],
            logs={"build": ["ok"]},
        )
        assert out == [] and captured_entries == []

    @pytest.mark.asyncio
    async def test_missing_marker_raises(self, captured_entries):
        with pytest.raises(MissingSastReportError):
            await capture_sast_reports(
                None, run_id="run-1", batch_id="b-1",
                bricks=[SAST_BRICK], logs={"sonar-scan": ["boom: connection refused"]},
            )
        assert captured_entries == []

    @pytest.mark.asyncio
    async def test_tampered_marker_raises_invalid(self, captured_entries):
        valid = emit_sast_report_marker(REPORT)
        tampered = re.sub(r"sha256=[0-9a-f]{64}", f"sha256={'a' * 64}", valid)
        with pytest.raises(InvalidSastReportError) as ei:
            await capture_sast_reports(
                None, run_id="run-1", batch_id="b-1",
                bricks=[SAST_BRICK], logs={"sonar-report": [tampered]},
            )
        assert "sha256 mismatch" in ei.value.problem
        assert captured_entries == []

    @pytest.mark.asyncio
    async def test_valid_marker_captured_durably(self, captured_entries, tmp_path):
        line = emit_sast_report_marker(REPORT, fmt="ce-issues")
        store = ArtifactStore(base_dir=tmp_path)
        ids = await capture_sast_reports(
            None, run_id="run-1", batch_id="b-1",
            bricks=[SAST_BRICK], logs={"sonar-report": [line]},
            store=store,
        )
        assert ids == ["ev-test-entry"]
        assert len(captured_entries) == 1
        entry = captured_entries[0]
        assert entry.type == "raw_response"
        assert entry.run_id == "run-1" and entry.batch_id == "b-1"
        assert entry.content_ref.startswith("artifact://")
        assert entry.content_hash == hashlib.sha256(REPORT).hexdigest()
        assert entry.provenance_json["source"] == "sonarqube"
        assert entry.provenance_json["format"] == "ce-issues"
        assert entry.provenance_json["bytes"] == len(REPORT)
        # blobs: файл реально записан в store под provenance run/batch
        stored = list((tmp_path / "run-1" / "b-1" / "sast-report").glob("response_*"))
        assert len(stored) == 1
        assert stored[0].read_bytes() == REPORT
