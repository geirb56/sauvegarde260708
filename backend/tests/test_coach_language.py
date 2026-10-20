"""Synthetic measured evidence only: no real athlete data or physiology thresholds."""

import json
import math
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from activity_phases import ActivityPhase
from coach_language import CoachConclusionV1, CoachLanguageV1, build_coach_language
from workout_analysis_v2 import WorkoutAnalysisV2Response, build_workout_analysis_v2


def workout(**updates):
    return dict(id="current", name="Run", date="2026-10-10", type="run",
                distance_km=4, duration_minutes=20, avg_pace_min_km=5,
                is_race=False, **updates)


def session(**updates):
    base = workout()
    base.update(updates)
    return base


def continuous_session(**updates):
    """Explicit synthetic continuous observation with coherent measured timing."""
    rows = updates.get("km_splits", [])
    duration = sum(row.get("duration_s", row["pace_min_km"] * 60
                          * row.get("distance_km", row.get("distance_m", 1000) / 1000))
                   for row in rows)
    covered = sum(row.get("distance_km", row.get("distance_m", 1000) / 1000) for row in rows)
    distance = updates.get("distance_km", 4)
    base = session(session_structure="continuous",
                   duration_minutes=(duration + max(0, distance - covered) * 300) / 60)
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
    result = conclusions(continuous_session(km_splits=splits()), language=language)
    assert len(result) == 1
    assert result[0].code == "coach.pacing"
    assert word in result[0].text
    assert result[0].evidence["second_half_pace_change_sec_per_km"] == 30
    assert result[0].metadata["coverage"] == "whole_session"


@pytest.mark.parametrize("distance", [4.2, 8])
def test_partial_distance_never_called_session_halves(distance):
    item = conclusions(continuous_session(distance_km=distance, km_splits=splits()))[0]
    assert item.metadata["coverage"] == "measured_segments"
    assert "half" not in item.text
    assert "second_half_pace_change_sec_per_km" not in item.evidence


@pytest.mark.parametrize("pace,direction", [(5.39999, "stable"), (5.4, "slower"),
                                         (5.40001, "slower"), (4.59999, "faster")])
def test_display_threshold_boundaries(pace, direction):
    item = conclusions(continuous_session(distance_km=2, km_splits=splits((5, pace))))[0]
    assert item.metadata["direction"] == direction


def test_variable_pace_not_falsely_stable_or_directional():
    item = conclusions(continuous_session(distance_km=3, km_splits=splits((5, 6, 5))))[0]
    assert item.metadata["direction"] == "variable"
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
    assert conclusions(session(session_structure="continuous", km_splits=rows)) == []


@pytest.mark.parametrize("hrs", [None, (150,), (150, None, 160, 165)])
def test_partial_hr_does_not_cross_with_session_hr_or_drift(hrs):
    item = conclusions(continuous_session(km_splits=splits(hrs=hrs), avg_heart_rate=150,
                               hr_analysis={"hr_drift": 20}))[0]
    assert item.code == "coach.pacing"
    assert not any("hr" in key for key in item.evidence)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("paces", [(5, 5, 5, 5), (5, 5.2, 5.4, 5.6), (6, 5.8, 5.6, 5.4)])
def test_same_segments_pace_hr_crossed_without_causality(language, paces):
    rows = splits(paces, (145, 150, 155, 160))
    for row in rows:
        row["duration_s"] = row["pace_min_km"] * 60
    items = conclusions(continuous_session(km_splits=rows), language=language)
    assert len(items) == 1
    item = items[0]
    assert item.code == "coach.execution.pace_hr"
    first_hr = sum(row["avg_hr"] * row["duration_s"] for row in rows[:2]) / sum(
        row["duration_s"] for row in rows[:2])
    last_hr = sum(row["avg_hr"] * row["duration_s"] for row in rows[2:]) / sum(
        row["duration_s"] for row in rows[2:])
    assert item.evidence["heart_rate_change_bpm"] == pytest.approx(last_hr - first_hr)
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == pytest.approx((paces[-1] - paces[0]) * 60)
    assert item.metadata["comparison_scope"] == "equal_distance_halves"
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
    analysis = build_workout_analysis_v2(session(), [], phases=phases)
    assert analysis.coach_language.conclusions == []
    assert analysis.coach_language.limitations == ["repetitions.insufficient_comparability"]
    assert [p.effort_number for p in analysis.phase_analysis.efforts] == [1, 2, 3]


def test_excluded_middle_effort_keeps_exact_number_sequence():
    analysis = build_workout_analysis_v2(
        session(), [], phases=efforts(paces=(300, 300, 300), distances=(1000, 100, 1000)),
    )
    assert analysis.coach_language.conclusions == []
    assert analysis.coach_language.limitations == ["repetitions.insufficient_comparability"]
    assert [p.effort_number for p in analysis.phase_analysis.efforts] == [1, 2, 3]


@pytest.mark.parametrize("changes", [{"is_race": None}, {"type": "ride"},
                                    {"distance_km": 10}, {"date": "2025-01-01"}])
def test_history_unknown_nature_describes_but_wrong_sport_distance_or_date_abstains(changes):
    history = prior(avg_heart_rate=150)
    for row in history:
        row.update(changes)
    items = conclusions(session(avg_heart_rate=155), history=history)
    if changes == {"is_race": None}:
        assert [item.code for item in items] == ["coach.history.pace"]
        assert items[0].kind == "descriptive"
        assert "comparability remains limited" in items[0].text
    else:
        assert items == []


