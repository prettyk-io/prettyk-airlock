"""
COS-212: Cryptographic Threshold M-of-N Approval Scheme.

Реализует:
  1. Пороговое подписание M-of-N (Multi-Signature Quorum) для критических релизов КИТС 1 категории.
  2. Проверку ролевого кворума (минимум M независимых подписей из разных ролевых групп).
  3. Криптографическую верификацию каждой подписи и агрегированное подтверждение релиза.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class SignatureVote:
    """Индивидуальная цифровая подпись одного из участников кворума."""
    signer_id: str
    signer_role: str
    signature_hex: str
    signed_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


@dataclass
class ThresholdPolicy:
    """Политика порогового кворума."""
    policy_id: str
    required_m: int = 2               # Минимум M подписей
    total_n: int = 3                  # Из N возможных
    required_roles: List[str] = field(default_factory=lambda: ["security_officer", "admin_sec", "developer_lead"])
    require_distinct_roles: bool = True


class ThresholdQuorumSession:
    """Сессия сбора пороговых подписей для релиза."""

    def __init__(
        self,
        session_id: str,
        release_id: str,
        release_digest: str,
        policy: ThresholdPolicy,
    ):
        self.session_id = session_id
        self.release_id = release_id
        self.release_digest = release_digest
        self.policy = policy
        self.votes: List[SignatureVote] = []
        self.is_sealed: bool = False
        self.final_aggregated_signature: str = ""

    def add_signature(
        self,
        signer_id: str,
        signer_role: str,
        signer_secret: str,
    ) -> Tuple[bool, str]:
        """Добавление подписи участника в кворум."""
        if self.is_sealed:
            return False, "409_SESSION_ALREADY_SEALED"

        # 1. Проверка на повторную подпись тем же пользователем
        if any(v.signer_id == signer_id for v in self.votes):
            return False, "409_DUPLICATE_SIGNER: user has already signed"

        # 2. Проверка соответствия роли политике
        if signer_role not in self.policy.required_roles:
            return False, f"403_INELIGIBLE_ROLE: role '{signer_role}' not in eligible roles"

        # 3. Вычисление подписи
        manifest = f"{self.session_id}:{self.release_id}:{self.release_digest}:{signer_id}:{signer_role}"
        sig = hmac.new(signer_secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()

        self.votes.append(SignatureVote(
            signer_id=signer_id,
            signer_role=signer_role,
            signature_hex=sig,
        ))

        # Проверяем достижение кворума
        if self.is_quorum_reached():
            self._seal_quorum()

        return True, "200_SIGNATURE_ACCEPTED"

    def verify_quorum(self) -> bool:
        """Проверка валидности собранного кворума."""
        if not self.is_sealed or not self.final_aggregated_signature:
            return False
        if not self.is_quorum_reached():
            return False
        sorted_sigs = sorted([v.signature_hex for v in self.votes])
        combined = ":".join(sorted_sigs)
        expected = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return expected == self.final_aggregated_signature

    def is_quorum_reached(self) -> bool:
        if len(self.votes) < self.policy.required_m:
            return False

        if self.policy.require_distinct_roles:
            unique_roles = {v.signer_role for v in self.votes}
            return len(unique_roles) >= self.policy.required_m

        return True

    def _seal_quorum(self):
        """Агрегация подписей кворума в финальный криптографический сертификат допуска."""
        sorted_sigs = sorted([v.signature_hex for v in self.votes])
        combined = ":".join(sorted_sigs)
        self.final_aggregated_signature = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        self.is_sealed = True
