"""PR230 — PerformedWorkout: PRESCRIBED vs PERFORMED (Garmin actual).

Purpose
-------
This module is the first real Data Moat brick: it separates

    what RunIndex PRESCRIBED      (WorkoutPrescription / plan)
from
    what the athlete ACTUALLY DID (real Garmin activity)

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

Source of truth and provenance lock (C230 #4)
----------------------------------------------
The only accepted evidence of a performed session is a real activity coming
from ``garmin_activities``.  ``db.workouts`` is NOT a source of truth and is
not consumed here.

``to_observed_activity`` therefore REFUSES any activity whose ``source`` is not
``"garmin"`` (legacy, manual, workout, ``None`` …).  Provenance is never
re-labelled: there is no fallback that turns a non-Garmin activity into Garmin
evidence.  The sanctioned entry point from persistence is
``garmin.domain_adapter.mongo_garmin_to_observed_activity``.

Local date contract (C230 #1)
------------------------------
``DomainActivity.start_time`` must NOT be assumed to be a local time: the
normalised ``garmin_activity`` sub-document is **GMT-first**
(``startTimeGMT`` then ``startTimeLocal``), while the top-level Mongo document
is **local-first**.  A run started at 00:30 local (22:30 GMT the previous day)
would therefore land on the wrong calendar day.

Consequence: :func:`to_observed_activity` takes an explicit
``local_start_time`` argument that carries the REAL Garmin
``startTimeLocal``.  ``ObservedActivity.local_date`` is derived from that value
only.  When no local evidence exists the activity is refused (``None``) instead
of being matched on a GMT-derived day.
``garmin.domain_adapter.garmin_local_start_time`` implements the resolution.

States (matching_status)
------------------------
planned
    The prescription's matching window is not closed yet (or the session is
    in the future).  Nothing is asserted about it.
matched
    A real running activity has been deterministically attributed to it.
missed
    The matching window is definitively closed, no acceptable activity was
    attributed, **and** no ambiguity was detected.
ambiguous
    Several activities are strictly equivalent on the available evidence.
    The engine refuses to choose.  An ambiguous prescription is never matched,
    never missed, never completed — even after the window has closed.
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
4. Deviation guard, applied to EVERY comparable dimension (see below): if any
   comparable dimension deviates by more than ``MATCH_MAX_DEVIATION_RATIO``,
   the activity is NOT the realisation of that prescription.
5. One activity can be attributed to at most one prescription.
6. Multi-activity resolution (C230 #2): candidates are ranked by their worst
   comparable deviation only.  Clock time is NOT a business criterion unless
   a start time was really prescribed (``planned_start_time``), in which case
   proximity to that prescribed time is used as an explicit second key.
   If the two best candidates remain strictly equal on those real criteria,
   the prescription is ``ambiguous`` and no activity is attributed.

Multi-dimension adherence (C230 #3)
------------------------------------
Adherence uses EVERY dimension that is really available on BOTH sides:

    distance   — planned_distance_km      vs actual distance
    duration   — planned_duration_min     vs actual duration
    pace       — planned_pace_min_per_km  vs actual pace
                 (only when a pace was REALLY prescribed)

A dimension is comparable only when both sides carry a strictly positive
value.  A missing dimension is never fabricated.

    completed_as_planned
        matched and ALL comparable dimensions stay within
        ``ADHERENCE_TOLERANCE_RATIO``.
    completed_modified
        matched, but at least one comparable dimension exceeds the tolerance
        (while all stay within ``MATCH_MAX_DEVIATION_RATIO``).
    completed_unverified
        matched on date + running type, with no comparable dimension at all.
    missed / ambiguous / unmatched_actual
        mirror the corresponding matching_status.
    pending
        nothing can be asserted yet (window still open / future session).
    not_applicable
        rest day: never matched, never missed.

Example that the previous single-dimension logic got wrong:
planned 10 km / 60 min, performed 10 km / 120 min → the duration deviation is
+100 %, above the guard, so the activity is NOT the realisation of that
session.  It can never be reported as ``completed_as_planned``.

Raw deltas (``distance_delta_km``, ``duration_delta_min``,
``pace_delta_min_per_km``) are kept as-is, signed (actual − planned), and are
``None`` when not computable.  Per-dimension deviation ratios are exposed too.

No-lookahead guarantee
----------------------
Activities whose local date is strictly after ``reference_date`` are dropped
before any matching happens.  A future activity can therefore never change the
state of a historical prescription, and a future prescription is always
``planned``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
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

GARMIN_SOURCE: str = "garmin"
"""The only activity provenance accepted as performed-workout evidence."""

COMPARABLE_DIMENSIONS: Tuple[str, ...] = ("distance", "duration", "pace")
"""All dimensions evaluated when both sides really carry a value."""

_ROUND = 2


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MatchingStatus(str, Enum):
    """Deterministic state of a prescription / actual activity pair."""

    PLANNED = "planned"
    MATCHED = "matched"
    MISSED = "missed"
    AMBIGUOUS = "ambiguous"
    UNMATCHED_ACTUAL = "unmatched_actual"


class AdherenceStatus(str, Enum):
    """Factual adherence diagnostic. No arbitrary physiological score."""

    PENDING = "pending"
    COMPLETED_AS_PLANNED = "completed_as_planned"
    COMPLETED_MODIFIED = "completed_modified"
    COMPLETED_UNVERIFIED = "completed_unverified"
    MISSED = "missed"
    AMBIGUOUS = "ambiguous"
    UNMATCHED_ACTUAL = "unmatched_actual"
    NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Reason codes (language-neutral, stable)
# ---------------------------------------------------------------------------

RC_MATCHED_ON_DISTANCE = "MATCHED_ON_DISTANCE"
RC_MATCHED_ON_DURATION = "MATCHED_ON_DURATION"
RC_MATCHED_ON_PACE = "MATCHED_ON_PACE"
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
RC_RESOLVED_BY_PLANNED_START_TIME = "RESOLVED_BY_PLANNED_START_TIME"


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

    planned_start_time: Optional[time] = None
    """Local clock time, ONLY when a start time was really prescribed.

    Clock proximity is otherwise not a business criterion: without a prescribed
    start time, an earlier run is not better evidence than a later one.
    """

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
    """A real activity actually performed by the athlete (Garmin truth).

    ``local_date`` / ``start_time`` are the REAL device-local values
    (``startTimeLocal``), never a GMT-derived approximation.
    """

    model_config = ConfigDict(frozen=True)

    activity_id: str
    user_id: str
    local_date: date
    start_time: Optional[datetime] = None
    """Local start datetime, when the local value carries a clock component."""

    source: str = GARMIN_SOURCE
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

    distance_deviation_ratio: Optional[float] = None
    duration_deviation_ratio: Optional[float] = None
    pace_deviation_ratio: Optional[float] = None

    comparison_dimensions: Tuple[str, ...] = ()
    """Dimensions really comparable on BOTH sides: distance / duration / pace."""

    deviation_ratio: Optional[float] = None
    """Worst absolute relative deviation across comparable dimensions."""

    candidate_activity_ids: Tuple[str, ...] = ()
    """Activities involved in an ambiguous situation (never attributed)."""

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
    ambiguous_count: int
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
    local_start_time: Any,
    activity_id: Optional[str] = None,
) -> Optional[ObservedActivity]:
    """Convert a Garmin :class:`DomainActivity` into an :class:`ObservedActivity`.

    Parameters
    ----------
    activity
        A :class:`DomainActivity` (or coercible input) produced by the Garmin
        normalisation layer.
    user_id
        Owner of the evidence.
    local_start_time
        The REAL device-local start time (``startTimeLocal``).  Mandatory:
        ``DomainActivity.start_time`` is GMT-first and must never be used to
        derive the local calendar day.

    Returns
    -------
    ``None`` when the activity cannot become evidence:

    - provenance is not Garmin (``source != "garmin"``) — no re-labelling;
    - no usable local start time;
    - no stable activity identifier.
    """
    domain: DomainActivity = (
        activity if isinstance(activity, DomainActivity) else to_domain_activity(activity)
    )

    if domain.source != GARMIN_SOURCE:
        return None

    local_date = _parse_date(local_start_time)
    if local_date is None:
        return None

    resolved_id = activity_id if activity_id is not None else domain.source_activity_id
    if not isinstance(resolved_id, str) or resolved_id == "":
        return None

    distance_m = _positive_float(domain.distance_m)
    distance_km = round(distance_m / 1000.0, 3) if distance_m is not None else None

    duration_s = _positive_float(domain.duration_s)
    duration_min = round(duration_s / 60.0, 2) if duration_s is not None else None

    pace = None
    if distance_km is not None and duration_min is not None and distance_km > 0:
        pace = round(duration_min / distance_km, _ROUND)

    return ObservedActivity(
        activity_id=resolved_id,
        user_id=user_id,
        local_date=local_date,
        start_time=_parse_datetime(local_start_time),
        source=GARMIN_SOURCE,
        activity_type=domain.activity_type,
        distance_km=distance_km,
        duration_min=duration_min,
        pace_min_per_km=pace,
    )


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _ratio(planned: Optional[float], actual: Optional[float]) -> Optional[float]:
    """Absolute relative deviation, or None when the dimension is not comparable."""
    p = _positive_float(planned)
    a = _positive_float(actual)
    if p is None or a is None:
        return None
    return abs(a - p) / p


def _deviations(
    prescription: PrescribedWorkout,
    activity: ObservedActivity,
) -> Dict[str, float]:
    """Return the deviation of every dimension comparable on BOTH sides.

    Pace is only considered when a pace was REALLY prescribed; it is never
    derived from the prescription's distance/duration.
    """
    deviations: Dict[str, float] = {}

    distance = _ratio(prescription.planned_distance_km, activity.distance_km)
    if distance is not None:
        deviations["distance"] = distance

    duration = _ratio(prescription.planned_duration_min, activity.duration_min)
    if duration is not None:
        deviations["duration"] = duration

    pace = _ratio(prescription.planned_pace_min_per_km, activity.pace_min_per_km)
    if pace is not None:
        deviations["pace"] = pace

    return deviations


def _worst_deviation(deviations: Dict[str, float]) -> Optional[float]:
    return max(deviations.values()) if deviations else None


def _sort_key_activity(activity: ObservedActivity) -> Tuple[Any, ...]:
    """Stable, deterministic ordering for observed activities (output only)."""
    return (
        activity.local_date,
        activity.start_time.isoformat() if activity.start_time is not None else "",
        activity.activity_id,
    )


def _start_time_distance_seconds(
    prescription: PrescribedWorkout,
    activity: ObservedActivity,
) -> Optional[float]:
    """Absolute gap to the PRESCRIBED start time, or None when not prescribed.

    This is the only situation where clock time is a legitimate business
    criterion: it compares the activity to a real prescription, not one
    activity to another.
    """
    planned = prescription.planned_start_time
    if planned is None or activity.start_time is None:
        return None
    planned_seconds = planned.hour * 3600 + planned.minute * 60 + planned.second
    actual = activity.start_time
    actual_seconds = actual.hour * 3600 + actual.minute * 60 + actual.second
    return abs(float(actual_seconds - planned_seconds))


def _candidate_rank(
    deviation: Optional[float],
    start_gap_seconds: Optional[float],
) -> Tuple[float, float]:
    """Comparison keys used to elect the best candidate.

    Only REAL evidence is used:
      1. worst deviation across comparable prescribed dimensions;
      2. distance to the prescribed start time, when a start time was really
         prescribed (otherwise neutral for every candidate).

    Neither ``activity_id`` nor the raw clock time is part of this key: two
    activities equally compatible with the prescription must be reported as
    ambiguous, never silently disambiguated.
    """
    dev = deviation if deviation is not None else float("inf")
    gap = start_gap_seconds if start_gap_seconds is not None else 0.0
    return (dev, gap)


def _delta(actual: Optional[float], planned: Optional[float]) -> Optional[float]:
    a = _positive_float(actual)
    p = _positive_float(planned)
    if a is None or p is None:
        return None
    return round(a - p, _ROUND)


def _round_ratio(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _unmatched_prescription_row(
    prescription: PrescribedWorkout,
    *,
    matching_status: MatchingStatus,
    adherence_status: AdherenceStatus,
    reason_codes: Tuple[str, ...],
    candidate_activity_ids: Tuple[str, ...] = (),
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
        distance_deviation_ratio=None,
        duration_deviation_ratio=None,
        pace_deviation_ratio=None,
        comparison_dimensions=(),
        deviation_ratio=None,
        candidate_activity_ids=candidate_activity_ids,
        reason_codes=reason_codes,
    )


_DIMENSION_REASON_CODE: Dict[str, str] = {
    "distance": RC_MATCHED_ON_DISTANCE,
    "duration": RC_MATCHED_ON_DURATION,
    "pace": RC_MATCHED_ON_PACE,
}


def _matched_row(
    prescription: PrescribedWorkout,
    activity: ObservedActivity,
    *,
    deviations: Dict[str, float],
    resolved_by_start_time: bool,
) -> PerformedWorkout:
    dimensions = tuple(d for d in COMPARABLE_DIMENSIONS if d in deviations)
    worst = _worst_deviation(deviations)

    if not dimensions:
        adherence = AdherenceStatus.COMPLETED_UNVERIFIED
        codes: List[str] = [RC_MATCHED_NO_COMPARABLE_DIMENSION]
    else:
        codes = [_DIMENSION_REASON_CODE[d] for d in dimensions]
        if worst is not None and worst <= ADHERENCE_TOLERANCE_RATIO:
            adherence = AdherenceStatus.COMPLETED_AS_PLANNED
            codes.append(RC_WITHIN_TOLERANCE)
        else:
            adherence = AdherenceStatus.COMPLETED_MODIFIED
            codes.append(RC_OUTSIDE_TOLERANCE)

    if resolved_by_start_time:
        codes.append(RC_RESOLVED_BY_PLANNED_START_TIME)

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
        distance_deviation_ratio=_round_ratio(deviations.get("distance")),
        duration_deviation_ratio=_round_ratio(deviations.get("duration")),
        pace_deviation_ratio=_round_ratio(deviations.get("pace")),
        comparison_dimensions=dimensions,
        deviation_ratio=_round_ratio(worst),
        candidate_activity_ids=(),
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
        distance_deviation_ratio=None,
        duration_deviation_ratio=None,
        pace_deviation_ratio=None,
        comparison_dimensions=(),
        deviation_ratio=None,
        candidate_activity_ids=(),
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
        Observed Garmin activities built with
        :func:`garmin.domain_adapter.mongo_garmin_to_observed_activity`.

    Returns
    -------
    PerformedWorkoutLedger
        Prescription rows first (ordered by planned_date, prescription_id),
        then unmatched real activities (ordered by local date, start time, id).
    """
    own_prescriptions = sorted(
        (p for p in (prescriptions or ()) if p.user_id == user_id),
        key=lambda p: (p.planned_date, p.prescription_id),
    )

    # No-lookahead + user isolation + Garmin provenance + running only.
    usable_activities = sorted(
        (
            a
            for a in (activities or ())
            if a.user_id == user_id
            and a.source == GARMIN_SOURCE
            and a.local_date <= reference_date
            and a.is_running
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

        evaluated: List[Tuple[ObservedActivity, Dict[str, float], Optional[float]]] = []
        rejected_for_deviation = False
        for activity in candidates:
            deviations = _deviations(prescription, activity)
            worst = _worst_deviation(deviations)
            if worst is not None and worst > MATCH_MAX_DEVIATION_RATIO:
                # At least one comparable dimension makes this activity
                # incompatible with the prescription.
                rejected_for_deviation = True
                continue
            evaluated.append(
                (
                    activity,
                    deviations,
                    _start_time_distance_seconds(prescription, activity),
                )
            )

        if not evaluated:
            codes: List[str] = []
            codes.append(
                RC_CANDIDATE_REJECTED_DEVIATION if rejected_for_deviation else RC_NO_CANDIDATE
            )
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

        ranked = sorted(
            evaluated,
            key=lambda item: _candidate_rank(_worst_deviation(item[1]), item[2]),
        )
        best_rank = _candidate_rank(_worst_deviation(ranked[0][1]), ranked[0][2])

        if len(ranked) > 1 and best_rank == _candidate_rank(
            _worst_deviation(ranked[1][1]), ranked[1][2]
        ):
            # Genuinely equivalent evidence: refuse to guess, and never
            # degrade the uncertainty into "missed" — even after the window
            # has closed.  The candidate activities stay unattributed.
            tied_ids = tuple(
                sorted(
                    activity.activity_id
                    for activity, deviations, gap in ranked
                    if _candidate_rank(_worst_deviation(deviations), gap) == best_rank
                )
            )
            rows.append(
                _unmatched_prescription_row(
                    prescription,
                    matching_status=MatchingStatus.AMBIGUOUS,
                    adherence_status=AdherenceStatus.AMBIGUOUS,
                    reason_codes=(
                        RC_AMBIGUOUS_MULTIPLE_CANDIDATES,
                        RC_WINDOW_CLOSED if window_closed else RC_WINDOW_OPEN,
                    ),
                    candidate_activity_ids=tied_ids,
                )
            )
            continue

        best_activity, best_deviations, best_gap = ranked[0]
        attributed[best_activity.activity_id] = prescription.prescription_id
        rows.append(
            _matched_row(
                prescription,
                best_activity,
                deviations=best_deviations,
                resolved_by_start_time=best_gap is not None,
            )
        )

    for activity in usable_activities:
        if activity.activity_id not in attributed:
            rows.append(_unmatched_actual_row(activity))

    def _count(status: MatchingStatus) -> int:
        return sum(1 for r in rows if r.matching_status is status)

    return PerformedWorkoutLedger(
        user_id=user_id,
        reference_date=reference_date,
        entries=tuple(rows),
        matched_count=_count(MatchingStatus.MATCHED),
        missed_count=_count(MatchingStatus.MISSED),
        planned_count=_count(MatchingStatus.PLANNED),
        ambiguous_count=_count(MatchingStatus.AMBIGUOUS),
        unmatched_actual_count=_count(MatchingStatus.UNMATCHED_ACTUAL),
    )
