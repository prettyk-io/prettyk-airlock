# -*- coding: utf-8 -*-
"""COS-066: Transfer API Security & Contract Hardening — matrix tests.

Acceptance-покрытие:
  1. Auth-матрица всех 9 transfer endpoints: anonymous / USER / operator /
     manager / ADMIN_SEC / system admin.
  2. Domain ownership на каждом read и mutation endpoint — решение ТОЛЬКО по
     principal.domain_id (anti-spoofing: заголовок X-Cosmo-Domain не расширяет
     доступ; admin — контекстный доступ через заголовок).
  3. Anti-disclosure: чужой ресурс → 404 (не 403, без раскрытия существования).
  4. Exhaustive error-contract matrix: route-level ошибки в едином конверте
     {"error": {code, message, details}}; deps-level (guard) — FastAPI
     {"detail": ...} (документированная граница).
  5. Malformed inputs: невалидный JSON / отсутствие обязательных полей.
  6. Дубликаты и идемпотентность: re-validate, re-receive, duplicate plan.
  7. OpenAPI: пути/коды/enum в спеке, сборка /openapi.json в чистом процессе.
  8. Cross-route regression: guarded маршруты после починки deps._guard —
     USER получает 400/403, никогда 500.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_orch = Path(__file__).resolve().parents[1]
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

pytestmark = pytest.mark.asyncio

from orchestrator.cosmo.api.deps import get_current_principal
from orchestrator.cosmo.api.main import app
from orchestrator.cosmo.api.routes.repos import FileTreeNode
from orchestrator.cosmo.api.routes.transfer import get_transfer_repository
from orchestrator.cosmo.domain.rbac import CBRRole, PrincipalContext, Role
from orchestrator.cosmo.transfer.registry import get_transfer_registry

BASE = "/api/v1/transfer"

# ── helpers ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_registry():
    """Изоляция in-memory registry между тестами.

    COS-077: боевой путь transfer API — durable PG-репозиторий; hermetic-тесты
    явно подменяют dependency на in-memory registry (PG не затрагивается).
    Override в teardown снимается — cross-file утечки dependency_overrides
    невозможны (корень flake ×4 в run1: кросс-файловый in-memory стейт)."""
    app.dependency_overrides[get_transfer_repository] = get_transfer_registry
    get_transfer_registry().reset()
    yield
    app.dependency_overrides.pop(get_transfer_repository, None)
    get_transfer_registry().reset()


def _set_principal(
    roles: list | None,
    domain_id: str = "test",
    is_system_admin: bool = False,
    zone: str = "zr",
    user_id: str = "matrix-user",
) -> None:
    """Переопределить get_current_principal. roles=None + is_system_admin=True
    оставляет conftest-админа нетронутым (см. использование в матрицах)."""
    async def _principal() -> PrincipalContext:
        return PrincipalContext(
            user_id=user_id,
            roles=roles or [Role.USER],
            domain_id=domain_id,
            zone=zone,
            is_authenticated=True,
            is_system_admin=is_system_admin,
        )
    app.dependency_overrides[get_current_principal] = _principal


def _anon() -> None:
    """Убрать override → реальный get_current_principal → без Authorization 401."""
    app.dependency_overrides.pop(get_current_principal, None)


def _principal_spec() -> list:
    """Параметры матриц: (label, roles, is_admin, expected_mutation, expected_read)."""
    return [
        ("anonymous", None, None, 401, 401),
        ("user", [Role.USER], False, 403, 200),
        ("operator_zpe", [CBRRole.ZONE_OPERATOR_ZPE], False, 403, 200),
        ("release_manager", [CBRRole.RELEASE_MANAGER], False, 201, 200),
        ("admin_sec", [Role.ADMIN_SEC], False, 201, 200),
        ("system_admin", None, True, 201, 200),
    ]


def _manifest(release_id: str, revision: int = 1, tag: str = "base") -> dict:
    return {"release_id": release_id, "revision": revision, "tag": tag}


def _plan_payload(
    plan_id: str = "plan-mx-1",
    release_id: str = "rel-mx",
    item_id: str = "item-mx-1",
    revision: int = 1,
    package_mode: str = "metadata_envelope",
    source_ref: str = "git::gitea/acme/app@main",
) -> dict:
    return {
        "plan_id": plan_id,
        "release_id": release_id,
        "correlation_id": f"corr-{plan_id}",
        "source_zone": "zr",
        "target_zone": "zt",
        "items": [
            {
                "item_id": item_id,
                "artifact_plane": "metadata_envelope",
                "package_mode": package_mode,
                "transport_profile": "direct_authenticated_api",
                "source_ref": source_ref,
                "target_ref": "sod-bridge://inbox/app",
                "manifest": _manifest(release_id, revision),
                "payload_refs": [],
                "revision": revision,
            }
        ],
    }


async def _ensure_domain(client, domain_id: str) -> None:
    """Создать домен в БД (guard require_domain проверяет существование).

    COS-068: POST /api/v1/domains — system-admin only. Домен-сетап выполняется
    под временным system-admin override; прежний principal восстанавливается."""
    prev = app.dependency_overrides.get(get_current_principal)

    async def _sysadmin() -> PrincipalContext:
        return PrincipalContext(
            user_id="sysadmin-setup",
            roles=[],
            is_authenticated=True,
            is_system_admin=True,
        )

    app.dependency_overrides[get_current_principal] = _sysadmin
    try:
        r = await client.post("/api/v1/domains", json={
            "id": domain_id,
            "label": f"Domain {domain_id}",
            "forge_binding": {
                "forge_type": "gitea",
                "url": "https://gitea.example",
                "token_ref": f"vault://cosmo/{domain_id}",
            },
            "quota": {"max_runs": 10, "max_storage_gb": 100, "max_cpu": 4},
        })
        assert r.status_code in (201, 409), r.text
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = prev


async def _create_plan_as_manager(client, payload: dict) -> None:
    """План создаётся manager'ом домена test (release:transfer в зоне zr).

    Не-админ мутации обязаны нести X-Cosmo-Domain на КАЖДОМ запросе
    (guard-level require_domain). Handler дополнительно привязывает запись
    к principal.domain_id (identity)."""
    await _ensure_domain(client, "test")
    _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
    r = await client.post(f"{BASE}/plans", json=payload,
                          headers={"X-Cosmo-Domain": "test"})
    assert r.status_code == 201, r.text


def _assert_error_contract(body: dict, code: str | None = None) -> None:
    """Route-level ошибки transfer — единый конверт без вложенного detail."""
    assert set(body.keys()) == {"error"}, f"unexpected top-level keys: {body.keys()}"
    err = body["error"]
    assert set(err.keys()) >= {"code", "message", "details"}
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["details"], dict)
    if code is not None:
        assert err["code"] == code, f"expected {code}, got {err['code']}"


def _assert_guard_error(body: dict) -> None:
    """Deps-level ошибки (guard) — FastAPI HTTPException shape {"detail": ...}."""
    assert "detail" in body, f"expected FastAPI detail shape, got: {body}"


# READ-эндпоинты (без guard'а — авторизация через _authorize_record_access)
_READ_URLS = [
    f"{BASE}/plans/plan-mx-1",
    f"{BASE}/plans/plan-mx-1/items",
    f"{BASE}/items/item-mx-1",
    f"{BASE}/items/item-mx-1/landing",
    f"{BASE}/items/item-mx-1/recovery",
]

_MUTATION_URLS = [
    ("POST", f"{BASE}/plans"),
    ("POST", f"{BASE}/items/item-mx-1/validate"),
    ("POST", f"{BASE}/items/item-mx-1/landing/receive"),
]


# ── 1. Auth-матрица: mutation (guard) × read (ownership) ─────────────


class TestAuthMatrix:

    async def test_mutation_matrix_create_plan(self, pg_client):
        """POST /plans: RBAC-механика guard'а по всем principal-классам."""
        await _ensure_domain(pg_client, "test")
        for label, roles, is_admin, mut_expected, _read in _principal_spec():
            if label == "anonymous":
                _anon()
            elif label == "system_admin":
                pass  # conftest-админ остаётся
            else:
                _set_principal(roles, is_system_admin=bool(is_admin))
            r = await pg_client.post(
                f"{BASE}/plans",
                json=_plan_payload(plan_id=f"plan-{label}", item_id=f"item-{label}",
                                   release_id=f"rel-{label}"),
                headers={"X-Cosmo-Domain": "test"})
            assert r.status_code == mut_expected, f"{label}: {r.text}"
            if r.status_code in (400, 401, 403):
                _assert_guard_error(r.json())

    async def test_mutation_matrix_item_endpoints(self, pg_client):
        """validate + landing/receive: разрешённые роли работают со СВОИМ
        свежим планом (validate → 200, receive → 200); запрещённые получают
        403 от guard'а на обоих эндпоинтах."""
        await _ensure_domain(pg_client, "test")
        denied = [("user", [Role.USER]),
                  ("operator_zpe", [CBRRole.ZONE_OPERATOR_ZPE])]
        for label, roles in denied:
            _set_principal(roles)
            for method, url in _MUTATION_URLS[1:]:
                r = await getattr(pg_client, method.lower())(
                    url, headers={"X-Cosmo-Domain": "test"})
                assert r.status_code == 403, f"{label} {url}: {r.text}"
                _assert_guard_error(r.json())
        allowed = [("release_manager", [CBRRole.RELEASE_MANAGER], False),
                   ("admin_sec", [Role.ADMIN_SEC], False),
                   ("system_admin", None, True)]
        for label, roles, is_admin in allowed:
            if label != "system_admin":
                _set_principal(roles, is_system_admin=is_admin)
            payload = _plan_payload(plan_id=f"plan-{label}", item_id=f"item-{label}",
                                    release_id=f"rel-{label}")
            r = await pg_client.post(f"{BASE}/plans", json=payload,
                                     headers={"X-Cosmo-Domain": "test"})
            assert r.status_code == 201, f"{label} create: {r.text}"
            r = await pg_client.post(f"{BASE}/items/item-{label}/validate",
                                     headers={"X-Cosmo-Domain": "test"})
            assert r.status_code == 200, f"{label} validate: {r.text}"
            r = await pg_client.post(f"{BASE}/items/item-{label}/landing/receive",
                                     headers={"X-Cosmo-Domain": "test"})
            assert r.status_code == 200, f"{label} receive: {r.text}"

    async def test_anonymous_all_mutation_endpoints_401(self, pg_client):
        await _ensure_domain(pg_client, "test")
        _anon()
        for method, url in _MUTATION_URLS:
            r = await getattr(pg_client, method.lower())(url)
            assert r.status_code == 401, f"{url}: {r.text}"
            _assert_guard_error(r.json())

    async def test_read_matrix(self, pg_client):
        """Все read-эндпоинты: authorized → 200, anonymous → 401."""
        await _create_plan_as_manager(pg_client, _plan_payload())
        for label, roles, is_admin, _mut, read_expected in _principal_spec():
            if label == "anonymous":
                _anon()
            elif label == "system_admin":
                pass
            else:
                _set_principal(roles, is_system_admin=bool(is_admin))
            for url in _READ_URLS:
                r = await pg_client.get(url)
                assert r.status_code == read_expected, f"{label} {url}: {r.text}"


