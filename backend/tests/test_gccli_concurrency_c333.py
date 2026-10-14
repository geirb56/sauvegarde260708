"""C333 renewal correction and executable evidence of the remaining spawn gap."""

import asyncio
import json
import multiprocessing
import os
import pty
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import redis
import redis.asyncio as aioredis

from garmin.runner import GccliError, GccliRunner
from jobs import queue
from sync import execution_lease, rate_limiter
from workers import sync_worker
from test_activity_details_delayed_redis_c321 import local_redis
from test_gccli_concurrency_pr333 import isolated, reserve, expire_global, stand_in


def rapid_renewal(monkeypatch):
    # Only cadence changes: the 10-second command safety margin remains intact.
    monkeypatch.setattr(execution_lease, "RENEWAL_MAX_INTERVAL_SECONDS", 0.04)


async def expire_user(client, user):
    deadline = time.monotonic() + 0.3
    key = f"{queue.LOCK_PREFIX}{user}"
    while time.monotonic() < deadline:
        await client.pexpire(key, 1)
        await asyncio.sleep(0.005)
        if not await client.exists(key):
            return
    pytest.fail("user lock did not expire between renewal checks")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not stat.exists() or stat.read_text().split()[2] != "Z"


def test_worker_renews_tiny_original_leases_while_event_loop_is_blocked(
    local_redis, monkeypatch, tmp_path,
):
    rapid_renewal(monkeypatch)
    observations = []
    leases = []
    original_renew = execution_lease.ExecutionLease._renew_owned
    marker = tmp_path / "blocked-loop-command"
    started_marker = tmp_path / "blocked-loop-started"
    shortened_at = []
    shortener_errors = []

    def shorten_after_physical_start():
        connection = redis.Redis.from_url(local_redis[0], socket_timeout=0.5)
        try:
            deadline = time.monotonic() + 3
            while not started_marker.exists() and time.monotonic() < deadline:
                time.sleep(0.002)
            assert started_marker.exists()
            seconds, micros = connection.time()
            transaction = connection.pipeline()
            transaction.zadd(rate_limiter.GLOBAL_LEASE_KEY, {
                leases[0].token: seconds + micros / 1e6 + 0.3,
            })
            transaction.pexpire(f"{queue.LOCK_PREFIX}a", 300)
            transaction.execute()
            shortened_at.append(time.monotonic())
        except BaseException as exc:
            shortener_errors.append(exc)
        finally:
            connection.close()

    def observed(lease):
        original_renew(lease)
        observations.append((threading.get_ident(), time.monotonic()))

    monkeypatch.setattr(execution_lease.ExecutionLease, "_renew_owned", observed)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            original_acquire = rate_limiter.acquire_global_slot

            async def tiny_initial_reservations(token):
                result = await original_acquire(token)
                seconds, micros = await client.time()
                await client.zadd(rate_limiter.GLOBAL_LEASE_KEY, {
                    token: seconds + micros / 1e6 + 0.3,
                })
                await client.pexpire(f"{queue.LOCK_PREFIX}a", 300)
                return result

            runner = GccliRunner(gccli_path=sys.executable, home=str(tmp_path), max_retries=1)
            runner.timeout = 2
            event_loop_thread = threading.get_ident()
            heartbeat = []

            async def tick():
                heartbeat.append(time.monotonic())

            async def work(*args):
                lease = execution_lease.current_execution.get()
                leases.append(lease)
                started = time.monotonic()
                timer = asyncio.create_task(tick())
                # Blocking provider work, not to_thread: the old renewal task
                # could never run before the original 300ms reservations died.
                runner._run_json(["-c", (
                    "import json,pathlib,time; "
                    f"pathlib.Path({str(started_marker)!r}).write_text('started'); "
                    "time.sleep(0.9); "
                    f"pathlib.Path({str(marker)!r}).write_text('real'); "
                    "print(json.dumps({'success': True}))"
                )])
                finished = time.monotonic()
                assert not heartbeat
                assert finished - started > 0.3
                assert not shortener_errors
                assert len(shortened_at) == 1
                assert finished - shortened_at[0] > 0.3
                assert sum(
                    ident != event_loop_thread and shortened_at[0] < stamp < finished
                    for ident, stamp in observations
                ) >= 3
                assert await client.get(f"{queue.LOCK_PREFIX}a") == lease.token
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token) > time.time()
                await timer
                return {"success": True}

            monkeypatch.setattr(rate_limiter, "acquire_global_slot", tiny_initial_reservations)
            monkeypatch.setattr(sync_worker, "_run_job", work)
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())
            job = {"id": "blocked", "type": queue.JOB_VO2MAX_BACKFILL, "user_id": "a"}
            shortener = threading.Thread(target=shorten_after_physical_start)
            shortener.start()
            try:
                await sync_worker.process_job(None, client, "raw", job)
            finally:
                shortener.join(3)
            assert not shortener.is_alive()
            assert marker.read_text() == "real"
            assert not leases[0]._renewal.is_alive()
            assert await rate_limiter.global_active_count() == 0
            assert not await client.exists(f"{queue.LOCK_PREFIX}a")
            sync_worker.ack_job.assert_awaited_once_with("raw", "blocked")

    asyncio.run(scenario())


