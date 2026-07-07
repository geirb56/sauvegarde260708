"""Garmin orchestration service.

Coordinates the provider with MongoDB persistence. Stores ONLY normalized
business data (connection status + activities). Never stores credentials.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .factory import get_provider, active_provider_name
from .providers.base import STATUS_CONNECTED, STATUS_MFA_REQUIRED
from events.stream import emit_activity_created

logger = logging.getLogger(__name__)


async def connect(db, user_id: str, simulate_mfa: bool = False) -> dict:
    provider = get_provider()
    result = provider.connect(user_id, simulate_mfa=simulate_mfa)

    if result.status == STATUS_CONNECTED:
        await db.garmin_connections.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "connected": True,
                "provider": active_provider_name(),
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        logger.info("[Garmin] connected user=%s provider=%s", user_id, active_provider_name())

    return {"status": result.status, "message": result.detail, "provider": active_provider_name()}


_ACTIVITY_TYPE_TO_WORKOUT = {
    "running": "run",
    "trail_running": "run",
    "treadmill_running": "run",
    "cycling": "cycle",
    "biking": "cycle",
    "swimming": "swim",
}


def activity_to_workout(act: dict, user_id: str) -> Optional[dict]:
    """Map a normalized Garmin activity to the app's workout schema.

    Used by the fan-out event worker to build the derived `workouts` (product)
    layer. Returns None if essential fields are missing.
    """
    ext_id = act.get("external_id")
    if not ext_id:
        return None
    distance_m = act.get("distance") or 0
    duration_s = act.get("duration") or 0
    distance_km = round(distance_m / 1000.0, 2) if distance_m else 0.0
    duration_minutes = int(round(duration_s / 60.0)) if duration_s else 0
    pace_spk = act.get("pace_seconds_per_km")
    avg_pace_min_km = round(pace_spk / 60.0, 3) if pace_spk else None
    atype = (act.get("activity_type") or "running").lower()
    wtype = _ACTIVITY_TYPE_TO_WORKOUT.get(atype, "run")
    return {
        "id": f"garmin-{ext_id}",
        "type": wtype,
        "name": act.get("name") or "Garmin Activity",
        "date": act.get("start_time") or datetime.now(timezone.utc).isoformat(),
        "duration_minutes": duration_minutes,
        "distance_km": distance_km,
        "avg_heart_rate": act.get("avg_hr"),
        "avg_pace_min_km": avg_pace_min_km,
        "data_source": "garmin",
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def _ingest_activities(db, user_id: str, activities: list) -> dict:
    """Ingestion layer (SOURCE OF TRUTH): upsert into `garmin_activities`,
    dedupe by external_id, and emit ACTIVITY_CREATED for each NEW activity.

    Never writes `workouts` directly — that derived layer is built by the
    fan-out event worker consuming ACTIVITY_CREATED.
    """
    synced = new_count = 0
    newest_start = None
    for act in activities:
        ext_id = act.get("external_id")
        if not ext_id:
            continue
        doc = {**act, "user_id": user_id, "synced_at": datetime.now(timezone.utc).isoformat()}
        res = await db.garmin_activities.update_one(
            {"user_id": user_id, "external_id": ext_id},
            {"$set": doc},
            upsert=True,
        )
        synced += 1
        start_time = act.get("start_time")
        if start_time and (newest_start is None or start_time > newest_start):
            newest_start = start_time
        # Emit only on first insert (dedupe) -> "created" event, no re-emit.
        if res.upserted_id is not None:
            new_count += 1
            try:
                await emit_activity_created(user_id, doc)
            except Exception as exc:  # event bus must never fail ingestion
                logger.error("[Garmin] emit ACTIVITY_CREATED failed user=%s: %s", user_id, exc)
    return {"synced": synced, "new": new_count, "newest_start": newest_start}


async def _finalize_connection(db, user_id: str, newest_start: Optional[str]) -> int:
    total = await db.garmin_activities.count_documents({"user_id": user_id})
    update = {
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "activity_count": total,
    }
    if newest_start:
        update["last_activity_at"] = newest_start
    await db.garmin_connections.update_one({"user_id": user_id}, {"$set": update})
    return total


async def sync(db, user_id: str, since: Optional[str] = None) -> dict:
    """Full Garmin sync (activities + daily metrics), used for manual triggers.

    Executed by the out-of-process worker (workers/sync_worker.py), never in the
    API request flow. Writes only the ingestion layer (`garmin_activities`) and
    emits ACTIVITY_CREATED events; the `workouts` product layer + feed cache are
    built asynchronously by the fan-out event worker.
    """
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn or not conn.get("connected"):
        return {"success": False, "synced_count": 0, "metrics_count": 0, "message": "Garmin not connected"}

    provider = get_provider()

    # --- Activities ---
    try:
        activities = provider.sync_activities(user_id, since=since)
    except Exception as exc:  # provider/runner failures -> graceful
        logger.error("[Garmin] activity sync failed user=%s: %s", user_id, exc)
        return {"success": False, "synced_count": 0, "metrics_count": 0, "message": "Sync failed, please reconnect"}

    ingest = await _ingest_activities(db, user_id, activities)

    # --- Daily health metrics (Phase 2: HRV / resting HR / sleep) ---
    metrics_count = 0
    try:
        metrics = provider.get_daily_metrics(user_id, days=7)
        for m in metrics:
            day = m.get("date")
            if not day:
                continue
            await db.garmin_daily_metrics.update_one(
                {"user_id": user_id, "date": day},
                {"$set": {**m, "user_id": user_id, "synced_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
            metrics_count += 1
    except Exception as exc:
        logger.warning("[Garmin] daily metrics sync skipped user=%s: %s", user_id, exc)

    await _finalize_connection(db, user_id, ingest["newest_start"])
    logger.info("[Garmin] synced %d activities (%d new), %d daily metrics user=%s",
                ingest["synced"], ingest["new"], metrics_count, user_id)
    return {
        "success": True,
        "synced_count": ingest["synced"],
        "new_count": ingest["new"],
        "metrics_count": metrics_count,
        "message": f"Imported {ingest['synced']} activities",
    }


async def incremental_sync(db, user_id: str) -> dict:
    """Incremental sync: fetch ONLY activities newer than the last stored one.

    Uses `since = last_activity_timestamp` so Garmin API usage stays flat (small
    payload) vs a full re-sync. Activities-only (no daily-metrics fetch) to keep
    the batch light; dedupe + event emission happen in _ingest_activities.
    """
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn or not conn.get("connected"):
        return {"success": False, "synced_count": 0, "new_count": 0, "message": "Garmin not connected"}

    last = await db.garmin_activities.find_one(
        {"user_id": user_id}, {"_id": 0, "start_time": 1}, sort=[("start_time", -1)]
    )
    since = last.get("start_time") if last else None

    provider = get_provider()
    try:
        activities = provider.sync_activities(user_id, since=since)
    except Exception as exc:
        logger.error("[Garmin] incremental sync failed user=%s: %s", user_id, exc)
        return {"success": False, "synced_count": 0, "new_count": 0, "message": "Sync failed"}

    ingest = await _ingest_activities(db, user_id, activities)
    await _finalize_connection(db, user_id, ingest["newest_start"])
    logger.info("[Garmin] incremental synced=%d new=%d user=%s since=%s",
                ingest["synced"], ingest["new"], user_id, since)
    return {
        "success": True,
        "synced_count": ingest["synced"],
        "new_count": ingest["new"],
        "metrics_count": 0,
        "message": f"{ingest['new']} new activities",
    }


async def get_status(db, user_id: str) -> dict:
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn:
        return {
            "connected": False,
            "provider": active_provider_name(),
            "last_sync": None,
            "activity_count": 0,
        }
    return {
        "connected": bool(conn.get("connected")),
        "provider": conn.get("provider", active_provider_name()),
        "last_sync": conn.get("last_sync"),
        "activity_count": conn.get("activity_count", 0),
    }


async def disconnect(db, user_id: str) -> dict:
    await db.garmin_connections.delete_one({"user_id": user_id})
    await db.garmin_activities.delete_many({"user_id": user_id})
    await db.garmin_daily_metrics.delete_many({"user_id": user_id})
    # Remove mirrored Garmin workouts only (keep manual/other-source workouts)
    await db.workouts.delete_many({"user_id": user_id, "data_source": "garmin"})
    logger.info("[Garmin] disconnected user=%s", user_id)
    return {"success": True, "message": "Garmin disconnected"}


async def get_daily_metrics(db, user_id: str, days: int = 7) -> dict:
    cursor = (
        db.garmin_daily_metrics.find({"user_id": user_id}, {"_id": 0})
        .sort("date", -1)
        .limit(days)
    )
    metrics = await cursor.to_list(length=days)
    latest = metrics[0] if metrics else None
    return {"metrics": metrics, "latest": latest, "count": len(metrics)}


async def list_activities(db, user_id: str, limit: int = 20, since: Optional[str] = None) -> list:
    query = {"user_id": user_id}
    if since:
        query["start_time"] = {"$gt": since}
    cursor = (
        db.garmin_activities.find(query, {"_id": 0})
        .sort("start_time", -1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)
