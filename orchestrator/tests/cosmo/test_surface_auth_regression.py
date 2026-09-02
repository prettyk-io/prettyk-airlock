# -*- coding: utf-8 -*-
"""COS-068: Unauthenticated Surfaces Hardening — regression matrix.

Закрывает finding 1 отчёта COS-067: ранее анонимные read/write поверхности
получают guards. Матрица acceptance:

  1. Anonymous → 401 на всех auth-only read-поверхностях
     (domains, audit, metrics, status, findings, artifacts, gates, projects,
      kits, release-types, release-batches, evidence, repos).
  2. Открытые поверхности остаются открытыми: GET /metrics (Prometheus
     scrape-контракт), /live, /health (Docker/Caddy healthcheck).
  3. USER → 403 на system-admin mutations (domains, audit, artifacts cleanup,
     release-types create/update) и на capability-поверхности
     (gates create — PIPELINE_CONFIGURE, commit-and-run — SCAN_START).
  4. USER → 200 на auth-only reads; evidence на несуществующий run → 404.
  5. Gates create: ownership-цепочка plan.app_id → Application.domain_id —
     foreign SERVICE_ADMIN → 404 (ghost, anti-enumeration), свой домен → 201.
  6. commit-and-run: identity binding до db-операций — чужой domain_id → 403.
  7. Findings search: доменный override — не-админ ищет только в своём
      домене (клиентский domain_id игнорируется), админ фильтрует свободно.
  8. COS-085: opaque-bearer legacy контракт закрыт — `garbage.sig.x` и все
      opaque-форматы (keyword/colon/произвольные) → 401; легитимен только
      JWT (ey.<payload>.<sig>).

PG fixture: conftest.py (auto-skip если тестовый PG :5433 недоступен).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from httpx import AsyncClient

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext, Role

# ── helpers ──────────────────────────────────────────────────────────


def _set_principal(
    roles: list | None,
    domain_id: str | None = None,
    is_system_admin: bool = False,
    user_id: str = "surface-user",
) -> None:
    """Переопределить get_current_principal (сбрасывает conftest-админа)."""
    async def _principal() -> PrincipalContext:
        return PrincipalContext(
            user_id=user_id,
            roles=roles or [Role.USER],
            domain_id=domain_id,
            is_authenticated=True,
            is_system_admin=is_system_admin,
        )
    app.dependency_overrides[get_current_principal] = _principal


def _anon() -> None:
    """Убрать override → реальный get_current_principal → 401 без Authorization."""
    app.dependency_overrides.pop(get_current_principal, None)


# ── 1. Anonymous → 401 на auth-only reads ────────────────────────────

ANON_401_GETS = [
    "/api/v1/domains",
    "/api/v1/audit",
    "/api/v1/audit/export/csv",
    "/api/v1/metrics/trends",
    "/api/v1/metrics/sla",
    "/api/v1/status/dashboard",
    "/api/v1/findings/search",
    "/api/v1/artifacts/retention/status",
    "/api/v1/gates",
    "/api/v1/projects",
    "/api/v1/kits/tags",
    "/api/v1/release-types",
    "/api/v1/projects/p-x/release-batches",
    "/api/v1/runs/run-ghost/evidence",
    "/api/v1/runs/run-ghost/gost-act",
    "/api/v1/repos/tree?repo=x/y",
]


@pytest.mark.parametrize("path", ANON_401_GETS)
async def test_anonymous_gets_require_auth(path: str, pg_client: AsyncClient):
    _anon()
    res = await pg_client.get(path)
    assert res.status_code == 401, f"{path}: expected 401, got {res.status_code}"


# ── 2. Открытые поверхности остаются открытыми ───────────────────────


async def test_metrics_prometheus_scrape_stays_open(pg_client: AsyncClient):
    """GET /metrics — Prometheus scrape-контракт, намеренно открыт
    (агрегированные счётчики, сетевая изоляция на уровне Caddy)."""
    _anon()
    res = await pg_client.get("/metrics")
    assert res.status_code == 200


async def test_health_endpoints_stay_open(pg_client: AsyncClient):
    """/live и /health — Docker/Caddy healthcheck, зона Buddy."""
    _anon()
    assert (await pg_client.get("/live")).status_code == 200
    assert (await pg_client.get("/health")).status_code == 200


# ── 3. USER → 403 на system-admin mutations ──────────────────────────

DOMAIN_PAYLOAD = {
    "id": "dom-sec68",
    "label": "Sec68 Domain",
    "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:x"},
}

AUDIT_PAYLOAD = {
    "user_id": "u-sec68",
    "action": "trigger_run",
    "resource_type": "run",
    "resource_id": "run-sec68",
}

GATE_PAYLOAD = {
    "id": "gate-sec68",
    "plan_id": "plan-sec68",
    "type": "manual",
    "position": 0,
    "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
}

COMMIT_AND_RUN_PAYLOAD = {
    "repo": "sec68/app",
    "branch": "main",
    "message": "cos-068 probe",
    "plan_id": "plan-sec68",
    "domain_id": "dom-sec68",
    "files": [],
}


async def test_user_cannot_create_domain(pg_client: AsyncClient):
    _set_principal([Role.USER])
    res = await pg_client.post("/api/v1/domains", json=DOMAIN_PAYLOAD)
    assert res.status_code == 403


async def test_user_cannot_inject_audit_event(pg_client: AsyncClient):
    """COS-068: POST /audit — закрытая дыра инъекции аудита."""
    _set_principal([Role.USER])
    res = await pg_client.post("/api/v1/audit", json=AUDIT_PAYLOAD)
    assert res.status_code == 403


async def test_user_cannot_run_artifact_cleanup(pg_client: AsyncClient):
    _set_principal([Role.USER])
    res = await pg_client.post("/api/v1/artifacts/cleanup", json={})
    assert res.status_code == 403


async def test_user_cannot_create_release_type(pg_client: AsyncClient):
    _set_principal([Role.USER])
    res = await pg_client.post(
        "/api/v1/release-types", json={"id": "rt-sec68", "name": "Sec68"}
    )
    assert res.status_code == 403


async def test_user_cannot_update_release_type(pg_client: AsyncClient):
    _set_principal([Role.USER])
    res = await pg_client.put("/api/v1/release-types/rt-any", json={"name": "X"})
    assert res.status_code == 403


async def test_user_cannot_create_gate(pg_client: AsyncClient):
    """PIPELINE_CONFIGURE отсутствует у USER → guard 403 до handler'а.

    Capability-guard резолвит RBAC по identity-домену principal'а — домен
    должен существовать в БД (иначе _load_domain_rbac даёт 404)."""
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-user", "label": "User Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:u"},
    })
    _set_principal([Role.USER], domain_id="dom-user")
    res = await pg_client.post("/api/v1/gates", json=GATE_PAYLOAD)
    assert res.status_code == 403


async def test_user_cannot_commit_and_run(pg_client: AsyncClient):
    """SCAN_START отсутствует у USER → guard 403 до handler'а."""
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-user", "label": "User Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:u"},
    })
    _set_principal([Role.USER], domain_id="dom-user")
    res = await pg_client.post("/api/v1/repos/commit-and-run", json=COMMIT_AND_RUN_PAYLOAD)
    assert res.status_code == 403


