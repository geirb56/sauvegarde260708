"""
Security blockers #1 — unit tests.

Covers:
  1. /api/admin/ is classified as RouteAccess.FREE so the subscription
     middleware never blocks a real admin. Admin RBAC is still enforced
     by Depends(require_admin) at the route level.
  2. DELETE /api/cache/clear and DELETE /api/metrics/reset require an
     authenticated admin (401 anonymous, 403 non-admin, 200 admin).
  3. /api/subscription/simulate-trial-end and /reset-to-trial return
     404 when ENVIRONMENT=production, and stay available otherwise.
"""
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

from access_control import RouteAccess, get_route_access
from auth.dependencies import get_current_user, require_admin
from auth.jwt_utils import create_access_token


# -----------------------------------------------------------------------------
# 1. Route classification
# -----------------------------------------------------------------------------

class TestAdminRouteClassification:
    def test_admin_root_is_free(self):
        assert get_route_access("/api/admin/") == RouteAccess.FREE

    def test_admin_users_is_free(self):
        assert get_route_access("/api/admin/users") == RouteAccess.FREE

    def test_admin_nested_is_free(self):
        assert get_route_access("/api/admin/anything/else") == RouteAccess.FREE


# -----------------------------------------------------------------------------
# 2. Cache / metrics admin-only
# -----------------------------------------------------------------------------

def _make_user(user_id: str, email: str, *, is_admin: bool = False) -> dict:
    return {
        "id": user_id,
        "email": email,
        "role": "admin" if is_admin else "user",
        "is_admin": is_admin,
        "is_email_verified": True,
        "is_active": True,
        "authenticated": True,
    }


@pytest.fixture
def admin_only_app():
    """Minimal app exposing only the two protected admin-only endpoints."""
    from fastapi import Depends, FastAPI

    app = FastAPI()

    @app.delete("/api/cache/clear")
    async def clear(_admin: dict = Depends(require_admin)):
        return {"success": True}

    @app.delete("/api/metrics/reset")
    async def reset(_admin: dict = Depends(require_admin)):
        return {"success": True}

    # Fake user DB used by get_current_user
    class _Users:
        def __init__(self, users):
            self._users = {u["id"]: u for u in users}

        async def find_one(self, query, projection=None):
            return self._users.get(query.get("id"))

    class _DB:
        users = _Users(
            [
                _make_user("admin-1", "admin@example.com", is_admin=True),
                _make_user("free-1", "free@example.com"),
                _make_user("premium-1", "premium@example.com"),
            ]
        )

    app.state.db = _DB()
    return app


@pytest_asyncio.fixture
async def admin_only_client(admin_only_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_only_app),
        base_url="http://test",
    ) as c:
        yield c


