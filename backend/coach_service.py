"""
RunIndex - Cascade Coaching Service with Cache and Metrics

Strategy:
1. Check cache (0ms)
2. Deterministic analysis (instant) via rag_engine
3. LLM enrichment (~500ms) if available
4. Store in cache + metrics

Usage:
    from coach_service import analyze_workout, weekly_review, chat_response, get_metrics
"""

import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

from llm_coach import (
    enrich_chat_response,
    enrich_weekly_review,
    enrich_workout_analysis,
)
from garmin.domain_adapter import mongo_garmin_activities_to_domain
from training_v2.plan_goal import GoalType, ULTRA_MIN_DISTANCE_KM, build_plan_goal
from training_v2.periodization import build_periodization
from training_v2.runner_profile import build_runner_profile
from training_v2.training_history import build_training_history
from training_v2.training_load import build_training_load
from training_v2.training_paces import compute_training_paces
from training_v2.training_response import build_recent_training_response
from training_v2.training_state import build_training_state
from training_v2.weekly_reconciliation import build_weekly_reconciliation
from training_v2.weekly_target import build_weekly_target
from training_v2.workout_generator import build_weekly_plan
from training_v2.runtime_plan_adapter import (
    adapt_weekly_plan_to_runtime_payload,
    build_runtime_phase_info,
)

logger = logging.getLogger(__name__)


# ============================================================
# METRICS
# ============================================================

@dataclass
class CoachMetrics:
    """Coaching service metrics"""
    llm_success: int = 0
    llm_fallback: int = 0
    cache_hits: int = 0
    total_requests: int = 0
    avg_latency_ms: float = 0.0
    llm_avg_latency_ms: float = 0.0
    cache_avg_latency_ms: float = 0.0
    workout_requests: int = 0
    weekly_requests: int = 0
    chat_requests: int = 0
    plan_requests: int = 0


metrics = CoachMetrics()


def get_metrics() -> dict:
    """Returns current metrics"""
    data = asdict(metrics)
    total_llm = metrics.llm_success + metrics.llm_fallback
    data["llm_success_rate"] = round(metrics.llm_success / total_llm * 100, 1) if total_llm > 0 else 0
    data["cache_hit_rate"] = round(metrics.cache_hits / metrics.total_requests * 100, 1) if metrics.total_requests > 0 else 0
    return data


def reset_metrics() -> dict:
    """Reset metrics"""
    global metrics
    old = get_metrics()
    metrics = CoachMetrics()
    return old


def _update_latency(latency_ms: float, is_llm: bool = False, is_cache: bool = False) -> None:
    """Updates moving average latencies"""
    alpha = 0.1
    metrics.avg_latency_ms = (metrics.avg_latency_ms * (1 - alpha)) + (latency_ms * alpha)
    if is_llm:
        metrics.llm_avg_latency_ms = (metrics.llm_avg_latency_ms * (1 - alpha)) + (latency_ms * alpha)
    if is_cache:
        metrics.cache_avg_latency_ms = (metrics.cache_avg_latency_ms * (1 - alpha)) + (latency_ms * alpha)


# ============================================================
# CACHE CONFIGURATION
# ============================================================

CACHE_TTL_SECONDS = 3600
MAX_CACHE_SIZE = 500

_workout_cache: Dict[str, Tuple[dict, float]] = {}
_weekly_cache: Dict[str, Tuple[dict, float]] = {}
_plan_cache: Dict[str, Tuple[dict, float]] = {}


def _cache_key(data: dict, prefix: str = "") -> str:
    key_parts = [prefix]
    for field in ["id", "distance_km", "duration_minutes", "avg_heart_rate", "type"]:
        key_parts.append(str(data.get(field, "")))
    return hashlib.md5("_".join(key_parts).encode()).hexdigest()


def _is_cache_valid(timestamp: float) -> bool:
    return (time.time() - timestamp) < CACHE_TTL_SECONDS


