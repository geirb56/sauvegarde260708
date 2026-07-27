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


def test_main_webhook_valid_signature_is_accepted():
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {"id": "cs_test"}}}).encode("utf-8")
    secret = "whsec_test_secret"
    header = _build_signature_header(payload, secret, int(time.time()))

    event = verify_and_parse_stripe_event(payload, header, secret)
    assert event["type"] == "checkout.session.completed"


def test_main_webhook_invalid_signature_is_rejected():
    payload = b'{"type":"checkout.session.completed"}'
    with pytest.raises(HTTPException) as exc:
        verify_and_parse_stripe_event(payload, "t=1,v1=deadbeef", "whsec_test_secret")
    assert exc.value.status_code == 400


def test_early_adopter_webhook_valid_signature_is_accepted():
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {"metadata": {"user_id": "u1"}}}}).encode("utf-8")
    secret = "whsec_test_secret_early"
    header = _build_signature_header(payload, secret, int(time.time()))

    event = verify_and_parse_stripe_event(payload, header, secret)
    assert event["data"]["object"]["metadata"]["user_id"] == "u1"


def test_early_adopter_webhook_invalid_signature_is_rejected():
    payload = b'{"type":"checkout.session.completed"}'
    with pytest.raises(HTTPException) as exc:
        verify_and_parse_stripe_event(payload, "t=1,v1=bad", "whsec_test_secret_early")
    assert exc.value.status_code == 400

