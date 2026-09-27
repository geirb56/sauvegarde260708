from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-training-v2-preferences-secret-32!!")
os.environ.setdefault("JWT_SECRET", "test-training-v2-preferences-secret-32!!")
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

import coach_service  # noqa: E402
import server  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from garmin.domain_adapter import mongo_garmin_activities_to_domain  # noqa: E402
from training_v2.week_plan_bridge import build_canonical_weekly_plan  # noqa: E402

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

pytestmark = pytest.mark.asyncio

_MONDAY = date(2026, 9, 14)
_USER_A = "prefs-user-a"
_USER_B = "prefs-user-b"


class _UpdateResult:
    matched_count = 1
    modified_count = 1


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def _match(self, doc: dict, query: dict) -> bool:
        for key, value in query.items():
            current = doc.get(key)
            if isinstance(value, dict):
                if "$gte" in value and (current is None or current < value["$gte"]):
                    return False
                if "$lte" in value and (current is None or current > value["$lte"]):
                    return False
                if "$ne" in value and current == value["$ne"]:
                    return False
                continue
            if current != value:
                return False
        return True

    async def find_one(self, query: dict, projection: Optional[dict] = None, sort=None) -> Optional[dict]:
        rows = [dict(doc) for doc in self._docs if self._match(doc, query)]
        if sort:
            field, direction = sort[0]
            rows.sort(key=lambda doc: doc.get(field) or "", reverse=direction < 0)
        return rows[0] if rows else None

    class _Cursor:
        def __init__(self, docs: List[dict]) -> None:
            self._docs = docs

        def sort(self, *_args: Any, **_kwargs: Any) -> "_Collection._Cursor":
            return self

        def limit(self, n: int) -> "_Collection._Cursor":
            self._docs = self._docs[:n]
            return self

        async def to_list(self, length: Optional[int] = None) -> List[dict]:
            if length is None:
                return list(self._docs)
            return list(self._docs[:length])

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> "_Collection._Cursor":
        results = [dict(doc) for doc in self._docs if self._match(doc, query or {})]
        return self._Cursor(results)

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> _UpdateResult:
        for doc in self._docs:
            if self._match(doc, query):
                doc.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    doc.pop(key, None)
                return _UpdateResult()
        if upsert:
            self._docs.append({**query, **update.get("$setOnInsert", {}), **update.get("$set", {})})
        return _UpdateResult()

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def delete_one(self, query: dict):
        for index, doc in enumerate(self._docs):
            if self._match(doc, query):
                self._docs.pop(index)
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    async def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self._docs if self._match(doc, query))

    async def create_index(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _FakeDB:
    def __init__(self) -> None:
        self.training_cycles = _Collection()
        self.training_prefs = _Collection()
        self.user_goals = _Collection()
        self.garmin_activities = _Collection()
        self.garmin_connections = _Collection()
        self.garmin_daily_metrics = _Collection()
        self.user_profiles = _Collection()
        self.training_prescription_snapshots = _Collection()
        self.training_planned_prescription_memory = _Collection()
        self.garmin_vo2max = _Collection()

    def __getattr__(self, name: str) -> _Collection:
        collection = _Collection()
        object.__setattr__(self, name, collection)
        return collection


async def _user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _bearer(user_id: str) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, f"{user_id}@example.com")}


def _make_fixed_datetime_class(fixed: datetime) -> type:
    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    return _FixedDT


def _patches(fake_db: _FakeDB, reference_date: date = _MONDAY) -> list:
    fixed_dt = datetime(
        reference_date.year,
        reference_date.month,
        reference_date.day,
        8,
        0,
        0,
        tzinfo=timezone.utc,
    )
    return [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
        patch("server.datetime", _make_fixed_datetime_class(fixed_dt)),
    ]


async def _request(
    method: str,
    path: str,
    *,
    fake_db: _FakeDB,
    user_id: str,
    json: Optional[dict] = None,
    reference_date: date = _MONDAY,
):
    if httpx is None:
        pytest.skip("httpx not installed")
    started = []
    try:
        for patcher in _patches(fake_db, reference_date):
            patcher.start()
            started.append(patcher)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            return await client.request(method, path, headers=_bearer(user_id), json=json)
    finally:
        for patcher in reversed(started):
            patcher.stop()


def _seed_cycle(fake_db: _FakeDB, user_id: str, *, goal: str = "SEMI", reference_date: date = _MONDAY) -> None:
    fake_db.training_cycles._docs.append(
        {
            "user_id": user_id,
            "goal": goal,
            "start_date": (reference_date - timedelta(weeks=4)).isoformat(),
        }
    )


def _seed_garmin_activities(
    fake_db: _FakeDB,
    user_id: str,
    *,
    n: int,
    km_per: float,
    reference_date: date = _MONDAY,
) -> None:
    for index in range(n):
        act_date = reference_date - timedelta(days=7 + index * 2)
        fake_db.garmin_activities._docs.append(
            {
                "user_id": user_id,
                "activity_type": "running",
                "start_time": act_date.isoformat() + "T07:00:00",
                "distance_m": km_per * 1000.0,
                "duration_s": km_per * 360,
                "average_hr": 145,
                "source_activity_id": f"{user_id}-{index}",
            }
        )


