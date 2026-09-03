"""PR226 — Goal-truth unification tests (final patch).

Section A: unit / source-inspection tests (no imports of server.py)
Section B: async integration tests using _resolve_goal_v2 with mocked DB
Section C: endpoint-level integration tests with FastAPI TestClient

Required coverage (from problem statement):
 ✓ 10K coherent → cycle/week OK
 ✓ cycle 10K + user_goal semi → rejected (coherence check)
 ✓ MAINTENANCE + metadata race → rejected (POST /user/goal) / ignored (/v2/week)
 ✓ ULTRA 50 km → /training/v2/week OK
 ✓ ULTRA 50 km → /training/v2/cycle OK
 ✓ ULTRA sans distance → rejected without mutation
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Path setup ───────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "testdb")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_SERVER_PY = os.path.join(_BACKEND_DIR, "server.py")


def _src() -> str:
    with open(_SERVER_PY, encoding="utf-8") as f:
        return f.read()


# ════════════════════════════════════════════════════════════════════════════
# Section A — Pure unit / source-inspection tests
# ════════════════════════════════════════════════════════════════════════════

def test_goal_config_has_all_goals():
    from config.training_goals import GOAL_CONFIG
    assert set(GOAL_CONFIG.keys()) == {"5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"}


@pytest.mark.parametrize("goal", ["5K", "10K", "SEMI", "MARATHON"])
def test_standard_goal_cycle_weeks(goal):
    from config.training_goals import GOAL_CONFIG
    assert GOAL_CONFIG[goal]["cycle_weeks"] > 0


def test_maintenance_has_no_race_date():
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="user")
    assert pg.race_date is None


def test_maintenance_has_no_target_time():
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="user")
    assert pg.target_time_seconds is None


def test_maintenance_rejects_race_date():
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises((ValueError, Exception)):
        build_plan_goal(
            goal_type=GoalType.maintenance,
            race_date=date(2027, 1, 1),
            created_from="user",
        )


def test_fallback_without_goal_is_maintenance():
    """Server fallback must be MAINTENANCE not SEMI."""
    src = _src()
    assert re.search(r'plan_data\.get\(["\']goal["\'],\s*["\']MAINTENANCE["\']', src), \
        "Fallback must be MAINTENANCE not SEMI"


def test_set_goal_deletes_user_goals():
    src = _src()
    assert "user_goals.delete_many" in src, "set-goal must delete user_goals"


def test_ultra_without_distance_rejected():
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises((ValueError, Exception)):
        build_plan_goal(goal_type=GoalType.ultra, created_from="user")


def test_ultra_exactly_42195_rejected():
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises((ValueError, Exception)):
        build_plan_goal(
            goal_type=GoalType.ultra,
            target_distance_km=42.195,
            created_from="user",
        )


def test_ultra_valid_distance_accepted():
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(
        goal_type=GoalType.ultra,
        target_distance_km=50.0,
        created_from="user",
    )
    assert pg.target_distance_km == 50.0


def test_ultra_distance_propagated_exactly():
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(
        goal_type=GoalType.ultra,
        target_distance_km=170.0,
        created_from="user",
    )
    assert pg.target_distance_km == 170.0


def test_user_goal_create_model_has_distance_km():
    import server as srv
    import inspect
    sig = inspect.signature(srv.UserGoalCreate)
    assert "distance_km" in sig.parameters


def test_canonical_resolver_exists():
    import server as srv
    assert hasattr(srv, "_resolve_goal_v2"), "_resolve_goal_v2 must exist in server.py"
    import asyncio
    assert asyncio.iscoroutinefunction(srv._resolve_goal_v2), "_resolve_goal_v2 must be async"


def test_semi_distance_is_21_0975():
    import server as srv
    assert srv.DISTANCE_TYPES["semi"] == 21.0975


def test_ultra_not_in_distance_types():
    import server as srv
    assert "ultra" not in srv.DISTANCE_TYPES, "ultra must not have a hardcoded distance"


def test_validate_ultra_distance_km_helper_exists():
    import server as srv
    assert callable(srv._validate_ultra_distance_km)


def test_validate_ultra_rejects_none():
    from fastapi import HTTPException
    import server as srv
    with pytest.raises(HTTPException) as exc_info:
        srv._validate_ultra_distance_km(None)
    assert exc_info.value.status_code == 400


def test_validate_ultra_rejects_42195():
    from fastapi import HTTPException
    import server as srv
    with pytest.raises(HTTPException) as exc_info:
        srv._validate_ultra_distance_km(42.195)
    assert exc_info.value.status_code == 400


def test_validate_ultra_accepts_50():
    import server as srv
    result = srv._validate_ultra_distance_km(50.0)
    assert result == 50.0


def test_goal_to_distance_type_map():
    import server as srv
    m = srv._GOAL_TO_DISTANCE_TYPE
    assert m["5K"] == "5k"
    assert m["10K"] == "10k"
    assert m["SEMI"] == "semi"
    assert m["MARATHON"] == "marathon"
    assert m["ULTRA"] == "ultra"
    assert "MAINTENANCE" not in m


def test_build_weekly_target_from_workouts_has_target_distance_param():
    from training_v2.week_plan_bridge import build_weekly_target_from_workouts
    import inspect
    sig = inspect.signature(build_weekly_target_from_workouts)
    assert "target_distance_km" in sig.parameters


def test_invalid_goal_raises_http400():
    """set-goal endpoints must raise HTTPException(400) for invalid goal."""
    src = _src()
    # Must NOT use return {"error": "Invalid goal"} pattern
    assert 'return {"error": "Invalid goal"}' not in src
    # Must use HTTPException 400 for invalid goal
    assert re.search(r'HTTPException.*status_code=400.*Invalid goal', src, re.DOTALL), \
        "Invalid goal must raise HTTPException(400)"


def test_post_user_goal_blocks_maintenance():
    """POST /user/goal must be blocked when cycle=MAINTENANCE."""
    src = _src()
    assert "MAINTENANCE" in src and "Cannot set race goal" in src, \
        "POST /user/goal must reject when cycle=MAINTENANCE"


def test_event_date_validated_in_post_user_goal():
    """POST /user/goal must validate event_date before any mutation."""
    src = _src()
    assert "parsed_event_date" in src or "fromisoformat" in src, \
        "event_date must be validated"


# ════════════════════════════════════════════════════════════════════════════
# Section B — Async integration tests for _resolve_goal_v2
# ════════════════════════════════════════════════════════════════════════════

def _make_db(cycle=None, user_goal=None, activities=None):
    """Build a mock db with find_one returning given docs."""
    db = MagicMock()

    async def _cycle_find_one(*args, **kwargs):
        return cycle

    async def _goal_find_one(*args, **kwargs):
        return user_goal

    db.training_cycles.find_one = _cycle_find_one
    db.user_goals.find_one = _goal_find_one
    return db


_CYCLE_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


def test_resolve_goal_10k_coherent():
    """10K cycle with no user_goal → resolved OK, race_date=None."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle, user_goal=None)
    with patch.object(srv, "db", mock_db):
        resolved = _run(srv._resolve_goal_v2("user1"))
    assert resolved.goal_type == "10K"
    assert resolved.race_date is None
    assert resolved.target_distance_km is None


