"""Anti-API-explosion layer for Garmin syncs (mandatory for 10k users).

Two independent protections, both Redis-backed so they hold ACROSS workers:

1. Global concurrency cap — at most GLOBAL_MAX gccli syncs run at once, cluster
   wide (owner leases, on top of each worker's local semaphore).
2. Per-user cooldown — a user cannot be auto-synced more often than
   COOLDOWN_SECONDS, unless an explicit/active trigger forces it (manual sync).

The scheduler consults the cooldown before enqueuing; the worker holds a global
slot only while a sync actually runs.
"""

from __future__ import annotations

import os
import uuid

from jobs.redis_client import get_redis

GLOBAL_MAX = int(os.environ.get("GARMIN_GLOBAL_MAX_SYNCS", "8"))   # 5-10 range
GLOBAL_LEASE_SECONDS = 300
COOLDOWN_SECONDS = int(os.environ.get("SYNC_USER_COOLDOWN", "900"))  # 15 min

GLOBAL_ACTIVE_KEY = "runindex:garmin:global_active"
GLOBAL_LEASE_KEY = "runindex:garmin:global_leases"
COOLDOWN_PREFIX = "runindex:sync_cooldown:"


# --------------------------------------------------------------- per-user cooldown
async def cooldown_ok(user_id: str) -> bool:
    """True if the user is outside their cooldown window (safe to auto-sync)."""
    r = get_redis()
    return not await r.exists(f"{COOLDOWN_PREFIX}{user_id}")


async def set_cooldown(user_id: str, seconds: int = COOLDOWN_SECONDS) -> None:
    r = get_redis()
    await r.set(f"{COOLDOWN_PREFIX}{user_id}", "1", ex=seconds)


# ------------------------------------------------------------- global concurrency
async def acquire_global_slot(token: str = None) -> str | None:
    """Atomically reserve capacity for a unique delivery, using Redis time.

    The legacy counter is a migration barrier: old workers must drain before
    new leases are admitted. Never recycle or delete their counter here.
    """
    token = token or uuid.uuid4().hex
    r = get_redis()
    acquired = await r.eval(
        """
        local legacy = redis.call('GET', KEYS[2])
        if legacy and tonumber(legacy) ~= 0 then return 0 end
        local now = redis.call('TIME')
        now = tonumber(now[1]) + tonumber(now[2]) / 1000000
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
        if redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
        if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
        redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[1])
        return 1
        """,
        2, GLOBAL_LEASE_KEY, GLOBAL_ACTIVE_KEY, token, GLOBAL_MAX, GLOBAL_LEASE_SECONDS,
    )
    return token if acquired else None


async def release_global_slot(token: str) -> bool:
    """A late release removes only its own member, never another holder."""
    return bool(await get_redis().zrem(GLOBAL_LEASE_KEY, token))


RENEW_LEASES_LUA = """
local now = redis.call('TIME')
now = tonumber(now[1]) + tonumber(now[2]) / 1000000
local expires = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not expires or tonumber(expires) <= now then return 0 end
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return 1
"""


async def renew_execution_leases(redis, user_id: str, token: str) -> bool:
    from jobs.queue import LOCK_PREFIX, LOCK_TTL

    return bool(await redis.eval(
        RENEW_LEASES_LUA, 2, GLOBAL_LEASE_KEY, f"{LOCK_PREFIX}{user_id}",
        token, GLOBAL_LEASE_SECONDS, LOCK_TTL,
    ))


async def global_active_count() -> int:
    r = get_redis()
    return int(await r.eval(
        """
        local now = redis.call('TIME')
        now = tonumber(now[1]) + tonumber(now[2]) / 1000000
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
        local legacy = redis.call('GET', KEYS[2])
        return redis.call('ZCARD', KEYS[1]) + (tonumber(legacy) or 0)
        """,
        2, GLOBAL_LEASE_KEY, GLOBAL_ACTIVE_KEY,
    ))
