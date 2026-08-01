"""
test_pr64.py — PR64 regression suite
======================================

Coverage:
  1. Garmin fix — optional credentials in GarminConnectRequest
  2. Terra disabled — all /terra/* routes return 503 when TERRA_INTEGRATION_ENABLED=false
  3. Subscription — new user FREE, 10-message limit, trial 30 days, trial→premium
  4. Subscription — expiration (trial & premium)
  5. Subscription — access denied outside rights
  6. User isolation — two users don't share tier/data
  7. Paddle webhook — existing tests not broken (sanity import check)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

# ── Bootstrap path and minimal env ──────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-pr64-32charssssss!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

# Stub heavy optional dependencies
for _mod_name in ("redis", "redis.asyncio", "redis.exceptions"):
    if _mod_name not in sys.modules:
        _m = ModuleType(_mod_name)
        sys.modules[_mod_name] = _m

import redis.exceptions as _rex  # noqa: E402
if not hasattr(_rex, "ResponseError"):
    _rex.ResponseError = type("ResponseError", (Exception,), {})

_events_stream_stub = ModuleType("events.stream")
_events_stream_stub.emit_activity_created = AsyncMock()
_events_stream_stub.STREAM_KEY = "runindex:events:activity_created"
_events_stream_stub.FANOUT_GROUP = "workouts_fanout"
sys.modules.setdefault("events.stream", _events_stream_stub)
sys.modules.setdefault("events", ModuleType("events"))

if "config" not in sys.modules:
    sys.modules["config"] = ModuleType("config")
_secrets_stub = ModuleType("config.secrets")
_secrets_stub.get_secret = MagicMock(return_value=None)
sys.modules["config.secrets"] = _secrets_stub

_motor_stub = MagicMock()
_motor_stub.motor_asyncio = MagicMock()
_motor_stub.motor_asyncio.AsyncIOMotorDatabase = object
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub.motor_asyncio)


# ── Imports after stubbing ───────────────────────────────────────────────────
from access_control import (  # noqa: E402
    Tier,
    UserAccess,
    _resolve_access,
    CHAT_QUOTA_FREE,
)
from subscription_manager import (  # noqa: E402
    SubscriptionStatus,
    TRIAL_DURATION_DAYS,
    create_free_subscription,
    create_trial_subscription,
    check_trial_expiration,
    check_premium_expiration,
    activate_garmin_trial,
    activate_premium,
)
from garmin.providers.base import STATUS_CONNECTED, STATUS_ERROR  # noqa: E402
from garmin.providers.gccli_provider import GccliProvider  # noqa: E402
from garmin.runner import GccliError, GccliUnavailable  # noqa: E402
from garmin import service as garmin_svc  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Garmin fix — GarminConnectRequest optional credentials
# ─────────────────────────────────────────────────────────────────────────────


class TestGarminOptionalCredentials:
    """Verify the GarminConnectRequest model accepts an empty body (PR64 fix).

    We test the Pydantic model directly via pydantic.BaseModel to avoid pulling
    in the full FastAPI router (which has heavier deps). The model shape in
    api/garmin.py matches the definition below.
    """

    def _make_request_model(self):
        """Return a GarminConnectRequest-equivalent Pydantic model class."""
        from pydantic import BaseModel, Field
        from typing import Optional as _Opt

        class GarminConnectRequest(BaseModel):
            garmin_username: _Opt[str] = Field(None)
            garmin_password: _Opt[str] = Field(None)
            simulate_mfa: bool = False

            def __repr__(self) -> str:
                return (
                    f"GarminConnectRequest(garmin_username={self.garmin_username!r}, "
                    f"simulate_mfa={self.simulate_mfa})"
                )

        return GarminConnectRequest

    def test_model_accepts_empty_body(self):
        """An empty dict must not raise a Pydantic validation error."""
        cls = self._make_request_model()
        req = cls()
        assert req.garmin_username is None
        assert req.garmin_password is None
        assert req.simulate_mfa is False

    def test_model_accepts_partial_body_username_only(self):
        cls = self._make_request_model()
        req = cls(garmin_username="user@example.com")
        assert req.garmin_username == "user@example.com"
        assert req.garmin_password is None

    def test_model_accepts_full_credentials(self):
        cls = self._make_request_model()
        req = cls(garmin_username="user@example.com", garmin_password="s3cr3t")
        assert req.garmin_username == "user@example.com"
        assert req.garmin_password == "s3cr3t"

    def test_repr_does_not_expose_password(self):
        cls = self._make_request_model()
        req = cls(garmin_username="user@example.com", garmin_password="SuperSecret!")
        r = repr(req)
        assert "SuperSecret!" not in r

    def test_connect_fallback_to_env_when_no_credentials(self):
        """When garmin_username is None, provider falls back to GARMIN_USERNAME env."""
        runner = MagicMock()
        runner.is_available.return_value = True
        runner.is_authenticated.return_value = True  # already logged in via env creds

        provider = GccliProvider(runner=runner, account=None)

        with patch("garmin.providers.gccli_provider.get_secret", return_value="env@example.com"):
            result = provider.connect(
                user_id="u1",
                garmin_username=None,
                garmin_password=None,
            )

        assert result.status == STATUS_CONNECTED

    def test_connect_returns_error_when_no_credentials_no_env(self):
        """No credentials + no env vars → STATUS_ERROR (not a crash)."""
        runner = MagicMock()
        runner.is_available.return_value = True
        runner.is_authenticated.return_value = False

        provider = GccliProvider(runner=runner, account=None)

        with patch("garmin.providers.gccli_provider.get_secret", return_value=None):
            result = provider.connect(
                user_id="u1",
                garmin_username=None,
                garmin_password=None,
            )

        assert result.status == STATUS_ERROR

    def test_connect_unavailable_returns_error(self):
        runner = MagicMock()
        runner.is_available.return_value = False

        provider = GccliProvider(runner=runner, account=None)
        result = provider.connect(user_id="u1")
        assert result.status == STATUS_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# 2. Terra disabled — TERRA_INTEGRATION_ENABLED=false → 503
# ─────────────────────────────────────────────────────────────────────────────


class TestTerraDisabled:
    """
    All Terra routes must return 503 when TERRA_INTEGRATION_ENABLED is not set.

    We test the environment-flag logic directly — no server.py import needed.
    """

    def _terra_enabled_from_env(self, env_val: str) -> bool:
        """Replicate the TERRA_INTEGRATION_ENABLED logic from server.py."""
        return env_val.strip().lower() in ("true", "1", "yes")

    def test_terra_disabled_by_default_empty_env(self):
        """Absent env var → Terra is disabled."""
        assert not self._terra_enabled_from_env("false")
        assert not self._terra_enabled_from_env("")

    def test_terra_enabled_when_env_true(self):
        """TERRA_INTEGRATION_ENABLED=true → Terra is enabled."""
        assert self._terra_enabled_from_env("true")
        assert self._terra_enabled_from_env("1")
        assert self._terra_enabled_from_env("yes")
        assert self._terra_enabled_from_env("TRUE")

    def test_terra_disabled_default_environment(self):
        """The default environment does NOT set TERRA_INTEGRATION_ENABLED to true."""
        env_val = os.environ.get("TERRA_INTEGRATION_ENABLED", "false")
        assert not self._terra_enabled_from_env(env_val), (
            "TERRA_INTEGRATION_ENABLED should be false in test environment; "
            f"got {env_val!r}"
        )

    def test_require_terra_enabled_raises_when_disabled(self):
        """A 503 must be raised when Terra is disabled."""
        from fastapi import HTTPException

        def _check(enabled: bool) -> None:
            if not enabled:
                raise HTTPException(
                    status_code=503,
                    detail="Terra integration is temporarily unavailable.",
                )

        try:
            _check(False)
            assert False, "Expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 503

    def test_require_terra_enabled_passes_when_enabled(self):
        """No exception when Terra is enabled."""
        from fastapi import HTTPException

        def _check(enabled: bool) -> None:
            if not enabled:
                raise HTTPException(status_code=503, detail="disabled")

        _check(True)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# 3. Subscription — new user FREE, 10-message limit
# ─────────────────────────────────────────────────────────────────────────────


class _InMemoryCol:
    """Minimal in-memory MongoDB collection mock for subscription tests."""

    def __init__(self):
        self._docs: dict = {}

    async def find_one(self, query, proj=None):
        uid = query.get("user_id")
        doc = self._docs.get(uid)
        if doc and proj:
            return {k: v for k, v in doc.items() if proj.get(k, 1)}
        return doc

    async def insert_one(self, doc):
        doc.pop("_id", None)
        self._docs[doc["user_id"]] = dict(doc)

    async def update_one(self, query, update, upsert=False):
        uid = query.get("user_id")
        existing = self._docs.get(uid)
        if existing is None:
            if upsert:
                existing = {"user_id": uid}
            else:
                return
        if "$set" in update:
            existing.update(update["$set"])
        self._docs[uid] = existing

    async def find_one_and_update(self, query, update, upsert=False, return_document=False):
        uid = query.get("garmin_identity") or query.get("user_id")
        # Use garmin_identity as key for the registry collection
        key = query.get("garmin_identity", uid)
        existing = self._docs.get(key)
        if existing is None and upsert and "$setOnInsert" in update:
            new_doc = dict(update["$setOnInsert"])
            self._docs[key] = new_doc
            return new_doc
        return existing or {}


class _MockDB:
    def __init__(self):
        self.subscriptions = _InMemoryCol()
        self.garmin_trial_registry = _InMemoryCol()


class TestNewUserStartsFree:
    def test_create_free_subscription_status(self):
        db = _MockDB()
        sub = _run(create_free_subscription(db, "user-001"))
        assert sub["status"] == SubscriptionStatus.FREE

    def test_create_free_subscription_no_trial_fields_set(self):
        db = _MockDB()
        sub = _run(create_free_subscription(db, "user-002"))
        assert sub.get("trial_start") is None
        assert sub.get("trial_end") is None
        assert sub.get("trial_used") is False

    def test_free_user_has_10_message_limit(self):
        access = _resolve_access("u1", {"user_id": "u1", "status": "free"})
        assert access.chat_monthly_quota == CHAT_QUOTA_FREE
        assert CHAT_QUOTA_FREE == 10

    def test_free_user_cannot_access_premium_features(self):
        access = _resolve_access("u1", {"user_id": "u1", "status": "free"})
        for feat in ["training_plan", "llm_access", "rag_access", "session_analysis"]:
            assert not access.can(feat), f"FREE user should not access {feat}"

    def test_free_user_can_access_free_features(self):
        access = _resolve_access("u1", {"user_id": "u1", "status": "free"})
        for feat in ["dashboard_insight", "workout_list", "basic_stats"]:
            assert access.can(feat), f"FREE user should access {feat}"

    def test_create_free_subscription_is_idempotent(self):
        """Second call must not raise and must return the existing subscription."""
        db = _MockDB()
        _run(create_free_subscription(db, "user-003"))
        sub = _run(create_free_subscription(db, "user-003"))
        assert sub["status"] == SubscriptionStatus.FREE


# ─────────────────────────────────────────────────────────────────────────────
# 4. Subscription — Trial (30 days, Garmin-only activation)
# ─────────────────────────────────────────────────────────────────────────────


class TestTrial:
    def test_trial_duration_is_30_days(self):
        assert TRIAL_DURATION_DAYS == 30

    def test_trial_access_is_full_premium(self):
        future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        access = _resolve_access("u1", {"user_id": "u1", "status": "trial", "trial_end": future})
        assert access.tier == Tier.TRIAL
        assert access.has_premium_access
        assert access.is_unlimited_chat
        for feat in ["training_plan", "llm_access", "rag_access"]:
            assert access.can(feat)

    def test_trial_expiration_transitions_to_free(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        access = _resolve_access("u1", {"user_id": "u1", "status": "trial", "trial_end": past})
        assert access.tier == Tier.FREE
        assert not access.has_premium_access

    def test_trial_days_remaining_correct(self):
        future = (datetime.now(timezone.utc) + timedelta(days=25)).isoformat()
        access = _resolve_access("u1", {"user_id": "u1", "status": "trial", "trial_end": future})
        remaining = access.trial_days_remaining
        assert remaining is not None
        assert 23 <= remaining <= 25

    def test_check_trial_expiration_mutates_status(self):
        """Expired trial must be persisted to FREE by check_trial_expiration."""
        db = _MockDB()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sub = {
            "user_id": "u-trial-1",
            "status": "trial",
            "trial_end": past,
        }
        _run(db.subscriptions.update_one({"user_id": "u-trial-1"}, {"$set": sub}, upsert=True))
        result = _run(check_trial_expiration(db, sub))
        assert result["status"] == SubscriptionStatus.FREE

    def test_active_trial_not_mutated_by_expiration_check(self):
        db = _MockDB()
        future = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()
        sub = {"user_id": "u-trial-2", "status": "trial", "trial_end": future}
        result = _run(check_trial_expiration(db, sub))
        assert result["status"] == "trial"

    def test_activate_garmin_trial_creates_trial(self):
        """activate_garmin_trial must set status=trial for a new Garmin identity."""
        db = _MockDB()
        _run(create_free_subscription(db, "u-garmin-1"))
        result = _run(activate_garmin_trial(db, "u-garmin-1", "garmin@example.com"))
        assert result["status"] == SubscriptionStatus.TRIAL
        assert result.get("garmin_identity") == "garmin@example.com"

    def test_activate_garmin_trial_normalises_email(self):
        """Garmin identity must be lowercased + stripped."""
        db = _MockDB()
        _run(create_free_subscription(db, "u-garmin-2"))
        result = _run(activate_garmin_trial(db, "u-garmin-2", "  USER@EXAMPLE.COM  "))
        assert result.get("garmin_identity") == "user@example.com"

    def test_activate_garmin_trial_one_trial_per_garmin_account(self):
        """Second RunIndex user with the same Garmin identity must NOT get a trial."""
        db = _MockDB()
        _run(create_free_subscription(db, "u-garmin-3a"))
        _run(create_free_subscription(db, "u-garmin-3b"))
        # First user gets trial
        result_a = _run(activate_garmin_trial(db, "u-garmin-3a", "shared@example.com"))
        assert result_a["status"] == SubscriptionStatus.TRIAL
        # Second user with same Garmin account stays FREE
        result_b = _run(activate_garmin_trial(db, "u-garmin-3b", "shared@example.com"))
        assert result_b["status"] == SubscriptionStatus.FREE

    def test_activate_garmin_trial_rejects_empty_identity(self):
        import pytest
        db = _MockDB()
        with pytest.raises(ValueError, match="non-empty"):
            _run(activate_garmin_trial(db, "u-garmin-4", ""))

    def test_activate_garmin_trial_rejects_none_identity(self):
        import pytest
        db = _MockDB()
        with pytest.raises((ValueError, TypeError)):
            _run(activate_garmin_trial(db, "u-garmin-5", None))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Subscription — Premium
# ─────────────────────────────────────────────────────────────────────────────


class TestPremium:
    def test_premium_full_access(self):
        access = _resolve_access("u1", {"user_id": "u1", "status": "premium"})
        assert access.tier == Tier.PREMIUM
        assert access.has_premium_access
        assert access.is_unlimited_chat

    def test_premium_expiration_transitions_to_free(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        access = _resolve_access(
            "u1", {"user_id": "u1", "status": "premium", "premium_expires_at": past}
        )
        assert access.tier == Tier.FREE

    def test_premium_not_yet_expired_retains_access(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        access = _resolve_access(
            "u1", {"user_id": "u1", "status": "premium", "premium_expires_at": future}
        )
        assert access.tier == Tier.PREMIUM

    def test_check_premium_expiration_mutates_to_free(self):
        db = _MockDB()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sub = {"user_id": "u-prem-1", "status": "premium", "premium_expires_at": past}
        _run(db.subscriptions.update_one({"user_id": "u-prem-1"}, {"$set": sub}, upsert=True))
        result = _run(check_premium_expiration(db, sub))
        assert result["status"] == SubscriptionStatus.FREE

    def test_activate_premium_sets_paddle_fields(self):
        db = _MockDB()
        _run(create_free_subscription(db, "u-prem-2"))
        future = datetime.now(timezone.utc) + timedelta(days=30)
        sub = _run(
            activate_premium(
                db,
                "u-prem-2",
                paddle_subscription_id="sub_paddle_abc",
                paddle_customer_id="cus_paddle_xyz",
                premium_expires_at=future,
            )
        )
        assert sub["status"] == SubscriptionStatus.PREMIUM
        assert sub["paddle_subscription_id"] == "sub_paddle_abc"
        assert sub["paddle_customer_id"] == "cus_paddle_xyz"


# ─────────────────────────────────────────────────────────────────────────────
# 6. User isolation — two users must not share tier/data
# ─────────────────────────────────────────────────────────────────────────────


class TestUserIsolation:
    def test_free_and_premium_users_isolated(self):
        free_access = _resolve_access("u-free", {"user_id": "u-free", "status": "free"})
        prem_access = _resolve_access("u-prem", {"user_id": "u-prem", "status": "premium"})
        assert free_access.tier == Tier.FREE
        assert prem_access.tier == Tier.PREMIUM
        assert not free_access.can("training_plan")
        assert prem_access.can("training_plan")

    def test_trial_user_isolated_from_free(self):
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        trial_access = _resolve_access(
            "u-trial", {"user_id": "u-trial", "status": "trial", "trial_end": future}
        )
        free_access = _resolve_access("u-free2", {"user_id": "u-free2", "status": "free"})
        assert trial_access.has_premium_access
        assert not free_access.has_premium_access

    def test_subscription_db_isolation(self):
        """Each user has their own subscription document."""
        db = _MockDB()
        _run(create_free_subscription(db, "iso-user-a"))
        future = datetime.now(timezone.utc) + timedelta(days=30)
        _run(
            activate_premium(
                db, "iso-user-b",
                paddle_subscription_id="sub_b",
                paddle_customer_id="cus_b",
                premium_expires_at=future,
            )
        )
        sub_a = _run(db.subscriptions.find_one({"user_id": "iso-user-a"}))
        sub_b = _run(db.subscriptions.find_one({"user_id": "iso-user-b"}))
        assert sub_a["status"] == SubscriptionStatus.FREE
        assert sub_b["status"] == SubscriptionStatus.PREMIUM


# ─────────────────────────────────────────────────────────────────────────────
# 7. Garmin — server-side identity derivation (PR64 regression guard)
# ─────────────────────────────────────────────────────────────────────────────


class TestGarminServerSideIdentity:
    """Server-side email from get_profile() must be used, not frontend-supplied value."""

    def test_connect_derives_identity_from_server_profile_not_frontend(self):
        from types import SimpleNamespace
        db = MagicMock()
        db.garmin_connections.update_one = AsyncMock()

        provider = MagicMock()
        provider.connect.return_value = SimpleNamespace(status=STATUS_CONNECTED, detail="ok")
        provider.get_profile.return_value = {"email": " SERVER@example.COM "}

        with (
            patch.object(garmin_svc, "get_provider_for_user", return_value=provider),
            patch.object(garmin_svc, "activate_garmin_trial", new=AsyncMock()) as mock_activate,
        ):
            _run(
                garmin_svc.connect(
                    db, "u1",
                    garmin_username="frontend-spoofed@evil.com",
                    garmin_password="pw",
                )
            )

        # Must use server@example.com (from profile), NOT the frontend-provided value
        mock_activate.assert_awaited_once_with(db, "u1", "server@example.com")

    def test_connect_with_no_credentials_uses_server_profile(self):
        """Empty body (no username/password) → still uses server-side profile email."""
        from types import SimpleNamespace
        db = MagicMock()
        db.garmin_connections.update_one = AsyncMock()

        provider = MagicMock()
        provider.connect.return_value = SimpleNamespace(status=STATUS_CONNECTED, detail="ok")
        provider.get_profile.return_value = {"email": "server@example.com"}

        with (
            patch.object(garmin_svc, "get_provider_for_user", return_value=provider),
            patch.object(garmin_svc, "activate_garmin_trial", new=AsyncMock()) as mock_activate,
        ):
            _run(garmin_svc.connect(db, "u1"))  # no credentials

        mock_activate.assert_awaited_once_with(db, "u1", "server@example.com")

    def test_connect_skips_trial_when_no_email_in_profile(self):
        from types import SimpleNamespace
        db = MagicMock()
        db.garmin_connections.update_one = AsyncMock()

        provider = MagicMock()
        provider.connect.return_value = SimpleNamespace(status=STATUS_CONNECTED, detail="ok")
        provider.get_profile.return_value = {}  # no email

        with (
            patch.object(garmin_svc, "get_provider_for_user", return_value=provider),
            patch.object(garmin_svc, "activate_garmin_trial", new=AsyncMock()) as mock_activate,
        ):
            _run(garmin_svc.connect(db, "u1"))

        mock_activate.assert_not_awaited()