def test_history_separate_populations_never_cross():
    history = prior(avg_pace_min_km=None, avg_heart_rate=150)
    history += [session(id=f"pace-{i}", date=f"2026-10-0{i}", avg_heart_rate=None,
                        avg_pace_min_km=5.5) for i in (3, 4)]
    items = conclusions(session(avg_heart_rate=155), history=history)
    assert len(items) == 1
    assert items[0].code == "coach.history.pace"
    assert items[0].metadata["population"] == "pace_only"
    assert not any("heart_rate" in key for key in items[0].evidence)


def test_history_hr_only_without_pace_population():
    items = conclusions(session(avg_pace_min_km=None, avg_heart_rate=155),
                        history=prior(avg_heart_rate=150))
    assert items[0].code == "coach.history.hr"
    assert items[0].evidence["heart_rate_difference_bpm"] == 5


def test_priorities_dedup_and_max_three_without_padding():
    items = conclusions(continuous_session(km_splits=splits(hrs=(140, 145, 150, 155))),
                        phases=efforts(), history=prior())
    assert [item.code for item in items] == [
        "coach.repetitions.pace_hr", "coach.history.pace",
    ]
    assert [item.priority for item in items] == sorted(item.priority for item in items)
    assert len(conclusions()) == 0
    assert len(conclusions(phases=efforts())) == 1
    assert len(items) <= 3
    assert len({item.category for item in items}) == len(items)


@pytest.mark.parametrize("phase_type", ["warmup", "cooldown", "recovery"])
@pytest.mark.parametrize("hrs", [None, (140, 145, 150, 155)])
def test_mixed_phase_blocks_global_km_inference(phase_type, hrs):
    phase = ActivityPhase(order=0, phase_type=phase_type, duration_s=300,
                          distance_m=1000, source="synthetic")
    assert conclusions(continuous_session(km_splits=splits(hrs=hrs)), phases=[phase]) == []


@pytest.mark.parametrize("structure", ["intervals", {"code": "intervals", "available": True}])
@pytest.mark.parametrize("hrs", [None, (140, 145, 150, 155)])
def test_explicit_intervals_block_global_km_inference(structure, hrs):
    assert conclusions(continuous_session(session_structure=structure, km_splits=splits(hrs=hrs))) == []


def test_multiple_efforts_without_recovery_block_global_km_inference():
    phases = [phase for phase in efforts() if phase.phase_type == "effort"]
    items = conclusions(continuous_session(km_splits=splits(hrs=(140, 145, 150, 155))), phases=phases)
    assert [item.category for item in items] == ["repetitions"]


def test_nonmonotonic_pace_halves_do_not_borrow_endpoint_hr():
    item = conclusions(continuous_session(km_splits=splits((5, 6, 4, 5.5), (150, 160, 140, 155))))[0]
    assert item.metadata["comparison_scope"] == "equal_distance_halves"
    assert item.code == "coach.pacing"
    assert item.evidence["second_half_pace_change_sec_per_km"] == -45
    assert not any("hr" in key for key in item.evidence)
    assert "progressively" not in item.text and "drift" not in item.text


@pytest.mark.parametrize("language,relationship", [
    ("fr", "premier et ton dernier"), ("en", "first and last"), ("es", "primer y último"),
])
def test_stable_pace_cross_is_relationship_not_unrelated_facts(language, relationship):
    item = conclusions(continuous_session(km_splits=splits((5, 5, 5, 5), (145, 150, 155, 160))),
                       language=language)[0]
    assert relationship in item.text
    assert "first" in item.text if language == "en" else True


@pytest.mark.parametrize("pace,direction", [(4.5, "faster"), (5.5, "slower"), (5, "matches")])
def test_history_direction_baseline_and_current_are_explicit(pace, direction):
    item = conclusions(session(avg_pace_min_km=pace), history=prior())[0]
    assert direction in item.text
    assert item.evidence["baseline_pace_min_km"] == 5
    assert item.evidence["current_pace_min_km"] == pace
    assert "positive" not in item.text and "gap" not in item.text


@pytest.mark.parametrize("hr,direction", [(140, "lower"), (160, "higher"), (150, "matches")])
def test_hr_history_direction_baseline_and_current_are_explicit(hr, direction):
    item = conclusions(session(avg_pace_min_km=None, avg_heart_rate=hr), history=prior())[0]
    assert direction in item.text
    assert item.evidence["baseline_heart_rate_bpm"] == 150
    assert item.evidence["current_heart_rate_bpm"] == hr


def test_crossed_execution_replaces_single_pace_phenomenon():
    items = conclusions(continuous_session(km_splits=splits(hrs=(145, 150, 155, 160))), history=prior())
    assert [item.category for item in items] == ["pacing", "history"]
    assert [item.priority for item in items] == sorted(item.priority for item in items)
    assert len({item.category for item in items}) == len(items)
    assert len(items) <= 3


@pytest.mark.parametrize("hrs", [None, (145, 150, 155, 160)])
def test_km_endpoint_evidence_is_independently_auditable(hrs):
    item = conclusions(continuous_session(km_splits=splits(hrs=hrs)))[0]
    assert item.evidence["first_pace_sec_per_km"] == 300
    assert item.evidence["last_pace_sec_per_km"] == 330
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == (
        item.evidence["last_pace_sec_per_km"] - item.evidence["first_pace_sec_per_km"]
    )


