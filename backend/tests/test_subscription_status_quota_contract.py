"""Commercial quota contract tests for both subscription status endpoints."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "subscription-status-test-secret-32chars")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import access_control  # noqa: E402
import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402


ENDPOINTS = ("/api/subscription/status", "/api/premium/status")
_NOW = datetime.now(timezone.utc)
_MONTH_START = _NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class _Collection:
    def __init__(self, docs=()):
        self.docs = [dict(doc) for doc in docs]
        self.write_count = 0

    @staticmethod
    def _matches(doc, query):
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                    return False
                if "$lt" in expected and (actual is None or actual >= expected["$lt"]):
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query, _projection=None):
        return next((dict(doc) for doc in self.docs if self._matches(doc, query)), None)

    async def count_documents(self, query):
        return sum(self._matches(doc, query) for doc in self.docs)

    async def find_one_and_update(
        self, query, update, upsert=False, return_document=None
    ):
        doc = next((doc for doc in self.docs if self._matches(doc, query)), None)
        if doc is None:
            if not upsert:
                return None
            doc = dict(query)
            doc.update(update.get("$setOnInsert", {}))
            self.docs.append(doc)
            self.write_count += 1
        doc.update(update.get("$set", {}))
        for key, amount in update.get("$inc", {}).items():
            doc[key] = int(doc.get(key, 0)) + amount
        return dict(doc)


class _FakeDB:
    def __init__(self, tier="free", usage=0, expired=False):
        active_until = (_NOW + timedelta(days=30)).isoformat()
        past = (_NOW - timedelta(days=1)).isoformat()
        status = {"user_id": "subject", "status": tier}
        if tier == "trial":
            status["trial_end"] = past if expired else active_until
        elif tier == "premium":
            status["premium_expires_at"] = past if expired else active_until
            status["paddle_subscription_id"] = "paddle-test-id"

        conversations = [
            {
                "user_id": "subject",
                "role": "user",
                "timestamp": (_MONTH_START + timedelta(minutes=index)).isoformat(),
            }
            for index in range(usage)
        ]
        conversations.extend(
            {
                "user_id": "another-user",
                "role": "user",
                "timestamp": _NOW.isoformat(),
            }
            for _ in range(4)
        )
        self.users = _Collection([
            {"id": "subject", "email": "subject@example.com", "is_active": True},
            {"id": "disabled", "email": "disabled@example.com", "is_active": False},
            {"id": "another-user", "email": "another@example.com", "is_active": True},
        ])
        self.subscriptions = _Collection([status])
        self.conversations = _Collection(conversations)
        self.coach_quota_counters = _Collection()
        self.status = status


@pytest.fixture
def isolated_db(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server.app.state, "db", db)
    return db


@pytest.fixture(autouse=True)
def use_canonical_entitlements(monkeypatch):
    monkeypatch.setattr(access_control, "DEMO_MODE", False)


def _auth(user_id="subject"):
    return {
        "Authorization": "Bearer "
        + create_access_token(user_id, f"{user_id}@example.com")
    }


def _expired_auth():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "subject",
            "email": "subject@example.com",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        os.environ["JWT_SECRET_KEY"],
        algorithm=os.environ["JWT_ALGORITHM"],
    )
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    ("headers", "status"),
    (
        ({}, 401),
        ({"Authorization": "******"}, 401),
        (_expired_auth(), 401),
        (_auth("deleted"), 401),
        (_auth("disabled"), 401),
    ),
)
@pytest.mark.asyncio
async def test_status_endpoints_require_valid_active_accounts(
    endpoint, headers, status, isolated_db
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(endpoint, headers=headers)
    assert response.status_code == status


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    ("tier", "usage", "expired", "expected_tier", "expected_used", "expected_remaining"),
    (
        ("free", 0, False, "free", 0, 10),
        ("free", 3, False, "free", 3, 7),
        ("free", 10, False, "free", 10, 0),
        ("trial", 3, False, "trial", 3, None),
        ("premium", 3, False, "premium", 3, None),
        ("trial", 3, True, "free", 3, 7),
        ("premium", 3, True, "free", 3, 7),
    ),
)
@pytest.mark.asyncio
async def test_status_endpoints_serialize_canonical_quota(
    endpoint,
    tier,
    usage,
    expired,
    expected_tier,
    expected_used,
    expected_remaining,
    monkeypatch,
):
    db = _FakeDB(tier=tier, usage=usage, expired=expired)
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server.app.state, "db", db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(endpoint, headers=_auth())

    assert response.status_code == 200
    data = response.json()
    is_unlimited = expected_tier in {"trial", "premium"}
    assert data["tier"] == expected_tier
    assert data["is_premium"] is is_unlimited
    assert data["is_unlimited"] is is_unlimited
    assert data["messages_used"] == expected_used
    assert data["messages_limit"] == (None if is_unlimited else 10)
    assert data["messages_remaining"] == expected_remaining
    assert data["tier_name"] == {
        "free": "Gratuit",
        "trial": "Essai gratuit",
        "premium": "Premium",
    }[expected_tier]
    if tier == "trial" and not expired:
        assert data["expires_at"] == db.status["trial_end"]
    if tier == "premium" and not expired:
        assert data["expires_at"] == db.status["premium_expires_at"]
        assert data["subscription_id"] == "paddle-test-id"
    assert db.subscriptions.write_count == 0
    assert db.conversations.write_count == 0


@pytest.mark.parametrize("tier", ("free", "trial", "premium"))
@pytest.mark.asyncio
async def test_status_endpoints_return_coherent_quota_for_the_same_user(tier, monkeypatch):
    db = _FakeDB(tier=tier, usage=3)
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server.app.state, "db", db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        subscription = await client.get(
            ENDPOINTS[0], headers=_auth()
        )
        premium = await client.get(ENDPOINTS[1], headers=_auth())

    assert subscription.status_code == premium.status_code == 200
    fields = ("tier", "is_premium", "is_unlimited", "messages_used", "messages_limit", "messages_remaining")
    assert {field: subscription.json()[field] for field in fields} == {
        field: premium.json()[field] for field in fields
    }


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.asyncio
async def test_status_usage_is_user_isolated_and_does_not_send_or_bill(
    endpoint, isolated_db, monkeypatch
):
    isolated_db.conversations.docs.append(
        {
            "user_id": "subject",
            "role": "user",
            "timestamp": (_MONTH_START - timedelta(days=1)).isoformat(),
        }
    )
    send_message = AsyncMock()
    monkeypatch.setattr(server, "process_coach_message", send_message)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(endpoint, headers=_auth())

    assert response.status_code == 200
    assert response.json()["messages_used"] == 0
    assert isolated_db.subscriptions.write_count == 0
    assert isolated_db.conversations.write_count == 0
    send_message.assert_not_awaited()
