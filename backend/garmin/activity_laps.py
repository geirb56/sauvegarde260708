"""Targeted Garmin laps, independent of typed-splits and derived workouts."""

import asyncio
import math
import uuid
from datetime import datetime, timedelta, timezone

from .activity_details import LEASE_SECONDS, RETRY_SECONDS
from .activity_ids import normalize_activity_id
from .factory import get_provider_for_user

SCHEMA_VERSION = 1
MAX_LAPS = 1000
FIELDS = {
    "lapIndex": "lap_index",
    "messageIndex": "order",
    "startTimeGMT": "start_time_gmt",
    "distance": "distance_m",
    "duration": "duration_s",
    "movingDuration": "moving_duration_s",
    "elapsedDuration": "elapsed_duration_s",
    "averageSpeed": "average_speed_mps",
    "averageMovingSpeed": "average_moving_speed_mps",
    "maxSpeed": "max_speed_mps",
    "averageHR": "average_hr",
    "maxHR": "max_hr",
    "averageRunCadence": "average_cadence_spm",
    "maxRunCadence": "max_cadence_spm",
    "elevationGain": "elevation_gain_m",
    "elevationLoss": "elevation_loss_m",
    "maxElevation": "max_elevation_m",
    "minElevation": "min_elevation_m",
    "intensityType": "intensity_type",
}


def validate_activity_id(activity_id):
    if isinstance(activity_id, str) and activity_id.startswith("garmin-"):
        activity_id = activity_id[7:]
    value = normalize_activity_id(activity_id)
    if int(value) <= 0:
        raise ValueError("Invalid activity identifier")
    return str(int(value))


def _timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Invalid lap timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Lap timestamp must be GMT")
    return parsed


def normalize_activity_laps(raw, activity_id):
    """Fail closed; preserve source values and exclude non-allowlisted data."""
    activity_id = validate_activity_id(activity_id)
    if not isinstance(raw, dict):
        raise ValueError("Invalid laps envelope")
    native_id = raw.get("activityId")
    if type(native_id) is not int or validate_activity_id(native_id) != activity_id:
        raise ValueError("Activity response identifier mismatch")
    laps = raw.get("lapDTOs")
    if not isinstance(laps, list) or len(laps) > MAX_LAPS:
        raise ValueError("Invalid lapDTOs")
    if "eventDTOs" in raw and not isinstance(raw["eventDTOs"], list):
        raise ValueError("Invalid eventDTOs")
    result = []
    previous_index = 0
    previous_order = -1
    previous_time = None
    for lap in laps:
        if not isinstance(lap, dict):
            raise ValueError("Invalid lap")
        index, order = lap.get("lapIndex"), lap.get("messageIndex")
        if (type(index) is not int or type(order) is not int
                or index <= previous_index or order <= previous_order):
            raise ValueError("Invalid lap order or duplicate")
        if "activityId" in lap:
            if type(lap["activityId"]) is not int or lap["activityId"] != native_id:
                raise ValueError("Lap activity identifier mismatch")
        normalized = {}
        for source, target in FIELDS.items():
            value = lap.get(source)
            if source == "startTimeGMT":
                if value is not None:
                    timestamp = _timestamp(value)
                    if previous_time is not None and timestamp < previous_time:
                        raise ValueError("Invalid lap chronology")
                    previous_time = timestamp
            elif source == "intensityType":
                if value is not None and (
                    not isinstance(value, str) or not value or len(value) > 64
                ):
                    raise ValueError("Invalid intensityType")
            elif source not in {"lapIndex", "messageIndex"} and value is not None:
                try:
                    valid = (type(value) in {int, float} and math.isfinite(value)
                             and (value >= 0 or source in {"maxElevation", "minElevation"}))
                except OverflowError:
                    valid = False
                if not valid:
                    raise ValueError("Invalid lap measurement")
            normalized[target] = value
        previous_index, previous_order = index, order
        result.append(normalized)
    return result


def _identity(user_id, activity_id):
    return {"user_id": user_id, "external_id": validate_activity_id(activity_id), "source": "garmin"}


def _cached(doc):
    cache = doc.get("activity_laps") or {}
    return cache.get("schema_version") == SCHEMA_VERSION and cache.get("status") in {
        "complete", "empty",
    }


