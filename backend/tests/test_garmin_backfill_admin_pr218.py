"""PR218 — A36 Security: /api/garmin/backfill?scope=all must be admin-only.

Tests verify:
  TEST 1  — unauthenticated → 401/403, no global job
  TEST 2  — normal user + scope=all → 403, no global job, no USER_B mutation
  TEST 3  — normal user + own scope (scope=user) → 200, job scoped to USER_A only
  TEST 4  — admin + scope=all → 200, global task started
  TEST 5  — forged admin info (is_admin/role in payload) → still 403
  TEST 6  — multi-user isolation: USER_A cannot trigger backfill for USER_B
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-pr218-backfill-admin-32c")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ADMIN_EMAILS", "admin@test.com")

from auth.jwt_utils import create_access_token
from fastapi import FastAPI, Request

# ---------------------------------------------------------------------------
# Minimal fake DB
# ---------------------------------------------------------------------------

class _Collection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    async def find_one(self, query, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items() if not isinstance(v, dict)):
                return dict(d)
        return None

    def find(self, query=None, projection=None):
        return _Cursor([])

    async def update_one(self, *a, **kw):
        pass

    async def insert_one(self, doc):
        self._docs.append(dict(doc))


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **kw):
        return self

    async def to_list(self, length=None):
        return list(self._docs[:length] if length else self._docs)


class _FakeDB:
    def __init__(self, users):
        self.users = _Collection(users)

    def __getattr__(self, name):
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

USER_A_ID = str(uuid.uuid4())
USER_A_EMAIL = "usera@test.com"
USER_B_ID = str(uuid.uuid4())
USER_B_EMAIL = "userb@test.com"
ADMIN_ID = str(uuid.uuid4())
ADMIN_EMAIL = "admin@test.com"  # in ADMIN_EMAILS env


def _make_users():
    return [
        {"id": USER_A_ID, "email": USER_A_EMAIL, "is_active": True, "is_email_verified": True},
        {"id": USER_B_ID, "email": USER_B_EMAIL, "is_active": True, "is_email_verified": True},
        {"id": ADMIN_ID, "email": ADMIN_EMAIL, "is_active": True, "is_email_verified": True},
    ]


def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


# ---------------------------------------------------------------------------
# Build minimal test app
# ---------------------------------------------------------------------------

from api.garmin import garmin_router


def _build_app(fake_db: _FakeDB) -> FastAPI:
    app = FastAPI()
    app.state.db = fake_db

    # Wire the garmin router under /api prefix to match real server
    from fastapi import APIRouter
    api_router = APIRouter(prefix="/api")
    api_router.include_router(garmin_router)
    app.include_router(api_router)
    return app


# ---------------------------------------------------------------------------
# Shared call helper
# ---------------------------------------------------------------------------

async def _post(app: FastAPI, path: str, headers: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.post(path, headers=headers or {})


# ---------------------------------------------------------------------------
# TEST 1 — unauthenticated → 401/403, no global job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthenticated_scope_all_rejected():
    """No JWT → 401; global backfill function must not be called."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    with patch(
        "api.garmin.backfill_connected_users_run_index_history",
        new=AsyncMock(),
    ) as mock_global:
        r = await _post(app, "/api/garmin/backfill?scope=all")

    assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
    mock_global.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 2 — normal user + scope=all → 403, no global job, no USER_B mutation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_user_scope_all_forbidden():
    """Authenticated non-admin + scope=all → 403; global backfill not invoked."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    with patch(
        "api.garmin.backfill_connected_users_run_index_history",
        new=AsyncMock(),
    ) as mock_global:
        r = await _post(app, "/api/garmin/backfill?scope=all",
                        headers=_bearer(USER_A_ID, USER_A_EMAIL))

    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
    mock_global.assert_not_called()


@pytest.mark.asyncio
async def test_normal_user_scope_all_no_userb_mutation():
    """USER_A with scope=all → 403; backfill_user never called for USER_B."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    with (
        patch("api.garmin.backfill_connected_users_run_index_history", new=AsyncMock()) as mock_global,
        patch("api.garmin.garmin_backfill.backfill_user", new=AsyncMock()) as mock_single,
        patch("api.garmin.backfill_run_index_history", new=AsyncMock()) as mock_history,
    ):
        r = await _post(app, "/api/garmin/backfill?scope=all",
                        headers=_bearer(USER_A_ID, USER_A_EMAIL))

    assert r.status_code == 403
    mock_global.assert_not_called()
    # Confirm backfill_user was never called with USER_B's id either
    for call_args in mock_single.call_args_list:
        assert USER_B_ID not in call_args.args and USER_B_ID not in call_args.kwargs.values(), \
            "backfill_user was called with USER_B's id"


