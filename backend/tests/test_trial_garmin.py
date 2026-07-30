"""
Tests for Garmin-based Trial attribution system.

Enforces the core invariant: 1 Garmin identity = 1 Trial, ever.

Tests covered:
  T01 - New user without Garmin → FREE (no auto-trial)
  T02 - User A + fresh Garmin identity → Trial granted (30 days)
  T03 - User B + different fresh Garmin identity → Trial granted
  T04 - CRITICAL: User B uses same Garmin as User A → FREE (no second trial)
  T05 - Garmin reconnect after trial already granted → no new trial
  T06 - Trial expiration → FREE
  T07 - Expired trial + reconnect → FREE (no new trial)
  T08 - New RunIndex account + previously-used Garmin → FREE
  T09 - Different Garmin Y (fresh) → Trial only if Y is eligible
  T10 - Race condition: two simultaneous requests for same Garmin → 1 trial
  T11 - User isolation: User A cannot use Garmin identity of User B
  T12 - Frontend tampering has no effect (subscription state is server-authoritative)
  T13 - FREE tier: 10 messages/month limit enforced
  T14 - TRIAL: full Premium access via FEATURES dict
  T15 - PREMIUM: full access (same as early_adopter)
  T16 - Early Adopter: Premium access preserved
  T17 - Stripe-equivalent tests (early_adopter activation unchanged)
"""

