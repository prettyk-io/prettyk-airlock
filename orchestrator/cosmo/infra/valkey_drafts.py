"""COS-110: Workspace drafts in Valkey — lazy client, no hard dependency.

Valkey is the PREFERRED store for workspace drafts, not a hard dependency.
If the valkey library is missing or Valkey is unreachable, the service
returns a clean 503 Service Unavailable — drafts never fall back to PG
(zero schema migration cost).

Key format:  cosmo:draft:{domain}:{user_id}:{owner}:{repo}:{branch}:{path}
TTL:         7 days (604800 s) per key on every save (sliding expiry).
Value:       JSON: {"content":..., "base_blob_sha":...|null, "updated_at":...}

Connection:  PK_VALKEY_HOST / PK_VALKEY_PORT (compose defaults) or
             COSMO_VALKEY_URL. Lazy per process; failure is never cached
             permanently — the next call retries.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DRAFT_TTL_S = 7 * 24 * 3600  # 7 days
_KEY_PREFIX = "cosmo:draft"
_valkey_client: Optional[Any] = None
_valkey_mode_logged = False


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
    the next call retries (Valkey may come back).
    """
    global _valkey_client, _valkey_mode_logged
    if _valkey_client is not None:
        return _valkey_client
    try:
        import valkey  # lazy — optional dependency, never required at import time
    except ImportError:
        if not _valkey_mode_logged:
            logger.warning(
                "[DRAFT] valkey client library not installed — "
                "workspace drafts are unavailable (503)"
            )
            _valkey_mode_logged = True
        return None
    try:
        client = valkey.Valkey.from_url(_valkey_url(), socket_connect_timeout=1.0)
        client.ping()
    except Exception:  # noqa: BLE001
        if not _valkey_mode_logged:
            logger.warning(
                "[DRAFT] Valkey unreachable at %s — workspace drafts are "
                "unavailable (503)", _valkey_url()
            )
            _valkey_mode_logged = True
        return None
    _valkey_client = client
    if not _valkey_mode_logged:
        logger.info("[DRAFT] Valkey connected at %s", _valkey_url())
        _valkey_mode_logged = True
    return _valkey_client


def _key(
    domain: str, user_id: str, owner: str, repo: str,
    branch: str, path: str,
) -> str:
    """Valkey key for a draft snapshot."""
    return f"{_KEY_PREFIX}:{domain}:{user_id}:{owner}:{repo}:{branch}:{path}"


# ── Public API ──────────────────────────────────────────────────────────


def save_draft(
    domain: str, user_id: str, owner: str, repo: str,
    branch: str, path: str, content: str, base_blob_sha: Optional[str],
) -> Dict[str, Any]:
    """Atomically save a draft in Valkey. Returns the saved data.

    Raises ValkeyUnreachableError if Valkey is unavailable.
    """
    client = _get_valkey()
    if client is None:
        raise ValkeyUnreachableError("Valkey is unavailable — drafts cannot be saved")

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "content": content,
        "base_blob_sha": base_blob_sha,
        "updated_at": now,
    }
    k = _key(domain, user_id, owner, repo, branch, path)
    client.set(k, json.dumps(data), ex=DRAFT_TTL_S)
    logger.debug("[DRAFT] saved %s", k)
    return data


def load_draft(
    domain: str, user_id: str, owner: str, repo: str,
    branch: str, path: str,
) -> Dict[str, Any] | None:
    """Load a draft from Valkey. None if not found.

    Raises ValkeyUnreachableError if Valkey is unavailable.
    """
    client = _get_valkey()
    if client is None:
        raise ValkeyUnreachableError("Valkey is unavailable — drafts cannot be read")

    k = _key(domain, user_id, owner, repo, branch, path)
    raw = client.get(k)
    if raw is None:
        return None
    return json.loads(raw)


def delete_draft(
    domain: str, user_id: str, owner: str, repo: str,
    branch: str, path: str,
) -> bool:
    """Delete a draft from Valkey. Returns True if it existed.

    Raises ValkeyUnreachableError if Valkey is unavailable.
    """
    client = _get_valkey()
    if client is None:
        raise ValkeyUnreachableError("Valkey is unavailable — drafts cannot be deleted")

    k = _key(domain, user_id, owner, repo, branch, path)
    deleted = client.delete(k)
    return bool(deleted)


class ValkeyUnreachableError(Exception):
    """Valkey is not available — mapped to 503 by route handlers."""