def _cleanup_cache(cache: dict) -> None:
    if len(cache) > MAX_CACHE_SIZE:
        expired_keys = [k for k, (_, ts) in cache.items() if not _is_cache_valid(ts)]
        for k in expired_keys:
            del cache[k]
        if len(cache) > MAX_CACHE_SIZE:
            sorted_items = sorted(cache.items(), key=lambda x: x[1][1])
            for k, _ in sorted_items[:len(cache) - MAX_CACHE_SIZE]:
                del cache[k]


# ============================================================
# MAIN FUNCTIONS
# ============================================================

async def analyze_workout(
    workout: dict,
    rag_result: dict,
    user_id: Optional[str] = None,
    language: str = "fr"
) -> Tuple[str, bool]:
    """Session analysis with cache + metrics + cascade strategy."""
    start = time.time()
    metrics.total_requests += 1
    metrics.workout_requests += 1
    
    cache_key = _cache_key(workout, f"workout_{language}")
    if cache_key in _workout_cache:
        cached_result, timestamp = _workout_cache[cache_key]
        if _is_cache_valid(timestamp):
            metrics.cache_hits += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_cache=True)
            return cached_result["summary"], cached_result["used_llm"]
    
    deterministic_summary = rag_result.get("summary", "")
    
    try:
        workout_stats = {
            "distance_km": workout.get("distance_km", 0),
            "duration_min": workout.get("duration_minutes", 0),
            "pace": rag_result.get("pace_str", "N/A"),
            "avg_hr": workout.get("avg_heart_rate"),
            "max_hr": workout.get("max_heart_rate"),
            "elevation": workout.get("elevation_gain_m"),
            "type": workout.get("type"),
            "zones": workout.get("effort_zone_distribution", {}),
            "splits": rag_result.get("splits_analysis", {}),
            "comparison": rag_result.get("comparison", {}).get("progression", ""),
            "strengths": rag_result.get("points_forts", []),
            "areas_to_improve": rag_result.get("points_ameliorer", []),
        }
        
        enriched, success, meta = await enrich_workout_analysis(
            workout=workout_stats,
            user_id=user_id,
            language=language
        )
        
        if success and enriched:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            _workout_cache[cache_key] = ({"summary": enriched, "used_llm": True}, time.time())
            _cleanup_cache(_workout_cache)
            return enriched, True
            
    except Exception as e:
        logger.warning(f"[Coach] Session fallback: {e}")
    
    metrics.llm_fallback += 1
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    _workout_cache[cache_key] = ({"summary": deterministic_summary, "used_llm": False}, time.time())
    _cleanup_cache(_workout_cache)
    return deterministic_summary, False


async def weekly_review(
    rag_result: dict,
    user_id: Optional[str] = None,
    language: str = "fr"
) -> Tuple[str, bool]:
    """Weekly review with cache + metrics + cascade strategy."""
    start = time.time()
    metrics.total_requests += 1
    metrics.weekly_requests += 1
    
    m = rag_result.get("metrics", {})
    cache_data = {
        "id": f"weekly_{language}_{m.get('nb_seances', 0)}_{m.get('km_total', 0)}",
        "distance_km": m.get("km_total", 0),
        "duration_minutes": m.get("duree_totale", 0),
    }
    cache_key = _cache_key(cache_data, "weekly")
    
    if cache_key in _weekly_cache:
        cached_result, timestamp = _weekly_cache[cache_key]
        if _is_cache_valid(timestamp):
            metrics.cache_hits += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_cache=True)
            return cached_result["summary"], cached_result["used_llm"]
    
    deterministic_summary = rag_result.get("summary", "")
    
    try:
        weekly_stats = {
            "weekly_km": m.get("km_total", 0),
            "num_sessions": m.get("nb_seances", 0),
            "avg_pace": m.get("allure_moyenne", "N/A"),
            "avg_cadence": m.get("cadence_moyenne", 0),
            "zones": m.get("zones", {}),
            "load_ratio": m.get("ratio", 1.0),
            "strengths": rag_result.get("points_forts", []),
            "areas_to_improve": rag_result.get("points_ameliorer", []),
            "trend": rag_result.get("comparison", {}).get("evolution", "stable"),
        }
        
        enriched, success, meta = await enrich_weekly_review(
            stats=weekly_stats,
            user_id=user_id,
            language=language
        )
        
        if success and enriched:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            _weekly_cache[cache_key] = ({"summary": enriched, "used_llm": True}, time.time())
            _cleanup_cache(_weekly_cache)
            return enriched, True
            
    except Exception as e:
        logger.warning(f"[Coach] Review fallback: {e}")
    
    metrics.llm_fallback += 1
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    _weekly_cache[cache_key] = ({"summary": deterministic_summary, "used_llm": False}, time.time())
    _cleanup_cache(_weekly_cache)
    return deterministic_summary, False


