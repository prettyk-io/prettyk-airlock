# -*- coding: utf-8 -*-
"""COS-183: live offline grype scan — self-skip, когда бинарь/DB недоступны.

Тест прогоняет РЕАЛЬНЫЙ grype (offline DB) на игрушечном CycloneDX-SBOM:

  - grype нет на PATH → skip (оффлайн-контур без инструмента — честно);
  - бинарь есть, но DB пуста/недоступна → skip по reason из результата;
  - всё есть → source="grype", реальные matches (requests 2.19.0 уязвим).

Запуск в контейнере cosmo-api (там бинарь + DB):
  docker exec cosmo-api python -m pytest orchestrator/tests/cosmo/test_grype_scan_live.py -q
"""
from __future__ import annotations

import shutil

import pytest

from orchestrator.cosmo.transfer.sbom import generate_vuln_report

pytestmark = pytest.mark.skipif(
    shutil.which("grype") is None,
    reason="grype binary not on PATH — live offline scan skipped",
)

#: requests 2.19.0 — заведомо уязвимая версия (гарантирует ≥1 findings на живой DB).
_TINY_SBOM = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "version": 1,
    "components": [
        {"type": "library", "name": "requests", "version": "2.19.0",
         "purl": "pkg:pypi/requests@2.19.0"},
    ],
}


def test_live_grype_offline_report():
    res = generate_vuln_report(_TINY_SBOM)
    if res.source != "grype":
        pytest.skip(f"grype offline DB unavailable: {res.reason}")
    matches = res.report.get("matches", [])
    assert isinstance(matches, list)
    assert len(matches) >= 1, "requests 2.19.0 must yield findings on the live DB"
