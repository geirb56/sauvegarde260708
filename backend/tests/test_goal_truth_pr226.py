"""PR226 — Goal-truth unification tests.

Covers:
- Goal creation/change for 5K / 10K / SEMI / MARATHON
- MAINTENANCE clears race_date and target_time from user_goals
- Fallback without goal → MAINTENANCE (dynamic fallback constant)
- ULTRA without valid distance → rejection (set-goal + user/goal)
- ULTRA with valid distance → propagation through training_cycles.ultra_distance_km
- No stale race_date after any goal change
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr226-goal-truth-secret-key-32!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import httpx  # noqa: E402
import pytest  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Minimal in-memory fake DB
# ---------------------------------------------------------------------------


class _DeleteResult:
    def __init__(self, deleted: int = 0) -> None:
        self.deleted_count = deleted


class _UpdateResult:
    pass


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def _match(self, doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if isinstance(v, dict):
                continue
            if doc.get(k) != v:
                return False
        return True

    def _simple_query(self, query: dict) -> dict:
        return {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        q = self._simple_query(query)
        for doc in self._docs:
            if self._match(doc, q):
                return dict(doc)
        return None

    class _Cursor:
        def __init__(self, docs: List[dict]) -> None:
            self._docs = docs

        def sort(self, *_a: Any, **_kw: Any) -> "_Collection._Cursor":
            return self

        def limit(self, n: int) -> "_Collection._Cursor":
            self._docs = self._docs[:n]
            return self

        async def to_list(self, length: Optional[int] = None) -> List[dict]:
            return list(self._docs[:length] if length is not None else self._docs)

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> "_Collection._Cursor":
        q = self._simple_query(query or {})
        results = [d for d in self._docs if self._match(d, q)]
        return self._Cursor(results)

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> _UpdateResult:
        q = self._simple_query(query)
        for doc in self._docs:
            if self._match(doc, q):
                doc.update(update.get("$set", {}))
                return _UpdateResult()
        if upsert:
            new_doc = {**q, **update.get("$set", {})}
            self._docs.append(new_doc)
        return _UpdateResult()

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def delete_one(self, query: dict) -> _DeleteResult:
        q = self._simple_query(query)
        for i, doc in enumerate(self._docs):
            if self._match(doc, q):
                self._docs.pop(i)
                return _DeleteResult(1)
        return _DeleteResult(0)

    async def delete_many(self, query: dict) -> _DeleteResult:
        q = self._simple_query(query)
        before = len(self._docs)
        self._docs = [d for d in self._docs if not self._match(d, q)]
        return _DeleteResult(before - len(self._docs))

    async def count_documents(self, query: dict) -> int:
        q = self._simple_query(query)
        return sum(1 for d in self._docs if self._match(d, q))

    async def create_index(self, *_a: Any, **_kw: Any) -> None:
        pass


class _FakeDB:
    def __init__(self) -> None:
        self.training_cycles: _Collection = _Collection()
        self.training_prefs: _Collection = _Collection()
        self.user_goals: _Collection = _Collection()
        self.training_context: _Collection = _Collection()
        self.training_plans: _Collection = _Collection()
        self.garmin_activities: _Collection = _Collection()
        self.users: _Collection = _Collection()
        self.subscriptions: _Collection = _Collection()


# ---------------------------------------------------------------------------
# App / client fixture
# ---------------------------------------------------------------------------


def _make_token(user_id: str = "user-pr226") -> str:
    return create_access_token({"sub": user_id})


def _auth_headers(user_id: str = "user-pr226") -> dict:
    return {"Authorization": f"******"}


_FAKE_USER = {
    "id": "user-pr226",
    "email": "pr226@test.com",
    "is_email_verified": True,
    "role": "user",
    "is_admin": False,
    "subscription_tier": "free",
}


@pytest.fixture()
async def client_and_db():
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.db", fake_db),
    ):
        import importlib

        importlib.reload(srv)
        patch.object(srv, "db", fake_db).start()
        patch("auth.dependencies.db", fake_db).start()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            yield ac, fake_db


# ---------------------------------------------------------------------------
# Helper: set-goal endpoint
# ---------------------------------------------------------------------------


async def _set_goal(client, goal: str, distance_km: Optional[float] = None, user_id: str = "user-pr226"):
    url = f"/api/training/set-goal?goal={goal}"
    if distance_km is not None:
        url += f"&distance_km={distance_km}"
    return await client.post(url, headers=_auth_headers(user_id))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("goal", ["5K", "10K", "SEMI", "MARATHON"])
async def test_standard_goals_set_correctly(goal):
    """Goal change for 5K/10K/SEMI/MARATHON persists correct goal in training_cycles."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                f"/api/training/set-goal?goal={goal}",
                headers=_auth_headers(),
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["goal"] == goal
    cycle = await fake_db.training_cycles.find_one({"user_id": "user-pr226"})
    assert cycle is not None
    assert cycle["goal"] == goal


