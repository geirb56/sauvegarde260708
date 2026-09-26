"""PR #128 — exact /api/dashboard legacy prescription route must be removed."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "integration-test-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402


def _bearer(user_id: str, email: str = "test@example.com") -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _get_user_access(_db, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def test_exact_dashboard_route_absent_from_route_table():
    route_paths = {getattr(route, "path", None) for route in server.app.routes}
    assert "/api/dashboard" not in route_paths
    assert "/api/dashboard/insight" in route_paths


@pytest.mark.asyncio
async def test_exact_dashboard_returns_404_for_authenticated_premium():
    with patch("server.get_user_access", AsyncMock(side_effect=_get_user_access)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/dashboard", headers=_bearer("premium-user"))

    assert response.status_code == 404, response.text


def test_server_no_longer_imports_or_registers_dashboard_router():
    source = Path(os.path.join(_BACKEND_DIR, "server.py")).read_text(encoding="utf-8")
    assert "from api.dashboard import dashboard_router" not in source
    assert "include_router(dashboard_router" not in source


def test_legacy_dashboard_authority_modules_are_deleted():
    assert not Path(os.path.join(_BACKEND_DIR, "api", "dashboard.py")).exists()
    assert not Path(os.path.join(_BACKEND_DIR, "services", "dashboard_service.py")).exists()
    assert not Path(os.path.join(_BACKEND_DIR, "engine", "workout_selector.py")).exists()


def test_runtime_sources_have_no_legacy_dashboard_import_chain_strings():
    runtime_files = [
        Path(os.path.join(_BACKEND_DIR, "server.py")),
        Path(os.path.join(_BACKEND_DIR, "subscription_manager.py")),
        Path(os.path.join(_BACKEND_DIR, "access_control.py")),
    ]
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    assert "from api.dashboard import dashboard_router" not in runtime_text
    assert "include_router(dashboard_router, prefix=\"/api\")" not in runtime_text
    assert "from services.dashboard_service import get_dashboard" not in runtime_text
    assert "from engine.workout_selector import select_workout" not in runtime_text
