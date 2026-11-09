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
import unicodedata
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
    r"distancias? (?:similar(?:es)?|comparables?)|de distance (?:similaire|comparable))", re.I)
_HR_POSITION = re.compile(
    r"(quartile|partie (?:basse|haute)|lower (?:part|end|quarter)|upper (?:part|end|quarter)|"
    r"parte (?:baja|alta)|m[ée]diane|median|mediana|position relative|relative position|"
    r"plus basse|plus haute|lowest|highest|partie interm[ée]diaire|intermediate (?:part|range)|"
    r"parte intermedia|niveau (?:interm[ée]diaire|moyen)|interm[ée]diaire|intermediate (?:level|position)|"
    r"mid(?:dle)?[- ](?:range|level)|nivel intermedio|posici[óo]n intermedia)", re.I)
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
                      r"plus basses?|lowest|bas(?:se)? de (?:votre|ton|ta|vos) |"
                      r"relativement (?:basse|faible)s?|relatively low|relativamente baja)", re.I)
_POS_HIGH = re.compile(r"(partie haute|zone haute|upper (?:part|end|range|quarter)|high end|parte alta|"
                       r"plus hautes?|highest|relativement (?:haute|[ée]lev[ée]e)s?|relatively high|"
                       r"relativamente alta)", re.I)
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


# --- durations (C408-F) -------------------------------------------------------------------------
_WORDS = "|".join(sorted(csc._WORD_VALUE, key=len, reverse=True))
_MULT_QUALIFIER = (
    r"plus (?:de |d['’]|du )|moins (?:de |d['’]|du )|au moins |environ |pr[èe]s de |presque |"
    r"more than |over |less than |fewer than |at least |about |around |roughly |almost |nearly |"
    r"m[áa]s (?:de |del )|menos (?:de |del )|al menos |alrededor de |casi |aproximadamente ")
_MULTIPLE = re.compile(
    rf"(?:(?P<q>{_MULT_QUALIFIER})\s*)?(?:(?P<n>\d+(?:[.,]\d+)?|{_WORDS})\s+(?:fois|times|veces)|"
    r"(?:(?:le|el)\s+)?(?P<dbl>double|doble)|(?P<tw>twice))(?![\w])", re.I)
_DURATION_NOUN = re.compile(r"\b(?:dur[ée]es?|durations?|duraci[óo]n(?:es)?|temps|tiempo)\b", re.I)
_DISTANCE_NOUN = re.compile(r"\b(?:distances?|distancia|kilom[èe]tres?|kilometers?|kil[óo]metros?|km|kms)\b", re.I)
_PACE_OR_HR_WORD = re.compile(
    r"\b(?:allures?|pace|ritmo|vitesse|speed|velocidad|FC|HR|fr[ée]quence|heart|cardi\w*|frecuencia|bpm)\b", re.I)
_METRIC_NOUN = re.compile(f"{_DURATION_NOUN.pattern}|{_DISTANCE_NOUN.pattern}|{_PACE_OR_HR_WORD.pattern}", re.I)
# "twice as long", "deux fois plus long(ue)": the adjective is a duration cue only right after the multiple.
_LENGTH_ADJECTIVE = re.compile(r"\s*(?:(?:as|plus|m[áa]s)\s+)?(?:long(?:ue)?s?|longer|larg[oa]s?)\b", re.I)
_MEAN_WORD = re.compile(r"\b(?:moyenn?e?s?|average|mean|media|medias|promedio|arithm\w+)\b", re.I)
# The reference V3 uses is the median of the athlete's own earlier sessions: only "usual"-type wording
# names it ("moyenne" / "average" would be another statistic).
_HABITUAL_REF = re.compile(
    r"(habituel\w*|d'habitude|usual\w*|typical\w*|habitual\w*|m[ée]diane|median|mediana)", re.I)
_RELATIVE_EASY = re.compile(r"\b(?:relativement|relatively|relativamente)\s+(?:facile|easy|f[áa]cil)\b", re.I)
_RELATIVE_FRAME = re.compile(
    r"(?:par rapport [àa] (?:tes|vos|ton|ta)|en comparaison (?:de|avec) (?:tes|ton|ta)|compared (?:to|with) your|"
    r"relative to your|respecto a (?:tus?)|en comparaci[óo]n con (?:tus?))\s+(?:\w+\s+){0,2}?"
    r"(?:habituel\w*|usual|typical|other|previous|own|pr[ée]c[ée]dent\w*|habitual\w*|anterior\w*|propi\w*|"
    r"s[ée]ances?|sorties?|efforts?|sessions?|runs?|workouts?|sesiones?|salidas?|esfuerzos?)", re.I)
# A position in the athlete's own history is never a zone, an endurance verdict or a recovery state.
_PHYSIO_READING = re.compile(
    r"\b(?:zones?|zona|endurance|resistencia|a[ée]rob\w*|r[ée]cup[ée]r\w*|recover\w*|recuper\w*)\b", re.I)
_NOT_A_ZONE = re.compile(
    r"\b(?:pas|not|no)\s+(?:une?|a|una|es una)\s+(?:(?:physiological|physiologique|fisiol[óo]gica)\s+)?"
    r"(?:zones?|zona)(?:\s+(?:physiologique|fisiol[óo]gica))?", re.I)
_DURATION_RATIO_METRIC = "session_duration_vs_habitual_median_duration"
_RATIO_EPS = 1e-9
_ALMOST_TOLERANCE = 0.25  # "presque / almost / casi N": N - 0.25 <= ratio < N


def _qualifier_kind(text: Optional[str]) -> str:
    q = (text or "").strip().lower()
    if not q:
        return "exact"
    if q.startswith(("presque", "près", "pres", "almost", "nearly", "casi")):
        return "almost"
    if q.startswith(("plus", "more", "over", "más", "mas")):
        return "more"
    if q.startswith(("moins", "less", "fewer", "menos")):
        return "less"
    if q.startswith(("au moins", "at least", "al menos")):
        return "least"
    return "about"


def _multiple_compatible(kind: str, value: float, decimals: int, ratio: float) -> bool:
    """A stated multiple is accepted only when it is a true statement about the V3 ratio."""
    if kind == "more":
        return ratio > value + _RATIO_EPS
    if kind == "less":
        return ratio < value - _RATIO_EPS
    if kind == "least":
        return ratio >= value - _RATIO_EPS
    if kind == "almost":  # just below the target: never at or above it
        return value - _ALMOST_TOLERANCE - _RATIO_EPS <= ratio < value - _RATIO_EPS
    if kind == "about":
        return abs(ratio - value) <= 0.5 + _RATIO_EPS  # rounding to the nearest whole multiple
    # Bare "N fois": the stated precision, never wider than 0.05 (so "deux fois" does not cover 2.18).
    return abs(ratio - value) <= (0.5 * 10 ** -decimals if decimals else 0.05) + 0.005 + _RATIO_EPS


def _multiple_metric(sentence: str, match: "re.Match", clause: str, clause_start: int) -> Optional[str]:
    """The metric a multiple ("deux fois …") qualifies: the nearest metric noun after it, else the one before.

    An unrelated cue elsewhere in the clause ("lors de cette longue sortie") never decides it.
    """
    def kind(noun: str) -> str:
        if _DURATION_NOUN.fullmatch(noun):
            return "duration"
        return "distance" if _DISTANCE_NOUN.fullmatch(noun) else "pace_or_hr"

    after = _METRIC_NOUN.search(clause, match.end() - clause_start)
    if _LENGTH_ADJECTIVE.match(clause, match.end() - clause_start) and not after:
        return "duration"
    if after:
        return kind(after.group(0))
    before = [m for m in _METRIC_NOUN.finditer(clause, 0, match.start() - clause_start)]
    return kind(before[-1].group(0)) if before else None


def _other_metric_multiples(sentence: str) -> bool:
    """True when a multiple is stated about a distance, a pace or an HR: V3 holds no such ratio."""
    breaks = [m.span() for m in csc._CLAUSE_BREAK.finditer(sentence)]
    for match in _MULTIPLE.finditer(sentence):
        start = max((e for _, e in breaks if e <= match.start()), default=0)
        end = min((b for b, _ in breaks if b >= match.end()), default=len(sentence))
        if _multiple_metric(sentence, match, sentence[start:end], start) in ("distance", "pace_or_hr"):
            return True
    return False