async def chat_response(
    message: str,
    context: dict,
    history: List[dict],
    user_id: str,
    workouts: List[dict] = None,
    user_goal: dict = None
) -> Tuple[str, bool, dict]:
    """Chat response with metrics (no cache)."""
    start = time.time()
    metrics.total_requests += 1
    metrics.chat_requests += 1
    
    try:
        response, success, meta = await enrich_chat_response(
            user_message=message,
            context=context,
            conversation_history=history,
            user_id=user_id
        )
        
        if success and response:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            return response, True, meta
            
    except Exception as e:
        logger.warning(f"[Coach] Chat LLM error: {e}")
    
    metrics.llm_fallback += 1
    language = context.get("language", "en")
    if language == "fr":
        error_msg = "Le service de coaching IA n'est pas disponible actuellement."
    elif language == "es":
        error_msg = "El servicio de coaching con IA no está disponible actualmente."
    else:
        error_msg = "The AI coaching service is currently unavailable."
    return error_msg, False, {}


# ============================================================
# DYNAMIC TRAINING PLAN GENERATION
# ============================================================

_GOAL_REQUIREMENTS = {
    "5K": {"min_weekly_km": 15, "min_vo2max": 35, "base_weeks": 6},
    "10K": {"min_weekly_km": 25, "min_vo2max": 38, "base_weeks": 8},
    "SEMI": {"min_weekly_km": 35, "min_vo2max": 42, "base_weeks": 12},
    "MARATHON": {"min_weekly_km": 50, "min_vo2max": 45, "base_weeks": 16},
    "ULTRA": {"min_weekly_km": 60, "min_vo2max": 48, "base_weeks": 20},
    "MAINTENANCE": {"min_weekly_km": 20, "min_vo2max": 35, "base_weeks": 12},
}

_PHASE_ORDER = {"base": 0, "build": 1, "specific": 2, "taper": 3, "race": 4, "consolidation": 5}
_RUN_ACTIVITY_TYPES = {"running", "trail_running", "treadmill_running", "run", "trail run", "treadmill run"}
_GOAL_MAP = {
    "5K": (GoalType.five_k, "5K"),
    "10K": (GoalType.ten_k, "10K"),
    "SEMI": (GoalType.half_marathon, "SEMI"),
    "HALF_MARATHON": (GoalType.half_marathon, "SEMI"),
    "MARATHON": (GoalType.marathon, "MARATHON"),
    "ULTRA": (GoalType.ultra, "ULTRA"),
    "MAINTENANCE": (GoalType.maintenance, "MAINTENANCE"),
    "MAINTAIN": (GoalType.maintenance, "MAINTENANCE"),
    "MAINTIEN EN FORME": (GoalType.maintenance, "MAINTENANCE"),
}


def _parse_optional_date(value):
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.fromisoformat(value.split("T")[0]).date()
            except ValueError:
                return None
    return None


