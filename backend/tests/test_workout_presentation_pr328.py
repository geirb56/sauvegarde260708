"""Additive presentation contract against the merged PR326/PR327 backend."""

from copy import deepcopy

import pytest

from activity_phases import ActivityPhase
from coach_context_v2 import CoachWorkoutDetail, build_llm_coach_context
from workout_analysis_v2 import (
    AnalysisText,
    WorkoutAnalysisMeaning,
    WorkoutAnalysisV2Response,
    _build_meaning,
    _phase_observations,
    _template,
    build_workout_analysis_v2,
)


LEGACY_TEXT = {
    "en": {
        "dispersion": "The 4 measured comparable efforts have a pace dispersion of 7.6 s/km.",
        "partial_dispersion": "The 3 measured comparable efforts have a pace dispersion of 8.2 s/km.",
        "equal_dispersion": "The 4 measured comparable efforts have a pace dispersion of 0 s/km.",
        "extremes": "Effort 3 was fastest (4:31/km); effort 4 was slowest (4:51/km).",
        "hr": "Mean heart rate changes from 151 to 159 bpm between measured efforts 1 and 4. This is not a cardiac drift measurement.",
        "maximum": "Peak heart rate observed in the phases: 175 bpm.",
        "reserve": "Physiological intensity cannot be reliably determined.",
        "partial": "These pace observations cover only 3 of 4 efforts; they do not describe every repetition.",
        "partial_hr": "Heart-rate coverage: 3 of 4 comparable efforts have a mean heart rate.",
        "missing_hr": "Heart-rate coverage: 0 of 4 comparable efforts have a mean heart rate.",
        "standard": "Pacing and cardiac data are recorded.",
        "advice": "The last measured comparable effort is 20 s/km slower than the preceding one.",
        "partial_advice": "The measured comparable efforts show a pace dispersion of 8.2 s/km.",
        "equal_advice": "The last two measured comparable efforts have the same pace.",
        "unavailable_advice": "No usable coaching observation is available from these data.",
    },
    "fr": {
        "dispersion": "Les 4 efforts comparables mesurés présentent une dispersion de 7,6 s/km.",
        "partial_dispersion": "Les 3 efforts comparables mesurés présentent une dispersion de 8,2 s/km.",
        "equal_dispersion": "Les 4 efforts comparables mesurés présentent une dispersion de 0 s/km.",
        "extremes": "L'effort 3 est le plus rapide (4:31/km) ; l'effort 4 est le plus lent (4:51/km).",
        "hr": "La FC moyenne évolue de 151 à 159 bpm entre les efforts mesurés 1 et 4. Cette évolution ne constitue pas une mesure de dérive cardiaque.",
        "maximum": "FC maximale observée dans les phases : 175 bpm.",
        "reserve": "L'intensité physiologique ne peut pas être déterminée de manière fiable.",
        "partial": "Ces observations d'allure portent sur 3 des 4 efforts ; elles ne décrivent pas toutes les répétitions.",
        "partial_hr": "Couverture cardiaque : 3 des 4 efforts comparables ont une FC moyenne.",
        "missing_hr": "Couverture cardiaque : 0 des 4 efforts comparables ont une FC moyenne.",
        "standard": "Des données d'allure et cardiaques sont enregistrées.",
        "advice": "Le dernier effort comparable mesuré est plus lent de 20 s/km que le précédent.",
        "partial_advice": "Les efforts comparables mesurés présentent une dispersion d'allure de 8,2 s/km.",
        "equal_advice": "Les deux derniers efforts comparables mesurés ont la même allure.",
        "unavailable_advice": "Aucune observation coach exploitable n'est disponible avec ces données.",
    },
    "es": {
        "dispersion": "Los 4 esfuerzos comparables medidos presentan una dispersión de 7,6 s/km.",
        "partial_dispersion": "Los 3 esfuerzos comparables medidos presentan una dispersión de 8,2 s/km.",
        "equal_dispersion": "Los 4 esfuerzos comparables medidos presentan una dispersión de 0 s/km.",
        "extremes": "El esfuerzo 3 fue el más rápido (4:31/km); el esfuerzo 4 fue el más lento (4:51/km).",
        "hr": "La frecuencia cardíaca media cambia de 151 a 159 bpm entre los esfuerzos medidos 1 y 4. No es una medición de deriva cardíaca.",
        "maximum": "Frecuencia cardíaca máxima observada en las fases: 175 bpm.",
        "reserve": "La intensidad fisiológica no puede determinarse de forma fiable.",
        "partial": "Estas observaciones de ritmo cubren 3 de los 4 esfuerzos; no describen todas las repeticiones.",
        "partial_hr": "Cobertura cardíaca: 3 de los 4 esfuerzos comparables tienen frecuencia cardíaca media.",
        "missing_hr": "Cobertura cardíaca: 0 de los 4 esfuerzos comparables tienen frecuencia cardíaca media.",
        "standard": "Hay datos de ritmo y cardíacos registrados.",
        "advice": "El último esfuerzo comparable medido es 20 s/km más lento que el anterior.",
        "partial_advice": "Los esfuerzos comparables medidos muestran una dispersión de ritmo de 8,2 s/km.",
        "equal_advice": "Los dos últimos esfuerzos comparables medidos tienen el mismo ritmo.",
        "unavailable_advice": "No hay una observación útil de coaching disponible con estos datos.",
    },
}


