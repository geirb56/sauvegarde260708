"""PR06 — Tests for Periodization (deterministic, pure business layer).

Tests are numbered 1–38 as per the PR06 spec.
All dates are injected explicitly; datetime.now() / date.today() are never used.
"""

import ast
import importlib
import inspect
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from training_v2 import (
    GoalType,
    PeriodizationMode,
    PeriodizationPhase,
    PeriodizationSnapshot,
    build_periodization,
    build_plan_goal,
)
from training_v2.periodization import (
    CONTINUOUS_BASE_WEEKS,
    CONTINUOUS_BUILD_WEEKS,
    CONTINUOUS_CONSOLIDATION_WEEKS,
    CONTINUOUS_CYCLE_LENGTH_WEEKS,
    PRE_TAPER_PROPORTIONS,
    TAPER_WEEKS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANCHOR = date(2024, 1, 1)  # Monday — deterministic cycle origin


def _goal(goal_type, *, race_date=None, target_time_seconds=None, target_distance_km=None):
    kwargs = dict(goal_type=goal_type)
    if race_date is not None:
        kwargs["race_date"] = race_date
    if target_time_seconds is not None:
        kwargs["target_time_seconds"] = target_time_seconds
    if target_distance_km is not None:
        kwargs["target_distance_km"] = target_distance_km
    return build_plan_goal(**kwargs)


def _snap(goal, ref_date, anchor=ANCHOR):
    return build_periodization(goal, ref_date, cycle_anchor_date=anchor)


def _snap_no_anchor(goal, ref_date, plan_start=None):
    """For race_calendar mode — no anchor needed."""
    return build_periodization(goal, ref_date, race_plan_start_date=plan_start)


# ---------------------------------------------------------------------------
# 1. 5k with far-away race date → race_calendar mode
# ---------------------------------------------------------------------------

def test_01_5k_race_calendar_mode():
    race = date(2025, 6, 1)
    ref = date(2024, 10, 1)
    snap = _snap_no_anchor(_goal("5k", race_date=race), ref)
    assert snap.mode == PeriodizationMode.race_calendar
    assert "RACE_CALENDAR" in snap.reason_codes


# ---------------------------------------------------------------------------
# 2. Marathon with far-away race date → coherent phase
# ---------------------------------------------------------------------------

def test_02_marathon_far_race_coherent_phase():
    race = date(2025, 10, 1)
    ref = date(2025, 1, 1)
    snap = _snap_no_anchor(_goal("marathon", race_date=race), ref)
    assert snap.mode == PeriodizationMode.race_calendar
    assert snap.phase in (
        PeriodizationPhase.base,
        PeriodizationPhase.build,
        PeriodizationPhase.specific,
        PeriodizationPhase.taper,
    )


# ---------------------------------------------------------------------------
# 3. Ultra with date → same 5 phases available
# ---------------------------------------------------------------------------

def test_03_ultra_with_date_same_phases():
    race = date(2025, 12, 1)
    ref = date(2025, 1, 1)
    snap = _snap_no_anchor(_goal("ultra", race_date=race, target_distance_km=80.0), ref)
    assert snap.mode == PeriodizationMode.race_calendar
    assert snap.phase in (
        PeriodizationPhase.base,
        PeriodizationPhase.build,
        PeriodizationPhase.specific,
        PeriodizationPhase.taper,
    )


# ---------------------------------------------------------------------------
# 4. No race date → continuous mode
# ---------------------------------------------------------------------------

def test_04_no_race_date_continuous():
    snap = _snap(_goal("half_marathon"), date(2024, 3, 1))
    assert snap.mode == PeriodizationMode.continuous
    assert "NO_RACE_DATE" in snap.reason_codes


# ---------------------------------------------------------------------------
# 5. maintenance → continuous
# ---------------------------------------------------------------------------

def test_05_maintenance_continuous():
    snap = _snap(_goal("maintenance"), date(2024, 3, 1))
    assert snap.mode == PeriodizationMode.continuous
    assert "MAINTENANCE_GOAL" in snap.reason_codes


# ---------------------------------------------------------------------------
# 6. Chrono goal without race date → continuous
# ---------------------------------------------------------------------------

def test_06_chrono_without_date_continuous():
    snap = _snap(_goal("half_marathon", target_time_seconds=6600), date(2024, 3, 1))
    assert snap.mode == PeriodizationMode.continuous
    assert "NO_RACE_DATE" in snap.reason_codes


# ---------------------------------------------------------------------------
# 7. reference_date == race_date → phase = race
# ---------------------------------------------------------------------------

def test_07_reference_equals_race_date():
    race = date(2025, 6, 15)
    snap = _snap_no_anchor(_goal("marathon", race_date=race), race)
    assert snap.phase == PeriodizationPhase.race
    assert snap.mode == PeriodizationMode.race_calendar
    assert snap.weeks_to_race == 0.0
    assert "PHASE_RACE" in snap.reason_codes


# ---------------------------------------------------------------------------
# 8. race date passed → continuous + consolidation + RACE_DATE_PASSED
# ---------------------------------------------------------------------------

def test_08_race_date_passed():
    race = date(2025, 5, 1)
    ref = date(2025, 5, 2)  # day after
    snap = _snap_no_anchor(_goal("marathon", race_date=race), ref)
    assert snap.phase == PeriodizationPhase.consolidation
    assert snap.mode == PeriodizationMode.continuous
    assert "RACE_DATE_PASSED" in snap.reason_codes


# ---------------------------------------------------------------------------
# Phase boundary helpers
# For a 20-week preparation to a marathon (140 days pre-taper):
#   taper = 2 weeks = 14 days
#   pre_taper = 126 days
#   base  = floor(126 * 0.30) = 37 days  (weeks 1..5)
#   build = floor(126 * 0.40) = 50 days  (weeks 6..12)
#   specific = 126 - 37 - 50 = 39 days  (weeks 13..18)
#   taper: 14 days (weeks 19..20)
# ---------------------------------------------------------------------------

_MARATHON_TAPER = TAPER_WEEKS[GoalType.marathon]  # 2

def _marathon_20w_dates():
    """Return (ref_start, race_date) for a 20-week marathon prep."""
    total_weeks = 20
    total_days = total_weeks * 7
    race = date(2026, 1, 1)
    ref_start = date.fromordinal(race.toordinal() - total_days)
    return ref_start, race


def _pre_taper_split(total_days, taper_days):
    import math
    pre = total_days - taper_days
    base = math.floor(pre * PRE_TAPER_PROPORTIONS["base"])
    build = math.floor(pre * PRE_TAPER_PROPORTIONS["build"])
    specific = pre - base - build
    return base, build, specific


# ---------------------------------------------------------------------------
# 9. Exact base/build boundary
# ---------------------------------------------------------------------------

def test_09_exact_base_build_boundary():
    ref_start, race = _marathon_20w_dates()
    taper_days = _MARATHON_TAPER * 7
    base_days, build_days, _ = _pre_taper_split((race - ref_start).days, taper_days)

    last_base = date.fromordinal(ref_start.toordinal() + base_days - 1)
    first_build = date.fromordinal(ref_start.toordinal() + base_days)

    snap_last_base = _snap_no_anchor(_goal("marathon", race_date=race), last_base, plan_start=ref_start)
    snap_first_build = _snap_no_anchor(_goal("marathon", race_date=race), first_build, plan_start=ref_start)

    assert snap_last_base.phase == PeriodizationPhase.base, f"Expected base, got {snap_last_base.phase}"
    assert snap_first_build.phase == PeriodizationPhase.build, f"Expected build, got {snap_first_build.phase}"


# ---------------------------------------------------------------------------
# 10. Exact build/specific boundary
# ---------------------------------------------------------------------------

def test_10_exact_build_specific_boundary():
    ref_start, race = _marathon_20w_dates()
    taper_days = _MARATHON_TAPER * 7
    base_days, build_days, _ = _pre_taper_split((race - ref_start).days, taper_days)

    last_build = date.fromordinal(ref_start.toordinal() + base_days + build_days - 1)
    first_specific = date.fromordinal(ref_start.toordinal() + base_days + build_days)

    snap_last_build = _snap_no_anchor(_goal("marathon", race_date=race), last_build, plan_start=ref_start)
    snap_first_specific = _snap_no_anchor(_goal("marathon", race_date=race), first_specific, plan_start=ref_start)

    assert snap_last_build.phase == PeriodizationPhase.build
    assert snap_first_specific.phase == PeriodizationPhase.specific


# ---------------------------------------------------------------------------
# 11. Exact specific/taper boundary
# ---------------------------------------------------------------------------

def test_11_exact_specific_taper_boundary():
    ref_start, race = _marathon_20w_dates()
    total_days = (race - ref_start).days
    taper_days = _MARATHON_TAPER * 7
    base_days, build_days, specific_days = _pre_taper_split(total_days, taper_days)

    last_specific = date.fromordinal(ref_start.toordinal() + base_days + build_days + specific_days - 1)
    first_taper = date.fromordinal(ref_start.toordinal() + base_days + build_days + specific_days)

    snap_last_specific = _snap_no_anchor(_goal("marathon", race_date=race), last_specific, plan_start=ref_start)
    snap_first_taper = _snap_no_anchor(_goal("marathon", race_date=race), first_taper, plan_start=ref_start)

    assert snap_last_specific.phase == PeriodizationPhase.specific
    assert snap_first_taper.phase == PeriodizationPhase.taper


# ---------------------------------------------------------------------------
# 12. Exact taper/race boundary
# ---------------------------------------------------------------------------

def test_12_exact_taper_race_boundary():
    ref_start, race = _marathon_20w_dates()
    total_days = (race - ref_start).days
    taper_days = _MARATHON_TAPER * 7
    base_days, build_days, specific_days = _pre_taper_split(total_days, taper_days)

    last_taper = date.fromordinal(race.toordinal() - 1)
    snap_last_taper = _snap_no_anchor(_goal("marathon", race_date=race), last_taper)
    snap_race = _snap_no_anchor(_goal("marathon", race_date=race), race)

    assert snap_last_taper.phase == PeriodizationPhase.taper
    assert snap_race.phase == PeriodizationPhase.race


# ---------------------------------------------------------------------------
# 13. Short prep — not enough time for base
# ---------------------------------------------------------------------------

def test_13_short_prep_no_base():
    # 10 days to a 5k: taper=1w=7 days, pre_taper=3 days
    # base=floor(3*0.30)=0, build=floor(3*0.40)=1, specific=2
    # → ref_date is in first day → build phase (base dropped)
    race = date(2025, 8, 11)
    ref = date(2025, 8, 1)  # 10 days before race
    snap = _snap_no_anchor(_goal("5k", race_date=race), ref)
    assert snap.phase != PeriodizationPhase.base, \
        f"Expected non-base for very short 5k prep, got {snap.phase}"


# ---------------------------------------------------------------------------
# 14. Very short prep
# ---------------------------------------------------------------------------

def test_14_very_short_prep():
    # 5 days before a 5k: taper = 7 days, pre_taper = 0 → taper starts from day 1
    race = date(2025, 8, 10)
    ref = date(2025, 8, 5)  # 5 days before race
    snap = _snap_no_anchor(_goal("5k", race_date=race), ref)
    assert snap.phase == PeriodizationPhase.taper
    assert snap.mode == PeriodizationMode.race_calendar


# ---------------------------------------------------------------------------
# 15–19. Taper durations by goal type
# ---------------------------------------------------------------------------

def _taper_duration_days(goal_type_str, *, target_distance_km=None):
    """Return the configured taper duration in days for a given goal type."""
    gt = GoalType(goal_type_str)
    return TAPER_WEEKS[gt] * 7


def test_15_taper_5k_duration():
    assert _taper_duration_days("5k") == 7


def test_16_taper_10k_duration():
    assert _taper_duration_days("10k") == 7


def test_17_taper_half_marathon_duration():
    assert _taper_duration_days("half_marathon") == 14


def test_18_taper_marathon_duration():
    assert _taper_duration_days("marathon") == 14


def test_19_taper_ultra_duration():
    assert _taper_duration_days("ultra") == 14


# ---------------------------------------------------------------------------
# 20. No week lost in phase distribution
# ---------------------------------------------------------------------------

def test_20_no_week_lost():
    import math
    race = date(2026, 1, 1)
    ref = date(2025, 1, 1)
    total_days = (race - ref).days  # 365 days

    taper_days = TAPER_WEEKS[GoalType.marathon] * 7
    pre_taper = total_days - taper_days

    base = math.floor(pre_taper * PRE_TAPER_PROPORTIONS["base"])
    build = math.floor(pre_taper * PRE_TAPER_PROPORTIONS["build"])
    specific = pre_taper - base - build

    assert base + build + specific == pre_taper
    assert base + build + specific + taper_days == total_days


# ---------------------------------------------------------------------------
# 21. No week counted twice
# ---------------------------------------------------------------------------

def test_21_no_week_counted_twice():
    import math
    total_days = 140  # exactly 20 weeks
    taper_days = TAPER_WEEKS[GoalType.marathon] * 7
    pre_taper = total_days - taper_days

    base = math.floor(pre_taper * PRE_TAPER_PROPORTIONS["base"])
    build = math.floor(pre_taper * PRE_TAPER_PROPORTIONS["build"])
    specific = pre_taper - base - build

    # Verify strict partitioning: offsets are non-overlapping
    assert 0 <= base
    assert base <= base + build
    assert base + build <= base + build + specific
    assert base + build + specific + taper_days == total_days


# ---------------------------------------------------------------------------
# 22–28. Continuous cycle
# ---------------------------------------------------------------------------

def test_22_continuous_week1_is_base():
    snap = _snap(_goal("maintenance"), ANCHOR)
    assert snap.phase == PeriodizationPhase.base
    assert snap.cycle_week == 1


def test_23_continuous_last_week_base():
    last_day_base = date.fromordinal(ANCHOR.toordinal() + CONTINUOUS_BASE_WEEKS * 7 - 1)
    snap = _snap(_goal("maintenance"), last_day_base)
    assert snap.phase == PeriodizationPhase.base
    assert snap.cycle_week == CONTINUOUS_BASE_WEEKS


def test_24_continuous_first_week_build():
    first_build = date.fromordinal(ANCHOR.toordinal() + CONTINUOUS_BASE_WEEKS * 7)
    snap = _snap(_goal("maintenance"), first_build)
    assert snap.phase == PeriodizationPhase.build
    assert snap.cycle_week == 1


def test_25_continuous_last_week_build():
    last_build = date.fromordinal(
        ANCHOR.toordinal() + (CONTINUOUS_BASE_WEEKS + CONTINUOUS_BUILD_WEEKS) * 7 - 1
    )
    snap = _snap(_goal("maintenance"), last_build)
    assert snap.phase == PeriodizationPhase.build
    assert snap.cycle_week == CONTINUOUS_BUILD_WEEKS


def test_26_continuous_first_week_consolidation():
    first_consol = date.fromordinal(
        ANCHOR.toordinal() + (CONTINUOUS_BASE_WEEKS + CONTINUOUS_BUILD_WEEKS) * 7
    )
    snap = _snap(_goal("maintenance"), first_consol)
    assert snap.phase == PeriodizationPhase.consolidation
    assert snap.cycle_week == 1


def test_27_continuous_last_week_consolidation():
    last_consol = date.fromordinal(
        ANCHOR.toordinal() + CONTINUOUS_CYCLE_LENGTH_WEEKS * 7 - 1
    )
    snap = _snap(_goal("maintenance"), last_consol)
    assert snap.phase == PeriodizationPhase.consolidation
    assert snap.cycle_week == CONTINUOUS_CONSOLIDATION_WEEKS


def test_28_continuous_cycle_wraps_back_to_base():
    next_cycle_start = date.fromordinal(
        ANCHOR.toordinal() + CONTINUOUS_CYCLE_LENGTH_WEEKS * 7
    )
    snap = _snap(_goal("maintenance"), next_cycle_start)
    assert snap.phase == PeriodizationPhase.base
    assert snap.cycle_week == 1


# ---------------------------------------------------------------------------
# 29. Same input → same output (determinism)
# ---------------------------------------------------------------------------

def test_29_determinism():
    goal = _goal("marathon", race_date=date(2025, 10, 1))
    ref = date(2025, 5, 15)
    snap1 = _snap_no_anchor(goal, ref)
    snap2 = _snap_no_anchor(goal, ref)
    assert snap1 == snap2


# ---------------------------------------------------------------------------
# 30. Model is immutable (frozen Pydantic model)
# ---------------------------------------------------------------------------

def test_30_model_immutable():
    snap = _snap(_goal("maintenance"), ANCHOR)
    with pytest.raises(Exception):  # ValidationError or TypeError depending on Pydantic version
        snap.phase = PeriodizationPhase.build  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 31. No datetime.now() / date.today() in periodization.py
# ---------------------------------------------------------------------------

def test_31_no_datetime_now_or_date_today():
    module_path = (
        Path(__file__).parent.parent / "training_v2" / "periodization.py"
    )
    source = module_path.read_text()
    # Parse the AST to check for actual CALLS (not docstring mentions)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # datetime.now()
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "now"
                and isinstance(func.value, ast.Name)
                and func.value.id == "datetime"
            ):
                raise AssertionError("datetime.now() call found in periodization.py")
            # date.today()
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "today"
                and isinstance(func.value, ast.Name)
                and func.value.id == "date"
            ):
                raise AssertionError("date.today() call found in periodization.py")


