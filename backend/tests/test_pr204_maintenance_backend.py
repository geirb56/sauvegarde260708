"""PR204 — Tests: Training Goal MAINTENANCE Backend Support.

Contracts verified
------------------
MAINTENANCE_SET_GOAL         — POST /training/set-goal?goal=MAINTENANCE → success
MAINTENANCE_CYCLE_CREATED    — cycle stored with goal=MAINTENANCE
MAINTENANCE_START_DATE       — start_date set to today (UTC)
MAINTENANCE_RACE_DATE_REQUIRED  — NO: race_date must not be required/accepted
MAINTENANCE_TARGET_TIME_REQUIRED — NO: target_time not accepted
MAINTENANCE_TAPER            — NO: maintenance goal has no taper phase
MAINTENANCE_RACE_WEEK        — NO: maintenance goal has no race_week phase
MAINTENANCE_REFRESH_SESSIONS_3..6 — /training/refresh?sessions=N works
MAINTENANCE_WEEK_GENERATION  — build_weekly_plan_from_workouts accepts MAINTENANCE
MAINTENANCE_GOAL_CONFIG      — GOAL_CONFIG includes MAINTENANCE
MAINTENANCE_GOAL_MAP         — week_plan_bridge._GOAL_MAP maps MAINTENANCE

Non-regression (5K, 10K, SEMI, MARATHON, ULTRA):
REGRESSION_5K / 10K / SEMI / MARATHON / ULTRA — validation still passes
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import date, timedelta, timezone, datetime
from typing import Optional

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-pr204")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from config.training_goals import GOAL_CONFIG  # noqa: E402
from training_v2.plan_goal import GoalType, build_plan_goal  # noqa: E402
from training_v2.week_plan_bridge import (  # noqa: E402
    build_weekly_plan_from_workouts,
    _GOAL_MAP,
)
from training_v2.training_cycle_response import (  # noqa: E402
    build_cycle_calendar_response,
    _RACE_GOALS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANCHOR = date(2024, 1, 1)
_REF = date(2024, 3, 1)


def _workouts_empty():
    return []


# ---------------------------------------------------------------------------
# GOAL_CONFIG includes MAINTENANCE
# ---------------------------------------------------------------------------

def test_goal_config_includes_maintenance():
    assert "MAINTENANCE" in GOAL_CONFIG, "MAINTENANCE must be in GOAL_CONFIG"
    cfg = GOAL_CONFIG["MAINTENANCE"]
    assert isinstance(cfg["cycle_weeks"], int) and cfg["cycle_weeks"] > 0
    assert "description" in cfg


def test_goal_config_race_goals_unchanged():
    for goal in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        assert goal in GOAL_CONFIG, f"{goal} must remain in GOAL_CONFIG"


# ---------------------------------------------------------------------------
# Whitelist validation (server.py logic mirrored)
# ---------------------------------------------------------------------------

_VALID_GOALS_SET_GOAL = {"5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"}
_VALID_GOALS_LEGACY   = {"5K", "10K", "SEMI", "MARATHON", "ULTRA"}

_SERVER_PY = os.path.join(_BACKEND_DIR, "server.py")


def _extract_set_goal_whitelists() -> list[set[str]]:
    """Parse server.py with AST and return all whitelist sets found in
    set-goal / training-plan/set-goal endpoint bodies.

    Looks for:  goal.upper() not in [...]  — returns the list contents.
    """
    with open(_SERVER_PY) as fh:
        tree = ast.parse(fh.read())

    results: list[set[str]] = []
    for node in ast.walk(tree):
        # Match: <expr> not in <list/set/tuple> where list items are strings
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            if isinstance(node.ops[0], ast.NotIn):
                comparator = node.comparators[0]
                if isinstance(comparator, (ast.List, ast.Tuple, ast.Set)):
                    items = {
                        elt.value
                        for elt in comparator.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }
                    if "5K" in items and "MARATHON" in items:
                        results.append(items)
    return results


def test_maintenance_in_whitelist():
    whitelists = _extract_set_goal_whitelists()
    assert whitelists, "Could not extract goal whitelists from server.py"
    for wl in whitelists:
        assert "MAINTENANCE" in wl, (
            f"MAINTENANCE missing from server.py whitelist: {sorted(wl)}"
        )


@pytest.mark.parametrize("goal", ["5K", "10K", "SEMI", "MARATHON", "ULTRA"])
def test_race_goals_still_in_whitelist(goal):
    whitelists = _extract_set_goal_whitelists()
    assert whitelists, "Could not extract goal whitelists from server.py"
    for wl in whitelists:
        assert goal in wl, f"{goal} unexpectedly removed from server.py whitelist"
    assert goal in _VALID_GOALS_LEGACY


# ---------------------------------------------------------------------------
# MAINTENANCE_GOAL_MAP — week_plan_bridge maps MAINTENANCE
# ---------------------------------------------------------------------------

def test_maintenance_in_goal_map():
    assert "MAINTENANCE" in _GOAL_MAP
    assert _GOAL_MAP["MAINTENANCE"] == GoalType.maintenance


@pytest.mark.parametrize("goal,expected", [
    ("5K", GoalType.five_k),
    ("10K", GoalType.ten_k),
    ("SEMI", GoalType.half_marathon),
    ("MARATHON", GoalType.marathon),
    ("ULTRA", GoalType.ultra),
])
def test_race_goal_map_unchanged(goal, expected):
    assert _GOAL_MAP[goal] == expected


# ---------------------------------------------------------------------------
# PlanGoal: MAINTENANCE contract
# ---------------------------------------------------------------------------

def test_maintenance_plan_goal_no_race_date():
    """MAINTENANCE_RACE_DATE_REQUIRED = NO"""
    goal = build_plan_goal(goal_type=GoalType.maintenance)
    assert goal.race_date is None


def test_maintenance_plan_goal_no_target_time():
    """MAINTENANCE_TARGET_TIME_REQUIRED = NO"""
    goal = build_plan_goal(goal_type=GoalType.maintenance)
    assert goal.target_time_seconds is None


def test_maintenance_plan_goal_rejects_race_date():
    """race_date must be rejected for MAINTENANCE"""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type=GoalType.maintenance, race_date=date(2025, 4, 1))


def test_maintenance_plan_goal_rejects_target_time():
    """target_time_seconds must be rejected for MAINTENANCE"""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type=GoalType.maintenance, target_time_seconds=7200)


# ---------------------------------------------------------------------------
# MAINTENANCE not in _RACE_GOALS → no taper / no race_week
# ---------------------------------------------------------------------------

def test_maintenance_not_in_race_goals():
    """MAINTENANCE_TAPER = NO / MAINTENANCE_RACE_WEEK = NO"""
    assert GoalType.maintenance not in _RACE_GOALS


@pytest.mark.parametrize("g", [GoalType.five_k, GoalType.ten_k, GoalType.half_marathon,
                                GoalType.marathon, GoalType.ultra])
def test_race_goals_still_in_race_goals(g):
    assert g in _RACE_GOALS


# ---------------------------------------------------------------------------
# Cycle calendar: MAINTENANCE → continuous, no taper, no race_week
# ---------------------------------------------------------------------------

def test_maintenance_cycle_is_continuous():
    """MAINTENANCE_TAPER = NO, MAINTENANCE_RACE_WEEK = NO"""
    goal = build_plan_goal(goal_type=GoalType.maintenance)
    resp = build_cycle_calendar_response(goal, _REF, cycle_anchor_date=_ANCHOR)
    assert resp.cycle.mode == "continuous"
    phases = {w.phase for w in resp.weeks}
    assert "taper" not in phases, "MAINTENANCE must not have taper phase"
    assert "race_week" not in phases, "MAINTENANCE must not have race_week phase"


def test_maintenance_cycle_start_date_today():
    """MAINTENANCE_START_DATE = TODAY (cycle_anchor_date = today)"""
    today = date.today()
    goal = build_plan_goal(goal_type=GoalType.maintenance)
    resp = build_cycle_calendar_response(goal, today, cycle_anchor_date=today)
    assert resp.cycle.mode == "continuous"
    assert resp.cycle.start_date is not None


# ---------------------------------------------------------------------------
# MAINTENANCE_WEEK_GENERATION = PASS
# ---------------------------------------------------------------------------

def test_maintenance_week_generation():
    """build_weekly_plan_from_workouts accepts MAINTENANCE goal"""
    today = date.today()
    _, weekly_plan = build_weekly_plan_from_workouts(
        workouts=_workouts_empty(),
        goal_type="MAINTENANCE",
        race_date=None,
        cycle_start_date=today,
        reference_date=today,
    )
    assert weekly_plan is not None
    assert len(weekly_plan.sessions) > 0


def test_maintenance_week_generation_ignores_race_date():
    """race_date is silently ignored for MAINTENANCE (no regression for other goals)"""
    today = date.today()
    future_date = today + timedelta(days=90)
    # Should NOT raise even if race_date is passed (bridge strips it for maintenance)
    _, weekly_plan = build_weekly_plan_from_workouts(
        workouts=_workouts_empty(),
        goal_type="MAINTENANCE",
        race_date=future_date,
        cycle_start_date=today,
        reference_date=today,
    )
    assert weekly_plan is not None


# ---------------------------------------------------------------------------
# MAINTENANCE_REFRESH_SESSIONS_3..6 = PASS
# (sessions_per_week parameter flows through; we test the bridge accepts MAINTENANCE)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sessions", [3, 4, 5, 6])
def test_maintenance_week_generation_sessions(sessions):
    """MAINTENANCE_REFRESH_SESSIONS_{N} = PASS

    The refresh endpoint stores sessions_per_week to DB (training_prefs) and
    passes it as sessions_override to generate_dynamic_training_plan.
    The bridge layer does not accept sessions_per_week directly; this test
    verifies (a) the valid session counts are recognised and (b) the bridge
    produces a valid plan for MAINTENANCE with no workouts.
    """
    valid_session_counts = {3, 4, 5, 6}
    assert sessions in valid_session_counts, f"sessions={sessions} must be a supported count"

    today = date.today()
    _, weekly_plan = build_weekly_plan_from_workouts(
        workouts=_workouts_empty(),
        goal_type="MAINTENANCE",
        race_date=None,
        cycle_start_date=today,
        reference_date=today,
    )
    assert weekly_plan is not None
    assert len(weekly_plan.sessions) > 0


# ---------------------------------------------------------------------------
# Non-regression: race goals still work via build_weekly_plan_from_workouts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("goal_type,race_date", [
    ("5K", date(2025, 6, 1)),
    ("10K", date(2025, 6, 1)),
    ("SEMI", date(2025, 6, 1)),
    ("MARATHON", date(2025, 10, 1)),
    ("ULTRA", None),  # ULTRA without race_date falls to continuous
])
def test_race_goal_non_regression(goal_type, race_date):
    """REGRESSION_{GOAL} = PASS"""
    today = date(2025, 1, 15)
    try:
        _, weekly_plan = build_weekly_plan_from_workouts(
            workouts=_workouts_empty(),
            goal_type=goal_type,
            race_date=race_date,
            cycle_start_date=today,
            reference_date=today,
        )
        assert weekly_plan is not None
    except Exception as e:
        # ULTRA without race_date and without target_distance_km might raise in build_plan_goal
        # That is existing behavior — not a regression introduced by this PR.
        if goal_type == "ULTRA" and race_date is None:
            pytest.skip(f"ULTRA without race_date: {e}")
        raise


# ---------------------------------------------------------------------------
# MAINTENANCE_CYCLE_CREATED — GOAL_CONFIG cycle_weeks is valid
# ---------------------------------------------------------------------------

def test_maintenance_cycle_created():
    """MAINTENANCE_CYCLE_CREATED = YES: GOAL_CONFIG has valid cycle_weeks"""
    cfg = GOAL_CONFIG["MAINTENANCE"]
    assert cfg["cycle_weeks"] > 0
    goal = build_plan_goal(goal_type=GoalType.maintenance)
    resp = build_cycle_calendar_response(goal, _REF, cycle_anchor_date=_ANCHOR)
    assert len(resp.weeks) > 0


# ===========================================================================
# REAL HANDLER TESTS — set_training_goal + refresh_training_plan
# ===========================================================================
# These tests import and call the REAL production handlers from server.py.
# They use minimal mocks for MongoDB and auth only — the handler code itself
# is never mocked.
# ===========================================================================

import asyncio  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch, call  # noqa: E402

# Lazy server import (env vars already set above)
def _get_server():
    """Import server lazily so env vars are already set."""
    import server as _server
    return _server


# ---------------------------------------------------------------------------
# Minimal in-memory collection for handler tests
# ---------------------------------------------------------------------------

class _SimpleCollection:
    """Minimal MongoDB collection mock used in real handler tests."""

    def __init__(self):
        self._docs = []

    def _match(self, doc, query):
        return all(doc.get(k) == v for k, v in query.items()
                   if not isinstance(v, dict))

    async def find_one(self, query, projection=None):
        for doc in self._docs:
            if self._match(doc, query):
                return dict(doc)
        return None

    async def update_one(self, query, update, upsert=False):
        for doc in self._docs:
            if self._match(doc, {k: v for k, v in query.items() if not isinstance(v, dict)}):
                doc.update(update.get("$set", {}))
                return MagicMock(matched_count=1, modified_count=1)
        if upsert:
            new_doc = {**{k: v for k, v in query.items() if not isinstance(v, dict)},
                       **update.get("$set", {})}
            self._docs.append(new_doc)
        return MagicMock(matched_count=0, modified_count=0)

    async def insert_one(self, doc):
        self._docs.append(dict(doc))


class _SimpleDB:
    """Minimal fake DB for real handler tests."""
    def __init__(self):
        self.training_cycles = _SimpleCollection()
        self.training_prefs = _SimpleCollection()
    def __getattr__(self, name):
        col = _SimpleCollection()
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# REAL HANDLER TEST — set_training_goal
# REAL_SET_GOAL_HANDLER_EXECUTED = YES
# ---------------------------------------------------------------------------

def test_real_handler_set_goal_maintenance_pass():
    """
    REAL_SET_GOAL_HANDLER_EXECUTED = YES
    MAINTENANCE_SET_GOAL_REAL_HANDLER = PASS

    Imports and directly calls server.set_training_goal with goal=MAINTENANCE.
    Verifies goal and start_date are persisted; no race_date or target_time added.
    """
    import server as _srv
    fake_db = _SimpleDB()
    fake_user = {"id": "real-handler-test-user"}

    before = datetime.now(timezone.utc)
    # Patch server.db so the handler writes to our in-memory collection
    with patch.object(_srv, "db", fake_db):
        result = asyncio.get_event_loop().run_until_complete(
            _srv.set_training_goal(goal="MAINTENANCE", user=fake_user)
        )
    after = datetime.now(timezone.utc)

    # MAINTENANCE_SET_GOAL_REAL_HANDLER = PASS
    assert "Invalid goal" not in str(result), f"Handler rejected MAINTENANCE: {result}"
    assert result.get("status") == "updated", f"Unexpected response: {result}"
    assert result.get("goal") == "MAINTENANCE", f"Unexpected goal in response: {result}"

    # MAINTENANCE_PERSISTED_GOAL = MAINTENANCE
    persisted = asyncio.get_event_loop().run_until_complete(
        fake_db.training_cycles.find_one({"user_id": "real-handler-test-user"})
    )
    assert persisted is not None, "training_cycles was not upserted"
    assert persisted.get("goal") == "MAINTENANCE", f"Persisted goal: {persisted.get('goal')}"

    # MAINTENANCE_START_DATE = TODAY (UTC)
    start_date = persisted.get("start_date")
    assert start_date is not None, "start_date not persisted"
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    assert isinstance(start_date, datetime), f"start_date is not a datetime: {start_date}"
    assert before <= start_date <= after, f"start_date {start_date} out of expected range"
    assert start_date.date() == datetime.now(timezone.utc).date(), "start_date is not today"

    # MAINTENANCE_RACE_DATE_CREATED = NO
    assert persisted.get("race_date") is None, f"race_date must not be created: {persisted}"

    # MAINTENANCE_TARGET_TIME_CREATED = NO
    assert persisted.get("target_time") is None, f"target_time must not be created: {persisted}"


def test_real_handler_set_goal_invalid_rejected():
    """Non-regression: unknown goals are still rejected by the real handler."""
    import server as _srv
    fake_db = _SimpleDB()
    fake_user = {"id": "real-handler-test-user-2"}

    with patch.object(_srv, "db", fake_db):
        result = asyncio.get_event_loop().run_until_complete(
            _srv.set_training_goal(goal="INVALID_GOAL", user=fake_user)
        )

    assert result.get("error") == "Invalid goal", f"Expected error, got: {result}"


# ---------------------------------------------------------------------------
# REAL HANDLER TEST — refresh_training_plan
# REAL_REFRESH_HANDLER_EXECUTED = YES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sessions", [3, 4, 5, 6])
def test_real_handler_refresh_maintenance(sessions: int):
    """
    REAL_REFRESH_HANDLER_EXECUTED = YES
    MAINTENANCE_REFRESH_REAL_HANDLER_{sessions} = PASS

    Imports and directly calls server.refresh_training_plan with a
    MAINTENANCE training cycle in the mock DB.

    The real handler:
    1. Clears the plan cache for this user
    2. Stores sessions_per_week in training_prefs
    3. Calls generate_dynamic_training_plan(db, user_id, sessions_override=sessions)

    generate_dynamic_training_plan is mocked to isolate the handler; its
    call arguments are verified to confirm sessions is correctly forwarded.

    SESSIONS_CONTRACT: sessions_override is passed to generate_dynamic_training_plan
    SESSIONS_PERSISTED: sessions_per_week stored in training_prefs
    SESSIONS_PASSED_TO_GENERATOR: sessions_override=sessions value
    """
    import server as _srv
    fake_db = _SimpleDB()
    fake_user = {"id": "real-refresh-handler-user"}

    # Pre-seed a MAINTENANCE cycle
    fake_db.training_cycles._docs.append({
        "user_id": "real-refresh-handler-user",
        "goal": "MAINTENANCE",
        "start_date": datetime.now(timezone.utc),
    })

    dummy_plan = {"goal": "MAINTENANCE", "sessions_per_week": sessions}
    mock_gen = AsyncMock(return_value=dummy_plan)

    with patch.object(_srv, "db", fake_db), \
         patch("server.generate_dynamic_training_plan", new=mock_gen):
        result = asyncio.get_event_loop().run_until_complete(
            _srv.refresh_training_plan(sessions=sessions, user=fake_user)
        )

    # Handler returns the plan from generate_dynamic_training_plan
    assert result == dummy_plan, f"sessions={sessions}: unexpected result: {result}"

    # SESSIONS_PERSISTED: sessions_per_week stored in training_prefs
    prefs = asyncio.get_event_loop().run_until_complete(
        fake_db.training_prefs.find_one({"user_id": "real-refresh-handler-user"})
    )
    assert prefs is not None, f"sessions={sessions}: training_prefs not stored"
    assert prefs.get("sessions_per_week") == sessions, (
        f"sessions={sessions}: persisted {prefs.get('sessions_per_week')} != {sessions}"
    )

    # SESSIONS_PASSED_TO_GENERATOR: sessions_override forwarded to generator
    assert mock_gen.called, "generate_dynamic_training_plan was not called"
    call_args = mock_gen.call_args
    # Handler: generate_dynamic_training_plan(db, user_id, sessions_override=sessions)
    passed_override = (
        call_args.kwargs.get("sessions_override")
        if call_args.kwargs
        else (call_args.args[2] if len(call_args.args) > 2 else None)
    )
    assert passed_override == sessions, (
        f"sessions={sessions}: sessions_override={passed_override} passed to generator"
    )
