# -*- coding: utf-8 -*-
"""COS-099: SBOM & vulnerability report for release packages.

Генерация машиночитаемого SBOM (CycloneDX 1.5 — единый SBOM-контракт
build_modes) из дерева репозитория и артефактов сборки, отчёт уязвимостей
grype (offline), digest pinning в манифест пакета.

Airgap-канон:
  - syft/grype — опциональные внешние инструменты. Нет бинарника/базы →
    честный fallback (internal parser / source="none"), НИКОГДА фейковый
    отчёт и НИКАКИХ сетевых вызовов (GRYPE_DB_AUTO_UPDATE=false).
  - Digest pinning: sha256 SBOM/отчёта фиксируется в manifest["security"],
    manifest покрыт детерминированным PackageRevision.checksum —
    модификация манифеста ловится существующим checksum-контролем.
  - Тамper против payload-байтов: PreTransferValidator.validate_with_artifacts
    (source-side) и LandingStateMachine.receive_and_verify (target-side)
    пересчитывают sha256 фактических байтов против pinned digest.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.cosmo.transfer.builder import PackageBuilder
from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    TransferItem,
)

Runner = Callable[..., Any]  # subprocess.run-совместимый (инъекция в тестах)

# Prune-список обхода дерева (не проваливаться внутрь)
_PRUNE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".tox", "target",
}
_MAX_DEPTH = 6
_MAX_FILES = 500


# ══════════════════════════════════════════════════════════════════
# Pins — digest pinning в манифесте
# ══════════════════════════════════════════════════════════════════

class SBOMPin(BaseModel):
    """Pinned SBOM: формат, источник, payload ref, sha256."""
    model_config = ConfigDict(extra="ignore")
    format: str = "cyclonedx"
    source: str = "internal"                  # syft | internal
    tool_version: str = ""
    ref: str = "sbom/cdx.json"
    sha256: str = Field(..., min_length=64, max_length=64)


class VulnReportPin(BaseModel):
    """Pinned vulnerability report. source="none" — инструмент недоступен
    (честный маркер, ref/sha256 пустые; отсутствие отчёта не скрывается)."""
    model_config = ConfigDict(extra="ignore")
    source: str = "none"                      # grype | none
    tool_version: str = ""
    ref: str = ""
    sha256: str = ""
    reason: str = ""                          # почему недоступен (для аудита)


class SecuritySection(BaseModel):
    """security-секция манифеста пакета."""
    model_config = ConfigDict(extra="ignore")
    sbom: SBOMPin
    vulnerability_report: Optional[VulnReportPin] = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    """Детерминированная сериализация для digest pinning."""
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def extract_security(manifest: dict[str, Any]) -> Optional[SecuritySection]:
    """Прочитать security-секцию манифеста (None если не pinned)."""
    raw = manifest.get("security")
    if not isinstance(raw, dict) or not raw.get("sbom"):
        return None
    try:
        return SecuritySection.model_validate(raw)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
# SBOM generation: syft wrapper + internal fallback
# ══════════════════════════════════════════════════════════════════

class SBOMResult:
    """Результат генерации SBOM: документ + происхождение + digest."""

    def __init__(self, document: dict[str, Any], source: str,
                 tool_version: str = "", warnings: list[str] | None = None):
        self.document = document
        self.source = source                    # syft | internal
        self.tool_version = tool_version
        self.warnings = warnings or []

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.document))

    def pin(self, ref: str = "sbom/cdx.json") -> SBOMPin:
        return SBOMPin(source=self.source, tool_version=self.tool_version,
                       ref=ref, sha256=self.sha256)


def generate_sbom(
    target: str | os.PathLike[str],
    *,
    app_id: str = "",
    version: str = "1.0.0",
    syft_path: Optional[str] = None,
    runner: Optional[Runner] = None,
    timeout: int = 300,
) -> SBOMResult:
    """Сгенерировать CycloneDX SBOM для дерева/артефакта.

    Порядок: syft CLI (если доступен) → internal dependency parser.
    Ошибки syft (нет бинарника, timeout, non-zero) → fallback с warning.
    """
    run = runner or subprocess.run
    exe = syft_path or shutil.which("syft")
    if exe is None and runner is not None:
        # Инъекция runner'а: резолв бинарника делегирован runner'у (тесты).
        exe = "syft"
    if exe:
        try:
            proc = run(
                [exe, str(target), "-o", "cyclonedx-json"],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                doc = json.loads(proc.stdout)
                if isinstance(doc, dict) and doc.get("bomFormat") == "CycloneDX":
                    return SBOMResult(doc, source="syft")
            # non-zero / невалидный вывод — честный fallback
            tail = (proc.stderr or proc.stdout or "")[-200:]
            return _internal_sbom(target, app_id=app_id, version=version,
                                  warnings=[f"syft failed (rc={proc.returncode}): {tail}"])
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            return _internal_sbom(target, app_id=app_id, version=version,
                                  warnings=[f"syft unavailable: {exc}"])
    return _internal_sbom(target, app_id=app_id, version=version,
                          warnings=["syft binary not found; internal parser used"])


# ── Internal dependency parser (airgap fallback) ──


def _purl(ecosystem: str, name: str, version: str) -> str:
    return f"pkg:{ecosystem}/{name}@{version}" if version else f"pkg:{ecosystem}/{name}"


def _parse_requirements(path: Path) -> list[tuple[str, str, str]]:
    """requirements*.txt → [(ecosystem, name, version)] без комментариев."""
    out: list[tuple[str, str, str]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            for sep in ("==", ">=", "~=", "<=", ">", "<", "!="):
                if sep in line:
                    name, ver = line.split(sep, 1)
                    name = name.strip().lower()
                    ver = ver.strip().rstrip(",;") or ""
                    if name and ver:
                        out.append(("pypi", name, ver))
                    break
    except OSError:
        pass
    return out


def _parse_pyproject(path: Path) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    try:
        import tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out
    for dep in (data.get("project", {}) or {}).get("dependencies", []) or []:
        if isinstance(dep, str) and dep.strip():
            name = dep.split(";", 1)[0]
            for sep in ("==", ">=", "~=", "<=", ">", "<", "!="):
                if sep in name:
                    n, v = name.split(sep, 1)
                    n = n.strip().strip('"').lower()
                    v = v.strip().strip('"').split(",")[0]
                    if n and v:
                        out.append(("pypi", n, v))
                    break
    poetry = ((data.get("tool", {}) or {}).get("poetry", {}) or {}).get("dependencies", {}) or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            continue
        if isinstance(spec, str) and spec:
            v = spec.lstrip("^~>=<").split(",")[0].strip()
            out.append(("pypi", name.lower(), v))
    return out


def _parse_package_json(path: Path) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out
    for section in ("dependencies", "devDependencies"):
        for name, ver in ((data.get(section, {}) or {}).items()):
            v = str(ver).lstrip("^~>=< ").split(" ")[0]
            out.append(("npm", str(name).lower(), v))
    return out


_PARSERS = {
    "requirements.txt": _parse_requirements,
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
}


def _collect_components(target: Path) -> list[dict[str, Any]]:
    """Собрать components из dependency-манифестов дерева (детерминированно)."""
    if target.is_file():
        parser = _PARSERS.get(target.name)
        found = parser(target) if parser else []
        return _components_from(found)

    deps: list[tuple[str, str, str]] = []
    seen = 0
    for root, dirs, files in os.walk(target):
        depth = Path(root).resolve().as_posix().count("/") - \
            target.resolve().as_posix().count("/")
        if depth >= _MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in _PRUNE_DIRS)
        for fname in sorted(files):
            if fname in _PARSERS:
                seen += 1
                if seen > _MAX_FILES:
                    break
                p = Path(root) / fname
                key = "requirements.txt" if fname.startswith("requirements") else fname
                deps.extend(_PARSERS[key](p))

    # Дедуп: (ecosystem, name) → последняя версия
    uniq: dict[tuple[str, str], str] = {}
    for eco, name, ver in deps:
        uniq[(eco, name)] = ver
    ordered = sorted(((eco, name, ver) for (eco, name), ver in uniq.items()),
                     key=lambda t: (t[0], t[1], t[2]))
    return _components_from(ordered)


def _components_from(deps: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    return [
        {"type": "library", "name": name, "version": ver,
         "purl": _purl(eco, name, ver)}
        for (eco, name, ver) in deps
        if name and ver
    ]


def _internal_sbom(target: str | os.PathLike[str], *, app_id: str,
                   version: str, warnings: list[str]) -> SBOMResult:
    target_path = Path(target)
    name = app_id or target_path.name or "unknown"
    components = _collect_components(target_path)
    content_hash = hashlib.sha256(
        canonical_json_bytes({"name": name, "version": version,
                              "components": components})
    ).hexdigest()
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{content_hash[:32]}",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": name, "version": version},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [{"vendor": "PrettyK", "name": "cosmoport-internal-parser"}],
        },
        "components": components,
    }
    return SBOMResult(document, source="internal", warnings=warnings)


# ══════════════════════════════════════════════════════════════════
# Vulnerability report: grype (offline)
# ══════════════════════════════════════════════════════════════════

class VulnReportResult:
    """Результат grype-сканирования. source="none" — честно, не фейк."""

    def __init__(self, report: dict[str, Any], source: str,
                 tool_version: str = "", reason: str = "",
                 warnings: list[str] | None = None):
        self.report = report
        self.source = source                    # grype | none
        self.tool_version = tool_version
        self.reason = reason
        self.warnings = warnings or []

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.report))

    def pin(self, ref: str = "sbom/grype.json") -> VulnReportPin:
        if self.source == "grype":
            return VulnReportPin(source=self.source, tool_version=self.tool_version,
                                 ref=ref, sha256=self.sha256)
        return VulnReportPin(source="none", reason=self.reason)


_GRYPE_ENV = {
    # Airgap-канон: никаких автообновлений/сети, возраст offline-снапшота
    # не проверяется (снапшот может быть старше max-allowed-age).
    "GRYPE_DB_AUTO_UPDATE": "false",
    "GRYPE_DB_VALIDATE_AGE": "false",
}


def generate_vuln_report(
    sbom_document: dict[str, Any],
    *,
    grype_path: Optional[str] = None,
    db_dir: Optional[str] = None,
    runner: Optional[Runner] = None,
    timeout: int = 600,
) -> VulnReportResult:
    """Прогнать SBOM через grype (offline DB snapshot). Никакой сети:
    GRYPE_DB_AUTO_UPDATE=false. Нет инструмента/базы → source="none" с reason.
    """
    run = runner or subprocess.run
    exe = grype_path or shutil.which("grype")
    if exe is None and runner is not None:
        # Инъекция runner'а: резолв бинарника делегирован runner'у (тесты).
        exe = "grype"
    if not exe:
        return VulnReportResult(
            {"status": "unavailable", "tool": "grype",
             "reason": "grype binary not found"},
            source="none", reason="grype binary not found")

    env = dict(os.environ)
    env.update(_GRYPE_ENV)
    if db_dir:
        env["GRYPE_DB_CACHE_DIR"] = db_dir

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".cdx.json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(sbom_document, fh, ensure_ascii=False)
            tmp = fh.name
        proc = run(
            [exe, f"sbom:{tmp}", "-o", "json"],
            capture_output=True, text=True, timeout=timeout, check=False,
            env=env,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            doc = json.loads(proc.stdout)
            if isinstance(doc, dict):
                return VulnReportResult(doc, source="grype")
        tail = (proc.stderr or proc.stdout or "")[-200:]
        return VulnReportResult(
            {"status": "unavailable", "tool": "grype", "reason": tail},
            source="none", reason=f"grype failed (rc={proc.returncode}): {tail}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return VulnReportResult(
            {"status": "unavailable", "tool": "grype", "reason": str(exc)},
            source="none", reason=f"grype unavailable: {exc}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ══════════════════════════════════════════════════════════════════
# Facade: сборка пакета с pinned SBOM
# ══════════════════════════════════════════════════════════════════

SBOM_REF = "sbom/cdx.json"
VULN_REF = "sbom/grype.json"


def build_secured_package(
    item_id: str,
    release_id: str,
    plan_id: str,
    target: str | os.PathLike[str],
    *,
    app_id: str = "",
    version: str = "1.0.0",
    source_ref: str = "",
    target_ref: str = "",
    sbom_ref: str = SBOM_REF,
    syft_path: Optional[str] = None,
    grype_path: Optional[str] = None,
    grype_db_dir: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> tuple[TransferItem, SBOMResult, VulnReportResult]:
    """Собрать TransferItem с pinned SBOM (+vuln report при наличии grype).

    SBOM входит в payload_refs и в security-секцию манифеста; манифест
    покрыт PackageRevision checksum → digest tamper-evident.
    """
    sbom = generate_sbom(target, app_id=app_id, version=version,
                         syft_path=syft_path, runner=runner)
    vuln = generate_vuln_report(sbom.document, grype_path=grype_path,
                                db_dir=grype_db_dir, runner=runner)
    security = SecuritySection(
        sbom=sbom.pin(ref=sbom_ref),
        vulnerability_report=vuln.pin(ref=VULN_REF),
    )
    item = PackageBuilder.build_item(
        item_id=item_id,
        release_id=release_id,
        plan_id=plan_id,
        artifact_plane=ArtifactPlane.SBOM,
        package_mode=PackageMode.FULL_PACKAGE,
        payload_refs=[sbom_ref],
        source_ref=source_ref,
        target_ref=target_ref,
        security=security,
    )
    return item, sbom, vuln


def envelope_artifacts_from_security(
    security: SecuritySection,
    payload_bytes: dict[str, bytes],
) -> list[dict[str, Any]]:
    """Envelope-записи для security payload'ов (для seal_envelope(artifacts=...)).

    Совместимо с COS-126 AirgapReleaseBundle: import_and_verify пересчитает
    sha256 фактических байтов против этих дайджестов.
    """
    from orchestrator.cosmo.ledger.release_envelope import EnvelopeArtifactDigest

    out: list[dict[str, Any]] = []
    if security.sbom.ref in payload_bytes:
        data = payload_bytes[security.sbom.ref]
        out.append(EnvelopeArtifactDigest(
            name=security.sbom.ref, artifact_type="sbom",
            sha256=sha256_hex(data), size_bytes=len(data),
        ).to_dict())
    vr = security.vulnerability_report
    if vr and vr.ref and vr.ref in payload_bytes:
        data = payload_bytes[vr.ref]
        out.append(EnvelopeArtifactDigest(
            name=vr.ref, artifact_type="vulnerability_report",
            sha256=sha256_hex(data), size_bytes=len(data),
        ).to_dict())
    return out
