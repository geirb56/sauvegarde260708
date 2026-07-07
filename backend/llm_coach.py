"""
CardioCoach - LLM Coach Module (GPT-4o-mini)

This module handles the enrichment of coach texts via GPT-4o-mini.
Training data is sent directly to the LLM to
generate personalized and motivating analyses.

Flow:
1. Receive training data
2. Send to GPT-4o-mini for text generation
3. Error returned if API is not available
"""

import os
import time
import json
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
from training_engine import compute_target_km, compute_long_run_km, VOLUME_GOAL_CONFIG

load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
LLM_MODEL = "gpt-4.1-mini"
LLM_PROVIDER = "openai"
LLM_TIMEOUT = 15


# ============================================================
# SYSTEM PROMPTS
# ============================================================

SYSTEM_PROMPT_COACH = """You are CardioCoach, an expert and caring personal running coach.

🎯 YOUR ROLE:
You answer the athlete's questions about their training like a real personal coach.
You have access to ALL their real training data: complete session history, training plan, VO2max, race predictions, fitness metrics.

📊 AVAILABLE DATA:
- COMPLETE session history (last 28 days with distance, duration, pace, HR)
- Weekly training plan (goal, planned sessions)
- Estimated VO2max and race time predictions
- Fitness metrics: ACWR (acute/chronic workload ratio), TSB (freshness)
- Current goal (5K, 10K, Half, Marathon, Ultra)

💬 RESPONSE STYLE:
1. Be direct and concise (3-5 sentences max unless detailed analysis requested)
2. Use real data to personalize your response
3. Give actionable advice based on past sessions
4. Stay motivating and positive, even for critiques
5. If you don't know, say so honestly

🏃 EXPERTISE:
- Training plans (5K, 10K, half, marathon, ultra)
- Load management and recovery
- Heart rate zones and target paces
- Injury prevention
- Basic nutrition and hydration
- Progression and periodization
- Performance analysis and predictions

⚠️ IMPORTANT:
- ALWAYS respond in the user's language (FR, EN or ES)
- Don't use bullet points unless requested
- Speak like a human coach, not like a report
- Refer to specific sessions when relevant"""

SYSTEM_PROMPT_BILAN = """You are a running coach providing a weekly review.

Review structure:
1. Positive intro (congratulate consistency or effort)
2. Analysis of key metrics (explain simply)
3. Strengths (max 2)
4. Area to improve (max 1, framed positively)
5. Advice for next week
6. Motivating follow-up question

Be encouraging even if stats are average. Max 6-8 sentences."""

SYSTEM_PROMPT_SEANCE = """You are a running coach analyzing a session.

Structure:
1. Positive reaction to the effort
2. Simple data analysis (pace, HR, consistency)
3. Session highlight
4. Advice for next run
5. Motivating follow-up (optional)

Be concrete and encouraging. Max 4-5 sentences."""

SYSTEM_PROMPT_PLAN = """You are an elite running coach specialized in periodization.
Respond ONLY in valid JSON, without text before or after."""


# Map language code -> a strong, explicit output-language directive.
_LANG_NAMES = {"fr": "French (français)", "en": "English", "es": "Spanish (español)"}


def _lang_directive(language: str) -> str:
    lang = (language or "fr").lower()
    name = _LANG_NAMES.get(lang, _LANG_NAMES["fr"])
    return (f"\n\nCRITICAL: Write your ENTIRE response in {name}. "
            f"Do not use any other language.")


# ============================================================
# ENRICHMENT FUNCTIONS
# ============================================================

