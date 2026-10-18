"""Synthetic measured evidence only: no real athlete data or physiology thresholds."""

import json
import math

import pytest
from pydantic import ValidationError

from activity_phases import ActivityPhase
from coach_language import CoachConclusionV1, CoachLanguageV1
from workout_analysis_v2 import WorkoutAnalysisV2Response, build_workout_analysis_v2


def workout(**updates):
    return dict(id="current", name="Run", date="2026-10-10", type="run",
                distance_km=4, duration_minutes=20, avg_pace_min_km=5,
                is_race=False, **updates)


def session(**updates):
    base = workout()
    base.update(updates)
    return base


def splits(paces=(5, 5, 5.5, 5.5), hrs=None):
    rows = [{"km": index, "pace_min_km": pace} for index, pace in enumerate(paces, 1)]
    if hrs is not None:
        for row, hr in zip(rows, hrs):
            row["avg_hr"] = hr
    return rows


def efforts(paces=(300, 310, 330), hrs=(150, 155, 160), distances=(1000, 1000, 1000)):
    phases = [ActivityPhase(order=0, phase_type="warmup", duration_s=600,
                            distance_m=1000, average_hr=110, source="synthetic")]
    for index, (pace, hr, distance) in enumerate(zip(paces, hrs, distances), 1):
        phases += [
            ActivityPhase(order=index * 2, phase_type="effort", duration_s=pace * distance / 1000,
                          distance_m=distance, average_hr=hr, source="synthetic"),
            ActivityPhase(order=index * 2 + 1, phase_type="recovery", duration_s=100,
                          distance_m=100, average_hr=120, source="synthetic"),
        ]
    return phases


def conclusions(workout=None, phases=None, history=None, language="en"):
    return build_workout_analysis_v2(
        workout or session(), history or [], language, phases,
    ).coach_language.conclusions


def prior(**changes):
    changes = {"avg_heart_rate": 150, **changes}
    return [session(id=f"prior-{index}", date=f"2026-10-0{index}", **changes) for index in (1, 2)]


@pytest.mark.parametrize("language,word", [("fr", "Tu"), ("en", "You"), ("es", "Corres")])
def test_localized_full_session_halves(language, word):
    result = conclusions(session(km_splits=splits()), language=language)
    assert len(result) == 1
    assert result[0].code == "coach.pacing"
    assert word in result[0].text
    assert result[0].evidence["second_half_pace_change_sec_per_km"] == 30
    assert result[0].evidence["coverage"] == "whole_session"


@pytest.mark.parametrize("distance", [4.2, 8])
def test_partial_distance_never_called_session_halves(distance):
    item = conclusions(session(distance_km=distance, km_splits=splits()))[0]
    assert item.evidence["coverage"] == "measured_full_km"
    assert "half" not in item.text
    assert "second_half_pace_change_sec_per_km" not in item.evidence


@pytest.mark.parametrize("pace,direction", [(5.39999, "stable"), (5.4, "slower"),
                                         (5.40001, "slower"), (4.59999, "faster")])
def test_display_threshold_boundaries(pace, direction):
    item = conclusions(session(distance_km=2, km_splits=splits((5, pace))))[0]
    assert item.evidence["direction"] == direction


def test_variable_pace_not_falsely_stable_or_directional():
    item = conclusions(session(distance_km=3, km_splits=splits((5, 6, 5))))[0]
    assert item.evidence["direction"] == "variable"
    assert item.kind == "descriptive"
    assert item.evidence["pace_range_sec_per_km"] == 60


@pytest.mark.parametrize("rows", [
    None, [], [{"km": 1, "pace_min_km": 5}],
    [{"pace_min_km": 5}, {"pace_min_km": 6}],
    [{"km": 1, "pace_min_km": 5}, {"km": 3, "pace_min_km": 6}],
    [{"km": 2, "pace_min_km": 5}, {"km": 1, "pace_min_km": 6}],
    [{"km": True, "pace_min_km": 5}, {"km": 2, "pace_min_km": 6}],
    [{"km": 1, "pace_min_km": 5}, None],
    [{"km": 1, "pace_min_km": 5}, {"km": 2, "pace_min_km": None}],
    [{"km": 1, "pace_min_km": 5}, {"km": 2, "pace_min_km": float("nan")}],
    [{"km": 1, "pace_min_km": 5}, {"km": 2, "pace_min_km": 6, "distance_m": 400}],
])
def test_missing_malformed_gapped_splits_abstain(rows):
    assert conclusions(session(km_splits=rows)) == []


