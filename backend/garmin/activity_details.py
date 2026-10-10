"""Targeted typed-splits normalization and persistence (summary-independent).

No verified typed-splits fixture exists in GitHub. Supported envelope/field
names are a provisional contract, not a claim about the real GCCLI response.
Unrecognized envelopes fail closed rather than being cached as empty data.
"""

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from .factory import get_provider_for_user

SCHEMA_VERSION = 1
LEASE_SECONDS = 900
RETRY_SECONDS = 300


def validate_activity_id(activity_id: str) -> str:
    if not isinstance(activity_id, str) or not re.fullmatch(r"[0-9]{1,30}", activity_id):
        raise ValueError("Invalid activity identifier")
    return activity_id


def _identity(user_id: str, activity_id: str) -> dict:
    return {
        "user_id": user_id,
        "external_id": validate_activity_id(activity_id),
        "source": "garmin",
    }


def _cached(doc: dict) -> bool:
    details = doc.get("activity_details") or {}
    return details.get("schema_version") == SCHEMA_VERSION and details.get("status") in {
        "complete", "no_data",
    }


async def request_activity_details(db, user_id: str, activity_id: str) -> dict:
    from jobs.queue import enqueue_activity_details

    doc = await db.garmin_activities.find_one(_identity(user_id, activity_id), {"_id": 0})
    if doc is None:
        return {"status": "not_found"}
    if _cached(doc):
        return {"status": "cached"}
    state = doc.get("activity_details_fetch") or {}
    if state.get("next_attempt_at", "") > datetime.now(timezone.utc).isoformat():
        return {"status": "cooldown"}
    return await enqueue_activity_details(user_id, activity_id)


async def fetch_activity_details(db, user_id: str, activity_id: str) -> dict:
    identity = _identity(user_id, activity_id)
    doc = await db.garmin_activities.find_one(identity, {"_id": 0})
    if doc is None or _cached(doc):
        return {"success": True, "status": "not_found" if doc is None else "cached"}
    conn = await db.garmin_connections.find_one({"user_id": user_id})
    if not conn or not conn.get("connected") or not conn.get("garmin_username"):
        return {"success": False, "error": "session_unavailable"}
    now = datetime.now(timezone.utc)
    token = uuid.uuid4().hex
    claim = await db.garmin_activities.update_one(
        {**identity, "$nor": [{
            "activity_details.schema_version": SCHEMA_VERSION,
            "activity_details.status": {"$in": ["complete", "no_data"]},
        }], "$or": [
            {"activity_details_fetch.next_attempt_at": {"$exists": False}},
            {"activity_details_fetch.next_attempt_at": {"$lte": now.isoformat()}},
        ]},
        {"$set": {"activity_details_fetch": {
            "token": token, "status": "running",
            "next_attempt_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        }}},
    )
    if not claim.modified_count:
        return {"success": True, "status": "cooldown"}
    fenced = {**identity, "activity_details_fetch.token": token}
    try:
        provider = get_provider_for_user(user_id, garmin_account=conn["garmin_username"])
        phases = await asyncio.to_thread(provider.get_activity_phases, user_id, activity_id)
        if phases is None:
            raise ValueError("Provider does not support activity phases")
        completed = datetime.now(timezone.utc).isoformat()
        result = await db.garmin_activities.update_one(
            fenced,
            {"$set": {
                "activity_details": {
                    "schema_version": SCHEMA_VERSION,
                    "status": "complete" if phases else "no_data",
                    "source": "garmin", "endpoint": "typed-splits",
                    "fetched_at": completed, "phases": phases,
                },
                "activity_details_fetch": {"status": "complete"},
            }},
        )
        return {"success": True, "status": "complete" if result.modified_count else "superseded"}
    except Exception:
        await db.garmin_activities.update_one(fenced, {"$set": {
            "activity_details_fetch": {
                "status": "failed", "error_code": "activity_phases_fetch_failed",
                "next_attempt_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=RETRY_SECONDS)
                ).isoformat(),
            },
        }})
        return {"success": False, "error": "activity_phases_fetch_failed"}
