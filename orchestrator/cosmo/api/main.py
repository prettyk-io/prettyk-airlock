"""Cosmoport 2.0 — FastAPI application entry point.

Включает health-роутер (/live, /ready, /health).
Основные бизнес-роуты добавляются по мере реализации.

Docker: uvicorn orchestrator.cosmo.api.main:app --host 0.0.0.0 --port 8100
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.cosmo.api.health import router as health_router
from orchestrator.cosmo.api.routes.domains import router as domains_router
from orchestrator.cosmo.api.routes.apps import router as apps_router
from orchestrator.cosmo.api.routes.pipelines import router as pipelines_router
from orchestrator.cosmo.api.routes.runs import router as runs_router
from orchestrator.cosmo.api.routes.gates import router as gates_router
from orchestrator.cosmo.api.routes.sse import router as sse_router
from orchestrator.cosmo.api.routes.preferences import router as preferences_router
from orchestrator.cosmo.api.routes.releases import router as releases_router
from orchestrator.cosmo.api.routes.transfer import (
    router as transfer_router,
    transfer_error_handler,
)
from orchestrator.cosmo.api.routes.metrics import router as metrics_router
from orchestrator.cosmo.api.routes.status import router as status_router
from orchestrator.cosmo.api.routes.repos import router as repos_router
from orchestrator.cosmo.api.routes.workspace import router as workspace_router, run_log_router
from orchestrator.cosmo.api.routes.audit import router as audit_router
from orchestrator.cosmo.api.routes.evidence import router as evidence_router
from orchestrator.cosmo.api.routes.notifications import router as notifications_router
from orchestrator.cosmo.api.routes.artifacts import router as artifacts_router
from orchestrator.cosmo.api.routes.findings import router as findings_router
from orchestrator.cosmo.api.routes.builds import router as builds_router
from orchestrator.cosmo.api.routes.deployments import router as deployments_router
from orchestrator.cosmo.api.routes.projects import router as projects_router, kits_router
from orchestrator.cosmo.api.routes.release_batches import router as release_batches_router
from orchestrator.cosmo.api.routes.webhooks import router as webhooks_router
from orchestrator.cosmo.api.startup import lifespan

app = FastAPI(
    title="Cosmoport 2.0 API",
    description="Sovereign Run Control Plane — управление жизненным циклом безопасности разработки",
    version="0.2.0",
    lifespan=lifespan,
)

# ── CORS (dev — разрешить все origins; production — конкретный host) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(domains_router)
app.include_router(apps_router)
app.include_router(pipelines_router)
# COS-112: run_log_router BEFORE runs_router — чтобы GET /api/v1/runs/{run_id}/steps/{step_id}/logs
# не затенялся GET /api/v1/runs/{id} (run_log_router имеет более конкретный сигнальный путь)
# COS-097: evidence_router BEFORE runs_router — чтобы GET /api/v1/runs/{id}/evidence
# и GET /api/v1/runs/{id}/gost-act не затенялись GET /api/v1/runs/{id}
app.include_router(run_log_router)
app.include_router(evidence_router)
app.include_router(runs_router)
app.include_router(gates_router)
app.include_router(sse_router)
app.include_router(preferences_router)
app.include_router(releases_router)
# COS-058: transfer boundary API (kernel COS-050/053)
app.include_router(transfer_router)
# COS-058: unified error contract {"error": {...}} для dict-detail HTTPException
from fastapi import HTTPException as _HTTPException  # noqa: E402
app.add_exception_handler(_HTTPException, transfer_error_handler)
app.include_router(metrics_router)
app.include_router(status_router)
app.include_router(repos_router)
# COS-103: workspace-роуты ПЕРЕД repos_router — /workspace/bootstrap и
# CAS-переопределения /tree, /file резолвятся первыми (оба роутера имеют
# prefix /api/v1/repos).
app.include_router(workspace_router)
app.include_router(audit_router)
app.include_router(notifications_router)
app.include_router(artifacts_router)
app.include_router(findings_router)
app.include_router(builds_router)
app.include_router(deployments_router)
app.include_router(projects_router)
app.include_router(kits_router)
app.include_router(release_batches_router)
app.include_router(webhooks_router)