@pytest.mark.parametrize("loss", ["global-expiry", "user-expiry", "replacement"])
def test_renewal_loss_during_real_command_never_revives_or_kills_it_immediately(
    local_redis, monkeypatch, tmp_path, loss,
):
    rapid_renewal(monkeypatch)
    command = stand_in(tmp_path)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            runner = GccliRunner(gccli_path=command[0], home=str(tmp_path), max_retries=1)
            runner.timeout = 0.9
            lease.start_renewal()
            context = execution_lease.current_execution.set(lease)
            task = asyncio.create_task(asyncio.to_thread(runner._run_json, command[1:]))
            try:
                deadline = time.monotonic() + 3
                while not (tmp_path / "started").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert (tmp_path / "started").exists()
                pid = int((tmp_path / "started").read_text())
                if loss == "global-expiry":
                    await expire_global(client, lease.token)
                elif loss == "user-expiry":
                    await expire_user(client, "a")
                else:
                    await client.set(f"{queue.LOCK_PREFIX}a", "replacement", ex=30)
                score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token)
                assert await asyncio.to_thread(lease.stopped.wait, 0.5)
                assert alive(pid), "renewal loss is not an immediate physical kill"
                assert not task.done()
                with pytest.raises(execution_lease.LeaseLostError):
                    runner._run_json(command[1:])
                await asyncio.sleep(0.08)
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token) == score
                assert await client.get(f"{queue.LOCK_PREFIX}a") == (
                    "replacement" if loss == "replacement" else
                    None if loss == "user-expiry" else "owner"
                )
                with pytest.raises(GccliError):
                    await task
                assert not alive(pid)
                assert not (tmp_path / "escaped").exists()
            finally:
                execution_lease.current_execution.reset(context)
                await lease.join_renewal()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)
                lease.close()

    asyncio.run(scenario())


def test_renewal_outage_recovery_never_reopens_same_execution(local_redis, monkeypatch):
    rapid_renewal(monkeypatch)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            connection = lease._client()
            score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token)
            try:
                with monkeypatch.context() as outage:
                    outage.setattr(connection, "eval", lambda *args: (_ for _ in ()).throw(
                        redis.ConnectionError("deterministic unavailable Redis"),
                    ))
                    lease.start_renewal()
                    assert await asyncio.to_thread(lease.stopped.wait, 1)
                assert connection.ping()
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token) == score
                assert await rate_limiter.renew_execution_leases(client, "a", lease.token)
                with pytest.raises(execution_lease.LeaseLostError):
                    lease.command([sys.executable, "-c", "print('forbidden')"], 0.2)
            finally:
                await lease.join_renewal()
                lease.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("expiry", ["global", "user"])
