from copy import deepcopy

import pytest

from activity_phases import ActivityPhase
from coach_context_v2 import CoachWorkoutDetail
from workout_analysis_v2 import WorkoutAnalysisV2Response, build_workout_analysis_v2


def reference_workout():
    return {
        "id": "synthetic-24671804067",
        "name": "Vannes – 4x4min @allure Z5",
        "date": "2026-10-10",
        "type": "run",
        "distance_km": 14.26,
        "duration_minutes": 80,
        "max_heart_rate": 175,
        "km_splits": [],
    }


def reference_phases():
    phases = []
    for distance, hr in zip((832.07, 851.11, 885.81, 825.41), (151, 157, 159, 159)):
        phases.append(ActivityPhase(
            order=len(phases), phase_type="effort", duration_s=240,
            distance_m=distance, average_hr=hr, max_hr=175 if distance == 885.81 else None,
            source="synthetic-provider",
        ))
        phases.append(ActivityPhase(
            order=len(phases), phase_type="recovery", duration_s=180,
            distance_m=400, average_hr=140, source="synthetic-provider",
        ))
    return phases


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_reference_has_one_coherent_interpretation_without_zones_or_km_splits(language):
    analysis = build_workout_analysis_v2(
        reference_workout(), [], language, reference_phases(),
    )
    assert analysis.signals.session_structure.code == "intervals"
    assert analysis.signals.session_type.code == "standard"
    assert analysis.signals.intensity.available is False
    assert analysis.evidence.has_splits is False
    assert analysis.evidence.has_structured_phases is True
    assert analysis.evidence.has_effort_regularity is True
    regularity = analysis.phase_analysis.effort_regularity
    assert regularity.average_pace_sec_per_km == pytest.approx(283.0313, abs=0.001)
    assert regularity.pace_dispersion_sec_per_km == pytest.approx(7.6870, abs=0.001)
    assert regularity.average_hr_change_bpm == 8
    assert analysis.physiology.hr_drift is None
    for field in (analysis.summary, analysis.meaning, analysis.advice):
        assert "4 × 4 min" in field.text
        assert "4 × 3 min" in field.text
        assert "4:43/km" in field.text
        assert "7.7 s/km" in field.text
        assert "151 → 157 → 159 → 159" in field.text
        assert "175 bpm" in field.text
        assert "4:31/km" in field.text and "4:51/km" in field.text
    assert analysis.advice.available is True
    assert "Training Today/Week" in analysis.advice.text
    assert "14.26 km" in analysis.summary.text
    codes = {item.code for item in analysis.limitations}
    assert "limitations.phase_splits" in codes
    assert "limitations.splits" not in codes
    assert "limitations.intensity" in codes
    assert analysis.model_dump() == WorkoutAnalysisV2Response.model_validate(analysis.model_dump()).model_dump()


def test_name_and_unverified_zones_do_not_establish_structure_or_intensity():
    workout = reference_workout()
    workout["effort_zone_distribution"] = {"z5": 90}
    analysis = build_workout_analysis_v2(workout, [])
    assert analysis.signals.session_structure.available is False
    assert analysis.signals.intensity.available is False
    assert analysis.summary.code == "summary.standard_structural"


def test_continuous_without_phases_preserves_existing_contract():
    workout = reference_workout()
    workout.update(name="Continuous", session_structure="continuous", avg_pace_min_km=5.5)
    analysis = build_workout_analysis_v2(workout, [])
    assert analysis.signals.session_structure.code == "continuous"
    assert analysis.phase_analysis.available is False
    assert analysis.evidence.has_structured_phases is False
    assert analysis.evidence.has_effort_regularity is False
    assert analysis.summary.code == "summary.standard_structural"
    assert "limitations.splits" in {item.code for item in analysis.limitations}
    payload = analysis.model_dump()
    del payload["signals"]["session_structure"]
    for key in ("has_structured_phases", "has_effort_regularity", "has_phase_heart_rate"):
        del payload["evidence"][key]
    legacy = WorkoutAnalysisV2Response.model_validate(payload)
    assert legacy.signals.session_structure.available is False
    assert legacy.summary == analysis.summary


