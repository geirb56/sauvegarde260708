"""C386 — hotfix of C385: snapshot replay never restores removed km; post-race without cycle start."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_c385_post_merge_hotfix import FRI, MON, PLAN30, SAT, SUN, THU, TUE, WED, _km
from test_weekly_volume_trajectory import _history, _plan, _run
from training_v2.week_plan_bridge import build_canonical_weekly_plan
from training_v2.weekly_budget import apply_weekly_budget
from training_v2.workout_generator import WorkoutPrescription

# Tue/Thu/Sat/Sun plan, 18 km off-plan Monday run: 12 km of budget left.
PLAN4 = [
    ("tuesday", "easy", 7.0), ("thursday", "easy", 8.0),
    ("saturday", "easy", 5.0), ("sunday", "long_easy", 10.0),
]
OFF = [_run(MON, 18.0, aid="off")]


def _rest(day):
    return WorkoutPrescription(
        day=day, workout_type="rest", intensity_class="rest", distance_km=None,
        duration_minutes=None, reason_codes=(),
    )


def _session(plan, day):
    return next(s for s in plan.sessions if s.day == day)


def _all_days(plan, acts, ref, frozen=None):
    new, _ = apply_weekly_budget(plan, acts, ref, frozen_sessions=frozen)
    return {s.day: s.distance_km or 0.0 for s in new.sessions}


# ── 1. snapshot replay ───────────────────────────────────────────────────────

def test_thursday_rest_snapshot_does_not_raise_sunday():
    plan = _plan(PLAN4)
    before = _all_days(plan, OFF, THU)
    after = _all_days(plan, OFF, THU, {"thursday": _rest("thursday")})
    assert after["sunday"] <= before["sunday"] + 1e-9
    assert after["saturday"] <= before["saturday"] + 1e-9


def test_shortened_snapshot_does_not_raise_other_sessions():
    plan = _plan(PLAN4)
    before = _all_days(plan, OFF, THU)
    short = _session(plan, "thursday").model_copy(update={"distance_km": 3.0})
    after = _all_days(plan, OFF, THU, {"thursday": short})
    for day in ("saturday", "sunday"):
        assert after[day] <= before[day] + 1e-9


def test_future_served_snapshot_never_reopens_budget_for_unserved_days():
    plan = _plan(PLAN4)
    before = _all_days(plan, OFF, WED)
    sat_rest = _rest("saturday")
    after = _all_days(plan, OFF, WED, {"saturday": sat_rest})
    assert after["saturday"] == 0.0  # authoritative, untouched
    for day in ("thursday", "sunday"):
        assert after[day] <= before[day] + 1e-9


@pytest.mark.parametrize("ref", [WED, THU, FRI, SAT])
def test_chronology_unserved_sessions_never_grow_across_days(ref):
    plan = _plan(PLAN4)
    days_seen = []
    for d in (TUE, WED, THU, FRI, SAT):
        if d > ref:
            break
        frozen = {"thursday": _rest("thursday")} if d >= THU else None
        days_seen.append(_all_days(plan, OFF, d, frozen))
    for prev, cur in zip(days_seen, days_seen[1:]):
        for day in ("saturday", "sunday"):
            assert cur[day] <= prev[day] + 1e-9


def test_snapshot_is_never_overwritten():
    plan = _plan(PLAN4)
    thu = _session(plan, "thursday").model_copy(update={"distance_km": 9.0})
    new, _ = apply_weekly_budget(plan, OFF, THU, frozen_sessions={"thursday": thu})
    assert _session(new, "thursday") == thu


def test_two_consultations_identical_and_late_activity_never_adds_budget():
    plan = _plan(PLAN4)
    frozen = {"thursday": _rest("thursday")}
    a = _all_days(plan, OFF, FRI, frozen)
    assert a == _all_days(plan, OFF, FRI, frozen)
    late = OFF + [_run(TUE, 4.0, aid="late")]
    b = _all_days(plan, late, FRI, frozen)
    for day in ("saturday", "sunday"):
        assert b[day] <= a[day] + 1e-9


def test_missed_session_frees_nothing():
    plan = _plan(PLAN4)
    on_thu = _all_days(plan, OFF, THU)
    on_fri = _all_days(plan, OFF, FRI)  # Tuesday/Thursday never run
    for day in ("saturday", "sunday"):
        assert on_fri[day] <= on_thu[day] + 1e-9


def test_frozen_overshoot_is_explicit_and_snapshot_kept():
    plan = _plan(PLAN4)
    big = _session(plan, "saturday").model_copy(update={"distance_km": 20.0})
    new, budget = apply_weekly_budget(plan, OFF, WED, frozen_sessions={"saturday": big})
    assert _session(new, "saturday") == big
    assert "WEEKLY_BUDGET_EXCEEDED_BY_FROZEN_SESSIONS" in budget.reason_codes


# ── 2. post-race without cycle_start_date ────────────────────────────────────

RACE = date(2026, 3, 11)  # Wednesday


@pytest.mark.parametrize("race,ref", [
    (RACE, RACE - timedelta(days=1)),            # A before race (cycle start absent -> see below)
    (RACE, RACE),                                 # B race day
    (RACE, RACE + timedelta(days=1)),             # C day after
    (RACE, RACE + timedelta(days=4)),             # D several days after
    (RACE, RACE + timedelta(days=6)),             # E new week
    (MON, MON),                                   # F race on Monday
    (MON, MON + timedelta(days=2)),
    (SUN, SUN),                                   # G race on Sunday
    (SUN, SUN + timedelta(days=1)),
])
def test_post_race_without_cycle_start_does_not_raise(race, ref):
    hist = _history([30] * 6, ref=ref)
    if ref < race:
        with pytest.raises(ValueError):  # future race needs an explicit plan start (unchanged rule)
            build_canonical_weekly_plan(
                workouts=hist, goal_type="10K", race_date=race, cycle_start_date=None,
                reference_date=ref,
            )
        return
    plan = build_canonical_weekly_plan(
        workouts=hist, goal_type="10K", race_date=race, cycle_start_date=None, reference_date=ref,
    )
    t = plan.original_target
    assert t.target_km is not None or t.target_duration_minutes is not None


# Inside the race week the explicit start anchors the Monday pre-race trajectory, which an
# omitted start cannot reproduce without inventing one; from the next week both agree.
@pytest.mark.parametrize("ref", [RACE + timedelta(days=6), RACE + timedelta(days=9), RACE + timedelta(days=13)])
def test_post_race_target_matches_explicit_cycle_start_after_race_week(ref):
    hist = _history([30] * 6, ref=ref)
    kw = dict(workouts=hist, goal_type="10K", race_date=RACE, reference_date=ref)
    implicit = build_canonical_weekly_plan(cycle_start_date=None, **kw)
    explicit = build_canonical_weekly_plan(cycle_start_date=RACE - timedelta(weeks=8), **kw)
    assert implicit.original_target.target_km == explicit.original_target.target_km
    assert implicit.weekly_plan.sessions == explicit.weekly_plan.sessions
