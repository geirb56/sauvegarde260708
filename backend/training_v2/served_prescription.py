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

from datetime import date, datetime
from typing import Any, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .prescription_snapshot import (
    PrescriptionSnapshot,
    resolve_effective_session,
    snapshot_from_prescription,
)
from .structured_workout import StructuredWorkoutPrescription
from .workout_generator import WorkoutPrescription


class ServedPrescriptionResult(BaseModel):
    """Result of :func:`get_or_create_served_prescription`.

    Bundles the canonical effective prescription together with the
    ``modified_from_planned`` metadata of the SAME winning snapshot — the
    two values must never be read from different sources (e.g. prescription
    from the snapshot but the boolean recomputed live), or Today/Week could
    display a prescription and an adaptation-banner state that don't
    logically belong together.

    #235 — ``structured`` (the frozen #234 STRUCTURED view, from the SAME
    winning snapshot document) is bundled here too, for the exact same
    reason: Today/Week must never combine a frozen parent with a
    separately, freshly recomputed structure.

    C235 (corrective audit) — ``adaptation_action``/``adaptation_reason_codes``
    (the frozen DailyAdaptation decision metadata from the SAME winning
    snapshot) are bundled here for the identical reason: once a snapshot
    exists, these must never be recomputed from a fresh DailyAdaptation
    call — Today must read them from here, never from a live
    ``adaptation_result``.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    prescription: WorkoutPrescription
    modified_from_planned: Optional[bool] = None
    structured: Optional[StructuredWorkoutPrescription] = None
    adaptation_action: Optional[str] = None
    adaptation_reason_codes: Tuple[str, ...] = ()


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
    structured_factory: Optional[Any] = None,
    served_at: Optional[datetime] = None,
    adaptation_action: Optional[str] = None,
    adaptation_reason_codes: Tuple[str, ...] = (),
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
    structured_factory
        #235 — a zero-argument callable returning the #234
        ``StructuredWorkoutPrescription`` built from ``served_candidate``
        (or ``None`` if the caller does not want structuring). Called ONLY
        when this call's cheap pre-check read (below) found no existing
        document — guaranteeing "second GET Today never re-runs the
        Structured Workout engine" (idempotence, #235 §11/§6) for the
        common sequential case. Ignored entirely when a snapshot already
        exists.

        C235 (corrective audit) — HONEST concurrency note: this is NOT
        "called at most once globally per day". Two genuinely concurrent
        callers can both observe "no existing document" on their
        respective pre-check reads and therefore BOTH invoke
        ``structured_factory`` (and both attempt the ``$setOnInsert``
        write) before either one wins. What IS guaranteed:

        - ``structured_factory`` (and the #234 engine it wraps) is PURE —
          a losing caller's call has no side effect beyond wasted CPU; its
          result is discarded, never persisted, never observed by anyone.
        - The final PERSISTED document is unique and atomic: MongoDB's
          ``$setOnInsert`` + the unique index on
          ``(user_id, prescription_id)`` guarantee exactly one document
          ever exists for a given day, and every caller (including the
          "losing" ones) re-reads and converges on that SAME winning
          document before returning.
        - Every subsequent (non-concurrent) call short-circuits on the
          cheap pre-check and never calls ``structured_factory`` again.

        See ``tests/test_pr235_c235_corrections.py`` for a concurrency test
        that exercises genuine interleaving.
    served_at
        #235 — wall-clock instant supplied by the caller, frozen into the
        snapshot ONLY at creation time. Ignored if a snapshot already
        exists.
    adaptation_action, adaptation_reason_codes
        C235 (corrective audit) — the DailyAdaptation decision (action +
        reason codes) THIS caller just computed, frozen into the snapshot
        ONLY at creation time, exactly like ``structured_factory``'s
        result. Ignored (never applied) if a snapshot already exists —
        Today must read these back from the WINNING snapshot afterwards,
        never from a freshly recomputed DailyAdaptation call, once a
        snapshot exists for this day.

    Returns
    -------
    ServedPrescriptionResult
        The canonical, effective prescription for this day, together with
        the winning snapshot's own ``modified_from_planned``,
        ``structured``, ``adaptation_action`` and
        ``adaptation_reason_codes`` — all guaranteed to come from the SAME
        underlying Mongo document, identical for every caller regardless of
        which one actually created it.
    """
    # #235 — cheap pre-check: if a snapshot already exists, NEVER invoke
    # structured_factory (no second Structured Workout engine call) and
    # NEVER recompute modified_from_planned — just read the winning
    # document as-is. This is what makes the second (and every subsequent)
    # GET Today call for the same day a pure read, with zero adaptation
    # and zero structuring recomputation. Under genuine concurrency this
    # pre-check does NOT prevent two callers from both missing (see the
    # ``structured_factory`` docstring above) — only the final write+re-read
    # below guarantees convergence.
    existing_doc = await db.training_prescription_snapshots.find_one(
        {"user_id": user_id, "prescription_id": prescription_id}, {"_id": 0}
    )
    if existing_doc:
        winning_snapshot = PrescriptionSnapshot(**existing_doc)
    else:
        modified_from_planned: Optional[bool] = None
        if planned_prescription is not None:
            modified_from_planned = _prescription_core_fields(
                served_candidate
            ) != _prescription_core_fields(planned_prescription)

        structured_candidate = structured_factory() if structured_factory is not None else None

        candidate_snapshot = snapshot_from_prescription(
            user_id=user_id,
            prescription_id=prescription_id,
            planned_date=planned_date,
            session=served_candidate,
            modified_from_planned=modified_from_planned,
            structured=structured_candidate,
            served_at=served_at,
            adaptation_action=adaptation_action,
            adaptation_reason_codes=adaptation_reason_codes,
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
        # #235 — likewise, NEVER reconstructed: None for legacy snapshots
        # that predate structuring.
        structured=winning_snapshot.structured,
        # C235 (corrective audit) — likewise, NEVER reconstructed from a
        # fresh DailyAdaptation call: None/() for legacy snapshots and the
        # Week-only fallback creation path.
        adaptation_action=winning_snapshot.adaptation_action,
        adaptation_reason_codes=winning_snapshot.adaptation_reason_codes,
    )


__all__ = ["ServedPrescriptionResult", "get_or_create_served_prescription"]
