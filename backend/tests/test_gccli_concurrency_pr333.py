"""PR333 owner leases and physical fencing, with isolated Redis and no Garmin."""

import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import redis

from garmin.runner import GccliError, GccliRunner
from jobs import queue
from sync import execution_lease, rate_limiter
from workers import sync_worker
from test_activity_details_delayed_redis_c321 import client_for, local_redis


@asynccontextmanager
async def isolated(local_redis, monkeypatch):
    async with client_for(local_redis, monkeypatch) as client:
        monkeypatch.setenv("REDIS_URL", local_redis[0])
        monkeypatch.setattr(rate_limiter, "get_redis", lambda: client)
        monkeypatch.setattr(sync_worker, "update_sync_progress", AsyncMock())
        yield client


async def reserve(client, user="a", token="owner"):
    assert await queue.acquire_user_lock(client, user, token)
    assert await rate_limiter.acquire_global_slot(token) == token
    return execution_lease.ExecutionLease(user, token)


async def expire_global(client, token):
    seconds, micros = await client.time()
    await client.zadd(rate_limiter.GLOBAL_LEASE_KEY, {token: seconds + micros / 1e6 - 1})


def test_owner_acquisition_release_and_redis_time(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 2)
            before = await client.time()
            first = await rate_limiter.acquire_global_slot()
            second = await rate_limiter.acquire_global_slot()
            assert first and second and first != second
            score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, first)
            second_score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, second)
            after = await client.time()
            assert before[0] + before[1] / 1e6 + rate_limiter.GLOBAL_LEASE_SECONDS <= score
            assert score <= after[0] + after[1] / 1e6 + rate_limiter.GLOBAL_LEASE_SECONDS
            assert await rate_limiter.acquire_global_slot(first) is None
            assert await rate_limiter.acquire_global_slot("over-cap") is None
            assert await rate_limiter.global_active_count() == 2
            assert not await rate_limiter.release_global_slot("stranger")
            assert await rate_limiter.release_global_slot(first)
            assert not await rate_limiter.release_global_slot(first)
            assert await rate_limiter.acquire_global_slot("replacement") == "replacement"
            assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, second) == second_score
    asyncio.run(scenario())


def test_concurrent_cluster_acquisitions_never_exceed_cap(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 3)
            results = await asyncio.gather(*[
                rate_limiter.acquire_global_slot(f"delivery-{i}") for i in range(30)
            ])
            owners = [token for token in results if token is not None]
            assert len(owners) == len(set(owners)) == 3
            assert set(await client.zrange(rate_limiter.GLOBAL_LEASE_KEY, 0, -1)) == set(owners)
            await asyncio.gather(*[rate_limiter.release_global_slot(token) for token in owners])
            assert await rate_limiter.global_active_count() == 0
    asyncio.run(scenario())


def test_existing_scheduler_cap_contract_uses_isolated_redis(local_redis, monkeypatch):
    from test_sync_scheduler import test_global_cap as check_cap

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            await check_cap(client)
            assert await rate_limiter.global_active_count() == 0
    asyncio.run(scenario())