# ── 4. USER → 200 на auth-only reads ─────────────────────────────────

USER_200_GETS = [
    "/api/v1/domains",
    "/api/v1/audit",
    "/api/v1/metrics/trends",
    "/api/v1/status/dashboard",
    "/api/v1/findings/search",
    "/api/v1/artifacts/retention/status",
    "/api/v1/gates",
    "/api/v1/projects",
    "/api/v1/kits/tags",
    "/api/v1/release-types",
]


@pytest.mark.parametrize("path", USER_200_GETS)
async def test_user_reads_are_allowed(path: str, pg_client: AsyncClient):
    _set_principal([Role.USER], domain_id="dom-user")
    res = await pg_client.get(path)
    assert res.status_code == 200, f"{path}: expected 200, got {res.status_code}: {res.text}"


async def test_user_evidence_ghost_is_404(pg_client: AsyncClient):
    """Auth прошёл, но run не существует → 404 (anti-disclosure)."""
    _set_principal([Role.USER], domain_id="dom-user")
    res = await pg_client.get("/api/v1/runs/run-ghost/evidence")
    assert res.status_code == 404


# ── 5. Gates create: ownership-цепочка через plan ────────────────────


async def test_gate_create_ownership_chain(pg_client: AsyncClient):
    """Собственный домен → 201, чужой SERVICE_ADMIN → 404 ghost,
    USER → 403. Ownership резолвится plan.app_id → Application.domain_id
    (PipelinePlan не имеет собственного domain_id)."""
    # Setup под conftest-админом
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-g68", "label": "G68 Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:g68"},
    })
    await pg_client.post("/api/v1/apps", json={
        "id": "app-g68", "domain_id": "dom-g68", "level": 1,
        "repo_binding": {"forge_id": "gitea", "repo_path": "dom-g68/app"},
    })
    await pg_client.post("/api/v1/plans", json={
        "id": "plan-g68", "app_id": "app-g68", "brick_ids": [],
    })

    payload = {
        "id": "gate-g68",
        "plan_id": "plan-g68",
        "type": "manual",
        "position": 0,
        "policy": {"rules": [{"finding_type": "Critical", "action": "block"}]},
    }

    # USER → 403 (нет PIPELINE_CONFIGURE)
    _set_principal([Role.USER], domain_id="dom-g68")
    res = await pg_client.post("/api/v1/gates", json=payload)
    assert res.status_code == 403, f"USER: expected 403, got {res.status_code}"

    # Foreign SERVICE_ADMIN → 404 ghost (план чужого домена не раскрывается).
    # Домен foreign должен существовать, иначе 404 придёт от _load_domain_rbac,
    # а не от ownership-цепочки plan.app_id → Application.domain_id.
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-foreign", "label": "Foreign Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:f"},
    })
    _set_principal([CBRRole.SERVICE_ADMIN], domain_id="dom-foreign")
    res = await pg_client.post("/api/v1/gates", json=payload)
    assert res.status_code == 404, f"foreign admin: expected 404, got {res.status_code}"

    # Own-domain SERVICE_ADMIN → 201
    _set_principal([CBRRole.SERVICE_ADMIN], domain_id="dom-g68")
    res = await pg_client.post("/api/v1/gates", json=payload)
    assert res.status_code == 201, f"own admin: expected 201, got {res.status_code}: {res.text}"


