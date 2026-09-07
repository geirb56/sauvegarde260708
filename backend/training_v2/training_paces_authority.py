"""C234 (final corrective audit) — the ONE canonical Training Paces loader.

Problem
-------
Before this module, three different code paths each loaded Garmin activity
history and called ``compute_training_paces`` independently:

- ``GET /training/v2/paces`` — ALL activities (no day filter), most-recent
  500 (a pre-existing, unrelated technical limit — see
  ``TRAINING_PACES_ACTIVITY_LIMIT`` below).
- ``GET /training/today`` and ``GET /training/v2/week`` — reused
  ``domain_activities_90``, the Training Engine's own 90-day activity window
  (loaded for WorkoutGenerator / WeeklyTarget / periodization decisions).

The Training Engine's 90-day window is a LOAD/VOLUME decision boundary. It
has nothing to do with Training Paces' own, separate recency policy
(``training_paces.py``: HIGH performance recent <=21d, MEDIUM <=56d, HIGH
historical NEVER expires — its confidence degrades to LOW instead of the
performance disappearing). Reusing the 90-day window as if it were a
Training Paces window silently truncated exactly the historical evidence
``training_paces.py`` is designed to keep using (at LOW confidence) —
creating two different authorities that could disagree for the same user at
the same instant (e.g. ``/training/v2/paces`` returning real LOW-confidence
paces while Today/Week's structured output claimed ``PACE_UNAVAILABLE``
purely because of an unrelated 90-day cutoff).

Fix
---
:func:`load_canonical_training_paces` is now the SINGLE loader used
identically by all three call sites:

- ``GET /training/v2/paces``
- ``GET /training/today``
- ``GET /training/v2/week``

It never imposes a 90-day (or any other arbitrary) cutoff of its own; the
only bound it applies is the pre-existing, unrelated
``TRAINING_PACES_ACTIVITY_LIMIT`` (most-recent-N activities fetched from
Mongo — a storage/query-size limit, audited and confirmed pre-existing in
``GET /training/v2/paces`` before this correction, not newly introduced
here and not disproportionate to touch in this PR). All age-based
qualification and confidence policy is applied downstream, unchanged, by
``training_paces.compute_training_paces`` itself.

Forbidden sources (unchanged, enforced by ``training_paces.py``, never
touched here): Garmin VO2max, VMA, Performance Curve / Race Predictions
outputs. No-lookahead is preserved via ``reference_date``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from garmin.domain_adapter import mongo_garmin_activities_to_domain
from .training_paces import TrainingPaces, compute_training_paces

logger = logging.getLogger(__name__)


TRAINING_PACES_ACTIVITY_LIMIT: int = 500
"""Pre-existing technical limit (audited, unchanged) on the number of
most-recent Garmin activities fetched to feed ``compute_training_paces``.
This is a storage/query-size bound, NOT a Training Paces recency window:
``training_paces.py``'s own HIGH/MEDIUM/LOW policy decides which evidence
still counts and at what confidence. Documented here as a known remaining
technical limit (see RUNINDEX_PR234_REPORT.md, C234 final corrective
audit) rather than expanded in this PR."""


async def load_canonical_training_paces(
    db: Any,
    *,
    user_id: str,
    reference_date: date,
) -> TrainingPaces:
    """The single canonical Training Paces V2 authority for the backend.

    Loads the same Garmin activity evidence (most-recent
    ``TRAINING_PACES_ACTIVITY_LIMIT`` activities, no day-count filter) and
    calls ``compute_training_paces`` identically, regardless of caller.
    Must be used by ``/training/v2/paces``, ``/training/today`` and
    ``/training/v2/week`` — never re-implemented locally, and never fed the
    Training Engine's own 90-day ``domain_activities_90`` window instead.
    """
    domain_activities: list = []
    garmin_conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if garmin_conn and garmin_conn.get("connected"):
        try:
            garmin_activities = await (
                db.garmin_activities.find({"user_id": user_id}, {"_id": 0})
                .sort("start_time", -1)
                .limit(TRAINING_PACES_ACTIVITY_LIMIT)
                .to_list(length=TRAINING_PACES_ACTIVITY_LIMIT)
            )
            domain_activities = mongo_garmin_activities_to_domain(garmin_activities)
        except Exception as exc:
            logger.warning(f"[TrainingPacesAuthority] Garmin activity load failed: {exc}")
    return compute_training_paces(domain_activities, reference_date, user_max_hr=None)


__all__ = ["load_canonical_training_paces", "TRAINING_PACES_ACTIVITY_LIMIT"]
