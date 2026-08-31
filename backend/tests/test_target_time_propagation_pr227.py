from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.periodization import (
    PeriodizationMode,
    PeriodizationPhase,
    PeriodizationSnapshot,
    build_periodization,
)
from training_v2.plan_goal import GoalType, build_plan_goal
from training_v2.runner_profile import RunnerProfile
from training_v2.training_paces import PaceRange, PaceValue, TrainingPaces, VdotResult
from training_v2.week_plan_bridge import (
    _equivalent_time_seconds_from_vdot,
    build_weekly_plan_from_workouts,
)
from training_v2.weekly_target import WeeklyTarget
from training_v2.workout_generator import WeeklyPlan, build_weekly_plan


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


def _weekly_target(
    *,
    continuity_state: str = "normal",
    allow_intensity: bool = True,
) -> WeeklyTarget:
    return WeeklyTarget(
        reference_date=REF,
        target_basis="distance",
        target_km=40.0,
        target_duration_minutes=None,
        target_sessions=4,
        allow_intensity=allow_intensity,
        confidence="medium",
        continuity_state=continuity_state,
        reason_codes=(),
    )


def _periodization(phase: PeriodizationPhase = PeriodizationPhase.build) -> PeriodizationSnapshot:
    return PeriodizationSnapshot(
        reference_date=REF,
        phase=phase,
        mode=PeriodizationMode.continuous,
        weeks_to_race=None,
        phase_start_date=None,
        phase_end_date=None,
        cycle_week=None,
        cycle_length_weeks=None,
        reason_codes=(),
    )


def _build_direct(
    *,
    goal_type: GoalType,
    target_time_seconds: int | None,
    capability_time_seconds: int | None,
    continuity_state: str = "normal",
    allow_intensity: bool = True,
    phase: PeriodizationPhase = PeriodizationPhase.build,
) -> WeeklyPlan:
    plan_goal = build_plan_goal(
        goal_type=goal_type,
        target_time_seconds=target_time_seconds,
        created_from="user",
    )
    return build_weekly_plan(
        weekly_target=_weekly_target(continuity_state=continuity_state, allow_intensity=allow_intensity),
        runner_profile=_runner_profile(),
        plan_goal=plan_goal,
        periodization=_periodization(phase),
        reference_date=REF,
        target_capability_time_seconds=capability_time_seconds,
    )


def _running_signature(plan: WeeklyPlan) -> tuple[tuple[str, str, float | None], ...]:
    return tuple(
        (s.day, s.workout_type, s.distance_km)
        for s in plan.sessions
        if s.workout_type != "rest"
    )


def _activity(km: float, duration_s: float) -> dict:
    return {
        "activity_type": "running",
        "start_time": "2026-08-01T08:00:00+00:00",
        "distance_m": km * 1000.0,
        "duration_s": duration_s,
    }


def _paces_from_vdot(vdot: float, confidence: str) -> TrainingPaces:
    return TrainingPaces(
        reference_date=REF,
        vdot_result=VdotResult(
            reference_vdot=vdot,
            paces_confidence=confidence.lower(),
            evidence_count=2,
            high_count=2 if confidence == "HIGH" else 0,
            medium_count=2 if confidence == "MEDIUM" else 0,
            concordant=True,
            reason="test",
        ),
        confidence=confidence,
        easy=PaceRange(
            lower=PaceValue(min_per_km=5.2, km_per_hour=11.54),
            upper=PaceValue(min_per_km=5.6, km_per_hour=10.71),
        ),
        marathon=PaceValue(min_per_km=4.5, km_per_hour=13.33),
        threshold=PaceValue(min_per_km=4.2, km_per_hour=14.29),
        interval=PaceRange(
            lower=PaceValue(min_per_km=3.9, km_per_hour=15.38),
            upper=PaceValue(min_per_km=4.1, km_per_hour=14.63),
        ),
        repetition=PaceValue(min_per_km=3.7, km_per_hour=16.22),
        reason="test",
    )


def _assert_distance_goal_modulation(goal_type: GoalType) -> None:
    plan_goal = build_plan_goal(goal_type=goal_type, target_time_seconds=1, created_from="user")
    cap = _equivalent_time_seconds_from_vdot(
        target_distance_km=plan_goal.target_distance_km,
        vdot=50.0,
    )
    assert cap is not None

    aggressive = _build_direct(
        goal_type=goal_type,
        target_time_seconds=int(cap * 0.95),
        capability_time_seconds=cap,
    )
    conservative = _build_direct(
        goal_type=goal_type,
        target_time_seconds=int(cap * 1.05),
        capability_time_seconds=cap,
    )
    assert "target_time_profile_aggressive" in aggressive.reason_codes
    assert "target_time_profile_conservative" in conservative.reason_codes


