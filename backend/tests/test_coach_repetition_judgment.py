"""C348-A: measured repetitions only; no plan or physiological interpretation."""

import json
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from activity_phases import ACTIVITY_PHASE_SCHEMA_VERSION, ActivityPhase
from coach_language import RepetitionJudgmentConfig, build_coach_language
from workout_analysis_v2 import (
    _effort_comparison_cohort,
    _efforts_comparable,
    build_workout_analysis_v2,
)
from workout_analysis_v2_service import load_scoped_workout_analysis_v2


def repetitions(paces, duration=240):
    return [
        ActivityPhase(order=index, phase_type="effort", duration_s=duration,
                      distance_m=duration * 1000 / pace, source="garmin")
        for index, pace in enumerate(paces)
    ]


def analyze(paces=None, *, phases=None, language="en", **workout_fields):
    workout = dict(id="anonymous-reference", type="run", date="2026-10-10",
                   distance_km=5, duration_minutes=30, avg_pace_min_km=6)
    workout.update(workout_fields)
    return build_workout_analysis_v2(
        workout, [], language, repetitions(paces) if paces is not None else phases,
    )


def configured(paces, **settings):
    analysis = analyze(paces)
    phases = analysis.phase_analysis
    return build_coach_language(
        {}, phases, analysis.comparison, *_effort_comparison_cohort(phases.efforts),
        _efforts_comparable, repetition_config=RepetitionJudgmentConfig(**settings),
    )


@pytest.mark.parametrize("paces,band", [
    ([300] * 4, "homogeneous"),
    ([298, 300, 302, 300], "homogeneous"),
    ([280, 290, 310, 320], "variable"),
    ([300, 300, 260, 300], "noticeable"),
    ([300, 300, 340, 300], "noticeable"),
    ([300, 240, 360, 300], "variable"),
])
def test_global_band_uses_every_repetition(paces, band):
    coach = analyze(paces).coach_language
    assert coach.limitations == []
    item, = coach.conclusions
    assert item.kind == "conclusion"
    assert item.metadata["regularity_band"] == band
    assert item.metadata["metric"] == "mean_absolute_deviation_from_median"
    assert item.evidence["comparable_effort_count"] == 4
    assert all(item.evidence[f"effort_{i}_pace_sec_per_km"] == pytest.approx(pace)
               for i, pace in enumerate(paces, 1))


@pytest.mark.parametrize("paces,difference", [
    ([300, 300, 260, 300], -40), ([300, 300, 340, 300], 40),
])
def test_unique_atypical_repetition_has_number_pace_reference_and_gap(paces, difference):
    item, = analyze(paces).coach_language.conclusions
    assert item.evidence["atypical_effort_number"] == 3
    assert item.evidence["atypical_pace_sec_per_km"] == paces[2]
    assert item.evidence["atypical_reference_sec_per_km"] == 300
    assert item.evidence["atypical_difference_sec_per_km"] == difference
    assert item.metadata["endpoint_relationship"] == "close"
    assert "group_direction" not in item.metadata


@pytest.mark.parametrize("paces,direction", [
    ([330, 320, 310, 300], "faster"),
    ([300, 310, 320, 330], "slower"),
    ([350, 330, 310, 290, 270], "faster"),
])
def test_direction_uses_balanced_groups_not_endpoints(paces, direction):
    item, = analyze(paces).coach_language.conclusions
    assert item.metadata["group_direction"] == direction
    assert item.evidence["group_size"] == 2
    assert abs(item.evidence["group_pace_change_sec_per_km"]) == (20 if len(paces) == 4 else 60)
    assert abs(item.evidence["first_to_last_pace_change_sec_per_km"]) == (30 if len(paces) == 4 else 80)
    assert "atypical_effort_number" not in item.evidence


def test_equal_endpoints_do_not_hide_interior_variability_or_invent_trend():
    item, = analyze([300, 240, 360, 300]).coach_language.conclusions
    assert item.metadata["regularity_band"] == "variable"
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == 0
    assert item.evidence["absolute_deviation_sec_per_km"] == 30
    assert "group_direction" not in item.metadata
    assert "atypical_effort_number" not in item.evidence


