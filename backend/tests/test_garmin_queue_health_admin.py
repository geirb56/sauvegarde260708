"""HTTP authorization of Garmin queue health on the real ASGI application."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("ENVIRONMENT", "test")

import server
from access_control import RouteAccess, get_route_access
from auth.jwt_utils import create_access_token
from api import garmin as garmin_api
from jobs import health as jobs_health


PATH = "/api/garmin/queue/health"
SNAPSHOT = {
    "status": "degraded",
    "redis_connected": True,
    "queue_length": 500,
    "processing_length": 2,
    "active_workers": 1,
    "oldest_processing_seconds": 12,
    "orphans_recovered_total": 3,
    "failed_jobs_total": 4,
    "timestamp": "2026-09-29T07:00:00+00:00",
}


class _Collection:
    def __init__(self, docs):
        self.docs = {doc["id"] if "id" in doc else doc["user_id"]: doc for doc in docs}

    async def find_one(self, query, projection=None):
        return next(
            (dict(doc) for doc in self.docs.values() if all(doc.get(k) == v for k, v in query.items())),
            None,
        )


class _FakeDB:
    def __init__(self):
        self.users = _Collection([
            {"id": name, "email": f"{name}@example.com", "role": role, "is_active": active}
            for name, role, active in (
                ("free-user", "user", True),
                ("trial-user", "user", True),
                ("premium-user", "user", True),
                ("admin-free", "admin", True),
                ("admin-premium", "admin", True),
                ("disabled-admin", "admin", False),
            )
        ])
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        self.subscriptions = _Collection([
            {"user_id": name, "status": tier, **(
                {"trial_end": expires} if tier == "trial" else
                {"premium_expires_at": expires} if tier == "premium" else {}
            )}
            for name, tier in (
                ("free-user", "free"),
                ("trial-user", "trial"),
                ("premium-user", "premium"),
                ("admin-free", "free"),
                ("admin-premium", "premium"),
                ("disabled-admin", "free"),
            )
        ])


def _bearer(user_id, claims=None):
    if claims is None:
        token = create_access_token(user_id, f"{user_id}@example.com")
    else:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"sub": user_id, "email": f"{user_id}@example.com",
             "iat": now, "exp": now + timedelta(minutes=5), **claims},
            os.environ["JWT_SECRET_KEY"],
            algorithm=os.environ["JWT_ALGORITHM"],
        )
    return {"Authorization": "Bearer " + token}


def _expired_bearer():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": "admin-free", "iat": now - timedelta(minutes=2),
         "exp": now - timedelta(minutes=1)},
        os.environ["JWT_SECRET_KEY"],
        algorithm=os.environ["JWT_ALGORITHM"],
    )
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def isolated_services(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server.app.state, "db", db)
    monkeypatch.setattr(server.rate_limiter, "is_limited", lambda _key: False)
    monkeypatch.setattr(server.rate_limiter, "record", lambda _key: None)
    health = AsyncMock(return_value=SNAPSHOT)
    redis = Mock(side_effect=AssertionError("Redis must not be contacted"))
    monkeypatch.setattr(garmin_api, "queue_health", health)
    monkeypatch.setattr(garmin_api, "get_redis", redis)
    monkeypatch.setattr(jobs_health, "get_redis", redis)
    return health, redis


@pytest.mark.parametrize(
    ("identity", "expected"),
    (
        ("anonymous", 401),
        ("invalid", 401),
        ("expired", 401),
        ("deleted", 401),
        ("disabled-admin", 401),
        ("free-user", 403),
        ("trial-user", 403),
        ("premium-user", 403),
        ("forged-is-admin", 403),
        ("forged-role", 403),
        ("admin-free", 200),
        ("admin-premium", 200),
    ),
)
@pytest.mark.asyncio
async def test_queue_health_access_matrix(identity, expected, isolated_services):
    health, redis = isolated_services
    if identity == "anonymous":
        headers = {}
    elif identity == "invalid":
        headers = {"Authorization": "Bearer " + "not-a-valid-token"}
    elif identity == "expired":
        headers = _expired_bearer()
    elif identity == "deleted":
        headers = _bearer("deleted")
    elif identity == "forged-is-admin":
        headers = _bearer("free-user", {"is_admin": True})
    elif identity == "forged-role":
        headers = _bearer("premium-user", {"role": "admin"})
    else:
        headers = _bearer(identity)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(PATH, headers=headers)

    assert response.status_code == expected
    redis.assert_not_called()
    if expected == 200:
        assert response.json() == SNAPSHOT
        health.assert_awaited_once_with()
    else:
        health.assert_not_awaited()
        assert not set(response.json()).intersection(SNAPSHOT)


def test_garmin_route_classification_is_narrow():
    assert get_route_access(PATH) == RouteAccess.FREE
    for path in ("/api/garmin/connect", "/api/garmin/status", "/api/garmin/disconnect"):
        assert get_route_access(path) == RouteAccess.FREE
    for path in (
        "/api/garmin/sync", "/api/garmin/activities", "/api/garmin/queue/other",
        "/api/garmin/sync/stream", "/api/garmin/feed/stream",
    ):
        assert get_route_access(path) == RouteAccess.PREMIUM


@pytest.mark.asyncio
async def test_existing_garmin_routes_keep_subscription_behavior(isolated_services, monkeypatch):
    health, redis = isolated_services
    status = AsyncMock(return_value={"status": "connected"})
    disconnect = AsyncMock(return_value={"status": "disconnected"})
    enqueue = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(garmin_api.garmin_service, "get_status", status)
    monkeypatch.setattr(garmin_api.garmin_service, "disconnect", disconnect)
    monkeypatch.setattr(garmin_api, "enqueue_sync", enqueue)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        free_status = await client.get("/api/garmin/status", headers=_bearer("free-user"))
        free_disconnect = await client.post("/api/garmin/disconnect", headers=_bearer("free-user"))
        free_sync = await client.post("/api/garmin/sync", headers=_bearer("free-user"))
        premium_sync = await client.post("/api/garmin/sync", headers=_bearer("premium-user"))

    assert free_status.status_code == 200
    assert free_status.json() == {"status": "connected"}
    assert free_disconnect.status_code == 200
    assert free_disconnect.json() == {"status": "disconnected"}
    assert free_sync.status_code == 403
    assert premium_sync.status_code == 200
    assert premium_sync.json() == {"status": "queued"}
    status.assert_awaited_once()
    disconnect.assert_awaited_once()
    enqueue.assert_awaited_once_with("premium-user")
    health.assert_not_awaited()
    redis.assert_not_called()
