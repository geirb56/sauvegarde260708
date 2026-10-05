"""
RunIndex - LLM Coach Module

This module handles LLM text enrichment for coach conversations and analyses.
Training and physiology values are expected to come from canonical engines
before being passed to this module.
"""

import os
import time
import asyncio
import json
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
The Training V2 engine decides the prescription. The Coach only explains it.

📊 AVAILABLE DATA:
- Canonical Training V2 goal, current week, today prescription, readiness, load, paces and performance context
- Bounded factual history of recent workouts (recent_workouts: distance, duration, pace, HR, elevation)
- Factual session detail and canonical Workout Analysis V2 (workout_detail: summary, signals, physiology, pacing, similar sessions comparison) when a workout is selected
- recent_workouts is a bounded selection, not necessarily the athlete's full history; use its coverage metadata and never claim to have reviewed every session when truncated
- Some fields can be unavailable; unavailable data must stay unavailable
- Confidence, sufficiency and extrapolation metadata are authoritative and must be respected

💬 RESPONSE STYLE:
1. Be direct and concise (3-5 sentences max unless detailed analysis requested)
2. Use real data to personalize your response
3. Explain the current prescription and recent training context without inventing new data
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
- Refer to specific sessions when relevant (dates, distances, paces, heart rate)
- When comparing workouts, use the canonical comparison.similar facts without inventing new baselines
- Raw recent_workouts and workout_detail metrics are descriptive facts only. Average HR, pace, zone distribution, splits, or a workout name alone do not establish physiological intensity.
- Never infer threshold, LT1/LT2, easy/hard effort, progress, regression, or physiological efficiency from those raw metrics. A difference in HR or pace between two sessions does not prove progress.
- Physiological or comparative conclusions may only come from available Workout Analysis V2 fields; respect each field's availability, limitations, and confidence.
- Follow selected_workout_permissions literally. If intensity_interpretation_allowed is false, do not label effort or infer training zones from heart rate or pace; when a comparison is not comparable, state differences as descriptive only.
- Use pace display strings verbatim. Do not calculate or verbalize pace from decimal min/km values.
- If Workout Analysis V2 analysis is absent, or the requested conclusion is unavailable, say so clearly and limit the answer to descriptive facts.
- Workout Analysis V2 advice is an observational fact/boundary, not an independent prescription
- Never create a new prescription
- Never modify or replace the served prescription
- Never fabricate missing metrics, readiness scores, paces, or performance certainty
- Respect readiness confidence/sufficiency and performance extrapolation metadata"""

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

    Context is a serialized Coach Context V2 payload built from canonical
    Training V2 authorities.
    """
    language = context.get("language", "fr")
    context_text = json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    # Format conversation history
    history_text = ""
    if conversation_history:
        for msg in conversation_history[-4:]:  # last 4 messages max
            role = "Athlete" if msg.get("role") == "user" else "Coach"
            content = msg.get("content", "")[:200]  # Truncate if too long
            history_text += f"{role}: {content}\n"

    prompt = f"""COACH CONTEXT V2 JSON:
{context_text}

💬 CONVERSATION HISTORY:
{history_text if history_text else "(New conversation)"}

❓ ATHLETE'S QUESTION: {user_message}

Respond in {language.upper()} as a caring and expert personal coach.
Explain only the authoritative data provided above.
When asked about recent sessions or specific workouts, use the factual recent_workouts history and workout_detail Workout Analysis V2 facts.
Treat raw recent_workouts and workout_detail metrics as descriptive facts only: average HR, pace, zone distribution, splits, and workout names alone do not establish physiological intensity. Do not infer threshold, LT1/LT2, easy/hard effort, progress, regression, or physiological efficiency from them; HR/pace differences between sessions do not prove progress.
Follow selected_workout_permissions literally. When intensity_interpretation_allowed is false, raw HR and pace are descriptive only; do not infer effort labels, zones, efficiency, progress, regression, or causes. When similar_comparable is false, describe differences only. Use pace display strings verbatim and never convert a decimal min/km value yourself.
Training V2, readiness, load, and performance are current context; they do not establish the athlete's historical state on a selected workout date.
Use physiological or comparative conclusions only when the corresponding Workout Analysis V2 fields are available, and respect their availability, limitations, and confidence. If analysis is absent or the conclusion is unavailable, say so clearly and stick to descriptive facts.
recent_workouts is a bounded selection, not necessarily the full history. Use its coverage metadata, and if truncated do not claim to have reviewed all sessions in the period.
If a field is unavailable or low-confidence, say so plainly.
Workout Analysis V2 advice is not a new prescription. Training V2 remains the sole prescription authority; do not invent a prescription or alter the served prescription.{_lang_directive(language)}"""

    return await _call_gpt(SYSTEM_PROMPT_COACH + _lang_directive(language), prompt, user_id, "chat")


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
    "LLM_MODEL",
    "LLM_PROVIDER"
]
