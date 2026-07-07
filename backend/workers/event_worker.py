"""Fan-out worker — builds the product/UI layer from ACTIVITY_CREATED events.

Consumes the Redis Stream (consumer group -> horizontally scalable) and, for
each newly ingested activity:
  a. upserts the derived `workouts` document (what the frontend renders)
  b. updates the per-user Redis feed cache (instant UX)

Strict separation of concerns: the gccli sync worker NEVER writes `workouts`
directly. `garmin_activities` stays the immutable ingestion source of truth;
`workouts` is derived and replaceable. Fully decoupled from gccli/sync.

Start with:  python -m workers.event_worker   (cwd = /app/backend)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient

from events.stream import STREAM_KEY, FANOUT_GROUP, ensure_group, parse_event
from feed import realtime_cache
from garmin.service import activity_to_workout

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("event_worker")

CONSUMER = f"{socket.gethostname()}:{os.getpid()}"
BLOCK_MS = int(os.environ.get("EVENT_BLOCK_MS", "5000"))
BATCH = int(os.environ.get("EVENT_BATCH", "50"))


async def handle_event(db, ev: dict) -> None:
    user_id = ev.get("user_id")
    activity = ev.get("activity") or {}
    if not user_id or not activity.get("external_id"):
        return
    # a) derived workouts (product layer) — key by (id, user_id) so activities
    # from different users can never overwrite each other.
    workout = activity_to_workout(activity, user_id)
    if workout:
        await db.workouts.update_one(
            {"id": workout["id"], "user_id": user_id},
            {"$set": workout},
            upsert=True,
        )
    # b) instant feed cache
    await realtime_cache.update_feed(user_id, activity)


async def main() -> None:
    from jobs.redis_client import get_redis

    redis = get_redis()
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ["DB_NAME"]]

    await ensure_group()
    logger.info("[event] started consumer=%s group=%s stream=%s", CONSUMER, FANOUT_GROUP, STREAM_KEY)

    while True:
        try:
            resp = await redis.xreadgroup(
                FANOUT_GROUP, CONSUMER, {STREAM_KEY: ">"}, count=BATCH, block=BLOCK_MS
            )
            if not resp:
                continue
            for _stream, entries in resp:
                for entry_id, fields in entries:
                    try:
                        await handle_event(db, parse_event(fields))
                    except Exception as exc:  # keep consuming; ack to avoid poison loop
                        logger.error("[event] handler error id=%s: %s", entry_id, exc)
                    await redis.xack(STREAM_KEY, FANOUT_GROUP, entry_id)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[event] loop error: %s", exc)
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