def _duration_claims(sentence: str, ratio_fact: Optional[dict]) -> list[tuple["re.Match", bool]]:
    """(match, supported) for every multiple stated about a DURATION ("plus de deux fois la durée habituelle").

    A multiple not about a duration (pace, HR, a number of sessions) is not considered here. A duration
    multiple is supported only by the V3 duration ratio: it never borrows a pace or HR figure, and it
    needs the habitual-duration reference and a statement compatible with the ratio.
    """
    claims = []
    breaks = [m.span() for m in csc._CLAUSE_BREAK.finditer(sentence)]
    for match in _MULTIPLE.finditer(sentence):
        start = max((e for _, e in breaks if e <= match.start()), default=0)
        end = min((b for b, _ in breaks if b >= match.end()), default=len(sentence))
        clause = sentence[start:end]
        if _multiple_metric(sentence, match, clause, start) != "duration":
            continue
        if match.group("n"):
            raw = match.group("n")
            value = float(raw.replace(",", ".")) if raw[0].isdigit() else float(csc._WORD_VALUE[raw.lower()])
            decimals = len(re.split(r"[.,]", raw)[1]) if raw[0].isdigit() and re.search(r"[.,]", raw) else 0
        else:
            value, decimals = 2.0, 0
        # the reference must be the habitual/median one, never an explicitly named mean
        ok = bool(ratio_fact) and _HABITUAL_REF.search(clause) and not _MEAN_WORD.search(clause) and \
            not _PACE_OR_HR_WORD.search(clause) and \
            _multiple_compatible(_qualifier_kind(match.group("q")), value, decimals, ratio_fact["ratio"])
        claims.append((match, bool(ok)))
    return claims


_HABITUAL_MINUTES = re.compile(
    rf"{_HABITUAL_REF.pattern}(?:\s+(?:de|d['’]|du|of|est|is|was|[ée]tait|fue|es|environ|about))*\s*"
    r"(?P<n>\d+(?:[.,]\d+)?)\s*min(?:ute?s?|utos?)?\b(?!\s*/)", re.I)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """The text with each (start, end) span replaced by as many spaces: every position stays valid."""
    for start, end in spans:
        text = text[:start] + " " * (end - start) + text[end:]
    return text


_STRUCTURE_UNIT = r"min(?:utes?|utos?)?|secs?|s|sec(?:ond(?:e|s|es|os)?)?"
_STRUCTURE_CLAIM = re.compile(
    r"(?<![\w:.,])(?P<n1>\d{1,2})\s*(?:[×xX*]|fois|times|veces)\s*(?P<d1>\d+(?:[.,]\d+)?)\s*"
    r"(?P<u1>" + _STRUCTURE_UNIT + r")\b|"
    r"(?<![\w:.,])(?P<n2>\d{1,2})\s+(?:r[ée]p[ée]titions?|repetitions?|repeticiones|efforts?|esfuerzos?|"
    r"intervalles?|intervals?|intervalos?|fractions?|s[ée]ries|reps)\s+(?:de|of|d['’])\s*(?P<d2>\d+(?:[.,]\d+)?)\s*"
    r"(?P<u2>" + _STRUCTURE_UNIT + r")\b", re.I)


def _structure_spans(sentence: str, structure: Optional[dict]) -> list[tuple[int, int]]:
    """Spans of "N × D min" wordings that match the recorded effort structure exactly; others stay visible."""
    if not structure:
        return []
    spans = []
    for m in _STRUCTURE_CLAIM.finditer(sentence):
        count = int(m.group("n1") or m.group("n2"))
        value = float((m.group("d1") or m.group("d2")).replace(",", "."))
        unit = (m.group("u1") or m.group("u2")).lower()
        seconds = value * (60 if unit.startswith("min") else 1)
        if count == structure["count"] and abs(seconds - structure["duration_s"]) <= max(3.0, 0.02 * seconds):
            spans.append(m.span())
    return spans


def _habitual_full_spans(sentence: str, ratio_fact: Optional[dict]) -> list[tuple[int, int]]:
    """Spans (figure + unit) of the minute figure worded as the V3 habitual (median) duration, only those.

    The figure must follow the median/habitual wording directly and equal the habitual duration of the
    V3 ratio: the session's own duration, a "moyenne" / "average", another value or another unit never
    match, even when they share the figure.
    """
    if not ratio_fact or _MEAN_WORD.search(sentence):
        return []
    return [m.span("n")[:1] + (m.end(),) for m in _HABITUAL_MINUTES.finditer(sentence)
            if abs(float(m.group("n").replace(",", ".")) - ratio_fact["habitual"]) <= 0.51]


def _duration_ratio_fact(contract: dict) -> Optional[dict]:
    """The V3 duration ratio, only when internally consistent and tied to this session's measured duration."""
    entry = next((e for e in contract.get("validated_comparisons") or []
                  if isinstance(e, dict) and e.get("metric") == _DURATION_RATIO_METRIC), None)
    if not entry:
        return None
    ratio, session, habitual = (_finite(entry.get(k)) for k in
                                ("ratio", "session_duration_minutes", "habitual_duration_minutes"))
    count = entry.get("reference_count")
    measured = _finite((contract.get("measured_facts") or {}).get("duration_minutes"))
    if not (ratio and session and habitual and measured and ratio > 0 and session > 0 and habitual > 0):
        return None
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        return None
    if abs(session - measured) > 0.51 or abs(ratio - session / habitual) > 0.011:
        return None
    return {"ratio": ratio, "count": count, "habitual": habitual}


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
    duration_ratio = _duration_ratio_fact(contract)
    classification = v3.get("classification") or {}
    provenance = relative.get("provenance") if isinstance(relative.get("provenance"), dict) else {}
    # V3 itself concludes "relatively easy compared with the athlete's usual efforts": an explicit
    # diagnosis, a personal-history decision tier, a low position and a sized, traceable population.
    # A bare HR position never reaches it.
    relative_easy = bool(
        relative_used and relative.get("relative_position") == "low"
        and classification.get("probable_type") == "easy_run_probable"
        and classification.get("decision_tier") == "individual_history"
        and any(isinstance(i, dict) and i.get("code") == "diagnosis.easy_run_relative"
                for i in contract.get("allowed_interpretations") or [])
        and isinstance(relative.get("reference_count"), int) and relative["reference_count"] > 0
        and provenance.get("activity_count") == relative["reference_count"])
    by_metric = {
        "hr_position": _int_set(relative.get("reference_count") if relative_used else None),
        "comparable_effort": _int_set(
            comparison.get("reference_count"),
            *(block.get("activity_count") for block in sub.values() if isinstance(block, dict))),
        "similar_distance": _int_set(similar_count, similar_entry.get("pace_sample_count")),
        "pace_at_hr": _int_set((sub.get("pace_at_comparable_hr") or {}).get("activity_count")),
        "hr_at_pace": _int_set((sub.get("hr_at_comparable_pace") or {}).get("activity_count")),
        "comparison_global": _int_set(comparison.get("reference_count")),
        "duration_habitual": _int_set((duration_ratio or {}).get("count")),
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
        "relative_easy": relative_easy,
        "duration_ratio": duration_ratio,
        "relative_position": relative.get("relative_position") if relative_used else None,
        "threshold_position": intensity.get("position_vs_declared_thresholds")
        if intensity.get("thresholds_available") else None,
        "recorded": recorded if isinstance(recorded, dict) else None,
        "has_not_demonstrated": set(contract.get("not_demonstrated") or {}),
        "type_certain_ok": classification.get("probable_type") == "intervals"
        and classification.get("confidence") == "high",
    }


def _allowed_counts(sentence: str, c: dict) -> set[int]:
    """Counts a sentence may cite, decided by the kind of population the sentence talks about."""
    by = c["by_metric"]
    if _duration_claims(sentence, c["duration_ratio"]) or _habitual_full_spans(sentence, c["duration_ratio"]):
        return by["duration_habitual"]  # a duration multiple may cite only the population of the V3 ratio
    if _RELATIVE_EASY.search(sentence) or (_HR_WORD.search(sentence) and (
            _HR_POSITION.search(sentence) or _POS_LOW.search(sentence) or _POS_HIGH.search(sentence))):
        return by["hr_position"]  # exclusive (also V3's relative-easy diagnosis: same relative-effort population): an HR position is about the relative-HR population only
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


_TYPE_TERM = (
    r"(?:sortie longue|footing|sortie facile|sortie tempo|s[ée]ance (?:de )?(?:tempo|seuil|fractionn[ée])|"
    r"fractionn[ée]|long run|easy run|tempo run|steady run|interval(?:s| session| workout)|"
    r"tirada larga|salida larga|rodaje|entrenamiento (?:de )?(?:series|intervalos))")
_CERTAIN_WORD = (
    r"(?:clairement|nettement|sans (?:aucun )?doute|[àa] coup s[ûu]r|certainement|d[ée]finitivement|"
    r"manifestement|[ée]videmment|incontestablement|sans [ée]quivoque|clearly|definitely|certainly|"
    r"undoubtedly|obviously|without (?:a )?doubt|unmistakabl[ey]|sin duda|claramente|definitivamente|"
    r"ciertamente|obviamente)")
_CATEGORICAL_TYPE = re.compile(
    rf"(?:{_CERTAIN_WORD}[^.!?;]{{0,40}}?\b{_TYPE_TERM}\b|\b{_TYPE_TERM}\b[^.!?;]{{0,30}}?{_CERTAIN_WORD}|"
    rf"(?:c['’]était|c['’]est|il s['’]agissait d['’]|il s['’]agit d['’]|it was|it is|it's|this was|this is|"
    rf"fue|era|es|se trata de|se trataba de)\s+(?:une?|a|an|una?)\s+{_TYPE_TERM}\b)", re.I)