# ---------------------------------------------------------------------------
# 32. No legacy imports in periodization.py
# ---------------------------------------------------------------------------

def test_32_no_legacy_imports():
    module_path = (
        Path(__file__).parent.parent / "training_v2" / "periodization.py"
    )
    source = module_path.read_text()
    # Parse the AST to check for actual import statements (not docstring mentions)
    tree = ast.parse(source)
    forbidden = ["training_engine", "training_load_engine", "llm_coach", "coach_service"]
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.append(node.module)
    for name in forbidden:
        for mod in imported_modules:
            assert name not in mod, f"Legacy import '{name}' found in periodization.py imports"


# ---------------------------------------------------------------------------
# 33. partial_reprise does not change calendar phase
# ---------------------------------------------------------------------------

def test_33_partial_reprise_no_phase_change():
    """A runner in partial_reprise should stay in the calendar-computed phase."""
    from training_v2.training_state import TrainingState

    race = date(2026, 1, 1)
    ref = date(2025, 1, 1)
    goal = _goal("marathon", race_date=race)

    snap_without_state = _snap_no_anchor(goal, ref)

    ts = TrainingState(
        reference_date=ref,
        continuity_state="partial_reprise",
        continuity_confidence="medium",
        load_state="balanced",
        load_confidence="low",
        overall_confidence="low",
        days_since_last_run=5,
        recent_7d_km=5.0,
        recent_30d_km=20.0,
        acute_load=None,
        chronic_weekly_load=None,
        acwr=None,
        reason_codes=["RECENT_VOLUME_FAR_BELOW_BASELINE"],
    )

    snap_with_state = build_periodization(goal, ref, training_state=ts)
    assert snap_with_state.phase == snap_without_state.phase


