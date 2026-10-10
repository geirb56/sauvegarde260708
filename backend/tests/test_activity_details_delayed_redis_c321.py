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
