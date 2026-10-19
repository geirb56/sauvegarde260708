"""Synthetic history only: independent metric populations, no acquisition or writes."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from workout_analysis_v2 import (
    WorkoutAnalysisSimilarReference,
    WorkoutAnalysisV2Response,
    build_workout_analysis_v2,
)


LANGUAGES = ("fr", "en", "es")
LIMITATION = {
    "fr": "comparabilité reste limitée",
    "en": "comparability remains limited",
    "es": "comparabilidad sigue siendo limitada",
}


def current(**updates):
    return {
        "id": "current", "name": "Synthetic run", "type": "run", "date": "2026-10-10",
        "distance_km": 10, "duration_minutes": 50, "avg_pace_min_km": 5,
        "avg_heart_rate": 150, "is_race": False, **updates,
    }


def history():
    return [
        current(id=f"prior-{index}", date=f"2026-10-0{index}",
                distance_km=distance, avg_pace_min_km=pace, avg_heart_rate=hr)
        for index, (distance, pace, hr) in enumerate(
            [(9, 5.5, 140), (10, 6, 145), (12, 6.5, 150)], 1,
        )
    ]


def historical_facts(analysis):
    return {item.code: item for item in analysis.meaning.factual_observations
            if item.code.startswith("fact.similar_")}


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("metric", ["pace", "hr"])
def test_sufficient_metric_is_not_blocked_by_other_population(language, metric):
    prior = history()
    missing = "avg_heart_rate" if metric == "pace" else "avg_pace_min_km"
    for row in prior[1:]:
        row[missing] = None
    original = deepcopy(prior)
    analysis = build_workout_analysis_v2(current(), prior, language)
    reference = analysis.comparison.similar
    items = analysis.coach_language.conclusions
    assert [item.code for item in items] == [f"coach.history.{metric}"]
    assert set(historical_facts(analysis)) == {f"fact.similar_{metric}"}
    assert reference.comparable is False
    assert reference.session_nature_known is True
    assert getattr(reference, f"{metric}_comparison_status") == "comparable"
    other = "hr" if metric == "pace" else "pace"
    assert getattr(reference, f"{other}_comparison_status") == "unavailable"
    assert getattr(reference, f"{metric}_sample_count") == 3
    assert getattr(reference, f"{other}_sample_count") == 1
    assert items[0].kind == "conclusion"
    assert items[0].metadata["population"] == f"{metric}_only"
    assert f"fact.similar_{metric}" in items[0].replaces_factual_codes
    if metric == "pace":
        assert items[0].evidence["baseline_pace_min_km"] == 6
        assert items[0].evidence["pace_difference_sec_per_km"] == -60
        assert reference.pace_avg_distance_km == pytest.approx(31 / 3, abs=0.001)
        assert not any("heart_rate" in key for key in items[0].evidence)
    else:
        assert items[0].evidence["baseline_heart_rate_bpm"] == 145
        assert items[0].evidence["heart_rate_difference_bpm"] == 5
        assert not any("pace" in key for key in items[0].evidence)
    assert prior == original


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("metric", ["pace", "hr"])
@pytest.mark.parametrize("unknown", ["current", "history"])
def test_unknown_nature_only_allows_explicitly_limited_description(language, metric, unknown):
    selected = current(avg_pace_min_km=None) if metric == "hr" else current()
    prior = history()
    if unknown == "current":
        selected.pop("is_race")
    else:
        prior[1].pop("is_race")
    analysis = build_workout_analysis_v2(selected, prior, language)
    reference = analysis.comparison.similar
    assert reference.session_nature_known is False
    assert reference.comparable is False
    assert getattr(reference, f"{metric}_comparison_status") == "descriptive"
    items = analysis.coach_language.conclusions
    assert [item.code for item in items] == [f"coach.history.{metric}"]
    assert items[0].kind == "descriptive"
    assert LIMITATION[language] in items[0].text
    for item in historical_facts(analysis).values():
        assert LIMITATION[language] in item.text
    texts = " ".join([items[0].text] + [
        item.text for item in historical_facts(analysis).values()
    ]).lower()
    assert not any(word in texts for word in (
        "progress", "efficien", "physiolog", "easy", "facile", "fácil", "continuous",
        "continu", "equivalent", "équivalent", "equivalente",
    ))


@pytest.mark.parametrize("language", LANGUAGES)
def test_known_races_remain_excluded_from_training_comparison(language):
    prior = history()
    for row in prior:
        row["is_race"] = True
    analysis = build_workout_analysis_v2(current(), prior, language)
    assert analysis.comparison.similar.available is False
    assert analysis.comparison.similar.workout_ids == []
    assert analysis.coach_language.conclusions == []
    assert historical_facts(analysis) == {}


@pytest.mark.parametrize("prior", [[], history()[:1]])
def test_no_or_single_reference_never_creates_comparative_conclusion(prior):
    analysis = build_workout_analysis_v2(current(), prior)
    assert analysis.coach_language.conclusions == []
    assert historical_facts(analysis) == {}
    assert analysis.comparison.similar.pace_comparison_status == "unavailable"
    assert analysis.comparison.similar.hr_comparison_status == "unavailable"
    if not prior:
        assert analysis.comparison.similar.avg_pace_min_km is None
        assert analysis.comparison.similar.avg_heart_rate is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_history_does_not_require_or_invent_laps_or_phases(language):
    analysis = build_workout_analysis_v2(current(), history(), language)
    assert [item.code for item in analysis.coach_language.conclusions] == ["coach.history.pace"]
    assert len(analysis.coach_language.conclusions) <= 3
    assert analysis.evidence.has_splits is False
    assert analysis.evidence.has_structured_phases is False
    assert analysis.phase_analysis.phases == []
    assert analysis.pacing.negative_split is None
    assert analysis.physiology.hr_drift is None
    assert set(historical_facts(analysis)) == {"fact.similar_pace", "fact.similar_hr"}


@pytest.mark.parametrize("metric", ["pace", "hr"])
def test_unknown_nature_in_other_population_does_not_taint_measured_metric(metric):
    prior = history()
    prior[2].pop("is_race")
    prior[2]["avg_pace_min_km" if metric == "pace" else "avg_heart_rate"] = None
    analysis = build_workout_analysis_v2(current(), prior)
    assert analysis.comparison.similar.session_nature_known is False
    assert getattr(analysis.comparison.similar, f"{metric}_comparison_status") == "comparable"


@pytest.mark.parametrize("invalid", [None, 0, -1, True, float("nan"), float("inf")])
@pytest.mark.parametrize("metric", ["pace", "hr"])
def test_invalid_current_metric_cannot_be_eligible(invalid, metric):
    selected = current()
    selected["avg_pace_min_km" if metric == "pace" else "avg_heart_rate"] = invalid
    analysis = build_workout_analysis_v2(selected, history())
    assert getattr(analysis.comparison.similar, f"{metric}_comparison_status") == "unavailable"
    assert f"fact.similar_{metric}" not in historical_facts(analysis)
    assert f"coach.history.{metric}" not in [item.code for item in analysis.coach_language.conclusions]


def test_additive_typed_contract_keeps_legacy_fields_and_defaults_safe():
    analysis = build_workout_analysis_v2(current(), history())
    payload = analysis.model_dump()
    similar = payload["comparison"]["similar"]
    assert similar["comparable"] is True
    assert similar["limitations"] == []
    for key in ("pace_comparison_status", "hr_comparison_status"):
        assert similar[key] == "comparable"
        similar.pop(key)
    similar.pop("session_nature_known")
    legacy = WorkoutAnalysisV2Response.model_validate(payload)
    assert legacy.comparison.similar.pace_comparison_status == "unavailable"
    assert legacy.comparison.similar.hr_comparison_status == "unavailable"
    assert legacy.comparison.similar.session_nature_known is False
    assert legacy.comparison.similar.comparable is True
    json.dumps(analysis.model_dump(), allow_nan=False)
    with pytest.raises(ValidationError):
        WorkoutAnalysisSimilarReference(available=True, pace_comparison_status="invented")
