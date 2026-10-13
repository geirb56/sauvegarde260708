"""Architecture test: legacy `/api/training/week-plan` route is removed."""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-route-removed")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-route-removed")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import server  # noqa: E402
from access_control import ROUTE_ACCESS_MAP, RouteAccess, Tier, UserAccess, get_route_access  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402

pytestmark = pytest.mark.asyncio


async def _mock_get_user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _bearer(user_id: str = "u1", email: str = "u1@example.com") -> dict:
    token = create_access_token(user_id, email)
    return {"Authorization": "Bearer " + token}


async def test_legacy_week_plan_route_is_removed_and_access_fallback_is_premium():
    with patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/training/week-plan", headers=_bearer())

    assert response.status_code == 404

    route_paths = set(server.app.openapi().get("paths", {}).keys())
    assert "/api/training/week-plan" not in route_paths
    assert "/api/training/v2/week" in route_paths

    assert "/api/training/week-plan" not in ROUTE_ACCESS_MAP
    assert ROUTE_ACCESS_MAP["/api/training/"] == RouteAccess.PREMIUM
    assert get_route_access("/api/training/week-plan") == RouteAccess.PREMIUM
