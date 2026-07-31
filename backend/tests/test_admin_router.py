from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

from admin.router import admin_router
from auth.jwt_utils import create_access_token


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        reverse = direction == -1
        self._docs.sort(key=lambda doc: doc.get(key) or "", reverse=reverse)
        return self

    async def to_list(self, _limit):
        return [doc.copy() for doc in self._docs]


class _FakeCollection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    @staticmethod
    def _match(doc, query):
        for key, value in query.items():
            if isinstance(value, dict):
                if "$gt" in value and not (doc.get(key) is not None and doc.get(key) > value["$gt"]):
                    return False
                continue
            if doc.get(key) != value:
                return False
        return True

    @staticmethod
    def _project(doc, projection):
        if not projection:
            return doc.copy()
        included = {key for key, flag in projection.items() if flag}
        excluded = {key for key, flag in projection.items() if not flag}
        if included:
            result = {key: doc[key] for key in included if key in doc}
        else:
            result = doc.copy()
        for key in excluded:
            result.pop(key, None)
        return result

    async def find_one(self, query, projection=None):
        for doc in self._docs:
            if self._match(doc, query):
                return self._project(doc, projection)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        return _FakeCursor(
            self._project(doc, projection)
            for doc in self._docs
            if self._match(doc, query)
        )


class _FakeDB:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.users = _FakeCollection([
            {
                "id": "admin-1",
                "email": "admin@example.com",
                "role": "admin",
                "is_active": True,
                "is_email_verified": True,
                "created_at": now,
                "last_login_at": now,
            },
            {
                "id": "trial-1",
                "email": "trial@example.com",
                "role": "user",
                "is_active": True,
                "is_email_verified": True,
                "created_at": now - timedelta(days=1),
                "last_login_at": now - timedelta(hours=2),
            },
            {
                "id": "premium-1",
                "email": "premium@example.com",
                "role": "user",
                "is_active": True,
                "is_email_verified": True,
                "created_at": now - timedelta(days=2),
                "last_login_at": now - timedelta(hours=4),
            },
        ])
        self.subscriptions = _FakeCollection([
            {
                "user_id": "admin-1",
                "status": "free",
                "trial_used": False,
            },
            {
                "user_id": "trial-1",
                "status": "trial",
                "trial_used": True,
                "trial_end": (now + timedelta(days=5)).isoformat(),
            },
            {
                "user_id": "premium-1",
                "status": "premium",
                "trial_used": True,
                "premium_expires_at": (now + timedelta(days=30)).isoformat(),
            },
        ])
        self.garmin_connections = _FakeCollection([
            {"user_id": "trial-1", "connected": True},
        ])

    def __getattr__(self, _name):
        return _FakeCollection()


@pytest.fixture
def app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(admin_router)
    app.state.db = _FakeDB()
    return app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _auth(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


@pytest.mark.asyncio
async def test_admin_users_requires_jwt(client):
    response = await client.get("/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_users_rejects_non_admin(client):
    response = await client.get(
        "/admin/users",
        headers=_auth("trial-1", "trial@example.com"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


@pytest.mark.asyncio
async def test_admin_users_returns_status_trial_and_garmin_flags(client):
    response = await client.get(
        "/admin/users",
        headers=_auth("admin-1", "admin@example.com"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3

    by_email = {user["email"]: user for user in payload["users"]}
    assert by_email["admin@example.com"]["is_admin"] is True
    assert by_email["admin@example.com"]["status"] == "free"
    assert by_email["trial@example.com"]["status"] == "trial"
    assert by_email["trial@example.com"]["trial_active"] is True
    assert by_email["trial@example.com"]["trial_used"] is True
    assert by_email["trial@example.com"]["garmin_connected"] is True
    assert by_email["premium@example.com"]["status"] == "premium"
    assert by_email["premium@example.com"]["garmin_connected"] is False
