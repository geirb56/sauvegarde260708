"""C232 — Structured Workout Prescription V1 (canonical engine).

Problem
-------
Before this module, ``training_v2/session_structure.py`` was the ONLY place
that ever attached anything pace-related to a session, and it deliberately
did the SMALLEST honest thing possible: a single whole-session pace ZONE for
``easy``/``recovery``/``long_easy``, and nothing at all for ``quality`` — the
Training Engine had never actually decided a real interval/segment structure
for any workout_type, so displaying one (as an earlier, now-corrected version
of this codebase briefly did) would have been an invented, UNPRESCRIBED
physiological decision made in a display/presenter layer.

That correction was necessary but left the product incomplete: a "Quality —
9 km" session still told the runner nothing about how to actually run it.
``WorkoutPrescription.steps`` (see ``workout_generator.py``) already existed
as a snapshot-compatible, typed contract for real structure — but no engine
populated it.

Fix — Structured Workout Prescription V1
-----------------------------------------
This module is the FIRST real engine that decides ``WorkoutPrescription``
structure. It is BUSINESS LOGIC / PRESCRIPTION, not a presenter: it is the
only place, alongside ``workout_generator.py`` itself, allowed to decide a
session's ``steps``. It must be called BEFORE a prescription is served (see
``served_prescription.get_or_create_served_prescription`` and
``prescription_snapshot.py``) so that the structure AND its numeric paces are
frozen together, atomically, with the rest of the served prescription.

Canonical chain (mandatory)
----------------------------
    WeeklyPlan broad prescription (steps=())
        -> build_structured_prescription()          (THIS MODULE)
        -> DailyAdaptation (KEEP/EASY_DOWNGRADE/SHORTEN/REST)
        -> build_structured_prescription() again, on the FINAL adapted
           workout_type/distance/duration, so the structure always matches
           whatever was actually decided for today (see server.py: applied
           once, after DailyAdaptation, right before
           ``get_or_create_served_prescription``)
        -> PrescriptionSnapshot (freezes ``steps`` — including each step's
           numeric ``pace_range`` — verbatim, forever, for that day)
        -> Week/Today API -> Training UX

Design rules (V1, deterministic, testable)
-------------------------------------------
- PURE: no MongoDB, no HTTP, no LLM, no clock, no global state.
  ``TrainingPaces`` is supplied by the caller (already resolved for the
  correct ``reference_date`` via the canonical loader).
- REST -> ``steps=()``. Always.
- EASY / RECOVERY / LONG_EASY -> ONE continuous step covering the ENTIRE
  session, ``pace_zone="easy"``. No marathon-pace segment, no 65/20/15
  progression: the Training Engine has not prescribed one, so none is
  fabricated here either — this module only ADDS the (engine-decided,
  literal) pace zone/step wrapper; it does not invent a segmentation that
  does not exist.
- STEADY -> ONE continuous step, but with NO pace zone: "steady" is not part
  of the Daniels E/M/T/I/R vocabulary this codebase uses, so no canonical
  zone correspondence exists for it — inventing one here would be exactly
  the kind of undecided physiological choice this correction forbids.
- QUALITY -> V1 makes this a REAL, engine-decided THRESHOLD session:
  warmup (easy) -> N x work (threshold) -> recovery (easy jog, untimed pace)
  -> cooldown (easy). The distance/duration split is PRODUCT CALIBRATION V1
  (see the constants below) — recalibratable, not a physiological law — but
  it is a genuine engine decision now, not a UI inference: once decided, it
  is what gets served and frozen. Every km/minute is accounted for exactly:
  warmup + (per-rep x repetitions) + cooldown == the parent session's total,
  by construction (the cooldown absorbs the exact remainder). Recovery
  intervals are time-only (no distance, no pace) and therefore excluded from
  the distance/duration accounting — this mirrors how a real coach describes
  a recovery jog ("2 min facile") without claiming a fixed marked distance
  for it. Sessions too short for a coherent 3-rep threshold block (see
  ``_QUALITY_MIN_*``) fall back to a single honest continuous step with NO
  pace zone (exactly the previous behaviour) rather than a degenerate,
  meaningless split.
- Numeric pace resolution uses ONLY the supplied canonical ``TrainingPaces``:
  easy -> E, threshold -> T. When ``paces`` is ``None`` or its confidence is
  INSUFFICIENT (fields are ``None``), every step's ``pace_range`` is ``None``
  — the STRUCTURE (reps/blocks) is still an engine decision and is still
  shown, but no numeric pace is ever fabricated. ``None`` stays ``None``.
- Idempotent / order-independent: calling this twice with the same
  ``(workout_type, distance_km, duration_minutes, paces)`` always produces
  byte-identical steps — this lets the server call it once before
  DailyAdaptation is irrelevant and once after (on the FINAL adapted
  workout) without any special-casing.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .training_paces import PaceRange, PaceValue, TrainingPaces
from .workout_generator import WorkoutPrescription, WorkoutStep, WorkoutStepPaceRange

# ---------------------------------------------------------------------------
# PRODUCT CALIBRATION V1 — recalibrable constants, NOT physiological law.
# Centralized here so any future tuning happens in exactly one place.
# ---------------------------------------------------------------------------

_QUALITY_WARMUP_FRACTION: float = 0.20
_QUALITY_COOLDOWN_FRACTION: float = 0.10
_QUALITY_WORK_FRACTION: float = 1.0 - _QUALITY_WARMUP_FRACTION - _QUALITY_COOLDOWN_FRACTION  # 0.70
_QUALITY_REPETITIONS: int = 3
_QUALITY_RECOVERY_MINUTES: float = 2.0

# Below these totals, a warmup + 3-rep-threshold + cooldown split would be
# degenerate (near-zero or negative segments) — fall back to a single
# honest continuous step (no pace zone) instead of a broken structure.
_QUALITY_MIN_DISTANCE_KM: float = 4.0
_QUALITY_MIN_DURATION_MINUTES: float = 24.0

_WHOLE_SESSION_EASY_PACE_TYPES: frozenset = frozenset({"easy", "recovery", "long_easy"})


# ---------------------------------------------------------------------------
# Numeric pace helpers
# ---------------------------------------------------------------------------


def _pace_range_from_value(value: Optional[PaceValue]) -> Optional[WorkoutStepPaceRange]:
    """A single PaceValue (e.g. Threshold) becomes a zero-width numeric range."""
    if value is None:
        return None
    return WorkoutStepPaceRange(lower_min_per_km=value.min_per_km, upper_min_per_km=value.min_per_km)


def _pace_range_from_range(value: Optional[PaceRange]) -> Optional[WorkoutStepPaceRange]:
    if value is None:
        return None
    return WorkoutStepPaceRange(
        lower_min_per_km=value.lower.min_per_km, upper_min_per_km=value.upper.min_per_km
    )


def _easy_pace_range(paces: Optional[TrainingPaces]) -> Optional[WorkoutStepPaceRange]:
    if paces is None:
        return None
    return _pace_range_from_range(paces.easy)


def _threshold_pace_range(paces: Optional[TrainingPaces]) -> Optional[WorkoutStepPaceRange]:
    if paces is None:
        return None
    return _pace_range_from_value(paces.threshold)


# ---------------------------------------------------------------------------
# Continuous (single-block) session builders
# ---------------------------------------------------------------------------


def _duration_as_float(duration_minutes: Optional[int]) -> Optional[float]:
    return float(duration_minutes) if duration_minutes is not None else None


def _build_continuous_steps(
    prescription: WorkoutPrescription,
    *,
    pace_zone: Optional[str],
    pace_range: Optional[WorkoutStepPaceRange],
    reason_code: str,
) -> Tuple[WorkoutStep, ...]:
    if prescription.distance_km is None and prescription.duration_minutes is None:
        return ()
    return (
        WorkoutStep(
            kind="continuous",
            repetitions=None,
            distance_km=prescription.distance_km,
            duration_minutes=_duration_as_float(prescription.duration_minutes),
            pace_zone=pace_zone,
            pace_range=pace_range,
            reason_codes=(reason_code,),
        ),
    )


# ---------------------------------------------------------------------------
# Quality (structured threshold session) builder
# ---------------------------------------------------------------------------


def _split_quality_total(
    total: float, *, reps: int, precision: int
) -> Optional[Tuple[float, float, float]]:
    """Split ``total`` into (warmup, per_rep, cooldown) that sum EXACTLY to
    ``total`` (the cooldown absorbs the exact rounding remainder), or
    ``None`` when the split would be degenerate (any segment <= 0)."""
    if total is None or total <= 0:
        return None
    warmup = round(total * _QUALITY_WARMUP_FRACTION, precision)
    raw_work_total = total * _QUALITY_WORK_FRACTION
    per_rep = round(raw_work_total / reps, precision)
    if per_rep <= 0 or warmup <= 0:
        return None
    work_total = round(per_rep * reps, precision)
    cooldown = round(total - warmup - work_total, precision)
    if cooldown <= 0:
        return None
    return (warmup, per_rep, cooldown)


def _build_quality_steps(
    prescription: WorkoutPrescription, paces: Optional[TrainingPaces]
) -> Tuple[WorkoutStep, ...]:
    easy_pace = _easy_pace_range(paces)
    threshold_pace = _threshold_pace_range(paces)

    distance_km = prescription.distance_km
    duration_minutes = prescription.duration_minutes

    split: Optional[Tuple[float, float, float]] = None
    basis: Optional[str] = None
    if distance_km is not None and distance_km >= _QUALITY_MIN_DISTANCE_KM:
        split = _split_quality_total(distance_km, reps=_QUALITY_REPETITIONS, precision=2)
        basis = "distance"
    elif duration_minutes is not None and duration_minutes >= _QUALITY_MIN_DURATION_MINUTES:
        split = _split_quality_total(float(duration_minutes), reps=_QUALITY_REPETITIONS, precision=0)
        basis = "duration"

    if split is None:
        # Too short (or no total at all) for a coherent 3-rep threshold
        # block — an honest continuous fallback, no pace zone fabricated
        # (the engine has not decided a real structure for this size).
        return _build_continuous_steps(
            prescription,
            pace_zone=None,
            pace_range=None,
            reason_code="QUALITY_STRUCTURE_TOO_SHORT_FOR_INTERVALS_V1",
        )

    warmup_amount, per_rep_amount, cooldown_amount = split
    steps: list = []
    if basis == "distance":
        steps.append(
            WorkoutStep(
                kind="warmup", repetitions=None, distance_km=warmup_amount, duration_minutes=None,
                pace_zone="easy", pace_range=easy_pace, reason_codes=("QUALITY_WARMUP_V1",),
            )
        )
        steps.append(
            WorkoutStep(
                kind="work", repetitions=_QUALITY_REPETITIONS, distance_km=per_rep_amount,
                duration_minutes=None, pace_zone="threshold", pace_range=threshold_pace,
                reason_codes=("QUALITY_THRESHOLD_WORK_V1",),
            )
        )
        if _QUALITY_REPETITIONS > 1:
            steps.append(
                WorkoutStep(
                    kind="recovery", repetitions=_QUALITY_REPETITIONS - 1, distance_km=None,
                    duration_minutes=_QUALITY_RECOVERY_MINUTES, pace_zone=None, pace_range=None,
                    reason_codes=("QUALITY_RECOVERY_V1",),
                )
            )
        steps.append(
            WorkoutStep(
                kind="cooldown", repetitions=None, distance_km=cooldown_amount, duration_minutes=None,
                pace_zone="easy", pace_range=easy_pace, reason_codes=("QUALITY_COOLDOWN_V1",),
            )
        )
    else:
        steps.append(
            WorkoutStep(
                kind="warmup", repetitions=None, distance_km=None, duration_minutes=warmup_amount,
                pace_zone="easy", pace_range=easy_pace, reason_codes=("QUALITY_WARMUP_V1",),
            )
        )
        steps.append(
            WorkoutStep(
                kind="work", repetitions=_QUALITY_REPETITIONS, distance_km=None,
                duration_minutes=per_rep_amount, pace_zone="threshold", pace_range=threshold_pace,
                reason_codes=("QUALITY_THRESHOLD_WORK_V1",),
            )
        )
        if _QUALITY_REPETITIONS > 1:
            steps.append(
                WorkoutStep(
                    kind="recovery", repetitions=_QUALITY_REPETITIONS - 1, distance_km=None,
                    duration_minutes=_QUALITY_RECOVERY_MINUTES, pace_zone=None, pace_range=None,
                    reason_codes=("QUALITY_RECOVERY_V1",),
                )
            )
        steps.append(
            WorkoutStep(
                kind="cooldown", repetitions=None, distance_km=None, duration_minutes=cooldown_amount,
                pace_zone="easy", pace_range=easy_pace, reason_codes=("QUALITY_COOLDOWN_V1",),
            )
        )
    return tuple(steps)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_structured_prescription(
    *, prescription: WorkoutPrescription, paces: Optional[TrainingPaces]
) -> WorkoutPrescription:
    """Return a COPY of ``prescription`` with ``steps`` decided by the
    Structured Workout Prescription V1 engine.

    Every other field (``day``, ``workout_type``, ``intensity_class``,
    ``distance_km``, ``duration_minutes``, ``reason_codes``) is preserved
    verbatim — this function only ever ADDS structure, never changes what
    was already decided upstream (WorkoutGenerator / DailyAdaptation).

    Idempotent / non-destructive: if ``prescription.steps`` is already
    non-empty (a real structure was already decided by SOME upstream
    engine — including a previous call to this very function), it is
    returned UNCHANGED. V1 only ever fills a gap; it never overwrites an
    already-decided structure.
    """
    if prescription.steps:
        return prescription

    workout_type = prescription.workout_type

    if workout_type == "rest":
        steps: Tuple[WorkoutStep, ...] = ()
    elif workout_type in _WHOLE_SESSION_EASY_PACE_TYPES:
        steps = _build_continuous_steps(
            prescription,
            pace_zone="easy",
            pace_range=_easy_pace_range(paces),
            reason_code="WHOLE_SESSION_EASY_PACE_V1",
        )
    elif workout_type == "steady":
        steps = _build_continuous_steps(
            prescription,
            pace_zone=None,
            pace_range=None,
            reason_code="NO_CANONICAL_PACE_ZONE_FOR_STEADY_V1",
        )
    elif workout_type == "quality":
        steps = _build_quality_steps(prescription, paces)
    else:
        steps = ()

    return WorkoutPrescription(
        day=prescription.day,
        workout_type=prescription.workout_type,
        intensity_class=prescription.intensity_class,
        distance_km=prescription.distance_km,
        duration_minutes=prescription.duration_minutes,
        reason_codes=prescription.reason_codes,
        steps=steps,
    )


def resolve_primary_step(steps: Tuple[WorkoutStep, ...]) -> Optional[WorkoutStep]:
    """Return the ONE step that represents the useful/main information for a
    compact card heading: the ``work`` block when one exists (e.g. the
    threshold repetitions of a quality session), else the sole
    ``continuous`` step, else ``None``.

    Never averages/ranges across heterogeneous blocks (see
    RUNINDEX_PR232_REPORT.md — "avoid absurd global ranges across different
    blocks"): a session with a real work block always surfaces THAT block's
    pace as the headline, never a blended warmup..work..cooldown range.
    """
    for step in steps:
        if step.kind == "work":
            return step
    for step in steps:
        if step.kind == "continuous":
            return step
    return None


__all__ = [
    "build_structured_prescription",
    "resolve_primary_step",
]