def test_homogeneous_series_does_not_borrow_legacy_endpoint_direction_or_priority():
    phases = [phase.model_copy(update={"average_hr": 140 if index == 0 else 141})
              for index, phase in enumerate(repetitions([288] + [300] * 98 + [312]))]
    item, = analyze(phases=phases).coach_language.conclusions
    assert item.metadata["regularity_band"] == "homogeneous"
    assert item.metadata["direction"] == "stable"
    assert item.metadata["group_direction"] == "close"
    assert item.priority == 30


def test_group_direction_ignores_the_explicitly_excluded_middle_repetition():
    item, = analyze([300, 301, 302, 301.5, 340, 341, 342]).coach_language.conclusions
    assert item.evidence["group_size"] == 3
    assert item.evidence["group_pace_change_sec_per_km"] == 40
    assert item.metadata["group_direction"] == "slower"
    assert item.metadata["direction"] == "slower"


def test_two_efforts_are_one_bounded_description_not_series_judgment():
    item, = analyze([300, 320]).coach_language.conclusions
    assert item.kind == "descriptive"
    assert item.metadata["regularity_band"] == "not_assessed"
    assert item.metadata["comparison_scope"] == "two_efforts_only"
    assert "group_direction" not in item.metadata
    assert "atypical_effort_number" not in item.evidence


@pytest.mark.parametrize("paces,reason", [
    ([300], "insufficient_efforts"),
    (None, "phases_unavailable"),
])
def test_missing_series_abstains_with_machine_readable_reason(paces, reason):
    coach = analyze(paces).coach_language
    assert coach.conclusions == []
    assert coach.limitations == [f"repetitions.{reason}"]


def test_noncomparable_efforts_abstain_without_discarding_legacy_facts():
    phases = repetitions([300] * 4)
    phases[2] = phases[2].model_copy(update={"duration_s": 60, "distance_m": 200})
    analysis = analyze(phases=phases)
    assert analysis.coach_language.conclusions == []
    assert analysis.coach_language.limitations == ["repetitions.insufficient_comparability"]
    assert analysis.phase_analysis.effort_regularity.partial_comparison
    assert analysis.meaning.factual_observations


@pytest.mark.parametrize("field", ["duration_s", "distance_m", "average_speed_mps"])
@pytest.mark.parametrize("invalid", [None, 0, -1, float("nan"), float("inf"), float("-inf")])
def test_invalid_observations_never_become_judgments(field, invalid):
    phases = repetitions([300] * 4)
    phases[1] = phases[1].model_copy(update={field: invalid})
    coach = analyze(phases=phases).coach_language
    if field == "average_speed_mps" and invalid is None:
        assert coach.conclusions  # Optional speed is not required when time/distance exist.
    else:
        assert coach.conclusions == []
        assert coach.limitations


@pytest.mark.parametrize("invalid", [None, 0, -1, float("nan"), float("inf"), float("-inf")])
def test_invalid_individual_paces_are_rejected_at_coach_boundary(invalid):
    analysis = analyze([300] * 4)
    phases = analysis.phase_analysis
    phases.efforts[1].pace_sec_per_km = invalid
    coach = build_coach_language(
        {}, phases, analysis.comparison, *_effort_comparison_cohort(phases.efforts),
        _efforts_comparable,
    )
    assert coach.conclusions == []
    assert coach.limitations == ["repetitions.invalid_measurements"]


@pytest.mark.parametrize("orders", [[0, 2, 1, 3], [0, 1, 1, 3], [-1, 0, 1, 2]])
def test_unreliable_chronology_abstains(orders):
    phases = [p.model_copy(update={"order": order})
              for p, order in zip(repetitions([300] * 4), orders)]
    coach = analyze(phases=phases).coach_language
    assert coach.conclusions == []
    assert coach.limitations == ["repetitions.unreliable_order"]


def test_unknown_interior_phase_abstains():
    phases = repetitions([300] * 4)
    phases[2] = phases[2].model_copy(update={"phase_type": "unknown"})
    coach = analyze(phases=phases).coach_language
    assert coach.conclusions == []
    assert coach.limitations == ["repetitions.incoherent_structure"]


