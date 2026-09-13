from __future__ import annotations

import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "testdb")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


class _TrackedCollection:
    def __init__(self, docs=None):
        self._docs = [deepcopy(d) for d in (docs or [])]
        self.update_calls = 0
        self.delete_calls = 0

    async def find_one(self, query, projection=None):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return deepcopy(doc)
        return None

    async def update_one(self, query, update, upsert=False):
        self.update_calls += 1
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(deepcopy(update.get("$set", {})))
                return MagicMock(matched_count=1, modified_count=1)
        if upsert:
            new_doc = {**deepcopy(query), **deepcopy(update.get("$set", {}))}
            self._docs.append(new_doc)
            return MagicMock(matched_count=0, modified_count=0, upserted_id="new")
        return MagicMock(matched_count=0, modified_count=0)

    async def delete_many(self, query):
        self.delete_calls += 1
        kept = []
        deleted = 0
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                deleted += 1
            else:
                kept.append(doc)
        self._docs = kept
        return MagicMock(deleted_count=deleted)


class _FakeDB:
    def __init__(self, training_cycles=None, user_goals=None):
        self.training_cycles = _TrackedCollection(training_cycles)
        self.user_goals = _TrackedCollection(user_goals)


@pytest.mark.asyncio
async def test_set_training_goal_same_goal_is_noop_and_preserves_metadata():
    import server as srv

    start_date = datetime(2026, 8, 1, tzinfo=timezone.utc)
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "u1", "goal": "SEMI", "start_date": start_date}],
        user_goals=[{
            "user_id": "u1",
            "event_name": "Auray-Vannes",
            "event_date": "2026-10-10",
            "distance_type": "semi",
            "distance_km": 21.0975,
            "target_time_minutes": 115,
            "target_pace": "5:27",
        }],
    )
    before_cycle = deepcopy(fake_db.training_cycles._docs[0])
    before_goal = deepcopy(fake_db.user_goals._docs[0])

    with patch.object(srv, "db", fake_db):
        result = await srv.set_training_goal(goal="SEMI", user={"id": "u1"})

    assert result == {"status": "unchanged", "goal": "SEMI"}
    assert fake_db.training_cycles.update_calls == 0
    assert fake_db.user_goals.delete_calls == 0
    assert fake_db.training_cycles._docs[0] == before_cycle
    assert fake_db.user_goals._docs[0] == before_goal


@pytest.mark.asyncio
async def test_set_training_goal_true_change_resets_cycle_and_clears_user_goals():
    import server as srv

    old_start_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "u1", "goal": "SEMI", "start_date": old_start_date}],
        user_goals=[{"user_id": "u1", "distance_type": "semi"}],
    )

    with patch.object(srv, "db", fake_db):
        result = await srv.set_training_goal(goal="MARATHON", user={"id": "u1"})

    cycle = await fake_db.training_cycles.find_one({"user_id": "u1"})
    assert result == {"status": "updated", "goal": "MARATHON"}
    assert fake_db.training_cycles.update_calls == 1
    assert fake_db.user_goals.delete_calls == 1
    assert cycle["goal"] == "MARATHON"
    assert cycle["start_date"] != old_start_date
    assert fake_db.user_goals._docs == []


@pytest.mark.asyncio
async def test_set_training_goal_ultra_same_distance_is_noop():
    import server as srv

    fake_db = _FakeDB(
        training_cycles=[{
            "user_id": "u1",
            "goal": "ULTRA",
            "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "ultra_distance_km": 80.0,
        }],
        user_goals=[{"user_id": "u1", "distance_type": "ultra", "distance_km": 80.0}],
    )

    with patch.object(srv, "db", fake_db):
        result = await srv.set_training_goal(goal="ULTRA", distance_km=80.0, user={"id": "u1"})

    assert result == {"status": "unchanged", "goal": "ULTRA"}
    assert fake_db.training_cycles.update_calls == 0
    assert fake_db.user_goals.delete_calls == 0


@pytest.mark.asyncio
async def test_set_training_goal_ultra_distance_change_is_not_noop():
    import server as srv

    fake_db = _FakeDB(
        training_cycles=[{
            "user_id": "u1",
            "goal": "ULTRA",
            "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "ultra_distance_km": 80.0,
        }],
        user_goals=[{"user_id": "u1", "distance_type": "ultra", "distance_km": 80.0}],
    )

    with patch.object(srv, "db", fake_db):
        result = await srv.set_training_goal(goal="ULTRA", distance_km=100.0, user={"id": "u1"})

    cycle = await fake_db.training_cycles.find_one({"user_id": "u1"})
    assert result == {"status": "updated", "goal": "ULTRA"}
    assert fake_db.training_cycles.update_calls == 1
    assert fake_db.user_goals.delete_calls == 1
    assert cycle["ultra_distance_km"] == 100.0


@pytest.mark.asyncio
async def test_set_training_plan_goal_same_goal_is_noop_and_preserves_metadata():
    import server as srv

    start_date = datetime(2026, 8, 1, tzinfo=timezone.utc)
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "u1", "goal": "MARATHON", "start_date": start_date}],
        user_goals=[{
            "user_id": "u1",
            "event_name": "Berlin",
            "event_date": "2026-10-01",
            "distance_type": "marathon",
            "distance_km": 42.195,
            "target_time_minutes": 220,
            "target_pace": "5:13",
        }],
    )
    before_cycle = deepcopy(fake_db.training_cycles._docs[0])
    before_goal = deepcopy(fake_db.user_goals._docs[0])

    with patch.object(srv, "db", fake_db):
        result = await srv.set_training_plan_goal(goal="MARATHON", user={"id": "u1"})

    assert result["status"] == "unchanged"
    assert result["goal"] == "MARATHON"
    assert result["cycle_weeks"] == 16
    assert result["description"] == "Marathon"
    assert fake_db.training_cycles.update_calls == 0
    assert fake_db.user_goals.delete_calls == 0
    assert fake_db.training_cycles._docs[0] == before_cycle
    assert fake_db.user_goals._docs[0] == before_goal
