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

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Optional

from workout_analysis_v2 import (
    SIMILAR_DISTANCE_TOLERANCE_PCT,
    SIMILAR_HISTORY_WINDOW_DAYS,
    SIMILAR_MAX_RESULTS,
)
from workout_analysis_v2_service import (
    _extract_garmin_external_id,
    _fetch_garmin_activity,
    _is_garmin_workout,
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
}
_WEEKDAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_ALT = "|".join(_WEEKDAYS)
_NUMBER_WORDS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "two": 2, "three": 3, "four": 4, "five": 5}

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_RE = re.compile(
    r"(?<![\w:.,/-])(\d{1,2})(?:/(\d{1,2})(?:/(\d{4}|\d{2}))?|[-.](\d{1,2})[-.](\d{4}))(?![\w:/-])")
_DAY_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}})\s*(?:er|st|nd|rd|th)?\s+(?:de\s+|d')?({_MONTH_ALT})\b\.?(?:\s+(\d{{4}}))?")
_MONTH_DAY_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")
_WEEKDAY_RE = re.compile(rf"\b({_WEEKDAY_ALT})\b")
_LAST_RE = re.compile(
    r"\b(?:ma|mon|ta|ton|la|ma toute|my|the)?\s*(?:derniere|dernier|last|latest|most recent)\s+"
    r"(?:sortie|course|seance|run|workout|session|semi|marathon|activite|footing)\b|"
    r"\b(?:derniere|dernier)\s+(?:semi|marathon)\b")
_HALF_RE = re.compile(r"\b(?:semi(?:-| )?marathon|semi|half(?:-| )?marathon|half)\b")
_FULL_RE = re.compile(r"\bmarathon\b")
_KM_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*km\b")
_COMPARE_RE = re.compile(r"\bcompar|\bversus\b|\bvs\b|par rapport|\bcontre\b|\bagainst\b|\bdiffer")
_HISTORY_RE = re.compile(
    r"(?:(\d+|deux|trois|quatre|cinq|two|three|four|five)\s+)?"
    r"(?:dernieres?|last|previous|precedentes?|recent|recentes?)\s+"
    r"(?:sorties?|seances?|courses?|runs?|workouts?|sessions?)"
    r"(?:\s+(longues?|similaires?|comparables?|long|similar|comparable))?|"
    r"(?:sorties?|seances?|runs?|workouts?)\s+(longues?|similaires?|comparables?|long|similar)")
_ANAPHORA_RE = re.compile(
    r"\b(?:celle-ci|celui-ci|cette (?:sortie|seance|course|activite)|this (?:run|session|workout|one)|"
    r"la precedente|the previous one|les deux|ces deux|both|these two|ces seances|ces sorties|"
    r"compare[- ]la|compare[- ]les|compare it|compare them|cette meme)\b")
_BOTH_RE = re.compile(r"\b(?:les deux|ces deux|both|these two|ces seances|ces sorties|compare[- ]les|compare them)\b")
_ORDINAL_RE = re.compile(
    r"\b(?:la |le |the )?(premiere|premier|first|seconde|second|deuxieme|derniere|dernier|last|1|2|3|4|5)\b")
_TOPIC_CHANGE_RE = re.compile(
    r"\b(?:autre sujet|parlons d'autre chose|changeons de sujet|change of subject|different topic|"
    r"oublie (?:ca|cette|ces)|forget (?:that|this))\b")
_PLAN_EXCLUDE_RE = re.compile(
    r"\b(?:cible|objectif|target|goal|demain|tomorrow|prochaine|prochain|next|plan|aujourd|today|semaine|week)\b")
_FOCUS_PATTERNS = (
    ("progress", re.compile(r"\bprogress|\bamelior|\bforme\b|\bimproving\b|\bfitter\b|\bfitness\b")),
    ("demanding", re.compile(r"exigeant|difficile|\bdur(?:e|s)?\b|\bhardest\b|\bharder\b|\bdemanding\b|\btough")),
    ("hr", re.compile(r"cardio|\bfc\b|frequence cardiaque|\bbpm\b|heart|\bhr\b|coeur")),
    ("pace", re.compile(r"plus vite|\ballure|\bvitesse|\brapide|\bfaster\b|\bfastest\b|\bpace\b")),
    ("distance", re.compile(r"\bdistance\b|plus longue|plus long\b|\blongest\b|\bfarther\b")),
    ("duration", re.compile(r"\bduree\b|\btemps\b|\bduration\b")),
    ("elevation", re.compile(r"denivele|\belevation\b|\bd\+")),
)
_WHY_RE = re.compile(r"\bpourquoi\b|\bwhy\b|\bexplique|\bexplain\b")
_FOLLOWUP_RE = re.compile(r"^\s*(?:et|and|mais|ok|d'accord)\b")


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
    for m in re.finditer(r"\b(hier|yesterday)\b", text):
        found.append((m.start(), today - timedelta(days=1)))
    for m in re.finditer(r"\b(aujourd'hui|today|ce matin|ce soir)\b", text):
        found.append((m.start(), today))
    for m in _WEEKDAY_RE.finditer(text):
        found.append((m.start(), _weekday_date(_WEEKDAYS[m.group(1)], today)))
    ordered: list[date] = []
    for _, value in sorted(found):
        if value <= today and value not in ordered:
            ordered.append(value)
    return ordered


_HISTORY_EN_RE = re.compile(
    r"(?:last|previous|recent)\s+(\d+|two|three|four|five)\s+(long|similar|comparable)?\s*"
    r"(?:runs?|workouts?|sessions?)")


def _history_request(text: str) -> Optional[dict]:
    match = _HISTORY_RE.search(text)
    if not match:
        english = _HISTORY_EN_RE.search(text)
        if not english:
            return None
        match = english
    raw_count = match.group(1)
    count = HISTORY_DEFAULT_COUNT
    if raw_count:
        count = _NUMBER_WORDS.get(raw_count) or int(raw_count)
    qualifier = _norm(match.group(2) or (match.group(3) if match.re is _HISTORY_RE else "") or "")
    kind = "recent"
    if qualifier.startswith("long"):
        kind = "long"
    elif qualifier.startswith(("simil", "compar")):
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
    history = _history_request(text) if (_COMPARE_RE.search(text) or _HISTORY_RE.search(text)
                                         or _HISTORY_EN_RE.search(text)) else None
    if history is not None and history["kind"] == "recent" and not _COMPARE_RE.search(text):
        history = None
    dates = [] if history is not None and not _DAY_MONTH_RE.search(text) and not _NUMERIC_RE.search(text) \
        else _dates_in(text, today)
    selectors: list[dict] = [{"type": "date", "date": d} for d in dates]
    if not selectors:
        km = _KM_RE.search(text)
        if _LAST_RE.search(text) and history is None:
            if _FULL_RE.search(text):
                selectors.append({"type": "last", "km": (41.5, 43.5)})
            elif _HALF_RE.search(text):
                selectors.append({"type": "last", "km": (20.5, 22.0)})
            else:
                selectors.append({"type": "last"})
        elif km and history is None:
            value = float(km.group(1).replace(",", "."))
            tolerance = max(0.5, value * 0.05)
            selectors.append({"type": "distance", "km": (value - tolerance, value + tolerance), "value": value})
        elif (_HALF_RE.search(text) or _FULL_RE.search(text)) and history is None and re.search(
                r"\b(?:ma|mon|my|la|le|the)\s+(?:sortie|course|seance|run|semi|marathon|half)", text):
            selectors.append({"type": "distance", "km": (41.5, 43.5) if _FULL_RE.search(text) else (20.5, 22.0)})
    ordinal = _ORDINAL_RE.search(text)
    return {
        "text": text,
        "selectors": selectors,
        "compare": bool(_COMPARE_RE.search(text)),
        "history": history,
        "anaphora": bool(_ANAPHORA_RE.search(text)),
        "both": bool(_BOTH_RE.search(text)),
        "focus": _focus_of(text),
        "why": bool(_WHY_RE.search(text)),
        "ordinal": ordinal.group(1) if ordinal else None,
        "topic_change": bool(_TOPIC_CHANGE_RE.search(text)),
        "plan_related": bool(_PLAN_EXCLUDE_RE.search(text)),
        "followup": bool(_FOLLOWUP_RE.search(text)),
    }


def needs_memory(parsed: dict) -> bool:
    """Whether the previous turn's references may be required (avoids a read otherwise)."""
    return not parsed["topic_change"] and (
        parsed["anaphora"] or parsed["compare"] or parsed["history"] is not None
        or parsed["ordinal"] is not None or parsed["focus"] is not None or parsed["followup"]
        or bool(parsed["selectors"])
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
    }


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
    docs = await (
        db.workouts.find({"user_id": user_id, "type": "run"}, _PROJECTION)
        .sort("date", -1).limit(200).to_list(200)
    )
    docs = [d for d in docs if d.get("user_id") == user_id and _day(d.get("date"))]
    if km is not None:
        docs = [d for d in docs if _positive(d.get("distance_km")) is not None
                and km[0] <= float(d["distance_km"]) <= km[1]]
    return docs[:limit]


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
    return activity_facts(workout)


# ---------------------------------------------------------------- formatting

def _lang(language: str) -> str:
    return "fr" if (language or "").lower().startswith("fr") else "en"


_MONTH_NAMES = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
}


