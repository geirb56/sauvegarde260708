"""B1 — soft day preferences preserve the canonical training prescription."""

from datetime import date, timedelta
from itertools import combinations

import pytest

from test_workout_generator_v2 import (
    _periodization,
    _plan_goal,
    _runner_profile_minimal,
    _wt_distance,
    _wt_duration,
)
from training_v2.workout_generator import _ALL_DAYS, _assign_days, build_weekly_plan
from training_v2.week_plan_bridge import build_canonical_weekly_plan


REF = date(2026, 9, 14)


def _profile(days=None, long_day=None, **overrides):
    return _runner_profile_minimal(REF).model_copy(update={
        "preferred_training_days": days,
        "preferred_long_run_day": long_day,
        "max_days_per_week": 6,
        **overrides,
    })


def _build(target, profile, *, phase="build", race_date=None):
    return build_weekly_plan(
        weekly_target=target,
        runner_profile=profile,
        plan_goal=_plan_goal(race_date=race_date),
        periodization=_periodization(phase, REF),
        reference_date=REF,
    )


def _active(plan):
    return [s for s in plan.sessions if s.workout_type not in {"rest", "race"}]


def test_preferred_days_and_long_run_are_used_without_changing_training_load():
    target = _wt_distance(30, sessions=3)
    baseline = _build(target, _profile())
    preferred = _build(target, _profile(["tuesday", "thursday", "sunday"], "sunday"))
    assert {s.day for s in _active(preferred)} == {"tuesday", "thursday", "sunday"}
    assert next(s.day for s in preferred.sessions if s.workout_type == "long_easy") == "sunday"
    assert preferred.planned_km == baseline.planned_km == 30
    assert preferred.session_count == baseline.session_count == 3
    assert sorted((s.workout_type, s.distance_km) for s in _active(preferred)) == sorted(
        (s.workout_type, s.distance_km) for s in _active(baseline)
    )


@pytest.mark.parametrize("sessions", range(2, 7))
def test_restrictive_preferences_never_remove_sessions(sessions):
    plan = _build(_wt_distance(40, sessions=sessions), _profile(["sunday"], "sunday"))
    assert plan.session_count == sessions
    assert plan.planned_km == 40
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" in plan.reason_codes
    assert next(s.day for s in plan.sessions if s.workout_type == "long_easy") == "sunday"


def test_more_available_days_than_sessions_is_supported():
    plan = _build(
        _wt_distance(30, sessions=3),
        _profile(["monday", "tuesday", "thursday", "saturday", "sunday"], "sunday"),
    )
    assert plan.session_count == 3
    assert {s.day for s in _active(plan)} <= {"monday", "tuesday", "thursday", "saturday", "sunday"}
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" not in plan.reason_codes


@pytest.mark.parametrize("continuity", ["deep_reprise", "no_history", "partial_reprise"])
def test_no_artificial_long_run_and_reprise_recovery(continuity):
    target = _wt_duration(90, sessions=3, continuity_state=continuity)
    plan = _build(target, _profile(["monday", "tuesday", "wednesday"], "wednesday"))
    assert plan.session_count == 3
    assert plan.planned_duration_minutes == 90
    assert {s.workout_type for s in _active(plan)} <= {"easy", "recovery"}
    active_indices = {_ALL_DAYS.index(s.day) for s in _active(plan)}
    assert all((index + 1) % 7 not in active_indices for index in active_indices)
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" in plan.reason_codes
    assert "PREFERRED_LONG_RUN_DAY_FALLBACK" not in plan.reason_codes


def test_strict_unavailability_is_not_overridden_by_preference():
    plan = _build(
        _wt_distance(30, sessions=3),
        _profile(["sunday"], "sunday", availability_constraints=["sunday"]),
    )
    assert plan.sessions[-1].workout_type == "rest"
    assert plan.session_count == 3
    assert "PREFERRED_LONG_RUN_DAY_FALLBACK" in plan.reason_codes
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" in plan.reason_codes


@pytest.mark.parametrize("race_offset", range(7))
def test_race_week_guards_override_incompatible_preferences(race_offset):
    target = _wt_distance(30, sessions=4)
    race_date = REF + timedelta(days=race_offset)
    baseline = _build(target, _profile(), phase="race", race_date=race_date)
    preferred = _build(target, _profile(["sunday"], "sunday"), phase="race", race_date=race_date)
    assert preferred.sessions[race_offset].workout_type == "race"
    assert preferred.session_count == baseline.session_count
    assert preferred.planned_km <= baseline.planned_km
    assert not any(s.workout_type in {"quality", "long_easy", "steady"} for s in _active(preferred))
    if race_offset:
        assert preferred.sessions[race_offset - 1].workout_type == "rest"
    assert all(_ALL_DAYS.index(s.day) < race_offset for s in _active(preferred))


