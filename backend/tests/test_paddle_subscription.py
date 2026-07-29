"""
test_paddle_subscription.py
============================

Tests for Paddle Billing integration, subscription lifecycle, and security.

Coverage:
    - Paddle webhook HMAC-SHA256 signature verification
    - Webhook without signature → rejected
    - Webhook with invalid signature → rejected
    - Webhook with tampered body → rejected
    - access_control: Trial 30-day tier resolution
    - access_control: Free tier (fail-closed)
    - access_control: Premium tier (canonical + legacy)
    - access_control: Expiration (trial + premium)
    - access_control: User isolation
    - access_control: Feature gating (fail-closed on unknown)
    - access_control: Chat quota
    - Subscription manager: CRUD via mocked DB (motor not required)
    - verify-checkout endpoint returns 410 (frontend cannot grant Premium)
    - SubscriptionContext.jsx fail-closed (status=free on error)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone, timedelta

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Paddle webhook security — pure HMAC-SHA256, no heavy deps
# ═══════════════════════════════════════════════════════════════════════════════

from services.paddle_webhook_security import (
    PaddleWebhookError,
    verify_and_parse_paddle_event,
)


def _make_sig(secret: str, ts: str, body: bytes) -> str:
    """Build a valid Paddle-Signature header value."""
    payload = f"{ts}:{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


class TestPaddleWebhookSecurity:
    SECRET = "test_paddle_secret_abc123xyz"

    def _body(self, event_type="subscription.activated") -> bytes:
        return json.dumps({"event_type": event_type, "event_id": str(uuid.uuid4())}).encode()

    def test_valid_signature_returns_event(self):
        body = self._body()
        ts = str(int(time.time()))
        sig = _make_sig(self.SECRET, ts, body)
        event = verify_and_parse_paddle_event(body, sig, self.SECRET)
        assert isinstance(event, dict)
        assert event["event_type"] == "subscription.activated"

    def test_missing_signature_raises(self):
        with pytest.raises(PaddleWebhookError, match="Missing"):
            verify_and_parse_paddle_event(self._body(), "", self.SECRET)

    def test_none_signature_raises(self):
        with pytest.raises(PaddleWebhookError, match="Missing"):
            verify_and_parse_paddle_event(self._body(), None, self.SECRET)

    def test_wrong_signature_raises(self):
        body = self._body()
        ts = str(int(time.time()))
        bad_sig = f"ts={ts};h1=" + "a" * 64
        with pytest.raises(PaddleWebhookError, match="mismatch"):
            verify_and_parse_paddle_event(body, bad_sig, self.SECRET)

    def test_tampered_body_raises(self):
        original = self._body("subscription.activated")
        ts = str(int(time.time()))
        sig = _make_sig(self.SECRET, ts, original)
        tampered = original.replace(b"subscription.activated", b"subscription.cancelled")
        with pytest.raises(PaddleWebhookError, match="mismatch"):
            verify_and_parse_paddle_event(tampered, sig, self.SECRET)

    def test_wrong_secret_raises(self):
        body = self._body()
        ts = str(int(time.time()))
        sig = _make_sig("WRONG_SECRET", ts, body)
        with pytest.raises(PaddleWebhookError, match="mismatch"):
            verify_and_parse_paddle_event(body, sig, self.SECRET)

    def test_malformed_header_raises(self):
        with pytest.raises(PaddleWebhookError, match="Malformed"):
            verify_and_parse_paddle_event(self._body(), "not_valid_header", self.SECRET)

    def test_empty_secret_raises(self):
        body = self._body()
        ts = str(int(time.time()))
        sig = f"ts={ts};h1=abc"
        with pytest.raises(PaddleWebhookError, match="not configured"):
            verify_and_parse_paddle_event(body, sig, "")

    def test_all_paddle_event_types_parse(self):
        """Verify all expected Paddle Billing event types can be parsed."""
        for etype in [
            "subscription.activated",
            "subscription.updated",
            "subscription.cancelled",
            "subscription.past_due",
            "transaction.completed",
            "transaction.payment_failed",
        ]:
            body = self._body(etype)
            ts = str(int(time.time()))
            sig = _make_sig(self.SECRET, ts, body)
            event = verify_and_parse_paddle_event(body, sig, self.SECRET)
            assert event["event_type"] == etype


# ═══════════════════════════════════════════════════════════════════════════════
# access_control — single source of truth (no motor required)
# ═══════════════════════════════════════════════════════════════════════════════

from access_control import (
    Tier,
    UserAccess,
    _resolve_access,
    CHAT_QUOTA_FREE,
    CHAT_ANTIABUSE_CAP,
)


class TestAccessControlResolve:
    def _sub(self, **kw):
        return {"user_id": "u1", "status": "free", **kw}

    # ── Trial ─────────────────────────────────────────────────────────────

    def test_trial_active_is_trial_tier(self):
        future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        access = _resolve_access("u1", self._sub(status="trial", trial_end=future))
        assert access.tier == Tier.TRIAL
        assert access.has_premium_access
        assert access.is_unlimited_chat

    def test_trial_expired_is_free(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        access = _resolve_access("u1", self._sub(status="trial", trial_end=past))
        assert access.tier == Tier.FREE
        assert not access.has_premium_access

    def test_trial_days_remaining_is_correct(self):
        future = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()
        access = _resolve_access("u1", self._sub(status="trial", trial_end=future))
        assert access.trial_days_remaining is not None
        assert 13 <= access.trial_days_remaining <= 15

    def test_trial_30_day_duration(self):
        """New trial should have ~30 days remaining."""
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        access = _resolve_access("u1", self._sub(status="trial", trial_end=future))
        assert access.trial_days_remaining is not None
        assert access.trial_days_remaining >= 29

    # ── Free ──────────────────────────────────────────────────────────────

    def test_free_has_no_premium_access(self):
        access = _resolve_access("u1", self._sub(status="free"))
        assert access.tier == Tier.FREE
        assert not access.has_premium_access
        assert not access.can("training_plan")
        assert not access.can("llm_access")
        assert access.chat_monthly_quota == CHAT_QUOTA_FREE

    def test_free_cannot_access_premium_features(self):
        access = _resolve_access("u1", self._sub(status="free"))
        for feat in ["training_plan", "llm_access", "rag_access", "coach_detailed"]:
            assert not access.can(feat)

    def test_free_can_access_free_features(self):
        access = _resolve_access("u1", self._sub(status="free"))
        for feat in ["dashboard_insight", "workout_list", "basic_stats"]:
            assert access.can(feat)

    # ── Premium ───────────────────────────────────────────────────────────

    def test_premium_no_expiry(self):
        access = _resolve_access("u1", self._sub(status="premium"))
        assert access.tier == Tier.PREMIUM
        assert access.has_premium_access

    def test_premium_not_yet_expired(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        access = _resolve_access("u1", self._sub(status="premium", premium_expires_at=future))
        assert access.tier == Tier.PREMIUM

    def test_premium_expired_returns_free(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        access = _resolve_access("u1", self._sub(status="premium", premium_expires_at=past))
        assert access.tier == Tier.FREE

    def test_premium_can_all_features(self):
        access = _resolve_access("u1", self._sub(status="premium"))
        for feat in ["training_plan", "llm_access", "rag_access", "coach_detailed"]:
            assert access.can(feat)

    # ── Legacy statuses ───────────────────────────────────────────────────

    def test_early_adopter_is_premium(self):
        """Grandfathered early_adopter must remain Premium."""
        access = _resolve_access("u1", self._sub(status="early_adopter"))
        assert access.tier == Tier.PREMIUM

    def test_active_stripe_unexpired_is_premium(self):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        access = _resolve_access("u1", self._sub(status="active", expires_at=future))
        assert access.tier == Tier.PREMIUM

    def test_active_stripe_expired_is_free(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        access = _resolve_access("u1", self._sub(status="active", expires_at=past))
        assert access.tier == Tier.FREE

    def test_starter_is_premium(self):
        assert _resolve_access("u1", self._sub(status="starter")).tier == Tier.PREMIUM

    def test_confort_is_premium(self):
        assert _resolve_access("u1", self._sub(status="confort")).tier == Tier.PREMIUM

    def test_pro_is_premium(self):
        assert _resolve_access("u1", self._sub(status="pro")).tier == Tier.PREMIUM

    # ── Fail-closed defaults ──────────────────────────────────────────────

    def test_unknown_status_returns_free(self):
        access = _resolve_access("u1", self._sub(status="some_unknown_tier_xyz"))
        assert access.tier == Tier.FREE

    def test_unknown_feature_returns_false(self):
        access = _resolve_access("u1", self._sub(status="premium"))
        assert not access.can("nonexistent_feature_xyz")

    # ── Chat quota ────────────────────────────────────────────────────────

    def test_free_limited_chat(self):
        access = _resolve_access("u1", self._sub(status="free"))
        assert not access.is_unlimited_chat
        assert access.chat_monthly_quota == CHAT_QUOTA_FREE

    def test_premium_unlimited_chat(self):
        access = _resolve_access("u1", self._sub(status="premium"))
        assert access.is_unlimited_chat
        assert access.chat_monthly_quota is None

    def test_trial_unlimited_chat(self):
        future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        access = _resolve_access("u1", self._sub(status="trial", trial_end=future))
        assert access.is_unlimited_chat

    def test_antiabuse_cap_constant_is_positive(self):
        assert CHAT_ANTIABUSE_CAP > 0

    # ── User isolation ────────────────────────────────────────────────────

    def test_user_isolation(self):
        """Two users with different tiers must not share access."""
        free_access = _resolve_access("user_free", {"user_id": "user_free", "status": "free"})
        prem_access = _resolve_access("user_prem", {"user_id": "user_prem", "status": "premium"})

        assert free_access.tier == Tier.FREE
        assert prem_access.tier == Tier.PREMIUM
        assert not free_access.can("training_plan")
        assert prem_access.can("training_plan")
        assert free_access.user_id != prem_access.user_id


# ═══════════════════════════════════════════════════════════════════════════════
# subscription_manager — mocked DB (avoids motor dependency)
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio
import sys
from unittest.mock import MagicMock, AsyncMock

# Provide a minimal motor stub so subscription_manager can be imported
_motor_stub = MagicMock()
_motor_stub.motor_asyncio = MagicMock()
_motor_stub.motor_asyncio.AsyncIOMotorDatabase = object
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub.motor_asyncio)

from subscription_manager import (  # noqa: E402
    SubscriptionStatus,
    TRIAL_DURATION_DAYS,
    create_trial_subscription,
    activate_premium,
    renew_premium,
    cancel_subscription,
    check_trial_expiration,
    check_premium_expiration,
    get_trial_days_remaining,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Col:
    """Minimal in-memory MongoDB collection mock."""

    def __init__(self):
        self._docs = {}

    async def find_one(self, q, proj=None):
        doc = self._docs.get(q.get("user_id"))
        if doc and proj:
            return {k: v for k, v in doc.items() if proj.get(k, 1)}
        return doc

    async def insert_one(self, doc):
        doc.pop("_id", None)
        self._docs[doc["user_id"]] = dict(doc)

    async def update_one(self, q, upd, upsert=False):
        uid = q.get("user_id")
        existing = self._docs.get(uid)
        if existing is None:
            if upsert:
                existing = {"user_id": uid}
            else:
                return
        if "$set" in upd:
            existing.update(upd["$set"])
        self._docs[uid] = existing


class _DB:
    def __init__(self):
        self.subscriptions = _Col()


class TestSubscriptionManager:
    def test_create_trial_has_correct_status(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u1")
            assert sub["status"] == SubscriptionStatus.TRIAL
            assert sub["user_id"] == "u1"
        _run(go())

    def test_trial_lasts_30_days(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_days")
            trial_end = datetime.fromisoformat(sub["trial_end"].replace("Z", "+00:00"))
            delta = trial_end - datetime.now(timezone.utc)
            assert 29 <= delta.days <= 30
        _run(go())

    def test_trial_creates_paddle_fields(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_paddle")
            assert "paddle_subscription_id" in sub
            assert sub["paddle_subscription_id"] is None
            assert "paddle_customer_id" in sub
            assert "stripe_customer_id" in sub  # Legacy field preserved
        _run(go())

    def test_activate_premium_sets_status(self):
        async def go():
            db = _DB()
            await create_trial_subscription(db, "u_prem")
            exp = datetime.now(timezone.utc) + timedelta(days=30)
            sub = await activate_premium(db, "u_prem", "sub_paddle_123", "cus_paddle_456", exp)
            assert sub["status"] == SubscriptionStatus.PREMIUM
            assert sub["paddle_subscription_id"] == "sub_paddle_123"
            assert sub["paddle_customer_id"] == "cus_paddle_456"
        _run(go())

    def test_renew_extends_expiry(self):
        async def go():
            db = _DB()
            await create_trial_subscription(db, "u_renew")
            exp1 = datetime.now(timezone.utc) + timedelta(days=30)
            await activate_premium(db, "u_renew", "sub_1", "cus_1", exp1)
            exp2 = datetime.now(timezone.utc) + timedelta(days=60)
            sub = await renew_premium(db, "u_renew", "sub_1", exp2)
            assert sub["status"] == SubscriptionStatus.PREMIUM
            exp_dt = datetime.fromisoformat(sub["premium_expires_at"].replace("Z", "+00:00"))
            assert exp_dt > datetime.now(timezone.utc) + timedelta(days=50)
        _run(go())

    def test_cancel_no_expiry_becomes_free(self):
        async def go():
            db = _DB()
            await create_trial_subscription(db, "u_cancel")
            await activate_premium(db, "u_cancel", "sub_x", "cus_x", None)
            sub = await cancel_subscription(db, "u_cancel")
            assert sub["status"] == SubscriptionStatus.FREE
        _run(go())

    def test_cancel_with_future_expiry_stays_premium(self):
        """Access is retained until end of paid period after cancellation."""
        async def go():
            db = _DB()
            await create_trial_subscription(db, "u_grace")
            future = datetime.now(timezone.utc) + timedelta(days=15)
            await activate_premium(db, "u_grace", "sub_y", "cus_y", future)
            sub = await cancel_subscription(db, "u_grace")
            assert sub["status"] == SubscriptionStatus.PREMIUM
            assert sub.get("cancelled_at") is not None
        _run(go())

    def test_trial_expiration_sets_free(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_trial_exp")
            sub["trial_end"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            db.subscriptions._docs["u_trial_exp"]["trial_end"] = sub["trial_end"]
            result = await check_trial_expiration(db, sub)
            assert result["status"] == SubscriptionStatus.FREE
        _run(go())

    def test_premium_expiration_sets_free(self):
        async def go():
            db = _DB()
            await create_trial_subscription(db, "u_prem_exp")
            past = datetime.now(timezone.utc) - timedelta(hours=1)
            await activate_premium(db, "u_prem_exp", "sub_z", "cus_z", past)
            sub = await db.subscriptions.find_one({"user_id": "u_prem_exp"})
            result = await check_premium_expiration(db, sub)
            assert result["status"] == SubscriptionStatus.FREE
        _run(go())

    def test_trial_days_remaining(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_d")
            days = get_trial_days_remaining(sub)
            assert days is not None
            assert 28 <= days <= TRIAL_DURATION_DAYS
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════════
# verify-checkout disabled (frontend cannot grant Premium)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyCheckoutDisabled:
    def test_endpoint_returns_410_in_source(self):
        """verify_checkout_session must raise HTTPException(410)."""
        import inspect
        try:
            import server
            src = inspect.getsource(server.verify_checkout_session)
            assert "410" in src, "verify_checkout_session must raise 410 Gone"
        except ImportError:
            pytest.skip("server module not importable in this test context")


# ═══════════════════════════════════════════════════════════════════════════════
# SubscriptionContext.jsx — fail-closed contract
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendFailClosed:
    def test_error_fallback_is_free_not_trial(self):
        """On API error, SubscriptionContext must set status='free', not 'trial'."""
        import os
        jsx = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../frontend/src/context/SubscriptionContext.jsx")
        )
        if not os.path.exists(jsx):
            pytest.skip("SubscriptionContext.jsx not found")

        with open(jsx) as f:
            src = f.read()

        # The error catch block must set status to "free", not "trial"
        # Find the error handler section
        assert 'status: "free"' in src, "Error fallback must set status='free'"

    def test_error_fallback_features_are_disabled(self):
        """All premium features must be false in the error fallback."""
        import os
        jsx = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../frontend/src/context/SubscriptionContext.jsx")
        )
        if not os.path.exists(jsx):
            pytest.skip("SubscriptionContext.jsx not found")

        with open(jsx) as f:
            src = f.read()

        # Look for the pattern where features are disabled in error fallback
        assert "training_plan: false" in src, \
            "Error fallback must disable training_plan"
        assert "llm_access: false" in src, \
            "Error fallback must disable llm_access"


# ═══════════════════════════════════════════════════════════════════════════════
# chat/send uses access_control (structural)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatUsesAccessControl:
    def test_chat_send_uses_get_user_access(self):
        """chat/send handler must call get_user_access(), not read subscriptions directly."""
        import inspect
        try:
            import server
            src = inspect.getsource(server.send_chat_message)
            assert "get_user_access" in src, \
                "send_chat_message must use access_control.get_user_access()"
            # Must NOT have the old manual PREMIUM_STATUSES pattern
            assert "PREMIUM_STATUSES" not in src, \
                "send_chat_message must not use manual PREMIUM_STATUSES set"
        except ImportError:
            pytest.skip("server module not importable in this test context")


# ═══════════════════════════════════════════════════════════════════════════════
# Webhook idempotence — structural
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebhookIdempotence:
    def test_paddle_webhook_checks_event_id(self):
        """paddle_webhook handler must check db.paddle_events for duplicates."""
        import inspect
        try:
            import server
            src = inspect.getsource(server.paddle_webhook)
            assert "paddle_events" in src, \
                "paddle_webhook must check paddle_events collection for idempotence"
            assert "event_id" in src, \
                "paddle_webhook must use event_id for deduplication"
        except ImportError:
            pytest.skip("server module not importable in this test context")