# ── 6. commit-and-run: identity binding до db ────────────────────────


async def test_commit_and_run_foreign_domain_is_403(pg_client: AsyncClient):
    """SERVICE_ADMIN имеет SCAN_START, но body.domain_id ≠ principal.domain_id
    → 403 от binding-проверки (до любых db-операций)."""
    await pg_client.post("/api/v1/domains", json={
        "id": "dom-own", "label": "Own Domain",
        "forge_binding": {"forge_type": "gitea", "url": "http://gitea", "token_ref": "vault:o"},
    })
    _set_principal([CBRRole.SERVICE_ADMIN], domain_id="dom-own")
    body = dict(COMMIT_AND_RUN_PAYLOAD)
    body["domain_id"] = "dom-other"
    res = await pg_client.post("/api/v1/repos/commit-and-run", json=body)
    assert res.status_code == 403


# ── 8. COS-085: opaque-bearer legacy контракт закрыт ─────────────────


async def test_http_opaque_bearer_is_401_on_guarded_route(pg_client: AsyncClient):
    """Главный кейс находки COS-085: `Bearer garbage.sig.x` был 200 как
    Role.USER (legacy-контракт). Теперь — 401 на guarded-роуте."""
    _anon()
    res = await pg_client.get(
        "/api/v1/projects",
        headers={"Authorization": "Bearer garbage.sig.x"},
    )
    assert res.status_code == 401, res.text


