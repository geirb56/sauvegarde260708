"""
RunIndex - Coaching Service metrics and chat LLM bridge

Usage:
    from coach_service import chat_response, get_metrics
"""

import logging
import time
from dataclasses import dataclass, asdict
from typing import List, Tuple

from llm_coach import (
    enrich_chat_response,
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
    chat_requests: int = 0


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
    """Compatibility shim: workout analysis cache was removed."""
    result = {
        "cleared_workout": 0,
    }
    return result


def get_cache_stats() -> dict:
    """Compatibility shim stats after workout analysis cache removal."""
    return {
        "workout_cache_size": 0,
        "max_size": 0,
        "ttl_seconds": 0
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "chat_response",
    "clear_cache",
    "get_cache_stats",
    "get_metrics",
    "reset_metrics"
]
