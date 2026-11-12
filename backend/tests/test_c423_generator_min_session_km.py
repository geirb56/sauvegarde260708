"""C423 — the initial weekly plan never contains an ordinary session < 4 km."""
from datetime import date, timedelta

import pytest

from training_v2.weekly_budget import apply_weekly_budget
from training_v2.workout_generator import (
    _LONG_RUN_ABS_CAP,
    LONG_RUN_MAX_FRACTION,
    MIN_ORDINARY_SESSION_KM,
    build_weekly_plan,
)
from tests.test_workout_generator_v2 import (
    _periodization, _plan, _plan_goal, _runner_profile_minimal, _running_sessions, _wt_distance,
)

MON = date(2026, 11, 9)
MIN = MIN_ORDINARY_SESSION_KM


def _plan_at(km, sessions, allow=True, state="normal", phase="build", goal="marathon", **kw):
    return _plan(_wt_distance(km, sessions=sessions, allow_intensity=allow, continuity_state=state),
                 phase=phase, ref=MON, goal=goal, **kw)


def _km(plan):
    return [s.distance_km for s in _running_sessions(plan)]


def _long_cap(km, goal):
    return min(_LONG_RUN_ABS_CAP[goal], max(LONG_RUN_MAX_FRACTION * km, MIN))


def test_reported_case_8_1km_3_sessions_is_reduced_to_coherent_sessions():
    plan = _plan_at(8.1, 3)
    run = _running_sessions(plan)
    assert run and len(run) < 3
    assert all(s.distance_km >= MIN for s in run)
    assert "MIN_SESSION_KM_FEWER_SESSIONS" in plan.reason_codes
    assert sum(_km(plan)) <= 8.1 + 1e-9
    assert plan.planned_km == pytest.approx(8.1, abs=0.1)


@pytest.mark.parametrize("target,kept", [(3.9, False), (4.0, True)])
def test_last_session_3_9_becomes_rest_4_0_is_kept(target, kept):
    plan = _plan_at(target, 1, allow=False)
    run = _running_sessions(plan)
    if kept:
        assert [s.distance_km for s in run] == [4.0]
        assert "MIN_SESSION_KM_FEWER_SESSIONS" not in plan.reason_codes
    else:
        assert run == []
        assert plan.planned_km == 0
        assert "MIN_SESSION_KM_FEWER_SESSIONS" in plan.reason_codes
        assert "MIN_SESSION_KM_VOLUME_REDUCED" in plan.reason_codes
        rests = [s for s in plan.sessions if "ORDINARY_SESSION_MIN_KM_NOT_MET" in s.reason_codes]
        assert len(rests) == 1 and rests[0].workout_type == "rest"


def test_3_sessions_with_3_9_total_leaves_an_explicit_rest_week():
    plan = _plan_at(3.9, 3)
    assert _running_sessions(plan) == [] and plan.planned_km == 0
    assert "MIN_SESSION_KM_VOLUME_REDUCED" in plan.reason_codes


def test_12km_3_sessions_5k_respects_long_run_cap_and_minimum():
    plan = _plan_at(12.0, 3, goal="5k")
    run = _running_sessions(plan)
    assert len(run) in (2, 3)  # never one long run carrying the whole week
    assert all(s.distance_km >= MIN for s in run)
    long = [s for s in run if s.workout_type == "long_easy"]
    assert all(s.distance_km <= _long_cap(12.0, "5k") + 1e-9 for s in long)
    assert max(s.distance_km for s in run) < 12.0
    assert sum(_km(plan)) == pytest.approx(12.0, abs=0.1)
    assert sum(_km(plan)) <= 12.0 + 1e-9


@pytest.mark.parametrize("goal", ["5k", "10k", "half_marathon", "marathon"])
@pytest.mark.parametrize("km", [4.0, 5.5, 8.0, 8.1, 9.9, 12.0, 13.5, 16.0, 20.0, 30.0])
@pytest.mark.parametrize("sessions", range(1, 7))
@pytest.mark.parametrize("allow", (True, False))
def test_invariants_minimum_long_cap_and_no_inflation(goal, km, sessions, allow):
    plan = _plan_at(km, sessions, allow, goal=goal)
    run = _running_sessions(plan)
    assert all(s.distance_km >= MIN - 1e-9 for s in run)
    assert sum(_km(plan)) <= km + 0.1 + 1e-9
    if plan.reason_codes and "MIN_SESSION_KM_FEWER_SESSIONS" in plan.reason_codes:
        for s in run:
            if s.workout_type == "long_easy":
                assert s.distance_km <= _long_cap(km, goal) + 1e-9
    assert plan == _plan_at(km, sessions, allow, goal=goal)  # deterministic


def test_quality_session_keeps_4km_and_is_preferred_over_easy():
    run = _running_sessions(_plan_at(10.0, 3))
    assert any(s.workout_type == "quality" for s in run)
    assert all(s.distance_km >= 4.0 for s in run)


def test_sufficient_volume_keeps_all_sessions_unchanged():
    plan = _plan_at(32.0, 4)
    assert len(_running_sessions(plan)) == 4
    assert "MIN_SESSION_KM_FEWER_SESSIONS" not in plan.reason_codes