def _date_label(day: str, language: str, today: date, *, capital: bool = False) -> str:
    d = date.fromisoformat(day)
    lang = _lang(language)
    month = _MONTH_NAMES[lang][d.month - 1]
    year = f" {d.year}" if d.year != today.year else ""
    if lang == "fr":
        label = f"le {d.day}{'er' if d.day == 1 else ''} {month}{year}"
    else:
        label = f"on {d.day} {month}{year}"
    return label[0].upper() + label[1:] if capital else label


def _num(value: float, language: str, decimals: int = 2) -> str:
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",") if _lang(language) == "fr" else text


def _pace(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _duration(minutes: int, language: str) -> str:
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60:02d}"
    return f"{minutes} min"


def _pace_gap(seconds: int, language: str) -> str:
    minutes, rest = divmod(seconds, 60)
    if _lang(language) == "fr":
        return f"{minutes} min {rest:02d} s/km" if minutes else f"{rest} s/km"
    return f"{minutes} min {rest:02d} s/km" if minutes else f"{rest} s/km"


def _join(items: list[str], language: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    word = "et" if _lang(language) == "fr" else "and"
    return f"{', '.join(items[:-1])} {word} {items[-1]}"


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
        "allowed_interpretations": ["measured_values", "computed_gaps", "which_session_is_higher_per_metric"],
        "undemonstrated_conclusions": [
            "fitness_progress", "vo2max_change", "lactate_threshold_change", "better_recovery",
            "higher_physiological_difficulty",
        ],
    }


