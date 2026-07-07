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
QUEUE_KEY = "cardiocoach:garmin:queue"
# Reliable-queue in-flight list: a job lives here from claim until ACK.
PROCESSING_KEY = "cardiocoach:garmin:processing"
# Hash job_id -> claimed_at (epoch); used by the watchdog to detect orphans.
CLAIMS_KEY = "cardiocoach:garmin:claims"
# A job stuck in processing longer than this (s) is considered orphaned.
ORPHAN_TIMEOUT = int(os.environ.get("SYNC_ORPHAN_TIMEOUT", "120"))

# --- Monitoring-only keys (additive instrumentation; no queue behaviour) ---
# Per-worker heartbeat: cardiocoach:worker:heartbeat:{pid}, TTL-refreshed.
HEARTBEAT_PREFIX = "cardiocoach:worker:heartbeat:"
HEARTBEAT_TTL = int(os.environ.get("SYNC_HEARTBEAT_TTL", "15"))
HEARTBEAT_INTERVAL = int(os.environ.get("SYNC_HEARTBEAT_INTERVAL", "10"))
# Monotonic counters (INCR only).
STATS_ORPHANS_KEY = "cardiocoach:stats:orphans_recovered"
STATS_FAILED_KEY = "cardiocoach:stats:failed_jobs"

# Job types
JOB_SYNC_USER = "SYNC_USER"          # full sync: activities + daily health metrics
JOB_SYNC_ACTIVITY = "SYNC_ACTIVITY"  # activities-focused sync
JOB_INCREMENTAL_SYNC = "INCREMENTAL_SYNC"  # incremental: only new activities (since last)

# Redis keys for throttling / dedupe
LOCK_PREFIX = "sync_lock:"       # per-user concurrency lock (worker side)
LOCK_TTL = 120                   # seconds
PENDING_PREFIX = "sync_pending:"  # dedupe flag: a job is queued/running for user
PENDING_TTL = 300                # seconds


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
    fresh = await r.set(f"{PENDING_PREFIX}{user_id}", job_type, nx=True, ex=PENDING_TTL)
    if not fresh:
        logger.info("[queue] job=%s already pending user=%s (skipped)", job_type, user_id)
        return {"status": "already_queued"}
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
            await r.hset(CLAIMS_KEY, job_id, now)
            continue
        if now - float(claimed_at) <= ORPHAN_TIMEOUT:
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