EXPECTED_COMPARISON = {
    "available": True, "baseline_period_days": 14, "baseline_sample_count": 2,
    "distance_km": {"current": 14.26, "baseline": 15.0, "difference": -0.74, "percent_change": -4.9},
    "duration_minutes": {"current": 80.0, "baseline": 80.0, "difference": 0.0, "percent_change": 0.0},
    "avg_heart_rate": None,
    "avg_pace_min_km": {"current": 5.0, "baseline": 6.25, "difference": -1.25, "percent_change": -20.0},
    "avg_speed_kmh": None,
    "similar": {
        "available": True, "comparable": True, "sample_count": 2, "period_days": 180,
        "distance_tolerance_pct": 30.0, "min_comparable_sample": 2,
        "workout_ids": ["synthetic-history-1", "synthetic-history-0"],
        "avg_distance_km": 15.0, "avg_pace_min_km": 6.25, "avg_heart_rate": 145.5,
        "distance_sample_count": 2, "pace_sample_count": 2, "pace_avg_distance_km": 15.0,
        "hr_sample_count": 2, "pace_difference_min_km": -1.25,
        "heart_rate_difference_bpm": None, "limitations": [], "reason_unavailable": None,
    },
    "reason_unavailable": None,
}


def workout(**updates):
    return {
        "id": "synthetic-pr328",
        "name": "Synthetic observations",
        "date": "2026-10-10",
        "type": "run",
        "distance_km": 14.26,
        "duration_minutes": 80,
        "max_heart_rate": 175,
        "avg_pace_min_km": 5.0,
        "workout_type": "training",
        **updates,
    }


def intervals():
    phases = []
    for pace, hr in zip((288, 282, 271, 291), (151, 157, 159, 159)):
        phases.append(ActivityPhase(
            order=len(phases), phase_type="effort", duration_s=240,
            distance_m=240000 / pace, average_hr=hr, max_hr=175,
            source="synthetic",
        ))
        phases.append(ActivityPhase(
            order=len(phases), phase_type="recovery", duration_s=180,
            distance_m=400, source="synthetic",
        ))
    return phases