def test_half_comparison_includes_both_measured_means():
    item = conclusions(continuous_session(km_splits=splits()))[0]
    assert item.evidence["first_half_pace_sec_per_km"] == 300
    assert item.evidence["second_half_pace_sec_per_km"] == 330
    assert item.evidence["second_half_pace_change_sec_per_km"] == (
        item.evidence["second_half_pace_sec_per_km"] - item.evidence["first_half_pace_sec_per_km"]
    )


def test_repetition_endpoint_evidence_is_independently_auditable():
    item = conclusions(phases=efforts())[0]
    assert item.evidence["first_pace_sec_per_km"] == 300
    assert item.evidence["last_pace_sec_per_km"] == 330
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == (
        item.evidence["last_pace_sec_per_km"] - item.evidence["first_pace_sec_per_km"]
    )


def test_informative_variability_precedes_relevant_history():
    items = conclusions(continuous_session(distance_km=3, km_splits=splits((5, 6, 5))),
                        history=[{**row, "distance_km": 3, "avg_pace_min_km": 5.5} for row in prior()])
    assert [item.code for item in items] == ["coach.pacing", "coach.history.pace"]
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
    item = conclusions(continuous_session(distance_km=2, km_splits=splits((5, pace), hrs)))[0]
    if pace == 5:
        assert item.code == "coach.execution.pace_hr"
        assert item.evidence["heart_rate_change_bpm"] == hrs[-1] - hrs[0]
    else:
        assert item.code == "coach.pacing"
        assert item.metadata["comparison_scope"] == "equal_distance_halves"
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == (pace - 5) * 60


def test_odd_full_distance_not_called_equal_halves():
    item = conclusions(continuous_session(distance_km=3, km_splits=splits((5, 5.5, 6))))[0]
    assert item.metadata["coverage"] == "whole_session"
    assert "half" not in item.text


def test_reported_splits_longer_than_workout_are_rejected():
    assert conclusions(continuous_session(distance_km=2, km_splits=splits())) == []


def test_history_insufficient_hr_coverage_does_not_block_pace_conclusion():
    history = prior()
    history[1]["avg_heart_rate"] = None
    items = conclusions(history=history)
    assert [item.code for item in items] == ["coach.history.pace"]
    assert not any("heart_rate" in key for key in items[0].evidence)


def test_history_single_reference_abstains():
    assert conclusions(history=prior()[:1]) == []


def test_complete_partial_cohort_does_not_claim_all_efforts():
    phases = efforts(paces=(300, 300, 300), distances=(100, 1000, 1000))
    analysis = build_workout_analysis_v2(session(), [], phases=phases)
    assert analysis.coach_language.conclusions == []
    assert analysis.phase_analysis.effort_regularity.comparable_effort_count == 2


def test_baseline_average_never_substitutes_for_similar_history():
    history = [session(id="ride", type="ride", date="2026-10-08",
                       avg_pace_min_km=3, avg_heart_rate=130)]
    assert conclusions(history=history) == []


def test_legacy_derived_metrics_do_not_substitute_for_measured_rows():
    assert conclusions(session(split_analysis={"pace_drop": 1, "negative_split": True},
                               hr_analysis={"hr_drift": 10})) == []


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, None,
                                    {}, "", "5", "stable"])
def test_evidence_contract_rejects_nonfinite_or_invalid(invalid):
    with pytest.raises(ValidationError):
        CoachConclusionV1(code="x", text="x", evidence={"x": invalid},
                          category="pacing", priority=1)


def test_legacy_serialization_and_finite_evidence():
    analysis = build_workout_analysis_v2(continuous_session(km_splits=splits()), [])
    payload = analysis.model_dump()
    assert payload["coach_language"]["version"] == "v1"
    for item in payload["coach_language"]["conclusions"]:
        assert item["available"] is True
        assert all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) for value in item["evidence"].values())
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


def full_session_phase(value, **updates):
    fields = dict(order=0, phase_type="effort",
                  duration_s=value["duration_minutes"] * 60,
                  distance_m=value["distance_km"] * 1000, source="synthetic")
    fields.update(updates)
    return ActivityPhase(**fields)


@pytest.mark.parametrize("language,word", [("fr", "Tu"), ("en", "You"), ("es", "Corres")])
@pytest.mark.parametrize("raw_structure", [
    "omitted", None, "intervals", {"code": "continuous", "available": False},
])
def test_canonical_continuous_observation_is_authority_not_raw_label(language, word, raw_structure):
    value = continuous_session(km_splits=splits())
    if raw_structure == "omitted":
        del value["session_structure"]
    else:
        value["session_structure"] = raw_structure
    analysis = build_workout_analysis_v2(value, [], language, [full_session_phase(value)])
    assert analysis.signals.session_structure.available is True
    assert analysis.signals.session_structure.code == "continuous"
    item, = analysis.coach_language.conclusions
    assert item.code == "coach.pacing"
    assert word in item.text
    assert item.metadata["coverage"] == "whole_session"
    assert item.evidence["second_half_pace_change_sec_per_km"] == 30


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("structure", ["intervals", "unavailable"])
def test_canonical_noncontinuous_observation_blocks_global_conclusions(language, structure):
    value = continuous_session(km_splits=splits())
    phases = efforts() if structure == "intervals" else [full_session_phase(value, phase_type="unknown")]
    analysis = build_workout_analysis_v2(value, [], language, phases)
    signal = analysis.signals.session_structure
    assert signal.available is (structure == "intervals")
    assert signal.code == ("intervals" if structure == "intervals" else None)
    assert not {"coach.pacing", "coach.execution.pace_hr"} & {
        item.code for item in analysis.coach_language.conclusions
    }