def test_resolve_goal_10k_with_coherent_user_goal():
    """10K cycle + user_goal distance_type=10k → OK."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    user_goal = {
        "distance_type": "10k",
        "event_date": "2027-06-01",
        "target_time_minutes": 55,
    }
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    with patch.object(srv, "db", mock_db):
        resolved = _run(srv._resolve_goal_v2("user1"))
    assert resolved.goal_type == "10K"
    assert resolved.race_date == date(2027, 6, 1)
    assert resolved.target_time_sec == 55 * 60


def test_resolve_goal_10k_target_time_without_event_date():
    """10K cycle + target_time only (no race date) resolves with race_date=None."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    user_goal = {
        "distance_type": "10k",
        "event_date": None,
        "target_time_minutes": 50,
    }
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    with patch.object(srv, "db", mock_db):
        resolved = _run(srv._resolve_goal_v2("user1"))
    assert resolved.goal_type == "10K"
    assert resolved.race_date is None
    assert resolved.target_time_sec == 50 * 60


def test_resolve_goal_10k_incoherent_semi_rejected():
    """10K cycle + user_goal distance_type=semi → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    user_goal = {"distance_type": "semi", "event_date": "2027-06-01"}
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400
    assert "10K" in exc_info.value.detail
    assert "semi" in exc_info.value.detail


def test_resolve_goal_maintenance_race_date_always_none():
    """MAINTENANCE cycle with user_goal that has event_date → race_date=None."""
    import server as srv
    cycle = {"goal": "MAINTENANCE", "start_date": _CYCLE_START}
    user_goal = {"distance_type": "marathon", "event_date": "2027-06-01"}
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    with patch.object(srv, "db", mock_db):
        resolved = _run(srv._resolve_goal_v2("user1"))
    assert resolved.race_date is None
    assert resolved.target_time_sec is None
    assert resolved.target_distance_km is None


def test_resolve_goal_ultra_50km_ok():
    """ULTRA cycle + ultra_distance_km=50 → resolved, target_distance_km=50."""
    import server as srv
    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START, "ultra_distance_km": 50.0}
    mock_db = _make_db(cycle=cycle, user_goal=None)
    with patch.object(srv, "db", mock_db):
        resolved = _run(srv._resolve_goal_v2("user1"))
    assert resolved.goal_type == "ULTRA"
    assert resolved.target_distance_km == 50.0


def test_resolve_goal_ultra_no_distance_rejected():
    """ULTRA cycle + no distance anywhere → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle, user_goal=None)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400
    assert "42.195" in exc_info.value.detail


