from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("REDIS_URL", "redis://test")

from api.garmin import garmin_router  # noqa: E402
from events import stream as activity_stream  # noqa: E402
from events import sync_progress as progress_events  # noqa: E402
from feed import sse as activity_sse  # noqa: E402
from feed import sync_progress_sse  # noqa: E402
from garmin import sync_progress as sync_progress_store  # noqa: E402


pytestmark = pytest.mark.asyncio


class _FakeRedisStore:
    def __init__(self):
        self.data = {}
        self.streams = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def xadd(self, stream, fields, maxlen=None, approximate=None):
        entries = self.streams.setdefault(stream, [])
        entry_id = f"{len(entries) + 1}-0"
        entries.append((entry_id, dict(fields)))
        return entry_id


class _FakeStreamRedis:
    def __init__(self, responses):
        self.responses = list(responses)
        self.closed = False

    async def xread(self, streams, count=None, block=None):
        if self.responses:
            return self.responses.pop(0)
        await asyncio.sleep(0)
        return []

    async def aclose(self):
        self.closed = True


class _FakeRequest:
    def __init__(self, disconnected=None, headers=None):
        self._disconnected = list(disconnected or [])
        self.headers = headers or {}

    async def is_disconnected(self):
        if self._disconnected:
            return self._disconnected.pop(0)
        return False


async def _first_data(agen, timeout=1):
    async def _run():
        async for chunk in agen:
            if chunk.startswith(":"):
                continue
            return chunk
        return None

    return await asyncio.wait_for(_run(), timeout=timeout)


def _decode_frame(frame: str) -> dict:
    for line in frame.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"missing data line in frame: {frame!r}")


def _sync_event(payload: dict, user_id: str = "user-a", entry_id: str = "1-0"):
    return [
        (
            progress_events.STREAM_KEY,
            [
                (
                    entry_id,
                    {
                        "event": progress_events.EVENT_SYNC_PROGRESS,
                        "user_id": user_id,
                        "snapshot": json.dumps(payload),
                    },
                )
            ],
        )
    ]


def _activity_event(payload: dict, user_id: str = "user-a", entry_id: str = "1-0"):
    return [
        (
            activity_stream.STREAM_KEY,
            [
                (
                    entry_id,
                    {
                        "event": activity_stream.EVENT_ACTIVITY_CREATED,
                        "user_id": user_id,
                        "activity": json.dumps(payload),
                    },
                )
            ],
        )
    ]


async def test_update_sync_progress_persists_and_publishes_sanitized_snapshot(monkeypatch):
    redis = _FakeRedisStore()
    monkeypatch.setattr("jobs.redis_client.get_redis", lambda: redis)
    monkeypatch.setattr(progress_events, "get_redis", lambda: redis)

    result = await sync_progress_store.update_sync_progress(
        "user-a",
        phase="metrics_7d_fetching",
        activities_status="ready",
        activities_count=18,
        run_index_status="ready",
        daily_metrics_status="pending",
        readiness_status="pending",
        garmin_token="secret-token",
        cookie_payload="cookie",
    )

    stored = json.loads(redis.data["runindex:garmin:sync_status:user-a"])
    assert stored["phase"] == "metrics_7d_fetching"
    assert stored["run_index_status"] == "ready"
    assert stored["status"] == "in_progress"
    assert "garmin_token" not in stored
    assert "cookie_payload" not in stored

    event_id, fields = redis.streams[progress_events.STREAM_KEY][0]
    payload = json.loads(fields["snapshot"])
    assert event_id == "1-0"
    assert payload["type"] == "SYNC_PROGRESS"
    assert payload["user_id"] == "user-a"
    assert payload["run_index_status"] == "ready"
    assert "garmin_token" not in payload
    assert "cookie_payload" not in payload
    assert result["updated_at"] == stored["updated_at"]