@pytest.mark.parametrize("offset", [-30, 30])
def test_coach_duration_rounding_does_not_override_canonical_short_session_classification(offset):
    value = continuous_session(distance_km=2, km_splits=splits((3.5, 4)),
                               duration_minutes=(450 + offset) / 60)
    del value["session_structure"]
    phase = full_session_phase(value, duration_s=450)
    analysis = build_workout_analysis_v2(value, [], phases=[phase])
    assert analysis.signals.session_structure.code == "other"
    assert analysis.coach_language.conclusions == []


@pytest.mark.parametrize("guard", ["distance", "phase_pace", "split_time", "duration"])
def test_canonical_continuous_is_necessary_not_sufficient_for_coherent_measurements(guard):
    value = continuous_session(distance_km=11, km_splits=splits([5] * 11))
    del value["session_structure"]
    phase_updates = {}
    if guard == "distance":
        phase_updates["distance_m"] = 9000
    elif guard == "phase_pace":
        phase_updates["average_speed_mps"] = 10
    elif guard == "split_time":
        value["km_splits"][0]["duration_s"] = 600
    else:
        # 31 s fits V2's relative 1% but not Coach's absolute rounding allowance.
        phase_updates["duration_s"] = value["duration_minutes"] * 60 - 31
    analysis = build_workout_analysis_v2(value, [], phases=[full_session_phase(value, **phase_updates)])
    assert analysis.signals.session_structure.available is True
    assert analysis.signals.session_structure.code == "continuous"
    assert analysis.coach_language.conclusions == []


@pytest.mark.parametrize("phase_type", ["warmup", "recovery", "unknown"])
@pytest.mark.parametrize("mixed", [False, True])
def test_direct_canonical_continuous_cannot_override_contradictory_phases(phase_type, mixed):
    value = continuous_session(km_splits=splits())
    phases = [full_session_phase(value, phase_type=phase_type)]
    if mixed:
        phases.insert(0, full_session_phase(value, order=1))
    analysis = build_workout_analysis_v2(value, [], phases=phases)
    result = build_coach_language(
        value, analysis.phase_analysis, analysis.comparison, [], None, lambda *_: False,
        session_structure=SimpleNamespace(available=True, code="continuous"),
    )
    assert result.conclusions == []


@pytest.mark.parametrize("signal", [
    None, SimpleNamespace(available=False, code="continuous"),
    SimpleNamespace(available=True, code="intervals"),
    SimpleNamespace(available=True, code=None),
    SimpleNamespace(available=1, code="continuous"),
    SimpleNamespace(code="continuous"), SimpleNamespace(available=True),
])
def test_direct_missing_or_noncontinuous_canonical_signal_abstains_despite_raw_continuous(signal):
    value = continuous_session(km_splits=splits())
    analysis = build_workout_analysis_v2(value, [])
    assert analysis.coach_language.conclusions
    result = build_coach_language(
        value, analysis.phase_analysis, analysis.comparison, [], None, lambda *_: False,
        session_structure=signal,
    )
    assert result.conclusions == []


def test_direct_legacy_positional_language_remains_compatible_and_safely_abstains():
    value = continuous_session(km_splits=splits())
    analysis = build_workout_analysis_v2(value, [])
    args = (value, analysis.phase_analysis, analysis.comparison, [], None, lambda *_: False, "fr")
    assert build_coach_language(*args).conclusions == []
    result = build_coach_language(*args, session_structure=analysis.signals.session_structure)
    assert "Tu" in result.conclusions[0].text
    with pytest.raises(TypeError):
        build_coach_language(*args, analysis.signals.session_structure)


def test_canonical_signal_handoff_keeps_exact_serialized_api_fields():
    value = continuous_session(km_splits=splits())
    del value["session_structure"]
    payload = build_workout_analysis_v2(value, [], phases=[full_session_phase(value)]).model_dump()
    assert set(payload) == {
        "version", "workout", "summary", "signals", "physiology", "pacing", "comparison",
        "meaning", "advice", "evidence", "limitations", "phase_analysis", "coach_language",
    }
    assert set(payload["signals"]["session_structure"]) == {
        "available", "code", "text", "reason_unavailable",
    }
    assert set(payload["coach_language"]) == {"version", "conclusions", "limitations"}
    item, = payload["coach_language"]["conclusions"]
    assert set(item) == {
        "code", "text", "evidence", "metadata", "category", "priority", "available",
        "kind", "replaces_factual_codes",
    }
    assert item["available"] is True
    json.dumps(payload, allow_nan=False)


