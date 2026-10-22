"""C360 offline experiment: validated narrative planning and controlled rendering.

V3 structured observations are the only runtime authority. The provider selects
only authorized fact IDs and operations; the server validates and renders them.
No route, knowledge loader, persistence or scientific calculation is added.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
from time import perf_counter
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from access_control import UserAccess
from narrative_coach_v3 import Transport, format_narrative_number
from workout_intelligence_v3_models import WorkoutIntelligenceV3

FEATURE_FLAG = "C359_HYBRID_COACH_ENABLED"
TIMEOUT_SECONDS = 8.0
MAX_RESPONSE_CHARS = 700
VERSION = "c360-validated-plan-1"

_REQUIRED_LIMITS = {
    "interval.count": ("no_repetition_durations", "regularity_verdict_unavailable"),
    "session.long": ("probable_not_certain", "duration_not_effort"),
    "session.kind": ("probable_not_certain",),
    "intensity.position": ("average_not_whole_effort", "no_time_in_zones", "no_physiological_cause"),
    "intensity.hr": ("no_physiological_zone", "average_not_whole_effort"),
    "session.unknown": ("unknown_not_easy",),
    "prescription.review": ("no_new_prescription", "no_inferred_cause"),
}

_LIMIT_TEXT = {
    "fr": {
        "no_repetition_durations": "La durée de chaque répétition n'est pas disponible.",
        "regularity_verdict_unavailable": "La régularité ne peut donc pas être jugée.",
        "probable_not_certain": "Ce type reste probable, pas certain.",
        "duration_not_effort": "La durée ne permet pas à elle seule d'estimer l'intensité.",
        "low_confidence": "La classification reste incertaine.",
        "relative_effort_not_physiological_intensity": "Cette classification est relative à ton historique, pas à une intensité physiologique.",
        "average_not_whole_effort": "Cette moyenne ne décrit pas chaque moment de l'effort.",
        "no_time_in_zones": "Elle n'indique pas le temps passé dans les zones.",
        "no_physiological_cause": "Elle n'en établit pas la cause.",
        "no_physiological_zone": "Cette moyenne seule ne permet pas d'établir une zone physiologique.",
        "unknown_not_easy": "Un type inconnu ne signifie pas que la séance était facile.",
        "missing_average_hr": "Aucune fréquence cardiaque moyenne n'est disponible.",
        "threshold_interpretation_unavailable": "Aucune zone physiologique ne peut être établie.",
        "not_proof_of_fitness": "Ce signal ne prouve pas un changement de forme.",
        "no_cause": "La cause de cette tendance n'est pas établie.",
        "terrain_weather_not_controlled": "Les effets du terrain et de la météo ne sont pas isolés.",
        "no_new_prescription": "Cette lecture ne remplace ni ne modifie la prescription.",
        "no_inferred_cause": "Aucune cause n'est déduite.",
    },
    "en": {
        "no_repetition_durations": "Individual repetition durations are unavailable.",
        "regularity_verdict_unavailable": "So repetition regularity cannot be judged.",
        "probable_not_certain": "This type remains probable, not certain.",
        "duration_not_effort": "Duration alone does not establish effort intensity.",
        "low_confidence": "The classification remains uncertain.",
        "relative_effort_not_physiological_intensity": "This classification is relative to your history, not physiological intensity.",
        "average_not_whole_effort": "This average does not describe every part of the effort.",
        "no_time_in_zones": "It does not show time spent in zones.",
        "no_physiological_cause": "It does not establish a cause.",
        "no_physiological_zone": "Average HR alone cannot establish a physiological zone.",
        "unknown_not_easy": "An unknown type does not mean the session was easy.",
        "missing_average_hr": "No average heart rate is available.",
        "threshold_interpretation_unavailable": "No physiological zone can be established.",
        "not_proof_of_fitness": "This signal does not prove a change in fitness.",
        "no_cause": "The cause of this trend is not established.",
        "terrain_weather_not_controlled": "Terrain and weather effects are not isolated.",
        "no_new_prescription": "This reading does not replace or change the prescription.",
        "no_inferred_cause": "No cause is inferred.",
    },
    "es": {
        "no_repetition_durations": "No están disponibles las duraciones de cada repetición.",
        "regularity_verdict_unavailable": "Por tanto, no se puede juzgar la regularidad.",
        "probable_not_certain": "Este tipo sigue siendo probable, no seguro.",
        "duration_not_effort": "La duración por sí sola no determina la intensidad del esfuerzo.",
        "low_confidence": "La clasificación sigue siendo incierta.",
        "relative_effort_not_physiological_intensity": "Esta clasificación es relativa a tu historial, no a la intensidad fisiológica.",
        "average_not_whole_effort": "Esta media no describe cada momento del esfuerzo.",
        "no_time_in_zones": "No indica el tiempo pasado en las zonas.",
        "no_physiological_cause": "No establece la causa.",
        "no_physiological_zone": "La FC media por sí sola no permite establecer una zona fisiológica.",
        "unknown_not_easy": "Un tipo desconocido no significa que la sesión fuera fácil.",
        "missing_average_hr": "No hay una frecuencia cardíaca media disponible.",
        "threshold_interpretation_unavailable": "No se puede establecer una zona fisiológica.",
        "not_proof_of_fitness": "Esta señal no demuestra un cambio de forma.",
        "no_cause": "No se establece la causa de esta tendencia.",
        "terrain_weather_not_controlled": "No se aíslan los efectos del terreno y del tiempo.",
        "no_new_prescription": "Esta lectura no sustituye ni modifica la prescripción.",
        "no_inferred_cause": "No se deduce ninguna causa.",
    },
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
            "usage_conditions": list(self.usage_conditions),
            "important_limits": list(self.important_limits), "priority": self.priority,
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
    mode: Literal["disabled", "denied", "deterministic_fallback", "planned_synthesis"]
    verdict: Literal["HOLD"] = "HOLD"
    reason: str
    verification_scope: Literal["none", "structured_plan"] = "none"
    blockers: list[str] = Field(default_factory=lambda: [
        "free_form_scientific_prose_not_accepted", "shared_adapter_700_char_truncation",
    ])
    text: str = ""
    claims: list[HybridClaim] = Field(default_factory=list)
    narrative_plan: Optional[dict] = None
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
            tr(f"Garmin a enregistré {e} phases d'effort et {r} phases de récupération.",
               f"Garmin recorded {e} effort phases and {r} recovery phases.",
               f"Garmin registró {e} fases de esfuerzo y {r} fases de recuperación."))
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
                tr(f"Sortie longue probable : {num(duration)} min, contre tes {num(usual)} min habituelles.",
                   f"Probable long run: {num(duration)} min versus your usual {num(usual)} min.",
                   f"Tirada larga probable: {num(duration)} min, frente a tus {num(usual)} min habituales.") + caveat)
    elif allowed_classification and cls.type in {"easy_run_probable", "steady_run_probable", "tempo_probable"}:
        label = {
            "easy_run_probable": tr("footing facile", "easy run", "carrera fácil"),
            "steady_run_probable": tr("sortie soutenue", "steady run", "carrera sostenida"),
            "tempo_probable": tr("tempo", "tempo run", "carrera tempo"),
        }[cls.type]
        uncertain = cls.confidence in {"low", "none"}
        history_qualification = history_classification
        uncertainty = tr("; le type reste incertain", "; the type remains uncertain",
                         "; el tipo sigue siendo incierto") if uncertain else ""
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
        add("session.kind", {"classification": cls.type}, {}, "probable_session_type",
            cls.confidence, conditions, limits, 45,
            ["session_classification.type", "session_classification.confidence"],
            tr(f"Type probable de ta séance : {label}{uncertainty}{relative_effort}.",
               f"Your probable session type: {label}{uncertainty}{relative_effort}.",
               f"Tipo probable de tu sesión: {label}{uncertainty}{relative_effort}."))

    hr = intensity.hr_used_bpm
    if _finite(hr):
        lt1, lt2 = intensity.lt1, intensity.lt2
        reliable = intensity.confidence in {"medium", "high"}
        threshold_ok = (
            reliable and lt1 is not None and lt2 is not None
            and _finite(lt1.value_bpm) and _finite(lt2.value_bpm)
            and lt1.value_bpm > 0 and lt2.value_bpm > lt1.value_bpm
            and lt1.confidence in {"medium", "high"} and lt2.confidence in {"medium", "high"}
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

    if prescription and allowed_classification and intelligence.prescription_assessment.status == "deviation":
        add("prescription.review", {"status": "deviation"}, {}, "review_training_prescription",
            "none", ["prescription_authorized", "training_is_prescription_authority"],
            ["no_new_prescription", "no_inferred_cause"], 85, ["prescription_assessment.status"],
            tr("Un écart à ta prescription a été relevé ; cette lecture ne la remplace ni ne la modifie.",
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
    return {"language": _language(language), "facts": [f.provider_fact() for f in facts]}


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


def validate_narrative_plan(
    payload: object, intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
) -> Optional[dict]:
    """Validate an ID-only plan against freshly rebuilt facts and permissions."""
    facts = build_admissible_facts(
        intelligence, access=access, permissions=permissions, language=language,
    )
    index = {fact.id: fact for fact in facts}
    if type(payload) is not dict or set(payload) != {
        "main_fact_id", "supporting_fact_ids", "conclusion_ids",
        "required_limit_ids", "detail_level",
    }:
        return None
    main_id = payload["main_fact_id"]
    supporting = payload["supporting_fact_ids"]
    conclusions = payload["conclusion_ids"]
    limits = payload["required_limit_ids"]
    detail = payload["detail_level"]
    if (type(main_id) is not str or type(supporting) is not list
            or any(type(item) is not str for item in supporting)
            or type(conclusions) is not dict or type(limits) is not dict
            or type(detail) is not str or detail not in {"concise", "balanced", "detailed"}):
        return None
    selected = [main_id, *supporting]
    maximum = {"concise": 1, "balanced": 2, "detailed": 3}[detail]
    if (not 1 <= len(selected) <= maximum or len(set(selected)) != len(selected)
            or any(item not in index for item in selected)
            or set(conclusions) != set(selected) or set(limits) != set(selected)):
        return None
    if "session.unknown" in selected and "intensity.hr" in selected:
        return None
    for fact_id in selected:
        fact = index[fact_id]
        if (type(conclusions[fact_id]) is not str
                or conclusions[fact_id] != fact.allowed_conclusion
                or type(limits[fact_id]) is not list
                or any(type(item) is not str for item in limits[fact_id])
                or len(set(limits[fact_id])) != len(limits[fact_id])
                or not set(_required_limit_ids(fact)).issubset(set(limits[fact_id]))
                or not set(limits[fact_id]).issubset(set(fact.important_limits))):
            return None
    return {
        "main_fact_id": main_id, "supporting_fact_ids": list(supporting),
        "conclusion_ids": dict(conclusions),
        "required_limit_ids": {key: list(value) for key, value in limits.items()},
        "detail_level": detail,
    }


_LIMITS_ALREADY_IN_ASSERTIONS = {
    "session.long": {"probable_not_certain"},
    "session.kind": {"probable_not_certain", "low_confidence",
                     "relative_effort_not_physiological_intensity"},
    "intensity.position": {"average_not_whole_effort"},
    "intensity.hr": {"no_physiological_zone", "average_not_whole_effort"},
    "session.unknown": {"missing_average_hr"},
    "trend.probable_improvement": {"not_proof_of_fitness"},
    "trend.stable": {"not_proof_of_fitness"},
    "trend.possible_decline": {"not_proof_of_fitness"},
    "prescription.review": {"no_new_prescription"},
}


def render_validated_plan(
    plan: dict, facts: tuple[AdmissibleFact, ...], *, language: str = "fr",
) -> list[HybridClaim]:
    """Render canonical assertions and allowlisted clauses; never accept provider prose."""
    lang = _language(language)
    index = {fact.id: fact for fact in facts}
    ids = [plan["main_fact_id"], *plan["supporting_fact_ids"]]
    rendered = []
    for position, fact_id in enumerate(ids):
        fact = index[fact_id]
        text = fact.assertion
        already_stated = _LIMITS_ALREADY_IN_ASSERTIONS.get(fact_id, set())
        clauses = [
            _LIMIT_TEXT[lang][limit]
            for limit in plan["required_limit_ids"][fact_id]
            if limit not in already_stated
        ]
        if clauses:
            text = text.rstrip() + " " + " ".join(clauses)
        if position:
            prefix = {
                "fr": ("En complément, ", "Autre repère utile : "),
                "en": ("Alongside that, ", "Another useful detail: "),
                "es": ("Además, ", "Como dato adicional: "),
            }[lang][position - 1]
            text = prefix + text[0].lower() + text[1:]
        rendered.append(HybridClaim(
            id=fact.id, text=text, evidence_ids=[fact.id],
            conclusion_ids=[fact.allowed_conclusion], evidence_refs=list(fact.source_paths),
        ))
    return rendered


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def _transport(system, prompt, user, context_type):
    from llm_coach import _call_gpt

    return await _call_gpt(system, prompt, user, context_type, sanitize_errors=True)


async def generate_hybrid_coach(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
    transport: Optional[Transport] = None,
) -> HybridResult:
    """Request an ID-only narrative plan, validate it, then render locally.

    The unchanged shared adapter truncates at 700 characters. Raw responses
    exceeding that boundary or already truncated JSON fail closed. No provider
    prose is accepted or interpreted.
    """
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
        "Create a narrative plan, not prose. Select the most characteristic authorized fact as main, "
        "then zero to two useful supporting facts in the order to explain them. Choose concise for one "
        "fact, balanced for up to two, or detailed for up to three. For each selected fact, use only "
        "its exact allowed conclusion ID and preserve every required limit ID. Do not repeat facts. "
        "Never infer physiology, causes, recovery, fitness, regularity, zones, or prescriptions. "
        "Return only JSON with exactly these keys: "
        '{"main_fact_id":"ID","supporting_fact_ids":["ID"],'
        '"conclusion_ids":{"ID":"allowed conclusion ID"},'
        '"required_limit_ids":{"ID":["required limit ID"]},'
        '"detail_level":"concise|balanced|detailed"}. '
        "No natural-language text is accepted; the server renders the validated plan."
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
            if len(text) > MAX_RESPONSE_CHARS:
                result.reason = "transport_response_limit"
            else:
                payload = json.loads(text, object_pairs_hook=_unique_object)
                plan = validate_narrative_plan(
                    payload, intelligence, access=access, permissions=permissions, language=language,
                )
                if plan is not None:
                    result.narrative_plan = plan
                    result.claims = render_validated_plan(plan, facts, language=language)
                    result.text = _render(result.claims)
                    result.mode = "planned_synthesis"
                    result.reason = "validated_narrative_plan"
                    result.verification_scope = "structured_plan"
                else:
                    result.reason = "invalid_narrative_plan"
    except asyncio.TimeoutError:
        result.reason = "timeout"
    except Exception:
        # Neither rejected text nor exception details enter output or logs.
        result.reason = "invalid_response_or_provider_error"
    result.elapsed_ms = (perf_counter() - start) * 1000
    return result
