"""Regression test for iteration_26 fix: subscription middleware now honors X-User-Id header.

Previously (iter_25) the middleware only read ?user_id= and fell back to client IP, causing
403 subscription_required on /api/workouts, /api/training/plan, /api/training/full-cycle
and /api/training/race-predictions for the trial user 'default'.
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

GATED = [
    "/api/workouts",
    "/api/training/plan",
    "/api/training/full-cycle",
    "/api/training/race-predictions",
]


def test_gated_endpoints_with_header():
    """With X-User-Id: default header, all gated endpoints must return 200."""
    for ep in GATED:
        r = requests.get(f"{BASE_URL}{ep}", headers={"X-User-Id": "default"}, timeout=30)
        assert r.status_code == 200, f"{ep} expected 200, got {r.status_code}: {r.text[:200]}"


def test_gated_endpoints_with_query_param():
    """Query param path must still work (parity)."""
    for ep in GATED:
        r = requests.get(f"{BASE_URL}{ep}", params={"user_id": "default"}, timeout=30)
        assert r.status_code == 200, f"{ep} expected 200, got {r.status_code}: {r.text[:200]}"


def test_no_id_does_not_crash():
    """Requests without any user id fall back to IP; must not 500."""
    for ep in GATED:
        r = requests.get(f"{BASE_URL}{ep}", timeout=30)
        # 403 subscription_required is expected/sane, but must not 5xx
        assert r.status_code < 500, f"{ep} crashed with {r.status_code}: {r.text[:200]}"