async def test_sync_progress_stream_filters_other_users(monkeypatch):
    redis = _FakeStreamRedis(
        [
            [
                (
                    progress_events.STREAM_KEY,
                    [
                        (
                            "1-0",
                            {
                                "event": progress_events.EVENT_SYNC_PROGRESS,
                                "user_id": "user-b",
                                "snapshot": json.dumps({"phase": "queued", "status": "queued"}),
                            },
                        ),
                        (
                            "2-0",
                            {
                                "event": progress_events.EVENT_SYNC_PROGRESS,
                                "user_id": "user-a",
                                "snapshot": json.dumps({"phase": "complete", "status": "complete"}),
                            },
                        ),
                    ],
                )
            ]
        ]
    )
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(sync_progress_sse, "get_sync_progress", AsyncMock(return_value=None))

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        frame = await _first_data(agen)
    finally:
        await agen.aclose()

    payload = _decode_frame(frame)
    assert payload["user_id"] == "user-a"
    assert payload["phase"] == "complete"


async def test_sync_progress_stream_sends_initial_snapshot_immediately(monkeypatch):
    redis = _FakeStreamRedis([[]])
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(
        sync_progress_sse,
        "get_sync_progress",
        AsyncMock(
            return_value={
                "status": "in_progress",
                "phase": "enriching",
                "activities_status": "ready",
                "activities_count": 18,
                "run_index_status": "ready",
                "daily_metrics_status": "ready",
                "readiness_status": "ready",
                "error_code": None,
                "updated_at": "2026-08-10T13:15:04+00:00",
            }
        ),
    )

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        frame = await _first_data(agen)
    finally:
        await agen.aclose()

    payload = _decode_frame(frame)
    assert payload["phase"] == "enriching"
    assert payload["run_index_status"] == "ready"
    assert payload["readiness_status"] == "ready"


async def test_transient_run_index_phase_can_be_missed_without_losing_ready_status(monkeypatch):
    redis = _FakeStreamRedis([[]])
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(
        sync_progress_sse,
        "get_sync_progress",
        AsyncMock(
            return_value={
                "status": "in_progress",
                "phase": "metrics_7d_fetching",
                "activities_status": "ready",
                "activities_count": 18,
                "run_index_status": "ready",
                "daily_metrics_status": "pending",
                "readiness_status": "pending",
                "error_code": None,
                "updated_at": "2026-08-10T13:15:04+00:00",
            }
        ),
    )

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        frame = await _first_data(agen)
    finally:
        await agen.aclose()

    payload = _decode_frame(frame)
    assert payload["phase"] == "metrics_7d_fetching"
    assert payload["run_index_status"] == "ready"


async def test_transient_readiness_phase_can_be_missed_without_losing_ready_status(monkeypatch):
    redis = _FakeStreamRedis([[]])
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(
        sync_progress_sse,
        "get_sync_progress",
        AsyncMock(
            return_value={
                "status": "in_progress",
                "phase": "enriching",
                "activities_status": "ready",
                "activities_count": 18,
                "run_index_status": "ready",
                "daily_metrics_status": "ready",
                "readiness_status": "ready",
                "error_code": None,
                "updated_at": "2026-08-10T13:15:04+00:00",
            }
        ),
    )

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        frame = await _first_data(agen)
    finally:
        await agen.aclose()

    payload = _decode_frame(frame)
    assert payload["phase"] == "enriching"
    assert payload["readiness_status"] == "ready"


async def test_reconnect_replays_latest_snapshot_from_redis(monkeypatch):
    redis1 = _FakeStreamRedis([[]])
    redis2 = _FakeStreamRedis([[]])
    snapshots = {
        "status": "in_progress",
        "phase": "enriching",
        "activities_status": "ready",
        "activities_count": 18,
        "run_index_status": "ready",
        "daily_metrics_status": "ready",
        "readiness_status": "ready",
        "error_code": None,
        "updated_at": "2026-08-10T13:15:04+00:00",
    }
    connections = iter([redis1, redis2])
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: next(connections))
    monkeypatch.setattr(sync_progress_sse, "get_sync_progress", AsyncMock(return_value=snapshots))

    agen1 = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    agen2 = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        payload1 = _decode_frame(await _first_data(agen1))
        payload2 = _decode_frame(await _first_data(agen2))
    finally:
        await agen1.aclose()
        await agen2.aclose()

    assert payload1 == payload2
    assert payload2["phase"] == "enriching"