def _session_sentence(f: dict, language: str, today: date, *, verb_index: int) -> str:
    lang = _lang(language)
    label = _date_label(f["date"], language, today, capital=True)
    parts: list[str] = []
    if lang == "fr":
        if f["distance_km"] is not None:
            parts.append(f"{_num(f['distance_km'], language)} km")
            if f["duration_min"] is not None:
                parts[0] += f" en {_duration(f['duration_min'], language)}"
        elif f["duration_min"] is not None:
            parts.append(f"durée {_duration(f['duration_min'], language)}")
        if f["pace_s_per_km"] is not None:
            parts.append(f"à {_pace(f['pace_s_per_km'])}/km")
        if f["avg_hr"] is not None:
            parts.append(f"avec une FC moyenne de {f['avg_hr']} bpm")
        if f["max_hr"] is not None:
            parts.append(f"FC max {f['max_hr']} bpm")
        if f["elevation_gain_m"] is not None:
            parts.append(f"{f['elevation_gain_m']} m de dénivelé positif")
        verb = ("tu as parcouru", "tu as couru")[verb_index % 2]
        if f["distance_km"] is not None:
            head = f"{verb} {parts[0]}"
            tail = ", ".join(parts[1:])
        else:
            head, tail = "séance enregistrée", ", ".join(parts)
        return f"{label}, {head}{', ' + tail if tail else ''}."
    if f["distance_km"] is not None:
        parts.append(f"{_num(f['distance_km'], language)} km")
        if f["duration_min"] is not None:
            parts[0] += f" in {_duration(f['duration_min'], language)}"
    elif f["duration_min"] is not None:
        parts.append(f"duration {_duration(f['duration_min'], language)}")
    if f["pace_s_per_km"] is not None:
        parts.append(f"at {_pace(f['pace_s_per_km'])}/km")
    if f["avg_hr"] is not None:
        parts.append(f"with an average HR of {f['avg_hr']} bpm")
    if f["max_hr"] is not None:
        parts.append(f"max HR {f['max_hr']} bpm")
    if f["elevation_gain_m"] is not None:
        parts.append(f"{f['elevation_gain_m']} m of climbing")
    verb = ("you covered", "you ran")[verb_index % 2]
    if f["distance_km"] is not None:
        head, tail = f"{verb} {parts[0]}", ", ".join(parts[1:])
    else:
        head, tail = "recorded session", ", ".join(parts)
    return f"{label}, {head}{', ' + tail if tail else ''}."


def _gap_phrase(metric: str, gap: Any, language: str, *, lead: bool) -> str:
    fr = _lang(language) == "fr"
    if metric == "distance_km":
        value = f"{_num(gap, language)} km"
        return (f"distance supérieure de {value}" if fr else f"distance {value} longer") if lead \
            else (f"distance inférieure de {value}" if fr else f"distance {value} shorter")
    if metric == "duration_min":
        value = _duration(gap, language) if gap >= 60 else f"{gap} min"
        return (f"durée supérieure de {value}" if fr else f"duration {value} longer") if lead \
            else (f"durée inférieure de {value}" if fr else f"duration {value} shorter")
    if metric == "pace_s_per_km":
        value = _pace_gap(gap, language)
        return (f"allure plus rapide de {value}" if fr else f"pace {value} faster") if lead \
            else (f"allure plus lente de {value}" if fr else f"pace {value} slower")
    if metric == "avg_hr":
        return (f"FC moyenne supérieure de {gap} bpm" if fr else f"average HR {gap} bpm higher") if lead \
            else (f"FC moyenne inférieure de {gap} bpm" if fr else f"average HR {gap} bpm lower")
    if metric == "max_hr":
        return (f"FC max supérieure de {gap} bpm" if fr else f"max HR {gap} bpm higher") if lead \
            else (f"FC max inférieure de {gap} bpm" if fr else f"max HR {gap} bpm lower")
    return (f"dénivelé supérieur de {gap} m" if fr else f"climbing {gap} m higher") if lead \
        else (f"dénivelé inférieur de {gap} m" if fr else f"climbing {gap} m lower")


