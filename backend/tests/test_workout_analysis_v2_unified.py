from copy import deepcopy

import pytest

from activity_phases import ActivityPhase
from coach_context_v2 import CoachWorkoutDetail, build_llm_coach_context
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
    assert "4 × 4 min" in analysis.summary.text
    assert "4 × 3 min" in analysis.summary.text
    assert "4:43/km" in analysis.summary.text
    decimal = "." if language == "en" else ","
    assert f"14{decimal}26 km" in analysis.summary.text
    assert f"7{decimal}7 s/km" in analysis.meaning.text
    assert "151" in analysis.meaning.text and "159" in analysis.meaning.text
    assert "175 bpm" in analysis.meaning.text
    assert "4:31/km" in analysis.meaning.text and "4:51/km" in analysis.meaning.text
    assert f"19{decimal}8 s/km" in analysis.advice.text
    for detail in ("4 × 4 min", "4:43/km", "14.26 km", "14,26 km"):
        assert detail not in analysis.meaning.text
        assert detail not in analysis.advice.text
    for detail in ("s/km", "151", "175 bpm", "4:31/km", "4:51/km"):
        assert detail not in analysis.summary.text
    assert all(detail not in analysis.advice.text for detail in ("151", "175 bpm", "4:31/km", "4:51/km"))
    assert len(analysis.advice.text) < 250
    assert len(analysis.summary.text) < 250
    assert analysis.advice.available is True
    assert "Training Today/Week" not in analysis.advice.text
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
    assert "(2/4)" in analysis.summary.text
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
    assert "151 à 159 bpm" in analysis.meaning.text
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


