"""Per-user "latest activities" feed cache — Redis-backed, ultra-fast read path.

Gives the Strava-like instant feel: the fan-out worker pushes each newly ingested
activity here right after ingestion, and GET /api/garmin/activities serves from
this cache first (Mongo is the fallback / warm source).

Stores the SAME normalized shape as `garmin_activities` documents, so the API
response contract is unchanged.
"""

from __future__ import annotations

import json

from jobs.redis_client import get_redis

FEED_PREFIX = "cardiocoach:feed:"
FEED_MAXLEN = 50            # keep only the latest N per user
FEED_TTL = 7 * 24 * 3600    # evict cold users after a week


def _key(user_id: str) -> str:
    return f"{FEED_PREFIX}{user_id}"


def _sort_key(a: dict) -> str:
    return a.get("start_time") or ""


async def update_feed(user_id: str, activity: dict) -> None:
    """Insert one activity at the head of the user's feed (newest first)."""
    r = get_redis()
    key = _key(user_id)
    async with r.pipeline(transaction=True) as pipe:
        pipe.lpush(key, json.dumps(activity))
        pipe.ltrim(key, 0, FEED_MAXLEN - 1)
        pipe.expire(key, FEED_TTL)
        await pipe.execute()


async def warm_feed(user_id: str, activities: list) -> None:
    """Replace the feed with a batch (used to warm the cache from Mongo)."""
    if not activities:
        return
    r = get_redis()
    key = _key(user_id)
    ordered = sorted(activities, key=_sort_key, reverse=True)[:FEED_MAXLEN]
    payloads = [json.dumps(a) for a in ordered]
    async with r.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        pipe.rpush(key, *payloads)  # rpush preserves newest-first order
        pipe.expire(key, FEED_TTL)
        await pipe.execute()


async def get_feed(user_id: str, since: str | None = None, limit: int = 20) -> list:
    """Return up to `limit` cached activities (newest first), optionally only
    those newer than `since` (ISO start_time). Empty list on cache miss."""
    r = get_redis()
    items = await r.lrange(_key(user_id), 0, max(limit, FEED_MAXLEN) - 1)
    acts = []
    for raw in items:
        try:
            acts.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    if since:
        acts = [a for a in acts if _sort_key(a) > since]
    return acts[:limit]