def test_legacy_counter_is_a_non_destructive_migration_barrier(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            await client.set(rate_limiter.GLOBAL_ACTIVE_KEY, 1)
            assert await rate_limiter.acquire_global_slot("new") is None
            assert await rate_limiter.global_active_count() == 1
            assert not await rate_limiter.release_global_slot("new")
            assert await client.get(rate_limiter.GLOBAL_ACTIVE_KEY) == "1"
            await client.set(rate_limiter.GLOBAL_ACTIVE_KEY, 0)
            assert await rate_limiter.acquire_global_slot("new") == "new"
    asyncio.run(scenario())


def test_crashed_lease_expires_and_late_cleanup_cannot_release_replacement(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 1)
            await reserve(client, token="crashed")
            await client.pexpire(f"{queue.LOCK_PREFIX}a", 1)
            await expire_global(client, "crashed")
            await asyncio.sleep(0.02)
            await reserve(client, token="replacement")
            assert not await rate_limiter.release_global_slot("crashed")
            assert not await queue.maintain_user_lock(client, "a", "crashed", release=True)
            assert not await queue.maintain_user_lock(client, "a", "crashed")
            assert await client.get(f"{queue.LOCK_PREFIX}a") == "replacement"
            assert await rate_limiter.global_active_count() == 1
    asyncio.run(scenario())


def test_user_owner_refresh_release_and_user_isolation(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            assert await queue.acquire_user_lock(client, "a", "first")
            assert not await queue.acquire_user_lock(client, "a", "redelivery")
            assert await queue.acquire_user_lock(client, "b", "other")
            await client.pexpire(f"{queue.LOCK_PREFIX}a", 500)
            assert await queue.maintain_user_lock(client, "a", "first")
            assert await client.ttl(f"{queue.LOCK_PREFIX}a") > 1
            assert not await queue.maintain_user_lock(client, "a", "redelivery", release=True)
            assert await queue.maintain_user_lock(client, "a", "first", release=True)
            assert await client.get(f"{queue.LOCK_PREFIX}b") == "other"
    asyncio.run(scenario())


@pytest.mark.parametrize("loss", [None, "user", "global", "expired"])
def test_renewal_is_atomic_and_never_resurrects_lost_owner(local_redis, monkeypatch, loss):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            await reserve(client)
            await client.pexpire(f"{queue.LOCK_PREFIX}a", 2000)
            seconds, micros = await client.time()
            await client.zadd(rate_limiter.GLOBAL_LEASE_KEY, {"owner": seconds + micros / 1e6 + 2})
            if loss == "user":
                await client.set(f"{queue.LOCK_PREFIX}a", "new-owner", ex=20)
            elif loss == "global":
                await client.zrem(rate_limiter.GLOBAL_LEASE_KEY, "owner")
            elif loss == "expired":
                await expire_global(client, "owner")
            score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "owner")
            ttl = await client.pttl(f"{queue.LOCK_PREFIX}a")
            assert await rate_limiter.renew_execution_leases(client, "a", "owner") is (loss is None)
            if loss:
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "owner") == score
                assert await client.pttl(f"{queue.LOCK_PREFIX}a") <= ttl
            else:
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "owner") > score
                assert await client.ttl(f"{queue.LOCK_PREFIX}a") >= queue.LOCK_TTL - 1
    asyncio.run(scenario())


def test_temporary_redis_failure_does_not_grant_or_mutate_ownership(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            await reserve(client)
            original = client.eval
            with monkeypatch.context() as outage:
                outage.setattr(client, "eval", AsyncMock(side_effect=redis.ConnectionError("outage")))
                with pytest.raises(redis.ConnectionError):
                    await rate_limiter.acquire_global_slot("unconfirmed")
                with pytest.raises(redis.ConnectionError):
                    await rate_limiter.renew_execution_leases(client, "a", "owner")
            assert client.eval == original
            assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "unconfirmed") is None
            assert await rate_limiter.renew_execution_leases(client, "a", "owner")
    asyncio.run(scenario())


@pytest.mark.parametrize("loss", ["user", "redis"])
def test_periodic_worker_renews_then_stops_on_lost_ownership(local_redis, monkeypatch, loss):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            monkeypatch.setattr(sync_worker, "LOCK_TTL", 1)
            await client.pexpire(f"{queue.LOCK_PREFIX}a", 1000)
            renewed = asyncio.Event()
            original_renew = rate_limiter.renew_execution_leases

            async def observed_renew(*args):
                result = await original_renew(*args)
                renewed.set()
                return result

            monkeypatch.setattr(rate_limiter, "renew_execution_leases", observed_renew)
            renewal = asyncio.create_task(sync_worker._renew_execution(client, lease))
            try:
                await asyncio.wait_for(renewed.wait(), 2)
                assert await client.ttl(f"{queue.LOCK_PREFIX}a") >= queue.LOCK_TTL - 1
                assert not lease.stopped.is_set()
                if loss == "user":
                    await client.set(f"{queue.LOCK_PREFIX}a", "replacement", ex=10)
                else:
                    monkeypatch.setattr(rate_limiter, "renew_execution_leases",
                                        AsyncMock(side_effect=redis.ConnectionError("outage")))
                await asyncio.wait_for(renewal, 2)
                assert lease.stopped.is_set()
                if loss == "user":
                    assert await client.get(f"{queue.LOCK_PREFIX}a") == "replacement"
            finally:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
                lease.close()
    asyncio.run(scenario())


