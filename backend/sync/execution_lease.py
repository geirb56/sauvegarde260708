"""Execution fencing for queued GCCLI commands, including to_thread callers.

Redis ownership is checked before EACH physical command (also inline retries).
An independent GNU timeout process bounds children even if the worker dies.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
import time
from contextvars import ContextVar
from contextlib import contextmanager

import redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from jobs.queue import LOCK_PREFIX, LOCK_TTL
from sync import rate_limiter

RENEWAL_MAX_INTERVAL_SECONDS = 30

current_execution: ContextVar["ExecutionLease | None"] = ContextVar(
    "gccli_execution_lease", default=None,
)


class LeaseLostError(RedisError):
    """Fail closed, leaving the delivery in PROCESSING for recovery."""


class ExecutionLease:
    def __init__(self, user_id: str, token: str):
        self.user_id = user_id
        self.token = token
        self.stopped = threading.Event()
        self.idle = threading.Event()
        self.idle.set()
        self._active = 0
        self._lock = threading.Lock()
        self._client_lock = threading.Lock()
        self._redis = None
        self._renewal_stop = threading.Event()
        self._renewal = None

    def stop(self):
        with self._lock:
            self.stopped.set()

    @contextmanager
    def running(self):
        # Register before checking Redis, including direct task cancellation
        # during asyncio.run shutdown (shield alone cannot protect that case).
        with self._lock:
            if self.stopped.is_set():
                raise LeaseLostError("GCCLI execution stopped")
            self._active += 1
            self.idle.clear()
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
                if not self._active:
                    self.idle.set()

    async def wait_idle(self):
        cancelled = False
        while not self.idle.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                cancelled = True
        return cancelled

    def _client(self):
        # Redis's connection pool is thread-safe; its lazy creation must be too.
        with self._client_lock:
            if self._redis is None:
                self._redis = redis.Redis.from_url(
                    os.environ["REDIS_URL"], decode_responses=True,
                    socket_timeout=0.5, socket_connect_timeout=0.5,
                    retry=Retry(NoBackoff(), 0), retry_on_timeout=False,
                )
            return self._redis

    def _renew_owned(self):
        try:
            owned = self._client().eval(
                rate_limiter.RENEW_LEASES_LUA, 2,
                rate_limiter.GLOBAL_LEASE_KEY, f"{LOCK_PREFIX}{self.user_id}",
                self.token, rate_limiter.GLOBAL_LEASE_SECONDS, LOCK_TTL,
            )
        except RedisError:
            self.stop()
            raise
        if not owned:
            self.stop()
            raise LeaseLostError("GCCLI lease expired or changed owner")

    def start_renewal(self):
        """Start once, after both acquisitions; never restart a stopped lease.

        stop() fences future commands but retains owned reservations while a
        current command drains. join_renewal() ends that intentional retention.
        """
        def renew():
            interval = min(
                min(LOCK_TTL, rate_limiter.GLOBAL_LEASE_SECONDS) / 4,
                RENEWAL_MAX_INTERVAL_SECONDS,
            )
            while not self._renewal_stop.wait(interval):
                try:
                    self._renew_owned()
                except Exception:
                    self.stop()
                    return

        with self._lock:
            if self._renewal is not None or self.stopped.is_set():
                return
            renewal = threading.Thread(
                target=renew, name="gccli-lease-renewal", daemon=True,
            )
            renewal.start()
            self._renewal = renewal

    async def join_renewal(self):
        self._renewal_stop.set()
        cancelled = False
        if self._renewal is not None:
            # Configured socket deadlines and no retries bound normal Redis IO,
            # not OS DNS resolution. Poll rather than block the event loop.
            while self._renewal.is_alive():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    cancelled = True
            self._renewal.join()
        return cancelled

    def check_launch(self, timeout: float):
        """Last practical CAS; not atomic with the subsequent OS spawn.

        A pause/replacement after this check can still admit physical overlap.
        Strict exclusion needs fencing at the command execution authority, not
        another expiring Redis check. Already-running commands rely on timeout.
        """
        if self.stopped.is_set():
            raise LeaseLostError("GCCLI execution stopped")
        started = time.monotonic()
        self._renew_owned()
        if (
            self.stopped.is_set()
            or time.monotonic() - started + timeout + 10 >= min(
                LOCK_TTL, rate_limiter.GLOBAL_LEASE_SECONDS,
            )
        ):
            self.stop()
            raise LeaseLostError("GCCLI lease expired or changed owner")

    def command(self, cmd: list[str], timeout: float) -> list[str]:
        """Grant a bounded command only while BOTH reservations are owned."""
        if self.stopped.is_set():
            raise LeaseLostError("GCCLI execution stopped")
        guardian = shutil.which("timeout")
        if guardian is None:
            raise LeaseLostError("GNU timeout is required for queued GCCLI")
        if timeout > min(LOCK_TTL, rate_limiter.GLOBAL_LEASE_SECONDS) - 10:
            raise LeaseLostError("GCCLI timeout exceeds safe lease window")
        self.check_launch(timeout)
        return [guardian, "--signal=KILL", "--kill-after=5", str(timeout), *cmd]

    def close(self):
        if self._renewal is not None and self._renewal.is_alive():
            raise RuntimeError("join GCCLI renewal before closing Redis")
        if self._redis is not None:
            self._redis.close()


async def run_with_lease(work, timeout: float, lease: ExecutionLease):
    """Do not abandon a provider thread while releasing its reservations."""
    context = current_execution.set(lease)
    try:
        task = asyncio.create_task(work)
    finally:
        current_execution.reset(context)
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout)
        if lease.stopped.is_set():
            raise LeaseLostError("GCCLI execution lost ownership")
        return result
    except BaseException:
        lease.stop()
        # shield keeps to_thread attached to its coroutine. Further commands
        # are fenced; the current command has an independent physical deadline.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()
        await lease.wait_idle()
        raise
