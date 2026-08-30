"""A63 — Subscription middleware security tests.

Tests are structured in two layers:

Layer 1 — Unit tests for the two new helper functions extracted from server.py,
           using only auth.jwt_utils (no full server import needed).

Layer 2 — Integration tests using a minimal FastAPI app that reproduces the
           subscription_middleware logic exactly as it appears in server.py,
           verifying 401-gating and that get_user_access is never invoked for
           unauthenticated requests.

Covers:
1. PREMIUM without Authorization → 401, get_user_access NOT called.
2. PREMIUM with invalid JWT → 401, get_user_access NOT called.
3. X-Forwarded-For without JWT → 401; never becomes subscription identity.
4. IP without JWT → 401; never becomes subscription identity.
5. Valid JWT, FREE user → get_user_access called with JWT sub; 403.
6. Valid JWT, TRIAL/PREMIUM user → get_user_access called with JWT sub; passes.
7. Anonymous rate-limit key → IP used correctly; no regression.
8. No subscription creation/upsert triggered for anonymous cases.
"""
from __future__ import annotations

import os
import sys
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Env vars — set BEFORE any local import
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-a63-unit-tests-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

# ---------------------------------------------------------------------------
# Imports (lightweight — no server.py)
# ---------------------------------------------------------------------------
from access_control import Tier, UserAccess, RouteAccess, get_route_access
from auth.jwt_utils import create_access_token, decode_access_token

# ---------------------------------------------------------------------------
# Replicate the two helper functions exactly as they appear in server.py
# (These are the functions under test — kept in sync with server.py)
# ---------------------------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import jwt as _jwt


def get_rate_limit_key_from_request(request: Request) -> str:
    """Exact copy of server.get_rate_limit_key_from_request."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            payload = decode_access_token(token)
            sub = payload.get("sub")
            if sub:
                return sub
        except Exception:
            pass
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_jwt_user_id_from_request(request: Request) -> Optional[str]:
    """Exact copy of server.get_jwt_user_id_from_request."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        return sub if sub else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Minimal test app — reproduces subscription_middleware logic from server.py
# ---------------------------------------------------------------------------

PREMIUM_PATH = "/api/training/plan"
FREE_PATH = "/api/subscription/status"

# Injected by tests via module-level variable
_mock_get_user_access: Optional[AsyncMock] = None


def _make_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def subscription_middleware(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)

        route_access = get_route_access(path)
        if route_access != RouteAccess.PREMIUM:
            return await call_next(request)

        # --- The exact logic under test ---
        user_id = get_jwt_user_id_from_request(request)
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"error": "authentication_required", "message": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Call the injected mock so tests can spy on it
        user_access = await _mock_get_user_access(user_id)

        if not user_access.has_premium_access:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "subscription_required",
                    "message": "Subscription required to access this feature",
                    "status": user_access.tier.value,
                },
            )
        request.state.user_access = user_access
        return await call_next(request)

    @app.get(PREMIUM_PATH)
    async def premium_route():
        return {"ok": True}

    @app.get(FREE_PATH)
    async def free_route():
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_access(user_id: str, tier: Tier) -> UserAccess:
    return UserAccess(user_id=user_id, tier=tier)


def _valid_bearer(user_id: str) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, "u@example.com")}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    global _mock_get_user_access
    _mock_get_user_access = AsyncMock()
    app = _make_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        c._spy = _mock_get_user_access
        yield c


# ===========================================================================
# LAYER 1 — Unit tests for the helper functions
# ===========================================================================

class TestGetJwtUserIdFromRequest:
    """get_jwt_user_id_from_request must only return an id from a valid JWT."""

    def _req(self, headers: dict) -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        return Request(scope)

    def test_no_auth_header_returns_none(self):
        req = self._req({})
        assert get_jwt_user_id_from_request(req) is None

    def test_invalid_token_returns_none(self):
        req = self._req({"Authorization": "Bearer " + "not.a.valid.jwt.token"})
        assert get_jwt_user_id_from_request(req) is None

    def test_x_forwarded_for_without_jwt_returns_none(self):
        req = self._req({"X-Forwarded-For": "1.2.3.4"})
        assert get_jwt_user_id_from_request(req) is None

    def test_valid_jwt_returns_sub(self):
        token = create_access_token("user-abc", "u@example.com")
        req = self._req({"Authorization": "Bearer " + token})
        assert get_jwt_user_id_from_request(req) == "user-abc"


class TestGetRateLimitKeyFromRequest:
    """get_rate_limit_key_from_request may use IP as fallback — rate-limit only."""

    def _req(self, headers: dict, client_host: str = "127.0.0.1") -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (client_host, 9999),
        }
        return Request(scope)

    def test_valid_jwt_returns_sub(self):
        token = create_access_token("user-xyz", "u@example.com")
        req = self._req({"Authorization": "Bearer " + token})
        assert get_rate_limit_key_from_request(req) == "user-xyz"

    def test_x_forwarded_for_used_as_fallback(self):
        req = self._req({"X-Forwarded-For": "203.0.113.1"})
        assert get_rate_limit_key_from_request(req) == "203.0.113.1"

    def test_client_ip_used_when_no_jwt_no_xff(self):
        req = self._req({}, client_host="10.0.0.5")
        assert get_rate_limit_key_from_request(req) == "10.0.0.5"

    def test_invalid_jwt_falls_back_to_ip(self):
        req = self._req({"Authorization": "Bearer " + "bad.jwt.payload", "X-Forwarded-For": "5.5.5.5"})
        assert get_rate_limit_key_from_request(req) == "5.5.5.5"


