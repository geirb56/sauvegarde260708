from __future__ import annotations

import os
import sys
from copy import deepcopy
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
from training_v2.training_preferences import (  # noqa: E402
    preferences_response,
    resolve_active_preferences,
)

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

pytestmark = pytest.mark.asyncio

_MONDAY = date(2026, 9, 14)
_USER_A = "prefs-user-a"
_USER_B = "prefs-user-b"


class _UpdateResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count
        self.modified_count = matched_count


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def _match(self, doc: dict, query: dict) -> bool:
        for key, value in query.items():
            if key == "$or":
                if not any(self._match(doc, branch) for branch in value):
                    return False
                continue
            if key == "$expr":
                left, right = value["$ne"]
                if doc.get(left.removeprefix("$")) == doc.get(right.removeprefix("$")):
                    return False
                continue
            current = doc.get(key)
            if isinstance(value, dict):
                if "$exists" in value and (key in doc) != value["$exists"]:
                    return False
                if "$gte" in value and (current is None or current < value["$gte"]):
                    return False
                if "$lte" in value and (current is None or current > value["$lte"]):
                    return False
                if "$gt" in value and (
                    current is None or current <= value["$gt"]
                ):
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
        return _UpdateResult(0)

    async def insert_one(self, doc: dict) -> None:
        if "_id" in doc and any(row.get("_id") == doc["_id"] for row in self._docs):
            raise server.DuplicateKeyError("duplicate _id")
        self._docs.append(dict(doc))

    async def delete_one(self, query: dict):
        for index, doc in enumerate(self._docs):
            if self._match(doc, query):
                self._docs.pop(index)
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    async def delete_many(self, query: dict):
        self._docs = [doc for doc in self._docs if not self._match(doc, query)]

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
        self.users = _Collection([
            {"id": _USER_A, "email": f"{_USER_A}@example.com", "is_active": True, "is_email_verified": True},
            {"id": _USER_B, "email": f"{_USER_B}@example.com", "is_active": True, "is_email_verified": True},
        ])

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
        patch.object(server.app.state, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
        patch("server.datetime", _make_fixed_datetime_class(fixed_dt)),
        patch.object(server.rate_limiter, "is_limited", return_value=False),
        patch.object(server.rate_limiter, "record"),
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
        "training_prefs": {
            "sessions_per_week": value,
            "preferred_training_days": None,
            "preferred_long_run_day": None,
            "effective_from": "2026-09-21",
            "active_preferences": {
                "sessions_per_week": None,
                "preferred_training_days": None,
                "preferred_long_run_day": None,
            },
        },
    }
    stored = await fake_db.training_prefs.find_one({"user_id": _USER_A})
    assert stored["user_id"] == _USER_A
    assert preferences_response(stored, _MONDAY) == response.json()["training_prefs"]