def scenario(kind):
    current = workout()
    phases = intervals()
    if kind == "no_phases":
        phases = None
    elif kind == "continuous_no_phases":
        current["session_structure"] = "continuous"
        phases = None
    elif kind == "continuous":
        phases = [ActivityPhase(
            order=0, phase_type="effort", duration_s=4800, distance_m=14260,
            average_hr=150, max_hr=175, source="synthetic",
        )]
    elif kind == "unknown":
        phases = [ActivityPhase(order=0, duration_s=60, source="synthetic")]
    elif kind == "unknown_max_only":
        phases = [ActivityPhase(order=0, max_hr=175, source="synthetic")]
    elif kind == "mixed":
        phases.insert(1, ActivityPhase(order=99, duration_s=60, source="synthetic"))
    elif kind == "partial":
        phases[0] = phases[0].model_copy(update={"distance_m": None, "average_hr": None})
    elif kind == "missing_hr":
        phases = [phase.model_copy(update={"average_hr": None, "max_hr": None}) for phase in phases]
    elif kind == "equal":
        phases = [
            phase.model_copy(update={"distance_m": 800}) if phase.phase_type == "effort" else phase
            for phase in phases
        ]
    elif kind == "untrusted_zones":
        current["effort_zone_distribution"] = {"z4": 70, "z5": 30}
    return current, phases


