"""C231 — Immutable prescription snapshot (architecture BLOCKER fix).

Problem
-------
``WorkoutGenerator`` / ``WeeklyReconciliation`` are allowed to change their
output over time (new activities logged, athlete history extended,
reconciliation state changed, ...). Before this module, ``/training/v2/week``
recomputed the *live* ``WeeklyPlan`` on every call and matched it against
Garmin evidence — so a Monday prescribed at 8 km could silently become 10 km
a few days later, and the adherence comparison for the (already elapsed)
Monday activity would then run against the wrong distance.

Fix
---
Once a session's ``planned_date`` is no longer strictly in the future, the
FIRST prescription served for it is frozen ("snapshotted") and reused for
ALL subsequent matching, forever — regardless of how many times the plan is
later recomputed.

Design rules
------------
- PURE: no MongoDB, no HTTP. The persistence boundary (read the existing
  snapshots for a week, write the newly-frozen ones) lives in the endpoint
  layer (``server.py``), mirroring every other ``db.*`` collection access in
  this codebase.
- Freeze rule (single, explicit): a session becomes eligible for freezing as
  soon as ``planned_date <= reference_date`` (today or the past). Strictly
  future sessions (``planned_date > reference_date``) are NEVER frozen — the
  live ``WorkoutPrescription`` is always used for them, since the plan may
  still legitimately evolve until they stop being in the future.
- Once frozen, a snapshot is NEVER rewritten because of a later recompute:
  this module never asks the caller to overwrite an already-existing
  snapshot — see :func:`build_snapshots_to_persist`.

#235 — PRESCRIPTION SNAPSHOT V2 — GARMIN-EXPORT-READY
------------------------------------------------------
Extends the PARENT-only snapshot above with the STRUCTURED (#234
``StructuredWorkoutPrescription``) view of the exact same served
prescription, frozen in ONE canonical document at ONE instant:

    WorkoutGenerator -> DailyAdaptation (TODAY) -> final served
    WorkoutPrescription -> StructuredWorkoutPrescriptionEngine (#234) ->
    PrescriptionSnapshot V2 (parent + structured, same document)

Once written, the structured view is NEVER recomputed against a later
Training Paces / goal / periodization-phase / #234 engine-rule change —
for an already-served day, HISTORICAL TRUTH = SNAPSHOT, never a live
recompute (ABSOLUTE RULE). This is what makes the snapshot Garmin-export
ready: a future ``GarminWorkoutCompiler`` can read a frozen sequence of
steps/recoveries/pace-ranges and translate it directly, without ever
calling back into Training Paces, PlanGoal, Periodization or the
Structured Workout engine. No Garmin-specific vendor concept is
introduced here: the contract stays #234's own neutral vocabulary.

Legacy compatibility (no destructive migration): a snapshot written before
#235 has no ``structured`` field (deserializes as ``None``) and MUST stay
that way forever — never backfilled from current rules. Its
``structured_status`` is ``historical_unavailable`` when the day is
strictly historical (see :func:`resolve_structured_status`).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .structured_workout import StructuredWorkoutPrescription
from .workout_generator import WorkoutPrescription

# ── #235 — machine-readable structured_status values (vendor-neutral) ─────
# Never invented frontend wording: these are the SAME four states #234
# already documented (today_served / future_live / historical_unavailable),
# plus ONE new state this module introduces — historical_frozen — for a
# past day backed by a real V2 structured snapshot (see module docstring
# update below).
STRUCTURED_STATUS_TODAY_SERVED = "today_served"
STRUCTURED_STATUS_FUTURE_LIVE = "future_live"
STRUCTURED_STATUS_HISTORICAL_FROZEN = "historical_frozen"
STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE = "historical_unavailable"


class PrescriptionSnapshot(BaseModel):
    """Immutable copy of a ``WorkoutPrescription`` as it was FIRST served.

    Persisted keyed by ``(user_id, prescription_id)`` — ``prescription_id``
    already encodes ``user_id + planned_date + day``. Never rewritten once
    created.

    #235 — PRESCRIPTION SNAPSHOT V2 — GARMIN-EXPORT-READY
    -------------------------------------------------------
    Extends the C231 PARENT-only snapshot with the STRUCTURED
    (#234 ``StructuredWorkoutPrescription``) view of the exact same served
    prescription, frozen in the SAME document at the SAME instant. Once
    written, neither the parent nor the structured fields are ever
    recomputed or rewritten — see ``snapshot_from_prescription`` below.

    The structured payload is intentionally vendor-neutral: it reuses
    #234's own step/recovery contract (``StructuredStepType``,
    ``pace_zone``, distance/duration basis, invariant/closure flags) with
    no Garmin-specific naming, so a future ``GarminWorkoutCompiler`` can be
    built as a pure adapter over this snapshot without recomputing any
    RunIndex rule.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    prescription_id: str
    planned_date: date
    day: str
    workout_type: str
    intensity_class: str
    distance_km: Optional[float] = None
    duration_minutes: Optional[int] = None
    modified_from_planned: Optional[bool] = None
    """Whether the SERVED prescription differed from the raw plan AT THE
    MOMENT this snapshot was created. Computed exactly once, at
    snapshot-creation time (see ``served_prescription.get_or_create_served_prescription``),
    and NEVER recomputed afterwards against a later, possibly-different
    live plan — the live plan may keep moving, but what was actually served
    that day is a historical fact that cannot change retroactively.

    ``None`` for snapshots created before this field existed (backward
    compatibility) — deliberately NOT reconstructed from the current live
    plan, since that would silently invent a fact that was never recorded.
    A consumer seeing ``None`` MUST treat it as "unknown" (e.g. the frontend
    shows no adaptation banner), never as ``False``.
    """

    reason_codes: Tuple[str, ...] = ()
    """#235 — PARENT reason codes, frozen at serve time. Defaults to ``()``
    for snapshots created before this field existed (legacy documents),
    which is indistinguishable from a legitimately-empty tuple — legacy
    consumers already tolerated this ambiguity for the parent (see
    ``resolve_effective_session``)."""

    served_at: Optional[datetime] = None
    """#235 — wall-clock instant this snapshot was FIRST created, supplied
    by the caller (server.py) — this module itself never reads the clock
    (see ``test_module_has_no_io_dependencies``). ``None`` for legacy
    snapshots predating this field."""

    structured: Optional[StructuredWorkoutPrescription] = None
    """#235 — the frozen #234 ``StructuredWorkoutPrescription`` for the
    EXACT prescription this snapshot's parent fields describe, built from
    the FINAL served prescription (post-DailyAdaptation) at the SAME
    instant the parent was frozen. ``None`` for:

    - legacy (pre-#235) snapshots that never captured structure — see
      ``STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE``;
    - the rare edge case where a legacy parent-only snapshot exists for a
      day that is still "today" (see ``server.py`` today handler).

    Once populated, NEVER recomputed against later Training Paces, goal,
    periodization phase, or #234 engine-rule changes — historical truth is
    the snapshot, never a live recompute (ABSOLUTE RULE, #235 §2)."""

    adaptation_action: Optional[str] = None
    """C235 (corrective audit) — the ``DailyAdaptationAction`` value (e.g.
    ``"KEEP"``, ``"SHORTEN"``, ``"EASY_DOWNGRADE"``, ``"REST"``) that
    produced THIS snapshot's ``session`` fields, frozen at serve-creation
    time. Together with ``adaptation_reason_codes`` below, this is the
    metadata boundary fix for the C235 blocker where Today combined a
    frozen parent with freshly-recomputed live adaptation metadata: once a
    snapshot exists, ``adaptation_action``/``adaptation_reason_codes`` MUST
    be read from here, never recomputed from a new DailyAdaptation call.
    ``None`` for:

    - legacy (pre-C235-corrective) snapshots that predate this field;
    - the Week-only fallback creation path (see
      ``week_execution.build_week_execution``) which freezes the raw plan
      session directly without ever running DailyAdaptation — there is no
      adaptation decision to record, so ``None`` (unknown) is the honest
      value, never a fabricated ``"KEEP"``."""

    adaptation_reason_codes: Tuple[str, ...] = ()
    """C235 (corrective audit) — the live DailyAdaptation reason codes AT
    THE INSTANT this snapshot was created, frozen alongside
    ``adaptation_action``. Deliberately a SEPARATE field from the parent's
    own ``reason_codes`` (which describes the SERVED prescription itself,
    e.g. why the plan/reconciliation produced this session) — this field is
    purely diagnostic metadata about the ADAPTATION decision, never used to
    describe the prescription's own identity. Defaults to ``()`` for legacy
    snapshots and the Week-only fallback creation path (see
    ``adaptation_action`` above)."""


