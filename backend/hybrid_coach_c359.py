"""C359 offline experiment: free synthesis requested, independent proof on HOLD.

V3 structured observations are the only runtime authority. Literal certificates
prove only a selected subset of our assertions, never arbitrary entailment.
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
VERSION = "c359-selected-facts-hold-3"


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
    mode: Literal["disabled", "denied", "deterministic_fallback", "literal_subset_verified"]
    verdict: Literal["HOLD"] = "HOLD"
    reason: str
    verification_scope: Literal["none", "literal_assertions_only"] = "none"
    blockers: list[str] = Field(default_factory=lambda: [
        "free_semantic_verification_unavailable", "shared_adapter_700_char_truncation",
    ])
    text: str = ""
    claims: list[HybridClaim] = Field(default_factory=list)
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


def validate_hybrid_response(
    payload: object, intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
) -> Optional[list[HybridClaim]]:
    """Fresh literal assertion certificates only, NOT a semantic verifier.

    Exact assertions bind values, units, confidence and inseparable limits.
    Every output character is accounted for; no unchecked connectors, hidden
    sentences, reference laundering or external verifier callback can pass.
    """
    facts = build_admissible_facts(
        intelligence, access=access, permissions=permissions, language=language,
    )
    index = {fact.id: fact for fact in facts}
    if type(payload) is not dict or set(payload) != {"text", "claims"}:
        return None
    if type(payload["text"]) is not str or type(payload["claims"]) is not list:
        return None
    if not 1 <= len(payload["claims"]) <= 3:
        return None
    certified = []
    seen = set()
    for claim in payload["claims"]:
        if type(claim) is not dict or set(claim) != {"text", "evidence_ids", "conclusion_ids"}:
            return None
        ids = claim["evidence_ids"]
        if type(ids) is not list or len(ids) != 1 or type(ids[0]) is not str:
            return None
        fact = index.get(ids[0])
        if fact is None or fact.id in seen:
            return None
        if (type(claim["text"]) is not str or type(claim["conclusion_ids"]) is not list
                or any(type(id) is not str for id in claim["conclusion_ids"])
                or claim["conclusion_ids"] != [fact.allowed_conclusion]
                or claim["text"] != fact.assertion):
            return None
        seen.add(fact.id)
        certified.append(_claim(fact))
    return certified if payload["text"] == _render(certified) else None


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
    """One free synthesis request; unprovable prose withheld without logging.

    The unchanged shared adapter truncates at 700 characters. Raw responses
    exceeding that boundary or already truncated JSON fail closed.
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
        "Write a useful, natural running-coach synthesis in the requested language; never prescribe. "
        "In French, always address the runner with tu (tutoiement), never vous. "
        "Do not mention administrative V3 or Training implementation internals in the prose. "
        "Express uncertainty where material to the main conclusions, not as repeated generic reservations. "
        "Freely select, prioritize, reorder and connect useful conclusions from the authorized facts. "
        "Do not follow a synonym list or copy a supplied narrative: no wording is prescribed. "
        "Respect each fact's values, units, confidence, usage conditions and important limits. "
        "Do not infer causes, recovery, fitness, regularity, zones or advice beyond the allowed conclusions. "
        'Return only JSON {"text":"complete synthesis","claims":'
        '[{"text":"factual assertion","evidence_ids":["fact ID"],"conclusion_ids":["allowed conclusion ID"]}]}. '
        "Report all factual assertions, including connections; choose one to three useful claims. "
        "An independent proof gate may withhold unverifiable free prose; declared IDs are not proof. "
        "The existing transport has a 700-character raw response boundary."
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
                verified = validate_hybrid_response(
                    payload, intelligence, access=access, permissions=permissions, language=language,
                )
                if verified is not None:
                    result.claims, result.text = verified, _render(verified)
                    result.mode = "literal_subset_verified"
                    result.reason = "literal_subset_only_free_synthesis_on_hold"
                    result.verification_scope = "literal_assertions_only"
                else:
                    result.reason = "semantic_verification_unavailable"
    except asyncio.TimeoutError:
        result.reason = "timeout"
    except Exception:
        # Neither rejected text nor exception details enter output or logs.
        result.reason = "invalid_response_or_provider_error"
    result.elapsed_ms = (perf_counter() - start) * 1000
    return result