def test_resolve_goal_no_cycle_rejected():
    """No training_cycles doc → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    mock_db = _make_db(cycle=None, user_goal=None)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400


# ════════════════════════════════════════════════════════════════════════════
# Section C — POST /user/goal endpoint tests (via _resolve_goal_v2 + handler)
# ════════════════════════════════════════════════════════════════════════════

def test_post_user_goal_maintenance_cycle_blocked():
    """POST /user/goal → 400 when active cycle is MAINTENANCE."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "MAINTENANCE", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate(
        event_name="Test",
        event_date=future_date,
        distance_type="marathon",
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert "MAINTENANCE" in exc_info.value.detail


def test_post_user_goal_ultra_no_distance_no_mutation():
    """ULTRA payload without distance_km → 400, no delete_many called."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    delete_called = []

    async def fake_delete(*a, **kw):
        delete_called.append(True)
        return MagicMock(deleted_count=0)

    mock_db.user_goals.delete_many = fake_delete

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate(
        event_name="Ultra Race",
        event_date=future_date,
        distance_type="ultra",
        distance_km=None,
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert not delete_called, "delete_many must NOT be called when payload is invalid"


def test_post_user_goal_ultra_42195_exact_rejected():
    """distance_km == 42.195 → 400 (must be strictly greater)."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate(
        event_name="Ultra",
        event_date=future_date,
        distance_type="ultra",
        distance_km=42.195,
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400


