"""
Terra Integration Module for CardioCoach
=========================================
Replaces the Strava integration for wearable data aggregation.

Uses the Terra API (https://api.tryterra.co/v2)

Terra endpoints consumed:
  GET /users      → create and retrieve Terra user profiles
  GET /activities → retrieve daily activities
  GET /heartRate  → retrieve HR and RHR data
  GET /sleep      → retrieve sleep data
  GET /daily      → retrieve HRV and other daily metrics
  GET /workouts   → retrieve past workout sessions

Utility functions (async, require a motor ``db`` handle):
  syncDailyMetrics(userId, db)           → sync sleep/HR/HRV metrics from Terra
  computeRecoveryScore(userId, db)       → calculate recovery score and persist it
  computeTrainingLoad(userId, db)        → calculate ACWR/training load and persist it
  generateWorkoutRecommendation(userId, db) → generate and persist workout recommendation

Design:
  - All Terra API calls use a configurable base URL (read from TERRA_API_BASE_URL env var).
  - HRV fallback: if HRV is unavailable, RHR is used instead.
  - Modular: set TERRA_API_BASE_URL to switch between environments.
  - Matches the existing MVC / service-layer architecture.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

# Re-use the pure computation engines that are already in the project.
from engine.readiness_engine import compute_readiness
from engine.training_load_engine import compute_acwr, compute_training_load_score
from engine.workout_selector import select_workout

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Terra API base URL — read from the environment, defaulting to the real Terra API.
TERRA_API_BASE = os.environ.get("TERRA_API_BASE_URL", "https://api.tryterra.co/v2")

# HTTP timeout (seconds) for Terra API requests.
TERRA_TIMEOUT = 20.0


# ---------------------------------------------------------------------------
# Low-level Terra API helpers
# ---------------------------------------------------------------------------

async def _terra_get(endpoint: str, token: str, params: dict | None = None) -> dict | list:
    """Perform an authenticated GET request to the Terra API.

    Parameters
    ----------
    endpoint:
        API path starting with ``/`` (e.g. ``/daily``).
    token:
        Terra user token used as a Bearer credential.
    params:
        Optional query-string parameters.

    Returns
    -------
    Parsed JSON response (dict or list).

    Raises
    ------
    httpx.HTTPStatusError
        When the server responds with a 4xx / 5xx status.
    """
    url = f"{TERRA_API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=TERRA_TIMEOUT) as client:
        response = await client.get(url, headers=headers, params=params or {})
        response.raise_for_status()
        return response.json()


async def fetch_terra_user(token: str) -> dict:
    """Fetch the Terra user profile for the given token.

    Returns the user object from the Terra ``/users`` endpoint.
    Falls back to an empty dict on error so callers can handle gracefully.
    """
    try:
        data = await _terra_get("/users", token)
        # Mock may return a list or a dict with a ``user`` key — normalise.
        if isinstance(data, list):
            return data[0] if data else {}
        return data.get("user", data)
    except Exception as exc:
        logger.warning("Terra /users request failed: %s", exc)
        return {}


async def fetch_terra_activities(token: str, start_date: str | None = None) -> list:
    """Fetch daily activities from Terra ``/activities``.

    Parameters
    ----------
    token:
        Terra user token.
    start_date:
        Optional ISO-8601 date string (``YYYY-MM-DD``) to limit results.

    Returns
    -------
    List of activity dicts.
    """
    try:
        params = {}
        if start_date:
            params["start_date"] = start_date
        data = await _terra_get("/activities", token, params)
        if isinstance(data, list):
            return data
        return data.get("activities", data.get("data", []))
    except Exception as exc:
        logger.warning("Terra /activities request failed: %s", exc)
        return []


async def fetch_terra_heart_rate(token: str) -> dict:
    """Fetch HR and RHR data from Terra ``/heartRate``.

    Returns a dict with at least ``avg_hr`` and ``rhr`` keys (may be None).
    """
    try:
        data = await _terra_get("/heartRate", token)
        if isinstance(data, list):
            return data[0] if data else {}
        return data
    except Exception as exc:
        logger.warning("Terra /heartRate request failed: %s", exc)
        return {}


async def fetch_terra_sleep(token: str) -> dict:
    """Fetch sleep data from Terra ``/sleep``.

    Returns a dict with at least ``duration_hours`` and ``quality_score`` keys.
    """
    try:
        data = await _terra_get("/sleep", token)
        if isinstance(data, list):
            return data[0] if data else {}
        return data
    except Exception as exc:
        logger.warning("Terra /sleep request failed: %s", exc)
        return {}


async def fetch_terra_daily(token: str) -> dict:
    """Fetch HRV and other daily metrics from Terra ``/daily``.

    Returns a dict with at least ``hrv`` key (may be None when unavailable).
    """
    try:
        data = await _terra_get("/daily", token)
        if isinstance(data, list):
            return data[0] if data else {}
        return data
    except Exception as exc:
        logger.warning("Terra /daily request failed: %s", exc)
        return {}


async def fetch_terra_workouts(token: str) -> list:
    """Fetch completed workout sessions from Terra ``/workouts``.

    Returns a list of workout dicts compatible with the internal Workout model.
    """
    try:
        data = await _terra_get("/workouts", token)
        if isinstance(data, list):
            return data
        return data.get("workouts", data.get("data", []))
    except Exception as exc:
        logger.warning("Terra /workouts request failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Terra → internal data converters
# ---------------------------------------------------------------------------

def convert_terra_workout_to_internal(terra_workout: dict, user_id: str) -> dict:
    """Convert a Terra workout payload to the CardioCoach internal workout format.

    Parameters
    ----------
    terra_workout:
        Raw workout dict from the Terra ``/workouts`` endpoint.
    user_id:
        CardioCoach user identifier.

    Returns
    -------
    Dict compatible with the ``workouts`` MongoDB collection schema.
    """
    activity_type_map = {
        "running": "run",
        "run": "run",
        "cycling": "cycle",
        "bike": "cycle",
        "cycle": "cycle",
        "swimming": "swim",
        "swim": "swim",
        "walking": "walk",
        "walk": "walk",
        "strength": "strength",
        "hiit": "hiit",
    }

    raw_type = terra_workout.get("type", terra_workout.get("activity_type", "")).lower()
    workout_type = activity_type_map.get(raw_type, "run")

    # Duration: prefer moving_time, fall back to elapsed_time or duration
    duration_seconds = (
        terra_workout.get("moving_time")
        or terra_workout.get("elapsed_time")
        or terra_workout.get("duration")
        or 0
    )
    duration_minutes = round(duration_seconds / 60, 1) if duration_seconds >= 60 else round(float(duration_seconds) / 60, 1)

    # Distance: convert from metres if value is large, else assume km already
    distance_raw = terra_workout.get("distance", terra_workout.get("distance_km", 0)) or 0
    distance_km = round(distance_raw / 1000, 2) if distance_raw > 1000 else round(float(distance_raw), 2)

    # Heart rate
    avg_hr = terra_workout.get("avg_hr") or terra_workout.get("average_heartrate")
    max_hr = terra_workout.get("max_hr") or terra_workout.get("max_heartrate")

    # Elevation
    elevation = terra_workout.get("elevation_gain") or terra_workout.get("total_elevation_gain")

    # Calories
    calories = terra_workout.get("calories") or terra_workout.get("total_calories")

    # Date
    start_date = (
        terra_workout.get("start_time")
        or terra_workout.get("start_date")
        or terra_workout.get("date")
        or datetime.now(timezone.utc).isoformat()
    )

    terra_id = terra_workout.get("id") or str(uuid.uuid4())

    return {
        "id": f"terra_{terra_id}",
        "user_id": user_id,
        "type": workout_type,
        "date": start_date,
        "duration_minutes": duration_minutes,
        "distance_km": distance_km,
        "avg_heart_rate": avg_hr,
        "max_heart_rate": max_hr,
        "elevation_gain_m": elevation,
        "calories": calories,
        "name": terra_workout.get("name", f"{workout_type.title()} Workout"),
        "data_source": "terra",
        "terra_workout_id": str(terra_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Core utility functions (require async motor db handle)
# ---------------------------------------------------------------------------

async def syncDailyMetrics(user_id: str, db) -> dict:
    """Sync daily health metrics (HRV, RHR, sleep, HR) from Terra for a user.

    Fetches data from Terra ``/heartRate``, ``/sleep``, and ``/daily`` endpoints,
    then upserts a document in the ``daily_metrics`` MongoDB collection.

    Parameters
    ----------
    user_id:
        CardioCoach user identifier.
    db:
        Motor async MongoDB database handle.

    Returns
    -------
    Dict summarising the metrics that were synced:
    ``{"hrv": float|None, "rhr": float|None, "sleep_hours": float|None,
       "sleep_quality": float|None, "avg_hr": float|None, "synced_at": str}``
    """
    # Retrieve the Terra token for the user.
    token_doc = await db.terra_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        logger.warning("syncDailyMetrics: no Terra token for user %s", user_id)
        return {"error": "not_connected"}

    token = token_doc.get("access_token") or token_doc.get("token")

    # Fetch data from Terra in parallel-ish fashion (sequential but simple).
    hr_data = await fetch_terra_heart_rate(token)
    sleep_data = await fetch_terra_sleep(token)
    daily_data = await fetch_terra_daily(token)

    # Extract metrics — use None when unavailable (explicit fallback below).
    hrv = daily_data.get("hrv") or daily_data.get("hrv_rmssd")
    rhr = (
        hr_data.get("rhr")
        or hr_data.get("resting_heart_rate")
        or daily_data.get("rhr")
    )
    avg_hr = hr_data.get("avg_hr") or hr_data.get("average_heart_rate")
    sleep_hours = sleep_data.get("duration_hours") or sleep_data.get("total_sleep_hours")
    sleep_quality = sleep_data.get("quality_score") or sleep_data.get("sleep_efficiency")

    today = datetime.now(timezone.utc).date().isoformat()

    metrics = {
        "user_id": user_id,
        "date": today,
        "hrv": hrv,
        "rhr": rhr,
        "avg_hr": avg_hr,
        "sleep_hours": sleep_hours,
        "sleep_quality": sleep_quality,
        "raw_hr": hr_data,
        "raw_sleep": sleep_data,
        "raw_daily": daily_data,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }

    # Upsert so re-running the sync on the same day overwrites stale data.
    await db.daily_metrics.update_one(
        {"user_id": user_id, "date": today},
        {"$set": metrics},
        upsert=True,
    )

    logger.info("syncDailyMetrics: synced metrics for user %s on %s", user_id, today)
    return {
        "hrv": hrv,
        "rhr": rhr,
        "sleep_hours": sleep_hours,
        "sleep_quality": sleep_quality,
        "avg_hr": avg_hr,
        "synced_at": metrics["synced_at"],
    }


async def computeRecoveryScore(user_id: str, db) -> dict:
    """Calculate and persist the recovery score for a user.

    Uses today's ``daily_metrics`` document plus recent workouts to derive
    a readiness score via ``engine.readiness_engine.compute_readiness``.
    Falls back gracefully when HRV is not available (uses RHR instead).

    Parameters
    ----------
    user_id:
        CardioCoach user identifier.
    db:
        Motor async MongoDB database handle.

    Returns
    -------
    Dict: ``{"recovery_score": float, "fatigue_score": float,
             "readiness": float, "status": str, "computed_at": str}``
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # --- Load today's daily metrics (sync first if missing) ---
    daily_doc = await db.daily_metrics.find_one({"user_id": user_id, "date": today})
    if not daily_doc:
        await syncDailyMetrics(user_id, db)
        daily_doc = await db.daily_metrics.find_one({"user_id": user_id, "date": today}) or {}

    hrv = daily_doc.get("hrv")
    rhr = daily_doc.get("rhr")
    sleep_hours = daily_doc.get("sleep_hours")
    sleep_quality = daily_doc.get("sleep_quality")

    # --- Compute sleep score (0-100) ---
    if sleep_quality is not None:
        sleep_score = float(sleep_quality)
        # Normalise if expressed as 0-1 fraction
        if sleep_score <= 1.0:
            sleep_score *= 100.0
    elif sleep_hours is not None:
        # Heuristic: 8 hours → 80, scale linearly
        sleep_score = min(100.0, float(sleep_hours) * 10.0)
    else:
        sleep_score = 70.0  # Default per readiness_engine convention

    # --- Retrieve baseline RHR (for fallback when HRV unavailable) ---
    baseline_doc = await db.baselines.find_one({"user_id": user_id}) or {}
    baseline_rhr = baseline_doc.get("baseline_rhr")

    # --- Compute training load score ---
    load_result = await computeTrainingLoad(user_id, db)
    training_load_score = load_result.get("training_load_score", 70.0)

    # --- HRV score (0-100): normalise relative to baseline ---
    # At baseline → 100; below baseline → proportionally lower; above baseline → up to 120 (rewarded) but clamped to 100.
    hrv_score: Optional[float] = None
    if hrv is not None:
        baseline_hrv = baseline_doc.get("baseline_hrv")
        if baseline_hrv and float(baseline_hrv) > 0:
            # Ratio > 1 means HRV is above baseline (good recovery) → score > 100 → clamped at 100.
            # Ratio < 1 means below baseline (fatigue) → score drops proportionally.
            ratio = float(hrv) / float(baseline_hrv)
            hrv_score = min(100.0, max(0.0, ratio * 100.0))
        else:
            # No baseline: map typical 20-80 ms absolute HRV range to 0-100.
            hrv_score = min(100.0, max(0.0, (float(hrv) - 20.0) / 60.0 * 100.0))

    # --- Readiness score ---
    readiness = compute_readiness(
        training_load_score=training_load_score,
        sleep_score=sleep_score,
        hrv_score=hrv_score,
        rhr_today=float(rhr) if rhr else None,
        baseline_rhr=float(baseline_rhr) if baseline_rhr else None,
    )

    # --- Derive recovery and fatigue scores ---
    recovery_score = round(readiness, 1)
    fatigue_score = round(100.0 - readiness, 1)

    if readiness >= 75:
        status = "ready"
    elif readiness >= 50:
        status = "moderate"
    else:
        status = "fatigued"

    computed_at = datetime.now(timezone.utc).isoformat()

    result = {
        "user_id": user_id,
        "date": today,
        "recovery_score": recovery_score,
        "fatigue_score": fatigue_score,
        "readiness": readiness,
        "status": status,
        "hrv_available": hrv is not None,
        "computed_at": computed_at,
    }

    # Persist in recovery_scores collection.
    await db.recovery_scores.update_one(
        {"user_id": user_id, "date": today},
        {"$set": result},
        upsert=True,
    )

    logger.info(
        "computeRecoveryScore: user=%s recovery=%.1f fatigue=%.1f status=%s",
        user_id, recovery_score, fatigue_score, status,
    )
    return result