def _gaps_sentence(contract: dict, language: str, today: date, metrics: tuple = _METRICS,
                   header: bool = True) -> Optional[str]:
    first, second = contract["activities"]
    fr = _lang(language) == "fr"
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
        if fr:
            sentence = (f"{_date_label(leader['date'], language, today, capital=True)}, par rapport "
                        f"{_date_label(other['date'], language, today).replace('le ', 'au ', 1)} : {clauses}")
        else:
            sentence = f"{_date_label(leader['date'], language, today, capital=True)}, compared with " \
                       f"{other['date'] and _date_label(other['date'], language, today)[3:]}: {clauses}"
        if same:
            sentence += (", mesures identiques : " if fr else ", identical: ") + _join(
                [_metric_name(m, language) for m in same], language)
        return sentence + "."
    clauses = []
    for metric, delta in moving:
        leader = by_id[delta["leader_id"]]
        clauses.append(f"{_gap_phrase(metric, delta['gap'], language, lead=True)} "
                       f"{_date_label(leader['date'], language, today)}")
    if same:
        clauses.append(
            ("mesures identiques : " if fr else "identical: ") + _join([_metric_name(m, language) for m in same], language))
    return ("Écarts : " if fr else "Gaps: ") + "; ".join(clauses) + "."


def _metric_name(metric: str, language: str) -> str:
    names = {
        "fr": {"distance_km": "distance", "duration_min": "durée", "pace_s_per_km": "allure",
               "avg_hr": "FC moyenne", "max_hr": "FC max", "elevation_gain_m": "dénivelé"},
        "en": {"distance_km": "distance", "duration_min": "duration", "pace_s_per_km": "pace",
               "avg_hr": "average HR", "max_hr": "max HR", "elevation_gain_m": "climbing"},
    }
    return names[_lang(language)][metric]


def _missing_sentence(contract: dict, language: str, today: date) -> Optional[str]:
    if not any(len(ids) == 1 for ids in contract["missing"].values()):
        return None
    by_id = {a["id"]: a for a in contract["activities"]}
    fr = _lang(language) == "fr"
    parts = []
    for metric, ids in contract["missing"].items():
        if len(ids) == 2:
            continue
        dates = _join([_short_date(by_id[i]["date"], language) for i in ids], language)
        parts.append(f"{_metric_name(metric, language)} ({dates})")
    prefix = "Non disponible, donc non comparé : " if fr else "Not available, so not compared: "
    return prefix + "; ".join(parts) + "."


def _limit_sentence(contract: dict, language: str) -> str:
    fr = _lang(language) == "fr"
    if contract["distances_comparable"] is False:
        return ("Ces deux séances n'ont pas la même distance et pas forcément le même objectif : ces écarts "
                "décrivent les séances, mais ne démontrent ni une progression, ni un changement de VO2max, "
                "de seuil ou de récupération, ni que l'une était plus difficile physiologiquement."
                if fr else
                "These two sessions differ in distance and not necessarily in purpose: the gaps describe "
                "the sessions but do not show progress, a change in VO2max, threshold or recovery, or that "
                "one was physiologically harder.")
    return ("Ces écarts décrivent les deux séances ; ils ne suffisent pas, seuls, à conclure sur ta forme, "
            "ta VO2max, ton seuil ou ta récupération."
            if fr else
            "These gaps describe the two sessions; on their own they do not allow conclusions about "
            "fitness, VO2max, threshold or recovery.")


