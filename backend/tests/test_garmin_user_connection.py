"""Tests for per-user Garmin connection (GARMIN_FIX).

Verifies:
  - a per-user provider NEVER falls back to the global .env credentials;
  - the global bootstrap provider still may use them;
  - connect uses the user-supplied credentials, never the environment;
  - credentials never appear in the ConnectResult;
  - service.connect persists data under the authenticated user_id only;
  - list_activities is always scoped by user_id (isolation).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")


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
# get_secret returns the GLOBAL credentials if it is ever consulted.
_secrets_stub.get_secret = MagicMock(side_effect=lambda key, *a, **k: {
    "GARMIN_USERNAME": "GLOBAL@garmin.com",
    "GARMIN_PASSWORD": "GLOBAL_PASSWORD",
}.get(key))
sys.modules["config.secrets"] = _secrets_stub

from garmin import service as svc  # noqa: E402
from garmin.providers.base import STATUS_CONNECTED, STATUS_ERROR  # noqa: E402
from garmin.providers.gccli_provider import GccliProvider  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _runner(authenticated: bool = False):
    r = MagicMock()
    r.is_available.return_value = True
    r.is_authenticated.return_value = authenticated
    return r


# --------------------------------------------------------------------------
# 1. No global .env fallback for a per-user connection
# --------------------------------------------------------------------------

def test_per_user_connect_without_credentials_never_uses_env():
    _secrets_stub.get_secret.reset_mock()
    runner = _runner(authenticated=False)
    provider = GccliProvider(runner=runner, account=None, allow_global_account=False)

    result = provider.connect(user_id="user-1")  # no credentials supplied

    assert result.status == STATUS_ERROR
    assert "credentials required" in result.detail.lower()
    # Must NOT log in with anything (in particular not the global account).
    runner.login.assert_not_called()
    # Must NOT read the global credentials from the environment.
    assert _secrets_stub.get_secret.call_count == 0


def test_per_user_account_is_none_without_env_fallback():
    provider = GccliProvider(runner=_runner(), account=None, allow_global_account=False)
    assert provider._account() is None


def test_bootstrap_provider_still_uses_env_account():
    provider = GccliProvider(runner=_runner(), account=None, allow_global_account=True)
    assert provider._account() == "GLOBAL@garmin.com"


# --------------------------------------------------------------------------
# 2. Connect uses the user-supplied credentials, never the environment
# --------------------------------------------------------------------------

def test_connect_uses_supplied_credentials_not_env():
    _secrets_stub.get_secret.reset_mock()
    runner = _runner(authenticated=False)
    provider = GccliProvider(runner=runner, account=None, allow_global_account=False)

    result = provider.connect(
        user_id="user-1",
        garmin_username="alice@garmin.com",
        garmin_password="alice-secret",
    )

    assert result.status == STATUS_CONNECTED
    runner.login.assert_called_once_with("alice@garmin.com", "alice-secret")
    # The global env credentials must never be consulted.
    assert _secrets_stub.get_secret.call_count == 0


def test_connect_username_without_password_is_rejected_no_env_password():
    _secrets_stub.get_secret.reset_mock()
    runner = _runner(authenticated=False)
    provider = GccliProvider(runner=runner, account=None, allow_global_account=False)

    result = provider.connect(user_id="user-1", garmin_username="bob@garmin.com")

    assert result.status == STATUS_ERROR
    runner.login.assert_not_called()
    assert _secrets_stub.get_secret.call_count == 0


# --------------------------------------------------------------------------
# 3. Credentials never leak into the API result
# --------------------------------------------------------------------------

def test_credentials_never_in_connect_result():
    runner = _runner(authenticated=False)
    provider = GccliProvider(runner=runner, account=None, allow_global_account=False)

    result = provider.connect(
        user_id="user-1",
        garmin_username="carol@garmin.com",
        garmin_password="carol-secret",
    )
    blob = f"{result.status} {result.detail}"
    assert "carol-secret" not in blob


# --------------------------------------------------------------------------
# 4. service.connect persists under the authenticated user_id only
# --------------------------------------------------------------------------

def test_service_connect_writes_under_authenticated_user_id():
    db = MagicMock()
    db.garmin_connections.update_one = AsyncMock()

    provider = MagicMock()
    provider.connect.return_value = SimpleNamespace(status=STATUS_CONNECTED, detail="Garmin connected")
    provider.get_profile.return_value = {"email": "dave@garmin.com"}

    with (
        patch.object(svc, "get_provider_for_user", return_value=provider) as mk,
        patch.object(svc, "activate_garmin_trial", new=AsyncMock()),
    ):
        _run(svc.connect(db, "user-A", garmin_username="dave@garmin.com", garmin_password="pw"))

    # Provider was built for the authenticated user id.
    mk.assert_called_once_with("user-A", garmin_account="dave@garmin.com")
    # Persisted connection is scoped to that user id.
    args, kwargs = db.garmin_connections.update_one.call_args
    assert args[0] == {"user_id": "user-A"}
    assert args[1]["$set"]["user_id"] == "user-A"


# --------------------------------------------------------------------------
# 5. list_activities is always scoped by user_id (A cannot see B)
# --------------------------------------------------------------------------

def test_list_activities_is_scoped_by_user_id():
    captured = {}

    class _Cursor:
        def sort(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        async def to_list(self, length=None):
            return []

    def _find(query, projection=None):
        captured["query"] = query
        return _Cursor()

    db = MagicMock()
    db.garmin_activities.find = _find

    _run(svc.list_activities(db, "user-B", limit=10))
    assert captured["query"] == {"user_id": "user-B"}
