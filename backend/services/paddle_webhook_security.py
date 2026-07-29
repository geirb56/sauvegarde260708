"""
paddle_webhook_security.py
==========================

Verifies incoming Paddle Billing webhook signatures using HMAC-SHA256.

Paddle Billing webhook signature format (Paddle-Signature header):
    ts=<unix_timestamp>;h1=<hex_hmac_sha256>

Verification steps (per official Paddle Billing documentation):
    1. Extract `ts` (timestamp) and `h1` (hex signature) from the header.
    2. Build signed payload:  f"{ts}:{raw_body}"
    3. Compute HMAC-SHA256 of that payload using your webhook secret key.
    4. Constant-time compare the computed digest with `h1`.

Reference: https://developer.paddle.com/webhooks/about/verify-signatures
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PaddleWebhookError(ValueError):
    """Raised when a Paddle webhook cannot be verified."""


def verify_and_parse_paddle_event(
    raw_body: bytes,
    paddle_signature: str,
    secret_key: str,
) -> Dict[str, Any]:
    """
    Verify the Paddle-Signature header and return the parsed JSON event.

    Args:
        raw_body:          The raw (undecoded) request body bytes.
        paddle_signature:  Value of the `Paddle-Signature` request header.
        secret_key:        Paddle webhook secret key from the dashboard.

    Returns:
        Parsed JSON event as a Python dict.

    Raises:
        PaddleWebhookError: If the signature header is missing, malformed,
                            or the HMAC digest does not match.
    """
    import json

    if not paddle_signature:
        raise PaddleWebhookError("Missing Paddle-Signature header")

    if not secret_key:
        raise PaddleWebhookError("Paddle webhook secret key is not configured")

    # ── 1. Parse header ──────────────────────────────────────────────────────
    try:
        parts: Dict[str, str] = dict(
            item.split("=", 1) for item in paddle_signature.split(";")
        )
        ts = parts["ts"]
        h1 = parts["h1"]
    except (KeyError, ValueError) as exc:
        raise PaddleWebhookError(
            f"Malformed Paddle-Signature header: {paddle_signature!r}"
        ) from exc

    # ── 2. Build signed payload ───────────────────────────────────────────────
    body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
    signed_payload = f"{ts}:{body_str}".encode("utf-8")

    # ── 3. Compute HMAC-SHA256 ────────────────────────────────────────────────
    computed_sig = hmac.new(
        secret_key.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    # ── 4. Constant-time comparison ───────────────────────────────────────────
    if not hmac.compare_digest(computed_sig, h1):
        raise PaddleWebhookError("Paddle webhook signature mismatch — request rejected")

    # ── 5. Parse JSON ─────────────────────────────────────────────────────────
    try:
        event: Dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise PaddleWebhookError(f"Invalid JSON in Paddle webhook body: {exc}") from exc

    logger.debug(
        "[PaddleWebhook] Verified event type=%r ts=%s",
        event.get("event_type"),
        ts,
    )
    return event
