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
- C231 (round 2) — a past day that was never actually served/frozen has no
  real prescription to match against. This is a BRIDGE-level fact, never a
  PR230 ``MatchingStatus``/``AdherenceStatus`` value: PR230's own enums stay
  limited to the states ``build_performed_workouts`` can really produce
  (``planned``/``matched``/``missed``/``ambiguous``/``unmatched_actual`` and
  their adherence counterparts). Such a day is excluded from PR230 matching
  entirely and reported here as ``SessionExecution(row=None,
  execution_status=EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE)``.
- C231 (corrections finales) — this applies UNCONDITIONALLY to every
  strictly past, un-frozen day, including one whose live recompute (today)
  says ``rest``: without a frozen historical snapshot there is no way to
  know whether that day really was a rest day when it should have been
  served. The previous rest-day exemption was incorrect and has been
  removed. A day that DOES have an existing frozen snapshot (rest or
  active) is unaffected and still matched normally against PR230.
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
from .periodization import PeriodizationSnapshot
from .plan_goal import PlanGoal
from .prescription_snapshot import (
    PrescriptionSnapshot,
    STRUCTURED_STATUS_FUTURE_LIVE,
    STRUCTURED_STATUS_HISTORICAL_FROZEN,
    STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE,
    STRUCTURED_STATUS_TODAY_SERVED,
    resolve_effective_session,
    resolve_structured_status,
    snapshot_from_prescription,
)
from .structured_workout import StructuredWorkoutPrescription, build_structured_workout_prescription
from .training_paces import TrainingPaces
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

EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE: str = "prescription_unavailable"
"""C231 (round 2) — bridge/API-level execution status for a past day that
was never actually served/frozen while it was current. Deliberately NOT a
PR230 ``MatchingStatus``/``AdherenceStatus`` value (PR230's engine never
produces this state); it lives only in ``SessionExecution.execution_status``
and the corresponding API response field."""


