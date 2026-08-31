from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.periodization import PeriodizationMode, PeriodizationPhase, PeriodizationSnapshot
from training_v2.plan_goal import GoalType, build_plan_goal
from training_v2.runner_profile import RunnerProfile
from training_v2.weekly_target import WeeklyTarget
from training_v2.workout_generator import WorkoutPrescription, WeeklyPlan, build_weekly_plan
from training_v2.week_plan_bridge import build_weekly_plan_from_workouts


REF = date(2026, 8, 11)


def _runner_profile() -> RunnerProfile:
    return RunnerProfile(
        reference_date=REF,
        age=35,
        sex="male",
        primary_discipline="road",
        experience_level="established",
        typical_weekly_km=40.0,
        typical_weekly_km_is_observed=True,
        typical_weekly_hours=None,
        typical_runs_per_week=4.0,
        typical_long_run_km=None,
        typical_speed_kmh=None,
        available_history_days=120,
        profile_confidence="medium",
        vo2max=None,
        vma_kmh=None,
        max_hr=None,
        resting_hr=None,
        has_hrv=False,
        has_vo2max=False,
        has_training_readiness=False,
        has_power=False,
        has_running_dynamics=False,
        preferred_days_per_week=4,
        max_days_per_week=5,
        preferred_long_run_day=None,
        injury_constraints=[],
        availability_constraints=[],
    )


def _weekly_target() -> WeeklyTarget:
    return WeeklyTarget(
        reference_date=REF,
        target_basis="distance",
        target_km=40.0,
        target_duration_minutes=None,
        target_sessions=4,
        allow_intensity=True,
        confidence="medium",
        continuity_state="normal",
        reason_codes=(),
    )


def _periodization() -> PeriodizationSnapshot:
    return PeriodizationSnapshot(
        reference_date=REF,
        phase=PeriodizationPhase.build,
        mode=PeriodizationMode.continuous,
        weeks_to_race=None,
        phase_start_date=None,
        phase_end_date=None,
        cycle_week=None,
        cycle_length_weeks=None,
        reason_codes=(),
    )


def _build(goal_type: GoalType, target_time_seconds: int | None) -> WeeklyPlan:
    plan_goal = build_plan_goal(
        goal_type=goal_type,
        target_time_seconds=target_time_seconds,
        created_from="user",
    )
    return build_weekly_plan(
        weekly_target=_weekly_target(),
        runner_profile=_runner_profile(),
        plan_goal=plan_goal,
        periodization=_periodization(),
        reference_date=REF,
    )


def _running_signature(plan: WeeklyPlan) -> tuple[tuple[str, str, float | None], ...]:
    return tuple(
        (s.day, s.workout_type, s.distance_km)
        for s in plan.sessions
        if s.workout_type != "rest"
    )


def _activity(days_ago: int, km: float) -> dict:
    return {
        "activity_type": "running",
        "start_time": f"2026-08-{max(1, 11 - days_ago):02d}T08:00:00+00:00",
        "distance_m": km * 1000.0,
        "duration_s": max(1.0, km * 360.0),
    }


def test_10k_without_target_time_keeps_baseline():
    base = _build(GoalType.ten_k, None)
    realistic_neutral = _build(GoalType.ten_k, 50 * 60)
    assert _running_signature(base) == _running_signature(realistic_neutral)
    assert "target_time_profile_aggressive" not in base.reason_codes
    assert "target_time_profile_conservative" not in base.reason_codes


def test_10k_two_target_times_change_prescription():
    fast = _build(GoalType.ten_k, 42 * 60)
    slow = _build(GoalType.ten_k, 62 * 60)
    assert _running_signature(fast) != _running_signature(slow)
    assert "target_time_profile_aggressive" in fast.reason_codes
    assert "target_time_profile_conservative" in slow.reason_codes


def test_semi_two_target_times_change_prescription():
    fast = _build(GoalType.half_marathon, 95 * 60)
    slow = _build(GoalType.half_marathon, 140 * 60)
    assert _running_signature(fast) != _running_signature(slow)
    assert "target_time_profile_aggressive" in fast.reason_codes
    assert "target_time_profile_conservative" in slow.reason_codes


def test_maintenance_never_uses_target_time():
    import pytest

    with pytest.raises(ValueError):
        build_plan_goal(
            goal_type=GoalType.maintenance,
            target_time_seconds=3600,
            created_from="user",
        )


def test_bridge_propagates_target_time_seconds_to_workout_generator():
    captured: dict = {}

    def _fake_build_weekly_plan(*, plan_goal, **kwargs):
        captured["target_time_seconds"] = plan_goal.target_time_seconds
        weekly_target = _weekly_target()
        sessions = tuple(
            WorkoutPrescription(
                day=d,
                workout_type="rest",
                intensity_class="rest",
                distance_km=None,
                duration_minutes=None,
                reason_codes=(),
            )
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        )
        weekly_plan = WeeklyPlan(
            reference_date=REF,
            target_basis="distance",
            planned_km=0.0,
            planned_duration_minutes=None,
            session_count=0,
            sessions=sessions,
            allow_intensity=True,
            reason_codes=(),
        )
        return weekly_plan

    workouts = [_activity(days, 8.0) for days in (3, 6, 9, 12, 15, 18, 24, 31, 38)]
    with patch("training_v2.week_plan_bridge.build_weekly_plan", side_effect=_fake_build_weekly_plan):
        _, _ = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="10K",
            race_date=None,
            cycle_start_date=REF,
            reference_date=REF,
            target_time_seconds=3000,
        )

    assert captured["target_time_seconds"] == 3000


def test_bridge_without_target_time_does_not_synthesize_seconds():
    captured: dict = {}

    def _fake_build_weekly_plan(*, plan_goal, **kwargs):
        captured["target_time_seconds"] = plan_goal.target_time_seconds
        return _build(GoalType.ten_k, None)

    workouts = [_activity(days, 8.0) for days in (3, 6, 9, 12, 15, 18, 24, 31, 38)]
    with patch("training_v2.week_plan_bridge.build_weekly_plan", side_effect=_fake_build_weekly_plan):
        _, _ = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="10K",
            race_date=None,
            cycle_start_date=REF,
            reference_date=REF,
            target_time_seconds=None,
        )

    assert captured["target_time_seconds"] is None