# ---------------------------------------------------------------------------
# TEST 3 — normal user + own scope → 200, job scoped to USER_A only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_user_own_scope_allowed():
    """Authenticated user with default scope → 200; result scoped to USER_A."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    mock_result = {"rebuilt": 3, "cache_items": 3}

    with (
        patch("api.garmin.garmin_backfill.backfill_user", new=AsyncMock(return_value=mock_result)) as mock_single,
        patch("api.garmin.backfill_run_index_history", new=AsyncMock(return_value={})) as mock_hist,
        patch("api.garmin._dic.invalidate_user") as mock_inv,
    ):
        # Default scope=user (no query param)
        r = await _post(app, "/api/garmin/backfill",
                        headers=_bearer(USER_A_ID, USER_A_EMAIL))

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "ok"

    # backfill_user called exactly once with USER_A's db + user_id
    mock_single.assert_awaited_once()
    call_args = mock_single.call_args
    assert call_args.args[1] == USER_A_ID or call_args.kwargs.get("user_id") == USER_A_ID, \
        f"backfill_user called with wrong user_id: {call_args}"

    # Cache invalidated for USER_A
    mock_inv.assert_called_once_with(USER_A_ID)


# ---------------------------------------------------------------------------
# TEST 4 — admin + scope=all → 200, global task started
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_scope_all_allowed():
    """Admin user + scope=all → 200; global backfill task created."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    started_tasks = []

    async def _fake_global_backfill(db):
        pass

    async def _capturing_create_task(coro):
        started_tasks.append(coro)
        # Drain the coroutine so it doesn't warn about never being awaited
        try:
            await coro
        except Exception:
            pass

    with (
        patch("api.garmin.backfill_connected_users_run_index_history", new=_fake_global_backfill),
        patch("asyncio.create_task", side_effect=lambda coro: asyncio.ensure_future(coro)) as mock_create,
    ):
        r = await _post(app, "/api/garmin/backfill?scope=all",
                        headers=_bearer(ADMIN_ID, ADMIN_EMAIL))

    assert r.status_code == 200, f"Expected 200 for admin, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "started"
    assert body.get("scope") == "all"
    mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 5 — forged admin info → still 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forged_admin_role_in_body_rejected():
    """Sending role=admin or is_admin=true as query params must not grant scope=all."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    with patch(
        "api.garmin.backfill_connected_users_run_index_history",
        new=AsyncMock(),
    ) as mock_global:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Attempt 1: role=admin as query param
            r1 = await client.post(
                "/api/garmin/backfill?scope=all&role=admin",
                headers=_bearer(USER_A_ID, USER_A_EMAIL),
            )
            # Attempt 2: is_admin=true as query param
            r2 = await client.post(
                "/api/garmin/backfill?scope=all&is_admin=true",
                headers=_bearer(USER_A_ID, USER_A_EMAIL),
            )

    assert r1.status_code == 403, f"Expected 403, got {r1.status_code}"
    assert r2.status_code == 403, f"Expected 403, got {r2.status_code}"
    mock_global.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 6 — multi-user isolation: USER_A cannot trigger backfill for USER_B
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_a_cannot_backfill_user_b():
    """Even with own scope, USER_A's backfill never touches USER_B's data."""
    fake_db = _FakeDB(_make_users())
    app = _build_app(fake_db)

    with (
        patch("api.garmin.garmin_backfill.backfill_user", new=AsyncMock(return_value={})) as mock_single,
        patch("api.garmin.backfill_run_index_history", new=AsyncMock(return_value={})),
        patch("api.garmin._dic.invalidate_user"),
    ):
        r = await _post(app, "/api/garmin/backfill",
                        headers=_bearer(USER_A_ID, USER_A_EMAIL))

    assert r.status_code == 200
    # Ensure only one call and it was for USER_A, never USER_B
    assert mock_single.await_count == 1
    call_args = mock_single.call_args
    called_user = call_args.args[1] if len(call_args.args) >= 2 else call_args.kwargs.get("user_id")
    assert called_user == USER_A_ID, f"Expected USER_A_ID, got {called_user}"
    assert called_user != USER_B_ID