def test_unclassified_unusable_phases_preserve_existing_pacing_conclusions():
    workout = reference_workout()
    workout["split_analysis"] = {"pace_drop": 0.5}
    baseline = build_workout_analysis_v2(workout, [])
    analysis = build_workout_analysis_v2(
        workout, [], phases=[ActivityPhase(order=0, source="synthetic-provider")],
    )
    assert analysis.phase_analysis.available is True
    assert analysis.signals.session_structure.available is False
    assert analysis.summary == baseline.summary
    assert analysis.meaning == baseline.meaning
    assert analysis.advice == baseline.advice
    assert analysis.advice.code == "advice.even_pacing"


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize(
    "kinds,expected_structure",
    [
        ([], None),
        (["unknown"], None),
        (["unknown", "unknown", "unknown"], None),
        (["effort"], "other"),
        (["recovery"], "other"),
        (["warmup"], "other"),
        (["cooldown"], "other"),
        (["unknown", "effort"], "other"),
        (["unknown", "recovery"], "other"),
        (["effort", "recovery"], "other"),
        (["effort", "effort"], "other"),
        (["effort", "recovery", "effort"], "intervals"),
        (["effort", "unknown", "effort"], "other"),
        (["effort", "unknown", "recovery", "effort"], "intervals"),
    ],
)
def test_structured_evidence_requires_classification_not_presence(language, kinds, expected_structure):
    workout = reference_workout()
    phases = [
        ActivityPhase(
            order=index, phase_type=kind, native_type=f"SYNTHETIC_{kind.upper()}",
            duration_s=240, distance_m=800, average_hr=150, max_hr=160,
            source="synthetic-provider",
        )
        for index, kind in enumerate(kinds)
    ]
    analysis = build_workout_analysis_v2(workout, [], language, phases)
    classified = any(kind != "unknown" for kind in kinds)
    result = analysis.phase_analysis
    assert result.available is bool(kinds)
    assert result.analysis_type == ("structured_phases" if kinds else "standard")
    assert analysis.evidence.has_structured_phases is classified
    assert analysis.signals.session_structure.code == expected_structure
    assert analysis.signals.session_structure.available is (expected_structure is not None)
    assert [row.phase_type for row in result.phases] == kinds
    assert [row.native_type for row in result.phases] == [row.native_type for row in phases]
    assert all(row.duration_s == 240 and row.distance_m == 800 for row in result.phases)
    assert all(row.pace_sec_per_km == 300 and row.average_hr == 150 for row in result.phases)
    assert len(result.efforts) == kinds.count("effort")
    assert len(result.recoveries) == kinds.count("recovery")
    assert result.effort_statistics.count == kinds.count("effort")
    assert result.recovery_statistics.count == kinds.count("recovery")
    assert all(
        row.effort_number is None and row.recovery_number is None
        for row in result.phases if row.phase_type == "unknown"
    )
    codes = {item.code for item in analysis.limitations}
    assert ("limitations.phase_splits" in codes) is classified
    assert ("limitations.splits" in codes) is not classified
    assert ("limitations.phase_classification" in codes) is (bool(kinds) and not classified)
    assert ("limitations.phase_classification_partial" in codes) is (classified and "unknown" in kinds)
    if kinds.count("effort") < 2:
        assert analysis.evidence.has_effort_regularity is False
        assert result.effort_regularity.available is False
        assert result.effort_regularity.pace_dispersion_sec_per_km is None
        assert result.effort_regularity.first_to_last_pace_change_sec_per_km is None
    if not classified:
        baseline = build_workout_analysis_v2(workout, [], language)
        assert result.effort_statistics.total_duration_s is None
        assert result.recovery_statistics.total_duration_s is None
        assert analysis.summary == baseline.summary
        assert analysis.advice == baseline.advice
        assert "limitations.phase_regularity" not in codes
        assert "limitations.phase_hr" not in codes
    # Coach receives the canonical proof; its pace projection must not infer classification.
    detail = CoachWorkoutDetail(
        id=workout["id"], name=workout["name"], date=workout["date"], type="run", analysis=analysis,
    )
    payload = detail.model_dump(mode="json")
    assert payload["analysis"] == analysis.model_dump(mode="json")
    projected = build_llm_coach_context({"workout_detail": payload})["workout_detail"]["analysis"]
    assert projected["evidence"] == payload["analysis"]["evidence"]
    assert projected["phase_analysis"]["available"] is bool(kinds)
    assert [row["phase_type"] for row in projected["phase_analysis"]["phases"]] == kinds
    assert projected["signals"]["session_structure"] == payload["analysis"]["signals"]["session_structure"]
    assert projected["limitations"] == payload["analysis"]["limitations"]
    assert WorkoutAnalysisV2Response.model_validate(payload["analysis"]) == analysis


