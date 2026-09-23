# -*- coding: utf-8 -*-
"""COS-156: тестовый RS256 keypair и помощники минтинга JWT.

Это **тестовая фикстура** (НЕ боевой ключ). Приватный ключ лежит здесь только
для подписи токенов в тестах; публичный — для ``COSMO_JWT_DEV_PUBLIC_KEY``.

Используется:
  - ``test_jwt_verification.py`` (unit verifier),
  - ``test_sanitary_rbac.py`` / ``test_surface_auth_regression.py`` (positive auth).

Ключ RSA-2048 сгенерирован одноразово; детерминирован, чтобы тесты были
стабильны между прогонами.
"""
from __future__ import annotations

import base64
import json
from typing import Any

TEST_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA8gV++/6CGWM6vDX9MGnr
h1MVl0gEvk1hvEgGFuChzgteIXcV0VP5cQ7so2Ubw3/WThtzQe+e3IsLwoPrAxJP
PLr4NSyCPKTDsKk9lgsUh5NxIRZ3SKPuINj5zOUE/hfV0iVALRYBPJBzF8hXL9ct
ZyvN2sX3qqZegG4WSdGcEjyhuh06X92Y2qSGvTxptjSQAlE2AmzqsnInUcBbYbs5
eYVgffwkWmghojbTCILkMAoTwt0LOpBBf6SElwIpnxA6CUMHh8MHArrKgWstGcwf
7eFO8QXsd+3BJKtc4KZgMyawsRFsTlsaY5w1FNbsaFGe2IyVhO3GnCCNpCieuLwa
jwIDAQAB
-----END PUBLIC KEY-----
"""

_TEST_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDyBX77/oIZYzq8
Nf0waeuHUxWXSAS+TWG8SAYW4KHOC14hdxXRU/lxDuyjZRvDf9ZOG3NB757ciwvC
g+sDEk88uvg1LII8pMOwqT2WCxSHk3EhFndIo+4g2PnM5QT+F9XSJUAtFgE8kHMX
yFcv1y1nK83axfeqpl6AbhZJ0ZwSPKG6HTpf3ZjapIa9PGm2NJACUTYCbOqycidR
wFthuzl5hWB9/CRaaCGiNtMIguQwChPC3Qs6kEF/pISXAimfEDoJQweHwwcCusqB
ay0ZzB/t4U7xBex37cEkq1zgpmAzJrCxEWxOWxpjnDUU1uxoUZ7YjJWE7cacII2k
KJ64vBqPAgMBAAECggEAIf5l9tTUMZGvqHZNhkp9A73GnMBHs50ghbbOGCeGwpnz
0kUs7NaGhPv2KVXPH6y/OABWC48HJBi/AZwlhdcWscPcj3IdfDweT8bYY3tR77W6
IE4iBLN12T+bXU1WYAQ5YHIiq1KEa50pyqTf+NRt8v2tmorPkzTECvZWLhnWz0lW
n0sMnArJMwbrFh+ntmXu4bcYT3s8GM7v5a0W5+Og9kSnuShVL5kMPe1WcjX0/dVs
RWgjtEbz3ipyIfFvZlF9bQTbCPCyDQeWxWI2vxWTq0MOP4BsIEmtkLi7SJLP4ngt
SRMoiRVbLnNdo8u3+Ic1Tvn9uJq51+aqfjiuDNttKQKBgQD9SnHWcGJJIRyUtZwh
bO7KYrkaxWqjwULC16d1JE+USD986CjDDBRT6YmTpyW/7AqmASkWpDBFHVNQrRdI
o5ZFlVdvxWUKyyKnVtjrnU8ysV8AV4qFjhaehQ215YhJiOG2gTv4s+dZYTyCgAyT
iZpeK7bsrPDjOnsv+ICUdj3MWQKBgQD0nDGkuzgt9EETmbnv/ItGxWc0oux55iOH
vfp1Yrj+tm0gC7jUgOTp75FZEjtZ1/rKbjWKM2XToRAThuMdZL349mYwaqWBNbfD
bySgwbQylhSNgCa3L+jfhjZERxkDqHlVKptjt4ICOu4CsH0rmgFNdBtY2n80czZw
AWHK5H6hJwKBgAgyhZakEno9aRhi/EeUp/HC2izEoNvl4ExAAHppD25EHFHljZQq
auoAT+SIb09Ty1BuDy9dZvaFqXGd+HfwW2erGqZSZB/CTT/PLrwJXkvMs79mFeSW
oaLFuZjecde3Z16pthApel5JKFUs4btQo79SeNwWCMHB3cTCrR6g6QUZAoGAdSM3
QsPFK3yEjXZYbGxr5gAyZCqBQ/7JlP+NKRmVraR+rZHveRQgi0aGPDlW4rdjCf2s
9fmXEblXkYJO0IylzMtyNE1d5Hps/dIDoFgiivcD8J8l6yOuSRxkcF37xJyxPe+h
aic+wwKlZ/RMfMzLQuQPFIXN1Lg3oXuH8TlqypECgYEAynV6yyMdXxdK+UmKujsK
Pb86v8jiInEYe6oBlTWRZaEi32Ggxaw26RLH/pq/RsIKVW8JPP9nkjGnBW3064WT
2hnUJdF/b8mh+eH4N056hinPvpo3Ltk3IpZk9vRP5cRF5g36VEqUgBPDVPQ+BUv6
2yL96sA12ErEm8lkMT5vSPA=
-----END PRIVATE KEY-----
"""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _load_private(pem: str | None = None):
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(
        (pem or _TEST_PRIVATE_KEY_PEM).encode(), password=None
    )


def mint_rs256(
    claims: dict[str, Any],
    *,
    header: dict[str, Any] | None = None,
    private_key_pem: str | None = None,
) -> str:
    """Подписать RS256 JWT (реальный, не фейковый)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key = _load_private(private_key_pem)
    hdr: dict[str, Any] = {"alg": "RS256", "typ": "JWT"}
    if header:
        hdr.update(header)
    header_b64 = _b64url(json.dumps(hdr, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b64}.{payload_b64}.{_b64url(sig)}"


def mint_alg_none(claims: dict[str, Any]) -> str:
    """Склеить токен с ``alg=none`` и пустой сигнатурой (forge-вектор)."""
    header_b64 = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload_b64 = _b64url(json.dumps(claims).encode())
    return f"{header_b64}.{payload_b64}."


def tamper_signature(token: str) -> str:
    """Подменить подпись (последний символ) — forged signature."""
    head, payload, sig = token.rsplit(".", 2)
    forged = ("A" if not sig.endswith("A") else "B") + sig[1:]
    return f"{head}.{payload}.{forged}"
