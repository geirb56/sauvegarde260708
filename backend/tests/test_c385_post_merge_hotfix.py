"""C385 — post-merge hotfix of C384 (budget rollover, calendar, target stability, frequency)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_weekly_volume_trajectory import _canonical, _history, _plan, _run
from training_v2.training_history import build_completed_week_km, week_start_of
from training_v2.weekly_budget import apply_weekly_budget
from training_v2.weekly_volume import build_volume_trajectory

MON = date(2026, 3, 9)
TUE, WED, THU, FRI, SAT, SUN = (MON + timedelta(days=i) for i in range(1, 7))
PLAN30 = [
    ("tuesday", "easy", 7.0), ("thursday", "quality", 8.0),
    ("saturday", "easy", 5.0), ("sunday", "long_easy", 10.0),
]


def _km(plan, day):
    s = next(s for s in plan.sessions if s.day == day)
    return s.distance_km or 0.0, s.workout_type


# ── 1. budget reduction survives the J+1 → J rollover ────────────────────────

def test_reduction_survives_rollover_and_second_service_is_identical():
    plan = _plan(PLAN30)
    off_plan = [_run(MON, 18.0, aid="off")]  # large off-plan run, 12 km left

    wed_plan, wed_budget = apply_weekly_budget(plan, off_plan, WED)
    thu_before = _km(wed_plan, "thursday")
    assert thu_before[0] < 8.0  # reduced (or dropped) on Wednesday

    thu_plan, _ = apply_weekly_budget(plan, off_plan, THU)  # no new activity
    assert _km(thu_plan, "thursday")[0] <= thu_before[0]
    # served again the same day: identical
    again, _ = apply_weekly_budget(plan, off_plan, THU)
    assert again == thu_plan


def test_missed_wednesday_session_does_not_free_budget_for_thursday():
    plan = _plan(PLAN30 + [("wednesday", "easy", 6.0)])
    acts = [_run(MON, 20.0, aid="off")]
    wed_plan, _ = apply_weekly_budget(plan, acts, WED)
    thu_plan, _ = apply_weekly_budget(plan, acts, THU)  # Wednesday not run
    for day in ("thursday", "saturday", "sunday"):
        assert _km(thu_plan, day)[0] <= _km(wed_plan, day)[0]


def test_today_unserved_respects_budget_and_never_exceeds_original():
    plan = _plan(PLAN30)
    thu_plan, budget = apply_weekly_budget(plan, [_run(MON, 25.0, aid="off")], THU)
    assert _km(thu_plan, "thursday")[0] <= 8.0
    assert budget.adapted_remaining_km <= budget.remaining_budget_km + 0.1


def test_today_already_run_is_not_modified():
    plan = _plan(PLAN30)
    acts = [_run(MON, 25.0, aid="off"), _run(THU, 8.0, aid="thu")]
    new, _ = apply_weekly_budget(plan, acts, THU)
    assert _km(new, "thursday") == (8.0, "quality")


def test_served_today_is_immutable():
    plan = _plan(PLAN30)
    thu = next(s for s in plan.sessions if s.day == "thursday")
    new, _ = apply_weekly_budget(plan, [_run(MON, 25.0, aid="off")], THU, frozen_sessions={"thursday": thu})
    assert next(s for s in new.sessions if s.day == "thursday") == thu


def test_no_off_plan_run_keeps_plan_unchanged_on_every_day():
    plan = _plan(PLAN30)
    for ref in (MON, TUE, WED, THU, FRI, SAT, SUN):
        new, _ = apply_weekly_budget(plan, [], ref)
        assert new.sessions == plan.sessions


# ── 2. calendar boundaries ────────────────────────────────────────────────────

REF = date(2026, 3, 11)


@pytest.mark.parametrize(
    "act_day, expected_index",
    [
        (date(2026, 3, 2), 0),    # previous Monday
        (date(2026, 3, 8), 0),    # previous Sunday
        (date(2026, 2, 23), 1),   # Monday two weeks ago
        (date(2026, 3, 1), 1),    # Sunday two weeks ago
        (date(2026, 2, 2), 4),    # Monday five weeks ago (month change)
    ],
)
def test_week_index_has_no_offset(act_day, expected_index):
    out = build_completed_week_km([_run(act_day, 10.0, aid="a")], REF, weeks=6)
    assert out[expected_index] == 10.0
    assert sum(v or 0 for v in out) == 10.0  # counted exactly once


def test_current_week_monday_is_excluded():
    out = build_completed_week_km([_run(MON, 9.0, aid="a"), _run(date(2026, 3, 2), 4.0, aid="b")], REF)
    assert out[0] == 4.0


def test_december_january_rollover():
    ref = date(2026, 1, 7)
    out = build_completed_week_km([_run(date(2025, 12, 29), 7.0, aid="a"), _run(date(2026, 1, 4), 3.0, aid="b")], ref, 3)
    assert out[0] == 10.0
    assert week_start_of(date(2026, 1, 4)) == date(2025, 12, 29)


def test_near_midnight_and_late_sync_use_local_date():
    from training_v2.domain_activity import DomainActivity
    late = DomainActivity(
        activity_type="running", start_time="2026-03-08T23:30:00", start_time_local="2026-03-09T00:10:00",
        distance_m=5000.0, source="garmin", source_activity_id="n",
    )  # local Monday 00:10: current week
    before = DomainActivity(
        activity_type="running", start_time="2026-03-09T00:30:00", start_time_local="2026-03-08T23:50:00",
        distance_m=6000.0, source="garmin", source_activity_id="m",
    )  # local Sunday 23:50: previous week
    out = build_completed_week_km([late, before], REF, weeks=2)
    assert out[0] == 6.0
    assert build_completed_week_km([late, before, before], REF, weeks=2)[0] == 6.0  # dedup


# ── 3. weekly target stability ────────────────────────────────────────────────

def test_target_and_initial_volume_stable_across_the_week_with_dated_race():
    hist = _history([30] * 6) + [_run(MON, 5.0, aid="cur")]
    race = REF + timedelta(weeks=12)
    targets = {
        _canonical(hist, race=race, ref=ref).original_target.target_km for ref in (MON, WED, FRI, SUN)
    }
    assert targets == {31.4}


@pytest.mark.parametrize("goal", ["10K", "SEMI", "MARATHON"])
def test_target_stable_across_phase_boundaries_inside_the_week(goal):
    from training_v2.week_plan_bridge import build_canonical_weekly_plan
    hist = _history([30] * 6) + [_run(MON, 5.0, aid="cur")]
    for off in range(0, 100):
        race = MON + timedelta(days=off)
        seen = {
            build_canonical_weekly_plan(
                workouts=hist, goal_type=goal, race_date=race,
                cycle_start_date=MON - timedelta(weeks=8), reference_date=MON + timedelta(days=i),
            ).original_target.target_km
            for i in range(7)
        }
        assert len(seen) == 1, (goal, off, seen)


def test_remaining_budget_varies_with_activities_not_the_initial_target():
    hist = _history([30] * 6)
    race = REF + timedelta(weeks=12)
    mon = _canonical(hist + [_run(MON, 5.0, aid="c1")], race=race, ref=MON)
    fri = _canonical(hist + [_run(MON, 5.0, aid="c1"), _run(WED, 8.0, aid="c2")], race=race, ref=FRI)
    assert mon.original_target.target_km == fri.original_target.target_km
    assert fri.volume_budget.actual_weekly_km == 13.0
    assert mon.volume_budget.planned_weekly_km == fri.volume_budget.planned_weekly_km
    assert fri.volume_budget.remaining_budget_km < mon.volume_budget.remaining_budget_km


def test_new_week_recomputes_the_trajectory():
    hist = _history([30] * 6)
    race = REF + timedelta(weeks=12)
    this = _canonical(hist + [_run(MON, 5.0, aid="c")], race=race, ref=WED).original_target.target_km
    nxt_ref = REF + timedelta(weeks=3)
    nxt = _canonical(_history([30] * 6, ref=nxt_ref) + [_run(week_start_of(nxt_ref), 5.0, aid="c")], race=race, ref=nxt_ref)
    assert nxt.original_target.target_km is not None and this is not None


# ── 4. requested frequency ────────────────────────────────────────────────────

def _traj(sessions):
    return build_volume_trajectory(
        completed_week_km=[30.0] * 6, goal_type="10k", weeks_to_race=12.0,
        taper_weeks=1, phase_multiplier=1.0, phase="build", target_sessions=sessions,
    )


def test_two_sessions_hold_three_or_more_grow():
    assert _traj(2).weekly_rate == 0.0 and "TRAJECTORY_FREQUENCY_HOLD" in _traj(2).reason_codes
    assert _traj(3).weekly_rate > 0
    assert _traj(4).weekly_rate > 0


def _freq_target(pref, profile=None, acts=None, **kw):
    acts = acts if acts is not None else _history([30] * 6) + [_run(MON, 5.0, aid="c")]
    return _canonical(
        acts, race=REF + timedelta(weeks=12), ref=WED, sessions_preference=pref,
        user_profile=profile, **kw,
    ).original_target


def test_profile_three_but_requested_two_holds_volume():
    profile = {"preferred_days_per_week": 3}
    two = _freq_target(2, profile)
    three = _freq_target(3, profile)
    assert two.target_sessions == 2
    assert "TRAJECTORY_FREQUENCY_HOLD" in two.reason_codes
    assert "TRAJECTORY_FREQUENCY_HOLD" not in three.reason_codes
    assert two.target_km < three.target_km


@pytest.mark.parametrize("pref", [3, 4])
def test_three_and_four_allow_growth(pref):
    t = _freq_target(pref, {"preferred_days_per_week": 2})
    assert t.target_sessions == pref and "TRAJECTORY_FREQUENCY_HOLD" not in t.reason_codes


def test_absent_preference_uses_profile_frequency():
    t = _freq_target(None, {"preferred_days_per_week": 3})
    assert t.target_sessions == 3 and "TRAJECTORY_FREQUENCY_HOLD" not in t.reason_codes
    t2 = _freq_target(None, {"preferred_days_per_week": 2})
    assert t2.target_sessions == 2 and "TRAJECTORY_FREQUENCY_HOLD" in t2.reason_codes


def test_availability_cap_below_preference_holds_volume():
    t = _freq_target(5, {"max_days_per_week": 2})
    assert t.target_sessions == 2 and "TRAJECTORY_FREQUENCY_HOLD" in t.reason_codes


def test_preference_above_admissible_is_capped_never_raised():
    t = _freq_target(6, {"max_days_per_week": 4})
    assert t.target_sessions == 4


def test_training_preferences_dict_is_the_requested_frequency():
    t = _canonical(
        _history([30] * 6) + [_run(MON, 5.0, aid="c")], race=REF + timedelta(weeks=12), ref=WED,
        user_profile={"preferred_days_per_week": 3}, training_preferences={"sessions_per_week": 2},
    ).original_target
    assert t.target_sessions == 2 and "TRAJECTORY_FREQUENCY_HOLD" in t.reason_codes
