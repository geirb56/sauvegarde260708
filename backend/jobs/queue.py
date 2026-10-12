"""Garmin sync job queue — enqueue side (used by the FastAPI process).

All Garmin sync work is enqueued here and executed out-of-process by
workers/sync_worker.py. The API never runs blocking gccli calls itself.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

from .redis_client import get_redis

logger = logging.getLogger(__name__)

# Single FIFO queue (LPUSH to enqueue, BLMOVE to claim into processing).
QUEUE_KEY = "runindex:garmin:queue"
# Reliable-queue in-flight list: a job lives here from claim until ACK.
PROCESSING_KEY = "runindex:garmin:processing"
# Hash job_id -> claimed_at (epoch); used by the watchdog to detect orphans.
CLAIMS_KEY = "runindex:garmin:claims"
# Explicit details/laps jobs share these existing delayed structures.
DELAYED_KEY = "runindex:garmin:details:delayed"
DELAYED_PAYLOADS_KEY = "runindex:garmin:details:delayed_payloads"
DETAILS_OUTCOMES_KEY = "runindex:garmin:details:outcomes"
# A job stuck in processing longer than this (s) is considered orphaned.
ORPHAN_TIMEOUT = int(os.environ.get("SYNC_ORPHAN_TIMEOUT", "120"))

# --- Monitoring-only keys (additive instrumentation; no queue behaviour) ---
# Per-worker heartbeat: runindex:worker:heartbeat:{pid}, TTL-refreshed.
HEARTBEAT_PREFIX = "runindex:worker:heartbeat:"
HEARTBEAT_TTL = int(os.environ.get("SYNC_HEARTBEAT_TTL", "15"))
HEARTBEAT_INTERVAL = int(os.environ.get("SYNC_HEARTBEAT_INTERVAL", "10"))
# Monotonic counters (INCR only).
STATS_ORPHANS_KEY = "runindex:stats:orphans_recovered"
STATS_FAILED_KEY = "runindex:stats:failed_jobs"

# Job types
JOB_SYNC_USER = "SYNC_USER"          # full sync: activities + daily health metrics
JOB_SYNC_ACTIVITY = "SYNC_ACTIVITY"  # activities-focused sync
JOB_INCREMENTAL_SYNC = "INCREMENTAL_SYNC"  # incremental: only new activities (since last)
JOB_VO2MAX_BACKFILL = "VO2MAX_BACKFILL"  # one-shot historical VO2max fetch
JOB_ACTIVITY_DETAILS = "ACTIVITY_DETAILS"
JOB_ACTIVITY_LAPS = "ACTIVITY_LAPS"
TARGETED_JOB_TYPES = {JOB_ACTIVITY_DETAILS, JOB_ACTIVITY_LAPS}


def _pending_key(job_type: str, user_id: str) -> str:
    if job_type == JOB_ACTIVITY_DETAILS:
        return f"{PENDING_PREFIX}{user_id}:activity_details"
    if job_type == JOB_ACTIVITY_LAPS:
        return f"{PENDING_PREFIX}{user_id}:activity_laps"
    if job_type == JOB_VO2MAX_BACKFILL:
        return f"{PENDING_PREFIX}{user_id}:vo2max_backfill"
    return f"{PENDING_PREFIX}{user_id}"


def _should_update_sync_progress(job_type: str) -> bool:
    return job_type in {JOB_SYNC_USER, JOB_SYNC_ACTIVITY, JOB_INCREMENTAL_SYNC}

# Redis keys for throttling / dedupe
LOCK_PREFIX = "sync_lock:"       # per-user concurrency lock (worker side)
LOCK_TTL = 120                   # seconds
PENDING_PREFIX = "sync_pending:"  # dedupe flag: a job is queued/running for user
PENDING_TTL = 300                # seconds
DETAILS_PENDING_TTL = 1800


async def acquire_user_lock(redis, user_id: str, token: str) -> bool:
    return bool(await redis.set(f"{LOCK_PREFIX}{user_id}", token, nx=True, ex=LOCK_TTL))


async def maintain_user_lock(redis, user_id: str, token: str, release=False) -> bool:
    """Only the current delivery may refresh or release the user lock."""
    return bool(await redis.eval(
        """
        if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
        if ARGV[2] == 'release' then return redis.call('DEL', KEYS[1]) end
        return redis.call('EXPIRE', KEYS[1], ARGV[3])
        """,
        1, f"{LOCK_PREFIX}{user_id}", token,
        "release" if release else "refresh", LOCK_TTL,
    ))


async def maintain_details_pending(
    redis, user_id: str, job_id: str, release=False, job_type=JOB_ACTIVITY_DETAILS,
):
    """Refresh/release only this job's reservation, never a newer job's flag."""
    if job_type not in TARGETED_JOB_TYPES:
        raise ValueError("Unsupported targeted job type")
    return await redis.eval(
        """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            if ARGV[2] == 'release' then return redis.call('DEL', KEYS[1]) end
            return redis.call('EXPIRE', KEYS[1], ARGV[3])
        end
        return 0
        """,
        1, _pending_key(job_type, user_id), job_id,
        "release" if release else "refresh", DETAILS_PENDING_TTL,
    )


async def recover_details_pending(redis, raw: str, job: dict) -> int:
    """Explicit recovery: only a claimed delivery still in PROCESSING is eligible."""
    return await redis.eval(
        """
        local expected = {'string', 'list', 'hash', 'hash'}
        for i, key in ipairs(KEYS) do
            local kind = redis.call('TYPE', key).ok
            if kind ~= 'none' and kind ~= expected[i] then
                return redis.error_reply('Invalid reservation recovery key type')
            end
        end
        local delivery = cjson.decode(ARGV[1])
        local suffixes = {ACTIVITY_DETAILS = ':activity_details', ACTIVITY_LAPS = ':activity_laps'}
        local suffix = suffixes[delivery.type]
        if delivery.id ~= ARGV[2] or delivery.user_id ~= ARGV[3]
           or suffix == nil or KEYS[1] ~= ARGV[5] .. delivery.user_id .. suffix then return 0 end
        if redis.call('LPOS', KEYS[2], ARGV[1]) == false then return 0 end
        if redis.call('HEXISTS', KEYS[3], ARGV[2]) == 0 then return 0 end
        if redis.call('HGET', KEYS[4], ARGV[2]) == 'superseded' then return 0 end
        local owner = redis.call('GET', KEYS[1])
        if owner == false then
            redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[4])
            return 1
        end
        if owner == ARGV[2] then
            return redis.call('EXPIRE', KEYS[1], ARGV[4])
        end
        redis.call('HSET', KEYS[4], ARGV[2], 'superseded')
        redis.call('EXPIRE', KEYS[4], ARGV[4])
        return 0
        """,
        4, _pending_key(job.get("type", JOB_ACTIVITY_DETAILS), job["user_id"]),
        PROCESSING_KEY, CLAIMS_KEY, DETAILS_OUTCOMES_KEY,
        raw, job["id"], job["user_id"], DETAILS_PENDING_TTL, PENDING_PREFIX,
    )


async def _push(job_type: str, user_id: str, attempts: int = 0, job_id: str = None) -> None:
    r = get_redis()
    payload = json.dumps({
        "id": job_id or uuid.uuid4().hex,
        "type": job_type,
        "user_id": user_id,
        "attempts": attempts,
        "enqueued_at": time.time(),
    })
    await r.lpush(QUEUE_KEY, payload)


async def _enqueue_deduped(job_type: str, user_id: str) -> dict:
    """Enqueue a job, skipping if one is already pending for this user."""
    r = get_redis()
    # NX pending flag prevents flooding the queue with duplicates for one user.
    fresh = await r.set(_pending_key(job_type, user_id), job_type, nx=True, ex=PENDING_TTL)
    if not fresh:
        logger.info("[queue] job=%s already pending user=%s (skipped)", job_type, user_id)
        return {"status": "already_queued"}
    if _should_update_sync_progress(job_type):
        from garmin.sync_progress import update_sync_progress
        await update_sync_progress(user_id, phase="queued", error_code=None)
    await _push(job_type, user_id)
    logger.info("[queue] enqueued job=%s user=%s", job_type, user_id)
    return {"status": "queued"}


async def enqueue_sync(user_id: str) -> dict:
    """Queue a full user sync (activities + daily metrics)."""
    return await _enqueue_deduped(JOB_SYNC_USER, user_id)


async def enqueue_activity_sync(user_id: str) -> dict:
    """Queue an activities-focused sync."""
    return await _enqueue_deduped(JOB_SYNC_ACTIVITY, user_id)


async def enqueue_incremental_sync(user_id: str) -> dict:
    """Queue an incremental sync (only new activities since the last one)."""
    return await _enqueue_deduped(JOB_INCREMENTAL_SYNC, user_id)


async def enqueue_vo2max_backfill(user_id: str) -> dict:
    """Queue the one-shot historical VO2max backfill."""
    return await _enqueue_deduped(JOB_VO2MAX_BACKFILL, user_id)


async def enqueue_activity_details(user_id: str, activity_id: str) -> dict:
    """One explicit target, at most one queued enrichment per user."""
    return await _enqueue_targeted(user_id, activity_id)


async def enqueue_activity_laps(user_id: str, activity_id: str) -> dict:
    """One lap target per user, independent of the details reservation.

    POST-only lookup confirms the reserved delivery's target; an unknown or
    different target is busy. The caller persists Mongo queued state before
    enqueueing; Redis is never the GET authority.
    """
    return await _enqueue_targeted(user_id, activity_id, JOB_ACTIVITY_LAPS)


async def _enqueue_targeted(
    user_id: str, activity_id: str, job_type=JOB_ACTIVITY_DETAILS,
) -> dict:
    if job_type == JOB_ACTIVITY_LAPS:
        from garmin.activity_laps import validate_activity_id
    else:
        from garmin.activity_details import validate_activity_id

    if job_type not in TARGETED_JOB_TYPES:
        raise ValueError("Unsupported targeted job type")
    activity_id = validate_activity_id(activity_id)
    r = get_redis()
    key = _pending_key(job_type, user_id)
    job_id = uuid.uuid4().hex
    if job_type == JOB_ACTIVITY_LAPS:
        payload = json.dumps({
            "id": job_id, "type": job_type, "user_id": user_id,
            "activity_id": activity_id, "attempts": 0, "enqueued_at": time.time(),
        })
        reservation = await r.eval(
            """
                local expected = {'string', 'list', 'list', 'hash'}
                for i, key in ipairs(KEYS) do
                    local kind = redis.call('TYPE', key).ok
                    if kind ~= 'none' and kind ~= expected[i] then
                        return redis.error_reply('Invalid laps enqueue key type')
                    end
                end
                if redis.call('SET', KEYS[1], ARGV[3], 'NX', 'EX', ARGV[4]) then
                    redis.call('LPUSH', KEYS[2], ARGV[5])
                    return 2
                end
                local owner = redis.call('GET', KEYS[1])
                if owner == false then return 0 end
                local function matches(payload)
                    local ok, job = pcall(cjson.decode, payload)
                    if not ok or type(job) ~= 'table' or job.id ~= owner then return nil end
                    return job.type == 'ACTIVITY_LAPS' and job.user_id == ARGV[1]
                           and job.activity_id == ARGV[2]
                end
                local payload = redis.call('HGET', KEYS[4], owner)
                if payload then
                    local same = matches(payload)
                    if same ~= nil then return same and 1 or 0 end
                end
                for i = 2, 3 do
                    for _, raw in ipairs(redis.call('LRANGE', KEYS[i], 0, -1)) do
                        local same = matches(raw)
                        if same ~= nil then return same and 1 or 0 end
                    end
                end
                return 0
            """,
            4, key, QUEUE_KEY, PROCESSING_KEY, DELAYED_PAYLOADS_KEY,
            user_id, activity_id, job_id, DETAILS_PENDING_TTL, payload,
        )
        if reservation != 2:
            return {"status": "already_queued" if reservation == 1 else "busy"}
        return {"status": "queued"}
    elif not await r.set(key, job_id, nx=True, ex=DETAILS_PENDING_TTL):
        return {"status": "already_queued"}
    try:
        await r.lpush(QUEUE_KEY, json.dumps({
            "id": job_id, "type": job_type,
            "user_id": user_id, "activity_id": activity_id,
            "attempts": 0, "enqueued_at": time.time(),
        }))
    except Exception:
        await maintain_details_pending(r, user_id, job_id, release=True, job_type=job_type)
        raise
    return {"status": "queued"}


# --------------------------------------------------------------------------- #
# Reliable-queue primitives (at-least-once delivery).
#
# A job flows: QUEUE_KEY --BLMOVE--> PROCESSING_KEY --ACK(LREM)--> gone.
# While in PROCESSING_KEY it is "in flight" and CLAIMS_KEY[id] holds the claim
# time. If a worker dies before ACK, the job stays in PROCESSING_KEY and the
# watchdog (recover_orphans) pushes it back to QUEUE_KEY once its claim is older
# than ORPHAN_TIMEOUT. Nothing is lost on crash; jobs may run more than once,
# which is safe because service.sync is idempotent (upserts).
# --------------------------------------------------------------------------- #


async def claim_job(timeout: int = 5):
    """Atomically move the oldest job from the queue into the processing list.

    LPUSH enqueues at the head, so the tail (RIGHT) holds the oldest job (FIFO).
    Returns (raw, job) or None on timeout. Malformed payloads are discarded.
    """
    r = get_redis()
    raw = await r.blmove(QUEUE_KEY, PROCESSING_KEY, timeout, src="RIGHT", dest="LEFT")
    if not raw:
        return None
    try:
        job = json.loads(raw)
        job_id = job["id"]
    except (ValueError, TypeError, KeyError):
        logger.error("[queue] discarded malformed in-flight payload")
        await r.lrem(PROCESSING_KEY, 1, raw)
        return None
    await r.hset(CLAIMS_KEY, job_id, time.time())
    return raw, job


async def ack_job(raw: str, job_id: str) -> None:
    """Acknowledge a finished job: remove it from the processing list."""
    r = get_redis()
    async with r.pipeline(transaction=True) as pipe:
        pipe.lrem(PROCESSING_KEY, 1, raw)
        pipe.hdel(CLAIMS_KEY, job_id)
        await pipe.execute()


async def requeue_job(raw: str, job_id: str, new_payload: str = None) -> None:
    """Remove an in-flight job and push it back to the queue for another attempt."""
    r = get_redis()
    async with r.pipeline(transaction=True) as pipe:
        pipe.lrem(PROCESSING_KEY, 1, raw)
        pipe.hdel(CLAIMS_KEY, job_id)
        pipe.lpush(QUEUE_KEY, new_payload if new_payload is not None else raw)
        await pipe.execute()


async def defer_activity_details(raw: str, job: dict) -> None:
    """Atomically park an in-flight job, without ACK or a runnable-queue loop."""
    due = float(job["not_before"])
    ttl = max(DETAILS_PENDING_TTL, int(due - time.time()) + DETAILS_PENDING_TTL)
    await get_redis().eval(
        """
        local expected = {'list', 'hash', 'zset', 'hash', 'string'}
        for i, key in ipairs(KEYS) do
            local kind = redis.call('TYPE', key).ok
            if kind ~= 'none' and kind ~= expected[i] then
                return redis.error_reply('Invalid deferred key type')
            end
        end
        local delivery = cjson.decode(ARGV[1])
        local job = cjson.decode(ARGV[3])
        local suffixes = {ACTIVITY_DETAILS = ':activity_details', ACTIVITY_LAPS = ':activity_laps'}
        local suffix = suffixes[job.type]
        if suffix == nil or job.id ~= ARGV[2] or delivery.id ~= job.id
           or delivery.type ~= job.type or delivery.user_id ~= job.user_id
           or delivery.activity_id ~= job.activity_id
           or type(job.user_id) ~= 'string'
           or KEYS[5] ~= ARGV[6] .. job.user_id .. suffix then
            return redis.error_reply('Invalid deferred identity')
        end
        if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 0 then return 0 end
        redis.call('HDEL', KEYS[2], ARGV[2])
        redis.call('HSET', KEYS[4], ARGV[2], ARGV[3])
        redis.call('ZADD', KEYS[3], ARGV[4], ARGV[2])
        if redis.call('GET', KEYS[5]) == ARGV[2] then
            redis.call('EXPIRE', KEYS[5], ARGV[5])
        end
        return 1
        """,
        5, PROCESSING_KEY, CLAIMS_KEY, DELAYED_KEY, DELAYED_PAYLOADS_KEY,
        _pending_key(job.get("type", JOB_ACTIVITY_DETAILS), job["user_id"]),
        raw, job["id"], json.dumps(job), due, ttl, PENDING_PREFIX,
    )


async def promote_due_activity_details() -> int:
    """Watchdog promotion, bounded and atomic across multiple workers."""
    result = await get_redis().eval(
        """
        local expected = {'zset', 'hash', 'list', 'hash'}
        for i, key in ipairs(KEYS) do
            local kind = redis.call('TYPE', key).ok
            if kind ~= 'none' and kind ~= expected[i] then
                return redis.error_reply('Invalid promotion key type')
            end
        end
        local ids = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1],
                               'LIMIT', 0, 100)
        local jobs = {}
        for _, id in ipairs(ids) do
            local payload = redis.call('HGET', KEYS[2], id)
            if not payload then return redis.error_reply('Missing delayed payload: ' .. id) end
            local job = cjson.decode(payload)
            local suffixes = {ACTIVITY_DETAILS = ':activity_details', ACTIVITY_LAPS = ':activity_laps'}
            local suffix = suffixes[job.type]
            if job.id ~= id or type(job.user_id) ~= 'string' or suffix == nil then
                return redis.error_reply('Invalid delayed identity')
            end
            local pending = ARGV[2] .. job.user_id .. suffix
            local kind = redis.call('TYPE', pending).ok
            if kind ~= 'none' and kind ~= 'string' then
                return redis.error_reply('Invalid pending key type')
            end
            jobs[id] = pending
        end
        local promoted = 0
        local superseded = {}
        for _, id in ipairs(ids) do
            local payload = redis.call('HGET', KEYS[2], id)
            if payload then
                local pending = jobs[id]
                local owner = redis.call('GET', pending)
                if owner == false or owner == id then
                    redis.call('SET', pending, id, 'EX', ARGV[3])
                    redis.call('LPUSH', KEYS[3], payload)
                    promoted = promoted + 1
                else
                    redis.call('HSET', KEYS[4], id, 'superseded')
                    redis.call('EXPIRE', KEYS[4], ARGV[3])
                    table.insert(superseded, id)
                end
            else
                return redis.error_reply('Missing delayed payload: ' .. id)
            end
            redis.call('ZREM', KEYS[1], id)
            redis.call('HDEL', KEYS[2], id)
        end
        return {promoted, superseded}
        """,
        4, DELAYED_KEY, DELAYED_PAYLOADS_KEY, QUEUE_KEY, DETAILS_OUTCOMES_KEY, time.time(),
        PENDING_PREFIX, DETAILS_PENDING_TTL,
    )
    for job_id in result[1]:
        logger.warning("[queue] targeted enrichment terminal=superseded job_id=%s", job_id)
    return result[0]


async def recover_orphans() -> int:
    """Requeue jobs stuck in the processing list past ORPHAN_TIMEOUT.

    Called periodically by the worker watchdog. A missing claim record is
    adopted (stamped now) rather than recovered immediately, to avoid racing a
    worker that just claimed a job but has not yet recorded its claim time.
    """
    r = get_redis()
    raws = await r.lrange(PROCESSING_KEY, 0, -1)
    now = time.time()
    recovered = 0
    for raw in raws:
        try:
            job = json.loads(raw)
            job_id = job["id"]
        except (ValueError, TypeError, KeyError):
            await r.lrem(PROCESSING_KEY, 1, raw)
            continue
        claimed_at = await r.hget(CLAIMS_KEY, job_id)
        if claimed_at is None:
            if job.get("type") in TARGETED_JOB_TYPES:
                await r.eval(
                    """
                    if redis.call('LPOS', KEYS[1], ARGV[1]) == false then return 0 end
                    return redis.call('HSETNX', KEYS[2], ARGV[2], ARGV[3])
                    """,
                    2, PROCESSING_KEY, CLAIMS_KEY, raw, job_id, now,
                )
            else:
                await r.hset(CLAIMS_KEY, job_id, now)
            continue
        if now - float(claimed_at) <= ORPHAN_TIMEOUT:
            continue
        if job.get("type") in TARGETED_JOB_TYPES:
            # The same payload may have been recovered and freshly claimed
            # since HGET; only move the delivery we actually observed.
            moved = await r.eval(
                """
                local expected = {'list', 'hash', 'list'}
                for i, key in ipairs(KEYS) do
                    local kind = redis.call('TYPE', key).ok
                    if kind ~= 'none' and kind ~= expected[i] then
                        return redis.error_reply('Invalid orphan key type')
                    end
                end
                if redis.call('HGET', KEYS[2], ARGV[2]) ~= ARGV[3] then return 0 end
                if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 0 then return 0 end
                redis.call('HDEL', KEYS[2], ARGV[2])
                redis.call('LPUSH', KEYS[3], ARGV[1])
                return 1
                """,
                3, PROCESSING_KEY, CLAIMS_KEY, QUEUE_KEY, raw, job_id, claimed_at,
            )
            recovered += int(moved)
            continue
        # Orphan: move it back to the queue atomically. LREM returns 0 if another
        # process already recovered/acked it, in which case we do nothing.
        async with r.pipeline(transaction=True) as pipe:
            pipe.lrem(PROCESSING_KEY, 1, raw)
            pipe.hdel(CLAIMS_KEY, job_id)
            results = await pipe.execute()
        if results and results[0]:
            await r.lpush(QUEUE_KEY, raw)
            recovered += 1
            logger.warning("[watchdog] recovered orphan job id=%s user=%s", job_id, job.get("user_id"))
    if recovered:
        # Monitoring counter only (additive; does not affect recovery logic).
        await r.incrby(STATS_ORPHANS_KEY, recovered)
    return recovered
