from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Allow imports from backend package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Minimal env for auth/access imports.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")


def _stub_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


for _mod in ("redis", "redis.asyncio", "redis.exceptions"):
    if _mod not in sys.modules:
        _stub_module(_mod)

import redis.exceptions as _rex  # noqa: E402
if not hasattr(_rex, "ResponseError"):
    _rex.ResponseError = type("ResponseError", (Exception,), {})

_events_stream_stub = _stub_module("events.stream")
_events_stream_stub.emit_activity_created = AsyncMock()

if "config" not in sys.modules:
    _stub_module("config")
_secrets_stub = ModuleType("config.secrets")
_secrets_stub.get_secret = MagicMock(return_value=None)
sys.modules["config.secrets"] = _secrets_stub

from access_control import RouteAccess, get_route_access  # noqa: E402
from garmin import service as svc  # noqa: E402
from garmin.providers.base import STATUS_CONNECTED, STATUS_ERROR  # noqa: E402
from garmin.providers.gccli_provider import GccliProvider  # noqa: E402
from garmin.runner import GccliError  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_free_funnel_routes_are_accessible_for_free_users():
    assert get_route_access("/api/garmin/status") == RouteAccess.FREE
    assert get_route_access("/api/garmin/connect") == RouteAccess.FREE
    assert get_route_access("/api/garmin/disconnect") == RouteAccess.FREE
    assert get_route_access("/api/garmin/sync") == RouteAccess.PREMIUM
    assert get_route_access("/api/garmin/activities") == RouteAccess.PREMIUM


def test_connect_derives_identity_from_server_auth_status_not_frontend():
    db = MagicMock()
    db.garmin_connections.update_one = AsyncMock()

    provider = MagicMock()
    provider.connect.return_value = SimpleNamespace(status=STATUS_CONNECTED, detail="Garmin connected")
    provider.get_profile.return_value = {"email": " USER@example.COM "}

    with (
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "activate_garmin_trial", new=AsyncMock()) as mock_activate,
    ):
        _run(
            svc.connect(
                db,
                "user-1",
                garmin_username="spoofed-frontend@example.com",
                garmin_password="pw",
            )
        )

    mock_activate.assert_awaited_once_with(db, "user-1", "user@example.com")


def test_connect_skips_trial_activation_when_auth_status_email_missing():
    db = MagicMock()
    db.garmin_connections.update_one = AsyncMock()

    provider = MagicMock()
    provider.connect.return_value = SimpleNamespace(status=STATUS_CONNECTED, detail="Garmin connected")
    provider.get_profile.return_value = {}

    with (
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "activate_garmin_trial", new=AsyncMock()) as mock_activate,
    ):
        _run(
            svc.connect(
                db,
                "user-1",
                garmin_username="frontend@example.com",
                garmin_password="pw",
            )
        )

    mock_activate.assert_not_awaited()


def test_gccli_connect_log_does_not_expose_sensitive_error(caplog):
    runner = MagicMock()
    runner.is_available.return_value = True
    runner.is_authenticated.return_value = False
    runner.login.side_effect = GccliError("gccli login failed: SuperSecret123")

    provider = GccliProvider(runner=runner, account="user@example.com")

    with caplog.at_level(logging.ERROR):
        result = provider.connect(
            user_id="user-1",
            garmin_username="user@example.com",
            garmin_password="pw",
        )

    assert result.status == STATUS_ERROR
    assert "SuperSecret123" not in caplog.text
    assert "[gccli] connect failed" in caplog.text
