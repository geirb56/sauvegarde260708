"""Tests for the READ-ONLY queue health endpoint (jobs/health.queue_health).

Covers: Redis OK, Redis unavailable, empty queue, loaded queue, worker absent,
and orphan recovery counter. The live sync-worker is stopped during the run so
worker heartbeats are fully deterministic (we create/delete them ourselves),
then restarted at the end.

Run:  cd /app/backend && python -m tests.test_queue_health
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

os.environ["SYNC_ORPHAN_TIMEOUT"] = "2"

import redis.asyncio as aioredis  # noqa: E402

from jobs import redis_client  # noqa: E402
from jobs.health import queue_health  # noqa: E402
from jobs.queue import (  # noqa: E402
    QUEUE_KEY,
    PROCESSING_KEY,
    CLAIMS_KEY,
    HEARTBEAT_PREFIX,
    STATS_ORPHANS_KEY,
    STATS_FAILED_KEY,
    recover_orphans,
)


def _ok(m): print(f"  ✅ {m}", flush=True)
def _fail(m):
    print(f"  ❌ {m}", flush=True)
    raise AssertionError(m)


async def _reset(r):
    await r.delete(QUEUE_KEY, PROCESSING_KEY, CLAIMS_KEY, STATS_ORPHANS_KEY, STATS_FAILED_KEY)
    async for k in r.scan_iter(match=f"{HEARTBEAT_PREFIX}*", count=100):
        await r.delete(k)


async def _add_worker(r, pid="test-1"):
    await r.set(f"{HEARTBEAT_PREFIX}{pid}", time.time(), ex=15)


async def test_redis_ok_empty(r):
    print("\n[TEST 1] Redis OK + empty queue + worker present -> healthy", flush=True)
    await _reset(r)
    await _add_worker(r)
    h = await queue_health()
    if not h["redis_connected"]:
        _fail("redis_connected should be True")
    if h["status"] != "healthy":
        _fail(f"expected healthy, got {h['status']}")
    if h["queue_length"] != 0 or h["processing_length"] != 0:
        _fail(f"expected empty lengths, got {h}")
    if h["active_workers"] != 1:
        _fail(f"expected 1 worker, got {h['active_workers']}")
    _ok(f"healthy, workers=1, queue=0 (timestamp {h['timestamp']})")


async def test_redis_unavailable():
    print("\n[TEST 2] Redis unavailable -> unhealthy, redis_connected False", flush=True)
    # Point the singleton at a dead port so ping fails.
    saved = redis_client._redis
    redis_client._redis = aioredis.from_url(
        "redis://localhost:6399/0", decode_responses=True, socket_connect_timeout=1
    )
    try:
        h = await queue_health()
    finally:
        try:
            await redis_client._redis.aclose()
        except Exception:
            pass
        redis_client._redis = saved
    if h["redis_connected"]:
        _fail("redis_connected should be False")
    if h["status"] != "unhealthy":
        _fail(f"expected unhealthy, got {h['status']}")
    _ok("redis down -> unhealthy, redis_connected False")


async def test_queue_loaded(r):
    print("\n[TEST 3] loaded queue -> degraded then unhealthy", flush=True)
    await _reset(r)
    await _add_worker(r)

    await r.rpush(QUEUE_KEY, *[str(i) for i in range(600)])
    h = await queue_health()
    if h["status"] != "degraded" or h["queue_length"] != 600:
        _fail(f"expected degraded @600, got status={h['status']} len={h['queue_length']}")
    _ok("queue=600 -> degraded")

    await r.rpush(QUEUE_KEY, *[str(i) for i in range(1500)])  # total 2100
    h = await queue_health()
    if h["status"] != "unhealthy" or h["queue_length"] != 2100:
        _fail(f"expected unhealthy @2100, got status={h['status']} len={h['queue_length']}")
    _ok("queue=2100 -> unhealthy")
    await _reset(r)


async def test_worker_absent(r):
    print("\n[TEST 4] no worker heartbeat -> unhealthy", flush=True)
    await _reset(r)  # removes all heartbeats
    h = await queue_health()
    if h["active_workers"] != 0:
        _fail(f"expected 0 workers, got {h['active_workers']}")
    if h["status"] != "unhealthy":
        _fail(f"expected unhealthy with no worker, got {h['status']}")
    _ok("active_workers=0 -> unhealthy")


async def test_orphan_counter(r):
    print("\n[TEST 5] orphan recovery increments orphans_recovered_total", flush=True)
    await _reset(r)
    await _add_worker(r)

    job = {"id": uuid.uuid4().hex, "type": "SYNC_USER", "user_id": "hc", "attempts": 0}
    raw = json.dumps(job)
    await r.rpush(PROCESSING_KEY, raw)
    await r.hset(CLAIMS_KEY, job["id"], time.time() - 9999)  # very old -> orphan

    before = await queue_health()
    n = await recover_orphans()
    if n != 1:
        _fail(f"recover_orphans returned {n}, expected 1")
    after = await queue_health()
    if after["orphans_recovered_total"] != before["orphans_recovered_total"] + 1:
        _fail(f"counter not incremented: {before['orphans_recovered_total']} -> {after['orphans_recovered_total']}")
    _ok(f"orphans_recovered_total {before['orphans_recovered_total']} -> {after['orphans_recovered_total']}")
    await _reset(r)


async def test_latency(r):
    print("\n[TEST 6] endpoint latency < 10ms (server-side)", flush=True)
    await _reset(r)
    await _add_worker(r)
    await queue_health()  # warm
    times = []
    for _ in range(20):
        t = time.perf_counter()
        await queue_health()
        times.append((time.perf_counter() - t) * 1000)
    avg, mx = sum(times) / len(times), max(times)
    if mx >= 10:
        _fail(f"max latency {mx:.2f}ms >= 10ms")
    _ok(f"avg={avg:.2f}ms max={mx:.2f}ms (<10ms)")
    await _reset(r)


async def main() -> int:
    subprocess.run(["sudo", "supervisorctl", "stop", "sync-worker"], capture_output=True, text=True)
    await asyncio.sleep(1)
    r = redis_client.get_redis()
    await r.ping()
    failed = 0
    try:
        for test in (test_redis_ok_empty, test_queue_loaded, test_worker_absent,
                     test_orphan_counter, test_latency):
            try:
                await test(r)
            except AssertionError:
                failed += 1
            except Exception as exc:
                print(f"  ❌ error in {test.__name__}: {exc}", flush=True)
                failed += 1
        # Redis-unavailable test manipulates the singleton, run it last/isolated.
        try:
            await test_redis_unavailable()
        except AssertionError:
            failed += 1
        await _reset(redis_client.get_redis())
    finally:
        subprocess.run(["sudo", "supervisorctl", "start", "sync-worker"], capture_output=True, text=True)
    print(f"\n{'='*50}\nRESULT: {'ALL PASSED ✅' if failed == 0 else f'{failed} TEST(S) FAILED ❌'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
