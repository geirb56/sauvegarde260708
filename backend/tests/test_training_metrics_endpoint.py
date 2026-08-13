"""RUNINDEX #123 — /training/metrics endpoint integration tests.

Tests hit the **real** FastAPI route from server.py using an in-memory fake
database and a thin access-control stub, so no live MongoDB connection is
required.

Requirements verified (per problem statement #123 item 5):
A. ACWR identical to TrainingLoadSnapshot V2 (build_training_load)
B. ACWR is None when no valid duration data (no fallback to 1.0)
C. Distance-only activities → no load invented, acwr is None
D. Multi-user isolation: user A's garmin activities do not affect user B
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Environment must be set before server is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("JWT_SECRET_KEY", "integration-test-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Ensure the backend `config` package is used (not root-level config.py).
if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from training_v2.training_load import build_training_load  # noqa: E402

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_A = "garmin-metrics-user-a"
_USER_B = "garmin-metrics-user-b"

# ---------------------------------------------------------------------------
# In-memory fake database
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, *_a: Any, **_kw: Any) -> "_Cursor":
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if length is not None:
            return list(self._docs[:length])
        return list(self._docs)


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        # Filter by exact-match keys only; skip dict-value operators like $gte.
        q = {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}
        results = [d for d in self._docs if all(d.get(k) == v for k, v in q.items())]
        return _Cursor(results)

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in q.items()):
                return dict(doc)
        return None

    async def count_documents(self, query: dict) -> int:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        return sum(1 for d in self._docs if all(d.get(k) == v for k, v in q.items()))

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def create_index(self, *_a: Any, **_kw: Any) -> None:
        pass


class _FakeDB:
    """Minimal fake database for /training/metrics tests."""

    def __init__(
        self,
        garmin_activities: Optional[List[dict]] = None,
        workouts: Optional[List[dict]] = None,
    ) -> None:
        self.garmin_activities = _Collection(garmin_activities or [])
        self.workouts = _Collection(workouts or [])

    def __getattr__(self, name: str) -> _Collection:
        col: _Collection = _Collection()
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer(user_id: str, email: str = "test@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _garmin_act(
    user_id: str,
    days_ago: int,
    duration_s: Optional[float],
    distance_m: Optional[float] = None,
) -> dict:
    """Build a minimal garmin_activities document relative to today."""
    today = date.today()
    act_date = today - timedelta(days=days_ago)
    doc: dict = {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": act_date.isoformat() + "T08:00:00",
    }
    if duration_s is not None:
        doc["duration"] = duration_s
    if distance_m is not None:
        doc["distance"] = distance_m
    return doc


def _get_user_access(db: Any, user_id: str) -> UserAccess:
    """Grant PREMIUM to test users."""
    if user_id in (_USER_A, _USER_B):
        return UserAccess(user_id=user_id, tier=Tier.PREMIUM)
    return UserAccess(user_id=user_id, tier=Tier.FREE)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_client(fake_db: _FakeDB):
    """Context manager: patch server.db + get_user_access; return AsyncClient."""
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_get_user_access)),
    ]
    return patches


# ---------------------------------------------------------------------------
# A. ACWR identical to build_training_load (V2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_acwr_matches_build_training_load():
    """A. /training/metrics acwr == build_training_load(garmin_activities, today).acwr."""
    today = date.today()
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    fake_db = _FakeDB(garmin_activities=acts)
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/metrics", headers=_bearer(_USER_A))
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    payload = r.json()
    expected_snap = build_training_load(acts, today)
    assert payload["acwr"] == expected_snap.acwr


@pytest.mark.asyncio
async def test_a_acwr_matches_build_training_load_varied_load():
    """A. Varied daily load: endpoint acwr == snapshot acwr."""
    today = date.today()
    acts = [
        _garmin_act(_USER_A, days_ago=d, duration_s=1200.0 if d % 2 == 0 else 2400.0)
        for d in range(28)
    ]
    fake_db = _FakeDB(garmin_activities=acts)
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/metrics", headers=_bearer(_USER_A))
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    payload = r.json()
    expected_snap = build_training_load(acts, today)
    assert payload["acwr"] == expected_snap.acwr


# ---------------------------------------------------------------------------
# B. ACWR is None when no valid duration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_no_activities_acwr_none():
    """B. No Garmin activities → acwr is None, not 1.0."""
    fake_db = _FakeDB(garmin_activities=[])
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/metrics", headers=_bearer(_USER_A))
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["acwr"] is None
    assert payload["acwr_status"] == "unavailable"


@pytest.mark.asyncio
async def test_b_activities_missing_duration_acwr_none():
    """B. Activities present but all lack duration → acwr is None."""
    acts = [
        {
            "user_id": _USER_A,
            "activity_type": "running",
            "start_time": (date.today() - timedelta(days=d)).isoformat() + "T08:00:00",
        }
        for d in range(28)
    ]
    fake_db = _FakeDB(garmin_activities=acts)
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/metrics", headers=_bearer(_USER_A))
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    assert r.json()["acwr"] is None


# ---------------------------------------------------------------------------
# C. Distance-only → no load invented
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_distance_only_no_load():
    """C. Distance present but duration absent → acwr is None (no duration invented)."""
    acts = [
        _garmin_act(_USER_A, days_ago=d, duration_s=None, distance_m=10_000.0)
        for d in range(28)
    ]
    fake_db = _FakeDB(garmin_activities=acts)
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/metrics", headers=_bearer(_USER_A))
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["acwr"] is None, "distance-only must not invent duration-based load"


# ---------------------------------------------------------------------------
# D. Multi-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_user_b_sees_only_own_activities():
    """D. User B has no activities → acwr is None even when User A has many."""
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    # DB contains only user A activities; user B will query their own user_id
    fake_db = _FakeDB(garmin_activities=acts_a)
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get(
                "/api/training/metrics",
                headers=_bearer(_USER_B, "b@example.com"),
            )
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["acwr"] is None, "User B must not see User A activities"


@pytest.mark.asyncio
async def test_d_user_a_acwr_not_influenced_by_user_b():
    """D. User A acwr computed only from user A activities, not user B's."""
    today = date.today()
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    acts_b = [_garmin_act(_USER_B, days_ago=d, duration_s=7200.0) for d in range(28)]
    fake_db = _FakeDB(garmin_activities=acts_a + acts_b)
    patches = _make_client(fake_db)
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/metrics", headers=_bearer(_USER_A))
    finally:
        for p in reversed(started):
            p.stop()

    assert r.status_code == 200, r.text
    payload = r.json()
    expected_snap = build_training_load(acts_a, today)
    assert payload["acwr"] == expected_snap.acwr
