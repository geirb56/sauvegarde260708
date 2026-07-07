"""
CardioCoach - Cascade Coaching Service with Cache and Metrics

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
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

from llm_coach import (
    enrich_chat_response,
    enrich_weekly_review,
    enrich_workout_analysis,
    generate_cycle_week,
    LLM_MODEL
)
from training_engine import (
    GOAL_CONFIG,
    VOLUME_GOAL_CONFIG,
    compute_target_km,
    compute_week_number,
    determine_phase,
    build_training_context,
    determine_target_load,
    get_phase_description
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
    user_id: str = "default",
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
    user_id: str = "default",
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
    else:
        error_msg = "The AI coaching service is currently unavailable."
    return error_msg, False, {}


# ============================================================
# DYNAMIC TRAINING PLAN GENERATION
# ============================================================

async def generate_dynamic_training_plan(db, user_id: str, sessions_override: int = None) -> dict:
    """
    Generates a dynamic training plan based on user data.

    Integrates:
    - VMA to calculate personalized paces
    - Race predictions to adapt preparation duration

    Args:
        db: MongoDB database instance (async)
        user_id: User ID
        sessions_override: Forced number of sessions (3, 4, 5, 6)

    Returns:
        Training plan with week, phase, goal and sessions
    """
    start = time.time()
    metrics.total_requests += 1
    metrics.plan_requests += 1
    
    # Retrieve user preferences (number of sessions)
    prefs = await db.training_prefs.find_one({"user_id": user_id})
    sessions_per_week = sessions_override or (prefs.get("sessions_per_week") if prefs else None)

    # 1. Retrieve or create training cycle
    cycle = await db.training_cycles.find_one({"user_id": user_id})

    if not cycle:
        # Create a default cycle
        default_cycle = {
            "user_id": user_id,
            "goal": "SEMI",
            "start_date": datetime.now(timezone.utc),
            "race_date": None,
            "created_at": datetime.now(timezone.utc)
        }
        await db.training_cycles.insert_one(default_cycle)
        cycle = await db.training_cycles.find_one({"user_id": user_id})
        logger.info(f"[Coach] Cycle created for user {user_id}")
    
    goal = cycle.get("goal", "SEMI")
    
    if goal not in GOAL_CONFIG:
        goal = "SEMI"
    
    config = GOAL_CONFIG[goal]

    # 2. Retrieve training data (6 weeks for VMA consistency)
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    six_weeks_ago = today - timedelta(days=42)
    twenty_eight_days_ago = today - timedelta(days=28)

    # Retrieve workouts
    workouts_7 = await db.workouts.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    workouts_28 = await db.workouts.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)

    # 6-week data for VMA calculation
    workouts_6w = await db.workouts.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "date": {"$gte": six_weeks_ago.isoformat()}
    }).to_list(500)

    # 3. Calculate base metrics
    def get_distance_km(w):
        """Extracts distance in km"""
        return w.get("distance_km", 0) or 0
    
    def get_duration_min(w):
        """Extracts duration in minutes"""
        moving_time = w.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        elapsed = w.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        return w.get("duration_minutes", 0)
    
    def get_pace(w):
        """Calculates pace in min/km"""
        dist = get_distance_km(w)
        duration = get_duration_min(w)
        if dist > 0 and duration > 0:
            return duration / dist
        return None
    
    km_7 = sum(get_distance_km(w) for w in workouts_7)
    km_28 = sum(get_distance_km(w) for w in workouts_28)
    weekly_km = km_28 / 4 if km_28 > 0 else 20

    # 4. CALCULATE VMA (same logic as /api/training/vma-history)
    vma_efforts = []
    paces = []
    MIN_VMA_DURATION = 6
    
    for w in workouts_6w:
        dist = get_distance_km(w)
        pace = get_pace(w)
        duration = get_duration_min(w)
        
        if dist > 0 and pace and 3 < pace < 10:
            paces.append(pace)
            # Efforts >= 6 min with fast pace (< 5:30/km)
            if duration >= MIN_VMA_DURATION and pace < 5.5:
                vma_efforts.append({
                    "pace": pace,
                    "duration": duration,
                    "speed_kmh": 60 / pace
                })

    # VMA calculation
    if paces:
        avg_pace = sum(paces) / len(paces)
        
        if vma_efforts:
            best_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
            best_speed = best_effort["speed_kmh"]
            duration = best_effort["duration"]
            
            if duration >= 20:
                estimated_vma = best_speed / 0.85
            elif duration >= 12:
                estimated_vma = best_speed / 0.90
            else:
                estimated_vma = best_speed / 0.95
            vma_method = "effort"
        else:
            avg_speed = 60 / avg_pace
            estimated_vma = avg_speed / 0.70
            vma_method = "average"
        
        # Sanity check
        if estimated_vma * 3.5 > 70:
            estimated_vma = 14.0  # Realistic default value
            vma_method = "default"
    else:
        estimated_vma = 12.0  # Default VMA
        vma_method = "default"
    
    estimated_vma = round(estimated_vma, 1)
    vo2max = round(estimated_vma * 3.5, 1)

    # 5. CALCULATE PERSONALIZED PACE ZONES based on VMA
    def vma_to_pace(vma_pct):
        """Converts a VMA % to pace in min/km"""
        speed = estimated_vma * vma_pct
        if speed > 0:
            pace = 60 / speed
            return pace
        return 6.0
    
    def format_pace(pace):
        """Formats a pace as min:sec/km"""
        mins = int(pace)
        secs = int((pace % 1) * 60)
        return f"{mins}:{secs:02d}"
    
    personalized_paces = {
        "z1": f"{format_pace(vma_to_pace(0.65))}-{format_pace(vma_to_pace(0.70))}",  # 65-70% VMA (recovery)
        "z2": f"{format_pace(vma_to_pace(0.75))}-{format_pace(vma_to_pace(0.80))}",  # 75-80% VMA (endurance)
        "z3": f"{format_pace(vma_to_pace(0.82))}-{format_pace(vma_to_pace(0.87))}",  # 82-87% VMA (tempo)
        "z4": f"{format_pace(vma_to_pace(0.88))}-{format_pace(vma_to_pace(0.93))}",  # 88-93% VMA (threshold)
        "z5": f"{format_pace(vma_to_pace(0.95))}-{format_pace(vma_to_pace(1.00))}",  # 95-100% VMA
        "marathon": f"{format_pace(vma_to_pace(0.78))}-{format_pace(vma_to_pace(0.82))}",  # 78-82% VMA
        "semi": f"{format_pace(vma_to_pace(0.82))}-{format_pace(vma_to_pace(0.85))}",  # 82-85% VMA
    }

    # 6. ADAPT PREPARATION DURATION according to level
    # Calculate "readiness score" for the goal
    goal_requirements = {
        "5K": {"min_weekly_km": 15, "min_vo2max": 35, "base_weeks": 6},
        "10K": {"min_weekly_km": 25, "min_vo2max": 38, "base_weeks": 8},
        "SEMI": {"min_weekly_km": 35, "min_vo2max": 42, "base_weeks": 12},
        "MARATHON": {"min_weekly_km": 50, "min_vo2max": 45, "base_weeks": 16},
        "ULTRA": {"min_weekly_km": 60, "min_vo2max": 48, "base_weeks": 20},
    }
    
    req = goal_requirements.get(goal, goal_requirements["SEMI"])

    # Preparation score (0-100)
    volume_score = min(100, (weekly_km / req["min_weekly_km"]) * 100) if req["min_weekly_km"] > 0 else 50
    fitness_score = min(100, (vo2max / req["min_vo2max"]) * 100) if req["min_vo2max"] > 0 else 50
    readiness_score = (volume_score * 0.6 + fitness_score * 0.4)  # Volume counts more

    # Adjust number of weeks
    base_weeks = req["base_weeks"]
    if readiness_score >= 90:
        # Very ready → short preparation (-25%)
        adjusted_weeks = max(4, int(base_weeks * 0.75))
        prep_status = "advanced"
    elif readiness_score >= 70:
        # Ready → normal preparation
        adjusted_weeks = base_weeks
        prep_status = "normal"
    elif readiness_score >= 50:
        # Need to progress → long preparation (+25%)
        adjusted_weeks = int(base_weeks * 1.25)
        prep_status = "progressive"
    else:
        # Beginner → very long preparation (+50%)
        adjusted_weeks = int(base_weeks * 1.5)
        prep_status = "beginner"

    # Update config with adapted duration
    config = {**config, "cycle_weeks": adjusted_weeks}

    # 7. Calculate week and phase
    start_date = cycle.get("start_date")
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    
    week = compute_week_number(start_date.date() if isinstance(start_date, datetime) else start_date)
    phase = determine_phase(week, adjusted_weeks)

    # 8. Calculate ACWR and TSB
    chronic_avg = km_28 / 4 if km_28 > 0 else 1
    acwr = round(km_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    
    ctl = km_28 / 4
    atl = km_7
    tsb = round(ctl - atl, 1)
    
    load_7 = km_7 * 10
    load_28 = km_28 * 10
    
    fitness_data = {
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "load_7": load_7,
        "load_28": load_28,
        "acwr": acwr
    }

    # 9. Build enriched context with VMA
    context = build_training_context(fitness_data, weekly_km)
    context["vma"] = estimated_vma
    context["vo2max"] = vo2max
    context["vma_method"] = vma_method
    # VMA confidence: effort=derived from a real hard effort (reliable),
    # average=rough estimate from mean training speed, default=hardcoded fallback.
    vma_confidence = {"effort": "high", "average": "medium", "default": "low"}.get(vma_method, "low")
    context["vma_confidence"] = vma_confidence
    context["paces"] = personalized_paces
    context["readiness_score"] = round(readiness_score, 1)
    context["prep_status"] = prep_status
    context["adjusted_weeks"] = adjusted_weeks

    # 10. Calculate target load
    target_load = determine_target_load(context, phase)

    # 11. Check cache
    cache_key = f"plan_{user_id}_{week}_{phase}_{goal}_{estimated_vma}"
    if cache_key in _plan_cache:
        cached_plan, timestamp = _plan_cache[cache_key]
        if _is_cache_valid(timestamp):
            metrics.cache_hits += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_cache=True)
            logger.debug(f"[Coach] Plan cache hit ({latency:.1f}ms)")
            return cached_plan

    # 12. Generate plan via LLM with personalized paces
    try:
        week_plan, success, meta = await generate_cycle_week(
            context=context,
            phase=phase,
            target_load=target_load,
            goal=goal,
            user_id=user_id,
            sessions_per_week=sessions_per_week,
            personalized_paces=personalized_paces
        )
        
        if success and week_plan:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            logger.info(f"[Coach] ✅ Plan LLM ({latency:.0f}ms)")
        else:
            raise Exception("LLM plan generation failed")
            
    except Exception as e:
        logger.warning(f"[Coach] Plan fallback: {e}")
        metrics.llm_fallback += 1
        week_plan = _deterministic_plan(context, phase, target_load, goal, sessions_per_week, personalized_paces)

    # 13. Build result
    result = {
        "week": week,
        "phase": phase,
        "phase_info": get_phase_description(phase),
        "goal": goal,
        "goal_config": config,
        "context": context,
        "plan": week_plan,
        "sessions_per_week": sessions_per_week,
        "vma": estimated_vma,
        "vo2max": vo2max,
        "vma_method": vma_method,
        "vma_confidence": vma_confidence,
        "paces": personalized_paces,
        "readiness_score": round(readiness_score, 1),
        "prep_status": prep_status,
        "adjusted_weeks": adjusted_weeks,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

    # 14. Update cycle in database
    await db.training_cycles.update_one(
        {"user_id": user_id},
        {"$set": {
            "last_generated_week": week,
            "current_plan": week_plan,
            "vma": estimated_vma,
            "vo2max": vo2max,
            "adjusted_weeks": adjusted_weeks,
            "updated_at": datetime.now(timezone.utc)
        }}
    )

    # 15. Store in cache
    _plan_cache[cache_key] = (result, time.time())
    _cleanup_cache(_plan_cache)
    
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    
    return result


# ============================================================
# WEEKLY VOLUME — imported from training_engine (single source of truth)
# ============================================================


def _deterministic_plan(context: dict, phase: str, target_load: int, goal: str, sessions_per_week: int = None, personalized_paces: dict = None) -> dict:
    """Generates a deterministic fallback plan with personalized VMA-based paces."""

    # Athlete's current volume (based on last 4 weeks)
    current_weekly_km = context.get("weekly_km", 30)

    config = VOLUME_GOAL_CONFIG.get(goal, VOLUME_GOAL_CONFIG["SEMI"])

    # Use specified number of sessions or default
    num_sessions = sessions_per_week if sessions_per_week in [3, 4, 5, 6] else config["sessions"]
    num_rest_days = 7 - num_sessions

    # Target weekly volume — single source of truth shared with cycle overview
    target_km = compute_target_km(current_weekly_km, goal, phase)

    # Proportional long run
    long_ratio = (target_km - config["min"]) / (config["max"] - config["min"]) if config["max"] > config["min"] else 0.5
    long_run = round(config["long_min"] + long_ratio * (config["long_max"] - config["long_min"]))
    long_run = max(config["long_min"], min(config["long_max"], long_run))

    # Distribution of remaining volume
    remaining = target_km - long_run
    easy_km = round(remaining * 0.35)
    tempo_km = round(remaining * 0.25)
    seuil_km = round(remaining * 0.22)
    recup_km = remaining - easy_km - tempo_km - seuil_km

    # Personalized paces (VMA-based) or default values
    if personalized_paces:
        paces = personalized_paces
    else:
        paces = {"z1": "6:30-7:00", "z2": "5:45-6:15", "z3": "5:15-5:30", "z4": "4:45-5:00", "z5": "4:15-4:30", "semi": "5:00-5:15", "marathon": "5:15-5:30"}
    
    hr = {"z1": "120-135", "z2": "135-150", "z3": "150-165", "z4": "165-175", "z5": "175-185"}

    # Templates by phase - adapted to goal
    if phase == "deload":
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Stretching recommended", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Endurance", "duration": f"{easy_km*6}min", "details": f"{easy_km} km • {paces['z1']}/km • HR {hr['z1']} bpm • Zone 1-2", "intensity": "easy", "estimated_tss": easy_km*5, "distance_km": easy_km},
            {"day": "Wednesday", "type": "Recovery", "duration": f"{recup_km*7}min", "details": f"{recup_km} km • {paces['z1']}/km • HR {hr['z1']} bpm • Very easy", "intensity": "easy", "estimated_tss": recup_km*5, "distance_km": recup_km},
            {"day": "Thursday", "type": "Endurance", "duration": f"{easy_km*6}min", "details": f"{easy_km} km • {paces['z2']}/km • HR {hr['z2']} bpm", "intensity": "easy", "estimated_tss": easy_km*5, "distance_km": easy_km},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Recovery • Light walking possible", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Endurance", "duration": f"{tempo_km*6}min", "details": f"{tempo_km} km progressive • {paces['z2']}/km → {paces['z3']}/km", "intensity": "easy", "estimated_tss": tempo_km*6, "distance_km": tempo_km},
            {"day": "Sunday", "type": "Long run", "duration": f"{long_run*6}min", "details": f"{long_run} km • {paces['z2']}/km • HR {hr['z2']} bpm • Easy run", "intensity": "moderate", "estimated_tss": long_run*6, "distance_km": long_run},
        ]
    elif phase == "taper":
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Hydration ++", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Endurance", "duration": "30min", "details": f"{recup_km} km + 4×100m • {paces['z2']}/km • HR {hr['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": recup_km + 0.5},
            {"day": "Wednesday", "type": "Recovery", "duration": "20min", "details": f"{recup_km-1} km • {paces['z1']}/km • HR {hr['z1']} bpm", "intensity": "easy", "estimated_tss": 15, "distance_km": max(3, recup_km-1)},
            {"day": "Thursday", "type": "Short tempo", "duration": "25min", "details": f"{recup_km} km including 2 km race pace • {paces['semi']}/km • HR {hr['z3']} bpm", "intensity": "moderate", "estimated_tss": 35, "distance_km": recup_km},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Complete rest • Gear preparation", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Activation", "duration": "20min", "details": f"3 km + 3×200m • {paces['z2']}/km", "intensity": "easy", "estimated_tss": 25, "distance_km": 3.6},
            {"day": "Sunday", "type": "Rest", "duration": "0min", "details": "DAY BEFORE RACE • Rest, carbs", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    elif phase == "race":
        race_km = {"5K": 5, "10K": 10, "SEMI": 21.1, "MARATHON": 42.2, "ULTRA": 50}.get(goal, 21.1)
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Activation", "duration": "20min", "details": f"3 km • {paces['z1']}/km • HR {hr['z1']} bpm", "intensity": "easy", "estimated_tss": 15, "distance_km": 3},
            {"day": "Wednesday", "type": "Recovery", "duration": "15min", "details": f"2.5 km • {paces['z1']}/km • HR {hr['z1']} bpm", "intensity": "easy", "estimated_tss": 12, "distance_km": 2.5},
            {"day": "Thursday", "type": "Activation", "duration": "15min", "details": f"2 km + 2×100m • {paces['z1']}/km", "intensity": "easy", "estimated_tss": 10, "distance_km": 2.2},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Complete rest", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Rest", "duration": "0min", "details": "DAY BEFORE • Carbs", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Sunday", "type": "RACE", "duration": "Variable", "details": f"🏆 {goal} ({race_km} km) • Target: {paces.get('semi')}/km", "intensity": "race", "estimated_tss": int(race_km * 7), "distance_km": race_km},
        ]
    else:  # build, intensification - Standard plan adapted to goal
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Stretching recommended", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Endurance", "duration": f"{easy_km*6}min", "details": f"{easy_km} km • {paces['z2']}/km • HR {hr['z2']} bpm • Strict zone 2", "intensity": "easy", "estimated_tss": easy_km*6, "distance_km": easy_km},
            {"day": "Wednesday", "type": "Threshold", "duration": f"{seuil_km*5}min", "details": f"{seuil_km} km including 20min at {paces['z4']}/km • HR {hr['z4']} bpm • 2min recovery", "intensity": "hard", "estimated_tss": seuil_km*8, "distance_km": seuil_km},
            {"day": "Thursday", "type": "Recovery", "duration": f"{recup_km*7}min", "details": f"{recup_km} km • {paces['z1']}/km • HR <135 bpm • Easy jog", "intensity": "easy", "estimated_tss": recup_km*5, "distance_km": recup_km},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Recovery • Cross-training possible (bike, swim)", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Tempo", "duration": f"{tempo_km*5}min", "details": f"{tempo_km} km including 25min at {paces['semi']}/km • HR {hr['z3']} bpm", "intensity": "moderate", "estimated_tss": tempo_km*7, "distance_km": tempo_km},
            {"day": "Sunday", "type": "Long run", "duration": f"{long_run*5}min", "details": f"{long_run} km progressive • {paces['z2']}/km → {paces['z3']}/km • HR {hr['z2']}→{hr['z3']} bpm", "intensity": "moderate", "estimated_tss": long_run*6, "distance_km": long_run},
        ]
    
    total_tss = sum(s["estimated_tss"] for s in sessions)
    total_km = sum(s.get("distance_km", 0) for s in sessions)
    
    return {
        "focus": phase,
        "planned_load": target_load,
        "weekly_km": round(total_km, 1),
        "sessions": sessions,
        "total_tss": total_tss,
        "advice": get_phase_description(phase).get("advice", f"Focus on {goal} preparation. Respect target paces!")
    }


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