def measured_segments(distances, paces, hrs=None):
    """Explicit test-only segments; no claim that a production producer exists."""
    return [
        dict(km=index, distance_km=distance, duration_s=distance * pace * 60,
             pace_min_km=pace, **({"avg_hr": hrs[index - 1]} if hrs is not None else {}))
        for index, (distance, pace) in enumerate(zip(distances, paces), 1)
    ]


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("distance", [9.33, 11.4])
@pytest.mark.parametrize("with_tail", [False, True])
def test_canonical_no_raw_full_phase_preserves_measured_tail_and_midpoint_scope(
    language, distance, with_tail,
):
    whole = int(distance)
    rows = measured_segments([1] * whole, [5 + i * 0.1 for i in range(whole)],
                             [150 + i for i in range(whole)])
    if with_tail:
        rows += measured_segments([distance - whole], [6], [170])
        rows[-1]["km"] = whole + 1
    value = continuous_session(distance_km=distance, km_splits=rows)
    del value["session_structure"]
    analysis = build_workout_analysis_v2(value, [], language, [full_session_phase(value)])
    assert analysis.signals.session_structure.code == "continuous"
    item, = analysis.coach_language.conclusions
    assert item.metadata["comparison_scope"] == "first_last_measured_segments"
    assert item.metadata["coverage"] == ("whole_session" if with_tail else "measured_segments")
    assert item.evidence["measured_distance_km"] == pytest.approx(distance if with_tail else whole)
    assert not any("half" in key for key in item.evidence)
    assert item.evidence["first_hr_bpm"] == 150
    assert item.evidence["last_hr_bpm"] == (170 if with_tail else 150 + whole - 1)


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("hrs", [None, (150, 150, 150, 150, 170, 170, 170, 150)])
def test_cancelling_endpoints_cannot_erase_significant_halves(language, hrs):
    rows = splits((5, 5, 5, 5, 6, 6, 6, 5), hrs)
    item = conclusions(continuous_session(distance_km=8, km_splits=rows), language=language)[0]
    assert item.code == "coach.pacing"
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == 0
    assert item.evidence["second_half_pace_change_sec_per_km"] == 45
    assert item.metadata["comparison_scope"] == "equal_distance_halves"
    assert not any("hr" in key for key in item.evidence)
    assert "45" in item.text
    assert item.priority == 20
    if language == "fr":
        assert item.text == (
            "Sur tes 8 segments mesurés (8 km) : Tu cours la seconde moitié en distance "
            "de ta séance 45 s/km plus lentement."
        )


def test_duration_weighted_hr_uses_interior_observations_not_endpoints():
    rows = measured_segments((1, 1, 1, 1), (5, 5, 6, 5), (150, 150, 180, 150))
    item = conclusions(continuous_session(km_splits=rows), language="fr")[0]
    assert item.code == "coach.execution.pace_hr"
    assert item.evidence["first_half_hr_bpm"] == 150
    assert item.evidence["second_half_hr_bpm"] == pytest.approx(109800 / 660)
    assert item.evidence["second_half_pace_change_sec_per_km"] == 30
    assert "first_hr_bpm" not in item.evidence
    assert item.text == (
        "Sur tes 4 segments mesurés (4 km) : Tu cours la seconde moitié en distance "
        "de ta séance 30 s/km plus lentement, avec une FC moyenne de 150 puis "
        "166.4 bpm sur ces mêmes moitiés."
    )


@pytest.mark.parametrize("missing_index", [0, 1, 2, 3])
def test_one_missing_measured_duration_prevents_half_hr_aggregation(missing_index):
    rows = measured_segments((1, 1, 1, 1), (5, 5, 6, 6), (150, 155, 160, 165))
    del rows[missing_index]["duration_s"]
    item = conclusions(continuous_session(km_splits=rows))[0]
    assert item.code == "coach.pacing"
    assert item.evidence["second_half_pace_change_sec_per_km"] == 60
    assert not any("hr" in key for key in item.evidence)


@pytest.mark.parametrize("distance", [8, 9, 9.33, 11.4])
@pytest.mark.parametrize("with_hr", [False, True])
def test_explicit_unequal_segments_at_exact_midpoint_have_true_weighted_halves(distance, with_hr):
    half = distance / 2
    distances = (1, half - 1, half - 1, 1)
    paces = (4, 5, 6, 5)
    rows = measured_segments(distances, paces, (140, 150, 170, 160) if with_hr else None)
    item = conclusions(continuous_session(distance_km=distance, km_splits=rows))[0]
    first = (240 + (half - 1) * 300) / half
    second = ((half - 1) * 360 + 300) / half
    assert item.evidence["first_half_pace_sec_per_km"] == pytest.approx(first)
    assert item.evidence["second_half_pace_sec_per_km"] == pytest.approx(second)
    assert item.evidence["second_half_pace_change_sec_per_km"] == pytest.approx(second - first)
    assert first != 270  # Arithmetic mean of the two paces would be wrong.
    assert item.metadata["comparison_scope"] == "equal_distance_halves"
    assert item.metadata["coverage"] == "whole_session"
    if with_hr:
        expected_hr = (140 * 240 + 150 * (half - 1) * 300) / (half * first)
        assert item.evidence["first_half_hr_bpm"] == pytest.approx(expected_hr)
        assert item.priority == 10
    else:
        assert item.code == "coach.pacing"