def test_unknown_phases_preserve_missing_data_without_hiding_classified_observations():
    phases = [ActivityPhase(order=0, source="synthetic-provider")] + [
        phase.model_copy(update={"order": phase.order + 1}) for phase in reference_phases()
    ]
    analysis = build_workout_analysis_v2(reference_workout(), [], "fr", phases)
    baseline = build_workout_analysis_v2(reference_workout(), [], "fr", reference_phases())
    assert analysis.evidence.has_structured_phases is True
    assert analysis.signals.session_structure.code == "intervals"
    assert analysis.phase_analysis.effort_regularity == baseline.phase_analysis.effort_regularity
    assert analysis.phase_analysis.effort_statistics == baseline.phase_analysis.effort_statistics
    assert analysis.phase_analysis.recovery_statistics == baseline.phase_analysis.recovery_statistics
    assert analysis.summary == baseline.summary
    assert analysis.meaning == baseline.meaning
    assert analysis.advice == baseline.advice
    assert analysis.phase_analysis.missing_data == ["distance", "duration", "heart_rate", "pace"]
    codes = {item.code for item in analysis.limitations}
    assert {"limitations.phase_missing", "limitations.phase_classification_partial"} <= codes


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("classified", [False, True])
def test_classification_limitations_are_localized(language, classified):
    phases = [ActivityPhase(order=0, source="synthetic-provider")]
    if classified:
        phases.append(ActivityPhase(order=1, phase_type="effort", source="synthetic-provider"))
    analysis = build_workout_analysis_v2(reference_workout(), [], language, phases)
    code = "limitations.phase_classification_partial" if classified else "limitations.phase_classification"
    text = next(item.text for item in analysis.limitations if item.code == code)
    assert {"fr": "classifiées", "en": "unclassified", "es": "clasificadas"}[language] in text
    assert code not in text
    assert "limitations.phase_missing" in {item.code for item in analysis.limitations}


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("reason", [
    "incoherent_pace", "efforts_not_comparable", "efforts_partially_comparable",
    "effort_paces_incomplete", "insufficient_comparable_effort_paces",
])
def test_phase_limitation_texts_are_localized_without_changing_diagnostic_codes(language, reason):
    from workout_analysis_v2 import _build_limitations

    analysis = build_workout_analysis_v2(reference_workout(), [], language, reference_phases())
    phases = analysis.phase_analysis.model_copy(update={
        "limitations": [reason], "missing_data": ["duration", "distance", "pace", "heart_rate"],
    })
    limitations = _build_limitations(
        reference_workout(), analysis.signals, analysis.comparison, analysis.evidence, language, phases,
    )
    texts = {item.code: item.text for item in limitations}
    text = texts[f"limitations.phases.{reason}"]
    assert reason not in text and "_" not in text
    assert "heart_rate" not in texts["limitations.phase_missing"]
    assert {"fr": "durée", "en": "duration", "es": "duración"}[language] in texts["limitations.phase_missing"]
    if reason == "effort_paces_incomplete":
        assert {"fr": "Certaines allures", "en": "Some effort paces", "es": "Faltan algunos ritmos"}[language] in text


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_partial_observations_remain_scoped_and_coach_is_non_prescriptive(language):
    phases = reference_phases()
    phases[0] = phases[0].model_copy(update={"distance_m": None, "average_hr": None})
    analysis = build_workout_analysis_v2(reference_workout(), [], language, phases)
    assert analysis.phase_analysis.effort_regularity.partial_comparison is True
    assert "(3/4)" in analysis.summary.text
    assert "3" in analysis.meaning.text
    assert "4" in analysis.meaning.text
    assert {"fr": "ne décrivent pas toutes", "en": "do not describe every", "es": "no describen todas"}[language] in analysis.meaning.text
    assert {"fr": "Couverture cardiaque", "en": "Heart-rate coverage", "es": "Cobertura cardíaca"}[language] in analysis.meaning.text
    assert analysis.signals.intensity.available is False
    assert analysis.physiology.hr_drift is None
    assert "relatively regular" not in analysis.meaning.text
    assert "relativement régulières" not in analysis.meaning.text
    assert "relativamente regulares" not in analysis.meaning.text
    for text in (analysis.advice.text, analysis.meaning.text):
        assert "effort_paces_incomplete" not in text
    assert all(word not in analysis.advice.text.lower() for word in ("tomorrow", "demain", "mañana"))


def test_equal_paces_describe_equality_without_success_or_intensity_judgment():
    phases = [
        phase.model_copy(update={"distance_m": 800}) if phase.phase_type == "effort" else phase
        for phase in reference_phases()
    ]
    analysis = build_workout_analysis_v2(reference_workout(), [], "fr", phases)
    assert "même allure" in analysis.advice.text
    assert "0 s/km" in analysis.meaning.text
    assert "réuss" not in analysis.advice.text
    assert analysis.signals.intensity.available is False


def test_older_similar_reference_is_not_hidden_by_missing_recent_baseline():
    workout = reference_workout()
    workout.update(avg_pace_min_km=5.0, workout_type="training")
    earlier = {**workout, "id": "older-synthetic", "date": "2026-08-01", "avg_pace_min_km": 5.5}
    analysis = build_workout_analysis_v2(workout, [earlier], "en", reference_phases())
    assert analysis.comparison.available is False
    assert analysis.comparison.similar.available is True
    assert "5:30/km" in analysis.meaning.text
