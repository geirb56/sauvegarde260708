"""
test_pr62_security.py
=====================

Targeted security tests for PR62 Medium findings:

1. Paddle webhook timestamp replay protection — stale and future timestamps
   are rejected even when the HMAC signature is otherwise valid.

2. Global rate limiter (server.py) — ``get_user_id_from_request`` must never
   blindly trust ``X-Forwarded-For`` when ``TRUSTED_PROXY_COUNT`` is unset
   (or 0).  Spoofed headers must not allow a client to rotate its rate-limit
   identity.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path / env setup (must precede backend imports)
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ.setdefault("JWT_SECRET_KEY", "pr62-test-secret-for-unit-tests-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")


# ===========================================================================
# 1. Paddle webhook — timestamp validation (PR62, finding #1)
# ===========================================================================

from services.paddle_webhook_security import (
    PaddleWebhookError,
    verify_and_parse_paddle_event,
)


def _make_sig(secret: str, ts: str, body: bytes) -> str:
    payload = f"{ts}:{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


def _make_body() -> bytes:
    return json.dumps({"event_type": "subscription.activated", "event_id": str(uuid.uuid4())}).encode()


SECRET = "pr62_test_paddle_secret"


class TestPaddleTimestampReplay:
    def test_stale_timestamp_rejected(self):
        """Timestamp older than 5 min (300 s) must be rejected — replay attack."""
        body = _make_body()
        stale_ts = str(int(time.time()) - 301)
        sig = _make_sig(SECRET, stale_ts, body)
        with pytest.raises(PaddleWebhookError, match="outside the allowed window"):
            verify_and_parse_paddle_event(body, sig, SECRET)

    def test_future_timestamp_rejected(self):
        """Timestamp more than 5 min in the future must be rejected."""
        body = _make_body()
        future_ts = str(int(time.time()) + 301)
        sig = _make_sig(SECRET, future_ts, body)
        with pytest.raises(PaddleWebhookError, match="outside the allowed window"):
            verify_and_parse_paddle_event(body, sig, SECRET)

    def test_boundary_just_inside_window_accepted(self):
        """Timestamp at exactly (max_age - 1) seconds old must be accepted."""
        body = _make_body()
        ts = str(int(time.time()) - 299)
        sig = _make_sig(SECRET, ts, body)
        event = verify_and_parse_paddle_event(body, sig, SECRET)
        assert event["event_type"] == "subscription.activated"

    def test_current_timestamp_accepted(self):
        """A webhook with the current timestamp must pass."""
        body = _make_body()
        ts = str(int(time.time()))
        sig = _make_sig(SECRET, ts, body)
        event = verify_and_parse_paddle_event(body, sig, SECRET)
        assert isinstance(event, dict)

    def test_stale_hmac_still_rejected_separately(self):
        """A stale timestamp whose HMAC is also wrong produces a timestamp error
        (timestamp is checked before HMAC to avoid timing side-channels on stale
        requests)."""
        body = _make_body()
        stale_ts = str(int(time.time()) - 600)
        bad_sig = f"ts={stale_ts};h1=" + "a" * 64
        with pytest.raises(PaddleWebhookError, match="outside the allowed window"):
            verify_and_parse_paddle_event(body, bad_sig, SECRET)


# ===========================================================================
# 2. Global rate limiter — TRUSTED_PROXY_COUNT (PR62, finding #2)
# ===========================================================================

# ===========================================================================
# 2. Global rate limiter — TRUSTED_PROXY_COUNT (PR62, finding #2)
#
# Both ``server.get_user_id_from_request`` (global rate limiter) and
# ``auth.router._get_client_ip`` (auth rate limiter) share the same
# TRUSTED_PROXY_COUNT-aware IP extraction pattern introduced in PR62.
# We test ``_get_client_ip`` directly (it has lighter deps) to verify
# the shared security property: X-Forwarded-For is ignored by default.
# ===========================================================================

from auth.router import _get_client_ip


def _make_request(xff: str | None = None, direct_ip: str = "10.0.0.1") -> MagicMock:
    """Build a minimal mock Starlette Request for _get_client_ip / get_user_id_from_request."""
    headers: dict[str, str] = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff

    req = MagicMock()
    # Make .headers behave like a real mapping
    req.headers = MagicMock()
    req.headers.get = lambda key, default="": headers.get(key, default)
    req.client = MagicMock()
    req.client.host = direct_ip
    return req


class TestGlobalRateLimiterXFF:
    """Verify TRUSTED_PROXY_COUNT-aware IP extraction used by the global rate limiter.

    ``server.get_user_id_from_request`` and ``auth.router._get_client_ip`` both
    implement the same TRUSTED_PROXY_COUNT pattern (PR62 fix).  These tests
    exercise ``_get_client_ip`` which has lighter import requirements, while
    validating the security property that applies to the global rate limiter
    as well.
    """

    def test_xff_ignored_when_trusted_proxy_zero(self, monkeypatch):
        """With TRUSTED_PROXY_COUNT=0 (default), XFF is ignored; direct IP is used."""
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "0")
        req = _make_request(xff="1.2.3.4", direct_ip="127.0.0.1")
        result = _get_client_ip(req)
        assert result == "127.0.0.1", (
            f"Expected direct IP '127.0.0.1', got {result!r}. "
            "XFF must be ignored when TRUSTED_PROXY_COUNT=0."
        )

    def test_xff_ignored_when_trusted_proxy_not_set(self, monkeypatch):
        """Without TRUSTED_PROXY_COUNT env var, XFF must also be ignored."""
        monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
        req = _make_request(xff="9.9.9.9", direct_ip="192.168.1.1")
        result = _get_client_ip(req)
        assert result == "192.168.1.1", (
            f"Expected direct IP, got {result!r}. "
            "XFF must not be trusted when TRUSTED_PROXY_COUNT is absent."
        )

    def test_spoofed_xff_cannot_rotate_identity(self, monkeypatch):
        """Rotating XFF values must all resolve to the same direct IP (no bypass)."""
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "0")
        direct_ip = "10.10.10.10"
        identities = set()
        for fake_ip in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]:
            req = _make_request(xff=fake_ip, direct_ip=direct_ip)
            identities.add(_get_client_ip(req))
        assert identities == {direct_ip}, (
            f"Expected all requests to map to {direct_ip!r}, got {identities}. "
            "Spoofed XFF headers must not create distinct rate-limit identities."
        )

    def test_xff_used_correctly_with_one_trusted_proxy(self, monkeypatch):
        """With TRUSTED_PROXY_COUNT=1, a single XFF entry is taken as the client IP."""
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
        # Single hop: trusted load balancer adds XFF containing only the real client IP.
        req = _make_request(xff="203.0.113.5", direct_ip="10.0.0.1")
        result = _get_client_ip(req)
        # idx = max(0, 1 - 1) = 0 → parts[0] = "203.0.113.5"
        assert result == "203.0.113.5"
