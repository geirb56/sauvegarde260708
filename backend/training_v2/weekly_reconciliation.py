"""PR134 — Weekly Reconciliation V2: cautious structural reconciliation layer.

Design rules
------------
- PURE: no DB, no provider calls, no HTTP, no Redis, no LLM, no random, no
  mutable global state, no clock-based calls.
- Consumes existing contracts only: WeeklyTarget and RecentTrainingResponse.
- Asymmetric rule: can keep or reduce, never increase.
- WeeklyTarget remains the base prescription owner; this layer only reconciles
  structural targets for the next week.
- PRODUCT CALIBRATION V1 values are centralized, documented, and recalibrable.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .training_response import RecentTrainingResponse
from .weekly_target import WeeklyTarget

# PRODUCT CALIBRATION V1 — RECALIBRABLE — NOT PHYSIOLOGICAL LAW
FREQUENCY_REDUCTION_MARGIN: float = 0.75
MAX_SESSION_REDUCTION_PER_RECONCILIATION: int = 1
VOLUME_REDUCTION_MARGIN: float = 0.80
RECONCILED_VOLUME_FLOOR_FACTOR: float = 0.85
WEEKLY_RESPONSE_WINDOW_WEEKS: float = 4.0


class WeeklyReconciliationAction(str, Enum):
    KEEP = "KEEP"
    REDUCE_VOLUME = "REDUCE_VOLUME"
    REDUCE_FREQUENCY = "REDUCE_FREQUENCY"
    REDUCE_BOTH = "REDUCE_BOTH"


class WeeklyReconciliationResult(BaseModel):
    """Immutable result of structural weekly reconciliation."""

    model_config = ConfigDict(frozen=True)

    action: WeeklyReconciliationAction
    original_target: WeeklyTarget
    reconciled_target: WeeklyTarget
    reason_codes: tuple[str, ...]

    observed_runs_per_week: Optional[float]
    observed_distance_km: Optional[float]
    observed_duration_minutes: Optional[float]
    response_status: str
    confidence: str


def _dedupe_codes(codes: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return tuple(ordered)


def _round_half_up(value: float) -> int:
    """Deterministic half-up rounding for session counts."""
    return int(math.floor(value + 0.5))


def _reconciled_weekly_distance(target_km: float, weekly_observed_km: float) -> float:
    reconciled = max(
        weekly_observed_km,
        target_km * RECONCILED_VOLUME_FLOOR_FACTOR,
    )
    return round(min(reconciled, target_km), 1)


def _reconciled_weekly_duration(target_minutes: int, weekly_observed_minutes: float) -> int:
    reconciled = max(
        weekly_observed_minutes,
        float(target_minutes) * RECONCILED_VOLUME_FLOOR_FACTOR,
    )
    return int(round(min(reconciled, float(target_minutes))))


def _keep_result(
    *,
    proposed_target: WeeklyTarget,
    recent_response: Optional[RecentTrainingResponse],
    keep_reason: str,
) -> WeeklyReconciliationResult:
    observed_runs_per_week = (
        recent_response.observed_runs_per_week if recent_response is not None else None
    )
    observed_distance_km = (
        recent_response.observed_distance_km if recent_response is not None else None
    )
    observed_duration_minutes = (
        recent_response.observed_duration_minutes if recent_response is not None else None
    )
    response_status = (
        recent_response.response_status if recent_response is not None else "unavailable"
    )
    confidence = recent_response.confidence if recent_response is not None else "none"

    return WeeklyReconciliationResult(
        action=WeeklyReconciliationAction.KEEP,
        original_target=proposed_target,
        reconciled_target=proposed_target,
        reason_codes=_dedupe_codes(["PLAN_STRUCTURE_KEPT", keep_reason]),
        observed_runs_per_week=observed_runs_per_week,
        observed_distance_km=observed_distance_km,
        observed_duration_minutes=observed_duration_minutes,
        response_status=response_status,
        confidence=confidence,
    )


def _enforce_monotone_target(
    *,
    proposed_target: WeeklyTarget,
    reconciled_target: WeeklyTarget,
    reason_codes: list[str],
) -> WeeklyTarget:
    """Guarantee that reconciliation never increases structural targets."""
    updates: dict[str, object] = {}

    if reconciled_target.target_sessions > proposed_target.target_sessions:
        updates["target_sessions"] = proposed_target.target_sessions

    if (
        proposed_target.target_basis == "distance"
        and proposed_target.target_km is not None
        and reconciled_target.target_km is not None
        and reconciled_target.target_km > proposed_target.target_km
    ):
        updates["target_km"] = proposed_target.target_km

    if (
        proposed_target.target_basis == "duration"
        and proposed_target.target_duration_minutes is not None
        and reconciled_target.target_duration_minutes is not None
        and reconciled_target.target_duration_minutes > proposed_target.target_duration_minutes
    ):
        updates["target_duration_minutes"] = proposed_target.target_duration_minutes

    if not updates:
        return reconciled_target

    reason_codes.append("MONOTONE_RECONCILIATION_GUARD")
    return reconciled_target.model_copy(update=updates)


def build_weekly_reconciliation(
    *,
    proposed_target: WeeklyTarget,
    recent_response: Optional[RecentTrainingResponse],
) -> WeeklyReconciliationResult:
    """Reconcile next-week structural target with observed 28-day response."""
    if recent_response is None:
        return _keep_result(
            proposed_target=proposed_target,
            recent_response=None,
            keep_reason="RECENT_RESPONSE_UNAVAILABLE",
        )

    if recent_response.response_status == "unavailable":
        return _keep_result(
            proposed_target=proposed_target,
            recent_response=recent_response,
            keep_reason="RECENT_RESPONSE_UNAVAILABLE",
        )

    if recent_response.response_status == "insufficient":
        return _keep_result(
            proposed_target=proposed_target,
            recent_response=recent_response,
            keep_reason="RECENT_RESPONSE_INSUFFICIENT",
        )

    reasons: list[str] = []
    reconciled_target = proposed_target

    observed_runs_per_week = recent_response.observed_runs_per_week
    observed_distance_km = recent_response.observed_distance_km
    observed_duration_minutes = recent_response.observed_duration_minutes

    frequency_candidate = False
    frequency_reduced = False
    if observed_runs_per_week is not None:
        frequency_threshold = proposed_target.target_sessions * FREQUENCY_REDUCTION_MARGIN
        if observed_runs_per_week < frequency_threshold:
            frequency_candidate = True
            reasons.append("OBSERVED_FREQUENCY_BELOW_TARGET")
            observed_candidate = max(1, _round_half_up(observed_runs_per_week))
            max_allowed_drop_candidate = max(
                1,
                proposed_target.target_sessions - MAX_SESSION_REDUCTION_PER_RECONCILIATION,
            )
            candidate_sessions = max(observed_candidate, max_allowed_drop_candidate)
            candidate_sessions = min(candidate_sessions, proposed_target.target_sessions)
            if candidate_sessions < proposed_target.target_sessions:
                frequency_reduced = True
                reconciled_target = reconciled_target.model_copy(
                    update={"target_sessions": candidate_sessions}
                )
                reasons.append("FREQUENCY_REDUCED")
                reasons.append("SESSION_FREQUENCY_REDUCTION_CAPPED")

    volume_candidate = False
    volume_reduced = False

    if (
        proposed_target.target_basis == "distance"
        and proposed_target.target_km is not None
        and observed_distance_km is not None
    ):
        weekly_observed_km = observed_distance_km / WEEKLY_RESPONSE_WINDOW_WEEKS
        threshold_km = proposed_target.target_km * VOLUME_REDUCTION_MARGIN
        if weekly_observed_km < threshold_km:
            volume_candidate = True
            reasons.append("OBSERVED_VOLUME_BELOW_TARGET")
            reconciled_km = _reconciled_weekly_distance(
                proposed_target.target_km,
                weekly_observed_km,
            )
            if reconciled_km < proposed_target.target_km:
                volume_reduced = True
                reconciled_target = reconciled_target.model_copy(
                    update={"target_km": reconciled_km}
                )
                reasons.append("VOLUME_REDUCED")

    if (
        proposed_target.target_basis == "duration"
        and proposed_target.target_duration_minutes is not None
        and observed_duration_minutes is not None
    ):
        weekly_observed_minutes = observed_duration_minutes / WEEKLY_RESPONSE_WINDOW_WEEKS
        threshold_minutes = proposed_target.target_duration_minutes * VOLUME_REDUCTION_MARGIN
        if weekly_observed_minutes < threshold_minutes:
            volume_candidate = True
            reasons.append("OBSERVED_VOLUME_BELOW_TARGET")
            reconciled_minutes = _reconciled_weekly_duration(
                proposed_target.target_duration_minutes,
                weekly_observed_minutes,
            )
            if reconciled_minutes < proposed_target.target_duration_minutes:
                volume_reduced = True
                reconciled_target = reconciled_target.model_copy(
                    update={"target_duration_minutes": reconciled_minutes}
                )
                reasons.append("VOLUME_REDUCED")

    if frequency_reduced:
        session_ratio = (
            float(reconciled_target.target_sessions) / float(proposed_target.target_sessions)
        )
        if (
            proposed_target.target_basis == "distance"
            and proposed_target.target_km is not None
            and reconciled_target.target_km is not None
        ):
            session_safe_max_km = round(proposed_target.target_km * session_ratio, 1)
            # Frequency reduction safety: never increase average per-session load.
            final_target_km = round(min(reconciled_target.target_km, session_safe_max_km), 1)
            if final_target_km < reconciled_target.target_km:
                volume_reduced = True
                reconciled_target = reconciled_target.model_copy(
                    update={"target_km": final_target_km}
                )
                reasons.append("SESSION_LOAD_CONCENTRATION_GUARD")
                reasons.append("VOLUME_REDUCED_FOR_FREQUENCY_SAFETY")
        if (
            proposed_target.target_basis == "duration"
            and proposed_target.target_duration_minutes is not None
            and reconciled_target.target_duration_minutes is not None
        ):
            session_safe_max_minutes = int(
                round(float(proposed_target.target_duration_minutes) * session_ratio)
            )
            final_target_minutes = int(
                min(reconciled_target.target_duration_minutes, session_safe_max_minutes)
            )
            if final_target_minutes < reconciled_target.target_duration_minutes:
                volume_reduced = True
                reconciled_target = reconciled_target.model_copy(
                    update={"target_duration_minutes": final_target_minutes}
                )
                reasons.append("SESSION_LOAD_CONCENTRATION_GUARD")
                reasons.append("VOLUME_REDUCED_FOR_FREQUENCY_SAFETY")

    if volume_candidate and recent_response.long_run_trend == "decreasing":
        reasons.append("LONG_RUN_CAUTION")

    if recent_response.cardiac_efficiency_trend == "decreasing":
        reasons.append("RECENT_CARDIAC_RESPONSE_CAUTION")

    if volume_reduced and frequency_reduced:
        action = WeeklyReconciliationAction.REDUCE_BOTH
        reasons.append("VOLUME_AND_FREQUENCY_REDUCED")
    elif volume_reduced:
        action = WeeklyReconciliationAction.REDUCE_VOLUME
    elif frequency_reduced:
        action = WeeklyReconciliationAction.REDUCE_FREQUENCY
    else:
        action = WeeklyReconciliationAction.KEEP
        reasons.append("PLAN_STRUCTURE_KEPT")

    reconciled_target = _enforce_monotone_target(
        proposed_target=proposed_target,
        reconciled_target=reconciled_target,
        reason_codes=reasons,
    )

    return WeeklyReconciliationResult(
        action=action,
        original_target=proposed_target,
        reconciled_target=reconciled_target,
        reason_codes=_dedupe_codes(reasons),
        observed_runs_per_week=observed_runs_per_week,
        observed_distance_km=observed_distance_km,
        observed_duration_minutes=observed_duration_minutes,
        response_status=recent_response.response_status,
        confidence=recent_response.confidence,
    )


__all__ = [
    "FREQUENCY_REDUCTION_MARGIN",
    "MAX_SESSION_REDUCTION_PER_RECONCILIATION",
    "VOLUME_REDUCTION_MARGIN",
    "RECONCILED_VOLUME_FLOOR_FACTOR",
    "WEEKLY_RESPONSE_WINDOW_WEEKS",
    "WeeklyReconciliationAction",
    "WeeklyReconciliationResult",
    "build_weekly_reconciliation",
]
