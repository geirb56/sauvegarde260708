"""C362 offline experiment: selective, evidence-grounded coaching with risk checks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
import re
from time import perf_counter
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from access_control import UserAccess
from narrative_coach_v3 import Transport, format_narrative_number
from workout_intelligence_v3_models import WorkoutIntelligenceV3

FEATURE_FLAG = "C359_HYBRID_COACH_ENABLED"
TIMEOUT_SECONDS = 8.0
MAX_RESPONSE_CHARS = 2400
VERSION = "c362-evidence-grounded-llm-1"

_VALUE_MEANINGS = {
    "efforts": "Number of recorded Garmin effort phases, not their duration.",
    "recoveries": "Number of recorded Garmin recovery phases, not their duration.",
    "duration": "Recorded session duration.",
    "usual_duration": "Habitual duration established by V3 from prior sessions.",
    "classification": "V3 classification; probable labels are never certain.",
    "average_hr": "Session-average heart rate, not every moment of the session.",
    "average_hr_available": "Availability indicator, not a measured value.",
    "lt1": "Personal LT1 heart-rate threshold used by V3.",
    "lt2": "Personal LT2 heart-rate threshold used by V3.",
    "position": "V3 position of session-average HR relative to personal thresholds.",
    "status": "V3 assessment status, not an independently inferred conclusion.",
    "observations": "Number of observations used by V3.",
    "median_change": "V3 median pace change: later minus earlier; negative is faster.",
    "span": "Time span covered by the V3 trend.",
    "pace_difference": "Current pace minus mean reference pace at comparable HR; negative is faster.",
    "hr_difference": "Current HR minus mean reference HR at comparable pace.",
    "references": "Number of comparable prior sessions used by V3.",
}

_REQUIRED_LIMITS = {
    "interval.count": ("no_repetition_durations", "regularity_verdict_unavailable"),
    "session.long": ("probable_not_certain", "duration_not_effort"),
    "session.kind": ("probable_not_certain",),
    "intensity.position": ("average_not_whole_effort", "no_time_in_zones", "no_physiological_cause"),
    "intensity.hr": ("no_physiological_zone", "average_not_whole_effort"),
    "session.unknown": ("unknown_not_easy",),
    "prescription.review": ("no_new_prescription", "no_inferred_cause"),
}

@dataclass(frozen=True)
class HybridPermissions:
    history: bool = False
    prescription: bool = False


@dataclass(frozen=True)
class ValidatedKnowledgeProvenance:
    """Future audit interface only; no prose, runtime loader or admission API."""

    source_uri: str
    content_digest: str
    reviewed_revision: str


VALIDATED_KNOWLEDGE: tuple[ValidatedKnowledgeProvenance, ...] = ()


@dataclass(frozen=True)
class AdmissibleFact:
    id: str
    values: tuple[tuple[str, float | int | str], ...]
    units: tuple[tuple[str, str], ...]
    allowed_conclusion: str
    confidence: Literal["high", "medium", "low", "none"]
    usage_conditions: tuple[str, ...]
    important_limits: tuple[str, ...]
    priority: int
    source_paths: tuple[str, ...]
    assertion: str

    def provider_fact(self) -> dict:
        # IDs are fixed public vocabulary, never workout/user/provider IDs.
        return {
            "evidence_id": self.id, "values": dict(self.values),
            "units": dict(self.units), "allowed_conclusion": self.allowed_conclusion,
            "confidence": self.confidence,
            "meaning": {key: _VALUE_MEANINGS[key] for key, _ in self.values},
            "priority": self.priority,
            "usage_conditions": list(self.usage_conditions),
            "forbidden_conclusions": list(self.important_limits),
            "required_limits": list(_required_limit_ids(self)),
        }


class HybridClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    section: str = "analysis"
    text: str
    evidence_ids: list[str]
    conclusion_ids: list[str]
    evidence_refs: list[str]


class HybridResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = VERSION
    mode: Literal["disabled", "denied", "deterministic_fallback", "generated_narrative"]
    verdict: Literal["HOLD"] = "HOLD"
    reason: str
    verification_scope: Literal["none", "heuristic_risk_checks"] = "none"
    blockers: list[str] = Field(default_factory=lambda: [
        "heuristic_checks_are_not_semantic_proof",
    ])
    text: str = ""
    claims: list[HybridClaim] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    provider_attempted: bool = False
    transport_kind: Literal["none", "runindex", "injected"] = "none"
    elapsed_ms: Optional[float] = None
    provider_duration_sec: Optional[float] = None
    cost: Optional[float] = None


def _authorized(access: Optional[UserAccess]) -> bool:
    return isinstance(access, UserAccess) and access.can("coach_workout_analysis")


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _count(value) -> bool:
    return _finite(value) and value >= 0 and int(value) == value


def _required_limit_ids(fact: AdmissibleFact) -> tuple[str, ...]:
    required = list(_REQUIRED_LIMITS.get(fact.id, ()))
    if fact.id in {"session.kind", "session.long"} and "low_confidence" in fact.important_limits:
        required.append("low_confidence")
    if (fact.id == "session.kind"
            and "relative_effort_not_physiological_intensity" in fact.important_limits):
        required.append("relative_effort_not_physiological_intensity")
    if fact.id.startswith("trend."):
        required.extend(("not_proof_of_fitness", "no_cause", "terrain_weather_not_controlled"))
    return tuple(limit for limit in required if limit in fact.important_limits)


def _language(language: str) -> str:
    code = language.lower().split("-")[0] if isinstance(language, str) else "fr"
    return code if code in {"fr", "en", "es"} else "fr"


def build_admissible_facts(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
) -> tuple[AdmissibleFact, ...]:
    """Finite structured authority, independent of Narrative V3 selected prose.

    Never copy V3 prose, source-path strings, IDs, dates or arbitrary evidence.
    Counts/availability do NOT authorize a regularity verdict, even at high
    classification confidence. This V3-only experiment has no V2 authority.
    """
    if not _authorized(access):
        return ()
    lang = _language(language)
    cls = intelligence.session_classification
    intensity = intelligence.intensity_assessment
    facts = []
    history = permissions.history is True
    prescription = permissions.prescription is True
    history_classification = (
        cls.decision_tier == "individual_history" or cls.type == "long_run_probable"
        or any(p == "history" or p.startswith("history.") for p in cls.source_paths)
    )

    def tr(fr, en, es):
        return {"fr": fr, "en": en, "es": es}[lang]

    def num(value):
        return format_narrative_number(value, lang)

    def add(id, values, units, conclusion, confidence, conditions, limits, priority, refs, text):
        facts.append(AdmissibleFact(
            id, tuple(values.items()), tuple(units.items()), conclusion, confidence,
            tuple(conditions), tuple(limits), priority, tuple(refs), text,
        ))

    allowed_classification = history or not history_classification
    efforts = cls.evidence.get("effort_count")
    recoveries = cls.evidence.get("recovery_count")
    if (allowed_classification and cls.type == "intervals"
            and _count(efforts) and efforts >= 2 and _count(recoveries) and recoveries >= 1):
        e, r = int(efforts), int(recoveries)
        add("interval.count", {"efforts": e, "recoveries": r}, {"efforts": "count", "recoveries": "count"},
            "recorded_intervals_without_regularity", cls.confidence, ["garmin_phases"],
            ["no_repetition_durations", "regularity_verdict_unavailable"], 100,
            ["session_classification.type", "session_classification.confidence",
             "session_classification.evidence.effort_count", "session_classification.evidence.recovery_count"],
            tr(f"Garmin a enregistré une séance fractionnée avec {e} phases d'effort et {r} phases de récupération.",
               f"Garmin recorded an interval session with {e} effort phases and {r} recovery phases.",
               f"Garmin registró una sesión de intervalos con {e} fases de esfuerzo y {r} fases de recuperación."))
    elif allowed_classification and cls.type == "long_run_probable":
        duration = cls.evidence.get("duration_minutes")
        usual = cls.evidence.get("habitual_duration_minutes")
        if _finite(duration) and _finite(usual) and usual > 0 and duration > 0:
            uncertain = cls.confidence in {"low", "none"}
            caveat = tr(" Le type reste incertain.", " The type remains uncertain.",
                        " El tipo sigue siendo incierto.") if uncertain else ""
            add("session.long", {"duration": duration, "usual_duration": usual},
                {"duration": "min", "usual_duration": "min"}, "probable_long_duration_comparison",
                cls.confidence, ["history_authorized", "v3_classification"],
                ["probable_not_certain", "duration_not_effort"] + (["low_confidence"] if uncertain else []), 95,
                ["session_classification.type", "session_classification.confidence",
                 "session_classification.evidence.duration_minutes",
                 "session_classification.evidence.habitual_duration_minutes"],
                tr(f"Ta sortie est probablement longue : {num(duration)} min, contre {num(usual)} min habituellement.",
                   f"At {num(duration)} min versus your usual {num(usual)} min, this was probably a long run.",
                   f"Con {num(duration)} min frente a tus {num(usual)} min habituales, probablemente fue una tirada larga.") + caveat)
    elif allowed_classification and cls.type in {"easy_run_probable", "steady_run_probable", "tempo_probable"}:
        assertion = {
            "easy_run_probable": tr(
                "Tu as probablement fait un footing facile.",
                "This was probably an easy run.",
                "Probablemente fue una carrera fácil.",
            ),
            "steady_run_probable": tr(
                "Ta séance ressemble probablement à une sortie soutenue.",
                "This was probably a steady run.",
                "Probablemente fue una carrera sostenida.",
            ),
            "tempo_probable": tr(
                "Ça ressemble probablement à une séance tempo.",
                "This was probably a tempo run.",
                "Probablemente fue una sesión tempo.",
            ),
        }[cls.type]
        uncertain = cls.confidence in {"low", "none"}
        history_qualification = history_classification
        relative_effort = tr(
            "; cette classification est relative à ton historique, pas à une intensité physiologique",
            "; this classification is relative to your history, not physiological intensity",
            "; esta clasificación es relativa a tu historial, no a la intensidad fisiológica",
        ) if history_qualification else ""
        limits = ["probable_not_certain"] + (["low_confidence"] if uncertain else [])
        conditions = ["v3_classification"]
        if history_qualification:
            conditions.append("history_authorized")
            limits.append("relative_effort_not_physiological_intensity")
        if uncertain:
            assertion += tr(" Le type reste incertain.", " The type remains uncertain.",
                            " El tipo sigue siendo incierto.")
        if history_qualification:
            assertion += relative_effort
        add("session.kind", {"classification": cls.type}, {}, "probable_session_type",
            cls.confidence, conditions, limits, 45,
            ["session_classification.type", "session_classification.confidence"],
            assertion)

    hr = intensity.hr_used_bpm
    if _finite(hr):
        lt1, lt2 = intensity.lt1, intensity.lt2
        reliable = intensity.confidence in {"medium", "high"}
        threshold_ok = (
            reliable and lt1 is not None and lt2 is not None
            and _finite(lt1.value_bpm) and _finite(lt2.value_bpm)
            and lt1.value_bpm > 0 and lt2.value_bpm > lt1.value_bpm
            and lt1.confidence in {"medium", "high"} and lt2.confidence in {"medium", "high"}
            and lt1.source in {"lab_test", "field_test", "device_estimate"}
            and lt2.source in {"lab_test", "field_test", "device_estimate"}
        )
        position = intensity.position
        consistent = threshold_ok and (
            (position == "below_LT1" and hr < lt1.value_bpm)
            or (position == "between_LT1_LT2" and lt1.value_bpm <= hr <= lt2.value_bpm)
            or (position == "above_LT2" and hr > lt2.value_bpm)
        )
        if consistent:
            relation = {
                "below_LT1": tr("sous LT1", "below LT1", "por debajo de LT1"),
                "between_LT1_LT2": tr("entre LT1 et LT2", "between LT1 and LT2", "entre LT1 y LT2"),
                "above_LT2": tr("au-dessus de LT2", "above LT2", "por encima de LT2"),
            }[position]
            add("intensity.position", {"average_hr": hr, "lt1": lt1.value_bpm, "lt2": lt2.value_bpm,
                                      "position": position},
                {"average_hr": "bpm", "lt1": "bpm", "lt2": "bpm"}, "average_hr_threshold_position",
                intensity.confidence, ["reliable_v3_personal_thresholds"],
                ["average_not_whole_effort", "no_time_in_zones", "no_physiological_cause"], 70,
                ["intensity_assessment.hr_used_bpm", "intensity_assessment.position",
                 "intensity_assessment.confidence", "intensity_assessment.lt1.value_bpm",
                 "intensity_assessment.lt1.confidence", "intensity_assessment.lt2.value_bpm",
                 "intensity_assessment.lt2.confidence"],
                tr(f"Ta FC moyenne est de {num(hr)} bpm, {relation} ; elle ne décrit pas tout l'effort.",
                   f"Your average HR is {num(hr)} bpm, {relation}; it does not describe the entire effort.",
                   f"Tu FC media es de {num(hr)} lpm, {relation}; no describe todo el esfuerzo."))
        else:
            add("intensity.hr", {"average_hr": hr}, {"average_hr": "bpm"},
                "descriptive_average_hr_only", intensity.confidence, ["session_average_only"],
                ["no_physiological_zone", "average_not_whole_effort"], 60,
                ["intensity_assessment.hr_used_bpm"],
                tr(f"Ta FC moyenne enregistrée est de {num(hr)} bpm ; elle ne suffit pas à établir une zone physiologique.",
                   f"Your recorded average HR is {num(hr)} bpm; it cannot establish a physiological zone on its own.",
                   f"Tu FC media registrada es de {num(hr)} lpm; no basta para establecer una zona fisiológica."))

    if allowed_classification and cls.type == "unknown":
        missing = not _finite(hr)
        values = {"classification": "unknown", "average_hr_available": int(not missing)}
        units = {}
        if not missing:
            values["average_hr"] = hr
            units["average_hr"] = "bpm"
        add("session.unknown", values, units,
            "session_type_unproven", cls.confidence, ["v3_classification"],
            ["unknown_not_easy"] + (["missing_average_hr"] if missing else ["threshold_interpretation_unavailable"]), 55,
            ["session_classification.type", "session_classification.confidence", "intensity_assessment.hr_used_bpm"],
            tr("Le type de ta séance reste incertain ; aucune FC moyenne n'est disponible." if missing
               else f"Ta FC moyenne est de {num(hr)} bpm ; le type de ta séance reste incertain.",
               "Your session type remains uncertain; no average HR is available." if missing
               else f"Your average HR is {num(hr)} bpm; your session type remains uncertain.",
               "El tipo de tu sesión sigue siendo incierto; no hay FC media disponible." if missing
               else f"Tu FC media es de {num(hr)} lpm; el tipo de tu sesión sigue siendo incierto."))

    trend = intelligence.performance_trend
    comparison = intelligence.historical_comparison
    if (history and comparison.status == "available"
            and comparison.comparability == "strong"
            and "reference_structure_unknown" not in comparison.limitations):
        for suffix, block, field, key, unit, conclusion, labels in (
            ("pace", comparison.pace_at_comparable_hr, "pace_difference_sec_per_km",
             "pace_difference", "s/km", "observed_pace_difference_at_comparable_hr",
             ("À FC comparable, l'écart d'allure observé est de",
              "At comparable HR, the observed pace difference is",
              "A FC comparable, la diferencia de ritmo observada es de")),
            ("hr", comparison.hr_at_comparable_pace, "hr_difference_bpm",
             "hr_difference", "bpm", "observed_hr_difference_at_comparable_pace",
             ("À allure comparable, l'écart de FC observé est de",
              "At comparable pace, the observed HR difference is",
              "A ritmo comparable, la diferencia de FC observada es de")),
        ):
            delta = getattr(block, field)
            if (_finite(delta) and _count(block.reference_count)
                    and block.reference_count >= 2):
                path = ("historical_comparison.pace_at_comparable_hr" if suffix == "pace"
                        else "historical_comparison.hr_at_comparable_pace")
                add("comparison." + suffix, {key: delta, "references": block.reference_count},
                    {key: unit, "references": "count"}, conclusion, "high",
                    ["history_authorized", "v3_strong_comparability"],
                    ["not_proof_of_fitness", "no_cause", "terrain_weather_not_controlled"],
                    80, [path + "." + field, path + ".reference_count",
                         "historical_comparison.comparability"],
                    tr(*labels) + f" {num(delta)} {unit}.")
    directional_trend = trend.status in {"probable_improvement", "possible_decline"}
    corroborated_trend = (
        bool(trend.sensitivity)
        and all(row.status == trend.status for row in trend.sensitivity)
        and trend.variation_confirmed is directional_trend
        and not any(limit in trend.limitations for limit in (
            "status_sensitive_to_criteria", "reference_structure_unknown",
        ))
    )
    if (history and trend.confidence in {"medium", "high"}
            and corroborated_trend
            and _count(trend.observation_count) and trend.observation_count > 0
            and _count(trend.span_days) and trend.span_days > 0
            and _finite(trend.median_change_sec_per_km)
            and trend.status in {"probable_improvement", "stable", "possible_decline"}
            and (trend.status != "probable_improvement" or trend.median_change_sec_per_km < 0)
            and (trend.status != "possible_decline" or trend.median_change_sec_per_km > 0)):
        n, delta = trend.observation_count, trend.median_change_sec_per_km
        values = {"status": trend.status, "observations": n, "median_change": delta}
        units = {"observations": "count", "median_change": "s/km"}
        refs = ["performance_trend.status", "performance_trend.confidence",
                "performance_trend.observation_count", "performance_trend.median_change_sec_per_km",
                "performance_trend.variation_confirmed", "performance_trend.limitations",
                *[f"performance_trend.sensitivity.{i}.status" for i in range(len(trend.sensitivity))]]
        span = ""
        if _count(trend.span_days):
            values["span"] = trend.span_days
            units["span"] = "days"
            refs.append("performance_trend.span_days")
            span = tr(f" sur {trend.span_days} jours", f" over {trend.span_days} days", f" durante {trend.span_days} días")
        label = {
            "probable_improvement": tr("amélioration probable", "probable improvement", "mejora probable"),
            "stable": tr("tendance stable", "stable trend", "tendencia estable"),
            "possible_decline": tr("baisse possible", "possible decline", "descenso posible"),
        }[trend.status]
        add("trend." + trend.status, values, units, "qualified_historical_trend", trend.confidence,
            ["history_authorized", "v3_trend_only", "v3_sensitivity_agrees",
             "v3_confirmed_variation" if directional_trend else "v3_stable_assessment"],
            ["not_proof_of_fitness", "no_cause", "terrain_weather_not_controlled"], 90, refs,
            tr(f"Ton historique suggère une {label} : {n} observations{span}, variation d'allure médiane de {num(delta)} s/km (récente moins ancienne) ; ce n'est pas une preuve de changement de forme.",
               f"Your history suggests {label}: {n} observations{span}, median pace change {num(delta)} s/km (later minus earlier); not proof of a fitness change.",
               f"Tu historial sugiere {label}: {n} observaciones{span}, cambio de ritmo mediano de {num(delta)} s/km (reciente menos antiguo); no es una prueba de cambio de forma."))

    prescription_status = intelligence.prescription_assessment.status
    if (prescription and allowed_classification
            and prescription_status in {"consistent", "deviation"}):
        add("prescription.review", {"status": prescription_status}, {}, "review_training_prescription",
            "none", ["prescription_authorized", "training_is_prescription_authority"],
            ["no_new_prescription", "no_inferred_cause", "type_only_not_full_compliance",
             "classification_uncertainty_preserved"], 85, ["prescription_assessment.status"],
            tr("Le type observé correspond au type prescrit, selon la classification V3.",
               "The observed type matches the prescribed type under the V3 classification.",
               "El tipo observado coincide con el tipo prescrito según la clasificación V3.")
            if prescription_status == "consistent" else
            tr("Un écart au type prescrit a été relevé ; cette lecture ne le remplace ni ne le modifie.",
               "A deviation from your prescription was identified; this reading neither replaces nor changes it.",
               "Se ha identificado una desviación de tu prescripción; esta lectura no la sustituye ni modifica."))
    return tuple(facts)


def build_hybrid_context(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
) -> dict:
    """Provider-safe numeric/enum packet; local assertion/source refs excluded."""
    facts = build_admissible_facts(
        intelligence, access=access, permissions=permissions, language=language,
    )
    return {
        "language": _language(language), "facts": [f.provider_fact() for f in facts],
        "threshold_conventions": {
            "LT1": "Personal first lactate threshold; use only the value admitted by V3.",
            "LT2": "Personal second lactate threshold; use only the value admitted by V3.",
            "boundary": "Not FCmax percentages or interchangeable ventilatory thresholds; "
                        "a session average establishes neither time in zones nor whole-session intensity.",
        },
    }


def _claim(fact: AdmissibleFact) -> HybridClaim:
    return HybridClaim(
        id=fact.id, text=fact.assertion, evidence_ids=[fact.id],
        conclusion_ids=[fact.allowed_conclusion], evidence_refs=list(fact.source_paths),
    )


def select_deterministic_synthesis(facts: tuple[AdmissibleFact, ...]) -> list[HybridClaim]:
    """Choose a main reading and nonredundant support, not an LLM gain.

    Session-average HR does not explain repetitions. A trend already carries
    the useful historical reading; a derived type adds little alongside it.
    Unknown-type assertions already contain any available HR observation.
    """
    index = {fact.id: fact for fact in facts}
    trends = sorted((f for f in facts if f.id.startswith("trend.")), key=lambda f: (-f.priority, f.id))
    primary_ids = ["interval.count", "session.long"]
    primary_ids += [f.id for f in trends]
    primary_ids += ["session.unknown", "session.kind", "intensity.position", "intensity.hr"]
    primary = next((index[id] for id in primary_ids if id in index), None)
    if primary is None:
        return [_claim(index["prescription.review"])] if "prescription.review" in index else []
    selected = [primary]
    if (primary.id in {"session.long", "session.kind"} or primary.id.startswith("trend.")):
        support = index.get("intensity.position")
        if support is not None:
            selected.append(support)
    if "prescription.review" in index:
        selected.append(index["prescription.review"])
    return [_claim(f) for f in selected]


def _render(claims: list[HybridClaim]) -> str:
    return " ".join(c.text for c in claims)


_NUMBER_RE = re.compile(r"(?<![\w.])[-+−]?\d+(?:[.,]\d+)?")
_AVERAGE_HR_CLAIM = re.compile(
    r"(?:fc moyenne|fréquence cardiaque moyenne|average hr|mean heart rate|"
    r"fc media|frecuencia cardíaca media)[^.!?]{0,35}?"
    r"([-+−]?\d+(?:[.,]\d+)?)\s*(?:bpm|lpm)\b", re.I,
)
_AVERAGE_HR_POST_CLAIM = re.compile(
    r"([-+−]?\d+(?:[.,]\d+)?)\s*(?:bpm|lpm)\s*"
    r"(?:de moyenne|en moyenne|on average|de media)\b", re.I,
)
_NUMBER_WITH_UNIT = re.compile(
    r"(?<![\w.])([-+−]?\d+(?:[.,]\d+)?)\s*"
    r"(bpm|lpm|min(?:ute)?s?|days?|días|jours?|s/km|sec(?:onds?)?/km|km|%|h)\b", re.I,
)
_UNSUPPORTED_SCIENCE = re.compile(
    r"\b(?:base a[ée]robie|aerobic base|base aer[oó]bica|"
    r"favorise la r[ée]cup[ée]ration|promotes recovery|favorece la recuperaci[oó]n|"
    r"risque de blessure|injury risk|riesgo de lesi[oó]n|"
    r"progr[èe]s durable|progresses durablement|sustainable progress|"
    r"efforts portent leurs fruits|efforts? (?:are )?paying off|"
    r"d[ée]veloppe (?:ton |votre |l')endurance|builds? (?:your )?endurance|"
    r"stimule (?:ton|le) (?:syst[èe]me|m[ée]tabolisme)|"
    r"r[ée]cup[ée]ration active|active recovery|recuperaci[oó]n activa|"
    r"forme (?:s'am[ée]liore|physiologique)|fitness (?:gain|improvement)|"
    r"vraiment intense|s[ée]ance intense|hard workout|very intense|muy intensa|"
    r"efficacit[ée] (?:a[ée]robie|physiologique)|physiological efficiency|"
    r"d[ée]rive cardiaque|cardiac drift|deriva card[ií]aca|"
    r"tout l'effort (?:est|[ée]tait)|toute la s[ée]ance (?:est|[ée]tait)|"
    r"whole (?:run|session) was|temps pass[ée] (?:sous|au-dessus)|time spent (?:below|above))\b",
    re.I,
)
_GENERIC_SIGNOFF = re.compile(
    r"\b(?:bravo|continue comme [çc]a|keep it up|well done|great (?:run|workout)|"
    r"belle s[ée]ance|buen trabajo|sigue as[ií])\b", re.I,
)
_DIRECTIVE = re.compile(
    r"(?:^|[.!?;]\s*|\b(?:demain|ensuite),?\s+)(?:ajoute|augmente|r[ée]duis|ralentis|acc[ée]l[èe]re|pr[ée]vois|"
    r"cours demain|fais (?:une|un|des)|repose-toi|"
    r"run tomorrow|add (?:a|an)|increase your|reduce your|take a rest|"
    r"corre ma[ñn]ana|a[ñn]ade|reduce tu)\b", re.I,
)
_HISTORY_CLAIM = re.compile(
    r"\b(?:historique|habituellement|s[ée]ances (?:compar[ée]es|de r[ée]f[ée]rence)|"
    r"history|usually|reference sessions|historial|habitualmente)\b", re.I,
)
_PRESCRIPTION_CLAIM = re.compile(
    r"\b(?:prescription|prescripci[oó]n|entraînement prévu|planned workout|"
    r"objectif d'entraînement|training goal|objetivo de entrenamiento)\b", re.I,
)
_SENSITIVE_PATTERNS = {
    "physiological_threshold": re.compile(
        r"\b(?:lt\s*[12]|thresholds?|threshold zone|zone\s*[123]|zona\s*[123]|"
        r"seuils?|zona fisiol[oó]gica|zones? physiologiques?)\b", re.I,
    ),
    "trend": re.compile(
        r"\b(?:progress(?:ion|ed|ing)?|improv(?:e|ement|ing)|declin(?:e|ed)|"
        r"progrès|progression|amélior(?:ation|e)|baisse|progreso|mejora|descenso)\b", re.I,
    ),
    "causality": re.compile(
        r"\b(?:because of|caused by|caused the|due to|result(?:s|ed)? from|"
        r"explained by|à cause de|dû à|due à|provient de|entra[iî]ne|"
        r"s'explique par|expliqué par|causé par|debido a|causado por|"
        r"provocado por|se debe a|es la causa)\b", re.I,
    ),
    "prescription": re.compile(
        r"\b(?:you should|you need to|should run|try running|i recommend|"
        r"tu devrais|tu dois|je te conseille|il faut|fais demain|cours demain|"
        r"aumenta|te recomiendo|deberías|debes|haz mañana|corre mañana)\b", re.I,
    ),
}
_POSITIVE_REGULARITY = re.compile(
    r"\b(?:regular intervals|regular repetitions|regularly paced|"
    r"repetitions (?:are|look) regular|intervals (?:are|were|look) regular|"
    r"regularity (?:is|looks) (?:good|high|consistent)|"
    r"irrégulières|régulières|régulièrement|irregular repetitions|irregular intervals|"
    r"régularité (?:est|semble) (?:bonne|excellente|constante)|"
    r"repeticiones regulares|intervalos regulares|regularidad (?:es|parece) (?:buena|constante))\b",
    re.I,
)
_THRESHOLD_POSITIONS = {
    "below_LT1": re.compile(r"\b(?:below LT1|sous LT1|por debajo de LT1)\b", re.I),
    "between_LT1_LT2": re.compile(
        r"\b(?:between LT1 and LT2|entre LT1 et LT2|entre LT1 y LT2)\b", re.I,
    ),
    "above_LT2": re.compile(r"\b(?:above LT2|au-dessus de LT2|por encima de LT2)\b", re.I),
}
_NUMBERED_ZONE = re.compile(r"\b(?:zone|zona)\s*[1-5]\b", re.I)
_CLASSIFICATION_CLAIM = re.compile(
    r"\b(?:easy(?: run| pace)?|steady run|tempo run|footing facile|facile|"
    r"sortie soutenue|séance tempo|soutenue|carrera fácil|fácil|"
    r"carrera sostenida|sesión tempo)\b", re.I,
)
_CLASSIFICATION_LABELS = {
    "easy_run_probable": re.compile(r"\b(?:easy(?: run| pace)?|footing facile|facile|carrera fácil|fácil)\b", re.I),
    "steady_run_probable": re.compile(r"\b(?:steady run|sortie soutenue|soutenue|carrera sostenida)\b", re.I),
    "tempo_probable": re.compile(r"\b(?:tempo run|séance tempo|sesión tempo)\b", re.I),
}
_TREND_QUALIFICATIONS = {
    "trend.probable_improvement": {
        "fr": re.compile(r"\b(?:amélioration|progression) probable\b", re.I),
        "en": re.compile(r"\b(?:probable|likely) improvement\b|\bimprovement is (?:probable|likely)\b", re.I),
        "es": re.compile(r"\b(?:mejora|progreso) probable\b", re.I),
    },
    "trend.possible_decline": {
        "fr": re.compile(r"\b(?:baisse|déclin) possible\b", re.I),
        "en": re.compile(r"\bpossible decline\b|\bdecline is possible\b", re.I),
        "es": re.compile(r"\b(?:descenso|bajada) posible\b", re.I),
    },
    "trend.stable": {
        "fr": re.compile(r"\btendance stable\b", re.I),
        "en": re.compile(r"\bstable trend\b", re.I),
        "es": re.compile(r"\btendencia estable\b", re.I),
    },
}
_NEGATED = {
    "fr": ("ne peut pas", "ne permet pas", "n'est pas", "pas une preuve",
           "ne prouve pas", "impossible d'établir", "ne suffit pas"),
    "en": ("cannot", "can't", "does not", "doesn't", "not a proof", "not prove",
           "cannot establish", "does not establish"),
    "es": ("no se puede", "no permite", "no es", "no demuestra", "no basta",
           "no se establece", "no permite establecer", "no está disponible",
           "no disponible"),
}
_REQUIRED_PHRASES = {
    "relative_effort_not_physiological_intensity": {
        "fr": ("historique", "pas à une intensité physiologique"),
        "en": ("history", "not physiological"),
        "es": ("historial", "no a la intensidad fisiológica"),
    },
    "probable_not_certain": {
        "fr": ("probable",), "en": ("probably", "probable"), "es": ("probable",),
    },
    "low_confidence": {
        "fr": ("incertain", "incertaine"), "en": ("uncertain",), "es": ("inciert",),
    },
    "average_not_whole_effort": {
        "fr": ("ne décrit pas tout", "ne décrit pas chaque moment", "pas toute la séance", "moyenne seule"),
        "en": ("not describe the entire", "not represent the whole", "not represent every part", "average alone"),
        "es": ("no describe todo", "no describe cada momento", "no representa todo", "media por sí sola"),
    },
    "no_time_in_zones": {
        "fr": ("temps passé dans les zones", "temps dans les zones", "ne renseigne pas les zones"),
        "en": ("time spent in zones", "does not show time", "not time in zones"),
        "es": ("tiempo pasado en las zonas", "no indica el tiempo", "tiempo en las zonas"),
    },
    "no_physiological_zone": {
        "fr": ("ne suffit pas à établir une zone", "ne permet pas d'établir une zone"),
        "en": ("cannot establish a physiological zone", "cannot establish a zone"),
        "es": ("no permite establecer una zona", "no basta para establecer una zona"),
    },
    "regularity_verdict_unavailable": {
        "fr": ("ne peut pas être jugée", "impossible à juger", "pas disponible"),
        "en": ("cannot be judged", "cannot assess", "unavailable"),
        "es": ("no se puede juzgar", "no puede evaluarse", "no disponible"),
    },
    "not_proof_of_fitness": {
        "fr": ("pas une preuve", "ne prouve pas", "ne démontre pas"),
        "en": ("not proof", "does not prove", "doesn't prove"),
        "es": ("no es una prueba", "no demuestra"),
    },
    "no_new_prescription": {
        "fr": ("ne remplace", "ne modifie pas"),
        "en": ("does not replace", "doesn't replace", "does not change"),
        "es": ("no sustituye", "no modifica"),
    },
    "duration_not_effort": {
        "fr": ("durée ne suffit pas", "durée seule ne permet pas"),
        "en": ("duration alone does not", "duration does not establish"),
        "es": ("duración por sí sola no", "duración no determina"),
    },
    "missing_average_hr": {
        "fr": ("aucune fc moyenne", "pas de fc moyenne"),
        "en": ("no average hr", "no average heart rate"),
        "es": ("no hay fc media", "no hay frecuencia cardíaca media"),
    },
}


def _numeric_value(value: str) -> float:
    return float(value.replace("−", "-").replace(",", "."))


def _authorized_numbers(facts: tuple[AdmissibleFact, ...]) -> set[float]:
    return {
        float(value)
        for fact in facts
        for key, value in fact.values
        if key != "average_hr_available"
        and type(value) in (int, float) and math.isfinite(value)
    }


def _has_unqualified(pattern: re.Pattern, text: str, language: str) -> bool:
    for match in pattern.finditer(text):
        prefix = re.split(r"[.!?;]|\b(?:mais|but|pero)\b", text[:match.start()])[-1][-90:].lower()
        if not any(phrase in prefix for phrase in _NEGATED[language]):
            return True
    return False


def validate_generated_narrative(
    text: object, facts: tuple[AdmissibleFact, ...], *, language: str = "fr",
) -> tuple[bool, str, list[str]]:
    """Apply conservative risk heuristics, not a semantic proof of the prose."""
    if not isinstance(text, str):
        return False, "response_not_text", []
    candidate = text.strip()
    if not candidate or len(candidate) > MAX_RESPONSE_CHARS:
        return False, "response_length", []
    if candidate.startswith(("#", "-", "*", "{", "[")) or "```" in candidate:
        return False, "response_format", []
    lang = _language(language)
    if _NUMBERED_ZONE.search(candidate):
        return False, "unsupported_physiological_zone", []
    authorized = _authorized_numbers(facts)
    for number in _NUMBER_RE.findall(candidate):
        if _numeric_value(number) not in authorized:
            return False, "unsupported_numeric_value", []
    for match in _NUMBER_WITH_UNIT.finditer(candidate):
        number, unit = match.groups()
        unit = unit.lower()
        if unit in {"lpm"}:
            unit = "bpm"
        elif unit in {"minute", "minutes"}:
            unit = "min"
        elif unit in {"day", "days", "días", "jours"}:
            unit = "days"
        elif unit in {"sec/km", "second/km", "seconds/km"}:
            unit = "s/km"
        allowed_for_unit = {
            float(value)
            for fact in facts
            for key, value in fact.values
            if dict(fact.units).get(key) == unit
            and type(value) in (int, float) and math.isfinite(value)
        }
        if _numeric_value(number) not in allowed_for_unit:
            return False, "unsupported_numeric_unit_or_value", []
    average_hr = next(
        (value for fact in facts for key, value in fact.values if key == "average_hr"),
        None,
    )
    if average_hr is not None:
        for pattern in (_AVERAGE_HR_CLAIM, _AVERAGE_HR_POST_CLAIM):
            for match in pattern.finditer(candidate):
                if _numeric_value(match.group(1)) != float(average_hr):
                    return False, "contradictory_average_hr", []
    position_fact = next((fact for fact in facts if fact.id == "intensity.position"), None)
    if position_fact is not None:
        actual_position = dict(position_fact.values).get("position")
        mentioned_positions = {
            position for position, pattern in _THRESHOLD_POSITIONS.items()
            if pattern.search(candidate)
        }
        if mentioned_positions and mentioned_positions != {actual_position}:
            return False, "contradictory_threshold_position", []
        values = dict(position_fact.values)
        for match in re.finditer(
            r"\b(LT[12])\s*(?:(?:personnel|personal)\s*)?(?:(?:de|of|at|à|es)\s*|[=:]\s*)"
            r"([-+−]?\d+(?:[.,]\d+)?)\s*(?:bpm|lpm)\b", candidate, re.I,
        ):
            if _numeric_value(match.group(2)) != values[match.group(1).lower()]:
                return False, "contradictory_threshold_value", []

    lowered = candidate.lower()
    if _GENERIC_SIGNOFF.search(lowered):
        return False, "generic_encouragement", []
    if _has_unqualified(_UNSUPPORTED_SCIENCE, lowered, lang):
        return False, "unsupported_scientific_interpretation", []
    if _DIRECTIVE.search(lowered):
        return False, "unauthorized_prescription", []
    if not any("history_authorized" in f.usage_conditions for f in facts) and _has_unqualified(
        _HISTORY_CLAIM, lowered, lang,
    ):
        return False, "unauthorized_history_claim", []
    if not any(f.id == "prescription.review" for f in facts) and _has_unqualified(
        _PRESCRIPTION_CLAIM, lowered, lang,
    ):
        return False, "unauthorized_prescription_claim", []
    has_intensity_position = any(f.id == "intensity.position" for f in facts)
    has_intensity_hr = any(f.id == "intensity.hr" for f in facts)
    if not has_intensity_position and _has_unqualified(
        _SENSITIVE_PATTERNS["physiological_threshold"], lowered, lang,
    ):
        return False, "unauthorized_physiological_conclusion", []
    if _has_unqualified(_POSITIVE_REGULARITY, lowered, lang):
        return False, "unsupported_regularity_claim", []
    if not any(f.id.startswith("trend.") for f in facts) and _has_unqualified(
        _SENSITIVE_PATTERNS["trend"], lowered, lang,
    ):
        return False, "unauthorized_trend_claim", []
    for category in ("causality", "prescription"):
        if _has_unqualified(_SENSITIVE_PATTERNS[category], lowered, lang):
            return False, f"unauthorized_{category}", []

    required = set().union(*(_required_limit_ids(fact) for fact in facts)) if facts else set()
    checks = ["format", "length", "authorized_numbers", "sensitive_claims"]
    relative = any(
        fact.id == "session.kind"
        and "relative_effort_not_physiological_intensity" in fact.important_limits
        for fact in facts
    )
    classification_claim = _has_unqualified(_CLASSIFICATION_CLAIM, lowered, lang)
    if classification_claim and not any(f.id == "session.kind" for f in facts):
        return False, "unsupported_session_classification", checks
    kind = next((dict(f.values)["classification"] for f in facts if f.id == "session.kind"), None)
    if classification_claim and any(
        label != kind and _has_unqualified(pattern, lowered, lang)
        for label, pattern in _CLASSIFICATION_LABELS.items()
    ):
        return False, "contradictory_session_classification", checks
    if relative and classification_claim:
        if not all(phrase in lowered for phrase in _REQUIRED_PHRASES[
            "relative_effort_not_physiological_intensity"
        ][lang]):
            return False, "missing_history_relative_qualification", checks
        checks.append("history_relative_qualification")
    if classification_claim and "probable_not_certain" in required:
        for sentence in re.split(r"[.!?;]", lowered):
            if _has_unqualified(_CLASSIFICATION_CLAIM, sentence, lang) and not any(
                phrase in sentence for phrase in _REQUIRED_PHRASES["probable_not_certain"][lang]
            ):
                return False, "missing_probability_qualification", checks
        checks.append("probability_qualification")
    if classification_claim and any(
        f.id == "session.kind" and "low_confidence" in f.important_limits for f in facts
    ):
        if not any(phrase in lowered for phrase in _REQUIRED_PHRASES["low_confidence"][lang]):
            return False, "missing_low_confidence_qualification", checks
        checks.append("low_confidence_qualification")
    long_pattern = re.compile(r"\b(?:sortie longue|long run|tirada larga|longer run)\b", re.I)
    long_claim = _has_unqualified(long_pattern, lowered, lang)
    if long_claim:
        if not any(f.id == "session.long" for f in facts):
            return False, "unsupported_session_classification", checks
        if not any(phrase in lowered for phrase in _REQUIRED_PHRASES["probable_not_certain"][lang]):
            return False, "missing_probability_qualification", checks
        checks.append("duration_limits")
    if not any(f.id == "interval.count" for f in facts) and _has_unqualified(
        re.compile(r"\b(?:fractionn[ée]e?|interval session|interval workout|sesión de intervalos)\b", re.I),
        lowered, lang,
    ):
        return False, "unsupported_session_classification", checks
    intensity_claim = has_intensity_position and bool(re.search(
        r"\b(?:lt\s*[12]|threshold|seuil|umbral|zone|zona|sous|below|por debajo|"
        r"fc moyenne|fréquence cardiaque|average hr|mean heart rate|fc media|"
        r"frecuencia cardíaca media)\b",
        lowered, re.I,
    )) or has_intensity_hr and bool(re.search(
        r"\b(?:fc moyenne|fréquence cardiaque|average hr|mean heart rate|fc media|"
        r"frecuencia cardíaca media)\b", lowered, re.I,
    ))
    if intensity_claim:
        checks.append("average_effort_limits")
    if any(f.id.startswith("trend.") for f in facts) and _has_unqualified(
        _SENSITIVE_PATTERNS["trend"], lowered, lang,
    ):
        trend_fact = next(fact for fact in facts if fact.id.startswith("trend."))
        trend_qualification = _TREND_QUALIFICATIONS.get(trend_fact.id, {}).get(lang)
        if trend_qualification is None or not trend_qualification.search(candidate):
            return False, "missing_trend_qualification", checks
        if not any(phrase in lowered for phrase in _REQUIRED_PHRASES["not_proof_of_fitness"][lang]):
            return False, "missing_trend_limit", checks
        checks.append("trend_limit")
    return True, "heuristic_checks_passed", checks


async def _transport(system, prompt, user, context_type):
    from llm_coach import _call_gpt

    return await _call_gpt(
        system, prompt, user, context_type, sanitize_errors=True,
        response_max_chars=MAX_RESPONSE_CHARS,
    )


async def generate_hybrid_coach(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
    transport: Optional[Transport] = None,
) -> HybridResult:
    """Generate original prose from admitted facts; reject risky text to fallback."""
    start = perf_counter()
    if not _authorized(access):
        return HybridResult(mode="denied", reason="workout_analysis_not_authorized")
    if os.getenv(FEATURE_FLAG, "").lower() not in {"1", "true", "yes"}:
        return HybridResult(mode="disabled", reason="flag_off")
    facts = build_admissible_facts(
        intelligence, access=access, permissions=permissions, language=language,
    )
    claims = select_deterministic_synthesis(facts)
    result = HybridResult(
        mode="deterministic_fallback", reason="provider_unavailable",
        text=_render(claims), claims=claims,
    )
    if intelligence.session_classification.type == "intervals":
        result.blockers.append("regularity_verdict_authority_unavailable")
    if not facts or not access.can("llm_access"):
        result.reason = "no_authorized_facts" if not facts else "llm_access_not_authorized"
        result.elapsed_ms = (perf_counter() - start) * 1000
        return result
    context = build_hybrid_context(
        intelligence, access=access, permissions=permissions, language=language,
    )
    prompt = json.dumps(context, ensure_ascii=False, allow_nan=False)
    system = (
        "You are a running coach responding naturally to the workout described only by the "
        "authorized evidence pack in the user message. Write an original, useful analysis in the "
        "requested language; in French, address the runner as tu. React to a concrete session "
        "observation. Be direct, precise, personal and sober. Length follows analytical value, "
        "never a word quota: a simple session may need only one or two sentences. Select the "
        "distinctive observation first; priority is guidance, not a checklist. Ignore secondary facts. "
        "Do not catalogue metrics. Recorded intervals deserve structure evidence, not an explanation "
        "from average HR. A measured historical difference is not physiological progress. "
        "Prefer established descriptive facts over uncertain classification. Never turn probable "
        "classification into certainty, even at high confidence. Do not routinely say 'semble', "
        "'probablement', 'il est possible', 'could indicate' or equivalent hesitant filler. "
        "Forbidden conclusions constrain what you assert; they are NOT caveats to recite. "
        "Mention a limitation only when it materially changes the conclusion you actually make. "
        "A factual average HR or interval count needs no automatic disclaimer. Only V3-authorized "
        "facts and conclusions are scientific authority. Do not invent or recalculate values; infer "
        "no LT1/LT2 from average HR, repetition regularity, progression from one workout, fatigue "
        "causes, or a new prescription. A history-relative classification is not physiological "
        "intensity. Never claim a conclusion excluded by permissions. No RAG or outside knowledge. "
        "Never add generic benefits (aerobic base, recovery, injury prevention, durable progress), "
        "congratulations, encouragement, or advice to close the text. No invented training goal. "
        "Return only the analysis prose, without headings, IDs, JSON, or a generic sign-off."
    )
    result.provider_attempted = True
    result.transport_kind = "injected" if transport is not None else "runindex"
    try:
        text, success, metadata = await asyncio.wait_for(
            (transport or _transport)(system, prompt, "anonymous", "c359_hybrid"),
            timeout=TIMEOUT_SECONDS,
        )
        duration = metadata.get("duration_sec") if success is True and isinstance(metadata, dict) else None
        if _finite(duration) and duration >= 0:
            result.provider_duration_sec = duration
        if success is True and isinstance(text, str):
            if ((isinstance(metadata, dict) and metadata.get("response_truncated") is True)
                    or len(text) > MAX_RESPONSE_CHARS):
                result.reason = "transport_response_limit"
            else:
                render_facts = build_admissible_facts(
                    intelligence, access=access, permissions=permissions, language=language,
                )
                valid, reason, checks = validate_generated_narrative(
                    text, render_facts, language=language,
                )
                if valid:
                    result.text = text.strip()
                    result.claims = []
                    result.mode = "generated_narrative"
                    result.reason = reason
                    result.verification_scope = "heuristic_risk_checks"
                    result.checks = checks
                else:
                    result.reason = reason
    except asyncio.TimeoutError:
        result.reason = "timeout"
    except Exception:
        # Neither rejected text nor exception details enter output or logs.
        result.reason = "invalid_response_or_provider_error"
    result.elapsed_ms = (perf_counter() - start) * 1000
    return result