def render_pair(contract: dict, language: str, today: date, focus: Optional[str] = None, why: bool = False) -> str:
    first, second = contract["activities"]
    fr = _lang(language) == "fr"
    by_id = {first["id"]: first, second["id"]: second}

    def label(f: dict) -> str:
        return _date_label(f["date"], language, today)

    def both(metric: str, fmt) -> Optional[str]:
        if metric in contract["missing"]:
            return None
        return fmt(first[metric]), fmt(second[metric])

    if focus == "progress":
        return (
            f"Je ne peux pas conclure que tu progresses à partir de ces deux séances. "
            f"{_session_sentence(first, language, today, verb_index=0)} "
            f"{_session_sentence(second, language, today, verb_index=1)} "
            "Deux séances de distances et d'objectifs différents ne prouvent pas une évolution de ta forme ; "
            "pour en parler, il faudrait des séances comparables dans le temps. "
            "Je peux comparer avec tes dernières sorties similaires."
            if fr else
            "I can't conclude that you are improving from these two sessions. "
            f"{_session_sentence(first, language, today, verb_index=0)} "
            f"{_session_sentence(second, language, today, verb_index=1)} "
            "Two sessions with different distances and purposes do not show a change in fitness; that needs "
            "comparable sessions over time. I can compare with your most similar recent runs."
        )
    if focus == "hr":
        if "avg_hr" in contract["missing"]:
            return (_missing_sentence(contract, language, today) or "")
        hr = contract["deltas"]["avg_hr"]
        text = (f"Côté cardio, la FC moyenne était de {first['avg_hr']} bpm {label(first)} et de "
                f"{second['avg_hr']} bpm {label(second)}"
                if fr else
                f"On heart rate, the average was {first['avg_hr']} bpm {label(first)} and "
                f"{second['avg_hr']} bpm {label(second)}")
        if hr["leader_id"] is not None:
            text += (f", soit {hr['gap']} bpm de plus {label(by_id[hr['leader_id']])}." if fr
                     else f", {hr['gap']} bpm higher {label(by_id[hr['leader_id']])}.")
        else:
            text += ", soit une FC moyenne identique." if fr else ", i.e. identical."
        if "max_hr" in contract["deltas"]:
            text += (f" FC max : {first['max_hr']} bpm contre {second['max_hr']} bpm." if fr
                     else f" Max HR: {first['max_hr']} bpm versus {second['max_hr']} bpm.")
        if why:
            context = _gaps_sentence(contract, language, today, ("distance_km", "duration_min", "pace_s_per_km"),
                                     header=False)
            text += (" Les données disponibles ne permettent pas d'isoler la cause de cet écart"
                     if fr else " The available data do not isolate the cause of this gap")
            text += ((f" ; les séances diffèrent aussi : {context}." if fr
                      else f"; the sessions also differ: {context}.") if context else ".")
            text += (" La chaleur, la fatigue ou la dérive cardiaque ne sont pas mesurées ici." if fr
                     else " Heat, fatigue or cardiac drift are not measured here.")
        return text
    if focus == "pace":
        if "pace_s_per_km" in contract["missing"]:
            return _missing_sentence(contract, language, today) or ""
        delta = contract["deltas"]["pace_s_per_km"]
        if delta["leader_id"] is None:
            return (f"Ton allure moyenne est identique : {_pace(first['pace_s_per_km'])}/km." if fr
                    else f"Your average pace is identical: {_pace(first['pace_s_per_km'])}/km.")
        winner = by_id[delta["leader_id"]]
        loser = second if winner is first else first
        text = (f"C'est {label(winner)} que tu as couru le plus vite : {_pace(winner['pace_s_per_km'])}/km "
                f"contre {_pace(loser['pace_s_per_km'])}/km, soit {_pace_gap(delta['gap'], language)} plus vite."
                if fr else
                f"You ran faster {label(winner)}: {_pace(winner['pace_s_per_km'])}/km versus "
                f"{_pace(loser['pace_s_per_km'])}/km, {_pace_gap(delta['gap'], language)} faster.")
        if contract["distances_comparable"] is False:
            text += (" Les distances sont différentes, donc cet écart ne mesure pas à lui seul une différence de forme."
                     if fr else " The distances differ, so this gap alone does not measure a difference in fitness.")
        return text
    if focus in ("distance", "duration", "elevation"):
        metric = {"distance": "distance_km", "duration": "duration_min", "elevation": "elevation_gain_m"}[focus]
        if metric in contract["missing"]:
            return _missing_sentence(contract, language, today) or ""
        sentence = _gaps_sentence(contract, language, today, (metric,))
        return sentence or ""
    if focus == "demanding":
        counts: dict[str, int] = {first["id"]: 0, second["id"]: 0}
        used = []
        for metric in ("distance_km", "duration_min", "avg_hr", "pace_s_per_km"):
            delta = contract["deltas"].get(metric)
            if delta and delta["leader_id"] is not None:
                counts[delta["leader_id"]] += 1
                used.append(metric)
        names = _join([_metric_name(m, language) for m in used], language)
        if used and counts[first["id"]] == len(used) or used and counts[second["id"]] == len(used):
            leader = first if counts[first["id"]] else second
            text = (f"Sur les indicateurs disponibles ({names}), c'est {label(leader)} que les valeurs sont "
                    "les plus élevées."
                    if fr else
                    f"On the available indicators ({names}), the values are higher {label(leader)}.")
        elif used:
            text = ("Les indicateurs disponibles ne vont pas dans le même sens "
                    f"({names}), donc je ne peux pas désigner la séance la plus exigeante."
                    if fr else
                    f"The available indicators do not agree ({names}), so I can't name the more demanding session.")
        else:
            text = ("Je n'ai pas assez d'indicateurs comparables pour désigner la séance la plus exigeante."
                    if fr else "I don't have enough comparable indicators to name the more demanding session.")
        text += (" Ce n'est pas une mesure de difficulté physiologique : elle dépend aussi de l'objectif et de "
                 "ton état du jour, que je ne connais pas ici." if fr else
                 " This is not a measure of physiological difficulty: it also depends on purpose and how you felt, "
                 "which I don't have here.")
        return text

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
    population = list(reversed(picked[:count]))  # most recent `count`, shown chronologically
    contract["population"] = population
    stats: dict[str, Any] = {}
    for metric in ("distance_km", "duration_min", "pace_s_per_km", "avg_hr"):
        values = [f[metric] for f in population if f[metric] is not None]
        stats[metric] = {"n": len(values), "median": _median_int(values) if metric != "distance_km"
                         else (round(median(values), 2) if values else None)}
    contract["population_stats"] = stats
    return contract