def test_speed_distance_discrepancy_is_not_precise_enough_for_judgment():
    phases = repetitions([300] * 4)
    phases[1] = phases[1].model_copy(update={"average_speed_mps": 1000 / 310})
    coach = analyze(phases=phases).coach_language
    assert coach.conclusions == []
    assert coach.limitations == ["repetitions.imprecise_measurements"]


def test_small_reconciliation_gap_can_make_category_uncertain():
    phases = repetitions([294, 294, 306, 306])
    # The alternative time/distance observations are 2 s/km away, within 1%.
    phases = [phase.model_copy(update={"average_speed_mps": 1000 / (pace + 2)})
              for phase, pace in zip(phases, [294, 294, 306, 306])]
    coach = analyze(phases=phases).coach_language
    assert coach.conclusions == []
    assert coach.limitations == ["repetitions.category_uncertain"]


@pytest.mark.parametrize("gap,atypical", [(12.999, False), (13, False), (13.001, True)])
def test_atypical_threshold_includes_rounding_uncertainty(gap, atypical):
    item, = configured([300, 300, 300 + gap, 300],
                       homogeneous_relative=0.001, variable_relative=0.1).conclusions
    assert ("atypical_effort_number" in item.evidence) is atypical


@pytest.mark.parametrize("gap,directional", [(6.999, False), (7, False), (7.001, True)])
def test_group_direction_threshold_includes_rounding_uncertainty(gap, directional):
    item, = configured([300, 300, 300 + gap, 300 + gap], trend_relative=0.001,
                       trend_floor_sec_km=6, homogeneous_relative=0.001,
                       variable_relative=0.1).conclusions
    assert (item.metadata.get("group_direction") == "slower") is directional


@pytest.mark.parametrize("deviation,expected", [
    (2.999, "homogeneous"), (3, "homogeneous"), (3.001, "noticeable"),
    (11.999, "noticeable"), (12, "noticeable"), (12.001, "variable"),
])
def test_inclusive_category_boundaries_without_input_uncertainty(deviation, expected):
    # Symmetric paces fix median=300 and L1 dispersion=deviation exactly.
    item, = configured([300 - deviation, 300 - deviation, 300 + deviation, 300 + deviation],
                       pace_uncertainty_sec_km=0).conclusions
    assert item.metadata["regularity_band"] == expected


@pytest.mark.parametrize("deviation", [3, 12])
def test_rounded_measurements_at_category_boundaries_abstain(deviation):
    coach = configured([300 - deviation] * 2 + [300 + deviation] * 2)
    assert coach.conclusions == []
    assert coach.limitations == ["repetitions.category_uncertain"]


def test_rounding_floor_is_absolute_and_configuration_changes_bands():
    item, = configured([99, 99, 101, 101], homogeneous_relative=0.001,
                       variable_relative=0.002, pace_uncertainty_sec_km=0).conclusions
    assert item.evidence["homogeneous_limit_sec_per_km"] == 1
    assert item.evidence["variable_limit_sec_per_km"] == 2
    assert item.metadata["regularity_band"] == "homogeneous"
    item, = configured([290, 290, 310, 310], homogeneous_relative=0.05,
                       variable_relative=0.1, pace_uncertainty_sec_km=0).conclusions
    assert item.metadata["regularity_band"] == "homogeneous"


@pytest.mark.parametrize("settings", [
    {"homogeneous_relative": 0}, {"variable_relative": 0.01},
    {"pace_uncertainty_sec_km": -1}, {"trend_relative": float("nan")},
    {"atypical_relative": float("inf")},
])
def test_configuration_requires_finite_ordered_positive_bands(settings):
    with pytest.raises(ValidationError):
        RepetitionJudgmentConfig(**settings)


@pytest.fixture
def october_reference():
    # Only the supplied observed paces, durations and HR; no athlete identifiers.
    return [phase.model_copy(update={"average_hr": hr}) for phase, hr in zip(
        repetitions([288, 282, 271, 291]), [151, 157, 159, 159],
    )]