async def test_maintenance_clears_race_date_and_target_time():
    """Switching to MAINTENANCE must delete any existing user_goals record."""
    import server as srv

    fake_db = _FakeDB()
    # Pre-populate a stale user_goals record (from a previous MARATHON goal)
    await fake_db.user_goals.insert_one({
        "user_id": "user-pr226",
        "event_name": "Berlin Marathon",
        "event_date": "2025-09-28",
        "distance_type": "marathon",
        "distance_km": 42.195,
        "target_time_minutes": 210,
    })

    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/training/set-goal?goal=MAINTENANCE",
                headers=_auth_headers(),
            )
    assert resp.status_code == 200
    # user_goals must be gone
    remaining = await fake_db.user_goals.find_one({"user_id": "user-pr226"})
    assert remaining is None, "MAINTENANCE must clear user_goals (no race_date, no target_time)"


async def test_no_stale_race_date_after_goal_change():
    """Changing from MARATHON to 5K must delete the previous user_goals."""
    import server as srv

    fake_db = _FakeDB()
    await fake_db.user_goals.insert_one({
        "user_id": "user-pr226",
        "event_name": "Old Marathon",
        "event_date": "2025-04-01",
        "distance_type": "marathon",
        "distance_km": 42.195,
        "target_time_minutes": 200,
    })

    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post("/api/training/set-goal?goal=5K", headers=_auth_headers())

    assert resp.status_code == 200
    stale = await fake_db.user_goals.find_one({"user_id": "user-pr226"})
    assert stale is None, "Goal change must clear user_goals to prevent stale race_date"


async def test_fallback_without_goal_is_maintenance():
    """Hardcoded SEMI fallback must be replaced by MAINTENANCE.

    Verifies the literal string 'SEMI' no longer appears as the default
    fallback in the training-plans LLM context builder (server.py line ~1383).
    """
    import server as srv
    import inspect

    source = inspect.getsource(srv)
    # Ensure the specific fallback pattern is now MAINTENANCE, not SEMI.
    assert 'plan_data.get("goal", "SEMI")' not in source, (
        'Stale SEMI fallback found — must be "MAINTENANCE"'
    )
    assert 'plan_data.get("goal", "MAINTENANCE")' in source


async def test_ultra_without_distance_rejected_set_goal():
    """POST /training/set-goal?goal=ULTRA without distance_km must return 400."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/training/set-goal?goal=ULTRA",
                headers=_auth_headers(),
            )
    assert resp.status_code == 400


async def test_ultra_with_invalid_distance_rejected():
    """ULTRA distance <= 42.195 km must be rejected."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp_eq = await ac.post(
                "/api/training/set-goal?goal=ULTRA&distance_km=42.195",
                headers=_auth_headers(),
            )
            resp_lt = await ac.post(
                "/api/training/set-goal?goal=ULTRA&distance_km=40.0",
                headers=_auth_headers(),
            )
    assert resp_eq.status_code == 400
    assert resp_lt.status_code == 400


async def test_ultra_with_valid_distance_propagated():
    """ULTRA with distance_km > 42.195 must be stored in training_cycles.ultra_distance_km."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/training/set-goal?goal=ULTRA&distance_km=50.0",
                headers=_auth_headers(),
            )
    assert resp.status_code == 200
    cycle = await fake_db.training_cycles.find_one({"user_id": "user-pr226"})
    assert cycle is not None
    assert cycle["goal"] == "ULTRA"
    assert cycle.get("ultra_distance_km") == 50.0


async def test_ultra_user_goal_without_distance_rejected():
    """POST /user/goal with distance_type=ultra but no valid distance_km must return 400."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/user/goal",
                json={
                    "event_name": "My Ultra",
                    "event_date": "2025-09-01",
                    "distance_type": "ultra",
                    # no distance_km — should be rejected
                },
                headers=_auth_headers(),
            )
    assert resp.status_code == 400


async def test_ultra_user_goal_with_valid_distance_accepted():
    """POST /user/goal with distance_type=ultra and distance_km > 42.195 must succeed."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/user/goal",
                json={
                    "event_name": "CCC",
                    "event_date": "2025-08-29",
                    "distance_type": "ultra",
                    "distance_km": 100.0,
                },
                headers=_auth_headers(),
            )
    assert resp.status_code == 200
    stored = await fake_db.user_goals.find_one({"user_id": "user-pr226"})
    assert stored is not None
    assert stored["distance_km"] == 100.0
    assert stored["distance_type"] == "ultra"


async def test_ultra_distance_preserved_not_overwritten_by_default():
    """When ULTRA distance 100 km is set, it must not be silently downgraded to DISTANCE_TYPES["ultra"]=50."""
    import server as srv

    fake_db = _FakeDB()
    with (
        patch.object(srv, "db", fake_db),
        patch("auth.dependencies.get_current_user", new_callable=AsyncMock, return_value=_FAKE_USER),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=srv.app), base_url="http://test"
        ) as ac:
            await ac.post(
                "/api/user/goal",
                json={
                    "event_name": "UTMB",
                    "event_date": "2025-08-29",
                    "distance_type": "ultra",
                    "distance_km": 170.0,
                },
                headers=_auth_headers(),
            )
    stored = await fake_db.user_goals.find_one({"user_id": "user-pr226"})
    assert stored["distance_km"] == 170.0, (
        "Custom ultra distance 170 km must be stored verbatim, not replaced by default 50 km"
    )


async def test_maintenance_has_no_race_date_in_plan_goal():
    """PlanGoal for MAINTENANCE must have race_date=None and target_distance_km=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal

    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.race_date is None
    assert pg.target_distance_km is None
    assert pg.target_time_seconds is None