def history():
    return [
        workout(
            id=f"synthetic-history-{index}", date=f"2026-10-0{index + 1}",
            distance_km=15, avg_pace_min_km=pace, avg_heart_rate=145 + index,
        )
        for index, pace in enumerate((6.0, 6.5))
    ]


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("kind", [
    "intervals", "no_phases", "continuous_no_phases", "continuous",
    "unknown", "unknown_max_only", "mixed", "partial", "missing_hr", "equal",
    "untrusted_zones",
])
def test_legacy_presentation_and_comparison_invariants(language, kind):
    current, phases = scenario(kind)
    analysis = build_workout_analysis_v2(current, [], language, phases)
    payload = analysis.model_dump()
    assert set(payload["meaning"]) == {"code", "text", "observations", "caveats"}
    text = LEGACY_TEXT[language]
    meaning_keys = ["dispersion", "extremes", "hr", "maximum", "reserve"]
    advice_keys = ["advice", "reserve"]
    meaning_code = "meaning.structured_phases"
    advice_code = "advice.structured_phases"
    available = True
    if kind in {"no_phases", "continuous_no_phases", "unknown", "continuous", "unknown_max_only"}:
        meaning_keys = ["maximum", "reserve"]
        if kind in {"no_phases", "continuous_no_phases", "unknown"}:
            meaning_keys = ["standard", "reserve"]
            meaning_code = "meaning.hr_without_intensity_with_pacing"
        advice_keys = ["unavailable_advice"]
        advice_code = "advice.hr_without_intensity"
        available = False
    elif kind == "partial":
        meaning_keys = ["partial_dispersion", "extremes", "maximum", "partial", "partial_hr", "reserve"]
        advice_keys = ["partial_advice", "partial", "reserve"]
    elif kind == "missing_hr":
        meaning_keys = ["dispersion", "extremes", "missing_hr", "reserve"]
    elif kind == "equal":
        meaning_keys = ["equal_dispersion", "hr", "maximum", "reserve"]
        advice_keys = ["equal_advice", "reserve"]
    assert {"code": analysis.meaning.code, "text": analysis.meaning.text} == {
        "code": meaning_code, "text": " ".join(text[key] for key in meaning_keys),
    }
    assert payload["advice"] == {
        "code": advice_code, "text": " ".join(text[key] for key in advice_keys), "available": available,
    }
    assert build_workout_analysis_v2(current, history(), language, phases).comparison.model_dump() == EXPECTED_COMPARISON


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_localized_takeaways_share_execution_facts_without_max_hr_or_history(language):
    analysis = build_workout_analysis_v2(workout(), history(), language, intervals())
    facts = _phase_observations(analysis.phase_analysis, analysis.signals.session_structure, language)
    decimal = "." if language == "en" else ","
    assert len(analysis.meaning.observations) == 3
    assert analysis.meaning.observations == facts["takeaways"]
    assert f"7{decimal}6 s/km" in analysis.meaning.observations[0]
    assert "4:31/km" in analysis.meaning.observations[1]
    assert "4:51/km" in analysis.meaning.observations[1]
    assert "151" in analysis.meaning.observations[2]
    assert "159" in analysis.meaning.observations[2]
    assert analysis.meaning.caveats == [_template(language, "meaning.intensity_unavailable")]
    for fact in analysis.meaning.observations + analysis.meaning.caveats:
        assert fact in analysis.meaning.text
    assert "175 bpm" in analysis.meaning.text
    assert "175 bpm" not in " ".join(analysis.meaning.observations)
    assert facts["execution"][:-1] == analysis.meaning.observations
    without_history = build_workout_analysis_v2(workout(), [], language, intervals())
    assert analysis.meaning.text != without_history.meaning.text
    assert analysis.meaning.observations == without_history.meaning.observations
    assert analysis.meaning.caveats == without_history.meaning.caveats
    assert analysis.summary == without_history.summary
    assert analysis.advice == without_history.advice
    assert len(analysis.summary.text) < 250
    for detail in ("s/km", "151", "159", "175 bpm", "4:31/km", "4:51/km"):
        assert detail not in analysis.summary.text


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("kind", ["partial", "missing_hr"])
def test_caveats_share_uncertainty_and_intensity_reserve(language, kind):
    current, phases = scenario(kind)
    analysis = build_workout_analysis_v2(current, [], language, phases)
    facts = _phase_observations(analysis.phase_analysis, analysis.signals.session_structure, language)
    expected = facts["uncertainty"] + (
        [] if analysis.signals.intensity.available else [_template(language, "meaning.intensity_unavailable")]
    )
    assert analysis.meaning.caveats == expected
    assert all(fact in analysis.meaning.text for fact in expected)
    assert facts["uncertainty"]
    assert len(analysis.meaning.observations) == 2
    assert all("151" not in fact for fact in analysis.meaning.observations)


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_presentation_omits_intensity_reserve_when_signal_is_available(language):
    analysis = build_workout_analysis_v2(workout(), [], language, intervals())
    signals = analysis.signals.model_copy(deep=True)
    signals.intensity.available = True
    facts = _phase_observations(analysis.phase_analysis, signals.session_structure, language)
    meaning = _build_meaning(
        workout(), analysis.physiology, analysis.pacing, analysis.comparison,
        signals, language, facts,
    )
    assert meaning.caveats == []
    assert meaning.observations == facts["takeaways"]
    assert _template(language, "meaning.intensity_unavailable") not in meaning.text


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("kind", ["no_phases", "continuous_no_phases", "unknown"])
def test_standard_fallback_uses_original_text(language, kind):
    current, phases = scenario(kind)
    analysis = build_workout_analysis_v2(current, [], language, phases)
    assert analysis.meaning.observations == [analysis.meaning.text]
    assert analysis.meaning.caveats == []


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("kind", ["continuous", "unknown_max_only"])
def test_maximum_only_execution_has_conservative_nonempty_observation(language, kind):
    current, phases = scenario(kind)
    analysis = build_workout_analysis_v2(current, history(), language, phases)
    assert analysis.meaning.observations == [LEGACY_TEXT[language]["reserve"]]
    assert analysis.meaning.caveats == [LEGACY_TEXT[language]["reserve"]]
    assert "175 bpm" in analysis.meaning.text
    assert all("175" not in fact for fact in analysis.meaning.observations)
    without_history = build_workout_analysis_v2(current, [], language, phases)
    assert analysis.meaning.text != without_history.meaning.text
    assert analysis.meaning.observations == without_history.meaning.observations


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("intensity_code,meaning_code", [
    ("high", "meaning.with_hr_high"),
    ("very_high", "meaning.with_hr_high"),
    ("low", "meaning.with_hr_easy"),
    ("moderate", "meaning.with_hr_moderate"),
])
def test_maximum_only_reliable_intensity_uses_existing_meaning_without_history(
    language, intensity_code, meaning_code,
):
    current, phases = scenario("unknown_max_only")
    analysis = build_workout_analysis_v2(current, history(), language, phases)
    signals = analysis.signals.model_copy(deep=True)
    signals.intensity.available = True
    signals.intensity.code = intensity_code
    facts = _phase_observations(analysis.phase_analysis, signals.session_structure, language)
    meaning = _build_meaning(
        current, analysis.physiology, analysis.pacing, analysis.comparison,
        signals, language, facts,
    )
    assert meaning.observations == [_template(language, meaning_code)]
    assert meaning.caveats == []
    assert "175 bpm" in meaning.text
    assert all("175" not in fact for fact in meaning.observations)
    without_history = build_workout_analysis_v2(current, [], language, phases)
    meaning_without_history = _build_meaning(
        current, analysis.physiology, analysis.pacing, without_history.comparison,
        signals, language, facts,
    )
    assert meaning.text != meaning_without_history.text
    assert meaning.observations == meaning_without_history.observations
    assert meaning.caveats == meaning_without_history.caveats


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_json_roundtrip_legacy_defaults_and_coach_passthrough(language):
    analysis = build_workout_analysis_v2(workout(), [], language, intervals())
    assert isinstance(analysis.meaning, AnalysisText)
    restored = WorkoutAnalysisV2Response.model_validate_json(analysis.model_dump_json())
    assert restored == analysis
    legacy_payload = deepcopy(analysis.model_dump())
    del legacy_payload["meaning"]["observations"]
    del legacy_payload["meaning"]["caveats"]
    legacy = WorkoutAnalysisV2Response.model_validate(legacy_payload)
    assert legacy.meaning.code == analysis.meaning.code
    assert legacy.meaning.text == analysis.meaning.text
    assert legacy.meaning.observations == legacy.meaning.caveats == []
    detail = CoachWorkoutDetail(
        id=analysis.workout.id, date=analysis.workout.date, type="run", analysis=restored,
    )
    canonical = {"workout_detail": detail.model_dump(mode="json")}
    projected = build_llm_coach_context(canonical)
    assert projected["workout_detail"]["analysis"]["meaning"] == analysis.meaning.model_dump()
    assert projected["workout_detail"]["analysis"]["advice"] == analysis.advice.model_dump()
    assert canonical["workout_detail"]["analysis"] == analysis.model_dump(mode="json")