async def test_complete_event_is_forwarded(monkeypatch):
    redis = _FakeStreamRedis(
        [
            _sync_event(
                {
                    "type": "SYNC_PROGRESS",
                    "user_id": "user-a",
                    "status": "complete",
                    "phase": "complete",
                    "activities_status": "ready",
                    "activities_count": 18,
                    "run_index_status": "ready",
                    "daily_metrics_status": "ready",
                    "readiness_status": "ready",
                    "error_code": None,
                }
            )
        ]
    )
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(sync_progress_sse, "get_sync_progress", AsyncMock(return_value=None))

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        payload = _decode_frame(await _first_data(agen))
    finally:
        await agen.aclose()

    assert payload["status"] == "complete"
    assert payload["phase"] == "complete"


async def test_partial_success_snapshot_preserves_statuses(monkeypatch):
    redis = _FakeStreamRedis(
        [
            _sync_event(
                {
                    "type": "SYNC_PROGRESS",
                    "user_id": "user-a",
                    "status": "partial_success",
                    "phase": "partial_success",
                    "activities_status": "ready",
                    "activities_count": 18,
                    "run_index_status": "ready",
                    "daily_metrics_status": "failed",
                    "readiness_status": "unavailable",
                    "error_code": "daily_metrics_7d_failed",
                }
            )
        ]
    )
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(sync_progress_sse, "get_sync_progress", AsyncMock(return_value=None))

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        payload = _decode_frame(await _first_data(agen))
    finally:
        await agen.aclose()

    assert payload["status"] == "partial_success"
    assert payload["run_index_status"] == "ready"
    assert payload["daily_metrics_status"] == "failed"
    assert payload["readiness_status"] == "unavailable"


async def test_failed_snapshot_stays_safe_for_frontend(monkeypatch):
    redis = _FakeStreamRedis(
        [
            _sync_event(
                {
                    "type": "SYNC_PROGRESS",
                    "user_id": "user-a",
                    "status": "failed",
                    "phase": "failed",
                    "activities_status": "pending",
                    "activities_count": 0,
                    "run_index_status": "pending",
                    "daily_metrics_status": "pending",
                    "readiness_status": "unavailable",
                    "error_code": "worker_sync_failed",
                }
            )
        ]
    )
    monkeypatch.setattr(sync_progress_sse.aioredis, "from_url", lambda *a, **k: redis)
    monkeypatch.setattr(sync_progress_sse, "get_sync_progress", AsyncMock(return_value=None))

    agen = sync_progress_sse.sync_progress_stream("user-a", _FakeRequest())
    try:
        payload = _decode_frame(await _first_data(agen))
    finally:
        await agen.aclose()

    blob = json.dumps(payload).lower()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "worker_sync_failed"
    assert "traceback" not in blob
    for forbidden in ("password", "token", "session", "secret", "credential", "cookie"):
        assert forbidden not in blob


async def test_activity_created_stream_remains_unchanged(monkeypatch):
    redis = _FakeStreamRedis(
        [
            [
                (
                    activity_stream.STREAM_KEY,
                    [
                        (
                            "1-0",
                            {
                                "event": activity_stream.EVENT_ACTIVITY_CREATED,
                                "user_id": "other-user",
                                "activity": json.dumps({"external_id": "skip-me"}),
                            },
                        ),
                        (
                            "2-0",
                            {
                                "event": activity_stream.EVENT_ACTIVITY_CREATED,
                                "user_id": "user-a",
                                "activity": json.dumps({"external_id": "keep-me"}),
                            },
                        ),
                    ],
                )
            ]
        ]
    )
    monkeypatch.setattr(activity_sse.aioredis, "from_url", lambda *a, **k: redis)

    agen = activity_sse.event_stream("user-a", _FakeRequest(), "0-0")
    try:
        frame = await _first_data(agen)
    finally:
        await agen.aclose()

    assert "event: activity_created" in frame
    assert '"keep-me"' in frame
    assert "skip-me" not in frame


async def test_sync_progress_sse_requires_authentication():
    app = FastAPI()
    api_router = APIRouter(prefix="/api")
    api_router.include_router(garmin_router)
    app.include_router(api_router)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/garmin/sync/stream")

    assert response.status_code == 401
