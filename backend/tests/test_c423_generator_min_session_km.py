"""C423 — the initial weekly plan never contains an ordinary session < 4 km."""
from datetime import date, timedelta

import pytest

from training_v2.workout_generator import MIN_ORDINARY_SESSION_KM, build_weekly_plan
from training_v2.weekly_budget import apply_weekly_budget
from tests.test_workout_generator_v2 import (
    _periodization, _plan, _plan_goal, _runner_profile_minimal, _running_sessions, _wt_distance,
)

MON = date(2026, 11, 9)


def _plan_at(km, sessions, allow=True, state="normal", phase="build"):
    return _plan(_wt_distance(km, sessions=sessions, allow_intensity=allow, continuity_state=state),
                 phase=phase, ref=MON)


def test_reported_case_8_1km_3_sessions_is_reduced_to_coherent_sessions():
    plan = _plan_at(8.1, 3)
    run = _running_sessions(plan)
    assert run and len(run) < 3
    assert all(s.distance_km >= MIN_ORDINARY_SESSION_KM for s in run)
    assert "MIN_SESSION_KM_FEWER_SESSIONS" in plan.reason_codes
    assert plan.planned_km == pytest.approx(8.1, abs=0.1)  # volume never inflated


@pytest.mark.parametrize("km", [6.0, 8.1, 10.0, 12.0, 16.0, 20.0, 25.0, 30.0])
@pytest.mark.parametrize("sessions", range(1, 7))
@pytest.mark.parametrize("allow", (True, False))
def test_no_ordinary_or_quality_session_under_4km(km, sessions, allow):
    run = _running_sessions(_plan_at(km, sessions, allow))
    for s in run:
        assert s.distance_km >= MIN_ORDINARY_SESSION_KM - 1e-9, (s.workout_type, s.distance_km)


def test_quality_session_keeps_4km_and_is_preferred_over_easy():
    run = _running_sessions(_plan_at(10.0, 3))
    assert any(s.workout_type == "quality" for s in run)
    assert all(s.distance_km >= 4.0 for s in run)


def test_sufficient_volume_keeps_all_sessions():
    plan = _plan_at(32.0, 4)
    assert len(_running_sessions(plan)) == 4
    assert "MIN_SESSION_KM_FEWER_SESSIONS" not in plan.reason_codes


@pytest.mark.parametrize("state", ["no_history", "deep_reprise", "partial_reprise"])
def test_explicit_reprise_states_may_stay_short(state):
    plan = _plan(_wt_distance(8.1, sessions=3, allow_intensity=False, continuity_state=state),
                 phase="build", ref=MON)
    assert "MIN_SESSION_KM_FEWER_SESSIONS" not in plan.reason_codes


def test_future_weeks_have_no_short_sessions():
    for week in range(8):
        ref = MON + timedelta(days=7 * week)
        for km in (8.1, 12.0, 15.0):
            plan = _plan(_wt_distance(km, sessions=4), phase="build", ref=ref)
            assert all(s.distance_km >= 4.0 for s in _running_sessions(plan))


def test_today_week_budget_and_frozen_snapshot_preserved():
    plan = _plan_at(14.0, 4)
    first = next(s for s in plan.sessions if s.workout_type != "rest")
    new, _ = apply_weekly_budget(plan, [], MON + timedelta(days=3), frozen_sessions={first.day: first})
    assert next(s for s in new.sessions if s.day == first.day) == first
    for s in new.sessions:
        if s.workout_type not in ("rest", "race"):
            assert s.distance_km >= 4.0 - 1e-9
