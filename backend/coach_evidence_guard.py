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
    r"(m[êe]me distance|distances? (?:similaires?|comparables?|identiques?|proche)|same distance|"
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


def _contract(context: dict) -> dict:
    """What the contract says about populations and prescription, read from the chat context."""
    frame = context.get("session_coaching_frame") if isinstance(context.get("session_coaching_frame"), dict) else {}
    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    relative = ((v3.get("classification") or {}).get("relative_effort")) or {}
    comparison = v3.get("historical_comparison") or {}
    history = context.get("history_as_of_session") or {}
    profile = (context.get("runner_profile") or {}).get("observed_training") or {}
    contract = frame.get("evidence_contract") or {}
    similar_count = next(
        (c.get("activity_count") for c in contract.get("validated_comparisons") or []
         if c.get("metric") == "pace_and_hr_vs_similar_distance_sessions"), None)
    sub = ((comparison.get("provenance") or {}).get("sub_populations")) or {}
    v3_counts = _int_set(
        relative.get("reference_count") if relative.get("status") == "used" else None,
        comparison.get("reference_count"),
        *(block.get("activity_count") for block in sub.values() if isinstance(block, dict)),
    )
    recorded = (frame.get("session_intent") or {}).get("recorded_historical_prescription")
    return {
        "allowed_counts": v3_counts | _int_set(
            history.get("included_count"), history.get("eligible_count"),
            profile.get("sessions_count"), profile.get("sessions_with_distance_count"), similar_count, 1),
        "v3_counts": v3_counts,
        "similar_counts": _int_set(similar_count),
        "shown_count": history.get("included_count"),
        "population_count": profile.get("sessions_count"),
        "has_profile_stat": bool(profile),
        "recorded": recorded if isinstance(recorded, dict) else None,
        "has_not_demonstrated": set(contract.get("not_demonstrated") or {}),
    }


def check_contract_claims(text: str, context: dict) -> set[str]:
    """Contract-based reasons for rejecting a reply; empty when no checked claim is contradicted."""
    c = _contract(context)
    reasons: set[str] = set()
    recorded = c["recorded"]
    status = (recorded or {}).get("assessment_status")
    for sentence in csc._sentences(text):
        counts: list[int] = [int(m.group(1)) for m in _COUNT_BEFORE_NOUN.finditer(sentence)]
        counts += [csc._WORD_VALUE[m.group(1).lower()] for m in _WORD_COUNT_BEFORE_NOUN.finditer(sentence)]
        counts = [n for n in counts if n > 1]
        for n in counts:
            if n not in c["allowed_counts"]:
                reasons.add("ungrounded_population_count")
        if _SAME_DISTANCE.search(sentence) and not csc._only_negated(sentence, _SAME_DISTANCE):
            by_count = any(n in c["v3_counts"] and n not in c["similar_counts"] for n in counts)
            if _HR_POSITION.search(sentence) or by_count:
                reasons.add("population_misdescribed")
        if (c["has_profile_stat"] and _AVERAGE_WORDING.search(sentence)
                and c["shown_count"] and c["population_count"] and c["shown_count"] != c["population_count"]
                and c["shown_count"] in counts and c["population_count"] not in counts):
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


def verify_chat_reply(text: Any, context: dict, language: str) -> dict:
    """{"passed", "level", "rejected_checks"}: C403 heuristic guard plus the contract checks."""
    ok, reasons = csc.validate_session_comment(text, context, language)
    rejected = set(reasons)
    if isinstance(text, str) and text.strip():
        rejected |= check_contract_claims(text.strip(), context)
    return {"passed": not rejected, "level": LEVEL, "rejected_checks": sorted(rejected)}


# ------------------------------------------------------------------ factual fallback

def _num(value: float, language: str) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))
    return text.replace(".", ",") if language in {"fr", "es"} else text


def _day(value: Any, language: str) -> str:
    parsed = csc._parse_date(value)
    if parsed is None:
        return str(value)
    return parsed.strftime("%d/%m/%Y") if language in {"fr", "es"} else parsed.isoformat()


