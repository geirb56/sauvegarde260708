"""C409 — conversational activity references, session comparisons and follow-ups.

Pure parsing (`parse_message`) is separated from the read-only, owner-scoped resolution
(`resolve_turn`). Activity identity is always the real `workouts.id`; dates and titles are
only selectors. Conversation memory is the `coach_refs` field stored on the existing
assistant messages of the `conversations` collection (no new store).

Comparison answers are assembled deterministically from a structured contract: every number
shown is a stored measurement or a difference computed from the displayed values, and
physiological conclusions that two sessions cannot prove are explicitly not drawn. No Garmin
call, no write.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Optional

from coach_activity_text import MONTHS, lang_of, t
from workout_analysis_v2 import (
    SIMILAR_DISTANCE_TOLERANCE_PCT,
    SIMILAR_HISTORY_WINDOW_DAYS,
    SIMILAR_MAX_RESULTS,
)
from workout_analysis_v2_service import (
    _extract_garmin_external_id,
    _fetch_garmin_activity,
    _is_garmin_workout,
    _reliable_activity_type,
    enrich_workout_from_garmin_activity,
)
from workout_intelligence_v3 import LONG_RUN_DURATION_RATIO, LONG_RUN_MIN_HISTORY

REFS_VERSION = 1
CHOICE_LIMIT = 5
HISTORY_DEFAULT_COUNT = 3
HISTORY_MAX_COUNT = SIMILAR_MAX_RESULTS
_PROJECTION = {
    "_id": 0, "id": 1, "user_id": 1, "type": 1, "name": 1, "date": 1, "distance_km": 1,
    "duration_minutes": 1, "avg_heart_rate": 1, "max_heart_rate": 1, "avg_pace_min_km": 1,
    "elevation_gain_m": 1, "data_source": 1, "external_id": 1,
}

_MONTHS = {
    "janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11, "decembre": 12, "dec": 12,
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
    "enero": 1, "ene": 1, "febrero": 2, "marzo": 3, "abril": 4, "abr": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "ago": 8, "septiembre": 9, "setiembre": 9, "set": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12, "dic": 12,
}
_WEEKDAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_ALT = "|".join(_WEEKDAYS)
_NUMBER_WORDS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "two": 2, "three": 3, "four": 4, "five": 5,
                 "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_RE = re.compile(
    r"(?<![\w:.,/-])(\d{1,2})(?:/(\d{1,2})(?:/(\d{4}|\d{2}))?|[-.](\d{1,2})[-.](\d{4}))(?![\w:/-])")
_DAY_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}})\s*(?:er|st|nd|rd|th)?\s+(?:de\s+|d')?({_MONTH_ALT})\b\.?(?:\s+(?:de\s+)?(\d{{4}}))?")
_MONTH_DAY_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")
_WEEKDAY_RE = re.compile(rf"\b({_WEEKDAY_ALT})\b")
_LAST_RE = re.compile(
    r"\b(?:ma|mon|ta|ton|la|ma toute|my|the|mi|el|tu)?\s*(?:derniere|dernier|last|latest|most recent|"
    r"ultima|ultimo|mas reciente)\s+"
    r"(?:sortie|course|seance|run|workout|session|semi|marathon|activite|footing|salida|carrera|sesion|"
    r"entrenamiento|actividad|half(?:-| )?marathon|half|media maraton|medio maraton|maraton)\b|"
    r"\b(?:derniere|dernier)\s+(?:semi|marathon)\b")
_PREVIOUS_RE = re.compile(
    r"\b(?:precedente|precedent|previous(?:\s+(?:one|run|workout|session))?|avant[- ]derniere|anterior|"
    r"penultima|penultimo|one before|the one before|the one prior|the prior one|"
    r"celle d['’ ]?avant|celle avant|la de antes|la de atras)\b"
    r"(?!\s+(?:sorties|seances|courses|runs|workouts|sessions|salidas|carreras|sesiones|entrenamientos))")
_SAME_DISTANCE_RE = re.compile(
    r"\b(?:meme distance|distance (?:similaire|identique|comparable|equivalente)|same distance|"
    r"similar distance|equivalent distance|misma distancia|distancia (?:similar|parecida|identica|equivalente))\b")
_HALF_RE = re.compile(
    r"\b(?:semi(?:-| )?marathon|semi|half(?:-| )?marathon|half|medio maraton|media maraton)\b")
_FULL_RE = re.compile(r"(?<!semi-)(?<!semi )(?<!half-)(?<!half )(?<!medio )(?<!media )\b(?:marathon|maraton)\b")
_KM_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*km\b")
_COMPARE_RE = re.compile(
    r"\bcompar|\bversus\b|\bvs\b|par rapport|\bcontre\b|\bagainst\b|\bdiffer|frente a|respecto a")
_HISTORY_RE = re.compile(
    r"(?:(\d+|deux|trois|quatre|cinq|two|three|four|five|dos|tres|cuatro)\s+)?"
    r"(?:dernieres?|last|previous|precedentes?|recent|recentes?|ultimas?|ultimos?|anteriores|recientes?)\s+"
    r"(?:sorties?|seances?|courses?|runs?|workouts?|sessions?|salidas?|carreras?|sesiones|sesion|entrenamientos?)"
    r"(?:\s+(longues?|similaires?|comparables?|long|similar|comparable|largas?|largos?|parecidas?|similares))?|"
    r"(?:sorties?|seances?|runs?|workouts?|salidas?|carreras?|sesiones|entrenamientos?)\s+"
    r"(longues?|similaires?|comparables?|long|similar|largas?|largos?|parecidas?|similares)")
_ANAPHORA_RE = re.compile(
    r"\b(?:celle-ci|celui-ci|cette (?:sortie|seance|course|activite)|this (?:run|session|workout|one)|"
    r"la precedente|the previous one|les deux|ces deux|both|these two|ces seances|ces sorties|"
    r"compare[- ]la|compare[- ]les|compare it|compare them|cette meme|"
    r"esta (?:salida|sesion|carrera|actividad)|esta misma|la anterior|las dos|los dos|ambas|ambos|"
    r"estas dos|esas dos|estas (?:sesiones|salidas)|compara(?:la|lo|las|los))\b")
_BOTH_RE = re.compile(
    r"\b(?:les deux|ces deux|both|these two|ces seances|ces sorties|compare[- ]les|compare them|"
    r"las dos|los dos|ambas|ambos|estas dos|esas dos|estas (?:sesiones|salidas)|comparalas|comparalos)\b")
_ORDINAL_RE = re.compile(
    r"\b(?:la |le |the |el )?(premiere|premier|first|seconde|second|deuxieme|derniere|dernier|last|"
    r"primera|primero|segunda|segundo|ultima|ultimo|\d{1,2})\b")
_TOPIC_CHANGE_RE = re.compile(
    r"\b(?:autre sujet|parlons d'autre chose|changeons de sujet|change of subject|different topic|"
    r"oublie (?:ca|cette|ces)|forget (?:that|this)|cambiemos de tema|otro tema|hablemos de otra cosa|"
    r"olvida (?:eso|esto|esa|esas))\b")
_PLAN_INTENT_RE = re.compile(
    r"\b(?:dois-je|dois je|devrais-je|devrais je|what should i|should i|what do i|que faire|quoi faire|que debo|"
    r"que deberia|que hago|demain|tomorrow|manana|prochaine?s?|next|cible|target|objectif|objetivo|goal|"
    r"proxim[oa]s?|planning|plan)\b")
_ANALYSE_RE = re.compile(
    r"\b(?:analys|analyz|analiz|compar|explique|explain|resume|summar|how was|comment etait|como fue|"
    r"qu'est-ce que tu penses)")
_PLAN_EXCLUDE_RE = re.compile(
    r"\b(?:cible|objectif|target|goal|demain|tomorrow|prochaine|prochain|next|plan|aujourd|today|semaine|week|"
    r"objetivo|manana|proxima|proximo|hoy|semana)\b")
_FOCUS_PATTERNS = (
    ("progress", re.compile(
        r"\bprogress|\bamelior|\bforme\b|\bimproving\b|\bfitter\b|\bfitness\b|\bprogres|\bmejorando\b|\bmejoro\b|"
        r"\bmejoras\b|\bforma fisica\b")),
    ("demanding", re.compile(
        r"exigeant|difficile|\bdur(?:e|s)?\b|\bhardest\b|\bharder\b|\bdemanding\b|\btough|exigente|"
        r"\bdificil|\bmas dur[oa]s?\b")),
    ("hr", re.compile(
        r"cardio|\bfc\b|frequence cardiaque|\bbpm\b|heart|\bhr\b|coeur|frecuencia cardiaca|ritmo cardiaco|"
        r"pulsaciones|\bppm\b|corazon")),
    ("pace", re.compile(
        r"plus vite|\ballure|\bvitesse|\brapide|\bfaster\b|\bfastest\b|\bpace\b|\britmo\b|\bvelocidad|"
        r"\brapid[oa]s?\b|\bmas deprisa")),
    ("distance", re.compile(
        r"\bdistance\b|plus longue|plus long\b|\blongest\b|\bfarther\b|\bdistancia\b|\bmas larg[oa]\b")),
    ("duration", re.compile(r"\bduree\b|\btemps\b|\bduration\b|\bduracion\b|\btiempo\b")),
    ("elevation", re.compile(r"denivele|\belevation\b|\bd\+|\bdesnivel")),
)
_WHY_RE = re.compile(r"\bpourquoi\b|\bwhy\b|\bexplique|\bexplain\b|\bpor que\b|\bexplica\b")
_FOLLOWUP_RE = re.compile(r"^\s*(?:et|and|mais|ok|d'accord|y|pero|vale|de acuerdo)\b")


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return stripped.lower().replace("\u2019", "'")


def _valid_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _complete_year(month: int, day: int, year: Optional[int], today: date) -> Optional[date]:
    if year is not None:
        if year < 100:
            year += 2000
        return _valid_date(year, month, day)
    candidate = _valid_date(today.year, month, day)
    if candidate is None:
        return None
    return candidate if candidate <= today else _valid_date(today.year - 1, month, day)


def _weekday_date(weekday: int, today: date) -> date:
    return today - timedelta(days=(today.weekday() - weekday) % 7)


def _dates_in(text: str, today: date) -> list[date]:
    """Calendar dates mentioned, in order of appearance, without duplicates."""
    found: list[tuple[int, date]] = []
    consumed: list[tuple[int, int]] = []

    def take(match: "re.Match", value: Optional[date]) -> None:
        if value is not None:
            found.append((match.start(), value))
        consumed.append(match.span())

    for m in _ISO_RE.finditer(text):
        take(m, _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _DAY_MONTH_RE.finditer(text):
        year = int(m.group(3)) if m.group(3) else None
        take(m, _complete_year(_MONTHS[m.group(2)], int(m.group(1)), year, today))
    for m in _MONTH_DAY_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        year = int(m.group(3)) if m.group(3) else None
        take(m, _complete_year(_MONTHS[m.group(1)], int(m.group(2)), year, today))
    for m in _NUMERIC_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        month = m.group(2) or m.group(4)
        year_text = m.group(3) or m.group(5)
        take(m, _complete_year(int(month), int(m.group(1)), int(year_text) if year_text else None, today))
    for m in re.finditer(r"\b(hier|yesterday|ayer)\b", text):
        found.append((m.start(), today - timedelta(days=1)))
    for m in re.finditer(r"\b(aujourd'hui|today|ce matin|ce soir|hoy|esta manana)\b", text):
        found.append((m.start(), today))
    for m in _WEEKDAY_RE.finditer(text):
        found.append((m.start(), _weekday_date(_WEEKDAYS[m.group(1)], today)))
    ordered: list[date] = []
    for _, value in sorted(found):
        if value <= today and value not in ordered:
            ordered.append(value)
    return ordered


_HISTORY_EN_RE = re.compile(
    r"(?:last|previous|recent|ultimas|ultimos)\s+(\d+|two|three|four|five|dos|tres|cuatro|cinco)\s+"
    r"(long|similar|comparable|largas|largos|parecidas|similares)?\s*"
    r"(?:runs?|workouts?|sessions?|salidas|carreras|sesiones|entrenamientos)")


_HISTORY_COUNT_RE = re.compile(
    r"\b(\d+|deux|trois|quatre|cinq|two|three|four|five|dos|tres|cuatro|cinco)\s+"
    r"(?:sorties?|seances?|courses?|runs?|workouts?|sessions?|salidas?|carreras?|sesiones|entrenamientos?)"
    r"(?:\s+(precedentes|previous|anteriores))?\b")


def _history_match(text: str):
    """Count-before-noun wording ("3 sorties de même distance", "3 sorties précédentes") is also a history."""
    found = _HISTORY_RE.search(text) or _HISTORY_EN_RE.search(text)
    if found:
        return found
    counted = _HISTORY_COUNT_RE.search(text)
    return counted if counted and (counted.group(2) or _SAME_DISTANCE_RE.search(text)) else None


def _history_request(text: str) -> Optional[dict]:
    match = _HISTORY_RE.search(text)
    if not match:
        match = _history_match(text)
        if match is None:
            return None
    raw_count = match.group(1)
    count = HISTORY_DEFAULT_COUNT
    if raw_count:
        count = _NUMBER_WORDS.get(raw_count) or int(raw_count)
    qualifier = _norm(match.group(2) or (match.group(3) if match.re is _HISTORY_RE else "") or "")
    kind = "recent"
    if _SAME_DISTANCE_RE.search(text):
        kind = "similar"
    elif qualifier.startswith(("long", "larg")):
        kind = "long"
    elif qualifier.startswith(("simil", "compar", "parec")):
        kind = "similar"
    return {"kind": kind, "count": max(1, min(count, HISTORY_MAX_COUNT))}


def _focus_of(text: str) -> Optional[str]:
    for name, pattern in _FOCUS_PATTERNS:
        if pattern.search(text):
            return name
    return None


def parse_message(message: str, today: date) -> dict:
    """Pure interpretation of one message; never touches data."""
    text = _norm(message)
    history = _history_request(text) if (_COMPARE_RE.search(text) or _history_match(text)) else None
    if history is not None and history["kind"] == "recent" and not _COMPARE_RE.search(text):
        history = None
    dates = [] if history is not None and not (_DAY_MONTH_RE.search(text) or _MONTH_DAY_RE.search(text)
                                               or _NUMERIC_RE.search(text) or _ISO_RE.search(text)) \
        else _dates_in(text, today)
    last_vs_previous = bool(_COMPARE_RE.search(text) and _LAST_RE.search(text) and _PREVIOUS_RE.search(text)
                            and not _SAME_DISTANCE_RE.search(text))
    if last_vs_previous:
        history = None  # "my last run vs the previous one" names two activities, not a history request
    planning = bool(_PLAN_INTENT_RE.search(text)) and not _ANALYSE_RE.search(text)
    if planning:
        # A planning question is for the Coach / Training Engine, never a lookup of a performed activity.
        dates, history = [], None
    selectors: list[dict] = [{"type": "date", "date": d} for d in dates]
    # "Compare my 12 October run with the one before": the reference of "before" is the named date,
    # never the opened activity.
    before_date = bool(len(dates) == 1 and history is None and not last_vs_previous and not planning
                       and _COMPARE_RE.search(text) and _PREVIOUS_RE.search(text))
    if before_date:
        selectors.append({"type": "before", "date": dates[0]})
    if not selectors and not planning:
        km = _KM_RE.search(text)
        if last_vs_previous:
            selectors.extend([{"type": "last"}, {"type": "last", "offset": 1}])
        elif _LAST_RE.search(text) and history is None:
            if _HALF_RE.search(text):  # the half marathon has precedence over the marathon
                selectors.append({"type": "last", "km": (20.5, 22.0)})
            elif _FULL_RE.search(text):
                selectors.append({"type": "last", "km": (41.5, 43.5)})
            else:
                selectors.append({"type": "last"})
        elif km and history is None:
            value = float(km.group(1).replace(",", "."))
            tolerance = max(0.5, value * 0.05)
            selectors.append({"type": "distance", "km": (value - tolerance, value + tolerance), "value": value})
        elif (_HALF_RE.search(text) or _FULL_RE.search(text)) and history is None and re.search(
                r"\b(?:ma|mon|my|la|le|the)\s+(?:sortie|course|seance|run|semi|marathon|half)", text):
            selectors.append({"type": "distance", "km": (20.5, 22.0) if _HALF_RE.search(text) else (41.5, 43.5)})
    if re.search(r"\b(?:objectif|objetivo|goal|target|cible)\b", text):
        # "mon objectif 10 km" designates a target, not a past activity
        selectors = [x for x in selectors if x["type"] != "distance"]
    ordinal = _ORDINAL_RE.search(text)
    return {
        "text": text,
        "selectors": selectors,
        "before_date": before_date,
        "compare": bool(_COMPARE_RE.search(text)),
        "history": history,
        "anaphora": bool(_ANAPHORA_RE.search(text)),
        "both": bool(_BOTH_RE.search(text)),
        "focus": _focus_of(text),
        "why": bool(_WHY_RE.search(text)),
        "ordinal": ordinal.group(1) if ordinal else None,
        "topic_change": bool(_TOPIC_CHANGE_RE.search(text)),
        "plan_related": planning or bool(_PLAN_EXCLUDE_RE.search(text)),
        "followup": bool(_FOLLOWUP_RE.search(text)),
    }


def needs_memory(parsed: dict) -> bool:
    """Whether the previous turn's references may be required (avoids a read otherwise)."""
    return bool(
        parsed["anaphora"] or parsed["compare"] or parsed["history"] is not None
        or parsed["ordinal"] is not None or parsed["focus"] is not None or parsed["followup"]
        or parsed["selectors"]
    )


