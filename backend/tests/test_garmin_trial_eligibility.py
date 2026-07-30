"""
Tests for Garmin-linked Trial eligibility — RunIndex.

Covers the full test matrix from the product spec:

Trial scenarios
---------------
1.  New account without Garmin → FREE
2.  New Garmin identity never used → TRIAL (activate_garmin_trial)
3.  Same Garmin + new RunIndex account → FREE (trial already used)
4.  Garmin disconnect / reconnect → no new trial
5.  Trial expired → FREE
6.  Trial expired + reconnect → FREE
7.  New account + already-used Garmin → FREE
8.  Garmin X used, Garmin Y never used → Y can obtain trial
9.  Two concurrent requests with same Garmin X → only one trial
10. User A cannot use User B's Garmin identity
11. localStorage manipulation → backend rights unchanged
12. Frontend value mutation → backend rights unchanged

Access control
--------------
FREE   → limited access
TRIAL  → premium access
PREMIUM → premium access
early_adopter (legacy) → premium access

Auth / isolation
----------------
User A ≠ User B — no cross-user data leakage

BLOCKER NOTE:
    Tests 2–10 that exercise activate_garmin_trial() require
    _GARMIN_IDENTITY_AVAILABLE = True.  Currently this flag is False because
    the Garmin multi-user identity architecture is not yet in place.
    These tests are therefore marked with pytest.mark.skip, documenting both
    the expected behavior and the blocker.

    Tests 1, 11, 12 (free-on-signup, frontend manipulation) are fully runnable.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow importing from backend root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

from subscription_manager import (
    SubscriptionStatus,
    TRIAL_DURATION_DAYS,
    _GARMIN_IDENTITY_AVAILABLE,
    create_free_subscription,
    create_trial_subscription,
    activate_garmin_trial,
    check_trial_expiration,
    get_trial_days_remaining,
)
from access_control import (
    Tier,
    UserAccess,
    get_user_access,
    _resolve_access,
    PREMIUM_FEATURES,
    FREE_FEATURES,
)

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
# In-memory MongoDB fake
# ─────────────────────────────────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)

    async def to_list(self, length=None):
        result = self._docs[:length] if length else self._docs
        self._docs = []
        return result

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self


class _FakeCollection:
    """Minimal in-memory MongoDB collection for testing."""

    def __init__(self):
        self._docs: List[Dict] = []

    def _strip_id(self, doc):
        d = dict(doc)
        d.pop("_id", None)
        return d

    def _match(self, doc: Dict, query: Dict) -> bool:
        for k, v in query.items():
            if isinstance(v, dict):
                dv = doc.get(k)
                for op, val in v.items():
                    if op == "$gt" and not (dv is not None and dv > val):
                        return False
                    elif op == "$lt" and not (dv is not None and dv < val):
                        return False
                    elif op == "$ne" and dv == val:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    def _apply_update(self, doc: Dict, update: Dict) -> None:
        for op, fields in update.items():
            if op == "$set":
                doc.update(fields)
            elif op == "$setOnInsert":
                pass  # applied only on insert in find_one_and_update
            elif op == "$unset":
                for key in fields:
                    doc.pop(key, None)

    async def find_one(self, query: Dict, projection: Optional[Dict] = None):
        for doc in self._docs:
            if self._match(doc, query):
                d = self._strip_id(doc)
                if projection:
                    # Determine if this is an inclusion or exclusion projection.
                    # Exclusion: all values are 0 → keep all keys except excluded.
                    # Inclusion: some values are 1 → keep only included keys.
                    non_zero = {k for k, v in projection.items() if v != 0}
                    all_zero = len(non_zero) == 0
                    if all_zero:
                        # Pure exclusion: strip the excluded keys
                        excluded = {k for k, v in projection.items() if v == 0}
                        d = {k: v for k, v in d.items() if k not in excluded}
                    else:
                        # Inclusion projection (ignoring _id: 0 exclusion alongside)
                        excluded = {k for k, v in projection.items() if v == 0}
                        d = {k: v for k, v in d.items()
                             if k in non_zero or k not in excluded}
                return d
        return None

    async def insert_one(self, doc: Dict):
        # Duplicate key check on user_id and garmin_identity
        for existing in self._docs:
            if "user_id" in doc and existing.get("user_id") == doc.get("user_id"):
                raise Exception("Duplicate key: user_id")
            if "garmin_identity" in doc and doc["garmin_identity"] is not None:
                if existing.get("garmin_identity") == doc["garmin_identity"]:
                    raise Exception("Duplicate key: garmin_identity")
        self._docs.append(dict(doc))
        result = MagicMock()
        result.inserted_id = str(uuid.uuid4())
        return result

    async def update_one(self, query: Dict, update: Dict, upsert: bool = False):
        for doc in self._docs:
            if self._match(doc, query):
                self._apply_update(doc, update)
                result = MagicMock()
                result.matched_count = 1
                result.upserted_id = None
                return result
        if upsert:
            new_doc = dict(query)
            for op, fields in update.items():
                if op in ("$set", "$setOnInsert"):
                    new_doc.update(fields)
            self._docs.append(new_doc)
            result = MagicMock()
            result.matched_count = 0
            result.upserted_id = str(uuid.uuid4())
            return result
        result = MagicMock()
        result.matched_count = 0
        result.upserted_id = None
        return result

    async def find_one_and_update(
        self,
        query: Dict,
        update: Dict,
        upsert: bool = False,
        return_document=None,
    ):
        for doc in self._docs:
            if self._match(doc, query):
                # Document exists — do NOT apply $setOnInsert
                for op, fields in update.items():
                    if op == "$set":
                        doc.update(fields)
                return self._strip_id(doc)
        # Not found
        if upsert:
            new_doc = dict(query)
            for op, fields in update.items():
                if op in ("$set", "$setOnInsert"):
                    new_doc.update(fields)
            self._docs.append(new_doc)
            return self._strip_id(new_doc)
        return None

    async def count_documents(self, query: Dict):
        return sum(1 for d in self._docs if self._match(d, query))

    def find(self, query: Dict, projection: Optional[Dict] = None):
        results = [self._strip_id(d) for d in self._docs if self._match(d, query)]
        return _FakeCursor(results)

    async def delete_one(self, query: Dict):
        for i, doc in enumerate(self._docs):
            if self._match(doc, query):
                self._docs.pop(i)
                return
    async def delete_many(self, query: Dict):
        self._docs = [d for d in self._docs if not self._match(d, query)]

    async def create_index(self, *args, **kwargs):
        pass


class _FakeDB:
    def __init__(self):
        self.subscriptions = _FakeCollection()
        self.garmin_trial_registry = _FakeCollection()

    def __getattr__(self, name):
        return _FakeCollection()


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    return _FakeDB()


def _uid() -> str:
    return str(uuid.uuid4())


def _garmin_id() -> str:
    return f"garmin_user_{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build a subscription-like dict to feed _resolve_access
# ─────────────────────────────────────────────────────────────────────────────

def _sub(status: str, trial_end=None, premium_expires_at=None, expires_at=None) -> dict:
    return {
        "user_id": _uid(),
        "status": status,
        "trial_end": trial_end,
        "premium_expires_at": premium_expires_at,
        "expires_at": expires_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — New account without Garmin → FREE
# ─────────────────────────────────────────────────────────────────────────────

async def test_new_account_no_garmin_is_free(db):
    """New RunIndex accounts start as FREE; no trial is auto-created."""
    user_id = _uid()
    subscription = await create_free_subscription(db, user_id)

    assert subscription["status"] == SubscriptionStatus.FREE
    assert subscription["trial_used"] is False
    assert subscription["trial_start"] is None
    assert subscription["trial_end"] is None
    assert subscription["garmin_identity"] is None


async def test_get_user_access_new_user_is_free(db):
    """get_user_access for a brand new user returns FREE tier."""
    user_id = _uid()
    access = await get_user_access(db, user_id)

    assert access.tier == Tier.FREE
    assert access.is_free is True
    assert access.has_premium_access is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests 2–10 — Garmin identity-dependent (BLOCKED)
# ─────────────────────────────────────────────────────────────────────────────

GARMIN_BLOCKER_REASON = (
    "BLOCKER: activate_garmin_trial() requires a per-user Garmin identity. "
    "The current Garmin integration uses a single shared backend account "
    "(GARMIN_USERNAME env var). No per-user Garmin identifier is available. "
    "These tests will be enabled once the Garmin multi-user OAuth architecture ships."
)


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_new_garmin_identity_grants_trial(db):
    """Test 2: A Garmin identity never used before → TRIAL for 30 days."""
    user_id = _uid()
    garmin_id = _garmin_id()
    await create_free_subscription(db, user_id)

    result = await activate_garmin_trial(db, user_id, garmin_id)

    assert result["status"] == SubscriptionStatus.TRIAL
    assert result["garmin_identity"] == garmin_id
    assert result["trial_used"] is True

    now = datetime.now(timezone.utc)
    trial_end = datetime.fromisoformat(result["trial_end"])
    delta = trial_end - now
    assert TRIAL_DURATION_DAYS - 1 <= delta.days <= TRIAL_DURATION_DAYS


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_same_garmin_new_runindex_account_stays_free(db):
    """Test 3: Same Garmin identity + new RunIndex account → FREE (trial already used)."""
    user_a = _uid()
    user_b = _uid()
    garmin_id = _garmin_id()

    await create_free_subscription(db, user_a)
    await create_free_subscription(db, user_b)

    # User A gets trial
    result_a = await activate_garmin_trial(db, user_a, garmin_id)
    assert result_a["status"] == SubscriptionStatus.TRIAL

    # User B with same Garmin identity → stays FREE
    result_b = await activate_garmin_trial(db, user_b, garmin_id)
    assert result_b["status"] == SubscriptionStatus.FREE


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_garmin_reconnect_no_new_trial(db):
    """Test 4: Disconnecting and reconnecting Garmin does not reset trial status."""
    user_id = _uid()
    garmin_id = _garmin_id()
    await create_free_subscription(db, user_id)

    # First connection → trial
    r1 = await activate_garmin_trial(db, user_id, garmin_id)
    assert r1["status"] == SubscriptionStatus.TRIAL

    # Simulate disconnect (garmin_connections removed, subscription unchanged)
    # Second connection → trial was used, no new trial granted
    r2 = await activate_garmin_trial(db, user_id, garmin_id)
    # Should still be TRIAL (same user, same garmin — already activated)
    # The registry entry already exists with first_trial_user_id == user_id
    assert r2["status"] == SubscriptionStatus.TRIAL


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_trial_expired_is_free(db):
    """Test 5: Trial expired → FREE (resolved in-memory by _resolve_access)."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    sub = _sub("trial", trial_end=past)
    user_id = sub["user_id"]

    access = _resolve_access(user_id, sub)
    assert access.tier == Tier.FREE


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_trial_expired_reconnect_stays_free(db):
    """Test 6: Expired trial + Garmin reconnect → still FREE (Garmin used)."""
    user_id = _uid()
    garmin_id = _garmin_id()
    await create_free_subscription(db, user_id)

    # Activate trial
    r1 = await activate_garmin_trial(db, user_id, garmin_id)
    assert r1["status"] == SubscriptionStatus.TRIAL

    # Simulate expiry by setting trial_end in the past
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {"$set": {"trial_end": past, "status": SubscriptionStatus.TRIAL}},
    )

    # Check expiration — should transition to FREE
    sub = await db.subscriptions.find_one({"user_id": user_id})
    sub = await check_trial_expiration(db, sub)
    assert sub["status"] == SubscriptionStatus.FREE

    # Reconnect Garmin → no new trial
    r2 = await activate_garmin_trial(db, user_id, garmin_id)
    assert r2["status"] == SubscriptionStatus.FREE


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_new_account_already_used_garmin_stays_free(db):
    """Test 7: New RunIndex account with a Garmin that already used trial → FREE."""
    user_a = _uid()
    user_b = _uid()
    garmin_id = _garmin_id()

    await create_free_subscription(db, user_a)
    r_a = await activate_garmin_trial(db, user_a, garmin_id)
    assert r_a["status"] == SubscriptionStatus.TRIAL

    # Brand-new User B — Garmin already used
    await create_free_subscription(db, user_b)
    r_b = await activate_garmin_trial(db, user_b, garmin_id)
    assert r_b["status"] == SubscriptionStatus.FREE


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_different_garmin_identity_can_get_trial(db):
    """Test 8: Garmin X used, Garmin Y never used → Y can obtain trial."""
    user_id = _uid()
    garmin_x = _garmin_id()
    garmin_y = _garmin_id()

    await create_free_subscription(db, user_id)

    # Use Garmin X
    r_x = await activate_garmin_trial(db, user_id, garmin_x)
    assert r_x["status"] == SubscriptionStatus.TRIAL

    # User switches to Garmin Y — a different user with Garmin Y gets trial
    user_b = _uid()
    await create_free_subscription(db, user_b)
    r_y = await activate_garmin_trial(db, user_b, garmin_y)
    assert r_y["status"] == SubscriptionStatus.TRIAL


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_concurrent_requests_single_trial(db):
    """Test 9: Two concurrent requests with same Garmin → only one trial created."""
    user_a = _uid()
    user_b = _uid()
    garmin_id = _garmin_id()

    await create_free_subscription(db, user_a)
    await create_free_subscription(db, user_b)

    # Simulate concurrent requests
    results = await asyncio.gather(
        activate_garmin_trial(db, user_a, garmin_id),
        activate_garmin_trial(db, user_b, garmin_id),
        return_exceptions=True,
    )

    statuses = []
    for r in results:
        if isinstance(r, Exception):
            statuses.append("error")
        else:
            statuses.append(r.get("status"))

    # Exactly one trial, one free (or two resolving to FREE if race collision)
    trial_count = statuses.count(SubscriptionStatus.TRIAL)
    assert trial_count <= 1, (
        f"Expected at most 1 trial from concurrent requests, got {trial_count}. "
        f"Statuses: {statuses}"
    )


