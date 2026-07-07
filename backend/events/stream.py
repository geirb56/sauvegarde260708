"""Event stream layer — lightweight Redis Streams (no Kafka).

ACTIVITY_CREATED is emitted by the ingestion layer (garmin.service) after a new
activity is written to `garmin_activities` (source of truth). Downstream fan-out
workers consume it to build the product/UI layer (`workouts`) and the feed cache.

Kept intentionally minimal: one capped stream + one consumer group.
"""

from __future__ import annotations

import json
import time

from redis.exceptions import ResponseError

from jobs.redis_client import get_redis

STREAM_KEY = "cardiocoach:events:activity_created"
FANOUT_GROUP = "workouts_fanout"
STREAM_MAXLEN = 10000

EVENT_ACTIVITY_CREATED = "ACTIVITY_CREATED"


async def emit_activity_created(user_id: str, activity: dict) -> None:
    """Append an ACTIVITY_CREATED event (capped stream, approximate trim)."""
    r = get_redis()
    await r.xadd(
        STREAM_KEY,
        {
            "event": EVENT_ACTIVITY_CREATED,
            "user_id": user_id,
            "activity": json.dumps(activity),
            "emitted_at": str(time.time()),
        },
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )


async def ensure_group(group: str = FANOUT_GROUP) -> None:
    """Create the consumer group (idempotent), creating the stream if needed."""
    r = get_redis()
    try:
        await r.xgroup_create(STREAM_KEY, group, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def parse_event(fields: dict) -> dict:
    """Decode a stream entry's fields into a usable event dict."""
    activity = {}
    raw = fields.get("activity")
    if raw:
        try:
            activity = json.loads(raw)
        except (ValueError, TypeError):
            activity = {}
    return {
        "event": fields.get("event"),
        "user_id": fields.get("user_id"),
        "activity": activity,
    }