def test_expiry_during_existing_physical_command_can_overlap_successor_without_redis_revival(
    local_redis, monkeypatch, tmp_path, expiry,
):
    """Expected overlap evidence: CAS-safe Redis does not fence active commands."""
    rapid_renewal(monkeypatch)
    old_path = tmp_path / "ongoing-old.json"
    new_path = tmp_path / "ongoing-new.json"

    def code(path, duration):
        return (
            "import json,pathlib,time; start=time.monotonic(); "
            f"pathlib.Path({str(path)!r}).write_text(json.dumps([start,None])); "
            f"time.sleep({duration}); "
            f"pathlib.Path({str(path)!r}).write_text(json.dumps([start,time.monotonic()])); "
            "print('{}')"
        )

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 1 if expiry == "global" else 2)
            old = await reserve(client, token="old")
            old.start_renewal()
            runner = GccliRunner(gccli_path=sys.executable, home=str(tmp_path), max_retries=1)
            runner.timeout = 1.5
            context = execution_lease.current_execution.set(old)
            old_task = asyncio.create_task(asyncio.to_thread(
                runner._run_json, ["-c", code(old_path, 0.9)],
            ))
            execution_lease.current_execution.reset(context)
            successor = None
            new_task = None
            try:
                deadline = time.monotonic() + 3
                while not old_path.exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert old_path.exists() and not old_task.done()
                old_score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "old")
                if expiry == "global":
                    await expire_global(client, "old")
                else:
                    await expire_user(client, "a")
                assert await asyncio.to_thread(old.stopped.wait, 0.5)
                assert not old_task.done(), "ownership loss does not stop the physical command"
                successor_user = "b" if expiry == "global" else "a"
                successor = await reserve(client, user=successor_user, token="successor")
                successor.start_renewal()
                assert await rate_limiter.global_active_count() == (1 if expiry == "global" else 2)
                assert await client.get(f"{queue.LOCK_PREFIX}{successor_user}") == "successor"
                context = execution_lease.current_execution.set(successor)
                new_task = asyncio.create_task(asyncio.to_thread(
                    runner._run_json, ["-c", code(new_path, 0.5)],
                ))
                execution_lease.current_execution.reset(context)
                assert await old_task == {}
                assert await new_task == {}
                old_start, old_end = json.loads(old_path.read_text())
                new_start, new_end = json.loads(new_path.read_text())
                assert min(old_end, new_end) > max(old_start, new_start)
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "old") == (
                    None if expiry == "global" else old_score
                )
                if expiry == "user":
                    assert not await queue.maintain_user_lock(client, "a", "old", release=True)
                    assert await client.get(f"{queue.LOCK_PREFIX}a") == "successor"
                await rate_limiter.release_global_slot("old")
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "successor") is not None
            finally:
                await asyncio.gather(old_task, *([new_task] if new_task else []), return_exceptions=True)
                for lease in [old, successor]:
                    if lease is not None:
                        lease.stop()
                        await lease.join_renewal()
                        lease.close()

    asyncio.run(scenario())


def test_start_renewal_is_idempotent_and_cannot_restart_after_join(local_redis, monkeypatch):
    rapid_renewal(monkeypatch)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            try:
                lease.start_renewal()
                first = lease._renewal
                callers = [threading.Thread(target=lease.start_renewal) for _ in range(8)]
                for caller in callers:
                    caller.start()
                for caller in callers:
                    caller.join(1)
                    assert not caller.is_alive()
                assert lease._renewal is first
                assert first.is_alive()
                lease.stop()
                await lease.join_renewal()
                lease.start_renewal()
                assert lease._renewal is first and not first.is_alive()
            finally:
                await lease.join_renewal()
                lease.close()

    asyncio.run(scenario())


