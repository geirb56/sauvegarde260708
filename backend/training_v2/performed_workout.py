"""PR230 — PerformedWorkout: PRESCRIBED vs PERFORMED (Garmin actual).

Purpose
-------
This module is the first real Data Moat brick: it separates

    what RunIndex PRESCRIBED      (WorkoutPrescription / plan)
from
    what the athlete ACTUALLY DID (Garmin activity → DomainActivity)

and produces a deterministic, auditable reconciliation between the two.

    Prescription
      → real Garmin activity (garmin_activities → DomainActivity)
      → deterministic matching
      → PerformedWorkout
      → adherence / outcome

Design rules
------------
- PURE: no MongoDB, no Garmin client, no HTTP, no LLM, no cache, no random,
  no mutable global state.
- ``datetime.now()`` / ``date.today()`` are NEVER called here.  The caller
  supplies ``reference_date`` explicitly ("what is known as of J").
- Deterministic: same inputs → same outputs, always.  No fuzzy matching,
  no invented score, no LLM.
- The prescription is NEVER mutated.  Inputs are frozen pydantic models and
  the engine only produces new PerformedWorkout rows.
- None ≠ 0.  A missing value stays ``None``; it is never replaced by 0.

Source of truth
---------------
The only accepted evidence of a performed session is a real activity coming
from ``garmin_activities`` normalised into :class:`DomainActivity`
(``garmin.domain_adapter.mongo_garmin_to_domain``).  ``db.workouts`` is NOT a
source of truth for what was actually performed and is not consumed here.

States (matching_status)
------------------------
planned
    The prescription's matching window is not closed yet (or the session is
    in the future).  Nothing is asserted about it.
matched
    A real running activity has been deterministically attributed to it.
missed
    The matching window is definitively closed and no acceptable activity was
    attributed to the prescription.
unmatched_actual
    A real running activity that could not be attributed to any prescription.
    It stays fully visible — it is never dropped.

There is deliberately NO ``completed`` state produced by this engine: a past
session never becomes "completed" automatically.  ``matched`` means "we found
real evidence"; the adherence diagnostic then qualifies it.

Matching rules (deterministic, evidence only)
---------------------------------------------
1. Same ``user_id`` (strict multi-user isolation).
2. Local date inside the explicit matching window of the prescription:
       [planned_date - MATCH_WINDOW_DAYS_BEFORE, planned_date + MATCH_WINDOW_DAYS_AFTER]
   Calibration V1: both bounds are 0 → same local calendar day.  A wrong
   date / wrong timezone therefore cannot create a false match.
3. Running activities only (``RUNNING_TYPES``).  A non-running activity is
   never matched, and is not reported as ``unmatched_actual`` either — it is
   simply out of scope for the running plan.
4. Deviation guard: the candidate must stay within
   ``MATCH_MAX_DEVIATION_RATIO`` of the prescribed dimension (distance first,
   duration as fallback).  Beyond that, the activity is NOT considered the
   realisation of that prescription.
5. One activity can be attributed to at most one prescription.
6. Multi-activity resolution: the best candidate is the one minimising the
   comparison deviation, then the earlier local start time.  If two candidates
   are strictly equivalent on those comparison keys, the situation is
   AMBIGUOUS: nothing is matched (see ``AMBIGUOUS_MULTIPLE_CANDIDATES``).

Adherence (factual only — no arbitrary physiological score)
-----------------------------------------------------------
completed_as_planned
    matched and within ``ADHERENCE_TOLERANCE_RATIO`` on the comparison
    dimension.
completed_modified
    matched but outside that tolerance (still inside the matching guard).
completed_unverified
    matched on date + running type, but no comparable dimension was available
    on either side.  We do not fabricate a deviation.
missed / unmatched_actual
    mirror the corresponding matching_status.
pending
    nothing can be asserted yet (window still open / future session).
not_applicable
    rest day: never matched, never missed.

Raw deltas (``distance_delta_km``, ``duration_delta_min``,
``pace_delta_min_per_km``) are kept as-is, signed (actual − planned), and are
``None`` when not computable.

No-lookahead guarantee
----------------------
Activities whose local date is strictly after ``reference_date`` are dropped
before any matching happens.  A future activity can therefore never change the
state of a historical prescription, and a future prescription is always
``planned``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

from .domain_activity import DomainActivity, to_domain_activity
from .training_history import RUNNING_TYPES, _parse_date

# ---------------------------------------------------------------------------
# Calibration constants — V1, recalibrable, NOT physiological law
# ---------------------------------------------------------------------------

MATCH_WINDOW_DAYS_BEFORE: int = 0
"""Days before ``planned_date`` accepted as realisation of the prescription."""

MATCH_WINDOW_DAYS_AFTER: int = 0
"""Days after ``planned_date`` accepted as realisation of the prescription."""

ADHERENCE_TOLERANCE_RATIO: float = 0.10
"""Relative deviation under which a matched session is 'as planned' (±10 %)."""

MATCH_MAX_DEVIATION_RATIO: float = 0.50
"""Relative deviation above which an activity is NOT the realisation (±50 %)."""

_ROUND = 2


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MatchingStatus(str, Enum):
    """Deterministic state of a prescription / actual activity pair."""

    PLANNED = "planned"
    MATCHED = "matched"
    MISSED = "missed"
    UNMATCHED_ACTUAL = "unmatched_actual"


class AdherenceStatus(str, Enum):
    """Factual adherence diagnostic. No arbitrary physiological score."""

    PENDING = "pending"
    COMPLETED_AS_PLANNED = "completed_as_planned"
    COMPLETED_MODIFIED = "completed_modified"
    COMPLETED_UNVERIFIED = "completed_unverified"
    MISSED = "missed"
    UNMATCHED_ACTUAL = "unmatched_actual"
    NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Reason codes (language-neutral, stable)
# ---------------------------------------------------------------------------

RC_MATCHED_ON_DISTANCE = "MATCHED_ON_DISTANCE"
RC_MATCHED_ON_DURATION = "MATCHED_ON_DURATION"
RC_MATCHED_NO_COMPARABLE_DIMENSION = "MATCHED_NO_COMPARABLE_DIMENSION"
RC_WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
RC_OUTSIDE_TOLERANCE = "OUTSIDE_TOLERANCE"
RC_WINDOW_OPEN = "WINDOW_OPEN"
RC_WINDOW_CLOSED = "WINDOW_CLOSED"
RC_FUTURE_SESSION = "FUTURE_SESSION"
RC_NO_CANDIDATE = "NO_CANDIDATE"
RC_CANDIDATE_REJECTED_DEVIATION = "CANDIDATE_REJECTED_DEVIATION"
RC_AMBIGUOUS_MULTIPLE_CANDIDATES = "AMBIGUOUS_MULTIPLE_CANDIDATES"
RC_REST_NOT_MATCHABLE = "REST_NOT_MATCHABLE"
RC_NO_PRESCRIPTION = "NO_PRESCRIPTION"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class PrescribedWorkout(BaseModel):
    """A single prescribed session, independent from any observed activity.

    This model is an immutable *copy* of what the plan prescribed.  The engine
    never rewrites it to make it fit the observed activity.
    """

    model_config = ConfigDict(frozen=True)

    prescription_id: str
    user_id: str
    planned_date: date
    workout_type: str
    """rest | recovery | easy | steady | quality | long_easy."""

    intensity_class: Optional[str] = None
    planned_distance_km: Optional[float] = None
    planned_duration_min: Optional[float] = None
    planned_pace_min_per_km: Optional[float] = None
    """Only set when a pace was really prescribed. Never derived here."""

    @property
    def is_rest(self) -> bool:
        return self.workout_type == "rest"

    @property
    def window_start(self) -> date:
        return self.planned_date - timedelta(days=MATCH_WINDOW_DAYS_BEFORE)

    @property
    def window_end(self) -> date:
        return self.planned_date + timedelta(days=MATCH_WINDOW_DAYS_AFTER)


class ObservedActivity(BaseModel):
    """A real activity actually performed by the athlete (Garmin truth)."""

    model_config = ConfigDict(frozen=True)

    activity_id: str
    user_id: str
    local_date: date
    start_time: Optional[datetime] = None
    activity_type: Optional[str] = None
    distance_km: Optional[float] = None
    duration_min: Optional[float] = None
    pace_min_per_km: Optional[float] = None

    @property
    def is_running(self) -> bool:
        return isinstance(self.activity_type, str) and self.activity_type in RUNNING_TYPES


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class PerformedWorkout(BaseModel):
    """Reconciliation row: what was prescribed vs what was really performed."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    prescription_id: Optional[str] = None
    activity_id: Optional[str] = None

    planned_date: Optional[date] = None
    actual_start_time: Optional[datetime] = None

    planned_workout_type: Optional[str] = None
    actual_activity_type: Optional[str] = None

    planned_distance_km: Optional[float] = None
    actual_distance_km: Optional[float] = None
    planned_duration_min: Optional[float] = None
    actual_duration_min: Optional[float] = None
    planned_intensity_class: Optional[str] = None
    planned_pace_min_per_km: Optional[float] = None
    actual_pace_min_per_km: Optional[float] = None

    matching_status: MatchingStatus
    adherence_status: AdherenceStatus

    distance_delta_km: Optional[float] = None
    duration_delta_min: Optional[float] = None
    pace_delta_min_per_km: Optional[float] = None

    comparison_basis: Optional[str] = None
    """'distance' | 'duration' | None when nothing was comparable."""

    deviation_ratio: Optional[float] = None
    """Absolute relative deviation on the comparison basis, or None."""

    reason_codes: Tuple[str, ...] = ()