async def computeTrainingLoad(user_id: str, db) -> dict:
    """Calculate and persist the training load (ACWR) for a user.

    Reads the last 28 days of workouts from the ``workouts`` collection,
    computes the Acute:Chronic Workload Ratio, and persists the result in
    the ``training_load`` collection.

    Parameters
    ----------
    user_id:
        CardioCoach user identifier.
    db:
        Motor async MongoDB database handle.

    Returns
    -------
    Dict: ``{"acwr": float, "training_load_score": float,
             "status": str, "computed_at": str}``
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=28)
    cutoff_iso = cutoff.isoformat()

    # Fetch last 28 days of workouts for the user (include workouts with no user_id for
    # backward-compatible imported workouts matching the existing workouts_query pattern).
    workouts = await db.workouts.find(
        {
            "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
            "date": {"$gte": cutoff_iso},
        },
        {"date": 1, "duration_minutes": 1, "distance_km": 1, "_id": 0},
    ).to_list(500)

    if len(workouts) == 500:
        logger.warning(
            "computeTrainingLoad: reached 500-document limit for user %s — results may be truncated",
            user_id,
        )

    acwr = compute_acwr(workouts)
    training_load_score = compute_training_load_score(acwr)

    if acwr > 1.3:
        status = "overtraining_risk"
    elif acwr < 0.8:
        status = "undertraining"
    else:
        status = "optimal"

    computed_at = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    result = {
        "user_id": user_id,
        "date": today,
        "acwr": acwr,
        "training_load_score": training_load_score,
        "status": status,
        "workout_count": len(workouts),
        "computed_at": computed_at,
    }

    await db.training_load.update_one(
        {"user_id": user_id, "date": today},
        {"$set": result},
        upsert=True,
    )

    logger.info(
        "computeTrainingLoad: user=%s acwr=%.3f score=%.1f status=%s",
        user_id, acwr, training_load_score, status,
    )
    return result


async def generateWorkoutRecommendation(user_id: str, db) -> dict:
    """Generate and persist today's workout recommendation for a user.

    Combines the recovery score and training load to call
    ``engine.workout_selector.select_workout`` and stores the result in the
    ``workout_recommendations`` collection.

    Parameters
    ----------
    user_id:
        CardioCoach user identifier.
    db:
        Motor async MongoDB database handle.

    Returns
    -------
    Dict: ``{"type": str, "duration": int, "intensity": str,
             "recovery_score": float, "acwr": float, "computed_at": str}``
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # Compute (or load cached) recovery score and training load.
    recovery_result = await computeRecoveryScore(user_id, db)
    load_result = await computeTrainingLoad(user_id, db)

    readiness = recovery_result.get("readiness", 70.0)
    acwr = load_result.get("acwr", 1.0)

    recommendation = select_workout(readiness, acwr)

    computed_at = datetime.now(timezone.utc).isoformat()

    result = {
        "user_id": user_id,
        "date": today,
        "type": recommendation["type"],
        "duration": recommendation["duration"],
        "intensity": recommendation["intensity"],
        "recovery_score": recovery_result.get("recovery_score"),
        "fatigue_score": recovery_result.get("fatigue_score"),
        "acwr": acwr,
        "readiness": readiness,
        "computed_at": computed_at,
    }

    await db.workout_recommendations.update_one(
        {"user_id": user_id, "date": today},
        {"$set": result},
        upsert=True,
    )

    logger.info(
        "generateWorkoutRecommendation: user=%s type=%s intensity=%s",
        user_id, result["type"], result["intensity"],
    )
    return result


async def syncTerraWorkouts(user_id: str, db) -> dict:
    """Fetch Terra workouts and upsert them into the ``workouts`` collection.

    Parameters
    ----------
    user_id:
        CardioCoach user identifier.
    db:
        Motor async MongoDB database handle.

    Returns
    -------
    Dict: ``{"success": bool, "synced_count": int, "message": str}``
    """
    token_doc = await db.terra_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        return {"success": False, "synced_count": 0, "message": "Not connected to Terra"}

    token = token_doc.get("access_token") or token_doc.get("token")

    terra_workouts = await fetch_terra_workouts(token)
    synced = 0

    for tw in terra_workouts:
        workout = convert_terra_workout_to_internal(tw, user_id)
        existing = await db.workouts.find_one({"id": workout["id"]})
        if not existing:
            await db.workouts.insert_one(workout)
            synced += 1

    # Record sync timestamp.
    await db.sync_history.update_one(
        {"user_id": user_id, "source": "terra"},
        {"$set": {"user_id": user_id, "source": "terra", "synced_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    logger.info("syncTerraWorkouts: user=%s synced=%d new workouts", user_id, synced)
    return {
        "success": True,
        "synced_count": synced,
        "message": f"Synced {synced} new workouts from Terra",
    }
