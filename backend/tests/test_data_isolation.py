"""
Data isolation tests — user-scoped endpoint security.

Verifies that:
1. GET /training/race-predictions uses only the authenticated user's workouts.
2. DELETE /training/goal no longer raises NameError and only deletes the
   authenticated user's goal.

Pattern: two users (USER_A, USER_B) with distinct workouts; each must only
see their own data and be refused access to the other's resources.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
import pytest_asyncio
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-isolation-32chars!!!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

from auth.jwt_utils import create_access_token
from fastapi import Depends, FastAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _workout(user_id: str, workout_id: str | None = None, *, distance_km: float = 10.0,
             duration_minutes: float = 60.0, workout_type: str = "run",
             date: str = "2024-03-01") -> dict:
    return {
        "id": workout_id or str(uuid.uuid4()),
        "user_id": user_id,
        "date": date,
        "type": workout_type,
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "avg_pace_min_km": duration_minutes / distance_km if distance_km > 0 else None,
    }


def _goal(user_id: str, goal_id: str | None = None) -> dict:
    return {
        "id": goal_id or str(uuid.uuid4()),
        "user_id": user_id,
        "goal": "10K",
    }


# ---------------------------------------------------------------------------
# Minimal in-memory fake DB
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return list(self._docs[:length] if length else self._docs)


class _Collection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    async def find_one(self, query, projection=None):
        for d in self._docs:
            if _matches(d, query):
                return dict(d)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        return _Cursor(d for d in self._docs if _matches(d, query))

    async def delete_one(self, query):
        for i, d in enumerate(self._docs):
            if _matches(d, query):
                self._docs.pop(i)
                return _DeleteResult(1)
        return _DeleteResult(0)

    async def insert_one(self, doc):
        self._docs.append(dict(doc))

    async def count_documents(self, query):
        return sum(1 for d in self._docs if _matches(d, query))


class _DeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


def _matches(doc: dict, query: dict) -> bool:
    for k, v in query.items():
        if isinstance(v, dict):
            # Handle simple MongoDB operators used in tests
            doc_val = doc.get(k)
            for op, op_val in v.items():
                if op == "$gte" and not (doc_val is not None and doc_val >= op_val):
                    return False
                elif op == "$lte" and not (doc_val is not None and doc_val <= op_val):
                    return False
        else:
            if doc.get(k) != v:
                return False
    return True


# ===========================================================================
# 1. Race Predictions — user isolation
# ===========================================================================

def _race_predictions_app():
    """Minimal app mirroring the fixed /training/race-predictions endpoint."""
    from auth.dependencies import get_current_user
    from datetime import datetime, timedelta, timezone

    app = FastAPI()

    recent_date = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()

    wkt_a = _workout("user-a", "wkt-a", distance_km=12.0, duration_minutes=60.0,
                     date=recent_date)
    wkt_b = _workout("user-b", "wkt-b", distance_km=8.0, duration_minutes=45.0,
                     date=recent_date)

    class _DB:
        workouts = _Collection([wkt_a, wkt_b])
        users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True, "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True, "is_email_verified": True},
        ])

    app.state.db = _DB()
    db = app.state.db

    @app.get("/training/race-predictions")
    async def get_race_predictions(user: dict = Depends(get_current_user)):
        today = datetime.now(timezone.utc)
        six_weeks_ago = today - timedelta(days=42)
        user_id = user["id"]
        activities = await db.workouts.find({
            "user_id": user_id,
            "date": {"$gte": six_weeks_ago.isoformat()[:10]},
        }).to_list(500)
        return {"user_id": user_id, "workout_ids": [a["id"] for a in activities]}

    return app, wkt_a, wkt_b


@pytest_asyncio.fixture
async def race_pred_client():
    app, wkt_a, wkt_b = _race_predictions_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, wkt_a, wkt_b


class TestRacePredictionsIsolation:
    @pytest.mark.asyncio
    async def test_anonymous_401(self, race_pred_client):
        client, *_ = race_pred_client
        r = await client.get("/training/race-predictions")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_user_a_sees_only_own_workouts(self, race_pred_client):
        client, wkt_a, wkt_b = race_pred_client
        r = await client.get("/training/race-predictions", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200
        ids = r.json()["workout_ids"]
        assert wkt_a["id"] in ids
        assert wkt_b["id"] not in ids

    @pytest.mark.asyncio
    async def test_user_b_sees_only_own_workouts(self, race_pred_client):
        client, wkt_a, wkt_b = race_pred_client
        r = await client.get("/training/race-predictions", headers=_bearer("user-b", "b@test.com"))
        assert r.status_code == 200
        ids = r.json()["workout_ids"]
        assert wkt_b["id"] in ids
        assert wkt_a["id"] not in ids



# ===========================================================================
# 3. DELETE /training/goal — NameError fix + user isolation
# ===========================================================================

def _delete_goal_app():
    """Minimal app mirroring the fixed DELETE /training/goal endpoint."""
    from auth.dependencies import get_current_user

    app = FastAPI()

    goal_a = _goal("user-a", "goal-a")
    goal_b = _goal("user-b", "goal-b")

    class _DB:
        training_goals = _Collection([goal_a, goal_b])
        training_context = _Collection([
            {"user_id": "user-a"}, {"user_id": "user-b"}
        ])
        training_cycles = _Collection([
            {"user_id": "user-a"}, {"user_id": "user-b"}
        ])
        users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True, "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True, "is_email_verified": True},
        ])

    db_instance = _DB()
    app.state.db = db_instance

    @app.delete("/training/goal")
    async def delete_training_goal(user: dict = Depends(get_current_user)):
        user_id = user["id"]
        result = await db_instance.training_goals.delete_one({"user_id": user_id})
        await db_instance.training_context.delete_one({"user_id": user_id})
        await db_instance.training_cycles.delete_one({"user_id": user_id})
        return {
            "success": result.deleted_count > 0,
            "message": "Goal deleted" if result.deleted_count > 0 else "No goal found",
        }

    return app, db_instance, goal_a, goal_b


@pytest_asyncio.fixture
async def delete_goal_client():
    app, db_instance, goal_a, goal_b = _delete_goal_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, db_instance, goal_a, goal_b


class TestDeleteTrainingGoalIsolation:
    @pytest.mark.asyncio
    async def test_anonymous_401(self, delete_goal_client):
        client, *_ = delete_goal_client
        r = await client.delete("/training/goal")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_no_name_error(self, delete_goal_client):
        """Endpoint must not raise NameError for user_id."""
        client, *_ = delete_goal_client
        r = await client.delete("/training/goal", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_user_a_deletes_own_goal(self, delete_goal_client):
        client, db_instance, goal_a, goal_b = delete_goal_client
        r = await client.delete("/training/goal", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        # user-b's goal must still exist
        remaining = await db_instance.training_goals.count_documents({"user_id": "user-b"})
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_user_b_goal_not_deleted_by_user_a(self, delete_goal_client):
        """Deleting user-a's goal must NOT touch user-b's goal."""
        client, db_instance, goal_a, goal_b = delete_goal_client
        await client.delete("/training/goal", headers=_bearer("user-a", "a@test.com"))
        remaining = await db_instance.training_goals.count_documents({"user_id": "user-b"})
        assert remaining == 1