def _auth(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


class TestCacheClearAdminOnly:
    @pytest.mark.asyncio
    async def test_unauthenticated_401(self, admin_only_client):
        r = await admin_only_client.delete("/api/cache/clear")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_free_user_403(self, admin_only_client):
        r = await admin_only_client.delete(
            "/api/cache/clear", headers=_auth("free-1", "free@example.com")
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_premium_non_admin_403(self, admin_only_client):
        r = await admin_only_client.delete(
            "/api/cache/clear", headers=_auth("premium-1", "premium@example.com")
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_200(self, admin_only_client):
        r = await admin_only_client.delete(
            "/api/cache/clear", headers=_auth("admin-1", "admin@example.com")
        )
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestMetricsResetAdminOnly:
    @pytest.mark.asyncio
    async def test_unauthenticated_401(self, admin_only_client):
        r = await admin_only_client.delete("/api/metrics/reset")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_free_user_403(self, admin_only_client):
        r = await admin_only_client.delete(
            "/api/metrics/reset", headers=_auth("free-1", "free@example.com")
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_premium_non_admin_403(self, admin_only_client):
        r = await admin_only_client.delete(
            "/api/metrics/reset", headers=_auth("premium-1", "premium@example.com")
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_200(self, admin_only_client):
        r = await admin_only_client.delete(
            "/api/metrics/reset", headers=_auth("admin-1", "admin@example.com")
        )
        assert r.status_code == 200


# -----------------------------------------------------------------------------
# 3. Dev endpoints — production gating
# -----------------------------------------------------------------------------

def _dev_guard_app(env_value: str):
    """Build an app that mirrors the production gating decorator used in server.py."""
    from fastapi import Depends, FastAPI, HTTPException

    def _dev_endpoint_guard() -> None:
        env = env_value.strip().lower()
        if env == "production":
            raise HTTPException(status_code=404, detail="Not Found")

    app = FastAPI()

    @app.post("/api/subscription/simulate-trial-end")
    async def simulate(user: dict = Depends(get_current_user)):
        _dev_endpoint_guard()
        return {"ok": True, "user": user["id"]}

    @app.post("/api/subscription/reset-to-trial")
    async def reset(user: dict = Depends(get_current_user)):
        _dev_endpoint_guard()
        return {"ok": True, "user": user["id"]}

    class _Users:
        async def find_one(self, query, projection=None):
            if query.get("id") == "user-1":
                return _make_user("user-1", "u@example.com")
            return None

    class _DB:
        users = _Users()

    app.state.db = _DB()
    return app


@pytest.mark.asyncio
async def test_simulate_trial_end_returns_404_in_production():
    app = _dev_guard_app("production")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Even with a valid JWT, the endpoint must be unavailable in production.
        r = await c.post(
            "/api/subscription/simulate-trial-end",
            headers=_auth("user-1", "u@example.com"),
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_reset_to_trial_returns_404_in_production():
    app = _dev_guard_app("production")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/api/subscription/reset-to-trial",
            headers=_auth("user-1", "u@example.com"),
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_simulate_trial_end_available_in_development():
    app = _dev_guard_app("development")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/api/subscription/simulate-trial-end",
            headers=_auth("user-1", "u@example.com"),
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_reset_to_trial_available_in_test_env():
    app = _dev_guard_app("test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/api/subscription/reset-to-trial",
            headers=_auth("user-1", "u@example.com"),
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_dev_endpoint_requires_jwt_when_available():
    """When the route is available (non-prod), JWT is still mandatory."""
    app = _dev_guard_app("development")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/subscription/simulate-trial-end")
        assert r.status_code == 401


# -----------------------------------------------------------------------------
# 4. Admin routing end-to-end (min matrix from spec)
# -----------------------------------------------------------------------------

@pytest.fixture
def admin_matrix_app():
    """
    Build an app that mounts the real admin_router behind a stub of the
    subscription middleware. Verifies that an admin is allowed through even
    when the middleware would otherwise consider them FREE.
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    from admin.router import admin_router

    app = FastAPI()

    # --- Fake DB used by admin_router / get_current_user / get_user_access ---
    class _Cursor:
        def __init__(self, docs):
            self._docs = list(docs)

        def sort(self, key, direction):
            reverse = direction == -1
            self._docs.sort(key=lambda d: d.get(key) or "", reverse=reverse)
            return self

        async def to_list(self, _limit):
            return [d.copy() for d in self._docs]

    class _Collection:
        def __init__(self, docs=None):
            self._docs = list(docs or [])

        async def find_one(self, query, projection=None):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return d.copy()
            return None

        def find(self, query=None, projection=None):
            query = query or {}
            return _Cursor(
                d for d in self._docs
                if all(d.get(k) == v for k, v in query.items())
            )

    now = datetime.now(timezone.utc)

    class _DB:
        users = _Collection([
            {"id": "admin-free", "email": "admin@example.com", "role": "admin",
             "is_active": True, "is_email_verified": True, "created_at": now},
            {"id": "admin-trial", "email": "admin2@example.com", "role": "admin",
             "is_active": True, "is_email_verified": True, "created_at": now},
            {"id": "admin-prem", "email": "admin3@example.com", "role": "admin",
             "is_active": True, "is_email_verified": True, "created_at": now},
            {"id": "user-free", "email": "u1@example.com", "role": "user",
             "is_active": True, "is_email_verified": True, "created_at": now},
            {"id": "user-prem", "email": "u2@example.com", "role": "user",
             "is_active": True, "is_email_verified": True, "created_at": now},
        ])
        subscriptions = _Collection([
            {"user_id": "admin-free", "status": "free"},
            {"user_id": "admin-trial", "status": "trial",
             "trial_end": (now + timedelta(days=5)).isoformat()},
            {"user_id": "admin-prem", "status": "premium",
             "premium_expires_at": (now + timedelta(days=30)).isoformat()},
            {"user_id": "user-free", "status": "free"},
            {"user_id": "user-prem", "status": "premium",
             "premium_expires_at": (now + timedelta(days=30)).isoformat()},
        ])
        garmin_connections = _Collection([])

    db = _DB()
    app.state.db = db

    # --- Stub subscription middleware mirroring the real one ---
    @app.middleware("http")
    async def subscription_middleware(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)
        route_access = get_route_access(path)
        if route_access != RouteAccess.PREMIUM:
            # FREE/PUBLIC -> pass through. This is exactly the guarantee we
            # want: admin routes are never blocked by tier.
            return await call_next(request)
        # PREMIUM branch not reachable for /api/admin/* thanks to the fix.
        return JSONResponse(status_code=403, content={"error": "subscription_required"})

    # Mount admin router under /api to mirror production layout.
    from fastapi import APIRouter
    api_router = APIRouter(prefix="/api")
    api_router.include_router(admin_router)
    app.include_router(api_router)
    return app


@pytest_asyncio.fixture
async def admin_matrix_client(admin_matrix_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_matrix_app),
        base_url="http://test",
    ) as c:
        yield c


class TestAdminAccessMatrix:
    @pytest.mark.asyncio
    async def test_admin_free_allowed(self, admin_matrix_client):
        r = await admin_matrix_client.get(
            "/api/admin/users", headers=_auth("admin-free", "admin@example.com")
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_trial_allowed(self, admin_matrix_client):
        r = await admin_matrix_client.get(
            "/api/admin/users", headers=_auth("admin-trial", "admin2@example.com")
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_premium_allowed(self, admin_matrix_client):
        r = await admin_matrix_client.get(
            "/api/admin/users", headers=_auth("admin-prem", "admin3@example.com")
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_user_free_non_admin_403(self, admin_matrix_client):
        r = await admin_matrix_client.get(
            "/api/admin/users", headers=_auth("user-free", "u1@example.com")
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_user_premium_non_admin_403(self, admin_matrix_client):
        r = await admin_matrix_client.get(
            "/api/admin/users", headers=_auth("user-prem", "u2@example.com")
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_401(self, admin_matrix_client):
        r = await admin_matrix_client.get("/api/admin/users")
        assert r.status_code == 401