def is_freezable(*, planned_date: date, reference_date: date) -> bool:
    """A session is eligible for freezing once it is today or in the past.

    Strictly future sessions are never frozen: the live plan may still
    change for them until they stop being in the future.
    """
    return planned_date <= reference_date


def snapshot_from_prescription(
    *,
    user_id: str,
    prescription_id: str,
    planned_date: date,
    session: WorkoutPrescription,
    modified_from_planned: Optional[bool] = None,
    structured: Optional[StructuredWorkoutPrescription] = None,
    served_at: Optional[datetime] = None,
    adaptation_action: Optional[str] = None,
    adaptation_reason_codes: Tuple[str, ...] = (),
) -> PrescriptionSnapshot:
    """Build the immutable snapshot payload for a freshly-served prescription.

    ``modified_from_planned`` MUST be computed by the caller exactly once
    (see ``served_prescription.get_or_create_served_prescription``) — this
    function never derives it itself, to avoid silently recomputing it
    against a different/live plan than the one the caller actually compared.

    ``structured`` (#235) — the #234 ``StructuredWorkoutPrescription`` built
    from this SAME ``session`` (the final served prescription), by the
    caller, BEFORE calling this function. This function never invokes the
    structured-workout engine itself (PURE, no rule knowledge) — it only
    freezes whatever the caller already computed. ``None`` is a legitimate
    value (e.g. structuring not requested for this call site).

    ``served_at`` (#235) — wall-clock instant supplied by the caller; this
    module never reads the clock itself.

    ``adaptation_action``/``adaptation_reason_codes`` (C235 corrective
    audit) — the DailyAdaptation decision that produced this SAME
    ``session``, computed by the caller BEFORE calling this function (this
    module never invokes DailyAdaptation itself). ``None``/``()`` when the
    caller has no adaptation decision to record (e.g. the Week-only
    fallback creation path, which freezes the raw plan directly).
    """
    return PrescriptionSnapshot(
        user_id=user_id,
        prescription_id=prescription_id,
        planned_date=planned_date,
        day=session.day,
        workout_type=session.workout_type,
        intensity_class=session.intensity_class,
        distance_km=session.distance_km,
        duration_minutes=session.duration_minutes,
        modified_from_planned=modified_from_planned,
        reason_codes=session.reason_codes,
        structured=structured,
        served_at=served_at,
        adaptation_action=adaptation_action,
        adaptation_reason_codes=adaptation_reason_codes,
    )


