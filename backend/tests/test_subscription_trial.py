"""Tests for 30-day free trial subscription flow (RunIndex).

Covers:
- GET /api/subscription/status recognizes 'trial'
- GET /api/subscription/info returns trial with ~30 days remaining
- Brand new user auto-creates a 30-day trial
- POST /api/subscription/reset-to-trial resets to a 30-day trial
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


def test_status_default_user_trial(s):
    r = s.get(f"{BASE_URL}/api/subscription/status", params={"user_id": DEFAULT_USER}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("status(default):", data)
    assert data.get("tier") == "trial", f"tier expected 'trial' got {data.get('tier')}"
    assert data.get("is_premium") is True
    assert data.get("is_unlimited") is True
    assert data.get("messages_remaining") == 999
    # tier_name from tier_config
    assert "trial" in str(data.get("tier_name", "")).lower() or "free trial" in str(data.get("tier_name", "")).lower()


def test_info_default_user_trial(s):
    r = s.get(f"{BASE_URL}/api/subscription/info", params={"user_id": DEFAULT_USER}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("info(default):", data)
    assert data.get("status") == "trial"
    days = data.get("trial_days_remaining")
    assert days is not None and 25 <= int(days) <= 30, f"trial_days_remaining={days}"
    features = data.get("features", {})
    for k in ["training_plan", "plan_adaptation", "session_analysis", "sync_enabled", "llm_access", "full_access"]:
        assert features.get(k) is True, f"feature {k} not True: {features}"


def test_info_new_user_autocreates_trial(s):
    r = s.get(f"{BASE_URL}/api/subscription/info", params={"user_id": NEW_USER}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("info(new):", data)
    assert data.get("status") == "trial"
    days = data.get("trial_days_remaining")
    assert days is not None and 28 <= int(days) <= 30, f"new user trial_days_remaining={days}"


def test_status_new_user_trial(s):
    r = s.get(f"{BASE_URL}/api/subscription/status", params={"user_id": NEW_USER}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    print("status(new):", data)
    assert data.get("tier") == "trial"
    assert data.get("is_premium") is True


def test_reset_to_trial_default(s):
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