def test_redis_outage_fences_same_execution_even_after_recovery(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            lease._redis = redis.Redis.from_url(local_redis[0])
            try:
                with monkeypatch.context() as outage:
                    outage.setattr(lease._redis, "eval",
                                   lambda *a: (_ for _ in ()).throw(redis.ConnectionError("outage")))
                    with pytest.raises(redis.ConnectionError):
                        lease.command([sys.executable, "-c", "print('blocked')"], 0.2)
                assert lease.stopped.is_set()
                assert await rate_limiter.renew_execution_leases(client, "a", "owner")
                with pytest.raises(execution_lease.LeaseLostError):
                    lease.command([sys.executable, "-c", "print('still blocked')"], 0.2)
            finally:
                lease.close()
    asyncio.run(scenario())


def test_command_refuses_deadline_outside_safe_lease_window(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            try:
                with pytest.raises(execution_lease.LeaseLostError):
                    lease.command([sys.executable, "-c", "print('blocked')"],
                                  min(queue.LOCK_TTL, rate_limiter.GLOBAL_LEASE_SECONDS))
            finally:
                lease.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("hazard", ["slow-check", "stop-during-check"])
def test_command_rechecks_stop_and_remaining_window_after_redis(local_redis, monkeypatch, hazard):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            lease._redis = redis.Redis.from_url(local_redis[0])
            try:
                if hazard == "slow-check":
                    clock = iter([0, queue.LOCK_TTL])
                    monkeypatch.setattr(execution_lease, "time",
                                        SimpleNamespace(monotonic=lambda: next(clock)))
                else:
                    original_eval = lease._redis.eval

                    def stop_during_check(*args):
                        result = original_eval(*args)
                        lease.stop()
                        return result

                    monkeypatch.setattr(lease._redis, "eval", stop_during_check)
                with pytest.raises(execution_lease.LeaseLostError):
                    lease.command([sys.executable, "-c", "print('blocked')"], 0.2)
                assert lease.stopped.is_set()
            finally:
                lease.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("loss", ["expired", "global", "user", "stopped", "redis", "guardian"])
def test_old_holder_never_launches_another_command(local_redis, monkeypatch, tmp_path, loss):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            marker = tmp_path / "must-not-exist"
            try:
                if loss == "expired":
                    await expire_global(client, "owner")
                elif loss == "global":
                    await client.zrem(rate_limiter.GLOBAL_LEASE_KEY, "owner")
                elif loss == "user":
                    await client.set(f"{queue.LOCK_PREFIX}a", "replacement", ex=30)
                elif loss == "stopped":
                    lease.stop()
                elif loss == "redis":
                    lease._redis = redis.Redis.from_url(local_redis[0])
                    monkeypatch.setattr(lease._redis, "eval", lambda *a: (_ for _ in ()).throw(
                        redis.ConnectionError("outage"),
                    ))
                else:
                    monkeypatch.setattr(execution_lease.shutil, "which", lambda name: None)
                with pytest.raises(redis.RedisError):
                    command = lease.command(
                        [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"], 0.2,
                    )
                    subprocess.run(command, check=True, timeout=2)
                assert not marker.exists()
            finally:
                lease.close()
    asyncio.run(scenario())


def test_command_checks_and_renews_both_owners_every_time(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            try:
                for _ in range(2):
                    await client.pexpire(f"{queue.LOCK_PREFIX}a", 1000)
                    command = lease.command([sys.executable, "-c", "print('ok')"], 0.2)
                    assert command[1:3] == ["--signal=KILL", "--kill-after=5"]
                    assert await client.ttl(f"{queue.LOCK_PREFIX}a") > 1
                await client.set(f"{queue.LOCK_PREFIX}a", "replacement")
                with pytest.raises(execution_lease.LeaseLostError):
                    lease.command([sys.executable, "-c", "print('forbidden')"], 0.2)
                assert lease.stopped.is_set()
            finally:
                lease.close()
    asyncio.run(scenario())


def test_real_runner_fences_data_and_auth_subprocesses(local_redis, monkeypatch, tmp_path):
    executable = tmp_path / "gccli-json"
    marker = tmp_path / "launches"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib\n"
        f"with pathlib.Path({str(marker)!r}).open('a') as log:\n"
        "    log.write('launch\\n')\n"
        "print(json.dumps({'synthetic': True}))\n"
    )
    executable.chmod(0o700)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            runner = GccliRunner(gccli_path=str(executable), home=str(tmp_path), max_retries=1)
            context = execution_lease.current_execution.set(lease)
            try:
                assert await asyncio.to_thread(runner._run_json, ["data"]) == {"synthetic": True}
                assert await asyncio.to_thread(runner.auth_status) == {"synthetic": True}
                assert marker.read_text().splitlines() == ["launch", "launch"]
                await expire_global(client, "owner")
                with pytest.raises(execution_lease.LeaseLostError):
                    await asyncio.to_thread(runner._run_json, ["data"])
                with pytest.raises(execution_lease.LeaseLostError):
                    await asyncio.to_thread(runner.auth_status)
                assert marker.read_text().splitlines() == ["launch", "launch"]
            finally:
                execution_lease.current_execution.reset(context)
                lease.close()
    asyncio.run(scenario())


def test_inline_runner_retry_rechecks_ownership(local_redis, monkeypatch, tmp_path):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            runner = GccliRunner(gccli_path=sys.executable, home=str(tmp_path), max_retries=3)
            calls = []

            def failed_command(cmd, **kwargs):
                calls.append(cmd)
                connection = redis.Redis.from_url(local_redis[0])
                try:
                    connection.set(f"{queue.LOCK_PREFIX}a", "replacement")
                finally:
                    connection.close()
                return subprocess.CompletedProcess(cmd, 1, b"", b"transient")

            monkeypatch.setattr("garmin.runner.subprocess.run", failed_command)
            monkeypatch.setattr("garmin.runner.time.sleep", lambda _: None)
            context = execution_lease.current_execution.set(lease)
            try:
                with pytest.raises(execution_lease.LeaseLostError):
                    runner._run_json(["fake-data"])
                assert len(calls) == 1
                assert "--signal=KILL" in calls[0]
            finally:
                execution_lease.current_execution.reset(context)
                lease.close()
    asyncio.run(scenario())


def test_worker_redelivery_tokens_are_unique_and_users_execute_concurrently(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            active = set()
            tokens = []
            entered = asyncio.Event()
            finish = asyncio.Event()

            async def work(db, job_type, user):
                lease = execution_lease.current_execution.get()
                assert lease and lease.user_id == user
                assert user not in active
                active.add(user)
                tokens.append(lease.token)
                assert await client.get(f"{queue.LOCK_PREFIX}{user}") == lease.token
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token)
                if len(active) == 2:
                    entered.set()
                await finish.wait()
                active.remove(user)
                return {"success": True}

            monkeypatch.setattr(sync_worker, "_run_job", work)
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())
            monkeypatch.setattr(sync_worker, "requeue_job", AsyncMock())
            job = {"id": "same-job", "type": queue.JOB_VO2MAX_BACKFILL, "user_id": "a"}
            first = asyncio.create_task(sync_worker.process_job(None, client, "raw-a", job))
            other = asyncio.create_task(sync_worker.process_job(None, client, "raw-b", {**job, "user_id": "b"}))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                assert await rate_limiter.global_active_count() == 2
                await sync_worker.process_job(None, client, "duplicate", job)
                assert len(tokens) == 2
                sync_worker.requeue_job.assert_awaited_once_with("duplicate", "same-job")
            finally:
                finish.set()
                await asyncio.gather(first, other)
            await sync_worker.process_job(None, client, "redelivery", job)
            assert len(tokens) == len(set(tokens)) == 3
            assert await rate_limiter.global_active_count() == 0
            assert not await client.exists(f"{queue.LOCK_PREFIX}a", f"{queue.LOCK_PREFIX}b")
    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["global-acquire", "ambiguous-global", "ambiguous-user", "global-release"])
def test_independent_cleanup_after_redis_errors(local_redis, monkeypatch, phase):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            run = AsyncMock(return_value={"success": True})
            monkeypatch.setattr(sync_worker, "_run_job", run)
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())
            original_acquire = rate_limiter.acquire_global_slot
            original_user = sync_worker.acquire_user_lock
            original_release = rate_limiter.release_global_slot
            seen = []

            async def acquire(token):
                seen.append(token)
                if phase == "ambiguous-global":
                    await original_acquire(token)
                raise redis.ConnectionError("acquire reply lost")

            async def user_acquire(connection, user, token):
                seen.append(token)
                await original_user(connection, user, token)
                raise redis.ConnectionError("user acquisition reply lost")

            async def release(token):
                seen.append(token)
                raise redis.ConnectionError("release outage")

            if phase in ("global-acquire", "ambiguous-global"):
                monkeypatch.setattr(rate_limiter, "acquire_global_slot", acquire)
            elif phase == "ambiguous-user":
                monkeypatch.setattr(sync_worker, "acquire_user_lock", user_acquire)
            else:
                monkeypatch.setattr(rate_limiter, "release_global_slot", release)
            job = {"id": "job", "type": queue.JOB_VO2MAX_BACKFILL, "user_id": "a"}
            if phase == "global-release":
                await sync_worker.process_job(None, client, "raw", job)
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, seen[0])
                await original_release(seen[0])
                run.assert_awaited_once()
            else:
                with pytest.raises(redis.ConnectionError):
                    await sync_worker.process_job(None, client, "raw", job)
                run.assert_not_awaited()
                sync_worker.ack_job.assert_not_awaited()
            assert not await client.exists(f"{queue.LOCK_PREFIX}a")
            assert await rate_limiter.global_active_count() == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("job_type", [queue.JOB_ACTIVITY_DETAILS, queue.JOB_ACTIVITY_LAPS])
