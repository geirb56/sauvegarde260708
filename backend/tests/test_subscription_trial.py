"""Tests for the subscription flow (RunIndex).

Covers:
- GET /api/subscription/status recognizes 'free' for new users
- GET /api/subscription/info returns free for new accounts
- Brand new user starts as FREE (not trial — trial requires Garmin identity)
- POST /api/subscription/reset-to-trial still works for DEV tooling

IMPORTANT BEHAVIOR CHANGE:
  New RunIndex accounts now start as FREE.
  Trial access requires a Garmin identity (server-side only).
  See subscription_manager.activate_garmin_trial() and the BLOCKER note.
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

DEFAULT_USER = "default"
NEW_USER = "qa_trial_check_001"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def test_info_new_user_starts_free(s):
    """New users should start as FREE — not TRIAL."""
    new_user = f"qa_new_user_{os.getpid()}"
    r = s.get(f"{BASE_URL}/api/subscription/info", params={"user_id": new_user}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("info(new):", data)
    # New behavior: new user starts FREE
    assert data.get("status") == "free", (
        f"New user should be FREE (not trial). Got: {data.get('status')}. "
        "Trial requires Garmin identity. See BLOCKER in subscription_manager.py."
    )
    features = data.get("features", {})
    for k in ["training_plan", "plan_adaptation", "session_analysis", "sync_enabled", "llm_access", "full_access"]:
        assert features.get(k) is False, f"feature {k} should be False for FREE user: {features}"


def test_status_new_user_is_free(s):
    """New users should have 'free' tier in /subscription/status."""
    new_user = f"qa_new_user_status_{os.getpid()}"
    r = s.get(f"{BASE_URL}/api/subscription/status", params={"user_id": new_user}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("status(new):", data)
    assert data.get("tier") == "free", (
        f"New user tier should be 'free'. Got: {data.get('tier')}. "
        "Trial requires Garmin identity."
    )
    assert data.get("is_premium") is False


def test_reset_to_trial_still_works_for_dev(s):
    """POST /api/subscription/reset-to-trial is still available for DEV tooling."""
    r = s.post(f"{BASE_URL}/api/subscription/reset-to-trial", params={"user_id": DEFAULT_USER}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("reset:", data)
    assert data.get("success") is True or data.get("status") == "trial"
    # Verify status
    r2 = s.get(f"{BASE_URL}/api/subscription/status", params={"user_id": DEFAULT_USER}, timeout=30)
    assert r2.status_code == 200
    assert r2.json().get("tier") == "trial"
    # Verify info
    r3 = s.get(f"{BASE_URL}/api/subscription/info", params={"user_id": DEFAULT_USER}, timeout=30)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3.get("status") == "trial"
    days = d3.get("trial_days_remaining")
    assert days is not None and 28 <= int(days) <= 30

