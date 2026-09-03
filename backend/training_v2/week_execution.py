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
- C231 — Prescription snapshot: a session whose ``planned_date`` is today or
  in the past is matched (and displayed) against its FROZEN
  ``PrescriptionSnapshot`` when one already exists — never against a
  recomputed live prescription (see ``prescription_snapshot.py``). Any
  newly-eligible session without an existing snapshot is reported back via
  ``WeekExecutionResult.snapshots_to_persist`` for the caller to persist with
  an insert-only write.
- C231 — ``unmatched_actuals`` are scoped to the current week only
  (``[week_start, week_start + 6]`` by Garmin local date); older or newer
  unmatched Garmin activities are never exposed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Mapping, Optional, Sequence

from garmin.domain_adapter import mongo_garmin_to_observed_activities

from .performed_workout import (
    PerformedWorkout,
    PrescribedWorkout,
    build_performed_workouts,
)
from .prescription_snapshot import (
    PrescriptionSnapshot,
    is_freezable,
    resolve_effective_session,
    snapshot_from_prescription,
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


@dataclass(frozen=True)
class SessionExecution:
    """One WeeklyPlan session paired with its factual execution row.

    ``session`` is the EFFECTIVE prescription actually used for matching and
    display: the frozen snapshot when one exists for this ``planned_date``,
    otherwise the live (possibly still-evolving) ``WorkoutPrescription``.
    """

    session: WorkoutPrescription
    row: PerformedWorkout


@dataclass(frozen=True)
class WeekExecutionResult:
    """Result of reconciling one week's sessions with Garmin actuals."""

    sessions: List[SessionExecution]
    """One entry per input session, same order (Monday → Sunday)."""

    extra_rows: List[PerformedWorkout]
    """Garmin activities not attributed to any session of this week,
    already restricted to ``[week_start, week_start + 6]`` by local date."""

    snapshots_to_persist: List[PrescriptionSnapshot]
    """Newly-frozen snapshots (session is freezable and had no existing
    snapshot yet). Callers MUST persist with an insert-only write."""


def _session_planned_date(day: str, week_start: date) -> date:
    offset = _DAY_INDEX.get(day.lower() if isinstance(day, str) else "")
    if offset is None:
        raise ValueError(f"Unknown day name '{day}' — cannot resolve planned_date.")
    return week_start + timedelta(days=offset)


def prescription_id_for(user_id: str, planned_date: date, day: str) -> str:
    """Public — the SAME ``prescription_id`` format used internally here, so
    callers (e.g. server.py) can look up/compare against a specific
    prescription without duplicating the format string."""
    return _prescription_id(user_id, planned_date, day)


def _prescription_id(user_id: str, planned_date: date, day: str) -> str:
    return f"{user_id}:{planned_date.isoformat()}:{day.lower()}"


def build_week_execution(
    *,
    user_id: str,
    reference_date: date,
    week_start: date,
    sessions: Sequence[WorkoutPrescription],
    garmin_docs: Sequence[dict],
    frozen_snapshots: Optional[Mapping[str, PrescriptionSnapshot]] = None,
) -> WeekExecutionResult:
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
    frozen_snapshots
        Existing ``PrescriptionSnapshot`` rows for this user, keyed by
        ``prescription_id``, already fetched by the caller. When a session's
        ``prescription_id`` is present here, its snapshot is authoritative
        for BOTH matching and display — the live session is ignored.

    Returns
    -------
    WeekExecutionResult
        One ``SessionExecution`` per input session (same order), the extra
        Garmin activities restricted to the current week
        (``matching_status == unmatched_actual``), and any newly-frozen
        snapshots the caller must persist.
    """
    frozen_snapshots = frozen_snapshots or {}
    week_end = week_start + timedelta(days=6)

    prescriptions: List[PrescribedWorkout] = []
    effective_sessions: List[WorkoutPrescription] = []
    snapshots_to_persist: List[PrescriptionSnapshot] = []

    for session in sessions:
        planned_date = _session_planned_date(session.day, week_start)
        prescription_id = _prescription_id(user_id, planned_date, session.day)
        frozen = frozen_snapshots.get(prescription_id)
        effective = resolve_effective_session(
            live_session=session, frozen_snapshot=frozen
        )
        effective_sessions.append(effective)

        if frozen is None and is_freezable(
            planned_date=planned_date, reference_date=reference_date
        ):
            snapshots_to_persist.append(
                snapshot_from_prescription(
                    user_id=user_id,
                    prescription_id=prescription_id,
                    planned_date=planned_date,
                    session=session,
                )
            )

        prescriptions.append(
            PrescribedWorkout(
                prescription_id=prescription_id,
                user_id=user_id,
                planned_date=planned_date,
                workout_type=effective.workout_type,
                intensity_class=effective.intensity_class,
                planned_distance_km=effective.distance_km,
                planned_duration_min=(
                    float(effective.duration_minutes)
                    if effective.duration_minutes is not None
                    else None
                ),
                planned_pace_min_per_km=None,
                planned_start_time=None,
            )
        )

    observed_activities = mongo_garmin_to_observed_activities(
        list(garmin_docs or []), user_id=user_id
    )
    activity_local_dates: Dict[str, date] = {
        activity.activity_id: activity.local_date for activity in observed_activities
    }

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

    session_executions: List[SessionExecution] = []
    for i, prescription in enumerate(prescriptions):
        row = by_prescription_id.get(prescription.prescription_id)
        if row is None:
            # C231 — fail-fast invariant: build_performed_workouts MUST emit
            # exactly one ledger row per prescription passed in. Silently
            # dropping a session here would truncate the week without any
            # signal to the caller — never acceptable.
            raise ValueError(
                "build_week_execution invariant violated: prescription "
                f"'{prescription.prescription_id}' has no matching row in the "
                "PR230 ledger (by_prescription_id). Exactly one row per "
                "prescription is required; the week must never be silently "
                "truncated."
            )
        session_executions.append(
            SessionExecution(session=effective_sessions[i], row=row)
        )

    # C231 — unmatched_actuals are scoped to the CURRENT week only: an extra
    # Garmin activity from a previous or future week is never exposed here,
    # even though it stays available in the ledger for matching purposes.
    extra_activities: List[PerformedWorkout] = [
        row
        for row in ledger.entries
        if row.prescription_id is None
        and row.activity_id is not None
        and activity_local_dates.get(row.activity_id) is not None
        and week_start <= activity_local_dates[row.activity_id] <= week_end
    ]

    return WeekExecutionResult(
        sessions=session_executions,
        extra_rows=extra_activities,
        snapshots_to_persist=snapshots_to_persist,
    )


__all__ = ["build_week_execution", "WeekExecutionResult", "SessionExecution", "prescription_id_for"]
