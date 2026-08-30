"""
OWN-BUDDY-001: Registry Health & GAP Mode Audit Trail.

GAP mode = closed network, no external registry access.
Every registry operation (push/pull/health) hashed into Evidence chain.
Evidence: immutable SHA-256 log for auditor verification.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RegistryOperation:
    """Одна операция с registry, записанная в audit trail."""
    operation_id: str
    operation_type: str              # push / pull / manifest / health / promote
    registry_provider: str           # local-oci / nexus / t1_sfera
    registry_zone: str               # zr / zt / zpe
    registry_endpoint: str
    image_name: str
    image_tag: Optional[str] = None
    image_digest: Optional[str] = None
    status: str = "success"          # success / failed / blocked
    error: Optional[str] = None
    operator_id: str = "system"
    duration_ms: float = 0.0
    gap_mode: bool = False           # GAP: no external registry access
    gitea_commit_sha: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


@dataclass
class EvidenceEntry:
    """Одна запись в неизменяемой цепочке доказательств SHA-256."""
    entry_id: str
    prev_hash: str
    operation_hash: str
    chain_hash: str
    operation: RegistryOperation
    timestamp: str


class RegistryAuditTrail:
    """
    OWN-BUDDY-001: Неизменяемый журнал операций с Artifact Registry.

    Каждая операция создаёт Evidence запись с SHA-256 хешем,
    связывающим её с предыдущей записью в цепочке.
    """

    def __init__(self) -> None:
        self._entries: List[EvidenceEntry] = []
        self._prev_hash: str = "0000000000000000000000000000000000000000000000000000000000000000"

    def record_operation(self, op: RegistryOperation) -> EvidenceEntry:
        """Записать операцию в audit trail и вернуть evidence entry."""
        op_hash = self._hash_operation(op)
        chain_data = f"{self._prev_hash}:{op_hash}"
        chain_hash = hashlib.sha256(chain_data.encode()).hexdigest()

        entry = EvidenceEntry(
            entry_id=f"reg-ev-{len(self._entries) + 1:04d}",
            prev_hash=self._prev_hash,
            operation_hash=op_hash,
            chain_hash=chain_hash,
            operation=op,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

        self._entries.append(entry)
        self._prev_hash = chain_hash
        return entry

    def verify_chain(self) -> bool:
        """Проверить целостность всей цепочки доказательств."""
        expected = "0000000000000000000000000000000000000000000000000000000000000000"
        for entry in self._entries:
            if entry.prev_hash != expected:
                return False
            chain_data = f"{entry.prev_hash}:{entry.operation_hash}"
            expected = hashlib.sha256(chain_data.encode()).hexdigest()
            if expected != entry.chain_hash:
                return False
        return True

    def generate_gap_audit_report(self) -> Dict[str, Any]:
        """Сгенерировать GAP mode аудиторский отчёт."""
        gap_ops = [e for e in self._entries if e.operation.gap_mode]
        total_ops = len(self._entries)
        push_count = sum(1 for e in self._entries if e.operation.operation_type == "push")
        pull_count = sum(1 for e in self._entries if e.operation.operation_type == "pull")
        failed_ops = [e for e in self._entries if e.operation.status == "failed"]

        return {
            "report_id": f"gap-audit-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            "chain_verified": self.verify_chain(),
            "total_operations": total_ops,
            "gap_mode_operations": len(gap_ops),
            "pushes": push_count,
            "pulls": pull_count,
            "failed_operations": len(failed_ops),
            "failed_details": [
                {"operation_id": e.operation.operation_id, "error": e.operation.error}
                for e in failed_ops
            ],
            "external_registry_access": "NONE" if gap_ops else "NOT_APPLICABLE",
            "digest_based_pulls": sum(
                1 for e in self._entries
                if e.operation.operation_type == "pull" and e.operation.image_digest
            ),
            "mutable_tag_pulls": sum(
                1 for e in self._entries
                if e.operation.operation_type == "pull" and not e.operation.image_digest
            ),
            "providers_used": list(set(e.operation.registry_provider for e in self._entries)),
            "zones_accessed": list(set(e.operation.registry_zone for e in self._entries)),
            "entries": [
                {
                    "entry_id": e.entry_id,
                    "chain_hash": e.chain_hash[:16] + "...",
                    "operation": e.operation.operation_type,
                    "status": e.operation.status,
                    "gap_mode": e.operation.gap_mode,
                }
                for e in self._entries
            ],
        }

    @staticmethod
    def _hash_operation(op: RegistryOperation) -> str:
        data = json.dumps({
            "operation_id": op.operation_id,
            "type": op.operation_type,
            "provider": op.registry_provider,
            "zone": op.registry_zone,
            "image": op.image_name,
            "digest": op.image_digest,
            "status": op.status,
            "gap_mode": op.gap_mode,
            "timestamp": op.timestamp,
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    def get_chain_root(self) -> str:
        """Текущий root хеш цепочки (для внешней верификации)."""
        return self._prev_hash


# ── GAP Mode policy enforcement ──────────────────────────────────────────────

class GapModePolicy:
    """
    GAP mode: closed network, no external registry pull.
    
    - push — разрешён в локальный registry
    - pull — только из ЗР/ЗТ локального registry
    - external proxy/mirror — запрещён
    - внешние registries (docker.io, ghcr.io, quay.io) — заблокированы
    """

    ALLOWED_PROVIDERS_GAP = {"local-oci"}
    BLOCKED_EXTERNAL = {"docker.io", "ghcr.io", "quay.io", "gcr.io", "registry-1.docker.io"}

    @classmethod
    def is_allowed_operation(
        cls,
        operation_type: str,
        provider: str,
        endpoint: str,
    ) -> tuple[bool, str]:
        """
        Проверить, разрешена ли операция в GAP режиме.
        
        Returns:
            (allowed, reason)
        """
        # Проверка внешних registries
        for blocked in cls.BLOCKED_EXTERNAL:
            if blocked in endpoint:
                return False, f"GAP: external registry blocked ({blocked})"

        # Проверка провайдера
        if provider not in cls.ALLOWED_PROVIDERS_GAP:
            return False, f"GAP: provider '{provider}' not allowed (only local-oci)"

        # В GAP режиме разрешены push/pull только в локальный registry
        if operation_type not in ("push", "pull", "manifest", "health"):
            return False, f"GAP: operation '{operation_type}' not allowed in GAP mode"

        return True, "GAP: allowed"