_TYPE_HEDGE = re.compile(
    r"(probabl|likely|seems|semble|suggests?|plausible|parece|podr[ií]a|might|peut-[êe]tre|possibly|"
    r"appears|ressemble|looks like|compatible)", re.I)


_TYPE_TERM_RE = re.compile(rf"\b{_TYPE_TERM}\b", re.I)


# The HR position is measured against V3's own admitted population (strictly prior, same environment, comparable
# duration, no interval or race); it is not "the last N runs", "all your sessions" nor a same-distance population.
_HR_POPULATION_MISDESCRIBED = re.compile(
    r"(?:compar\w+|similaires?|similar|semejantes?)\s+(?:en|in|by|de|of)\s+(?:distance|distancia)|"
    r"m[êe]me distance|same[- ]distance|misma distancia|distance similaire|similar distance|distancia similar|"
    r"(?:s[ée]ances|sorties|runs|sessions|salidas|sesiones)\s+(?:habituelles|habituales|usual|regular|typical)\s+"
    r"(?:similaires|similar(?:es)?)|(?:similar|usual)\s+(?:and\s+)?(?:usual|similar)\s+(?:runs|sessions|workouts)|"
    r"(?:\d+|dix|vingt|trente|ten|twenty|thirty|diez|veinte|treinta)\s+(?:derni[èe]re?s?|r[ée]centes?|last|latest|"
    r"recent|[úu]ltim[ao]s|recientes)\s+(?:sorties|s[ée]ances|runs|sessions|salidas|sesiones)|"
    r"(?:derni[èe]re?s?|last|latest|[úu]ltim[ao]s)\s+\d+\s+(?:sorties|s[ée]ances|runs|sessions|salidas|sesiones)|"
    r"(?:toutes?\s+(?:tes|vos)|all\s+(?:of\s+)?your|todas\s+tus)\s+(?:sorties|s[ée]ances|runs|sessions|salidas|sesiones)",
    re.I)


_LOOSE_POSITION = re.compile(r"\b(?:basse|faible|haute|[ée]lev[ée]e|low|high|baja|alta|elevada)\b", re.I)


# A position sentence whose subject is a pronoun ("Elle est à un niveau intermédiaire parmi tes séances ...")
# still restates the HR position when it ranks the session inside a population.
_ELLIPTICAL_POSITION = re.compile(
    r"(?:partie (?:basse|haute|interm[ée]diaire)|niveau (?:interm[ée]diaire|moyen)|(?:lower|upper) part|"
    r"intermediate (?:part|range|level)|parte (?:baja|alta|intermedia)|nivel intermedio)", re.I)
_RANKED_IN_POPULATION = re.compile(
    r"\b(?:parmi|among|entre|de|of|in|dans|en)\s+(?:tes|vos|your|tus|les|the|las)\s+(?:\w+\s+){0,3}?"
    rf"{_SESSION_NOUN}\b", re.I)


def _states_hr_position(sentence: str) -> bool:
    if not _HR_WORD.search(sentence) and _ELLIPTICAL_POSITION.search(sentence) \
            and _RANKED_IN_POPULATION.search(sentence):
        return True
    return bool(_HR_WORD.search(sentence) and (_HR_POSITION.search(sentence) or _POS_LOW.search(sentence)
                or _POS_HIGH.search(sentence) or _LOOSE_POSITION.search(sentence)) and not _AT_COMPARABLE_HR.search(sentence)
                and not _AT_COMPARABLE_PACE.search(sentence))


_NEGATION = re.compile(r"\b(?:pas|not|no|never|jamais|nunca|nada)\b|n['’]t\b", re.I)


def _categorical_type_claim(sentence: str) -> bool:
    """A session type stated as certain: the V3 classification is probable, never certain."""
    matches = [m for m in _CATEGORICAL_TYPE.finditer(sentence) if not _NEGATION.search(m.group(0))]
    if not matches or csc._only_negated(sentence, _CATEGORICAL_TYPE):
        return False
    certain = [m for m in matches if re.search(_CERTAIN_WORD, m.group(0), re.I)]
    return bool(certain) or not _TYPE_HEDGE.search(sentence)


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
        if not c["type_certain_ok"] and _categorical_type_claim(sentence):
            reasons.add("type_certainty_not_established")
        if any(not ok for _, ok in _duration_claims(sentence, c["duration_ratio"])):
            reasons.add("duration_ratio_not_established")
        if _other_metric_multiples(sentence):
            reasons.add("multiple_not_established")
        if any(not ok for _, _, ok in _magnitude_claims(sentence, facts)):
            reasons.add("comparison_magnitude_not_established")
        if (_RELATIVE_EASY.search(sentence) or (_HR_WORD.search(sentence) and (
                _POS_LOW.search(sentence) or _POS_HIGH.search(sentence) or _HR_POSITION.search(sentence)))) \
                and _PHYSIO_READING.search(_NOT_A_ZONE.sub(" ", sentence)) \
                and not csc._only_negated(sentence, _PHYSIO_READING):
            reasons.add("relative_position_read_as_physiology")
        if _states_metric_figure(sentence) and _attribute(sentence, facts) is None and not (
                _requested_only(sentence, requested)):
            reasons.add("figure_not_attributed")
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
        if (_states_hr_position(sentence) or (_HR_WORD.search(sentence) and _LOOSE_POSITION.search(sentence))) \
                and _HR_POPULATION_MISDESCRIBED.search(sentence) \
                and not csc._only_negated(sentence, _HR_POPULATION_MISDESCRIBED):
            reasons.add("population_misdescribed")
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
        if recorded is not None and any(
                found != recorded.get("prescribed_workout_type") for _, found in _prescription_labels(sentence)):
            reasons.add("prescription_type_misstated")
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
    if sum(1 for sentence in csc._sentences(text) if _states_hr_position(sentence)) > 1:
        reasons.add("redundant_hr_position")
    return reasons


def _states_metric_figure(sentence: str) -> bool:
    """True when a sentence states a pace, a unit-bearing figure, a session count or a comparison figure."""
    if _PACE_RE.search(sentence):
        return True
    text = _PACE_RE.sub(" ", sentence)
    if csc._HM.search(text):
        return True
    cue = _AT_COMPARABLE_HR.search(text) or _AT_COMPARABLE_PACE.search(text) or _SAME_DISTANCE.search(text)
    for m in _FIGURE.finditer(text):
        tail = text[m.end():m.end() + 40]
        if cue or _UNIT_AFTER.match(tail) or _COUNT_AFTER.match(tail):
            return True
    return any(csc._WORD_VALUE[m.group(1).lower()] > 1 for m in _WORD_COUNT_BEFORE_NOUN.finditer(text))


def _requested_only(sentence: str, requested: set[int]) -> bool:
    """True when every figure is a session count the user asked for; any other figure (unit, pace, delta) disqualifies."""
    if _PACE_RE.search(sentence) or csc._HM.search(sentence):
        return False
    text = sentence
    counts = [int(m.group(1)) for m in _COUNT_BEFORE_NOUN.finditer(text)]
    counts += [csc._WORD_VALUE[m.group(1).lower()] for m in _WORD_COUNT_BEFORE_NOUN.finditer(text)]
    figures = [m for m in _FIGURE.finditer(text) if not _COUNT_AFTER.match(text[m.end():m.end() + 40])
               or _UNIT_AFTER.match(text[m.end():m.end() + 40])]
    return bool(counts) and not figures and all(n in requested for n in counts)


def _requested_counts(question: Optional[str], c: dict) -> set[int]:
    """List sizes the user asked for ("my last five sessions"): honoured only up to what is really available."""
    if not isinstance(question, str) or not question.strip():
        return set()
    available = c["shown_count"] if isinstance(c["shown_count"], int) else 0
    asked = [int(m.group(1)) for m in _COUNT_BEFORE_NOUN.finditer(question)]
    asked += [csc._WORD_VALUE[m.group(1).lower()] for m in _WORD_COUNT_BEFORE_NOUN.finditer(question)]
    return {n for n in asked if 1 < n <= available}


def _counts_in(sentence: str) -> set[int]:
    counts = {int(m.group(1)) for m in _COUNT_BEFORE_NOUN.finditer(sentence)}
    counts |= {csc._WORD_VALUE[m.group(1).lower()] for m in _WORD_COUNT_BEFORE_NOUN.finditer(sentence)}
    return {n for n in counts if n > 1}