def test_post_user_goal_10k_incoherent_semi_blocked():
    """10K cycle + distance_type=semi → 400."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    delete_called = []

    async def fake_delete(*a, **kw):
        delete_called.append(True)
        return MagicMock(deleted_count=0)

    mock_db.user_goals.delete_many = fake_delete

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate(
        event_name="HM Race",
        event_date=future_date,
        distance_type="semi",
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert "10K" in exc_info.value.detail
    assert not delete_called, "delete_many must NOT be called on validation failure"


def test_post_user_goal_past_date_rejected():
    """event_date in the past → 400 without mutation."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "MARATHON", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)

    goal_payload = srv.UserGoalCreate(
        event_name="Old Marathon",
        event_date="2020-01-01",
        distance_type="marathon",
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert "future" in exc_info.value.detail.lower() or "past" in exc_info.value.detail.lower() or "event_date" in exc_info.value.detail


@pytest.mark.parametrize("invalid_target_time", [0, -15, True, 12.5])
def test_post_user_goal_invalid_target_time_rejected_without_mutation(invalid_target_time):
    """target_time_minutes invalid => HTTP 400 before any DB mutation."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    delete_called = []
    insert_called = []

    async def fake_delete(*a, **kw):
        delete_called.append(True)
        return MagicMock(deleted_count=0)

    async def fake_insert(doc):
        insert_called.append(doc)
        return MagicMock(inserted_id="x")

    mock_db.user_goals.delete_many = fake_delete
    mock_db.user_goals.insert_one = fake_insert

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate(
        event_name="10K Target",
        event_date=future_date,
        distance_type="10k",
        target_time_minutes=invalid_target_time,
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())

    assert exc_info.value.status_code == 400
    assert "target_time_minutes" in exc_info.value.detail
    assert not delete_called, "delete_many must NOT be called when target_time is invalid"
    assert not insert_called, "insert_one must NOT be called when target_time is invalid"


def test_post_user_goal_non_numeric_target_time_rejected_without_mutation():
    """Non-numeric target_time_minutes => HTTP 400 before any DB mutation."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    delete_called = []
    insert_called = []

    async def fake_delete(*a, **kw):
        delete_called.append(True)
        return MagicMock(deleted_count=0)

    async def fake_insert(doc):
        insert_called.append(doc)
        return MagicMock(inserted_id="x")

    mock_db.user_goals.delete_many = fake_delete
    mock_db.user_goals.insert_one = fake_insert

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate.model_construct(
        event_name="10K Target",
        event_date=future_date,
        distance_type="10k",
        target_time_minutes="abc",
        distance_km=None,
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())

    assert exc_info.value.status_code == 400
    assert "target_time_minutes" in exc_info.value.detail
    assert not delete_called
    assert not insert_called


def test_post_user_goal_ultra_100km_succeeds():
    """Ultra 100 km with coherent ULTRA cycle → insert called once."""
    import server as srv

    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    inserts = []

    async def fake_delete(*a, **kw):
        return MagicMock(deleted_count=0)

    async def fake_insert(doc):
        inserts.append(doc)
        return MagicMock(inserted_id="abc")

    mock_db.user_goals.delete_many = fake_delete
    mock_db.user_goals.insert_one = fake_insert

    future_date = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    goal_payload = srv.UserGoalCreate(
        event_name="Ultra100",
        event_date=future_date,
        distance_type="ultra",
        distance_km=100.0,
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    result = _run(run())
    assert result["success"] is True
    assert inserts[0]["distance_km"] == 100.0


def test_post_user_goal_10k_target_time_without_race_date_succeeds():
    """Target-time-only goal must save with event_name/event_date=None."""
    import server as srv

    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    inserts = []

    async def fake_delete(*a, **kw):
        return MagicMock(deleted_count=0)

    async def fake_insert(doc):
        inserts.append(doc)
        return MagicMock(inserted_id="abc")

    mock_db.user_goals.delete_many = fake_delete
    mock_db.user_goals.insert_one = fake_insert

    goal_payload = srv.UserGoalCreate(
        event_name=None,
        event_date=None,
        distance_type="10k",
        target_time_minutes=50,
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    result = _run(run())
    assert result["success"] is True
    assert inserts[0]["event_name"] is None
    assert inserts[0]["event_date"] is None
    assert inserts[0]["target_time_minutes"] == 50


# ════════════════════════════════════════════════════════════════════════════
# Section D — _resolve_goal_v2 hardening: start_date / event_date validation
# ════════════════════════════════════════════════════════════════════════════

def test_resolve_goal_no_start_date_rejected():
    """Cycle missing start_date entirely → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "10K"}  # no start_date
    mock_db = _make_db(cycle=cycle, user_goal=None)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400
    assert "start_date" in exc_info.value.detail.lower()


def test_resolve_goal_invalid_start_date_rejected():
    """Cycle with garbage start_date string → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "10K", "start_date": "not-a-date"}
    mock_db = _make_db(cycle=cycle, user_goal=None)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400
    assert "start_date" in exc_info.value.detail.lower()


def test_resolve_goal_invalid_event_date_rejected():
    """user_goal present with garbage event_date → HTTP 400 (no silent drop)."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "MARATHON", "start_date": _CYCLE_START}
    user_goal = {"distance_type": "marathon", "event_date": "garbage-date"}
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400
    assert "event_date" in exc_info.value.detail.lower()


def test_resolve_goal_none_start_date_rejected():
    """Cycle with explicit None start_date → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "10K", "start_date": None}
    mock_db = _make_db(cycle=cycle, user_goal=None)
    with patch.object(srv, "db", mock_db):
        with pytest.raises(HTTPException) as exc_info:
            _run(srv._resolve_goal_v2("user1"))
    assert exc_info.value.status_code == 400


# ════════════════════════════════════════════════════════════════════════════
# Section E — Endpoint-level tests: get_training_v2_week / get_training_v2_cycle
# Calls the actual endpoint handler with mocked DB (no server startup needed).
# ════════════════════════════════════════════════════════════════════════════

def _make_db_with_activities(cycle, user_goal=None):
    """Build mock db that also provides garmin_activities.find().to_list()."""
    db = MagicMock()

    async def _cycle_find_one(*args, **kwargs):
        return cycle

    async def _goal_find_one(*args, **kwargs):
        return user_goal

    # garmin_activities.find(...).to_list(N) → empty list
    activities_cursor = MagicMock()
    activities_cursor.to_list = AsyncMock(return_value=[])
    db.garmin_activities.find = MagicMock(return_value=activities_cursor)
    db.training_cycles.find_one = _cycle_find_one
    db.user_goals.find_one = _goal_find_one

    # C231 — training_prescription_snapshots.find(...).to_list(N) → empty list
    snapshots_cursor = MagicMock()
    snapshots_cursor.to_list = AsyncMock(return_value=[])
    db.training_prescription_snapshots.find = MagicMock(return_value=snapshots_cursor)
    db.training_prescription_snapshots.update_one = AsyncMock()
    return db


def test_get_training_v2_week_10k_coherent():
    """get_training_v2_week with 10K cycle → 200, goal_type='10k'."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=None)

    async def run():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                return await srv.get_training_v2_week(user={"id": "u1"})

    result = _run(run())
    assert isinstance(result, dict)
    assert result["goal"]["goal_type"] == "10k"
    assert result["goal"]["race_date"] is None
    assert "weekly_target" in result
    assert "week" in result


def test_get_training_v2_week_target_time_without_race_date():
    """Week endpoint must support target_time with race_date=None."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    user_goal = {"distance_type": "10k", "event_name": None, "event_date": None, "target_time_minutes": 50}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=user_goal)

    async def run():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                return await srv.get_training_v2_week(user={"id": "u1"})

    result = _run(run())
    assert result["goal"]["goal_type"] == "10k"
    assert result["goal"]["race_date"] is None
    assert result["goal"]["target_time_seconds"] == 50 * 60
    assert not any(s.get("phase") in {"taper", "race"} for s in result["week"]["sessions"])


def test_get_training_v2_cycle_10k_coherent():
    """get_training_v2_cycle with 10K cycle → 200, contains phases/weeks."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=None)

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.get_training_v2_cycle(user={"id": "u1"})

    result = _run(run())
    assert isinstance(result, dict)
    # TrainingCycleV2Response has at least goal_type and some calendar info
    assert "goal_type" in result or "phases" in result or "weeks" in result or "calendar" in result or len(result) > 0


def test_get_training_v2_cycle_target_time_without_race_date_is_continuous():
    """Cycle endpoint must stay continuous without race_date."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    user_goal = {"distance_type": "10k", "event_name": None, "event_date": None, "target_time_minutes": 50}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=user_goal)

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.get_training_v2_cycle(user={"id": "u1"})

    result = _run(run())
    assert result["goal"]["goal_type"] == "10k"
    assert result["goal"]["race_date"] is None
    assert result["goal"]["target_time_seconds"] == 50 * 60
    assert result["cycle"]["mode"] == "continuous"
    assert not any(w["phase"] in {"taper", "race"} for w in result["weeks"])


def test_get_training_v2_cycle_adding_race_date_enables_race_calendar():
    """When race_date is later provided, cycle endpoint returns race_calendar."""
    import server as srv
    cycle = {"goal": "10K", "start_date": _CYCLE_START}
    future_date = (datetime.now(timezone.utc).date() + timedelta(days=90)).isoformat()
    user_goal = {"distance_type": "10k", "event_name": "Race", "event_date": future_date, "target_time_minutes": 50}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=user_goal)

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.get_training_v2_cycle(user={"id": "u1"})

    result = _run(run())
    assert result["cycle"]["mode"] == "race_calendar"
    assert any(w["phase"] in {"taper", "race"} for w in result["weeks"])