@pytest.mark.parametrize("distance", [9, 9.33, 11.4])
@pytest.mark.parametrize("with_tail", [False, True])
def test_midpoint_inside_recorded_segment_is_not_manufactured(distance, with_tail):
    whole = int(distance)
    paces = [5 + i * 0.1 for i in range(whole)]
    rows = measured_segments([1] * whole, paces, [150 + i for i in range(whole)])
    if with_tail and distance != whole:
        rows += measured_segments([distance - whole], [6], [170])
        rows[-1]["km"] = whole + 1
    item = conclusions(continuous_session(distance_km=distance, km_splits=rows))[0]
    assert item.metadata["comparison_scope"] == "first_last_measured_segments"
    assert "half" not in item.text
    assert "first_half_pace_sec_per_km" not in item.evidence
    expected_coverage = "whole_session" if with_tail or distance == whole else "measured_segments"
    assert item.metadata["coverage"] == expected_coverage
    assert item.evidence["measured_distance_km"] == pytest.approx(
        distance if with_tail else whole)


def test_eight_whole_km_can_use_pace_only_halves_without_measured_time():
    rows = splits((5, 5, 5, 5, 6, 6, 6, 6))
    item = conclusions(continuous_session(distance_km=8, km_splits=rows))[0]
    assert item.evidence["second_half_pace_change_sec_per_km"] == 60
    assert item.metadata["comparison_scope"] == "equal_distance_halves"


@pytest.mark.parametrize("distance", [9.33, 11.4])
@pytest.mark.parametrize("tail", [
    {"distance_km": None, "duration_s": 120},
    {"distance_km": 0, "duration_s": 120},
    {"distance_km": -0.33, "duration_s": 120},
    {"distance_km": float("nan"), "duration_s": 120},
    {"distance_km": True, "duration_s": 120},
    {"distance_m": 330, "duration_s": 120},  # Incoherent pace or session distance.
    {"distance_km": 0.33},  # No measured duration: no extrapolated tail.
    {"distance_km": 0.33, "duration_s": 0},
    {"distance_km": 0.33, "duration_s": None},
    {"distance_km": 0.33, "duration_s": float("inf")},
    {"distance_km": 0.33, "duration_s": True},
    {"distance_km": 0.33, "duration_s": 99, "distance_m": 400},
    {"distance_km": 0.33, "duration_s": 99, "duration_unit": "minutes"},
    {"distance_km": 0.33, "duration_s": 99, "pace_unit": "sec/km"},
])
def test_invalid_explicit_tail_is_rejected_not_silently_dropped(distance, tail):
    rows = splits([5] * int(distance))
    rows += [dict(km=len(rows) + 1, pace_min_km=5, **tail)]
    assert conclusions(session(distance_km=distance, duration_minutes=60,
                               session_structure="continuous", km_splits=rows)) == []


@pytest.mark.parametrize("structure", [None, "other", "unknown", "intervals",
                                      {"code": "continuous", "available": False},
                                      {"code": None}, {}])
def test_unknown_or_explicit_other_structure_abstains(structure):
    value = continuous_session(km_splits=splits(), session_structure=structure)
    assert conclusions(value) == []


def test_no_structure_even_with_complete_km_rows_abstains():
    value = continuous_session(km_splits=splits())
    del value["session_structure"]
    assert conclusions(value) == []


@pytest.mark.parametrize("phase_type", ["warmup", "cooldown", "recovery", "unknown"])
def test_unknown_or_mixed_observed_phase_overrides_continuous_label(phase_type):
    value = continuous_session(km_splits=splits())
    phases = [
        ActivityPhase(order=0, phase_type="effort", duration_s=1260,
                      distance_m=4000, source="synthetic"),
        ActivityPhase(order=1, phase_type=phase_type, duration_s=30,
                      distance_m=100, source="synthetic"),
    ]
    assert conclusions(value, phases=phases) == []


@pytest.mark.parametrize("distance,duration", [(4000, 1260), (None, 1260), (4000, None),
                                             (2000, 1260), (4000, 600)])
def test_single_effort_requires_both_full_session_distance_and_duration(distance, duration):
    value = continuous_session(km_splits=splits())
    del value["session_structure"]
    phase = ActivityPhase(order=0, phase_type="effort", duration_s=duration,
                          distance_m=distance, source="synthetic")
    items = conclusions(value, phases=[phase])
    assert bool(items) == (distance == 4000 and duration == 1260)


@pytest.mark.parametrize("updates", [
    {"duration_minutes": 20}, {"duration_minutes": 100}, {"duration_minutes": None},
    {"duration_minutes": True}, {"distance_km": None}, {"distance_km": 0},
])
def test_incoherent_session_totals_abstain(updates):
    value = continuous_session(km_splits=splits())
    value.update(updates)
    assert conclusions(value) == []


@pytest.mark.parametrize("invalid", [0, -1, True, float("inf"), float("nan"), "150"])
@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("measured_time", [False, True])
def test_explicit_invalid_hr_blocks_cross_but_preserves_reliable_pace(invalid, language, measured_time):
    rows = splits(hrs=(150, invalid, 160, 165))
    if measured_time:
        for row in rows:
            row["duration_s"] = row["pace_min_km"] * 60
    value = continuous_session(km_splits=rows)
    item = conclusions(value, language=language)[0]
    assert item.code == "coach.pacing"
    assert item.evidence["second_half_pace_change_sec_per_km"] == 30
    assert item.metadata["comparison_scope"] == "equal_distance_halves"
    assert not any("hr" in key for key in item.evidence)


@pytest.mark.parametrize("invalid", [0, float("nan")])
@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_invalid_interior_hr_preserves_pace_only_without_recoverable_halves(invalid, language):
    rows = measured_segments((1, 1, 1), (5, 5.1, 6), (150, invalid, 160))
    item = conclusions(continuous_session(distance_km=3, km_splits=rows), language=language)[0]
    assert item.code == "coach.pacing"
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == 60
    assert "first_half_pace_sec_per_km" not in item.evidence
    assert not any("hr" in key for key in item.evidence)


