"""C400 — automatic session comment written by the C396 Coach.

C388/Workout Analysis V2 stay the source of facts; C396 only supplies the voice.
The generated text is never a source of truth. It passes a conservative,
deterministic *heuristic* guard (NOT a proof of factual accuracy): any claim the
guard cannot tie to the selected session's facts makes the comment fall back to
the C388 deterministic narrative.

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
from typing import Any, Optional

from pydantic import BaseModel

import llm_coach

logger = logging.getLogger(__name__)

COACH_COMMENT_VERSION = "c396-session-comment-v2"
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


# ------------------------------------------------------------------ fact scope

def _walk(value: Any, path: tuple, out: list) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _walk(item, path + (str(key).lower(),), out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, path, out)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float, str)):
        out.append((path, value))


def split_session_facts(context: dict) -> tuple[list, list]:
    """(session facts, comparison facts) as flattened (key path, leaf) pairs.

    Only workout_detail and validated_workout_observations describe the selected
    session. recent_workouts, Training V2, readiness, load and performance are
    deliberately excluded: they are context, not facts about this workout.
    """
    detail = dict(context.get("workout_detail") or {})
    analysis = dict(detail.get("analysis") or {})
    comparison = analysis.pop("comparison", None)
    detail["analysis"] = analysis
    session: list = []
    _walk(detail, (), session)
    _walk(context.get("validated_workout_observations") or {}, ("observations",), session)
    compared: list = []
    _walk(comparison or {}, ("comparison",), compared)
    return session, compared


_NUMBER_IN_TEXT = re.compile(r"(?<![\w:.,])\d+(?:[.,]\d+)?")
_TOKEN = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])")
_HM = re.compile(r"\b(\d{1,2})\s*h\s*(\d{1,2})?\b", re.I)


def _is(path: tuple, *needles: str) -> bool:
    return any(n in part for part in path for n in needles)


def _has_none(path: tuple, *needles: str) -> bool:
    return not _is(path, *needles)


def _build_pools(facts: list) -> dict:
    pools: dict[str, set] = {k: set() for k in
                             ("km", "bpm", "min", "sec", "m", "kmh", "pct", "delta", "count", "any")}
    token_seconds: set[float] = set()
    for path, value in facts:
        if isinstance(value, str):
            for h, m, s in re.findall(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])", value):
                token_seconds.add(int(h) * 60 + int(m) if not s else int(h) * 3600 + int(m) * 60 + int(s))
            for tok in _NUMBER_IN_TEXT.findall(value):
                pools["any"].add(float(tok.replace(",", ".")))
            continue
        v = float(value)
        if v != v or abs(v) == float("inf"):
            continue
        pools["any"].add(v)
        pace_like = _is(path, "pace", "per_km", "min_km", "sec_km")
        if pace_like:
            seconds = v if _is(path, "second", "sec_") and not _is(path, "min_km") else v * 60
            token_seconds.add(round(seconds))
            pools["delta"].add(abs(v))
            continue
        if _is(path, "speed", "kmh"):
            pools["kmh"].add(v)
        elif _is(path, "distance") or (_is(path, "_km") and _has_none(path, "split")):
            pools["km"].add(v)
            pools["m"].add(v * 1000)
        elif _is(path, "hr", "heart"):
            pools["bpm"].add(v)
        elif _is(path, "elevation", "gain") or any(part.endswith("_m") for part in path):
            pools["m"].add(v)
        elif _is(path, "duration", "elapsed", "moving", "minute", "second", "_sec", "_min", "time"):
            pools["min"].update({v, v / 60})
            pools["sec"].update({v, v * 60})
            token_seconds.update({round(v * 60), round(v)})
        elif _is(path, "pct", "percent", "ratio", "share"):
            pools["pct"].update({v, v * 100})
        elif _is(path, "count", "effort", "recover", "repet", "reference", "sample", "number", "total"):
            pools["count"].add(v)
        if _is(path, "difference", "delta", "diff", "gap"):
            pools["delta"].add(abs(v))
    pools["tokens"] = token_seconds  # type: ignore[assignment]
    return pools


_UNIT_POOL = [
    (re.compile(r"^(km/h|kmh|km/hr)", re.I), "kmh"),
    (re.compile(r"^(s/km|sec/km|secs/km)", re.I), "delta"),
    (re.compile(r"^(bpm|ppm|battements|beats|pulsaciones|lpm)", re.I), "bpm"),
    (re.compile(r"^km\b|^kilom", re.I), "km"),
    (re.compile(r"^(m|mètres|metres|meters|metros|mt)\b", re.I), "m"),
    (re.compile(r"^(min|mins|minutes|minutos)\b", re.I), "min"),
    (re.compile(r"^(s|sec|secs|secondes|seconds|segundos)\b", re.I), "sec"),
    (re.compile(r"^%"), "pct"),
    (re.compile(r"^(répétitions|repetitions|repeticiones|reps|efforts|esfuerzos|intervalles|intervals|"
                r"intervalos|séries|fois|times|veces|récupérations|recoveries|recuperaciones|"
                r"séances|sessions|sesiones)\b", re.I), "count"),
]


def _match(value: float, decimals: int, candidates: set) -> bool:
    tol = 0.5 * 10 ** -decimals + 1e-9
    return any(abs(value - c) <= tol for c in candidates)


_NUMBER_WORDS = re.compile(
    r"\b(un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|"
    r"one|two|three|four|five|seven|eight|nine|ten|eleven|twelve|"
    r"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(km|kilomètres?|kilometers?|kilómetros?|répétitions?|repetitions?|repeticiones|fois|times|veces|"
    r"efforts?|esfuerzos|séries|reps|minutes?|minutos|bpm|intervalles|intervals|intervalos)\b", re.I)

_MONTHS = {
    1: ("janvier", "january", "enero"), 2: ("février", "february", "febrero"),
    3: ("mars", "march", "marzo"), 4: ("avril", "april", "abril"), 5: ("mai", "may", "mayo"),
    6: ("juin", "june", "junio"), 7: ("juillet", "july", "julio"), 8: ("août", "august", "agosto"),
    9: ("septembre", "september", "septiembre", "setiembre"), 10: ("octobre", "october", "octubre"),
    11: ("novembre", "november", "noviembre"), 12: ("décembre", "december", "diciembre"),
}
_MONTH_NAMES = {name: m for m, names in _MONTHS.items() for name in names}
_DATE_TEXT = re.compile(
    r"\b(\d{1,2})(?:er|st|nd|rd|th)?\s+(?:de\s+)?(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
    + r")\b|\b(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True)) + r")\s+(\d{1,2})\b", re.I)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# ------------------------------------------------------------------ claim guards

_NEGATION = re.compile(
    r"\b(pas|ne|n'|aucun|aucune|sans|ni|not|no|cannot|can't|without|nor|sin|ningún|ninguna|"
    r"tampoco|nunca|jamais|never)\b|n'", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#{1,6})\s", re.M)
_COMPARISON = re.compile(
    r"(compar|\bvs\b|versus|par rapport|plus (?:rapide|lent|vite)\w* que|moins (?:rapide|vite)\w* que|"
    r"(?:faster|slower|higher|lower|better|worse) than|than (?:usual|your|before|similar|earlier)|"
    r"s[ée]ances? (?:similaires?|comparables?|pr[ée]c[ée]dentes?|ant[ée]rieures?)|"
    r"similar (?:sessions?|workouts?|runs?)|earlier (?:sessions?|runs?)|previous (?:sessions?|runs?)|"
    r"sesiones? (?:similares?|comparables?|anteriores?)|en comparaci|"
    r"d'habitude|habituellement|usual(?:ly)?|habitual|normalmente|"
    r"que d'ordinaire|que la moyenne|than average|average of your|más (?:rápid|lent)\w* que|"
    r"menos (?:rápid|lent)\w* que)", re.I)
_UNSUPPORTED_PHYSIO = re.compile(
    r"(\bLT[12]\b|VO2\s?max|\bVMA\b|\bFC\s?max\b|\bHR\s?max\b|max(?:imum)?\s+heart\s+rate|"
    r"fr[ée]quence cardiaque maximale|frecuencia card[ií]aca m[aá]xima|\bseuil|threshold|umbral|"
    r"\bzones?\s*\d|\bzona\s*\d|\bZ[1-5]\b|anaerobic|ana[ée]robie|anaer[óo]bic|lactate|lactato)", re.I)
_INTENSITY = re.compile(
    r"\b(easy|hard|facile|difficile|dur(?:e|es)?|intense|intensit[ée]|intensity|intensidad|f[áa]cil|"
    r"tempo|recovery|r[ée]cup[ée]ration|recuperaci[óo]n|endurance fondamentale|aerobic|a[ée]robie|a[ée]robic[oa]|"
    r"effort (?:mod[ée]r[ée]|soutenu|[ée]lev[ée])|moderate effort|hard effort)\b", re.I)
_EFFICIENCY = re.compile(
    r"(efficien|efficac|[ée]conomie de course|running economy|econom[ií]a de carrera|rendement)", re.I)
_CAUSAL = re.compile(
    r"\b(because|due to|thanks to|as a result of|parce que|[àa] cause|en raison|gr[âa]ce [àa]|"
    r"porque|debido a|gracias a)\b", re.I)
_PROGRESS = re.compile(
    r"(progress|improv|am[ée]lior|regress|decline|d[ée]clin|mejor[aóe]\w*|empeor|retroces|fitness|"
    r"gagn[ée] en|gained|ganado en)", re.I)
_SENSATION = re.compile(
    r"(you felt|you were (?:tired|exhausted|strong)|tu as ressenti|tu te sentais|tu as d[ûu]|ressenti|"
    r"te sentiste|te sent[ií]as|has sentido|fatigu|tired|exhaust|[ée]puis|cansad|agotad|your body|tu corps|"
    r"tu cuerpo|sensations?)", re.I)
_PRESCRIPTION = re.compile(
    r"(prochaine?s? (?:s[ée]ance|sortie|course)|next (?:session|workout|run)|tomorrow|demain|"
    r"pr[óo]xim[ao] (?:sesi[óo]n|entrenamiento|salida)|ma[ñn]ana|cette semaine|this week|esta semana|"
    r"je te conseille|i recommend|te recomiendo|you should (?:run|do|try|take)|tu devrais|deber[ií]as|"
    r"tu peux (?:enchaîner|prévoir)|try to|essaie de|intenta)", re.I)
_CONTEXT_LEAK = re.compile(
    r"(objectif|\bgoal\b|objetivo|marathon|semi-marathon|half[- ]marathon|medio marat|readiness|"
    r"pr[ée]paration (?:course|à)|race day|jour de course|d[ée]but de cycle|training plan|plan d'entra)", re.I)
_INTERNAL = re.compile(
    r"(Training V2|Workout Analysis|Coach Context|selected_workout_permissions|canonical|C388|C396)", re.I)

_STOPWORDS = {
    "fr": {"le", "la", "les", "des", "et", "une", "est", "sur", "pour", "avec", "tu", "ta", "ton", "tes", "du",
           "un", "dans", "qui", "pas", "plus", "très", "ce", "cette", "au", "aux", "vous", "sont", "été",
           "par", "ça", "mais", "ou", "où", "il", "elle", "sortie", "séance"},
    "en": {"the", "and", "of", "was", "with", "for", "that", "this", "your", "you", "is", "on", "at",
           "it", "to", "but", "very", "more", "from", "as", "by", "were", "which", "run", "session"},
    "es": {"el", "los", "las", "del", "una", "un", "es", "con", "para", "por", "muy", "más", "tu", "tus",
           "se", "lo", "su", "al", "fue", "sido", "pero", "sobre", "salida", "sesión", "ritmo", "y", "o"},
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ']+", text.lower())


def _language_ok(text: str, language: str) -> bool:
    words = _words(text)
    scores = {code: sum(1 for w in words if w in sw) for code, sw in _STOPWORDS.items()}
    target = language if language in scores else "fr"
    return scores[target] >= 2 and all(scores[target] > v for c, v in scores.items() if c != target)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _parse_date(value: Any):
    from datetime import datetime
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _check_numbers(sentence: str, session: dict, compared: dict, comparison_ok: bool,
                   reasons: set) -> None:
    has_comparison_wording = bool(_COMPARISON.search(sentence))
    masked = _ISO_DATE.sub(" ", _DATE_TEXT.sub(" ", sentence))

    for match in _TOKEN.finditer(masked):
        h, m, s = match.groups()
        seconds = int(h) * 3600 + int(m) * 60 + int(s) if s else int(h) * 60 + int(m)
        if any(abs(seconds - t) <= 1 for t in session["tokens"]):
            continue
        if comparison_ok and any(abs(seconds - t) <= 1 for t in compared["tokens"]):
            if not has_comparison_wording:
                reasons.add("comparison_value_as_session")
            continue
        reasons.add("ungrounded_pace_or_time")
    masked = _TOKEN.sub(" ", masked)

    for match in _HM.finditer(masked):
        minutes = int(match.group(1)) * 60 + int(match.group(2) or 0)
        if not any(abs(minutes - c) <= 1 for c in session["min"]):
            reasons.add("ungrounded_duration")
    masked = _HM.sub(" ", masked)

    for match in _NUMBER_IN_TEXT.finditer(masked):
        raw = match.group(0)
        value = float(raw.replace(",", "."))
        decimals = len(re.split(r"[.,]", raw)[1]) if re.search(r"[.,]", raw) else 0
        rest = masked[match.end():match.end() + 18].lstrip()
        pool_name = next((name for rx, name in _UNIT_POOL if rx.match(rest)), None)
        pool = pool_name or "any"
        if _match(value, decimals, session[pool]):
            continue
        if comparison_ok and _match(value, decimals, compared[pool]):
            if not has_comparison_wording:
                reasons.add("comparison_value_as_session")
            continue
        reasons.add("ungrounded_number")


def validate_session_comment(text: Any, context: dict, language: str) -> tuple[bool, list[str]]:
    """Conservative heuristic guard; rejects whatever it cannot tie to session facts.

    Passing means "no checked claim contradicted the selected session's facts",
    never "the text is true".
    """
    if not isinstance(text, str) or not text.strip():
        return False, ["empty"]
    text = text.strip()
    reasons: set[str] = set()
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        reasons.add("length")
    if _BULLET.search(text):
        reasons.add("format")
    if not _language_ok(text, language):
        reasons.add("language")
    if _INTERNAL.search(text):
        reasons.add("internal_terms")
    if _NUMBER_WORDS.search(text):
        reasons.add("unverifiable_number_word")

    permissions = context.get("selected_workout_permissions") or {}
    session_facts, comparison_facts = split_session_facts(context)
    comparison_ok = bool(permissions.get("similar_comparison_available"))
    session = _build_pools(session_facts)
    compared = _build_pools(comparison_facts if comparison_ok else [])
    facts_text = json.dumps([v for _, v in session_facts], ensure_ascii=False).lower()

    def stated_in_facts(match: "re.Match") -> bool:
        return match.group(0).lower() in facts_text

    for pattern, reason in ((_UNSUPPORTED_PHYSIO, "unsupported_physiology"),
                            (_SENSATION, "invented_sensation"),
                            (_PRESCRIPTION, "prescription"),
                            (_CONTEXT_LEAK, "context_as_session_fact")):
        if any(not stated_in_facts(m) for m in pattern.finditer(text)):
            reasons.add(reason)
    if permissions.get("intensity_interpretation_allowed") is not True:
        if any(not stated_in_facts(m) for m in _INTENSITY.finditer(text)):
            reasons.add("intensity_not_allowed")
    if permissions.get("physiological_efficiency_allowed") is not True and _EFFICIENCY.search(text):
        reasons.add("efficiency_not_allowed")
    if permissions.get("causal_explanation_allowed") is not True and _CAUSAL.search(text):
        reasons.add("causal_not_allowed")

    selected_date = _parse_date(
        (context.get("workout_detail") or {}).get("start_time")
        or (context.get("workout_detail") or {}).get("date"))
    for match in _DATE_TEXT.finditer(text):
        day = int(match.group(1) or match.group(4))
        month = _MONTH_NAMES[(match.group(2) or match.group(3)).lower()]
        if selected_date is None or (selected_date.day, selected_date.month) != (day, month):
            reasons.add("ungrounded_date")
    if any(selected_date is None or d != selected_date.isoformat() for d in _ISO_DATE.findall(text)):
        reasons.add("ungrounded_date")

    for sentence in _sentences(text):
        if _COMPARISON.search(sentence) and not comparison_ok:
            reasons.add("comparison_not_available")
        if permissions.get("progress_regression_allowed") is not True \
                and _PROGRESS.search(sentence) and not _NEGATION.search(sentence):
            reasons.add("progress_claim")
        _check_numbers(sentence, session, compared, comparison_ok, reasons)
    return not reasons, sorted(reasons)


# ------------------------------------------------------------- cache / dedupe

_CACHE: "OrderedDict[str, tuple[float, str, dict]]" = OrderedDict()
_INFLIGHT: dict[str, "asyncio.Future[dict]"] = {}


def reset_state() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()


def cache_key(*, user_id: str, workout_id: str, language: str, context: Any) -> str:
    """Exact fingerprint of what is sent to C396: any context change is a new key.

    Also scoped to user, workout, language, Coach comment version and model.
    """
    payload = json.dumps(
        {"u": user_id, "w": workout_id, "l": language, "v": COACH_COMMENT_VERSION,
         "m": llm_coach.LLM_MODEL, "c": context},
        sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"),
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


async def _generate(context: dict, language: str, user_id: str) -> dict:
    try:
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
    *, key: str, user_id: str, language: str, context: dict,
) -> tuple[dict, bool]:
    """Return (result, cached). Concurrent identical requests share one LLM call."""
    cached = _cache_get(key, user_id)
    if cached is not None:
        return cached, True
    task = _INFLIGHT.get(key)
    if task is None:
        async def run() -> dict:
            result = await _generate(context, language, user_id)
            _cache_put(key, user_id, result,
                       SUCCESS_TTL_SEC if result["status"] == "generated" else FAILURE_TTL_SEC)
            return result

        task = asyncio.ensure_future(run())
        _INFLIGHT[key] = task
        task.add_done_callback(lambda _t, k=key: _INFLIGHT.pop(k, None))
    return dict(await asyncio.shield(task)), False