@pytest.mark.parametrize("blocked", ["user", "global"])
def test_details_laps_backpressure_parks_without_spending_retry(local_redis, monkeypatch, job_type, blocked):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            enqueue = queue.enqueue_activity_laps if job_type == queue.JOB_ACTIVITY_LAPS else queue.enqueue_activity_details
            assert await enqueue("a", "123") == {"status": "queued"}
            raw, job = await queue.claim_job(timeout=1)
            if blocked == "user":
                assert await queue.acquire_user_lock(client, "a", "existing-owner")
            else:
                monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 1)
                assert await rate_limiter.acquire_global_slot("other-user")
            run = AsyncMock(return_value={"success": True})
            monkeypatch.setattr(sync_worker, "_run_job", run)
            await sync_worker.process_job(None, client, raw, job)
            run.assert_not_awaited()
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.zcard(queue.DELAYED_KEY) == 1
            parked = json.loads(await client.hget(queue.DELAYED_PAYLOADS_KEY, job["id"]))
            assert parked["attempts"] == 0
            assert await client.get(queue._pending_key(job_type, "a")) == job["id"]
            assert await client.get(f"{queue.LOCK_PREFIX}a") == ("existing-owner" if blocked == "user" else None)
            if blocked == "user":
                await queue.maintain_user_lock(client, "a", "existing-owner", release=True)
            else:
                await rate_limiter.release_global_slot("other-user")
            parked["not_before"] = 0
            await client.hset(queue.DELAYED_PAYLOADS_KEY, job["id"], json.dumps(parked))
            await client.zadd(queue.DELAYED_KEY, {job["id"]: 0})
            assert await queue.promote_due_activity_details() == 1
            raw, job = await queue.claim_job(timeout=1)
            await sync_worker.process_job(None, client, raw, job)
            run.assert_awaited_once_with(None, job_type, "a", "123")
            assert await client.llen(queue.PROCESSING_KEY) == 0
            assert await client.get(queue._pending_key(job_type, "a")) is None
            assert await rate_limiter.global_active_count() == 0
    asyncio.run(scenario())