def render_history(contract: dict, language: str, today: date) -> str:
    fr = _lang(language) == "fr"
    ref = contract["reference"]
    criterion = contract["criterion"]
    ref_line = _session_sentence(ref, language, today, verb_index=0)
    kind = criterion["kind"]
    if criterion.get("established") is False:
        if kind == "long":
            reason = (f"Je ne peux pas établir ce qu'est une sortie longue pour toi : il faut au moins "
                      f"{criterion['min_history']} séances avec durée sur les {contract['window_days']} derniers jours "
                      f"avant celle-ci, et je n'en ai que {contract['window_size']}." if fr else
                      f"I can't establish what a long run is for you: at least {criterion['min_history']} timed "
                      f"sessions in the {contract['window_days']} days before this one are needed, and I have "
                      f"{contract['window_size']}.")
        else:
            reason = ("La distance de la séance de référence est absente : je ne peux pas chercher de séances "
                      "similaires." if fr else
                      "The reference session has no distance: I can't look for similar sessions.")
        return f"{ref_line} {reason}"
    if kind == "long":
        criteria = (f"séances d'au moins {_num(criterion['ratio'], language)} fois ta durée habituelle "
                    f"({_duration(int(round(contract['habitual_duration_min'])), language)} en médiane sur "
                    f"{contract['window_days']} jours), soit {_duration(int(round(criterion['threshold_min'])), language)} "
                    "ou plus" if fr else
                    f"sessions of at least {_num(criterion['ratio'], language)} times your usual duration "
                    f"({_duration(int(round(contract['habitual_duration_min'])), language)} median over "
                    f"{contract['window_days']} days), i.e. {_duration(int(round(criterion['threshold_min'])), language)} or more")
    elif kind == "similar":
        criteria = (f"distance de {_num(criterion['min_km'], language)} à {_num(criterion['max_km'], language)} km "
                    f"(±{_num(criterion['tolerance_pct'], language, 0)} % de la séance de référence)" if fr else
                    f"distance between {_num(criterion['min_km'], language)} and {_num(criterion['max_km'], language)} km "
                    f"(±{_num(criterion['tolerance_pct'], language, 0)}% of the reference session)")
    else:
        criteria = ("les sorties de course les plus récentes, sans autre critère" if fr
                    else "the most recent runs, with no other criterion")
    population = contract["population"]
    n = len(population)
    if n == 0:
        none = (f"Aucune séance antérieure ne correspond au critère ({criteria}) sur les "
                f"{contract['window_days']} derniers jours." if fr else
                f"No earlier session matches the criterion ({criteria}) in the last {contract['window_days']} days.")
        return f"{ref_line} {none}"
    head = (f"Critère retenu : {criteria}. {n} séance{'s' if n > 1 else ''} retenue{'s' if n > 1 else ''}"
            f"{f' sur {contract['requested']} demandées' if n < contract['requested'] else ''}, "
            "de la plus ancienne à la plus récente :" if fr else
            f"Criterion: {criteria}. {n} session{'s' if n != 1 else ''} kept"
            f"{f' out of {contract['requested']} requested' if n < contract['requested'] else ''}, "
            "oldest to most recent:")
    lines = [f"- {_session_sentence(f, language, today, verb_index=i)}" for i, f in enumerate(population)]
    stats = contract["population_stats"]
    gap_parts = []
    if ref["distance_km"] is not None and stats["distance_km"]["median"] is not None:
        diff = round(ref["distance_km"] - stats["distance_km"]["median"], 2)
        gap_parts.append((f"distance {'+' if diff >= 0 else '−'}{_num(abs(diff), language)} km"))
    if ref["duration_min"] is not None and stats["duration_min"]["median"] is not None:
        diff = ref["duration_min"] - stats["duration_min"]["median"]
        gap_parts.append(f"{'durée' if fr else 'duration'} {'+' if diff >= 0 else '−'}{abs(diff)} min")
    if ref["pace_s_per_km"] is not None and stats["pace_s_per_km"]["median"] is not None:
        diff = ref["pace_s_per_km"] - stats["pace_s_per_km"]["median"]
        word = ("plus lente" if diff > 0 else "plus rapide") if fr else ("slower" if diff > 0 else "faster")
        gap_parts.append(f"{'allure' if fr else 'pace'} {_pace_gap(abs(diff), language)} {word}" if diff
                         else ("allure identique" if fr else "same pace"))
    if ref["avg_hr"] is not None and stats["avg_hr"]["median"] is not None:
        diff = ref["avg_hr"] - stats["avg_hr"]["median"]
        gap_parts.append(f"{'FC moyenne' if fr else 'average HR'} {'+' if diff >= 0 else '−'}{abs(diff)} bpm")
    median_line = ""
    if gap_parts:
        counts = {m: s["n"] for m, s in stats.items()}
        partial = n and any(v < n for v in counts.values() if v)
        median_line = (f"Par rapport à la médiane de ces séances : {', '.join(gap_parts)}"
                       if fr else f"Against the median of these sessions: {', '.join(gap_parts)}")
        median_line += (" (certaines mesures manquent pour une partie des séances)." if fr and partial
                        else " (some measures are missing for part of the sessions)." if partial else ".")
    notes = []
    if kind == "long" and contract["reference_matches_criterion"] is False:
        notes.append("La séance de référence n'est pas elle-même une sortie longue selon ce critère, "
                     "les séances ne sont donc pas directement comparables." if fr else
                     "The reference session is not itself a long run under this criterion, so the sessions "
                     "are not directly comparable.")
    notes.append("Cette comparaison est descriptive : elle ne démontre ni progression, ni changement de forme, "
                 "de VO2max ou de récupération, car conditions et objectifs des séances peuvent différer." if fr else
                 "This comparison is descriptive: it does not show progress or a change in fitness, VO2max or "
                 "recovery, as conditions and purposes may differ.")
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


