"""Redis Stream publication for Garmin sync progress snapshots."""

from __future__ import annotations

import json
import time
from typing import Any

from jobs.redis_client import get_redis

STREAM_KEY = "runindex:events:sync_progress"
STREAM_MAXLEN = 10000
EVENT_SYNC_PROGRESS = "SYNC_PROGRESS"


async def emit_sync_progress(user_id: str, snapshot: dict[str, Any]) -> None:
    """Append the latest sync progress snapshot to the dedicated Redis stream."""
    payload = dict(snapshot)
    payload["type"] = EVENT_SYNC_PROGRESS
    payload["user_id"] = user_id
    await get_redis().xadd(
        STREAM_KEY,
        {
            "event": EVENT_SYNC_PROGRESS,
            "user_id": user_id,
            "snapshot": json.dumps(payload),
            "emitted_at": str(time.time()),
        },
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )


def parse_sync_progress_event(fields: dict) -> dict[str, Any]:
    """Decode a sync progress stream entry into a usable event dict."""
    snapshot: dict[str, Any] = {}
    raw = fields.get("snapshot")
    if raw:
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                snapshot = decoded
        except (TypeError, ValueError):
            snapshot = {}
    return {
        "event": fields.get("event"),
        "user_id": fields.get("user_id"),
        "snapshot": snapshot,
    }
