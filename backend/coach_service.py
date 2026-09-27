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
import logging
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

from llm_coach import (
    enrich_chat_response,
    enrich_weekly_review,
    enrich_workout_analysis,
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
# CACHE & UTILS
# ============================================================

def clear_cache() -> dict:
    """Clears caches."""
    global _workout_cache, _weekly_cache
    result = {
        "cleared_workout": len(_workout_cache),
        "cleared_weekly": len(_weekly_cache),
    }
    _workout_cache = {}
    _weekly_cache = {}
    return result


def get_cache_stats() -> dict:
    """Returns cache statistics."""
    return {
        "workout_cache_size": len(_workout_cache),
        "weekly_cache_size": len(_weekly_cache),
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
    "clear_cache",
    "get_cache_stats",
    "get_metrics",
    "reset_metrics"
]
