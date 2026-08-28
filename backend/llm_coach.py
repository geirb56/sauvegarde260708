"""
RunIndex - LLM Coach Module

This module handles LLM text enrichment for coach conversations and analyses.
Training and physiology values are expected to come from canonical engines
before being passed to this module.
"""

import os
import time
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

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

SYSTEM_PROMPT_COACH = """You are RunIndex, an expert and caring personal running coach.

🎯 YOUR ROLE:
You answer the athlete's questions about their training like a real personal coach.
You have access to ALL their real training data: complete session history, training plan, VO2max, race predictions, fitness metrics.

📊 AVAILABLE DATA:
- COMPLETE session history (last 28 days with distance, duration, pace, HR)
- Weekly training plan (goal, planned sessions)
- Estimated VO2max and race time predictions
- Fitness metrics: ACWR (acute/chronic workload ratio), TSB (freshness)
- Current goal (5K, 10K, Half, Marathon, Ultra, MAINTENANCE)

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
    """Enriches chat response with the configured LLM model.

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
- ACWR: {fitness.get('acwr') if fitness.get('acwr') is not None else 'N/A'} ({fitness.get('acwr_status', 'unavailable')})
- TSB: {fitness.get('tsb') if fitness.get('tsb') is not None else 'N/A'} ({fitness.get('tsb_status', 'unavailable')})

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
    """Enriches weekly review with the configured LLM model."""
    prompt = f"""WEEKLY STATS:
{_format_context(stats)}

Generate a motivating and personalized weekly review based on this data.{_lang_directive(language)}"""

    return await _call_gpt(SYSTEM_PROMPT_BILAN + _lang_directive(language), prompt, user_id, "bilan")


async def enrich_workout_analysis(
    workout: Dict,
    user_id: str = "unknown",
    language: str = "fr"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches workout analysis with the configured LLM model."""
    prompt = f"""SESSION DATA:
{_format_context(workout)}

Analyze this session as a caring running coach.{_lang_directive(language)}"""

    return await _call_gpt(SYSTEM_PROMPT_SEANCE + _lang_directive(language), prompt, user_id, "seance")


async def _call_gpt(
    system_prompt: str,
    user_prompt: str,
    user_id: str,
    context_type: str
) -> Tuple[Optional[str], bool, Dict]:
    """Call the configured LLM model via Emergent LLM Key."""

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
        
        session_id = f"runindex_{context_type}_{user_id}_{int(time.time())}"
        
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
    "LLM_MODEL",
    "LLM_PROVIDER"
]