@pytest.mark.parametrize(
    "payload",
    [
        {"sessions_per_week": 1},
        {"sessions_per_week": 7},
        {"sessions_per_week": 0},
        {"sessions_per_week": -1},
        {"sessions_per_week": "3"},
        {"sessions_per_week": "5"},
        {"sessions_per_week": 3.0},
        {"sessions_per_week": 5.0},
        {"sessions_per_week": 3.5},
        {"sessions_per_week": True},
        {"sessions_per_week": False},
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


@pytest.mark.parametrize("payload", [
    {"preferred_training_days": []},
    {"preferred_training_days": ["monday", "monday"]},
    {"preferred_training_days": ["Monday"]},
    {"preferred_training_days": ["holiday"]},
    {"preferred_training_days": [1]},
    {"preferred_training_days": "monday"},
    {"preferred_long_run_day": "Sunday"},
    {"preferred_long_run_day": "holiday"},
    {"preferred_long_run_day": 1},
    {"unknown": "monday"},
])
async def test_invalid_calendar_preferences(payload):
    fake_db = _FakeDB()
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json=payload,
    )
    assert response.status_code == 422, response.text
    assert fake_db.training_prefs._docs == []


async def test_absent_and_legacy_preferences_get_do_not_write():
    fake_db = _FakeDB()
    absent = await _request(
        "GET", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
    )
    assert absent.status_code == 200
    assert absent.json()["training_prefs"] == preferences_response(None, _MONDAY)
    assert fake_db.training_prefs._docs == []
    fake_db.training_prefs._docs.append({"user_id": _USER_A, "sessions_per_week": 4})
    legacy = await _request(
        "GET", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
    )
    assert legacy.json()["training_prefs"]["active_preferences"]["sessions_per_week"] == 4
    assert fake_db.training_prefs._docs == [{"user_id": _USER_A, "sessions_per_week": 4}]


@pytest.mark.parametrize("day", [_MONDAY, _MONDAY + timedelta(days=2), _MONDAY + timedelta(days=6)])
async def test_partial_updates_preserve_baseline_and_promote_on_next_week(day):
    fake_db = _FakeDB()
    fake_db.training_prefs._docs.append({"user_id": _USER_A, "sessions_per_week": 4})
    first = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=day,
        json={"preferred_training_days": ["monday", "wednesday", "sunday"], "preferred_long_run_day": "sunday"},
    )
    assert first.status_code == 200, first.text
    prefs = first.json()["training_prefs"]
    assert prefs["sessions_per_week"] == 4
    assert prefs["effective_from"] == "2026-09-21"
    assert prefs["active_preferences"]["preferred_training_days"] is None
    second = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=day, json={"sessions_per_week": 3},
    )
    assert second.status_code == 200, second.text
    prefs = second.json()["training_prefs"]
    assert prefs["preferred_long_run_day"] == "sunday"
    assert prefs["active_preferences"]["sessions_per_week"] == 4
    invalid = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=day, json={"preferred_training_days": ["monday"]},
    )
    assert invalid.status_code == 422
    next_week = _MONDAY + timedelta(days=7)
    activated = await _request(
        "GET", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=next_week,
    )
    assert activated.json()["training_prefs"]["active_preferences"] == {
        "sessions_per_week": 3,
        "preferred_training_days": ["monday", "wednesday", "sunday"],
        "preferred_long_run_day": "sunday",
    }
    third = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=next_week + timedelta(days=2),
        json={"preferred_long_run_day": None, "sessions_per_week": 2},
    )
    assert third.status_code == 200, third.text
    prefs = third.json()["training_prefs"]
    assert prefs["effective_from"] == "2026-09-28"
    assert prefs["preferred_long_run_day"] is None
    assert prefs["active_preferences"] == activated.json()["training_prefs"]["active_preferences"]
    reset = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=next_week + timedelta(days=6), json={"preferred_training_days": None},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["training_prefs"]["preferred_training_days"] is None
    assert reset.json()["training_prefs"]["sessions_per_week"] == 2
    stored = await fake_db.training_prefs.find_one({"user_id": _USER_A})
    assert resolve_active_preferences(stored, next_week + timedelta(days=7)) == {
        "sessions_per_week": 2, "preferred_training_days": None, "preferred_long_run_day": None,
    }


async def test_merged_validation_allows_days_and_long_run_reset_together():
    fake_db = _FakeDB()
    fake_db.training_prefs._docs.append({
        "user_id": _USER_A, "sessions_per_week": 3,
        "preferred_training_days": ["tuesday", "sunday"], "preferred_long_run_day": "sunday",
    })
    rejected = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json={"preferred_long_run_day": "monday"},
    )
    assert rejected.status_code == 422
    accepted = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        json={"preferred_training_days": ["monday"], "preferred_long_run_day": None},
    )
    assert accepted.status_code == 200


