"""C231 (P0 #2) — Canonical "served prescription" get-or-create service.

Problem
-------
Before this module, ``/training/today`` and ``/training/v2/week`` each froze
today's prescription snapshot independently:

- ``/training/v2/week`` computed a candidate (via
  ``training_v2.today_prescription.resolve_today_final_prescription``) and
  wrote it with an insert-only ``$setOnInsert`` — but never re-read the
  document afterwards, so its OWN response kept using its locally computed
  candidate even when a concurrent caller's write actually won the race.
- ``/training/today`` never even looked at the snapshot table: it always
  displayed its own freshly computed adaptation result, regardless of
  whatever had already been frozen (by itself on a previous call, or by
  ``/training/v2/week``).

Two concurrent calls to Today and Week — each observing a slightly
different readiness state (e.g. daily metrics landing between the two
requests) — could therefore each end up DISPLAYING a different distance for
"today", even though only one snapshot document can ever exist in Mongo.

Fix
---
Both endpoints MUST go through :func:`get_or_create_served_prescription`
for the ONE session whose ``planned_date == reference_date``:

1. Attempt an insert-only ``$setOnInsert`` write of the caller's locally
   computed candidate (harmless no-op if a document already exists).
2. Re-read the document immediately after — this is now guaranteed to be
   the SAME canonical value for every caller, whichever one actually won
   the race, because MongoDB serialises writes to a single document.
3. Return the resulting effective ``WorkoutPrescription`` (frozen snapshot
   fields override the caller's own candidate) — never the raw local
   candidate.

This guarantees, simultaneously:
- Today first → Week reads back the exact same value.
- Week first → Today reads back the exact same value.
- Concurrent Today + Week → exactly one Mongo document, both responses
  converge on it.
- "si snapshot existe: il est autoritaire, ne jamais recalculer/remplacer
  la prescription servie" — an existing snapshot is NEVER overwritten;
  ``$setOnInsert`` guarantees this at the Mongo level, backed by the
  UNIQUE index on ``(user_id, prescription_id)`` (see
  ``services/prescription_snapshot_index.py``).

Design rules
------------
- The only I/O boundary in this module: ``db.training_prescription_snapshots``
  (an ``update_one`` + a ``find_one``). No other collection is touched here.
- PURE with respect to the served-prescription CANDIDATE itself: the caller
  supplies it (already computed via ``today_prescription.py``); this module
  only handles the atomic persistence + canonical read-back.

C231 (micro-correction, "modified_from_planned immutability" fix)
-------------------------------------------------------------------
``session_modified_from_planned`` (whether the SERVED prescription actually
differed from the raw plan) must be computed ONCE, at snapshot-creation
time, and frozen alongside the snapshot — never recomputed against
whatever the LIVE plan looks like on a later call. The live plan can
legitimately keep changing (new activities, later reconciliation) even
though the prescription that was actually served that day never changes.
Comparing a frozen ``served_prescription`` against a moving
``planned_session`` would make the boolean flip retroactively, which is
incorrect: it must describe a fact about the moment the snapshot was
created, not the current instant.

Concretely: :func:`get_or_create_served_prescription` now also receives the
caller's locally computed ``planned_prescription`` (the raw, pre-adaptation
plan for this slot). It is used ONLY if this call is the one that creates
the snapshot (first-ever call for this day) — to compute
``modified_from_planned`` exactly once — and is otherwise ignored, exactly
like ``served_candidate``. The winning (possibly pre-existing) snapshot's
OWN ``modified_from_planned`` field is always what gets returned, never a
value recomputed from the current caller's own candidates.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from .prescription_snapshot import (
    PrescriptionSnapshot,
    resolve_effective_session,
    snapshot_from_prescription,
)
from .workout_generator import WorkoutPrescription


class ServedPrescriptionResult(BaseModel):
    """Result of :func:`get_or_create_served_prescription`.

    Bundles the canonical effective prescription together with the
    ``modified_from_planned`` metadata of the SAME winning snapshot — the
    two values must never be read from different sources (e.g. prescription
    from the snapshot but the boolean recomputed live), or Today/Week could
    display a prescription and an adaptation-banner state that don't
    logically belong together.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    prescription: WorkoutPrescription
    modified_from_planned: Optional[bool] = None