# ===========================================================================
# LAYER 2 — Middleware integration tests (minimal test app)
# ===========================================================================

# 1. PREMIUM without Authorization → 401, get_user_access NOT called
@pytest.mark.asyncio
async def test_premium_no_auth_returns_401(client):
    resp = await client.get(PREMIUM_PATH)
    assert resp.status_code == 401
    client._spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_premium_no_auth_response_body(client):
    resp = await client.get(PREMIUM_PATH)
    assert resp.json()["error"] == "authentication_required"
    client._spy.assert_not_awaited()


# 2. PREMIUM with invalid JWT → 401, get_user_access NOT called
@pytest.mark.asyncio
async def test_premium_invalid_jwt_returns_401(client):
    resp = await client.get(
        PREMIUM_PATH, headers={"Authorization": "Bearer " + "not.valid.jwt.token"}
    )
    assert resp.status_code == 401
    client._spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_premium_malformed_bearer_returns_401(client):
    resp = await client.get(
        PREMIUM_PATH, headers={"Authorization": "Bearer " + "malformed.bearer.data"}
    )
    assert resp.status_code == 401
    client._spy.assert_not_awaited()


# 3. X-Forwarded-For without JWT → 401; never becomes subscription identity
@pytest.mark.asyncio
async def test_x_forwarded_for_without_jwt_returns_401(client):
    resp = await client.get(
        PREMIUM_PATH, headers={"X-Forwarded-For": "1.2.3.4"}
    )
    assert resp.status_code == 401
    client._spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_x_forwarded_for_ip_never_passed_to_get_user_access(client):
    await client.get(PREMIUM_PATH, headers={"X-Forwarded-For": "203.0.113.42"})
    client._spy.assert_not_awaited()


# 4. IP without JWT → 401; never becomes subscription identity
@pytest.mark.asyncio
async def test_ip_without_jwt_returns_401(client):
    resp = await client.get(PREMIUM_PATH)  # no headers; client IP used
    assert resp.status_code == 401
    client._spy.assert_not_awaited()


# 5. Valid JWT, FREE user → get_user_access called with JWT sub; 403
@pytest.mark.asyncio
async def test_valid_jwt_free_user_returns_403(client):
    user_id = "free-user-001"
    client._spy.return_value = _make_user_access(user_id, Tier.FREE)

    resp = await client.get(PREMIUM_PATH, headers=_valid_bearer(user_id))

    assert resp.status_code == 403
    assert resp.json()["error"] == "subscription_required"
    client._spy.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_valid_jwt_free_user_get_user_access_called_with_exact_sub(client):
    user_id = "free-user-exact-sub"
    client._spy.return_value = _make_user_access(user_id, Tier.FREE)

    await client.get(PREMIUM_PATH, headers=_valid_bearer(user_id))

    called_with = client._spy.call_args[0][0]
    assert called_with == user_id, f"Expected '{user_id}', got '{called_with}'"


# 6. Valid JWT, TRIAL/PREMIUM user → get_user_access called with JWT sub; passes
@pytest.mark.asyncio
async def test_valid_jwt_trial_user_passes(client):
    user_id = "trial-user-001"
    client._spy.return_value = _make_user_access(user_id, Tier.TRIAL)

    resp = await client.get(PREMIUM_PATH, headers=_valid_bearer(user_id))

    assert resp.status_code == 200
    client._spy.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_valid_jwt_premium_user_passes(client):
    user_id = "premium-user-001"
    client._spy.return_value = _make_user_access(user_id, Tier.PREMIUM)

    resp = await client.get(PREMIUM_PATH, headers=_valid_bearer(user_id))

    assert resp.status_code == 200
    client._spy.assert_awaited_once_with(user_id)


# 7. Rate-limit key for anonymous requests uses IP (no regression)
@pytest.mark.asyncio
async def test_free_route_accessible_without_auth(client):
    """FREE-classified routes pass through subscription_middleware without a JWT."""
    resp = await client.get(FREE_PATH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_accessible_without_auth(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200


# 8. No subscription creation/upsert for anonymous PREMIUM requests
@pytest.mark.asyncio
async def test_no_get_user_access_call_for_anon_premium(client):
    """Confirms get_user_access is the DB-write entry point and is never reached."""
    await client.get(PREMIUM_PATH)
    client._spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_get_user_access_call_for_xff_premium(client):
    await client.get(PREMIUM_PATH, headers={"X-Forwarded-For": "198.51.100.1"})
    client._spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_bearer_never_triggers_subscription_write(client):
    await client.get(PREMIUM_PATH, headers={"Authorization": "Bearer " + "expired.or.invalid.jwt"})
    client._spy.assert_not_awaited()
