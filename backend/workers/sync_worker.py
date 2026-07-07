"""Garmin sync worker — consumes the Redis queue out-of-process.

Runs independently from the FastAPI process (own event loop, own Mongo + Redis
connections). Responsibilities:
  - consume the job queue via a reliable BLMOVE (queue -> processing list)
  - execute the real gccli sync via the existing service/provider layer
  - ACK (remove from processing) only on success -> at-least-once delivery
  - watchdog: requeue jobs orphaned by a crashed worker (kill -9)
  - throttle: max N concurrent syncs, one active sync per user (Redis lock)
  - retries (max SYNC_MAX_RETRIES) with backoff
  - per-job timeout (SYNC_JOB_TIMEOUT seconds)
  - structured logs (never credentials)

Start with:  python -m workers.sync_worker   (cwd = /app/backend)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time

# Make /app/backend importable when launched as a module or script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()  # load backend/.env when run standalone

import redis.asyncio as aioredis
from motor.motor_asyncio import AsyncIOMotorClient

from jobs.queue import (
    QUEUE_KEY,
    JOB_SYNC_USER,
    JOB_SYNC_ACTIVITY,
    JOB_INCREMENTAL_SYNC,
    LOCK_PREFIX,
    LOCK_TTL,
    PENDING_PREFIX,
    HEARTBEAT_PREFIX,
    HEARTBEAT_TTL,
    HEARTBEAT_INTERVAL,
    STATS_FAILED_KEY,
    claim_job,
    ack_job,
    requeue_job,
    recover_orphans,
)
from sync import rate_limiter
from garmin import service as garmin_service
from garmin.bootstrap import ensure_gccli_installed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_worker")

MAX_CONCURRENCY = int(os.environ.get("SYNC_MAX_CONCURRENCY", "5"))
JOB_TIMEOUT = int(os.environ.get("SYNC_JOB_TIMEOUT", "60"))
MAX_RETRIES = int(os.environ.get("SYNC_MAX_RETRIES", "3"))
# Watchdog cadence: how often the worker scans the processing list for orphans.
WATCHDOG_INTERVAL = int(os.environ.get("SYNC_WATCHDOG_INTERVAL", "30"))
# Periodic auto-sync (0 = disabled). When >0, all connected users are enqueued
# every N seconds, staggered to avoid a thundering herd at 1k users.
SCHEDULE_INTERVAL = int(os.environ.get("SYNC_SCHEDULE_INTERVAL", "0"))
SCHEDULE_STAGGER_MS = int(os.environ.get("SYNC_SCHEDULE_STAGGER_MS", "200"))


async def _run_job(db, job_type: str, user_id: str) -> dict:
    if job_type == JOB_INCREMENTAL_SYNC:
        return await garmin_service.incremental_sync(db, user_id)
    if job_type in (JOB_SYNC_USER, JOB_SYNC_ACTIVITY):
        # service.sync is idempotent (upserts) and writes to Mongo.
        return await garmin_service.sync(db, user_id)
    raise ValueError(f"unknown job type: {job_type}")


async def process_job(db, redis, raw: str, job: dict) -> None:
    job_type = job.get("type")
    user_id = job.get("user_id")
    job_id = job.get("id")
    attempts = int(job.get("attempts", 0))
    lock_key = f"{LOCK_PREFIX}{user_id}"

    # One active sync per user. If busy, move the in-flight job back to the queue.
    if not await redis.set(lock_key, "1", nx=True, ex=LOCK_TTL):
        logger.info("[worker] user=%s already syncing -> requeue", user_id)
        await asyncio.sleep(1)
        await requeue_job(raw, job_id)
        return

    # Global anti-explosion cap (cluster-wide). If saturated, requeue and back off.
    if not await rate_limiter.acquire_global_slot():
        logger.info("[worker] global sync cap reached -> requeue user=%s", user_id)
        await redis.delete(lock_key)
        await asyncio.sleep(2)
        await requeue_job(raw, job_id)
        return

    start = time.time()
    logger.info("[worker] sync_start type=%s user=%s attempt=%s", job_type, user_id, attempts + 1)
    try:
        result = await asyncio.wait_for(_run_job(db, job_type, user_id), timeout=JOB_TIMEOUT)
        duration = round(time.time() - start, 2)
        logger.info(
            "[worker] sync_success type=%s user=%s duration=%ss synced=%s new=%s metrics=%s",
            job_type, user_id, duration,
            result.get("synced_count"), result.get("new_count"), result.get("metrics_count"),
        )
        await redis.delete(f"{PENDING_PREFIX}{user_id}")
        # Cooldown: throttle auto-syncs for this user after a successful run.
        await rate_limiter.set_cooldown(user_id)
        # ACK only on success: this is the single point that removes the job.
        await ack_job(raw, job_id)
    except Exception as exc:  # timeout or provider/runner failure
        duration = round(time.time() - start, 2)
        attempts += 1
        if attempts < MAX_RETRIES:
            backoff = min(5 * attempts, 15)
            logger.warning(
                "[worker] sync_retry type=%s user=%s attempt=%s duration=%ss backoff=%ss err=%s",
                job_type, user_id, attempts, duration, backoff, exc,
            )
            job["attempts"] = attempts
            await asyncio.sleep(backoff)
            await requeue_job(raw, job_id, json.dumps(job))
        else:
            logger.error(
                "[worker] sync_failed type=%s user=%s attempts=%s duration=%ss err=%s",
                job_type, user_id, attempts, duration, exc,
            )
            await redis.delete(f"{PENDING_PREFIX}{user_id}")
            # Monitoring counter only (additive; failure handling unchanged).
            await redis.incr(STATS_FAILED_KEY)
            # Terminal failure after max retries: drop from processing.
            await ack_job(raw, job_id)
    finally:
        await rate_limiter.release_global_slot()
        await redis.delete(lock_key)


async def watchdog_loop() -> None:
    """Periodically recover orphan jobs left in the processing list by dead workers."""
    logger.info("[watchdog] enabled interval=%ss", WATCHDOG_INTERVAL)
    while True:
        try:
            n = await recover_orphans()
            if n:
                logger.warning("[watchdog] requeued %s orphan job(s)", n)
        except Exception as exc:
            logger.error("[watchdog] error: %s", exc)
        await asyncio.sleep(WATCHDOG_INTERVAL)


async def heartbeat_loop(redis) -> None:
    """Monitoring only: refresh this worker's presence key (TTL) periodically.

    active_workers in /queue/health counts these keys. Best-effort: a failure
    here never affects sync processing.
    """
    key = f"{HEARTBEAT_PREFIX}{os.getpid()}"
    logger.info("[heartbeat] enabled key=%s ttl=%ss interval=%ss", key, HEARTBEAT_TTL, HEARTBEAT_INTERVAL)
    while True:
        try:
            await redis.set(key, time.time(), ex=HEARTBEAT_TTL)
        except Exception as exc:
            logger.error("[heartbeat] error: %s", exc)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def scheduler_loop(db) -> None:
    """Optionally enqueue a sync for every connected user on a fixed interval.

    Disabled unless SYNC_SCHEDULE_INTERVAL > 0. Enqueues are deduped and
    staggered so 1k users don't hit Garmin simultaneously.
    """
    from jobs.queue import enqueue_sync  # local import: uses this process's Redis

    logger.info("[scheduler] enabled interval=%ss stagger=%sms", SCHEDULE_INTERVAL, SCHEDULE_STAGGER_MS)
    while True:
        try:
            cursor = db.garmin_connections.find({"connected": True}, {"_id": 0, "user_id": 1})
            count = 0
            async for conn in cursor:
                uid = conn.get("user_id")
                if not uid:
                    continue
                await enqueue_sync(uid)
                count += 1
                if SCHEDULE_STAGGER_MS:
                    await asyncio.sleep(SCHEDULE_STAGGER_MS / 1000.0)
            logger.info("[scheduler] tick enqueued=%s connected users", count)
        except Exception as exc:
            logger.error("[scheduler] error: %s", exc)
        await asyncio.sleep(SCHEDULE_INTERVAL)


async def main() -> None:
    # Ensure the gccli binary is on PATH for this (separate) worker process.
    try:
        ensure_gccli_installed()
    except Exception as exc:  # best-effort, never blocks worker startup
        logger.warning("[worker] gccli bootstrap skipped: %s", exc)

    # socket_timeout=None so blocking commands (BLMOVE) are not cut short.
    redis = aioredis.from_url(
        os.environ["REDIS_URL"],
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=None,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    mongo = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mongo[os.environ["DB_NAME"]]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    logger.info(
        "[worker] started concurrency=%s job_timeout=%ss max_retries=%s queue=%s",
        MAX_CONCURRENCY, JOB_TIMEOUT, MAX_RETRIES, QUEUE_KEY,
    )

    if SCHEDULE_INTERVAL > 0:
        asyncio.create_task(scheduler_loop(db))

    # Reliable-queue watchdog: recovers jobs orphaned by crashed workers.
    asyncio.create_task(watchdog_loop())
    # Monitoring-only heartbeat for /api/garmin/queue/health active_workers.
    asyncio.create_task(heartbeat_loop(redis))

    while True:
        try:
            await sem.acquire()
            claimed = await claim_job(timeout=5)
            if not claimed:
                sem.release()
                continue
            raw, job = claimed
            task = asyncio.create_task(process_job(db, redis, raw, job))
            task.add_done_callback(lambda _t: sem.release())
        except asyncio.CancelledError:
            break
        except Exception as exc:  # keep the loop alive
            logger.error("[worker] loop error: %s", exc)
            try:
                sem.release()
            except ValueError:
                pass
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