class PerformedWorkoutLedger(BaseModel):
    """Deterministic reconciliation output for one user at one reference date."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    reference_date: date
    entries: Tuple[PerformedWorkout, ...]

    matched_count: int
    missed_count: int
    planned_count: int
    unmatched_actual_count: int


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _positive_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f > 0 else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a naive/aware datetime from Garmin-style values, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return None
    if not isinstance(value, str) or value == "":
        return None

    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


def to_observed_activity(
    activity: Any,
    *,
    user_id: str,
    activity_id: Optional[str] = None,
) -> Optional[ObservedActivity]:
    """Convert a :class:`DomainActivity` (or coercible input) into an
    :class:`ObservedActivity` owned by ``user_id``.

    Returns ``None`` when the activity carries no usable local date or no
    stable identifier: without those, no deterministic matching is possible
    and we refuse to invent one.
    """
    domain: DomainActivity = (
        activity if isinstance(activity, DomainActivity) else to_domain_activity(activity)
    )

    local_date = _parse_date(domain.start_time)
    if local_date is None:
        return None

    resolved_id = activity_id if activity_id is not None else domain.source_activity_id
    if not isinstance(resolved_id, str) or resolved_id == "":
        return None

    distance_km = _positive_float(domain.distance_m)
    distance_km = round(distance_km / 1000.0, 3) if distance_km is not None else None

    duration_s = _positive_float(domain.duration_s)
    duration_min = round(duration_s / 60.0, 2) if duration_s is not None else None

    pace = None
    if distance_km is not None and duration_min is not None and distance_km > 0:
        pace = round(duration_min / distance_km, _ROUND)

    return ObservedActivity(
        activity_id=resolved_id,
        user_id=user_id,
        local_date=local_date,
        start_time=_parse_datetime(domain.start_time),
        activity_type=domain.activity_type,
        distance_km=distance_km,
        duration_min=duration_min,
        pace_min_per_km=pace,
    )


def to_observed_activities(
    activities: Sequence[Any],
    *,
    user_id: str,
) -> Tuple[ObservedActivity, ...]:
    """Convert a sequence of activities; unusable inputs are skipped."""
    observed: List[ObservedActivity] = []
    for activity in activities or ():
        item = to_observed_activity(activity, user_id=user_id)
        if item is not None:
            observed.append(item)
    return tuple(observed)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _comparison(
    prescription: PrescribedWorkout,
    activity: ObservedActivity,
) -> Tuple[Optional[str], Optional[float]]:
    """Return (basis, absolute relative deviation) or (None, None).

    Distance is the primary basis; duration is the fallback.  A dimension is
    only usable when BOTH sides carry a strictly positive value.
    """
    planned_km = _positive_float(prescription.planned_distance_km)
    actual_km = _positive_float(activity.distance_km)
    if planned_km is not None and actual_km is not None:
        return "distance", abs(actual_km - planned_km) / planned_km

    planned_min = _positive_float(prescription.planned_duration_min)
    actual_min = _positive_float(activity.duration_min)
    if planned_min is not None and actual_min is not None:
        return "duration", abs(actual_min - planned_min) / planned_min

    return None, None


def _sort_key_activity(activity: ObservedActivity) -> Tuple[Any, ...]:
    """Stable, deterministic ordering for observed activities."""
    return (
        activity.local_date,
        activity.start_time.isoformat() if activity.start_time is not None else "",
        activity.activity_id,
    )


def _candidate_rank(
    deviation: Optional[float],
    activity: ObservedActivity,
) -> Tuple[float, str]:
    """Comparison keys used to elect the best candidate.

    ``activity_id`` is deliberately NOT part of this key: two activities that
    are equivalent on the real comparison evidence must be reported as
    ambiguous rather than silently disambiguated by an arbitrary identifier.
    """
    dev = deviation if deviation is not None else float("inf")
    start = activity.start_time.isoformat() if activity.start_time is not None else ""
    return (dev, start)


def _delta(actual: Optional[float], planned: Optional[float]) -> Optional[float]:
    a = _positive_float(actual)
    p = _positive_float(planned)
    if a is None or p is None:
        return None
    return round(a - p, _ROUND)


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _unmatched_prescription_row(
    prescription: PrescribedWorkout,
    *,
    matching_status: MatchingStatus,
    adherence_status: AdherenceStatus,
    reason_codes: Tuple[str, ...],
) -> PerformedWorkout:
    return PerformedWorkout(
        user_id=prescription.user_id,
        prescription_id=prescription.prescription_id,
        activity_id=None,
        planned_date=prescription.planned_date,
        actual_start_time=None,
        planned_workout_type=prescription.workout_type,
        actual_activity_type=None,
        planned_distance_km=prescription.planned_distance_km,
        actual_distance_km=None,
        planned_duration_min=prescription.planned_duration_min,
        actual_duration_min=None,
        planned_intensity_class=prescription.intensity_class,
        planned_pace_min_per_km=prescription.planned_pace_min_per_km,
        actual_pace_min_per_km=None,
        matching_status=matching_status,
        adherence_status=adherence_status,
        distance_delta_km=None,
        duration_delta_min=None,
        pace_delta_min_per_km=None,
        comparison_basis=None,
        deviation_ratio=None,
        reason_codes=reason_codes,
    )


def _matched_row(
    prescription: PrescribedWorkout,
    activity: ObservedActivity,
    *,
    basis: Optional[str],
    deviation: Optional[float],
) -> PerformedWorkout:
    if basis is None:
        adherence = AdherenceStatus.COMPLETED_UNVERIFIED
        codes: List[str] = [RC_MATCHED_NO_COMPARABLE_DIMENSION]
    else:
        codes = [RC_MATCHED_ON_DISTANCE if basis == "distance" else RC_MATCHED_ON_DURATION]
        if deviation is not None and deviation <= ADHERENCE_TOLERANCE_RATIO:
            adherence = AdherenceStatus.COMPLETED_AS_PLANNED
            codes.append(RC_WITHIN_TOLERANCE)
        else:
            adherence = AdherenceStatus.COMPLETED_MODIFIED
            codes.append(RC_OUTSIDE_TOLERANCE)

    return PerformedWorkout(
        user_id=prescription.user_id,
        prescription_id=prescription.prescription_id,
        activity_id=activity.activity_id,
        planned_date=prescription.planned_date,
        actual_start_time=activity.start_time,
        planned_workout_type=prescription.workout_type,
        actual_activity_type=activity.activity_type,
        planned_distance_km=prescription.planned_distance_km,
        actual_distance_km=activity.distance_km,
        planned_duration_min=prescription.planned_duration_min,
        actual_duration_min=activity.duration_min,
        planned_intensity_class=prescription.intensity_class,
        planned_pace_min_per_km=prescription.planned_pace_min_per_km,
        actual_pace_min_per_km=activity.pace_min_per_km,
        matching_status=MatchingStatus.MATCHED,
        adherence_status=adherence,
        distance_delta_km=_delta(activity.distance_km, prescription.planned_distance_km),
        duration_delta_min=_delta(activity.duration_min, prescription.planned_duration_min),
        pace_delta_min_per_km=_delta(
            activity.pace_min_per_km, prescription.planned_pace_min_per_km
        ),
        comparison_basis=basis,
        deviation_ratio=round(deviation, 4) if deviation is not None else None,
        reason_codes=tuple(codes),
    )


def _unmatched_actual_row(activity: ObservedActivity) -> PerformedWorkout:
    return PerformedWorkout(
        user_id=activity.user_id,
        prescription_id=None,
        activity_id=activity.activity_id,
        planned_date=None,
        actual_start_time=activity.start_time,
        planned_workout_type=None,
        actual_activity_type=activity.activity_type,
        planned_distance_km=None,
        actual_distance_km=activity.distance_km,
        planned_duration_min=None,
        actual_duration_min=activity.duration_min,
        planned_intensity_class=None,
        planned_pace_min_per_km=None,
        actual_pace_min_per_km=activity.pace_min_per_km,
        matching_status=MatchingStatus.UNMATCHED_ACTUAL,
        adherence_status=AdherenceStatus.UNMATCHED_ACTUAL,
        distance_delta_km=None,
        duration_delta_min=None,
        pace_delta_min_per_km=None,
        comparison_basis=None,
        deviation_ratio=None,
        reason_codes=(RC_NO_PRESCRIPTION,),
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def build_performed_workouts(
    *,
    user_id: str,
    reference_date: date,
    prescriptions: Sequence[PrescribedWorkout],
    activities: Sequence[ObservedActivity],
) -> PerformedWorkoutLedger:
    """Reconcile prescriptions with really performed Garmin activities.

    Parameters
    ----------
    user_id
        The only user considered.  Prescriptions and activities belonging to
        another user are ignored (strict isolation).
    reference_date
        "What is known as of J".  Activities dated strictly after this date
        are dropped (no-lookahead), and no prescription whose window is still
        open can become ``missed``.
    prescriptions
        Immutable prescribed sessions.  Never mutated.
    activities
        Observed activities (Garmin truth) converted with
        :func:`to_observed_activity`.

    Returns
    -------
    PerformedWorkoutLedger
        Prescription rows first (ordered by planned_date, prescription_id),
        then unmatched real activities (ordered by date, start time, id).
    """
    own_prescriptions = sorted(
        (p for p in (prescriptions or ()) if p.user_id == user_id),
        key=lambda p: (p.planned_date, p.prescription_id),
    )

    # No-lookahead + user isolation + running only.
    usable_activities = sorted(
        (
            a
            for a in (activities or ())
            if a.user_id == user_id and a.local_date <= reference_date and a.is_running
        ),
        key=_sort_key_activity,
    )

    attributed: Dict[str, str] = {}  # activity_id → prescription_id
    rows: List[PerformedWorkout] = []

    for prescription in own_prescriptions:
        window_closed = reference_date > prescription.window_end
        is_future = prescription.planned_date > reference_date

        if prescription.is_rest:
            rows.append(
                _unmatched_prescription_row(
                    prescription,
                    matching_status=MatchingStatus.PLANNED,
                    adherence_status=AdherenceStatus.NOT_APPLICABLE,
                    reason_codes=(RC_REST_NOT_MATCHABLE,),
                )
            )
            continue

        candidates = [
            a
            for a in usable_activities
            if a.activity_id not in attributed
            and prescription.window_start <= a.local_date <= prescription.window_end
        ]

        evaluated: List[Tuple[ObservedActivity, Optional[str], Optional[float]]] = []
        rejected_for_deviation = False
        for activity in candidates:
            basis, deviation = _comparison(prescription, activity)
            if (
                basis is not None
                and deviation is not None
                and deviation > MATCH_MAX_DEVIATION_RATIO
            ):
                rejected_for_deviation = True
                continue
            evaluated.append((activity, basis, deviation))

        if not evaluated:
            codes: List[str] = []
            if rejected_for_deviation:
                codes.append(RC_CANDIDATE_REJECTED_DEVIATION)
            else:
                codes.append(RC_NO_CANDIDATE)
            if is_future:
                codes.append(RC_FUTURE_SESSION)
            codes.append(RC_WINDOW_CLOSED if window_closed else RC_WINDOW_OPEN)
            rows.append(
                _unmatched_prescription_row(
                    prescription,
                    matching_status=(
                        MatchingStatus.MISSED if window_closed else MatchingStatus.PLANNED
                    ),
                    adherence_status=(
                        AdherenceStatus.MISSED if window_closed else AdherenceStatus.PENDING
                    ),
                    reason_codes=tuple(codes),
                )
            )
            continue

        ranked = sorted(evaluated, key=lambda item: _candidate_rank(item[2], item[0]))
        best_activity, best_basis, best_deviation = ranked[0]

        if len(ranked) > 1 and _candidate_rank(ranked[0][2], ranked[0][0]) == _candidate_rank(
            ranked[1][2], ranked[1][0]
        ):
            # Genuinely ambiguous evidence: refuse to guess.
            codes = [RC_AMBIGUOUS_MULTIPLE_CANDIDATES]
            codes.append(RC_WINDOW_CLOSED if window_closed else RC_WINDOW_OPEN)
            rows.append(
                _unmatched_prescription_row(
                    prescription,
                    matching_status=(
                        MatchingStatus.MISSED if window_closed else MatchingStatus.PLANNED
                    ),
                    adherence_status=(
                        AdherenceStatus.MISSED if window_closed else AdherenceStatus.PENDING
                    ),
                    reason_codes=tuple(codes),
                )
            )
            continue

        attributed[best_activity.activity_id] = prescription.prescription_id
        rows.append(
            _matched_row(
                prescription,
                best_activity,
                basis=best_basis,
                deviation=best_deviation,
            )
        )

    for activity in usable_activities:
        if activity.activity_id not in attributed:
            rows.append(_unmatched_actual_row(activity))

    matched_count = sum(1 for r in rows if r.matching_status is MatchingStatus.MATCHED)
    missed_count = sum(1 for r in rows if r.matching_status is MatchingStatus.MISSED)
    planned_count = sum(1 for r in rows if r.matching_status is MatchingStatus.PLANNED)
    unmatched_count = sum(
        1 for r in rows if r.matching_status is MatchingStatus.UNMATCHED_ACTUAL
    )

    return PerformedWorkoutLedger(
        user_id=user_id,
        reference_date=reference_date,
        entries=tuple(rows),
        matched_count=matched_count,
        missed_count=missed_count,
        planned_count=planned_count,
        unmatched_actual_count=unmatched_count,
    )