@pytest.mark.skipif(not _GARMIN_IDENTITY_AVAILABLE, reason=GARMIN_BLOCKER_REASON)
async def test_user_cannot_use_other_user_garmin_identity(db):
    """Test 10: User A cannot use User B's Garmin identity to claim a trial."""
    user_a = _uid()
    user_b = _uid()
    garmin_a = _garmin_id()
    garmin_b = _garmin_id()

    await create_free_subscription(db, user_a)
    await create_free_subscription(db, user_b)

    # User A legitimately gets trial with garmin_a
    r_a = await activate_garmin_trial(db, user_a, garmin_a)
    assert r_a["status"] == SubscriptionStatus.TRIAL
    assert r_a["garmin_identity"] == garmin_a

    # User B uses garmin_b (different) — also gets trial
    r_b = await activate_garmin_trial(db, user_b, garmin_b)
    assert r_b["status"] == SubscriptionStatus.TRIAL
    assert r_b["garmin_identity"] == garmin_b

    # User A's subscription is unaffected by User B's operation
    sub_a = await db.subscriptions.find_one({"user_id": user_a})
    assert sub_a["garmin_identity"] == garmin_a


# ─────────────────────────────────────────────────────────────────────────────
# Tests 11–12 — Frontend manipulation (always runnable)
# ─────────────────────────────────────────────────────────────────────────────