def _passthrough() -> dict:
    return {"kind": "passthrough"}


def _reply(text: str, refs: Optional[dict] = None) -> dict:
    return {"kind": "reply", "text": text, "refs": refs}


def _clarify_text(language: str, kind: str, today: date, *, day: Optional[str] = None,
                  choices: Optional[list[str]] = None) -> str:
    fr = _lang(language) == "fr"
    if kind == "multiple":
        listing = " ; ".join(choices or [])
        when = _date_label(day, language, today)[3:] if day else ""
        return (f"J'ai trouvé plusieurs séances{' le ' + when if day else ''} : "
                f"{listing}. Laquelle veux-tu ? Réponds par exemple « la 1 »." if fr else
                f"I found several sessions{' on ' + when if day else ''}: {listing}. Which one do you mean? "
                "For example, answer “1”.")
    if kind == "none":
        when = _date_label(day, language, today)[3:] if day else ""
        return (f"Je ne trouve aucune course {'le ' + when if day else 'correspondante'} dans tes activités "
                "importées." if fr else
                f"I can't find any run{' on ' + when if day else ' matching that'} in your imported activities.")
    if kind == "referent":
        return ("De quelle séance parles-tu ? Donne-moi une date (par exemple « le 12 octobre ») ou « ma dernière "
                "sortie »." if fr else
                "Which session do you mean? Give me a date (for example “October 12”) or “my last run”.")
    if kind == "which_reference":
        return ("Avec laquelle de ces séances veux-tu faire la comparaison ? Indique une date." if fr
                else "Which of these sessions should be the reference? Please give a date.")
    return ""


def _pick_choice(parsed: dict, choices: list[dict]) -> Optional[dict]:
    """Choice designated by the answer to a clarification: a date, else an ordinal."""
    wanted = [s["date"].isoformat() for s in parsed["selectors"] if s["type"] == "date"]
    pool = [c for c in choices if wanted and c.get("date") in wanted]
    if len(pool) == 1:
        return pool[0]
    ordinal = parsed["ordinal"]
    if ordinal and not wanted:
        words = {"premiere": 1, "premier": 1, "first": 1, "seconde": 2, "second": 2, "deuxieme": 2}
        if ordinal in ("derniere", "dernier", "last"):
            return choices[-1]
        index = words.get(ordinal) or int(ordinal)
        if 1 <= index <= len(choices):
            return choices[index - 1]
    return None


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
    if selector["type"] == "last" or len(runs) == 1:
        return {"workout": runs[0]}
    shown = runs[:CHOICE_LIMIT]
    labels = []
    for i, w in enumerate(shown, 1):
        labels.append(f"{i}) {_date_label(_day(w['date']), language, today)[3:]} – "
                      f"{_choice_label(w, i, language).split(') ', 1)[1]}")
    return {"reply": _clarify_text(language, "multiple", today, choices=labels),
            "choices": [_choice_entry(w) for w in shown]}


async def _pair_response(db: Any, user_id: str, ids: list[str], language: str, today: date,
                         focus: Optional[str], why: bool) -> dict:
    facts = [await load_activity_facts(db, user_id, i) for i in ids]
    if any(f is None or not f["date"] for f in facts) or len({f["id"] for f in facts}) != 2:
        return _reply(_clarify_text(language, "referent", today))
    contract = build_comparison_contract(facts[0], facts[1])
    text = render_pair(contract, language, today, focus=focus, why=why)
    refs = _refs("pair", [f["id"] for f in contract["activities"]], primary=ids[0])
    return {"kind": "compare", "text": text, "refs": refs, "contract": contract}