def _parse_optional_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _to_positive_float(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        if not cleaned:
            return None
        try:
            parsed = float(cleaned)
            return parsed if parsed > 0 else None
        except ValueError:
            return None
    return None


def _extract_ultra_distance_km(cycle: dict, user_goal: dict) -> Optional[float]:
    for source in (cycle or {}, user_goal or {}):
        for key in ("target_distance_km", "distance_km", "event_distance_km"):
            value = _to_positive_float(source.get(key))
            if value is not None:
                return value
    return None


def _is_running_workout(workout: dict) -> bool:
    kind = str(workout.get("activity_type") or workout.get("type") or "").strip().lower()
    if kind in _RUN_ACTIVITY_TYPES:
        return True
    return "run" in kind


def _workout_distance_km(workout: dict) -> float:
    d = _to_positive_float(workout.get("distance_km"))
    if d is not None:
        return d
    dm = _to_positive_float(workout.get("distance_m"))
    if dm is not None:
        return dm / 1000.0
    return 0.0


def _workout_duration_seconds(workout: dict) -> float:
    for key in ("moving_time", "elapsed_time", "duration_s", "duration"):
        v = _to_positive_float(workout.get(key))
        if v is not None:
            return v
    minutes = _to_positive_float(workout.get("duration_minutes"))
    return (minutes or 0.0) * 60.0


def _to_domain_activity_from_workout(workout: dict) -> dict:
    duration_seconds = _workout_duration_seconds(workout)
    raw_start = workout.get("start_time") or workout.get("start_date_local") or workout.get("date")
    parsed_start = _parse_optional_datetime(raw_start)
    if parsed_start is not None:
        start_time = parsed_start.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        start_time = raw_start.split(".")[0] if isinstance(raw_start, str) else raw_start
    return {
        "activity_type": "running" if _is_running_workout(workout) else "other",
        "start_time": start_time,
        "distance_m": _workout_distance_km(workout) * 1000.0 if _workout_distance_km(workout) > 0 else None,
        "duration_s": duration_seconds if duration_seconds > 0 else None,
        "moderate_intensity_minutes": _to_positive_float(workout.get("moderate_intensity_minutes")),
        "vigorous_intensity_minutes": _to_positive_float(workout.get("vigorous_intensity_minutes")),
        "average_hr": _to_positive_float(workout.get("average_hr") or workout.get("avg_heart_rate")),
        "max_hr": _to_positive_float(workout.get("max_hr") or workout.get("max_heart_rate")),
        "elevation_gain_m": _to_positive_float(workout.get("elevation_gain_m")),
    }


def _to_runtime_paces(paces_v2) -> dict:
    paces = {}
    if paces_v2.easy is not None:
        paces["z1"] = f"{paces_v2.easy.lower_str}-{paces_v2.easy.upper_str}"
    if paces_v2.marathon is not None:
        paces["z2"] = paces_v2.marathon.pace_str
        paces["marathon"] = paces_v2.marathon.pace_str
    if paces_v2.threshold is not None:
        paces["z3"] = paces_v2.threshold.pace_str
        paces["semi"] = paces_v2.threshold.pace_str
    if paces_v2.interval is not None:
        paces["z4"] = paces_v2.interval.upper_str
        paces["z5"] = paces_v2.interval.lower_str
    if paces_v2.repetition is not None:
        paces["rep"] = paces_v2.repetition.pace_str
    return paces


async def _load_canonical_performance_signals(db, user_id: str, reference_date) -> tuple[Optional[float], Optional[float], Optional[str], str, dict]:
    vma = None
    vo2max = None
    vma_method = None
    vma_confidence = "insufficient"
    runtime_paces: dict = {}

    garmin_docs = []
    if hasattr(db, "garmin_activities"):
        garmin_docs = await db.garmin_activities.find({"user_id": user_id}, {"_id": 0}).to_list(2000)

    if garmin_docs:
        domain_activities = mongo_garmin_activities_to_domain(garmin_docs)
        paces_v2 = compute_training_paces(domain_activities, reference_date, user_max_hr=None)
        runtime_paces = _to_runtime_paces(paces_v2)

    if hasattr(db, "garmin_vo2max"):
        query = {"user_id": user_id, "vo2max_running": {"$ne": None}}
        projection = {"_id": 0, "vo2max_running": 1}
        try:
            vo2_doc = await db.garmin_vo2max.find_one(
                query,
                projection,
                sort=[("date", -1)],
            )
        except TypeError:
            rows = await db.garmin_vo2max.find(query, projection).sort("date", -1).to_list(1)
            vo2_doc = rows[0] if rows else None
        if vo2_doc:
            vo2max = _to_positive_float(vo2_doc.get("vo2max_running"))

    return vma, vo2max, vma_method, vma_confidence, runtime_paces


def _goal_compatibility_score(goal_label: str, weekly_km: float, vo2max: Optional[float]) -> tuple[float, str, int]:
    req = _GOAL_REQUIREMENTS.get(goal_label, _GOAL_REQUIREMENTS["SEMI"])
    volume_score = min(100.0, (weekly_km / req["min_weekly_km"]) * 100) if req["min_weekly_km"] > 0 else 50.0
    if vo2max is None:
        score = round(volume_score, 1)
    else:
        fitness_score = min(100.0, (vo2max / req["min_vo2max"]) * 100) if req["min_vo2max"] > 0 else 50.0
        score = round(volume_score * 0.6 + fitness_score * 0.4, 1)

    if score >= 90:
        prep_status = "avancé"
    elif score >= 70:
        prep_status = "normal"
    elif score >= 50:
        prep_status = "progressif"
    else:
        prep_status = "débutant"
    return score, prep_status, req["base_weeks"]


def _runtime_goal_and_type(raw_goal: str) -> tuple[GoalType, str]:
    normalized = (raw_goal or "SEMI").strip().upper()
    return _GOAL_MAP.get(normalized, (GoalType.half_marathon, "SEMI"))


def _stable_hash(payload: dict) -> str:
    serial = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serial.encode()).hexdigest()