# --- calendar: race the following Monday, Sunday reserved ---------------------

def _race_eve_plan(km=8.1, sessions=3, **kw):
    return _plan_at(km, sessions, phase="taper", race_date=MON + timedelta(days=7), **kw)


def test_race_next_monday_8_1km_keeps_earlier_sessions_and_rests_sunday():
    plan = _race_eve_plan()
    run = _running_sessions(plan)
    sunday = next(s for s in plan.sessions if s.day == "sunday")
    assert sunday.workout_type == "rest"
    assert run, "the week must not be emptied because Sunday is forbidden"
    assert all(s.day != "sunday" for s in run)
    assert all(s.distance_km >= MIN for s in run)
    assert sum(_km(plan)) <= 8.1 + 1e-9 and plan.planned_km == pytest.approx(8.1, abs=0.1)


def test_race_next_monday_sessions_never_on_forbidden_day_for_all_volumes():
    for km in (4.0, 6.0, 8.1, 10.0, 12.0, 18.0, 24.0):
        for n in range(1, 6):
            plan = _race_eve_plan(km, n)
            assert next(s for s in plan.sessions if s.day == "sunday").workout_type == "rest"
            assert all(s.distance_km >= MIN for s in _running_sessions(plan))


def test_race_next_monday_with_user_preferences_never_uses_sunday():
    profile = _runner_profile_minimal(MON).model_copy(update={"preferred_long_run_day": "sunday"})
    plan = build_weekly_plan(
        weekly_target=_wt_distance(8.1, sessions=3), runner_profile=profile,
        plan_goal=_plan_goal("marathon", race_date=MON + timedelta(days=7)),
        periodization=_periodization("taper", MON), reference_date=MON,
    )
    assert next(s for s in plan.sessions if s.day == "sunday").workout_type == "rest"
    assert all(s.distance_km >= MIN for s in _running_sessions(plan))
    assert _running_sessions(plan)


# --- phase race is not an exemption -------------------------------------------

@pytest.mark.parametrize("km", [5.0, 6.0, 8.1])
def test_race_phase_without_qualified_recovery_keeps_the_minimum(km):
    plan = _plan_at(km, 3, phase="race")
    assert all(s.distance_km >= MIN for s in _running_sessions(plan))


def test_race_week_with_race_in_the_week_keeps_the_minimum():
    plan = _plan_at(8.1, 3, phase="race", race_date=MON + timedelta(days=6))
    assert all(s.distance_km >= MIN for s in _running_sessions(plan))
    assert next(s for s in plan.sessions if s.day == "sunday").workout_type == "race"


# --- reprise ------------------------------------------------------------------

@pytest.mark.parametrize("state", ["no_history", "deep_reprise", "partial_reprise"])
def test_explicit_reprise_states_may_stay_short(state):
    plan = _plan(_wt_distance(8.1, sessions=3, allow_intensity=False, continuity_state=state),
                 phase="build", ref=MON)
    assert "MIN_SESSION_KM_FEWER_SESSIONS" not in plan.reason_codes


def test_exemption_is_not_inferred_from_session_names():
    plan = _plan_at(6.0, 3, allow=False)  # recovery/easy names never exempt
    assert all(s.distance_km >= MIN for s in _running_sessions(plan))


# --- future weeks / Today / Week / frozen -------------------------------------

def test_future_weeks_have_no_short_sessions():
    for week in range(8):
        ref = MON + timedelta(days=7 * week)
        for km in (8.1, 12.0, 15.0):
            plan = _plan(_wt_distance(km, sessions=4), phase="build", ref=ref)
            assert all(s.distance_km >= 4.0 for s in _running_sessions(plan))


def test_today_and_week_serve_the_same_minimum():
    from training_v2.today_prescription import resolve_today_final_prescription

    plan = _plan_at(8.1, 3)
    for s in _running_sessions(plan):
        final = resolve_today_final_prescription(
            planned_prescription=s, reference_date=MON, domain_activities_90=[],
            garmin_daily_metrics_docs=[], garmin_connected=False, continuity_state="normal",
        ).adaptation_result.adapted_workout
        assert final.workout_type == "rest" or final.distance_km >= MIN


def test_weekly_budget_and_frozen_snapshot_preserved():
    plan = _plan_at(14.0, 4)
    first = next(s for s in plan.sessions if s.workout_type != "rest")
    new, _ = apply_weekly_budget(plan, [], MON + timedelta(days=3), frozen_sessions={first.day: first})
    assert next(s for s in new.sessions if s.day == first.day) == first
    for s in new.sessions:
        if s.workout_type not in ("rest", "race"):
            assert s.distance_km >= 4.0 - 1e-9


def test_generation_does_not_rewrite_a_frozen_served_session():
    served = _plan_at(8.1, 3)
    day = _running_sessions(served)[0].day
    frozen = next(s for s in served.sessions if s.day == day)
    regenerated = _plan_at(12.0, 3)
    new, _ = apply_weekly_budget(regenerated, [], MON + timedelta(days=3), frozen_sessions={day: frozen})
    assert next(s for s in new.sessions if s.day == day) == frozen