@pytest.mark.parametrize("hrs", [None, (150,), (150, None, 160, 165),
                               (150, 0, 160, 165), (150, float("inf"), 160, 165)])
def test_partial_hr_does_not_cross_with_session_hr_or_drift(hrs):
    item = conclusions(session(km_splits=splits(hrs=hrs), avg_heart_rate=150,
                               hr_analysis={"hr_drift": 20}))[0]
    assert item.code == "coach.pacing"
    assert not any("hr" in key for key in item.evidence)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("paces", [(5, 5, 5, 5), (5, 5.2, 5.4, 5.6), (6, 5.8, 5.6, 5.4)])
def test_same_segments_pace_hr_crossed_without_causality(language, paces):
    items = conclusions(session(km_splits=splits(paces, (145, 150, 155, 160))), language=language)
    assert len(items) == 1
    item = items[0]
    assert item.code == "coach.execution.pace_hr"
    assert item.evidence["heart_rate_change_bpm"] == 15
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == pytest.approx((paces[-1] - paces[0]) * 60)
    assert "second half" not in item.text
    assert not any(word in item.text.lower() for word in ("fatigue", "efficiency", "fitness", "intention"))


def test_hr_without_pace_or_only_session_averages_never_concludes():
    assert conclusions(session(avg_heart_rate=160, hr_analysis={"hr_drift": 10})) == []


def test_repetitions_exclude_warmup_recovery_and_retain_numbers():
    item = conclusions(phases=efforts())[0]
    assert item.code == "coach.repetitions.pace_hr"
    assert item.evidence["comparable_effort_count"] == 3
    assert item.evidence["first_effort_number"] == 1
    assert item.evidence["last_effort_number"] == 3
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == 30
    assert item.evidence["heart_rate_change_bpm"] == 10
    assert item.evidence["pace_range_sec_per_km"] == 30
    assert "fact.effort_hr_evolution" in item.replaces_factual_codes


@pytest.mark.parametrize("hrs", [(150, None, 160), (None, None, None)])
def test_repetition_partial_hr_only_pacing(hrs):
    item = conclusions(phases=efforts(hrs=hrs))[0]
    assert item.code == "coach.repetitions.pacing"
    assert "fact.effort_hr_evolution" not in item.replaces_factual_codes


def test_anchor_cohort_with_incompatible_extremes_abstains():
    # Duration anchors at 100 include both 80 and 125; extremes differ by 36%.
    phases = efforts(paces=(300, 300, 300), distances=(800, 1000, 1250))
    assert conclusions(phases=phases) == []


def test_incomplete_pace_in_selected_cohort_abstains():
    phases = efforts()
    phases[3] = ActivityPhase(order=4, phase_type="effort", duration_s=310,
                             source="synthetic")
    assert conclusions(phases=phases) == []


def test_excluded_efforts_keep_original_numbers():
    phases = efforts(paces=(300, 300, 300), distances=(100, 1000, 1000))
    item = conclusions(phases=phases)[0]
    assert item.evidence["first_effort_number"] == 2
    assert item.evidence["last_effort_number"] == 3
    assert item.evidence["total_effort_count"] == 3


def test_excluded_middle_effort_keeps_exact_number_sequence():
    item = conclusions(phases=efforts(paces=(300, 300, 300),
                                     distances=(1000, 100, 1000)))[0]
    assert item.evidence["effort_numbers"] == "1, 3"
    assert "numbers 1, 3" in item.text


@pytest.mark.parametrize("changes", [{"is_race": None}, {"type": "ride"},
                                    {"distance_km": 10}, {"date": "2025-01-01"}])
def test_history_unknown_nature_wrong_sport_distance_or_date_abstains(changes):
    history = prior(avg_heart_rate=150)
    for row in history:
        row.update(changes)
    assert conclusions(session(avg_heart_rate=155), history=history) == []


def test_history_separate_populations_never_cross():
    history = prior(avg_pace_min_km=None, avg_heart_rate=150)
    history += [session(id=f"pace-{i}", date=f"2026-10-0{i}", avg_heart_rate=None,
                        avg_pace_min_km=5.5) for i in (3, 4)]
    items = conclusions(session(avg_heart_rate=155), history=history)
    assert len(items) == 1
    assert items[0].code == "coach.history.pace"
    assert items[0].evidence["population"] == "pace_only"
    assert not any("heart_rate" in key for key in items[0].evidence)


def test_history_hr_only_without_pace_population():
    items = conclusions(session(avg_pace_min_km=None, avg_heart_rate=155),
                        history=prior(avg_heart_rate=150))
    assert items[0].code == "coach.history.hr"
    assert items[0].evidence["heart_rate_difference_bpm"] == 5


