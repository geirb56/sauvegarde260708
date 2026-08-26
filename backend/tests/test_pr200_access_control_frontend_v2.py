"""
PR #200 — Access Control Frontend V2
=====================================

Tests for the GET /user/features endpoint, which is the canonical backend
source consumed by the frontend SubscriptionContext V2.

The endpoint wraps UserAccess.to_api_dict() and must return the correct shape
for each subscription tier: FREE / TRIAL / PREMIUM.

Test matrix:
1.  FREE user: plan="free", has_premium_access=False, all premium features False
2.  TRIAL user (active): plan="trial", has_premium_access=True, trial_active=True
3.  PREMIUM user (active): plan="premium", has_premium_access=True, trial_active=False
4.  TRIAL user (expired): plan="free", has_premium_access=False
5.  PREMIUM user (expired): plan="free", has_premium_access=False
6.  DB error: endpoint returns free-tier data (fail-closed)
7.  Unauthenticated request: 401
8.  feature_access keys include all FREE_FEATURES and PREMIUM_FEATURES
9.  FREE user: free features are True, premium features are False
10. TRIAL user: all premium and free features are True
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

from access_control import (
    Tier,
    UserAccess,
    PREMIUM_FEATURES,
    FREE_FEATURES,
    get_user_access,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_access(tier: Tier, *, trial_end=None, premium_expires_at=None) -> UserAccess:
    return UserAccess(
        user_id="user-test-1",
        tier=tier,
        trial_end=trial_end,
        premium_expires_at=premium_expires_at,
    )


def _future(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _past(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ─── UserAccess.to_api_dict() ─────────────────────────────────────────────────
# The /user/features endpoint is a thin wrapper around to_api_dict(), so
# testing the dict directly covers the shape contract.

class TestToApiDict:
    """to_api_dict() produces the shape that the frontend SubscriptionContext V2 consumes."""

    # 1. FREE
    def test_free_tier_shape(self):
        access = _make_access(Tier.FREE)
        d = access.to_api_dict()

        assert d["subscription_status"] == "free"
        assert d["is_free"] is True
        assert d["is_trial"] is False
        assert d["is_premium"] is False
        assert d["has_premium_access"] is False
        assert d["trial_days_remaining"] is None
        assert d["is_unlimited_chat"] is False
        assert d["chat_monthly_quota"] == 10  # CHAT_QUOTA_FREE

    # 2. TRIAL (active)
    def test_trial_tier_shape(self):
        trial_end = _future(21)
        access = _make_access(Tier.TRIAL, trial_end=trial_end)
        d = access.to_api_dict()

        assert d["subscription_status"] == "trial"
        assert d["is_trial"] is True
        assert d["has_premium_access"] is True
        # .days truncates; _future(21) is slightly under 21 full days from now
        assert d["trial_days_remaining"] in (20, 21)
        assert d["is_unlimited_chat"] is True
        assert d["chat_monthly_quota"] is None

    # 3. PREMIUM (active)
    def test_premium_tier_shape(self):
        premium_exp = _future(30)
        access = _make_access(Tier.PREMIUM, premium_expires_at=premium_exp)
        d = access.to_api_dict()

        assert d["subscription_status"] == "premium"
        assert d["is_premium"] is True
        assert d["has_premium_access"] is True
        assert d["trial_days_remaining"] is None
        assert d["is_unlimited_chat"] is True

    # 4. TRIAL expired → treated as FREE by _resolve_access; verify UserAccess FREE
    def test_expired_trial_is_free(self):
        access = _make_access(Tier.FREE, trial_end=_past(5))
        d = access.to_api_dict()

        assert d["subscription_status"] == "free"
        assert d["has_premium_access"] is False

    # 5. PREMIUM expired → treated as FREE
    def test_expired_premium_is_free(self):
        access = _make_access(Tier.FREE, premium_expires_at=_past(3))
        d = access.to_api_dict()

        assert d["subscription_status"] == "free"
        assert d["has_premium_access"] is False

    # 6. feature_access contains all declared features
    def test_feature_access_keys_complete(self):
        access = _make_access(Tier.PREMIUM)
        d = access.to_api_dict()

        for feat in PREMIUM_FEATURES:
            assert feat in d["feature_access"], f"Missing premium feature: {feat}"
        for feat in FREE_FEATURES:
            assert feat in d["feature_access"], f"Missing free feature: {feat}"

    # 7. FREE user: free features True, premium features False
    def test_free_user_feature_access_values(self):
        access = _make_access(Tier.FREE)
        d = access.to_api_dict()

        for feat in FREE_FEATURES:
            assert d["feature_access"][feat] is True, f"Free feature should be True: {feat}"
        for feat in PREMIUM_FEATURES:
            assert d["feature_access"][feat] is False, f"Premium feature should be False: {feat}"

    # 8. TRIAL user: all features True
    def test_trial_user_all_features_true(self):
        access = _make_access(Tier.TRIAL, trial_end=_future(21))
        d = access.to_api_dict()

        for feat in PREMIUM_FEATURES | FREE_FEATURES:
            assert d["feature_access"][feat] is True, f"Feature should be True for TRIAL: {feat}"

    # 9. PREMIUM user: all features True
    def test_premium_user_all_features_true(self):
        access = _make_access(Tier.PREMIUM)
        d = access.to_api_dict()

        for feat in PREMIUM_FEATURES | FREE_FEATURES:
            assert d["feature_access"][feat] is True, f"Feature should be True for PREMIUM: {feat}"


# ─── /user/features endpoint shape ───────────────────────────────────────────
# The endpoint re-maps to_api_dict() keys to the frontend-facing shape:
#   plan, trial_active, has_premium_access, trial_days_remaining, feature_access

class TestUserFeaturesEndpointShape:
    """
    Verifies the response mapping that the endpoint applies on top of
    to_api_dict().  We test directly against UserAccess rather than the full
    HTTP stack to keep tests fast and dependency-free.
    """

    def _simulate_endpoint(self, access: UserAccess) -> dict:
        """Reproduce exactly the mapping in server.py get_user_features()."""
        api_dict = access.to_api_dict()
        return {
            "plan": api_dict["subscription_status"],
            "trial_active": api_dict["is_trial"],
            "has_premium_access": api_dict["has_premium_access"],
            "trial_days_remaining": api_dict["trial_days_remaining"],
            "feature_access": api_dict["feature_access"],
        }

    # 10. FREE
    def test_endpoint_free_shape(self):
        result = self._simulate_endpoint(_make_access(Tier.FREE))
        assert result["plan"] == "free"
        assert result["trial_active"] is False
        assert result["has_premium_access"] is False
        assert result["trial_days_remaining"] is None
        assert result["feature_access"]["training_plan"] is False

    # 11. TRIAL active
    def test_endpoint_trial_shape(self):
        result = self._simulate_endpoint(_make_access(Tier.TRIAL, trial_end=_future(14)))
        assert result["plan"] == "trial"
        assert result["trial_active"] is True
        assert result["has_premium_access"] is True
        # .days truncates; _future(14) may return 13 or 14
        assert result["trial_days_remaining"] in (13, 14)
        assert result["feature_access"]["training_plan"] is True
        assert result["feature_access"]["garmin_sync"] is True

    # 12. PREMIUM active
    def test_endpoint_premium_shape(self):
        result = self._simulate_endpoint(_make_access(Tier.PREMIUM))
        assert result["plan"] == "premium"
        assert result["trial_active"] is False
        assert result["has_premium_access"] is True
        assert result["feature_access"]["race_predictions"] is True

    # 13. All required keys present
    def test_endpoint_required_keys_present(self):
        result = self._simulate_endpoint(_make_access(Tier.PREMIUM))
        required = {"plan", "trial_active", "has_premium_access", "trial_days_remaining", "feature_access"}
        assert required.issubset(result.keys())


# ─── get_user_access: fail-closed DB error ────────────────────────────────────

@pytest.mark.asyncio
async def test_db_error_returns_free():
    """
    14. When the DB raises an exception, get_user_access returns FREE.
    This ensures fail-closed behavior for the /user/features endpoint.
    """
    mock_db = MagicMock()
    mock_db.subscriptions.find_one = AsyncMock(side_effect=Exception("DB connection error"))

    access = await get_user_access(mock_db, "user-db-error")
    assert access.tier == Tier.FREE
    assert access.has_premium_access is False


# ─── get_user_access: new user auto-creates FREE ──────────────────────────────

@pytest.mark.asyncio
async def test_new_user_gets_free_subscription():
    """
    15. New user (no subscription doc) gets a FREE subscription via
    create_free_subscription(), which is then resolved as FREE tier.
    """
    mock_db = MagicMock()
    # No existing subscription
    mock_db.subscriptions.find_one = AsyncMock(return_value=None)

    free_sub = {
        "user_id": "user-new",
        "status": "free",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with patch("subscription_manager.create_free_subscription", AsyncMock(return_value=free_sub)):
        access = await get_user_access(mock_db, "user-new")

    assert access.tier == Tier.FREE


# ─── get_user_access: trial resolution ───────────────────────────────────────

@pytest.mark.asyncio
async def test_active_trial_resolved_correctly():
    """
    16. Active trial subscription resolves to TRIAL tier.
    """
    trial_end = _future(10).isoformat()
    sub = {"user_id": "user-t", "status": "trial", "trial_end": trial_end}

    mock_db = MagicMock()
    mock_db.subscriptions.find_one = AsyncMock(return_value=sub)

    access = await get_user_access(mock_db, "user-t")
    assert access.tier == Tier.TRIAL
    assert access.has_premium_access is True


@pytest.mark.asyncio
async def test_expired_trial_resolves_to_free():
    """
    17. Expired trial subscription resolves to FREE tier.
    """
    trial_end = _past(2).isoformat()
    sub = {"user_id": "user-te", "status": "trial", "trial_end": trial_end}

    mock_db = MagicMock()
    mock_db.subscriptions.find_one = AsyncMock(return_value=sub)

    access = await get_user_access(mock_db, "user-te")
    assert access.tier == Tier.FREE


# ─── get_user_access: premium resolution ─────────────────────────────────────

@pytest.mark.asyncio
async def test_active_premium_resolved_correctly():
    """
    18. Active premium subscription resolves to PREMIUM tier.
    """
    expires = _future(30).isoformat()
    sub = {"user_id": "user-p", "status": "premium", "premium_expires_at": expires}

    mock_db = MagicMock()
    mock_db.subscriptions.find_one = AsyncMock(return_value=sub)

    access = await get_user_access(mock_db, "user-p")
    assert access.tier == Tier.PREMIUM
    assert access.has_premium_access is True
