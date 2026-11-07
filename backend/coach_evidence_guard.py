"""C408-C — bounded, deterministic check of a Coach chat reply against the evidence contract.

Scope: a chat reply about a SELECTED historical workout. It is the C403 heuristic guard
(figures, units, dates, physiology wording, sensations, advice, goal claims) PLUS checks that
need the C408-C contract: populations (counts and what they are made of), prescription
chronology, and a few interpretation traps (HR rise read as intensity, pace read as
performance, recovery need).

What this is NOT: a proof of truth. A reply that passes only means no *checked* claim was
contradicted by the contract. Claims the patterns cannot see (a paraphrase, an implicit
comparison) pass unchecked. One generation, one deterministic check, no second LLM call: a
rejected reply is replaced by a factual reply built from the contract itself.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import coach_session_comment as csc

LEVEL = "heuristic_guard_with_evidence_contract"

_SESSION_NOUN = (r"(?:s[ée]ances?|sessions?|sorties?|runs?|sesiones?|salidas?|activit[ée]s?|activities|"
                 r"workouts?|entra[iî]nements?)")
_COUNT_BEFORE_NOUN = re.compile(rf"\b(\d{{1,3}})\s+(?:\w+\s+){{0,2}}?{_SESSION_NOUN}\b", re.I)
_WORD_COUNT_BEFORE_NOUN = re.compile(
    rf"\b(un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|one|two|three|four|five|seven|eight|nine|ten|"
    rf"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+(?:\w+\s+){{0,2}}?{_SESSION_NOUN}\b", re.I)

_SAME_DISTANCE = re.compile(
    r"(m[êe]me distance|(?:s[ée]ances?|sorties?|runs?|sessions?|salidas?|sesiones?)\s+(?:similaires?|similar(?:es)?)\b|"
    r"distances? (?:similaires?|comparables?|identiques?|proche)|same distance|"
    r"(?:similar|comparable|same)[- ]distance|distance (?:similar|comparable)|misma distancia|"
    r"distancias? (?:similares?|comparables?)|de distance (?:similaire|comparable))", re.I)
_HR_POSITION = re.compile(
    r"(quartile|partie (?:basse|haute)|lower (?:part|end|quarter)|upper (?:part|end|quarter)|"
    r"parte (?:baja|alta)|m[ée]diane|median|mediana|position relative|relative position|"
    r"plus basse|plus haute|lowest|highest)", re.I)
_AVERAGE_WORDING = re.compile(
    r"(en moyenne|on average|average|moyenne|habituel|usually|d'habitude|typical|promedio|"
    r"normalmente|generalmente|m[ée]diane|median)", re.I)

_NON_COMPLIANCE = re.compile(
    r"(non[- ]respect|pas respect|n'a pas [ée]t[ée] respect|ne respecte|[ée]cart (?:par rapport|avec|vis)|"
    r"s'[ée]carte|d[ée]vi(?:ation|e|ez|er)|deviat|did not (?:follow|respect|stick)|didn't (?:follow|stick)|"
    r"not (?:follow|respect)ed|departed from|differs? from the (?:plan|prescri)|"
    r"no (?:se )?respet|se desvi|incumpl|no sigui[óo]|contrairement [àa] (?:la|ce qui)|contrary to)", re.I)
_PRESCRIPTION_WORD = re.compile(r"(prescri|prescrit|prescripci|programm[ée]e?|planifi|planned|scheduled)", re.I)
_PRESCRIPTION_AS_INTENT = re.compile(
    r"(?:[ée]tai[ts]? (?:pr[ée]vu|prescrit|programm[ée]|censé)|was (?:planned|scheduled|prescribed|meant|"
    r"intended|supposed)|was meant|devait|should have been|pr[ée]vu(?:e)? (?:pour|ce jour)|planned for|"
    r"prescrit(?:e)? pour|estaba (?:previst|prescrit|planificad)|se supon[ií]a|"
    r"(?:avant|before|antes de)l?\s+(?:le d[ée]part|la s[ée]ance|the (?:start|session)|la sesi[óo]n|salir|partir))",
    re.I)
_HR_RISE = re.compile(
    r"(?:\b(?:FC|HR|fr[ée]quence cardiaque|heart rate|frecuencia card[ií]aca|cardiaque)\b[^.!?]{0,60}"
    r"\b(?:augment|mont|grimp|hausse|d[ée]rive|rise|rose|increas|climb|drift|sub[ei]|aument)\w*)", re.I)
_INTENSITY_RISE = re.compile(
    r"(intensit[ée]|intensity|intensidad|effort (?:croissant|plus|accru)|plus (?:dur|soutenu|intense)|"
    r"harder|more intense|increasing effort|esfuerzo creciente|mont[ée]e en (?:charge|puissance|intensit))", re.I)
_PERFORMANCE_CLAIM = re.compile(
    r"(meilleure? performance|better performance|performance (?:sup[ée]rieure|am[ée]lior[ée]e|en hausse)|"
    r"plus performant|mieux perform|mejor rendimiento|mejor desempe[ñn]o|performed better|"
    r"performance (?:was|is) (?:better|stronger)|belle performance|great performance|strong performance)", re.I)
_RECOVERY_ADVICE = re.compile(
    r"(besoin de (?:r[ée]cup[ée]r|repos)|(?:il faut|tu dois|vous devez|prends|prenez|pr[ée]vois|pr[ée]voyez|"
    r"pense [àa]|laisse|laissez|accorde|accordez)\s+(?:\w+\s+){0,3}(?:r[ée]cup[ée]r|repos|souffler)|"
    r"needs? (?:to )?(?:recover|rest)|(?:take|get|have|plan|allow)\s+(?:\w+\s+){0,2}(?:rest|recovery)\b|"
    r"should (?:rest|recover)|necesit(?:as|a|amos) (?:recuper|descans)|debes (?:descansar|recuperar)|"
    r"toma (?:un )?descanso|descansa\b|r[ée]cup[ée]ration (?:est|sera) (?:n[ée]cessaire|indispensable|importante)|"
    r"recovery (?:is|will be) (?:needed|necessary|important|essential))", re.I)


def _int_set(*values: Any) -> set[int]:
    return {int(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)}


_HR_WORD = re.compile(r"\b(?:FC|HR|fr[ée]quence cardiaque|heart rate|frecuencia card[ií]aca|cardiaque)\b", re.I)
_POS_LOW = re.compile(r"(partie basse|zone basse|lower (?:part|end|range|quarter)|low end|parte baja|"
                      r"plus basses?|lowest|bas(?:se)? de (?:votre|ton|ta|vos) )", re.I)
_POS_HIGH = re.compile(r"(partie haute|zone haute|upper (?:part|end|range|quarter)|high end|parte alta|"
                       r"plus hautes?|highest)", re.I)
_COMPARABLE_EFFORT = re.compile(
    r"(?:(?:[àa]|at|a)\s+(?:FC|HR|allure|pace|ritmo)\s+(?:comparable|similaire|similar)|comparable\s+(?:HR|FC|pace|"
    r"allure|ritmo)|(?:HR|FC|pace|allure|ritmo)\s+(?:at|[àa]|a)\s+(?:a\s+)?comparable)", re.I)
_AT_COMPARABLE_HR = re.compile(
    r"(?:(?:[àa]|at|con)\s+(?:FC|HR)\s+(?:comparable|similaire|similar)|comparable\s+(?:HR|FC)\b)", re.I)
_AT_COMPARABLE_PACE = re.compile(
    r"(?:(?:[àa]|at|con)\s+(?:allure|pace|ritmo)\s+(?:comparable|similaire|similar)|comparable\s+"
    r"(?:pace|allure|ritmo)\b)", re.I)
_HISTORY_LIST = re.compile(
    r"(derni[èe]res? (?:\w+\s+)?(?:s[ée]ances?|sorties?)|(?:last|recent|latest|previous)\s+(?:\w+\s+)?"
    r"(?:sessions?|runs?|workouts?)|[úu]ltimas? (?:\w+\s+)?(?:sesiones?|salidas?)|"
    r"s[ée]ances? (?:affich|list|transmises?)|listed|shown|mostrad)", re.I)
_BELOW_LT1 = re.compile(r"(sous (?:le |la )?(?:LT1|seuil 1|premier seuil)|below (?:the )?(?:LT1|first threshold)|"
                        r"por debajo (?:de(?:l)? )?(?:LT1|primer umbral))", re.I)
_ABOVE_LT2 = re.compile(r"(au[- ]dessus (?:du |de )?(?:LT2|seuil 2|second seuil)|above (?:the )?(?:LT2|second threshold)|"
                        r"por encima (?:de(?:l)? )?(?:LT2|segundo umbral))", re.I)


def _contract(context: dict) -> dict:
    """What the contract says, with every count tied to the metric and population it describes."""
    frame = context.get("session_coaching_frame") if isinstance(context.get("session_coaching_frame"), dict) else {}
    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    relative = ((v3.get("classification") or {}).get("relative_effort")) or {}
    comparison = v3.get("historical_comparison") or {}
    history = context.get("history_as_of_session") or {}
    profile = (context.get("runner_profile") or {}).get("observed_training") or {}
    contract = frame.get("evidence_contract") or {}
    similar_entry = next(
        (c for c in contract.get("validated_comparisons") or []
         if c.get("metric") == "pace_and_hr_vs_similar_distance_sessions"), {})
    similar_count = similar_entry.get("activity_count")
    sub = ((comparison.get("provenance") or {}).get("sub_populations")) or {}
    relative_used = relative.get("status") == "used"
    by_metric = {
        "hr_position": _int_set(relative.get("reference_count") if relative_used else None),
        "comparable_effort": _int_set(
            comparison.get("reference_count"),
            *(block.get("activity_count") for block in sub.values() if isinstance(block, dict))),
        "similar_distance": _int_set(similar_count, similar_entry.get("pace_sample_count")),
        "pace_at_hr": _int_set((sub.get("pace_at_comparable_hr") or {}).get("activity_count")),
        "hr_at_pace": _int_set((sub.get("hr_at_comparable_pace") or {}).get("activity_count")),
        "comparison_global": _int_set(comparison.get("reference_count")),
        "history_list": _int_set(history.get("included_count"), history.get("eligible_count")),
        "profile": _int_set(profile.get("sessions_count"), profile.get("sessions_with_distance_count")),
    }
    recorded = (frame.get("session_intent") or {}).get("recorded_historical_prescription")
    intensity = v3.get("intensity") or {}
    return {
        "by_metric": by_metric,
        "all_counts": set().union(*by_metric.values()),
        "shown_count": history.get("included_count"),
        "population_count": profile.get("sessions_count"),
        "has_profile_stat": bool(profile),
        "relative_used": relative_used,
        "relative_position": relative.get("relative_position") if relative_used else None,
        "threshold_position": intensity.get("position_vs_declared_thresholds")
        if intensity.get("thresholds_available") else None,
        "recorded": recorded if isinstance(recorded, dict) else None,
        "has_not_demonstrated": set(contract.get("not_demonstrated") or {}),
    }


def _allowed_counts(sentence: str, c: dict) -> set[int]:
    """Counts a sentence may cite, decided by the kind of population the sentence talks about."""
    by = c["by_metric"]
    if _HR_WORD.search(sentence) and (_HR_POSITION.search(sentence) or _POS_LOW.search(sentence)
                                      or _POS_HIGH.search(sentence)):
        return by["hr_position"]  # exclusive: an HR position is about the relative-HR population only
    at_hr, at_pace = bool(_AT_COMPARABLE_HR.search(sentence)), bool(_AT_COMPARABLE_PACE.search(sentence))
    if at_hr or at_pace:  # each metric-specific comparison may cite only its own population
        return (by["pace_at_hr"] if at_hr else set()) | (by["hr_at_pace"] if at_pace else set())
    if _COMPARABLE_EFFORT.search(sentence):
        return by["comparable_effort"]
    if _SAME_DISTANCE.search(sentence):
        return by["similar_distance"]
    if _HISTORY_LIST.search(sentence):
        return by["history_list"]
    if c["has_profile_stat"] and _AVERAGE_WORDING.search(sentence):
        return by["profile"] | by["history_list"]
    return c["all_counts"] | {1}  # no stated population: a known count, but unattributed (documented limit)


def check_contract_claims(text: str, context: dict, question: Optional[str] = None) -> set[str]:
    """Contract-based reasons for rejecting a reply; empty when no checked claim is contradicted."""
    c = _contract(context)
    requested = _requested_counts(question, c)
    reasons: set[str] = set()
    recorded = c["recorded"]
    status = (recorded or {}).get("assessment_status")
    facts = _facts(context)
    for sentence in csc._sentences(text):
        if _direction_contradicted(sentence, facts):
            reasons.add("comparison_direction_contradicts")
        counts: list[int] = [int(m.group(1)) for m in _COUNT_BEFORE_NOUN.finditer(sentence)]
        counts += [csc._WORD_VALUE[m.group(1).lower()] for m in _WORD_COUNT_BEFORE_NOUN.finditer(sentence)]
        counts = [n for n in counts if n > 1]
        allowed = _allowed_counts(sentence, c)
        for n in counts:
            if n in allowed or n in requested:
                continue
            if n in c["all_counts"] and allowed is c["by_metric"]["hr_position"]:
                reasons.add("hr_position_wrong_population")
            else:
                reasons.add("ungrounded_population_count")
        if _SAME_DISTANCE.search(sentence) and not csc._only_negated(sentence, _SAME_DISTANCE):
            by_count = any(n in c["by_metric"]["comparable_effort"] | c["by_metric"]["hr_position"]
                           and n not in c["by_metric"]["similar_distance"] for n in counts)
            if _HR_POSITION.search(sentence) or by_count:
                reasons.add("population_misdescribed")
        if _HR_WORD.search(sentence) and not csc._only_negated(sentence, _HR_POSITION):
            low, high = bool(_POS_LOW.search(sentence)), bool(_POS_HIGH.search(sentence))
            if low or high or _HR_POSITION.search(sentence):
                if not c["relative_used"]:
                    reasons.add("hr_position_not_established")
                elif (low and c["relative_position"] != "low") or (high and c["relative_position"] != "high"):
                    reasons.add("hr_position_contradicts_v3")
        position = c["threshold_position"]
        if _BELOW_LT1.search(sentence) and position != "below_LT1" or \
                _ABOVE_LT2.search(sentence) and position != "above_LT2":
            reasons.add("threshold_position_not_established")
        if (c["has_profile_stat"] and _AVERAGE_WORDING.search(sentence)
                and c["shown_count"] and c["population_count"] and c["shown_count"] != c["population_count"]
                and c["shown_count"] in counts and c["population_count"] not in counts
                and not _HISTORY_LIST.search(sentence)):
            reasons.add("statistic_on_wrong_population")
        if _NON_COMPLIANCE.search(sentence) and status != "deviation" and not csc._only_negated(
                sentence, _NON_COMPLIANCE):
            reasons.add("non_compliance_not_established")
        if _PRESCRIPTION_WORD.search(sentence) and not csc._only_negated(sentence, _PRESCRIPTION_WORD):
            if recorded is None:
                reasons.add("prescription_not_recorded")
            elif (recorded.get("recording_timing") != "recorded_before_session"
                  and _PRESCRIPTION_AS_INTENT.search(sentence)):
                reasons.add("prescription_timing_misstated")
        if "hr_rise_is_not_external_intensity" in c["has_not_demonstrated"] \
                and _HR_RISE.search(sentence) and _INTENSITY_RISE.search(sentence) \
                and not csc._only_negated(sentence, _INTENSITY_RISE):
            reasons.add("hr_rise_read_as_intensity")
        if _PERFORMANCE_CLAIM.search(sentence) and not csc._only_negated(sentence, _PERFORMANCE_CLAIM):
            reasons.add("pace_read_as_performance")
        if _RECOVERY_ADVICE.search(sentence) and not csc._only_negated(sentence, _RECOVERY_ADVICE):
            reasons.add("recovery_advice_not_supported")
    return reasons


def _requested_counts(question: Optional[str], c: dict) -> set[int]:
    """List sizes the user asked for ("my last five sessions"): honoured only up to what is really available."""
    if not isinstance(question, str) or not question.strip():
        return set()
    available = c["shown_count"] if isinstance(c["shown_count"], int) else 0
    asked = [int(m.group(1)) for m in _COUNT_BEFORE_NOUN.finditer(question)]
    asked += [csc._WORD_VALUE[m.group(1).lower()] for m in _WORD_COUNT_BEFORE_NOUN.finditer(question)]
    return {n for n in asked if 1 < n <= available}


def verify_chat_reply(text: Any, context: dict, language: str, question: Optional[str] = None) -> dict:
    """{"passed", "level", "rejected_checks"}: C403 heuristic guard plus the contract checks.

    "format" (bullets, numbered lists) is presentation only: the chat may use them when asked,
    so it is not a rejection reason here (it stays one for the automatic comment).
    """
    ok, reasons = csc.validate_session_comment(text, context, language)
    rejected = set(reasons) - {"format"}
    if isinstance(text, str) and text.strip():
        rejected |= check_contract_claims(text.strip(), context, question)
    return {"passed": not rejected, "level": LEVEL, "rejected_checks": sorted(rejected)}


# ------------------------------------------------------------------ factual fallback

def _num(value: float, language: str) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))
    return text.replace(".", ",") if language in {"fr", "es"} else text


def _day(value: Any, language: str) -> str:
    parsed = csc._parse_date(value)
    if parsed is None:
        return str(value)
    return parsed.strftime("%d/%m/%Y") if language in {"fr", "es"} else parsed.isoformat()


_FALLBACK = {
    "fr": {
        "measured": "Cette séance en chiffres : {parts}.",
        "efforts": "Allures des répétitions enregistrées : {paces}.",
        "position": {"low": "dans la partie basse", "intermediate": "dans la zone intermédiaire",
                     "high": "dans la partie haute"},
        "relative": "Ta FC moyenne se situe {position} de tes {count} séances de référence (même environnement, "
                    "durée comparable, hors fractionné et compétition) : c'est une position relative dans ton "
                    "historique, pas une zone physiologique.",
        "similar": "Par rapport à tes {count} sorties précédentes de distance similaire, ton allure est de "
                   "{delta} s/km {direction}.",
        "pace_at_hr": "À FC comparable, ton allure est de {delta} s/km {direction} que sur {count} séances "
                      "antérieures.",
        "hr_at_pace": "À allure comparable, ta FC moyenne est de {delta} bpm {direction} que sur {count} séances "
                      "antérieures.",
        "slower": "plus lente", "faster": "plus rapide", "slower_than": "plus lente", "faster_than": "plus rapide",
        "higher": "plus élevée", "lower": "plus faible",
        "before": "Une prescription du jour ({kind}) avait été enregistrée avant la séance ; son respect n'est pas établi.",
        "after": "Une prescription du jour ({kind}) n'a été enregistrée qu'après la séance : ce n'est pas une "
                 "intention connue avant le départ.",
        "unknown": "Une prescription du jour ({kind}) existe, mais l'heure de son enregistrement est inconnue.",
        "limits": {
            "physiological_intensity_undetermined": "L'intensité physiologique ne peut pas être déterminée "
                                                    "(aucun seuil personnel enregistré).",
            "progress_not_demonstrated": "Aucune progression n'est établie.",
            "recovery_not_measured": "La récupération n'est pas mesurée.",
        },
        "thresholds": "Selon tes seuils enregistrés, la FC moyenne se situe {position}.",
        "threshold_position": {"below_LT1": "sous LT1", "between_LT1_LT2": "entre LT1 et LT2",
                               "above_LT2": "au-dessus de LT2"},
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "FC moyenne {v} bpm",
                  "avg_pace": "allure moyenne {v}", "elevation_gain_m": "{v} m de dénivelé positif"},
    },
    "en": {
        "measured": "This session in numbers: {parts}.",
        "efforts": "Recorded repetition paces: {paces}.",
        "position": {"low": "in the lower part", "intermediate": "in the intermediate range",
                     "high": "in the upper part"},
        "relative": "Your average HR sits {position} of your {count} reference sessions (same environment, "
                    "comparable duration, excluding intervals and races): it is a relative position in your own "
                    "history, not a physiological zone.",
        "similar": "Compared with your {count} previous runs of similar distance, your pace is {delta} s/km "
                   "{direction}.",
        "pace_at_hr": "At comparable HR, your pace is {delta} s/km {direction} than over {count} earlier sessions.",
        "hr_at_pace": "At comparable pace, your average HR is {delta} bpm {direction} than over {count} earlier "
                      "sessions.",
        "slower": "slower", "faster": "faster", "slower_than": "slower", "faster_than": "faster",
        "higher": "higher", "lower": "lower",
        "before": "A prescription for the day ({kind}) was recorded before the session; whether it was followed "
                  "is not established.",
        "after": "A prescription for the day ({kind}) was only recorded after the session: it is not an intention "
                 "known before the start.",
        "unknown": "A prescription for the day ({kind}) exists, but the time it was recorded is unknown.",
        "limits": {
            "physiological_intensity_undetermined": "The physiological intensity cannot be determined "
                                                    "(no personal threshold recorded).",
            "progress_not_demonstrated": "No progress is established.",
            "recovery_not_measured": "Recovery is not measured.",
        },
        "thresholds": "According to your recorded thresholds, the average HR sits {position}.",
        "threshold_position": {"below_LT1": "below LT1", "between_LT1_LT2": "between LT1 and LT2",
                               "above_LT2": "above LT2"},
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "average HR {v} bpm",
                  "avg_pace": "average pace {v}", "elevation_gain_m": "{v} m of elevation gain"},
    },
    "es": {
        "measured": "Esta sesión en cifras: {parts}.",
        "efforts": "Ritmos de las repeticiones registradas: {paces}.",
        "position": {"low": "en la parte baja", "intermediate": "en la zona intermedia", "high": "en la parte alta"},
        "relative": "Tu FC media se sitúa {position} de tus {count} sesiones de referencia (mismo entorno, "
                    "duración comparable, sin series ni competición): es una posición relativa en tu historial, "
                    "no una zona fisiológica.",
        "similar": "Frente a tus {count} salidas anteriores de distancia similar, tu ritmo es {delta} s/km "
                   "{direction}.",
        "pace_at_hr": "Con FC comparable, tu ritmo es {delta} s/km {direction} que en {count} sesiones "
                      "anteriores.",
        "hr_at_pace": "Con ritmo comparable, tu FC media es {delta} bpm {direction} que en {count} sesiones "
                      "anteriores.",
        "slower": "más lento", "faster": "más rápido", "slower_than": "más lento", "faster_than": "más rápido",
        "higher": "más alta", "lower": "más baja",
        "before": "Se registró una prescripción del día ({kind}) antes de la sesión; no está establecido que se cumpliera.",
        "after": "La prescripción del día ({kind}) solo se registró después de la sesión: no es una intención "
                 "conocida antes de salir.",
        "unknown": "Existe una prescripción del día ({kind}), pero se desconoce cuándo se registró.",
        "limits": {
            "physiological_intensity_undetermined": "No se puede determinar la intensidad fisiológica "
                                                    "(ningún umbral personal registrado).",
            "progress_not_demonstrated": "No se establece ningún progreso.",
            "recovery_not_measured": "La recuperación no está medida.",
        },
        "thresholds": "Según tus umbrales registrados, la FC media se sitúa {position}.",
        "threshold_position": {"below_LT1": "por debajo de LT1", "between_LT1_LT2": "entre LT1 y LT2",
                               "above_LT2": "por encima de LT2"},
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "FC media {v} bpm",
                  "avg_pace": "ritmo medio {v}", "elevation_gain_m": "{v} m de desnivel positivo"},
    },
}

_DISPLAY_DELTA = re.compile(r"([+-]?)(\d+):(\d{2})(?:/km)?")
_LIMIT_PRIORITY = ("physiological_intensity_undetermined", "progress_not_demonstrated", "recovery_not_measured")
_PACE_RE = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])(?:\s*(?:min\s*)?/\s*km)?", re.I)
_FIGURE = re.compile(r"(?<![\w:])\d+(?:[.,]\d+)?")
_COMPARISON_PRIORITY = ("v3.pace_at_hr", "v2.similar_pace", "v3.hr_at_pace")
_MAX_COMPARISONS = 2


def _norm_pace(value: Any) -> Optional[str]:
    """"7:21", "7:21/km" and "7:21 min/km" are the same pace (min/km); anything else is not a pace."""
    match = _PACE_RE.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"{int(match.group(1))}:{match.group(2)}" if match else None


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float("inf"):
        return None
    return float(value)


def _display_seconds(display: Any) -> Optional[int]:
    """Signed s/km from a V2 "+m:ss/km" delta (current minus reference: positive = slower)."""
    match = _DISPLAY_DELTA.fullmatch(display.strip()) if isinstance(display, str) else None
    if not match:
        return None
    seconds = int(match.group(2)) * 60 + int(match.group(3))
    return -seconds if match.group(1) == "-" else seconds


def _facts(context: dict) -> dict:
    """The facts a reply may state, keyed by logical id with their value, unit and population."""
    frame = context.get("session_coaching_frame") if isinstance(context.get("session_coaching_frame"), dict) else {}
    contract = frame.get("evidence_contract") if isinstance(frame.get("evidence_contract"), dict) else {}
    measured = contract.get("measured_facts") or {}
    c = _contract(context)
    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    facts: dict[str, Any] = {
        "session.distance": _finite(measured.get("distance_km")),
        "session.duration": _finite(measured.get("duration_minutes")),
        "session.avg_hr": _finite(measured.get("avg_hr_bpm")),
        "session.avg_pace": _norm_pace(measured.get("avg_pace")),
        "session.effort_paces": {p for p in (_norm_pace(e.get("value")) for e in
                                             measured.get("recorded_effort_paces") or []
                                             if isinstance(e, dict)) if p},
        "relative_hr.population": next(iter(c["by_metric"]["hr_position"]), None)
        if len(c["by_metric"]["hr_position"]) == 1 else None,
        "history.population": c["by_metric"]["history_list"],
        "profile.population": c["by_metric"]["profile"],
    }
    entries = {e.get("metric"): e for e in contract.get("validated_comparisons") or [] if isinstance(e, dict)}
    similar = entries.get("pace_and_hr_vs_similar_distance_sessions")
    permitted = (context.get("selected_workout_permissions") or {}).get("similar_comparison_available")
    pace_n, delta = (_finite(similar.get("pace_sample_count")), _display_seconds(similar.get("pace_difference_display"))) \
        if similar and permitted else (None, None)
    # Without its own pace population the delta is attributed to nothing.
    if pace_n and pace_n > 0 and delta:
        facts["v2.similar_pace.population"], facts["v2.similar_pace.delta"] = int(pace_n), delta
    effort = entries.get("pace_and_hr_at_comparable_effort")
    if effort:
        values = effort.get("values") or {}
        sub = ((v3.get("historical_comparison") or {}).get("provenance") or {}).get("sub_populations") or {}
        for key, name, field in (("v3.pace_at_hr", "pace_at_comparable_hr", "pace_difference_at_comparable_hr"),
                                 ("v3.hr_at_pace", "hr_at_comparable_pace", "hr_difference_at_comparable_pace")):
            n = _finite((sub.get(name) or {}).get("activity_count"))
            delta_value = _finite((values.get(field) or {}).get("value"))
            if n and n > 0 and delta_value is not None and round(abs(delta_value), 1) != 0:
                facts[f"{key}.population"], facts[f"{key}.delta"] = int(n), delta_value
    return facts


_SLOWER = re.compile(r"(lent|slower|m[áa]s lent)", re.I)
_FASTER = re.compile(r"(rapide|faster|r[áa]pid|quicker)", re.I)
_HIGHER = re.compile(r"([ée]lev[ée]|haute|higher|alta|sup[ée]rieure?)", re.I)
_LOWER = re.compile(r"(faible|basse|lower|baja|inf[ée]rieure?)", re.I)
_UNIT_AFTER = re.compile(
    r"^\s*(?:(km/h|%|min\s*/\s*km)|(km)\b|(min(?:utes?)?)\b|(bpm)\b|(s\s*/\s*km|secs?|sec(?:ond(?:e|s|es)?)?)\b)",
    re.I)
_COUNT_AFTER = re.compile(rf"^\s+(?:\w+\s+){{0,2}}?{_SESSION_NOUN}\b", re.I)


def _direction_ok(sentence: str, signed: float, up: re.Pattern, down: re.Pattern) -> bool:
    has_up, has_down = bool(up.search(sentence)), bool(down.search(sentence))
    if has_up and has_down:
        return False
    return not ((has_up and signed < 0) or (has_down and signed > 0))


def _direction_contradicted(sentence: str, facts: dict) -> bool:
    """A comparison delta quoted with the wrong direction (slower/faster, higher/lower)."""
    for key, cue, up, down in (("v3.pace_at_hr.delta", _AT_COMPARABLE_HR, _SLOWER, _FASTER),
                               ("v2.similar_pace.delta", _SAME_DISTANCE, _SLOWER, _FASTER),
                               ("v3.hr_at_pace.delta", _AT_COMPARABLE_PACE, _HIGHER, _LOWER)):
        delta = facts.get(key)
        if delta is None or not cue.search(sentence):
            continue
        quoted = [float(m.group(0).replace(",", ".")) for m in _FIGURE.finditer(_PACE_RE.sub(" ", sentence))]
        if any(abs(v - abs(delta)) <= 0.051 for v in quoted) and not _direction_ok(sentence, delta, up, down):
            return True
    return False


def _attribute(sentence: str, facts: dict) -> Optional[set[str]]:
    """Logical ids of the facts a sentence states, or None when any figure cannot be tied to one.

    A figure is matched by unit, value AND population cue ("similar distance", "comparable HR",
    HR position…). A number that exists elsewhere in the contract under another metric,
    unit or population never matches.
    """
    ids: set[str] = set()
    text = sentence
    for match in list(_PACE_RE.finditer(sentence)):
        pace = f"{int(match.group(1))}:{match.group(2)}"
        if pace == facts["session.avg_pace"]:
            ids.add("session.avg_pace")
        elif pace in facts["session.effort_paces"]:
            ids.add("session.effort_pace")
        else:
            return None
    text = _PACE_RE.sub(" ", sentence)
    at_hr, at_pace = bool(_AT_COMPARABLE_HR.search(text)), bool(_AT_COMPARABLE_PACE.search(text))
    same_distance = bool(_SAME_DISTANCE.search(text))
    hr_position = bool(_HR_WORD.search(text) and (_HR_POSITION.search(text) or _POS_LOW.search(text)
                                                  or _POS_HIGH.search(text)))
    figures = [(float(m.group(0).replace(",", ".")), text[m.end():m.end() + 40]) for m in _FIGURE.finditer(text)]
    words = [(float(csc._WORD_VALUE[m.group(1).lower()]), text[m.end(1):]) for m in _WORD_COUNT_BEFORE_NOUN.finditer(text)
             if csc._WORD_VALUE[m.group(1).lower()] > 1]
    for value, tail in figures + words:
        unit = _UNIT_AFTER.match(tail)
        if unit:
            if unit.group(1):
                return None  # km/h, %, min/km: no such fact exists
            if unit.group(2):
                if facts["session.distance"] is None or abs(value - facts["session.distance"]) > 0.051:
                    return None
                ids.add("session.distance")
            elif unit.group(3):
                if facts["session.duration"] is None or abs(value - facts["session.duration"]) > 0.51:
                    return None
                ids.add("session.duration")
            elif unit.group(4):
                hit = facts["session.avg_hr"] is not None and abs(value - facts["session.avg_hr"]) <= 0.51
                diff = facts.get("v3.hr_at_pace.delta")
                if hit:
                    ids.add("session.avg_hr")
                elif at_pace and diff is not None and abs(value - abs(diff)) <= 0.051:
                    if not _direction_ok(text, diff, _HIGHER, _LOWER):
                        return None
                    ids.add("v3.hr_at_pace.delta")
                else:
                    return None
            else:
                matched = False
                for key, cue in (("v3.pace_at_hr", at_hr), ("v2.similar_pace", same_distance)):
                    delta = facts.get(f"{key}.delta")
                    if cue and delta is not None and abs(value - abs(delta)) <= 0.51:
                        if not _direction_ok(text, delta, _SLOWER, _FASTER):
                            return None
                        ids.add(f"{key}.delta")
                        matched = True
                if not matched:
                    return None
            continue
        if not _COUNT_AFTER.match(tail):
            return None
        counted = False
        if hr_position:
            candidates = [("relative_hr.population", {facts["relative_hr.population"]})]
        else:
            candidates = [(key, {facts.get(key)}) for key, cue in (
                ("v3.pace_at_hr.population", at_hr), ("v3.hr_at_pace.population", at_pace),
                ("v2.similar_pace.population", same_distance and not (at_hr or at_pace))) if cue]
            if not candidates and _HISTORY_LIST.search(text):
                candidates = [("history.population", facts["history.population"])]
        for key, allowed in candidates:
            if any(a is not None and abs(value - a) < 0.5 for a in allowed):
                ids.add(key)
                counted = True
        if not counted:
            return None
    return ids or None


def _fallback_items(context: dict, language: str, covered: frozenset = frozenset()) -> list[tuple[set[str], str]]:
    """Ordered (fact ids, sentence) from the evidence contract, minus facts already stated (`covered`)."""
    texts = _FALLBACK.get(language, _FALLBACK["en"])
    frame = context.get("session_coaching_frame")
    contract = (frame or {}).get("evidence_contract") if isinstance(frame, dict) else None
    if not isinstance(contract, dict):
        return []
    facts = _facts(context)
    items: list[tuple[set[str], str]] = []
    parts = []
    for fact_id, unit_key in (("session.distance", "distance_km"), ("session.duration", "duration_minutes"),
                              ("session.avg_pace", "avg_pace"), ("session.avg_hr", "avg_hr_bpm")):
        value = facts.get(fact_id)
        if value is None or fact_id in covered:
            continue
        shown = f"{value}/km" if fact_id == "session.avg_pace" else _num(value, language)
        parts.append(texts["units"][unit_key].format(v=shown))
    if parts:
        items.append(({"session.measures"}, texts["measured"].format(parts=", ".join(parts))))
    paces = [e["value"] for e in (contract.get("measured_facts") or {}).get("recorded_effort_paces") or []
             if isinstance(e, dict) and _norm_pace(e.get("value")) and "session.effort_pace" not in covered]
    if paces:
        items.append(({"session.effort_pace"}, texts["efforts"].format(paces=", ".join(paces))))
    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    relative = (v3.get("classification") or {}).get("relative_effort") or {}
    pop = facts["relative_hr.population"]
    if relative.get("status") == "used" and relative.get("relative_position") in texts["position"] and pop \
            and "relative_hr.population" not in covered:
        items.append(({"relative_hr.population"}, texts["relative"].format(
            position=texts["position"][relative["relative_position"]], count=pop)))

    already = sum(1 for key in _COMPARISON_PRIORITY if f"{key}.delta" in covered)
    for key in _COMPARISON_PRIORITY:
        if already >= _MAX_COMPARISONS:
            break
        pop, delta = facts.get(f"{key}.population"), facts.get(f"{key}.delta")
        if pop is None or delta is None or f"{key}.delta" in covered:
            continue
        words = {"v3.pace_at_hr": ("pace_at_hr", "slower_than", "faster_than"),
                 "v2.similar_pace": ("similar", "slower", "faster"),
                 "v3.hr_at_pace": ("hr_at_pace", "higher", "lower")}[key]
        signed = _signed_delta(delta, words[1], words[2], texts, language)
        if signed:
            items.append(({f"{key}.population", f"{key}.delta"}, texts[words[0]].format(
                count=pop, delta=signed[0], direction=signed[1])))
            already += 1

    recorded = (frame.get("session_intent") or {}).get("recorded_historical_prescription")
    if isinstance(recorded, dict):
        timing = {"recorded_before_session": "before", "recorded_after_session": "after"}.get(
            recorded.get("recording_timing"), "unknown")
        items.append(({"prescription"}, texts[timing].format(kind=recorded.get("prescribed_workout_type") or "?")))
    intensity = v3.get("intensity") or {}
    if intensity.get("thresholds_available") and intensity.get("position_vs_declared_thresholds") in \
            texts["threshold_position"]:
        items.append(({"thresholds"}, texts["thresholds"].format(
            position=texts["threshold_position"][intensity["position_vs_declared_thresholds"]])))
    return items


def _signed_delta(value: Any, positive: str, negative: str, texts: dict, language: str) -> Optional[tuple[str, str]]:
    value = _finite(value)
    if value is None or round(abs(value), 1) == 0:
        return None
    return _num(round(abs(value), 1), language), texts[positive if value > 0 else negative]


def _fallback_limit(contract: dict, language: str) -> Optional[str]:
    """The single most important limit the contract itself declares; nothing is asserted otherwise."""
    texts = _FALLBACK.get(language, _FALLBACK["en"])
    declared = contract.get("not_demonstrated") or {}
    for key in _LIMIT_PRIORITY:
        if key in declared:
            return texts["limits"][key]
    return None


def build_contract_fallback(context: dict, language: str) -> Optional[str]:
    """Factual, useful reply built only from the evidence contract; None when it holds nothing."""
    items = _fallback_items(context, language)
    if not items:
        return None
    limit = _fallback_limit(context["session_coaching_frame"]["evidence_contract"], language)
    return " ".join([text for _, text in items] + ([limit] if limit else []))


# ------------------------------------------------------------------ partial validation (C408-D)

# A sentence that leans on its neighbours (pronoun, connector) or that states an inference
# cannot be judged on its own: it never survives a partial repair.
_DEPENDENT_START = re.compile(
    r"^\W*(?:ce|cela|ça|c'est|ceci|il|elle|ils|elles|mais|donc|ainsi|et|or|car|du coup|en revanche|en effet|"
    r"par conséquent|d'où|dans ce cas|this|that|these|those|it|they|but|so|therefore|thus|and|however|also|"
    r"hence|as a result|in that case|esto|eso|ello|pero|así|por lo tanto|y|además|en ese caso)\b", re.I)
_SESSION_SUBJECT = re.compile(
    rf"^\W*(?:cette|this|esta|ces|these)\s+(?:\w+\s+)?{_SESSION_NOUN}\b", re.I)
_INFERENCE = re.compile(
    r"(ce qui|c'est (?:le )?signe|signe d|which|suggest|sugg[èe]re|indique|indicates?|shows? that|montre que|"
    r"confirm|prouve|prove|means|signifie|implies|implique|because|parce que|puisque|\bcar\b|\bdonc\b|"
    r"therefore|so that|reflet|reflects?|traduit|t[ée]moigne|demuestra|sugiere|\bindica\b|significa|"
    r"confirma|porque|por lo tanto|lo que)", re.I)


def _sentence_reasons(sentence: str, context: dict, language: str, question: Optional[str]) -> set[str]:
    _, local = csc.validate_session_comment(sentence, context, language)
    return (set(local) - {"format", "length", "language"}) | check_contract_claims(sentence, context, question)


def resolve_chat_reply(text: Any, context: dict, language: str, question: Optional[str] = None) -> dict:
    """One deterministic pass, no second LLM call.

    Returns {"passed", "level", "rejected_checks", "text", "response_source", "removed_sentences"}.
    A reply that passes is returned unchanged. A rejected one is repaired only when every
    rejection is attributable to whole sentences and each kept sentence is positively proven:
    guard-clean, no dependency, no inference, and every figure tied by unit, value and
    population to one logical fact of the contract. The facts of removed sentences come back
    from the contract (never re-stated when a kept sentence already carries them). Anything
    else gets the full contract fallback. No words are ever cut out of a sentence.
    """
    verdict = verify_chat_reply(text, context, language, question)
    result = {**verdict, "text": text, "response_source": "llm_reply_checked", "removed_sentences": 0}
    if verdict["passed"]:
        return result
    result["text"], result["response_source"] = None, "contract_fallback"
    fallback = build_contract_fallback(context, language)
    full_text = text.strip() if isinstance(text, str) else ""
    sentences = csc._sentences(full_text)
    if not sentences or fallback is None:
        result["text"] = fallback
        return result

    attributed: set[str] = set()
    kept: list[str] = []
    covered: set[str] = set()
    facts = _facts(context)
    for sentence in sentences:
        reasons = _sentence_reasons(sentence, context, language, question)
        attributed |= reasons
        if reasons:
            continue
        if _DEPENDENT_START.search(sentence) and not _SESSION_SUBJECT.search(sentence):
            continue
        if _INFERENCE.search(sentence):
            continue
        ids = _attribute(sentence, facts)
        if not ids:
            continue
        kept.append(sentence)
        covered |= ids
    result["removed_sentences"] = len(sentences) - len(kept)
    if not set(verdict["rejected_checks"]) <= attributed or not kept:
        result["text"] = fallback
        return result

    restored = [t for _, t in _fallback_items(context, language, frozenset(covered))]
    limit = _fallback_limit(context["session_coaching_frame"]["evidence_contract"], language)
    candidate = " ".join(restored + kept + ([limit] if limit else []))
    if not verify_chat_reply(candidate, context, language, question)["passed"]:
        result["text"] = fallback
        return result
    result["text"], result["response_source"] = candidate, "llm_reply_partially_validated"
    return result
