# -*- coding: utf-8 -*-
"""COS-155: PK-C-003.6 — SBOM-инвентарь cosmo-api (syft/grype vs python-inventory).

Требование PK-C-003.6 «SBOM in bundle, syft/grype»: для самой cosmo-api
собирается инвентарь зависимостей (Syft SBOM, CycloneDX 1.5) и уязвимостей
(Grype), запечатывается в ``evidence_ledger`` и читается по ``bundle_id``.

Генерация (в ``ledger/sbom_inventory.py``):
  - **syft** (CycloneDX) — если бинарник доступен, реальный скан дерева/
    контейнерных слоёв. Маркер ``generator: "syft"`` + имя/версия инструмента.
  - **python-inventory** — честный fallback: ``importlib.metadata`` (pip
    freeze-эквивалент установленных дистрибутивов). Маркер
    ``generator: "python-inventory"``. НИКОГДА не подделываем syft-подпись.

Грипе-визор:
  - CVE/severity список + summary (total/critical/high/medium/low);
  - grype отсутствует → ``vuln_summary.available=false`` + ``reason`` (честно,
    не фейковый пустой отчёт).

Инварианты (по образцу COS-138/142):
  - ``extra="ignore"`` на компонентах/уязвимостях (внешние инструменты дают
    более богатый формат; жёсткий ``forbid`` ломал бы легитимный вывод);
  - ``sbom_inventory_content_hash`` — канонический sha256 документа
    (sort_keys, compact) — якорь записи в evidence ledger.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Формат SBOM — CycloneDX 1.5 (единый контракт PK-C-003.6).
BOM_FORMAT = "CycloneDX"
SPEC_VERSION = "1.5"

#: Генераторы, которые честно фиксирует инвентарь.
PYTHON_INVENTORY_GENERATOR = "python-inventory"
SYFT_GENERATOR = "syft"

#: Severity после нормализации grype → закрытый набор.
SBOM_SEVERITIES = ("critical", "high", "medium", "low")

#: bundle_id уходит в content_ref и в URL-путь — без слэшей/пробелов.
_BUNDLE_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SbomInventoryError(ValueError):
    """Нарушение контракта SBOM-инвентаря."""


class SbomInventoryComponent(BaseModel):
    """Компонент (зависимость) инвентаря."""

    model_config = ConfigDict(extra="ignore")

    type: str = "library"
    name: str = Field(..., min_length=1)
    version: str = ""
    purl: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("component name must not be blank")
        return v


class SbomInventoryVulnerability(BaseModel):
    """Уязвимость из grype-отчёта (CVE/GHSA)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    severity: str
    package_name: str = ""
    installed_version: str = ""
    fixed_version: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _id_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("vulnerability id must not be blank")
        return v


class SbomVulnSummary(BaseModel):
    """Сводка уязвимостей. ``available=False`` — grype отсутствовал (честно)."""

    model_config = ConfigDict(extra="forbid")

    available: bool = True
    total: int = Field(default=0, ge=0)
    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    low: int = Field(default=0, ge=0)
    reason: str = ""