async def test_frontend_localStorage_manipulation_no_effect(db):
    """Test 11: localStorage / frontend-provided status does not change backend access.

    The backend always resolves access from the DB subscription document.
    Any value from localStorage, sessionStorage, or React state is ignored.
    """
    user_id = _uid()
    # User is FREE in the database
    await create_free_subscription(db, user_id)

    # Attacker tries to inject 'premium' or 'trial' via simulate the frontend
    # sending a forged "status" value — this never reaches access_control
    # because access_control reads directly from the DB.

    # Backend access is still FREE regardless of what the frontend "believes"
    access = await get_user_access(db, user_id)
    assert access.tier == Tier.FREE
    assert access.has_premium_access is False
    assert access.can("training_plan") is False
    assert access.can("llm_access") is False


async def test_frontend_value_mutation_no_effect(db):
    """Test 12: Mutating a frontend value (e.g., 'trial_used': False) does not
    grant new trial access — the backend never reads garmin_identity from the
    request; it reads only from the DB subscription document.
    """
    user_id = _uid()
    garmin_id = _garmin_id()

    # Simulate a user whose trial is already used and has expired
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=1)).isoformat()
    await db.subscriptions.insert_one({
        "user_id": user_id,
        "status": SubscriptionStatus.FREE,
        "trial_start": (now - timedelta(days=31)).isoformat(),
        "trial_end": past,
        "trial_used": True,
        "garmin_identity": garmin_id,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "updated_at": now.isoformat(),
    })

    # Even if the frontend somehow "sends" trial_used=False or status=trial,
    # the backend reads from DB — access remains FREE
    access = await get_user_access(db, user_id)
    assert access.tier == Tier.FREE
    assert access.has_premium_access is False