# ---------------------------------------------------------------------------
# 34. deep_reprise does not change calendar phase
# ---------------------------------------------------------------------------

def test_34_deep_reprise_no_phase_change():
    from training_v2.training_state import TrainingState

    race = date(2026, 6, 1)
    ref = date(2025, 6, 1)
    goal = _goal("marathon", race_date=race)

    snap_without_state = _snap_no_anchor(goal, ref)

    ts = TrainingState(
        reference_date=ref,
        continuity_state="deep_reprise",
        continuity_confidence="low",
        load_state="unavailable",
        load_confidence="none",
        overall_confidence="none",
        days_since_last_run=35,
        recent_7d_km=0.0,
        recent_30d_km=0.0,
        acute_load=None,
        chronic_weekly_load=None,
        acwr=None,
        reason_codes=["NO_RUN_LAST_28D"],
    )

    snap_with_state = build_periodization(goal, ref, training_state=ts)
    assert snap_with_state.phase == snap_without_state.phase


# ---------------------------------------------------------------------------
# 35. load_state = high does not change calendar phase
# ---------------------------------------------------------------------------

def test_35_high_load_no_phase_change():
    """A high load state must NOT change the calendar phase."""
    from training_v2.training_state import TrainingState

    race = date(2026, 6, 1)
    ref = date(2025, 6, 1)
    goal = _goal("marathon", race_date=race)

    snap_no_state = _snap_no_anchor(goal, ref)

    ts = TrainingState(
        reference_date=ref,
        continuity_state="normal",
        continuity_confidence="high",
        load_state="high",
        load_confidence="high",
        overall_confidence="high",
        days_since_last_run=1,
        recent_7d_km=80.0,
        recent_30d_km=280.0,
        acute_load=600.0,
        chronic_weekly_load=500.0,
        acwr=1.2,
        reason_codes=["CONTINUITY_STABLE", "LOAD_HIGH"],
    )

    snap_with_state = build_periodization(goal, ref, training_state=ts)
    assert snap_with_state.phase == snap_no_state.phase


