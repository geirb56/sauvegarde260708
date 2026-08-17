"""PR133 — DailyAdaptation V2: cautious same-day workout adaptation.

Design rules
------------
- PURE: no DB, no Garmin, no HTTP, no Redis, no LLM, no random, no global
  mutable state, no datetime.now()/date.today().
- Consumes existing V2 contracts only: WorkoutPrescription, ReadinessResult,
  TrainingLoadSnapshot, RecentTrainingResponse.
- Adapts the planned workout for TODAY only.  It does NOT rebuild the weekly
  plan, recalculate WeeklyTarget, or change structural training volume/frequency.
- Asymmetric rule: can keep or reduce, never increase.
- None ≠ 0 throughout: unavailable readiness/load/response never becomes a bad
  score automatically.
- PRODUCT CALIBRATION V1 — SHORTEN_FACTOR is recalibrable, not a physiological law.

Readiness interpretation on current main
----------------------------------------
ReadinessResult does not expose a dedicated adaptation recommendation contract.
PR133 therefore reuses the readiness score bands already present on main:

- score >= 75         -> favorable
- 55 <= score < 75    -> caution / easy-only reduction
- 40 <= score < 55    -> low / stronger reduction
- score < 40          -> very low / REST
- score is None       -> unavailable

Run from the backend directory
------------------------------
    python -m pytest tests/test_daily_adaptation_pr133.py -q
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .readiness import ReadinessResult
from .training_load import TrainingLoadSnapshot
from .training_response import RecentTrainingResponse
from .workout_generator import WorkoutPrescription

# PRODUCT CALIBRATION V1 — RECALIBRABLE — NOT PHYSIOLOGICAL LAW
SHORTEN_FACTOR: float = 0.70

# Existing score bands already used on main for readiness-derived decisions.
_READINESS_FAVORABLE_MIN = 75.0
_READINESS_CAUTION_MIN = 55.0
_READINESS_VERY_LOW_MAX = 40.0


class DailyAdaptationAction(str, Enum):
    KEEP = "KEEP"
    EASY_DOWNGRADE = "EASY_DOWNGRADE"
    SHORTEN = "SHORTEN"
    REST = "REST"


class DailyAdaptationResult(BaseModel):
    """Immutable result of a same-day adaptation decision."""

    model_config = ConfigDict(frozen=True)

    action: DailyAdaptationAction
    original_workout: WorkoutPrescription
    adapted_workout: WorkoutPrescription
    reason_codes: Tuple[str, ...]


def _dedupe_codes(codes: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return tuple(ordered)


def _readiness_band(readiness: Optional[ReadinessResult]) -> str:
    score = readiness.score if readiness is not None else None
    if score is None:
        return "unavailable"
    if score >= _READINESS_FAVORABLE_MIN:
        return "favorable"
    if score >= _READINESS_CAUTION_MIN:
        return "caution"
    if score >= _READINESS_VERY_LOW_MAX:
        return "low"
    return "very_low"


def _load_status(training_load: Optional[TrainingLoadSnapshot]) -> str:
    if training_load is None or training_load.status == "unavailable":
        return "unavailable"
    return training_load.status


def _recent_response_codes(recent_response: Optional[RecentTrainingResponse]) -> list[str]:
    if recent_response is None or recent_response.response_status == "unavailable":
        return ["RECENT_RESPONSE_UNAVAILABLE"]
    if recent_response.response_status == "insufficient":
        return ["RECENT_RESPONSE_INSUFFICIENT"]

    if any(
        trend == "decreasing"
        for trend in (
            recent_response.volume_trend,
            recent_response.frequency_pattern,
            recent_response.long_run_trend,
            recent_response.cardiac_efficiency_trend,
            recent_response.intensity_exposure_trend,
        )
    ):
        return ["RECENT_RESPONSE_CAUTION"]
    return []


def _adapt_to_easy(workout: WorkoutPrescription) -> WorkoutPrescription:
    return WorkoutPrescription(
        day=workout.day,
        workout_type="easy",
        intensity_class="low",
        distance_km=workout.distance_km,
        duration_minutes=workout.duration_minutes,
        reason_codes=workout.reason_codes,
    )


def _shorten_workout(workout: WorkoutPrescription) -> WorkoutPrescription:
    distance_km = workout.distance_km
    duration_minutes = workout.duration_minutes

    shortened_distance = (
        round(distance_km * SHORTEN_FACTOR, 1)
        if distance_km is not None and distance_km > 0
        else distance_km
    )
    shortened_duration = (
        max(1, int(round(duration_minutes * SHORTEN_FACTOR)))
        if duration_minutes is not None and duration_minutes > 0
        else duration_minutes
    )

    return WorkoutPrescription(
        day=workout.day,
        workout_type=workout.workout_type,
        intensity_class=workout.intensity_class,
        distance_km=shortened_distance,
        duration_minutes=shortened_duration,
        reason_codes=workout.reason_codes,
    )


def _rest_workout(workout: WorkoutPrescription) -> WorkoutPrescription:
    return WorkoutPrescription(
        day=workout.day,
        workout_type="rest",
        intensity_class="rest",
        distance_km=None,
        duration_minutes=None,
        reason_codes=workout.reason_codes,
    )


def _should_reduce_for_load(readiness_band: str, load_status: str) -> bool:
    if load_status == "high":
        return readiness_band != "favorable"
    if load_status == "elevated":
        return readiness_band in ("caution", "low")
    return False


def build_daily_adaptation(
    *,
    workout: WorkoutPrescription,
    readiness: Optional[ReadinessResult],
    training_load: Optional[TrainingLoadSnapshot],
    recent_response: Optional[RecentTrainingResponse],
) -> DailyAdaptationResult:
    """Decide whether to keep or reduce today's workout without rebuilding the plan."""

    readiness_band = _readiness_band(readiness)
    load_status = _load_status(training_load)

    reasons: list[str] = []
    if workout.workout_type == "rest":
        reasons.extend(["PLANNED_REST_DAY", "PLAN_KEPT"])
        return DailyAdaptationResult(
            action=DailyAdaptationAction.KEEP,
            original_workout=workout,
            adapted_workout=workout,
            reason_codes=_dedupe_codes(reasons),
        )

    if readiness_band == "unavailable":
        reasons.append("READINESS_UNAVAILABLE")
    elif readiness_band == "caution":
        reasons.append("READINESS_CAUTION")
    elif readiness_band == "low":
        reasons.append("READINESS_LOW")
    elif readiness_band == "very_low":
        reasons.append("READINESS_VERY_LOW")

    if load_status == "unavailable":
        reasons.append("TRAINING_LOAD_UNAVAILABLE")
    elif load_status == "elevated":
        reasons.append("TRAINING_LOAD_ELEVATED")
    elif load_status == "high":
        reasons.append("TRAINING_LOAD_HIGH")

    reasons.extend(_recent_response_codes(recent_response))

    if readiness_band == "very_low":
        reasons.append("REST_RECOMMENDED")
        return DailyAdaptationResult(
            action=DailyAdaptationAction.REST,
            original_workout=workout,
            adapted_workout=_rest_workout(workout),
            reason_codes=_dedupe_codes(reasons),
        )

    is_quality_like = workout.workout_type in ("quality", "steady")
    needs_reduction = readiness_band in ("caution", "low") or _should_reduce_for_load(
        readiness_band, load_status
    )

    if is_quality_like and needs_reduction:
        reasons.extend(["QUALITY_DOWNGRADED", "INTENSITY_NOT_INCREASED"])
        return DailyAdaptationResult(
            action=DailyAdaptationAction.EASY_DOWNGRADE,
            original_workout=workout,
            adapted_workout=_adapt_to_easy(workout),
            reason_codes=_dedupe_codes(reasons),
        )

    if workout.workout_type == "long_easy" and needs_reduction:
        reasons.extend(
            ["LONG_EASY_PROTECTED", "WORKOUT_SHORTENED", "INTENSITY_NOT_INCREASED"]
        )
        return DailyAdaptationResult(
            action=DailyAdaptationAction.SHORTEN,
            original_workout=workout,
            adapted_workout=_shorten_workout(workout),
            reason_codes=_dedupe_codes(reasons),
        )

    if workout.workout_type in ("easy", "recovery") and needs_reduction:
        reasons.extend(["WORKOUT_SHORTENED", "INTENSITY_NOT_INCREASED"])
        return DailyAdaptationResult(
            action=DailyAdaptationAction.SHORTEN,
            original_workout=workout,
            adapted_workout=_shorten_workout(workout),
            reason_codes=_dedupe_codes(reasons),
        )

    reasons.extend(["PLAN_KEPT", "INTENSITY_NOT_INCREASED"])
    return DailyAdaptationResult(
        action=DailyAdaptationAction.KEEP,
        original_workout=workout,
        adapted_workout=workout,
        reason_codes=_dedupe_codes(reasons),
    )


__all__ = [
    "SHORTEN_FACTOR",
    "DailyAdaptationAction",
    "DailyAdaptationResult",
    "build_daily_adaptation",
]
