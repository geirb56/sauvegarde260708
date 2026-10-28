"""Synthetic C358 presentation regressions; not historical Garmin validation."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from activity_phases import ActivityPhase
from narrative_coach_v3 import deterministic_fallback, format_narrative_number
from workout_analysis_v2 import build_workout_analysis_v2
from workout_intelligence_v3 import (
    build_workout_intelligence_v3,
    extract_workout_intelligence_input,
)


LABELS = {
    "fr": ("allure médiane", "écart-type des allures"),
    "en": ("median pace", "pace standard deviation"),
    "es": ("mediana de los ritmos", "desviación estándar de los ritmos"),
}


def synthetic_analysis(language, *, partial=False):
    data = json.loads(
        (Path(__file__).parent / "fixtures/coach_session_synthesis_c351.json").read_text()
    )
    workout = next(w for w in data["sessions"] if w["date"] == "2026-10-10")
    phases = []
    for effort in data["interval_efforts"]:
        phases.append(ActivityPhase(
            order=len(phases), phase_type="effort", source="synthetic", **effort,
        ))
        phases.append(ActivityPhase(
            order=len(phases), phase_type="recovery", source="synthetic",
            **data["interval_recovery"],
        ))
    if partial:
        # Two different-sized efforts leave the four-effort cohort partial.
        for duration in (60, 600):
            phases.append(ActivityPhase(
                order=len(phases), phase_type="effort", source="synthetic",
                duration_s=duration, distance_m=duration * 1000 / 300,
            ))
    analysis = build_workout_analysis_v2(workout, [], language, phases)
    facts = build_workout_intelligence_v3(extract_workout_intelligence_input(
        workout, [], v2_analysis=analysis,
    ))
    return analysis, facts


@pytest.mark.parametrize("language", LABELS)
def test_same_four_efforts_have_distinct_valid_metrics_and_labels(language, monkeypatch):
    analysis, facts = synthetic_analysis(language)
    conclusion, = analysis.coach_language.conclusions
    regularity = analysis.phase_analysis.effort_regularity
    assert conclusion.evidence["absolute_deviation_sec_per_km"] == pytest.approx(6.569673797567631)
    assert regularity.pace_dispersion_sec_per_km == pytest.approx(7.687007906315586)
    assert conclusion.evidence["comparable_effort_count"] == regularity.pace_sample_count == 4
    assert conclusion.evidence["total_effort_count"] == regularity.effort_count == 4
    assert conclusion.metadata["metric"] == "mean_absolute_deviation_from_median"
    assert conclusion.metadata["regularity_band"] == "noticeable"
    before = deepcopy(analysis.model_dump())

    def forbidden(*args, **kwargs):
        pytest.fail("Presentation must reuse backend metric sources, not recompute")

    monkeypatch.setattr("coach_language._repetition_judgment", forbidden)
    monkeypatch.setattr("workout_analysis_v2._effort_regularity", forbidden)
    result = deterministic_fallback(
        facts, language, phase_analysis=analysis.phase_analysis,
        coach_language=analysis.coach_language,
    )
    gap = format_narrative_number(conclusion.evidence["absolute_deviation_sec_per_km"], language)
    spread = format_narrative_number(regularity.pace_dispersion_sec_per_km, language)
    assert f"{gap} s/km" in result.interpretation
    assert LABELS[language][0] in result.interpretation
    assert f"{spread} s/km" not in result.analysis + result.interpretation
    assert LABELS[language][0] in conclusion.text
    dispersion_fact = next(
        item for item in analysis.meaning.factual_observations
        if item.code == "fact.effort_dispersion"
    )
    assert LABELS[language][1] in dispersion_fact.text
    assert f"{spread} s/km" in dispersion_fact.text
    assert analysis.model_dump() == before
    assert analysis.version == "v2" and facts.version == "v3"
    assert set(result.model_dump()) == {
        "headline", "analysis", "interpretation", "recommendation",
        "limitations", "language", "generation_mode", "evidence_refs",
    }


@pytest.mark.parametrize("language", LABELS)
def test_partial_six_efforts_never_gain_a_regularity_judgment_from_16_6(language):
    analysis, facts = synthetic_analysis(language, partial=True)
    regularity = analysis.phase_analysis.effort_regularity
    assert regularity.partial_comparison
    assert regularity.effort_count == 6 and regularity.pace_sample_count == 4
    assert analysis.coach_language.conclusions == []
    # Deliberately injected synthetic observation, not a measured 19/09 value.
    regularity.pace_dispersion_sec_per_km = 16.5621
    result = deterministic_fallback(
        facts, language, phase_analysis=analysis.phase_analysis,
        coach_language=analysis.coach_language,
    )
    assert LABELS[language][1] in result.analysis.lower()
    assert f"{format_narrative_number(16.5621, language)} s/km" in result.analysis
    assert {"fr": "elle ne suffit pas", "en": "alone is not enough", "es": "por sí sola no basta"}[language] in result.interpretation
    assert {"fr": "4 des 6", "en": "4 of 6", "es": "4 de las 6"}[language] in result.analysis
    assert "phase_analysis.effort_regularity.comparable_effort_count" in result.evidence_refs
    assert regularity.partial_comparison is True
    assert not any("regularity_band" in ref for ref in result.evidence_refs)


@pytest.mark.parametrize("language", LABELS)
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf")])
def test_missing_or_nonfinite_metrics_do_not_become_zero_or_a_verdict(language, value):
    analysis, facts = synthetic_analysis(language)
    analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km = value
    analysis.coach_language.conclusions[0].evidence["absolute_deviation_sec_per_km"] = value
    result = deterministic_fallback(
        facts, language, phase_analysis=analysis.phase_analysis,
        coach_language=analysis.coach_language,
    )
    text = result.analysis + result.interpretation
    assert "s/km" not in text
    assert not any("regularity_band" in ref for ref in result.evidence_refs)