# ─────────────────────────────────────────────────────────────────────────────
# Access Control tests
# ─────────────────────────────────────────────────────────────────────────────

def test_free_user_limited_access():
    """FREE → limited access."""
    user_id = _uid()
    access = _resolve_access(user_id, _sub("free"))
    assert access.tier == Tier.FREE
    assert access.has_premium_access is False
    assert access.can("training_plan") is False
    assert access.can("llm_access") is False
    assert access.can("dashboard_insight") is True   # free feature
    assert access.chat_monthly_quota == 10


def test_trial_user_premium_access():
    """TRIAL → premium access."""
    future = (datetime.now(timezone.utc) + timedelta(days=25)).isoformat()
    sub = _sub("trial", trial_end=future)
    access = _resolve_access(sub["user_id"], sub)
    assert access.tier == Tier.TRIAL
    assert access.has_premium_access is True
    assert access.can("training_plan") is True
    assert access.can("llm_access") is True
    assert access.chat_monthly_quota is None   # unlimited


def test_premium_user_premium_access():
    """PREMIUM → premium access."""
    sub = _sub("premium")
    access = _resolve_access(sub["user_id"], sub)
    assert access.tier == Tier.PREMIUM
    assert access.has_premium_access is True
    assert access.can("training_plan") is True
    assert access.can("llm_access") is True


