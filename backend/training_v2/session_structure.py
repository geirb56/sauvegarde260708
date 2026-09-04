"""PR232 — Training UX V3: display-only session structure (blocks/splits).

Design rules
------------
- PURE, presentation-layer only: no MongoDB, no Garmin, no LLM, no global state.
- Does NOT change prescribed distance_km / duration_minutes: those remain the
  single source of truth (WorkoutGenerator #131). This module only decomposes
  the already-decided total into a deterministic, readable breakdown
  (warmup / main block / recovery / cooldown, or long-run segments) and
  attaches VDOT-derived Daniels paces (training_v2.training_paces, #194) to
  each block.
- Never invents a pace: when TrainingPaces.confidence == "INSUFFICIENT" (or
  the relevant pace field is None), blocks are returned WITHOUT any pace
  (None stays None — no fabricated range).
- rest sessions and sessions with unknown distance/duration produce no
  blocks (None): the frontend falls back to a single-line summary.
- Does NOT touch WorkoutGenerator, WeeklyTarget, Readiness, DailyAdaptation,
  WeeklyReconciliation or PR230 (performed_workout). This is purely an
  additional read-only view over an already-computed WorkoutPrescription.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .training_paces import PaceRange, PaceValue, TrainingPaces

# ---------------------------------------------------------------------------
# Calibration constants — V1, display-only, recalibrable
# ---------------------------------------------------------------------------

# "quality" (threshold/interval) session shape.
_QUALITY_WARMUP_KM: float = 2.0
_QUALITY_COOLDOWN_KM: float = 1.0
_QUALITY_MIN_TOTAL_FOR_STRUCTURE_KM: float = 4.0
"""Below this total distance, a quality session is too short to carve a
warmup/main/cooldown shape without producing near-zero blocks; it is shown
as a single main block instead."""
_QUALITY_REP_LENGTH_KM: float = 2.0
"""Target length of one repetition in the main interval/threshold block."""
_QUALITY_MAX_REPS: int = 6
_QUALITY_RECOVERY_MINUTES: float = 2.0
"""Fixed easy-jog recovery between repetitions. Display-only, not a
physiological prescription — matches the existing jog-recovery convention
already used in narrative session descriptions."""
_QUALITY_MAIN_PACE_WINDOW_MIN_PER_KM: float = 0.083
"""~5 seconds/km narrow window applied around the single Threshold pace so
the main block reads as a target range instead of one exact number."""

# "long_easy" (long run) session shape.
_LONG_RUN_STRUCTURE_MIN_KM: float = 15.0
"""Below this distance, a long run is shown as one easy block."""
_LONG_RUN_LEAD_FRACTION: float = 0.65
_LONG_RUN_SUSTAINED_FRACTION: float = 0.20
_LONG_RUN_COOLDOWN_FRACTION: float = 0.15


@dataclass(frozen=True)
class SessionBlock:
    """One readable block/segment of a session.

    label: "warmup" | "main" | "recovery" | "cooldown" | "segment"
    order: 0-based position for deterministic display order.
    repetitions: number of repeats of this block (interval structure), or
        None for a single continuous block.
    distance_km: distance of ONE repetition (or of the whole block when
        repetitions is None). None when the block is duration-based.
    duration_minutes: duration of ONE repetition (or of the whole block when
        repetitions is None). None when the block is distance-based.
    pace: PaceRange for this block, or None when no pace evidence exists.
    """

    label: str
    order: int
    repetitions: Optional[int]
    distance_km: Optional[float]
    duration_minutes: Optional[float]
    pace: Optional[PaceRange]


def _single_pace_to_range(pace: Optional[PaceValue], window: float = 0.0) -> Optional[PaceRange]:
    """Wrap a single PaceValue into a degenerate/narrow PaceRange for display."""
    if pace is None:
        return None
    if window <= 0:
        return PaceRange(lower=pace, upper=pace, method=pace.method)
    upper = PaceValue(
        min_per_km=round(pace.min_per_km + window, 4),
        km_per_hour=pace.km_per_hour,
        method=pace.method,
    )
    return PaceRange(lower=pace, upper=upper, method=pace.method)


def _round1(value: float) -> float:
    return round(value, 1)


def build_session_blocks(
    *,
    workout_type: Optional[str],
    distance_km: Optional[float],
    duration_minutes: Optional[float],
    paces: Optional[TrainingPaces],
) -> Optional[tuple[SessionBlock, ...]]:
    """Build a deterministic, readable block breakdown for one session.

    Returns None when there is nothing meaningful to decompose (rest days,
    unknown workout_type, or both distance_km and duration_minutes unknown).
    """
    if not workout_type or workout_type == "rest":
        return None
    if distance_km is None and duration_minutes is None:
        return None

    easy_pace = paces.easy if paces else None
    marathon_pace = paces.marathon if paces else None
    threshold_pace = paces.threshold if paces else None

    if workout_type == "quality":
        return _build_quality_blocks(distance_km, duration_minutes, easy_pace, threshold_pace)

    if workout_type == "long_easy":
        return _build_long_easy_blocks(distance_km, duration_minutes, easy_pace, marathon_pace)

    # recovery / easy / steady / anything else running: single easy-paced block.
    pace = easy_pace if workout_type in ("recovery", "easy") else None
    return (
        SessionBlock(
            label="main",
            order=0,
            repetitions=None,
            distance_km=_round1(distance_km) if distance_km is not None else None,
            duration_minutes=duration_minutes,
            pace=pace,
        ),
    )


def _build_quality_blocks(
    distance_km: Optional[float],
    duration_minutes: Optional[float],
    easy_pace: Optional[PaceRange],
    threshold_pace: Optional[PaceValue],
) -> tuple[SessionBlock, ...]:
    if distance_km is None or distance_km < _QUALITY_MIN_TOTAL_FOR_STRUCTURE_KM:
        # Too short (or duration-based) to carve a warmup/cooldown shape.
        main_pace = _single_pace_to_range(threshold_pace, _QUALITY_MAIN_PACE_WINDOW_MIN_PER_KM)
        return (
            SessionBlock(
                label="main",
                order=0,
                repetitions=None,
                distance_km=_round1(distance_km) if distance_km is not None else None,
                duration_minutes=duration_minutes,
                pace=main_pace,
            ),
        )

    warmup_km = min(_QUALITY_WARMUP_KM, distance_km * 0.25)
    cooldown_km = min(_QUALITY_COOLDOWN_KM, distance_km * 0.15)
    main_km = max(0.0, distance_km - warmup_km - cooldown_km)

    reps = max(1, min(_QUALITY_MAX_REPS, round(main_km / _QUALITY_REP_LENGTH_KM)))
    rep_km = _round1(main_km / reps) if reps else _round1(main_km)

    main_pace = _single_pace_to_range(threshold_pace, _QUALITY_MAIN_PACE_WINDOW_MIN_PER_KM)

    return (
        SessionBlock(
            label="warmup",
            order=0,
            repetitions=None,
            distance_km=_round1(warmup_km),
            duration_minutes=None,
            pace=easy_pace,
        ),
        SessionBlock(
            label="main",
            order=1,
            repetitions=reps if reps > 1 else None,
            distance_km=rep_km,
            duration_minutes=None,
            pace=main_pace,
        ),
        SessionBlock(
            label="recovery",
            order=2,
            repetitions=None,
            distance_km=None,
            duration_minutes=_QUALITY_RECOVERY_MINUTES,
            pace=None,
        ),
        SessionBlock(
            label="cooldown",
            order=3,
            repetitions=None,
            distance_km=_round1(cooldown_km),
            duration_minutes=None,
            pace=easy_pace,
        ),
    )


def _build_long_easy_blocks(
    distance_km: Optional[float],
    duration_minutes: Optional[float],
    easy_pace: Optional[PaceRange],
    marathon_pace: Optional[PaceValue],
) -> tuple[SessionBlock, ...]:
    if distance_km is None or distance_km < _LONG_RUN_STRUCTURE_MIN_KM or marathon_pace is None:
        return (
            SessionBlock(
                label="main",
                order=0,
                repetitions=None,
                distance_km=_round1(distance_km) if distance_km is not None else None,
                duration_minutes=duration_minutes,
                pace=easy_pace,
            ),
        )

    lead_km = distance_km * _LONG_RUN_LEAD_FRACTION
    sustained_km = distance_km * _LONG_RUN_SUSTAINED_FRACTION
    cooldown_km = distance_km - lead_km - sustained_km

    sustained_pace = _single_pace_to_range(marathon_pace, _QUALITY_MAIN_PACE_WINDOW_MIN_PER_KM)

    return (
        SessionBlock(
            label="segment",
            order=0,
            repetitions=None,
            distance_km=_round1(lead_km),
            duration_minutes=None,
            pace=easy_pace,
        ),
        SessionBlock(
            label="segment",
            order=1,
            repetitions=None,
            distance_km=_round1(sustained_km),
            duration_minutes=None,
            pace=sustained_pace,
        ),
        SessionBlock(
            label="segment",
            order=2,
            repetitions=None,
            distance_km=_round1(cooldown_km),
            duration_minutes=None,
            pace=easy_pace,
        ),
    )
