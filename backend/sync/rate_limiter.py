"""Anti-API-explosion layer for Garmin syncs (mandatory for 10k users).

Two independent protections, both Redis-backed so they hold ACROSS workers:

1. Global concurrency cap — at most GLOBAL_MAX gccli syncs run at once, cluster
   wide (a distributed counter, on top of each worker's local semaphore).
2. Per-user cooldown — a user cannot be auto-synced more often than
   COOLDOWN_SECONDS, unless an explicit/active trigger forces it (manual sync).

The scheduler consults the cooldown before enqueuing; the worker holds a global
slot only while a sync actually runs.
"""

from __future__ import annotations

import os

from jobs.redis_client import get_redis

GLOBAL_MAX = int(os.environ.get("GARMIN_GLOBAL_MAX_SYNCS", "8"))   # 5-10 range
COOLDOWN_SECONDS = int(os.environ.get("SYNC_USER_COOLDOWN", "900"))  # 15 min

GLOBAL_ACTIVE_KEY = "cardiocoach:garmin:global_active"
COOLDOWN_PREFIX = "cardiocoach:sync_cooldown:"


# --------------------------------------------------------------- per-user cooldown
async def cooldown_ok(user_id: str) -> bool:
    """True if the user is outside their cooldown window (safe to auto-sync)."""
    r = get_redis()
    return not await r.exists(f"{COOLDOWN_PREFIX}{user_id}")


async def set_cooldown(user_id: str, seconds: int = COOLDOWN_SECONDS) -> None:
    r = get_redis()
    await r.set(f"{COOLDOWN_PREFIX}{user_id}", "1", ex=seconds)


# ------------------------------------------------------------- global concurrency
async def acquire_global_slot() -> bool:
    """Try to take a global sync slot. Returns False if the cap is reached."""
    r = get_redis()
    current = await r.incr(GLOBAL_ACTIVE_KEY)
    if current == 1:
        # Safety TTL so a crashed worker can't leak the counter forever.
        await r.expire(GLOBAL_ACTIVE_KEY, 300)
    if current > GLOBAL_MAX:
        await r.decr(GLOBAL_ACTIVE_KEY)
        return False
    return True


async def release_global_slot() -> None:
    r = get_redis()
    val = await r.decr(GLOBAL_ACTIVE_KEY)
    if val < 0:  # never go negative
        await r.set(GLOBAL_ACTIVE_KEY, 0)


async def global_active_count() -> int:
    r = get_redis()
    v = await r.get(GLOBAL_ACTIVE_KEY)
    return int(v) if v else 0