async def test_patch_retries_compare_and_swap_without_losing_other_changes():
    fake_db = _FakeDB()
    fake_db.training_prefs._docs.append({"user_id": _USER_A, "sessions_per_week": 4})
    original = fake_db.training_prefs.update_one
    conflicted = False

    async def update_with_conflict(query, update, upsert=False):
        nonlocal conflicted
        if not conflicted:
            conflicted = True
            fake_db.training_prefs._docs[0].update({
                "preferences_revision": 1,
                "preferred_training_days": ["tuesday", "sunday"],
                "effective_from": "2026-09-21",
                "active_preferences": {"sessions_per_week": 4},
            })
        return await original(query, update, upsert)

    fake_db.training_prefs.update_one = update_with_conflict
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json={"preferred_long_run_day": "sunday"},
    )
    assert response.status_code == 200, response.text
    prefs = response.json()["training_prefs"]
    assert prefs["preferred_training_days"] == ["tuesday", "sunday"]
    assert prefs["preferred_long_run_day"] == "sunday"
    assert fake_db.training_prefs._docs[0]["preferences_revision"] == 2


async def test_concurrent_first_write_retries_duplicate_id():
    fake_db = _FakeDB()
    original = fake_db.training_prefs.insert_one
    conflicted = False

    async def insert_with_conflict(document):
        nonlocal conflicted
        if not conflicted:
            conflicted = True
            await original({
                "_id": _USER_A, "user_id": _USER_A, "preferences_revision": 1,
                "sessions_per_week": 3,
            })
            raise server.DuplicateKeyError("competing first write")
        await original(document)

    fake_db.training_prefs.insert_one = insert_with_conflict
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json={"preferred_long_run_day": "sunday"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["training_prefs"]["sessions_per_week"] == 3
    assert len(fake_db.training_prefs._docs) == 1


async def test_exhausted_cas_returns_explicit_conflict():
    fake_db = _FakeDB()
    fake_db.training_prefs._docs.append({"user_id": _USER_A, "sessions_per_week": 4})
    fake_db.training_prefs.update_one = AsyncMock(return_value=_UpdateResult(0))
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json={"sessions_per_week": 3},
    )
    assert response.status_code == 409
    assert fake_db.training_prefs.update_one.await_count == 5
    assert fake_db.training_prefs._docs[0]["sessions_per_week"] == 4


async def test_patch_returns_persisted_readback():
    fake_db = _FakeDB()
    original = fake_db.training_prefs.insert_one

    async def insert_with_database_value(document):
        await original({**document, "sessions_per_week": 5})

    fake_db.training_prefs.insert_one = insert_with_database_value
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json={"sessions_per_week": 3},
    )
    assert response.status_code == 200
    assert response.json()["training_prefs"]["sessions_per_week"] == 5


