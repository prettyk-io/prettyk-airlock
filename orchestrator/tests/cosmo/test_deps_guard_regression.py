# -*- coding: utf-8 -*-
"""COS-067: deps guard domain binding regression — identity mode.

Пакет "deps._guard Domain Binding Hardening": 10 guarded маршрутов вне
transfer/ переведены на domain_binding="identity". Контракт:

  - X-Cosmo-Domain для не-админа НЕ обязателен (прежнее 400-требование
    снято — UX: заголовок не нужен, если хендлер его не использует);
  - заголовок игнорируется для не-админа: ghost-домен не раскрывается
    (прежний 404-утечка заменён на честный RBAC-вердикт);
  - operation domain берётся из principal.domain_id или самого ресурса,
    а не из клиентского ввода;
  - спуф чужого СУЩЕСТВУЮЩЕГО домена → явный отказ: 403 (binding на
    body.domain_id) или 404 (ownership по ресурсу), никогда 500 и
    никогда успех;
  - system admin сохраняет легитимный context switch через заголовок.

COS-083: capability-гранулярность pass 2 (builds/deployments/projects/
groups/lc-config/repo-binding) и единый резолв домена caller'а. Новые
маршруты добавлены в GUARDED_ROUTES; гранулярность ролей и зон — в
TestCapabilityGranularity, доменный scoping read'ов — в
TestDomainScopingReads. Инвариант исходников —
test_domain_resolve_invariant.py.

COS-091: capability-гранулярность pass 4 (releases/runs unification) —
lifecycle-роуты релиза, PATCH статуса прогона, batches-семья.

COS-092: guard pass 5 (notifications unification) — webhook-config CRUD,
DLQ list/replay, outbox visibility и process tick → DOMAIN_CONFIGURE
(ops-поверхность; hold: ADMIN_SEC / SERVICE_ADMIN, ЗР). Личная
поверхность (inbox, sse-ticket) — require_principal: recipient
резолвится из principal.user_id по построению, capability и домен не
участвуют; эти identity-scoped writes разрешены инвариантом 4 явным
allowlist'ом. Инвариант исходников — test_domain_resolve_invariant.py.

Transfer-маршруты остаются в "header"-режиме (COS-066) и покрыты
test_transfer_security_matrix.py — здесь они не трогаются.

Deps-level ошибки — FastAPI HTTPException {"detail": ...} (документированная
граница: единый {"error": ...} конверт применяется на route-level transfer).
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext, Role

# (method, url) — все маршруты с require_capability вне transfer/
GUARDED_ROUTES = [
    ("POST", "/api/v1/plans/compile"),            # PIPELINE_CONFIGURE
    ("POST", "/api/v1/releases"),                 # RELEASE_CREATE
    ("POST", "/api/v1/releases/rel-x/transfer"),  # RELEASE_TRANSFER
    ("POST", "/api/v1/releases/rel-x/transfer-v2"),  # RELEASE_TRANSFER
    ("POST", "/api/v1/gates/g-x/decision"),       # GATE_DECIDE
    ("POST", "/api/v1/apps"),                     # BRICK_MANAGE
    ("PUT", "/api/v1/apps/app-x"),                # BRICK_MANAGE
    ("DELETE", "/api/v1/apps/app-x"),             # BRICK_MANAGE
    ("PUT", "/api/v1/apps/app-x/repo-binding"),   # BRICK_MANAGE (COS-083)
    ("PUT", "/api/v1/apps/app-x/lc-config"),      # BRICK_MANAGE (COS-083)
    ("POST", "/api/v1/groups"),                   # BRICK_MANAGE (COS-083)
    ("DELETE", "/api/v1/groups/grp-x"),           # BRICK_MANAGE (COS-083)
    ("POST", "/api/v1/apps/app-x/builds"),        # BUILD_RUN (COS-083)
    ("POST", "/api/v1/builds/bld-x/abort"),       # BUILD_RUN (COS-083)
    ("POST", "/api/v1/apps/app-x/deploys"),       # DEPLOY_MANAGE (COS-083)
    ("POST", "/api/v1/deploys/dep-x/rollback"),   # DEPLOY_MANAGE (COS-083)
    ("POST", "/api/v1/projects"),                 # PROJECT_WRITE (COS-083)
    ("PUT", "/api/v1/projects/proj-x"),           # PROJECT_WRITE (COS-083)
    ("POST", "/api/v1/projects/proj-x/apps"),     # PROJECT_WRITE (COS-083)
    ("POST", "/api/v1/kits"),                     # PROJECT_WRITE (COS-083)
    ("POST", "/api/v1/bricks"),                   # BRICK_MANAGE (COS-086)
    ("PUT", "/api/v1/bricks/brick-x"),            # BRICK_MANAGE (COS-086)
    ("DELETE", "/api/v1/bricks/brick-x"),         # BRICK_MANAGE (COS-086)
    ("POST", "/api/v1/plans"),                    # PIPELINE_CONFIGURE (COS-086)
    ("DELETE", "/api/v1/plans/plan-x"),           # PIPELINE_CONFIGURE (COS-086)
    ("POST", "/api/v1/runs"),                     # SCAN_START
    ("POST", "/api/v1/runs/run-x/cancel"),        # SCAN_STOP
    ("PATCH", "/api/v1/runs/run-x/status"),       # SCAN_START (COS-091)
    ("POST", "/api/v1/batches"),                  # SCAN_START (COS-091)
    ("PATCH", "/api/v1/batches/batch-x/status"),  # SCAN_START (COS-091)
    ("POST", "/api/v1/releases/rel-x/submit"),    # RELEASE_SUBMIT (COS-091)
    ("POST", "/api/v1/releases/rel-x/approve"),   # RELEASE_APPROVE (COS-091)
    ("POST", "/api/v1/releases/rel-x/reject"),    # RELEASE_REJECT (COS-091)
    ("POST", "/api/v1/releases/rel-x/deploy"),    # RELEASE_DEPLOY (COS-091)
    ("DELETE", "/api/v1/releases/rel-x"),         # RELEASE_CREATE (COS-091)
    ("POST", "/api/v1/releases/envelope/verify"),  # ENVELOPE_VERIFY (COS-091)
    ("GET", "/api/v1/notifications"),              # DOMAIN_CONFIGURE (COS-092)
    ("POST", "/api/v1/notifications"),             # DOMAIN_CONFIGURE (COS-092)
    ("DELETE", "/api/v1/notifications/cfg-x"),     # DOMAIN_CONFIGURE (COS-092)
    ("GET", "/api/v1/notifications/dlq"),          # DOMAIN_CONFIGURE (COS-092)
    ("POST", "/api/v1/notifications/dlq/dlq-x/replay"),  # DOMAIN_CONFIGURE (COS-092)
    ("GET", "/api/v1/notifications/outbox/ev-x"),  # DOMAIN_CONFIGURE (COS-092)
    ("POST", "/api/v1/notifications/process"),     # DOMAIN_CONFIGURE (COS-092)
]

_DOMAIN_BODY = {
    "forge_binding": {
        "forge_type": "gitea",
        "url": "https://gitea.example",
        "token_ref": "vault://cosmo/test",
    },
    "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
}

_REPO_BINDING = {"forge_id": "forge-x", "repo_path": "org/repo"}

_GATE_POLICY = {"rules": [{"finding_type": "Critical", "action": "block"}]}

# Кто из не-админов проходит guard и что отвечает хендлер.
# role_factory(domain) → PrincipalContext; expected — статус хендлера
# (guard пройден: НЕ 400/401/403/500). Тела — минимально валидные,
# чтобы 422-валидация не заслоняла ресурсный вердикт.
GUARD_PASS_MATRIX = [
    # compile: SERVICE_ADMIN (PIPELINE_CONFIGURE); guard пройден — дальше
    # 422 body-валидации (brick_ids min_length=1). Ownership compile покрыт
    # в TestCrossDomainBinding (чужой app → 404).
    ("POST", "/api/v1/plans/compile", "svc", 422,
     {"plan_id": "plan-x", "app_id": "app-x", "brick_ids": []}),
    # releases: RELEASE_MANAGER (RELEASE_CREATE); план не существует → 404
    ("POST", "/api/v1/releases", "relmgr", 404,
     {"id": "rel-x", "domain_id": "test", "plan_id": "plan-x", "run_ids": ["run-x"]}),
    # transfer/transfer-v2: rel-x не существует → 404 ownership
    ("POST", "/api/v1/releases/rel-x/transfer", "relmgr", 404,
     {"initiated_by": "relmgr-test"}),
    ("POST", "/api/v1/releases/rel-x/transfer-v2", "relmgr", 404,
     {"target_zone": "zt", "officer_name": "X", "sign_signature": "sig"}),
    # gate decision: ADMIN_SEC (GATE_DECIDE); g-x не существует → 404
    ("POST", "/api/v1/gates/g-x/decision", "secadm", 404, {"decision": "pass"}),
    # apps: SERVICE_ADMIN (BRICK_MANAGE); домен test существует → 201 создано
    ("POST", "/api/v1/apps", "svc", 201,
     {"id": "app-x", "domain_id": "test", "repo_binding": _REPO_BINDING}),
    # PUT/DELETE: app-y не существует (app-x создан предыдущей строкой) → 404
    ("PUT", "/api/v1/apps/app-y", "svc", 404, {}),
    ("DELETE", "/api/v1/apps/app-y", "svc", 404, None),
    # runs: SERVICE_ADMIN (SCAN_START); план не существует → 404
    ("POST", "/api/v1/runs", "svc", 404,
     {"id": "run-x", "plan_id": "plan-x", "domain_id": "test"}),
    # cancel: ADMIN_SEC (SCAN_STOP); run-x не существует → 404
    ("POST", "/api/v1/runs/run-x/cancel", "secadm", 404, None),
    # ── COS-083: capability-гранулярные маршруты ──
    # repo-binding: SERVICE_ADMIN (BRICK_MANAGE); app-mx не существует → 404
    ("PUT", "/api/v1/apps/app-mx/repo-binding", "svc", 404,
     {"forge_id": "gitea", "repo_path": "org/repo"}),
    # lc-config: SERVICE_ADMIN (BRICK_MANAGE); app-mx не существует → 404
    ("PUT", "/api/v1/apps/app-mx/lc-config", "svc", 404, {}),
    # groups: SERVICE_ADMIN (BRICK_MANAGE); свой домен → 201 создано
    ("POST", "/api/v1/groups", "svc", 201,
     {"id": "grp-mx", "domain_id": "test", "level": 1, "name": "Matrix"}),
    # delete group: SERVICE_ADMIN; grp-mx-y не существует → 404
    ("DELETE", "/api/v1/groups/grp-mx-y", "svc", 404, None),
    # builds trigger: DEVELOPER (BUILD_RUN); app-mx не существует → 404
    ("POST", "/api/v1/apps/app-mx/builds", "dev", 404,
     {"commit_sha": "abcdef12345"}),
    # builds abort: DEVELOPER (BUILD_RUN); bld-mx не существует → 404
    ("POST", "/api/v1/builds/bld-mx/abort", "dev", 404, None),
    # deploys create: RELEASE_MANAGER (DEPLOY_MANAGE); app-mx → 404
    ("POST", "/api/v1/apps/app-mx/deploys", "relmgr", 404,
     {"build_id": "bld-mx"}),
    # deploys rollback: RELEASE_MANAGER; dep-mx не существует → 404
    ("POST", "/api/v1/deploys/dep-mx/rollback", "relmgr", 404, {}),
    # projects create: PRODUCT_OWNER (PROJECT_WRITE); свой домен → 201
    ("POST", "/api/v1/projects", "owner", 201,
     {"id": "proj-mx", "name": "Matrix Project"}),
    # projects update: PRODUCT_OWNER; proj-mx-y не существует → 404
    ("PUT", "/api/v1/projects/proj-mx-y", "owner", 404,
     {"name": "Renamed"}),
    # projects add app: PRODUCT_OWNER; проект и app не существуют → 404
    ("POST", "/api/v1/projects/proj-mx-y/apps", "owner", 404,
     {"app_id": "app-mx"}),
    # kits: PRODUCT_OWNER (PROJECT_WRITE); свой домен → 201
    ("POST", "/api/v1/kits", "owner", 201,
     {"id": "kit-mx", "label": "Matrix Kit"}),
    # ── COS-086: bricks/plans (guard pass 3) ──
    # bricks create: SERVICE_ADMIN (BRICK_MANAGE); глобальный каталог → 201
    ("POST", "/api/v1/bricks", "svc", 201,
     {"id": "brick-mx", "name": "Matrix Brick", "type": "autotest",
      "source": "internal", "definition": {"image": "pytest:latest"}}),
    # bricks update/delete: brick-bx не существует → 404
    ("PUT", "/api/v1/bricks/brick-bx", "svc", 404,
     {"name": "Renamed"}),
    ("DELETE", "/api/v1/bricks/brick-bx", "svc", 404, None),
    # plans create: SERVICE_ADMIN (PIPELINE_CONFIGURE); app-mx не существует → 404
    ("POST", "/api/v1/plans", "svc", 404,
     {"id": "plan-mx", "app_id": "app-mx", "brick_ids": []}),
    # plans delete: plan-mx не существует → 404
    ("DELETE", "/api/v1/plans/plan-mx", "svc", 404, None),
    # ── COS-091: guard pass 4 (releases/runs unification) ──
    # batches create: SERVICE_ADMIN (SCAN_START); план не существует → 404
    ("POST", "/api/v1/batches", "svc", 404,
     {"id": "batch-mx", "plan_id": "plan-mx", "type": "static_scan"}),
    # batches status: batch-mx не существует → 404
    ("PATCH", "/api/v1/batches/batch-mx/status", "svc", 404,
     {"status": "running"}),
    # run status: SERVICE_ADMIN (SCAN_START); run-mx не существует → 404
    ("PATCH", "/api/v1/runs/run-mx/status", "svc", 404,
     {"status": "running"}),
    # submit: RELEASE_MANAGER (RELEASE_SUBMIT); rel-mx не существует → 404
    ("POST", "/api/v1/releases/rel-mx/submit", "relmgr", 404, None),
    # approve: SECURITY_OFFICER (RELEASE_APPROVE — SoD: relmgr не утверждает);
    # rel-mx не существует → 404
    ("POST", "/api/v1/releases/rel-mx/approve", "secoff", 404,
     {"decided_by": "secoff-test"}),
    # reject: SECURITY_OFFICER (RELEASE_REJECT); rel-mx не существует → 404
    ("POST", "/api/v1/releases/rel-mx/reject", "secoff", 404,
     {"decided_by": "secoff-test"}),
    # delete: RELEASE_CREATE у relmgr; rel-mx не существует → 404
    ("DELETE", "/api/v1/releases/rel-mx", "relmgr", 404, None),
    # envelope verify: QA (ENVELOPE_VERIFY); pure-функция → 200 verified=false
    ("POST", "/api/v1/releases/envelope/verify", "qa", 200, {}),
    # ── COS-092: guard pass 5 (notifications ops) ──
    # webhook-config list: SERVICE_ADMIN (DOMAIN_CONFIGURE); in-memory
    # placeholder → 200 (пусто или накопленное другими тестами)
    ("GET", "/api/v1/notifications", "svc", 200, None),
    # webhook-config create: свой домен → 201 (in-memory placeholder)
    ("POST", "/api/v1/notifications?domain_id=test", "svc", 201,
     {"id": "wh-mx", "url": "https://hooks.example/cosmo", "channels": ["email"]}),
    # webhook-config delete: wh-mx-y не существует → 404
    ("DELETE", "/api/v1/notifications/wh-mx-y?domain_id=test", "svc", 404, None),
    # dlq list: пустая DLQ → 200 []
    ("GET", "/api/v1/notifications/dlq", "svc", 200, None),
    # dlq replay: dlq-mx не существует → 404
    ("POST", "/api/v1/notifications/dlq/dlq-mx/replay", "svc", 404, None),
    # outbox status: ev-mx не существует → 404
    ("GET", "/api/v1/notifications/outbox/ev-mx", "svc", 404, None),
    # process tick: пустой outbox → честный отчёт 200
    ("POST", "/api/v1/notifications/process", "svc", 200, None),
]


def _set_user(domain_id: str = "test") -> None:
    async def _principal() -> PrincipalContext:
        return PrincipalContext(
            user_id="plain-user",
            roles=[Role.USER],
            domain_id=domain_id,
            zone="zr",
            is_authenticated=True,
            is_system_admin=False,
        )
    app.dependency_overrides[get_current_principal] = _principal


def _set_role(kind: str, domain_id: str = "test", zone: str = "zr") -> None:
    roles = {
        "svc": [CBRRole.SERVICE_ADMIN],
        "relmgr": [CBRRole.RELEASE_MANAGER],
        "secadm": [Role.ADMIN_SEC],
        "secoff": [CBRRole.SECURITY_OFFICER],  # COS-091: RELEASE_APPROVE/REJECT
        # COS-083: гранулярные CBR-роли
        "dev": [CBRRole.DEVELOPER],
        "qa": [CBRRole.QA_ENGINEER],
        "owner": [CBRRole.PRODUCT_OWNER],
        "lead": [CBRRole.DEVELOPER_LEAD],
        "zpeop": [CBRRole.ZONE_OPERATOR_ZPE],
    }
    _roles = roles[kind]
    uid = f"{kind}-{domain_id}"

    async def _principal() -> PrincipalContext:
        return PrincipalContext(
            user_id=uid,
            roles=_roles,
            domain_id=domain_id,
            zone=zone,
            is_authenticated=True,
            is_system_admin=False,
        )
    app.dependency_overrides[get_current_principal] = _principal


def _anon() -> None:
    app.dependency_overrides.pop(get_current_principal, None)


async def _request(pg_client, method: str, url: str, headers: dict | None = None, json: dict | None = None):
    kwargs: dict = {"headers": headers or {}}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = json if json is not None else {}
    return await getattr(pg_client, method.lower())(url, **kwargs)


async def _ensure_domain(pg_client, domain_id: str) -> None:
    r = await pg_client.post("/api/v1/domains", json={
        "id": domain_id,
        "label": f"Domain {domain_id}",
        **_DOMAIN_BODY,
    })
    assert r.status_code in (201, 409), r.text


@asynccontextmanager
async def _admin_override():
    """Seed-операции всегда выполняются от system-admin; прежний principal
    восстанавливается на выходе (межтестовые override-утечки исключены)."""
    prev = app.dependency_overrides.get(get_current_principal)

    async def _admin() -> PrincipalContext:
        return PrincipalContext(
            user_id="seed-admin", roles=[Role.ADMIN_SEC],
            domain_id="test", zone="zr", is_authenticated=True,
            is_system_admin=True,
        )
    app.dependency_overrides[get_current_principal] = _admin
    try:
        yield
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = prev


async def _seed_brick(pg_client, brick_id: str) -> str:
    """Глобальный brick (без домена) — компилируемый шаг для планов."""
    async with _admin_override():
        r = await pg_client.post("/api/v1/bricks", json={
            "id": brick_id, "name": f"Brick {brick_id}", "type": "autotest",
            "source": "internal", "definition": {"image": "pytest:latest"},
        })
    assert r.status_code in (201, 409), r.text
    return brick_id


async def _seed_foreign_assets(pg_client) -> None:
    """Admin создаёт полный набор ресурсов в чужом (для тестируемых ролей)
    домене 'alpha': app → brick → plan → run → release → gate."""
    async with _admin_override():
        await _ensure_domain(pg_client, "test")
        await _ensure_domain(pg_client, "alpha")
        h = {"X-Cosmo-Domain": "alpha"}

        r = await pg_client.post("/api/v1/apps", headers=h, json={
            "id": "app-alpha", "domain_id": "alpha", "repo_binding": _REPO_BINDING,
        })
        assert r.status_code in (201, 409), r.text

        brick = await _seed_brick(pg_client, "brick-alpha")
        r = await pg_client.post("/api/v1/plans/compile", headers=h, json={
            "plan_id": "plan-alpha", "app_id": "app-alpha", "brick_ids": [brick],
        })
        assert r.status_code in (201, 409), r.text

        r = await pg_client.post("/api/v1/runs", headers=h, json={
            "id": "run-alpha", "plan_id": "plan-alpha", "domain_id": "alpha",
        })
        assert r.status_code in (201, 409), r.text

        r = await pg_client.post("/api/v1/releases", headers=h, json={
            "id": "rel-alpha", "domain_id": "alpha", "plan_id": "plan-alpha",
            "run_ids": ["run-alpha"],
        })
        assert r.status_code in (201, 409), r.text

        r = await pg_client.post("/api/v1/gates", headers=h, json={
            "id": "gate-alpha", "plan_id": "plan-alpha", "policy": _GATE_POLICY,
        })
        assert r.status_code in (201, 409), r.text


async def _seed_own_assets(pg_client) -> None:
    """Admin создаёт тот же набор в домене 'test' (свой для тестируемых ролей)."""
    async with _admin_override():
        await _ensure_domain(pg_client, "test")
        h = {"X-Cosmo-Domain": "test"}

        r = await pg_client.post("/api/v1/apps", headers=h, json={
            "id": "app-test", "domain_id": "test", "repo_binding": _REPO_BINDING,
        })
        assert r.status_code in (201, 409), r.text

        brick = await _seed_brick(pg_client, "brick-test")
        r = await pg_client.post("/api/v1/plans/compile", headers=h, json={
            "plan_id": "plan-test", "app_id": "app-test", "brick_ids": [brick],
        })
        assert r.status_code in (201, 409), r.text

        r = await pg_client.post("/api/v1/runs", headers=h, json={
            "id": "run-test", "plan_id": "plan-test", "domain_id": "test",
        })
        assert r.status_code in (201, 409), r.text

        r = await pg_client.post("/api/v1/releases", headers=h, json={
            "id": "rel-test", "domain_id": "test", "plan_id": "plan-test",
            "run_ids": ["run-test"],
        })
        assert r.status_code in (201, 409), r.text

        r = await pg_client.post("/api/v1/gates", headers=h, json={
            "id": "gate-test", "plan_id": "plan-test", "policy": _GATE_POLICY,
        })
        assert r.status_code in (201, 409), r.text


class TestIdentityModeGuardMatrix:
    """Матрица principal-class × guarded route на уровне guard."""

    async def test_user_without_header_gets_403(self, pg_client):
        """Identity-режим: заголовок не нужен. USER без capability → 403 RBAC.
        Прежний контракт (400 'header required') снят UX-решением пакета."""
        await _ensure_domain(pg_client, "test")
        _set_user()
        for method, url in GUARDED_ROUTES:
            r = await _request(pg_client, method, url)
            assert r.status_code == 403, f"{method} {url}: {r.text}"
            body = r.json()
            assert "detail" in body
            assert "forbidden" in body["detail"].lower()

    async def test_user_header_cannot_change_verdict(self, pg_client):
        """Заголовок игнорируется: ни свой, ни ghost-домен не меняют 403
        и не раскрывают существование домена (прежний 404-утечка закрыт)."""
        await _ensure_domain(pg_client, "test")
        _set_user()
        for method, url in GUARDED_ROUTES:
            r = await _request(pg_client, method, url,
                               headers={"X-Cosmo-Domain": "test"})
            assert r.status_code == 403, f"{method} {url}: {r.text}"
            r = await _request(pg_client, method, url,
                               headers={"X-Cosmo-Domain": "no-such-domain"})
            assert r.status_code == 403, f"{method} {url}: {r.text}"
            assert "no-such-domain" not in r.json()["detail"]

    async def test_anonymous_gets_401(self, pg_client):
        """Без principal → 401 (auth прежде контекста)."""
        _anon()
        for method, url in GUARDED_ROUTES:
            r = await _request(pg_client, method, url)
            assert r.status_code == 401, f"{method} {url}: {r.text}"
            assert "detail" in r.json()

    async def test_capability_holders_pass_guard_without_header(self, pg_client):
        """Держатель capability проходит guard БЕЗ заголовка (UX-цель пакета).
        Хендлер отвечает честным контрактом ресурса, не мусором guard."""
        await _ensure_domain(pg_client, "test")
        for method, url, kind, expected, body in GUARD_PASS_MATRIX:
            _set_role(kind, "test")
            r = await _request(pg_client, method, url, json=body)
            assert r.status_code == expected, f"{method} {url} ({kind}): {r.text}"
            assert r.status_code not in (400, 401, 403, 500), f"{method} {url}: {r.text}"


class TestCrossDomainBinding:
    """Acceptance-ядро: держатель capability не может оперировать в чужом
    СУЩЕСТВУЮЩЕМ домене — ни read, ни mutation; отказ явный, без 500."""

    async def test_create_rejects_foreign_domain_id_403(self, pg_client):
        """Явный body.domain_id=чужой-существующий → 403 binding (до 404
        ресурсных проверок)."""
        await _seed_foreign_assets(pg_client)

        _set_role("relmgr", "test")
        r = await _request(pg_client, "POST", "/api/v1/releases", json={
            "id": "rel-spoof", "domain_id": "alpha",
            "plan_id": "plan-alpha", "run_ids": ["run-alpha"],
        })
        assert r.status_code == 403, r.text
        assert "does not match authenticated principal domain" in r.json()["detail"]

        _set_role("svc", "test")
        r = await _request(pg_client, "POST", "/api/v1/apps", json={
            "id": "app-spoof", "domain_id": "alpha", "repo_binding": _REPO_BINDING,
        })
        assert r.status_code == 403, r.text

        r = await _request(pg_client, "POST", "/api/v1/runs", json={
            "id": "run-spoof", "plan_id": "plan-alpha", "domain_id": "alpha",
        })
        assert r.status_code == 403, r.text

    async def test_mutations_on_foreign_resources_404(self, pg_client):
        """Ownership-чек по ресурсу: чужой существующий ресурс → 404
        (анти-дисклеймер: существование не раскрывается)."""
        await _seed_foreign_assets(pg_client)

        _set_role("svc", "test")
        r = await _request(pg_client, "DELETE", "/api/v1/apps/app-alpha")
        assert r.status_code == 404, r.text
        r = await _request(pg_client, "PUT", "/api/v1/apps/app-alpha", json={})
        assert r.status_code == 404, r.text
        # compile: владение проверяется по app.domain_id (alpha ≠ test)
        r = await _request(pg_client, "POST", "/api/v1/plans/compile", json={
            "plan_id": "plan-spoof", "app_id": "app-alpha", "brick_ids": ["brick-alpha"],
        })
        assert r.status_code == 404, r.text

        _set_role("secadm", "test")
        r = await _request(pg_client, "POST", "/api/v1/runs/run-alpha/cancel")
        assert r.status_code == 404, r.text
        # gate: домен резолвится по цепочке gate → plan → app (alpha ≠ test)
        r = await _request(pg_client, "POST", "/api/v1/gates/gate-alpha/decision",
                           json={"decision": "pass"})
        assert r.status_code == 404, r.text

        _set_role("relmgr", "test")
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-alpha/transfer",
                           json={"initiated_by": "relmgr-test"})
        assert r.status_code == 404, r.text
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-alpha/transfer-v2",
                           json={"target_zone": "zt", "officer_name": "X",
                                 "sign_signature": "sig"})
        assert r.status_code == 404, r.text

    async def test_reads_cannot_be_widened_via_header(self, pg_client):
        """Read-пути: не-админ видит только свой домен; заголовок не
        расширяет чтение на чужой существующий домен."""
        await _seed_foreign_assets(pg_client)

        _set_role("relmgr", "test")
        r = await pg_client.get("/api/v1/releases")
        assert r.status_code == 200, r.text
        items = r.json()
        assert all(item["domain_id"] == "test" for item in items), items
        assert all(item["id"] != "rel-alpha" for item in items)

        r = await pg_client.get("/api/v1/releases/rel-alpha")
        assert r.status_code == 404, r.text
        r = await pg_client.get("/api/v1/releases/rel-alpha/envelope")
        assert r.status_code == 404, r.text

        _set_role("svc", "test")
        r = await pg_client.get("/api/v1/runs")
        assert r.status_code == 200, r.text
        assert all(item["domain_id"] == "test" for item in r.json()), r.json()
        r = await pg_client.get("/api/v1/runs/run-alpha")
        assert r.status_code == 404, r.text

        # PATCH статуса чужого прогона → 404
        _set_role("secadm", "test")
        r = await _request(pg_client, "PATCH", "/api/v1/runs/run-alpha/status",
                           json={"status": "running"})
        assert r.status_code == 404, r.text

    async def test_ghost_header_neither_blocks_nor_leaks(self, pg_client):
        """Ghost-заголовок для держателя capability: не 400, не 404, не 500 —
        операция в своём домене выполняется (заголовок игнорируется)."""
        await _seed_own_assets(pg_client)
        _set_role("svc", "test")
        r = await _request(pg_client, "PUT", "/api/v1/apps/app-test", json={},
                           headers={"X-Cosmo-Domain": "no-such-domain"})
        assert r.status_code == 200, r.text

        # Чужой существующий домен в заголовке не расширяет чтение
        await _seed_foreign_assets(pg_client)
        r = await pg_client.get("/api/v1/runs",
                                headers={"X-Cosmo-Domain": "alpha"})
        assert r.status_code == 200, r.text
        assert all(item["domain_id"] == "test" for item in r.json()), r.json()

    async def test_admin_context_switch_via_header_preserved(self, pg_client):
        """System admin сохраняет легитимный context switch: заголовок alpha
        показывает ресурсы домена alpha."""
        await _seed_foreign_assets(pg_client)
        # conftest даёт system-admin по умолчанию
        r = await pg_client.get("/api/v1/runs", headers={"X-Cosmo-Domain": "alpha"})
        assert r.status_code == 200, r.text
        items = r.json()
        assert any(item["id"] == "run-alpha" for item in items), items


class TestIdentityModeOwnDomainWorkflow:
    """Позитив: держатель capability полноценно работает в своём домене
    без единого заголовка."""

    async def test_full_own_domain_workflow_no_header(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _seed_own_assets(pg_client)

        # BRICK_MANAGE: создаём приложение
        _set_role("svc", "test")
        r = await _request(pg_client, "POST", "/api/v1/apps", json={
            "id": "app-own", "domain_id": "test", "repo_binding": _REPO_BINDING,
        })
        assert r.status_code == 201, r.text

        # SCAN_START: создаём прогон
        r = await _request(pg_client, "POST", "/api/v1/runs", json={
            "id": "run-own", "plan_id": "plan-test", "domain_id": "test",
        })
        assert r.status_code == 201, r.text

        # RELEASE_CREATE: релиз по своему плану и прогону
        _set_role("relmgr", "test")
        r = await _request(pg_client, "POST", "/api/v1/releases", json={
            "id": "rel-own", "domain_id": "test", "plan_id": "plan-test",
            "run_ids": ["run-own"],
        })
        assert r.status_code == 201, r.text

        # Чтение своего релиза без заголовка
        r = await pg_client.get("/api/v1/releases/rel-own")
        assert r.status_code == 200, r.text
        assert r.json()["domain_id"] == "test"

        # GATE_DECIDE: решение по gate своего плана (initiator run-own —
        # "system", SoD не срабатывает)
        _set_role("secadm", "test")
        r = await _request(pg_client, "POST", "/api/v1/gates/gate-test/decision",
                           json={"decision": "pass"})
        assert r.status_code == 200, r.text


class TestCapabilityGranularity:
    """COS-083: capability-гранулярность — держатель одной capability не
    получает смежные мутации. BUILD_RUN / DEPLOY_MANAGE / PROJECT_WRITE
    разнесены по ролям и зонам."""

    async def test_developer_builds_but_cannot_deploy(self, pg_client):
        """DEVELOPER: build:run есть, deploy:manage нет."""
        await _seed_own_assets(pg_client)
        _set_role("dev", "test")

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/builds",
                           json={"commit_sha": "abcdef12345"})
        assert r.status_code == 201, r.text

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/deploys",
                           json={"build_id": "bld-no"})
        assert r.status_code == 403, r.text
        assert "forbidden" in r.json()["detail"].lower()

    async def test_release_manager_deploys_but_cannot_build(self, pg_client):
        """RELEASE_MANAGER: deploy:manage есть, build:run нет."""
        await _seed_own_assets(pg_client)
        _set_role("relmgr", "test")

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/builds",
                           json={"commit_sha": "abcdef12345"})
        assert r.status_code == 403, r.text

        # Guard пройден: несуществующий деплой → честный 404, не 403
        r = await _request(pg_client, "POST", "/api/v1/deploys/dep-no/rollback",
                           json={})
        assert r.status_code == 404, r.text

    async def test_product_owner_projects_but_not_build(self, pg_client):
        """PRODUCT_OWNER: project:write есть, build:run нет."""
        await _seed_own_assets(pg_client)
        _set_role("owner", "test")

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/builds",
                           json={"commit_sha": "abcdef12345"})
        assert r.status_code == 403, r.text

        r = await _request(pg_client, "POST", "/api/v1/projects", json={
            "id": "proj-owner", "name": "Owner Project",
        })
        assert r.status_code == 201, r.text

    async def test_lead_has_build_deploy_project(self, pg_client):
        """DEVELOPER_LEAD: все три новые capability."""
        await _seed_own_assets(pg_client)
        _set_role("lead", "test")

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/builds",
                           json={"commit_sha": "abcdef12345"})
        assert r.status_code == 201, r.text
        build_id = r.json()["id"]

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/deploys",
                           json={"build_id": build_id})
        assert r.status_code == 201, r.text

        r = await _request(pg_client, "POST", "/api/v1/projects", json={
            "id": "proj-lead", "name": "Lead Project",
        })
        assert r.status_code == 201, r.text

    async def test_zone_gate_project_write_zr_only(self, pg_client):
        """PROJECT_WRITE — только ЗР: PRODUCT_OWNER в ЗТ получает 403
        (zone matrix), в ЗР — проходит."""
        await _ensure_domain(pg_client, "test")

        _set_role("owner", "test", zone="zt")
        r = await _request(pg_client, "POST", "/api/v1/projects", json={
            "id": "proj-zt", "name": "ZT Project",
        })
        assert r.status_code == 403, r.text

        _set_role("owner", "test", zone="zr")
        r = await _request(pg_client, "POST", "/api/v1/projects", json={
            "id": "proj-zr", "name": "ZR Project",
        })
        assert r.status_code == 201, r.text

    async def test_zone_build_zt_allowed(self, pg_client):
        """BUILD_RUN разрешён в ЗТ: DEVELOPER в ЗТ собирает своё приложение."""
        await _seed_own_assets(pg_client)
        _set_role("dev", "test", zone="zt")

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/builds",
                           json={"commit_sha": "abcdef12345"})
        assert r.status_code == 201, r.text

    async def test_zpe_operator_deploy_only(self, pg_client):
        """ZONE_OPERATOR_ZPE в ЗПЭ: deploy:manage есть, build:run нет."""
        await _seed_own_assets(pg_client)
        _set_role("zpeop", "test", zone="zpe")

        r = await _request(pg_client, "POST", "/api/v1/deploys/dep-no/rollback",
                           json={})
        assert r.status_code == 404, r.text  # guard пройден

        r = await _request(pg_client, "POST", "/api/v1/apps/app-test/builds",
                           json={"commit_sha": "abcdef12345"})
        assert r.status_code == 403, r.text


class TestDomainScopingReads:
    """COS-083: доменный scoping read-списков — не-админ видит только свой
    домен; чужие ресурсы — ghost-404; redaction производных полей."""

    async def _seed_projects(self, pg_client) -> None:
        """Admin: app-test (test), app-alpha (alpha), proj-test, proj-alpha,
        proj-mixed (alpha + test приложения)."""
        await _seed_foreign_assets(pg_client)  # app-alpha, brick-alpha, plan-alpha...
        # _seed_foreign_assets создаёт только alpha-набор; app-test (свой)
        # досоздаём здесь.
        async with _admin_override():
            r = await pg_client.post("/api/v1/apps", headers={"X-Cosmo-Domain": "test"},
                                     json={"id": "app-test", "domain_id": "test",
                                           "repo_binding": _REPO_BINDING})
            assert r.status_code in (201, 409), r.text

            for pid, app_ids in (
                ("proj-test", ["app-test"]),
                ("proj-alpha", ["app-alpha"]),
                ("proj-mixed", ["app-alpha", "app-test"]),
            ):
                r = await pg_client.post("/api/v1/projects", json={
                    "id": pid, "name": f"Project {pid}",
                })
                assert r.status_code in (201, 409), r.text
                for aid in app_ids:
                    # COS-083: ghost-контракт — админ без заголовка резолвится
                    # в свой домен, кросс-доменная привязка требует заголовок.
                    h = {"X-Cosmo-Domain": "alpha" if aid == "app-alpha" else "test"}
                    r = await pg_client.post(f"/api/v1/projects/{pid}/apps",
                                             headers=h, json={"app_id": aid})
                    assert r.status_code in (200, 409), r.text

    async def test_projects_list_scoped_and_ghost(self, pg_client):
        await self._seed_projects(pg_client)
        _set_role("owner", "test")

        r = await pg_client.get("/api/v1/projects")
        assert r.status_code == 200, r.text
        items = {p["id"]: p for p in r.json()}
        assert "proj-alpha" not in items
        assert "proj-test" in items
        assert "proj-mixed" in items
        # Redaction: application_ids не-админа — только видимые его домену
        assert items["proj-mixed"]["application_ids"] == ["app-test"], items["proj-mixed"]

        # Чужой проект → ghost-404
        r = await pg_client.get("/api/v1/projects/proj-alpha")
        assert r.status_code == 404, r.text

    async def test_project_apps_scoped(self, pg_client):
        await self._seed_projects(pg_client)
        _set_role("owner", "test")

        r = await pg_client.get("/api/v1/projects/proj-mixed/apps")
        assert r.status_code == 200, r.text
        app_ids = [a["id"] for a in r.json()]
        assert "app-alpha" not in app_ids
        assert "app-test" in app_ids

    async def test_add_foreign_app_to_project_ghost_404(self, pg_client):
        await self._seed_projects(pg_client)
        _set_role("owner", "test")

        r = await _request(pg_client, "POST", "/api/v1/projects/proj-test/apps",
                           json={"app_id": "app-alpha"})
        assert r.status_code == 404, r.text

    async def test_groups_scoping(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _ensure_domain(pg_client, "alpha")
        async with _admin_override():
            for gid, dom in (("grp-test2", "test"), ("grp-alpha", "alpha")):
                r = await pg_client.post("/api/v1/groups", json={
                    "id": gid, "domain_id": dom, "level": 1, "name": gid,
                })
                assert r.status_code in (201, 409), r.text

        _set_role("svc", "test")
        r = await pg_client.get("/api/v1/groups")
        assert r.status_code == 200, r.text
        ids = [g["id"] for g in r.json()]
        assert "grp-alpha" not in ids
        assert "grp-test2" in ids

        r = await pg_client.get("/api/v1/groups/grp-alpha")
        assert r.status_code == 404, r.text

    async def test_build_deploy_reads_scoped(self, pg_client):
        await _seed_foreign_assets(pg_client)  # app-alpha (чужой)
        await _seed_own_assets(pg_client)      # app-test (свой)
        _set_role("dev", "test")

        r = await pg_client.get("/api/v1/apps/app-alpha/builds")
        assert r.status_code == 404, r.text
        r = await pg_client.get("/api/v1/apps/app-alpha/deploys")
        assert r.status_code == 404, r.text

        r = await pg_client.get("/api/v1/apps/app-test/builds")
        assert r.status_code == 200, r.text
        r = await pg_client.get("/api/v1/apps/app-test/deploys")
        assert r.status_code == 200, r.text


class TestGuardPass3Pipelines:
    """COS-086: bricks CRUD + plans write/read — capability-guard'ы,
    ghost-404 через app-якорь, доменный scoping read-списков.

    Brick — глобальный каталог (без domain_id): capability-only.
    Plan якорится к домену через plan.app_id → Application.domain_id
    (как gates в COS-083)."""

    async def test_brick_reads_require_principal(self, pg_client):
        _anon()
        for url in ("/api/v1/bricks", "/api/v1/bricks/brick-x",
                    "/api/v1/plans", "/api/v1/plans/plan-x",
                    "/api/v1/projects/proj-x/team"):
            r = await pg_client.get(url)
            assert r.status_code == 401, f"{url}: {r.text}"

    async def test_dev_lacks_brick_manage(self, pg_client):
        """DEVELOPER имеет build:run, но НЕ brick:manage → 403."""
        await _ensure_domain(pg_client, "test")
        _set_role("dev", "test")
        r = await _request(pg_client, "POST", "/api/v1/bricks", json={
            "id": "brick-dev", "name": "Dev Brick", "type": "autotest",
            "source": "internal", "definition": {},
        })
        assert r.status_code == 403, r.text
        r = await _request(pg_client, "DELETE", "/api/v1/bricks/brick-dev")
        assert r.status_code == 403, r.text

    async def test_brick_crud_global_no_domain_scoping(self, pg_client):
        """Brick — глобальный каталог: держатель capability видит и правит
        все bricks (доменного scoping нет — якоря нет)."""
        await _ensure_domain(pg_client, "test")  # capability-guard резолвит домен
        await _seed_brick(pg_client, "brick-glob")
        _set_role("svc", "test")

        r = await pg_client.get("/api/v1/bricks")
        assert r.status_code == 200, r.text
        assert "brick-glob" in [b["id"] for b in r.json()]

        r = await pg_client.get("/api/v1/bricks/brick-glob")
        assert r.status_code == 200, r.text

        r = await _request(pg_client, "PUT", "/api/v1/bricks/brick-glob",
                           json={"name": "Renamed Glob"})
        assert r.status_code == 200, r.text
        r = await _request(pg_client, "DELETE", "/api/v1/bricks/brick-glob")
        assert r.status_code == 204, r.text

    async def test_plan_create_ghost_foreign_app_404(self, pg_client):
        await _seed_foreign_assets(pg_client)  # app-alpha + brick-alpha (alpha)
        await _seed_own_assets(pg_client)      # app-test (test)
        _set_role("svc", "test")

        # Чужое приложение → ghost-404 (существование не раскрывается)
        r = await _request(pg_client, "POST", "/api/v1/plans", json={
            "id": "plan-spoof", "app_id": "app-alpha",
            "brick_ids": ["brick-alpha"],
        })
        assert r.status_code == 404, r.text

        # Своё приложение → 201 (без заголовка — identity binding)
        r = await _request(pg_client, "POST", "/api/v1/plans", json={
            "id": "plan-own", "app_id": "app-test",
            "brick_ids": ["brick-test"],
        })
        assert r.status_code == 201, r.text

    async def test_plan_read_delete_ghost_and_scoping(self, pg_client):
        await _seed_foreign_assets(pg_client)
        await _seed_own_assets(pg_client)
        _set_role("svc", "test")

        # Свой план создаём здесь же (per-test БД)
        r = await _request(pg_client, "POST", "/api/v1/plans", json={
            "id": "plan-own", "app_id": "app-test",
            "brick_ids": ["brick-test"],
        })
        assert r.status_code == 201, r.text

        # list: только планы своего домена
        r = await pg_client.get("/api/v1/plans")
        assert r.status_code == 200, r.text
        ids = [p["id"] for p in r.json()]
        assert "plan-alpha" not in ids
        assert "plan-test" in ids

        # get/delete чужого плана → ghost-404
        r = await pg_client.get("/api/v1/plans/plan-alpha")
        assert r.status_code == 404, r.text
        r = await _request(pg_client, "DELETE", "/api/v1/plans/plan-alpha")
        assert r.status_code == 404, r.text

        # свой план читается и удаляется
        r = await pg_client.get("/api/v1/plans/plan-test")
        assert r.status_code == 200, r.text
        r = await _request(pg_client, "DELETE", "/api/v1/plans/plan-own")
        assert r.status_code == 204, r.text

    async def test_admin_sees_all_plans(self, pg_client):
        await _seed_foreign_assets(pg_client)
        await _seed_own_assets(pg_client)
        r = await pg_client.get("/api/v1/plans")
        assert r.status_code == 200, r.text
        ids = [p["id"] for p in r.json()]
        assert "plan-alpha" in ids and "plan-test" in ids


class TestProjectTeamAnchor:
    """COS-086: ProjectTeam привязан к резолв-контракту — видимость команды
    выводится из приложений проекта (ProjectTeam без собственного domain_id)."""

    async def test_team_ghost_for_foreign_project(self, pg_client):
        await TestDomainScopingReads()._seed_projects(pg_client)
        _set_role("owner", "test")

        # Чужой проект → ghost-404 (как get_project в COS-083)
        r = await pg_client.get("/api/v1/projects/proj-alpha/team")
        assert r.status_code == 404, r.text

        # Свой проект → 200 (пустая команда — валидный дефолт)
        r = await pg_client.get("/api/v1/projects/proj-test/team")
        assert r.status_code == 200, r.text

        # Смешанный: есть видимое приложение → 200
        r = await pg_client.get("/api/v1/projects/proj-mixed/team")
        assert r.status_code == 200, r.text

    async def test_team_anonymous_401(self, pg_client):
        _anon()
        r = await pg_client.get("/api/v1/projects/proj-any/team")
        assert r.status_code == 401, r.text


class TestGuardPass4ReleasesRuns:
    """COS-091: унификация in-body auth → deps-guards в releases.py/runs.py.

    releases: submit/approve/reject/deploy/delete были анонимными —
    RELEASE_SUBMIT/APPROVE/REJECT/DEPLOY/CREATE; envelope/verify →
    ENVELOPE_VERIFY (закрытие crypto-oracle). runs: PATCH status — был
    write с голым principal → scan:start; batches-семья была полностью
    анонимной — reads require_principal + доменный scoping через якорь
    план → приложение → домен, writes scan:start + ghost.
    notifications.py — зона Flash (13 in-body), сознательно не тронут.
    """

    async def test_batch_reads_require_principal(self, pg_client):
        _anon()
        for url in ("/api/v1/batches", "/api/v1/batches/batch-x"):
            r = await pg_client.get(url)
            assert r.status_code == 401, f"{url}: {r.text}"

    async def test_user_reads_batches_200(self, pg_client):
        """Read-роут require_principal: USER читает (свой скоуп) — не 403."""
        await _seed_own_assets(pg_client)
        _set_user()
        r = await pg_client.get("/api/v1/batches")
        assert r.status_code == 200, r.text

    async def test_release_lifecycle_guarded(self, pg_client):
        """Happy path сквозь гварды: relmgr submit (RELEASE_SUBMIT), secoff
        approve (RELEASE_APPROVE) — на своём домене гвард пройден."""
        await _seed_own_assets(pg_client)

        _set_role("relmgr", "test")
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-test/submit")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_review"

        _set_role("secoff", "test")
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-test/approve",
                           json={"decided_by": "secoff-test"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    async def test_sod_relmgr_cannot_approve(self, pg_client):
        """SoD: relmgr держит RELEASE_SUBMIT, но не RELEASE_APPROVE → 403
        даже на своём релизе (утверждение — только security officer)."""
        await _seed_own_assets(pg_client)
        _set_role("relmgr", "test")
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-test/submit")
        assert r.status_code == 200, r.text
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-test/approve",
                           json={"decided_by": "relmgr-test"})
        assert r.status_code == 403, r.text

    async def test_release_lifecycle_ghost_foreign(self, pg_client):
        """Чужой релиз → ghost-404 для lifecycle-роутов (держатели capability)."""
        await _seed_foreign_assets(pg_client)
        _set_role("relmgr", "test")

        r = await _request(pg_client, "POST", "/api/v1/releases/rel-alpha/submit")
        assert r.status_code == 404, r.text
        r = await _request(pg_client, "DELETE", "/api/v1/releases/rel-alpha")
        assert r.status_code == 404, r.text

    async def test_deploy_zone_restriction(self, pg_client):
        """RELEASE_DEPLOY — действие ЗТ: в ЗР → 403 по зоне; в ЗТ на чужом
        релизе → ghost-404."""
        await _seed_own_assets(pg_client)
        _set_role("relmgr", "test", zone="zr")
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-test/deploy")
        assert r.status_code == 403, r.text

        await _seed_foreign_assets(pg_client)
        _set_role("relmgr", "test", zone="zt")
        r = await _request(pg_client, "POST", "/api/v1/releases/rel-alpha/deploy")
        assert r.status_code == 404, r.text

    async def test_run_status_guard_and_ghost(self, pg_client):
        """PATCH run status: держатель scan:start правит свой прогон,
        чужой → ghost-404."""
        await _seed_own_assets(pg_client)
        await _seed_foreign_assets(pg_client)
        _set_role("svc", "test")

        r = await _request(pg_client, "PATCH", "/api/v1/runs/run-test/status",
                           json={"status": "running"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "running"

        r = await _request(pg_client, "PATCH", "/api/v1/runs/run-alpha/status",
                           json={"status": "running"})
        assert r.status_code == 404, r.text

    async def test_batch_scoping_and_ghost(self, pg_client):
        """Batches: чужие не видны в списке и по id; создание на чужом
        плане → ghost-404; свои создаются и ведутся."""
        await _seed_own_assets(pg_client)
        await _seed_foreign_assets(pg_client)

        # id чужих батчей — от админа (дефолтный conftest-override)
        async with _admin_override():
            r = await pg_client.get("/api/v1/batches?plan_id=plan-alpha")
            assert r.status_code == 200, r.text
            foreign_ids = [b["id"] for b in r.json()]
        assert len(foreign_ids) > 0

        _set_role("svc", "test")
        # Список: чужих батчей нет ни без фильтра, ни по плану
        r = await pg_client.get("/api/v1/batches")
        assert r.status_code == 200, r.text
        own_ids = [b["id"] for b in r.json()]
        r = await pg_client.get("/api/v1/batches?plan_id=plan-alpha")
        assert r.status_code == 200, r.text
        assert r.json() == [], r.text

        # По id чужой батч → ghost-404
        for bid in foreign_ids:
            assert bid not in own_ids
            r = await pg_client.get(f"/api/v1/batches/{bid}")
            assert r.status_code == 404, f"{bid}: {r.text}"

        # Создание на чужом плане → ghost-404
        r = await _request(pg_client, "POST", "/api/v1/batches",
                           json={"id": "batch-spoof", "plan_id": "plan-alpha",
                                 "type": "static_scan"})
        assert r.status_code == 404, r.text

        # Свой батч: 201 → PATCH running 200 → читается
        r = await _request(pg_client, "POST", "/api/v1/batches",
                           json={"id": "batch-own", "plan_id": "plan-test",
                                 "type": "static_scan"})
        assert r.status_code == 201, r.text
        r = await _request(pg_client, "PATCH", "/api/v1/batches/batch-own/status",
                           json={"status": "running"})
        assert r.status_code == 200, r.text
        r = await pg_client.get("/api/v1/batches/batch-own")
        assert r.status_code == 200, r.text