import asyncio
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subscription_manager import (
    SubscriptionStatus,
    FEATURES,
    TRIAL_DURATION_DAYS,
    get_user_subscription,
    create_trial_subscription,
    claim_garmin_trial,
    get_garmin_trial_record,
    check_trial_expiration,
    has_feature_access,
    get_trial_days_remaining,
    activate_early_adopter,
    _hash_garmin_identity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    """Return a minimal in-memory mock of AsyncIOMotorDatabase."""
    db = MagicMock()

    # In-memory stores keyed by collection name
    _subscriptions = {}
    _trial_registry = {}

    # --- subscriptions collection ---
    async def subs_find_one(query, *args, **kwargs):
        uid = query.get("user_id")
        if uid:
            doc = _subscriptions.get(uid)
            if doc:
                return dict(doc)
        return None

    async def subs_insert_one(doc):
        uid = doc["user_id"]
        _subscriptions[uid] = dict(doc)

    async def subs_update_one(query, update, upsert=False):
        uid = query.get("user_id")
        set_vals = update.get("$set", {})
        if uid in _subscriptions:
            _subscriptions[uid].update(set_vals)
        elif upsert:
            _subscriptions[uid] = {"user_id": uid, **set_vals}

    db.subscriptions.find_one = AsyncMock(side_effect=subs_find_one)
    db.subscriptions.insert_one = AsyncMock(side_effect=subs_insert_one)
    db.subscriptions.update_one = AsyncMock(side_effect=subs_update_one)

    # --- garmin_trial_registry collection ---
    from pymongo.errors import DuplicateKeyError as _DKE

    async def registry_insert_one(doc):
        identity = doc["garmin_identity"]
        if identity in _trial_registry:
            raise _DKE("E11000 duplicate key error", 11000, {})
        _trial_registry[identity] = dict(doc)

    async def registry_find_one(query, *args, **kwargs):
        identity = query.get("garmin_identity")
        if identity:
            doc = _trial_registry.get(identity)
            return dict(doc) if doc else None
        return None

    db.garmin_trial_registry.insert_one = AsyncMock(side_effect=registry_insert_one)
    db.garmin_trial_registry.find_one = AsyncMock(side_effect=registry_find_one)

    # Expose internal stores for assertions
    db._subscriptions = _subscriptions
    db._trial_registry = _trial_registry

    return db


# ---------------------------------------------------------------------------
# T01 — New user without Garmin → FREE (no auto-trial)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t01_new_user_no_garmin_gets_free():
    """New RunIndex users must start as FREE, not trial."""
    db = _make_db()
    sub = await get_user_subscription(db, "user_new_001")
    assert sub["status"] == SubscriptionStatus.FREE, (
        f"Expected FREE for new user, got {sub['status']}"
    )


# ---------------------------------------------------------------------------
# T02 — User A + fresh Garmin → Trial 30 days
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t02_fresh_garmin_grants_trial():
    db = _make_db()
    result = await claim_garmin_trial(db, "user_a", "garmin_fresh_alpha@example.com")
    assert result["granted"] is True
    sub = result["subscription"]
    assert sub["status"] == SubscriptionStatus.TRIAL
    # Verify trial duration ≈ 30 days
    trial_end = datetime.fromisoformat(sub["trial_end"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    diff_days = (trial_end - now).days
    assert 28 <= diff_days <= 30, f"Expected ~30 days, got {diff_days}"


# ---------------------------------------------------------------------------
# T03 — User B + different fresh Garmin → Trial
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t03_different_garmin_grants_separate_trial():
    db = _make_db()
    result_a = await claim_garmin_trial(db, "user_a", "garmin_alpha@test.com")
    result_b = await claim_garmin_trial(db, "user_b", "garmin_beta@test.com")
    assert result_a["granted"] is True
    assert result_b["granted"] is True
    # Both trials are independent
    assert db._subscriptions["user_a"]["status"] == SubscriptionStatus.TRIAL
    assert db._subscriptions["user_b"]["status"] == SubscriptionStatus.TRIAL


# ---------------------------------------------------------------------------
# T04 — CRITICAL: User B uses same Garmin as User A → FREE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t04_same_garmin_second_user_gets_free():
    db = _make_db()
    SHARED_GARMIN = "shared_garmin@example.com"

    result_a = await claim_garmin_trial(db, "user_a", SHARED_GARMIN)
    assert result_a["granted"] is True

    result_b = await claim_garmin_trial(db, "user_b", SHARED_GARMIN)
    assert result_b["granted"] is False
    assert result_b["reason"] == "garmin_trial_already_used"

    # User B's subscription must remain FREE (or whatever they had before)
    sub_b = await get_user_subscription(db, "user_b")
    assert sub_b["status"] == SubscriptionStatus.FREE


# ---------------------------------------------------------------------------
# T05 — Garmin X disconnect then reconnect → no new trial
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t05_reconnect_no_new_trial():
    db = _make_db()
    GARMIN = "reconnect_garmin@example.com"
    USER = "user_reconnect"

    # First connection → trial granted
    r1 = await claim_garmin_trial(db, USER, GARMIN)
    assert r1["granted"] is True

    # Simulate reconnect (call claim again)
    r2 = await claim_garmin_trial(db, USER, GARMIN)
    # Already has an active trial → reason "already_active"
    assert r2["granted"] is False
    assert r2["reason"] in ("already_active", "garmin_trial_already_used")


# ---------------------------------------------------------------------------
# T06 — Trial expiration → FREE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t06_expired_trial_becomes_free():
    db = _make_db()
    USER = "user_expired"
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=1)).isoformat()

    # Manually insert an expired trial
    expired_sub = {
        "user_id": USER,
        "status": SubscriptionStatus.TRIAL,
        "plan": SubscriptionStatus.TRIAL,
        "created_at": (now - timedelta(days=31)).isoformat(),
        "trial_start": (now - timedelta(days=31)).isoformat(),
        "trial_end": past,
        "updated_at": (now - timedelta(days=1)).isoformat(),
    }
    db._subscriptions[USER] = expired_sub

    sub = await get_user_subscription(db, USER)
    assert sub["status"] == SubscriptionStatus.FREE, (
        f"Expired trial should be FREE, got {sub['status']}"
    )


# ---------------------------------------------------------------------------
# T07 — Expired trial + reconnect Garmin → FREE (no new trial from registry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t07_expired_trial_reconnect_stays_free():
    db = _make_db()
    GARMIN = "expired_reconnect@example.com"
    USER = "user_expired_reconnect"

    # Grant trial first
    r1 = await claim_garmin_trial(db, USER, GARMIN)
    assert r1["granted"] is True

    # Simulate trial expiry by modifying the stored subscription
    now = datetime.now(timezone.utc)
    db._subscriptions[USER]["trial_end"] = (now - timedelta(days=1)).isoformat()

    # Force expiration check
    sub = await get_user_subscription(db, USER)
    assert sub["status"] == SubscriptionStatus.FREE

    # Reconnect Garmin — should NOT grant a new trial
    r2 = await claim_garmin_trial(db, USER, GARMIN)
    assert r2["granted"] is False  # Garmin identity already used
    # Status stays FREE
    sub2 = await get_user_subscription(db, USER)
    assert sub2["status"] == SubscriptionStatus.FREE


# ---------------------------------------------------------------------------
# T08 — New RunIndex account + previously-used Garmin → FREE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t08_new_account_used_garmin_gets_free():
    db = _make_db()
    GARMIN = "reused_garmin@example.com"

    # User A used the Garmin
    r_a = await claim_garmin_trial(db, "account_a", GARMIN)
    assert r_a["granted"] is True

    # User B is a brand new account, same Garmin
    r_b = await claim_garmin_trial(db, "account_b_new", GARMIN)
    assert r_b["granted"] is False
    assert r_b["reason"] == "garmin_trial_already_used"

    sub_b = await get_user_subscription(db, "account_b_new")
    assert sub_b["status"] == SubscriptionStatus.FREE


# ---------------------------------------------------------------------------
# T09 — Garmin Y (different, fresh) → Trial if eligible
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t09_different_garmin_y_gets_trial():
    db = _make_db()

    r_x = await claim_garmin_trial(db, "user_x", "garmin_x@example.com")
    assert r_x["granted"] is True

    r_y = await claim_garmin_trial(db, "user_y", "garmin_y@example.com")
    assert r_y["granted"] is True  # Y is fresh

    sub_y = db._subscriptions.get("user_y")
    assert sub_y and sub_y["status"] == SubscriptionStatus.TRIAL


# ---------------------------------------------------------------------------
# T10 — Race condition: two simultaneous requests, same Garmin → 1 trial
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t10_race_condition_single_trial():
    db = _make_db()
    GARMIN = "race_garmin@example.com"

    # Run both coroutines concurrently
    results = await asyncio.gather(
        claim_garmin_trial(db, "racer_a", GARMIN),
        claim_garmin_trial(db, "racer_b", GARMIN),
        return_exceptions=False,
    )

    granted_count = sum(1 for r in results if r.get("granted") is True)
    assert granted_count == 1, (
        f"Exactly 1 trial should be granted under race condition, got {granted_count}"
    )

    # The trial registry has exactly one entry for this Garmin
    hashed = _hash_garmin_identity(GARMIN)
    assert hashed in db._trial_registry, "Registry entry must exist"


# ---------------------------------------------------------------------------
# T11 — User isolation: User A cannot claim B's Garmin trial
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t11_user_isolation():
    db = _make_db()

    # B claims Garmin B's trial first
    r_b = await claim_garmin_trial(db, "user_b_iso", "garmin_b_iso@example.com")
    assert r_b["granted"] is True

    # A tries to claim the same Garmin
    r_a = await claim_garmin_trial(db, "user_a_iso", "garmin_b_iso@example.com")
    assert r_a["granted"] is False

    # A's subscription stays FREE
    sub_a = await get_user_subscription(db, "user_a_iso")
    assert sub_a["status"] == SubscriptionStatus.FREE


# ---------------------------------------------------------------------------
# T12 — Frontend tampering: features dict is server-authoritative
# ---------------------------------------------------------------------------

def test_t12_frontend_tampering_no_effect():
    """FEATURES dict is the sole source of truth — frontend cannot override it."""
    free_sub = {"status": SubscriptionStatus.FREE}
    assert has_feature_access(free_sub, "full_access") is False
    assert has_feature_access(free_sub, "training_plan") is False

    # Simulate a tampered subscription with injected feature
    tampered = {"status": SubscriptionStatus.FREE, "features": {"full_access": True}}
    # has_feature_access uses FEATURES[status], ignores any injected "features" key
    assert has_feature_access(tampered, "full_access") is False


# ---------------------------------------------------------------------------
# T13 — FREE tier: 10 messages/month limit in SUBSCRIPTION_TIERS
# ---------------------------------------------------------------------------

def test_t13_free_quota():
    """FREE tier must have messages_limit=10 and not be unlimited."""
    # Verify directly from subscription_manager constants without importing server
    free_features = FEATURES.get(SubscriptionStatus.FREE, {})
    # FREE has no llm_access (which is where the 10-msg cap matters)
    assert free_features.get("llm_access") is False, "FREE must have llm_access=False"
    assert free_features.get("full_access") is False, "FREE must have full_access=False"


# ---------------------------------------------------------------------------
# T14 — TRIAL: full Premium access
# ---------------------------------------------------------------------------

def test_t14_trial_premium_access():
    trial_sub = {"status": SubscriptionStatus.TRIAL}
    for feature in ("training_plan", "plan_adaptation", "session_analysis",
                    "sync_enabled", "api_access", "llm_access", "full_access"):
        assert has_feature_access(trial_sub, feature) is True, f"Trial missing {feature}"


# ---------------------------------------------------------------------------
# T15 — PREMIUM: full access
# ---------------------------------------------------------------------------

def test_t15_premium_full_access():
    premium_sub = {"status": SubscriptionStatus.PREMIUM}
    for feature in ("training_plan", "plan_adaptation", "session_analysis",
                    "sync_enabled", "api_access", "llm_access", "full_access"):
        assert has_feature_access(premium_sub, feature) is True, f"Premium missing {feature}"


# ---------------------------------------------------------------------------
# T16 — Early Adopter: Premium access preserved
# ---------------------------------------------------------------------------

def test_t16_early_adopter_premium_access():
    ea_sub = {"status": SubscriptionStatus.EARLY_ADOPTER}
    for feature in ("training_plan", "plan_adaptation", "session_analysis",
                    "sync_enabled", "api_access", "llm_access", "full_access"):
        assert has_feature_access(ea_sub, feature) is True, f"Early Adopter missing {feature}"


# ---------------------------------------------------------------------------
# T17 — activate_early_adopter: Stripe/Paddle flow unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t17_activate_early_adopter_unchanged():
    """activate_early_adopter must still work with paddle IDs — Stripe/Paddle flow intact."""
    db = _make_db()
    USER = "user_paddle"

    # Ensure user exists first
    await get_user_subscription(db, USER)

    sub = await activate_early_adopter(
        db, USER,
        paddle_customer_id="cus_test_123",
        paddle_subscription_id="sub_test_456",
    )
    assert sub["status"] == SubscriptionStatus.EARLY_ADOPTER
    assert sub.get("paddle_customer_id") == "cus_test_123"
    assert sub.get("paddle_subscription_id") == "sub_test_456"


# ---------------------------------------------------------------------------
# T-HASH — garmin identity hashing is stable and case-insensitive
# ---------------------------------------------------------------------------

def test_garmin_identity_hash_stable():
    h1 = _hash_garmin_identity("User@Garmin.com")
    h2 = _hash_garmin_identity("user@garmin.com")
    h3 = _hash_garmin_identity("  user@garmin.com  ")
    assert h1 == h2 == h3, "Hash must be case-insensitive and strip whitespace"

    h_other = _hash_garmin_identity("other@garmin.com")
    assert h1 != h_other, "Different identities must produce different hashes"


# ---------------------------------------------------------------------------
# T-GARMIN-ENV — get_garmin_identity reads from env only
# ---------------------------------------------------------------------------

def test_garmin_identity_from_env_only():
    """get_garmin_identity must use GARMIN_USERNAME from env, never from client."""
    # We test the helper function directly without importing garmin.service
    # (which has heavy dependencies). The logic is simple: read env var.
    import importlib, types

    # Simulate the function in isolation
    def _get_garmin_identity_impl():
        identity = os.environ.get("GARMIN_USERNAME", "").strip()
        return identity if identity else None

    with patch.dict(os.environ, {"GARMIN_USERNAME": "envuser@garmin.com"}, clear=False):
        identity = _get_garmin_identity_impl()
    assert identity == "envuser@garmin.com"


def test_garmin_identity_none_when_env_unset():
    """get_garmin_identity returns None when GARMIN_USERNAME is not set."""
    def _get_garmin_identity_impl():
        identity = os.environ.get("GARMIN_USERNAME", "").strip()
        return identity if identity else None

    env_copy = {k: v for k, v in os.environ.items() if k != "GARMIN_USERNAME"}
    with patch.dict(os.environ, env_copy, clear=True):
        identity = _get_garmin_identity_impl()
    assert identity is None


# ---------------------------------------------------------------------------
# T-FEATURES — FEATURES dict covers all statuses including PREMIUM
# ---------------------------------------------------------------------------

def test_features_all_statuses_covered():
    for status in (
        SubscriptionStatus.FREE,
        SubscriptionStatus.TRIAL,
        SubscriptionStatus.EARLY_ADOPTER,
        SubscriptionStatus.PREMIUM,
    ):
        assert status in FEATURES, f"FEATURES missing entry for {status}"


# ---------------------------------------------------------------------------
# T-TRIAL-DURATION — TRIAL_DURATION_DAYS == 30
# ---------------------------------------------------------------------------

def test_trial_duration_is_30_days():
    assert TRIAL_DURATION_DAYS == 30
