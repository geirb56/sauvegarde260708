import hashlib
import hmac
import json
import time
from typing import Dict, List, Optional

from fastapi import HTTPException


def _parse_signature_values(signature_header: str) -> Dict[str, List[str]]:
    values: Dict[str, List[str]] = {}
    for item in signature_header.split(","):
        item = item.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        values.setdefault(key, []).append(value)
    return values


def verify_and_parse_stripe_event(
    payload: bytes,
    signature_header: Optional[str],
    webhook_secret: str,
    tolerance_seconds: int = 300,
) -> Dict:
    """
    Verify Stripe webhook signature using the official HMAC-SHA256 scheme.
    Returns parsed JSON payload when valid, raises HTTPException(400) when invalid.
    """
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    fields = _parse_signature_values(signature_header)
    timestamps = fields.get("t", [])
    signatures = fields.get("v1", [])

    if not timestamps or not signatures:
        raise HTTPException(status_code=400, detail="Invalid Stripe-Signature header format")

    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature timestamp") from exc

    try:
        payload_text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload encoding") from exc

    signed_payload = f"{timestamp}.{payload_text}".encode("utf-8")
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not any(hmac.compare_digest(sig, expected_signature) for sig in signatures):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    now = int(time.time())
    if (now - timestamp) > tolerance_seconds or timestamp > now:
        raise HTTPException(status_code=400, detail="Stripe webhook timestamp outside tolerance")

    try:
        return json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON payload") from exc