def stand_in(tmp_path):
    executable = tmp_path / "gccli-stand-in.py"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
        "pathlib.Path(sys.argv[2]).write_text('escaped deadline')\n"
    )
    executable.chmod(0o700)
    return [str(executable), str(tmp_path / "started"), str(tmp_path / "escaped")]


def test_real_runner_guardian_kills_long_command_without_python_timeout(local_redis, monkeypatch, tmp_path):
    command = stand_in(tmp_path)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            runner = GccliRunner(gccli_path=command[0], home=str(tmp_path), max_retries=1)
            runner.timeout = 0.2
            original_run = subprocess.run
            invocations = []

            def without_python_timeout(cmd, **kwargs):
                invocations.append((cmd, kwargs.copy()))
                kwargs.pop("timeout")
                return original_run(cmd, **kwargs)

            monkeypatch.setattr("garmin.runner.subprocess.run", without_python_timeout)
            context = execution_lease.current_execution.set(lease)
            start = time.monotonic()
            try:
                with pytest.raises(GccliError):
                    await asyncio.to_thread(runner._run_json, command[1:])
                assert time.monotonic() - start < 3
                assert (tmp_path / "started").exists()
                assert not (tmp_path / "escaped").exists()
                assert len(invocations) == 1
                cmd, kwargs = invocations[0]
                assert cmd[1:3] == ["--signal=KILL", "--kill-after=5"]
                assert kwargs["start_new_session"] is True
                assert kwargs["timeout"] == runner.timeout + 5
            finally:
                execution_lease.current_execution.reset(context)
                lease.close()
    asyncio.run(scenario())