def test_real_redis_socket_timeout_then_recovery_keeps_execution_stopped(
    local_redis, monkeypatch, tmp_path,
):
    rapid_renewal(monkeypatch)
    command = stand_in(tmp_path)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            connection = lease._client()
            assert connection.ping()
            runner = GccliRunner(gccli_path=command[0], home=str(tmp_path), max_retries=1)
            runner.timeout = 1.8
            lease.start_renewal()
            context = execution_lease.current_execution.set(lease)
            task = asyncio.create_task(asyncio.to_thread(runner._run_json, command[1:]))
            execution_lease.current_execution.reset(context)
            successor = None
            try:
                deadline = time.monotonic() + 3
                while not (tmp_path / "started").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert (tmp_path / "started").exists()
                pid = int((tmp_path / "started").read_text())
                # Pause isolated Redis while a real guarded child is running.
                # A timed-out CAS may still execute after server recovery.
                await client.execute_command("CLIENT", "PAUSE", 1000, "ALL")
                started = time.monotonic()
                assert await asyncio.to_thread(lease.stopped.wait, 2)
                assert time.monotonic() - started < 1.5
                assert alive(pid) and not task.done()
                await lease.join_renewal()
                assert not lease._renewal.is_alive()
                await asyncio.sleep(max(0, 1.05 - (time.monotonic() - started)))
                assert await asyncio.to_thread(connection.ping)
                assert await client.get(f"{queue.LOCK_PREFIX}a") == lease.token
                await expire_user(client, "a")
                successor = await reserve(client, token="successor")
                successor.start_renewal()
                score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token)
                with pytest.raises(execution_lease.LeaseLostError):
                    lease.command([sys.executable, "-c", "print('forbidden')"], 0.2)
                await asyncio.sleep(0.08)
                assert lease.stopped.is_set()
                assert await client.get(f"{queue.LOCK_PREFIX}a") == "successor"
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, lease.token) == score
                with pytest.raises(GccliError):
                    await task
                assert not alive(pid)
                assert not (tmp_path / "escaped").exists()
                assert not await queue.maintain_user_lock(client, "a", lease.token, release=True)
                await rate_limiter.release_global_slot(lease.token)
                assert await client.get(f"{queue.LOCK_PREFIX}a") == "successor"
                assert await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "successor") is not None
            finally:
                await lease.join_renewal()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)
                lease.close()
                if successor is not None:
                    successor.stop()
                    await successor.join_renewal()
                    successor.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["subprocess", "pty"])
def test_final_cas_rejects_replacement_after_command_construction(
    local_redis, monkeypatch, tmp_path, path,
):
    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            lease = await reserve(client)
            runner = GccliRunner(gccli_path=sys.executable, home=str(tmp_path), max_retries=1)
            runner.timeout = 0.2
            original_command = runner._execution_command
            connection = redis.Redis.from_url(local_redis[0], decode_responses=True)
            physical_calls = []

            def constructed(cmd):
                result = original_command(cmd)
                connection.set(f"{queue.LOCK_PREFIX}a", "replacement", ex=30)
                return result

            def forbidden_spawn(*args, **kwargs):
                physical_calls.append(args)
                raise AssertionError("final CAS must reject before OS launch")

            monkeypatch.setattr(runner, "_execution_command", constructed)
            monkeypatch.setattr("garmin.runner.subprocess.run", forbidden_spawn)
            monkeypatch.setattr("garmin.runner.pty.fork", forbidden_spawn)
            context = execution_lease.current_execution.set(lease)
            try:
                with pytest.raises(execution_lease.LeaseLostError):
                    if path == "subprocess":
                        runner._run_json(["-c", "print('{}')"])
                    else:
                        runner.login("synthetic@example.test", "synthetic")
                assert not physical_calls
                assert lease.idle.is_set()
            finally:
                execution_lease.current_execution.reset(context)
                connection.close()
                lease.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["subprocess", "pty"])
def test_direct_runner_keeps_unguarded_launch_behavior(monkeypatch, tmp_path, path):
    runner = GccliRunner(gccli_path=sys.executable, home=str(tmp_path), max_retries=1)
    calls = []

    def forbidden_check(*args):
        raise AssertionError("direct runners must not require Redis")

    monkeypatch.setattr(execution_lease.ExecutionLease, "check_launch", forbidden_check)
    if path == "subprocess":
        assert runner._run_json(["-c", "print('{}')"]) == {}
    else:
        def direct_fork():
            calls.append(True)
            raise OSError("probe before creating a PTY child")
        monkeypatch.setattr("garmin.runner.pty.fork", direct_fork)
        with pytest.raises(OSError, match="probe"):
            runner.login("synthetic@example.test", "synthetic")
        assert calls == [True]


