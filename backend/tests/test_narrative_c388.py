"""C387B request facts, not captured Mongo payloads or live Garmin validation.

History fixtures freeze only the counts/deltas supplied in the C388 request:
no invented reference sessions, baseline pace, splits or physiological metrics.
Interval measurements reuse the explicitly synthetic C351 phase fixture.
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from activity_phases import ActivityPhase
from coach_language import CoachConclusionV1, CoachLanguageV1
from coach_session_synthesis import (
    CoachSessionSynthesisV2, SessionSynthesisItem, SessionSynthesisLimit,
)
import narrative_coach_v3 as narrative
from workout_analysis_v2 import WorkoutAnalysisFactualObservation, build_workout_analysis_v2
from workout_intelligence_v3 import (
    build_workout_intelligence_v3, extract_workout_intelligence_input,
)
from workout_intelligence_v3_models import WIV3PerformanceTrend, WIV3SessionClassification


LANGUAGES = ("fr", "en", "es")
AUDIT_FACTS = {
    "garmin-24701222152": {
        "date": "2026-10-12", "distance_km": 9.33, "avg_pace_min_km": 7.35,
        "avg_heart_rate": 127, "count": 5, "delta": 25.3,
    },
    "garmin-24346252881": {
        "date": "2026-09-13", "distance_km": 21.27, "duration_minutes": 122,
        "avg_pace_min_km": 5 + 43 / 60, "avg_heart_rate": 160,
        "count": 4, "delta": -70.7,
    },
}


def history_case(workout_id, language="fr"):
    facts = AUDIT_FACTS[workout_id]
    workout = {key: value for key, value in facts.items() if key not in {"count", "delta"}}
    workout.update(id=workout_id, type="run")
    analysis = build_workout_analysis_v2(workout, [], language)
    count, delta = facts["count"], facts["delta"]
    number = narrative.format_narrative_number(abs(delta), language)
    text = {
        "fr": (
            f"Par rapport à tes {count} sorties antérieures de distance comparable avec allure mesurée, "
            "sans garantie de même nature ni de même structure, "
            f"ton allure moyenne est {number} s/km plus {'lente' if delta > 0 else 'rapide'}."
        ),
        "en": (
            f"Compared with your {count} earlier sessions of comparable distance with recorded pace, "
            "without any guarantee of the same nature or structure, "
            f"your average pace is {number} s/km {'slower' if delta > 0 else 'faster'}."
        ),
        "es": (
            f"Frente a tus {count} sesiones anteriores de distancia comparable con ritmo registrado, "
            "sin garantía de que sean de la misma naturaleza ni de la misma estructura, "
            f"tu ritmo medio es {number} s/km más {'lento' if delta > 0 else 'rápido'}."
        ),
    }[language]
    source = CoachConclusionV1(
        code="coach.history.pace", text=text, category="history", priority=50,
        kind="descriptive", metadata={"comparability": "distance_only", "population": "pace_only"},
        evidence={"pace_sample_count": count, "pace_difference_sec_per_km": delta},
    )
    analysis.coach_language = CoachLanguageV1(conclusions=[source])
    analysis.session_synthesis = CoachSessionSynthesisV2(
        status="available",
        primary=SessionSynthesisItem(
            code=source.code, text=source.text, evidence=source.evidence,
            source_paths=["coach_language.conclusions[0]"],
        ),
        limitations=[SessionSynthesisLimit(
            code="synthesis.history_descriptive",
            text={
                "fr": "Cet écart décrit ces séances ; il ne suffit pas à conclure à un changement de forme ni à juger l’exécution.",
                "en": "This difference describes these sessions; it cannot alone establish a change in fitness or judge execution.",
                "es": "Esta diferencia describe esas sesiones; por sí sola no permite establecer un cambio de forma ni juzgar la ejecución.",
            }[language],
            source_paths=["coach_language.conclusions[0]"],
        )],
    )
    intelligence = build_workout_intelligence_v3(
        extract_workout_intelligence_input(workout, [], v2_analysis=analysis), language,
    )
    # Classification is independent of the admitted distance-only observation.
    intelligence.session_classification = WIV3SessionClassification(
        type="easy_run_probable" if delta > 0 else "long_run_probable",
        confidence="low", decision_tier="individual_history",
        limitations=["no_splits_whole_session_averages_only"],
    )
    return analysis, intelligence


def interval_case(language="fr", *, recovery_jitter=False):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/coach_session_synthesis_c351.json").read_text()
    )
    phases = []
    for effort in fixture["interval_efforts"]:
        for kind, row in (("effort", effort), ("recovery", fixture["interval_recovery"])):
            measured = {**row}
            if recovery_jitter and kind == "recovery" and len(phases) == 3:
                measured["duration_s"] += .5
            phases.append(ActivityPhase(order=len(phases), phase_type=kind, source="garmin", **measured))
    workout = {"id": "garmin-24671804067", "date": "2026-10-10", "type": "run"}
    analysis = build_workout_analysis_v2(workout, [], language, phases=phases)
    intelligence = build_workout_intelligence_v3(
        extract_workout_intelligence_input(workout, [], v2_analysis=analysis), language,
    )
    return analysis, intelligence


def render(analysis, intelligence, language="fr"):
    return narrative.deterministic_fallback(
        intelligence, language, phase_analysis=analysis.phase_analysis,
        coach_language=analysis.coach_language, v2_analysis=analysis,
    )


def assert_canonical(analysis, result):
    synthesis = analysis.session_synthesis
    assert result.analysis == synthesis.primary.text
    for item in synthesis.supporting:
        assert item.text in result.interpretation
    for limit in synthesis.limitations:
        assert any(limit.text in text for text in result.limitations)
    assert result.recommendation is None
    assert result.generation_mode == "deterministic_fallback"
    # Every reference resolves to this response or the supplied V3, not another user.
    assert "session_synthesis.primary" in result.evidence_refs
    for item in [synthesis.primary, *synthesis.supporting, *synthesis.limitations]:
        assert set(item.source_paths) <= set(result.evidence_refs)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("workout_id", AUDIT_FACTS)
def test_distance_only_history_is_primary_with_its_exact_limits(workout_id, language):
    analysis, intelligence = history_case(workout_id, language)
    before = deepcopy((analysis.model_dump(), intelligence.model_dump()))
    result = render(analysis, intelligence, language)
    assert_canonical(analysis, result)
    assert result.language == language and result.interpretation
    primary = analysis.session_synthesis.primary
    assert primary.evidence["pace_difference_sec_per_km"] == AUDIT_FACTS[workout_id]["delta"]
    assert primary.evidence["pace_sample_count"] == AUDIT_FACTS[workout_id]["count"]
    if language != "en":
        assert not re.search(r"\d+\.\d", result.analysis)
    assert not any(word in result.analysis.lower() for word in (
        "progress", "regress", "fatigue", "fatiga", "efficiency", "efficacité", "eficiencia",
        "lt1", "lt2", "prescription",
    ))
    assert not any(ref.startswith(("performance_trend.", "historical_comparison."))
                   for ref in result.evidence_refs)
    assert not any(ref.startswith(("phase_analysis.", "meaning.factual_observations"))
                   for ref in result.evidence_refs)
    assert (analysis.model_dump(), intelligence.model_dump()) == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_intervals_keep_whole_reasoning_outlier_endpoints_and_hr(language, monkeypatch):
    analysis, intelligence = interval_case(language)
    evidence = analysis.session_synthesis.primary.evidence
    assert evidence["comparable_effort_count"] == 4
    assert evidence["absolute_deviation_sec_per_km"] == pytest.approx(6.6, abs=.05)
    assert evidence["atypical_effort_number"] == 3
    assert abs(evidence["atypical_difference_sec_per_km"]) == pytest.approx(17.5, abs=.05)
    assert evidence["first_to_last_pace_change_sec_per_km"] == pytest.approx(2.3, abs=.05)
    assert evidence["first_hr_bpm"] == 151 and evidence["last_hr_bpm"] == 159
    assert [round(phase.pace_sec_per_km) for phase in analysis.phase_analysis.efforts] == [288, 282, 271, 291]
    before = deepcopy(analysis.model_dump())
    monkeypatch.setattr("coach_language._repetition_judgment",
                        lambda *args, **kwargs: pytest.fail("No scientific recomputation"))
    result = render(analysis, intelligence, language)
    assert_canonical(analysis, result)
    assert {"fr": "répétition n° 3", "en": "Repetition 3", "es": "repetición n.º 3"}[language] in result.analysis
    assert "151" in result.analysis and "159" in result.analysis
    assert len(result.analysis.split(". ")) >= 4
    assert not any(word in result.analysis.lower() for word in ("fatigue", "fatiga", "drift", "dérive", "deriva"))
    assert analysis.model_dump() == before


def test_localization_changes_only_display_not_v2_numeric_evidence():
    cases = [interval_case(language) for language in LANGUAGES]
    primary = [analysis.session_synthesis.primary for analysis, _ in cases]
    assert primary[0].evidence == primary[1].evidence == primary[2].evidence
    assert "6,6 s/km" in primary[0].text
    assert "6.6 s/km" in primary[1].text
    assert "6,6 s/km" in primary[2].text
    assert all(analysis.phase_analysis == cases[0][0].phase_analysis for analysis, _ in cases)


@pytest.mark.parametrize("mutation", [
    "missing", "insufficient", "no_primary", "wrong_workout", "wrong_version",
    "unavailable_source", "unknown_code", "wrong_path", "changed_evidence", "missing_limit",
    "changed_text",
])
def test_unavailable_or_unauthorized_synthesis_never_enters_narrative(mutation):
    analysis, intelligence = history_case("garmin-24701222152")
    if mutation == "missing":
        analysis.session_synthesis = None
    elif mutation == "insufficient":
        analysis.session_synthesis.status = "insufficient"
    elif mutation == "no_primary":
        analysis.session_synthesis.primary = None
    elif mutation == "wrong_workout":
        analysis.workout.id = "another-workout"
    elif mutation == "wrong_version":
        analysis.version = "v999"
    elif mutation == "unavailable_source":
        analysis.coach_language.conclusions[0].available = False
    elif mutation == "unknown_code":
        analysis.session_synthesis.primary.code = "unapproved.progress"
    elif mutation == "wrong_path":
        analysis.session_synthesis.primary.source_paths = ["advice.text"]
    elif mutation == "changed_evidence":
        analysis.session_synthesis.primary.evidence = {"pace_difference_sec_per_km": 999}
    elif mutation == "missing_limit":
        analysis.session_synthesis.limitations = []
    elif mutation == "changed_text":
        analysis.session_synthesis.primary.text += " Unsupported fitness improvement."
    result = render(analysis, intelligence)
    expected = narrative.deterministic_fallback(
        intelligence, "fr", phase_analysis=analysis.phase_analysis,
        coach_language=analysis.coach_language,
    )
    assert result == expected
    assert not any(ref.startswith("session_synthesis.") for ref in result.evidence_refs)


def test_uncertain_repetition_judgment_cannot_bypass_existing_guard():
    analysis, intelligence = interval_case()
    analysis.coach_language.conclusions[0].metadata["judgment_version"] = "unapproved"
    result = render(analysis, intelligence)
    assert "session_synthesis.primary" not in result.evidence_refs
    assert "coach_language.conclusions.0.evidence.absolute_deviation_sec_per_km" not in result.evidence_refs


def test_missing_phases_or_history_and_totally_insufficient_data_keep_complete_contract():
    workout = {"id": "empty", "date": "2026-10-20", "type": "run"}
    analysis = build_workout_analysis_v2(workout, [], "fr")
    intelligence = build_workout_intelligence_v3(
        extract_workout_intelligence_input(workout, [], v2_analysis=analysis), "fr",
    )
    result = render(analysis, intelligence)
    assert analysis.session_synthesis.status == "insufficient"
    assert result.headline and result.analysis and result.interpretation and result.limitations
    assert result.recommendation is None
    assert result == narrative.deterministic_fallback(intelligence, "fr")


def test_contextual_recoveries_keep_v2_duration_tolerance_without_rejudging():
    analysis, intelligence = interval_case(recovery_jitter=True)
    assert len({phase.duration_s for phase in analysis.phase_analysis.recoveries}) == 2
    assert analysis.session_synthesis.supporting[0].code == "fact.recoveries"
    assert_canonical(analysis, render(analysis, intelligence))


def test_history_without_hr_cannot_reintroduce_a_competing_trend_as_interpretation():
    analysis, intelligence = history_case("garmin-24346252881")
    intelligence.intensity_assessment.hr_used_bpm = None
    intelligence.performance_trend = WIV3PerformanceTrend(
        status="probable_improvement", confidence="high",
        observation_count=4, median_change_sec_per_km=-70.7,
    )
    result = render(analysis, intelligence)
    assert_canonical(analysis, result)
    assert result.interpretation
    assert "performance_trend.median_change_sec_per_km" not in result.evidence_refs


def test_selected_v2_history_is_not_promoted_by_competing_v3_trend_or_low_classification():
    analysis, intelligence = history_case("garmin-24346252881")
    intelligence.performance_trend = WIV3PerformanceTrend(
        status="probable_improvement", confidence="high",
        observation_count=4, median_change_sec_per_km=-70.7,
    )
    result = render(analysis, intelligence)
    assert_canonical(analysis, result)
    assert intelligence.session_classification.confidence == "low"
    assert not any(ref.startswith("performance_trend.") for ref in result.evidence_refs)


def test_unselected_legacy_splits_are_not_reintroduced():
    analysis, intelligence = history_case("garmin-24701222152")
    analysis.meaning.factual_observations.append(WorkoutAnalysisFactualObservation(
        code="fact.pace_change", text="UNSELECTED LEGACY SPLIT",
        evidence={"pace_change_sec_per_km": 999},
    ))
    result = render(analysis, intelligence)
    assert_canonical(analysis, result)
    assert "UNSELECTED" not in result.model_dump_json()
    assert not any(ref.startswith("meaning.factual_observations") for ref in result.evidence_refs)


@pytest.mark.parametrize("language", LANGUAGES)
def test_multiple_candidates_keep_v2_priority_and_supporting_order(language):
    workout = {
        "id": "synthetic-competing-observations", "date": "2026-10-20", "type": "run",
        "distance_km": 4, "duration_minutes": 22, "avg_pace_min_km": 5.5,
        "session_structure": "continuous",
        "km_splits": [{"km": index, "pace_min_km": pace}
                      for index, pace in enumerate((5, 5, 6, 6), 1)],
        "split_analysis": {"pace_drop": 1},
    }
    history = [{**workout, "id": f"synthetic-reference-{day}", "date": f"2026-10-0{day}",
                "avg_pace_min_km": 5} for day in (1, 2)]
    analysis = build_workout_analysis_v2(
        workout, history, language,
        activity_types={row["id"]: "running" for row in [workout, *history]},
    )
    intelligence = build_workout_intelligence_v3(
        extract_workout_intelligence_input(workout, history, v2_analysis=analysis), language,
    )
    assert analysis.session_synthesis.primary.code == "coach.pacing"
    assert [item.code for item in analysis.session_synthesis.supporting] == ["coach.history.pace"]
    result = render(analysis, intelligence, language)
    assert_canonical(analysis, result)
    assert result.interpretation == analysis.session_synthesis.supporting[0].text


def test_no_provider_or_shared_cache_for_canonical_prose_and_no_cross_workout_reuse(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    async def forbidden(*args):
        pytest.fail("Canonical V2 text must remain local")
    with narrative._CACHE_LOCK:
        before = deepcopy(narrative._CACHE)
    for workout_id in AUDIT_FACTS:
        analysis, intelligence = history_case(workout_id)
        result = asyncio.run(narrative.generate_narrative_coach_v3(
            intelligence, "fr", phase_analysis=analysis.phase_analysis,
            coach_language=analysis.coach_language, v2_analysis=analysis, transport=forbidden,
        ))
        assert_canonical(analysis, result)
        assert result.analysis == analysis.session_synthesis.primary.text
    with narrative._CACHE_LOCK:
        assert narrative._CACHE == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_closed_selection_cannot_omit_v2_reserves(language):
    analysis, intelligence = interval_case(language)
    kwargs = dict(phase_analysis=analysis.phase_analysis, coach_language=analysis.coach_language,
                  v2_analysis=analysis)
    context = narrative.build_narrative_context(intelligence, language, **kwargs)
    payload = {"selections": [[index, 0] for index in range(len(context["claims"]))]}
    validated = narrative.validate_narrative_selection(payload, intelligence, language, **kwargs)
    assert validated.analysis == analysis.session_synthesis.primary.text
    assert validated.limitations == render(analysis, intelligence, language).limitations
    payload["selections"] = [
        pair for pair in payload["selections"]
        if context["claims"][pair[0]]["section"] != "limitations"
    ]
    assert narrative.validate_narrative_selection(payload, intelligence, language, **kwargs) is None