async def resolve_turn(*, db: Any, user_id: str, message: str, language: str, today: date,
                       memory: Optional[dict], parsed: Optional[dict] = None) -> dict:
    """Decide how one general-chat message is handled.

    Returns {"kind": "passthrough"} (ordinary chat), {"kind": "single", "workout_id", "refs"}
    (selected-workout path), {"kind": "compare", "text", "refs", "contract"} or
    {"kind": "reply", "text", "refs"} (clarification / nothing found).
    `memory` is the `coach_refs` of the latest assistant message of the same user's general chat.
    """
    p = parsed or parse_message(message, today)
    if p["topic_change"] or not needs_memory(p):
        return _passthrough()
    memory = memory if isinstance(memory, dict) and memory.get("v") == REFS_VERSION else None
    ids = [i for i in (memory or {}).get("workout_ids", []) if isinstance(i, str)]
    mem_kind = (memory or {}).get("kind")
    pending = (memory or {}).get("pending")
    selectors = p["selectors"]
    fr = _lang(language) == "fr"

    # A) answer to a previous clarification
    if isinstance(pending, dict) and pending.get("choices"):
        choice = _pick_choice(p, pending["choices"])
        if choice is not None:
            intent = pending.get("intent") or {}
            others = [i for i in intent.get("others", []) if isinstance(i, str)]
            if intent.get("action") == "history":
                return await _history_turn(db, user_id, choice["id"], intent["history"], language, today)
            if others:
                return await _pair_response(db, user_id, [others[0], choice["id"]], language, today,
                                            intent.get("focus"), bool(intent.get("why")))
            return {"kind": "single", "workout_id": choice["id"],
                    "refs": _refs("single", [choice["id"]], primary=choice["id"])}
        if not selectors:
            if p["ordinal"] is not None or p["anaphora"]:
                return _reply(_clarify_text(language, "referent", today), None)
        # a new explicit selector or topic below supersedes the pending choice

    # B) history comparison
    if p["history"] is not None:
        ref_id: Optional[str] = None
        if selectors:
            resolved = await _resolve_selector(db, user_id, selectors[0], language, today)
            if "workout" not in resolved:
                intent = {"action": "history", "history": p["history"]}
                return _reply(resolved["reply"], _refs(mem_kind or "single", [], pending={
                    "choices": resolved.get("choices", []), "intent": intent}) if resolved.get("choices") else None)
            ref_id = resolved["workout"]["id"]
        elif len(ids) == 1:
            ref_id = ids[0]
        elif len(ids) == 2:
            choices = []
            for i in ids:
                f = await load_activity_facts(db, user_id, i)
                if f is not None:
                    choices.append({"id": i, "date": f["date"]})
            return _reply(_clarify_text(language, "which_reference", today),
                          _refs("pair", ids, pending={"choices": choices, "intent": {
                              "action": "history", "history": p["history"]}}))
        if ref_id is None:
            return _reply(_clarify_text(language, "referent", today), None)
        return await _history_turn(db, user_id, ref_id, p["history"], language, today)

    # C) comparison of two sessions
    if p["compare"] or (p["both"] and len(ids) == 2):
        chosen: list[str] = []
        for selector in selectors[:2]:
            resolved = await _resolve_selector(db, user_id, selector, language, today)
            if "workout" not in resolved:
                if resolved.get("choices"):
                    intent = {"action": "pair", "others": chosen, "focus": p["focus"], "why": p["why"]}
                    return _reply(resolved["reply"], _refs(mem_kind or "single", ids, pending={
                        "choices": resolved["choices"], "intent": intent}))
                return _reply(resolved["reply"], None)
            chosen.append(resolved["workout"]["id"])
        if len(chosen) == 2:
            return await _pair_response(db, user_id, chosen, language, today, p["focus"], p["why"])
        if len(chosen) == 1:
            if mem_kind == "single" and len(ids) == 1 and ids[0] != chosen[0]:
                return await _pair_response(db, user_id, [ids[0], chosen[0]], language, today, p["focus"], p["why"])
            if mem_kind == "pair" and chosen[0] in ids:
                return await _pair_response(db, user_id, ids, language, today, p["focus"], p["why"])
            return _reply(_clarify_text(language, "which_reference", today) if mem_kind == "pair"
                          else _clarify_text(language, "referent", today), None)
        if mem_kind == "pair" and len(ids) == 2:
            return await _pair_response(db, user_id, ids, language, today, p["focus"], p["why"])
        return _reply(_clarify_text(language, "referent", today), None)

    # D) new explicit session (also a change of subject)
    if selectors:
        resolved = await _resolve_selector(db, user_id, selectors[0], language, today)
        if "workout" in resolved:
            wid = resolved["workout"]["id"]
            return {"kind": "single", "workout_id": wid, "refs": _refs("single", [wid], primary=wid)}
        if resolved.get("choices"):
            return _reply(resolved["reply"], _refs(mem_kind or "single", [], pending={
                "choices": resolved["choices"], "intent": {"action": "single", "others": []}}))
        return _reply(resolved["reply"], None)

    # E) follow-up on the sessions of the previous turn
    if memory is not None and ids and not p["plan_related"]:
        if mem_kind == "pair" and len(ids) == 2 and (p["focus"] or p["both"] or p["anaphora"]):
            return await _pair_response(db, user_id, ids, language, today, p["focus"], p["why"])
        if mem_kind == "single" and len(ids) == 1 and (p["focus"] or p["anaphora"] or p["followup"]):
            return {"kind": "single", "workout_id": ids[0], "refs": _refs("single", ids, primary=ids[0])}
    if p["anaphora"]:
        return _reply(_clarify_text(language, "referent", today), None)
    return _passthrough()


async def _history_turn(db: Any, user_id: str, workout_id: str, history: dict, language: str, today: date) -> dict:
    reference = await load_activity_facts(db, user_id, workout_id)
    if reference is None or not reference["date"]:
        return _reply(_clarify_text(language, "referent", today), None)
    contract = await build_history_contract(db, user_id, reference, history["kind"], history["count"])
    return {"kind": "compare", "text": render_history(contract, language, today),
            "refs": _refs("single", [workout_id], primary=workout_id), "contract": contract}


def today_for(now_utc: datetime) -> date:
    return now_utc.astimezone(timezone.utc).date()
