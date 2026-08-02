"""Expired-trial enforcement — targeted final check.

Verifies that when a subscription has status="trial" but trial_end is in the
PAST, the backend (the single source of truth, access_control.get_user_access +
the subscription middleware):

  1. treats the trial as expired (resolves to FREE);
  2. refuses Premium access on premium-gated routes (403);
  3. cannot be bypassed by anything the frontend sends (body/headers ignored —
     tier is computed server-side from the stored trial_end only).

In-process ASGI, in-memory fake DB. get_user_access is NOT patched here so the
real access-control code path runs against the stored data.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

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
from auth.jwt_utils import create_access_token  # noqa: E402
from access_control import Tier, get_user_access  # noqa: E402
from unittest.mock import patch  # noqa: E402

pytestmark = pytest.mark.asyncio

_USER_ID = "u-expired-trial"
_EMAIL = "expired@test.com"


def _bearer() -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, _EMAIL)}


class _Collection:
    def __init__(self, docs=None) -> None:
        self._docs = list(docs or [])

    async def find_one(self, query: dict, projection: dict | None = None):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def update_one(self, query, update, upsert: bool = False) -> None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            new = dict(query)
            new.update(update.get("$set", {}))
            self._docs.append(new)

    def find(self, query=None, projection=None):
        class _C:
            def __init__(s, d): s._d = d
            def sort(s, *a, **k): return s
            def limit(s, *a, **k): return s
            async def to_list(s, length=None): return list(s._d)
        q = query or {}
        return _C([d for d in self._docs if all(d.get(k) == v for k, v in q.items())])

    async def create_index(self, *a, **kw) -> None:
        pass


class _FakeDB:
    def __init__(self, subscription: dict) -> None:
        self.subscriptions = _Collection([subscription])

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


def _expired_trial_sub() -> dict:
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return {
        "user_id": _USER_ID,
        "status": "trial",          # stored status says trial…
        "trial_start": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
        "trial_end": past,          # …but it ended in the past
        "trial_used": True,
        "premium_expires_at": None,
    }


@pytest_asyncio.fixture
async def client():
    fake_db = _FakeDB(_expired_trial_sub())
    with patch.object(server, "db", fake_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as c:
            yield c, fake_db


async def test_expired_trial_resolves_to_free_via_source_of_truth(client):
    """1. Source of truth treats an expired trial as FREE (no premium)."""
    _, fake_db = client
    access = await get_user_access(fake_db, _USER_ID)
    assert access.tier == Tier.FREE
    assert access.has_premium_access is False
    assert access.is_free is True


async def test_expired_trial_denied_on_premium_route(client):
    """2. A premium-gated route is refused (403) for an expired-trial user."""
    c, _ = client
    r = await c.get("/api/garmin/activities", headers=_bearer())
    assert r.status_code == 403


async def test_frontend_cannot_bypass_expiration(client):
    """3. Client-supplied status cannot override the server-computed tier."""
    c, _ = client
    headers = _bearer()
    # Attempt to forge premium via header + body — must be ignored server-side.
    headers["X-Subscription-Status"] = "premium"
    r = await c.get(
        "/api/garmin/activities?status=premium",
        headers=headers,
    )
    assert r.status_code == 403