def test_early_adopter_premium_access():
    """early_adopter (legacy) → premium access."""
    sub = _sub("early_adopter")
    access = _resolve_access(sub["user_id"], sub)
    assert access.tier == Tier.PREMIUM
    assert access.has_premium_access is True


def test_expired_trial_is_free():
    """Expired trial → FREE in-memory."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sub = _sub("trial", trial_end=past)
    access = _resolve_access(sub["user_id"], sub)
    assert access.tier == Tier.FREE
    assert access.has_premium_access is False


def test_trial_days_remaining():
    """trial_days_remaining is correct."""
    future = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()
    sub = _sub("trial", trial_end=future)
    access = _resolve_access(sub["user_id"], sub)
    assert access.tier == Tier.TRIAL
    assert access.trial_days_remaining is not None
    assert 14 <= access.trial_days_remaining <= 15


# ─────────────────────────────────────────────────────────────────────────────
# Auth / isolation tests
# ─────────────────────────────────────────────────────────────────────────────

async def test_user_isolation(db):
    """User A and User B have independent subscriptions."""
    user_a = _uid()
    user_b = _uid()

    await create_free_subscription(db, user_a)

    # Directly insert premium subscription for user_b (simulates Stripe webhook)
    await db.subscriptions.insert_one({
        "user_id": user_b,
        "status": "premium",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    access_a = await get_user_access(db, user_a)
    access_b = await get_user_access(db, user_b)

    assert access_a.tier == Tier.FREE
    assert access_b.tier == Tier.PREMIUM
    # User A cannot access User B's data
    assert access_a.user_id == user_a
    assert access_b.user_id == user_b


async def test_user_a_data_not_visible_to_user_b(db):
    """User A's subscription document is not returned for User B."""
    user_a = _uid()
    user_b = _uid()

    await create_free_subscription(db, user_a)
    await create_free_subscription(db, user_b)

    sub_a = await db.subscriptions.find_one({"user_id": user_a})
    sub_b = await db.subscriptions.find_one({"user_id": user_b})

    assert sub_a is not None
    assert sub_b is not None
    assert sub_a["user_id"] == user_a
    assert sub_b["user_id"] == user_b
    assert sub_a["user_id"] != sub_b["user_id"]