@pytest.mark.parametrize("language,global_word,atypical_word,close_word", [
    ("fr", "perceptibles", "n° 3", "restent proches"),
    ("en", "Noticeable", "Repetition 3", "remain close"),
    ("es", "perceptibles", "n.º 3", "siguen próximas"),
])
def test_october_reference_is_evaluative_reproducible_and_localized(
    october_reference, language, global_word, atypical_word, close_word,
):
    analysis = analyze(phases=october_reference, language=language,
                       prescription_snapshot={"type": "rest"})
    item, = analysis.coach_language.conclusions
    assert item.kind == "conclusion"
    assert item.metadata["regularity_band"] == "noticeable"
    assert item.evidence["absolute_deviation_sec_per_km"] == pytest.approx(6.5)
    assert item.evidence["median_pace_sec_per_km"] == 285
    assert item.evidence["relative_deviation"] == pytest.approx(6.5 / 285)
    assert item.evidence["atypical_effort_number"] == 3
    assert item.evidence["atypical_difference_sec_per_km"] == -17
    assert item.evidence["first_to_last_pace_change_sec_per_km"] == 3
    assert item.metadata["endpoint_relationship"] == "close"
    assert global_word in item.text and atypical_word in item.text and close_word in item.text
    assert "4:31/km" in item.text
    assert analysis == analyze(phases=october_reference, language=language,
                              prescription_snapshot={"type": "rest"})
    assert analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km == pytest.approx(
        math.sqrt(sum((p - 283) ** 2 for p in [288, 282, 271, 291]) / 4),
    )
    json.dumps(analysis.model_dump(), allow_nan=False)
    assert len(analysis.coach_language.conclusions) <= 3
    assert item.replaces_factual_codes == ["fact.effort_dispersion", "fact.effort_extremes",
                                         "fact.effort_hr_evolution"]
    text = item.text.lower()
    assert not any(term in text for term in (
        "fatigue", "fatiga", "drift", "dérive", "deriva", "endurance", "fitness",
        "objectif atteint", "goal achieved", "objetivo alcanzado", "trop rapide",
        "too fast", "demasiado", "negative split", "prescription",
    ))
    assert analysis.coach_language == analyze(
        phases=october_reference, language=language,
        prescription_snapshot={"type": "intervals", "target_pace": 200},
    ).coach_language


def test_without_phases_no_repetition_judgment_from_rejected_laps():
    analysis = analyze(km_splits=[{"lap": 1, "distance_m": 400},
                                 {"lap": 2, "distance_m": 700}])
    assert analysis.coach_language.conclusions == []
    assert analysis.coach_language.limitations == ["repetitions.phases_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_status", ["complete", "partial"])
async def test_scoped_get_service_uses_only_existing_validated_cache(october_reference, cache_status):
    workout = dict(id="garmin-anonymous", external_id="anonymous", type="run",
                   date="2026-10-10", distance_km=5, duration_minutes=30)
    activity = {"activity_details": {
        "schema_version": ACTIVITY_PHASE_SCHEMA_VERSION,
        "status": cache_status, "source": "garmin", "endpoint": "typed-splits",
        "phases": [phase.model_dump() for phase in october_reference],
    }}
    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    db = SimpleNamespace(
        workouts=SimpleNamespace(find_one=AsyncMock(return_value=workout),
                                 find=Mock(return_value=cursor)),
        garmin_activities=SimpleNamespace(find_one=AsyncMock(return_value=activity)),
    )
    _, analysis = await load_scoped_workout_analysis_v2(
        db=db, user_id="anonymous-user", workout_id=workout["id"], language="fr",
    )
    assert analysis is not None
    db.workouts.find_one.assert_awaited_once_with(
        {"id": "garmin-anonymous", "user_id": "anonymous-user"}, {"_id": 0},
    )
    db.garmin_activities.find_one.assert_awaited_once_with(
        {"user_id": "anonymous-user", "external_id": "anonymous"}, {"_id": 0},
    )
    if cache_status == "complete":
        item, = analysis.coach_language.conclusions
        assert item.metadata["regularity_band"] == "noticeable"
        assert item.evidence["atypical_effort_number"] == 3
    else:
        assert analysis.coach_language.conclusions == []
        assert analysis.coach_language.limitations == ["repetitions.phases_unavailable"]
