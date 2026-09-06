"""PR133 — DailyAdaptation V2: cautious same-day workout adaptation.

Design rules
------------
- PURE: no DB, no Garmin, no HTTP, no Redis, no LLM, no random, no global
  mutable state, no clock-based calls.
- Consumes existing V2 contracts only: WorkoutPrescription, ReadinessDecision,
  TrainingLoadSnapshot, RecentTrainingResponse.
- Adapts the planned workout for TODAY only.  It does NOT rebuild the weekly
  plan, recalculate WeeklyTarget, or change structural training volume/frequency.
- Asymmetric rule: can keep or reduce, never increase.
- None ≠ 0 throughout: unavailable readiness/load/response never becomes a bad
  score automatically.
- Readiness interpretation is delegated to the canonical readiness_decision
  layer.
- PRODUCT CALIBRATION V1 — SHORTEN_FACTOR is recalibrable, not a physiological law.

Run from the backend directory
------------------------------
    python -m pytest tests/test_daily_adaptation_pr133.py -q
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .readiness_decision import ReadinessBand, ReadinessDecision
from .training_load import TrainingLoadSnapshot
from .training_response import RecentTrainingResponse
from .workout_generator import WorkoutPrescription

# PRODUCT CALIBRATION V1 — RECALIBRABLE — NOT PHYSIOLOGICAL LAW
SHORTEN_FACTOR: float = 0.70


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
    # C232 (correction, round 7) — the workout_type itself changes to
    # "easy": any structural steps the original (e.g. "quality") prescription
    # may have carried (warmup / work intervals @ threshold / recovery /
    # cooldown) are now PHYSIOLOGICALLY INVALID for an easy-effort session —
    # blindly keeping them would silently misrepresent what is actually
    # served. steps=() ("unknown/none prescribed") is preferable to a wrong,
    # stale structure. This is a POLICY choice, not a new physiological
    # decision: DailyAdaptation still never invents a NEW structure, it only
    # discards one that no longer applies.
    return WorkoutPrescription(
        day=workout.day,
        workout_type="easy",
        intensity_class="low",
        distance_km=workout.distance_km,
        duration_minutes=workout.duration_minutes,
        reason_codes=workout.reason_codes,
        steps=(),
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

    # C232 (correction, round 7) — the total distance/duration shrinks by
    # SHORTEN_FACTOR: any original steps' repetitions/distances/durations
    # would no longer sum to the new (shorter) total, so keeping them
    # verbatim would present an internally-inconsistent, effectively
    # fabricated structure. steps=() until a real engine can re-derive a
    # consistent shortened structure — never invented here.
    return WorkoutPrescription(
        day=workout.day,
        workout_type=workout.workout_type,
        intensity_class=workout.intensity_class,
        distance_km=shortened_distance,
        duration_minutes=shortened_duration,
        reason_codes=workout.reason_codes,
        steps=(),
    )


def _rest_workout(workout: WorkoutPrescription) -> WorkoutPrescription:
    # C232 (correction, round 7) — a REST day has no structure by
    # definition: steps=() explicitly (never "whatever the original workout
    # happened to carry").
    return WorkoutPrescription(
        day=workout.day,
        workout_type="rest",
        intensity_class="rest",
        distance_km=None,
        duration_minutes=None,
        reason_codes=workout.reason_codes,
        steps=(),
    )


def _should_reduce_for_load(readiness_band: ReadinessBand, load_status: str) -> bool:
    if load_status == "high":
        return readiness_band != ReadinessBand.FAVORABLE
    if load_status == "elevated":
        return readiness_band in (ReadinessBand.CAUTION, ReadinessBand.LOW)
    return False


def build_daily_adaptation(
    *,
    workout: WorkoutPrescription,
    readiness_decision: Optional[ReadinessDecision],
    training_load: Optional[TrainingLoadSnapshot],
    recent_response: Optional[RecentTrainingResponse],
) -> DailyAdaptationResult:
    """Decide whether to keep or reduce today's workout without rebuilding the plan."""

    readiness_band = (
        readiness_decision.band
        if readiness_decision is not None
        else ReadinessBand.UNAVAILABLE
    )
    load_status = _load_status(training_load)

    reasons: list[str] = []
    if workout.workout_type == "rest":
        reasons.extend(["PLANNED_REST_DAY", "PLAN_KEPT"])
        # C232 (correction, round 7) — KEEP always returns the SAME
        # WorkoutPrescription instance, so `.steps` is preserved byte-for-byte
        # by construction (identity, not a copy) — never re-derived.
        return DailyAdaptationResult(
            action=DailyAdaptationAction.KEEP,
            original_workout=workout,
            adapted_workout=workout,
            reason_codes=_dedupe_codes(reasons),
        )

    if readiness_decision is None:
        reasons.append("READINESS_UNAVAILABLE")
    else:
        reasons.extend(readiness_decision.reason_codes)

    if load_status == "unavailable":
        reasons.append("TRAINING_LOAD_UNAVAILABLE")
    elif load_status == "elevated":
        reasons.append("TRAINING_LOAD_ELEVATED")
    elif load_status == "high":
        reasons.append("TRAINING_LOAD_HIGH")

    reasons.extend(_recent_response_codes(recent_response))

    if readiness_band == ReadinessBand.VERY_LOW:
        reasons.append("REST_RECOMMENDED")
        return DailyAdaptationResult(
            action=DailyAdaptationAction.REST,
            original_workout=workout,
            adapted_workout=_rest_workout(workout),
            reason_codes=_dedupe_codes(reasons),
        )

    is_quality_like = workout.workout_type in ("quality", "steady")
    needs_reduction = readiness_band in (
        ReadinessBand.CAUTION,
        ReadinessBand.LOW,
    ) or _should_reduce_for_load(readiness_band, load_status)

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
    # C232 (correction, round 7) — KEEP: same instance, steps preserved
    # byte-for-byte (see comment on the rest-day KEEP branch above).
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