def _csc_view(text: str, context: dict) -> str:
    """The text as the C403 heuristics read it.

    A duration multiple proven by the V3 ratio, and "relativement facile par rapport à tes efforts
    habituels" when V3 itself concludes it, are checked by this module; C403 would otherwise re-judge
    them as an unlabelled number or an intensity word. Everything else in the sentence is left intact.
    """
    c = _contract(context)
    facts = _facts(context)
    out = text
    for sentence in csc._sentences(text):
        claims = _duration_claims(sentence, c["duration_ratio"])
        habitual = _habitual_full_spans(sentence, c["duration_ratio"])
        masked = list(habitual)  # the habitual median, proven by the V3 ratio
        masked += [m.span() for m, _, ok in _magnitude_claims(sentence, facts) if ok]  # delta checked here
        masked += _prescription_label_spans(sentence, context)  # the recorded prescription's own label
        masked += _structure_spans(sentence, facts.get("session.effort_structure"))  # recorded "N × D min"
        view = _blank(sentence, masked)
        breaks = [m.span() for m in csc._CLAUSE_BREAK.finditer(sentence)]
        for match, ok in reversed(claims):
            if ok:  # the multiple and its own "habitual" reference, within its clause only
                end = min((b for b, _ in breaks if b >= match.end()), default=len(sentence))
                view = (view[:match.start()] + " " + _HABITUAL_REF.sub(" ", view[match.end():end]) + view[end:])
        if (claims or habitual) and all(ok for _, ok in claims):  # the population of the ratio, named by its own count
            population = c["by_metric"]["duration_habitual"]
            view = _COUNT_BEFORE_NOUN.sub(
                lambda m: m.group(0)[m.end(1) - m.start(0):] if int(m.group(1)) in population else m.group(0), view)
        if c["relative_easy"] and _RELATIVE_FRAME.search(sentence) and _counts_in(sentence) <= \
                c["by_metric"]["hr_position"]:
            view = _RELATIVE_EASY.sub("", view)
        if view != sentence:
            out = out.replace(sentence, view, 1)
    return out