@pytest.mark.parametrize("opaque", [
    "admin",                    # keyword: был system admin
    "bob:admin_sec:b@corp",     # colon: forged system admin
    "officer-token",            # keyword: был SECURITY_OFFICER
    "plainkey123456",           # произвольный opaque
])
async def test_http_opaque_formats_are_401(pg_client: AsyncClient, opaque: str):
    """Все opaque-форматы (keyword, colon, произвольные) → 401 (COS-085)."""
    _anon()
    res = await pg_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {opaque}"},
    )
    assert res.status_code == 401, f"{opaque}: {res.status_code} {res.text}"


async def test_http_opaque_cookie_is_401(pg_client: AsyncClient):
    """Тот же шов через cookie session_token закрыт тем же правилом."""
    _anon()
    res = await pg_client.get(
        "/api/v1/projects",
        cookies={"session_token": "garbage.sig.x"},
    )
    assert res.status_code == 401, res.text


async def test_http_jwt_bearer_still_authenticates(pg_client: AsyncClient):
    """Позитив: валидный JWT (ey.<payload>.<sig>) проходит реальный auth и
    попадает на guarded-роут (list_projects, scoping не-админа → 200)."""
    import base64 as _b64
    import json as _json

    claims = {"sub": "cos085-user", "roles": ["user"]}
    payload = _b64.urlsafe_b64encode(_json.dumps(claims).encode()).decode().rstrip("=")
    token = f"eyJhbGciOiJIUzI1NiJ9.{payload}.sig"
    _anon()
    res = await pg_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text


# ── 7. Findings search: доменный override (unit) ─────────────────────


async def test_findings_search_domain_override(monkeypatch):
    """Не-админ: клиентский domain_id игнорируется → поиск в своём домене.
    Админ: домен из запроса. USER без домена → __no_domain__ (пустой результат)."""
    from orchestrator.cosmo.api.routes import findings as findings_mod
    from orchestrator.cosmo.ledger import finding_search as fs_mod

    captured: dict = {}

    def fake_search_pg(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "offset": 0, "limit": 50}

    monkeypatch.setattr(fs_mod.FindingSearchEngine, "search_pg", staticmethod(fake_search_pg))

    # Не-админ пытается расширить поиск на чужой домен → свой домен
    user = PrincipalContext(
        user_id="u-dom", roles=[Role.USER], domain_id="dom-x",
        is_authenticated=True, is_system_admin=False,
    )
    await findings_mod.search_findings(
        q=None, severity=None, cwe=None, file=None, tool=None,
        domain_id="dom-hack", date_from=None, date_to=None,
        offset=0, limit=50, db=None, principal=user,
    )
    assert captured["domain_id"] == "dom-x"

    # Не-админ без домена → __no_domain__ (не глобальный поиск)
    user_no_dom = PrincipalContext(
        user_id="u-nd", roles=[Role.USER], domain_id=None,
        is_authenticated=True, is_system_admin=False,
    )
    await findings_mod.search_findings(
        q=None, severity=None, cwe=None, file=None, tool=None,
        domain_id=None, date_from=None, date_to=None,
        offset=0, limit=50, db=None, principal=user_no_dom,
    )
    assert captured["domain_id"] == "__no_domain__"

    # Системный админ фильтрует любым доменом из запроса
    admin = PrincipalContext(
        user_id="sa", roles=[], domain_id=None,
        is_authenticated=True, is_system_admin=True,
    )
    await findings_mod.search_findings(
        q=None, severity=None, cwe=None, file=None, tool=None,
        domain_id="dom-any", date_from=None, date_to=None,
        offset=0, limit=50, db=None, principal=admin,
    )
    assert captured["domain_id"] == "dom-any"