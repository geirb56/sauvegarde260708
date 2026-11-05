"""C400 — automatic session comment written by the C396 Coach.

C388/Workout Analysis V2 stay the source of facts; C396 only supplies the voice.
The generated text is never a source of truth: it passes a conservative
deterministic guard (heuristic, NOT a proof of factual accuracy) and any failure
leaves the C388 deterministic narrative as the displayed comment.

Cache and in-flight dedupe are process-local and read/write no database.
No provider is reached from workers: this module is only called from a route.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel

import llm_coach

logger = logging.getLogger(__name__)

COACH_COMMENT_VERSION = "c396-session-comment-v1"
COMMENT_SOURCE = "coach_c396"
VALIDATION_LEVEL = "heuristic_guard"  # explicitly not "factually validated"
COMMENT_TIMEOUT_SEC = 20
SUCCESS_TTL_SEC = 6 * 3600
FAILURE_TTL_SEC = 60
CACHE_MAX = 512
MIN_CHARS, MAX_CHARS = 40, 900


class CoachSessionCommentValidation(BaseModel):
    level: str = VALIDATION_LEVEL
    passed: bool = False
    rejected_checks: list[str] = []


class CoachSessionCommentResponse(BaseModel):
    """Distinct from the C388 narrative: never replaces headline/analysis/interpretation."""
    workout_id: str
    language: str
    status: str  # generated | fallback | unavailable | disabled
    text: Optional[str] = None
    cached: bool = False
    source: str = COMMENT_SOURCE
    coach_version: str = COACH_COMMENT_VERSION
    model: Optional[str] = None
    validation: CoachSessionCommentValidation = CoachSessionCommentValidation()
    fallback: str = "deterministic_c388"


def comment_enabled() -> bool:
    """Off by default: activation is an explicit product decision (see C400 report)."""
    return os.environ.get("C400_SESSION_COMMENT_ENABLED", "").strip().lower() in {"1", "true", "yes"}


# ------------------------------------------------------------------ validation

_NUMBER = re.compile(r"\d+(?::\d+)+|\d+(?:[.,]\d+)?")
_NEGATION = re.compile(
    r"\b(pas|ne|n'|aucun|sans|ni|not|no|cannot|can't|without|nor|sin|ningún|ninguna|tampoco)\b", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#{1,6})\s", re.M)

# Claims the model must not make unless the session facts themselves state them.
_UNSUPPORTED_TERMS = re.compile(
    r"\b(LT1|LT2|VO2\s?max|VMA|FC\s?max|HR\s?max|max(?:imum)?\s+heart\s+rate|seuil|threshold|umbral|"
    r"zones?\s*\d|zona\s*\d|Z[1-5])\b", re.I)
_PROGRESS_TERMS = re.compile(
    r"(progress|improv|amélior|regress|decline|déclin|mejor[aóe]|empeor|retroces|fitness)", re.I)
_SENSATION_TERMS = re.compile(
    r"\b(you felt|tu as ressenti|tu te sentais|tu as dû|ressenti|te sentiste|te sentías|has sentido|"
    r"tu corps|your body)\b", re.I)
_PRESCRIPTION_TERMS = re.compile(
    r"(prochaine?s? (?:séance|sortie|course)|next (?:session|workout|run)|tomorrow|demain|"
    r"próxim[ao] (?:sesión|entrenamiento|salida)|mañana|cette semaine|this week|esta semana|"
    r"je te conseille|i recommend|te recomiendo|you should (?:run|do|try)|tu devrais|deberías)", re.I)
_INTERNAL_TERMS = re.compile(
    r"(Training V2|Workout Analysis|Coach Context|selected_workout_permissions|canonical|C388|C396)", re.I)

_STOPWORDS = {
    "fr": {"le", "la", "les", "de", "des", "et", "une", "est", "sur", "pour", "que", "avec", "tu", "ta", "ton"},
    "en": {"the", "and", "of", "was", "with", "for", "that", "this", "your", "you", "is", "on"},
    "es": {"el", "los", "las", "de", "y", "una", "es", "con", "para", "que", "tu", "en", "del"},
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ']+", text.lower())


def _language_ok(text: str, language: str) -> bool:
    words = _words(text)
    scores = {code: sum(1 for w in words if w in sw) for code, sw in _STOPWORDS.items()}
    target = language if language in scores else "fr"
    return scores[target] >= 2 and all(scores[target] > v for c, v in scores.items() if c != target)


def _collect_numbers(value: Any, out: set[float], tokens: set[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if value == value and abs(value) != float("inf"):
            out.add(float(value))
    elif isinstance(value, str):
        for tok in _NUMBER.findall(value):
            if ":" in tok:
                tokens.add(tok)
            else:
                out.add(float(tok.replace(",", ".")))
    elif isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, out, tokens)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_numbers(v, out, tokens)


def _grounded(number: float, decimals: int, known: set[float]) -> bool:
    tol = 0.5 * 10 ** -decimals + 1e-9
    return any(abs(number - c) <= tol or abs(number - c / 60) <= tol or abs(number - c / 1000) <= tol
               for c in known)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def validate_session_comment(text: Any, context: dict, language: str) -> tuple[bool, list[str]]:
    """Conservative guard. Rejects on any doubt; passing is not proof of accuracy."""
    reasons: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return False, ["empty"]
    text = text.strip()
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        reasons.append("length")
    if _BULLET.search(text):
        reasons.append("format")
    if not _language_ok(text, language):
        reasons.append("language")
    if _INTERNAL_TERMS.search(text):
        reasons.append("internal_terms")

    # Anything the session facts themselves state may be repeated; nothing else.
    facts = json.dumps(
        {k: context.get(k) for k in ("workout_detail", "validated_workout_observations")},
        ensure_ascii=False,
    )
    permissions = context.get("selected_workout_permissions") or {}
    for pattern, reason in ((_UNSUPPORTED_TERMS, "unsupported_physiology"),
                            (_SENSATION_TERMS, "invented_sensation"),
                            (_PRESCRIPTION_TERMS, "prescription")):
        for match in pattern.finditer(text):
            if match.group(0).lower() not in facts.lower():
                reasons.append(reason)
                break
    if permissions.get("progress_regression_allowed") is not True:
        for sentence in _sentences(text):
            if _PROGRESS_TERMS.search(sentence) and not _NEGATION.search(sentence):
                reasons.append("progress_claim")
                break

    known: set[float] = set()
    tokens: set[str] = set()
    _collect_numbers(context, known, tokens)
    for tok in _NUMBER.findall(text):
        if ":" in tok:
            if tok not in tokens:
                reasons.append("ungrounded_number")
                break
            continue
        decimals = len(tok.split(",")[1] if "," in tok else tok.split(".")[1]) if re.search(r"[.,]", tok) else 0
        if not _grounded(float(tok.replace(",", ".")), decimals, known):
            reasons.append("ungrounded_number")
            break
    return not reasons, sorted(set(reasons))


# ------------------------------------------------------------- cache / dedupe

_CACHE: "OrderedDict[str, tuple[float, str, dict]]" = OrderedDict()
_INFLIGHT: dict[str, "asyncio.Future[dict]"] = {}


def reset_state() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()


def cache_key(*, user_id: str, workout_id: str, language: str, facts: Any) -> str:
    """Scoped to user, workout, language, Coach version/model and the exact facts served."""
    payload = json.dumps(
        {"u": user_id, "w": workout_id, "l": language, "v": COACH_COMMENT_VERSION,
         "m": llm_coach.LLM_MODEL, "f": facts},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str, user_id: str) -> Optional[dict]:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires, owner, value = entry
    if expires < time.monotonic() or owner != user_id:
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return dict(value)


def _cache_put(key: str, user_id: str, value: dict, ttl: float) -> None:
    _CACHE[key] = (time.monotonic() + ttl, user_id, dict(value))
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)


def _result(status: str, text: Optional[str] = None, reasons: Optional[list[str]] = None) -> dict:
    return {
        "status": status, "text": text, "source": COMMENT_SOURCE,
        "coach_version": COACH_COMMENT_VERSION, "model": llm_coach.LLM_MODEL,
        "validation": {"level": VALIDATION_LEVEL, "passed": status == "generated",
                       "rejected_checks": reasons or []},
    }


async def _generate(
    build_context: Callable[[], Awaitable[dict]], language: str, user_id: str,
) -> dict:
    try:
        context = await build_context()
        text, success, _meta = await asyncio.wait_for(
            llm_coach.generate_session_comment(context, user_id=user_id),
            timeout=COMMENT_TIMEOUT_SEC,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("[C400] session comment generation failed")
        return _result("fallback", reasons=["error"])
    if not success or not text:
        return _result("fallback", reasons=["llm_unavailable"])
    ok, reasons = validate_session_comment(text, context, language)
    return _result("generated", text.strip()) if ok else _result("fallback", reasons=reasons)


async def get_session_comment(
    *, key: str, user_id: str, language: str,
    build_context: Callable[[], Awaitable[dict]],
) -> tuple[dict, bool]:
    """Return (result, cached). Concurrent identical requests share one LLM call."""
    cached = _cache_get(key, user_id)
    if cached is not None:
        return cached, True
    task = _INFLIGHT.get(key)
    if task is None:
        async def run() -> dict:
            result = await _generate(build_context, language, user_id)
            _cache_put(key, user_id, result,
                       SUCCESS_TTL_SEC if result["status"] == "generated" else FAILURE_TTL_SEC)
            return result

        task = asyncio.ensure_future(run())
        _INFLIGHT[key] = task
        task.add_done_callback(lambda _t, k=key: _INFLIGHT.pop(k, None))
    return dict(await asyncio.shield(task)), False
