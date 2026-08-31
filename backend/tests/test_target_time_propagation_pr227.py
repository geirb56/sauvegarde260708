from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.periodization import PeriodizationMode, PeriodizationPhase, PeriodizationSnapshot
from training_v2.plan_goal import GoalType, build_plan_goal
from training_v2.runner_profile import RunnerProfile
from training_v2.weekly_target import WeeklyTarget
from training_v2.workout_generator import WorkoutPrescription, WeeklyPlan, build_weekly_plan


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


def _make_db(cycle: dict, user_goal: dict | None):
    db = MagicMock()

    async def _cycle_find_one(*args, **kwargs):
        return cycle

    async def _goal_find_one(*args, **kwargs):
        return user_goal

    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    db.garmin_activities.find = MagicMock(return_value=cursor)
    db.training_cycles.find_one = _cycle_find_one
    db.user_goals.find_one = _goal_find_one
    return db


def _run(coro):
    return asyncio.run(coro)


def test_10k_without_target_time_keeps_baseline():
    base = _build(GoalType.ten_k, None)
    no_target = _build(GoalType.ten_k, None)
    assert _running_signature(base) == _running_signature(no_target)
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


def test_week_endpoint_propagates_target_time_minutes_to_engine_seconds():
    import server as srv

    cycle = {"goal": "10K", "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    user_goal = {
        "distance_type": "10k",
        "event_date": "2027-06-01",
        "target_time_minutes": 50,
    }
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    captured: dict = {}

    def _fake_build_weekly_plan_from_workouts(**kwargs):
        captured.update(kwargs)
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
        return weekly_target, weekly_plan

    async def _call():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                with patch("training_v2.week_plan_bridge.build_weekly_plan_from_workouts", side_effect=_fake_build_weekly_plan_from_workouts):
                    return await srv.get_training_v2_week(user={"id": "u1"})

    result = _run(_call())
    assert result["goal"]["target_time_seconds"] == 3000
    assert captured["target_time_seconds"] == 3000


def test_week_endpoint_without_target_time_does_not_synthesize_seconds():
    import server as srv

    cycle = {"goal": "10K", "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    user_goal = {"distance_type": "10k", "event_date": "2027-06-01"}
    mock_db = _make_db(cycle=cycle, user_goal=user_goal)
    captured: dict = {}

    def _fake_build_weekly_plan_from_workouts(**kwargs):
        captured.update(kwargs)
        return _weekly_target(), _build(GoalType.ten_k, None)

    async def _call():
        with patch.object(srv, "db", mock_db):
            with patch.object(srv, "mongo_garmin_activities_to_domain", return_value=[]):
                with patch("training_v2.week_plan_bridge.build_weekly_plan_from_workouts", side_effect=_fake_build_weekly_plan_from_workouts):
                    return await srv.get_training_v2_week(user={"id": "u1"})

    result = _run(_call())
    assert result["goal"]["target_time_seconds"] is None
    assert captured["target_time_seconds"] is None