def verify_chat_reply(text: Any, context: dict, language: str, question: Optional[str] = None) -> dict:
    """{"passed", "level", "rejected_checks"}: C403 heuristic guard plus the contract checks.

    "format" (bullets, numbered lists) is presentation only: the chat may use them when asked,
    so it is not a rejection reason here (it stays one for the automatic comment).
    """
    ok, reasons = csc.validate_session_comment(_csc_view(text, context) if isinstance(text, str) else text,
                                               context, language)
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
        "measure": {"distance": "Tu as couru {v} km", "duration_head": "Ta séance a duré {v}",
                    "duration": " en {v}", "pace_head": "Ton allure moyenne était de {v}", "pace": ", à {v}",
                    "hr_head": "Ta FC moyenne était de {v} bpm", "hr": ", avec une FC moyenne de {v} bpm",
                    "minutes": "{v} minutes"},
        "type": "Le moteur d'analyse classe cette séance comme probablement {kind} (confiance {conf}).",
        "type_kinds": {"easy_run_probable": "un footing facile", "steady_run_probable": "une sortie à allure régulière",
                       "tempo_probable": "un effort de type tempo", "long_run_probable": "une sortie longue"},
        "type_conf": {"high": "élevée", "medium": "moyenne", "low": "faible"},
        "structure": "Structure enregistrée : {n} × {d} (efforts enregistrés uniquement).",
        "efforts": "Allures des répétitions enregistrées : {paces}.",
        "position": {"low": "dans la partie basse", "intermediate": "dans la partie intermédiaire",
                     "high": "dans la partie haute"},
        "relative": "Ta FC moyenne se situe {position} de tes {count} séances de référence (même environnement, "
                    "durée comparable, hors fractionné et compétition) : c'est une position relative dans ton "
                    "historique, pas une zone physiologique.",
        "duration_ratio": "La durée de cette séance représente {ratio} fois ta durée habituelle (médiane de tes "
                          "{count} séances précédentes).",
        "similar": "Par rapport à tes {count} sorties précédentes de distance similaire, ton allure est de "
                   "{delta} s/km {direction}.",
        "pace_at_hr": "À FC comparable, ton allure est de {delta} s/km {direction} que sur {count} séances "
                      "antérieures.",
        "hr_at_pace": "À allure comparable, ta FC moyenne est de {delta} bpm {direction} que sur {count} séances "
                      "antérieures.",
        "slower": "plus lente", "faster": "plus rapide", "slower_than": "plus lente", "faster_than": "plus rapide",
        "higher": "plus élevée", "lower": "plus faible",
        "before": "Une prescription du jour{kind} avait été enregistrée avant la séance ; son respect n'est pas établi.",
        "after": "Une prescription du jour{kind} n'a été enregistrée qu'après la séance : ce n'est pas une "
                 "intention connue avant le départ.",
        "unknown": "Une prescription du jour{kind} existe, mais l'heure de son enregistrement est inconnue.",
        "unordered": "Une prescription du jour{kind} existe, mais on ne peut pas établir si elle a été enregistrée "
                     "avant ou après la séance.",
        "kinds": {"race": "compétition", "easy": "footing facile", "recovery": "récupération",
                  "long_easy": "sortie longue facile", "steady": "allure régulière",
                  "quality": "séance de qualité", "rest": "repos"},
        "limits": {
            "physiological_intensity_undetermined": "Sans seuil personnel enregistré, je ne peux pas déterminer "
                                                    "ton intensité physiologique.",
            "progress_not_demonstrated": "Aucune progression n'est établie.",
            "recovery_not_measured": "Ta récupération n'est pas mesurée dans ces données.",
        },
        "focus": {
            "ordinals": {1: "premier", 2: "deuxième", 3: "troisième", 4: "quatrième", 5: "cinquième", 6: "sixième"},
            "last": "dernier",
            "fastest": "Le {ord} effort était le plus rapide, à {pace}/km.",
            "slowest": "Le {ord} effort était le plus lent, à {pace}/km.",
            "plain": "Le {ord} effort était à {pace}/km.",
            "fastest_partial": "Le {ord} effort était le plus rapide parmi les répétitions dont l'allure est enregistrée, à {pace}/km.",
            "slowest_partial": "Le {ord} effort était le plus lent parmi les répétitions dont l'allure est enregistrée, à {pace}/km.",
            "unexplained": "Les données montrent son allure, mais ne suffisent pas à expliquer pourquoi elle diffère des autres.",
            "numbered": "L'effort n° {n} était à {pace}/km.",
            "missing": "Je n'ai pas l'allure enregistrée de cet effort.",
            "last_unknown": "Je ne sais pas combien d'efforts ont été enregistrés, donc je ne peux pas identifier le dernier.",
            "cause": "Les données montrent cette différence, mais pas sa cause certaine.",
            "single_faster": "Une seule répétition plus rapide ne suffit pas à démontrer une amélioration de ta forme.",
            "single": "Une seule répétition ne suffit pas à démontrer une amélioration de ta forme.",
        },

        "thresholds": "Selon tes seuils enregistrés, la FC moyenne se situe {position}.",
        "threshold_position": {"below_LT1": "sous LT1", "between_LT1_LT2": "entre LT1 et LT2",
                               "above_LT2": "au-dessus de LT2"},
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "FC moyenne {v} bpm",
                  "avg_pace": "allure moyenne {v}", "elevation_gain_m": "{v} m de dénivelé positif"},
    },
    "en": {
        "measure": {"distance": "You ran {v} km", "duration_head": "Your session lasted {v}",
                    "duration": " in {v}", "pace_head": "Your average pace was {v}", "pace": ", at {v}",
                    "hr_head": "Your average HR was {v} bpm", "hr": ", with an average HR of {v} bpm",
                    "minutes": "{v} minutes"},
        "type": "The analysis engine classes this session as probably {kind} (confidence: {conf}).",
        "type_kinds": {"easy_run_probable": "an easy run", "steady_run_probable": "a steady-pace run",
                       "tempo_probable": "a tempo-type effort", "long_run_probable": "a long run"},
        "type_conf": {"high": "high", "medium": "medium", "low": "low"},
        "structure": "Recorded structure: {n} × {d} (recorded efforts only).",
        "efforts": "Recorded repetition paces: {paces}.",
        "position": {"low": "in the lower part", "intermediate": "in the intermediate range",
                     "high": "in the upper part"},
        "relative": "Your average HR sits {position} of your {count} reference sessions (same environment, "
                    "comparable duration, excluding intervals and races): it is a relative position in your own "
                    "history, not a physiological zone.",
        "duration_ratio": "This session's duration is {ratio} times your usual duration (median of your {count} "
                          "earlier sessions).",
        "similar": "Compared with your {count} previous runs of similar distance, your pace is {delta} s/km "
                   "{direction}.",
        "pace_at_hr": "At comparable HR, your pace is {delta} s/km {direction} than over {count} earlier sessions.",
        "hr_at_pace": "At comparable pace, your average HR is {delta} bpm {direction} than over {count} earlier "
                      "sessions.",
        "slower": "slower", "faster": "faster", "slower_than": "slower", "faster_than": "faster",
        "higher": "higher", "lower": "lower",
        "before": "A prescription for the day{kind} was recorded before the session; whether it was followed "
                  "is not established.",
        "after": "A prescription for the day{kind} was only recorded after the session: it is not an intention "
                 "known before the start.",
        "unknown": "A prescription for the day{kind} exists, but the time it was recorded is unknown.",
        "unordered": "A prescription for the day{kind} exists, but it cannot be established whether it was "
                     "recorded before or after the session.",
        "kinds": {"race": "race", "easy": "easy run", "recovery": "recovery", "long_easy": "easy long run",
                  "steady": "steady run", "quality": "quality session", "rest": "rest"},
        "limits": {
            "physiological_intensity_undetermined": "Without a recorded personal threshold, I can't determine "
                                                    "your physiological intensity.",
            "progress_not_demonstrated": "No progress is established.",
            "recovery_not_measured": "Your recovery isn't measured in this data.",
        },
        "focus": {
            "ordinals": {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"},
            "last": "last",
            "fastest": "The {ord} effort was the fastest, at {pace}/km.",
            "slowest": "The {ord} effort was the slowest, at {pace}/km.",
            "plain": "The {ord} effort was at {pace}/km.",
            "fastest_partial": "The {ord} effort was the fastest among the repetitions with a recorded pace, at {pace}/km.",
            "slowest_partial": "The {ord} effort was the slowest among the repetitions with a recorded pace, at {pace}/km.",
            "unexplained": "The data shows its pace, but is not enough to explain why it differs from the others.",
            "numbered": "Effort no. {n} was at {pace}/km.",
            "missing": "I don't have the recorded pace of that effort.",
            "last_unknown": "I don't know how many efforts were recorded, so I can't identify the last one.",
            "cause": "The data shows this difference, but not its definite cause.",
            "single_faster": "A single faster repetition is not enough to show that your fitness has improved.",
            "single": "A single repetition is not enough to show that your fitness has improved.",
        },

        "thresholds": "According to your recorded thresholds, the average HR sits {position}.",
        "threshold_position": {"below_LT1": "below LT1", "between_LT1_LT2": "between LT1 and LT2",
                               "above_LT2": "above LT2"},
        "units": {"distance_km": "{v} km", "duration_minutes": "{v} min", "avg_hr_bpm": "average HR {v} bpm",
                  "avg_pace": "average pace {v}", "elevation_gain_m": "{v} m of elevation gain"},
    },
    "es": {
        "measure": {"distance": "Has corrido {v} km", "duration_head": "Tu sesión duró {v}",
                    "duration": " en {v}", "pace_head": "Tu ritmo medio fue de {v}", "pace": ", a {v}",
                    "hr_head": "Tu FC media fue de {v} bpm", "hr": ", con una FC media de {v} bpm",
                    "minutes": "{v} min"},
        "type": "El motor de análisis clasifica esta sesión como probablemente {kind} (confianza: {conf}).",
        "type_kinds": {"easy_run_probable": "un rodaje fácil", "steady_run_probable": "una salida a ritmo constante",
                       "tempo_probable": "un esfuerzo tipo tempo", "long_run_probable": "una tirada larga"},
        "type_conf": {"high": "alta", "medium": "media", "low": "baja"},
        "structure": "Estructura registrada: {n} × {d} (solo esfuerzos registrados).",
        "efforts": "Ritmos de las repeticiones registradas: {paces}.",
        "position": {"low": "en la parte baja", "intermediate": "en la parte intermedia", "high": "en la parte alta"},
        "relative": "Tu FC media se sitúa {position} de tus {count} sesiones de referencia (mismo entorno, "
                    "duración comparable, sin series ni competición): es una posición relativa en tu historial, "
                    "no una zona fisiológica.",
        "duration_ratio": "La duración de esta sesión es {ratio} veces tu duración habitual (mediana de tus "
                          "{count} sesiones anteriores).",
        "similar": "Frente a tus {count} salidas anteriores de distancia similar, tu ritmo es {delta} s/km "
                   "{direction}.",
        "pace_at_hr": "Con FC comparable, tu ritmo es {delta} s/km {direction} que en {count} sesiones "
                      "anteriores.",
        "hr_at_pace": "Con ritmo comparable, tu FC media es {delta} bpm {direction} que en {count} sesiones "
                      "anteriores.",
        "slower": "más lento", "faster": "más rápido", "slower_than": "más lento", "faster_than": "más rápido",
        "higher": "más alta", "lower": "más baja",
        "before": "Se registró una prescripción del día{kind} antes de la sesión; no está establecido que se cumpliera.",
        "after": "La prescripción del día{kind} solo se registró después de la sesión: no es una intención "
                 "conocida antes de salir.",
        "unknown": "Existe una prescripción del día{kind}, pero se desconoce cuándo se registró.",
        "unordered": "Existe una prescripción del día{kind}, pero no se puede establecer si se registró antes o "
                     "después de la sesión.",
        "kinds": {"race": "competición", "easy": "rodaje suave", "recovery": "recuperación",
                  "long_easy": "tirada larga suave", "steady": "ritmo constante",
                  "quality": "sesión de calidad", "rest": "descanso"},
        "limits": {
            "physiological_intensity_undetermined": "Sin un umbral personal registrado, no puedo determinar "
                                                    "tu intensidad fisiológica.",
            "progress_not_demonstrated": "No se establece ningún progreso.",
            "recovery_not_measured": "Tu recuperación no se mide en estos datos.",
        },
        "focus": {
            "ordinals": {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto", 6: "sexto"},
            "last": "último",
            "fastest": "El {ord} esfuerzo fue el más rápido, a {pace}/km.",
            "slowest": "El {ord} esfuerzo fue el más lento, a {pace}/km.",
            "plain": "El {ord} esfuerzo fue a {pace}/km.",
            "fastest_partial": "El {ord} esfuerzo fue el más rápido entre las repeticiones con ritmo registrado, a {pace}/km.",
            "slowest_partial": "El {ord} esfuerzo fue el más lento entre las repeticiones con ritmo registrado, a {pace}/km.",
            "unexplained": "Los datos muestran su ritmo, pero no bastan para explicar por qué difiere de los demás.",
            "numbered": "El esfuerzo n.º {n} fue a {pace}/km.",
            "missing": "No tengo el ritmo registrado de ese esfuerzo.",
            "last_unknown": "No sé cuántos esfuerzos se registraron, así que no puedo identificar el último.",
            "cause": "Los datos muestran esa diferencia, pero no su causa segura.",
            "single_faster": "Una sola repetición más rápida no basta para demostrar una mejora de tu forma.",
            "single": "Una sola repetición no basta para demostrar una mejora de tu forma.",
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


def _effort_structure_fact(value: Any) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    count, duration = value.get("effort_count"), _finite(value.get("effort_duration_s"))
    if isinstance(count, bool) or not isinstance(count, int) or count < 2 or not duration or duration <= 0:
        return None
    return {"count": count, "duration_s": duration}


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
        "session.effort_structure": _effort_structure_fact(measured.get("recorded_effort_structure")),
        "session.effort_paces": {p for p in (_norm_pace(e.get("value")) for e in
                                             measured.get("recorded_effort_paces") or []
                                             if isinstance(e, dict)) if p},
        "relative_hr.population": next(iter(c["by_metric"]["hr_position"]), None)
        if len(c["by_metric"]["hr_position"]) == 1 else None,
        "history.population": c["by_metric"]["history_list"],
        "profile.population": c["by_metric"]["profile"],
        "duration.ratio": c["duration_ratio"],
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
        quoted = [float(m.group(0).replace(",", ".")) for m in
                  _FIGURE.finditer(csc._HM.sub(" ", _PACE_RE.sub(" ", sentence)))]
        if any(abs(v - abs(delta)) <= 0.051 for v in quoted) and not _direction_ok(sentence, delta, up, down):
            return True
    return False


_MAG_NUMBER = {"un": 1, "une": 1, "a": 1, "an": 1, "one": 1, "uno": 1, "una": 1, "deux": 2, "two": 2,
               "dos": 2, "trois": 3, "three": 3, "tres": 3}
_MINUTE_MAGNITUDE = re.compile(
    r"(?:(?P<q>plus (?:de |d['’])|moins (?:de |d['’])|more than |over |less than |m[áa]s de |menos de |"
    r"environ |about |around |presque |almost |casi )\s*)?"
    r"\b(?P<n>\d+|" + "|".join(sorted(_MAG_NUMBER, key=len, reverse=True)) + r")\s+(?:minutes?|minutos?)\s*"
    r"(?:(?:par|per|por|au|al)\s+(?:km|kilom[èe]tre|kilometers?|kilometres?|kil[óo]metro)|/\s*km)", re.I)


def _magnitude_claims(sentence: str, facts: dict) -> list[tuple["re.Match", Optional[str], bool]]:
    """(match, comparison key, supported) for each "plus d'une minute par km" said about a pace comparison.

    Supported only when the sentence names exactly one comparison population (same distance or
    comparable HR), that comparison has a delta, the stated bound is true of it and the direction agrees.
    """
    claims = []
    for match in _MINUTE_MAGNITUDE.finditer(sentence):
        raw = match.group("n").lower()
        seconds = 60.0 * (int(raw) if raw.isdigit() else _MAG_NUMBER[raw])
        cues = [key for key, cue in (("v3.pace_at_hr", _AT_COMPARABLE_HR), ("v2.similar_pace", _SAME_DISTANCE))
                if cue.search(sentence)]
        key = cues[0] if len(cues) == 1 else None
        delta = facts.get(f"{key}.delta") if key else None
        ok = False
        if delta is not None:
            size, kind = abs(delta), _qualifier_kind(match.group("q"))
            ok = {"more": size > seconds, "less": size < seconds,
                  "almost": seconds - 10 <= size < seconds}.get(kind, abs(size - seconds) <= max(5.0, 0.1 * seconds))
            ok = ok and _direction_ok(sentence, delta, _SLOWER, _FASTER)
        claims.append((match, key if ok else None, ok))
    return claims


def _attribute(sentence: str, facts: dict) -> Optional[set[str]]:
    """Logical ids of the facts a sentence states, or None when any figure cannot be tied to one.

    A figure is matched by unit, value AND population cue ("similar distance", "comparable HR",
    HR position…). A number that exists elsewhere in the contract under another metric,
    unit or population never matches.
    """
    ids: set[str] = set()
    structure = _structure_spans(sentence, facts.get("session.effort_structure"))
    if structure:
        ids.add("session.effort_structure")
        sentence = _blank(sentence, structure)
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
    for match in csc._HM.finditer(text):  # "2h02", "2 h 2 min", "2 hours 2 minutes": one duration
        if facts["session.duration"] is None or abs(csc.hm_minutes(match) - facts["session.duration"]) > 0.51:
            return None
        ids.add("session.duration")
    text = csc._HM.sub(" ", text)
    duration_claims = _duration_claims(text, facts["duration.ratio"])
    if any(not ok for _, ok in duration_claims):
        return None
    if duration_claims:
        ids.add("duration.ratio")
        for match, _ in reversed(duration_claims):
            text = text[:match.start()] + " " + text[match.end():]
    habitual = _habitual_full_spans(text, facts["duration.ratio"])
    if habitual:
        ids.add("duration.habitual")
        text = _blank(text, habitual)
    for match, key, ok in _magnitude_claims(text, facts):  # "plus d'une minute par km" states the delta
        if not ok:
            return None
        ids.add(f"{key}.delta")
        text = _blank(text, [match.span()])
    at_hr, at_pace = bool(_AT_COMPARABLE_HR.search(text)), bool(_AT_COMPARABLE_PACE.search(text))
    same_distance = bool(_SAME_DISTANCE.search(text))
    hr_position = bool(_RELATIVE_EASY.search(text) or (_HR_WORD.search(text) and (
        _HR_POSITION.search(text) or _POS_LOW.search(text) or _POS_HIGH.search(text))))
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
            if duration_claims or habitual:
                candidates = [("duration.ratio", {facts["duration.ratio"]["count"]})]
            elif not candidates and _HISTORY_LIST.search(text):
                candidates = [("history.population", facts["history.population"])]
        for key, allowed in candidates:
            if any(a is not None and abs(value - a) < 0.5 for a in allowed):
                ids.add(key)
                counted = True
        if not counted:
            return None
    return ids or None


def _duration_text(minutes: float, texts: dict, language: str) -> str:
    """"68 minutes", but "2h02" from two hours: the forms the guard reads as the same measured duration."""
    if minutes >= 120 and minutes == int(minutes):
        return f"{int(minutes) // 60}h{int(minutes) % 60:02d}"
    return texts["measure"]["minutes"].format(v=_num(minutes, language))


def _measures_sentence(facts: dict, covered: frozenset, texts: dict, language: str) -> Optional[str]:
    """One natural sentence with the measures the contract proves and no kept sentence already states.

    A measure the contract does not hold is never completed; a lone measure gets its own full phrasing,
    never a partial "in numbers: ..." introduction.
    """
    forms = texts["measure"]
    segments: list[str] = []
    for fact_id, name, render in (
            ("session.distance", "distance", lambda v: _num(v, language)),
            ("session.duration", "duration", lambda v: _duration_text(v, texts, language)),
            ("session.avg_pace", "pace", lambda v: f"{v}/km"),
            ("session.avg_hr", "hr", lambda v: _num(v, language))):
        value = facts.get(fact_id)
        if value is None or fact_id in covered:
            continue
        form = forms[name if segments or name == "distance" else f"{name}_head"]
        segments.append(form.format(v=render(value)))
    return "".join(segments) + "." if segments else None


def _fallback_items(context: dict, language: str, covered: frozenset = frozenset(),
                    question: Optional[str] = None, type_stated: bool = False) -> list[tuple[set[str], str]]:
    """Ordered (fact ids, sentence) from the evidence contract, minus facts already stated (`covered`)."""
    texts = _FALLBACK.get(language, _FALLBACK["en"])
    frame = context.get("session_coaching_frame")
    contract = (frame or {}).get("evidence_contract") if isinstance(frame, dict) else None
    if not isinstance(contract, dict):
        return []
    facts = _facts(context)
    items: list[tuple[set[str], str]] = []
    measures = _measures_sentence(facts, covered, texts, language)
    if measures:
        items.append(({"session.measures"}, measures))
    structure = facts.get("session.effort_structure")
    if structure and "session.effort_structure" not in covered:
        seconds = structure["duration_s"]
        shown = f"{round(seconds / 60)} min" if seconds >= 60 and abs(seconds - round(seconds / 60) * 60) <= 3 \
            else f"{int(round(seconds))} s"
        items.append(({"session.effort_structure"}, texts["structure"].format(n=structure["count"], d=shown)))
    paces = [e["value"] for e in (contract.get("measured_facts") or {}).get("recorded_effort_paces") or []
             if isinstance(e, dict) and _norm_pace(e.get("value")) and "session.effort_pace" not in covered]
    if paces:
        items.append(({"session.effort_pace"}, texts["efforts"].format(paces=", ".join(paces))))
    v3 = frame.get("v3_assessment") if isinstance(frame.get("v3_assessment"), dict) else {}
    classification = v3.get("classification") or {}
    if type_stated and "session.type" not in covered and classification.get("probable_type") in texts["type_kinds"] \
            and classification.get("confidence") in texts["type_conf"]:
        items.append(({"session.type"}, texts["type"].format(
            kind=texts["type_kinds"][classification["probable_type"]],
            conf=texts["type_conf"][classification["confidence"]])))
    relative = classification.get("relative_effort") or {}
    pop = facts["relative_hr.population"]
    if relative.get("status") == "used" and relative.get("relative_position") in texts["position"] and pop \
            and "relative_hr.population" not in covered:
        items.append(({"relative_hr.population"}, texts["relative"].format(
            position=texts["position"][relative["relative_position"]], count=pop)))
    ratio = facts["duration.ratio"]
    if ratio and "duration.ratio" not in covered:
        items.append(({"duration.ratio"}, texts["duration_ratio"].format(
            ratio=_num(ratio["ratio"], language), count=ratio["count"])))

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
            recorded.get("recording_timing"), "unordered" if recorded.get("recorded_at") else "unknown")
        label = texts["kinds"].get(recorded.get("prescribed_workout_type"))
        if _prescription_relevant(question):
            items.append(({"prescription"}, texts[timing].format(kind=f" ({label})" if label else "")))
    intensity = v3.get("intensity") or {}
    if intensity.get("thresholds_available") and intensity.get("position_vs_declared_thresholds") in \
            texts["threshold_position"]:
        items.append(({"thresholds"}, texts["thresholds"].format(
            position=texts["threshold_position"][intensity["position_vs_declared_thresholds"]])))
    return items


_PRESCRIPTION_LEAD = re.compile(
    r"(?:prescri\w+|prescripci\w+)(?:\s+(?:du jour|of the day|for the day|for today|del d[íi]a|de hoy|"
    r"d['’]aujourd['’]hui))?(?:\s*(?:\(|:|[–—-])|\s+(?:(?:[ée]tait|est|was|is|era|es)\s+)?"
    r"(?:(?:une?|a|an|una?|de|of)\s+)?)\s*", re.I)


def _prescription_labels(sentence: str) -> list[tuple[tuple[int, int], str]]:
    """((start, end), workout type) of each prescription type label written right after "prescription"."""
    labels = sorted(((label, kind) for texts in _FALLBACK.values() for kind, label in texts["kinds"].items()),
                    key=lambda item: -len(item[0]))
    found = []
    for lead in _PRESCRIPTION_LEAD.finditer(sentence):
        for label, kind in labels:
            match = re.compile(re.escape(label) + r"\b", re.I).match(sentence, lead.end())
            if match:
                found.append((match.span(), kind))
                break
    return found


def _prescription_label_spans(sentence: str, context: dict) -> list[tuple[int, int]]:
    """Spans of prescription labels that are exactly the recorded snapshot's type; any other stays visible.

    A prescription label is a statement about the plan, never about the effort actually run, and a
    prescription never proves it was carried out.
    """
    frame = context.get("session_coaching_frame") if isinstance(context.get("session_coaching_frame"), dict) else {}
    recorded = (frame.get("session_intent") or {}).get("recorded_historical_prescription")
    kind = recorded.get("prescribed_workout_type") if isinstance(recorded, dict) else None
    return [span for span, found in _prescription_labels(sentence) if kind and found == kind]


_PRESCRIPTION_QUESTION = re.compile(
    r"(prescri|planifi|\bplan\b|pr[ée]vu|consigne|objectif|programm|planned|scheduled|training plan|today's|"
    r"previst|planificad|programa\b)", re.I)


def _prescription_relevant(question: Optional[str]) -> bool:
    """A prescription is told only when the question is about it; without any question, as before."""
    return not isinstance(question, str) or not question.strip() or bool(_PRESCRIPTION_QUESTION.search(question))


def _signed_delta(value: Any, positive: str, negative: str, texts: dict, language: str) -> Optional[tuple[str, str]]:
    value = _finite(value)
    if value is None or round(abs(value), 1) == 0:
        return None
    return _num(round(abs(value), 1), language), texts[positive if value > 0 else negative]


_LIMIT_SIGNATURE = {
    "physiological_intensity_undetermined": re.compile(
        r"(physiolog|fisiol[óo]g)|(?:intensit[ée]|intensity|intensidad).{0,40}(?:d[ée]termin|determin)", re.I),
    "progress_not_demonstrated": re.compile(r"(progress|progresi[óo]n|progreso)", re.I),
    "recovery_not_measured": re.compile(r"(r[ée]cup[ée]ration|recovery|recuperaci[óo]n)", re.I),
}


_LIMIT_QUESTION = {
    "physiological_intensity_undetermined": re.compile(
        r"(intensit|zone|seuil|threshold|\bLT[12]\b|umbral|physiolog|fisiol|difficile|hard|facile|easy|"
        r"effort|esfuerzo|f[áa]cil)", re.I),
    "progress_not_demonstrated": re.compile(r"(progr|am[ée]liorat|improv|mejor)", re.I),
    "recovery_not_measured": re.compile(r"(r[ée]cup[ée]r|recover|recuper|repos|\brest\b|fatigue|cansanc)", re.I),
}


def _fallback_limit(contract: dict, language: str, said: str = "", question: Optional[str] = None,
                    default: bool = True) -> Optional[str]:
    """The limit the contract declares that matters for the question; nothing is asserted otherwise.

    Two different limits answer two different questions, so only the one the question is about is
    added. Nothing is added when `said` (the kept reply sentences) already expresses it, or, when the
    question points at no limit, already states any limit. Without a pointed question the single most
    important limit is added only when `default` is set (the full contract fallback).
    """
    texts = _FALLBACK.get(language, _FALLBACK["en"])
    declared = contract.get("not_demonstrated") or {}
    asked = next((k for k in _LIMIT_PRIORITY if k in declared and isinstance(question, str)
                  and _LIMIT_QUESTION[k].search(question)), None)
    if asked:
        return None if _LIMIT_SIGNATURE[asked].search(said) else texts["limits"][asked]
    if not default or _LIMIT_STATEMENT.search(said):
        return None
    for key in _LIMIT_PRIORITY:
        if key in declared:
            return None if _LIMIT_SIGNATURE[key].search(said) else texts["limits"][key]
    return None


_FOCUS_ORDINAL = {
    "premier": 1, "premiere": 1, "first": 1, "1st": 1, "primer": 1, "primero": 1, "primera": 1,
    "deuxieme": 2, "second": 2, "seconde": 2, "2nd": 2, "segundo": 2, "segunda": 2,
    "troisieme": 3, "third": 3, "3rd": 3, "tercer": 3, "tercero": 3, "tercera": 3,
    "quatrieme": 4, "fourth": 4, "4th": 4, "cuarto": 4, "cuarta": 4,
    "cinquieme": 5, "fifth": 5, "5th": 5, "quinto": 5, "quinta": 5,
    "sixieme": 6, "sixth": 6, "6th": 6, "sexto": 6, "sexta": 6,
    "septieme": 7, "seventh": 7, "7th": 7, "septimo": 7, "huitieme": 8, "eighth": 8, "8th": 8, "octavo": 8,
    "neuvieme": 9, "ninth": 9, "9th": 9, "noveno": 9, "dixieme": 10, "tenth": 10, "10th": 10, "decimo": 10,
    "dernier": -1, "derniere": -1, "last": -1, "final": -1, "ultimo": -1, "ultima": -1,
}
_FOCUS_NOUN = r"(?:efforts?|repetitions?|repeticion(?:es)?|reps?|intervalles?|intervals?|fractions?|esfuerzos?|series?|intervalos?)"
_FOCUS_ORDINAL_FIRST = re.compile(
    rf"\b({'|'.join(_FOCUS_ORDINAL)}|\d{{1,2}}\s*(?:e|er|eme|th|st|nd|rd|a|o))\s+{_FOCUS_NOUN}\b")
_FOCUS_NUMBER_AFTER = re.compile(rf"\b{_FOCUS_NOUN}\s*(?:n(?:o|°|º)?\.?\s*|numero\s*|#)?(\d{{1,2}})\b(?!\s*(?:km|min|m\b|s\b|sec|bpm|%|x))")
_FOCUS_WHY = re.compile(r"\b(?:pourquoi|why|por que|comment expliquer)\b")
_FOCUS_TOPICS = {
    "progress": re.compile(r"progr|ameliorat|improv|mejora|mejoro|mejorand|\bforme\b|fitness|\bforma\b|fitter"),
    "intensity": re.compile(r"intensi[td]|\bzone|seuil|threshold|\blt[12]\b|umbral|physiolog|fisiolog|difficile|"
                            r"\bhard\b|\bfacile\b|\beasy\b|\bfacil\b|dificil"),
    "recovery": re.compile(r"recuper|recover|\brepos\b|\brest\b|fatigue|cansanc"),
}
# Facts of the contract each topic may bring back; an item outside the asked topic is not repeated.
_TOPIC_FACTS = {
    "progress": ("session.effort_pace", "session.effort_structure", "v2.similar_pace", "v3.pace_at_hr",
                 "v3.hr_at_pace"),
    "intensity": ("relative_hr.population", "thresholds", "session.type"),
    "recovery": ("session.measures", "duration.ratio"),
}
_TOPIC_LIMIT = {"progress": "progress_not_demonstrated", "intensity": "physiological_intensity_undetermined",
                "recovery": "recovery_not_measured"}


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _question_focus(question: Optional[str]) -> dict:
    """What the runner asked about: an effort number, a "why", and progress/intensity/recovery topics."""
    text = _plain(question) if isinstance(question, str) else ""
    effort = None
    found = _FOCUS_ORDINAL_FIRST.search(text)
    if found:
        word = found.group(1)
        effort = _FOCUS_ORDINAL.get(word) or int(re.match(r"\d+", word).group(0))
    elif _FOCUS_NUMBER_AFTER.search(text):
        effort = int(_FOCUS_NUMBER_AFTER.search(text).group(1))
    return {"effort": effort, "why": bool(_FOCUS_WHY.search(text)),
            "topics": [name for name, pattern in _FOCUS_TOPICS.items() if pattern.search(text)]}


def _effort_pace_seconds(contract: dict) -> dict[int, tuple[str, int]]:
    """{effort_number: (pace shown, seconds/km)} for the recorded efforts that carry both."""
    found: dict[int, tuple[str, int]] = {}
    for entry in (contract.get("measured_facts") or {}).get("recorded_effort_paces") or []:
        if not isinstance(entry, dict):
            continue
        number, pace = entry.get("effort_number"), _norm_pace(entry.get("value"))
        if isinstance(number, bool) or not isinstance(number, int) or not pace:
            continue
        minutes, seconds = pace.split(":")
        found[number] = (pace, int(minutes) * 60 + int(seconds))
    return found


def _effort_sentences(contract: dict, language: str, effort: int) -> tuple[list[str], Optional[str]]:
    """Sentences about the asked effort from recorded paces only; also the rank ("fastest"/"slowest")."""
    words = (_FALLBACK.get(language, _FALLBACK["en"]))["focus"]
    paces = _effort_pace_seconds(contract)
    structure = _effort_structure_fact((contract.get("measured_facts") or {}).get("recorded_effort_structure"))
    number = effort
    if effort == -1:
        # The last repetition is the last expected one, never the last one that happens to have a pace.
        if not structure:
            return [words["last_unknown"]], None
        number = structure["count"]
    if number not in paces:
        return [words["missing"]], None
    pace, seconds = paces[number]
    others = [value for key, (_, value) in paces.items() if key != number]
    # "Fastest"/"slowest" is only claimed over the recorded paces; a tie gives no unique rank.
    complete = bool(structure) and set(paces) == set(range(1, structure["count"] + 1))
    rank = None
    if others and seconds < min(others):
        rank = "fastest"
    elif others and seconds > max(others):
        rank = "slowest"
    name = words["last"] if effort == -1 else words["ordinals"].get(number)
    if name is None:
        return [words["numbered"].format(n=number, pace=pace)], rank
    return [words[rank if rank and complete else f"{rank}_partial" if rank else "plain"]
            .format(ord=name, pace=pace)], rank


def _focused_fallback(context: dict, language: str, question: Optional[str], type_stated: bool) -> Optional[str]:
    """Answer the asked subject from the contract's facts only; None when the question points at nothing."""
    focus = _question_focus(question)
    if focus["effort"] is None and not focus["topics"]:
        return None
    texts = _FALLBACK.get(language, _FALLBACK["en"])
    contract = context["session_coaching_frame"]["evidence_contract"]
    declared = contract.get("not_demonstrated") or {}
    parts: list[str] = []
    rank = None
    if focus["effort"] is not None:
        parts, rank = _effort_sentences(contract, language, focus["effort"])
        if focus["why"] and len(parts) == 1 and parts[0] not in (
                texts["focus"]["missing"], texts["focus"]["last_unknown"]):
            parts.append(texts["focus"]["cause" if rank else "unexplained"])
    allowed = tuple(fact for topic in focus["topics"] for fact in _TOPIC_FACTS[topic])
    for ids, sentence in _fallback_items(context, language, question=question, type_stated=type_stated):
        if any(i.startswith(allowed) for i in ids) and not (
                focus["effort"] is not None and ids & {"session.effort_pace", "session.effort_structure"}):
            parts.append(sentence)
    for topic in focus["topics"]:
        key = _TOPIC_LIMIT[topic]
        if key not in declared:
            continue
        if topic == "progress" and focus["effort"] is not None:
            parts.append(texts["focus"]["single_faster" if rank == "fastest" else "single"])
        else:
            parts.append(texts["limits"][key])
    return " ".join(parts) if parts else None


def build_contract_fallback(context: dict, language: str, question: Optional[str] = None,
                            type_stated: bool = False) -> Optional[str]:
    """Factual, useful reply built only from the evidence contract; None when it holds nothing."""
    items = _fallback_items(context, language, question=question, type_stated=type_stated)
    if not items:
        return None
    focused = _focused_fallback(context, language, question, type_stated)
    if focused:
        return focused
    limit = _fallback_limit(context["session_coaching_frame"]["evidence_contract"], language, question=question)
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


# A figure-free sentence is kept only when it states a limit of the analysis: it restricts what can be
# concluded and asserts nothing about the session. Any other figure-free evaluation stays unproven.
_LIMIT_STATEMENT = re.compile(
    r"(limit[ée]e?s?\b|ne (?:peut|permet|suffit|permettent)|n'est pas (?:possible|d[ée]montr)|aucun[e]? |"
    r"cannot|can't|limited|not (?:possible|demonstrated|enough)|does not (?:allow|show)|no (?:se )?(?:puede|permite)|"
    r"limitad[oa]s?|no hay)", re.I)


def _proven_relative_statement(sentence: str, context: dict) -> bool:
    """A figure-free sentence the contract proves: V3's own relative conclusion, or the relative HR position."""
    c = _contract(context)
    if c["relative_easy"] and _RELATIVE_EASY.search(sentence) and _RELATIVE_FRAME.search(sentence):
        return True
    return _proven_relative_hr_position(sentence, context)


def _proven_relative_hr_position(sentence: str, context: dict) -> bool:
    c = _contract(context)
    return bool(c["relative_used"] and c["relative_position"] == "low" and _HR_WORD.search(sentence)
                and _POS_LOW.search(sentence) and not _POS_HIGH.search(sentence))


def _sentence_reasons(sentence: str, context: dict, language: str, question: Optional[str]) -> set[str]:
    _, local = csc.validate_session_comment(_csc_view(sentence, context), context, language)
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
    type_stated = "type_certainty_not_established" in verdict["rejected_checks"]
    fallback = build_contract_fallback(context, language, question, type_stated)
    full_text = text.strip() if isinstance(text, str) else ""
    sentences = csc._sentences(full_text)
    if not sentences or fallback is None:
        result["text"] = fallback
        return result

    attributed: set[str] = set()
    kept: list[str] = []
    kept_ids: dict[str, set] = {}  # logical facts carried by each kept sentence
    covered: set[str] = set()
    substantive = False
    facts = _facts(context)
    positions_seen = 0
    for sentence in sentences:
        reasons = _sentence_reasons(sentence, context, language, question)
        attributed |= reasons
        if _states_hr_position(sentence):
            positions_seen += 1
            if reasons and positions_seen > 1:
                attributed.add("redundant_hr_position")  # the repeated statement is the removed sentence
        if reasons:
            continue
        if _DEPENDENT_START.search(sentence) and not _SESSION_SUBJECT.search(sentence):
            continue
        if _INFERENCE.search(sentence):
            continue
        ids = _attribute(sentence, facts)
        if "relative_hr.population" in covered and (
                "relative_hr.population" in (ids or ()) or _states_hr_position(sentence)):
            attributed.add("redundant_hr_position")  # the HR position is stated once
            continue
        if not ids:
            if ids is None and not _states_metric_figure(sentence) and not _FIGURE.search(sentence) \
                    and (_LIMIT_STATEMENT.search(sentence) or _proven_relative_statement(sentence, context)):
                kept.append(sentence)
                kept_ids[sentence] = set()
                if _proven_relative_hr_position(sentence, context):
                    covered.add("relative_hr.population")  # stated once: the fallback must not repeat it
                    substantive = True
                elif not _LIMIT_STATEMENT.search(sentence):
                    substantive = True
            continue
        compared = {i for i in ids if i.endswith(".delta")}
        # a comparison is identified by metric, population, direction and delta, not by whether the
        # sentence also quotes the number of sessions
        if compared and compared <= covered and all(
                i in compared or (i.endswith(".population") and i[:-len(".population")] + ".delta" in covered)
                for i in ids):
            continue
        kept.append(sentence)
        kept_ids[sentence] = set(ids)
        substantive = True
        covered |= ids
        if _TYPE_TERM_RE.search(sentence):
            covered.add("session.type")
    result["removed_sentences"] = len(sentences) - len(kept)
    focus = _question_focus(question)
    if focus["effort"] is not None:
        # A precise repetition was asked: keep only sentences about its pace or pure reserves.
        kept = [k for k in kept if not kept_ids.get(k) or "session.effort_pace" in kept_ids[k]]
        covered = {c for c in covered if c == "session.effort_pace"} if any(
            "session.effort_pace" in kept_ids.get(k, ()) for k in kept) else set()
        substantive = any("session.effort_pace" in kept_ids.get(k, ()) for k in kept)
    if not set(verdict["rejected_checks"]) <= attributed or not kept:
        result["text"] = fallback
        return result

    restored_items = _fallback_items(context, language, frozenset(covered), question, type_stated)
    topics = focus["topics"]
    if topics:  # only the facts of the asked topic come back, not every removed metric
        allowed = tuple(fact for topic in topics for fact in _TOPIC_FACTS[topic])
        restored_items = [item for item in restored_items if any(i.startswith(allowed) for i in item[0])]
    restored = [t for _, t in restored_items]
    if focus["effort"] is not None:
        # A precise repetition was asked: restore only its own fact, never the other paces or measures.
        contract = context["session_coaching_frame"]["evidence_contract"]
        words = _FALLBACK.get(language, _FALLBACK["en"])["focus"]
        sentences_, rank = _effort_sentences(contract, language, focus["effort"])
        restored = [] if "session.effort_pace" in covered else list(sentences_)
        if focus["why"] and len(sentences_) == 1 and sentences_[0] not in (words["missing"], words["last_unknown"]):
            restored.append(words["cause" if rank else "unexplained"])
    if not substantive:  # nothing but reserves is kept: the factual fallback answers better
        result["text"] = fallback
        return result
    limit = None if focus["effort"] is not None else _fallback_limit(
        context["session_coaching_frame"]["evidence_contract"], language, " ".join(kept), question, default=False)
    if focus["effort"] is not None and "session.effort_pace" in covered:
        candidate = " ".join(kept + restored)  # the model's own sentence first, then the stated limit
    else:
        candidate = " ".join(restored + kept + ([limit] if limit else []))
    if not verify_chat_reply(candidate, context, language, question)["passed"]:
        result["text"] = fallback
        return result
    result["text"], result["response_source"] = candidate, "llm_reply_partially_validated"
    return result
