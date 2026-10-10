from __future__ import annotations

import logging
import math
from typing import Any, Optional

from activity_phases import ACTIVITY_PHASE_SCHEMA_VERSION, ActivityPhase
from workout_analysis_v2 import (
    SIMILAR_HISTORY_WINDOW_DAYS,
    WorkoutAnalysisV2Response,
    build_workout_analysis_v2,
    workout_analysis_candidate_date_bounds,
)

logger = logging.getLogger(__name__)


def _safe_hr(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        if math.isfinite(f) and f > 0:
            return int(round(f))
    except (ValueError, TypeError):
        pass
    return None


def _safe_elevation(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        if math.isfinite(f) and f >= 0:
            return round(f, 1)
    except (ValueError, TypeError):
        pass
    return None


def _safe_speed_kmh(candidates: dict[str, Any]) -> Optional[float]:
    for k in ("avg_speed_kmh", "average_speed_kmh"):
        v = candidates.get(k)
        if v is not None and not isinstance(v, bool):
            try:
                f = float(v)
                if math.isfinite(f) and f > 0:
                    return round(f, 2)
            except (ValueError, TypeError):
                pass
    for k in ("average_speed_mps", "average_moving_speed_mps", "averageSpeed"):
        v = candidates.get(k)
        if v is not None and not isinstance(v, bool):
            try:
                f = float(v)
                if math.isfinite(f) and f > 0:
                    return round(f * 3.6, 2)
            except (ValueError, TypeError):
                pass
    return None


def _safe_cadence(candidates: dict[str, Any]) -> Optional[float]:
    for k in (
        "avg_cadence_spm",
        "average_run_cadence",
        "averageRunningCadenceInStepsPerMinute",
        "cadence",
    ):
        v = candidates.get(k)
        if v is not None and not isinstance(v, bool):
            try:
                f = float(v)
                if math.isfinite(f) and f > 0:
                    return round(f, 1)
            except (ValueError, TypeError):
                pass
    return None


def _is_garmin_workout(workout: dict[str, Any]) -> bool:
    workout_id = str(workout.get("id") or "")
    data_source = str(workout.get("data_source") or "").lower()
    return workout_id.startswith("garmin-") or data_source == "garmin"


def _extract_garmin_external_id(workout: dict[str, Any]) -> Optional[str]:
    ext_id = workout.get("external_id")
    if ext_id is not None and str(ext_id).strip():
        return str(ext_id).strip()
    workout_id = str(workout.get("id") or "")
    if workout_id.startswith("garmin-"):
        suffix = workout_id[len("garmin-"):].strip()
        if suffix:
            return suffix
    return None


async def _fetch_garmin_activity(db: Any, user_id: str, external_id: str) -> Optional[dict[str, Any]]:
    if db is None or not hasattr(db, "garmin_activities"):
        return None
    activity = await db.garmin_activities.find_one(
        {"user_id": user_id, "external_id": external_id},
        {"_id": 0},
    )
    if activity is None and external_id.isdigit():
        activity = await db.garmin_activities.find_one(
            {"user_id": user_id, "external_id": int(external_id)},
            {"_id": 0},
        )
    if activity is None:
        activity = await db.garmin_activities.find_one(
            {"user_id": user_id, "activity_id": external_id},
            {"_id": 0},
        )
    return activity


def enrich_workout_from_garmin_activity(
    workout: dict[str, Any],
    activity_doc: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(workout)
    garmin_sub = activity_doc.get("garmin_activity")
    raw_payload = activity_doc.get("raw_payload")
    sub_dict = garmin_sub if isinstance(garmin_sub, dict) else {}
    payload_dict = raw_payload if isinstance(raw_payload, dict) else {}
    candidates = {**payload_dict, **sub_dict, **activity_doc}

    # Max HR
    if enriched.get("max_heart_rate") is None:
        for k in ("max_heart_rate", "max_heartrate", "max_hr", "maxHR"):
            val = _safe_hr(candidates.get(k))
            if val is not None:
                enriched["max_heart_rate"] = val
                if enriched.get("max_hr") is None:
                    enriched["max_hr"] = val
                break

    # Avg HR
    if enriched.get("avg_heart_rate") is None:
        for k in ("avg_heart_rate", "average_hr", "average_heartrate", "avg_hr", "averageHR"):
            val = _safe_hr(candidates.get(k))
            if val is not None:
                enriched["avg_heart_rate"] = val
                if enriched.get("avg_hr") is None:
                    enriched["avg_hr"] = val
                break

    # Elevation gain (preserve true zeros 0.0)
    if enriched.get("elevation_gain_m") is None:
        for k in ("elevation_gain_m", "elevation_gain", "total_elevation_gain_m", "elevationGain"):
            val = _safe_elevation(candidates.get(k))
            if val is not None:
                enriched["elevation_gain_m"] = val
                break

    # Avg speed (km/h)
    if enriched.get("avg_speed_kmh") is None:
        speed = _safe_speed_kmh(candidates)
        if speed is not None:
            enriched["avg_speed_kmh"] = speed

    # Avg cadence (spm)
    if enriched.get("avg_cadence_spm") is None:
        cadence = _safe_cadence(candidates)
        if cadence is not None:
            enriched["avg_cadence_spm"] = cadence

    # Effort zone distribution
    if enriched.get("effort_zone_distribution") is None:
        for k in ("effort_zone_distribution", "hr_zones", "time_in_zones"):
            val = candidates.get(k)
            if isinstance(val, dict) and val:
                enriched["effort_zone_distribution"] = val
                break

    # Splits
    if enriched.get("km_splits") is None:
        for k in ("km_splits", "splits"):
            val = candidates.get(k)
            if isinstance(val, list) and val:
                enriched["km_splits"] = val
                break

    # Deep analyses if available
    for k in ("split_analysis", "hr_analysis", "cadence_analysis", "elevation_analysis", "pace_stats"):
        if enriched.get(k) is None:
            val = candidates.get(k)
            if isinstance(val, dict) and val:
                enriched[k] = val

    # Preserve garmin_activity subdocument if present
    if enriched.get("garmin_activity") is None and isinstance(garmin_sub, dict):
        enriched["garmin_activity"] = garmin_sub

    return enriched


def _cached_activity_phases(activity_doc: dict[str, Any]) -> Optional[list[ActivityPhase]]:
    details = activity_doc.get("activity_details")
    if not isinstance(details, dict):
        return None
    if (
        details.get("schema_version") != ACTIVITY_PHASE_SCHEMA_VERSION
        or details.get("status") != "complete"
        or details.get("source") != "garmin"
        or details.get("endpoint") != "typed-splits"
    ):
        return None
    raw_phases = details.get("phases")
    if not isinstance(raw_phases, list) or not raw_phases or len(raw_phases) > 1000:
        return None

    phases: list[ActivityPhase] = []
    previous_order = -1
    try:
        for index, raw in enumerate(raw_phases):
            if not isinstance(raw, dict):
                return None
            order = raw.get("order")
            if (
                isinstance(order, bool) or not isinstance(order, int)
                or order != index or order <= previous_order
            ):
                return None
            previous_order = order
            if raw.get("phase_type") not in {"effort", "recovery", "warmup", "cooldown", "unknown"}:
                return None
            if not isinstance(raw.get("source"), str) or raw["source"] != details["source"]:
                return None
            for key in (
                "duration_s", "distance_m", "average_speed_mps",
                "average_hr", "max_hr", "min_hr",
            ):
                value = raw.get(key)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or value < 0
                ):
                    return None
            if raw.get("native_type") is not None and not isinstance(raw.get("native_type"), str):
                return None
            phases.append(ActivityPhase.model_validate(raw))
    except (OverflowError, TypeError, ValueError):
        return None
    return phases


async def load_scoped_workout_analysis_v2(
    *,
    db: Any,
    user_id: str,
    workout_id: str,
    language: str,
) -> Optional[tuple[dict[str, Any], Optional[WorkoutAnalysisV2Response]]]:
    workout = await db.workouts.find_one(
        {"id": workout_id, "user_id": user_id},
        {"_id": 0},
    )
    if workout is None:
        return None

    phases = None
    if _is_garmin_workout(workout):
        ext_id = _extract_garmin_external_id(workout)
        if ext_id:
            activity_doc = await _fetch_garmin_activity(db, user_id, ext_id)
            if activity_doc:
                workout = enrich_workout_from_garmin_activity(workout, activity_doc)
                phases = _cached_activity_phases(activity_doc)

    try:
        lower_bound, upper_bound = workout_analysis_candidate_date_bounds(
            workout.get("date", ""),
            days=SIMILAR_HISTORY_WINDOW_DAYS,
        )
        historical_workouts = await (
            db.workouts.find(
                {
                    "user_id": user_id,
                    "type": workout.get("type"),
                    "date": {"$gte": lower_bound, "$lt": upper_bound},
                },
                {"_id": 0},
            )
            .sort("date", -1)
            .to_list(length=200)
        )
        analysis = build_workout_analysis_v2(
            workout=workout,
            historical_workouts=historical_workouts,
            language=language,
            phases=phases,
        )
    except Exception:
        logger.exception(
            "Workout Analysis V2 unavailable for workout_id=%s",
            workout_id,
        )
        analysis = None
    return workout, analysis
