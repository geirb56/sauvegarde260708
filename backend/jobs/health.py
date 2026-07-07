"""Reliable-queue health snapshot — READ-ONLY Redis.

Powers GET /api/garmin/queue/health. Never writes, never touches Mongo, never
influences sync processing. One pipelined round-trip + a scan of the (tiny)
heartbeat keyspace, so it stays well under 10ms server-side.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .redis_client import get_redis
from .queue import (
    QUEUE_KEY,
    PROCESSING_KEY,
    CLAIMS_KEY,
    ORPHAN_TIMEOUT,
    HEARTBEAT_PREFIX,
    STATS_ORPHANS_KEY,
    STATS_FAILED_KEY,
)

logger = logging.getLogger(__name__)

# Status thresholds (fixed per SRE spec).
QUEUE_DEGRADED = 500
QUEUE_UNHEALTHY = 2000
AGE_DEGRADED = int(0.8 * ORPHAN_TIMEOUT)   # 96s at ORPHAN_TIMEOUT=120
AGE_UNHEALTHY = ORPHAN_TIMEOUT             # 120s


async def queue_health() -> dict:
    now = time.time()
    snapshot = {
        "status": "unhealthy",
        "redis_connected": False,
        "queue_length": None,
        "processing_length": None,
        "active_workers": 0,
        "oldest_processing_seconds": None,
        "orphans_recovered_total": None,
        "failed_jobs_total": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    r = get_redis()
    try:
        await r.ping()
    except Exception as exc:
        logger.error("[queue/health] redis unreachable: %r", exc)
        return snapshot  # redis_connected stays False -> UNHEALTHY

    snapshot["redis_connected"] = True

    async with r.pipeline(transaction=False) as pipe:
        pipe.llen(QUEUE_KEY)
        pipe.llen(PROCESSING_KEY)
        pipe.hgetall(CLAIMS_KEY)
        pipe.get(STATS_ORPHANS_KEY)
        pipe.get(STATS_FAILED_KEY)
        qlen, plen, claims, orphans, failed = await pipe.execute()

    # Count live worker heartbeats (non-blocking SCAN over a tiny keyspace).
    workers = 0
    async for _ in r.scan_iter(match=f"{HEARTBEAT_PREFIX}*", count=100):
        workers += 1

    oldest = 0
    if claims:
        try:
            oldest = max(0, round(now - min(float(v) for v in claims.values())))
        except ValueError:
            oldest = 0

    snapshot.update({
        "queue_length": qlen,
        "processing_length": plen,
        "active_workers": workers,
        "oldest_processing_seconds": oldest,
        "orphans_recovered_total": int(orphans) if orphans else 0,
        "failed_jobs_total": int(failed) if failed else 0,
    })

    if workers == 0 or oldest >= AGE_UNHEALTHY or qlen >= QUEUE_UNHEALTHY:
        snapshot["status"] = "unhealthy"
    elif qlen >= QUEUE_DEGRADED or oldest >= AGE_DEGRADED:
        snapshot["status"] = "degraded"
    else:
        snapshot["status"] = "healthy"

    return snapshot
