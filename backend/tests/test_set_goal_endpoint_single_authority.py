from __future__ import annotations

import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-goal-single-authority-secret-32chars!!")
os.environ.setdefault("JWT_SECRET", "test-goal-single-authority-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Ensure backend config package is used.
if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402


pytestmark = pytest.mark.asyncio


class _Collection:
    def __init__(self, docs=None):
        self._docs = [deepcopy(d) for d in (docs or [])]

    def _match(self, doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if isinstance(v, dict):
                continue
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, query: dict, projection: Optional[dict] = None):
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if self._match(doc, q):
                return deepcopy(doc)
        return None

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        set_fields = deepcopy(update.get("$set", {}))
        for doc in self._docs:
            if self._match(doc, q):
                doc.update(set_fields)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            self._docs.append({**q, **set_fields})
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def delete_many(self, query: dict):
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        kept = []
        deleted = 0
        for doc in self._docs:
            if self._match(doc, q):
                deleted += 1
            else:
                kept.append(doc)
        self._docs = kept
        return SimpleNamespace(deleted_count=deleted)


class _FakeDB:
    def __init__(self, training_cycles=None, user_goals=None):
        self.training_cycles = _Collection(training_cycles)
        self.user_goals = _Collection(user_goals)


def _auth_headers(user_id: str = "goal-test-user") -> dict[str, str]:
    token = create_access_token(user_id, f"{user_id}@example.com")
    return {"Authorization": "Bearer " + token}


def _premium_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


async def _post(path: str, fake_db: _FakeDB, user_id: str = "goal-test-user") -> httpx.Response:
    with patch.object(server, "db", fake_db), patch(
        "server.get_user_access", AsyncMock(side_effect=_premium_access)
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            return await client.post(path, headers=_auth_headers(user_id=user_id), json={})


def test_goal_route_table_contains_only_canonical_goal_mutation():
    openapi_paths = set(server.app.openapi().get("paths", {}).keys())
    assert "/api/training-plan/set-goal" not in openapi_paths
    assert "/api/training/set-goal" in openapi_paths


async def test_removed_training_plan_set_goal_route_returns_404_for_authenticated_premium():
    r = await _post("/api/training-plan/set-goal?goal=10K", _FakeDB())
    assert r.status_code == 404, r.text


async def test_canonical_set_goal_new_goal_writes_goal_start_date_and_updated_at():
    fake_db = _FakeDB()
    r = await _post("/api/training/set-goal?goal=10K", fake_db)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "updated", "goal": "10K"}

    cycle = await fake_db.training_cycles.find_one({"user_id": "goal-test-user"})
    assert cycle is not None
    assert cycle["goal"] == "10K"
    assert isinstance(cycle.get("start_date"), datetime)
    assert isinstance(cycle.get("updated_at"), datetime)


async def test_canonical_set_goal_same_goal_is_noop_and_preserves_start_date_and_metadata():
    existing_start_date = datetime(2026, 8, 1, tzinfo=timezone.utc)
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "goal-test-user", "goal": "10K", "start_date": existing_start_date}],
        user_goals=[{"user_id": "goal-test-user", "event_name": "Legacy race", "event_date": "2026-09-20"}],
    )
    before_user_goals = deepcopy(fake_db.user_goals._docs)

    r = await _post("/api/training/set-goal?goal=10K", fake_db)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "unchanged", "goal": "10K"}

    cycle = await fake_db.training_cycles.find_one({"user_id": "goal-test-user"})
    assert cycle is not None
    assert cycle["start_date"] == existing_start_date
    assert fake_db.user_goals._docs == before_user_goals


async def test_canonical_set_goal_true_change_refreshes_start_date_and_clears_stale_user_goals():
    old_start_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "goal-test-user", "goal": "10K", "start_date": old_start_date}],
        user_goals=[{"user_id": "goal-test-user", "event_name": "Old race"}],
    )

    r = await _post("/api/training/set-goal?goal=SEMI", fake_db)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "updated", "goal": "SEMI"}

    cycle = await fake_db.training_cycles.find_one({"user_id": "goal-test-user"})
    assert cycle is not None
    assert cycle["goal"] == "SEMI"
    assert cycle["start_date"] != old_start_date
    assert isinstance(cycle.get("updated_at"), datetime)
    assert fake_db.user_goals._docs == []


async def test_canonical_set_goal_ultra_valid_distance_persists_ultra_distance_km():
    fake_db = _FakeDB()

    r = await _post("/api/training/set-goal?goal=ULTRA&distance_km=80", fake_db)
    assert r.status_code == 200, r.text

    cycle = await fake_db.training_cycles.find_one({"user_id": "goal-test-user"})
    assert cycle is not None
    assert cycle["goal"] == "ULTRA"
    assert cycle["ultra_distance_km"] == 80.0


async def test_canonical_set_goal_switching_away_from_ultra_clears_ultra_distance_km():
    fake_db = _FakeDB(
        training_cycles=[{
            "user_id": "goal-test-user",
            "goal": "ULTRA",
            "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "ultra_distance_km": 100.0,
        }]
    )

    r = await _post("/api/training/set-goal?goal=MARATHON", fake_db)
    assert r.status_code == 200, r.text

    cycle = await fake_db.training_cycles.find_one({"user_id": "goal-test-user"})
    assert cycle is not None
    assert cycle["goal"] == "MARATHON"
    assert cycle["ultra_distance_km"] is None


async def test_canonical_set_goal_invalid_ultra_distance_is_rejected():
    fake_db = _FakeDB()

    r = await _post("/api/training/set-goal?goal=ULTRA&distance_km=42.195", fake_db)
    assert r.status_code == 400, r.text
    assert "distance_km" in str(r.json())


async def test_canonical_set_goal_invalid_goal_is_rejected():
    fake_db = _FakeDB()

    r = await _post("/api/training/set-goal?goal=INVALID", fake_db)
    assert r.status_code == 400, r.text
    assert r.json().get("detail") == "Invalid goal"


async def test_canonical_set_goal_mutation_isolated_to_authenticated_user():
    fake_db = _FakeDB(
        training_cycles=[
            {"user_id": "goal-test-user", "goal": "10K", "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc)},
            {"user_id": "other-user", "goal": "MARATHON", "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        ],
        user_goals=[
            {"user_id": "goal-test-user", "event_name": "Old race"},
            {"user_id": "other-user", "event_name": "Should stay"},
        ],
    )

    r = await _post("/api/training/set-goal?goal=SEMI", fake_db, user_id="goal-test-user")
    assert r.status_code == 200, r.text

    auth_user_cycle = await fake_db.training_cycles.find_one({"user_id": "goal-test-user"})
    other_user_cycle = await fake_db.training_cycles.find_one({"user_id": "other-user"})
    assert auth_user_cycle is not None and auth_user_cycle["goal"] == "SEMI"
    assert other_user_cycle is not None and other_user_cycle["goal"] == "MARATHON"

    assert await fake_db.user_goals.find_one({"user_id": "goal-test-user"}) is None
    other_goal = await fake_db.user_goals.find_one({"user_id": "other-user"})
    assert other_goal is not None
    assert other_goal["event_name"] == "Should stay"