def test_quality_is_not_placed_on_calendar_day_before_long_run():
    for count in range(1, 8):
        for preferred_days in combinations(_ALL_DAYS, count):
            skeleton, _ = _assign_days(
                ["easy", "quality", "long_easy"],
                _profile(list(preferred_days), preferred_days[-1]),
            )
            mapping = dict(skeleton)
            quality_day = next(day for day, kind in skeleton if kind == "quality")
            if quality_day != "sunday":
                assert mapping[_ALL_DAYS[_ALL_DAYS.index(quality_day) + 1]] != "long_easy"


@pytest.mark.parametrize("continuity", ["normal", "no_history", "deep_reprise", "partial_reprise"])
def test_next_monday_race_keeps_guard_reductions_without_preference_induced_losses(continuity):
    target = (
        _wt_distance(30, sessions=3, continuity_state=continuity)
        if continuity == "normal"
        else _wt_duration(90, sessions=3, continuity_state=continuity)
    )
    race_date = REF + timedelta(days=7)
    baseline = _build(target, _profile(), phase="taper", race_date=race_date)
    preferred = _build(target, _profile(["sunday"], "sunday"), phase="taper", race_date=race_date)
    assert preferred.sessions[-1].workout_type == "rest"
    assert preferred.session_count == baseline.session_count
    assert preferred.planned_km == baseline.planned_km
    assert preferred.planned_duration_minutes == baseline.planned_duration_minutes
    assert sorted((s.workout_type, s.distance_km, s.duration_minutes) for s in _active(preferred)) == sorted(
        (s.workout_type, s.distance_km, s.duration_minutes) for s in _active(baseline)
    )
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" in preferred.reason_codes


def test_cross_week_preference_pass_cannot_discard_surviving_sessions(monkeypatch):
    import training_v2.workout_generator as generator

    target = _wt_duration(90, sessions=3)
    race_date = REF + timedelta(days=7)
    baseline = _build(target, _profile(), phase="taper", race_date=race_date)
    original_assign = generator._assign_days

    def tighter_calendar(slots, profile, **kwargs):
        skeleton, codes = original_assign(slots, profile, **kwargs)
        if kwargs.get("allowed_training_days") is not None:
            day_to_remove = next(day for day, kind in skeleton if kind != "rest")
            skeleton = [(day, "rest" if day == day_to_remove else kind) for day, kind in skeleton]
        return skeleton, codes

    monkeypatch.setattr(generator, "_assign_days", tighter_calendar)
    preferred = _build(target, _profile(["tuesday", "thursday"]), phase="taper", race_date=race_date)
    assert preferred.sessions == baseline.sessions
    assert preferred.session_count == baseline.session_count
    assert preferred.planned_duration_minutes == baseline.planned_duration_minutes
    assert "PREFERRED_TRAINING_DAYS_FALLBACK" in preferred.reason_codes


def test_preference_order_does_not_change_deterministic_plan():
    days = ["tuesday", "thursday", "sunday"]
    target = _wt_distance(30, sessions=3)
    assert _build(target, _profile(days, "sunday")) == _build(target, _profile(days[::-1], "sunday"))


def test_canonical_bridge_uses_preferences_without_mutating_inputs():
    profile = {"availability_constraints": ["monday"]}
    preferences = {
        "sessions_per_week": 3,
        "preferred_training_days": ["tuesday", "thursday", "sunday"],
        "preferred_long_run_day": "sunday",
    }
    kwargs = dict(workouts=[], goal_type="MAINTENANCE", reference_date=REF, user_profile=profile)
    canonical = build_canonical_weekly_plan(**kwargs, training_preferences=preferences)
    assert canonical.weekly_plan.session_count == 3
    assert {s.day for s in _active(canonical.weekly_plan)} == set(preferences["preferred_training_days"])
    assert all(s.workout_type != "long_easy" for s in canonical.weekly_plan.sessions)
    assert profile == {"availability_constraints": ["monday"]}
    assert preferences["preferred_long_run_day"] == "sunday"


def test_absent_preferences_keep_legacy_canonical_output():
    kwargs = dict(workouts=[], goal_type="MAINTENANCE", reference_date=REF)
    assert build_canonical_weekly_plan(**kwargs, training_preferences={}) == build_canonical_weekly_plan(**kwargs)
