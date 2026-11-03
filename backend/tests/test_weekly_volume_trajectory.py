"""Weekly volume trajectory, reconciliation budget and off-plan kilometres."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.training_history import (
    build_completed_week_km,
    compute_actual_weekly_km,
    week_start_of,
)
from training_v2.week_plan_bridge import build_canonical_weekly_plan
from training_v2.weekly_budget import apply_weekly_budget, compute_remaining_budget
from training_v2.weekly_volume import build_volume_trajectory, compute_reference_km
from training_v2.workout_generator import WeeklyPlan, WorkoutPrescription

WED = date(2026, 3, 11)  # Wednesday
FRI = date(2026, 3, 13)
assert WED.weekday() == 2


def _run(day: date, km: float, *, aid=None, hh="07:00:00", **extra) -> DomainActivity:
    return DomainActivity(
        activity_type="running",
        start_time=f"{day.isoformat()}T{hh}",
        distance_m=km * 1000.0,
        duration_s=km * 360.0,
        source="garmin",
        source_activity_id=aid,
        **extra,
    )


def _history(week_kms, ref: date = WED, start_id: int = 1) -> list[DomainActivity]:
    """Completed weeks, newest first: three runs (Tue/Thu/Sat) per week."""
    monday = week_start_of(ref)
    acts = []
    n = start_id
    for i, km in enumerate(week_kms):
        wk = monday - timedelta(weeks=i + 1)
        for off in (1, 3, 5):
            if km > 0:
                acts.append(_run(wk + timedelta(days=off), km / 3.0, aid=str(n)))
                n += 1
    return acts


def _canonical(acts, goal="10K", race=None, ref=WED, **kw):
    return build_canonical_weekly_plan(
        workouts=acts,
        goal_type=goal,
        race_date=race,
        cycle_start_date=ref - timedelta(weeks=4),
        reference_date=ref,
        **kw,
    )


def _plan(sessions) -> WeeklyPlan:
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    by_day = {d: (t, km) for d, t, km in sessions}
    out = []
    for d in days:
        t, km = by_day.get(d, ("rest", None))
        cls = {"rest": "rest", "quality": "high"}.get(t, "low")
        out.append(WorkoutPrescription(
            day=d, workout_type=t, intensity_class=cls,
            distance_km=km, duration_minutes=None, reason_codes=(),
        ))
    training = [s for s in out if s.workout_type != "rest"]
    return WeeklyPlan(
        reference_date=WED, target_basis="distance",
        planned_km=sum(s.distance_km for s in training), planned_duration_minutes=None,
        session_count=len(training), sessions=tuple(out), allow_intensity=True, reason_codes=(),
    )


PLAN30 = [
    ("tuesday", "easy", 7.0), ("thursday", "quality", 8.0),
    ("saturday", "easy", 5.0), ("sunday", "long_easy", 10.0),
]


def _future(plan):
    return [s for s in plan.sessions if s.day in ("thursday", "friday", "saturday", "sunday")]


# 1-2 ---------------------------------------------------------------------

def test_10k_stable_history_with_race_date_follows_trajectory():
    t = _canonical(_history([30] * 6), race=WED + timedelta(weeks=12)).original_target
    assert t.reference_km == 30.0
    assert 30.0 < t.target_km <= 33.0
    assert "TRAJECTORY_RACE_CALENDAR" in t.reason_codes
    assert t.load_cap_km == 33.0


def test_10k_without_date_is_slower_than_with_date():
    with_date = _canonical(_history([30] * 6), race=WED + timedelta(weeks=12)).original_target
    without = _canonical(_history([30] * 6)).original_target
    assert "TRAJECTORY_CONTINUOUS" in without.reason_codes
    assert 30.0 <= without.target_km <= 30.9
    assert without.target_km <= with_date.target_km


# 3 -----------------------------------------------------------------------

def test_insufficient_history_creates_no_trajectory_and_no_fake_km():
    assert compute_reference_km([30, 28, 0, 0, 0, 0]) is None
    t = _canonical([]).original_target
    assert t.reference_km is None and t.target_km is None
    t2 = _canonical(_history([30, 30])).original_target
    assert t2.reference_km is None
    assert not any(c.startswith("TRAJECTORY") for c in t2.reason_codes)


# 4 -----------------------------------------------------------------------

def test_light_week_does_not_collapse_trajectory():
    steady = build_volume_trajectory(
        completed_week_km=[30] * 6, goal_type="10k", weeks_to_race=None,
        taper_weeks=1, phase_multiplier=1.0, phase="build", target_sessions=3,
    )
    light = build_volume_trajectory(
        completed_week_km=[18, 30, 30, 30, 30, 30], goal_type="10k", weeks_to_race=None,
        taper_weeks=1, phase_multiplier=1.0, phase="build", target_sessions=3,
    )
    assert light.reference_km == steady.reference_km == 30.0
    assert light.prescribed_km >= 30.0 > 18.0 * 1.10
    assert "TRAJECTORY_LIGHT_WEEK_IGNORED" in light.reason_codes


def test_spike_week_is_not_the_new_baseline():
    t = build_volume_trajectory(
        completed_week_km=[60, 30, 30, 30], goal_type="10k", weeks_to_race=None,
        taper_weeks=1, phase_multiplier=1.0, phase="build", target_sessions=3,
    )
    assert t.reference_km < 34.0
    assert t.prescribed_km <= round(t.reference_km * 1.10, 1)


def test_trajectory_evolves_with_completed_weeks_not_with_the_current_week():
    base = _history([30] * 6)
    t_wed = _canonical(base, ref=WED).original_target.target_km
    t_fri = _canonical(base + [_run(WED - timedelta(days=1), 20.0, aid="x")], ref=FRI).original_target.target_km
    assert t_wed == t_fri
    grown = _canonical(_history([34, 33, 32, 31, 30, 30]), ref=WED).original_target.target_km
    assert grown > t_wed


def test_missed_week_never_inflates_target():
    t = build_volume_trajectory(
        completed_week_km=[0, 30, 30, 30, 30, 30], goal_type="10k", weeks_to_race=None,
        taper_weeks=1, phase_multiplier=1.0, phase="build", target_sessions=3,
    )
    assert t.prescribed_km <= round(t.reference_km * 1.10, 1)


# 5-6 ---------------------------------------------------------------------

def test_budget_in_plan_plus_off_plan_leaves_15_km():
    plan = _plan(PLAN30)
    acts = [_run(date(2026, 3, 10), 7.0, aid="a"), _run(date(2026, 3, 9), 8.0, aid="b")]
    new, budget = apply_weekly_budget(plan, acts, WED)
    assert (budget.planned_weekly_km, budget.actual_weekly_km, budget.remaining_budget_km) == (30.0, 15.0, 15.0)
    assert sum(s.distance_km for s in _future(new) if s.distance_km) <= 15.0 + 0.2
    for before, after in zip(plan.sessions, new.sessions):
        assert (after.distance_km or 0) <= (before.distance_km or 0)
        if after.day in ("monday", "tuesday", "wednesday"):
            assert after == before


def test_budget_never_negative_and_exhausted_budget_rests_future_days():
    plan = _plan(PLAN30)
    acts = [_run(date(2026, 3, 9), 16.0, aid="a"), _run(date(2026, 3, 10), 16.0, aid="b")]
    new, budget = apply_weekly_budget(plan, acts, WED)
    assert budget.actual_weekly_km == 32.0 and budget.remaining_budget_km == 0.0
    assert all(s.workout_type == "rest" for s in _future(new))
    assert compute_remaining_budget(30.0, 32.0) == 0.0


# 7 -----------------------------------------------------------------------

def test_missed_session_is_not_made_up():
    plan = _plan(PLAN30)
    new, budget = apply_weekly_budget(plan, [], WED)
    assert budget.remaining_budget_km == 30.0
    assert new == plan  # Tuesday missed: Thursday/Saturday/Sunday unchanged, none increased


# 8 -----------------------------------------------------------------------

def test_intense_off_plan_run_does_not_duplicate_quality():
    plan = _plan(PLAN30)
    hard = _run(date(2026, 3, 9), 8.0, aid="h", vigorous_intensity_minutes=25.0)
    new, _ = apply_weekly_budget(plan, [hard], WED)
    thursday = next(s for s in new.sessions if s.day == "thursday")
    assert thursday.workout_type == "easy" and thursday.intensity_class == "low"
    easy_run = _run(date(2026, 3, 9), 8.0, aid="e", vigorous_intensity_minutes=0.0)
    kept, _ = apply_weekly_budget(plan, [easy_run], WED)
    assert next(s for s in kept.sessions if s.day == "thursday").workout_type == "quality"


def test_free_run_is_not_a_completed_specific_session():
    plan = _plan(PLAN30)
    new, _ = apply_weekly_budget(plan, [_run(date(2026, 3, 9), 6.0, aid="f")], WED)
    assert next(s for s in new.sessions if s.day == "thursday").workout_type == "quality"


# 9 -----------------------------------------------------------------------

def test_duplicates_counted_once_and_late_sync_counted_by_date():
    a = _run(date(2026, 3, 9), 10.0, aid="1")
    same_id = _run(date(2026, 3, 9), 10.0, aid="1")
    same_shape = _run(date(2026, 3, 9), 10.0, aid="2")
    assert compute_actual_weekly_km([a, same_id, same_shape], WED) == 10.0
    late = _run(date(2026, 3, 8), 12.0, aid="3")  # synced late, belongs to previous week
    assert compute_actual_weekly_km([a, late], WED) == 10.0
    assert build_completed_week_km([a, late], WED)[0] == 12.0
    assert build_completed_week_km([a, late, late], WED) == build_completed_week_km([late, a], WED)


def test_other_sports_and_future_days_excluded():
    ride = DomainActivity(activity_type="cycling", start_time="2026-03-10T07:00:00", distance_m=40000.0)
    future = _run(date(2026, 3, 12), 9.0, aid="z")
    assert compute_actual_weekly_km([ride, future], WED) == 0.0


# 10 ----------------------------------------------------------------------

def test_canonical_plan_is_deterministic_and_past_days_are_untouched():
    acts = _history([30] * 6) + [_run(date(2026, 3, 9), 9.0, aid="m"), _run(date(2026, 3, 10), 9.0, aid="t")]
    first = _canonical(acts)
    assert first == _canonical(acts)
    assert first.volume_budget.actual_weekly_km == 18.0
    unbudgeted = _canonical(_history([30] * 6))
    for before, after in zip(unbudgeted.weekly_plan.sessions, first.weekly_plan.sessions):
        if _DAYS.index(after.day) <= WED.weekday():
            assert after == before
        else:
            assert (after.distance_km or 0) <= (before.distance_km or 0)


_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# 11 ----------------------------------------------------------------------

def test_two_accounts_do_not_share_state():
    a = _history([30] * 6)
    b = _history([50] * 6, start_id=1000)
    ta1 = _canonical(a).original_target
    tb = _canonical(b).original_target
    ta2 = _canonical(a).original_target
    assert ta1 == ta2
    assert tb.reference_km == 50.0 and ta1.reference_km == 30.0


# 12 ----------------------------------------------------------------------

@pytest.mark.parametrize("goal", ["5K", "10K", "SEMI", "MARATHON", "MAINTENANCE"])
def test_goals_produce_bounded_targets(goal):
    race = None if goal == "MAINTENANCE" else WED + timedelta(weeks=10)
    t = _canonical(_history([32] * 6), goal=goal, race=race).original_target
    assert t.target_km is not None and t.reference_km == 32.0
    assert 28.0 <= t.target_km <= 32.0 * 1.10 + 0.05
    if goal == "MAINTENANCE":
        assert t.target_km == 32.0 and "TRAJECTORY_MAINTENANCE_HOLD" in t.reason_codes


def test_goal_peak_is_a_ceiling_not_a_minimum():
    t = build_volume_trajectory(
        completed_week_km=[12] * 6, goal_type="marathon", weeks_to_race=20,
        taper_weeks=2, phase_multiplier=1.0, phase="base", target_sessions=3,
    )
    assert t.prescribed_km <= 12 * 1.10 + 0.05
    held = build_volume_trajectory(
        completed_week_km=[60] * 6, goal_type="5k", weeks_to_race=8,
        taper_weeks=1, phase_multiplier=1.0, phase="build", target_sessions=4,
    )
    assert held.prescribed_km == 60.0
