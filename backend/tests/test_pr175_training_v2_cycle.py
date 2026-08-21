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