def test_partial_incoherent_phases_keep_limits_and_never_claim_full_regularity():
    phases = reference_phases()
    phases[0] = phases[0].model_copy(update={"average_speed_mps": 10})
    phases[2] = phases[2].model_copy(update={"distance_m": None, "average_hr": None})
    analysis = build_workout_analysis_v2(reference_workout(), [], "fr", phases)
    assert analysis.signals.session_structure.code == "intervals"
    assert analysis.phase_analysis.effort_regularity.partial_comparison is True
    assert "relativement régulières" not in analysis.meaning.text
    assert "151 →" not in analysis.meaning.text
    codes = {item.code for item in analysis.limitations}
    assert {
        "limitations.phases.incoherent_pace",
        "limitations.phases.effort_paces_incomplete",
        "limitations.phase_hr",
        "limitations.phase_missing",
    } <= codes
    assert analysis.physiology.hr_drift is None


def test_no_effort_paces_does_not_hide_available_structure():
    phases = [phase.model_copy(update={"distance_m": None}) for phase in reference_phases()]
    analysis = build_workout_analysis_v2(reference_workout(), [], "en", phases)
    assert analysis.evidence.has_effort_regularity is False
    assert "limitations.phase_regularity" in {item.code for item in analysis.limitations}
    assert "4 × 4 min" in analysis.summary.text
    assert "mean pace" not in analysis.summary.text


def test_missing_global_hr_does_not_erase_observed_phase_hr():
    workout = reference_workout()
    del workout["max_heart_rate"]
    analysis = build_workout_analysis_v2(workout, [], "fr", reference_phases())
    assert analysis.evidence.has_heart_rate is False
    assert analysis.evidence.has_phase_heart_rate is True
    assert "limitations.heart_rate" not in {item.code for item in analysis.limitations}
    assert "151 → 157 → 159 → 159" in analysis.meaning.text
    assert analysis.signals.intensity.available is False


def test_phase_observations_do_not_turn_historical_differences_into_progress():
    history = []
    for index, pace in enumerate((6.0, 6.5)):
        workout = deepcopy(reference_workout())
        workout.update(
            id=f"history-{index}", date=f"2026-10-0{index + 1}",
            avg_pace_min_km=pace, workout_type="race", distance_km=15,
        )
        history.append(workout)
    workout = reference_workout()
    workout.update(avg_pace_min_km=5.0, workout_type="training")
    analysis = build_workout_analysis_v2(workout, history, "en", reference_phases())
    assert analysis.comparison.available is True
    assert "limitations.baseline_descriptive" in {item.code for item in analysis.limitations}
    for field in (analysis.summary, analysis.meaning, analysis.advice):
        assert "progress" not in field.text.lower()
    assert analysis.physiology.hr_drift is None
    assert "not a cardiac drift measurement" in analysis.meaning.text


def test_coach_embeds_additive_canonical_analysis_without_reinterpretation():
    analysis = build_workout_analysis_v2(reference_workout(), [], "fr", reference_phases())
    detail = CoachWorkoutDetail(
        id=analysis.workout.id, name=analysis.workout.name,
        date=analysis.workout.date, type="run", analysis=analysis,
    )
    assert detail.analysis == analysis
    assert detail.model_dump()["analysis"]["signals"]["session_structure"]["code"] == "intervals"


@pytest.mark.parametrize(
    "kinds,durations,expected",
    [
        (["effort"], [4800], "continuous"),
        (["effort"], [240], "other"),
        (["effort", "effort"], [240, 240], "other"),
        (["unknown"], [4800], None),
        (["effort", "recovery", "effort"], [240, 180, 240], "intervals"),
    ],
)
def test_structure_requires_observed_sequence_or_full_continuous_coverage(kinds, durations, expected):
    phases = [
        ActivityPhase(
            order=index, phase_type=kind, duration_s=duration, source="synthetic-provider",
        )
        for index, (kind, duration) in enumerate(zip(kinds, durations))
    ]
    analysis = build_workout_analysis_v2(reference_workout(), [], phases=phases)
    assert analysis.signals.session_structure.code == expected
    assert analysis.signals.intensity.available is False
