# -*- coding: utf-8 -*-
"""COS-157: self-managed credential hashing (PBKDF2-HMAC-SHA256).

Боевой self-managed логин проверяет пароль против хэша, хранимого в OpenBao
``secret/cosmo/auth`` (OpenBao-seeded admin — решение PO от 2026-09-24). Сам
пароль нигде не хранится в открытом виде.

Формат хэша — self-describing (Django-стиль), чтобы ротация параметров KDF
проходила без миграции существующих записей:
    ``pbkdf2_sha256$<iterations>$<salt_b64url>$<hash_b64url>``

KDF — PBKDF2-HMAC-SHA256 через stdlib ``hashlib`` (без новой зависимости;
``cryptography>=42`` для JWT-подписи уже в requirements).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000  # OWASP 2023 для PBKDF2-SHA256
SALT_BYTES = 16
HASH_BYTES = 32


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded)


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    """Сформировать self-describing хэш пароля.

    ``salt``/``iterations`` инъектируются для тестов (скорость) и для
    детерминированной генерации dev-bootstrap'а.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    salt = salt if salt is not None else os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Проверить пароль против сохранённого self-describing хэша (constant-time)."""
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        algo, iterations_s, salt_b64, hash_b64 = encoded.split("$")
    except ValueError:
        return False
    if algo != ALGORITHM:
        return False
    try:
        iterations = int(iterations_s)
        salt = _unb64url(salt_b64)
        expected = _unb64url(hash_b64)
    except (ValueError, TypeError):
        return False
    if iterations < 1:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)