def test_direct_work_cancellation_still_drains_registered_runner_thread(local_redis, monkeypatch, tmp_path):
    command = stand_in(tmp_path)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            runner = GccliRunner(gccli_path=command[0], home=str(tmp_path), max_retries=1)
            runner.timeout = 0.6
            monkeypatch.setattr(sync_worker, "JOB_TIMEOUT", 10)
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())
            work_tasks = []
            leases = []

            async def work(*args):
                work_tasks.append(asyncio.current_task())
                leases.append(execution_lease.current_execution.get())
                await asyncio.to_thread(runner._run_json, command[1:])
                return {"success": True}

            monkeypatch.setattr(sync_worker, "_run_job", work)
            job = {"id": "job", "type": queue.JOB_VO2MAX_BACKFILL, "user_id": "a"}
            worker = asyncio.create_task(sync_worker.process_job(None, client, "raw", job))
            try:
                deadline = time.monotonic() + 3
                while not (tmp_path / "started").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert (tmp_path / "started").exists()
                assert not leases[0].idle.is_set()
                # Simulate asyncio.run shutdown cancelling the inner work task
                # as well as its parent, not just cancellation of the shield.
                work_tasks[0].cancel()
                worker.cancel()
                await asyncio.sleep(0.2)
                worker.cancel()
                assert not worker.done()
                assert not leases[0].idle.is_set()
                assert await client.get(f"{queue.LOCK_PREFIX}a") == leases[0].token
                assert await rate_limiter.global_active_count() == 1
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(worker, 3)
                assert leases[0].idle.is_set()
                assert not (tmp_path / "escaped").exists()
                assert not await client.exists(f"{queue.LOCK_PREFIX}a")
                assert await rate_limiter.global_active_count() == 0
                sync_worker.ack_job.assert_not_awaited()
            finally:
                if not worker.done():
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())


def test_cancellation_during_cleanup_cannot_skip_user_release(local_redis, monkeypatch):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            entered = asyncio.Event()
            finish = asyncio.Event()
            original = rate_limiter.release_global_slot

            async def blocked_release(token):
                entered.set()
                await finish.wait()
                return await original(token)

            monkeypatch.setattr(rate_limiter, "release_global_slot", blocked_release)
            monkeypatch.setattr(sync_worker, "_run_job", AsyncMock(return_value={"success": True}))
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())
            job = {"id": "job", "type": queue.JOB_VO2MAX_BACKFILL, "user_id": "a"}
            worker = asyncio.create_task(sync_worker.process_job(None, client, "raw", job))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                worker.cancel()
                await asyncio.sleep(0)
                worker.cancel()
                await asyncio.sleep(0)
                assert not worker.done()
                assert await client.exists(f"{queue.LOCK_PREFIX}a")
            finally:
                finish.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(worker, 3)
            assert not await client.exists(f"{queue.LOCK_PREFIX}a")
            assert await rate_limiter.global_active_count() == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("interrupt", ["timeout", "cancel", "repeat-cancel"])