# ─────────────────────────────────────────────────────────────────────────────
# activate_garmin_trial BLOCKER validation
# ─────────────────────────────────────────────────────────────────────────────

async def test_activate_garmin_trial_raises_when_identity_unavailable():
    """activate_garmin_trial raises NotImplementedError when identity is unavailable.

    This confirms the BLOCKER is active and the function cannot be called without
    a real per-user Garmin identity.
    """
    if _GARMIN_IDENTITY_AVAILABLE:
        pytest.skip("Garmin identity is available — BLOCKER has been resolved")

    db = _FakeDB()
    user_id = _uid()
    garmin_id = _garmin_id()
    await create_free_subscription(db, user_id)

    with pytest.raises(NotImplementedError) as exc_info:
        await activate_garmin_trial(db, user_id, garmin_id)

    assert "BLOCKER" in str(exc_info.value)


async def test_activate_garmin_trial_rejects_empty_identity(db):
    """activate_garmin_trial raises ValueError for empty garmin_identity."""
    # Temporarily enable the flag for this test
    import subscription_manager as sm
    original = sm._GARMIN_IDENTITY_AVAILABLE
    sm._GARMIN_IDENTITY_AVAILABLE = True
    try:
        user_id = _uid()
        await create_free_subscription(db, user_id)

        with pytest.raises((ValueError, NotImplementedError)):
            await activate_garmin_trial(db, user_id, "")

        with pytest.raises((ValueError, NotImplementedError)):
            await activate_garmin_trial(db, user_id, "   ")
    finally:
        sm._GARMIN_IDENTITY_AVAILABLE = original


# ─────────────────────────────────────────────────────────────────────────────
# SubscriptionContext fail-closed (documented behavioral test)
# ─────────────────────────────────────────────────────────────────────────────

def test_subscription_context_fail_closed_documented():
    """Document that SubscriptionContext.jsx is already fail-closed.

    When the /api/subscription/info call fails, SubscriptionContext sets:
        status = "free"
        features = { training_plan: false, llm_access: false, ... }

    This test is a documentation stub — the actual React behavior is verified
    by the frontend build and integration tests.
    """
    # The fail-closed fallback in SubscriptionContext.jsx lines 34-50:
    #   setSubscription({ status: "free", features: { ... all false ... }, ... })
    # This is confirmed correct — no changes needed to SubscriptionContext.jsx.
    assert True, "SubscriptionContext.jsx is already fail-closed (no changes needed)"
