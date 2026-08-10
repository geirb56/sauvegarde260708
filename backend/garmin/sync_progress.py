from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

SYNC_STATUS_PREFIX = "runindex:garmin:sync_status:"
SYNC_STATUS_TTL = 6 * 60 * 60

_DEFAULT_STATUS = {
    "status": "queued",
    "phase": "queued",
    "activities_status": "pending",
    "activities_count": 0,
    "run_index_status": "pending",
    "daily_metrics_status": "pending",
    "readiness_status": "pending",
    "error_code": None,
}
_SENSITIVE_SUBSTRINGS = ("password", "token", "session", "secret", "credential", "cookie")
_FINAL_PHASES = {"complete", "partial_success", "failed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(fields: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in fields.items():
        key_lower = str(key).lower()
        if any(part in key_lower for part in _SENSITIVE_SUBSTRINGS):
            continue
        sanitized[key] = value
    return sanitized


async def get_sync_progress(user_id: str) -> dict[str, Any] | None:
    try:
        from jobs.redis_client import get_redis

        raw = await get_redis().get(f"{SYNC_STATUS_PREFIX}{user_id}")
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def update_sync_progress(user_id: str, **fields: Any) -> dict[str, Any]:
    current = await get_sync_progress(user_id) or dict(_DEFAULT_STATUS)
    current.update(_sanitize(fields))
    current["updated_at"] = _now_iso()
    phase = current.get("phase")
    if phase == "queued":
        current["status"] = "queued"
    elif phase in _FINAL_PHASES:
        current["status"] = phase
    else:
        current["status"] = "in_progress"
    try:
        from jobs.redis_client import get_redis

        await get_redis().set(
            f"{SYNC_STATUS_PREFIX}{user_id}",
            json.dumps(current),
            ex=SYNC_STATUS_TTL,
        )
        try:
            from events.sync_progress import emit_sync_progress

            await emit_sync_progress(user_id, current)
        except Exception:
            pass
    except Exception:
        return current
    return current