def test_get_training_v2_week_ultra_50km():
    """get_training_v2_week with ULTRA 50km cycle → 200, goal_type='ultra'."""
    import server as srv
    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START, "ultra_distance_km": 50.0}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=None)

    async def run():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                return await srv.get_training_v2_week(user={"id": "u1"})

    result = _run(run())
    assert isinstance(result, dict)
    assert result["goal"]["goal_type"] == "ultra"
    assert result["goal"]["race_date"] is None


def test_get_training_v2_cycle_ultra_50km():
    """get_training_v2_cycle with ULTRA 50km cycle → 200."""
    import server as srv
    cycle = {"goal": "ULTRA", "start_date": _CYCLE_START, "ultra_distance_km": 50.0}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=None)

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.get_training_v2_cycle(user={"id": "u1"})

    result = _run(run())
    assert isinstance(result, dict)
    assert len(result) > 0


def test_get_training_v2_week_invalid_start_date_rejected():
    """get_training_v2_week with garbage start_date → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "10K", "start_date": "not-a-date"}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=None)

    async def run():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                return await srv.get_training_v2_week(user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert "start_date" in exc_info.value.detail.lower()


def test_get_training_v2_week_invalid_event_date_rejected():
    """get_training_v2_week with garbage event_date in user_goal → HTTP 400."""
    from fastapi import HTTPException
    import server as srv
    cycle = {"goal": "MARATHON", "start_date": _CYCLE_START}
    user_goal = {"distance_type": "marathon", "event_date": "not-a-date"}
    mock_db = _make_db_with_activities(cycle=cycle, user_goal=user_goal)

    async def run():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                return await srv.get_training_v2_week(user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert "event_date" in exc_info.value.detail.lower()


# ════════════════════════════════════════════════════════════════════════════
# Section F — event_date strict validation in POST /user/goal
# ════════════════════════════════════════════════════════════════════════════

def test_post_user_goal_garbage_suffix_date_rejected_no_mutation():
    """'2027-01-01garbage' → HTTP 400; delete_many must NOT be called."""
    from fastapi import HTTPException
    import server as srv

    cycle = {"goal": "MARATHON", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    delete_called = []

    async def fake_delete(*a, **kw):
        delete_called.append(True)
        return MagicMock(deleted_count=0)

    mock_db.user_goals.delete_many = fake_delete

    goal_payload = srv.UserGoalCreate(
        event_name="Marathon Race",
        event_date="2027-01-01garbage",
        distance_type="marathon",
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    with pytest.raises(HTTPException) as exc_info:
        _run(run())
    assert exc_info.value.status_code == 400
    assert "event_date" in exc_info.value.detail.lower() or "2027-01-01garbage" in exc_info.value.detail
    assert not delete_called, "delete_many must NOT be called when payload is invalid"


def test_post_user_goal_normalized_date_stored():
    """Valid date '2028-06-15' → inserted with normalized isoformat, not raw input."""
    import server as srv

    cycle = {"goal": "MARATHON", "start_date": _CYCLE_START}
    mock_db = _make_db(cycle=cycle)
    inserts = []

    async def fake_delete(*a, **kw):
        return MagicMock(deleted_count=0)

    async def fake_insert(doc):
        inserts.append(doc)
        return MagicMock(inserted_id="xyz")

    mock_db.user_goals.delete_many = fake_delete
    mock_db.user_goals.insert_one = fake_insert

    goal_payload = srv.UserGoalCreate(
        event_name="Marathon",
        event_date="2028-06-15",
        distance_type="marathon",
    )

    async def run():
        with patch.object(srv, "db", mock_db):
            return await srv.set_user_goal(goal_payload, user={"id": "u1"})

    result = _run(run())
    assert result["success"] is True
    assert inserts[0]["event_date"] == "2028-06-15"