def test_partial_distance_units_and_missing_variable_distances_abstain():
    rows = measured_segments((1, 1, 1, 1), (5, 5, 6, 6))
    rows[0]["distance_m"] = 1000
    assert conclusions(continuous_session(km_splits=rows))
    rows[0]["distance_unit"] = "miles"
    assert conclusions(continuous_session(km_splits=rows)) == []
    rows = measured_segments((1.5, 0.5, 1, 1), (5, 5, 6, 6))
    del rows[1]["distance_km"]
    assert conclusions(continuous_session(km_splits=rows)) == []


@pytest.mark.parametrize("distance", [9.33, 11.4])
def test_measured_final_tail_accepts_consistent_cumulative_label(distance):
    rows = splits([5] * int(distance))
    tail_distance = distance - int(distance)
    rows += [dict(km=distance, pace_min_km=5, distance_m=tail_distance * 1000,
                  duration_s=tail_distance * 300)]
    item = conclusions(continuous_session(distance_km=distance, km_splits=rows))[0]
    assert item.metadata["coverage"] == "whole_session"
    assert item.evidence["measured_distance_km"] == pytest.approx(distance)
    assert "first_half_pace_sec_per_km" not in item.evidence


def test_explicit_segment_distances_do_not_license_arbitrary_gapped_labels():
    rows = measured_segments((1, 1), (5, 6))
    rows[-1]["km"] = 3
    assert conclusions(continuous_session(distance_km=2, km_splits=rows)) == []


def test_mixed_ordinal_and_cumulative_label_conventions_are_rejected():
    rows = measured_segments((1, 3.5, 3.5, 1), (5, 5, 6, 6))
    for row, label in zip(rows, (1, 2, 8, 9)):
        row["km"] = label
    assert conclusions(continuous_session(distance_km=9, km_splits=rows)) == []


def test_limited_measured_scope_keeps_fractional_distance_precision():
    rows = measured_segments([1] * 9 + [0.33], [5] * 9 + [5.5])
    item = conclusions(continuous_session(distance_km=11.4, km_splits=rows))[0]
    assert item.metadata["coverage"] == "measured_segments"
    assert item.evidence["measured_distance_km"] == pytest.approx(9.33)
    assert "(9.33 km)" in item.text
    assert "(9.3 km)" not in item.text


def test_equal_half_aggregates_cannot_hide_interior_variability():
    rows = measured_segments((1, 1, 1, 1), (5, 6, 6, 5), (150, 150, 150, 150))
    item = conclusions(continuous_session(km_splits=rows))[0]
    assert item.code == "coach.pacing"
    assert item.metadata["direction"] == "variable"
    assert "varies by 60" in item.text
    assert item.priority == 30


def test_equal_half_aggregates_cannot_hide_significant_endpoint_evolution():
    rows = measured_segments((1, 1, 1, 1), (4, 6, 5, 5), (150, 150, 150, 150))
    item = conclusions(continuous_session(km_splits=rows))[0]
    assert item.metadata["comparison_scope"] == "first_last_measured_segments"
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == 60
    assert item.metadata["direction"] == "slower"
    assert item.priority == 10


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("paces_sec,code,direction,scope", [
    ((240, 360, 300, 300), "coach.execution.pace_hr", "slower", "first_last_measured_segments"),
    ((300, 340, 300, 300), "coach.pacing", "variable", "measured_segments"),
])
def test_changing_half_hr_cannot_hide_informative_series_pace(
    language, paces_sec, code, direction, scope,
):
    rows = measured_segments((1, 1, 1, 1), [pace / 60 for pace in paces_sec],
                             (150, 150, 170, 170))
    item = conclusions(continuous_session(km_splits=rows), language=language)[0]
    assert item.code == code
    assert item.metadata["direction"] == direction
    assert item.metadata["comparison_scope"] == scope
    assert item.evidence["pace_range_sec_per_km"] == max(paces_sec) - min(paces_sec)
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == paces_sec[-1] - paces_sec[0]
    assert abs(item.evidence["second_half_pace_change_sec_per_km"]) < 24
    assert "first_half_hr_bpm" not in item.evidence
    assert "second_half_hr_bpm" not in item.evidence
    if code == "coach.execution.pace_hr":
        assert item.evidence["first_hr_bpm"] == 150
        assert item.evidence["last_hr_bpm"] == 170
        assert item.priority == 10
    else:
        assert not any("hr" in key for key in item.evidence)
        assert item.priority == 30


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_bare_equal_cross_follows_relevant_history(language):
    rows = splits((5, 5, 5, 5), (150, 150, 150, 150))
    items = conclusions(continuous_session(km_splits=rows),
                        history=prior(avg_pace_min_km=5.5), language=language)
    assert [item.code for item in items] == ["coach.history.pace", "coach.execution.pace_hr"]
    assert [item.priority for item in items] == [40, 60]


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_future_history_never_enters_priorities(language):
    history = prior(avg_pace_min_km=5.5)
    for row in history:
        row["date"] = "2026-10-11"
    items = conclusions(continuous_session(km_splits=splits()), history=history, language=language)
    assert len(items) == 1
    assert items[0].code == "coach.pacing"


