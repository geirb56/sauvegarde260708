"""PR232A — Bridge: attach factual execution (PR230) to a WeeklyPlan.

Wires WorkoutPrescription sessions from a V2 WeeklyPlan to real Garmin
activities, producing one PerformedWorkout row per session — in the SAME
order as WeeklyPlan.sessions (Monday → Sunday) — plus any extra Garmin
activity that could not be attributed to a session of this week.

Design rules
------------
- PURE: no MongoDB, no HTTP, no Garmin client. The caller supplies
  already-fetched raw ``garmin_activities`` documents and ``reference_date``.
- Source of truth for ``actual`` is Garmin ONLY (PR230 boundary via
  ``garmin.domain_adapter.mongo_garmin_to_observed_activities``). There is no
  fallback to ``db.workouts`` and no calendar-only guess.
- None ≠ 0: a missing prescribed or observed value stays ``None``.
- Future sessions stay ``planned`` (no-lookahead is enforced by
  ``performed_workout.build_performed_workouts``).
- Ambiguity is preserved: an ``ambiguous`` prescription is never coerced into
  ``matched`` or ``missed``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Sequence

from garmin.domain_adapter import mongo_garmin_to_observed_activities

from .performed_workout import (
    PerformedWorkout,
    PrescribedWorkout,
    build_performed_workouts,
)
from .workout_generator import WorkoutPrescription

_DAY_INDEX: Dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
"""Monday → Sunday index, mirrors workout_generator._ALL_DAYS ordering."""


def _session_planned_date(day: str, week_start: date) -> date:
    offset = _DAY_INDEX.get(day.lower() if isinstance(day, str) else "")
    if offset is None:
        raise ValueError(f"Unknown day name '{day}' — cannot resolve planned_date.")
    return week_start + timedelta(days=offset)


def _prescription_id(user_id: str, planned_date: date, day: str) -> str:
    return f"{user_id}:{planned_date.isoformat()}:{day.lower()}"


def build_week_execution(
    *,
    user_id: str,
    reference_date: date,
    week_start: date,
    sessions: Sequence[WorkoutPrescription],
    garmin_docs: Sequence[dict],
) -> List[PerformedWorkout]:
    """Reconcile one week's WorkoutPrescription sessions with Garmin actuals.

    Parameters
    ----------
    user_id
        Owner of both the sessions and the Garmin activities. Strict
        isolation: nothing belonging to another user can leak in.
    reference_date
        "What is known as of J" — no-lookahead anchor.
    week_start
        Monday of the week the ``sessions`` belong to.
    sessions
        WorkoutPrescription rows from WeeklyPlan.sessions, Monday → Sunday.
    garmin_docs
        Raw ``db.garmin_activities`` documents (already fetched by the
        caller). Only documents with ``source == "garmin"`` become evidence.

    Returns
    -------
    One PerformedWorkout per input session (same order), followed by any
    Garmin activity that could not be attributed to a session of this week
    (``matching_status == unmatched_actual``) — it stays visible, never
    dropped.
    """
    prescriptions: List[PrescribedWorkout] = []
    for session in sessions:
        planned_date = _session_planned_date(session.day, week_start)
        prescriptions.append(
            PrescribedWorkout(
                prescription_id=_prescription_id(user_id, planned_date, session.day),
                user_id=user_id,
                planned_date=planned_date,
                workout_type=session.workout_type,
                intensity_class=session.intensity_class,
                planned_distance_km=session.distance_km,
                planned_duration_min=(
                    float(session.duration_minutes)
                    if session.duration_minutes is not None
                    else None
                ),
                planned_pace_min_per_km=None,
                planned_start_time=None,
            )
        )

    observed_activities = mongo_garmin_to_observed_activities(
        list(garmin_docs or []), user_id=user_id
    )

    ledger = build_performed_workouts(
        user_id=user_id,
        reference_date=reference_date,
        prescriptions=prescriptions,
        activities=observed_activities,
    )

    by_prescription_id = {
        row.prescription_id: row
        for row in ledger.entries
        if row.prescription_id is not None
    }

    ordered_rows: List[PerformedWorkout] = [
        by_prescription_id[prescription.prescription_id]
        for prescription in prescriptions
        if prescription.prescription_id in by_prescription_id
    ]
    extra_activities: List[PerformedWorkout] = [
        row for row in ledger.entries if row.prescription_id is None
    ]

    return ordered_rows + extra_activities


__all__ = ["build_week_execution"]
