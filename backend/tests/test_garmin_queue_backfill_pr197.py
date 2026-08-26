from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from jobs import queue
from workers import sync_worker


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.queue = []
        self.deleted = []
        self.counters = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def lpush(self, key, payload):
        self.queue.append((key, payload))

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1


def test_enqueue_sync_updates_progress():
    redis = _FakeRedis()

    with (
        patch("jobs.queue.get_redis", return_value=redis),
        patch("garmin.sync_progress.update_sync_progress", new=AsyncMock()) as mock_progress,
    ):
        result = asyncio.run(queue.enqueue_sync("user-1"))

    assert result == {"status": "queued"}
    assert redis.values["sync_pending:user-1"] == queue.JOB_SYNC_USER
    mock_progress.assert_awaited_once()


def test_enqueue_vo2max_backfill_uses_dedicated_pending_key_without_progress():
    redis = _FakeRedis()

    with (
        patch("jobs.queue.get_redis", return_value=redis),
        patch("garmin.sync_progress.update_sync_progress", new=AsyncMock()) as mock_progress,
    ):
        result = asyncio.run(queue.enqueue_vo2max_backfill("user-1"))

    assert result == {"status": "queued"}
    assert redis.values["sync_pending:user-1:vo2max_backfill"] == queue.JOB_VO2MAX_BACKFILL
    mock_progress.assert_not_awaited()


def test_retryable_backfill_failure_is_not_acked_as_success():
    redis = _FakeRedis()
    job = {
        "id": "job-1",
        "type": queue.JOB_VO2MAX_BACKFILL,
        "user_id": "user-1",
        "attempts": 0,
    }

    with (
        patch.object(sync_worker.rate_limiter, "acquire_global_slot", new=AsyncMock(return_value=True)),
        patch.object(sync_worker.rate_limiter, "release_global_slot", new=AsyncMock()),
        patch.object(sync_worker, "_run_job", new=AsyncMock(side_effect=RuntimeError("session_unavailable"))),
        patch.object(sync_worker, "requeue_job", new=AsyncMock()) as mock_requeue,
        patch.object(sync_worker, "ack_job", new=AsyncMock()) as mock_ack,
    ):
        asyncio.run(sync_worker.process_job(None, redis, "raw-job", job))

    mock_requeue.assert_awaited_once()
    mock_ack.assert_not_awaited()