def test_endpoint_cross_does_not_claim_whole_series_regularity():
    rows = splits((5, 5.1, 5.2), (150, 170, 155))
    item = conclusions(continuous_session(distance_km=3, km_splits=rows))[0]
    assert item.metadata["comparison_scope"] == "first_last_measured_segments"
    assert "Between your first and last segments" in item.text
    assert "steady" not in item.text
    assert "12 s/km" in item.text


@pytest.mark.parametrize("offset,available", [(-31, False), (-30, True),
                                             (30, True), (31, False)])
@pytest.mark.parametrize("observed_phase", [False, True])
def test_workout_duration_rounding_has_documented_absolute_boundary(offset, available, observed_phase):
    # V2's independent 1% classification must also accept these rounding offsets.
    rows = measured_segments((5, 5), (5, 5.5), (150, 155))
    value = continuous_session(distance_km=10, km_splits=rows,
                               duration_minutes=(3150 + offset) / 60)
    phases = None
    if observed_phase:
        del value["session_structure"]
        phases = [ActivityPhase(order=0, phase_type="effort", duration_s=3150,
                                distance_m=10000, source="synthetic")]
    assert bool(conclusions(value, phases=phases)) == available


def test_duration_rounding_allowance_does_not_expand_for_long_sessions():
    rows = measured_segments((1, 1), (50, 100))
    value = continuous_session(distance_km=2, km_splits=rows, duration_minutes=149)
    assert conclusions(value) == []  # 9000 vs 8940 s is not whole-minute rounding.


@pytest.mark.parametrize("measured_time", [False, True])
def test_stable_pace_and_unchanged_hr_is_never_priority_ten(measured_time):
    rows = splits((5, 5, 5, 5), (150, 150, 150, 150))
    if measured_time:
        for row in rows:
            row["duration_s"] = 300
    item = conclusions(continuous_session(km_splits=rows))[0]
    assert item.code == "coach.execution.pace_hr"
    assert item.evidence["heart_rate_change_bpm"] == 0
    assert item.priority == 60


@pytest.mark.parametrize("unit", ["km", "m"])
@pytest.mark.parametrize("both_fields", [False, True])
def test_declared_distance_units_match_explicit_measured_fields(unit, both_fields):
    rows = measured_segments((1, 3.665, 3.665, 1), (4, 5, 6, 5), (140, 150, 170, 160))
    for row in rows:
        if unit == "m" or both_fields:
            row["distance_m"] = row["distance_km"] * 1000
        if unit == "m" and not both_fields:
            del row["distance_km"]
        row.update(distance_unit=unit, duration_unit="s", pace_unit="min/km")
    item = conclusions(continuous_session(distance_km=9.33, km_splits=rows))[0]
    assert item.metadata["comparison_scope"] == "equal_distance_halves"
    assert item.evidence["second_half_pace_change_sec_per_km"] == pytest.approx(60)
    assert item.evidence["measured_distance_km"] == pytest.approx(9.33)


@pytest.mark.parametrize("distance_fields", [{}, {"distance_km": 1}])
def test_meter_declaration_requires_explicit_meter_field(distance_fields):
    rows = splits((5, 6))
    rows[0].update(distance_fields, distance_unit="m")
    assert conclusions(continuous_session(distance_km=2, km_splits=rows)) == []


def test_kilometer_declaration_cannot_override_meter_only_field():
    rows = splits((5, 6))
    rows[0].update(distance_m=1000, distance_unit="km")
    assert conclusions(continuous_session(distance_km=2, km_splits=rows)) == []


@pytest.mark.parametrize("first_hr,last_hr,priority", [
    (150, 150.00000000003, 60),
    (150.00000000003, 150, 60),
    (149.96, 150.04, 60),
    (150.049, 150.051, 10),
    (150.051, 150.149, 60),
    (150.2, 150.249999, 60),
    (150.2, 150.25, 60),  # Exact display tie rounds to 150.2.
    (150.2, 150.250001, 10),
])
@pytest.mark.parametrize("population", ["halves", "repetitions"])
def test_hr_priority_uses_displayed_values_not_roundoff(first_hr, last_hr, priority, population):
    if population == "halves":
        rows = measured_segments((1, 1, 1, 1), (5, 5, 5, 5),
                                 (first_hr, first_hr, last_hr, last_hr))
        item = conclusions(continuous_session(km_splits=rows))[0]
        assert item.metadata["comparison_scope"] == "equal_distance_halves"
    else:
        item = conclusions(phases=efforts(paces=(300, 300, 300),
                                          hrs=(first_hr, first_hr, last_hr)))[0]
    assert item.priority == priority
    assert item.evidence["heart_rate_change_bpm"] == pytest.approx(last_hr - first_hr)


@pytest.mark.parametrize("population", ["halves", "repetitions"])
def test_significant_pace_cross_remains_first_even_when_hr_displays_equal(population):
    if population == "halves":
        rows = measured_segments((1, 1, 1, 1), (5, 5, 6, 6),
                                 (150, 150, 150.00000000003, 150.00000000003))
        item = conclusions(continuous_session(km_splits=rows))[0]
    else:
        item = conclusions(phases=efforts(paces=(300, 330, 360),
                                          hrs=(150, 150, 150.00000000003)))[0]
    assert item.priority == 10
    assert item.metadata["direction"] == "slower"
