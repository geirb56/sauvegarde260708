"""SSE delivery layer for Garmin SYNC_PROGRESS snapshots."""

from __future__ import annotations

import asyncio
import json
import os

import redis.asyncio as aioredis

from events.sync_progress import EVENT_SYNC_PROGRESS, STREAM_KEY, parse_sync_progress_event
from garmin.sync_progress import get_sync_progress

SSE_BLOCK_MS = int(os.environ.get("SSE_BLOCK_MS", "15000"))
SSE_COUNT = int(os.environ.get("SSE_COUNT", "50"))
SSE_HEARTBEAT_S = int(os.environ.get("SSE_HEARTBEAT_S", "20"))


def _format_sync_progress_frame(payload: dict, *, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append("event: sync_progress")
    lines.append(f"data: {json.dumps(payload)}")
    return "\n".join(lines) + "\n\n"


async def sync_progress_stream(user_id: str, request):
    """Async generator yielding SSE frames of sync progress for one user."""
    redis = aioredis.from_url(
        os.environ["REDIS_URL"],
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=None,
        socket_connect_timeout=5,
    )
    last_id = request.headers.get("Last-Event-ID") or "$"
    try:
        yield ": connected\n\n"

        snapshot = await get_sync_progress(user_id)
        if snapshot:
            payload = dict(snapshot)
            payload["type"] = EVENT_SYNC_PROGRESS
            payload["user_id"] = user_id
            yield _format_sync_progress_frame(payload)

        while True:
            if await request.is_disconnected():
                break
            try:
                resp = await redis.xread({STREAM_KEY: last_id}, count=SSE_COUNT, block=SSE_BLOCK_MS)
            except Exception:
                await asyncio.sleep(1)
                yield ": ping\n\n"
                continue

            if not resp:
                yield ": ping\n\n"
                continue

            for _stream, entries in resp:
                for entry_id, fields in entries:
                    last_id = entry_id
                    ev = parse_sync_progress_event(fields)
                    if ev.get("event") != EVENT_SYNC_PROGRESS or ev.get("user_id") != user_id:
                        continue
                    payload = dict(ev.get("snapshot") or {})
                    payload["type"] = EVENT_SYNC_PROGRESS
                    payload["user_id"] = user_id
                    yield _format_sync_progress_frame(payload, event_id=entry_id)
    finally:
        try:
            await redis.aclose()
        except Exception:
            pass
