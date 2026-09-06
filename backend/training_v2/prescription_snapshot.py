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
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .workout_generator import WorkoutPrescription, WorkoutStep


class PrescriptionSnapshot(BaseModel):
    """Immutable copy of a ``WorkoutPrescription`` as it was FIRST served.

    Persisted keyed by ``(user_id, prescription_id)`` — ``prescription_id``
    already encodes ``user_id + planned_date + day``. Never rewritten once
    created.
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

    steps: tuple[WorkoutStep, ...] = ()
    """C232 (correction, round 7 — BLOCKER FIX): the canonical structural
    steps of the SERVED prescription, copied verbatim from
    ``WorkoutPrescription.steps`` at the moment this snapshot was created
    (see :func:`snapshot_from_prescription`). Before this field existed, a
    future session carrying explicit ``steps`` would silently LOSE them the
    instant it became "today" and got frozen — ``resolve_effective_session``
    rebuilt a ``WorkoutPrescription`` from the snapshot without a ``steps``
    field, so it always defaulted back to ``()``, even when the live session
    that was actually served had real steps.

    Defaults to ``()`` for snapshots persisted before this field existed
    (backward compatibility) — deliberately NEVER reconstructed from the
    current live plan; an old snapshot without steps means "unknown
    structure", not "no structure was ever prescribed". Once frozen, a
    snapshot's ``steps`` NEVER change, exactly like every other field here.
    """


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
) -> PrescriptionSnapshot:
    """Build the immutable snapshot payload for a freshly-served prescription.

    ``modified_from_planned`` MUST be computed by the caller exactly once
    (see ``served_prescription.get_or_create_served_prescription``) — this
    function never derives it itself, to avoid silently recomputing it
    against a different/live plan than the one the caller actually compared.
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
        # C232 (correction, round 7) — copy EXACTLY, never re-derived: this
        # is the one place a live session's structure is captured forever.
        steps=session.steps,
    )


def resolve_effective_session(
    *,
    live_session: WorkoutPrescription,
    frozen_snapshot: Optional[PrescriptionSnapshot],
) -> WorkoutPrescription:
    """Return the prescription that MUST be used for matching AND display.

    - When a frozen snapshot exists, it is authoritative — the live
      (possibly recomputed) session is ignored, so a past activity is never
      compared against a prescription recomputed today.
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
        reason_codes=live_session.reason_codes,
        # C232 (correction, round 7 — BLOCKER FIX): reconstruct EXACTLY the
        # steps that were frozen with this snapshot — never the live
        # session's (possibly different, possibly newly-recomputed) steps.
        # An old snapshot persisted before this field existed deserializes
        # with steps=() (pydantic default) — never reconstructed from the
        # current live plan.
        steps=frozen_snapshot.steps,
    )


__all__ = [
    "PrescriptionSnapshot",
    "is_freezable",
    "snapshot_from_prescription",
    "resolve_effective_session",
]
