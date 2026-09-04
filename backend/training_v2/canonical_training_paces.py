"""C232 (correction) — canonical Training Paces loader.

BLOCKER FIXED: before this correction, ``GET /training/v2/week`` computed
Training Paces from a 90-day-windowed activity list
(``compute_training_paces(domain_activities_90, reference_date)``) while
``GET /training/v2/paces`` loaded up to 500 most-recent activities with NO
calendar-date window at all. Since ``training_paces.py``'s own selection
policy explicitly retains a HIGH-quality historical performance beyond any
short recent window as a LOW-confidence fallback
("HIGH_HISTORICAL_NEVER_EXPIRES = YES" — see that module's docstring),
truncating the input activity list to the last 90 days could silently
discard that fallback evidence. The two endpoints could then disagree —
one showing a pace, the other ``None`` — for the exact same user and day.
This is forbidden: Training Paces MUST be single-sourced.

This module is now the ONLY place that (a) loads the Garmin activity
history feeding Training Paces and (b) calls ``compute_training_paces``.
Every V2 consumer (``/training/v2/paces``, ``/training/v2/week``, and any
future consumer) MUST call :func:`load_canonical_training_paces` instead of
querying Mongo / calling ``compute_training_paces`` directly with a locally
re-derived activity window.

Design rules
------------
- NO calendar-date filter on the Mongo query: ``compute_training_paces``'s
  own no-lookahead + HIGH-never-expires policy needs access to the full
  performance history, not a fixed recent window. Bounded only by a
  generous most-recent-N query (500, matching the pre-existing
  ``/training/v2/paces`` behavior) to avoid unbounded memory use.
- Same ``reference_date`` as the caller: this module never computes its
  own "today" — the canonical reference_date (C231,
  ``_resolve_canonical_reference_date``) must be passed in by the caller so
  Today/Week/Paces all evaluate no-lookahead against the identical day.
- Same ``user_max_hr=None``: Garmin VO2max/VMA independence (#194) is
  preserved — this loader never reads HR-based capability data either.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from garmin.domain_adapter import mongo_garmin_activities_to_domain
from training_v2.training_paces import TrainingPaces, compute_training_paces

# Matches the activity depth previously used by GET /training/v2/paces —
# generous enough to reach historical HIGH performances used as fallback
# evidence, bounded to avoid unbounded memory use.
CANONICAL_ACTIVITY_LOAD_LIMIT: int = 500


async def load_canonical_training_paces(
    db: Any,
    *,
    user_id: str,
    reference_date: date,
) -> TrainingPaces:
    """Load Garmin activity history and compute Training Paces canonically.

    This is the SINGLE function every V2 consumer must call to obtain
    Training Paces, so that ``/training/v2/paces`` and ``/training/v2/week``
    (and any future consumer) always agree for the same user + reference_date.
    """
    garmin_activities = await (
        db.garmin_activities.find({"user_id": user_id}, {"_id": 0})
        .sort("start_time", -1)
        .limit(CANONICAL_ACTIVITY_LOAD_LIMIT)
        .to_list(length=CANONICAL_ACTIVITY_LOAD_LIMIT)
    )
    domain_activities = mongo_garmin_activities_to_domain(garmin_activities)
    return compute_training_paces(domain_activities, reference_date, user_max_hr=None)