def _canonical_sessions(
    fake_db: _FakeDB,
    user_id: str,
    *,
    sessions_preference: Optional[int],
    reference_date: date = _MONDAY,
):
    cycle = next(doc for doc in fake_db.training_cycles._docs if doc["user_id"] == user_id)
    goal_doc = next((doc for doc in fake_db.user_goals._docs if doc.get("user_id") == user_id), None)
    garmin_docs = [
        doc
        for doc in fake_db.garmin_activities._docs
        if doc.get("user_id") == user_id
    ]
    canonical = build_canonical_weekly_plan(
        workouts=mongo_garmin_activities_to_domain(garmin_docs),
        goal_type=cycle.get("goal", "SEMI"),
        race_date=date.fromisoformat(goal_doc["event_date"]) if goal_doc and goal_doc.get("event_date") else None,
        cycle_start_date=date.fromisoformat(str(cycle["start_date"])[:10]),
        reference_date=reference_date,
        sessions_preference=sessions_preference,
    )
    return canonical.reconciled_target.target_sessions


@pytest.mark.parametrize("value", [2, 3, 4, 5, 6])
async def test_preferences_patch_accepts_supported_session_counts(value: int):
    fake_db = _FakeDB()

    response = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_A,
        json={"sessions_per_week": value},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "updated",
        "training_prefs": {"sessions_per_week": value},
    }
    stored = await fake_db.training_prefs.find_one({"user_id": _USER_A})
    assert stored == {"user_id": _USER_A, "sessions_per_week": value}


@pytest.mark.parametrize(
    "payload",
    [
        {"sessions_per_week": 1},
        {"sessions_per_week": 7},
        {"sessions_per_week": 0},
        {"sessions_per_week": -1},
        {"sessions_per_week": 3.5},
        {"sessions_per_week": True},
        {"sessions_per_week": None},
        {},
    ],
)
async def test_preferences_patch_rejects_invalid_values(payload: dict):
    fake_db = _FakeDB()

    response = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_A,
        json=payload,
    )

    assert response.status_code == 422, response.text
    assert fake_db.training_prefs._docs == []


async def test_preferences_patch_is_user_isolated():
    fake_db = _FakeDB()

    response_a = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_A,
        json={"sessions_per_week": 3},
    )
    response_b = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_B,
        json={"sessions_per_week": 5},
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert await fake_db.training_prefs.find_one({"user_id": _USER_A}) == {
        "user_id": _USER_A,
        "sessions_per_week": 3,
    }
    assert await fake_db.training_prefs.find_one({"user_id": _USER_B}) == {
        "user_id": _USER_B,
        "sessions_per_week": 5,
    }


async def test_preferences_patch_has_no_generator_side_effects():
    fake_db = _FakeDB()
    existing_plan_cache = getattr(coach_service, "_plan_cache", None)

    response = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_A,
        json={"sessions_per_week": 4},
    )

    assert response.status_code == 200, response.text
    assert fake_db.training_cycles._docs == []
    assert await fake_db.training_prefs.find_one({"user_id": _USER_A}) == {
        "user_id": _USER_A,
        "sessions_per_week": 4,
    }
    assert getattr(coach_service, "_plan_cache", None) is existing_plan_cache


async def test_preferences_patch_reads_back_from_canonical_week_and_caps_sessions():
    fake_db = _FakeDB()
    _seed_cycle(fake_db, _USER_A)
    _seed_garmin_activities(fake_db, _USER_A, n=20, km_per=12.0)

    patch_response = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_A,
        json={"sessions_per_week": 3},
    )
    week_response = await _request(
        "GET",
        "/api/training/v2/week",
        fake_db=fake_db,
        user_id=_USER_A,
    )

    expected_sessions = _canonical_sessions(fake_db, _USER_A, sessions_preference=3)

    assert patch_response.status_code == 200, patch_response.text
    assert week_response.status_code == 200, week_response.text
    body = week_response.json()
    assert body["training_prefs"]["sessions_per_week"] == 3
    assert body["weekly_target"]["session_count"] == expected_sessions
    assert body["week"]["session_count"] == expected_sessions


async def test_preferences_cannot_increase_canonical_recommendation():
    fake_db = _FakeDB()
    _seed_cycle(fake_db, _USER_A)

    patch_response = await _request(
        "PATCH",
        "/api/training/v2/preferences",
        fake_db=fake_db,
        user_id=_USER_A,
        json={"sessions_per_week": 6},
    )
    week_response = await _request(
        "GET",
        "/api/training/v2/week",
        fake_db=fake_db,
        user_id=_USER_A,
    )

    recommended_without_preference = _canonical_sessions(fake_db, _USER_A, sessions_preference=None)
    recommended_with_preference = _canonical_sessions(fake_db, _USER_A, sessions_preference=6)

    assert recommended_without_preference < 6
    assert recommended_with_preference == recommended_without_preference
    assert patch_response.status_code == 200, patch_response.text
    assert week_response.status_code == 200, week_response.text
    assert week_response.json()["weekly_target"]["session_count"] == recommended_without_preference


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/training/plan"),
        ("POST", "/api/training/refresh"),
        ("GET", "/api/training-plan"),
        ("GET", "/api/training/dynamic-plan"),
    ],
)
async def test_removed_legacy_dynamic_plan_routes_return_404(method: str, path: str):
    fake_db = _FakeDB()

    response = await _request(method, path, fake_db=fake_db, user_id=_USER_A)

    assert response.status_code == 404, response.text


def test_route_table_absent_for_removed_routes_and_present_for_canonical_routes():
    route_paths = {route.path for route in server.app.routes}

    assert "/api/training/plan" not in route_paths
    assert "/api/training/refresh" not in route_paths
    assert "/api/training-plan" not in route_paths
    assert "/api/training/dynamic-plan" not in route_paths

    assert "/api/training/today" in route_paths
    assert "/api/training/v2/week" in route_paths
    assert "/api/training/v2/cycle" in route_paths
    assert "/api/training/v2/preferences" in route_paths