@dataclass(frozen=True)
class SessionExecution:
    """One WeeklyPlan session paired with its factual execution outcome.

    ``session`` is the EFFECTIVE prescription actually used for matching and
    display: the frozen snapshot when one exists for this ``planned_date``,
    otherwise the live (possibly still-evolving) ``WorkoutPrescription``.

    ``row`` is the PR230 reconciliation row (``planned``/``matched``/
    ``missed``/``ambiguous``/``unmatched_actual``) — ``None`` when
    ``execution_status`` is set instead (see below), since PR230 was never
    consulted for that day.

    ``execution_status`` is a bridge-level fact, never fabricated into a
    PR230 state: ``EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE`` when this
    day's real historical prescription cannot be trusted (never frozen while
    it was current) — ``None`` otherwise (normal PR230-backed session, see
    ``row``).
    """

    session: WorkoutPrescription
    planned_date: date
    row: Optional[PerformedWorkout]
    execution_status: Optional[str] = None
    prescription_id: Optional[str] = None
    """C235 (corrective audit) — the SAME canonical ``prescription_id``
    format used by ``/training/today`` (see ``prescription_id_for`` below),
    computed for EVERY session (including
    ``EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE`` ones, where ``row`` is
    ``None``) so Today and Week can be compared on a common identity for
    the same day. Never a new/artificial identifier."""
    modified_from_planned: Optional[bool] = None
    """C235 (final correction) — the WINNING snapshot's own frozen
    ``modified_from_planned`` fact (identical source ``/training/today``
    reads for the exact same day), so Today and Week converge on the same
    "was this session adapted away from the plan" truth. NEVER recomputed
    here by comparing ``session``/``effective`` against the CURRENT live
    plan — that comparison is exactly what C235 forbids: the value
    describes a fact frozen at serve time and must never change
    retroactively if the live plan later changes. ``None`` when no
    trustworthy snapshot fact is available at all: either
    ``EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE``, or a legacy (pre-C231)
    snapshot that predates this field. ``None`` is never coerced to
    ``False``."""
    structured: Optional[StructuredWorkoutPrescription] = None
    """C234 — StructuredWorkoutPrescriptionEngine output built from
    ``session`` (the EFFECTIVE FINAL prescription above — frozen snapshot
    when one exists, else live — never a stale pre-adaptation parent).
    ``None`` when ``plan_goal``/``periodization`` were not supplied to
    ``build_week_execution``, when this day's prescription itself is
    untrustworthy (``execution_status ==
    EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE``), OR when this is a STRICT
    HISTORICAL day (``planned_date < reference_date``) backed ONLY by a
    legacy (pre-#235) parent-only snapshot — see ``structured_status``
    below. Never structuring a fact that isn't real."""
    structured_status: Optional[str] = None
    """#235 — machine-readable status explaining ``structured``'s value,
    set only when structuring was requested (i.e. ``plan_goal``/
    ``periodization`` were supplied to ``build_week_execution``):

    - ``"today_served"``  — ``planned_date == reference_date``: structured
      from the atomically-served, frozen V2 snapshot for today. Trustworthy.
    - ``"future_live"``   — ``planned_date > reference_date``: structured
      from a still-evolving, not-yet-served live prescription. Prospective —
      may legitimately change before it is actually served.
    - ``"historical_frozen"`` (#235) — ``planned_date < reference_date``
      with an existing V2 ``PrescriptionSnapshot`` whose ``structured``
      field was frozen at serve time. Read AS-IS from the snapshot, NEVER
      recomputed from CURRENT goal/phase/paces/engine rules — historical
      truth is the snapshot.
    - ``"historical_unavailable"`` — ``planned_date < reference_date`` with
      either no snapshot at all, or a legacy (pre-#235) snapshot whose
      PARENT (workout_type/distance/duration) is frozen and trustworthy but
      never captured a STRUCTURED payload. Recomputing structure now from
      CURRENT rules would silently rewrite history — forbidden, and NEVER
      backfilled. ``structured`` is always ``None`` here.
    - ``"prescription_unavailable"`` — mirrors ``execution_status``: no
      trustworthy prescription at all for this day.

    ``None`` when structuring was not requested at all (``plan_goal``/
    ``periodization`` omitted) — pre-C234 behaviour, unchanged."""


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
    plan_goal: Optional[PlanGoal] = None,
    periodization: Optional[PeriodizationSnapshot] = None,
    training_paces: Optional[TrainingPaces] = None,
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
    plan_goal, periodization, training_paces
        C234 — when ``plan_goal`` and ``periodization`` are supplied, each
        ``SessionExecution.structured`` is populated by
        ``StructuredWorkoutPrescriptionEngine`` from the EFFECTIVE session
        (frozen snapshot when one exists, else live — see ``session`` above),
        wiring the engine into the real Week pipeline. ``training_paces``
        MUST come from the single canonical Training Paces authority (see
        ``training_paces_authority.load_canonical_training_paces``), never a
        locally recomputed value over a different activity window. Omitted
        (``structured=None``) for ``EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE``
        days, and — C234 (final corrective audit), BLOCKER 2 FIX — also
        omitted for any STRICT HISTORICAL day (``planned_date <
        reference_date``) even when a frozen parent snapshot exists: only
        the FROZEN PARENT (workout_type/distance/duration) is trustworthy
        history; no structured snapshot has been frozen for it (that is
        #235's job), so recomputing structure from today's goal/phase/paces
        would silently rewrite history. See ``SessionExecution.
        structured_status`` for the machine-readable reason.

    Returns
    -------
    WeekExecutionResult
        One ``SessionExecution`` per input session (same order), the extra
        Garmin activities restricted to the current week
        (``matching_status == unmatched_actual``), and any newly-frozen
        snapshots the caller must persist.

    C231 (P0 #3) — a NEW snapshot is only ever proposed for ``planned_date ==
    reference_date`` (today, being served for the very first time). A
    strictly past session (``planned_date < reference_date``) with no
    existing frozen snapshot was NEVER actually served while it was current:
    its live (recomputed today) prescription is NOT trusted as historical
    truth — including when today's recompute says ``rest``. Without a
    frozen historical snapshot there is no way to know whether that day
    really was a rest day at the time it should have been served (C231
    corrections finales — the previous ``rest``-day exemption was incorrect
    and has been removed). It is excluded from PR230 matching entirely and
    reported as ``execution_status=EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE``
    (with ``row=None``) instead of being silently fabricated into
    ``matched``/``missed``/``completed_modified``/``planned``/
    ``not_applicable``. A day WITH an existing frozen snapshot (including a
    genuinely-frozen historical rest day) is unaffected and still goes
    through normal PR230 matching.
    """
    frozen_snapshots = frozen_snapshots or {}
    week_end = week_start + timedelta(days=6)

    prescriptions: List[PrescribedWorkout] = []
    snapshots_to_persist: List[PrescriptionSnapshot] = []
    # prescription_ids excluded from PR230 matching entirely (see docstring
    # above) — never given a fabricated PR230 row.
    unavailable_prescription_ids: set = set()
    # C235 (final correction) — modified_from_planned for a session frozen
    # by THIS SAME call's own bare-Week-only fallback branch below (not yet
    # present in `frozen_snapshots`, which was fetched by the caller BEFORE
    # this function ran). Tracked separately so the SessionExecution built
    # further down for that exact prescription_id reports the SAME fact
    # (False — served == planned by construction) it is persisting, instead
    # of falling back to None for the one call that actually creates it.
    self_created_modified_from_planned: Dict[str, bool] = {}

    for session in sessions:
        planned_date = _session_planned_date(session.day, week_start)
        prescription_id = _prescription_id(user_id, planned_date, session.day)
        frozen = frozen_snapshots.get(prescription_id)
        effective = resolve_effective_session(
            live_session=session, frozen_snapshot=frozen
        )

        # C231 corrections finales — no rest-day exception: without a
        # frozen historical snapshot, today's live recompute (rest or not)
        # is never trusted as historical fact for a strictly past day.
        if frozen is None and planned_date < reference_date:
            unavailable_prescription_ids.add(prescription_id)
            continue

        if frozen is None and planned_date == reference_date:
            # #235 — build+freeze STRUCTURED in the SAME snapshot as the
            # PARENT, at this exact creation instant, so this fallback path
            # (a bare Week call that is the FIRST ever caller for today,
            # with no prior Today/Week call) never leaves structure to be
            # recomputed later against possibly-different rules.
            fallback_structured: Optional[StructuredWorkoutPrescription] = None
            if plan_goal is not None and periodization is not None:
                fallback_structured = build_structured_workout_prescription(
                    workout=session,
                    plan_goal=plan_goal,
                    periodization=periodization,
                    training_paces=training_paces,
                )
            snapshots_to_persist.append(
                snapshot_from_prescription(
                    user_id=user_id,
                    prescription_id=prescription_id,
                    planned_date=planned_date,
                    session=session,
                    # This fallback path persists the RAW plan `session`
                    # itself as-is (no adaptation candidate available here —
                    # the normal "today" path in server.py, which does know
                    # the adaptation candidate, freezes it earlier via
                    # get_or_create_served_prescription and populates
                    # frozen_snapshots before this function is even called).
                    # served == planned by construction ⇒ never modified.
                    modified_from_planned=False,
                    structured=fallback_structured,
                    adaptation_action=None,
                    adaptation_reason_codes=(),
                )
            )
            self_created_modified_from_planned[prescription_id] = False

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
    for session in sessions:
        planned_date = _session_planned_date(session.day, week_start)
        prescription_id = _prescription_id(user_id, planned_date, session.day)
        effective = resolve_effective_session(
            live_session=session, frozen_snapshot=frozen_snapshots.get(prescription_id)
        )

        if prescription_id in unavailable_prescription_ids:
            session_executions.append(
                SessionExecution(
                    session=effective,
                    planned_date=planned_date,
                    row=None,
                    execution_status=EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE,
                    prescription_id=prescription_id,
                    structured_status=(
                        EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE
                        if (plan_goal is not None and periodization is not None)
                        else None
                    ),
                )
            )
            continue

        row = by_prescription_id.get(prescription_id)
        if row is None:
            # C231 — fail-fast invariant: build_performed_workouts MUST emit
            # exactly one ledger row per prescription passed in. Silently
            # dropping a session here would truncate the week without any
            # signal to the caller — never acceptable.
            raise ValueError(
                "build_week_execution invariant violated: prescription "
                f"'{prescription_id}' has no matching row in the "
                "PR230 ledger (by_prescription_id). Exactly one row per "
                "prescription is required; the week must never be silently "
                "truncated."
            )
        structured: Optional[StructuredWorkoutPrescription] = None
        structured_status: Optional[str] = None
        frozen = frozen_snapshots.get(prescription_id)
        if plan_goal is not None and periodization is not None:
            structured_status = resolve_structured_status(
                planned_date=planned_date,
                reference_date=reference_date,
                frozen_snapshot=frozen,
            )
            if structured_status == STRUCTURED_STATUS_FUTURE_LIVE:
                # Strictly future — never frozen; structure the EFFECTIVE
                # (live) session, may still legitimately evolve before it is
                # actually served.
                structured = build_structured_workout_prescription(
                    workout=effective,
                    plan_goal=plan_goal,
                    periodization=periodization,
                    training_paces=training_paces,
                )
            elif structured_status == STRUCTURED_STATUS_HISTORICAL_FROZEN:
                # #235 — a real V2 structured snapshot exists for this
                # strictly-past day: read it AS-IS, never recomputed from
                # today's goal/phase/paces/engine rules (ABSOLUTE RULE).
                structured = frozen.structured if frozen is not None else None
            elif structured_status == STRUCTURED_STATUS_TODAY_SERVED:
                # Today: the atomically-served snapshot (created earlier by
                # server.py's get_or_create_served_prescription, or by the
                # fallback branch above for a bare Week-only call) already
                # carries the frozen structure — read it, never recompute.
                # Legacy edge case: an existing PARENT-only snapshot for
                # TODAY predating #235 (structured is None) — rebuild once,
                # live, best-effort; never persisted over the existing
                # insert-only document.
                if frozen is not None and frozen.structured is not None:
                    structured = frozen.structured
                else:
                    structured = build_structured_workout_prescription(
                        workout=effective,
                        plan_goal=plan_goal,
                        periodization=periodization,
                        training_paces=training_paces,
                    )
            # else STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE — structured
            # stays None: no snapshot at all, or a legacy pre-#235 one.
        session_executions.append(
            SessionExecution(
                session=effective,
                planned_date=planned_date,
                row=row,
                prescription_id=prescription_id,
                # C235 (final correction) — the WINNING snapshot's own
                # frozen fact when one exists (NEVER recomputed against
                # `session`/`effective`'s CURRENT live plan); for the one
                # bare-Week-only call that just created today's snapshot in
                # the fallback branch above (not yet in `frozen_snapshots`),
                # use the SAME value it is persisting; otherwise `None`
                # (no trustworthy fact — e.g. legacy pre-C231 snapshot).
                modified_from_planned=(
                    frozen.modified_from_planned
                    if frozen is not None
                    else self_created_modified_from_planned.get(prescription_id)
                ),
                structured=structured,
                structured_status=structured_status,
            )
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


__all__ = [
    "build_week_execution",
    "WeekExecutionResult",
    "SessionExecution",
    "prescription_id_for",
    "EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE",
]
