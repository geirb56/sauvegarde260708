"""PR #155 — Verify GET /training/week-plan reads from canonical sources, not db.training_goals.

Tests the real route via httpx.AsyncClient against a fake DB.
Proves:
1. Happy path: training_cycles + GOAL_CONFIG + user_goals → 200.
2. No training_cycle → 400.
3. Unknown goal type → 400.
4. No start_date → 400.
5. No access to legacy db.training_goals.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

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
from access_control import Tier, UserAccess  # noqa: E402

pytestmark = pytest.mark.asyncio

_USER_ID = "pr155-test-user"
_START_DATE = datetime(2025, 4, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------

class _TrackedCollection:
    """Minimal collection that tracks calls."""

    def __init__(self, name: str, docs: Optional[List[dict]] = None):
        self.name = name
        self._docs: List[dict] = list(docs or [])
        self.calls: List[tuple] = []

    async def find_one(self, query: dict, projection=None):
        self.calls.append(("find_one", query))
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def update_one(self, *a, **kw):
        self.calls.append(("update_one", a))

    async def delete_one(self, query: dict):
        self.calls.append(("delete_one", query))

    def find(self, query=None, projection=None):
        self.calls.append(("find", query))
        return self

    def sort(self, *a, **kw):
        return self

    def limit(self, n):
        return self

    async def to_list(self, length=None):
        return []

    async def create_index(self, *a, **kw):
        pass

    async def count_documents(self, query):
        return 0


class _FakeDB:
    def __init__(self, cycle_docs=None, user_goal_docs=None):
        self.training_cycles = _TrackedCollection(
            "training_cycles", cycle_docs
        )
        self.user_goals = _TrackedCollection("user_goals", user_goal_docs)
        self.workouts = _TrackedCollection("workouts")
        # Legacy — should NEVER be accessed
        self.training_goals = _TrackedCollection("training_goals", [])

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        col = _TrackedCollection(name)
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bearer() -> dict:
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, "test@pr155.com")}


async def _mock_get_user_access(db, user_id):
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _mock_generate_cycle_week(**kwargs):
    """Mock that returns a simple plan without calling LLM."""
    async def _inner(context, phase, target_load, goal, user_id):
        return {"sessions": []}, True, {"source": "mock"}
    return _inner


@pytest_asyncio.fixture
async def client():
    fake_db = _FakeDB(
        cycle_docs=[{
            "user_id": _USER_ID,
            "goal": "MARATHON",
            "start_date": _START_DATE,
            "updated_at": _START_DATE,
        }],
        user_goal_docs=[{
            "user_id": _USER_ID,
            "event_name": "Paris Marathon",
            "event_date": datetime(2025, 10, 15, tzinfo=timezone.utc),
        }],
    )
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
        patch("server.generate_cycle_week", _mock_generate_cycle_week()),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as ac:
            ac._fake_db = fake_db
            yield ac
    finally:
        for p in started:
            p.stop()


@pytest_asyncio.fixture
async def client_no_cycle():
    fake_db = _FakeDB(cycle_docs=[], user_goal_docs=[])
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        for p in started:
            p.stop()


@pytest_asyncio.fixture
async def client_bad_goal():
    fake_db = _FakeDB(
        cycle_docs=[{
            "user_id": _USER_ID,
            "goal": "UNKNOWN_GOAL",
            "start_date": _START_DATE,
        }],
    )
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        for p in started:
            p.stop()


@pytest_asyncio.fixture
async def client_no_start_date():
    """Cycle exists with valid goal but no start_date."""
    fake_db = _FakeDB(
        cycle_docs=[{
            "user_id": _USER_ID,
            "goal": "MARATHON",
            "updated_at": _START_DATE,
            # start_date intentionally missing
        }],
    )
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        for p in started:
            p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWeekPlanPR155:
    """GET /api/training/week-plan uses canonical sources."""

    async def test_happy_path(self, client):
        resp = await client.get("/api/training/week-plan", headers=_bearer())
        assert resp.status_code == 200
        body = resp.json()
        assert body["goal"]["type"] == "MARATHON"
        assert body["total_weeks"] == 16  # from GOAL_CONFIG
        assert body["goal"]["name"] == "Paris Marathon"

    async def test_no_cycle_returns_400(self, client_no_cycle):
        resp = await client_no_cycle.get("/api/training/week-plan", headers=_bearer())
        assert resp.status_code == 400
        assert "No goal defined" in resp.json()["detail"]

    async def test_unknown_goal_returns_400(self, client_bad_goal):
        resp = await client_bad_goal.get("/api/training/week-plan", headers=_bearer())
        assert resp.status_code == 400
        assert "Unknown" in resp.json()["detail"]

    async def test_no_legacy_training_goals_access(self, client):
        await client.get("/api/training/week-plan", headers=_bearer())
        db = client._fake_db
        assert len(db.training_goals.calls) == 0, \
            "Legacy db.training_goals should never be accessed"

    async def test_no_start_date_returns_400(self, client_no_start_date):
        resp = await client_no_start_date.get("/api/training/week-plan", headers=_bearer())
        assert resp.status_code == 400
        assert "start_date" in resp.json()["detail"].lower()