def parse_may_apply(parsed: dict) -> bool:
    return needs_memory(parsed)


# ---------------------------------------------------------------- data access (read-only)

def _day(value: Any) -> Optional[str]:
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return None


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and value > 0 and value != float("inf") else None


def activity_facts(workout: dict) -> dict:
    """Validated measures of one stored workout; a missing measure stays None."""
    pace = _positive(workout.get("avg_pace_min_km"))
    distance = _positive(workout.get("distance_km"))
    duration = _positive(workout.get("duration_minutes"))
    avg_hr = _positive(workout.get("avg_heart_rate"))
    max_hr = _positive(workout.get("max_heart_rate"))
    elevation = workout.get("elevation_gain_m")
    elevation = float(elevation) if isinstance(elevation, (int, float)) and not isinstance(elevation, bool) \
        and elevation == elevation and elevation >= 0 else None
    return {
        "id": workout.get("id"),
        "date": _day(workout.get("date")),
        "start": workout.get("date") if isinstance(workout.get("date"), str) else None,
        "name": workout.get("name") if isinstance(workout.get("name"), str) else None,
        "distance_km": round(distance, 2) if distance is not None else None,
        "duration_min": int(round(duration)) if duration is not None else None,
        "pace_s_per_km": int(round(pace * 60)) if pace is not None else None,
        "avg_hr": int(round(avg_hr)) if avg_hr is not None else None,
        "max_hr": int(round(max_hr)) if max_hr is not None else None,
        "elevation_gain_m": int(round(elevation)) if elevation is not None else None,
        "environment": None,
    }


