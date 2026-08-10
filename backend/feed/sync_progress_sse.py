"""SSE delivery layer for Garmin sync-progress events (PR07B).

Streams SYNC_PROGRESS events to the browser via Server-Sent Events.
Pure delivery layer: no sync trigger, no gccli, no DB writes.

Design:
  - On connect: immediately emits the latest snapshot from Redis (sync_status)
    so the client never has to wait for the next Redis Stream event.
  - Then reads the dedicated stream (runindex:events:sync_progress) with plain
    XREAD (not a consumer group) — non-destructive, horizontally scalable.
  - Reconnect-safe: resumes from Last-Event-ID (Redis Stream entry id).
  - Heartbeat: `: ping` comment frames (no business payload).
  - User isolation: only events whose `user_id` matches the authenticated user
    are forwarded; all others are silently skipped.
  - Sensitive fields are never included (sanitation already applied upstream
    in sync_progress.py and emit_sync_progress).
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import redis.asyncio as aioredis

from events.sync_progress_stream import (
    SYNC_PROGRESS_STREAM_KEY,
    EVENT_SYNC_PROGRESS,
)
from garmin.sync_progress import get_sync_progress

SSE_BLOCK_MS = int(os.environ.get("SSE_SYNC_BLOCK_MS", "15000"))
SSE_COUNT = int(os.environ.get("SSE_SYNC_COUNT", "50"))
SSE_HEARTBEAT_S = int(os.environ.get("SSE_SYNC_HEARTBEAT_S", "20"))


def _format_sse_frame(entry_id: str, payload: dict) -> str:
    """Return a complete SSE frame string for one snapshot."""
    return f"id: {entry_id}\nevent: sync_progress\ndata: {json.dumps(payload)}\n\n"


async def sync_progress_event_stream(user_id: str, request, start_id: str = "$"):
    """Async generator yielding SSE frames of SYNC_PROGRESS for one user.

    Yields an initial snapshot immediately on connect (from the Redis key),
    then streams future events from the dedicated Redis Stream.
    """
    # Dedicated connection: blocking XREAD must not starve the shared pool.
    redis = aioredis.from_url(
        os.environ["REDIS_URL"],
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=None,
        socket_connect_timeout=5,
    )
    last_id = start_id
    last_beat = time.monotonic()

    try:
        yield ": connected\n\n"

        # --- Snapshot initial -----------------------------------------------
        # Emit the current state immediately so the client doesn't have to wait
        # for the next stream event.  Use a synthetic id so the client can
        # distinguish it from a real stream entry.
        snapshot = await get_sync_progress(user_id)
        if snapshot:
            yield f"id: snapshot\nevent: sync_progress\ndata: {json.dumps(snapshot)}\n\n"

        # --- Stream loop -----------------------------------------------------
        while True:
            if await request.is_disconnected():
                break

            try:
                resp = await redis.xread(
                    {SYNC_PROGRESS_STREAM_KEY: last_id},
                    count=SSE_COUNT,
                    block=SSE_BLOCK_MS,
                )
            except Exception:
                await asyncio.sleep(1)
                yield ": ping\n\n"
                continue

            now = time.monotonic()
            if not resp:
                yield ": ping\n\n"
                last_beat = now
                continue

            for _stream, entries in resp:
                for entry_id, fields in entries:
                    last_id = entry_id  # advance cursor regardless of user match
                    if fields.get("event") != EVENT_SYNC_PROGRESS:
                        continue
                    if fields.get("user_id") != user_id:
                        continue
                    raw = fields.get("data", "{}")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    yield _format_sse_frame(entry_id, payload)

            if now - last_beat >= SSE_HEARTBEAT_S:
                yield ": ping\n\n"
                last_beat = now
    finally:
        try:
            await redis.aclose()
        except Exception:
            pass