@pytest.mark.parametrize("method", ["GET", "PATCH"])
async def test_preferences_requires_authentication(method):
    fake_db = _FakeDB()
    with patch.object(server, "db", fake_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            response = await client.request(
                method, "/api/training/v2/preferences", json={"sessions_per_week": 3},
            )
    assert response.status_code in (401, 403)
    assert fake_db.training_prefs._docs == []


async def test_today_week_share_only_active_preferences_and_preserve_frozen_snapshot():
    fake_db = _FakeDB()
    _seed_cycle(fake_db, _USER_A)
    _seed_garmin_activities(fake_db, _USER_A, n=20, km_per=12)
    day = _MONDAY + timedelta(days=2)
    fake_db.training_prefs._docs.append({"user_id": _USER_A, "sessions_per_week": 4})
    before = await _request(
        "GET", "/api/training/today", fake_db=fake_db, user_id=_USER_A, reference_date=day,
    )
    assert before.status_code == 200, before.text
    snapshots = deepcopy(fake_db.training_prescription_snapshots._docs)
    assert snapshots
    changed = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
        reference_date=day,
        json={"sessions_per_week": 2, "preferred_training_days": ["tuesday", "sunday"], "preferred_long_run_day": "sunday"},
    )
    assert changed.status_code == 200, changed.text
    assert fake_db.training_prescription_snapshots._docs == snapshots
    with patch(
        "training_v2.week_plan_bridge.build_canonical_weekly_plan",
        wraps=build_canonical_weekly_plan,
    ) as bridge:
        today = await _request(
            "GET", "/api/training/today", fake_db=fake_db, user_id=_USER_A, reference_date=day,
        )
        week = await _request(
            "GET", "/api/training/v2/week", fake_db=fake_db, user_id=_USER_A, reference_date=day,
        )
    assert today.status_code == week.status_code == 200
    assert bridge.call_count == 2
    for call in bridge.call_args_list:
        assert "sessions_preference" not in call.kwargs
        assert call.kwargs["training_preferences"] == {
            "sessions_per_week": 4, "preferred_training_days": None, "preferred_long_run_day": None,
        }
        assert call.kwargs["reference_date"] == day
    assert today.json()["prescription_id"] == before.json()["prescription_id"]
    same_day = next(row for row in week.json()["week"]["sessions"] if row["day"] == "wednesday")
    assert same_day["prescription_id"] == today.json()["prescription_id"]
    assert week.json()["training_prefs"] == changed.json()["training_prefs"]
    assert fake_db.training_prescription_snapshots._docs == snapshots
    with patch(
        "training_v2.week_plan_bridge.build_canonical_weekly_plan",
        wraps=build_canonical_weekly_plan,
    ) as bridge:
        next_today = await _request(
            "GET", "/api/training/today", fake_db=fake_db, user_id=_USER_A,
            reference_date=_MONDAY + timedelta(days=7),
        )
        next_week = await _request(
            "GET", "/api/training/v2/week", fake_db=fake_db, user_id=_USER_A,
            reference_date=_MONDAY + timedelta(days=7),
        )
    assert next_today.status_code == next_week.status_code == 200
    assert bridge.call_count == 2
    for call in bridge.call_args_list:
        assert call.kwargs["training_preferences"] == {
            "sessions_per_week": 2,
            "preferred_training_days": ["tuesday", "sunday"],
            "preferred_long_run_day": "sunday",
        }