def resolve_effective_session(
    *,
    live_session: WorkoutPrescription,
    frozen_snapshot: Optional[PrescriptionSnapshot],
) -> WorkoutPrescription:
    """Return the prescription that MUST be used for matching AND display.

    - When a frozen snapshot exists, it is authoritative — the live
      (possibly recomputed) session, including its ``reason_codes``, is
      ignored, so a past activity is never compared against (or displayed
      with) a prescription recomputed today. #235 — ``reason_codes`` are now
      taken from the frozen snapshot itself (frozen at serve time), never
      from ``live_session``, so the PARENT view is fully immutable.
    - Without a snapshot (future session, or first time being served), the
      live session is used as-is.
    """
    if frozen_snapshot is None:
        return live_session
    return WorkoutPrescription(
        day=frozen_snapshot.day,
        workout_type=frozen_snapshot.workout_type,
        intensity_class=frozen_snapshot.intensity_class,
        distance_km=frozen_snapshot.distance_km,
        duration_minutes=frozen_snapshot.duration_minutes,
        reason_codes=frozen_snapshot.reason_codes,
    )


def resolve_structured_status(
    *,
    planned_date: date,
    reference_date: date,
    frozen_snapshot: Optional[PrescriptionSnapshot],
) -> str:
    """#235 — the single, canonical machine-readable status for the
    STRUCTURED view of a day, shared by ``/training/today`` and
    ``/training/v2/week`` so they can never diverge.

    - ``future_live``: ``planned_date > reference_date`` — never frozen,
      structure may still legitimately evolve before it is actually served.
    - ``today_served``: ``planned_date == reference_date`` — the atomically
      served prescription for today (frozen once, reused all day).
    - ``historical_frozen``: ``planned_date < reference_date`` AND a V2
      snapshot with a real ``structured`` payload exists — reconstructed
      ONLY from the frozen snapshot, never recomputed from current rules.
    - ``historical_unavailable``: ``planned_date < reference_date`` and
      either no snapshot exists at all, or it predates #235 (legacy,
      ``structured is None``) — never backfilled.
    """
    if planned_date > reference_date:
        return STRUCTURED_STATUS_FUTURE_LIVE
    if planned_date == reference_date:
        return STRUCTURED_STATUS_TODAY_SERVED
    if frozen_snapshot is not None and frozen_snapshot.structured is not None:
        return STRUCTURED_STATUS_HISTORICAL_FROZEN
    return STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE


__all__ = [
    "PrescriptionSnapshot",
    "is_freezable",
    "snapshot_from_prescription",
    "resolve_effective_session",
    "resolve_structured_status",
    "STRUCTURED_STATUS_TODAY_SERVED",
    "STRUCTURED_STATUS_FUTURE_LIVE",
    "STRUCTURED_STATUS_HISTORICAL_FROZEN",
    "STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE",
]