@pytest.mark.parametrize("path", ["subprocess", "pty"])
def test_post_final_cas_pause_can_still_overlap_replacement_even_with_renewal(
    local_redis, monkeypatch, tmp_path, path,
):
    """Expected evidence, NOT xfail: Redis admission != physical exclusion."""
    rapid_renewal(monkeypatch)
    intervals = [tmp_path / "old.json", tmp_path / "replacement.json"]
    last_cas_passed = threading.Event()
    allow_old_spawn = threading.Event()
    old_paused = threading.Event()
    original_run = subprocess.run
    original_fork = pty.fork

    def code(path, delay):
        return (
            "import json,os,pathlib,time; start=time.monotonic(); "
            f"pathlib.Path({str(path.with_suffix('.pid'))!r}).write_text(str(os.getpid())); "
            f"pathlib.Path({str(path)!r}).write_text(json.dumps([start,None])); "
            f"time.sleep({delay}); "
            f"pathlib.Path({str(path)!r}).write_text(json.dumps([start,time.monotonic()])); "
            "print('{}')"
        )

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 1)
            old = await reserve(client, token="old")
            old.start_renewal()
            executable_paths = [sys.executable, sys.executable]
            if path == "pty":
                executable_paths = []
                for index, duration in enumerate([0.3, 0.8]):
                    executable = tmp_path / f"synthetic-auth-{index}.py"
                    executable.write_text(f"#!{sys.executable}\n{code(intervals[index], duration)}\n")
                    executable.chmod(0o700)
                    executable_paths.append(str(executable))
            runner = GccliRunner(gccli_path=executable_paths[0], home=str(tmp_path), max_retries=1)
            new_runner = GccliRunner(gccli_path=executable_paths[1], home=str(tmp_path), max_retries=1)
            runner.timeout = 2
            new_runner.timeout = 2

            def delayed_os_spawn(cmd, **kwargs):
                if any(str(intervals[0]) in arg for arg in cmd):
                    # This boundary is AFTER runner's last successful CAS and
                    # BEFORE the actual subprocess implementation creates a PID.
                    last_cas_passed.set()
                    old_paused.set()
                    assert allow_old_spawn.wait(4)
                return original_run(cmd, **kwargs)

            def delayed_fork():
                if execution_lease.current_execution.get() is old:
                    last_cas_passed.set()
                    old_paused.set()
                    assert allow_old_spawn.wait(4)
                return original_fork()

            if path == "subprocess":
                monkeypatch.setattr("garmin.runner.subprocess.run", delayed_os_spawn)
            else:
                monkeypatch.setattr("garmin.runner.pty.fork", delayed_fork)
            context = execution_lease.current_execution.set(old)
            old_task = asyncio.create_task(asyncio.to_thread(*(
                [runner._run_json, ["-c", code(intervals[0], 0.3)]]
                if path == "subprocess" else
                [runner.login, "synthetic-old@example.test", "synthetic"]
            )))
            execution_lease.current_execution.reset(context)
            replacement = None
            new_task = None
            try:
                assert await asyncio.to_thread(last_cas_passed.wait, 2)
                assert old_paused.is_set() and not intervals[0].exists()
                await expire_global(client, "old")
                await client.delete(f"{queue.LOCK_PREFIX}a")
                replacement = await reserve(client, token="replacement")
                replacement.start_renewal()
                assert await asyncio.to_thread(old.stopped.wait, 1)
                context = execution_lease.current_execution.set(replacement)
                new_task = asyncio.create_task(asyncio.to_thread(*(
                    [new_runner._run_json, ["-c", code(intervals[1], 0.8)]]
                    if path == "subprocess" else
                    [new_runner.login, "synthetic-new@example.test", "synthetic"]
                )))
                execution_lease.current_execution.reset(context)
                deadline = time.monotonic() + 2
                while not intervals[1].exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert intervals[1].exists()
                assert await rate_limiter.global_active_count() == 1
                allow_old_spawn.set()
                deadline = time.monotonic() + 2
                while not intervals[0].exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert intervals[0].exists()
                for interval in intervals:
                    assert json.loads(interval.read_text())[1] is None
                    assert alive(int(interval.with_suffix(".pid").read_text()))
                # Sample Redis WHILE both same-user physical commands live,
                # not merely before the old launch or after both have exited.
                assert await rate_limiter.global_active_count() == 1
                assert await client.get(f"{queue.LOCK_PREFIX}a") == "replacement"
                assert all(alive(int(interval.with_suffix(".pid").read_text())) for interval in intervals)
                assert await old_task == ({} if path == "subprocess" else None)
                assert await new_task == ({} if path == "subprocess" else None)
                old_start, old_end = json.loads(intervals[0].read_text())
                new_start, new_end = json.loads(intervals[1].read_text())
                assert new_start < old_start < old_end < new_end
                assert min(old_end, new_end) > max(old_start, new_start)
                # A late old cleanup still cannot remove the replacement.
                assert not await queue.maintain_user_lock(client, "a", "old", release=True)
                await rate_limiter.release_global_slot("old")
                assert await client.get(f"{queue.LOCK_PREFIX}a") == "replacement"
                assert await rate_limiter.global_active_count() == 1
            finally:
                allow_old_spawn.set()
                await asyncio.gather(old_task, *([new_task] if new_task else []), return_exceptions=True)
                for lease in [old, replacement]:
                    if lease is not None:
                        lease.stop()
                        await lease.join_renewal()
                        lease.close()

    asyncio.run(scenario())