class SbomInventoryDocument(BaseModel):
    """CycloneDX-1.5-shaped SBOM-инвентарь + грипе-сводка.

    ``generator`` — честный маркер источника (``syft`` | ``python-inventory``);
    топ-уровневые ключи CycloneDX (``bomFormat``/``specVersion``/...) сериализуются
    с camelCase-алиасами — документ валиден как CycloneDX 1.5 JSON.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    bom_format: str = Field(BOM_FORMAT, alias="bomFormat")
    spec_version: str = Field(SPEC_VERSION, alias="specVersion")
    serial_number: str = Field(..., alias="serialNumber")
    version: int = 1
    generator: str
    tool_name: str = ""
    tool_version: str = ""
    metadata_component: dict[str, Any] = Field(
        default_factory=dict, alias="metadata",
    )
    components: list[SbomInventoryComponent] = Field(default_factory=list)
    vulnerabilities: list[SbomInventoryVulnerability] = Field(default_factory=list)
    vuln_summary: SbomVulnSummary = Field(
        default_factory=SbomVulnSummary, alias="vulnSummary",
    )


class SbomInventoryRequest(BaseModel):
    """Запрос генерации SBOM-инвентаря cosmo-api.

    ``run_id`` — якорь ledger-записи (``evidence_ledger.run_id`` NOT NULL FK на
    runs.id). ``target`` — опциональный путь для syft (пусто → корень
    репозитория); python-inventory работает из runtime и target не требует.
    """

    model_config = ConfigDict(extra="forbid")

    bundle_id: str = Field(..., min_length=1, max_length=128)
    run_id: str = Field(..., min_length=1, max_length=64)
    app_name: str = Field(default="cosmo-api", min_length=1, max_length=128)
    version: str = Field(default="", max_length=128)
    target: Optional[str] = None

    @field_validator("bundle_id")
    @classmethod
    def _bundle_id_safe(cls, v: str) -> str:
        if not _BUNDLE_ID_RE.match(v):
            raise ValueError(
                "bundle_id must match '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
            )
        return v


def sbom_inventory_content_hash(document: SbomInventoryDocument) -> str:
    """Канонический sha256 содержимого SBOM-документа (sort_keys, compact).

    Крипто-якорь ledger-записи — тот же приём, что ``sbom_content_hash``
    (COS-138) и ``manifest_content_hash`` (COS-142).
    """
    payload = json.dumps(
        document.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_severity(raw: str) -> str:
    """grype severity → закрытый набор {critical, high, medium, low}.

    ``Negligible``/``Unknown`` → ``low`` (не теряем, но не раздуваем контракт).
    """
    key = (raw or "").strip().lower()
    mapping = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "moderate": "medium",
        "low": "low",
        "negligible": "low",
        "unknown": "low",
    }
    return mapping.get(key, "low")


def python_inventory_components() -> list[SbomInventoryComponent]:
    """Честный runtime-инвентарь: ``importlib.metadata`` (pip freeze-эквивалент).

    Детерминированный порядок (по имени). Дистрибутивы без имени/версии
    пропускаются. Пустой результат честно пуст (не фейк).
    """
    import importlib.metadata as im

    out: list[SbomInventoryComponent] = []
    distributions = sorted(
        list(im.distributions()),
        key=lambda d: ((d.metadata.get("Name") or "").lower(), d.version or ""),
    )
    for dist in distributions:
        name = (dist.metadata.get("Name") or "").strip()
        version = (dist.version or "").strip()
        if not name:
            continue
        purl = f"pkg:pypi/{name.lower()}@{version}" if version else f"pkg:pypi/{name.lower()}"
        out.append(SbomInventoryComponent(name=name, version=version, purl=purl))
    return out


def parse_grype_report(
    report: dict[str, Any],
) -> tuple[list[SbomInventoryVulnerability], SbomVulnSummary]:
    """Разобрать grype JSON (``matches[]``) → уязвимости + сводка severity.

    Пустой/невалидный отчёт → пустой список и ``available=True`` (грify
    отработал, но ничего не нашёл) — в отличие от «grype отсутствует», где
    ``available=False`` (см. ``ledger/sbom_inventory.py``).
    """
    vulns: list[SbomInventoryVulnerability] = []
    for match in (report.get("matches") or []):
        vuln = match.get("vulnerability") or {}
        vid = (vuln.get("id") or "").strip()
        if not vid:
            continue
        artifact = match.get("artifact") or {}
        fix_versions = ((vuln.get("fix") or {}).get("versions")) or []
        vulns.append(SbomInventoryVulnerability(
            id=vid,
            severity=normalize_severity(str(vuln.get("severity") or "")),
            package_name=str(artifact.get("name") or ""),
            installed_version=str(artifact.get("version") or ""),
            fixed_version=fix_versions[0] if fix_versions else None,
        ))
    counts = {s: 0 for s in SBOM_SEVERITIES}
    for v in vulns:
        if v.severity in counts:
            counts[v.severity] += 1
    summary = SbomVulnSummary(
        available=True,
        total=len(vulns),
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
    )
    return vulns, summary