async def test_preferences_clock_matches_today_week_at_local_sunday_boundary():
    fake_db = _FakeDB()
    _seed_cycle(fake_db, _USER_A)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_A, "activity_type": "running",
        "start_time": "2026-09-13T23:00:00", "distance_m": 5000, "duration_s": 1800,
        "startTimeGMT": "2026-09-13T23:00:00", "startTimeLocal": "2026-09-13T13:00:00",
    })
    # UTC Monday 08:00 is still local Sunday at the Garmin-observed UTC-10 offset.
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=fake_db,
        user_id=_USER_A, json={"sessions_per_week": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["training_prefs"]["effective_from"] == "2026-09-14"
    get_response = await _request(
        "GET", "/api/training/v2/preferences", fake_db=fake_db, user_id=_USER_A,
    )
    assert get_response.json()["training_prefs"] == response.json()["training_prefs"]
    today = await _request("GET", "/api/training/today", fake_db=fake_db, user_id=_USER_A)
    week = await _request("GET", "/api/training/v2/week", fake_db=fake_db, user_id=_USER_A)
    assert today.status_code == week.status_code == 200
    assert today.json()["date"] == week.json()["reference_date"] == "2026-09-13"
    assert week.json()["training_prefs"] == response.json()["training_prefs"]


async def test_week_exposes_race_calendar_preference_fallback_reasons():
    fake_db = _FakeDB()
    _seed_cycle(fake_db, _USER_A)
    _seed_garmin_activities(fake_db, _USER_A, n=20, km_per=12)
    fake_db.user_goals._docs.append({
        "user_id": _USER_A, "event_date": "2026-09-20", "distance_type": "semi",
    })
    fake_db.training_prefs._docs.append({
        "user_id": _USER_A, "sessions_per_week": 4,
        "preferred_training_days": ["sunday"], "preferred_long_run_day": "sunday",
    })
    response = await _request(
        "GET", "/api/training/v2/week", fake_db=fake_db, user_id=_USER_A,
    )
    assert response.status_code == 200, response.text
    week = response.json()["week"]
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" in week["reason_codes"]
    sessions = {session["day"]: session for session in week["sessions"]}
    assert sessions["sunday"]["workout_type"] == "race"
    assert sessions["saturday"]["workout_type"] == "rest"
    today = await _request(
        "GET", "/api/training/today", fake_db=fake_db, user_id=_USER_A,
    )
    assert today.status_code == 200, today.text
    assert today.json()["schedule_reason_codes"] == week["reason_codes"]
    snapshots = deepcopy(fake_db.training_prescription_snapshots._docs)
    frozen_reasons = today.json()["reason_codes"]
    fake_db.training_prefs._docs[0].update({
        "preferred_training_days": None, "preferred_long_run_day": None,
    })
    replay = await _request(
        "GET", "/api/training/today", fake_db=fake_db, user_id=_USER_A,
    )
    assert replay.status_code == 200, replay.text
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" not in replay.json()["schedule_reason_codes"]
    assert replay.json()["reason_codes"] == frozen_reasons
    assert replay.json()["prescription_id"] == today.json()["prescription_id"]
    assert fake_db.training_prescription_snapshots._docs == snapshots


async def test_coach_metrics_excludes_plan_requests_field():
    previous = coach_service.reset_metrics()

    try:
        current = coach_service.get_metrics()
        assert "plan_requests" not in current
        assert "plan_requests" not in previous
    finally:
        coach_service.reset_metrics()


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
    for user_id, expected in ((_USER_A, 3), (_USER_B, 5)):
        stored = await fake_db.training_prefs.find_one({"user_id": user_id})
        assert stored["sessions_per_week"] == expected
        response = await _request("GET", "/api/training/v2/preferences", fake_db=fake_db, user_id=user_id)
        assert response.json()["training_prefs"]["sessions_per_week"] == expected


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
    assert (await fake_db.training_prefs.find_one({"user_id": _USER_A}))["sessions_per_week"] == 4
    assert fake_db.training_prescription_snapshots._docs == []
    assert fake_db.training_planned_prescription_memory._docs == []
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

    expected_sessions = _canonical_sessions(fake_db, _USER_A, sessions_preference=None)

    assert patch_response.status_code == 200, patch_response.text
    assert week_response.status_code == 200, week_response.text
    body = week_response.json()
    assert body["training_prefs"]["sessions_per_week"] == 3
    assert body["training_prefs"]["active_preferences"]["sessions_per_week"] is None
    assert body["weekly_target"]["session_count"] == expected_sessions
    assert body["week"]["session_count"] == expected_sessions

    next_week = _MONDAY + timedelta(days=7)
    activated = await _request(
        "GET", "/api/training/v2/week", fake_db=fake_db, user_id=_USER_A,
        reference_date=next_week,
    )
    assert activated.status_code == 200, activated.text
    expected_active = _canonical_sessions(
        fake_db, _USER_A, sessions_preference=3, reference_date=next_week,
    )
    assert activated.json()["weekly_target"]["session_count"] == expected_active
    assert activated.json()["training_prefs"]["active_preferences"]["sessions_per_week"] == 3


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
    route_paths = {route.path for route in server.app.routes if hasattr(route, "path")}
    route_paths.update(
        route.path for route in getattr(server, "api_router").routes if hasattr(route, "path")
    )

    assert "/api/training/plan" not in route_paths
    assert "/api/training/refresh" not in route_paths
    assert "/api/training-plan" not in route_paths
    assert "/api/training/dynamic-plan" not in route_paths

    assert "/api/training/today" in route_paths
    assert "/api/training/v2/week" in route_paths
    assert "/api/training/v2/cycle" in route_paths
    assert "/api/training/v2/preferences" in route_paths