def _cluster_worker(url, cap, index, gate, pipe, directory):
    os.environ["REDIS_URL"] = url
    if cap == 8:
        assert rate_limiter.GLOBAL_MAX == 8  # Unmodified production default.
    else:
        rate_limiter.GLOBAL_MAX = cap

    async def scenario():
        client = aioredis.from_url(url, decode_responses=True)
        queue.get_redis = rate_limiter.get_redis = lambda: client
        sync_worker.ack_job = AsyncMock()
        sync_worker.requeue_job = AsyncMock()
        admissions = []

        async def work(*args):
            admissions.append(await rate_limiter.global_active_count())
            path = str(Path(directory) / f"interval-{index}.json")
            code = (
                "import json,pathlib,time; start=time.monotonic(); time.sleep(0.8); "
                f"pathlib.Path({path!r}).write_text(json.dumps([start,time.monotonic()])); "
                "print('{}')"
            )
            runner = GccliRunner(gccli_path=sys.executable, home=directory, max_retries=1)
            runner.timeout = 2
            runner._run_json(["-c", code])
            return {"success": True}

        sync_worker._run_job = work
        pipe.send(("ready", os.getpid()))
        assert gate.wait(20)
        try:
            await sync_worker.process_job(None, client, "raw", {
                "id": f"job-{index}", "user_id": f"user-{index}",
                "type": queue.JOB_VO2MAX_BACKFILL,
            })
            pipe.send(("done", admissions))
        finally:
            await client.aclose()
            pipe.close()

    asyncio.run(scenario())


