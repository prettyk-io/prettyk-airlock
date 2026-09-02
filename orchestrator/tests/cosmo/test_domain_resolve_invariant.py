# -*- coding: utf-8 -*-
"""COS-083/COS-086: source-invariant — единый резолв домена caller'а в routes.

Контракт унификации (acceptance COS-083): "один резолв-путь домена во
всех route-файлах". Проверяется статически по исходникам, без БД:

  1. каждый routes/*.py, вызывающий verify_ownership, импортирует и
     resolve_caller_domain — сырой principal.domain_id как caller
     запрещён;
  2. ни один вызов verify_ownership не передаёт principal.domain_id
     напрямую — caller всегда результат resolve_caller_domain(principal,
     caller_domain-заголовок) (админ: header → identity → "default";
     не-админ: identity → header → "default");
  3. sanity: verify-поверхность непуста — инвариант не выродился в
     no-op при будущих рефакторингах.

COS-086 (guard pass 3) расширяет инвариант на новые поверхности:

  4. каждый write-хендлер (POST/PUT/DELETE/PATCH) в pipelines.py несёт
     capability-guard в сигнатуре — семья anonymous writes не может
     вернуться (bricks CRUD + POST/DELETE plans);
  5. ProjectTeam read (get_project_team) якорится к резолв-контракту —
     resolve_caller_domain + _caller_domain_app_ids в теле хендлера.

COS-091 (guard pass 4) распространяет инвариант 4 на releases.py и
runs.py: lifecycle-роуты релиза, PATCH статуса прогона и batches-семья
обязаны нести deps-guard — in-body auth-решения в этих файлах запрещены
(унификация гибридного auth).

COS-092 (guard pass 5) распространяет инвариант 4 на notifications.py:
ops-поверхность (webhook-config CRUD, DLQ, outbox, process tick) —
capability-guard (DOMAIN_CONFIGURE); личная поверхность (sse-ticket,
inbox read-marking) — identity-scoped personal writes, разрешены
явным allowlist'ом PRINCIPAL_OK_ROUTES (require_principal, recipient
из principal.user_id по построению).

Защита от дрейфа: новый route-файл с ownership-проверкой обязан пройти
через тот же резолв, иначе этот тест падает на CI до слияния.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROUTES_DIR = Path(__file__).resolve().parents[2] / "cosmo" / "api" / "routes"

# Минимальное число route-файлов с verify_ownership (sanity-порог
# против вырождения инварианта; на момент COS-083 — 8 файлов).
MIN_VERIFY_FILES = 5

# Окно после "verify_ownership(", в котором запрещён raw caller.
_RAW_WINDOW = 300


def _route_files() -> list[Path]:
    return sorted(ROUTES_DIR.glob("*.py"))


def _files_with(texts: dict[Path, str], needle: str) -> dict[Path, str]:
    return {p: t for p, t in texts.items() if needle in t}


def test_invariant_files_use_unified_resolve() -> None:
    """Инвариант 1: импорт resolve_caller_domain рядом с verify_ownership."""
    texts = {p: p.read_text(encoding="utf-8") for p in _route_files()}
    verify_files = _files_with(texts, "verify_ownership(")

    assert len(verify_files) >= MIN_VERIFY_FILES, (
        f"verify-поверхность сжалась до {len(verify_files)} файлов "
        f"(ожидалось >= {MIN_VERIFY_FILES}) — инвариант выродился"
    )

    for path, text in verify_files.items():
        assert "resolve_caller_domain" in text, (
            f"{path.name}: вызывает verify_ownership, но не импортирует "
            f"resolve_caller_domain — нарушен единый резолв домена (COS-083)"
        )


def test_invariant_no_raw_principal_domain_caller() -> None:
    """Инвариант 2: ни один verify_ownership не получает principal.domain_id
    напрямую вторым аргументом."""
    texts = {p: p.read_text(encoding="utf-8") for p in _route_files()}
    verify_files = _files_with(texts, "verify_ownership(")

    violations: list[str] = []
    for path, text in verify_files.items():
        for m in re.finditer(r"verify_ownership\s*\(", text):
            window = text[m.end():m.end() + _RAW_WINDOW]
            if "principal.domain_id" in window:
                line = text[:m.start()].count("\n") + 1
                violations.append(f"{path.name}:{line}")

    assert not violations, (
        "verify_ownership вызывается с raw principal.domain_id в: "
        f"{', '.join(violations)} — замените на "
        f"resolve_caller_domain(principal, caller_domain) (COS-083)"
    )


def test_invariant_domain_guard_contract_shape() -> None:
    """Контракт резолва: resolve_caller_domain в domain_guard.py принимает
    (principal, header) и покрывает обе ветки (admin/non-admin)."""
    guard = ROUTES_DIR.parent / "domain_guard.py"
    text = guard.read_text(encoding="utf-8")

    sig = re.search(
        r"def\s+resolve_caller_domain\s*\(\s*\w+\s*:?\s*[^)]*,\s*\w+\s*:?\s*[^)]*\)",
        text,
    )
    assert sig is not None, (
        "domain_guard.resolve_caller_domain потерял двухаргументную "
        "сигнатуру (principal, header) — контракт COS-083 нарушен"
    )

    assert "is_system_admin" in text, (
        "resolve_caller_domain не различает admin/non-admin ветки"
    )
    assert '"default"' in text, (
        "resolve_caller_domain потерял default-фолбэк (совместимость "
        "старых тестов и системных вызовов)"
    )


def test_invariant_pipeline_write_routes_guarded() -> None:
    """COS-086, инвариант 4: все write-хендлеры pipelines.py несут
    capability-guard в сигнатуре — семья anonymous writes не возвращается."""
    text = (ROUTES_DIR / "pipelines.py").read_text(encoding="utf-8")
    blocks = re.split(r"(?=@router\.(?:get|post|put|delete|patch)\()", text)

    violations = _write_routes_without_capability(text)
    assert not violations, (
        "write-хендлеры pipelines.py без capability-guard: "
        f"{', '.join(violations)} — семья anonymous writes (COS-086) "
        "не должна вернуться"
    )


@pytest.mark.parametrize(
    "route_file, principal_ok_routes",
    [
        ("releases.py", frozenset()),
        ("runs.py", frozenset()),
        ("notifications.py", frozenset({
            "/sse-ticket",
            "/inbox/read-all",
            "/inbox/{notification_id}/read",
        })),
    ],
)
def test_invariant_guard_pass4_write_routes_guarded(
    route_file: str, principal_ok_routes: frozenset
) -> None:
    """COS-091/092, инвариант 4 (расширение): все write-хендлеры
    releases.py / runs.py / notifications.py несут deps-guard — in-body
    auth-решения унифицированы. Identity-scoped personal writes
    (principal_ok_routes) допускают require_principal вместо capability."""
    text = (ROUTES_DIR / route_file).read_text(encoding="utf-8")

    violations = _write_routes_without_capability(text, principal_ok_routes)
    assert not violations, (
        f"write-хендлеры {route_file} без deps-guard: "
        f"{', '.join(violations)} — in-body auth (COS-091/092) не должна "
        "вернуться"
    )


def _write_routes_without_capability(
    text: str, principal_ok_routes: frozenset = frozenset()
) -> list[str]:
    """Найти write-декорации маршрутов без deps-guard в сигнатуре.

    require_capability обязателен; для identity-scoped personal writes
    (principal_ok_routes) достаточно require_principal."""
    blocks = re.split(r"(?=@router\.(?:get|post|put|delete|patch)\()", text)
    violations: list[str] = []
    for b in blocks:
        m = re.match(r"@router\.(post|put|delete|patch)\(", b)
        if not m:
            continue
        def_pos = b.find("\ndef ", 1)
        sig = b[:def_pos] if def_pos != -1 else b
        if "require_capability(" in sig:
            continue
        route = re.search(r'@router\.\w+\("([^"]+)"', b)
        route_path = route.group(1) if route else "?"
        if route_path in principal_ok_routes and "require_principal(" in sig:
            continue
        violations.append(f"{m.group(1).upper()} {route_path}")
    return violations


def test_invariant_project_team_uses_resolve() -> None:
    """COS-086, инвариант 5: get_project_team якорится к резолв-контракту —
    видимость команды выводится из приложений проекта."""
    text = (ROUTES_DIR / "projects.py").read_text(encoding="utf-8")
    m = re.search(r"async def get_project_team\(.*?(?=\n@router|\n# ──|\Z)", text, re.S)
    assert m, "get_project_team исчез — якорь ProjectTeam не проверить"
    body = m.group(0)
    assert "resolve_caller_domain" in body, (
        "get_project_team потерял resolve_caller_domain — ProjectTeam "
        "выпал из единого резолв-контракта (COS-086)"
    )
    assert "_caller_domain_app_ids" in body, (
        "get_project_team потерял доменный якорь по приложениям проекта"
    )