_OUTDOOR_TYPES = {"running", "run", "trail_running", "trail_run"}


def environment_of(activity_type: Optional[str]) -> Optional[str]:
    """'treadmill' / 'outdoor' from the precise source activity type; anything else stays unknown."""
    if not activity_type:
        return None
    if "treadmill" in activity_type or "indoor" in activity_type:
        return "treadmill"
    return "outdoor" if activity_type in _OUTDOOR_TYPES else None


async def _runs_between(db: Any, user_id: str, lower: str, upper: str, *, ascending: bool = True,
                        limit: int = 200) -> list[dict]:
    docs = await (
        db.workouts.find({"user_id": user_id, "type": "run", "date": {"$gte": lower, "$lt": upper}}, _PROJECTION)
        .sort("date", 1 if ascending else -1).limit(limit).to_list(limit)
    )
    return [d for d in docs if d.get("user_id") == user_id and _day(d.get("date"))]


async def _runs_on(db: Any, user_id: str, day: date) -> list[dict]:
    return await _runs_between(db, user_id, day.isoformat(), (day + timedelta(days=1)).isoformat(), limit=20)


async def _latest_runs(db: Any, user_id: str, km: Optional[tuple], limit: int = CHOICE_LIMIT + 1) -> list[dict]:
    query: dict[str, Any] = {"user_id": user_id, "type": "run"}
    if km is not None:
        # Bound applied in the query, before the limit: older matching runs are never crowded out.
        query["distance_km"] = {"$gte": km[0], "$lt": math.nextafter(km[1], math.inf)}
    docs = await db.workouts.find(query, _PROJECTION).sort("date", -1).limit(200).to_list(200)
    docs = [d for d in docs if d.get("user_id") == user_id and _day(d.get("date"))]
    if km is not None:
        docs = [d for d in docs if _positive(d.get("distance_km")) is not None
                and km[0] <= float(d["distance_km"]) <= km[1]]
    return docs[:limit]


async def _previous_run(db: Any, user_id: str, workout: dict) -> Optional[dict]:
    """The recorded run immediately before `workout` (strictly earlier), whatever the opened activity."""
    docs = await (
        db.workouts.find({"user_id": user_id, "type": "run", "date": {"$lt": workout["date"]}}, _PROJECTION)
        .sort("date", -1).limit(5).to_list(5)
    )
    docs = [d for d in docs if d.get("user_id") == user_id and _day(d.get("date"))
            and d.get("id") != workout.get("id")]
    return docs[0] if docs else None


async def _before_pair(db: Any, user_id: str, workout: dict, language: str, today: date,
                       focus: Optional[str], why: bool) -> dict:
    previous = await _previous_run(db, user_id, workout)
    if previous is None:
        return _reply(t("c_none_before", language, d=_date_label(_day(workout["date"]), language, today,
                                                                  prefix=False)), None)
    return await _pair_response(db, user_id, [workout["id"], previous["id"]], language, today, focus, why)


async def load_activity_facts(db: Any, user_id: str, workout_id: str) -> Optional[dict]:
    """Owner-scoped facts of one activity, enriched from its stored Garmin document (read only)."""
    workout = await db.workouts.find_one({"id": workout_id, "user_id": user_id}, {"_id": 0})
    if workout is None or workout.get("user_id") != user_id:
        return None
    if _is_garmin_workout(workout):
        ext_id = _extract_garmin_external_id(workout)
        if ext_id:
            activity = await _fetch_garmin_activity(db, user_id, ext_id)
            if activity:
                workout = enrich_workout_from_garmin_activity(workout, activity)
                facts = activity_facts(workout)
                facts["environment"] = environment_of(_reliable_activity_type(activity))
                return facts
    return activity_facts(workout)


# ---------------------------------------------------------------- formatting

def _lang(language: str) -> str:
    return lang_of(language)


def _date_label(day: str, language: str, today: date, *, capital: bool = False, prefix: bool = True) -> str:
    d = date.fromisoformat(day)
    lang = _lang(language)
    year = t("date_year", lang, y=d.year) if d.year != today.year else ""
    day_text = f"{d.day}er" if (lang == "fr" and d.day == 1) else str(d.day)
    label = t("date_on" if prefix else "date_bare", lang, d=day_text, month=MONTHS[lang][d.month - 1], year=year)
    return label[0].upper() + label[1:] if capital else label


def _num(value: float, language: str, decimals: int = 2) -> str:
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",") if _lang(language) in ("fr", "es") else text


def _pace(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _duration(minutes: int, language: str) -> str:
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60:02d}"
    return f"{minutes} min"


def _pace_gap(seconds: int, language: str) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest:02d} s/km" if minutes else f"{rest} s/km"


