"""
BRG-003: Т1-Сфера Capability Probe — capability matrix.

Цель: определить реальную поддержку OCI/Docker Registry V2 в Т1-Сфере
по официальной документации, demo/trial или разрешённому доступу.

Не заявлять готовую интеграцию до проверки. Без fake-реализации.
Никакого копирования или несанкционированного извлечения продукта.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CapabilityStatus(str, Enum):
    """Статус возможности."""
    CONFIRMED = "confirmed"       # проверено на живом инстансе
    DOCUMENTED = "documented"     # заявлено в документации, не проверено
    NOT_SUPPORTED = "not_supported"  # документально не поддерживается
    UNKNOWN = "unknown"           # не удалось определить
    BLOCKED = "blocked"           # нет доступа к инстансу/документации


@dataclass
class CapabilityEntry:
    """Одна строка capability matrix."""
    capability: str
    status: CapabilityStatus
    notes: str = ""
    doc_reference: str = ""
    tested_version: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# T1-Сфера Capability Matrix
# ══════════════════════════════════════════════════════════════════════════════

T1_SFERA_CAPABILITY_MATRIX: List[CapabilityEntry] = [
    # ── Core: OCI/Docker Registry V2 ─────────────────────────────────────
    CapabilityEntry(
        capability="OCI Distribution Spec v1.1 (Docker Registry HTTP API V2)",
        status=CapabilityStatus.UNKNOWN,
        notes="Ключевой вопрос. Если Сфера реализует OCI V2, отдельный adapter не нужен — "
              "используется общий OciRegistry из BRG-002. Если API проприетарный — пишется "
              "тонкий REST adapter по официальной документации.",
    ),
    CapabilityEntry(
        capability="OCI Image Manifest v2 (schemaVersion 2)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="OCI Content Descriptors (digest, mediaType, size)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="Multi-arch manifests (manifest list / image index)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── Push / Pull ─────────────────────────────────────────────────────
    CapabilityEntry(
        capability="docker push / docker pull (docker CLI)",
        status=CapabilityStatus.UNKNOWN,
        notes="Минимальное требование: docker pull/push через docker CLI.",
    ),
    CapabilityEntry(
        capability="skopeo copy (OCI → OCI, без Docker daemon)",
        status=CapabilityStatus.UNKNOWN,
        notes="Нужно для airgap-зеркалирования (mirror-oci-registry.sh).",
    ),
    CapabilityEntry(
        capability="helm push OCI (helm chart как OCI artifact)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="oras push/pull (generic OCI artifacts — SBOM, signatures)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── Authentication ──────────────────────────────────────────────────
    CapabilityEntry(
        capability="Basic Auth (robot account / service account)",
        status=CapabilityStatus.UNKNOWN,
        notes="Нужен service account для CI/CD pipeline.",
    ),
    CapabilityEntry(
        capability="Bearer Token Auth (OAuth2 / JWT)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="LDAP / Active Directory integration",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="RBAC (role-based access: push/pull/admin per repository)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── TLS / Security ──────────────────────────────────────────────────
    CapabilityEntry(
        capability="TLS 1.3 with custom CA certificates",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="mTLS (mutual TLS — client certificate authentication)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="Content Trust / Notary (Docker Content Trust)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── Airgap ──────────────────────────────────────────────────────────
    CapabilityEntry(
        capability="Offline/airgap deployment (no external internet dependency)",
        status=CapabilityStatus.UNKNOWN,
        notes="Критично для ЗПЭ и закрытого контура ЦБ.",
    ),
    CapabilityEntry(
        capability="Registry mirror / proxy cache (pull-through cache for external registries)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="Group repositories (virtual repository aggregation)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── Webhooks ────────────────────────────────────────────────────────
    CapabilityEntry(
        capability="Webhook notifications (push events, delete events)",
        status=CapabilityStatus.UNKNOWN,
        notes="Нужно для автоматического триггера Cosmo pipeline при push артефакта.",
    ),

    # ── SBOM ───────────────────────────────────────────────────────────
    CapabilityEntry(
        capability="Attached SBOM (CycloneDX or SPDX as OCI artifact)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="SBOM generation (built-in, без внешних инструментов)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── Signatures / Attestations ──────────────────────────────────────
    CapabilityEntry(
        capability="Cosign signature support (sigstore/cosign)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="in-toto attestations (SLSA provenance)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="ГОСТ-подпись (ГОСТ Р 34.10-2012 / 34.11-2012)",
        status=CapabilityStatus.UNKNOWN,
        notes="Приоритет для ЦБ РФ.",
    ),

    # ── Staging / Promotion ────────────────────────────────────────────
    CapabilityEntry(
        capability="Staging repository (pre-release artifacts before promotion)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="Artifact promotion (ЗР → ЗТ → ЗПЭ via API or UI)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="Retention policies (cleanup by age, count, regex)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="Quota per repository / namespace",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── REST API ───────────────────────────────────────────────────────
    CapabilityEntry(
        capability="REST API (CRUD repositories, users, permissions, artifacts)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="OpenAPI / Swagger specification for REST API",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="API tokens (personal access tokens / robot tokens)",
        status=CapabilityStatus.UNKNOWN,
    ),

    # ── High Availability ──────────────────────────────────────────────
    CapabilityEntry(
        capability="High Availability mode (multi-node, active/active or active/passive)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="S3-compatible storage backend (MinIO, Ceph, local FS)",
        status=CapabilityStatus.UNKNOWN,
    ),
    CapabilityEntry(
        capability="PostgreSQL backend (metadata storage)",
        status=CapabilityStatus.UNKNOWN,
    ),
]


def get_capability_summary() -> Dict[str, int]:
    """Сводка по статусам проверки."""
    summary: Dict[str, int] = {}
    for entry in T1_SFERA_CAPABILITY_MATRIX:
        summary[entry.status.value] = summary.get(entry.status.value, 0) + 1
    return summary


def is_oci_v2_confirmed() -> bool:
    """Поддерживает ли Т1-Сфера OCI/Docker Registry V2 по матрице?"""
    for entry in T1_SFERA_CAPABILITY_MATRIX:
        if "OCI Distribution" in entry.capability and entry.status == CapabilityStatus.CONFIRMED:
            return True
    return False


def generate_capability_report() -> str:
    """Markdown-отчёт по capability matrix."""
    from io import StringIO
    buf = StringIO()
    buf.write("# Т1-Сфера: Capability Probe Report (BRG-003)\n\n")
    buf.write(f"**Дата:** 2026-08-30\n\n")
    buf.write("## Сводка\n\n")
    summary = get_capability_summary()
    buf.write("| Статус | Количество |\n")
    buf.write("|--------|-----------|\n")
    for status, count in sorted(summary.items()):
        buf.write(f"| {status} | {count} |\n")
    buf.write("\n## Детальная матрица\n\n")
    buf.write("| # | Возможность | Статус | Примечание |\n")
    buf.write("|---|------------|--------|----------|\n")
    for i, entry in enumerate(T1_SFERA_CAPABILITY_MATRIX, 1):
        status_icon = {
            CapabilityStatus.CONFIRMED: "✅",
            CapabilityStatus.DOCUMENTED: "📄",
            CapabilityStatus.NOT_SUPPORTED: "❌",
            CapabilityStatus.UNKNOWN: "❓",
            CapabilityStatus.BLOCKED: "🔒",
        }.get(entry.status, "❓")
        buf.write(f"| {i} | {entry.capability} | {status_icon} {entry.status.value} | {entry.notes} |\n")
    return buf.getvalue()


if __name__ == "__main__":
    print(generate_capability_report())