async def request_activity_laps(db, user_id, activity_id):
    from jobs.queue import enqueue_activity_laps

    identity = _identity(user_id, activity_id)
    doc = await db.garmin_activities.find_one(identity, {"_id": 0})
    if doc is None:
        return {"status": "not_found"}
    if _cached(doc):
        return {"status": "cached"}
    now = datetime.now(timezone.utc)
    state = doc.get("activity_laps_fetch") or {}
    if state.get("next_attempt_at", "") > now.isoformat():
        return {"status": state["status"] if state.get("status") in {"queued", "running"} else "cooldown"}
    token = uuid.uuid4().hex
    claim = await db.garmin_activities.update_one(
        {**identity, "$nor": [{
            "activity_laps.schema_version": SCHEMA_VERSION,
            "activity_laps.status": {"$in": ["complete", "empty"]},
        }], "$or": [
            {"activity_laps_fetch.next_attempt_at": {"$exists": False}},
            {"activity_laps_fetch.next_attempt_at": {"$lte": now.isoformat()}},
        ]},
        {"$set": {"activity_laps_fetch": {
            "token": token, "status": "queued",
            "next_attempt_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        }}},
    )
    if not claim.modified_count:
        return {"status": "already_requested"}
    fenced = {**identity, "activity_laps_fetch.token": token}
    try:
        result = await enqueue_activity_laps(user_id, identity["external_id"])
        if result["status"] not in {"queued", "already_queued"}:
            # The per-user queue slot may belong to a different target.
            await db.garmin_activities.update_one(fenced, {"$set": {
                "activity_laps_fetch": {"status": "failed", "error_code": "queue_busy",
                                       "next_attempt_at": now.isoformat()},
            }})
        return result
    except Exception:
        await db.garmin_activities.update_one(fenced, {"$set": {
            "activity_laps_fetch": {"status": "failed", "error_code": "queue_unavailable",
                                   "next_attempt_at": now.isoformat()},
        }})
        raise


async def get_activity_laps(db, user_id, activity_id):
    doc = await db.garmin_activities.find_one(
        _identity(user_id, activity_id),
        {"_id": 0, "activity_laps": 1, "activity_laps_fetch": 1},
    )
    if doc is None:
        return {"status": "not_found"}
    state = doc.get("activity_laps_fetch") or {}
    status = state.get("status", "not_requested")
    error_code = state.get("error_code")
    if (status in {"queued", "running"} and state.get("next_attempt_at", "")
            <= datetime.now(timezone.utc).isoformat()):
        status, error_code = "retryable_error", "lease_expired"
    if status == "failed":
        status = "retryable_error"
    cache = doc.get("activity_laps")
    return {
        "activity_laps": cache,
        "cache_current": _cached(doc),
        "fetch_status": status,
        "error_code": error_code,
        "next_attempt_at": state.get("next_attempt_at"),
    }


async def fetch_activity_laps(db, user_id, activity_id):
    identity = _identity(user_id, activity_id)
    doc = await db.garmin_activities.find_one(identity, {"_id": 0})
    if doc is None or _cached(doc):
        return {"success": True, "status": "not_found" if doc is None else "cached"}
    now = datetime.now(timezone.utc)
    token = uuid.uuid4().hex
    claim = await db.garmin_activities.update_one(
        {**identity, "$nor": [{
            "activity_laps.schema_version": SCHEMA_VERSION,
            "activity_laps.status": {"$in": ["complete", "empty"]},
        }], "$or": [
            {"activity_laps_fetch.status": "queued"},
            {"activity_laps_fetch.next_attempt_at": {"$exists": False}},
            {"activity_laps_fetch.next_attempt_at": {"$lte": now.isoformat()}},
        ]},
        {"$set": {"activity_laps_fetch": {
            "token": token, "status": "running",
            "next_attempt_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        }}},
    )
    if not claim.modified_count:
        current = await db.garmin_activities.find_one(identity, {"_id": 0})
        if current is None or _cached(current):
            return {"success": True, "status": "not_found" if current is None else "cached"}
        return {"success": False, "status": "deferred",
                "retry_at": current["activity_laps_fetch"]["next_attempt_at"]}
    fenced = {**identity, "activity_laps_fetch.token": token}
    try:
        conn = await db.garmin_connections.find_one({"user_id": user_id})
        if not conn or not conn.get("connected") or not conn.get("garmin_username"):
            raise ValueError("Session unavailable")
        provider = get_provider_for_user(user_id, garmin_account=conn["garmin_username"])
        laps = await asyncio.to_thread(provider.get_activity_laps, user_id, identity["external_id"])
        if not isinstance(laps, list):
            raise ValueError("Unsupported laps provider")
        result = await db.garmin_activities.update_one(fenced, {"$set": {
            "activity_laps": {
                "schema_version": SCHEMA_VERSION, "source": "garmin", "endpoint": "splits",
                "status": "complete" if laps else "empty",
                "fetched_at": datetime.now(timezone.utc).isoformat(), "laps": laps,
            },
            "activity_laps_fetch": {"status": "complete" if laps else "empty"},
        }})
        return {"success": True, "status": "complete" if result.modified_count else "superseded"}
    except Exception:
        await db.garmin_activities.update_one(fenced, {"$set": {
            "activity_laps_fetch": {
                "status": "failed", "error_code": "activity_laps_fetch_failed",
                "next_attempt_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=RETRY_SECONDS)
                ).isoformat(),
            },
        }})
        return {"success": False, "error": "activity_laps_fetch_failed"}
