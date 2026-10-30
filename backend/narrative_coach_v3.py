"""Read-only narrative rendering of canonical V3 and same-pass V2 synthesis.

Safety tradeoff: the LLM is an editor, not a free-text author. It may choose
approved sentence variants and reorder claims within sections, but cannot add,
omit or rewrite claims. Existing evidence paths alone do not prove a sentence.
The trusted builder binds each sentence to typed V3 evidence; the validator
accepts only that exact closed vocabulary. Optional V2 phase metrics and
versioned coach regularity judgments are reused without recalculation. Numeric
dispersion alone is not promoted into a categorical regularity verdict.
No coach text, source-path strings,
identifiers, dates, or other user-controlled strings are sent to the provider.
Canonical V2 synthesis is rendered whole and locally, with its own reserves;
it never enters the optional editor or its cross-request cache.

The optional LLM costs nothing by default (C355_NARRATIVE_LLM_ENABLED=false).
When enabled, one isolated llm_coach._call_gpt call has a bounded outer timeout.
Only successful validated results enter a bounded process-local LRU, protected
by a thread lock and keyed by sanitized context, language and generation version.
No outage fallbacks, database writes, user identifiers or prompt telemetry.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import logging
import math
import os
from threading import Lock
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from narrative_coach_v3_models import NarrativeCoachV3
from workout_intelligence_v3_models import WorkoutIntelligenceV3

if TYPE_CHECKING:
    from coach_language import CoachLanguageV1
    from workout_analysis_v2 import WorkoutAnalysisPhaseAnalysis, WorkoutAnalysisV2Response

GENERATION_VERSION = "c388-controlled-1"
LLM_TIMEOUT_SECONDS = 8.0
CACHE_MAX_ENTRIES = 128
MAX_RESPONSE_CHARS = 24000
_LOGGER = logging.getLogger(__name__)
_CACHE: OrderedDict[str, "NarrativeCoachV3"] = OrderedDict()
_CACHE_LOCK = Lock()
Transport = Callable[[str, str, str, str], Awaitable[tuple[Optional[str], bool, dict]]]


def _language(language: str) -> str:
    normalized = language.lower().replace("_", "-").split("-")[0]
    return normalized if normalized in {"fr", "en", "es"} else "en"


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value: Any) -> bool:
    return _finite(value) and value >= 0 and value == int(value)


def format_narrative_number(value: Any, language: str = "en", *, signed: bool = False) -> Optional[str]:
    """Format display-only metrics; absent/non-finite values never become zero."""
    if not _finite(value):
        return None
    magnitude = f"{abs(value):.1f}".removesuffix(".0")
    sign = ("−" if value < 0 else "+") if magnitude != "0" and (value < 0 or signed) else ""
    if _language(language) in {"fr", "es"}:
        magnitude = magnitude.replace(".", ",")
    return sign + magnitude


def _approved_repetition_judgment(coach_language, effort_count):
    """Read only the existing versioned categorical judgment, never its prose."""
    if coach_language is None:
        return None
    from coach_language import CoachLanguageV1

    if type(coach_language) is not CoachLanguageV1 or coach_language.version != "v1":
        return None
    approved = []
    for index, item in enumerate(coach_language.conclusions):
        if (item.code not in {"coach.repetitions.pacing", "coach.repetitions.pace_hr"}
                or not item.available or item.category != "repetitions" or item.kind != "conclusion"):
            continue
        metadata, evidence = item.metadata, item.evidence
        if (metadata.get("judgment_version") != "v1"
                or metadata.get("comparison_scope") != "all_comparable_efforts"
                or metadata.get("metric") != "mean_absolute_deviation_from_median"
                or metadata.get("regularity_band") not in {"homogeneous", "noticeable", "variable"}
                or metadata.get("comparability_basis") not in {"duration", "distance"}):
            continue
        count = evidence.get("total_effort_count")
        compared = evidence.get("comparable_effort_count")
        deviation = evidence.get("absolute_deviation_sec_per_km")
        median = evidence.get("median_pace_sec_per_km")
        if (not _count(count) or count < 3 or count != effort_count
                or not _count(compared) or compared != count
                or not _finite(deviation) or deviation < 0
                or not _finite(median) or median <= 0):
            continue
        approved.append({
            "band": metadata["regularity_band"], "count": int(count),
            "deviation": deviation, "index": index,
        })
    # Canonical output contains one repetition judgment. Ambiguity is not
    # resolved by selecting whichever conclusion happens to come first.
    return approved[0] if len(approved) == 1 else None


def _synthesis_claims(analysis, intelligence, language):
    """Consume only the canonical, same-pass server response, never client text.

    V2 has already gated environment, comparability and measurement confidence.
    Synthesis has no confidence field: admission is its available status plus
    traceability to the selected, available V2 sources, not V3 classification.
    """
    from workout_analysis_v2 import WorkoutAnalysisV2Response
    from coach_session_synthesis import synthesis_conclusion_text

    if (type(analysis) is not WorkoutAnalysisV2Response or analysis.version != "v2"
            or analysis.workout.id != intelligence.workout_id):
        return []
    synthesis = analysis.session_synthesis
    if synthesis is None or synthesis.status != "available" or synthesis.primary is None:
        return []
    items = [synthesis.primary, *synthesis.supporting]
    limits = {limit.code for limit in synthesis.limitations}
    if (any(item.code.startswith("coach.history.") for item in items)
            and "synthesis.history_descriptive" not in limits):
        return []
    if (any("heart_rate_change_bpm" in item.evidence
            or "heart_rate_difference_bpm" in item.evidence
            or item.code == "fact.effort_hr_evolution" for item in items)
            and "synthesis.hr_observation" not in limits):
        return []
    sources = {}
    if analysis.coach_language is not None and analysis.coach_language.version == "v1":
        for index, item in enumerate(analysis.coach_language.conclusions):
            if item.available and item.code in {
                "coach.pacing", "coach.execution.pace_hr",
                "coach.repetitions.pacing", "coach.repetitions.pace_hr",
                "coach.history.pace", "coach.history.hr",
            }:
                sources[f"coach_language.conclusions[{index}]"] = item
    for index, item in enumerate(analysis.meaning.factual_observations):
        if item.code in {
            "fact.pace_change", "fact.negative_split",
            "fact.effort_extremes", "fact.effort_hr_evolution",
        }:
            sources[f"meaning.factual_observations[{index}]"] = item

    claims = []
    for index, item in enumerate(items):
        if len(item.source_paths) != 1 or not item.text.strip():
            return []
        path = item.source_paths[0]
        source = sources.get(path)
        if source is not None:
            if item.code != source.code or item.evidence != source.evidence:
                return []
            approved_texts = {source.text}
            if (item.code == "coach.history.pace"
                    and {"current_pace_min_km", "baseline_pace_min_km"} <= source.evidence.keys()):
                approved_texts.add(synthesis_conclusion_text(source, language))
            if item.text not in approved_texts:
                return []
            if item.code.startswith("coach.repetitions.") and source.kind == "conclusion":
                judgment = _approved_repetition_judgment(
                    analysis.coach_language, len(analysis.phase_analysis.efforts),
                )
                if judgment is None or not analysis.phase_analysis.available:
                    return []
        elif item.code in {"fact.repetitions", "fact.recoveries"}:
            expected_path = "phase_analysis." + (
                "efforts" if item.code == "fact.repetitions" else "recoveries"
            )
            rows = getattr(analysis.phase_analysis, expected_path.split(".")[1])
            if (path != expected_path or not analysis.phase_analysis.available
                    or len(rows) < 2 or item.evidence.get("count") != len(rows)
                    or rows[0].duration_s != item.evidence.get("duration_s")):
                return []
        else:
            return []
        claims.append({
            "id": f"v2.synthesis.{index}", "section": "analysis" if index == 0 else "interpretation",
            "variants": [item.text],
            "evidence_refs": [
                f"session_synthesis.{'primary' if index == 0 else 'supporting.' + str(index - 1)}",
                *item.source_paths,
            ],
        })
    for index, limit in enumerate(synthesis.limitations):
        claims.append({
            "id": f"v2.limit.{index}", "section": "limitations",
            "variants": [limit.text],
            "evidence_refs": [f"session_synthesis.limitations.{index}", *limit.source_paths],
        })
    return claims


def build_narrative_context(
    intelligence: Optional[WorkoutIntelligenceV3], language: str = "en",
    *, phase_analysis: Optional[WorkoutAnalysisPhaseAnalysis] = None,
    coach_language: Optional[CoachLanguageV1] = None,
    v2_analysis: Optional[WorkoutAnalysisV2Response] = None,
) -> dict:
    """Return a minimal, PII-free approved-claim catalog (not raw V3).

    Refs are relative to WorkoutIntelligenceV3, except ``phase_analysis.*``,
    ``coach_language.*``, ``meaning.*`` and ``session_synthesis.*``, which
    document the supplied canonical WorkoutAnalysisV2Response sources.
    V2 evidence must come from the same scoped loader pass. No I/O or
    scientific recalculation occurs.
    Missing metrics stay missing. Arbitrary coach text/advice is never copied.
    """
    lang = _language(language)
    claims: list[dict] = []

    def number(value, *, signed=False):
        return format_narrative_number(value, lang, signed=signed)

    def add(claim_id, section, en, fr, es, refs=(), variants=None):
        texts = {"en": en, "fr": fr, "es": es}
        sentences = [texts[lang]]
        if variants:
            sentences.append(variants[lang])
        claims.append({"id": claim_id, "section": section, "variants": sentences,
                       "evidence_refs": list(refs)})

    if intelligence is None:
        add("missing.headline", "headline", "Session analysis unavailable",
            "Analyse de séance indisponible", "Análisis de la sesión no disponible")
        add("missing.analysis", "analysis", "The session data needed for this analysis is unavailable.",
            "Les données nécessaires à l'analyse de cette séance sont indisponibles.",
            "Los datos necesarios para analizar esta sesión no están disponibles.")
        add("missing.interpretation", "interpretation",
            "The session cannot be interpreted without its evidence.",
            "La séance ne peut pas être interprétée sans ses données.",
            "La sesión no puede interpretarse sin sus datos.")
        add("missing.limit", "limitations", "No intensity, trend or prescription judgment is available.",
            "Aucun jugement d'intensité, de tendance ou de conformité à la prescription n'est disponible.",
            "No hay valoración de intensidad, tendencia o conformidad con la prescripción.")
        return {"generation_version": GENERATION_VERSION, "language": lang,
                "available": False, "claims": claims}

    v3 = intelligence
    cls = v3.session_classification
    intensity = v3.intensity_assessment
    trend = v3.performance_trend
    prescription = v3.prescription_assessment
    kind_names = {
        "intervals": ("An interval session", "Une séance fractionnée", "Una sesión de intervalos"),
        "easy_run_probable": ("Probably an easy run", "Probablement un footing facile", "Probablemente un rodaje suave"),
        "steady_run_probable": ("Probably a steady run", "Probablement une sortie soutenue modérée", "Probablemente un rodaje sostenido moderado"),
        "tempo_probable": ("Probably a tempo session", "Probablement une séance tempo", "Probablemente una sesión tempo"),
        "long_run_probable": ("Probably a long run", "Probablement une sortie longue", "Probablemente una tirada larga"),
        "unknown": ("Session type uncertain", "Type de séance incertain", "Tipo de sesión incierto"),
    }
    add("session.kind", "headline", *kind_names[cls.type],
        refs=("session_classification.type", "session_classification.confidence",
              "session_classification.decision_tier"))
    if cls.type == "unknown":
        add("session.unknown", "analysis",
            "The available evidence does not reliably identify the session type.",
            "Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable.",
            "Los datos disponibles no permiten identificar con fiabilidad el tipo de sesión.",
            refs=("session_classification.type",))

    if cls.type == "intervals":
        efforts = cls.evidence.get("effort_count")
        recoveries = cls.evidence.get("recovery_count")
        if _count(efforts) and _count(recoveries):
            n, r = int(efforts), int(recoveries)
            add("interval.count", "analysis",
                f"Garmin recorded {n} effort phases and {r} recovery phases.",
                f"Garmin a enregistré {n} phases d'effort et {r} phases de récupération.",
                f"Garmin registró {n} fases de esfuerzo y {r} fases de recuperación.",
                refs=("session_classification.evidence.effort_count",
                      "session_classification.evidence.recovery_count"),
                variants={
                    "en": f"The recorded structure contains {n} effort phases, separated by recovery phases ({r} recorded).",
                    "fr": f"La structure enregistrée contient {n} phases d'effort, séparées par des récupérations ({r} enregistrées).",
                    "es": f"La estructura registrada contiene {n} fases de esfuerzo, separadas por recuperaciones ({r} registradas).",
                })
        # V3 exposes availability (via confidence/limitations), never the
        # regularity judgment itself. High confidence must not mean "regular".
        regularity = phase_analysis.effort_regularity if phase_analysis is not None else None
        judgment = _approved_repetition_judgment(coach_language, efforts)
        usable_spread = (
            phase_analysis is not None and phase_analysis.available
            and regularity.available
            and _count(efforts) and regularity.effort_count == efforts
            and 2 <= regularity.pace_sample_count <= regularity.effort_count
            and _finite(regularity.pace_dispersion_sec_per_km)
            and regularity.pace_dispersion_sec_per_km >= 0
        )
        if usable_spread and judgment is None:
            spread = number(regularity.pace_dispersion_sec_per_km)
            sampled, total = regularity.pace_sample_count, regularity.effort_count
            add("interval.spread", "analysis",
                f"The recorded pace standard deviation is {spread} s/km across {sampled} of {total} effort phases.",
                f"L'écart-type des allures enregistré est de {spread} s/km sur {sampled} des {total} phases d'effort.",
                f"La desviación estándar de los ritmos registrada es de {spread} s/km en {sampled} de las {total} fases de esfuerzo.",
                refs=("phase_analysis.effort_regularity",
                      "session_classification.evidence.effort_count"))
            if regularity.partial_comparison:
                add("interval.partial", "limitations",
                    "The comparison is partial; it does not cover all recorded efforts.",
                    "La comparaison est partielle ; elle ne couvre pas tous les efforts enregistrés.",
                    "La comparación es parcial; no abarca todos los esfuerzos registrados.",
                    refs=("phase_analysis.effort_regularity.partial_comparison",
                          "phase_analysis.effort_regularity.pace_sample_count",
                          "phase_analysis.effort_regularity.effort_count"))
        cohort_available = (
            phase_analysis is not None and phase_analysis.available
            and _count(efforts) and regularity.effort_count == efforts
            and regularity.comparability_basis in {"duration", "distance"}
            and 2 <= regularity.comparable_effort_count <= regularity.effort_count
        )
        if cohort_available:
            comparable, total = regularity.comparable_effort_count, regularity.effort_count
            en, fr, es = (
                ("duration", "durée", "duración") if regularity.comparability_basis == "duration"
                else ("distance", "distance", "distancia")
            )
            add("interval.cohort", "interpretation",
                f"To compare like with like, {comparable} of the {total} efforts were grouped by similar {en}; different-sized efforts should not be treated as equivalent repetitions.",
                f"Pour comparer ce qui est comparable, {comparable} des {total} efforts ont été regroupés selon une {fr} similaire ; des efforts de tailles différentes ne doivent pas être traités comme des répétitions équivalentes.",
                f"Para comparar esfuerzos equivalentes, se agruparon {comparable} de los {total} esfuerzos por {es} similar; los esfuerzos de distinto tamaño no deben tratarse como repeticiones equivalentes.",
                refs=("phase_analysis.effort_regularity.comparable_effort_count",
                      "phase_analysis.effort_regularity.effort_count",
                      "phase_analysis.effort_regularity.comparability_basis"))
        if judgment is not None:
            n = judgment["count"]
            gap = number(judgment["deviation"])
            labels = {
                "homogeneous": ("Homogeneous paces", "Allures homogènes", "Ritmos homogéneos"),
                "noticeable": ("Noticeable pace variations", "Variations d'allure perceptibles", "Variaciones de ritmo perceptibles"),
                "variable": ("Large pace variations", "Variations d'allure importantes", "Variaciones de ritmo importantes"),
            }
            en, fr, es = labels[judgment["band"]]
            path = f"coach_language.conclusions.{judgment['index']}"
            add("interval.judgment", "interpretation",
                f"{en} across your {n} comparable repetitions: an average gap of {gap} s/km from the median pace.",
                f"{fr} sur tes {n} répétitions comparables : un écart moyen de {gap} s/km par rapport à l'allure médiane.",
                f"{es} en tus {n} repeticiones comparables: una diferencia media de {gap} s/km respecto a la mediana de los ritmos.",
                refs=(f"{path}.code", f"{path}.metadata.judgment_version",
                      f"{path}.metadata.comparison_scope", f"{path}.metadata.regularity_band",
                      f"{path}.metadata.metric", f"{path}.evidence.comparable_effort_count",
                      f"{path}.evidence.total_effort_count",
                      f"{path}.evidence.absolute_deviation_sec_per_km"))
        elif usable_spread:
            add("interval.execution", "interpretation",
                "The measure describes pace differences between the efforts analysed; this alone is not enough to determine whether the repetitions were consistent.",
                "La mesure porte sur les écarts d'allure entre les efforts analysés ; elle ne suffit pas à déterminer si les répétitions ont été régulières.",
                "La medida describe las diferencias de ritmo entre los esfuerzos analizados; por sí sola no basta para determinar si las repeticiones fueron regulares.",
                refs=("phase_analysis.effort_regularity",))
        else:
            add("interval.execution", "interpretation",
                "The available data does not allow us to assess the consistency of the repetitions; this does not mean they were inconsistent.",
                "Les données disponibles ne permettent pas d'évaluer la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières.",
                "Los datos disponibles no permiten evaluar la regularidad de las repeticiones; esto no significa que fueran irregulares.",
                refs=("session_classification.type", "session_classification.limitations") + (
                    ("phase_analysis.available", "phase_analysis.effort_regularity.available")
                    if phase_analysis is not None else ()))
        unavailable = (
            "effort_regularity_unavailable" in cls.limitations if phase_analysis is None
            else not phase_analysis.available or not regularity.available
        )
        if judgment is not None:
            pass
        elif unavailable:
            add("interval.regularity", "limitations",
                "There is not enough data to determine whether the repetitions were consistent.",
                "Les données sont insuffisantes pour déterminer si les répétitions ont été régulières.",
                "No hay datos suficientes para determinar si las repeticiones fueron regulares.",
                refs=(("session_classification.limitations",) if phase_analysis is None
                      else ("phase_analysis.available", "phase_analysis.effort_regularity.available")))
        elif phase_analysis is not None:
            add("interval.regularity", "limitations",
                "The measured pace variations alone are not enough to draw a conclusion about the consistency of the repetitions.",
                "Les variations d'allure mesurées ne suffisent pas, à elles seules, à conclure sur la régularité des répétitions.",
                "Las variaciones de ritmo medidas no bastan, por sí solas, para concluir si las repeticiones fueron regulares.",
                refs=("phase_analysis.effort_regularity",))
        else:
            add("interval.regularity", "limitations",
                "The available information is not enough to draw a conclusion about the consistency of the repetitions.",
                "Les informations disponibles ne permettent pas de conclure sur la régularité des répétitions.",
                "La información disponible no permite concluir si las repeticiones fueron regulares.",
                refs=("session_classification.confidence", "session_classification.limitations"))

    if _finite(intensity.hr_used_bpm) and cls.type != "intervals":
        hr = number(intensity.hr_used_bpm)
        add("intensity.hr", "analysis", f"Your average heart rate for this session was {hr} bpm.",
            f"Ta fréquence cardiaque moyenne sur cette séance était de {hr} bpm.",
            f"Tu FC media en esta sesión fue de {hr} lpm.",
            refs=("intensity_assessment.hr_used_bpm",))
        add("intensity.average", "limitations",
            "Average heart rate does not describe time in each zone or individual effort phases.",
            "La FC moyenne ne décrit ni le temps dans chaque zone ni les phases d'effort individuelles.",
            "La FC media no describe el tiempo en cada zona ni las fases de esfuerzo individuales.",
            refs=("intensity_assessment.hr_metric",))
    if intensity.position != "unknown" and cls.type != "intervals":
        positions = {
            "below_LT1": ("below LT1", "sous LT1", "por debajo de LT1"),
            "between_LT1_LT2": ("between LT1 and LT2", "entre LT1 et LT2", "entre LT1 y LT2"),
            "above_LT2": ("above LT2", "au-dessus de LT2", "por encima de LT2"),
        }
        en, fr, es = positions[intensity.position]
        hr = number(intensity.hr_used_bpm)
        add("intensity.position", "analysis",
            f"Your average heart rate{' (' + hr + ' bpm)' if hr else ''} sits {en}, using your personal thresholds.",
            f"Ta fréquence cardiaque moyenne{' (' + hr + ' bpm)' if hr else ''} se situe {fr}, selon tes seuils personnels.",
            f"Tu FC media{' (' + hr + ' lpm)' if hr else ''} se sitúa {es}, según tus umbrales personales.",
            refs=("intensity_assessment.hr_used_bpm", "intensity_assessment.position",
                  "intensity_assessment.lt1", "intensity_assessment.lt2"))
    if intensity.lt1 is None and cls.type != "intervals":
        add("intensity.lt1_unknown", "limitations",
            "A reliable personal LT1 is unavailable; an easy label does not establish that the session was below LT1.",
            "Un LT1 personnel fiable est indisponible ; une étiquette facile ne prouve pas que la séance était sous LT1.",
            "No hay un LT1 personal fiable; la etiqueta suave no demuestra que la sesión estuviera por debajo de LT1.",
            refs=("intensity_assessment.lt1",))
    if cls.decision_tier == "individual_history":
        rel = cls.relative_effort
        relative_label = {
            "easy_run_probable": ("relatively easy", "relativement facile", "relativamente suave"),
            "steady_run_probable": ("relatively sustained", "relativement soutenu", "relativamente sostenido"),
        }.get(cls.type)
        if relative_label and rel.status == "used" and rel.reference_count > 0:
            en, fr, es = relative_label
            count = rel.reference_count
            add("intensity.relative", "analysis",
                f"Compared with your {count} personal reference sessions, this effort looks {en}.",
                f"Par rapport à tes {count} séances de référence, cet effort paraît {fr}.",
                f"En comparación con tus {count} sesiones personales de referencia, este esfuerzo parece {es}.",
                refs=("session_classification.type", "session_classification.decision_tier",
                      "session_classification.relative_effort.status",
                      "session_classification.relative_effort.reference_count"))
        else:
            add("intensity.relative", "limitations",
                "The classification is relative to personal history, not a physiological zone assessment.",
                "La classification est relative à l'historique personnel, pas à une zone physiologique.",
                "La clasificación es relativa al historial personal, no a una zona fisiológica.",
                refs=("session_classification.decision_tier", "session_classification.relative_effort.status"))
        if rel.status == "used" and rel.reference_count > 0:
            add("intensity.relative_count", "analysis",
                f"This relative assessment uses {rel.reference_count} of your earlier sessions.",
                f"Cette évaluation relative utilise {rel.reference_count} de tes séances antérieures.",
                f"Esta evaluación relativa utiliza {rel.reference_count} de tus sesiones anteriores.",
                refs=("session_classification.relative_effort.reference_count",))

    comparison = v3.historical_comparison
    pace = comparison.pace_at_comparable_hr
    if (comparison.status == "available" and comparison.comparability in {"strong", "moderate"}
            and pace.reference_count >= 3 and _finite(pace.pace_difference_sec_per_km)):
        delta = number(pace.pace_difference_sec_per_km, signed=True)
        add("comparison.pace", "analysis",
            f"At comparable heart rate, this session's pace difference is {delta} s/km versus {pace.reference_count} references (session minus reference); this alone is not a trend.",
            f"À FC comparable, l'écart d'allure de cette séance est de {delta} s/km sur {pace.reference_count} références (séance moins référence) ; cela seul n'est pas une tendance.",
            f"A FC comparable, la diferencia de ritmo de esta sesión es de {delta} s/km frente a {pace.reference_count} referencias (sesión menos referencia); esto por sí solo no es una tendencia.",
            refs=("historical_comparison.status", "historical_comparison.comparability",
                  "historical_comparison.pace_at_comparable_hr.reference_count",
                  "historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km"))
    strong_trend = (
        trend.confidence in {"medium", "high"}
        and trend.observation_count > 0 and _finite(trend.median_change_sec_per_km)
    )
    trend_refs = ("performance_trend.status", "performance_trend.confidence",
                  "performance_trend.observation_count", "performance_trend.median_change_sec_per_km")
    if cls.type == "intervals":
        pass
    elif trend.status == "probable_improvement" and strong_trend and trend.median_change_sec_per_km < 0:
        n, gain = trend.observation_count, number(abs(trend.median_change_sec_per_km))
        span = trend.span_days if _count(trend.span_days) else None
        en_span = f" over {span} days" if span is not None else ""
        fr_span = f" sur {span} jours" if span is not None else ""
        es_span = f" durante {span} días" if span is not None else ""
        add("trend.improvement", "interpretation",
            f"Your median pace is {gain} s/km faster at comparable heart rate across {n} observations{en_span}: an encouraging sign of probable improvement, not proof of fitness gain.",
            f"Ton allure médiane est plus rapide de {gain} s/km à fréquence cardiaque comparable sur {n} observations{fr_span} : un signe encourageant d'amélioration probable, pas une preuve de gain de forme.",
            f"Tu ritmo mediano es {gain} s/km más rápido a FC comparable en {n} observaciones{es_span}: una señal alentadora de mejora probable, no una prueba de mejora de forma.",
            refs=trend_refs + (("performance_trend.span_days",) if span is not None else ()))
    elif trend.status == "stable" and strong_trend:
        n, delta = trend.observation_count, number(trend.median_change_sec_per_km, signed=True)
        add("trend.stable", "interpretation",
            f"Your history shows a stable trend across {n} observations (median pace change {delta} s/km); this does not establish improvement.",
            f"Sur tes {n} observations comparables, la tendance reste stable (variation d'allure médiane de {delta} s/km) : ta progression n'est pas encore démontrée.",
            f"Tu historial muestra una tendencia estable en {n} observaciones (cambio de ritmo mediano de {delta} s/km); esto no demuestra una mejora.",
            refs=trend_refs)
    elif trend.status == "possible_decline" and strong_trend:
        delta = number(trend.median_change_sec_per_km, signed=True)
        add("trend.decline", "interpretation",
            f"Your history suggests a possible decline across {trend.observation_count} observations (median pace change {delta} s/km), not a confirmed loss of fitness.",
            f"Ton historique suggère une baisse possible sur {trend.observation_count} observations (variation d'allure médiane de {delta} s/km), pas une perte de forme confirmée.",
            f"Tu historial sugiere un posible descenso en {trend.observation_count} observaciones (cambio de ritmo mediano de {delta} s/km), no una pérdida de forma confirmada.",
            refs=trend_refs)
    else:
        add("trend.insufficient", "interpretation",
            "Your comparable history is insufficient to conclude confidently that you are improving or declining.",
            "Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent.",
            "Tu historial comparable es insuficiente para concluir con confianza una mejora o un descenso.",
            refs=("performance_trend.status", "performance_trend.confidence"))
    if cls.type != "intervals":
        add("trend.caution", "limitations",
            "Historical comparisons are observational, not proof of a physiological change.",
            "Les comparaisons historiques sont des observations, pas la preuve d'un changement physiologique.",
            "Las comparaciones históricas son observaciones, no pruebas de un cambio fisiológico.",
            refs=("historical_comparison.status", "performance_trend.status"))

    if "no_splits_whole_session_averages_only" in cls.limitations:
        add("session.no_splits", "limitations",
            "No splits are available; only supplied whole-session observations can be described.",
            "Aucun split n'est disponible ; seules les observations globales fournies peuvent être décrites.",
            "No hay parciales disponibles; solo pueden describirse las observaciones globales proporcionadas.",
            refs=("session_classification.limitations",))
    if "no_recorded_session_structure" in cls.limitations:
        add("session.no_structure", "limitations",
            "The recorded session structure is unknown.",
            "La structure enregistrée de la séance est inconnue.",
            "La estructura registrada de la sesión es desconocida.",
            refs=("session_classification.limitations",))
    prescription_text = {
        "consistent": (
            "Your session type is consistent with the recorded prescription; this does not verify every target.",
            "Ton type de séance correspond à la prescription enregistrée ; cela ne vérifie pas chaque objectif.",
            "Tu tipo de sesión es conforme con la prescripción registrada; esto no comprueba cada objetivo."),
        "deviation": (
            "Your session type shows a deviation from the recorded prescription.",
            "Ton type de séance diffère de la prescription enregistrée.",
            "Tu tipo de sesión muestra una desviación respecto a la prescripción registrada."),
        "unavailable": (
            "No reliable prescription comparison is available, so conformity cannot be judged.",
            "Aucune comparaison fiable avec la prescription n'est disponible pour juger la conformité.",
            "No hay una comparación fiable con la prescripción para valorar la conformidad."),
        "indeterminate": (
            "Prescription conformity remains indeterminate.",
            "La conformité à la prescription reste indéterminée.",
            "La conformidad con la prescripción sigue indeterminada."),
    }
    add("prescription.status", "analysis", *prescription_text[prescription.status],
        refs=("prescription_assessment.status",))
    if prescription.status == "deviation":
        add("prescription.review", "recommendation",
            "Review this type deviation against the existing Training prescription; this analysis does not replace or modify it.",
            "Compare ce type de séance à la prescription Training existante ; cette analyse ne la remplace ni ne la modifie.",
            "Revisa esta desviación de tipo frente a la prescripción Training existente; este análisis no la sustituye ni la modifica.",
            refs=("prescription_assessment.status",))
    elif (cls.type == "easy_run_probable" and cls.decision_tier == "individual_history"
          and cls.relative_effort.status == "used"
          and cls.relative_effort.relative_position == "low"
          and cls.relative_effort.reference_count > 0):
        add("advice.comfortable", "recommendation",
            "You can keep the effort comfortable, without always trying to speed up.",
            "Tu peux garder un effort confortable, sans chercher systématiquement à accélérer.",
            "Puedes mantener un esfuerzo cómodo, sin intentar acelerar sistemáticamente.",
            refs=("session_classification.type", "session_classification.decision_tier",
                  "session_classification.relative_effort.status",
                  "session_classification.relative_effort.relative_position",
                  "session_classification.relative_effort.reference_count",
                  "prescription_assessment.status"))
    # Relevance is chosen deterministically before the LLM sees its closed
    # catalog. The editor cannot turn an exhaustive factual catalog into prose.
    catalog = {claim["id"]: claim for claim in claims}
    selected = [catalog["session.kind"]]
    if cls.type == "intervals":
        selected.extend(claim for claim in claims if claim["id"].startswith("interval.")
                        and claim["id"] not in {"interval.partial", "interval.regularity"}
                        and not (claim["id"] == "interval.cohort" and "interval.judgment" in catalog))
    else:
        primary = next((catalog[key] for key in (
            "session.unknown", "intensity.relative", "intensity.position", "intensity.hr",
        ) if key in catalog and catalog[key]["section"] == "analysis"), None)
        if primary is not None:
            selected.append(primary)
        selected.extend(claim for claim in claims
                        if claim["section"] == "interpretation")
        no_splits = "session.no_splits" in catalog
        no_zone = intensity.position == "unknown" and intensity.lt1 is None
        if no_zone or no_splits or "intensity.average" in catalog:
            if no_zone and no_splits:
                sentences = {
                    "en": "Without splits or a reliable LT1, session averages cannot confirm a physiological zone.",
                    "fr": "Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique.",
                    "es": "Sin parciales ni un LT1 fiable, las medias de la sesión no permiten confirmar una zona fisiológica.",
                }
            elif no_zone:
                sentences = {
                    "en": "Without a reliable LT1, this reading does not confirm a physiological zone.",
                    "fr": "Sans LT1 fiable, cette lecture ne confirme pas une zone physiologique.",
                    "es": "Sin un LT1 fiable, esta lectura no confirma una zona fisiológica.",
                }
            elif no_splits:
                sentences = {
                    "en": "Without splits, average heart rate cannot describe time spent in each zone.",
                    "fr": "Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone.",
                    "es": "Sin parciales, la FC media no describe el tiempo en cada zona.",
                }
            else:
                sentences = {
                    "en": "Average heart rate does not describe time spent in each zone.",
                    "fr": "La FC moyenne ne décrit pas le temps passé dans chaque zone.",
                    "es": "La FC media no describe el tiempo en cada zona.",
                }
            refs = []
            if no_zone:
                refs.extend(("intensity_assessment.lt1", "intensity_assessment.position"))
            if no_splits:
                refs.append("session_classification.limitations")
            if "intensity.average" in catalog:
                refs.append("intensity_assessment.hr_metric")
            selected.append({"id": "limit.scope", "section": "limitations",
                             "variants": [sentences[lang]], "evidence_refs": refs})
    prescription_claim = catalog["prescription.status"]
    if prescription.status in {"unavailable", "indeterminate"} and any(
        claim["section"] == "analysis" for claim in selected
    ):
        prescription_claim = {**prescription_claim, "section": "limitations"}
    selected.append(prescription_claim)
    if "prescription.review" in catalog:
        selected.append(catalog["prescription.review"])
    elif "advice.comfortable" in catalog:
        selected.append(catalog["advice.comfortable"])
    if len(selected) > 6:
        selected = [claim for claim in selected if claim["id"] != "interval.cohort"]
    synthesis_claims = _synthesis_claims(v2_analysis, v3, lang) if v2_analysis is not None else []
    if synthesis_claims:
        # V2 owns relevance and reserves. Do not mix its distance-only comparison
        # with V3 physiological/trend judgments or automatically append advice.
        scope_limits = [claim for claim in selected if claim["id"] == "limit.scope"]
        selected = [catalog["session.kind"], *synthesis_claims, *scope_limits]
        if not any(claim["section"] == "interpretation" for claim in selected):
            if "intensity.hr" in catalog:
                selected.append({**catalog["intensity.hr"], "section": "interpretation"})
            elif "interval.count" in catalog:
                selected.append({**catalog["interval.count"], "section": "interpretation"})
            else:
                caution = catalog["interval.execution"] if cls.type == "intervals" else catalog["trend.caution"]
                selected.append({**caution, "section": "interpretation"})
        selected.extend(
            claim for claim in claims
            if claim["id"] in {"intensity.relative", "session.no_structure"}
            and claim["section"] == "limitations"
        )
        selected.append({**prescription_claim, "section": "limitations"})
    elif "intensity.relative" in catalog and catalog["intensity.relative"]["section"] == "limitations":
        selected.append(catalog["intensity.relative"])
    return {"generation_version": GENERATION_VERSION, "language": lang,
            "available": True, "claims": selected}


def _render(context: dict, selections: list[dict], mode: str) -> NarrativeCoachV3:
    catalog = {claim["id"]: claim for claim in context["claims"]}
    sections: dict[str, list[str]] = {
        key: [] for key in ("headline", "analysis", "interpretation", "recommendation", "limitations")
    }
    refs = []
    limitation_groups: dict[str, list[str]] = {}
    for selection in selections:
        claim = catalog[selection["id"]]
        sentence = claim["variants"][selection["variant"]]
        if claim["section"] == "limitations":
            family = claim["id"].split(".")[0]
            limitation_groups.setdefault(family, []).append(sentence)
        else:
            sections[claim["section"]].append(sentence)
        refs.extend(claim["evidence_refs"])
    return NarrativeCoachV3(
        headline=" ".join(sections["headline"]),
        analysis=" ".join(sections["analysis"]),
        interpretation=" ".join(sections["interpretation"]),
        recommendation=" ".join(sections["recommendation"]) or None,
        limitations=[" ".join(group) for group in limitation_groups.values()],
        evidence_refs=list(dict.fromkeys(refs)),
        language=context["language"], generation_mode=mode,
    )


def validate_narrative_selection(
    payload: Any, intelligence: Optional[WorkoutIntelligenceV3], language: str = "en",
    *, phase_analysis: Optional[WorkoutAnalysisPhaseAnalysis] = None,
    coach_language: Optional[CoachLanguageV1] = None,
    v2_analysis: Optional[WorkoutAnalysisV2Response] = None,
) -> Optional[NarrativeCoachV3]:
    """Fail closed on anything except a complete approved-ID/variant selection.

    Rebuild trusted context from typed evidence, rather than accepting a
    caller/LLM-supplied catalog or trusting even real-looking evidence refs.
    Every claim is mandatory, including limitations; unknown keys, duplicate
    IDs, booleans-as-indices, free text and evidence_refs are rejected.
    The compact transport form uses ``[claim_index, variant_index]`` pairs:
    these refer only to positions in the rebuilt approved catalog. This keeps
    valid output below the existing llm_coach 700-character response limit.
    """
    if intelligence is None:
        return None
    context = build_narrative_context(
        intelligence, language, phase_analysis=phase_analysis, coach_language=coach_language,
        v2_analysis=v2_analysis,
    )
    if type(payload) is not dict or set(payload) != {"selections"}:
        return None
    selections = payload["selections"]
    if type(selections) is not list or len(selections) != len(context["claims"]):
        return None
    catalog = {claim["id"]: claim for claim in context["claims"]}
    seen = set()
    expanded = []
    for selection in selections:
        if type(selection) is list:
            if len(selection) != 2:
                return None
            index, variant = selection
            if type(index) is not int or not 0 <= index < len(context["claims"]):
                return None
            selection = {"id": context["claims"][index]["id"], "variant": variant}
        if type(selection) is not dict or set(selection) != {"id", "variant"}:
            return None
        claim_id, variant = selection["id"], selection["variant"]
        if type(claim_id) is not str or claim_id not in catalog or claim_id in seen:
            return None
        if type(variant) is not int or not 0 <= variant < len(catalog[claim_id]["variants"]):
            return None
        seen.add(claim_id)
        expanded.append(selection)
    return _render(context, expanded, "llm_validated")


def deterministic_fallback(
    intelligence: Optional[WorkoutIntelligenceV3], language: str = "en",
    *, phase_analysis: Optional[WorkoutAnalysisPhaseAnalysis] = None,
    coach_language: Optional[CoachLanguageV1] = None,
    v2_analysis: Optional[WorkoutAnalysisV2Response] = None,
) -> NarrativeCoachV3:
    """Complete localized narrative requiring no provider or I/O.

    Optional canonical V2 synthesis is server-generated prose from the same
    scoped loader pass. It is never forwarded to an editing provider.
    """
    context = build_narrative_context(
        intelligence, language, phase_analysis=phase_analysis, coach_language=coach_language,
        v2_analysis=v2_analysis,
    )
    selections = [{"id": claim["id"], "variant": 0} for claim in context["claims"]]
    return _render(context, selections, "deterministic_fallback" if intelligence is not None else "none")


async def _default_transport(system: str, prompt: str, user: str, context_type: str):
    from llm_coach import _call_gpt

    return await _call_gpt(system, prompt, user, context_type)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def generate_narrative_coach_v3(
    intelligence: Optional[WorkoutIntelligenceV3], language: str = "en", *,
    phase_analysis: Optional[WorkoutAnalysisPhaseAnalysis] = None,
    coach_language: Optional[CoachLanguageV1] = None,
    v2_analysis: Optional[WorkoutAnalysisV2Response] = None,
    transport: Optional[Transport] = None,
) -> NarrativeCoachV3:
    """Optionally edit approved claims; all provider failures use fresh fallback.

    Transport injection preserves the same opt-in, timeout and validation.
    Caller cancellation propagates; provider errors never escape this layer.
    Cache copies prevent callers from poisoning subsequent responses.
    Without canonical V2 synthesis, coach_language prose is never consumed;
    only versioned categorical repetition evidence can add a regularity label.
    """
    fallback = deterministic_fallback(
        intelligence, language, phase_analysis=phase_analysis, coach_language=coach_language,
        v2_analysis=v2_analysis,
    )
    # Canonical V2 prose is rendered locally, never sent to or cached by the
    # optional closed-vocabulary editor. No user text crosses that boundary.
    if any(ref.startswith("session_synthesis.") for ref in fallback.evidence_refs):
        return fallback
    if intelligence is None or os.getenv("C355_NARRATIVE_LLM_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return fallback
    context = build_narrative_context(
        intelligence, language, phase_analysis=phase_analysis, coach_language=coach_language,
    )
    prompt = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    cache_key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            _CACHE.move_to_end(cache_key)
            _LOGGER.info("c355_narrative outcome=cache_hit")
            return cached.model_copy(deep=True)
    system = (
        "You are a constrained narrative editor. Return only JSON with one key: "
        'selections, a list of [claim_index,variant_index] integer pairs, e.g. '
        '{"selections":[[0,0],[1,0]]}. claim_index is the zero-based position in '
        "the supplied claims array; variant_index selects its approved sentence. "
        "Select every supplied claim exactly once. You may reorder claims within "
        "each section and choose approved sentence variants. No free text, extra "
        "keys, evidence refs, new claims, recommendations or omissions. "
        "Use compact single-line JSON without spaces, under 700 characters."
    )
    try:
        text, success, _ = await asyncio.wait_for(
            (transport or _default_transport)(system, prompt, "anonymous", "c355_narrative"),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        if not success or not isinstance(text, str) or len(text) > MAX_RESPONSE_CHARS:
            _LOGGER.info("c355_narrative outcome=unavailable")
            return fallback
        payload = json.loads(text, object_pairs_hook=_strict_object)
        result = validate_narrative_selection(
            payload, intelligence, language, phase_analysis=phase_analysis, coach_language=coach_language,
        )
        if result is None:
            _LOGGER.info("c355_narrative outcome=rejected")
            return fallback
    except asyncio.TimeoutError:
        _LOGGER.info("c355_narrative outcome=timeout")
        return fallback
    except Exception:
        # Do not log exception messages, provider content or supplied data.
        _LOGGER.info("c355_narrative outcome=error")
        return fallback
    with _CACHE_LOCK:
        _CACHE[cache_key] = result.model_copy(deep=True)
        _CACHE.move_to_end(cache_key)
        while len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
    _LOGGER.info("c355_narrative outcome=llm_validated")
    return result