_FALLBACK = {
    "fr": {
        "measured": "Voici ce que montrent les données de cette séance : {parts}.",
        "efforts": "Allures des répétitions enregistrées : {paces}.",
        "position": {"low": "dans la partie basse", "intermediate": "dans la zone intermédiaire",
                     "high": "dans la partie haute"},
        "relative": "Votre FC moyenne se situe {position} de vos {count} séances de référence ({start} au {end}), "
                    "retenues selon les critères du moteur (même environnement, durée comparable, hors fractionné "
                    "et compétition ; la distance n'est pas un critère). C'est une position relative dans votre "
                    "historique, pas une zone physiologique.",
        "before": "Une prescription du jour ({kind}) avait été enregistrée avant la séance ; son respect n'est pas établi.",
        "after": "Une prescription du jour ({kind}) n'a été enregistrée qu'après la séance : ce n'est pas une "
                 "intention connue avant le départ.",
        "unknown": "Une prescription du jour ({kind}) existe, mais l'heure de son enregistrement est inconnue.",
        "limit": "Ces données ne permettent pas de déterminer l'intensité physiologique ni une "
                 "progression ; la récupération n'est pas mesurée.",
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "FC moyenne {v} bpm",
                  "avg_pace": "allure moyenne {v}", "elevation_gain_m": "{v} m de dénivelé positif"},
    },
    "en": {
        "measured": "Here is what the data of this session show: {parts}.",
        "efforts": "Recorded repetition paces: {paces}.",
        "position": {"low": "in the lower part", "intermediate": "in the intermediate range",
                     "high": "in the upper part"},
        "relative": "Your average HR sits {position} of your {count} reference sessions ({start} to {end}), "
                    "selected by the engine's criteria (same environment, comparable duration, excluding intervals "
                    "and races; distance is not a criterion). It is a relative position in your own history, not "
                    "a physiological zone.",
        "before": "A prescription for the day ({kind}) was recorded before the session; whether it was followed "
                  "is not established.",
        "after": "A prescription for the day ({kind}) was only recorded after the session: it is not an intention "
                 "known before the start.",
        "unknown": "A prescription for the day ({kind}) exists, but the time it was recorded is unknown.",
        "limit": "These data cannot establish the physiological intensity, a need for recovery or progress.",
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "average HR {v} bpm",
                  "avg_pace": "average pace {v}", "elevation_gain_m": "{v} m of elevation gain"},
    },
    "es": {
        "measured": "Esto es lo que muestran los datos de esta sesión: {parts}.",
        "efforts": "Ritmos de las repeticiones registradas: {paces}.",
        "position": {"low": "en la parte baja", "intermediate": "en la zona intermedia", "high": "en la parte alta"},
        "relative": "Tu FC media se sitúa {position} de tus {count} sesiones de referencia ({start} a {end}), "
                    "elegidas según los criterios del motor (mismo entorno, duración comparable, sin series ni "
                    "competición; la distancia no es un criterio). Es una posición relativa en tu historial, no "
                    "una zona fisiológica.",
        "before": "Se registró una prescripción del día ({kind}) antes de la sesión; no está establecido que se cumpliera.",
        "after": "La prescripción del día ({kind}) solo se registró después de la sesión: no es una intención "
                 "conocida antes de salir.",
        "unknown": "Existe una prescripción del día ({kind}), pero se desconoce cuándo se registró.",
        "limit": "Estos datos no permiten determinar la intensidad fisiológica, una necesidad de recuperación "
                 "ni un progreso.",
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "FC media {v} bpm",
                  "avg_pace": "ritmo medio {v}", "elevation_gain_m": "{v} m de desnivel positivo"},
    },
}


def build_contract_fallback(context: dict, language: str) -> Optional[str]:
    """Factual, useful reply built only from the evidence contract; None when it holds nothing."""
    texts = _FALLBACK.get(language, _FALLBACK["en"])
    frame = context.get("session_coaching_frame")
    contract = (frame or {}).get("evidence_contract") if isinstance(frame, dict) else None
    if not isinstance(contract, dict):
        return None
    measured = contract.get("measured_facts") or {}
    parts = []
    for key, template in texts["units"].items():
        value = measured.get(key)
        if isinstance(value, bool) or value is None:
            continue
        parts.append(template.format(v=_num(value, language) if isinstance(value, (int, float)) else value))
    sentences = []
    if parts:
        sentences.append(texts["measured"].format(parts=", ".join(parts)))
    paces = [e["value"] for e in measured.get("recorded_effort_paces") or [] if isinstance(e, dict) and e.get("value")]
    if paces:
        sentences.append(texts["efforts"].format(paces=", ".join(paces)))
    relative = (((frame.get("v3_assessment") or {}) if isinstance(frame.get("v3_assessment"), dict) else {})
                .get("classification") or {}).get("relative_effort") or {}
    provenance = relative.get("provenance") or {}
    if relative.get("status") == "used" and relative.get("relative_position") in texts["position"] \
            and provenance.get("activity_count"):
        sentences.append(texts["relative"].format(
            position=texts["position"][relative["relative_position"]], count=provenance["activity_count"],
            start=_day(provenance.get("period_start"), language), end=_day(provenance.get("period_end"), language)))
    recorded = (frame.get("session_intent") or {}).get("recorded_historical_prescription")
    if isinstance(recorded, dict):
        timing = {"recorded_before_session": "before", "recorded_after_session": "after"}.get(
            recorded.get("recording_timing"), "unknown")
        sentences.append(texts[timing].format(kind=recorded.get("prescribed_workout_type") or "?"))
    if not sentences:
        return None
    sentences.append(texts["limit"])
    return " ".join(sentences)
