"""PR216 — Training V2 must follow garmin_activities as the canonical source."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr216-training-source-secret-32!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import coach_service  # noqa: E402
import server  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from garmin.domain_adapter import mongo_garmin_activities_to_domain  # noqa: E402
from training_v2.week_plan_bridge import build_weekly_plan_from_workouts  # noqa: E402

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_Cursor":
        self._docs.sort(key=lambda doc: doc.get(field) or "", reverse=direction < 0)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs = list(docs or [])

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        def _matches(doc: dict) -> bool:
            for key, value in (query or {}).items():
                current = doc.get(key)
                if isinstance(value, dict):
                    if "$gte" in value and (current is None or current < value["$gte"]):
                        return False
                    if "$ne" in value and current == value["$ne"]:
                        return False
                    continue
                if current != value:
                    return False
            return True

        return _Cursor([dict(doc) for doc in self._docs if _matches(doc)])

    async def find_one(self, query: dict, projection: Optional[dict] = None, sort=None) -> Optional[dict]:
        rows = await self.find(query, projection).to_list(None)
        if sort:
            field, direction = sort[0]
            rows.sort(key=lambda doc: doc.get(field) or "", reverse=direction < 0)
        return rows[0] if rows else None

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        for doc in self._docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            payload = dict(query)
            payload.update(update.get("$set", {}))
            payload.update(update.get("$setOnInsert", {}))
            self._docs.append(payload)

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))


class _FakeDB:
    def __init__(
        self,
        *,
        garmin_activities: Optional[List[dict]] = None,
        workouts: Optional[List[dict]] = None,
        training_cycles: Optional[List[dict]] = None,
        user_goals: Optional[List[dict]] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.garmin_activities = _Collection(garmin_activities)
        self.workouts = _Collection(workouts)
        self.training_cycles = _Collection(
            training_cycles
            or [{"user_id": "u1", "goal": "MARATHON", "start_date": now - timedelta(days=21)}]
        )
        self.user_goals = _Collection(user_goals or [])
        self.training_prefs = _Collection([{"user_id": "u1", "sessions_per_week": 4}])
        self.user_profiles = _Collection([])
        self.garmin_vo2max = _Collection([])

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _bearer(user_id: str = "u1", email: str = "u1@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


async def _mock_get_user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _garmin_run(days_ago: int, km: float, *, user_id: str = "u1") -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": dt.isoformat(),
        "distance_m": km * 1000.0,
        "duration_s": km * 6 * 60,
        "average_hr": 150.0,
        "source": "garmin",
        "source_activity_id": f"garmin-{days_ago}-{km}",
    }


def _workout_run(days_ago: int, km: float, *, user_id: str = "u1") -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": "running",
        "date": dt.isoformat(),
        "distance_km": km,
        "moving_time": int(km * 6 * 60),
        "id": f"workout-{days_ago}-{km}",
    }


def _canonical_dataset_a() -> List[dict]:
    return [_garmin_run(d, 10.0) for d in (1, 3, 6, 8, 10, 13, 15, 17)]


def _divergent_dataset_b() -> List[dict]:
    return [_workout_run(d, 9.0) for d in (30, 33, 36)]


def _expected_from_garmin_dataset(garmin_dataset: List[dict]) -> tuple[Any, Any]:
    return build_weekly_plan_from_workouts(
        workouts=mongo_garmin_activities_to_domain(garmin_dataset),
        goal_type="MARATHON",
        race_date=None,
        cycle_start_date=(datetime.now(timezone.utc).date() - timedelta(days=21)),
        reference_date=datetime.now(timezone.utc).date(),
    )


async def _call(path: str, fake_db: _FakeDB) -> dict:
    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.get(path, headers=_bearer())
    assert response.status_code == 200, response.text
    return response.json()


async def test_training_week_plan_uses_canonical_garmin_source_when_workouts_diverge():
    garmin_a = _canonical_dataset_a()
    workouts_b = _divergent_dataset_b()
    fake_db = _FakeDB(garmin_activities=garmin_a, workouts=workouts_b)

    response = await _call("/api/training/week-plan", fake_db)
    expected_a, plan_a = _expected_from_garmin_dataset(garmin_a)
    expected_b, _ = build_weekly_plan_from_workouts(
        workouts=workouts_b,
        goal_type="MARATHON",
        race_date=None,
        cycle_start_date=(datetime.now(timezone.utc).date() - timedelta(days=21)),
        reference_date=datetime.now(timezone.utc).date(),
    )

    assert response["context"]["training_state"] == expected_a.continuity_state
    assert response["debug_volume"]["target_basis"] == expected_a.target_basis
    assert response["debug_volume"]["target_basis"] != expected_b.target_basis
    assert response["debug_volume"]["target_km"] == expected_a.target_km
    assert response["plan"]["weekly_km"] == plan_a.planned_km


async def test_training_v2_week_uses_canonical_garmin_source_when_workouts_diverge():
    garmin_a = _canonical_dataset_a()
    workouts_b = _divergent_dataset_b()
    fake_db = _FakeDB(garmin_activities=garmin_a, workouts=workouts_b)

    response = await _call("/api/training/v2/week", fake_db)
    expected_a, plan_a = _expected_from_garmin_dataset(garmin_a)
    expected_b, _ = build_weekly_plan_from_workouts(
        workouts=workouts_b,
        goal_type="MARATHON",
        race_date=None,
        cycle_start_date=(datetime.now(timezone.utc).date() - timedelta(days=21)),
        reference_date=datetime.now(timezone.utc).date(),
    )

    assert response["state"]["continuity_state"] == expected_a.continuity_state
    assert response["weekly_target"]["target_basis"] == expected_a.target_basis
    assert response["weekly_target"]["target_basis"] != expected_b.target_basis
    assert response["weekly_target"]["target_km"] == expected_a.target_km
    assert response["week"]["planned_km"] == plan_a.planned_km


async def test_dynamic_training_plan_uses_canonical_garmin_source_when_workouts_diverge():
    coach_service.clear_cache()
    garmin_a = _canonical_dataset_a()
    workouts_b = _divergent_dataset_b()
    fake_db = _FakeDB(garmin_activities=garmin_a, workouts=workouts_b)

    result = await coach_service.generate_dynamic_training_plan(fake_db, "u1")
    expected_a, _ = _expected_from_garmin_dataset(garmin_a)
    expected_b, _ = build_weekly_plan_from_workouts(
        workouts=workouts_b,
        goal_type="MARATHON",
        race_date=None,
        cycle_start_date=(datetime.now(timezone.utc).date() - timedelta(days=21)),
        reference_date=datetime.now(timezone.utc).date(),
    )

    assert result["context"]["training_state"] == expected_a.continuity_state
    assert result["context"]["training_state"] != expected_b.continuity_state
    assert result["debug_volume"]["target_basis"] == expected_a.target_basis
    assert result["debug_volume"]["target_basis"] != expected_b.target_basis