def test_worker_drains_real_guarded_thread_before_releasing_locks(local_redis, monkeypatch, tmp_path, interrupt):
    command = stand_in(tmp_path)
    done = threading.Event()
    second_fenced = threading.Event()
    leases = []

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            monkeypatch.setattr(sync_worker, "JOB_TIMEOUT", 0.12)
            monkeypatch.setattr(sync_worker, "MAX_RETRIES", 1)
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())

            def physical_work():
                lease = execution_lease.current_execution.get()
                leases.append(lease)
                try:
                    subprocess.run(lease.command(command, 0.6), timeout=3, check=False)
                    try:
                        lease.command(command, 0.6)
                    except execution_lease.LeaseLostError:
                        second_fenced.set()
                    return {"success": True}
                finally:
                    done.set()

            async def work(*args):
                return await asyncio.to_thread(physical_work)

            monkeypatch.setattr(sync_worker, "_run_job", work)
            job = {"id": "job", "type": queue.JOB_VO2MAX_BACKFILL, "user_id": "a"}
            worker = asyncio.create_task(sync_worker.process_job(None, client, "raw", job))
            try:
                deadline = time.monotonic() + 3
                while not (tmp_path / "started").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert (tmp_path / "started").exists()
                if interrupt != "timeout":
                    worker.cancel()
                await asyncio.sleep(0.2)
                if interrupt == "repeat-cancel":
                    worker.cancel()
                assert not worker.done()
                assert not done.is_set()
                assert await client.get(f"{queue.LOCK_PREFIX}a") == leases[0].token
                assert await rate_limiter.global_active_count() == 1
                if interrupt == "timeout":
                    await asyncio.wait_for(worker, 3)
                else:
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(worker, 3)
                assert done.is_set() and second_fenced.is_set()
                assert leases[0].stopped.is_set()
                assert not (tmp_path / "escaped").exists()
                assert not await client.exists(f"{queue.LOCK_PREFIX}a")
                assert await rate_limiter.global_active_count() == 0
                if interrupt != "timeout":
                    sync_worker.ack_job.assert_not_awaited()
            finally:
                if not worker.done():
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())


def _crashing_worker(url, command, pipe):
    os.environ["REDIS_URL"] = url
    lease = execution_lease.ExecutionLease("a", "crashed")
    child = subprocess.Popen(lease.command(command, 0.5), start_new_session=True)
    pipe.send(child.pid)
    pipe.close()
    time.sleep(30)


def test_sigkill_worker_cannot_leave_unbounded_gccli_child(local_redis, monkeypatch, tmp_path):
    command = stand_in(tmp_path)
    async def setup():
        async with isolated(local_redis, monkeypatch) as client:
            await reserve(client, token="crashed")
    asyncio.run(setup())
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_crashing_worker, args=(local_redis[0], command, sender))
    guardian_pid = None
    try:
        worker.start()
        sender.close()
        assert receiver.poll(5), "worker did not launch its guardian"
        guardian_pid = receiver.recv()
        deadline = time.monotonic() + 3
        while not (tmp_path / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert (tmp_path / "started").exists()
        child_pid = int((tmp_path / "started").read_text())
        os.kill(worker.pid, signal.SIGKILL)
        worker.join(3)
        assert worker.exitcode == -signal.SIGKILL
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = Path(f"/proc/{child_pid}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("physical GCCLI child survived its independent deadline")
        assert not (tmp_path / "escaped").exists()

        async def reclaim():
            async with isolated(local_redis, monkeypatch) as client:
                await expire_global(client, "crashed")
                await client.pexpire(f"{queue.LOCK_PREFIX}a", 1)
                await asyncio.sleep(0.02)
                await reserve(client, token="replacement")
                assert not await queue.maintain_user_lock(client, "a", "crashed", release=True)
                assert not await rate_limiter.release_global_slot("crashed")
                assert await client.get(f"{queue.LOCK_PREFIX}a") == "replacement"
        asyncio.run(reclaim())
    finally:
        receiver.close()
        if worker.is_alive():
            worker.kill()
            worker.join(3)
        if guardian_pid is not None:
            try:
                os.killpg(guardian_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
