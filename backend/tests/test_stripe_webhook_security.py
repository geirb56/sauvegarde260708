import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from services.stripe_webhook_security import verify_and_parse_stripe_event


def _build_signature_header(payload: bytes, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_verify_stripe_webhook_with_valid_signature():
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {"id": "cs_test"}}}).encode("utf-8")
    secret = "whsec_test_secret"
    header = _build_signature_header(payload, secret, int(time.time()))

    event = verify_and_parse_stripe_event(payload, header, secret)
    assert event["type"] == "checkout.session.completed"


def test_verify_stripe_webhook_with_invalid_signature():
    payload = b'{"type":"checkout.session.completed"}'
    with pytest.raises(HTTPException) as exc:
        verify_and_parse_stripe_event(payload, "t=1,v1=deadbeef", "whsec_test_secret")
    assert exc.value.status_code == 400


def test_verify_stripe_webhook_with_valid_signature_and_metadata():
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {"metadata": {"user_id": "u1"}}}}).encode("utf-8")
    secret = "whsec_test_secret"
    header = _build_signature_header(payload, secret, int(time.time()))

    event = verify_and_parse_stripe_event(payload, header, secret)
    assert event["data"]["object"]["metadata"]["user_id"] == "u1"


def test_verify_stripe_webhook_with_malformed_signature():
    payload = b'{"type":"checkout.session.completed"}'
    with pytest.raises(HTTPException) as exc:
        verify_and_parse_stripe_event(payload, "t=1,v1=bad", "whsec_test_secret")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid Stripe webhook signature"
