"""On-demand backfill: rebuild the derived `workouts` layer + feed cache from
`garmin_activities` (the immutable source of truth).

Use it to:
  - repopulate `workouts` for activities ingested before the event-driven flow,
  - self-heal if the fan-out event-worker was down during a sync,
  - reconcile/prune orphan Garmin-derived workouts that no longer have a source
    activity (never touches non-Garmin / manual workouts).

Idempotent (upserts). Reads Mongo + writes only the derived layer; never calls
gccli, never touches `garmin_activities`.
"""

from __future__ import annotations

import logging

from .service import activity_to_workout
from feed import realtime_cache

logger = logging.getLogger(__name__)


async def backfill_user(db, user_id: str, prune: bool = True) -> dict:
    """Re-derive `workouts` + feed cache for one user from garmin_activities."""
    acts = await db.garmin_activities.find({"user_id": user_id}, {"_id": 0}).to_list(None)

    valid_ids = []
    upserted = 0
    for act in acts:
        workout = activity_to_workout(act, user_id)
        if not workout:
            continue
        valid_ids.append(workout["id"])
        await db.workouts.update_one(
            {"id": workout["id"], "user_id": user_id},
            {"$set": workout},
            upsert=True,
        )
        upserted += 1

    pruned = 0
    if prune:
        # Remove only Garmin-derived workouts with no matching source activity.
        res = await db.workouts.delete_many({
            "user_id": user_id,
            "data_source": "garmin",
            "id": {"$nin": valid_ids},
        })
        pruned = res.deleted_count

    try:
        await realtime_cache.warm_feed(user_id, acts)
    except Exception as exc:  # cache is best-effort
        logger.warning("[backfill] feed warm failed user=%s: %s", user_id, exc)

    result = {
        "user_id": user_id,
        "activities": len(acts),
        "workouts_upserted": upserted,
        "workouts_pruned": pruned,
        "feed_entries": min(len(acts), realtime_cache.FEED_MAXLEN),
    }
    logger.info("[backfill] %s", result)
    return result


async def backfill_all(db) -> dict:
    """Backfill every user that has ingested Garmin activities."""
    user_ids = await db.garmin_activities.distinct("user_id")
    users = 0
    total_upserted = total_pruned = 0
    for uid in user_ids:
        if not uid:
            continue
        r = await backfill_user(db, uid)
        users += 1
        total_upserted += r["workouts_upserted"]
        total_pruned += r["workouts_pruned"]
    return {"users": users, "workouts_upserted": total_upserted, "workouts_pruned": total_pruned}
