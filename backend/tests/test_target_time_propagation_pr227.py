from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.periodization import PeriodizationMode, PeriodizationPhase, PeriodizationSnapshot
from training_v2.plan_goal import GoalType, build_plan_goal
from training_v2.runner_profile import RunnerProfile
from training_v2.training_paces import PaceRange, PaceValue, TrainingPaces, VdotResult
from training_v2.weekly_target import WeeklyTarget
from training_v2.workout_generator import WeeklyPlan, build_weekly_plan
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


def _build(
    *,
    goal_type: GoalType,
    target_time_seconds: int | None,
    capability_pace_seconds_per_km: float | None,
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
        target_capability_pace_seconds_per_km=capability_pace_seconds_per_km,
    )


def _running_signature(plan: WeeklyPlan) -> tuple[tuple[str, str, float | None], ...]:
    return tuple(
        (s.day, s.workout_type, s.distance_km)
        for s in plan.sessions
        if s.workout_type != "rest"
    )


def _count_types(plan: WeeklyPlan, kind: str) -> int:
    return sum(1 for s in plan.sessions if s.workout_type == kind)


def _activity(km: float, duration_s: float) -> dict:
    return {
        "activity_type": "running",
        "start_time": "2026-08-01T08:00:00+00:00",
        "distance_m": km * 1000.0,
        "duration_s": duration_s,
    }


def _paces_with_threshold_seconds_per_km(
    threshold_seconds_per_km: float,
    *,
    confidence: str = "HIGH",
) -> TrainingPaces:
    threshold_min_per_km = threshold_seconds_per_km / 60.0
    marathon_min_per_km = threshold_min_per_km + 0.3
    easy_lower = threshold_min_per_km + 0.8
    easy_upper = threshold_min_per_km + 1.2
    return TrainingPaces(
        reference_date=REF,
        vdot_result=VdotResult(
            reference_vdot=50.0,
            paces_confidence=confidence.lower(),
            evidence_count=2,
            high_count=2 if confidence == "HIGH" else 0,
            medium_count=2 if confidence == "MEDIUM" else 0,
            concordant=True,
            reason="test",
        ),
        confidence=confidence,
        easy=PaceRange(
            lower=PaceValue(min_per_km=easy_lower, km_per_hour=60.0 / easy_lower),
            upper=PaceValue(min_per_km=easy_upper, km_per_hour=60.0 / easy_upper),
        ),
        marathon=PaceValue(min_per_km=marathon_min_per_km, km_per_hour=60.0 / marathon_min_per_km),
        threshold=PaceValue(min_per_km=threshold_min_per_km, km_per_hour=60.0 / threshold_min_per_km),
        interval=PaceRange(
            lower=PaceValue(min_per_km=threshold_min_per_km - 0.3, km_per_hour=60.0 / (threshold_min_per_km - 0.3)),
            upper=PaceValue(min_per_km=threshold_min_per_km - 0.1, km_per_hour=60.0 / (threshold_min_per_km - 0.1)),
        ),
        repetition=PaceValue(min_per_km=threshold_min_per_km - 0.5, km_per_hour=60.0 / (threshold_min_per_km - 0.5)),
        reason="test",
    )


def test_10k_aggressive_when_target_faster_than_observed_capability():
    plan = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=42 * 60,
        capability_pace_seconds_per_km=300.0,
    )
    assert "target_time_profile_aggressive" in plan.reason_codes


def test_10k_conservative_when_target_slower_than_observed_capability():
    plan = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=62 * 60,
        capability_pace_seconds_per_km=300.0,
    )
    assert "target_time_profile_conservative" in plan.reason_codes


def test_insufficient_capability_does_not_alter_prescription():
    no_target = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=None,
        capability_pace_seconds_per_km=None,
    )
    with_target_but_no_cap = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=45 * 60,
        capability_pace_seconds_per_km=None,
    )
    assert _running_signature(no_target) == _running_signature(with_target_but_no_cap)
    assert "target_time_profile_aggressive" not in with_target_but_no_cap.reason_codes
    assert "target_time_profile_conservative" not in with_target_but_no_cap.reason_codes


def test_same_target_time_two_runners_can_be_classified_differently():
    slow_runner = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=50 * 60,
        capability_pace_seconds_per_km=330.0,
    )
    fast_runner = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=50 * 60,
        capability_pace_seconds_per_km=270.0,
    )

    assert "target_time_profile_aggressive" in slow_runner.reason_codes
    assert "target_time_profile_conservative" in fast_runner.reason_codes


def test_bridge_uses_canonical_paces_for_target_time_modulation():
    workouts = [_activity(10.0, 50 * 60)]
    forced_state = type(
        "TS",
        (),
        {"continuity_state": "normal", "overall_confidence": "medium"},
    )()
    with patch(
        "training_v2.week_plan_bridge.compute_training_paces",
        return_value=_paces_with_threshold_seconds_per_km(300.0, confidence="HIGH"),
    ), patch(
        "training_v2.week_plan_bridge.build_training_state",
        return_value=forced_state,
    ), patch(
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
    assert "target_time_profile_aggressive" in plan.reason_codes


def test_taper_aggressive_target_does_not_reintroduce_steady_or_quality():
    plan = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=42 * 60,
        capability_pace_seconds_per_km=300.0,
        phase=PeriodizationPhase.taper,
    )
    assert _count_types(plan, "quality") == 0
    assert _count_types(plan, "steady") == 0


def test_race_aggressive_target_keeps_race_week_unchanged():
    baseline = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=None,
        capability_pace_seconds_per_km=300.0,
        phase=PeriodizationPhase.race,
    )
    aggressive = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=42 * 60,
        capability_pace_seconds_per_km=300.0,
        phase=PeriodizationPhase.race,
    )
    assert _running_signature(baseline) == _running_signature(aggressive)


def test_reprise_target_time_keeps_protections_unchanged():
    baseline = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=None,
        capability_pace_seconds_per_km=300.0,
        continuity_state="partial_reprise",
        allow_intensity=False,
    )
    aggressive = _build(
        goal_type=GoalType.ten_k,
        target_time_seconds=42 * 60,
        capability_pace_seconds_per_km=300.0,
        continuity_state="partial_reprise",
        allow_intensity=False,
    )
    assert _running_signature(baseline) == _running_signature(aggressive)
    assert _count_types(aggressive, "quality") == 0
    assert _count_types(aggressive, "steady") == 0


def test_without_target_time_baseline_is_unchanged():
    baseline = _build(
        goal_type=GoalType.half_marathon,
        target_time_seconds=None,
        capability_pace_seconds_per_km=330.0,
    )
    no_target_again = _build(
        goal_type=GoalType.half_marathon,
        target_time_seconds=None,
        capability_pace_seconds_per_km=330.0,
    )
    assert _running_signature(baseline) == _running_signature(no_target_again)