def _paused_before_spawn(url, pipe, resume, path):
    os.environ["REDIS_URL"] = url
    execution_lease.LOCK_TTL = rate_limiter.GLOBAL_LEASE_SECONDS = 12
    execution_lease.RENEWAL_MAX_INTERVAL_SECONDS = 0.04
    lease = execution_lease.ExecutionLease("a", "old")
    lease.start_renewal()
    original_run = subprocess.run

    def pause_boundary(cmd, **kwargs):
        pipe.send("last-cas-passed")
        assert resume.wait(20)
        return original_run(cmd, **kwargs)

    subprocess.run = pause_boundary
    runner = GccliRunner(gccli_path=sys.executable, home=str(Path(path).parent), max_retries=1)
    runner.timeout = 0.8
    context = execution_lease.current_execution.set(lease)
    try:
        runner._run_json(["-c", (
            "import json,pathlib,time; start=time.monotonic(); time.sleep(0.2); "
            f"pathlib.Path({path!r}).write_text(json.dumps([start,time.monotonic()])); "
            "print('{}')"
        )])
        pipe.send("physical-command-completed")
    finally:
        execution_lease.current_execution.reset(context)
        lease.stop()
        asyncio.run(lease.join_renewal())
        lease.close()
        pipe.close()


def test_sigstop_after_final_cas_pauses_renewal_and_allows_physical_overlap_after_real_expiry(
    local_redis, monkeypatch, tmp_path,
):
    # 12s leases preserve the unchanged 10s margin for <1s commands. Real
    # SIGSTOP pauses BOTH the command caller and its independent renewal thread.
    monkeypatch.setattr(queue, "LOCK_TTL", 12)
    monkeypatch.setattr(execution_lease, "LOCK_TTL", 12)
    monkeypatch.setattr(rate_limiter, "GLOBAL_LEASE_SECONDS", 12)
    monkeypatch.setattr(rate_limiter, "GLOBAL_MAX", 1)
    context = multiprocessing.get_context("spawn")
    resume = context.Event()
    receiver, sender = context.Pipe(duplex=False)
    old_path = tmp_path / "paused-old.json"
    new_path = tmp_path / "paused-replacement.json"
    process = context.Process(target=_paused_before_spawn, args=(
        local_redis[0], sender, resume, str(old_path),
    ))

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            await reserve(client, token="old")
            process.start()
            sender.close()
            assert await asyncio.to_thread(receiver.poll, 5)
            assert receiver.recv() == "last-cas-passed"
            os.kill(process.pid, signal.SIGSTOP)
            score = await client.zscore(rate_limiter.GLOBAL_LEASE_KEY, "old")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                seconds, micros = await client.time()
                if seconds + micros / 1e6 > score and not await client.exists(f"{queue.LOCK_PREFIX}a"):
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("paused owner's real reservations did not expire")
            replacement = await reserve(client, token="replacement")
            runner = GccliRunner(gccli_path=sys.executable, home=str(tmp_path), max_retries=1)
            runner.timeout = 1
            context_token = execution_lease.current_execution.set(replacement)
            task = asyncio.create_task(asyncio.to_thread(runner._run_json, ["-c", (
                "import json,pathlib,time; start=time.monotonic(); "
                f"pathlib.Path({str(new_path)!r}).write_text(json.dumps([start,None])); "
                "time.sleep(0.7); "
                f"pathlib.Path({str(new_path)!r}).write_text(json.dumps([start,time.monotonic()])); "
                "print('{}')"
            )]))
            execution_lease.current_execution.reset(context_token)
            try:
                deadline = time.monotonic() + 2
                while not new_path.exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.005)
                assert new_path.exists()
                assert await rate_limiter.global_active_count() == 1
                os.kill(process.pid, signal.SIGCONT)
                resume.set()
                assert await asyncio.to_thread(receiver.poll, 3)
                assert receiver.recv() == "physical-command-completed"
                assert await task == {}
                await asyncio.to_thread(process.join, 3)
                assert process.exitcode == 0
                old_start, old_end = json.loads(old_path.read_text())
                new_start, new_end = json.loads(new_path.read_text())
                assert new_start < old_start < old_end < new_end
                assert await rate_limiter.global_active_count() == 1
            finally:
                await asyncio.gather(task, return_exceptions=True)
                replacement.close()

    try:
        asyncio.run(scenario())
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join(3)
        receiver.close()
        sender.close()


