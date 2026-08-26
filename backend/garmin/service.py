"""Garmin orchestration service.

Coordinates the provider with MongoDB persistence. Stores ONLY normalized
business data (connection status + activities). Never stores Garmin passwords.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

from .factory import get_provider_for_user, active_provider_name
from .providers.base import STATUS_CONNECTED, STATUS_MFA_REQUIRED
from . import session_store
from .data_layer import GarminCapabilities, GarminVO2Max
from .sync_progress import get_sync_progress, update_sync_progress
from events.stream import emit_activity_created
from garmin.insights import compute_run_index
from services.run_index_history import (
    backfill_run_index_history_after_garmin_sync,
    refresh_today_run_index_after_garmin_activities,
)
from .backfill import backfill_user as _backfill_workouts_user
from subscription_manager import activate_garmin_trial
import dashboard_insight_cache as _dic

logger = logging.getLogger(__name__)
INITIAL_DAILY_METRICS_DAYS = 7
ENRICHMENT_DAILY_METRICS_START_DAYS_AGO = 8
ENRICHMENT_DAILY_METRICS_DAYS = 23
INITIAL_VO2MAX_BACKFILL_MONTHS = 12
_RUNNING_ACTIVITY_TYPES = frozenset(
    {"running", "run", "trail_running", "trail_run", "treadmill_running"}
)


def _subtract_months(target_day: date, months: int) -> date:
    year = target_day.year
    month = target_day.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(target_day.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse_activity_day(activity: dict) -> Optional[date]:
    raw_value = activity.get("start_time") or activity.get("date")
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(raw_value).split("T")[0]).date()
        except ValueError:
            return None


def _is_running_activity(activity: dict) -> bool:
    activity_type = activity.get("activity_type")
    return isinstance(activity_type, str) and activity_type.strip().lower() in _RUNNING_ACTIVITY_TYPES


async def _persist_capabilities(db, user_id: str, capabilities: GarminCapabilities) -> None:
    """Upsert the garmin_capabilities sub-document into garmin_connections.

    Targeted $set so no other field in the document is touched (multi-user safe).
    """
    await db.garmin_connections.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "garmin_capabilities": capabilities.model_dump(),
                "capabilities_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )


async def _persist_vo2max(db, user_id: str, vo2max: GarminVO2Max) -> None:
    """Upsert a dated Garmin VO₂max point into the ``garmin_vo2max`` collection.

    Each (user_id, date) pair is an independent document — a new measurement for
    a different date does NOT overwrite an older one.  This preserves the full
    sparse history of real Garmin readings.

    Canonical date field: ``date`` (from ``calendarDate`` in the Garmin payload).
    If Garmin does not provide a ``calendarDate`` the measurement is NOT persisted
    as a historical point — no synthetic date is invented.

    ``vo2max_running_precise`` is only written when the payload provides it; a
    lower-fidelity payload does not erase a previously stored precise value for
    the same date.
    """
    measurement_date = vo2max.date
    if measurement_date is None:
        # No date in payload → cannot create a meaningful historical point.
        # Per design: no fabrication, no forward-fill.  Skip persistence.
        logger.info(
            "[Garmin] _persist_vo2max: no calendarDate in payload, skipping history write user=%s",
            user_id,
        )
        return

    set_fields: dict = {
        "user_id": user_id,
        "date": measurement_date,
        "vo2max_running": vo2max.vo2max_running,
        "source": vo2max.source,
        "sport": "running",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if vo2max.vo2max_running_precise is not None:
        set_fields["vo2max_running_precise"] = vo2max.vo2max_running_precise

    await db.garmin_vo2max.update_one(
        {"user_id": user_id, "date": measurement_date},
        {"$set": set_fields},
        upsert=True,
    )
    logger.info(
        "[Garmin] VO2max persisted user=%s vo2max_running=%s precise=%s date=%s",
        user_id, vo2max.vo2max_running, vo2max.vo2max_running_precise, measurement_date,
    )


async def _fetch_and_persist_vo2max(
    db,
    user_id: str,
    provider,
    *,
    target_date: Optional[str] = None,
) -> Optional[float]:
    """Fetch native Garmin VO₂max from gccli, normalize, and persist.

    Returns the resolved ``vo2max_running`` value (or ``None``).
    Never raises: any error is logged and ``None`` is returned so it does not
    break the broader sync pipeline.

    No-overwrite guard: when the payload yields no value (vo2max_running is None),
    the collection is NOT updated so a previously stored good value is preserved.
    """
    try:
        raw = provider.get_max_metrics(user_id, date=target_date)
        vo2max = GarminVO2Max.from_max_metrics(raw)
        if vo2max.vo2max_running is None:
            logger.info(
                "[Garmin] _fetch_and_persist_vo2max: no value in payload, skipping write user=%s requested_date=%s",
                user_id,
                target_date,
            )
            return None
        await _persist_vo2max(db, user_id, vo2max)
        return vo2max.vo2max_running
    except Exception:
        logger.exception(
            "[Garmin] _fetch_and_persist_vo2max failed user=%s requested_date=%s",
            user_id,
            target_date,
        )
        return None


async def _backfill_historical_vo2max_for_running_days(
    db,
    user_id: str,
    provider,
    *,
    activities: Optional[list[dict]] = None,
    reference_date: Optional[date] = None,
) -> int:
    today = reference_date or datetime.now(timezone.utc).date()
    cutoff_day = _subtract_months(today, INITIAL_VO2MAX_BACKFILL_MONTHS)
    source_activities = activities
    if source_activities is None:
        source_activities = await (
            db.garmin_activities.find(
                {"user_id": user_id},
                {"_id": 0, "activity_type": 1, "start_time": 1, "date": 1},
            ).to_list(None)
        )

    running_days = sorted(
        {
            activity_day.isoformat()
            for activity in source_activities
            if _is_running_activity(activity)
            for activity_day in [_parse_activity_day(activity)]
            if activity_day is not None and cutoff_day <= activity_day <= today
        }
    )
    if not running_days:
        logger.info("[Garmin] VO2max initial backfill skipped user=%s running_days=0", user_id)
        return 0

    hits = 0
    for activity_day in running_days:
        if await _fetch_and_persist_vo2max(db, user_id, provider, target_date=activity_day) is not None:
            hits += 1
    logger.info(
        "[Garmin] VO2max initial backfill complete user=%s running_days=%d persisted_days=%d",
        user_id,
        len(running_days),
        hits,
    )
    return hits


async def _build_and_persist_capabilities(db, user_id: str) -> None:
    """Build GarminCapabilities from already-stored daily metrics and persist them.

    Uses ONLY data already in garmin_daily_metrics / garmin_vo2max — no new
    gccli calls.

    Stored shapes (from GarminDailyMetrics.model_dump):
    - ``hrv``          : scalar float (lastNightAvg or weeklyAvg) → reconstituted as
                         ``{"hrvSummary": {"lastNightAvg": val}}`` for from_probe
    - ``stress``       : int (avgStressLevel, Garmin -1/-2 stripped at storage time,
                         but stored as None when absent) → reconstituted as
                         ``{"avgStressLevel": val}``
    - ``body_battery`` : int scalar → passed directly (from_probe uses _has_data)

    VO2max:
    - ``vo2max_running``: scalar float stored in garmin_vo2max → reconstituted as
                          ``[{"vo2MaxValue": val}]`` proxy for from_probe
    """
    latest_hrv_doc = await db.garmin_daily_metrics.find_one(
        {"user_id": user_id, "hrv": {"$ne": None}},
        {"_id": 0, "hrv": 1},
        sort=[("date", -1)],
    )
    hrv_val = (latest_hrv_doc or {}).get("hrv")
    # hrv_val is a scalar float stored by GarminDailyMetrics; wrap into the shape
    # expected by GarminCapabilities._hrv_ok ({"hrvSummary": {"lastNightAvg": ...}}).
    hrv_payload = {"hrvSummary": {"lastNightAvg": hrv_val}} if hrv_val is not None else {}

    latest_bb_doc = await db.garmin_daily_metrics.find_one(
        {"user_id": user_id, "body_battery": {"$ne": None}},
        {"_id": 0, "body_battery": 1},
        sort=[("date", -1)],
    )
    bb_val = (latest_bb_doc or {}).get("body_battery")

    latest_stress_doc = await db.garmin_daily_metrics.find_one(
        {"user_id": user_id, "stress": {"$ne": None}},
        {"_id": 0, "stress": 1},
        sort=[("date", -1)],
    )
    stress_val = (latest_stress_doc or {}).get("stress")
    # stress_val is the int already stripped of Garmin -1/-2 sentinels at storage
    # time; wrap into the shape expected by GarminCapabilities._stress_ok.
    stress_payload = {"avgStressLevel": stress_val} if stress_val is not None else {}

    # Native Garmin running VO₂max: read the most recent valid point from the
    # sparse history stored in garmin_vo2max (sorted by measurement date DESC).
    # The garmin_vo2max collection is updated by _fetch_and_persist_vo2max during sync.
    vo2max_doc = await db.garmin_vo2max.find_one(
        {"user_id": user_id, "vo2max_running": {"$ne": None}},
        {"_id": 0, "vo2max_running": 1},
        sort=[("date", -1)],
    )
    vo2max_val = (vo2max_doc or {}).get("vo2max_running")
    max_metrics_proxy = [{"vo2MaxValue": vo2max_val}] if vo2max_val is not None else []

    capabilities = GarminCapabilities.from_probe(
        hrv=hrv_payload,
        body_battery=bb_val,
        stress=stress_payload,
        max_metrics=max_metrics_proxy,
    )
    await _persist_capabilities(db, user_id, capabilities)
    logger.info("[Garmin] capabilities persisted user=%s %s", user_id, capabilities.model_dump())


def _derive_garmin_identity_from_profile(profile: dict) -> Optional[str]:
    """Derive canonical Garmin identity from server-side gccli auth status."""
    email = (profile or {}).get("email")
    if not email:
        return None
    normalized = str(email).strip().lower()
    return normalized or None


async def _get_garmin_account(db, user_id: str) -> Optional[str]:
    """Look up the stored Garmin username for a RunIndex user."""
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0, "garmin_username": 1})
    return conn.get("garmin_username") if conn else None


async def connect(db, user_id: str, garmin_username: Optional[str] = None,
                  garmin_password: Optional[str] = None,
                  simulate_mfa: bool = False) -> dict:
    provider = get_provider_for_user(user_id, garmin_account=garmin_username)
    result = provider.connect(
        user_id,
        garmin_username=garmin_username,
        garmin_password=garmin_password,
        simulate_mfa=simulate_mfa,
    )

    if result.status == STATUS_CONNECTED:
        update_doc: dict = {
            "user_id": user_id,
            "connected": True,
            "provider": active_provider_name(),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        # Persist the Garmin username so subsequent syncs can build the
        # per-user provider without re-asking for credentials.
        if garmin_username:
            update_doc["garmin_username"] = garmin_username
        await db.garmin_connections.update_one(
            {"user_id": user_id},
            {"$set": update_doc},
            upsert=True,
        )

        # Persist the freshly-created gccli session so out-of-process workers
        # (possibly on another host) can hydrate it before syncing.
        await session_store.save_session(db, user_id)

        # Trial identity must come from server-side gccli auth status, never from
        # frontend-provided username/email.
        try:
            profile = provider.get_profile(user_id)
            garmin_identity = _derive_garmin_identity_from_profile(profile)
            if garmin_identity:
                await activate_garmin_trial(db, user_id, garmin_identity)
            else:
                logger.warning(
                    "[GarminTrial] Missing authenticated Garmin email for user=%s; trial not activated",
                    user_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[GarminTrial] Trial activation failed for user=%s",
                user_id,
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


async def _persist_daily_metrics(db, user_id: str, metrics: list[dict]) -> int:
    metrics_count = 0
    for metric in metrics:
        day = metric.get("date")
        if not day:
            continue
        await db.garmin_daily_metrics.update_one(
            {"user_id": user_id, "date": day},
            {"$set": {**metric, "user_id": user_id, "synced_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        metrics_count += 1
    return metrics_count


def _has_usable_physio_data(metrics: list[dict]) -> bool:
    for metric in metrics:
        if any(metric.get(key) is not None for key in ("hrv", "resting_hr", "sleep_hours", "sleep_score")):
            return True
    return False


async def _current_activity_count(db, user_id: str) -> int:
    return await db.garmin_activities.count_documents({"user_id": user_id})


async def _safe_save_session(db, user_id: str) -> None:
    try:
        await session_store.save_session(db, user_id)
    except Exception as exc:
        logger.warning("[Garmin] session persist skipped user=%s: %s", user_id, exc)


async def _mark_sync_failed(user_id: str, error_code: str, **fields) -> None:
    await update_sync_progress(
        user_id,
        phase="failed",
        error_code=error_code,
        readiness_status=fields.pop("readiness_status", "unavailable"),
        **fields,
    )


def _resume_phase_from_progress(progress: Optional[dict]) -> Optional[str]:
    if not progress:
        return None
    if progress.get("run_index_status") != "ready":
        return None
    if progress.get("daily_metrics_status") not in {"failed", "pending"}:
        return None
    if progress.get("readiness_status") == "ready":
        return "metrics_enrichment"
    return "metrics_7d"


async def _complete_post_activities_pipeline(
    db,
    user_id: str,
    provider,
    *,
    activity_count: int,
    synced_count: int,
    new_count: int,
    deep_sync: bool = False,
    resume_from: Optional[str] = None,
    activities: Optional[list[dict]] = None,
) -> dict:
    metrics_count = 0
    history_backfill = None
    run_index_refresh = None
    readiness_payload = None
    readiness_status = "pending"
    daily_metrics_status = "pending"

    if resume_from not in {"metrics_7d", "metrics_enrichment"}:
        await update_sync_progress(
            user_id,
            phase="activities_ready",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="pending",
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        )
        run_index_refresh = await refresh_today_run_index_after_garmin_activities(db, user_id)
        run_index_value = (run_index_refresh.get("today_snapshot") or {}).get("run_index")
        await update_sync_progress(
            user_id,
            phase="run_index_ready",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="ready",
            run_index=run_index_value,
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        )

    try:
        if resume_from != "metrics_enrichment":
            await update_sync_progress(
                user_id,
                phase="metrics_7d_fetching",
                activities_status="ready",
                activities_count=activity_count,
                run_index_status="ready",
                daily_metrics_status="pending",
                readiness_status="pending",
                error_code=None,
            )
            metrics_7d = list(provider.get_daily_metrics(
                user_id,
                days=INITIAL_DAILY_METRICS_DAYS,
                start_days_ago=1,
            ))
            metrics_count += await _persist_daily_metrics(db, user_id, metrics_7d)
            # First sync backfills sparse Garmin VO₂max history from distinct running
            # days over the last 12 months; regular syncs keep the lightweight latest-only fetch.
            vo2max_backfill_days = 0
            if deep_sync:
                vo2max_backfill_days = await _backfill_historical_vo2max_for_running_days(
                    db,
                    user_id,
                    provider,
                    activities=activities,
                )
            if not deep_sync or vo2max_backfill_days == 0:
                await _fetch_and_persist_vo2max(db, user_id, provider)
            await _build_and_persist_capabilities(db, user_id)
            readiness_payload = await compute_run_index(db, user_id)
            has_usable_physio = _has_usable_physio_data(metrics_7d)
            daily_metrics_status = "ready" if has_usable_physio else "no_usable_data"
            # V2: score present (not None) → ready; score None (INSUFFICIENT) → unavailable.
            readiness_value = ((readiness_payload or {}).get("metrics") or {}).get("run_readiness") if readiness_payload else None
            readiness_status = "ready" if has_usable_physio and readiness_value is not None else "unavailable"
            await update_sync_progress(
                user_id,
                phase="readiness_ready" if readiness_status == "ready" else "readiness_unavailable",
                activities_status="ready",
                activities_count=activity_count,
                run_index_status="ready",
                daily_metrics_status=daily_metrics_status,
                readiness_status=readiness_status,
                readiness=readiness_value,
                error_code=None,
            )
        else:
            progress = await get_sync_progress(user_id) or {}
            daily_metrics_status = progress.get("daily_metrics_status", "ready")
            readiness_status = progress.get("readiness_status", "ready")

        await update_sync_progress(
            user_id,
            phase="enriching",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="ready",
            daily_metrics_status=daily_metrics_status,
            readiness_status=readiness_status,
            error_code=None,
        )
        metrics_30d = list(provider.get_daily_metrics(
            user_id,
            days=ENRICHMENT_DAILY_METRICS_DAYS,
            start_days_ago=ENRICHMENT_DAILY_METRICS_START_DAYS_AGO,
        ))
        metrics_count += await _persist_daily_metrics(db, user_id, metrics_30d)
        await _build_and_persist_capabilities(db, user_id)
        history_backfill = await backfill_run_index_history_after_garmin_sync(db, user_id)
        # Invalidate the dashboard insight cache so the next GET /dashboard/insight
        # recomputes RunIndex from the freshly persisted data (PR181: CACHE_STALE_RUNINDEX).
        _dic.invalidate_user(user_id)
        # Self-heal db.workouts for legacy consumers — decoupled from RunIndex.
        # RunIndex is already computed from garmin_activities above; this call
        # only rebuilds the derived workouts layer and never feeds RunIndex.
        try:
            await _backfill_workouts_user(db, user_id, prune=False)
        except Exception:
            logger.exception("[Garmin] workouts self-heal failed user=%s", user_id)
        await update_sync_progress(
            user_id,
            phase="complete",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="ready",
            daily_metrics_status=daily_metrics_status,
            readiness_status=readiness_status,
            error_code=None,
        )
        return {
            "success": True,
            "status": "complete",
            "synced_count": synced_count,
            "new_count": new_count,
            "metrics_count": metrics_count,
            "activities_status": "ready",
            "run_index_status": "ready",
            "daily_metrics_status": daily_metrics_status,
            "readiness_status": readiness_status,
            "message": f"Imported {synced_count} activities",
            "deep_sync": deep_sync,
            "today_snapshot": None if run_index_refresh is None else run_index_refresh.get("today_snapshot"),
            "history_backfill": history_backfill,
        }
    except Exception as exc:
        phase_error_code = "daily_metrics_enrichment_failed"
        if resume_from != "metrics_enrichment" and daily_metrics_status == "pending":
            phase_error_code = "daily_metrics_7d_failed"
        await update_sync_progress(
            user_id,
            phase="partial_success",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="ready",
            daily_metrics_status="failed",
            readiness_status="ready" if readiness_status == "ready" else "unavailable",
            error_code=phase_error_code,
        )
        logger.warning("[Garmin] phased metrics sync partial user=%s: %s", user_id, exc)
        return {
            "success": True,
            "status": "partial_success",
            "synced_count": synced_count,
            "new_count": new_count,
            "metrics_count": metrics_count,
            "activities_status": "ready",
            "run_index_status": "ready",
            "daily_metrics_status": "failed",
            "readiness_status": "ready" if readiness_status == "ready" else "unavailable",
            "error": phase_error_code,
            "message": "Activities and RunIndex ready; daily metrics incomplete",
            "deep_sync": deep_sync,
        }


async def deep_sync(db, user_id: str) -> dict:
    """Full historical import for a user's first Garmin connection.

    Fetches ALL available Garmin activities using paginated gccli calls, then
    ingests them through the standard pipeline (garmin_activities → ACTIVITY_CREATED
    events → workouts → RunIndex history backfill).

    This function is only triggered once per user (gated by the `deep_sync_done`
    flag in garmin_connections). Subsequent syncs use the lightweight incremental
    path. Never call this directly for regular syncs.
    """
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn or not conn.get("connected"):
        return {
            "success": False, "synced_count": 0, "metrics_count": 0,
            "message": "Garmin not connected",
        }

    page_size = int(os.environ.get("GARMIN_PAGE_SIZE", "50"))
    garmin_account = conn.get("garmin_username")
    provider = get_provider_for_user(user_id, garmin_account=garmin_account)

    logger.info("[Garmin] deep sync starting user=%s page_size=%d", user_id, page_size)
    try:
        await update_sync_progress(
            user_id,
            phase="activities_fetching",
            activities_status="pending",
            run_index_status="pending",
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        )
        activities = provider.fetch_all_activities(page_size=page_size)
    except Exception as exc:
        logger.error("[Garmin] deep sync fetch failed user=%s: %s", user_id, exc)
        await _mark_sync_failed(
            user_id,
            "activities_fetch_failed",
            activities_status="failed",
            run_index_status="failed",
            daily_metrics_status="pending",
        )
        return {
            "success": False, "synced_count": 0, "metrics_count": 0,
            "message": "Deep sync failed, please reconnect",
        }

    ingest = await _ingest_activities(db, user_id, activities)

    # Mark deep sync done so subsequent syncs use the incremental path.
    await db.garmin_connections.update_one(
        {"user_id": user_id},
        {"$set": {"deep_sync_done": True}},
    )
    activity_count = await _finalize_connection(db, user_id, ingest["newest_start"])
    try:
        try:
            result = await _complete_post_activities_pipeline(
                db,
                user_id,
                provider,
                activity_count=activity_count,
                synced_count=ingest["synced"],
                new_count=ingest["new"],
                deep_sync=True,
                activities=activities,
            )
            result["message"] = f"Deep sync: imported {ingest['synced']} activities"
            return result
        except Exception as exc:
            logger.error("[Garmin] deep sync run-index refresh failed user=%s: %s", user_id, exc)
            await _mark_sync_failed(
                user_id,
                "run_index_refresh_failed",
                activities_status="ready",
                activities_count=activity_count,
                run_index_status="failed",
                daily_metrics_status="pending",
            )
            return {
                "success": False,
                "synced_count": ingest["synced"],
                "new_count": ingest["new"],
                "metrics_count": 0,
                "message": "RunIndex refresh failed",
            }
    finally:
        await _safe_save_session(db, user_id)


async def sync(db, user_id: str, since: Optional[str] = None) -> dict:
    """Full Garmin sync (activities + daily metrics), used for manual triggers.

    Executed by the out-of-process worker (workers/sync_worker.py), never in the
    API request flow. Writes only the ingestion layer (`garmin_activities`) and
    emits ACTIVITY_CREATED events; the `workouts` product layer + feed cache are
    built asynchronously by the fan-out event worker.

    On the first sync for a user (deep_sync_done not set) and when
    GARMIN_DEEP_SYNC_ENABLED=true, this delegates to deep_sync() to import the
    full available history. Subsequent calls use the standard single-page fetch.
    """
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn or not conn.get("connected"):
        return {"success": False, "synced_count": 0, "metrics_count": 0, "message": "Garmin not connected"}

    # Hydrate the gccli session from Mongo when running out-of-process (worker on
    # another host). If no usable session exists, degrade gracefully.
    if not await session_store.ensure_session(db, user_id):
        logger.warning("[Garmin] no gccli session available for user=%s — reconnect required", user_id)
        await _mark_sync_failed(
            user_id,
            "session_unavailable",
            activities_status="failed",
            run_index_status="failed",
            daily_metrics_status="failed",
        )
        return {"success": False, "synced_count": 0, "metrics_count": 0,
                "message": "Garmin session unavailable, please reconnect", "error": "session_unavailable"}

    resume_from = _resume_phase_from_progress(await get_sync_progress(user_id))

    # First-connection deep sync: enabled by default, triggered once per user.
    deep_sync_enabled = os.environ.get("GARMIN_DEEP_SYNC_ENABLED", "true").lower() not in (
        "0", "false", "no",
    )
    if deep_sync_enabled and not conn.get("deep_sync_done") and resume_from is None:
        logger.info("[Garmin] first sync detected for user=%s — starting deep sync", user_id)
        return await deep_sync(db, user_id)

    garmin_account = conn.get("garmin_username")
    provider = get_provider_for_user(user_id, garmin_account=garmin_account)

    if resume_from in {"metrics_7d", "metrics_enrichment"}:
        logger.info("[Garmin] resuming phased sync user=%s from=%s", user_id, resume_from)
        try:
            return await _complete_post_activities_pipeline(
                db,
                user_id,
                provider,
                activity_count=await _current_activity_count(db, user_id),
                synced_count=0,
                new_count=0,
                deep_sync=False,
                resume_from=resume_from,
            )
        finally:
            await _safe_save_session(db, user_id)

    # --- Activities ---
    try:
        await update_sync_progress(
            user_id,
            phase="activities_fetching",
            activities_status="pending",
            run_index_status="pending",
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        )
        activities = provider.sync_activities(user_id, since=since)
    except Exception as exc:  # provider/runner failures -> graceful
        logger.error("[Garmin] activity sync failed user=%s: %s", user_id, exc)
        await _mark_sync_failed(
            user_id,
            "activities_fetch_failed",
            activities_status="failed",
            run_index_status="failed",
            daily_metrics_status="pending",
        )
        return {"success": False, "synced_count": 0, "metrics_count": 0, "message": "Sync failed, please reconnect"}

    ingest = await _ingest_activities(db, user_id, activities)
    activity_count = await _finalize_connection(db, user_id, ingest["newest_start"])
    try:
        try:
            result = await _complete_post_activities_pipeline(
                db,
                user_id,
                provider,
                activity_count=activity_count,
                synced_count=ingest["synced"],
                new_count=ingest["new"],
                deep_sync=False,
                activities=activities,
            )
            logger.info(
                "[Garmin] synced %d activities (%d new), %d daily metrics user=%s status=%s",
                ingest["synced"],
                ingest["new"],
                result.get("metrics_count"),
                user_id,
                result.get("status"),
            )
            return result
        except Exception as exc:
            logger.error("[Garmin] run-index refresh failed user=%s: %s", user_id, exc)
            await _mark_sync_failed(
                user_id,
                "run_index_refresh_failed",
                activities_status="ready",
                activities_count=activity_count,
                run_index_status="failed",
                daily_metrics_status="pending",
            )
            return {
                "success": False,
                "synced_count": ingest["synced"],
                "new_count": ingest["new"],
                "metrics_count": 0,
                "message": "RunIndex refresh failed",
            }
    finally:
        await _safe_save_session(db, user_id)


async def incremental_sync(db, user_id: str) -> dict:
    """Incremental sync: fetch ONLY activities newer than the last stored one.

    Uses `since = last_activity_timestamp` so Garmin API usage stays flat (small
    payload) vs a full re-sync. Activities-only (no daily-metrics fetch) to keep
    the batch light; dedupe + event emission happen in _ingest_activities.
    """
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn or not conn.get("connected"):
        return {"success": False, "synced_count": 0, "new_count": 0, "message": "Garmin not connected"}

    if not await session_store.ensure_session(db, user_id):
        logger.warning("[Garmin] no gccli session available for user=%s — reconnect required", user_id)
        await _mark_sync_failed(
            user_id,
            "session_unavailable",
            activities_status="failed",
            run_index_status="failed",
            daily_metrics_status="failed",
        )
        return {"success": False, "synced_count": 0, "new_count": 0,
                "message": "Garmin session unavailable, please reconnect", "error": "session_unavailable"}

    last = await db.garmin_activities.find_one(
        {"user_id": user_id}, {"_id": 0, "start_time": 1}, sort=[("start_time", -1)]
    )
    since = last.get("start_time") if last else None

    garmin_account = conn.get("garmin_username")
    provider = get_provider_for_user(user_id, garmin_account=garmin_account)
    try:
        await update_sync_progress(
            user_id,
            phase="activities_fetching",
            activities_status="pending",
            run_index_status="pending",
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        )
        activities = provider.sync_activities(user_id, since=since)
    except Exception as exc:
        logger.error("[Garmin] incremental sync failed user=%s: %s", user_id, exc)
        await _mark_sync_failed(
            user_id,
            "activities_fetch_failed",
            activities_status="failed",
            run_index_status="failed",
            daily_metrics_status="pending",
        )
        return {"success": False, "synced_count": 0, "new_count": 0, "message": "Sync failed"}

    ingest = await _ingest_activities(db, user_id, activities)
    activity_count = await _finalize_connection(db, user_id, ingest["newest_start"])
    try:
        refreshed = await refresh_today_run_index_after_garmin_activities(db, user_id)
        await backfill_run_index_history_after_garmin_sync(db, user_id)
        # Invalidate the dashboard insight cache so the next GET /dashboard/insight
        # recomputes RunIndex from the freshly persisted data (PR181: CACHE_STALE_RUNINDEX).
        _dic.invalidate_user(user_id)
        # Self-heal db.workouts for legacy consumers — decoupled from RunIndex.
        try:
            await _backfill_workouts_user(db, user_id, prune=False)
        except Exception:
            logger.exception("[Garmin] workouts self-heal failed user=%s", user_id)
        await update_sync_progress(
            user_id,
            phase="complete",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="ready",
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        )
    except Exception as exc:
        logger.error("[Garmin] incremental run-index refresh failed user=%s: %s", user_id, exc)
        await _mark_sync_failed(
            user_id,
            "run_index_refresh_failed",
            activities_status="ready",
            activities_count=activity_count,
            run_index_status="failed",
            daily_metrics_status="pending",
        )
        return {
            "success": False,
            "synced_count": ingest["synced"],
            "new_count": ingest["new"],
            "metrics_count": 0,
            "message": "RunIndex refresh failed",
        }
    await _safe_save_session(db, user_id)
    logger.info("[Garmin] incremental synced=%d new=%d user=%s since=%s",
                ingest["synced"], ingest["new"], user_id, since)
    return {
        "success": True,
        "status": "complete",
        "synced_count": ingest["synced"],
        "new_count": ingest["new"],
        "metrics_count": 0,
        "message": f"{ingest['new']} new activities",
    }


async def get_status(db, user_id: str) -> dict:
    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    sync_status = await get_sync_progress(user_id)
    if not conn:
        return {
            "connected": False,
            "provider": active_provider_name(),
            "last_sync": None,
            "activity_count": 0,
            "sync_status": sync_status,
        }
    return {
        "connected": bool(conn.get("connected")),
        "provider": conn.get("provider", active_provider_name()),
        "last_sync": conn.get("last_sync"),
        "activity_count": conn.get("activity_count", 0),
        "garmin_capabilities": conn.get("garmin_capabilities"),
        "capabilities_updated_at": conn.get("capabilities_updated_at"),
        "sync_status": sync_status,
    }


async def disconnect(db, user_id: str) -> dict:
    await db.garmin_connections.delete_one({"user_id": user_id})
    await db.garmin_activities.delete_many({"user_id": user_id})
    await db.garmin_daily_metrics.delete_many({"user_id": user_id})
    # Remove mirrored Garmin workouts only (keep manual/other-source workouts)
    await db.workouts.delete_many({"user_id": user_id, "data_source": "garmin"})
    # Remove the stored gccli session (isolation + no stale token reuse).
    await session_store.delete_session(db, user_id)
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