async def enrich_chat_response(
    user_message: str,
    context: Dict,
    conversation_history: List[Dict],
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches chat response with GPT-4o-mini.

    Context includes:
    - 7-day and 28-day stats (km, sessions)
    - Fitness metrics (ACWR, TSB)
    - ALL sessions from last 28 days
    - Current training plan
    - Estimated VO2max and race predictions
    - Current goal
    """
    language = context.get("language", "fr")

    # Format context in readable format
    stats_7 = context.get("stats_7j", {})
    stats_28 = context.get("stats_28j", {})
    fitness = context.get("fitness", {})
    all_sessions = context.get("all_sessions", "")
    training_plan = context.get("training_plan", "")
    current_goal = context.get("current_goal", "Not set")
    vma = context.get("vma", "")
    predictions = context.get("predictions", "")
    workout = context.get("workout_detail")

    context_text = f"""📊 COMPLETE ATHLETE DATA:

🎯 CURRENT GOAL: {current_goal}

⚡ PERFORMANCE:
- {vma}
- Predictions: {predictions}

📈 THIS WEEK (7d):
- Volume: {stats_7.get('km', 0)} km
- Sessions: {stats_7.get('sessions', 0)}

📅 THIS MONTH (28d):
- Volume: {stats_28.get('km', 0)} km
- Sessions: {stats_28.get('sessions', 0)}

💪 FITNESS STATUS:
- ACWR: {fitness.get('acwr', 1.0)} ({fitness.get('acwr_status', 'ok')})
- TSB: {fitness.get('tsb', 0)} ({fitness.get('tsb_status', 'normal')})

📋 TRAINING PLAN:
{training_plan if training_plan else "No active plan"}

🏃 COMPLETE SESSION HISTORY (last 28 days):
{all_sessions}"""

    # Add workout details if available
    if workout:
        zones = workout.get('zones', {})
        zones_str = ""
        if zones:
            zones_str = f"Z1:{zones.get('z1',0)}% Z2:{zones.get('z2',0)}% Z3:{zones.get('z3',0)}% Z4:{zones.get('z4',0)}% Z5:{zones.get('z5',0)}%"

        context_text += f"""

🔍 SESSION BEING ANALYZED:
- Name: {workout.get('name', 'N/A')}
- Distance: {workout.get('distance_km', 0):.1f} km
- Duration: {workout.get('duration_min', 0):.0f} min
- Avg HR: {workout.get('avg_hr', 'N/A')} bpm
- Max HR: {workout.get('max_hr', 'N/A')} bpm
- Zones: {zones_str}"""

    # Format conversation history
    history_text = ""
    if conversation_history:
        for msg in conversation_history[-4:]:  # last 4 messages max
            role = "Athlete" if msg.get("role") == "user" else "Coach"
            content = msg.get("content", "")[:200]  # Truncate if too long
            history_text += f"{role}: {content}\n"

    prompt = f"""{context_text}

💬 CONVERSATION HISTORY:
{history_text if history_text else "(New conversation)"}

❓ ATHLETE'S QUESTION: {user_message}

Respond in {language.upper()} as a caring and expert personal coach. Use the data above to personalize your response.{_lang_directive(language)}"""

    return await _call_gpt(SYSTEM_PROMPT_COACH + _lang_directive(language), prompt, user_id, "chat")


async def enrich_weekly_review(
    stats: Dict,
    user_id: str = "unknown",
    language: str = "fr"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches weekly review with GPT-4o-mini (in the requested language)."""
    prompt = f"""WEEKLY STATS:
{_format_context(stats)}

Generate a motivating and personalized weekly review based on this data.{_lang_directive(language)}"""

    return await _call_gpt(SYSTEM_PROMPT_BILAN + _lang_directive(language), prompt, user_id, "bilan")


async def enrich_workout_analysis(
    workout: Dict,
    user_id: str = "unknown",
    language: str = "fr"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches workout analysis with GPT-4o-mini (in the requested language)."""
    prompt = f"""SESSION DATA:
{_format_context(workout)}

Analyze this session as a caring running coach.{_lang_directive(language)}"""

    return await _call_gpt(SYSTEM_PROMPT_SEANCE + _lang_directive(language), prompt, user_id, "seance")


async def generate_cycle_week(
    context: Dict,
    phase: str,
    target_load: int,
    goal: str,
    user_id: str = "unknown",
    sessions_per_week: int = None,
    personalized_paces: Dict = None
) -> Tuple[Optional[Dict], bool, Dict]:
    """
    Generates a structured weekly training plan with personalized paces.
    
    Sessions are generated DETERMINISTICALLY by the code (not by LLM).
    LLM is only used for weekly advice/focus text.

    Args:
        context: Fitness data (CTL, ATL, TSB, ACWR, weekly_km, vma, vo2max, paces)
        phase: Current phase (build, deload, intensification, taper, race)
        target_load: Target load in TSS
        goal: Goal (5K, 10K, SEMI, MARATHON, ULTRA)
        user_id: User ID
        sessions_per_week: Number of sessions per week (3, 4, 5, 6)
        personalized_paces: Personalized paces based on VO2max

    Returns:
        (plan_dict, success, metadata)
    """
    start_time = time.time()
    metadata = {
        "model": "deterministic",
        "provider": "code",
        "context_type": "cycle_week",
        "duration_sec": 0,
        "success": False
    }
    
    # Athlete's current volume (based on last 4 weeks)
    current_weekly_km = context.get('weekly_km', 30)

    config = VOLUME_GOAL_CONFIG.get(goal, VOLUME_GOAL_CONFIG["SEMI"])

    # Number of sessions
    target_sessions = sessions_per_week if sessions_per_week in [3, 4, 5, 6] else config["sessions"]

    # Target weekly volume — single source of truth shared with cycle overview
    target_km = compute_target_km(current_weekly_km, goal, phase)

    # Long run distance, capped so it never exceeds the weekly target
    target_long_run = min(compute_long_run_km(target_km, goal), max(0, round(target_km * 0.5)))

    # Use personalized paces or defaults
    paces = personalized_paces or context.get('paces', {})
    
    # Helper: parse pace string to minutes (e.g., "6:30-7:00" -> 7.0)
    def parse_pace(pace_range: str) -> float:
        """Extract slower pace (second value) as float minutes."""
        try:
            pace_str = pace_range.split('-')[-1].strip().replace('/km', '')
            parts = pace_str.split(':')
            return int(parts[0]) + int(parts[1]) / 60
        except (ValueError, IndexError, TypeError):
            return 6.0
    
    # Helper: format pace as string
    def format_pace(pace_min: float) -> str:
        """Format pace float to MM:SS/km string."""
        mins = int(pace_min)
        secs = int((pace_min % 1) * 60)
        return f"{mins}:{secs:02d}/km"
    
    # Pace zones as floats (min/km)
    pace_z1 = parse_pace(paces.get('z1', '7:00-7:30'))
    pace_z2 = parse_pace(paces.get('z2', '6:00-6:30'))
    pace_z3 = parse_pace(paces.get('z3', '5:30-5:45'))
    pace_z4 = parse_pace(paces.get('z4', '5:00-5:15'))
    
    # Session templates: (type, duration_min, pace_zone, intensity, tss_per_km)
    session_templates = {
        "Rest": (0, None, "rest", 0),
        "Recovery": (30, pace_z1, "easy", 4),
        "Endurance": (50, pace_z2, "easy", 5),
        "Tempo": (45, pace_z3, "moderate", 7),
        "Threshold": (40, pace_z4, "hard", 8),
        "Fartlek": (45, pace_z3, "moderate", 7),
    }
    
    # Build sessions based on number of sessions per week
    def build_session(day: str, session_type: str, custom_duration: int = None, custom_distance: float = None) -> dict:
        """Build a single session with calculated values."""
        if session_type == "Rest":
            return {
                "day": day,
                "type": "Rest",
                "duration": "0min",
                "details": "Complete recovery",
                "intensity": "rest",
                "estimated_tss": 0,
                "distance_km": 0
            }
        
        if session_type == "Long run":
            # Long run: distance is primary, duration is calculated
            distance = custom_distance or target_long_run
            pace = pace_z2  # Long runs at Z2
            duration = round(distance * pace)
            return {
                "day": day,
                "type": "Long run",
                "duration": f"{duration}min",
                "details": f"{distance} km • {format_pace(pace)} • HR 135-150 bpm • Progressive",
                "intensity": "moderate",
                "estimated_tss": round(distance * 6),
                "distance_km": distance
            }
        
        # Standard sessions: distance-primary when a custom distance is given
        # (volume-driven), otherwise fall back to duration-primary.
        template = session_templates.get(session_type, session_templates["Endurance"])
        pace = template[1]
        intensity = template[2]
        tss_per_km = template[3]

        if custom_distance is not None:
            distance = round(custom_distance, 1)
            duration = round(distance * pace)
        else:
            duration = custom_duration or template[0]
            distance = round(duration / pace, 1)
        tss = round(distance * tss_per_km)
        
        # Build details string
        if session_type == "Threshold":
            details = f"{distance} km incl. 20min at {format_pace(pace)} • HR 165-175 bpm"
        elif session_type == "Tempo":
            details = f"{distance} km incl. 25min at {format_pace(pace)} • HR 150-165 bpm"
        elif session_type == "Fartlek":
            details = f"{distance} km • varied pace • HR 140-170 bpm"
        else:
            hr_range = "120-135" if session_type == "Recovery" else "135-150"
            zone = "Zone 1" if session_type == "Recovery" else "Zone 2"
            details = f"{distance} km • {format_pace(pace)} • HR {hr_range} bpm • {zone}"
        
        return {
            "day": day,
            "type": session_type,
            "duration": f"{duration}min",
            "details": details,
            "intensity": intensity,
            "estimated_tss": tss,
            "distance_km": distance
        }
    
    # Define weekly structure based on sessions per week
    if target_sessions == 3:
        week_structure = [
            ("Monday", "Rest"),
            ("Tuesday", "Endurance"),
            ("Wednesday", "Rest"),
            ("Thursday", "Threshold"),
            ("Friday", "Rest"),
            ("Saturday", "Rest"),
            ("Sunday", "Long run"),
        ]
    elif target_sessions == 4:
        week_structure = [
            ("Monday", "Rest"),
            ("Tuesday", "Endurance"),
            ("Wednesday", "Rest"),
            ("Thursday", "Threshold"),
            ("Friday", "Rest"),
            ("Saturday", "Tempo"),
            ("Sunday", "Long run"),
        ]
    elif target_sessions == 5:
        week_structure = [
            ("Monday", "Rest"),
            ("Tuesday", "Endurance"),
            ("Wednesday", "Threshold"),
            ("Thursday", "Recovery"),
            ("Friday", "Rest"),
            ("Saturday", "Tempo"),
            ("Sunday", "Long run"),
        ]
    else:  # 6 sessions
        week_structure = [
            ("Monday", "Recovery"),
            ("Tuesday", "Endurance"),
            ("Wednesday", "Threshold"),
            ("Thursday", "Recovery"),
            ("Friday", "Rest"),
            ("Saturday", "Tempo"),
            ("Sunday", "Long run"),
        ]
    
    # Adjust for phase
    if phase == "deload":
        # Reduce all durations by 30%
        week_structure = [(d, "Recovery" if t not in ["Rest", "Long run"] else t) for d, t in week_structure]
    elif phase == "taper":
        # Keep intensity, reduce volume
        week_structure = [(d, "Recovery" if t == "Endurance" else t) for d, t in week_structure]
    
    # Build all sessions — VOLUME-DRIVEN so the sum matches target_km exactly.
    # The long run takes its bounded distance; the remaining volume is split
    # across the work sessions weighted by session type.
    has_long_run = any(t == "Long run" for _, t in week_structure)
    long_total = min(target_long_run, target_km) if has_long_run else 0
    remaining = max(0.0, target_km - long_total)

    # Relative volume weight per session type
    type_weights = {"Recovery": 0.8, "Endurance": 1.3, "Tempo": 1.0, "Threshold": 0.9, "Fartlek": 1.0}
    work_entries = [(d, t) for d, t in week_structure if t not in ("Rest", "Long run")]
    weight_sum = sum(type_weights.get(t, 1.0) for _, t in work_entries) or 1.0

    distances = {}
    for d, t in work_entries:
        distances[(d, t)] = remaining * (type_weights.get(t, 1.0) / weight_sum)

    sessions = []
    for day, session_type in week_structure:
        if session_type == "Long run":
            sessions.append(build_session(day, session_type, custom_distance=long_total))
        elif session_type == "Rest":
            sessions.append(build_session(day, session_type))
        else:
            sessions.append(build_session(day, session_type, custom_distance=distances.get((day, session_type))))

    # Calculate totals
    total_km = round(sum(s["distance_km"] for s in sessions), 1)
    total_tss = sum(s["estimated_tss"] for s in sessions)
    
    # Generate focus text based on phase
    focus_texts = {
        "build": "Volume en endurance fondamentale (Z1-Z2)",
        "deload": "Récupération active - réduction du volume",
        "intensification": "Travail spécifique - seuil et tempo",
        "taper": "Affûtage - maintien intensité, réduction volume",
        "race": "Semaine de course - fraîcheur maximale"
    }
    
    # Build plan
    plan = {
        "focus": focus_texts.get(phase, "Construction aérobie"),
        "planned_load": target_load,
        "weekly_km": total_km,
        "sessions": sessions,
        "total_tss": total_tss,
        "advice": f"Volume actuel: {current_weekly_km} km → cible: {target_km} km. Sortie longue: {target_long_run} km."
    }
    
    elapsed = time.time() - start_time
    metadata["duration_sec"] = round(elapsed, 2)
    metadata["success"] = True
    
    logger.info(f"[Coach] ✅ Plan generated deterministically in {elapsed:.3f}s (TSS: {total_tss}, KM: {total_km})")
    
    return plan, True, metadata


# ============================================================
# INTERNAL FUNCTIONS
# ============================================================

async def _call_gpt(
    system_prompt: str,
    user_prompt: str,
    user_id: str,
    context_type: str
) -> Tuple[Optional[str], bool, Dict]:
    """Call GPT-4o-mini via Emergent LLM Key"""

    start_time = time.time()
    metadata = {
        "model": LLM_MODEL,
        "provider": LLM_PROVIDER,
        "context_type": context_type,
        "duration_sec": 0,
        "success": False
    }

    if not EMERGENT_LLM_KEY or not EMERGENT_LLM_KEY.startswith("sk-emergent"):
        logger.warning("[LLM] Emergent LLM Key not configured")
        return None, False, metadata
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        session_id = f"cardiocoach_{context_type}_{user_id}_{int(time.time())}"
        
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=system_prompt
        ).with_model(LLM_PROVIDER, LLM_MODEL)
        
        response = await asyncio.wait_for(
            chat.send_message(UserMessage(text=user_prompt)),
            timeout=LLM_TIMEOUT
        )
        
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        metadata["success"] = True
        response_text = _clean_response(str(response))

        if response_text:
            logger.info(f"[LLM] ✅ {context_type} enriched in {elapsed:.2f}s")
            return response_text, True, metadata
        else:
            logger.warning(f"[LLM] Empty response for {context_type}")
            return None, False, metadata

    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.warning(f"[LLM] ⏱️ Timeout after {elapsed:.2f}s")
        return None, False, metadata

    except Exception as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ Error: {e}")
        return None, False, metadata


def _format_context(data: Dict) -> str:
    """Formats data into readable text for LLM"""
    lines = []
    for key, value in data.items():
        if value is not None and value != "" and value != {} and value != []:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "No data"


def _format_history(history: List[Dict]) -> str:
    """Formats conversation history"""
    if not history:
        return "Start of conversation"

    lines = []
    for msg in history[-4:]:
        role = "User" if msg.get("role") == "user" else "Coach"
        content = msg.get("content", "")[:150]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _clean_response(response: str) -> str:
    """Cleans GPT response"""
    if not response:
        return ""

    response = response.strip()
    if response.startswith('"') and response.endswith('"'):
        response = response[1:-1]

    if len(response) > 700:
        response = response[:700]
        last_period = max(response.rfind("."), response.rfind("!"), response.rfind("?"))
        if last_period > 400:
            response = response[:last_period + 1]

    return response.strip()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "enrich_chat_response",
    "enrich_weekly_review", 
    "enrich_workout_analysis",
    "generate_cycle_week",
    "LLM_MODEL",
    "LLM_PROVIDER"
]