def test_priorities_dedup_and_max_three_without_padding():
    items = conclusions(session(km_splits=splits(hrs=(140, 145, 150, 155))),
                        phases=efforts(), history=prior())
    assert [item.code for item in items] == [
        "coach.execution.pace_hr", "coach.repetitions.pace_hr", "coach.history.pace",
    ]
    assert [item.priority for item in items] == sorted(item.priority for item in items)
    assert len(conclusions()) == 0
    assert len(conclusions(phases=efforts())) == 1


def test_descriptive_last_after_reliable_history():
    items = conclusions(session(distance_km=3, km_splits=splits((5, 6, 5))),
                        history=[{**row, "distance_km": 3} for row in prior()])
    assert [item.code for item in items] == ["coach.history.pace", "coach.pacing"]
    assert [item.priority for item in items] == sorted(item.priority for item in items)


@pytest.mark.parametrize("language,rep_word,history_word", [
    ("fr", "répétitions", "séances"), ("en", "repetitions", "sessions"),
    ("es", "repeticiones", "sesiones"),
])
def test_repetition_and_history_localizations(language, rep_word, history_word):
    items = conclusions(phases=efforts(), history=prior(), language=language)
    assert rep_word in items[0].text
    assert history_word in items[1].text


@pytest.mark.parametrize("pace", [4.5, 5, 5.5])
@pytest.mark.parametrize("hrs", [(160, 150), (150, 150), (150, 160)])
def test_pace_and_hr_directions_have_no_physiological_threshold(pace, hrs):
    item = conclusions(session(distance_km=2, km_splits=splits((5, pace), hrs)))[0]
    assert item.code == "coach.execution.pace_hr"
    assert item.evidence["heart_rate_change_bpm"] == hrs[-1] - hrs[0]
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == (pace - 5) * 60


def test_odd_full_distance_not_called_equal_halves():
    item = conclusions(session(distance_km=3, km_splits=splits((5, 5.5, 6))))[0]
    assert item.evidence["coverage"] == "whole_session"
    assert "half" not in item.text


def test_reported_splits_longer_than_workout_are_rejected():
    assert conclusions(session(distance_km=2, km_splits=splits())) == []


def test_history_insufficient_metric_coverage_is_not_coach_conclusion():
    history = prior()
    history[1]["avg_heart_rate"] = None
    assert conclusions(history=history) == []


def test_history_single_reference_abstains():
    assert conclusions(history=prior()[:1]) == []


def test_complete_partial_cohort_does_not_claim_all_efforts():
    item = conclusions(phases=efforts(paces=(300, 300, 300),
                                     distances=(100, 1000, 1000)))[0]
    assert item.evidence["comparable_effort_count"] == 2
    assert "2 comparable repetitions" in item.text


def test_baseline_average_never_substitutes_for_similar_history():
    history = [session(id="ride", type="ride", date="2026-10-08",
                       avg_pace_min_km=3, avg_heart_rate=130)]
    assert conclusions(history=history) == []


def test_legacy_derived_metrics_do_not_substitute_for_measured_rows():
    assert conclusions(session(split_analysis={"pace_drop": 1, "negative_split": True},
                               hr_analysis={"hr_drift": 10})) == []


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, None, {}, ""])
def test_evidence_contract_rejects_nonfinite_or_invalid(invalid):
    with pytest.raises(ValidationError):
        CoachConclusionV1(code="x", text="x", evidence={"x": invalid},
                          category="pacing", priority=1)


def test_legacy_serialization_and_finite_evidence():
    analysis = build_workout_analysis_v2(session(km_splits=splits()), [])
    payload = analysis.model_dump()
    assert payload["coach_language"]["version"] == "v1"
    for item in payload["coach_language"]["conclusions"]:
        assert item["available"] is True
        assert all(isinstance(value, str) or math.isfinite(value) for value in item["evidence"].values())
    json.dumps(payload, allow_nan=False)
    del payload["coach_language"]
    legacy = WorkoutAnalysisV2Response.model_validate(payload)
    assert legacy.coach_language is None
    assert legacy.meaning == analysis.meaning
    assert legacy.advice == analysis.advice


def test_max_three_contract_enforced():
    item = CoachConclusionV1(code="x", text="x", evidence={"x": 1},
                             category="pacing", priority=1)
    with pytest.raises(ValidationError):
        CoachLanguageV1(conclusions=[item] * 4)
