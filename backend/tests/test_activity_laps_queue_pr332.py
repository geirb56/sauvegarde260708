"""PR332 queue/worker contracts, isolated local Redis and mocked Garmin/Mongo."""

import asyncio
import json
import time
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import redis

from jobs import queue
from workers import sync_worker
from test_activity_details_delayed_redis_c321 import client_for, local_redis


async def claimed_laps(client, user_id="a"):
    assert await queue.enqueue_activity_laps(user_id, "123") == {"status": "queued"}
    return await queue.claim_job(timeout=1)


def mock_slots(monkeypatch):
    acquire = AsyncMock(return_value=True)
    release = AsyncMock()
    monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot", acquire)
    monkeypatch.setattr(sync_worker.rate_limiter, "release_global_slot", release)
    monkeypatch.setattr(sync_worker.rate_limiter, "set_cooldown", AsyncMock())
    monkeypatch.setattr(sync_worker, "update_sync_progress", AsyncMock())
    return acquire, release


def test_repeated_enqueue_is_per_user_and_type(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            results = await asyncio.gather(*[
                queue.enqueue_activity_laps("a", "123") for _ in range(10)
            ])
            assert results.count({"status": "queued"}) == 1
            assert results.count({"status": "already_queued"}) + results.count({"status": "busy"}) == 9
            assert await queue.enqueue_activity_laps("a", "123") == {"status": "already_queued"}
            assert await queue.enqueue_activity_laps("a", "456") == {"status": "busy"}
            assert await queue.enqueue_activity_details("a", "123") == {"status": "queued"}
            assert await queue.enqueue_activity_laps("b", "123") == {"status": "queued"}
            assert await client.llen(queue.QUEUE_KEY) == 3
            laps_owner = await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a"))
            details_owner = await client.get(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a"))
            assert laps_owner and details_owner and laps_owner != details_owner
            assert not queue._should_update_sync_progress(queue.JOB_ACTIVITY_LAPS)
    asyncio.run(scenario())


@pytest.mark.parametrize("location", ["queue", "processing", "delayed", "unknown"])
def test_post_dedup_confirms_pending_target_in_all_delivery_states(local_redis, monkeypatch, location):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            if location == "unknown":
                await client.set(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a"), "unknown-job")
            else:
                assert await queue.enqueue_activity_laps("a", "123") == {"status": "queued"}
                if location != "queue":
                    raw, job = await queue.claim_job(timeout=1)
                    if location == "delayed":
                        job["not_before"] = time.time() + 900
                        await queue.defer_activity_details(raw, job)
            assert await queue.enqueue_activity_laps("a", "123") == {
                "status": "busy" if location == "unknown" else "already_queued",
            }
            assert await queue.enqueue_activity_laps("a", "456") == {"status": "busy"}
            assert await client.llen(queue.QUEUE_KEY) == (1 if location == "queue" else 0)
            assert await client.llen(queue.PROCESSING_KEY) == (1 if location == "processing" else 0)
            assert await client.zcard(queue.DELAYED_KEY) == (1 if location == "delayed" else 0)
    asyncio.run(scenario())


@pytest.mark.parametrize("location", ["queue", "processing", "delayed", "unknown"])
def test_core_post_mongo_state_matches_real_redis_reservation(local_redis, monkeypatch, location):
    from garmin import activity_laps
    from test_activity_details_pr321 import Collection

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            db = SimpleNamespace(garmin_activities=Collection([
                {"user_id": "a", "external_id": "123", "source": "garmin",
                 "activity_laps_fetch": {"status": "queued", "next_attempt_at": "2000-01-01T00:00:00+00:00"}},
                {"user_id": "a", "external_id": "456", "source": "garmin"},
            ]))
            if location == "unknown":
                await client.set(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a"), "unknown-owner")
            else:
                assert await queue.enqueue_activity_laps("a", "123") == {"status": "queued"}
                if location != "queue":
                    raw, job = await queue.claim_job(timeout=1)
                    if location == "delayed":
                        job["not_before"] = time.time() + 900
                        await queue.defer_activity_details(raw, job)
            same = await activity_laps.request_activity_laps(db, "a", "garmin-00123")
            same_state = db.garmin_activities.docs[0]["activity_laps_fetch"]
            if location == "unknown":
                assert same == {"status": "busy"}
                assert same_state["status"] == "failed"
                assert same_state["error_code"] == "queue_busy"
            else:
                assert same == {"status": "already_queued"}
                assert same_state["status"] == "queued"
                assert same_state["token"]
            other = await activity_laps.request_activity_laps(db, "a", "garmin-456")
            assert other == {"status": "busy"}
            other_state = db.garmin_activities.docs[1]["activity_laps_fetch"]
            assert other_state["status"] == "failed"
            assert other_state["error_code"] == "queue_busy"
            assert await client.llen(queue.QUEUE_KEY) == (1 if location == "queue" else 0)
            assert await client.llen(queue.PROCESSING_KEY) == (1 if location == "processing" else 0)
            assert await client.zcard(queue.DELAYED_KEY) == (1 if location == "delayed" else 0)
    asyncio.run(scenario())


def test_core_post_first_repeated_busy_and_expired_same_target(local_redis, monkeypatch):
    from garmin import activity_laps
    from test_activity_details_pr321 import Collection

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            db = SimpleNamespace(garmin_activities=Collection([
                {"user_id": "a", "external_id": "123", "source": "garmin"},
                {"user_id": "a", "external_id": "456", "source": "garmin"},
            ]))
            assert await activity_laps.request_activity_laps(db, "a", "garmin-123") == {"status": "queued"}
            state = db.garmin_activities.docs[0]["activity_laps_fetch"]
            token = state["token"]
            assert state["status"] == "queued"
            assert await activity_laps.request_activity_laps(db, "a", "123") == {"status": "queued"}
            assert db.garmin_activities.docs[0]["activity_laps_fetch"]["token"] == token
            assert await activity_laps.request_activity_laps(db, "a", "456") == {"status": "busy"}
            other = db.garmin_activities.docs[1]["activity_laps_fetch"]
            assert other["status"] == "failed"
            assert other["error_code"] == "queue_busy"
            state["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
            assert await activity_laps.request_activity_laps(db, "a", "garmin-00123") == {
                "status": "already_queued",
            }
            refreshed = db.garmin_activities.docs[0]["activity_laps_fetch"]
            assert refreshed["status"] == "queued"
            assert refreshed["token"] != token
            assert await client.llen(queue.QUEUE_KEY) == 1
            payload = json.loads(await client.lindex(queue.QUEUE_KEY, 0))
            assert payload["activity_id"] == "123"
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")) == payload["id"]
    asyncio.run(scenario())


def test_mongo_reservation_crash_before_enqueue_recovers_after_expiry(local_redis, monkeypatch):
    from garmin import activity_laps
    from test_activity_details_pr321 import Collection

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            db = SimpleNamespace(garmin_activities=Collection([
                {"user_id": "a", "external_id": "123", "source": "garmin"},
            ]))
            enqueue = queue.enqueue_activity_laps
            monkeypatch.setattr(queue, "enqueue_activity_laps", AsyncMock(
                side_effect=asyncio.CancelledError,
            ))
            with pytest.raises(asyncio.CancelledError):
                await activity_laps.request_activity_laps(db, "a", "123")
            state = db.garmin_activities.docs[0]["activity_laps_fetch"]
            old_token = state["token"]
            assert state["status"] == "queued"
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert await activity_laps.request_activity_laps(db, "a", "123") == {"status": "queued"}
            state["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
            assert (await activity_laps.get_activity_laps(db, "a", "123"))["error_code"] == "lease_expired"
            monkeypatch.setattr(queue, "enqueue_activity_laps", enqueue)
            assert await activity_laps.request_activity_laps(db, "a", "123") == {"status": "queued"}
            assert db.garmin_activities.docs[0]["activity_laps_fetch"]["token"] != old_token
            assert await client.llen(queue.QUEUE_KEY) == 1
    asyncio.run(scenario())


def test_interruption_cannot_leave_redis_pending_without_delivery(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            monkeypatch.setattr(client, "lpush", AsyncMock(side_effect=asyncio.CancelledError))
            try:
                await queue.enqueue_activity_laps("a", "123")
            except asyncio.CancelledError:
                pass
            owner = await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a"))
            if owner is not None:
                deliveries = await client.lrange(queue.QUEUE_KEY, 0, -1)
                assert any(json.loads(raw)["id"] == owner for raw in deliveries)
    asyncio.run(scenario())


def test_laps_enqueue_wrong_type_does_not_create_reservation(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            await client.set(queue.QUEUE_KEY, "wrong-type")
            with pytest.raises(redis.ResponseError):
                await queue.enqueue_activity_laps("a", "123")
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")) is None
            assert await client.get(queue.QUEUE_KEY) == "wrong-type"
    asyncio.run(scenario())


def test_worker_restart_and_duplicate_delivery_use_persisted_cache(local_redis, monkeypatch):
    from garmin import activity_laps
    from test_activity_details_pr321 import Collection

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            db = SimpleNamespace(
                garmin_activities=Collection([
                    {"user_id": "a", "external_id": "123", "source": "garmin",
                     "activity_day": "local-day", "activity_details": {"phases": []}},
                ]),
                garmin_connections=Collection([
                    {"user_id": "a", "connected": True, "garmin_username": "synthetic-a"},
                ]),
            )
            provider = Mock()
            provider.get_activity_laps.return_value = [{"distance_m": 400}]
            monkeypatch.setattr(activity_laps, "get_provider_for_user", Mock(return_value=provider))
            mock_slots(monkeypatch)
            raw, job = await claimed_laps(client)
            # A claimed worker disappears; the reliable record outlives that worker.
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
            assert await queue.recover_orphans() == 1
            raw, recovered = await queue.claim_job(timeout=1)
            await sync_worker.process_job(db, client, raw, recovered)
            await client.lpush(queue.QUEUE_KEY, raw)
            raw, duplicate = await queue.claim_job(timeout=1)
            await sync_worker.process_job(db, client, raw, duplicate)
            provider.get_activity_laps.assert_called_once_with("a", "123")
            doc = db.garmin_activities.docs[0]
            assert doc["activity_day"] == "local-day"
            assert doc["activity_details"] == {"phases": []}
            assert await activity_laps.request_activity_laps(db, "a", "123") == {"status": "cached"}
            assert (await activity_laps.get_activity_laps(db, "a", "123"))["cache_current"]
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert await client.llen(queue.PROCESSING_KEY) == 0
    asyncio.run(scenario())


def test_expired_running_post_does_not_lose_the_reserved_delivery(local_redis, monkeypatch):
    from garmin import activity_laps
    from test_activity_details_pr321 import Collection

    entered, release = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test release timeout")
        return [{"distance_m": 400}]

    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            db = SimpleNamespace(
                garmin_activities=Collection([
                    {"user_id": "a", "external_id": "123", "source": "garmin"},
                ]),
                garmin_connections=Collection([
                    {"user_id": "a", "connected": True, "garmin_username": "synthetic-a"},
                ]),
            )
            provider = Mock()
            provider.get_activity_laps.side_effect = blocked
            monkeypatch.setattr(activity_laps, "get_provider_for_user", Mock(return_value=provider))
            mock_slots(monkeypatch)
            assert await activity_laps.request_activity_laps(db, "a", "123") == {"status": "queued"}
            raw, job = await queue.claim_job(timeout=1)
            worker = asyncio.create_task(sync_worker.process_job(db, client, raw, job))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                state = db.garmin_activities.docs[0]["activity_laps_fetch"]
                state["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
                assert await activity_laps.request_activity_laps(db, "a", "123") == {
                    "status": "already_queued",
                }
            finally:
                release.set()
                await worker
            # The old thread must not write, but its delivery must survive for recovery.
            assert "activity_laps" not in db.garmin_activities.docs[0]
            assert await client.zcard(queue.DELAYED_KEY) == 1
            assert await queue.promote_due_activity_details() == 1
            raw, recovered = await queue.claim_job(timeout=1)
            assert recovered["id"] == job["id"]
            assert recovered["attempts"] == 0
            provider.get_activity_laps.side_effect = None
            provider.get_activity_laps.return_value = [{"distance_m": 800}]
            await sync_worker.process_job(db, client, raw, recovered)
            assert db.garmin_activities.docs[0]["activity_laps"]["laps"] == [{"distance_m": 800}]
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")) is None
    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [
    "invalid JSON",
    json.dumps({"id": "owner", "type": queue.JOB_ACTIVITY_DETAILS,
                "user_id": "a", "activity_id": "123"}),
    json.dumps({"id": "owner", "type": queue.JOB_ACTIVITY_LAPS,
                "user_id": "other", "activity_id": "123"}),
])
def test_pending_lookup_fails_closed_for_unknown_delivery(local_redis, monkeypatch, payload):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            key = queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")
            await client.set(key, "owner")
            await client.lpush(queue.QUEUE_KEY, payload)
            assert await queue.enqueue_activity_laps("a", "123") == {"status": "busy"}
            assert await client.get(key) == "owner"
            assert await client.llen(queue.QUEUE_KEY) == 1
    asyncio.run(scenario())


def test_enqueue_failure_releases_only_its_reservation(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            key = queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")

            async def fail(*args):
                await client.set(key, "new-owner")
                raise redis.ConnectionError("synthetic outage")

            monkeypatch.setattr(client, "eval", fail)
            with pytest.raises(redis.ConnectionError):
                await queue.enqueue_activity_laps("a", "123")
            assert await client.get(key) == "new-owner"
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [None, "", "--help", "../123", True, "0", "garmin-0"])
def test_invalid_target_never_enqueues(monkeypatch, invalid):
    client = AsyncMock()
    monkeypatch.setattr(queue, "get_redis", lambda: client)
    with pytest.raises(ValueError):
        asyncio.run(queue.enqueue_activity_laps("a", invalid))
    client.set.assert_not_awaited()


def test_laps_enqueue_normalizes_prefixed_target_and_dedup(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            assert await queue.enqueue_activity_laps("a", "garmin-00123") == {"status": "queued"}
            assert json.loads(await client.lindex(queue.QUEUE_KEY, 0))["activity_id"] == "123"
            assert await queue.enqueue_activity_laps("a", "000123") == {"status": "already_queued"}
            assert await queue.enqueue_activity_laps("a", "garmin-456") == {"status": "busy"}
    asyncio.run(scenario())


def test_laps_dispatch_is_targeted(monkeypatch):
    from garmin import activity_laps

    fetch = AsyncMock(return_value={"success": True, "status": "cached"})
    monkeypatch.setattr(activity_laps, "fetch_activity_laps", fetch)
    db = object()
    assert asyncio.run(sync_worker._run_job(db, queue.JOB_ACTIVITY_LAPS, "a", "123"))["success"]
    fetch.assert_awaited_once_with(db, "a", "123")


def test_worker_deferred_retry_promotes_and_acks(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            acquire, release = mock_slots(monkeypatch)
            due = time.time() + 900
            work = AsyncMock(return_value={
                "status": "deferred", "success": False,
                "retry_at": datetime.fromtimestamp(due, timezone.utc).isoformat(),
            })
            monkeypatch.setattr(sync_worker, "_run_job", work)
            await sync_worker.process_job(None, client, raw, job)
            assert job["attempts"] == 0
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.hlen(queue.CLAIMS_KEY) == 0
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert await client.zscore(queue.DELAYED_KEY, job["id"]) == pytest.approx(due, rel=0, abs=1e-6)
            key = queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")
            assert await client.ttl(key) >= 2698
            assert await queue.promote_due_activity_details() == 0
            monkeypatch.setattr(queue.time, "time", lambda: due + 1)
            counts = await asyncio.gather(
                queue.promote_due_activity_details(), queue.promote_due_activity_details(),
            )
            assert sum(counts) == 1
            raw, job = await queue.claim_job(timeout=1)
            work.return_value = {"success": True, "status": "cached"}
            await sync_worker.process_job(None, client, raw, job)
            assert await client.get(key) is None
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.hlen(queue.DELAYED_PAYLOADS_KEY) == 0
            assert acquire.await_count == release.await_count == 2
            sync_worker.rate_limiter.set_cooldown.assert_not_awaited()
            sync_worker.update_sync_progress.assert_not_awaited()
            work.assert_awaited_with(None, queue.JOB_ACTIVITY_LAPS, "a", "123")
    asyncio.run(scenario())


@pytest.mark.parametrize("blocked", ["user", "global"])
def test_laps_backpressure_shares_existing_locks(local_redis, monkeypatch, blocked):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            acquire, release = mock_slots(monkeypatch)
            acquire.return_value = False
            lock = f"{queue.LOCK_PREFIX}a"
            if blocked == "user":
                await client.set(lock, "existing-sync", ex=queue.LOCK_TTL)
            work = AsyncMock()
            monkeypatch.setattr(sync_worker, "_run_job", work)
            await sync_worker.process_job(None, client, raw, job)
            assert await client.zcard(queue.DELAYED_KEY) == 1
            assert await client.llen(queue.QUEUE_KEY) == 0
            assert job["attempts"] == 0
            work.assert_not_awaited()
            release.assert_not_awaited()
            assert acquire.await_count == (0 if blocked == "user" else 1)
            assert await client.get(lock) == ("existing-sync" if blocked == "user" else None)
    asyncio.run(scenario())


@pytest.mark.parametrize("transition", ["defer", "ack", "cancel"])
def test_interrupted_worker_redelivery(local_redis, monkeypatch, transition):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            mock_slots(monkeypatch)
            work = AsyncMock(return_value={"success": True})
            monkeypatch.setattr(sync_worker, "_run_job", work)
            if transition == "cancel":
                work.side_effect = asyncio.CancelledError()
                error = asyncio.CancelledError
            else:
                error = redis.ConnectionError
                name = "ack_job" if transition == "ack" else "defer_activity_details"
                monkeypatch.setattr(sync_worker, name, AsyncMock(side_effect=error("outage")))
                if transition == "defer":
                    work.return_value = {"status": "deferred", "retry_at": "2099-01-01T00:00:00+00:00"}
            with pytest.raises(error):
                await sync_worker.process_job(None, client, raw, job)
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await client.get(f"{queue.LOCK_PREFIX}a") is None
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
            assert sum(await asyncio.gather(queue.recover_orphans(), queue.recover_orphans())) == 1
            raw, job = await queue.claim_job(timeout=1)
            monkeypatch.setattr(sync_worker, "ack_job", queue.ack_job)
            monkeypatch.setattr(sync_worker, "defer_activity_details", queue.defer_activity_details)
            work.side_effect = None
            work.return_value = {"success": True, "status": "cached"}
            await sync_worker.process_job(None, client, raw, job)
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.hlen(queue.CLAIMS_KEY) == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("new_owner", [False, True])
def test_stale_pending_cannot_refresh_release_or_execute(local_redis, monkeypatch, new_owner):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            key = queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")
            await client.delete(key)
            if new_owner:
                await client.set(key, "new-owner", ex=30)
            assert await queue.maintain_details_pending(
                client, "a", job["id"], job_type=queue.JOB_ACTIVITY_LAPS,
            ) == 0
            mock_slots(monkeypatch)
            work = AsyncMock(return_value={"success": True})
            monkeypatch.setattr(sync_worker, "_run_job", work)
            await sync_worker.process_job(None, client, raw, job)
            assert work.await_count == (0 if new_owner else 1)
            assert await client.get(key) == ("new-owner" if new_owner else None)
            if new_owner:
                assert await queue.recover_details_pending(client, raw, job) == 0
                await queue.maintain_details_pending(
                    client, "a", job["id"], release=True, job_type=queue.JOB_ACTIVITY_LAPS,
                )
                assert await client.get(key) == "new-owner"
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["type", "identity", "pending_type"])
def test_lua_validation_preserves_inflight_and_delayed(local_redis, monkeypatch, invalid):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            job["not_before"] = time.time() - 1
            if invalid == "pending_type":
                key = queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")
                await client.delete(key)
                await client.lpush(key, "wrong-type")
            else:
                job["type" if invalid == "type" else "activity_id"] = "invalid"
            with pytest.raises(redis.ResponseError):
                await queue.defer_activity_details(raw, job)
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await client.hlen(queue.CLAIMS_KEY) == 1
            assert await client.zcard(queue.DELAYED_KEY) == 0
    asyncio.run(scenario())


def test_promotion_checks_type_and_correct_pending_suffix(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            job["not_before"] = time.time() - 1
            await queue.defer_activity_details(raw, job)
            await client.hset(queue.DELAYED_PAYLOADS_KEY, job["id"],
                              json.dumps({**job, "type": queue.JOB_SYNC_USER}))
            with pytest.raises(redis.ResponseError):
                await queue.promote_due_activity_details()
            assert await client.zcard(queue.DELAYED_KEY) == 1
            await client.hset(queue.DELAYED_PAYLOADS_KEY, job["id"], json.dumps(job))
            await client.set(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a"), "details-owner")
            await client.set(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a"), "new-laps-owner")
            assert await queue.promote_due_activity_details() == 0
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")) == "details-owner"
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")) == "new-laps-owner"
            assert await client.hget(queue.DETAILS_OUTCOMES_KEY, job["id"]) == "superseded"
    asyncio.run(scenario())


def test_laps_delayed_storage_survives_local_redis_restart(local_redis, monkeypatch):
    async def park():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            job["not_before"] = time.time() - 1
            await queue.defer_activity_details(raw, job)
            await queue.defer_activity_details(raw, {**job, "attempts": 99})
            assert await client.zcard(queue.DELAYED_KEY) == 1
    asyncio.run(park())
    local_redis[1]()

    async def promote():
        async with client_for(local_redis, monkeypatch) as client:
            assert await queue.promote_due_activity_details() == 1
            raw, job = await queue.claim_job(timeout=1)
            assert job["type"] == queue.JOB_ACTIVITY_LAPS
            assert job["attempts"] == 0
            key = queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")
            await client.delete(key)
            assert await queue.recover_details_pending(client, raw, {**job, "type": queue.JOB_ACTIVITY_DETAILS}) == 0
            assert await queue.recover_details_pending(client, raw, job) == 1
            await queue.ack_job(raw, job["id"])
            await client.delete(key)
            assert await queue.recover_details_pending(client, raw, job) == 0
    asyncio.run(promote())


def test_laps_stale_watchdog_cannot_recover_fresh_redelivery(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            await client.hset(queue.CLAIMS_KEY, job["id"], 0)
            original_hget = client.hget

            async def redeliver(key, job_id):
                old = await original_hget(key, job_id)
                await queue.requeue_job(raw, job_id)
                await queue.claim_job(timeout=1)
                return old

            monkeypatch.setattr(client, "hget", redeliver)
            assert await queue.recover_orphans() == 0
            assert await client.llen(queue.PROCESSING_KEY) == 1
            assert await client.llen(queue.QUEUE_KEY) == 0
    asyncio.run(scenario())


def test_laps_failures_use_existing_retries_and_targeted_timeout(local_redis, monkeypatch):
    async def scenario():
        async with client_for(local_redis, monkeypatch) as client:
            raw, job = await claimed_laps(client)
            mock_slots(monkeypatch)
            monkeypatch.setattr(sync_worker, "_run_job", AsyncMock(side_effect=RuntimeError("failure")))
            sleep = AsyncMock()
            wait_for = sync_worker.asyncio.wait_for
            timeouts = []

            async def timed(work, timeout):
                timeouts.append(timeout)
                return await wait_for(work, timeout)

            monkeypatch.setattr(sync_worker, "asyncio", SimpleNamespace(sleep=sleep, wait_for=timed))
            for attempt in range(sync_worker.MAX_RETRIES):
                await sync_worker.process_job(None, client, raw, job)
                if attempt + 1 < sync_worker.MAX_RETRIES:
                    assert await client.llen(queue.QUEUE_KEY) == 1
                    raw, job = await queue.claim_job(timeout=1)
                    assert job["attempts"] == attempt + 1
            assert timeouts == [max(sync_worker.JOB_TIMEOUT, 65)] * sync_worker.MAX_RETRIES
            assert sleep.await_count == sync_worker.MAX_RETRIES - 1
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.get(queue._pending_key(queue.JOB_ACTIVITY_LAPS, "a")) is None
            assert await client.get(queue.STATS_FAILED_KEY) == "1"
    asyncio.run(scenario())