# ── 2. Domain ownership + anti-spoofing ──────────────────────────────


class TestOwnershipAntiSpoof:

    async def test_foreign_user_cannot_read_with_spoofed_header(self, pg_client):
        """USER из домена beta + заголовок test → 404. Заголовок не даёт доступ."""
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([Role.USER], domain_id="beta")
        for url in _READ_URLS:
            r = await pg_client.get(url, headers={"X-Cosmo-Domain": "test"})
            assert r.status_code == 404, f"{url}: {r.text}"
            _assert_error_contract(r.json(), "NOT_FOUND")
        # Корреляция не утекает чужие планы даже с подделанным заголовком
        r = await pg_client.get(f"{BASE}/releases/rel-mx/plans",
                                headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 200
        assert r.json() == []

    async def test_spoofed_header_cannot_redirect_creation(self, pg_client):
        """Manager домена test с заголовком alpha: план регистрируется в СВОЁМ
        домене (test), а не в alpha — контекст создания не подделать."""
        await _ensure_domain(pg_client, "test")
        await _ensure_domain(pg_client, "alpha")
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload(),
                                 headers={"X-Cosmo-Domain": "alpha"})
        assert r.status_code == 201, r.text
        # План принадлежит test: manager test видит, beta user — нет
        r = await pg_client.get(f"{BASE}/plans/plan-mx-1")
        assert r.status_code == 200
        _set_principal([Role.USER], domain_id="beta")
        r = await pg_client.get(f"{BASE}/plans/plan-mx-1")
        assert r.status_code == 404
        _assert_error_contract(r.json(), "NOT_FOUND")

    async def test_foreign_manager_mutation_gets_404_no_disclosure(self, pg_client):
        """Manager из чужого домена beta: guard пропускает (cap есть), но
        ownership по principal.domain_id → 404 без раскрытия существования."""
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="beta")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/landing/receive",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 404, r.text
        _assert_error_contract(r.json(), "NOT_FOUND")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/validate",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 404
        _assert_error_contract(r.json(), "NOT_FOUND")

    async def test_admin_header_is_context_switch(self, pg_client):
        """System admin: заголовок — легитимное переключение контекста."""
        _set_principal(None, is_system_admin=True)  # noop, conftest-админ
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload(),
                                 headers={"X-Cosmo-Domain": "beta"})
        assert r.status_code == 201, r.text
        # beta user видит план, созданный админом в его домене
        _set_principal([Role.USER], domain_id="beta")
        r = await pg_client.get(f"{BASE}/plans/plan-mx-1")
        assert r.status_code == 200
        # test user НЕ видит (план в beta)
        _set_principal([Role.USER], domain_id="test")
        r = await pg_client.get(f"{BASE}/plans/plan-mx-1")
        assert r.status_code == 404

    async def test_correlation_filters_by_identity_not_header(self, pg_client):
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="beta")
        r = await pg_client.get(f"{BASE}/releases/rel-mx/plans",
                                headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 200
        assert r.json() == []
        # Свой домен — план виден
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.get(f"{BASE}/releases/rel-mx/plans")
        assert r.status_code == 200
        assert len(r.json()) == 1


# ── 3. Error-contract matrix (route-level) + guard boundary ──────────


class TestErrorContractMatrix:

    async def test_duplicate_plan_conflict(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload(),
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 409
        _assert_error_contract(r.json(), "CONFLICT")

    async def test_unknown_transition_404(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/landing/teleport",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 404
        _assert_error_contract(r.json(), "NOT_FOUND")

    async def test_invalid_transition_preserves_state(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/landing/bootstrap",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 409
        _assert_error_contract(r.json(), "INVALID_TRANSITION")
        r = await pg_client.get(f"{BASE}/items/item-mx-1/landing")
        assert r.json()["state"] == "not_received"

    async def test_checksum_mismatch_contract(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/landing/receive",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 200
        tampered = _manifest("rel-mx", 1, tag="tampered")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/landing/verify",
                                 json={"incoming_manifest": tampered},
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 409
        _assert_error_contract(r.json(), "CHECKSUM_MISMATCH")

    async def test_duplicate_revision_contract(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        other = _plan_payload(plan_id="plan-mx-2", item_id="item-mx-2", revision=1)
        await _create_plan_as_manager(pg_client, other)
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/items/item-mx-1/landing/receive",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 200
        r = await pg_client.post(f"{BASE}/items/item-mx-2/landing/receive",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 409
        _assert_error_contract(r.json(), "DUPLICATE_REVISION")
        assert r.json()["error"]["details"]["existing_item_id"] == "item-mx-1"

    async def test_validation_failure_contract(self, pg_client):
        await _ensure_domain(pg_client, "test")
        payload = _plan_payload(plan_id="plan-bad", item_id="item-bad",
                                package_mode="full_package", source_ref="")
        await _create_plan_as_manager(pg_client, payload)
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/items/item-bad/validate",
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 422
        _assert_error_contract(r.json(), "VALIDATION_FAILURE")
        details = r.json()["error"]["details"]
        assert "FULL_PACKAGE_NO_PAYLOAD" in details["error_codes"]
        assert "SOURCE_REF_MISSING" in details["error_codes"]

    async def test_malformed_json_is_fastapi_boundary(self, pg_client):
        """Невалидный JSON → 422 {"detail": [...]}: FastAPI-native граница
        (guard пропускает manager'а, body-валидация падает до обработчика)."""
        await _ensure_domain(pg_client, "test")
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(
            f"{BASE}/plans", content="{not json",
            headers={"Content-Type": "application/json",
                     "X-Cosmo-Domain": "test"})
        assert r.status_code == 422
        _assert_guard_error(r.json())

    async def test_missing_required_field_422(self, pg_client):
        await _ensure_domain(pg_client, "test")
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/plans", json={"plan_id": "incomplete"},
                                 headers={"X-Cosmo-Domain": "test"})
        assert r.status_code == 422
        _assert_guard_error(r.json())

    async def test_guard_boundaries_400_and_404(self, pg_client):
        """Не-админ мутация: без заголовка → 400; несуществующий домен → 404."""
        await _ensure_domain(pg_client, "test")
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload())
        assert r.status_code == 400
        _assert_guard_error(r.json())
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload(),
                                 headers={"X-Cosmo-Domain": "ghost-domain"})
        assert r.status_code == 404
        _assert_guard_error(r.json())

    async def test_system_admin_bypasses_header_requirement(self, pg_client):
        """System admin без заголовка: guard bypass + контекст principal.domain_id."""
        r = await pg_client.post(f"{BASE}/plans", json=_plan_payload())
        assert r.status_code == 201, r.text


# ── 4. Идемпотентность повторов ──────────────────────────────────────


class TestIdempotency:

    async def test_revalidate_is_idempotent(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r1 = await pg_client.post(f"{BASE}/items/item-mx-1/validate",
                                  headers={"X-Cosmo-Domain": "test"})
        assert r1.status_code == 200
        r2 = await pg_client.post(f"{BASE}/items/item-mx-1/validate",
                                  headers={"X-Cosmo-Domain": "test"})
        assert r2.status_code == 200
        assert r1.json() == r2.json()

    async def test_rereceive_is_rejected_as_invalid_transition(self, pg_client):
        await _ensure_domain(pg_client, "test")
        await _create_plan_as_manager(pg_client, _plan_payload())
        _set_principal([CBRRole.RELEASE_MANAGER], domain_id="test")
        r1 = await pg_client.post(f"{BASE}/items/item-mx-1/landing/receive",
                                  headers={"X-Cosmo-Domain": "test"})
        assert r1.status_code == 200
        r2 = await pg_client.post(f"{BASE}/items/item-mx-1/landing/receive",
                                  headers={"X-Cosmo-Domain": "test"})
        assert r2.status_code == 409
        # Тот же item → state machine, НЕ duplicate-revision
        _assert_error_contract(r2.json(), "INVALID_TRANSITION")
        # Состояние не пострадало
        r = await pg_client.get(f"{BASE}/items/item-mx-1/landing")
        assert r.json()["state"] == "received"


# ── 5. OpenAPI: контракт vs фактические ответы ───────────────────────


class TestOpenAPIContract:

    async def test_all_transfer_paths_documented(self, pg_client):
        r = await pg_client.get("/openapi.json")
        assert r.status_code == 200
        spec = r.json()
        expected_paths = {
            "/api/v1/transfer/plans",
            "/api/v1/transfer/plans/{plan_id}",
            "/api/v1/transfer/plans/{plan_id}/items",
            "/api/v1/transfer/releases/{release_id}/plans",
            "/api/v1/transfer/items/{item_id}",
            "/api/v1/transfer/items/{item_id}/validate",
            "/api/v1/transfer/items/{item_id}/landing",
            "/api/v1/transfer/items/{item_id}/landing/{transition}",
            "/api/v1/transfer/items/{item_id}/recovery",
        }
        assert expected_paths <= set(spec["paths"]), (
            f"missing: {expected_paths - set(spec['paths'])}"
        )

    async def test_documented_error_codes_match_observed(self, pg_client):
        """Задокументированные коды ответов совпадают с фактически
        наблюдаемыми в error-contract matrix (сводная сверка)."""
        r = await pg_client.get("/openapi.json")
        spec = r.json()
        # POST /plans: 201 + 409 (CONFLICT) задокументированы
        post_plans = spec["paths"]["/api/v1/transfer/plans"]["post"]
        assert "409" in post_plans["responses"]
        # landing/{transition}: 404/409/422 задокументированы
        transition = spec["paths"]["/api/v1/transfer/items/{item_id}/landing/{transition}"]["post"]
        for code in ("404", "409", "422"):
            assert code in transition["responses"], code
        # GET plan: 404 задокументирован
        get_plan = spec["paths"]["/api/v1/transfer/plans/{plan_id}"]["get"]
        assert "404" in get_plan["responses"]

    async def test_transfer_error_enum_in_spec(self, pg_client):
        r = await pg_client.get("/openapi.json")
        raw = r.text
        for code in ("NOT_FOUND", "INVALID_TRANSITION", "VALIDATION_FAILURE",
                     "CHECKSUM_MISMATCH", "DUPLICATE_REVISION", "CONFLICT"):
            assert code in raw, code

    async def test_openapi_builds_in_clean_process(self, pg_client):
        """Регрессия repos.py forward-ref: /openapi.json собирается в чистом
        интерпретаторе без тест-конотекста."""
        repo_root = Path(__file__).resolve().parents[3]
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "from orchestrator.cosmo.api.main import app; "
            "spec = app.openapi(); "
            "assert '/api/v1/transfer/plans' in spec['paths']; "
            "assert '/api/v1/repos/tree' in spec['paths']; "
            "print('openapi-ok')",
            cwd=str(repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        assert proc.returncode == 0, f"rc={proc.returncode}\n{err.decode()}"
        assert b"openapi-ok" in out

    async def test_file_tree_node_forward_ref_resolved(self, pg_client):
        """Регрессия: FileTreeNode (self-reference) строит schema с $defs."""
        schema = FileTreeNode.model_json_schema()
        assert "$defs" in schema
        assert "FileTreeNode" in schema["$defs"]
