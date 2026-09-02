"""COS-075: SSE stream tickets — auth without bearer-in-URL for EventSource.

Problem: EventSource cannot set custom headers, so the notification SSE
stream previously accepted `recipient_id` as a bare query param (V1
compromise) — no auth at all on the stream, and the recipient was
client-asserted.

Solution: client first POSTs /api/v1/notifications/sse-ticket with the
normal bearer auth; server returns a short-TTL ticket bound to
principal.user_id. The stream is opened with ?ticket=... and the server
resolves the recipient from the ticket — never from a client query param.

Ticket formats:
  * "v1.<payload_b64url>.<sig_b64url>" — stateless HMAC ticket (fallback).
    payload is a JSON {"r": recipient_id, "e": exp_unix}; signature is
    HMAC-SHA256(secret, payload).
  * "ot1.<random_token>" — one-time ticket (COS-079): random token stored in
    Valkey with TTL; validate burns it with GETDEL (single-use).

COS-079 decision (deliberate): Valkey is a PREFERRED store, not a hard
dependency. If the valkey client library is missing or Valkey is
unreachable at mint time, mint_ticket falls back to the stateless HMAC
ticket — SSE never becomes hard-coupled to Valkey (degraded-mode safe).
An "ot1" ticket whose GETDEL fails at validate time is rejected (fail
closed); the client reconnect loop mints a fresh ticket, which will fall
back to HMAC while Valkey is down.

Secret: COSMO_SSE_TICKET_SECRET env. If unset — a per-process random secret
is generated (logged once). On a multi-replica deployment set the env, or
stateless tickets minted by one replica are rejected by another (one-time
tickets live in shared Valkey and work across replicas).

Valkey connection: COSMO_VALKEY_URL (e.g. redis://cosmo-valkey:6379/0) or
PK_VALKEY_HOST / PK_VALKEY_PORT (compose defaults). Configured lazily per
process; failure is never cached permanently — the next mint retries.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

TICKET_TTL_S = 60
_PREFIX = "v1"
_OT_PREFIX = "ot1"
_OT_KEY_PREFIX = "cosmo:sse:ot:"
_secret_cache: Optional[bytes] = None
_valkey_client: Optional[Any] = None
_valkey_mode_logged = False


def _get_secret() -> bytes:
    """Ticket-signing secret: env override or per-process random (lazy)."""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    raw = os.getenv("COSMO_SSE_TICKET_SECRET", "").strip()
    if raw:
        _secret_cache = raw.encode("utf-8")
    else:
        _secret_cache = secrets.token_bytes(32)
        logger.warning(
            "[SSE:TICKET] COSMO_SSE_TICKET_SECRET not set — using per-process "
            "random secret (tickets are invalidated on restart; set the env "
            "for multi-replica deployments)"
        )
    return _secret_cache


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ── COS-079: one-time ticket store (lazy Valkey, never a hard dependency) ──


def _valkey_url() -> str:
    url = os.getenv("COSMO_VALKEY_URL", "").strip()
    if url:
        return url
    host = os.getenv("PK_VALKEY_HOST", "localhost").strip() or "localhost"
    port = os.getenv("PK_VALKEY_PORT", "6379").strip() or "6379"
    return f"redis://{host}:{port}/0"


def _get_valkey() -> Optional[Any]:
    """Lazily import and connect the valkey client; None if unavailable.

    Success is cached for the process lifetime; failure is NOT cached —
    the next call retries (Valkey may come back between mints).
    """
    global _valkey_client, _valkey_mode_logged
    if _valkey_client is not None:
        return _valkey_client
    try:
        import valkey  # lazy — optional dependency, never required at import time
    except ImportError:
        if not _valkey_mode_logged:
            logger.warning(
                "[SSE:TICKET] valkey client library not installed — "
                "one-time tickets fall back to stateless HMAC tickets"
            )
            _valkey_mode_logged = True
        return None
    try:
        client = valkey.Valkey.from_url(_valkey_url(), socket_connect_timeout=1.0)
        client.ping()
    except Exception:  # noqa: BLE001 — Valkey down/unreachable → fallback
        if not _valkey_mode_logged:
            logger.warning(
                "[SSE:TICKET] valkey unreachable at %s — "
                "one-time tickets fall back to stateless HMAC tickets",
                _valkey_url(),
            )
            _valkey_mode_logged = True
        return None
    logger.info("[SSE:TICKET] one-time tickets enabled via valkey %s", _valkey_url())
    _valkey_client = client
    return client


def mint_ticket(recipient_id: str, ttl_s: int = TICKET_TTL_S) -> str:
    """Mint a short-TTL ticket bound to recipient_id.

    Prefers a single-use Valkey ticket ("ot1."); falls back to the
    stateless HMAC ticket ("v1.") when Valkey is not available.
    """
    one_time = _mint_one_time_ticket(recipient_id, ttl_s)
    if one_time is not None:
        return one_time
    payload = json.dumps(
        {"r": recipient_id, "e": int(time.time()) + ttl_s},
        separators=(",", ":"),
    ).encode("utf-8")
    sig = hmac.new(_get_secret(), payload, hashlib.sha256).digest()
    return f"{_PREFIX}.{_b64url_encode(payload)}.{_b64url_encode(sig)}"


def _mint_one_time_ticket(recipient_id: str, ttl_s: int) -> Optional[str]:
    client = _get_valkey()
    if client is None:
        return None
    token = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"r": recipient_id, "e": int(time.time()) + ttl_s},
        separators=(",", ":"),
    )
    try:
        client.set(_OT_KEY_PREFIX + token, payload, ex=ttl_s)
    except Exception:  # noqa: BLE001 — transient Valkey failure → fallback
        return None
    return f"{_OT_PREFIX}.{token}"


def validate_ticket(ticket: str) -> Optional[str]:
    """Return recipient_id for a valid, unexpired ticket; None otherwise.

    Stateless tickets: constant-time signature comparison, server-side expiry.
    One-time tickets ("ot1."): burned with GETDEL — the second validate of the
    same ticket returns None. Valkey failure at validate time → None (fail
    closed); the client mints a fresh ticket on reconnect.
    """
    try:
        parts = ticket.split(".")
        if len(parts) == 2 and parts[0] == _OT_PREFIX:
            return _validate_one_time_ticket(parts[1])
        if len(parts) != 3 or parts[0] != _PREFIX:
            return None
        payload = _b64url_decode(parts[1])
        expected_sig = hmac.new(_get_secret(), payload, hashlib.sha256).digest()
        actual_sig = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        data = json.loads(payload.decode("utf-8"))
        recipient_id = data.get("r")
        exp = data.get("e")
        if not isinstance(recipient_id, str) or not recipient_id.strip():
            return None
        if not isinstance(exp, (int, float)) or time.time() > exp:
            return None
        return recipient_id
    except Exception:  # noqa: BLE001 — any malformed ticket is just invalid
        return None


def _validate_one_time_ticket(token: str) -> Optional[str]:
    if not token or len(token) < 32:
        return None
    client = _get_valkey()
    if client is None:
        return None  # ot1 ticket without Valkey can never be validated
    try:
        raw = client.getdel(_OT_KEY_PREFIX + token)
    except Exception:  # noqa: BLE001 — fail closed on store errors
        return None
    if not raw:
        return None  # unknown or already burned (single use)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    recipient_id = data.get("r")
    exp = data.get("e")
    if not isinstance(recipient_id, str) or not recipient_id.strip():
        return None
    if not isinstance(exp, (int, float)) or time.time() > exp:
        return None
    return recipient_id
