"""SSE delivery layer for ACTIVITY_CREATED — READ-ONLY, stateless.

Streams new-activity events to a browser via Server-Sent Events. It is a pure
DELIVERY layer on top of the existing Redis Stream: it never triggers a sync,
never calls gccli, never writes to Mongo or Redis.

Design:
  - Consumes with plain XREAD (NOT a consumer group) so it is non-destructive:
    the fan-out worker's group is untouched, and any number of SSE clients /
    server instances can read independently -> horizontally scalable.
  - Reconnect-safe & idempotent: the client resumes from `Last-Event-ID`
    (the Redis Stream entry id). No server-side per-client state.
  - Low footprint: one dedicated Redis connection per stream, closed on
    disconnect; blocking XREAD with periodic heartbeats to detect drop-offs.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import redis.asyncio as aioredis

from events.stream import STREAM_KEY, parse_event, EVENT_ACTIVITY_CREATED

SSE_BLOCK_MS = int(os.environ.get("SSE_BLOCK_MS", "15000"))
SSE_COUNT = int(os.environ.get("SSE_COUNT", "50"))
SSE_HEARTBEAT_S = int(os.environ.get("SSE_HEARTBEAT_S", "20"))


async def event_stream(user_id: str, request, start_id: str = "$"):
    """Async generator yielding SSE frames of ACTIVITY_CREATED for one user."""
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
        while True:
            if await request.is_disconnected():
                break
            try:
                resp = await redis.xread({STREAM_KEY: last_id}, count=SSE_COUNT, block=SSE_BLOCK_MS)
            except Exception:
                # Transient Redis hiccup: brief pause, keep the stream alive.
                await asyncio.sleep(1)
                yield ": ping\n\n"
                continue

            now = time.monotonic()
            if not resp:
                yield ": ping\n\n"  # heartbeat / keep-alive
                last_beat = now
                continue

            for _stream, entries in resp:
                for entry_id, fields in entries:
                    last_id = entry_id  # advance regardless of user match
                    ev = parse_event(fields)
                    if ev.get("event") != EVENT_ACTIVITY_CREATED or ev.get("user_id") != user_id:
                        continue
                    frame = {"user_id": ev["user_id"], "activity": ev["activity"]}
                    yield f"id: {entry_id}\nevent: activity_created\ndata: {json.dumps(frame)}\n\n"

            if now - last_beat >= SSE_HEARTBEAT_S:
                yield ": ping\n\n"
                last_beat = now
    finally:
        try:
            await redis.aclose()
        except Exception:
            pass
