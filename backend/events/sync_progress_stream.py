"""Dedicated Redis Stream for Garmin sync-progress events (PR07B).

Separate from ACTIVITY_CREATED — see events/stream.py.
Each entry carries the full sanitized sync-progress snapshot so consumers
(SSE, analytics) don't need a secondary Redis lookup.
"""

from __future__ import annotations

import json
import time

from redis.exceptions import ResponseError

from jobs.redis_client import get_redis

SYNC_PROGRESS_STREAM_KEY = "runindex:events:sync_progress"
SYNC_PROGRESS_STREAM_MAXLEN = 5000
SYNC_PROGRESS_GROUP = "sync_progress_fanout"

EVENT_SYNC_PROGRESS = "SYNC_PROGRESS"

_SENSITIVE_SUBSTRINGS = (
    "password",
    "token",
    "session",
    "secret",
    "credential",
    "cookie",
)


def _sanitize_payload(snapshot: dict) -> dict:
    """Remove sensitive keys before writing to the stream."""
    return {
        k: v
        for k, v in snapshot.items()
        if not any(s in str(k).lower() for s in _SENSITIVE_SUBSTRINGS)
    }


async def emit_sync_progress(user_id: str, snapshot: dict) -> str | None:
    """Append a SYNC_PROGRESS event to the dedicated stream.

    Returns the Redis Stream entry id on success, None on error.
    The ``user_id`` is stored for server-side routing only; it is never
    forwarded to the client in the SSE frame.
    """
    r = get_redis()
    payload = _sanitize_payload(snapshot)
    try:
        entry_id = await r.xadd(
            SYNC_PROGRESS_STREAM_KEY,
            {
                "event": EVENT_SYNC_PROGRESS,
                "user_id": user_id,
                "data": json.dumps(payload),
                "emitted_at": str(time.time()),
            },
            maxlen=SYNC_PROGRESS_STREAM_MAXLEN,
            approximate=True,
        )
        return entry_id
    except Exception:
        return None


async def ensure_group(group: str = SYNC_PROGRESS_GROUP) -> None:
    """Create the consumer group (idempotent), creating the stream if needed."""
    r = get_redis()
    try:
        await r.xgroup_create(
            SYNC_PROGRESS_STREAM_KEY, group, id="0", mkstream=True
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
