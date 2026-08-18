from __future__ import annotations

import sys
from datetime import date, timedelta

sys.path.insert(0, "backend")

from training_v2.domain_activity import DomainActivity
from training_v2.periodization import build_periodization
from training_v2.plan_goal import build_plan_goal
from training_v2.runner_profile import build_runner_profile
from training_v2.training_history import build_training_history
from training_v2.training_load import build_training_load
from training_v2.training_state import build_training_state
from training_v2.weekly_reconciliation import build_weekly_reconciliation
from training_v2.weekly_target import WeeklyTarget, build_weekly_target
from training_v2.workout_generator import (
    WeeklyPlan,
    _compute_long_run_km,
    build_weekly_plan,
)


REF = date(2026, 8, 18)
CYCLE_ANCHOR = REF - timedelta(weeks=8)
GOALS = ("5k", "10k", "half_marathon", "marathon", "ultra")


def _activity(days_ago: int, km: float, minutes: float | None = None) -> DomainActivity:
    return DomainActivity(
        activity_type="running",
        start_time=(REF - timedelta(days=days_ago)).isoformat(),
        distance_m=km * 1000.0,
        duration_s=(minutes if minutes is not None else km * 6.0) * 60.0,
    )


def _goal(goal_type: str):
    kwargs = {"goal_type": goal_type}
    if goal_type == "ultra":
        kwargs["target_distance_km"] = 50.0
    return build_plan_goal(**kwargs)


def _periodization(goal):
    return build_periodization(
        goal,
        REF,
        cycle_anchor_date=CYCLE_ANCHOR,
    )


def _pipeline(*activities: DomainActivity, goal_type: str = "half_marathon"):
    history = build_training_history(list(activities), REF)
    load = build_training_load(activities=list(activities), reference_date=REF)
    profile = build_runner_profile(
        training_history=history,
        training_load=load,
        reference_date=REF,
    )
    state = build_training_state(
        training_history=history,
        training_load=load,
        runner_profile=profile,
        reference_date=REF,
    )
    goal = _goal(goal_type)
    periodization = _periodization(goal)
    weekly_target = build_weekly_target(
        runner_profile=profile,
        training_history=history,
        training_state=state,
        plan_goal=goal,
        periodization=periodization,
        reference_date=REF,
    )
    reconciliation = build_weekly_reconciliation(
        proposed_target=weekly_target,
        recent_response=None,
    )
    weekly_plan = build_weekly_plan(
        weekly_target=reconciliation.reconciled_target,
        runner_profile=profile,
        plan_goal=goal,
        periodization=periodization,
        reference_date=REF,
    )
    return state, weekly_target, reconciliation, weekly_plan


def test_half_marathon_deep_reprise_stays_duration_based():
    prior_history = [
        _activity(28, 10.0),
        _activity(31, 10.0),
        _activity(34, 10.0),
        _activity(38, 10.0),
    ]

    state, weekly_target, reconciliation, weekly_plan = _pipeline(
        *prior_history,
        goal_type="half_marathon",
    )

    assert state.continuity_state == "deep_reprise"
    assert weekly_target.target_basis == "duration"
    assert weekly_target.target_km is None
    assert weekly_target.allow_intensity is False
    assert reconciliation.reconciled_target.target_basis == "duration"
    assert weekly_plan.planned_km is None
    assert weekly_plan.planned_duration_minutes == reconciliation.reconciled_target.target_duration_minutes
    assert all(
        session.distance_km is None
        for session in weekly_plan.sessions
        if session.workout_type != "rest"
    )


def test_multi_goal_reprise_state_never_overridden():
    activities = [
        _activity(28, 10.0),
        _activity(31, 10.0),
        _activity(34, 10.0),
        _activity(38, 10.0),
    ]

    for goal_type in GOALS:
        state, weekly_target, reconciliation, _ = _pipeline(*activities, goal_type=goal_type)
        assert state.continuity_state == "deep_reprise"
        assert weekly_target.target_basis == "duration"
        assert weekly_target.target_km is None
        assert weekly_target.allow_intensity is False
        assert reconciliation.reconciled_target.target_basis == "duration"


def test_long_run_invariants_use_weekly_target_only():
    assert _compute_long_run_km(5.0) <= 5.0

    weekly_target = WeeklyTarget(
        reference_date=REF,
        target_basis="distance",
        target_km=5.0,
        target_duration_minutes=None,
        target_sessions=2,
        allow_intensity=False,
        confidence="medium",
        continuity_state="reprise_exit",
        reason_codes=(),
    )
    goal = _goal("half_marathon")
    periodization = _periodization(goal)
    profile = build_runner_profile(
        training_history=build_training_history([], REF),
        training_load=build_training_load(activities=[], reference_date=REF),
        reference_date=REF,
    )
    plan: WeeklyPlan = build_weekly_plan(
        weekly_target=weekly_target,
        runner_profile=profile,
        plan_goal=goal,
        periodization=periodization,
        reference_date=REF,
    )
    long_runs = [s.distance_km for s in plan.sessions if s.workout_type == "long_easy" and s.distance_km is not None]
    assert long_runs
    assert max(long_runs) <= 5.0

    _, _, _, deep_plan = _pipeline(_activity(60, 5.0), goal_type="half_marathon")
    assert deep_plan.planned_km is None
    assert all(session.distance_km is None for session in deep_plan.sessions if session.workout_type != "rest")


def test_weekly_reconciliation_is_monotone():
    original = WeeklyTarget(
        reference_date=REF,
        target_basis="distance",
        target_km=18.0,
        target_duration_minutes=None,
        target_sessions=4,
        allow_intensity=False,
        confidence="medium",
        continuity_state="partial_reprise",
        reason_codes=(),
    )

    result = build_weekly_reconciliation(
        proposed_target=original,
        recent_response=None,
    )

    assert result.reconciled_target.target_sessions <= original.target_sessions
    assert result.reconciled_target.target_km <= original.target_km
