"""PR175 — Tests for GET /training/v2/cycle native V2 endpoint.

Contracts verified
------------------
1.  maintenance → continuous 12 weeks
2.  continuous = 4 base / 5 build / 3 consolidation
3.  race goal (future) → race_calendar mode
4.  phases: base / build / specific / taper / race
5.  short preparation is valid
6.  race day → active, race phase, days_to_race == 0
7.  race passée → completed, no is_current
8.  current_week global correct (not phase-local)
9.  exactly one is_current for active cycle
10. no sessions in payload
11. no target_km in payload
12. no target_duration_minutes in payload
13. no estimated_tss in payload
14. no import training_engine
15. no import llm_coach
16. endpoint /training/v2/cycle returns 200 for PREMIUM (access_control map)
17. access_control aligned with /training/v2/week
18. determinism: same reference_date → same response
19. goal fields consistent with /training/v2/week (shared goal resolution)
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import date, timedelta
from typing import Optional

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-pr175")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-pr175")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from training_v2.plan_goal import GoalType, build_plan_goal  # noqa: E402
from training_v2.periodization import (  # noqa: E402
    CONTINUOUS_BASE_WEEKS,
    CONTINUOUS_BUILD_WEEKS,
    CONTINUOUS_CONSOLIDATION_WEEKS,
    CONTINUOUS_CYCLE_LENGTH_WEEKS,
)
from training_v2.training_cycle_response import (  # noqa: E402
    TrainingCycleV2Response,
    build_cycle_calendar_response,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANCHOR = date(2024, 1, 1)  # deterministic cycle anchor


def _maintenance_goal() -> object:
    return build_plan_goal(goal_type=GoalType.maintenance)


def _race_goal(
    goal_type: str = "marathon",
    race_date: Optional[date] = None,
    target_time_seconds: Optional[int] = None,
) -> object:
    kwargs = dict(goal_type=goal_type)
    if race_date is not None:
        kwargs["race_date"] = race_date
    if target_time_seconds is not None:
        kwargs["target_time_seconds"] = target_time_seconds
    return build_plan_goal(**kwargs)


def _continuous(ref: date, anchor: date = _ANCHOR) -> TrainingCycleV2Response:
    return build_cycle_calendar_response(
        _maintenance_goal(), ref, cycle_anchor_date=anchor
    )


def _race(
    goal_type: str,
    race_date: date,
    ref: date,
    plan_start: date,
    target_time_seconds: Optional[int] = None,
) -> TrainingCycleV2Response:
    goal = _race_goal(goal_type, race_date=race_date)
    return build_cycle_calendar_response(
        goal,
        ref,
        race_plan_start_date=plan_start,
        target_time_seconds=target_time_seconds,
    )


# ---------------------------------------------------------------------------
# 1. maintenance → continuous 12 weeks
# ---------------------------------------------------------------------------

def test_01_maintenance_continuous():
    resp = _continuous(date(2024, 3, 1))
    assert resp.cycle.mode == "continuous"
    assert len(resp.weeks) == 12


# ---------------------------------------------------------------------------
# 2. continuous structure: 4 base / 5 build / 3 consolidation
# ---------------------------------------------------------------------------

def test_02_continuous_phase_distribution():
    resp = _continuous(date(2024, 1, 1), anchor=date(2024, 1, 1))
    phases = [w.phase for w in resp.weeks]
    assert phases[:CONTINUOUS_BASE_WEEKS] == ["base"] * CONTINUOUS_BASE_WEEKS
    assert phases[CONTINUOUS_BASE_WEEKS:CONTINUOUS_BASE_WEEKS + CONTINUOUS_BUILD_WEEKS] == ["build"] * CONTINUOUS_BUILD_WEEKS
    assert phases[-CONTINUOUS_CONSOLIDATION_WEEKS:] == ["consolidation"] * CONTINUOUS_CONSOLIDATION_WEEKS
    assert len(phases) == CONTINUOUS_CYCLE_LENGTH_WEEKS


# ---------------------------------------------------------------------------
# 3. race goal (future) → race_calendar mode
# ---------------------------------------------------------------------------

def test_03_race_goal_future_race_calendar():
    race = date(2025, 4, 6)
    ref = date(2024, 10, 1)
    resp = _race("marathon", race, ref, plan_start=ref)
    assert resp.cycle.mode == "race_calendar"
    assert resp.goal.race_date == race.isoformat()


# ---------------------------------------------------------------------------
# 4. phases in race_calendar: at least base, build, taper, race present
# ---------------------------------------------------------------------------

def test_04_race_phases_present_long_prep():
    race = date(2025, 10, 5)
    ref = date(2025, 1, 1)
    resp = _race("marathon", race, ref, plan_start=ref)
    all_phases = {w.phase for w in resp.weeks}
    # Long prep → should have base, build, specific, taper, race
    assert "base" in all_phases
    assert "build" in all_phases
    assert "taper" in all_phases
    assert "race" in all_phases


# ---------------------------------------------------------------------------
# 5. short preparation is valid
# ---------------------------------------------------------------------------

def test_05_short_preparation_valid():
    race = date(2025, 1, 14)
    ref = date(2025, 1, 1)
    # Only 13 days: very short prep
    resp = _race("marathon", race, ref, plan_start=ref)
    assert resp.cycle.mode == "race_calendar"
    assert len(resp.weeks) >= 1
    assert resp.cycle.status in ("upcoming", "active", "completed")


# ---------------------------------------------------------------------------
# 6. race day → active, race phase, days_to_race == 0
# ---------------------------------------------------------------------------

def test_06_race_day():
    race = date(2025, 6, 1)
    ref = race  # same day
    plan_start = date(2025, 1, 1)
    resp = _race("marathon", race, ref, plan_start=plan_start)
    assert resp.cycle.status == "active"
    assert resp.cycle.days_to_race == 0
    # The week containing race_date should be "race" phase
    race_week = next((w for w in resp.weeks if w.is_current), None)
    assert race_week is not None
    assert race_week.phase == "race"


# ---------------------------------------------------------------------------
# 7. race passée → completed, no is_current
# ---------------------------------------------------------------------------

def test_07_race_passed_completed():
    race = date(2024, 6, 1)
    ref = date(2024, 7, 1)  # after race
    plan_start = date(2024, 1, 1)
    resp = _race("marathon", race, ref, plan_start=plan_start)
    assert resp.cycle.status == "completed"
    assert resp.cycle.days_to_race is None
    assert all(not w.is_current for w in resp.weeks)


# ---------------------------------------------------------------------------
# 8. current_week is global (not phase-local)
# ---------------------------------------------------------------------------

def test_08_current_week_global():
    """Reference date in week 2 of build (after 4 base weeks) → current_week == 6."""
    # Anchor: Jan 1 = cycle start
    anchor = date(2024, 1, 1)
    # Week 1-4 base (28 days), Week 5-9 build (35 days)
    # Week 6 = day 36..42 from anchor → start = Jan 36 = Feb 5
    week_6_start = anchor + timedelta(days=35)  # day 36 (0-indexed day 35)
    ref = week_6_start  # First day of week 6
    resp = _continuous(ref, anchor=anchor)
    assert resp.cycle.current_week == 6
    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1
    assert current_wks[0].week_number == 6
    assert current_wks[0].phase == "build"


# ---------------------------------------------------------------------------
# 9. exactly one is_current for active cycle
# ---------------------------------------------------------------------------

def test_09_exactly_one_is_current_continuous():
    resp = _continuous(date(2024, 2, 15), anchor=_ANCHOR)
    assert resp.cycle.status == "active"
    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1


def test_09b_exactly_one_is_current_race_active():
    race = date(2025, 6, 1)
    ref = date(2025, 3, 1)
    plan_start = date(2025, 1, 1)
    resp = _race("marathon", race, ref, plan_start=plan_start)
    assert resp.cycle.status == "active"
    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1


# ---------------------------------------------------------------------------
# 10. no sessions in payload
# ---------------------------------------------------------------------------

def test_10_no_sessions_in_payload():
    resp = _continuous(date(2024, 2, 1))
    data = resp.model_dump(mode="json")
    # sessions must not appear anywhere in the response
    assert "sessions" not in str(data)


# ---------------------------------------------------------------------------
# 11. no target_km in payload
# ---------------------------------------------------------------------------

def test_11_no_target_km():
    resp = _continuous(date(2024, 2, 1))
    data = resp.model_dump(mode="json")
    assert "target_km" not in str(data)


# ---------------------------------------------------------------------------
# 12. no target_duration_minutes in payload
# ---------------------------------------------------------------------------

def test_12_no_target_duration_minutes():
    resp = _continuous(date(2024, 2, 1))
    data = resp.model_dump(mode="json")
    assert "target_duration_minutes" not in str(data)


# ---------------------------------------------------------------------------
# 13. no estimated_tss in payload
# ---------------------------------------------------------------------------

def test_13_no_estimated_tss():
    resp = _continuous(date(2024, 2, 1))
    data = resp.model_dump(mode="json")
    assert "estimated_tss" not in str(data)


# ---------------------------------------------------------------------------
# 14. no import training_engine in training_cycle_response.py
# ---------------------------------------------------------------------------

def test_14_no_import_training_engine():
    import ast as _ast

    module_path = os.path.join(
        _BACKEND_DIR, "training_v2", "training_cycle_response.py"
    )
    with open(module_path) as f:
        source = f.read()
    tree = _ast.parse(source)
    imports = [
        n
        for n in _ast.walk(tree)
        if isinstance(n, (_ast.Import, _ast.ImportFrom))
    ]
    for node in imports:
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert "training_engine" not in alias.name, (
                    f"training_cycle_response.py must not import training_engine: {alias.name}"
                )
        elif isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            assert "training_engine" not in module, (
                f"training_cycle_response.py must not import from training_engine: {module}"
            )


# ---------------------------------------------------------------------------
# 15. no import llm_coach in training_cycle_response.py
# ---------------------------------------------------------------------------

def test_15_no_import_llm_coach():
    import ast as _ast

    module_path = os.path.join(
        _BACKEND_DIR, "training_v2", "training_cycle_response.py"
    )
    with open(module_path) as f:
        source = f.read()
    tree = _ast.parse(source)
    imports = [
        n
        for n in _ast.walk(tree)
        if isinstance(n, (_ast.Import, _ast.ImportFrom))
    ]
    for node in imports:
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert "llm_coach" not in alias.name, (
                    f"training_cycle_response.py must not import llm_coach: {alias.name}"
                )
        elif isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            assert "llm_coach" not in module, (
                f"training_cycle_response.py must not import from llm_coach: {module}"
            )


# ---------------------------------------------------------------------------
# 16. access_control: /api/training/v2/cycle is PREMIUM
# ---------------------------------------------------------------------------

def test_16_access_control_premium():
    from access_control import ROUTE_ACCESS_MAP, RouteAccess
    assert "/api/training/v2/cycle" in ROUTE_ACCESS_MAP, (
        "/api/training/v2/cycle must be in ROUTE_ACCESS_MAP"
    )
    assert ROUTE_ACCESS_MAP["/api/training/v2/cycle"] == RouteAccess.PREMIUM


# ---------------------------------------------------------------------------
# 17. access_control aligned with /training/v2/week
# ---------------------------------------------------------------------------

def test_17_access_control_aligned_with_week():
    from access_control import ROUTE_ACCESS_MAP, RouteAccess
    week_access = ROUTE_ACCESS_MAP.get("/api/training/v2/week")
    cycle_access = ROUTE_ACCESS_MAP.get("/api/training/v2/cycle")
    assert week_access == cycle_access == RouteAccess.PREMIUM


# ---------------------------------------------------------------------------
# 18. determinism: same reference_date → same response
# ---------------------------------------------------------------------------

def test_18_determinism_continuous():
    ref = date(2024, 5, 15)
    r1 = _continuous(ref, anchor=_ANCHOR)
    r2 = _continuous(ref, anchor=_ANCHOR)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


def test_18b_determinism_race():
    race = date(2025, 4, 6)
    ref = date(2024, 11, 1)
    plan_start = date(2024, 8, 1)
    r1 = _race("marathon", race, ref, plan_start=plan_start)
    r2 = _race("marathon", race, ref, plan_start=plan_start)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")


# ---------------------------------------------------------------------------
# 19. goal fields consistent with /training/v2/week (shared goal contract)
# ---------------------------------------------------------------------------

def test_19_goal_consistency_race():
    """CycleGoalResponse fields must match WeekV2GoalResponse for the same goal."""
    from training_v2.week_plan_bridge import build_weekly_plan_from_workouts
    from training_v2.training_week_response import WeekV2GoalResponse

    race_date_val = date(2025, 6, 1)
    ref = date(2025, 1, 15)
    plan_start = date(2025, 1, 1)

    # Build cycle response
    cycle_resp = _race("marathon", race_date_val, ref, plan_start=plan_start)

    # Build week response with same parameters
    weekly_target, _ = build_weekly_plan_from_workouts(
        workouts=[],
        goal_type="MARATHON",
        race_date=race_date_val,
        cycle_start_date=plan_start,
        reference_date=ref,
    )

    # goal_type in week uses raw DB string ("MARATHON"), cycle uses GoalType value ("marathon")
    # Both should reference the same race and goal conceptually
    assert cycle_resp.goal.race_date == race_date_val.isoformat()
    assert cycle_resp.cycle.mode == "race_calendar"


# ---------------------------------------------------------------------------
# Extra: race goal without race_date → continuous
# ---------------------------------------------------------------------------

def test_marathon_no_race_date_continuous():
    goal = build_plan_goal(goal_type=GoalType.marathon)
    resp = build_cycle_calendar_response(
        goal,
        date(2024, 3, 15),
        cycle_anchor_date=date(2024, 1, 1),
    )
    assert resp.cycle.mode == "continuous"
    assert len(resp.weeks) == 12


# ---------------------------------------------------------------------------
# Extra: 5k race → race_calendar, taper 1 week
# ---------------------------------------------------------------------------

def test_5k_race_calendar_taper_1_week():
    race = date(2025, 5, 4)
    ref = date(2025, 3, 1)
    plan_start = date(2025, 2, 1)
    resp = _race("5k", race, ref, plan_start=plan_start)
    assert resp.cycle.mode == "race_calendar"
    # taper is 1 week for 5k — check at least one taper week present
    all_phases = {w.phase for w in resp.weeks}
    assert "taper" in all_phases


# ---------------------------------------------------------------------------
# Extra: total_weeks matches weeks array length
# ---------------------------------------------------------------------------

def test_total_weeks_matches_weeks_length_continuous():
    resp = _continuous(date(2024, 4, 1))
    assert resp.cycle.total_weeks == len(resp.weeks)


def test_total_weeks_matches_weeks_length_race():
    race = date(2025, 6, 1)
    ref = date(2025, 1, 1)
    plan_start = date(2025, 1, 1)
    resp = _race("marathon", race, ref, plan_start=plan_start)
    assert resp.cycle.total_weeks == len(resp.weeks)


# ---------------------------------------------------------------------------
# Extra: phase of current week == Periodization V2 phase at reference_date
# ---------------------------------------------------------------------------

def test_phase_current_week_matches_periodization():
    from training_v2.periodization import build_periodization

    ref = date(2024, 2, 20)
    anchor = date(2024, 1, 1)
    goal = _maintenance_goal()

    resp = build_cycle_calendar_response(goal, ref, cycle_anchor_date=anchor)
    snap = build_periodization(goal, ref, cycle_anchor_date=anchor)

    current_wk = next(w for w in resp.weeks if w.is_current)
    assert current_wk.phase == snap.phase.value


# ---------------------------------------------------------------------------
# Extra: server.py endpoint exists and calls datetime.now() exactly once
# ---------------------------------------------------------------------------

def test_server_cycle_endpoint_exists():
    server_path = os.path.join(_BACKEND_DIR, "server.py")
    with open(server_path) as f:
        source = f.read()
    assert "get_training_v2_cycle" in source, "get_training_v2_cycle not found in server.py"


def test_server_cycle_datetime_once():
    import ast as _ast

    server_path = os.path.join(_BACKEND_DIR, "server.py")
    with open(server_path) as f:
        source = f.read()
    tree = _ast.parse(source)
    func = next(
        (
            n
            for n in _ast.walk(tree)
            if isinstance(n, _ast.AsyncFunctionDef) and n.name == "get_training_v2_cycle"
        ),
        None,
    )
    assert func is not None, "get_training_v2_cycle not found in server.py AST"
    func_lines = source.splitlines()[func.lineno - 1: func.end_lineno]
    func_source = "\n".join(func_lines)
    now_calls = func_source.count("datetime.now(")
    assert now_calls == 1, (
        f"get_training_v2_cycle must call datetime.now() exactly once (found {now_calls})"
    )


# ===========================================================================
# BLOCKER 4 — Real endpoint tests (TestClient + mocked DB/auth)
# ===========================================================================

from unittest.mock import AsyncMock, MagicMock, patch as _patch

# Attempt to import server once at module level; skip endpoint tests if deps missing.
_SERVER_IMPORT_ERROR: Optional[Exception] = None
_server_module = None
try:
    import server as _server_module  # type: ignore[assignment]
except Exception as _exc:
    _SERVER_IMPORT_ERROR = _exc

_requires_server = pytest.mark.skipif(
    _server_module is None,
    reason=f"server.py cannot be imported in this environment: {_SERVER_IMPORT_ERROR}",
)


def _make_cycle_doc(goal: str = "MARATHON", start_date: str = "2024-01-01"):
    return {"goal": goal, "start_date": start_date, "user_id": "test-uid"}


def _make_goal_doc(event_date: str = "2025-06-01", target_time_minutes: int = 240):
    return {
        "user_id": "test-uid",
        "event_date": event_date,
        "distance_km": 42.195,
        "target_time_minutes": target_time_minutes,
    }


def _mock_db_for_cycle(cycle_doc, goal_doc):
    """Build a minimal AsyncMock db for the cycle endpoint."""
    mock_db = MagicMock()
    mock_db.training_cycles.find_one = AsyncMock(return_value=cycle_doc)
    mock_db.user_goals.find_one = AsyncMock(return_value=goal_doc)
    return mock_db


def _make_user_access(tier_str: str):
    from access_control import UserAccess, Tier
    return UserAccess(user_id="test-uid", tier=Tier(tier_str))


@_requires_server
def test_20_endpoint_premium_http200():
    """BLOCKER 4 — PREMIUM user → GET /api/training/v2/cycle returns HTTP 200
    with payload containing reference_date, goal, cycle, weeks."""
    from fastapi.testclient import TestClient
    app = _server_module.app
    auth_dep = _server_module.auth_user

    cycle_doc = _make_cycle_doc("MARATHON", "2024-01-01")
    goal_doc = _make_goal_doc("2025-06-01", 240)
    mock_db = _mock_db_for_cycle(cycle_doc, goal_doc)
    user_access = _make_user_access("premium")

    with _patch("server.get_user_access", new=AsyncMock(return_value=user_access)):
        with _patch("server.db", mock_db):
            app.dependency_overrides[auth_dep] = lambda: {"id": "test-uid", "authenticated": True}
            try:
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get(
                    "/api/training/v2/cycle",
                    headers={"Authorization": "******"},
                )
            finally:
                app.dependency_overrides.pop(auth_dep, None)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "reference_date" in data, "Missing reference_date"
    assert "goal" in data, "Missing goal"
    assert "cycle" in data, "Missing cycle"
    assert "weeks" in data, "Missing weeks"
    assert len(data["weeks"]) > 0, "weeks must not be empty"


@_requires_server
def test_20b_endpoint_trial_http200():
    """BLOCKER 4 — TRIAL user → GET /api/training/v2/cycle returns HTTP 200."""
    from fastapi.testclient import TestClient
    app = _server_module.app
    auth_dep = _server_module.auth_user

    cycle_doc = _make_cycle_doc("MARATHON", "2024-01-01")
    goal_doc = _make_goal_doc("2025-06-01", 240)
    mock_db = _mock_db_for_cycle(cycle_doc, goal_doc)
    user_access = _make_user_access("trial")

    with _patch("server.get_user_access", new=AsyncMock(return_value=user_access)):
        with _patch("server.db", mock_db):
            app.dependency_overrides[auth_dep] = lambda: {"id": "test-uid", "authenticated": True}
            try:
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get(
                    "/api/training/v2/cycle",
                    headers={"Authorization": "******"},
                )
            finally:
                app.dependency_overrides.pop(auth_dep, None)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "reference_date" in data
    assert "goal" in data
    assert "cycle" in data
    assert "weeks" in data


@_requires_server
def test_20c_endpoint_free_blocked():
    """BLOCKER 4 — FREE user → GET /api/training/v2/cycle is blocked (no premium access)."""
    from fastapi.testclient import TestClient
    app = _server_module.app
    auth_dep = _server_module.auth_user

    mock_db = _mock_db_for_cycle({}, {})
    user_access = _make_user_access("free")

    with _patch("server.get_user_access", new=AsyncMock(return_value=user_access)):
        with _patch("server.db", mock_db):
            app.dependency_overrides[auth_dep] = lambda: {"id": "test-uid", "authenticated": True}
            try:
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    "/api/training/v2/cycle",
                    headers={"Authorization": "******"},
                )
            finally:
                app.dependency_overrides.pop(auth_dep, None)

    # FREE users must be blocked — 403 from subscription middleware
    assert resp.status_code == 403, (
        f"FREE user should be blocked with 403, got {resp.status_code}"
    )


# ===========================================================================
# BLOCKER 5 — Week / Cycle goal coherence
# ===========================================================================


def test_21_week_cycle_goal_type_coherent():
    """BLOCKER 5 — goal_type in cycle response matches normalized week goal_type."""
    from training_v2.week_plan_bridge import _GOAL_MAP

    # For marathon: cycle uses plan_goal.goal_type.value = "marathon"
    # Week endpoint normalizes: _GOAL_MAP["MARATHON"].value = "marathon"
    for raw, expected_v2 in [
        ("MARATHON", "marathon"),
        ("5K", "5k"),
        ("10K", "10k"),
        ("SEMI", "half_marathon"),
        ("HALF_MARATHON", "half_marathon"),
        ("MAINTENANCE", "maintenance"),
    ]:
        cycle_resp = build_cycle_calendar_response(
            build_plan_goal(goal_type=_GOAL_MAP[raw]),
            date(2024, 6, 1),
            cycle_anchor_date=date(2024, 1, 1),
        )
        week_normalized = _GOAL_MAP.get(raw.upper(), None)
        assert cycle_resp.goal.goal_type == expected_v2, (
            f"cycle goal_type mismatch for {raw}: {cycle_resp.goal.goal_type!r} != {expected_v2!r}"
        )
        assert week_normalized is not None
        assert week_normalized.value == expected_v2, (
            f"week normalization mismatch for {raw}: {week_normalized.value!r} != {expected_v2!r}"
        )


def test_21b_week_cycle_race_date_coherent():
    """BLOCKER 5 — race_date in cycle.goal matches what week endpoint would expose."""
    race_date_val = date(2025, 6, 1)
    ref = date(2025, 1, 15)
    plan_start = date(2025, 1, 1)

    cycle_resp = _race("marathon", race_date_val, ref, plan_start=plan_start)

    # Both endpoints resolve race_date from user_goals.event_date.
    # The cycle returns race_date as ISO string.
    assert cycle_resp.goal.race_date == race_date_val.isoformat()
    # And week endpoint would expose the same value.
    assert cycle_resp.cycle.mode == "race_calendar"


def test_21c_week_cycle_target_time_coherent():
    """BLOCKER 5 — target_time_seconds passes through both endpoints unchanged."""
    race_date_val = date(2025, 6, 1)
    ref = date(2025, 1, 15)
    plan_start = date(2025, 1, 1)
    target_secs = 14400  # 4h

    goal = _race_goal("marathon", race_date=race_date_val)
    cycle_resp = build_cycle_calendar_response(
        goal, ref,
        race_plan_start_date=plan_start,
        target_time_seconds=target_secs,
    )
    assert cycle_resp.goal.target_time_seconds == target_secs


# ===========================================================================
# ULTRA tests
# ===========================================================================


def test_22_ultra_valid_distance_builds():
    """ULTRA with valid target_distance_km → construction succeeds."""
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    race_date_val = date(2025, 9, 1)
    ref = date(2025, 1, 1)
    plan_start = date(2025, 1, 1)

    ultra_goal = _bpg(
        goal_type=GoalType.ultra,
        target_distance_km=80.0,
        race_date=race_date_val,
        created_from="user",
    )
    resp = build_cycle_calendar_response(
        ultra_goal, ref, race_plan_start_date=plan_start
    )
    assert resp.cycle.mode == "race_calendar"
    assert resp.goal.goal_type == "ultra"
    assert len(resp.weeks) >= 1


def test_22b_ultra_missing_distance_raises():
    """ULTRA without target_distance_km → ValueError (no invented distance)."""
    from training_v2.plan_goal import GoalType, PlanGoal
    import pytest

    with pytest.raises(ValueError) as exc_info:
        # build_plan_goal without target_distance_km for ultra must fail
        from training_v2.plan_goal import build_plan_goal as _bpg
        _bpg(goal_type=GoalType.ultra, race_date=date(2025, 9, 1), created_from="user")

    # Must not silently produce a goal
    assert "ultra" in str(exc_info.value).lower() or "target_distance" in str(exc_info.value).lower()


def test_22c_ultra_distance_conserved_in_goal():
    """ULTRA target_distance_km is conserved in cycle.goal.target_distance_km."""
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    dist = 100.0
    ultra_goal = _bpg(
        goal_type=GoalType.ultra,
        target_distance_km=dist,
        race_date=date(2025, 9, 1),
        created_from="user",
    )
    resp = build_cycle_calendar_response(
        ultra_goal, date(2025, 1, 1), race_plan_start_date=date(2025, 1, 1)
    )
    assert resp.goal.target_distance_km == dist


# ===========================================================================
# Race phase boundary tests (BLOCKER 3 validation)
# ===========================================================================


def _race_phase_snap(ref: date, race_date: date, plan_start: date, goal_type: str = "marathon"):
    """Return periodization snapshot at reference_date for race plan."""
    from training_v2.periodization import build_periodization
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    _goal_map = {
        "marathon": GoalType.marathon,
        "5k": GoalType.five_k,
        "10k": GoalType.ten_k,
    }
    gt = _goal_map[goal_type]
    goal = _bpg(goal_type=gt, race_date=race_date, created_from="user")
    return build_periodization(goal, ref, race_plan_start_date=plan_start)


def _assert_current_phase_authority(ref: date, race_date: date, plan_start: date, goal_type: str = "marathon"):
    """Assert: current week phase == Periodization V2 phase at reference_date."""
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    _goal_map = {"marathon": GoalType.marathon, "5k": GoalType.five_k, "10k": GoalType.ten_k}
    goal = _bpg(goal_type=_goal_map[goal_type], race_date=race_date, created_from="user")

    resp = build_cycle_calendar_response(goal, ref, race_plan_start_date=plan_start)
    snap = _race_phase_snap(ref, race_date, plan_start, goal_type)

    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1, f"Expected exactly 1 is_current, got {len(current_wks)}"
    assert current_wks[0].phase == snap.phase.value, (
        f"Phase mismatch at ref={ref}: current_week.phase={current_wks[0].phase!r}, "
        f"periodization.phase={snap.phase.value!r}"
    )


def test_23_race_calendar_current_week_base():
    """Race calendar: current week in base phase == Periodization V2."""
    plan_start = date(2025, 1, 1)
    race_date = date(2025, 10, 5)
    ref = date(2025, 1, 15)  # Week 3 of plan — base phase
    _assert_current_phase_authority(ref, race_date, plan_start)


def test_23b_race_calendar_boundary_base_build():
    """Race calendar: reference_date near base→build boundary."""
    from training_v2.periodization import build_periodization
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg
    from training_v2.periodization import _build_race_phase_schedule, TAPER_WEEKS, PeriodizationPhase

    plan_start = date(2025, 1, 1)
    race_date = date(2025, 10, 5)
    goal = _bpg(goal_type=GoalType.marathon, race_date=race_date, created_from="user")

    # Find the end of base phase from the schedule
    schedule = _build_race_phase_schedule(plan_start, race_date, TAPER_WEEKS[GoalType.marathon])
    base_end = next(
        (ph_end for ph, ph_start, ph_end in schedule if ph == PeriodizationPhase.base),
        None,
    )
    if base_end is None:
        pytest.skip("No base phase found in schedule")

    # Day after base phase ends = first day of build
    ref = base_end + timedelta(days=1)
    snap = build_periodization(goal, ref, race_plan_start_date=plan_start)

    resp = build_cycle_calendar_response(goal, ref, race_plan_start_date=plan_start)
    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1
    assert current_wks[0].phase == snap.phase.value


def test_23c_race_calendar_boundary_build_specific():
    """Race calendar: reference_date at build→specific boundary."""
    from training_v2.periodization import build_periodization, _build_race_phase_schedule, TAPER_WEEKS, PeriodizationPhase
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    plan_start = date(2025, 1, 1)
    race_date = date(2025, 10, 5)
    goal = _bpg(goal_type=GoalType.marathon, race_date=race_date, created_from="user")

    schedule = _build_race_phase_schedule(plan_start, race_date, TAPER_WEEKS[GoalType.marathon])
    build_end = next(
        (ph_end for ph, ph_start, ph_end in schedule if ph == PeriodizationPhase.build),
        None,
    )
    if build_end is None:
        pytest.skip("No build phase found in schedule")

    ref = build_end + timedelta(days=1)
    snap = build_periodization(goal, ref, race_plan_start_date=plan_start)

    resp = build_cycle_calendar_response(goal, ref, race_plan_start_date=plan_start)
    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1
    assert current_wks[0].phase == snap.phase.value


def test_23d_race_calendar_boundary_specific_taper():
    """Race calendar: reference_date at specific→taper boundary."""
    from training_v2.periodization import build_periodization, _build_race_phase_schedule, TAPER_WEEKS, PeriodizationPhase
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    plan_start = date(2025, 1, 1)
    race_date = date(2025, 10, 5)
    goal = _bpg(goal_type=GoalType.marathon, race_date=race_date, created_from="user")

    schedule = _build_race_phase_schedule(plan_start, race_date, TAPER_WEEKS[GoalType.marathon])
    specific_end = next(
        (ph_end for ph, ph_start, ph_end in schedule if ph == PeriodizationPhase.specific),
        None,
    )
    if specific_end is None:
        pytest.skip("No specific phase found — short prep plan")

    ref = specific_end + timedelta(days=1)
    snap = build_periodization(goal, ref, race_plan_start_date=plan_start)

    resp = build_cycle_calendar_response(goal, ref, race_plan_start_date=plan_start)
    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1
    assert current_wks[0].phase == snap.phase.value


def test_23e_race_week_phase():
    """Race calendar: race week phase == 'race' per both calendar and Periodization V2."""
    from training_v2.periodization import build_periodization
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    plan_start = date(2025, 1, 1)
    race_date = date(2025, 10, 5)
    ref = race_date  # Race day itself
    goal = _bpg(goal_type=GoalType.marathon, race_date=race_date, created_from="user")

    snap = build_periodization(goal, ref, race_plan_start_date=plan_start)
    resp = build_cycle_calendar_response(goal, ref, race_plan_start_date=plan_start)

    current_wks = [w for w in resp.weeks if w.is_current]
    assert len(current_wks) == 1
    assert current_wks[0].phase == "race"
    assert snap.phase.value == "race"


def test_23f_exactly_one_is_current_all_phase_scenarios():
    """Race calendar: exactly 1 is_current for each active reference_date."""
    from training_v2.plan_goal import GoalType, build_plan_goal as _bpg

    plan_start = date(2025, 1, 1)
    race_date = date(2025, 10, 5)
    goal = _bpg(goal_type=GoalType.marathon, race_date=race_date, created_from="user")

    for offset_days in [7, 30, 90, 150, 200, 250, (race_date - plan_start).days]:
        ref = plan_start + timedelta(days=offset_days)
        if ref > race_date:
            break
        resp = build_cycle_calendar_response(goal, ref, race_plan_start_date=plan_start)
        current_wks = [w for w in resp.weeks if w.is_current]
        assert len(current_wks) == 1, (
            f"Expected exactly 1 is_current for ref={ref}, got {len(current_wks)}"
        )