def _join(items: list[str], language: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {t('and', language)} {items[-1]}"


def _short_date(day: str, language: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


# ---------------------------------------------------------------- comparison contract

_METRICS = ("distance_km", "duration_min", "pace_s_per_km", "avg_hr", "max_hr", "elevation_gain_m")


def _leader(metric: str, a: dict, b: dict) -> Optional[str]:
    """Id of the session with the larger value (the faster one for pace); None when equal."""
    va, vb = a[metric], b[metric]
    if va == vb:
        return None
    larger_wins = metric != "pace_s_per_km"
    return (a["id"] if (va > vb) == larger_wins else b["id"])


def _environments_differ(a: dict, b: dict) -> bool:
    """True only when both environments are known and different (never inferred from a name)."""
    ea, eb = a.get("environment"), b.get("environment")
    return ea is not None and eb is not None and ea != eb


def _env_name(environment: Optional[str], language: str) -> str:
    return t("env_treadmill" if environment == "treadmill" else "env_outdoor", language)


def build_comparison_contract(a: dict, b: dict) -> dict:
    """Two real activities (chronological order), measured values and computed gaps only."""
    first, second = sorted((a, b), key=lambda f: (f.get("start") or f.get("date") or "", f.get("id") or ""))
    deltas: dict[str, Any] = {}
    missing: dict[str, list[str]] = {}
    for metric in _METRICS:
        absent = [f["id"] for f in (first, second) if f[metric] is None]
        if absent:
            missing[metric] = absent
            continue
        gap = abs(first[metric] - second[metric])
        deltas[metric] = {
            "gap": round(gap, 2) if metric == "distance_km" else int(gap),
            "leader_id": _leader(metric, first, second),
        }
    distances = [f["distance_km"] for f in (first, second)]
    comparable = None
    if all(v is not None for v in distances):
        comparable = abs(distances[0] - distances[1]) <= max(distances) * SIMILAR_DISTANCE_TOLERANCE_PCT / 100.0
    return {
        "version": REFS_VERSION,
        "kind": "pair",
        "activities": [first, second],
        "deltas": deltas,
        "missing": missing,
        "distances_comparable": comparable,
        "environments_differ": _environments_differ(first, second),
        "allowed_interpretations": ["measured_values", "computed_gaps", "which_session_is_higher_per_metric"],
        "undemonstrated_conclusions": [
            "fitness_progress", "vo2max_change", "lactate_threshold_change", "better_recovery",
            "higher_physiological_difficulty",
        ],
    }


def _session_sentence(f: dict, language: str, today: date, *, verb_index: int) -> str:
    label = _date_label(f["date"], language, today, capital=True)
    parts: list[str] = []
    if f["distance_km"] is not None:
        dist = _num(f["distance_km"], language)
        if f["duration_min"] is not None:
            parts.append(t("dist_dur", language, dist=dist, dur=_duration(f["duration_min"], language)))
        else:
            parts.append(t("dist", language, dist=dist))
    elif f["duration_min"] is not None:
        parts.append(t("dur_only", language, dur=_duration(f["duration_min"], language)))
    if f["pace_s_per_km"] is not None:
        parts.append(t("pace_at", language, pace=_pace(f["pace_s_per_km"])))
    if f["avg_hr"] is not None:
        parts.append(t("avg_hr_at", language, hr=f["avg_hr"]))
    if f["max_hr"] is not None:
        parts.append(t("max_hr_at", language, hr=f["max_hr"]))
    if f["elevation_gain_m"] is not None:
        parts.append(t("elev_at", language, m=f["elevation_gain_m"]))
    if f["distance_km"] is not None:
        head, tail = f"{t(('verb_a', 'verb_b')[verb_index % 2], language)} {parts[0]}", ", ".join(parts[1:])
    else:
        head, tail = t("no_distance_head", language), ", ".join(parts)
    return f"{label}, {head}{', ' + tail if tail else ''}."


def _gap_phrase(metric: str, gap: Any, language: str, *, lead: bool) -> str:
    if metric == "distance_km":
        value = f"{_num(gap, language)} km"
    elif metric == "duration_min":
        value = _duration(gap, language) if gap >= 60 else f"{gap} min"
    elif metric == "pace_s_per_km":
        value = _pace_gap(gap, language)
    else:
        value = str(gap)
    return t(f"g_{metric}_{'up' if lead else 'down'}", language, v=value)


def _gaps_sentence(contract: dict, language: str, today: date, metrics: tuple = _METRICS,
                   header: bool = True) -> Optional[str]:
    first, second = contract["activities"]
    entries = [(m, contract["deltas"][m]) for m in metrics if m in contract["deltas"]]
    if not entries:
        return None
    moving = [(m, d) for m, d in entries if d["leader_id"] is not None]
    by_id = {first["id"]: first, second["id"]: second}
    leaders = {d["leader_id"] for _, d in moving}
    same = [m for m, d in entries if d["leader_id"] is None]
    if len(leaders) == 1:
        leader = by_id[next(iter(leaders))]
        other = second if leader is first else first
        clauses = _join([_gap_phrase(m, d["gap"], language, lead=True) for m, d in moving], language)
        if not header:
            return f"{clauses} {_date_label(leader['date'], language, today)}"
        sentence = t("gaps_one", language,
                     label=_date_label(leader["date"], language, today, capital=True),
                     other=t("date_ref_prep", language,
                             bare=_date_label(other["date"], language, today, prefix=False)),
                     clauses=clauses)
        if same:
            sentence += t("gaps_identical", language) + _join([_metric_name(m, language) for m in same], language)
        return sentence + "."
    clauses = []
    for metric, delta in moving:
        leader = by_id[delta["leader_id"]]
        clauses.append(f"{_gap_phrase(metric, delta['gap'], language, lead=True)} "
                       f"{_date_label(leader['date'], language, today)}")
    if same:
        clauses.append(t("gaps_identical_item", language) + _join([_metric_name(m, language) for m in same], language))
    return t("gaps_many", language) + "; ".join(clauses) + "."


def _metric_name(metric: str, language: str) -> str:
    return t(f"n_{metric}", language)


def _missing_sentence(contract: dict, language: str, today: date) -> Optional[str]:
    if not any(len(ids) == 1 for ids in contract["missing"].values()):
        return None
    by_id = {a["id"]: a for a in contract["activities"]}
    parts = []
    for metric, ids in contract["missing"].items():
        if len(ids) == 2:
            continue
        dates = _join([_short_date(by_id[i]["date"], language) for i in ids], language)
        parts.append(f"{_metric_name(metric, language)} ({dates})")
    return t("missing", language) + "; ".join(parts) + "."


def _limit_sentence(contract: dict, language: str) -> str:
    return t("limit_diff" if contract["distances_comparable"] is False else "limit_same", language)


def render_pair(contract: dict, language: str, today: date, focus: Optional[str] = None, why: bool = False) -> str:
    text = _render_pair_body(contract, language, today, focus, why)
    if contract.get("environments_differ") and focus not in ("distance", "duration", "elevation"):
        first, second = contract["activities"]
        text += t("env_pair_note", language, a=_env_name(first["environment"], language),
                  b=_env_name(second["environment"], language))
    return text


def _render_pair_body(contract: dict, language: str, today: date, focus: Optional[str], why: bool) -> str:
    first, second = contract["activities"]
    by_id = {first["id"]: first, second["id"]: second}

    def label(f: dict) -> str:
        return _date_label(f["date"], language, today)

    if focus == "progress":
        return t("progress", language,
                 a=_session_sentence(first, language, today, verb_index=0),
                 b=_session_sentence(second, language, today, verb_index=1))
    if focus == "hr":
        if "avg_hr" in contract["missing"]:
            return _missing_sentence(contract, language, today) or t("no_metric", language)
        hr = contract["deltas"]["avg_hr"]
        text = t("hr_head", language, a=first["avg_hr"], b=second["avg_hr"], la=label(first), lb=label(second))
        if hr["leader_id"] is not None:
            text += t("hr_more", language, gap=hr["gap"], l=label(by_id[hr["leader_id"]]))
        else:
            text += t("hr_same", language)
        if "max_hr" in contract["deltas"]:
            text += t("hr_max", language, a=first["max_hr"], b=second["max_hr"])
        if why:
            context = _gaps_sentence(contract, language, today, ("distance_km", "duration_min", "pace_s_per_km"),
                                     header=False)
            text += t("hr_why", language)
            text += t("hr_why_ctx", language, c=context) if context else "."
            text += t("hr_why_end", language)
        return text
    if focus == "pace":
        if "pace_s_per_km" in contract["missing"]:
            return _missing_sentence(contract, language, today) or t("no_metric", language)
        delta = contract["deltas"]["pace_s_per_km"]
        if delta["leader_id"] is None:
            return t("pace_same", language, p=_pace(first["pace_s_per_km"]))
        winner = by_id[delta["leader_id"]]
        loser = second if winner is first else first
        text = t("pace_win", language, w=label(winner), pw=_pace(winner["pace_s_per_km"]),
                 pl=_pace(loser["pace_s_per_km"]), gap=_pace_gap(delta["gap"], language))
        if contract["distances_comparable"] is False:
            text += t("pace_note", language)
        return text
    if focus in ("distance", "duration", "elevation"):
        metric = {"distance": "distance_km", "duration": "duration_min", "elevation": "elevation_gain_m"}[focus]
        if metric in contract["missing"]:
            return _missing_sentence(contract, language, today) or t("no_metric", language)
        return _gaps_sentence(contract, language, today, (metric,)) or t("no_metric", language)
    if focus == "demanding":
        counts: dict[str, int] = {first["id"]: 0, second["id"]: 0}
        used = []
        for metric in ("distance_km", "duration_min", "avg_hr", "pace_s_per_km"):
            delta = contract["deltas"].get(metric)
            if delta and delta["leader_id"] is not None:
                counts[delta["leader_id"]] += 1
                used.append(metric)
        names = _join([_metric_name(m, language) for m in used], language)
        if used and (counts[first["id"]] == len(used) or counts[second["id"]] == len(used)):
            leader = first if counts[first["id"]] else second
            text = t("dem_one", language, names=names, l=label(leader))
        elif used:
            text = t("dem_mixed", language, names=names)
        else:
            text = t("dem_none", language)
        return text + t("dem_note", language)

    lines = [
        _session_sentence(first, language, today, verb_index=0),
        _session_sentence(second, language, today, verb_index=1),
    ]
    gaps = _gaps_sentence(contract, language, today)
    if gaps:
        lines.append(gaps)
    missing = _missing_sentence(contract, language, today)
    if missing:
        lines.append(missing)
    lines.append(_limit_sentence(contract, language))
    return " ".join(lines)


# ---------------------------------------------------------------- historical comparison

def _median_int(values: list[float]) -> Optional[int]:
    return int(round(median(values))) if values else None


async def build_history_contract(db: Any, user_id: str, reference: dict, kind: str, count: int) -> dict:
    """Reference session vs the most recent earlier runs matching an established criterion."""
    start = reference.get("start") or reference["date"]
    ref_day = date.fromisoformat(reference["date"])
    lower = (ref_day - timedelta(days=SIMILAR_HISTORY_WINDOW_DAYS)).isoformat()
    window = await _runs_between(db, user_id, lower, start, ascending=False, limit=200)
    window = [d for d in window if d.get("id") != reference["id"]]
    window_facts = [activity_facts(d) for d in window]
    contract: dict[str, Any] = {
        "timed_sessions": sum(1 for f in window_facts if f["duration_min"] is not None),
        "version": REFS_VERSION, "kind": "history", "reference": reference, "criterion": {"kind": kind},
        "requested": count, "window_days": SIMILAR_HISTORY_WINDOW_DAYS, "window_size": len(window_facts),
        "reference_matches_criterion": None, "population": [], "habitual_duration_min": None,
        "allowed_interpretations": ["measured_values", "computed_gaps", "median_of_listed_sessions"],
        "undemonstrated_conclusions": [
            "fitness_progress", "vo2max_change", "lactate_threshold_change", "better_recovery",
            "higher_physiological_difficulty",
        ],
    }
    if kind == "long":
        durations = [f["duration_min"] for f in window_facts if f["duration_min"] is not None]
        if len(durations) < LONG_RUN_MIN_HISTORY:
            contract["criterion"].update(established=False, min_history=LONG_RUN_MIN_HISTORY)
            return contract
        habitual = median(durations)
        threshold = LONG_RUN_DURATION_RATIO * habitual
        contract["habitual_duration_min"] = round(habitual, 1)
        contract["criterion"].update(established=True, ratio=LONG_RUN_DURATION_RATIO,
                                     threshold_min=round(threshold, 1))
        contract["reference_matches_criterion"] = (
            reference["duration_min"] is not None and reference["duration_min"] >= threshold)
        picked = [f for f in window_facts if f["duration_min"] is not None and f["duration_min"] >= threshold]
    elif kind == "similar":
        ref_km = reference["distance_km"]
        if ref_km is None:
            contract["criterion"].update(established=False, reason="reference_distance_missing")
            return contract
        tolerance = ref_km * SIMILAR_DISTANCE_TOLERANCE_PCT / 100.0
        contract["criterion"].update(established=True, tolerance_pct=SIMILAR_DISTANCE_TOLERANCE_PCT,
                                     min_km=round(ref_km - tolerance, 2), max_km=round(ref_km + tolerance, 2))
        picked = [f for f in window_facts if f["distance_km"] is not None
                  and abs(f["distance_km"] - ref_km) <= tolerance]
    else:
        contract["criterion"].update(established=True)
        picked = list(window_facts)
    # Bounded to `count`: enrich with the stored Garmin document (same owner-scoped loader as the pair path).
    enriched = []
    for f in picked[:count]:
        richer = await load_activity_facts(db, user_id, f["id"]) if f.get("id") else None
        enriched.append(richer or f)
    population = list(reversed(enriched))  # most recent `count`, shown chronologically
    contract["population"] = population
    stats: dict[str, Any] = {}
    for metric in ("distance_km", "duration_min", "pace_s_per_km", "avg_hr"):
        values = [f[metric] for f in population if f[metric] is not None]
        stats[metric] = {"n": len(values), "median": _median_int(values) if metric != "distance_km"
                         else (round(median(values), 2) if values else None)}
    contract["population_stats"] = stats
    differing = [f for f in population if reference.get("environment") is not None
                 and f.get("environment") is not None and f["environment"] != reference["environment"]]
    contract["environment_differs"] = {"count": len(differing), "of": len(population)} if differing else None
    return contract


_HISTORY_FOCUS = {"hr": "avg_hr", "pace": "pace_s_per_km", "distance": "distance_km", "duration": "duration_min"}


def _metric_value(metric: str, value: float, language: str) -> str:
    if metric == "avg_hr":
        return f"{int(value)} bpm"
    if metric == "pace_s_per_km":
        return f"{_pace(int(value))}/km"
    if metric == "distance_km":
        return f"{_num(value, language)} km"
    return _duration(int(value), language)


def _focused_history(contract: dict, language: str, today: date, focus: str, criteria: str) -> str:
    """One measure of the reference session against the same population and criterion."""
    metric = _HISTORY_FOCUS[focus]
    ref, population, stats = contract["reference"], contract["population"], contract["population_stats"][metric]
    name = _metric_name(metric, language)
    name = name[0].upper() + name[1:]
    lines = [t("h_f_crit", language, c=criteria)]
    if ref[metric] is None:
        lines.append(t("h_f_ref_missing", language, m=name, d=_short_date(ref["date"], language)))
        return " ".join(lines)
    lines.append(t("h_f_ref", language, m=name, d=_short_date(ref["date"], language),
                   v=_metric_value(metric, ref[metric], language)))
    values = [f"{_short_date(f['date'], language)} : {_metric_value(metric, f[metric], language)}"
              for f in population if f[metric] is not None]
    if not values:
        lines.append(t("h_f_pop_none", language, m=name, total=len(population)))
        return " ".join(lines)
    lines.append(t("h_f_pop", language, n=stats["n"], total=len(population), vals="; ".join(values)))
    diff = ref[metric] - stats["median"]
    if metric == "pace_s_per_km":
        gap = (t("h_same", language) if not diff else
               f"{_pace_gap(abs(diff), language)} {t('h_pace_slow' if diff > 0 else 'h_pace_fast', language)}")
    elif not diff:
        gap = t("h_same", language)
    else:
        unit = {"avg_hr": " bpm", "duration_min": " min", "distance_km": " km"}[metric]
        gap = f"{'+' if diff > 0 else '−'}{_num(abs(round(diff, 2)), language)}{unit}"
    lines.append(t("h_f_med", language, n=stats["n"], med=_metric_value(metric, stats["median"], language), gap=gap))
    lines.append(t("h_descriptive", language))
    return " ".join(lines)


def render_history(contract: dict, language: str, today: date, focus: Optional[str] = None) -> str:
    ref = contract["reference"]
    criterion = contract["criterion"]
    ref_line = _session_sentence(ref, language, today, verb_index=0)
    kind = criterion["kind"]
    if criterion.get("established") is False:
        if kind == "long":
            reason = t("h_long_unset", language, n=criterion["min_history"], w=contract["window_days"],
                       have=contract["timed_sessions"])
        else:
            reason = t("h_sim_unset", language)
        return f"{ref_line} {reason}"
    if kind == "long":
        criteria = t("h_c_long", language, r=_num(criterion["ratio"], language),
                     h=_duration(int(round(contract["habitual_duration_min"])), language),
                     w=contract["window_days"],
                     t=_duration(int(round(criterion["threshold_min"])), language))
    elif kind == "similar":
        criteria = t("h_c_sim", language, lo=_num(criterion["min_km"], language),
                     hi=_num(criterion["max_km"], language), p=_num(criterion["tolerance_pct"], language, 0))
    else:
        criteria = t("h_c_recent", language)
    population = contract["population"]
    n = len(population)
    if focus in _HISTORY_FOCUS and n:
        text = _focused_history(contract, language, today, focus, criteria)
        env = contract.get("environment_differs")
        if env and focus in ("hr", "pace"):
            text += "\n" + t("env_history_note", language, k=env["count"], n=env["of"],
                             r=_env_name(ref.get("environment"), language))
        return text
    if n == 0:
        return f"{ref_line} {t('h_none', language, c=criteria, w=contract['window_days'])}"
    head = t("h_head", language, c=criteria, n=n,
             sessions=t("h_session_one" if n == 1 else "h_session_many", language),
             kept=t("h_kept_one" if n == 1 else "h_kept_many", language),
             of=t("h_of", language, r=contract["requested"]) if n < contract["requested"] else "")
    lines = [f"- {_session_sentence(f, language, today, verb_index=i)}" for i, f in enumerate(population)]
    stats = contract["population_stats"]
    gap_parts = []

    def counted(metric: str) -> str:
        n_metric = stats[metric]["n"]
        return f" ({n_metric}/{n})" if n_metric < n else ""

    if ref["distance_km"] is not None and stats["distance_km"]["median"] is not None:
        diff = round(ref["distance_km"] - stats["distance_km"]["median"], 2)
        gap_parts.append(f"{_metric_name('distance_km', language)} {'+' if diff >= 0 else '−'}"
                         f"{_num(abs(diff), language)} km{counted('distance_km')}")
    if ref["duration_min"] is not None and stats["duration_min"]["median"] is not None:
        diff = ref["duration_min"] - stats["duration_min"]["median"]
        gap_parts.append(f"{_metric_name('duration_min', language)} {'+' if diff >= 0 else '−'}{abs(diff)} min{counted('duration_min')}")
    if ref["pace_s_per_km"] is not None and stats["pace_s_per_km"]["median"] is not None:
        diff = ref["pace_s_per_km"] - stats["pace_s_per_km"]["median"]
        if diff:
            word = t("h_pace_slow" if diff > 0 else "h_pace_fast", language)
            gap_parts.append(f"{_metric_name('pace_s_per_km', language)} {_pace_gap(abs(diff), language)} {word}{counted('pace_s_per_km')}")
        else:
            gap_parts.append(t("h_pace_same", language) + counted("pace_s_per_km"))
    if ref["avg_hr"] is not None and stats["avg_hr"]["median"] is not None:
        diff = ref["avg_hr"] - stats["avg_hr"]["median"]
        gap_parts.append(f"{_metric_name('avg_hr', language)} {'+' if diff >= 0 else '−'}{abs(diff)} bpm{counted('avg_hr')}")
    median_line = ""
    if gap_parts:
        counts = {m: s["n"] for m, s in stats.items()}
        partial = n and any(v < n for v in counts.values() if v)
        median_line = t("h_med_head", language, g=", ".join(gap_parts))
        median_line += t("h_med_partial", language) if partial else "."
    notes = []
    if kind == "long" and contract["reference_matches_criterion"] is False:
        notes.append(t("h_not_long", language))
    env = contract.get("environment_differs")
    if env:
        notes.append(t("env_history_note", language, k=env["count"], n=env["of"],
                       r=_env_name(ref.get("environment"), language)))
    notes.append(t("h_descriptive", language))
    return "\n".join([ref_line, head, *lines, *([median_line] if median_line else []), " ".join(notes)])


# ---------------------------------------------------------------- turn resolution

def _choice_entry(workout: dict) -> dict:
    return {"id": workout["id"], "date": _day(workout.get("date"))}


def _choice_label(workout: dict, index: int, language: str) -> str:
    facts = activity_facts(workout)
    start = workout.get("date") or ""
    clock = start[11:16] if len(start) >= 16 and start[10] in "T " else None
    parts = []
    if clock:
        parts.append(clock)
    if facts["distance_km"] is not None:
        parts.append(f"{_num(facts['distance_km'], language)} km")
    if facts["duration_min"] is not None:
        parts.append(_duration(facts["duration_min"], language))
    return f"{index}) " + (" – ".join(parts) if parts else (workout.get("name") or "?"))


def _refs(kind: str, ids: list[str], *, primary: Optional[str] = None, pending: Optional[dict] = None) -> dict:
    refs: dict[str, Any] = {"v": REFS_VERSION, "kind": kind, "workout_ids": ids}
    if primary is not None:
        refs["primary"] = primary
    if pending is not None:
        refs["pending"] = pending
    return refs


def _reply(text: str, refs: Optional[dict] = None) -> dict:
    return {"kind": "reply", "text": text, "refs": refs}


def _clarify_text(language: str, kind: str, today: date, *, day: Optional[str] = None,
                  choices: Optional[list[str]] = None) -> str:
    bare = _date_label(day, language, today, prefix=False) if day else ""
    if kind == "multiple":
        when = t("c_when", language, d=bare) if day else ""
        return t("c_multiple", language, when=when, listing=" ; ".join(choices or []))
    if kind == "none":
        return t("c_none_day", language, d=bare) if day else t("c_none", language)
    key = {"referent": "c_referent", "which_reference": "c_which_reference", "same": "c_same",
           "invalid": "c_invalid"}.get(kind)
    return t(key, language) if key else ""


_ORDINAL_WORDS = {
    "premiere": 1, "premier": 1, "first": 1, "primera": 1, "primero": 1,
    "seconde": 2, "second": 2, "deuxieme": 2, "segunda": 2, "segundo": 2,
}
_LAST_WORDS = ("derniere", "dernier", "last", "ultima", "ultimo")


def _pick_choice(parsed: dict, choices: list[dict]) -> Optional[dict]:
    """Choice designated by the answer to a clarification: a date, else an ordinal."""
    wanted = [s["date"].isoformat() for s in parsed["selectors"] if s["type"] == "date"]
    pool = [c for c in choices if wanted and c.get("date") in wanted]
    if len(pool) == 1:
        return pool[0]
    ordinal = parsed["ordinal"]
    if ordinal and not wanted and choices:
        if ordinal in _LAST_WORDS:
            return choices[-1]
        index = _ORDINAL_WORDS.get(ordinal) or (int(ordinal) if ordinal.isdigit() else 0)
        if 1 <= index <= len(choices):
            return choices[index - 1]
    return None


def _pending(choices: list[dict], intent: dict, prompt: str) -> dict:
    return {"choices": choices, "intent": intent, "prompt": prompt}


# ---- conversation memory policy
# The memory of a turn is the `coach_refs` of the latest assistant message of the SAME scope
# (user + general chat, or user + selected workout). Rules:
#  * a deterministic answer or a resolved single activity writes fresh refs (current reference);
#  * an ordinary reply on the same subject propagates them (`carried` counter, MAX_CARRY hops,
#    short acknowledgements or follow-up wording only, never after a plan question);
#  * an explicit change of subject writes none, so nothing older can be resurrected;
#  * refs older than MEMORY_TTL are ignored.
MAX_CARRY = 2
MEMORY_TTL = timedelta(hours=6)
_CARRY_MAX_WORDS = 12


def usable_memory(doc: Any, now_utc: datetime) -> Optional[dict]:
    """`coach_refs` of an assistant message if well-formed, owned in this scope and fresh."""
    if not isinstance(doc, dict):
        return None
    refs = doc.get("coach_refs")
    if not isinstance(refs, dict) or refs.get("v") != REFS_VERSION:
        return None
    try:
        stamp = datetime.fromisoformat(str(doc.get("timestamp")))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = now_utc - stamp
    return refs if timedelta(0) - timedelta(minutes=5) <= age <= MEMORY_TTL else None


def carried_refs(memory: Optional[dict], parsed: dict) -> Optional[dict]:
    """Refs to store next to an ordinary (non-activity) reply, or None to let the context lapse."""
    if memory is None or parsed["topic_change"] or parsed["plan_related"]:
        return None
    if not memory.get("workout_ids") and not memory.get("pending"):
        return None
    related = parsed["focus"] or parsed["anaphora"] or parsed["followup"] or parsed["compare"]
    if not related and len(parsed["text"].split()) > _CARRY_MAX_WORDS:
        return None
    hops = memory.get("carried") if isinstance(memory.get("carried"), int) else 0
    if hops >= MAX_CARRY:
        return None
    return {**memory, "carried": hops + 1}


async def _resolve_selector(db: Any, user_id: str, selector: dict, language: str, today: date) -> dict:
    """-> {"workout": doc} | {"reply": text, "choices": [...]}; never invents an activity."""
    if selector["type"] == "date":
        runs = await _runs_on(db, user_id, selector["date"])
        day = selector["date"].isoformat()
        if not runs:
            return {"reply": _clarify_text(language, "none", today, day=day)}
        if len(runs) > 1:
            shown = runs[:CHOICE_LIMIT]
            labels = [_choice_label(w, i, language) for i, w in enumerate(shown, 1)]
            return {"reply": _clarify_text(language, "multiple", today, day=day, choices=labels),
                    "choices": [_choice_entry(w) for w in shown]}
        return {"workout": runs[0]}
    km = selector.get("km")
    runs = await _latest_runs(db, user_id, km)
    if not runs:
        return {"reply": _clarify_text(language, "none", today)}
    if selector["type"] == "last":
        offset = selector.get("offset", 0)
        if offset >= len(runs):
            return {"reply": _clarify_text(language, "none", today)}
        return {"workout": runs[offset]}
    if len(runs) == 1:
        return {"workout": runs[0]}
    shown = runs[:CHOICE_LIMIT]
    labels = []
    for i, w in enumerate(shown, 1):
        labels.append(f"{i}) {_date_label(_day(w['date']), language, today, prefix=False)} – "
                      f"{_choice_label(w, i, language).split(') ', 1)[1]}")
    return {"reply": _clarify_text(language, "multiple", today, choices=labels),
            "choices": [_choice_entry(w) for w in shown]}


async def _history_reference_choices(db: Any, user_id: str, history: dict, language: str,
                                     today: date) -> dict:
    """Similar-distance history without a reference: offer the latest runs instead of a dead end."""
    runs = (await _latest_runs(db, user_id, None, limit=3))
    if not runs:
        return _reply(_clarify_text(language, "none", today), None)
    labels = [f"{i}) {_date_label(_day(w['date']), language, today, prefix=False)} – "
              f"{_choice_label(w, i, language).split(') ', 1)[1]}" for i, w in enumerate(runs, 1)]
    prompt = t("c_history_reference", language, n=history["count"], listing=" ; ".join(labels))
    return _reply(prompt, _refs("single", [], pending=_pending(
        [_choice_entry(w) for w in runs], {"action": "history", "history": history}, prompt)))


async def _pair_response(db: Any, user_id: str, ids: list[str], language: str, today: date,
                         focus: Optional[str], why: bool) -> dict:
    facts = [await load_activity_facts(db, user_id, i) for i in ids]
    if any(f is None or not f["date"] for f in facts):
        return _reply(_clarify_text(language, "referent", today))
    if len({f["id"] for f in facts}) != 2:
        return _reply(_clarify_text(language, "same", today))
    contract = build_comparison_contract(facts[0], facts[1])
    text = render_pair(contract, language, today, focus=focus, why=why)
    refs = _refs("pair", [f["id"] for f in contract["activities"]], primary=ids[0])
    return {"kind": "compare", "text": text, "refs": refs, "contract": contract}


def _single(workout_id: str, *, continues: bool = False) -> dict:
    return {"kind": "single", "workout_id": workout_id, "continues": continues,
            "refs": _refs("single", [workout_id], primary=workout_id)}


_KINDS = ("single", "pair", "history")


def clean_memory(memory: Any) -> Optional[dict]:
    """Well-formed copy of stored `coach_refs`, or None: stored data is never trusted blindly."""
    if not isinstance(memory, dict) or memory.get("v") != REFS_VERSION:
        return None
    raw_ids = memory.get("workout_ids")
    ids = [i for i in raw_ids if isinstance(i, str) and i][:2] if isinstance(raw_ids, list) else []
    kind = memory.get("kind") if memory.get("kind") in _KINDS else None
    if kind == "pair" and len(ids) != 2:
        kind = None
    if kind in ("single", "history") and len(ids) != 1:
        kind = None
    cleaned: dict[str, Any] = {"v": REFS_VERSION, "kind": kind, "workout_ids": ids if kind else []}
    stored_history = memory.get("history")
    if kind == "history":
        valid = (isinstance(stored_history, dict) and stored_history.get("kind") in ("long", "similar", "recent")
                 and isinstance(stored_history.get("count"), int) and not isinstance(stored_history["count"], bool)
                 and 1 <= stored_history["count"] <= HISTORY_MAX_COUNT)
        if not valid:
            cleaned["kind"], cleaned["workout_ids"] = None, []
        else:
            cleaned["history"] = {"kind": stored_history["kind"], "count": stored_history["count"]}
    if isinstance(memory.get("primary"), str):
        cleaned["primary"] = memory["primary"]
    if isinstance(memory.get("carried"), int) and not isinstance(memory["carried"], bool):
        cleaned["carried"] = max(0, memory["carried"])
    pending = memory.get("pending")
    if isinstance(pending, dict) and isinstance(pending.get("choices"), list):
        choices = [{"id": c["id"], "date": c.get("date") if isinstance(c.get("date"), str) else None}
                   for c in pending["choices"] if isinstance(c, dict) and isinstance(c.get("id"), str)]
        intent = pending.get("intent") if isinstance(pending.get("intent"), dict) else {}
        action = intent.get("action") if intent.get("action") in ("history", "pair", "single", "before") else None
        history = intent.get("history")
        if action == "history" and not (isinstance(history, dict) and history.get("kind") in
                                        ("long", "similar", "recent") and isinstance(history.get("count"), int)):
            action = None
        if choices and action:
            others = intent.get("others")
            cleaned["pending"] = {
                "choices": choices[:CHOICE_LIMIT],
                "intent": {
                    "action": action,
                    "others": [i for i in others if isinstance(i, str)][:1] if isinstance(others, list) else [],
                    "focus": intent.get("focus") if isinstance(intent.get("focus"), str) else None,
                    "why": bool(intent.get("why")),
                    **({"history": {"kind": history["kind"], "count": history["count"]}}
                       if action == "history" else {}),
                },
                "prompt": pending["prompt"] if isinstance(pending.get("prompt"), str) else "",
            }
    if not cleaned["workout_ids"] and "pending" not in cleaned:
        return None
    return cleaned


async def resolve_turn(*, db: Any, user_id: str, message: str, language: str, today: date,
                       memory: Optional[dict], parsed: Optional[dict] = None,
                       selected_id: Optional[str] = None) -> dict:
    """Decide how one chat message is handled.

    Returns {"kind": "passthrough", "refs"} (ordinary chat; `refs` = controlled propagation),
    {"kind": "single", "workout_id", "refs", "continues"} (selected-workout path),
    {"kind": "compare", "text", "refs", "contract"} or {"kind": "reply", "text", "refs"}
    (clarification / nothing found).
    `memory` comes from `usable_memory` (same user, same scope). `selected_id` is the activity the
    client opened (scope = that activity): it is the first reference of any comparison, and an
    analysis of another activity is never started inside that scope (no mixed histories).
    """
    p = parsed or parse_message(message, today)
    memory = clean_memory(memory)
    if p["topic_change"]:
        memory = None
    if not needs_memory(p):
        return {"kind": "passthrough", "refs": carried_refs(memory, p)}
    turn = await _resolve(db=db, user_id=user_id, language=language, today=today, memory=memory, p=p,
                          selected_id=selected_id)
    if selected_id is not None and turn["kind"] == "single":
        # The scope already is the opened activity: the normal selected-workout path answers.
        turn = {"kind": "passthrough", "refs": _refs("single", [selected_id], primary=selected_id)}
    if turn["kind"] == "passthrough" and "refs" not in turn:
        turn["refs"] = carried_refs(memory, p)
    return turn


async def _resolve(*, db: Any, user_id: str, language: str, today: date, memory: Optional[dict],
                   p: dict, selected_id: Optional[str]) -> dict:
    ids = [i for i in (memory or {}).get("workout_ids", []) if isinstance(i, str)]
    mem_kind = (memory or {}).get("kind")
    pending = (memory or {}).get("pending")
    selectors = list(p["selectors"])
    compare = p["compare"]

    if selected_id is not None:
        # The opened activity is the first reference; a pair already built in this scope may be followed up.
        # The memory is already limited to this user/scope/TTL and cleared on topic change, so an explicit
        # A <-> C pair survives follow-ups even though the opened activity B is neither of them.
        keeps_pair = (mem_kind == "pair" and len(ids) == 2 and not p["topic_change"]
                      and not (selectors or p["history"] is not None))
        keeps_history = (mem_kind == "history" and ids == [selected_id] and not selectors)
        if not (keeps_pair or keeps_history):
            ids, mem_kind = [selected_id], "single"
        if selectors and p["history"] is None:
            compare = True  # naming another activity from a selected one means comparing with it

    # A) answer to a previous clarification
    if isinstance(pending, dict) and pending.get("choices"):
        choices = [c for c in pending["choices"] if isinstance(c, dict) and isinstance(c.get("id"), str)]
        choice = _pick_choice(p, choices)
        if choice is not None:
            intent = pending.get("intent") if isinstance(pending.get("intent"), dict) else {}
            others = [i for i in intent.get("others", []) if isinstance(i, str)]
            history = intent.get("history")
            if intent.get("action") == "before":
                picked = await db.workouts.find_one({"id": choice["id"], "user_id": user_id}, _PROJECTION)
                if picked is None or picked.get("user_id") != user_id or not _day(picked.get("date")):
                    return _reply(_clarify_text(language, "referent", today), None)
                return await _before_pair(db, user_id, picked, language, today,
                                          intent.get("focus"), bool(intent.get("why")))
            if intent.get("action") == "history" and isinstance(history, dict):
                return await _history_turn(db, user_id, choice["id"], history, language, today)
            if others:
                return await _pair_response(db, user_id, [others[0], choice["id"]], language, today,
                                            intent.get("focus"), bool(intent.get("why")))
            return _single(choice["id"])
        if not selectors and (p["ordinal"] is not None or p["anaphora"]):
            # Invalid or ambiguous answer: keep the same choices and intent, ask again.
            kept = carried_refs(memory, {**p, "plan_related": False})
            if kept is not None and pending.get("prompt"):
                return _reply(_clarify_text(language, "invalid", today) + str(pending["prompt"]), kept)
            return _reply(_clarify_text(language, "referent", today), None)
        # a new explicit selector or topic below supersedes the pending choice

    # B) history comparison
    if p["history"] is not None:
        ref_id: Optional[str] = None
        if selectors:
            resolved = await _resolve_selector(db, user_id, selectors[0], language, today)
            if "workout" not in resolved:
                if resolved.get("choices"):
                    return _reply(resolved["reply"], _refs("single", [], pending=_pending(
                        resolved["choices"], {"action": "history", "history": p["history"]}, resolved["reply"])))
                return _reply(resolved["reply"], None)
            ref_id = resolved["workout"]["id"]
        elif len(ids) == 1:
            ref_id = ids[0]
        elif len(ids) == 2:
            choices = []
            for i in ids:
                f = await load_activity_facts(db, user_id, i)
                if f is not None:
                    choices.append({"id": i, "date": f["date"]})
            prompt = _clarify_text(language, "which_reference", today)
            return _reply(prompt, _refs("pair", ids, pending=_pending(
                choices, {"action": "history", "history": p["history"]}, prompt)))
        if ref_id is None:
            if p["history"]["kind"] == "similar":
                return await _history_reference_choices(db, user_id, p["history"], language, today)
            return _reply(_clarify_text(language, "referent", today), None)
        return await _history_turn(db, user_id, ref_id, p["history"], language, today)

    # C0) "<named date> versus the one before it": the named date alone anchors the comparison
    if p["before_date"]:
        named = next(sel for sel in selectors if sel["type"] == "date")
        resolved = await _resolve_selector(db, user_id, named, language, today)
        if "workout" not in resolved:
            if resolved.get("choices"):
                return _reply(resolved["reply"], _refs("single", [], pending=_pending(
                    resolved["choices"], {"action": "before", "focus": p["focus"], "why": p["why"]},
                    resolved["reply"])))
            return _reply(resolved["reply"], None)
        return await _before_pair(db, user_id, resolved["workout"], language, today, p["focus"], p["why"])

    # C) comparison of two sessions
    if compare or (p["both"] and len(ids) == 2):
        chosen: list[str] = []
        ambiguous: Optional[dict] = None
        for selector in selectors[:2]:
            resolved = await _resolve_selector(db, user_id, selector, language, today)
            if "workout" not in resolved:
                if resolved.get("choices") and ambiguous is None:
                    ambiguous = resolved
                    continue
                if resolved.get("choices"):  # two ambiguous selectors: ask for precise dates instead
                    return _reply(_clarify_text(language, "referent", today), None)
                return _reply(resolved["reply"], None)
            chosen.append(resolved["workout"]["id"])
        if ambiguous is not None:
            # The comparison survives the clarification: the other activity is kept in the pending intent.
            others = chosen[:1] or (ids[:1] if mem_kind in ("single", "history") and len(ids) == 1 else [])
            if not others:
                return _reply(_clarify_text(language, "referent", today), None)
            intent = {"action": "pair", "others": others, "focus": p["focus"], "why": p["why"]}
            return _reply(ambiguous["reply"], _refs(mem_kind or "single", ids, pending=_pending(
                ambiguous["choices"], intent, ambiguous["reply"])))
        if len(chosen) == 2:
            return await _pair_response(db, user_id, chosen, language, today, p["focus"], p["why"])
        if len(chosen) == 1:
            if mem_kind in ("single", "history") and len(ids) == 1:
                return await _pair_response(db, user_id, [ids[0], chosen[0]], language, today,
                                            p["focus"], p["why"])
            if mem_kind == "pair" and chosen[0] in ids:
                return await _pair_response(db, user_id, ids, language, today, p["focus"], p["why"])
            return _reply(_clarify_text(language, "which_reference" if mem_kind == "pair" else "referent",
                                        today), None)
        if mem_kind == "pair" and len(ids) == 2:
            return await _pair_response(db, user_id, ids, language, today, p["focus"], p["why"])
        return _reply(_clarify_text(language, "referent", today), None)

    # D) new explicit session (also a change of subject)
    if selectors:
        resolved = await _resolve_selector(db, user_id, selectors[0], language, today)
        if "workout" in resolved:
            return _single(resolved["workout"]["id"])
        if resolved.get("choices"):
            return _reply(resolved["reply"], _refs("single", [], pending=_pending(
                resolved["choices"], {"action": "single", "others": []}, resolved["reply"])))
        return _reply(resolved["reply"], None)

    # E) follow-up on the sessions of the previous turn
    if ids and not p["plan_related"]:
        if mem_kind == "pair" and len(ids) == 2 and (p["focus"] or p["both"] or p["anaphora"]):
            return await _pair_response(db, user_id, ids, language, today, p["focus"], p["why"])
        if mem_kind == "history" and len(ids) == 1 and (p["focus"] or p["anaphora"] or p["followup"]):
            history = (memory or {}).get("history")
            return await _history_turn(db, user_id, ids[0], history, language, today, p["focus"])
        if mem_kind == "single" and len(ids) == 1 and (p["focus"] or p["anaphora"] or p["followup"]):
            return _single(ids[0], continues=True)
    if p["anaphora"]:
        return _reply(_clarify_text(language, "referent", today), None)
    return {"kind": "passthrough"}


async def _history_turn(db: Any, user_id: str, workout_id: str, history: dict, language: str, today: date,
                        focus: Optional[str] = None) -> dict:
    reference = await load_activity_facts(db, user_id, workout_id)
    if reference is None or not reference["date"]:
        return _reply(_clarify_text(language, "referent", today), None)
    contract = await build_history_contract(db, user_id, reference, history["kind"], history["count"])
    refs = _refs("history", [workout_id], primary=workout_id)
    refs["history"] = {"kind": history["kind"], "count": history["count"]}
    return {"kind": "compare", "text": render_history(contract, language, today, focus), "refs": refs,
            "contract": contract}


def today_for(now_utc: datetime) -> date:
    return now_utc.astimezone(timezone.utc).date()