def _prescription_core_fields(p: WorkoutPrescription) -> tuple:
    """The subset of fields that matter for "was this actually adapted?".

    Deliberately excludes ``reason_codes`` (language-neutral diagnostic
    metadata that can differ between two structurally-identical
    prescriptions) — mirrors exactly the fields persisted by
    :func:`training_v2.prescription_snapshot.snapshot_from_prescription`.
    """
    return (p.workout_type, p.intensity_class, p.distance_km, p.duration_minutes)


async def get_or_create_served_prescription(
    db: Any,
    *,
    user_id: str,
    prescription_id: str,
    planned_date: date,
    served_candidate: WorkoutPrescription,
    planned_prescription: Optional[WorkoutPrescription] = None,
) -> ServedPrescriptionResult:
    """Atomically get-or-create the canonical SERVED prescription for a day.

    Parameters
    ----------
    db
        Mongo database handle (or any object exposing an async
        ``training_prescription_snapshots`` collection with
        ``update_one``/``find_one``).
    user_id, prescription_id, planned_date
        Identify the (user, day) whose served prescription is being
        resolved. ``prescription_id`` must be produced by
        ``training_v2.week_execution.prescription_id_for``.
    served_candidate
        The prescription THIS caller just computed (post-DailyAdaptation)
        for this day. Used to create the snapshot ONLY if none exists yet;
        ignored (never applied) if a snapshot already exists.
    planned_prescription
        The RAW (pre-adaptation) plan for this same slot, as computed by
        THIS caller. Used ONLY at snapshot-creation time to compute
        ``modified_from_planned = served_candidate != planned_prescription``
        (compared on ``_prescription_core_fields``) — frozen into the
        snapshot forever. Ignored if a snapshot already exists. May be
        omitted (``None``) by callers that cannot supply it; the resulting
        snapshot's ``modified_from_planned`` is then left ``None`` (unknown)
        rather than fabricated.

    Returns
    -------
    ServedPrescriptionResult
        The canonical, effective prescription for this day, together with
        the winning snapshot's own ``modified_from_planned`` — both
        guaranteed to come from the SAME underlying Mongo document,
        identical for every caller regardless of which one actually created
        it.
    """
    modified_from_planned: Optional[bool] = None
    if planned_prescription is not None:
        modified_from_planned = _prescription_core_fields(
            served_candidate
        ) != _prescription_core_fields(planned_prescription)

    candidate_snapshot = snapshot_from_prescription(
        user_id=user_id,
        prescription_id=prescription_id,
        planned_date=planned_date,
        session=served_candidate,
        modified_from_planned=modified_from_planned,
    )
    await db.training_prescription_snapshots.update_one(
        {"user_id": user_id, "prescription_id": prescription_id},
        {"$setOnInsert": candidate_snapshot.model_dump(mode="json")},
        upsert=True,
    )
    winning_doc = await db.training_prescription_snapshots.find_one(
        {"user_id": user_id, "prescription_id": prescription_id}, {"_id": 0}
    )
    if not winning_doc:
        # Should never happen right after an upsert; never fabricate a
        # snapshot here — surface the anomaly instead of silently guessing.
        raise RuntimeError(
            "get_or_create_served_prescription: no snapshot found for "
            f"prescription_id={prescription_id!r} immediately after upsert."
        )
    winning_snapshot = PrescriptionSnapshot(**winning_doc)
    effective = resolve_effective_session(
        live_session=served_candidate, frozen_snapshot=winning_snapshot
    )
    return ServedPrescriptionResult(
        prescription=effective,
        # Old snapshots persisted before this field existed deserialize with
        # modified_from_planned=None (pydantic default) — NEVER reconstructed
        # from the live plan; see PrescriptionSnapshot.modified_from_planned.
        modified_from_planned=winning_snapshot.modified_from_planned,
    )


__all__ = ["ServedPrescriptionResult", "get_or_create_served_prescription"]