def test_meaning_default_lists_are_independent():
    first = WorkoutAnalysisMeaning(code="synthetic", text="Synthetic")
    second = WorkoutAnalysisMeaning(code="synthetic", text="Synthetic")
    first.observations.append("Observed")
    first.caveats.append("Uncertain")
    assert second.observations == []
    assert second.caveats == []


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("constructor", ["direct", "model_validate"])
def test_response_accepts_legacy_analysis_text_instance(language, constructor):
    analysis = build_workout_analysis_v2(workout(), [], language, intervals())
    legacy_meaning = AnalysisText(code=analysis.meaning.code, text=analysis.meaning.text)
    payload = analysis.model_dump()
    payload["meaning"] = legacy_meaning
    restored = (
        WorkoutAnalysisV2Response(**payload)
        if constructor == "direct" else WorkoutAnalysisV2Response.model_validate(payload)
    )
    assert isinstance(restored.meaning, WorkoutAnalysisMeaning)
    assert restored.meaning.model_dump() == {
        "code": legacy_meaning.code, "text": legacy_meaning.text,
        "observations": [], "caveats": [],
    }
    assert legacy_meaning.model_dump() == {
        "code": analysis.meaning.code, "text": analysis.meaning.text,
    }
    assert restored.advice == analysis.advice
