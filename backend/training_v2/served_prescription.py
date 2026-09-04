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
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .prescription_snapshot import (
    PrescriptionSnapshot,
    resolve_effective_session,
    snapshot_from_prescription,
)
from .workout_generator import WorkoutPrescription


async def get_or_create_served_prescription(
    db: Any,
    *,
    user_id: str,
    prescription_id: str,
    planned_date: date,
    served_candidate: WorkoutPrescription,
) -> WorkoutPrescription:
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

    Returns
    -------
    WorkoutPrescription
        The canonical, effective prescription for this day — guaranteed
        identical for every caller regardless of which one actually created
        the underlying Mongo document.
    """
    candidate_snapshot = snapshot_from_prescription(
        user_id=user_id,
        prescription_id=prescription_id,
        planned_date=planned_date,
        session=served_candidate,
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
    return resolve_effective_session(
        live_session=served_candidate, frozen_snapshot=winning_snapshot
    )


__all__ = ["get_or_create_served_prescription"]
