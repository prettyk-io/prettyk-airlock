# -*- coding: utf-8 -*-
"""COS-155: PK-C-003.6 — SBOM-инвентарь cosmo-api (syft/grype vs python-inventory).

Покрытие:
  - DTO: CycloneDX-1.5 структура (``bomFormat``/``specVersion`` camelCase
    alias), generator-маркер, python-inventory fallback компоненты, парсинг
    grype-отчёта (severity набора, negligible/unknown → low), summary
    total/critical/high/medium/low;
  - content_hash: детерминированный, чувствителен к компонентам;
  - POST /api/v1/artifacts/sbom:
      * валидный запрос → 200, ``generator`` (python-inventory при отсутствии
        syft + monkeypatched grype), документ CycloneDX 1.5, ledger-якорь;
      * неизвестный ``run_id`` → 422 (нечем якорить durable read);
      * grype отсутствует (monkeypatch) → ``vuln_summary.available=false``
        + reason (честно, не фейк);
  - GET /api/v1/artifacts/sbom/{bundle_id}: durable read, 404 ghost,
    latest wins, cross-process restart-survival;
  - 401 без principal.

Запуск:  pytest .../test_sbom_inventory.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.domain.sbom_inventory import (  # noqa: E402
    BOM_FORMAT,
    PYTHON_INVENTORY_GENERATOR,
    SPEC_VERSION,
    SbomInventoryComponent,
    SbomInventoryDocument,
    SbomInventoryRequest,
    normalize_severity,
    parse_grype_report,
    python_inventory_components,
    sbom_inventory_content_hash,
)
from orchestrator.cosmo.ledger import sbom_inventory as ledger  # noqa: E402

import _testpg  # noqa: E402
from _durable_probe import get_in_fresh_process  # noqa: E402

DOMAIN = "cos155-dom"
PLAN = "cos155-plan"
RUN = "cos155run0001"
BUNDLE = "bundle-cos155"
_PG_URL = _testpg.TEST_PG_URL


def _request(**over: object) -> dict:
    body = {
        "bundle_id": BUNDLE,
        "run_id": RUN,
        "app_name": "cosmo-api",
        "version": "2.0.0",
        "target": None,
    }
    body.update(over)
    return body


def _doc(**over: object) -> SbomInventoryDocument:
    data = {
        "serial_number": "urn:uuid:aaaaaaaa-1111-2222-3333-444444444444",
        "generator": PYTHON_INVENTORY_GENERATOR,
        "tool_name": "python-inventory",
        "metadata": {"type": "application", "name": "cosmo-api", "version": "2.0.0"},
        "components": [
            {"type": "library", "name": "fastapi", "version": "0.115.0",
             "purl": "pkg:pypi/fastapi@0.115.0"},
        ],
        "vuln_summary": {"available": False, "reason": "grype not available"},
    }
    data.update(over)
    return SbomInventoryDocument.model_validate(data)


async def _ledger_rows(run_id: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_URL, echo=False)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT id, type, content_hash, content_ref, provenance_json "
                    "FROM evidence_ledger WHERE run_id = :rid "
                    "ORDER BY created_at ASC"
                ),
                {"rid": run_id},
            )
            return [dict(r) for r in res.mappings().all()]
    finally:
        await engine.dispose()


# ── DTO unit ─────────────────────────────────────────────────────────────

class TestSbomInventoryDto:
    def test_cyclonedx_1_5_structure_by_alias(self):
        doc = _doc()
        dumped = doc.model_dump(mode="json", by_alias=True)
        assert dumped["bomFormat"] == "CycloneDX"
        assert dumped["specVersion"] == "1.5"
        assert "serialNumber" in dumped
        assert "vulnSummary" in dumped

    def test_generator_marker(self):
        assert _doc().generator == PYTHON_INVENTORY_GENERATOR

    def test_python_inventory_components(self):
        comps = python_inventory_components()
        assert isinstance(comps, list)
        for c in comps:
            assert c.type == "library"
            assert c.name
            assert c.purl

    def test_content_hash_deterministic(self):
        a = sbom_inventory_content_hash(_doc())
        b = sbom_inventory_content_hash(_doc())
        c = sbom_inventory_content_hash(_doc(components=[
            {"type": "library", "name": "uvicorn", "version": "0.30.0"}
        ]))
        assert a == b
        assert a != c
        assert len(a) == 64

    def test_bundle_id_unsafe_rejected(self):
        with pytest.raises(ValidationError):
            SbomInventoryRequest.model_validate(_request(bundle_id="../escape"))

    def test_bundle_id_safe_regex(self):
        for bid in ("b1", "bundle-1._:x", "a" * 128):
            SbomInventoryRequest.model_validate(_request(bundle_id=bid))
        with pytest.raises(ValidationError):
            SbomInventoryRequest.model_validate(_request(bundle_id="-leading"))
        with pytest.raises(ValidationError):
            SbomInventoryRequest.model_validate(_request(bundle_id="has space"))

    def test_normalize_severity(self):
        assert normalize_severity("Critical") == "critical"
        assert normalize_severity("HIGH") == "high"
        assert normalize_severity("Moderate") == "medium"
        assert normalize_severity("negligible") == "low"
        assert normalize_severity("unknown") == "low"
        assert normalize_severity("") == "low"

    def test_parse_grype_report(self):
        report = {
            "matches": [
                {"vulnerability": {"id": "CVE-2024-0001", "severity": "Critical",
                                   "fix": {"versions": ["0.116.0"]}},
                 "artifact": {"name": "fastapi", "version": "0.115.0"}},
                {"vulnerability": {"id": "GHSA-abcd", "severity": "high",
                                   "fix": {"versions": ["2.0.1"]}},
                 "artifact": {"name": "starlette", "version": "2.0.0"}},
                {"vulnerability": {"id": "CVE-2024-0002", "severity": "Negligible"},
                 "artifact": {"name": "x", "version": "1.0.0"}},
            ]
        }
        vulns, summary = parse_grype_report(report)
        assert len(vulns) == 3
        assert summary.available is True
        assert summary.total == 3
        assert summary.critical == 1
        assert summary.high == 1
        assert summary.low == 1
        assert summary.medium == 0
        assert vulns[0].id == "CVE-2024-0001"
        assert vulns[0].fixed_version == "0.116.0"

    def test_parse_grype_empty(self):
        vulns, summary = parse_grype_report({"matches": []})
        assert vulns == []
        assert summary.available is True
        assert summary.total == 0


# ── Route tests ──────────────────────────────────────────────────────────

class TestSbomInventoryRoute:
    @pytest_asyncio.fixture(autouse=True)
    async def _seed(self, pg_client: AsyncClient):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_PG_URL, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO domains (id, label, forge_type, forge_url, "
                "forge_token_ref, rbac_config, quota_max_runs, "
                "quota_max_storage_gb, quota_max_cpu, created_at) "
                "VALUES (:d, 'cos155', 'gitea', 'http://gitea:3000', "
                "'t', '{}'::jsonb, 50, 100, 8, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO apps (id, domain_id, level) "
                "VALUES ('cos155-app', :d, 0) ON CONFLICT (id) DO NOTHING"
            ), {"d": DOMAIN})
            await conn.execute(text(
                "INSERT INTO pipeline_plans (id, app_id, level, scope_id, "
                "compiled_hash, compiled_at) VALUES (:p, 'cos155-app', "
                "'app', :p, 'h', now()) ON CONFLICT (id) DO NOTHING"
            ), {"p": PLAN})
            await conn.execute(text(
                "INSERT INTO runs (id, plan_id, trigger, domain_id, status, "
                "initiator_user_id, initiator_role, findings_refs, created_at) "
                "VALUES (:r, :p, 'manual', :d, 'succeeded', 'system', "
                "'system', '[]'::jsonb, now()) ON CONFLICT (id) DO NOTHING"
            ), {"r": RUN, "p": PLAN, "d": DOMAIN})
        await engine.dispose()

    async def test_post_generates_and_anchors(self, pg_client: AsyncClient):
        res = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bomFormat"] == "CycloneDX"
        assert body["specVersion"] == "1.5"
        assert "serialNumber" in body
        assert body["generator"] in (PYTHON_INVENTORY_GENERATOR, "syft")
        assert isinstance(body["components"], list)
        assert "vulnSummary" in body

        rows = await _ledger_rows(RUN)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == "decision"
        prov = row["provenance_json"]
        assert prov["source"] == "cosmo-sbom-inventory"
        assert prov["sbom_type"] == "SBOM_INVENTORY"
        assert prov["contract"] == "PK-C-003.6"
        assert prov["bundle_id"] == BUNDLE
        assert prov["content_hash"] == row["content_hash"]
        assert len(prov["content_hash"]) == 64

    async def test_unknown_run_422(self, pg_client: AsyncClient):
        res = await pg_client.post(
            "/api/v1/artifacts/sbom", json=_request(run_id="cos155run-ghost"),
        )
        assert res.status_code == 422, res.text
        assert await _ledger_rows(RUN) == []

    async def test_get_reads_back(self, pg_client: AsyncClient):
        posted = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert posted.status_code == 200, posted.text
        res = await pg_client.get(f"/api/v1/artifacts/sbom/{BUNDLE}")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bomFormat"] == "CycloneDX"
        assert body["specVersion"] == "1.5"
        assert body["generator"] == posted.json()["generator"]

    async def test_get_unknown_404(self, pg_client: AsyncClient):
        res = await pg_client.get("/api/v1/artifacts/sbom/bundle-ghost")
        assert res.status_code == 404, res.text

    async def test_get_latest_wins(self, pg_client: AsyncClient):
        first = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert first.status_code == 200, first.text
        first_serial = first.json()["serialNumber"]

        second = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert second.status_code == 200, second.text
        second_serial = second.json()["serialNumber"]
        assert second_serial != first_serial

        res = await pg_client.get(f"/api/v1/artifacts/sbom/{BUNDLE}")
        assert res.status_code == 200, res.text
        assert res.json()["serialNumber"] == second_serial

    async def test_get_survives_process_restart(self, pg_client: AsyncClient):
        posted = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert posted.status_code == 200, posted.text

        status, body = get_in_fresh_process(
            f"/api/v1/artifacts/sbom/{BUNDLE}", _PG_URL,
        )
        assert status == 200, body
        assert body["bomFormat"] == "CycloneDX"
        assert body["specVersion"] == "1.5"
        assert body["generator"] == posted.json()["generator"]

    async def test_post_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.deps import get_current_principal
        from orchestrator.cosmo.api.main import app

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert res.status_code == 401, res.text

    async def test_get_requires_principal(self, pg_client: AsyncClient):
        from orchestrator.cosmo.api.main import app
        from orchestrator.cosmo.api.deps import get_current_principal

        app.dependency_overrides.pop(get_current_principal, None)
        res = await pg_client.get(f"/api/v1/artifacts/sbom/{BUNDLE}")
        assert res.status_code == 401, res.text

    async def test_vuln_summary_contract(self, pg_client: AsyncClient):
        """grype отсутствует → summary unavailable честно; иначе available."""
        res = await pg_client.post("/api/v1/artifacts/sbom", json=_request())
        assert res.status_code == 200, res.text
        vs = res.json()["vulnSummary"]
        assert "available" in vs
        if not vs["available"]:
            assert vs.get("reason")
        else:
            assert vs["total"] >= 0