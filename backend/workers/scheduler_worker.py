"""Smart scheduler worker — decides WHEN to sync each user (no global polling).

Periodically scans connected users, classifies each into a tier (ACTIVE /
NORMAL / INACTIVE) from freshness signals, and enqueues an INCREMENTAL sync only
for users that are actually DUE and outside their cooldown. This keeps Garmin
API usage flat while giving active users a near-real-time feel.

Fully worker-based and decoupled: it only reads Mongo/Redis and enqueues jobs;
it never calls gccli. Horizontally scalable via a Redis leader lock (one active
scheduler at a time; others are hot standbys).

Start with:  python -m workers.scheduler_worker   (cwd = /app/backend)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient

from jobs.redis_client import get_redis
from jobs.queue import enqueue_incremental_sync
from sync import scheduler
from sync import rate_limiter
from sync.rate_limiter import global_active_count, GLOBAL_MAX

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("scheduler_worker")

SCAN_INTERVAL = int(os.environ.get("SCHEDULER_SCAN_INTERVAL", "60"))
STAGGER_MS = int(os.environ.get("SCHEDULER_STAGGER_MS", "20"))
LEADER_TTL = int(os.environ.get("SCHEDULER_LEADER_TTL", "90"))
STANDBY_POLL = int(os.environ.get("SCHEDULER_STANDBY_POLL", "15"))

LEADER_KEY = "cardiocoach:scheduler:leader"
ACTIVE_SIGNAL_PREFIX = "cardiocoach:active_signal:"
OWNER = f"{socket.gethostname()}:{os.getpid()}"


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


async def _acquire_or_refresh_leadership(redis) -> bool:
    if await redis.set(LEADER_KEY, OWNER, nx=True, ex=LEADER_TTL):
        return True
    if await redis.get(LEADER_KEY) == OWNER:
        await redis.expire(LEADER_KEY, LEADER_TTL)
        return True
    return False


async def scan_once(db, redis) -> dict:
    now = datetime.now().timestamp()
    enqueued = scanned = skipped_cooldown = skipped_notdue = 0

    cursor = db.garmin_connections.find(
        {"connected": True},
        {"_id": 0, "user_id": 1, "last_sync": 1, "last_activity_at": 1},
    )
    async for conn in cursor:
        uid = conn.get("user_id")
        if not uid:
            continue
        scanned += 1

        # Budget guard: don't flood the queue past the global concurrency cap.
        if await global_active_count() >= GLOBAL_MAX:
            break

        active_signal_ts = _epoch(await redis.get(f"{ACTIVE_SIGNAL_PREFIX}{uid}"))
        last_activity_ts = _epoch(conn.get("last_activity_at"))
        last_sync_ts = _epoch(conn.get("last_sync"))

        decision = scheduler.decide(
            now,
            active_signal_ts=active_signal_ts,
            last_activity_ts=last_activity_ts,
            last_sync_ts=last_sync_ts,
        )
        if not decision["due"]:
            skipped_notdue += 1
            continue
        if not await rate_limiter.cooldown_ok(uid):
            skipped_cooldown += 1
            continue

        await enqueue_incremental_sync(uid)
        enqueued += 1
        if STAGGER_MS:
            await asyncio.sleep(STAGGER_MS / 1000.0)

    return {"scanned": scanned, "enqueued": enqueued,
            "skipped_cooldown": skipped_cooldown, "skipped_notdue": skipped_notdue}


async def main() -> None:
    redis = get_redis()
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ["DB_NAME"]]
    logger.info("[scheduler] started owner=%s scan_interval=%ss", OWNER, SCAN_INTERVAL)

    while True:
        try:
            if not await _acquire_or_refresh_leadership(redis):
                await asyncio.sleep(STANDBY_POLL)
                continue
            stats = await scan_once(db, redis)
            logger.info("[scheduler] scan %s", stats)
            await asyncio.sleep(SCAN_INTERVAL)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[scheduler] loop error: %s", exc)
            await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