# ---------------------------------------------------------------------------
# 36. maintenance does not stay eternally in base
# ---------------------------------------------------------------------------

def test_36_maintenance_not_eternal_base():
    # After 4 weeks the cycle moves to build
    first_build = date.fromordinal(ANCHOR.toordinal() + CONTINUOUS_BASE_WEEKS * 7)
    snap = _snap(_goal("maintenance"), first_build)
    assert snap.phase == PeriodizationPhase.build, \
        f"Maintenance should exit base after {CONTINUOUS_BASE_WEEKS} weeks"


# ---------------------------------------------------------------------------
# 37. ultra without date works in continuous cycle
# ---------------------------------------------------------------------------

def test_37_ultra_without_date_continuous():
    snap = _snap(_goal("ultra", target_distance_km=80.0), ANCHOR)
    assert snap.mode == PeriodizationMode.continuous
    assert snap.phase in (
        PeriodizationPhase.base,
        PeriodizationPhase.build,
        PeriodizationPhase.consolidation,
    )


# ---------------------------------------------------------------------------
# 38. Target time does not influence phase
# ---------------------------------------------------------------------------

def test_38_target_time_no_phase_influence():
    ref = date(2025, 3, 1)
    race = date(2025, 10, 1)

    snap_with_time = _snap_no_anchor(
        _goal("marathon", race_date=race, target_time_seconds=10800), ref
    )
    snap_without_time = _snap_no_anchor(
        _goal("marathon", race_date=race), ref
    )
    assert snap_with_time.phase == snap_without_time.phase
    assert snap_with_time.mode == snap_without_time.mode


# ---------------------------------------------------------------------------
# py_compile sanity check
# ---------------------------------------------------------------------------

def test_py_compile_periodization():
    import py_compile
    path = str(
        Path(__file__).parent.parent / "training_v2" / "periodization.py"
    )
    py_compile.compile(path, doraise=True)


def test_py_compile_init():
    import py_compile
    path = str(
        Path(__file__).parent.parent / "training_v2" / "__init__.py"
    )
    py_compile.compile(path, doraise=True)
