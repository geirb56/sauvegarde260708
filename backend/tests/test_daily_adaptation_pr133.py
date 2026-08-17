"""PR133 — Tests for DailyAdaptation V2."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.daily_adaptation import (  # noqa: E402
    SHORTEN_FACTOR,
    DailyAdaptationAction,
    DailyAdaptationResult,
    build_daily_adaptation,
)
from training_v2.readiness import ReadinessConfidence, ReadinessResult  # noqa: E402
from training_v2.readiness_sufficiency import SufficiencyLevel  # noqa: E402
from training_v2.training_load import TrainingLoadSnapshot  # noqa: E402
from training_v2.training_response import RecentTrainingResponse  # noqa: E402
from training_v2.workout_generator import WorkoutPrescription  # noqa: E402

REF = date(2026, 8, 17)
SOURCE = Path(__file__).resolve().parents[1] / "training_v2" / "daily_adaptation.py"


def _workout(
    workout_type: str,
    *,
    distance_km: float | None = None,
    duration_minutes: int | None = None,
    day: str = "monday",
) -> WorkoutPrescription:
    intensity = {
        "rest": "rest",
        "recovery": "low",
        "easy": "low",
        "steady": "moderate",
        "quality": "high",
        "long_easy": "low",
    }[workout_type]
    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class=intensity,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=("ORIGINAL_PLAN",),
    )


def _readiness(score: float | None, *, confidence: ReadinessConfidence = ReadinessConfidence.NORMAL) -> ReadinessResult:
    if score is None:
        return ReadinessResult(
            score=None,
            confidence=ReadinessConfidence.NONE,
            sufficiency_level=SufficiencyLevel.INSUFFICIENT,
            reasons=(),
        )
    return ReadinessResult(
        score=score,
        confidence=confidence,
        sufficiency_level=SufficiencyLevel.SUFFICIENT,
        reasons=(),
    )


def _load(status: str, *, acwr: float | None = 1.0) -> TrainingLoadSnapshot:
    return TrainingLoadSnapshot(
        reference_date=REF,
        acute_load_7d=300.0,
        load_28d=1200.0,
        chronic_weekly_load=300.0,
        acwr=acwr if status != "unavailable" else None,
        status=status,
        is_available=status != "unavailable",
        has_sufficient_history=True,
        confidence="high",
        activities_7d=4,
        activities_28d=12,
        previous_7d_load=280.0,
        load_change_percent=7.1,
    )


def _response(
    *,
    response_status: str = "sufficient",
    confidence: str = "moderate",
    volume_trend: str = "stable",
    frequency_pattern: str = "stable",
    long_run_trend: str = "stable",
    cardiac_efficiency_trend: str = "stable",
    intensity_exposure_trend: str = "stable",
) -> RecentTrainingResponse:
    return RecentTrainingResponse(
        reference_date=REF,
        window_days=28,
        available_running_activities=6 if response_status == "sufficient" else 2,
        selected_running_activities=6 if response_status == "sufficient" else 2,
        response_status=response_status,
        confidence=confidence,
        observed_distance_km=48.0,
        observed_duration_minutes=260.0,
        observed_runs=6 if response_status == "sufficient" else 2,
        observed_runs_per_week=1.5 if response_status == "sufficient" else 0.5,
        longest_run_km=16.0,
        longest_run_duration_minutes=95.0,
        hr_coverage_count=6 if response_status == "sufficient" else 0,
        intensity_coverage_count=6 if response_status == "sufficient" else 0,
        average_hr_recent=145.0 if response_status == "sufficient" else None,
        average_pace_recent_s_per_km=320.0,
        cardiac_efficiency_samples=(0.02,) * (6 if response_status == "sufficient" else 2),
        cardiac_efficiency_trend=cardiac_efficiency_trend,
        volume_trend=volume_trend,
        frequency_pattern=frequency_pattern,
        long_run_trend=long_run_trend,
        intensity_exposure_trend=intensity_exposure_trend,
        reason_codes=(),
    )


def test_A_rest_stays_rest():
    result = build_daily_adaptation(
        workout=_workout("rest"),
        readiness=_readiness(20.0),
        training_load=_load("high", acwr=1.7),
        recent_response=_response(volume_trend="decreasing"),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout.workout_type == "rest"
    assert result.adapted_workout.distance_km is None
    assert result.adapted_workout.duration_minutes is None


def test_B_easy_with_normal_signals_kept():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(82.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout == result.original_workout


def test_C_quality_with_normal_signals_kept():
    result = build_daily_adaptation(
        workout=_workout("quality", distance_km=8.0),
        readiness=_readiness(85.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP


def test_D_quality_with_readiness_defavorable_becomes_easy():
    result = build_daily_adaptation(
        workout=_workout("quality", distance_km=8.0),
        readiness=_readiness(50.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.EASY_DOWNGRADE
    assert result.adapted_workout.workout_type == "easy"
    assert result.adapted_workout.distance_km == 8.0
    assert result.adapted_workout.distance_km <= result.original_workout.distance_km


def test_E_steady_with_readiness_defavorable_becomes_easy():
    result = build_daily_adaptation(
        workout=_workout("steady", duration_minutes=50),
        readiness=_readiness(52.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.EASY_DOWNGRADE
    assert result.adapted_workout.workout_type == "easy"
    assert result.adapted_workout.duration_minutes == 50


def test_F_easy_moderate_adaptation_shortens():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=10.0),
        readiness=_readiness(65.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.SHORTEN
    assert result.adapted_workout.distance_km == 7.0


def test_G_long_easy_moderate_adaptation_shortens():
    result = build_daily_adaptation(
        workout=_workout("long_easy", duration_minutes=60),
        readiness=_readiness(60.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.SHORTEN
    assert result.adapted_workout.duration_minutes == 42
    assert "LONG_EASY_PROTECTED" in result.reason_codes


def test_H_very_unfavorable_daily_signal_rests():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(35.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.REST
    assert result.adapted_workout.workout_type == "rest"


def test_I_readiness_unavailable_does_not_auto_rest():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(None),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert "READINESS_UNAVAILABLE" in result.reason_codes


def test_J_recent_response_insufficient_adds_reason_only():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(80.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(response_status="insufficient", confidence="low"),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert "RECENT_RESPONSE_INSUFFICIENT" in result.reason_codes
    assert "RECENT_RESPONSE_CAUTION" not in result.reason_codes


def test_K_training_load_unavailable_is_not_zero():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(80.0),
        training_load=_load("unavailable", acwr=None),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert "TRAINING_LOAD_UNAVAILABLE" in result.reason_codes


def test_L_excellent_readiness_never_increases():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(90.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout.distance_km == 8.0


def test_M_favorable_recent_response_never_increases():
    result = build_daily_adaptation(
        workout=_workout("quality", duration_minutes=45),
        readiness=_readiness(82.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(
            volume_trend="increasing",
            frequency_pattern="increasing",
            long_run_trend="increasing",
            cardiac_efficiency_trend="increasing",
            intensity_exposure_trend="stable",
        ),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout.duration_minutes == 45


def test_N_favorable_training_load_never_increases():
    result = build_daily_adaptation(
        workout=_workout("easy", duration_minutes=50),
        readiness=_readiness(82.0),
        training_load=_load("low", acwr=0.7),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout.duration_minutes == 50


def test_O_quality_distance_downgrade_never_exceeds_original():
    result = build_daily_adaptation(
        workout=_workout("quality", distance_km=8.0),
        readiness=_readiness(65.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.EASY_DOWNGRADE
    assert result.adapted_workout.workout_type == "easy"
    assert result.adapted_workout.distance_km <= 8.0


def test_P_sixty_minutes_shorten_uses_factor_070():
    result = build_daily_adaptation(
        workout=_workout("easy", duration_minutes=60),
        readiness=_readiness(65.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert SHORTEN_FACTOR == pytest.approx(0.70)
    assert result.adapted_workout.duration_minutes == 42


def test_Q_ten_km_shorten_uses_factor_070():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=10.0),
        readiness=_readiness(65.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.adapted_workout.distance_km == 7.0


def test_R_original_workout_is_not_mutated():
    workout = _workout("quality", distance_km=8.0, duration_minutes=50)
    result = build_daily_adaptation(
        workout=workout,
        readiness=_readiness(50.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert workout.workout_type == "quality"
    assert workout.distance_km == 8.0
    assert workout.duration_minutes == 50
    assert result.adapted_workout != workout


def test_S_same_inputs_same_result():
    kwargs = dict(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(65.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    first = build_daily_adaptation(**kwargs)
    second = build_daily_adaptation(**kwargs)
    assert first == second


def test_TUVWXYZ_AB_AC_forbidden_dependencies_and_terms_absent():
    source = SOURCE.read_text(encoding="utf-8")
    lowered = source.lower()
    forbidden_imports = [
        "garmin",
        "gccli",
        "redis",
        "requests",
        "random",
        "training_engine",
    ]
    for item in forbidden_imports:
        assert f"import {item}" not in lowered
        assert f"from {item}" not in lowered

    forbidden_terms = [
        "datetime.now(",
        "date.today(",
        "LT1",
        "LT2",
        "TRIMP",
        "TSS",
        "CTL",
        "ATL",
        "TSB",
        "fatigue_ratio",
        "MOVE",
        "build_weekly_target",
    ]
    for item in forbidden_terms:
        assert item not in source


def test_conflict_readiness_good_plus_training_load_high_keeps():
    result = build_daily_adaptation(
        workout=_workout("quality", distance_km=8.0),
        readiness=_readiness(82.0),
        training_load=_load("high", acwr=1.7),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert "TRAINING_LOAD_HIGH" in result.reason_codes


def test_conflict_readiness_low_plus_recent_response_favorable_still_reduces():
    result = build_daily_adaptation(
        workout=_workout("quality", distance_km=8.0),
        readiness=_readiness(50.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(
            volume_trend="increasing",
            frequency_pattern="increasing",
            long_run_trend="increasing",
            cardiac_efficiency_trend="increasing",
        ),
    )
    assert result.action == DailyAdaptationAction.EASY_DOWNGRADE


def test_conflict_readiness_unavailable_plus_normal_load_plus_stable_response_keeps():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(None),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP


def test_conflict_readiness_normal_plus_recent_response_unfavorable_generally_keeps():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(82.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(volume_trend="decreasing"),
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert "RECENT_RESPONSE_CAUTION" in result.reason_codes


def test_result_contract_is_immutable_and_action_enum_is_closed():
    result = build_daily_adaptation(
        workout=_workout("easy", distance_km=8.0),
        readiness=_readiness(82.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert isinstance(result, DailyAdaptationResult)
    assert {item.value for item in DailyAdaptationAction} == {
        "KEEP",
        "EASY_DOWNGRADE",
        "SHORTEN",
        "REST",
    }
