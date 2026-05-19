"""
The Board Market — Event Emit

Fire-and-forget publisher. POSTs a signed event to the Takeoff router.
Never blocks. Never raises. Failures are logged at WARN.

Required environment variables:
    BOARD_MARKET_ROUTER_URL     — full URL of the router endpoint
    BOARD_MARKET_HMAC_SECRET    — shared secret for HMAC signing

When unset (typical for local dev / backtest runs), emit() silently no-ops.
"""

import os
import hmac
import hashlib
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Literal

try:
    import httpx
except ImportError:
    httpx = None

from .types import EVENT_TYPES


log = logging.getLogger(__name__)

SOURCE = "board-market"
SCHEMA_VERSION = "1"

EventSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def _generate_ulid() -> str:
    """
    Generate a ULID (lexicographically sortable, time-prefixed unique ID).
    26 chars, Crockford base32. No external dependency.
    """
    # 48-bit timestamp + 80-bit randomness
    ts_ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")

    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out = []
    # Encode timestamp (10 chars)
    for i in range(9, -1, -1):
        out.append(alphabet[(ts_ms >> (i * 5)) & 0x1F])
    # Encode randomness (16 chars)
    for i in range(15, -1, -1):
        out.append(alphabet[(randomness >> (i * 5)) & 0x1F])
    return "".join(out)


def _canonical_json(obj: dict) -> str:
    """Canonical JSON serialization for signing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sign(envelope: dict, secret: str) -> str:
    """HMAC-SHA256 signature, base64-encoded."""
    canonical = _canonical_json(envelope).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def emit(
    type: str,
    title: str,
    body: str,
    payload: Optional[dict] = None,
    sev: Optional[EventSeverity] = None,
    deeplink: Optional[str] = None,
) -> bool:
    """
    Fire-and-forget event to the Takeoff router.

    Returns True if accepted by the router, False otherwise.
    Never raises. Never blocks for more than 3 seconds.

    Args:
        type: event type, must be in EVENT_TYPES registry
        title: human-readable headline ≤80 chars
        body: human-readable detail ≤300 chars
        payload: structured data for subscribers
        sev: override default severity (rarely needed)
        deeplink: URL to open when user taps the notification
    """
    # Validate type is registered
    if type not in EVENT_TYPES:
        log.warning(f"emit() called with unregistered type: {type}")
        return False

    type_version, default_sev, _ = EVENT_TYPES[type]
    severity = sev or default_sev

    # Enforce length limits
    if len(title) > 80:
        title = title[:77] + "..."
    if len(body) > 300:
        body = body[:297] + "..."

    # Build envelope (without signature, which is added after)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _generate_ulid(),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "src": SOURCE,
        "type": type,
        "type_version": type_version,
        "sev": severity,
        "title": title,
        "body": body,
    }
    if deeplink:
        envelope["deeplink"] = deeplink
    if payload:
        envelope["payload"] = payload

    # Sign
    secret = os.environ.get("BOARD_MARKET_HMAC_SECRET")
    router_url = os.environ.get("BOARD_MARKET_ROUTER_URL")

    if not secret or not router_url:
        # Dev/test mode: silently no-op
        log.debug(f"emit() no-op (router not configured): {type}")
        return False

    envelope["signature"] = _sign(envelope, secret)

    # Fire
    if httpx is None:
        log.warning("emit() needs httpx installed")
        return False

    try:
        response = httpx.post(
            router_url,
            json=envelope,
            timeout=3.0,
        )
        if response.status_code == 200:
            return True
        log.warning(f"Router returned {response.status_code}: {response.text[:200]}")
        return False
    except Exception as e:
        log.warning(f"emit() failed for {type}: {e}")
        return False
