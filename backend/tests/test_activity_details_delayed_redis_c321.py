"""C321 Lua integration against an isolated LOCAL Redis, never production.

Uses the repository's Redis dependency/runtime, no Garmin or MongoDB.
Skipped when redis-server is unavailable; no external REDIS_URL is used.
"""

import asyncio
import json
import shutil
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import redis
import redis.asyncio as aioredis

from jobs import queue


@pytest.fixture
def local_redis(tmp_path):
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("Local redis-server is not installed")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    def start():
        process = subprocess.Popen([
            executable, "--bind", "127.0.0.1", "--port", str(port),
            "--dir", str(tmp_path), "--appendonly", "yes", "--appendfsync", "always",
            "--save", "", "--loglevel", "warning",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = redis.Redis(host="127.0.0.1", port=port)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if client.ping():
                    client.close()
                    return process
            except redis.ConnectionError:
                pass
            time.sleep(0.01)
        process.kill()
        process.wait(timeout=5)
        client.close()
        pytest.fail("Isolated Redis did not start")

    process = start()

    def restart():
        nonlocal process
        process.kill()
        process.wait(timeout=5)
        process = start()

    try:
        yield f"redis://127.0.0.1:{port}/0", restart
    finally:
        process.terminate()
        process.wait(timeout=5)


@asynccontextmanager
async def client_for(local_redis, monkeypatch):
    client = aioredis.from_url(local_redis[0], decode_responses=True)
    monkeypatch.setattr(queue, "get_redis", lambda: client)
    try:
        yield client
    finally:
        await client.aclose()


async def in_flight(client, job_id="c321", delay=900, user_id="a"):
    job = {
        "id": job_id, "type": queue.JOB_ACTIVITY_DETAILS, "user_id": user_id,
        "activity_id": "123", "attempts": 1, "not_before": time.time() + delay,
    }
    raw = json.dumps(job)
    await client.lpush(queue.PROCESSING_KEY, raw)
    await client.hset(queue.CLAIMS_KEY, job_id, time.time())
    await client.set(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, user_id),
                     job_id, ex=queue.DETAILS_PENDING_TTL)
    return raw, job


def test_delay_is_atomic_idempotent_and_keeps_fifo_available(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            await queue.defer_activity_details(raw, job)
            await queue.defer_activity_details(raw, {**job, "attempts": 99})
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.hlen(queue.CLAIMS_KEY) == 0
            assert await client.zcard(queue.DELAYED_KEY) == 1
            assert json.loads(await client.hget(queue.DELAYED_PAYLOADS_KEY, job["id"]))["attempts"] == 1
            assert await client.ttl(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")) >= 2698
            for _ in range(3):
                assert await queue.promote_due_activity_details() == 0
            normal = json.dumps({"id": "normal", "type": queue.JOB_SYNC_USER, "user_id": "b"})
            await client.lpush(queue.QUEUE_KEY, normal)
            claimed = await queue.claim_job(timeout=1)
            assert claimed[1]["id"] == "normal"
            await queue.ack_job(claimed[0], "normal")
            assert await client.llen(queue.QUEUE_KEY) == 0

    asyncio.run(scenario())


def test_due_promotion_is_exactly_once_across_watchdogs(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            await queue.defer_activity_details(raw, job)
            counts = await asyncio.gather(
                queue.promote_due_activity_details(), queue.promote_due_activity_details(),
            )
            assert sum(counts) == 1
            assert await client.zcard(queue.DELAYED_KEY) == 0
            assert await client.hlen(queue.DELAYED_PAYLOADS_KEY) == 0
            claimed = await queue.claim_job(timeout=1)
            assert claimed[1]["id"] == job["id"]
            assert claimed[1]["attempts"] == 1
            assert await client.llen(queue.QUEUE_KEY) == 0
            await queue.ack_job(claimed[0], job["id"])

    asyncio.run(scenario())


def test_due_promotion_has_bounded_batch(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            for i in range(101):
                raw, job = await in_flight(client, job_id=f"c321-{i}", delay=-1, user_id=f"user-{i}")
                await queue.defer_activity_details(raw, job)
            assert await queue.promote_due_activity_details() == 100
            assert await client.zcard(queue.DELAYED_KEY) == 1
            assert await queue.promote_due_activity_details() == 1
            assert await client.llen(queue.QUEUE_KEY) == 101
            ids = [json.loads(raw)["id"] for raw in await client.lrange(queue.QUEUE_KEY, 0, -1)]
            assert len(set(ids)) == 101

    asyncio.run(scenario())


def test_pending_ownership_survives_old_deferral_and_release(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")
            await client.set(key, "newer-job", ex=30)
            await queue.defer_activity_details(raw, job)
            await queue.maintain_details_pending(client, "a", job["id"], release=True)
            assert await client.get(key) == "newer-job"
            assert await client.ttl(key) <= 30
            assert queue.DETAILS_PENDING_TTL > 900

    asyncio.run(scenario())


def test_parked_job_survives_local_redis_kill_and_aof_restart(local_redis, monkeypatch):
    async def park():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            await queue.defer_activity_details(raw, job)

    asyncio.run(park())
    local_redis[1]()

    async def promote():
        async with client_for(local_redis, monkeypatch) as client:
            assert await client.zcard(queue.DELAYED_KEY) == 1
            assert await queue.promote_due_activity_details() == 1
            raw, job = await queue.claim_job(timeout=1)
            assert job["id"] == "c321"
            assert job["attempts"] == 1
            await queue.ack_job(raw, job["id"])

    asyncio.run(promote())


@pytest.mark.parametrize("new_owner", [None, "new-job"])
def test_expired_pending_promotion_reclaims_only_if_unowned(local_redis, monkeypatch, new_owner):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            await queue.defer_activity_details(raw, job)
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")
            await client.pexpire(key, 1)
            await asyncio.sleep(0.01)
            assert await client.get(key) is None
            if new_owner:
                await client.set(key, new_owner, ex=30)
            assert await queue.promote_due_activity_details() == (0 if new_owner else 1)
            assert await client.get(key) == (new_owner or job["id"])
            assert await client.zcard(queue.DELAYED_KEY) == 0
            assert await client.llen(queue.QUEUE_KEY) == (0 if new_owner else 1)
            if new_owner:
                assert await client.hget(queue.DETAILS_OUTCOMES_KEY, job["id"]) == "superseded"

    asyncio.run(scenario())


def test_crash_before_parking_keeps_processing_and_recovery_is_safe(local_redis, monkeypatch):
    async def claim():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
    asyncio.run(claim())
    local_redis[1]()

    async def recover():
        async with client_for(local_redis, monkeypatch) as client:
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await queue.recover_orphans() == 1
            raw, job = await queue.claim_job(timeout=1)
            await queue.defer_activity_details(raw, job)
            assert await queue.promote_due_activity_details() == 1
    asyncio.run(recover())


def test_redis_wrong_type_before_transition_preserves_job(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            await client.set(queue.DELAYED_KEY, "wrong-type")
            with pytest.raises(redis.ResponseError):
                await queue.defer_activity_details(raw, job)
            assert await client.llen(queue.PROCESSING_KEY) == 1
            await client.delete(queue.DELAYED_KEY)
            await queue.defer_activity_details(raw, job)
            await client.set(queue.QUEUE_KEY, "wrong-type")
            with pytest.raises(redis.ResponseError):
                await queue.promote_due_activity_details()
            assert await client.zcard(queue.DELAYED_KEY) == 1
            await client.delete(queue.QUEUE_KEY)
            assert await queue.promote_due_activity_details() == 1
    asyncio.run(scenario())


def test_two_watchdogs_recover_one_details_orphan_once(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
            results = await asyncio.gather(queue.recover_orphans(), queue.recover_orphans())
            assert sum(results) == 1
            assert await client.llen(queue.QUEUE_KEY) == 1
            assert await client.llen(queue.PROCESSING_KEY) == 0
    asyncio.run(scenario())


def test_stale_watchdog_does_not_recover_a_fresh_redelivery(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
            original_hget = client.hget

            async def redeliver(key, job_id):
                observed = await original_hget(key, job_id)
                await queue.requeue_job(raw, job_id)
                assert (await queue.claim_job(timeout=1))[1]["id"] == job_id
                return observed

            monkeypatch.setattr(client, "hget", redeliver)
            assert await queue.recover_orphans() == 0
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert float(await original_hget(queue.CLAIMS_KEY, job["id"])) > 0
    asyncio.run(scenario())


def test_missing_claim_adoption_does_not_overwrite_a_fresh_claim(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            _, job = await in_flight(client)
            await client.hdel(queue.CLAIMS_KEY, job["id"])
            original_hget = client.hget
            fresh_claim = time.time() + 10

            async def claim_during_read(key, job_id):
                observed = await original_hget(key, job_id)
                await client.hset(key, job_id, fresh_claim)
                return observed

            monkeypatch.setattr(client, "hget", claim_during_read)
            assert await queue.recover_orphans() == 0
            assert float(await original_hget(queue.CLAIMS_KEY, job["id"])) == fresh_claim
    asyncio.run(scenario())


def test_missing_claim_adoption_does_not_resurrect_an_acked_job(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            await client.hdel(queue.CLAIMS_KEY, job["id"])
            original_hget = client.hget

            async def ack_during_read(key, job_id):
                observed = await original_hget(key, job_id)
                await queue.ack_job(raw, job_id)
                return observed

            monkeypatch.setattr(client, "hget", ack_during_read)
            assert await queue.recover_orphans() == 0
            assert await client.hlen(queue.CLAIMS_KEY) == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", ["user_lock", "global_cap"])
def test_details_backpressure_parks_without_sleep_or_retry(monkeypatch, blocked):
    from workers import sync_worker

    client = AsyncMock()
    client.set.return_value = blocked != "user_lock"
    monkeypatch.setattr(sync_worker, "maintain_details_pending", AsyncMock(return_value=1))
    acquire = AsyncMock(return_value=False)
    monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot", acquire)
    defer = AsyncMock()
    requeue = AsyncMock()
    work = AsyncMock()
    sleep = AsyncMock()
    ack = AsyncMock()
    monkeypatch.setattr(sync_worker, "defer_activity_details", defer)
    monkeypatch.setattr(sync_worker, "requeue_job", requeue)
    monkeypatch.setattr(sync_worker, "_run_job", work)
    monkeypatch.setattr(sync_worker, "ack_job", ack)
    monkeypatch.setattr(sync_worker.asyncio, "sleep", sleep)
    job = {"id": "blocked", "type": queue.JOB_ACTIVITY_DETAILS, "user_id": "a",
           "activity_id": "123", "attempts": 1}
    before = time.time()
    asyncio.run(sync_worker.process_job(None, client, "raw", job))
    defer.assert_awaited_once_with("raw", job)
    assert job["not_before"] >= before + sync_worker.WATCHDOG_INTERVAL
    assert job["attempts"] == 1
    requeue.assert_not_awaited()
    sleep.assert_not_awaited()
    work.assert_not_awaited()
    ack.assert_not_awaited()
    if blocked == "user_lock":
        acquire.assert_not_awaited()
        client.delete.assert_not_awaited()
    else:
        client.delete.assert_awaited_once_with(f"{queue.LOCK_PREFIX}a")


@pytest.mark.parametrize("transition", ["defer", "ack"])
def test_worker_redis_error_keeps_inflight_for_recovery(local_redis, monkeypatch, transition):
    from workers import sync_worker

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot",
                                AsyncMock(return_value=True))
            monkeypatch.setattr(sync_worker.rate_limiter, "release_global_slot", AsyncMock())
            result = {"success": True, "status": "cached"}
            if transition == "defer":
                result = {"status": "deferred",
                          "retry_at": "2099-01-01T00:00:00+00:00"}
            work = AsyncMock(return_value=result)
            monkeypatch.setattr(sync_worker, "_run_job", work)
            failing = "defer_activity_details" if transition == "defer" else "ack_job"
            monkeypatch.setattr(sync_worker, failing,
                                AsyncMock(side_effect=redis.ConnectionError("synthetic outage")))
            with pytest.raises(redis.ConnectionError):
                await sync_worker.process_job(None, client, raw, job)
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await client.zcard(queue.DELAYED_KEY) == 0
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert job["attempts"] == 1
            assert await client.get(f"{queue.LOCK_PREFIX}a") is None
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
            assert await queue.recover_orphans() == 1
            recovered_raw, recovered_job = await queue.claim_job(timeout=1)
            assert recovered_job["id"] == job["id"]
            # Redelivery consults the Mongo cache through the unchanged service.
            monkeypatch.setattr(sync_worker, "ack_job", queue.ack_job)
            work.return_value = {"success": True, "status": "cached"}
            await sync_worker.process_job(None, client, recovered_raw, recovered_job)
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")) is None
    asyncio.run(scenario())


def test_claim_stamp_outage_keeps_job_until_watchdog_adoption(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            job = {"id": "unstamped", "type": queue.JOB_ACTIVITY_DETAILS,
                   "user_id": "a", "activity_id": "123"}
            await client.lpush(queue.QUEUE_KEY, json.dumps(job))
            monkeypatch.setattr(client, "hset",
                                AsyncMock(side_effect=redis.ConnectionError("synthetic outage")))
            with pytest.raises(redis.ConnectionError):
                await queue.claim_job(timeout=1)
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await client.hlen(queue.CLAIMS_KEY) == 0
            assert await queue.recover_orphans() == 0
            assert await client.hlen(queue.CLAIMS_KEY) == 1
            now = time.time()
            monkeypatch.setattr(queue.time, "time", lambda: now + queue.ORPHAN_TIMEOUT + 1)
            assert await queue.recover_orphans() == 1
            assert await client.llen(queue.QUEUE_KEY) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", ["user_lock", "global_cap"])
def test_details_backpressure_stays_outside_fifo(local_redis, monkeypatch, blocked):
    from workers import sync_worker

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            if blocked == "user_lock":
                await client.set(f"{queue.LOCK_PREFIX}a", "existing-sync", ex=queue.LOCK_TTL)
            monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot",
                                AsyncMock(return_value=False))
            await sync_worker.process_job(None, client, raw, job)
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.zcard(queue.DELAYED_KEY) == 1
            assert await client.hlen(queue.CLAIMS_KEY) == 0
            for _ in range(3):
                assert await queue.promote_due_activity_details() == 0
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")) == job["id"]
            if blocked == "user_lock":
                assert await client.get(f"{queue.LOCK_PREFIX}a") == "existing-sync"
    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", ["user_lock", "global_cap"])
def test_other_garmin_jobs_keep_existing_backpressure(monkeypatch, blocked):
    from workers import sync_worker

    client = AsyncMock()
    client.set.return_value = blocked != "user_lock"
    monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot",
                        AsyncMock(return_value=False))
    defer = AsyncMock()
    requeue = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr(sync_worker, "defer_activity_details", defer)
    monkeypatch.setattr(sync_worker, "requeue_job", requeue)
    monkeypatch.setattr(sync_worker.asyncio, "sleep", sleep)
    job = {"id": "normal", "type": queue.JOB_SYNC_USER, "user_id": "a"}
    asyncio.run(sync_worker.process_job(None, client, "raw", job))
    requeue.assert_awaited_once_with("raw", "normal")
    sleep.assert_awaited_once_with(1 if blocked == "user_lock" else 2)
    defer.assert_not_awaited()


@pytest.mark.parametrize("owner,release,expected", [
    ("c321", False, 1), (None, False, 0), ("new-job", False, 0),
    ("c321", True, 1), (None, True, 0), ("new-job", True, 0),
])
def test_strict_pending_refresh_and_release(local_redis, monkeypatch, owner, release, expected):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")
            if owner:
                await client.set(key, owner, ex=10)
            assert await queue.maintain_details_pending(client, "a", "c321", release=release) == expected
            assert await client.get(key) == (None if release and owner == "c321" else owner)
            if owner == "c321" and not release:
                assert await client.ttl(key) > 10
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid_state", ["missing_delivery", "missing_claim", "wrong_identity", "superseded"])
def test_explicit_recovery_requires_claimed_live_delivery(local_redis, monkeypatch, invalid_state):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")
            await client.delete(key)
            if invalid_state == "missing_delivery":
                await client.lrem(queue.PROCESSING_KEY, 1, raw)
            elif invalid_state == "missing_claim":
                await client.hdel(queue.CLAIMS_KEY, job["id"])
            elif invalid_state == "wrong_identity":
                job = {**job, "user_id": "b"}
            else:
                await client.hset(queue.DETAILS_OUTCOMES_KEY, job["id"], "superseded")
            assert await queue.recover_details_pending(client, raw, job) == 0
            assert await client.get(key) is None
    asyncio.run(scenario())


def test_explicit_recovery_after_ttl_expiry_is_atomic(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client)
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")
            await client.pexpire(key, 1)
            await asyncio.sleep(0.01)
            assert await queue.maintain_details_pending(client, "a", job["id"]) == 0
            assert await client.get(key) is None
            assert await queue.recover_details_pending(client, raw, job) == 1
            assert await client.get(key) == job["id"]
            await client.set(key, "new-job", ex=10)
            assert await queue.recover_details_pending(client, raw, job) == 0
            assert await client.get(key) == "new-job"
            await client.delete(key)
            assert await queue.recover_details_pending(client, raw, job) == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("new_owner", [False, True])
def test_worker_expiration_before_dispatch_uses_explicit_recovery(local_redis, monkeypatch, new_owner):
    from workers import sync_worker

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")

            async def slot():
                await client.delete(key)
                if new_owner:
                    await client.set(key, "new-job", ex=30)
                return True

            work = AsyncMock(return_value={"success": True, "status": "cached"})
            monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot", slot)
            monkeypatch.setattr(sync_worker.rate_limiter, "release_global_slot", AsyncMock())
            monkeypatch.setattr(sync_worker, "_run_job", work)
            await sync_worker.process_job(None, client, raw, job)
            assert work.await_count == (0 if new_owner else 1)
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.get(key) == ("new-job" if new_owner else None)
    asyncio.run(scenario())


def test_restart_redelivery_with_expired_pending_reclaims_live_delivery(local_redis, monkeypatch):
    async def prepare():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            await client.delete(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a"))
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
    asyncio.run(prepare())
    local_redis[1]()

    async def recover():
        async with client_for(local_redis, monkeypatch) as client:
            assert await queue.recover_orphans() == 1
            raw, job = await queue.claim_job(timeout=1)
            assert await queue.maintain_details_pending(client, "a", job["id"]) == 0
            assert await queue.recover_details_pending(client, raw, job) == 1
            await queue.ack_job(raw, job["id"])
            await queue.maintain_details_pending(client, "a", job["id"], release=True)
            assert await queue.recover_details_pending(client, raw, job) == 0
    asyncio.run(recover())


@pytest.mark.parametrize("new_owner", [False, True])
def test_expiration_during_execution_does_not_recreate_on_release(local_redis, monkeypatch, new_owner):
    from workers import sync_worker

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await in_flight(client, delay=-1)
            key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")

            async def work(*args):
                await client.pexpire(key, 1)
                await asyncio.sleep(0.01)
                assert await client.get(key) is None
                if new_owner:
                    await client.set(key, "new-job", ex=30)
                return {"success": True}

            monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot",
                                AsyncMock(return_value=True))
            monkeypatch.setattr(sync_worker.rate_limiter, "release_global_slot", AsyncMock())
            invocation = AsyncMock(side_effect=work)
            monkeypatch.setattr(sync_worker, "_run_job", invocation)
            await sync_worker.process_job(None, client, raw, job)
            invocation.assert_awaited_once()
            assert await client.get(key) == ("new-job" if new_owner else None)
            assert await client.llen(queue.PROCESSING_KEY) == 0
    asyncio.run(scenario())