@pytest.mark.parametrize("cap,count", [(8, 10), (2, 5)])
def test_multiple_process_workers_bound_redis_admissions_and_actual_child_intervals(
    local_redis, monkeypatch, tmp_path, cap, count,
):
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    workers = []
    receivers = []
    try:
        for index in range(count):
            receiver, sender = context.Pipe(duplex=False)
            worker = context.Process(target=_cluster_worker, args=(
                local_redis[0], cap, index, gate, sender, str(tmp_path),
            ))
            worker.start()
            sender.close()
            workers.append(worker)
            receivers.append(receiver)
        for receiver in receivers:
            assert receiver.poll(20), "worker did not initialize"
            assert receiver.recv()[0] == "ready"
        gate.set()
        admissions = []
        for receiver in receivers:
            assert receiver.poll(15), "worker did not finish"
            kind, observed = receiver.recv()
            assert kind == "done"
            admissions.extend(observed)
        for worker in workers:
            worker.join(3)
            assert worker.exitcode == 0
        assert len(admissions) == cap
        assert max(admissions) == cap
        events = []
        paths = list(tmp_path.glob("interval-*.json"))
        assert len(paths) == cap
        for path in paths:
            start, end = json.loads(path.read_text())
            events.extend([(start, 1), (end, -1)])
        active = maximum_physical = 0
        for _, delta in sorted(events):
            active += delta
            maximum_physical = max(maximum_physical, active)
        assert active == 0
        assert maximum_physical == cap
        connection = redis.Redis.from_url(local_redis[0])
        try:
            assert connection.zcard(rate_limiter.GLOBAL_LEASE_KEY) == 0
            assert not connection.keys(f"{queue.LOCK_PREFIX}*")
        finally:
            connection.close()
    finally:
        gate.set()
        for worker in workers:
            if worker.is_alive():
                worker.kill()
            worker.join(3)
        for receiver in receivers:
            receiver.close()


def test_bounded_redis_client_initialized_once_for_concurrent_renewal_and_commands(monkeypatch):
    lease = execution_lease.ExecutionLease("a", "owner")
    creations = []
    connection = object()

    def create(*args, **kwargs):
        creations.append(kwargs)
        time.sleep(0.02)
        return connection

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(execution_lease.redis.Redis, "from_url", create)
    results = []
    threads = [threading.Thread(target=lambda: results.append(lease._client())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert results == [connection] * 8
    assert len(creations) == 1
    assert creations[0]["socket_timeout"] == 0.5
    assert creations[0]["socket_connect_timeout"] == 0.5
    assert creations[0]["retry"].get_retries() == 0


def test_cleanup_joins_inflight_renewal_without_blocking_loop_or_skipping_release(
    local_redis, monkeypatch,
):
    rapid_renewal(monkeypatch)
    entered = threading.Event()
    finish = threading.Event()
    leases = []
    original_renew = execution_lease.ExecutionLease._renew_owned

    def blocked_renew(lease):
        entered.set()
        assert finish.wait(2)
        original_renew(lease)

    async def scenario():
        async with isolated(local_redis, monkeypatch) as client:
            async def work(*args):
                lease = execution_lease.current_execution.get()
                leases.append(lease)
                monkeypatch.setattr(lease, "_renew_owned", lambda: blocked_renew(lease))
                assert await asyncio.to_thread(entered.wait, 1)
                return {"success": True}

            monkeypatch.setattr(sync_worker, "_run_job", work)
            monkeypatch.setattr(sync_worker, "ack_job", AsyncMock())
            task = asyncio.create_task(sync_worker.process_job(None, client, "raw", {
                "id": "join", "user_id": "a", "type": queue.JOB_VO2MAX_BACKFILL,
            }))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                await asyncio.sleep(0.08)
                assert not task.done()
                assert await rate_limiter.global_active_count() == 1
                assert await client.get(f"{queue.LOCK_PREFIX}a") == leases[0].token
                task.cancel()
                await asyncio.sleep(0.02)
                assert not task.done()
            finally:
                finish.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert not leases[0]._renewal.is_alive()
            assert await rate_limiter.global_active_count() == 0
            assert not await client.exists(f"{queue.LOCK_PREFIX}a")

    asyncio.run(scenario())