def _workouts_fingerprint(workouts: List[dict]) -> str:
    compact = []
    for w in workouts:
        compact.append(
            {
                "id": w.get("id") or w.get("_id") or w.get("activity_id"),
                "date": w.get("date") or w.get("start_time") or w.get("start_date_local"),
                "activity_type": w.get("activity_type") or w.get("type"),
                "distance_km": _workout_distance_km(w),
                "duration_s": _workout_duration_seconds(w),
            }
        )
    compact.sort(key=lambda x: (str(x["date"]), str(x["id"])))
    return _stable_hash({"workouts": compact})


def _profile_fingerprint(profile_doc: Optional[dict]) -> str:
    if not isinstance(profile_doc, dict):
        return "none"
    clean = {k: v for k, v in profile_doc.items() if k != "_id"}
    return _stable_hash({"profile": clean})


def _current_week_from_dates(start_date, reference_date, total_weeks: int) -> int:
    if start_date is None:
        return 1
    delta_days = (reference_date - start_date).days
    if delta_days < 0:
        return 0
    return min(total_weeks, (delta_days // 7) + 1) if total_weeks > 0 else 1


def _apply_sessions_preference_cap(weekly_target, sessions_preference: Optional[int]):
    """Runtime preference cap only: never increase WeeklyTarget V2 prescription."""
    if sessions_preference not in (3, 4, 5, 6):
        return weekly_target
    effective_sessions = min(weekly_target.target_sessions, sessions_preference)
    if effective_sessions == weekly_target.target_sessions:
        return weekly_target
    return weekly_target.model_copy(update={"target_sessions": effective_sessions})


async def generate_dynamic_training_plan(db, user_id: str, sessions_override: int = None) -> dict:
    start = time.time()
    metrics.total_requests += 1
    metrics.plan_requests += 1

    now = datetime.now(timezone.utc)
    reference_date = now.date()
    prefs = await db.training_prefs.find_one({"user_id": user_id})
    sessions_per_week = (
        sessions_override if sessions_override is not None else (prefs.get("sessions_per_week") if prefs else None)
    )

    cycle = await db.training_cycles.find_one({"user_id": user_id})
    if not cycle:
        cycle = {
            "user_id": user_id,
            "goal": "SEMI",
            "start_date": now,
            "created_at": now,
        }
        await db.training_cycles.insert_one(cycle)
        cycle = await db.training_cycles.find_one({"user_id": user_id}) or cycle

    user_goal = await db.user_goals.find_one({"user_id": user_id})
    profile_doc = await db.user_profiles.find_one({"user_id": user_id}) if hasattr(db, "user_profiles") else None

    ninety_days_ago = now - timedelta(days=90)
    workouts = await db.workouts.find(
        {"user_id": user_id, "date": {"$gte": ninety_days_ago.isoformat()}}
    ).to_list(1000)

    goal_type, goal_label = _runtime_goal_and_type(cycle.get("goal"))
    race_date = _parse_optional_date((user_goal or {}).get("event_date") or cycle.get("race_date"))
    cycle_start_dt = _parse_optional_datetime(cycle.get("start_date"))
    cycle_start_date = cycle_start_dt.date() if cycle_start_dt else None
    ultra_distance = _extract_ultra_distance_km(cycle or {}, user_goal or {})
    _cache_payload = {
        "user_id": user_id,
        "reference_date": reference_date.isoformat(),
        "goal": goal_label,
        "goal_type": goal_type.value,
        "race_date": race_date.isoformat() if race_date else None,
        "cycle_start_date": cycle_start_date.isoformat() if cycle_start_date else None,
        "ultra_distance_km": ultra_distance,
        "sessions_override": sessions_per_week,
        "workouts_fingerprint": _workouts_fingerprint(workouts),
        "profile_fingerprint": _profile_fingerprint(profile_doc),
    }
    cache_key = f"plan_v2_{_stable_hash(_cache_payload)}"
    cached = _plan_cache.get(cache_key)
    if cached and _is_cache_valid(cached[1]):
        metrics.cache_hits += 1
        latency = (time.time() - start) * 1000
        _update_latency(latency, is_cache=True)
        return cached[0]

    performance_vma, performance_vo2max, vma_method, vma_confidence, personalized_paces = await _load_canonical_performance_signals(
        db,
        user_id,
        reference_date,
    )

    if goal_type == GoalType.ultra and (ultra_distance is None or ultra_distance <= ULTRA_MIN_DISTANCE_KM):
        return {
            "week": 0,
            "phase": "unavailable",
            "phase_info": {},
            "goal": goal_label,
            "goal_config": {"goal_type": goal_type.value, "error": "ULTRA_TARGET_DISTANCE_REQUIRED"},
            "context": {"error": "ULTRA_TARGET_DISTANCE_REQUIRED"},
            "plan": None,
            "sessions_per_week": sessions_per_week,
            "vma": performance_vma,
            "vo2max": performance_vo2max,
            "vma_method": vma_method,
            "vma_confidence": vma_confidence,
            "paces": personalized_paces,
            "goal_compatibility_score": None,
            "prep_status": None,
            "adjusted_weeks": None,
            "prep_insufficient": None,
            "event_date": race_date.isoformat() if race_date else None,
            "start_date": cycle_start_date.isoformat() if cycle_start_date else None,
            "end_date": race_date.isoformat() if race_date else None,
            "current_week": 0,
            "total_weeks": None,
            "days_to_race": (race_date - reference_date).days if race_date else None,
            "status": "unavailable",
            "debug_volume": {"error": "ULTRA_TARGET_DISTANCE_REQUIRED"},
            "generated_at": now.isoformat(),
        }

    if cycle_start_date and cycle_start_date > reference_date:
        days_to_start = (cycle_start_date - reference_date).days
        goal_compatibility_score, prep_status, base_weeks = _goal_compatibility_score(
            goal_label, 0.0, performance_vo2max
        )
        return {
            "week": 0,
            "phase": "upcoming",
            "phase_info": {},
            "goal": goal_label,
            "goal_config": {"goal_type": goal_type.value, "base_weeks": base_weeks},
            "context": {},
            "plan": None,
            "sessions_per_week": sessions_per_week,
            "vma": performance_vma,
            "vo2max": performance_vo2max,
            "vma_method": vma_method,
            "vma_confidence": vma_confidence,
            "paces": personalized_paces,
            "goal_compatibility_score": goal_compatibility_score,
            "prep_status": prep_status,
            "adjusted_weeks": base_weeks,
            "prep_insufficient": race_date is not None and (race_date - reference_date).days // 7 < base_weeks,
            "event_date": race_date.isoformat() if race_date else None,
            "start_date": cycle_start_date.isoformat(),
            "end_date": race_date.isoformat() if race_date else None,
            "current_week": 0,
            "total_weeks": base_weeks,
            "days_to_race": (race_date - reference_date).days if race_date else None,
            "days_to_start": days_to_start,
            "status": "upcoming",
            "message": f"Votre préparation commence dans {days_to_start} jours.",
            "generated_at": now.isoformat(),
        }

    activities = [_to_domain_activity_from_workout(w) for w in workouts]
    training_history = build_training_history(activities, reference_date)
    training_load = build_training_load(activities, reference_date)
    runner_profile = build_runner_profile(
        training_history=training_history,
        training_load=training_load,
        user_profile=profile_doc,
        capabilities=None,
        physiological_metrics=None,
        reference_date=reference_date,
    )
    training_state = build_training_state(
        training_history=training_history,
        training_load=training_load,
        runner_profile=runner_profile,
        reference_date=reference_date,
    )
    plan_goal = build_plan_goal(
        goal_type=goal_type,
        target_distance_km=ultra_distance if goal_type == GoalType.ultra else None,
        race_date=race_date,
        created_from="user" if cycle.get("goal") else "default",
    )

    try:
        if race_date is not None:
            if cycle_start_date is None and race_date > reference_date:
                raise ValueError("cycle_start_date_missing_for_race_calendar")
            periodization = build_periodization(
                plan_goal=plan_goal,
                reference_date=reference_date,
                race_plan_start_date=cycle_start_date if race_date > reference_date else None,
            )
        else:
            periodization = build_periodization(
                plan_goal=plan_goal,
                reference_date=reference_date,
                cycle_anchor_date=cycle_start_date or reference_date,
            )
    except ValueError as exc:
        logger.warning(f"[Coach] V2 periodization unavailable for user={user_id}: {exc}")
        return {
            "week": 0,
            "phase": "unavailable",
            "phase_info": {},
            "goal": goal_label,
            "goal_config": {"goal_type": goal_type.value, "error": "PERIODIZATION_UNAVAILABLE"},
            "context": {"error": "PERIODIZATION_UNAVAILABLE"},
            "plan": None,
            "sessions_per_week": sessions_per_week,
            "vma": performance_vma,
            "vo2max": performance_vo2max,
            "vma_method": vma_method,
            "vma_confidence": vma_confidence,
            "paces": personalized_paces,
            "goal_compatibility_score": None,
            "prep_status": None,
            "adjusted_weeks": None,
            "prep_insufficient": None,
            "event_date": race_date.isoformat() if race_date else None,
            "start_date": cycle_start_date.isoformat() if cycle_start_date else None,
            "end_date": race_date.isoformat() if race_date else None,
            "current_week": 0,
            "total_weeks": None,
            "days_to_race": (race_date - reference_date).days if race_date else None,
            "status": "unavailable",
            "debug_volume": {"error": "PERIODIZATION_UNAVAILABLE"},
            "generated_at": now.isoformat(),
        }

    weekly_target = build_weekly_target(
        runner_profile=runner_profile,
        training_history=training_history,
        training_state=training_state,
        plan_goal=plan_goal,
        periodization=periodization,
        reference_date=reference_date,
    )
    weekly_target = _apply_sessions_preference_cap(
        weekly_target=weekly_target,
        sessions_preference=sessions_per_week,
    )

    recent_response = build_recent_training_response(activities, reference_date)
    reconciliation = build_weekly_reconciliation(
        proposed_target=weekly_target,
        recent_response=recent_response,
    )
    reconciled_target = reconciliation.reconciled_target
    weekly_plan = build_weekly_plan(
        weekly_target=reconciled_target,
        runner_profile=runner_profile,
        plan_goal=plan_goal,
        periodization=periodization,
        reference_date=reference_date,
    )

    weekly_km_recent = training_history.window_7d.distance_km if training_history.window_7d.activity_count > 0 else 0.0
    goal_compatibility_score, prep_status, base_weeks = _goal_compatibility_score(
        goal_label,
        weekly_km_recent,
        performance_vo2max,
    )
    prep_insufficient = False
    if race_date is not None:
        prep_insufficient = ((race_date - reference_date).days // 7) < base_weeks

    phase_name = periodization.phase.value
    cycle_start = cycle_start_date or periodization.phase_start_date or reference_date
    if race_date is not None:
        total_weeks = max(1, int(math.ceil(max(0, (race_date - cycle_start).days) / 7.0)))
    else:
        total_weeks = 12
    current_week = _current_week_from_dates(cycle_start, reference_date, total_weeks)
    phase_info = build_runtime_phase_info(phase_name)
    runtime_plan = adapt_weekly_plan_to_runtime_payload(
        weekly_plan=weekly_plan,
        phase=phase_name,
        continuity_state=reconciled_target.continuity_state,
        paces=personalized_paces,
    )
    context = {
        "acwr": training_load.acwr,
        "tsb": None,
        "weekly_km": round(weekly_km_recent, 1),
        "vma": performance_vma,
        "vo2max": performance_vo2max,
        "vma_method": vma_method,
        "vma_confidence": vma_confidence,
        "paces": personalized_paces,
        "goal_compatibility_score": goal_compatibility_score,
        "prep_status": prep_status,
        "training_state": training_state.continuity_state,
        "training_state_v2": training_state.continuity_state,
        "weekly_target_v2": reconciled_target.model_dump(),
        "weekly_reconciliation_v2": reconciliation.model_dump(),
        "recent_training_response_v2": recent_response.model_dump(),
    }
    result = {
        "week": current_week,
        "phase": phase_name,
        "phase_info": phase_info,
        "goal": goal_label,
        "goal_config": {
            "goal_type": goal_type.value,
            "target_distance_km": plan_goal.target_distance_km,
            "race_date": plan_goal.race_date.isoformat() if plan_goal.race_date else None,
            "base_weeks": base_weeks,
        },
        "context": context,
        "plan": runtime_plan,
        "sessions_per_week": reconciled_target.target_sessions,
        "vma": performance_vma,
        "vo2max": performance_vo2max,
        "vma_method": vma_method,
        "vma_confidence": vma_confidence,
        "paces": personalized_paces,
        "goal_compatibility_score": goal_compatibility_score,
        "prep_status": prep_status,
        "adjusted_weeks": total_weeks,
        "prep_insufficient": prep_insufficient,
        "event_date": race_date.isoformat() if race_date else None,
        "start_date": cycle_start.isoformat() if cycle_start else None,
        "end_date": race_date.isoformat() if race_date else None,
        "current_week": current_week,
        "total_weeks": total_weeks,
        "days_to_race": (race_date - reference_date).days if race_date else None,
        "status": "completed" if race_date and reference_date > race_date else "active",
        "debug_volume": {
            "km_7": round(training_history.window_7d.distance_km, 1),
            "km_28": round(training_history.window_30d.distance_km, 1),
            "target_basis": reconciled_target.target_basis,
            "target_km": reconciled_target.target_km,
            "target_duration_minutes": reconciled_target.target_duration_minutes,
            "target_sessions": reconciled_target.target_sessions,
            "phase": phase_name,
            "weekly_reconciliation_action": reconciliation.action.value,
        },
        "generated_at": now.isoformat(),
    }

    await db.training_cycles.update_one(
        {"user_id": user_id},
        {"$set": {
            "last_generated_week": current_week,
            "current_plan": runtime_plan,
            "vma": performance_vma,
            "vo2max": performance_vo2max,
            "updated_at": now,
        }},
    )

    _plan_cache[cache_key] = (result, time.time())
    _cleanup_cache(_plan_cache)
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    return result


# ============================================================
# CACHE & UTILS
# ============================================================

def clear_cache() -> dict:
    """Clears caches."""
    global _workout_cache, _weekly_cache, _plan_cache
    result = {
        "cleared_workout": len(_workout_cache),
        "cleared_weekly": len(_weekly_cache),
        "cleared_plan": len(_plan_cache)
    }
    _workout_cache = {}
    _weekly_cache = {}
    _plan_cache = {}
    return result


def get_cache_stats() -> dict:
    """Returns cache statistics."""
    return {
        "workout_cache_size": len(_workout_cache),
        "weekly_cache_size": len(_weekly_cache),
        "plan_cache_size": len(_plan_cache),
        "max_size": MAX_CACHE_SIZE,
        "ttl_seconds": CACHE_TTL_SECONDS
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "analyze_workout",
    "weekly_review", 
    "chat_response",
    "generate_dynamic_training_plan",
    "clear_cache",
    "get_cache_stats",
    "get_metrics",
    "reset_metrics"
]
