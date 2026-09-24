# -*- coding: utf-8 -*-
"""COS-157: unit-тесты credential hashing (PBKDF2-HMAC-SHA256)."""
from __future__ import annotations

import pytest

from orchestrator.cosmo.security.credentials import hash_password, verify_password


def test_hash_verify_roundtrip():
    h = hash_password("s3cret-password", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert verify_password("s3cret-password", h) is True


def test_wrong_password_rejected():
    h = hash_password("correct", iterations=1000)
    assert verify_password("wrong", h) is False


def test_salt_is_random_by_default():
    h1 = hash_password("same", iterations=1000)
    h2 = hash_password("same", iterations=1000)
    assert h1 != h2  # разный salt → разный хэш


def test_format_self_describes_iterations():
    h = hash_password("pw", iterations=5000)
    assert h.split("$")[1] == "5000"
    assert verify_password("pw", h) is True


def test_invalid_or_tampered_hash_rejected():
    assert verify_password("pw", "not-a-hash") is False
    h = hash_password("pw", iterations=1000)
    parts = h.split("$")
    parts[-1] = "A" * len(parts[-1])
    assert verify_password("pw", "$".join(parts)) is False


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")