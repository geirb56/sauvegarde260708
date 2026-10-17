from copy import deepcopy
import math

import pytest
from pydantic import ValidationError

from activity_phases import ActivityPhase
from workout_analysis_v2 import (
    AnalysisText,
    WorkoutAnalysisFactualObservation,
    WorkoutAnalysisMeaning,
    WorkoutAnalysisV2Response,
    _build_meaning,
    _phase_observations,
    build_workout_analysis_v2,
)


LANGUAGES = ["fr", "en", "es"]
PACING_CODES = {"fact.pacing_consistency", "fact.pace_change", "fact.negative_split"}
HISTORY_CODES = {"fact.similar_pace", "fact.similar_hr"}


def workout(**updates):
    return {
        "id": "synthetic-current",
        "name": "Synthetic run",
        "date": "2026-10-10",
        "type": "run",
        "distance_km": 10,
        "duration_minutes": 50,
        "avg_pace_min_km": 5,
        **updates,
    }


def repetitions(*, distances=(800, 850, 820), hrs=(151, 157, 159), durations=None):
    rows = []
    durations = durations or [240] * len(distances)
    for duration, distance, hr in zip(durations, distances, hrs):
        rows.extend([
            ActivityPhase(
                order=len(rows), phase_type="effort", duration_s=duration,
                distance_m=distance, average_hr=hr, source="synthetic",
            ),
            ActivityPhase(
                order=len(rows) + 1, phase_type="recovery", duration_s=180,
                distance_m=200, average_hr=130, source="synthetic",
            ),
        ])
    return rows


def facts(analysis):
    return {fact.code: fact for fact in analysis.meaning.factual_observations}


