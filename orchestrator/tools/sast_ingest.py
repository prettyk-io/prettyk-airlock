# -*- coding: utf-8 -*-
"""SAST-INGEST-2 CLI: SAST-отчёт → runs.findings_refs (живой мост COS-101).

Запускается из CI-шага/оператором после скана (STEP-1), не из процесса API.

Usage:
    python -m tools.sast_ingest --run-id <run_id> --sarif <path-to.sarif>
    python -m tools.sast_ingest --run-id <run_id> --issues <ce-issues.json>

DB: env ``COSMO_DATABASE_URL`` (async SQLAlchemy URL); для стенда Airlock —
host :5432, для изолированных прогонов — test PG :5433.

Exit codes: 0 — успех (включая идемпотентный повтор: attached=0);
            2 — битый отчёт / run не найден / IO-ошибка (честный fail).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Repo root — для абсолютных импортов ``orchestrator.*`` (как seed-скрипты).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.cosmo.control_plane.sast_ingest import (  # noqa: E402
    SastReportError,
    convert_sonar_issues,
    ingest_findings_to_run,
    ingest_sarif_to_run,
)


async def _run(args: argparse.Namespace) -> dict:
    from orchestrator.cosmo.db.session import get_sessionmaker

    session_factory = get_sessionmaker()
    source = Path(args.sarif or args.issues)
    payload = source.read_bytes()

    if args.sarif:
        result = await ingest_sarif_to_run(session_factory, args.run_id, payload)
    else:
        try:
            issues = json.loads(payload.decode("utf-8"))
        except ValueError as exc:
            raise SastReportError(f"invalid CE issues JSON: {exc}") from exc
        if not isinstance(issues, list):
            raise SastReportError("CE issues payload is not a list")
        findings = convert_sonar_issues(issues)
        result = await ingest_findings_to_run(session_factory, args.run_id, findings)

    return {
        "run_id": result.run_id,
        "source": str(source),
        "parsed": result.parsed,
        "attached": result.attached,
        "duplicates": result.duplicates,
        "total": result.total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SAST report → runs.findings_refs (bridge COS-101)")
    parser.add_argument("--run-id", required=True, help="target run id (must exist)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sarif", help="SARIF 2.1.0 report path")
    source.add_argument("--issues", help="SonarQube api/issues/search JSON path")
    args = parser.parse_args()

    try:
        summary = asyncio.run(_run(args))
    except (SastReportError, LookupError, OSError) as exc:
        print(f"SAST-INGEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())