def test_5k_daniels_capability_vs_target_time():
    _assert_distance_goal_modulation(GoalType.five_k)


def test_10k_daniels_capability_vs_target_time():
    _assert_distance_goal_modulation(GoalType.ten_k)


def test_semi_daniels_capability_vs_target_time():
    _assert_distance_goal_modulation(GoalType.half_marathon)


def test_marathon_daniels_capability_vs_target_time():
    _assert_distance_goal_modulation(GoalType.marathon)


def test_same_target_time_two_vdot_levels_different_classification():
    workouts = [_activity(10.0, 48 * 60)]
    forced_state = type("TS", (), {"continuity_state": "normal", "overall_confidence": "medium"})()

    with patch(
        "training_v2.week_plan_bridge.compute_training_paces",
        side_effect=[
            _paces_from_vdot(44.0, "HIGH"),
            _paces_from_vdot(58.0, "HIGH"),
        ],
    ), patch("training_v2.week_plan_bridge.build_training_state", return_value=forced_state), patch(
        "training_v2.week_plan_bridge.build_weekly_target",
        return_value=_weekly_target(),
    ):
        _, runner_low_vdot = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="10K",
            race_date=None,
            cycle_start_date=REF,
            reference_date=REF,
            target_time_seconds=50 * 60,
        )
        _, runner_high_vdot = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="10K",
            race_date=None,
            cycle_start_date=REF,
            reference_date=REF,
            target_time_seconds=50 * 60,
        )

    assert "target_time_profile_aggressive" in runner_low_vdot.reason_codes
    assert "target_time_profile_conservative" in runner_high_vdot.reason_codes


def test_low_and_insufficient_confidence_disable_target_time_modulation():
    baseline = _build_direct(
        goal_type=GoalType.ten_k,
        target_time_seconds=None,
        capability_time_seconds=None,
    )

    workouts = [_activity(10.0, 48 * 60)]
    forced_state = type("TS", (), {"continuity_state": "normal", "overall_confidence": "medium"})()
    for confidence in ("LOW", "INSUFFICIENT"):
        with patch(
            "training_v2.week_plan_bridge.compute_training_paces",
            return_value=_paces_from_vdot(50.0, confidence),
        ), patch("training_v2.week_plan_bridge.build_training_state", return_value=forced_state), patch(
            "training_v2.week_plan_bridge.build_weekly_target",
            return_value=_weekly_target(),
        ):
            _, plan = build_weekly_plan_from_workouts(
                workouts=workouts,
                goal_type="10K",
                race_date=None,
                cycle_start_date=REF,
                reference_date=REF,
                target_time_seconds=42 * 60,
            )
        assert _running_signature(plan) == _running_signature(baseline)
        assert "target_time_profile_aggressive" not in plan.reason_codes
        assert "target_time_profile_conservative" not in plan.reason_codes


def test_ultra_target_time_modulation_explicitly_disabled():
    baseline = _build_direct(
        goal_type=GoalType.ultra,
        target_time_seconds=None,
        capability_time_seconds=None,
    )
    with_target = _build_direct(
        goal_type=GoalType.ultra,
        target_time_seconds=6 * 3600,
        capability_time_seconds=5 * 3600,
    )
    assert _running_signature(with_target) == _running_signature(baseline)
    assert "target_time_profile_aggressive" not in with_target.reason_codes
    assert "target_time_profile_conservative" not in with_target.reason_codes


def test_target_time_without_race_date_keeps_continuous_periodization():
    goal_no_race = build_plan_goal(
        goal_type=GoalType.ten_k,
        target_time_seconds=50 * 60,
        race_date=None,
        created_from="user",
    )
    snap = build_periodization(
        goal_no_race,
        REF,
        cycle_anchor_date=date(2026, 1, 1),
    )
    assert snap.mode == PeriodizationMode.continuous
    assert snap.phase != PeriodizationPhase.taper
    assert snap.phase != PeriodizationPhase.race


def test_adding_race_date_reenables_race_periodization():
    goal_with_race = build_plan_goal(
        goal_type=GoalType.ten_k,
        target_time_seconds=50 * 60,
        race_date=date(2026, 9, 30),
        created_from="user",
    )
    snap = build_periodization(
        goal_with_race,
        REF,
        race_plan_start_date=date(2026, 7, 1),
    )
    assert snap.mode == PeriodizationMode.race_calendar


def test_target_time_without_value_keeps_baseline_unchanged():
    baseline = _build_direct(
        goal_type=GoalType.ten_k,
        target_time_seconds=None,
        capability_time_seconds=3000,
    )
    without_target = _build_direct(
        goal_type=GoalType.ten_k,
        target_time_seconds=None,
        capability_time_seconds=3000,
    )
    assert _running_signature(without_target) == _running_signature(baseline)
