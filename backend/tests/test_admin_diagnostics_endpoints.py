"""Admin-only access tests for cache and service diagnostics."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("ENVIRONMENT", "test")

import server
from auth.jwt_utils import create_access_token
from access_control import RouteAccess, get_route_access


JWT_SECRET = os.environ["JWT_SECRET_KEY"]
JWT_ALGORITHM = os.environ["JWT_ALGORITHM"]
CACHE_STATS = {"entries": 3, "hits": 7}
COACH_METRICS = {"requests": 12, "errors": 1}
METRICS_RESPONSE = {"coach": COACH_METRICS, "cache": CACHE_STATS}


class _Users:
    def __init__(self, docs):
        self.docs = {doc["id"]: dict(doc) for doc in docs}

    async def find_one(self, query, projection=None):
        for doc in self.docs.values():
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


class _Subscriptions:
    def __init__(self):
        self.docs = {
            "free-user": {"user_id": "free-user", "status": "free"},
            "trial-user": {
                "user_id": "trial-user",
                "status": "trial",
                "trial_end": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            },
            "premium-user": {
                "user_id": "premium-user",
                "status": "premium",
                "premium_expires_at": (
                    datetime.now(timezone.utc) + timedelta(days=30)
                ).isoformat(),
            },
            "admin-free": {"user_id": "admin-free", "status": "free"},
            "admin-premium": {
                "user_id": "admin-premium",
                "status": "premium",
                "premium_expires_at": (
                    datetime.now(timezone.utc) + timedelta(days=30)
                ).isoformat(),
            },
        }


class _FakeDB:
    def __init__(self):
        self.users = _Users(
            [
                {"id": "free-user", "email": "free@example.com", "role": "user", "is_active": True},
                {"id": "trial-user", "email": "trial@example.com", "role": "user", "is_active": True},
                {"id": "premium-user", "email": "premium@example.com", "role": "user", "is_active": True},
                {"id": "admin-free", "email": "admin-free@example.com", "role": "admin", "is_active": True},
                {"id": "admin-premium", "email": "admin-premium@example.com", "role": "admin", "is_active": True},
                {"id": "disabled-user", "email": "disabled@example.com", "role": "admin", "is_active": False},
            ]
        )
        self.subscriptions = _Subscriptions()


def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer" + " " + create_access_token(user_id, email)}


def _expired_bearer() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "admin-free",
            "email": "admin-free@example.com",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": "Bearer" + " " + token}


def _forged_admin_bearer() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "free-user",
            "email": "free@example.com",
            "role": "admin",
            "is_admin": True,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": "Bearer" + " " + token}


@pytest.fixture
def diagnostics(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server.app.state, "db", db)
    monkeypatch.setattr(server.rate_limiter, "is_limited", lambda _key: False)
    monkeypatch.setattr(server.rate_limiter, "record", lambda _key: None)
    get_cache_stats = Mock(return_value=CACHE_STATS)
    get_coach_metrics = Mock(return_value=COACH_METRICS)
    monkeypatch.setattr(server, "get_cache_stats", get_cache_stats)
    monkeypatch.setattr(server, "get_coach_metrics", get_coach_metrics)
    return get_cache_stats, get_coach_metrics


@pytest_asyncio.fixture
async def client(diagnostics):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app),
        base_url="http://test",
    ) as test_client:
        yield test_client


ENDPOINTS = ("/api/cache/stats", "/api/metrics")


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize(
    ("auth_kind", "expected_status"),
    (
        ("anonymous", 401),
        ("invalid", 401),
        ("expired", 401),
        ("deleted", 401),
        ("disabled", 401),
        ("forged-admin-claim", 403),
        ("free-user", 403),
        ("trial-user", 403),
        ("premium-user", 403),
        ("admin-free", 200),
        ("admin-premium", 200),
    ),
)
@pytest.mark.asyncio
async def test_diagnostics_auth_matrix(path, auth_kind, expected_status, client, diagnostics):
    get_cache_stats, get_coach_metrics = diagnostics
    headers = {}
    if auth_kind == "invalid":
        headers = {"Authorization": "Bearer" + " " + "not-a-valid-token"}
    elif auth_kind == "expired":
        headers = _expired_bearer()
    elif auth_kind == "deleted":
        headers = _bearer("deleted-user", "deleted@example.com")
    elif auth_kind == "disabled":
        headers = _bearer("disabled-user", "disabled@example.com")
    elif auth_kind == "forged-admin-claim":
        headers = _forged_admin_bearer()
    elif auth_kind in {"free-user", "trial-user", "premium-user"}:
        email = {
            "free-user": "free@example.com",
            "trial-user": "trial@example.com",
            "premium-user": "premium@example.com",
        }[auth_kind]
        headers = _bearer(auth_kind, email)
    elif auth_kind in {"admin-free", "admin-premium"}:
        email = f"{auth_kind}@example.com"
        headers = _bearer(auth_kind, email)

    response = await client.get(path, headers=headers)
    assert response.status_code == expected_status

    if expected_status != 200:
        get_cache_stats.assert_not_called()
        get_coach_metrics.assert_not_called()
        return

    if path == "/api/cache/stats":
        assert response.json() == CACHE_STATS
        get_cache_stats.assert_called_once_with()
        get_coach_metrics.assert_not_called()
    else:
        assert response.json() == METRICS_RESPONSE
        get_coach_metrics.assert_called_once_with()
        get_cache_stats.assert_called_once_with()


@pytest.mark.parametrize("path", ENDPOINTS)
def test_diagnostics_remain_free_at_subscription_layer(path):
    assert get_route_access(path) == RouteAccess.FREE


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    (
        ("delete", "/api/cache/clear", "clear_cache"),
        ("delete", "/api/metrics/reset", "reset_coach_metrics"),
    ),
)
@pytest.mark.asyncio
async def test_existing_delete_diagnostics_remain_admin_only(
    method, path, operation, client, monkeypatch
):
    reset_result = {"requests": 4}
    action = Mock(return_value=reset_result)
    monkeypatch.setattr(server, operation, action)

    anonymous = await client.delete(path)
    non_admin = await client.delete(
        path, headers=_bearer("free-user", "free@example.com")
    )
    admin = await client.delete(
        path, headers=_bearer("admin-free", "admin-free@example.com")
    )

    assert anonymous.status_code == 401
    assert non_admin.status_code == 403
    assert admin.status_code == 200
    action.assert_called_once()


@pytest.mark.asyncio
async def test_public_auth_login_is_not_blocked_by_diagnostics_auth(client, monkeypatch):
    import auth.router

    monkeypatch.setattr(auth.router, "_check_rate_limit", AsyncMock())
    response = await client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "NotARealPassword123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_cache_stats_is_subject_to_rate_limiter(client, diagnostics, monkeypatch):
    get_cache_stats, get_coach_metrics = diagnostics
    is_limited = Mock(return_value=True)
    monkeypatch.setattr(server.rate_limiter, "is_limited", is_limited)

    response = await client.get("/api/cache/stats")

    assert response.status_code == 429
    is_limited.assert_called_once()
    get_cache_stats.assert_not_called()
    get_coach_metrics.assert_not_called()