def history(**updates):
    return [
        workout(id=f"synthetic-prior-{day}", date=f"2026-10-0{day}",
                avg_heart_rate=150, is_race=False, **updates)
        for day in (1, 4)
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_factual_pacing_and_drift_do_not_depend_on_intensity(language):
    analysis = build_workout_analysis_v2(workout(
        km_splits=[{"pace_min_km": 5}, {"pace_min_km": 5.1}],
        split_analysis={"pace_drop": 0.5, "negative_split": True},
        hr_analysis={"hr_drift": 3.5},
        effort_zone_distribution={"z5": 90},
    ), [], language)
    observed = facts(analysis)
    assert set(observed) == PACING_CODES | {"fact.hr_drift_measured"}
    assert analysis.signals.intensity.available is False
    assert observed["fact.pace_change"].evidence == {"pace_drop_min_km": 0.5}
    assert observed["fact.hr_drift_measured"].evidence == {"hr_drift_bpm": 3.5}
    assert "+0:30/km" in observed["fact.pace_change"].text
    assert all(item.placement == "summary" for item in observed.values())
    assert all("intens" not in item.text.lower() for item in observed.values())
    assert all("cause" not in item.text.lower() for item in observed.values())
    assert [item.code for item in analysis.limitations].count("limitations.intensity") == 1
    for item in observed.values():
        assert item.evidence
        assert all(math.isfinite(value) for value in item.evidence.values())
    expected = {
        "fr": "Score de régularité",
        "en": "Recorded pacing consistency",
        "es": "Puntuación de regularidad",
    }
    assert observed["fact.pacing_consistency"].text.startswith(expected[language])


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("splits", [None, [], [{"pace_min_km": 5}]])
def test_absent_or_single_split_does_not_prove_consistency(language, splits):
    analysis = build_workout_analysis_v2(workout(km_splits=splits), [], language)
    assert analysis.meaning.factual_observations == []


@pytest.mark.parametrize("invalid", [None, 0, -1, True, "5", "bad", float("nan"),
                                     float("inf"), float("-inf"), {}, []])
def test_invalid_split_values_are_skipped_without_inventing_pacing(invalid):
    analysis = build_workout_analysis_v2(workout(
        km_splits=[None, [], "bad", {"pace_min_km": invalid}, {"pace_min_km": 5}],
    ), [])
    assert analysis.meaning.factual_observations == []
    assert analysis.pacing.fastest_split_min_km == 5


def test_partial_valid_splits_use_only_valid_numeric_paces():
    analysis = build_workout_analysis_v2(workout(
        km_splits=[
            {"pace_min_km": 5}, {"pace_min_km": None}, {"pace_min_km": float("nan")},
            {"pace_min_km": 5.2}, None,
        ],
    ), [])
    item = facts(analysis)["fact.pacing_consistency"]
    assert item.evidence["valid_split_count"] == 2
    assert item.evidence["consistency_score"] == analysis.pacing.consistency_score


@pytest.mark.parametrize("score", [0, 70, 90, 100])
def test_valid_existing_split_analysis_can_supply_consistency_without_raw_splits(score):
    item = facts(build_workout_analysis_v2(
        workout(split_analysis={"consistency_score": score}), [],
    ))["fact.pacing_consistency"]
    assert item.evidence == {"consistency_score": score, "valid_split_count": 0}


@pytest.mark.parametrize("invalid", [None, True, "bad", -1, 101,
                                     float("nan"), float("inf"), float("-inf")])
def test_invalid_analysis_metrics_never_become_facts(invalid):
    analysis = build_workout_analysis_v2(workout(
        split_analysis={"consistency_score": invalid, "pace_drop": invalid,
                        "negative_split": invalid, "fastest_split_pace": invalid},
        hr_analysis={"hr_drift": invalid},
    ), [])
    # Finite signed drift and changes are valid even when not valid scores.
    observed = facts(analysis)
    assert "fact.pacing_consistency" not in observed
    assert ("fact.negative_split" in observed) is (invalid is True)
    for item in observed.values():
        assert all(math.isfinite(value) for value in item.evidence.values())


@pytest.mark.parametrize("container", ["bad", [], 1])
def test_malformed_metric_containers_are_skipped(container):
    analysis = build_workout_analysis_v2(workout(
        km_splits=container, split_analysis=container, hr_analysis=container,
        pace_stats=container,
    ), [])
    assert analysis.meaning.factual_observations == []


@pytest.mark.parametrize("drop,expected", [
    (0, False), (None, False), (0.3999, False), (-0.3999, False),
    (0.4, True), (-0.4, True),
])
def test_pace_change_significance_uses_existing_unrounded_value(drop, expected):
    observed = facts(build_workout_analysis_v2(
        workout(split_analysis={"pace_drop": drop}), [],
    ))
    assert ("fact.pace_change" in observed) is expected
    if expected:
        assert observed["fact.pace_change"].evidence["pace_drop_min_km"] == drop
        assert ("-" if drop < 0 else "+") in observed["fact.pace_change"].text


def test_faster_split_sequence_alone_does_not_invent_negative_split():
    analysis = build_workout_analysis_v2(workout(
        km_splits=[{"pace_min_km": 6}, {"pace_min_km": 5}, {"pace_min_km": 4}],
    ), [])
    assert "fact.negative_split" not in facts(analysis)


@pytest.mark.parametrize("drift", [0, -3, 3])
def test_zero_and_signed_drift_are_observations_not_missing_values(drift):
    item = facts(build_workout_analysis_v2(
        workout(hr_analysis={"hr_drift": drift}), [],
    ))["fact.hr_drift_measured"]
    assert item.evidence["hr_drift_bpm"] == drift


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("with_recoveries", [False, True])
def test_comparable_efforts_replace_global_pacing_conclusions(language, with_recoveries):
    phases = repetitions()
    if not with_recoveries:
        phases = [phase for phase in phases if phase.phase_type == "effort"]
    analysis = build_workout_analysis_v2(workout(
        km_splits=[{"pace_min_km": 5}, {"pace_min_km": 5}],
        split_analysis={"pace_drop": 1, "negative_split": True, "consistency_score": 95},
    ), [], language, phases)
    observed = facts(analysis)
    assert set(observed) == {
        "fact.effort_dispersion", "fact.effort_extremes", "fact.effort_hr_evolution",
    }
    assert observed["fact.effort_dispersion"].placement == "phases"
    assert observed["fact.effort_extremes"].placement == "summary"
    extremes = observed["fact.effort_extremes"].evidence
    assert extremes["fastest_effort_number"] == 2
    assert extremes["slowest_effort_number"] == 1
    assert extremes["fastest_pace_sec_per_km"] == pytest.approx(240000 / 850)
    assert "151" in observed["fact.effort_hr_evolution"].text
    assert "159" in observed["fact.effort_hr_evolution"].text
    assert observed["fact.effort_hr_evolution"].evidence["average_hr_change_bpm"] == 8
    assert analysis.physiology.hr_drift is None


def test_explicit_interval_structure_suppresses_global_pacing_without_phases():
    analysis = build_workout_analysis_v2(workout(
        session_structure="intervals", split_analysis={
            "pace_drop": 1, "negative_split": True, "consistency_score": 100,
        },
    ), [])
    assert analysis.meaning.factual_observations == []


def test_noncomparable_efforts_do_not_produce_execution_facts():
    analysis = build_workout_analysis_v2(workout(), [], phases=repetitions(
        durations=(60, 240, 600), distances=(100, 800, 2400),
    ))
    assert analysis.meaning.factual_observations == []
    assert "efforts_not_comparable" in analysis.phase_analysis.limitations


def test_partial_pace_coverage_is_preserved_without_claiming_missing_hr():
    analysis = build_workout_analysis_v2(workout(), [], phases=repetitions(
        distances=(800, None, 820), hrs=(151, None, 159),
    ))
    observed = facts(analysis)
    assert set(observed) == {"fact.effort_dispersion", "fact.effort_extremes"}
    assert observed["fact.effort_dispersion"].evidence["pace_sample_count"] == 2
    assert observed["fact.effort_dispersion"].evidence["effort_count"] == 3
    assert analysis.phase_analysis.effort_regularity.partial_comparison is True


def test_equal_efforts_keep_zero_dispersion_and_zero_hr_change_without_extremes():
    observed = facts(build_workout_analysis_v2(workout(), [], phases=repetitions(
        distances=(800, 800, 800), hrs=(150, 150, 150),
    )))
    assert observed["fact.effort_dispersion"].evidence["pace_dispersion_sec_per_km"] == 0
    assert observed["fact.effort_hr_evolution"].evidence["average_hr_change_bpm"] == 0
    assert "fact.effort_extremes" not in observed


@pytest.mark.parametrize("language", LANGUAGES)
def test_history_requires_existing_available_and_comparable_contract(language):
    current = workout(avg_heart_rate=150, is_race=False)
    analysis = build_workout_analysis_v2(current, history(), language)
    assert analysis.comparison.similar.available is True
    assert analysis.comparison.similar.comparable is True
    observed = facts(analysis)
    assert set(observed) == HISTORY_CODES
    assert observed["fact.similar_pace"].evidence["pace_difference_min_km"] == 0
    assert observed["fact.similar_hr"].evidence["heart_rate_difference_bpm"] == 0
    assert observed["fact.similar_pace"].evidence["pace_sample_count"] == 2
    assert "5:00/km" in observed["fact.similar_pace"].text
    assert all("intens" not in item.text.lower() for item in observed.values())


@pytest.mark.parametrize("scenario", ["absent", "single", "unknown_nature", "missing_hr",
                                     "invalid_pace", "distance_mismatch", "race_mismatch"])
def test_unavailable_or_noncomparable_history_does_not_become_facts(scenario):
    current = workout(avg_heart_rate=150, is_race=False)
    prior = history()
    if scenario == "absent":
        prior = []
    elif scenario == "single":
        prior = prior[:1]
    elif scenario == "unknown_nature":
        current.pop("is_race")
    elif scenario == "missing_hr":
        prior[0]["avg_heart_rate"] = None
    elif scenario == "invalid_pace":
        prior[0]["avg_pace_min_km"] = float("nan")
    elif scenario == "distance_mismatch":
        for row in prior:
            row["distance_km"] = 25
    elif scenario == "race_mismatch":
        for row in prior:
            row["is_race"] = True
    analysis = build_workout_analysis_v2(current, prior)
    assert analysis.comparison.similar.comparable is False
    assert facts(analysis) == {}


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("structured", [False, True])
def test_addition_preserves_all_legacy_meaning_fields_and_roundtrips(language, structured):
    current = workout(
        km_splits=[{"pace_min_km": 5}, {"pace_min_km": 5.1}],
        hr_analysis={"hr_drift": 4},
    )
    prior = deepcopy(current)
    analysis = build_workout_analysis_v2(
        current, [], language, repetitions() if structured else None,
    )
    legacy = _build_meaning(
        current, analysis.physiology, analysis.pacing, analysis.comparison,
        analysis.signals, language,
        _phase_observations(analysis.phase_analysis, analysis.signals.session_structure, language),
    )
    assert analysis.meaning.model_dump(exclude={"factual_observations"}) == legacy.model_dump(
        exclude={"factual_observations"},
    )
    assert current == prior
    payload = analysis.model_dump()
    assert WorkoutAnalysisV2Response.model_validate(payload).model_dump() == payload
    payload["meaning"].pop("factual_observations")
    assert WorkoutAnalysisV2Response.model_validate(payload).meaning.factual_observations == []
    payload["meaning"] = AnalysisText(code="legacy", text="Legacy")
    assert WorkoutAnalysisV2Response.model_validate(payload).meaning.factual_observations == []
    assert WorkoutAnalysisMeaning(code="legacy", text="Legacy").factual_observations == []


@pytest.mark.parametrize("evidence", [{}, {"value": float("nan")}, {"value": float("inf")}])
def test_typed_fact_contract_rejects_empty_and_nonfinite_evidence(evidence):
    with pytest.raises(ValidationError):
        WorkoutAnalysisFactualObservation(code="test", text="Test", evidence=evidence)
