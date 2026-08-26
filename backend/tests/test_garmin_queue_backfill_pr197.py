from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from jobs import queue


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.queue = []

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def lpush(self, key, payload):
        self.queue.append((key, payload))


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
