from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from activity_phases import ACTIVITY_PHASE_SCHEMA_VERSION, ActivityPhase
from workout_analysis_v2 import WorkoutAnalysisV2Response, build_workout_analysis_v2
from workout_analysis_v2_service import load_scoped_workout_analysis_v2


def _phase(order, phase_type, *, duration=None, distance=None, avg_hr=None, max_hr=None,
           speed=None, native_type=None):
    return ActivityPhase(
        order=order,
        native_type=native_type or phase_type.upper(),
        phase_type=phase_type,
        duration_s=duration,
        distance_m=distance,
        average_speed_mps=speed,
        average_hr=avg_hr,
        max_hr=max_hr,
        min_hr=None,
        source="synthetic",
    )


def _workout(**updates):
    return {
        "id": "synthetic-run",
        "name": "synthetic interval session",
        "date": "2026-10-01",
        "type": "run",
        "distance_km": 6.0,
        "duration_minutes": 35,
        "km_splits": [{"km": 1, "pace_min_km": 5.8}],
        "split_analysis": {},
        **updates,
    }


def _reference_phases():
    rows = [
        ("warmup", 600, None, None, None),
        ("effort", 240, 832.07, 151, 160),
        ("recovery", 180, None, None, None),
        ("effort", 240, 851.11, 157, 165),
        ("recovery", 180, None, None, None),
        ("effort", 240, 885.81, 159, 175),
        ("recovery", 180, None, None, None),
        ("effort", 240, 825.41, 159, 166),
        ("recovery", 180, None, None, None),
        ("cooldown", 600, None, None, None),
    ]
    return [
        _phase(index, kind, duration=duration, distance=distance, avg_hr=avg, max_hr=maximum)
        for index, (kind, duration, distance, avg, maximum) in enumerate(rows)
    ]


def test_no_phases_preserves_standard_analysis_and_kilometre_splits():
    analysis = build_workout_analysis_v2(_workout(), [])
    assert analysis.phase_analysis.available is False
    assert analysis.phase_analysis.analysis_type == "standard"
    assert analysis.evidence.has_splits is True
    assert analysis.pacing.fastest_split_min_km == 5.8
    assert analysis.phase_analysis.efforts == []


def test_valid_phases_preserve_order_and_produce_four_efforts_and_recoveries():
    analysis = build_workout_analysis_v2(_workout(), [], phases=_reference_phases())
    phases = analysis.phase_analysis
    assert phases.available is True
    assert phases.analysis_type == "structured_phases"
    assert [phase.phase_type for phase in phases.phases] == [
        "warmup", "effort", "recovery", "effort", "recovery",
        "effort", "recovery", "effort", "recovery", "cooldown",
    ]
    assert [phase.effort_number for phase in phases.efforts] == [1, 2, 3, 4]
    assert [phase.recovery_number for phase in phases.recoveries] == [1, 2, 3, 4]
    assert [round(phase.pace_sec_per_km) for phase in phases.efforts] == [288, 282, 271, 291]
    assert [(phase.average_hr, phase.max_hr) for phase in phases.efforts] == [
        (151, 160), (157, 165), (159, 175), (159, 166),
    ]
    assert phases.effort_regularity.available is True
    assert phases.effort_regularity.comparable_effort_count == 4
    assert phases.effort_regularity.comparability_basis == "duration"
    assert phases.effort_regularity.pace_sample_count == 4
    assert phases.effort_regularity.partial_comparison is False
    assert phases.effort_regularity.average_duration_s == 240
    assert phases.effort_regularity.first_to_last_pace_change_sec_per_km > 0
    assert phases.effort_regularity.average_hr_change_bpm == 8
    assert analysis.evidence.has_splits is True


def test_unknown_phase_is_preserved_without_becoming_effort_or_recovery():
    phase = _phase(0, "unknown", duration=60, native_type="UNMAPPED_NATIVE")
    result = build_workout_analysis_v2(_workout(), [], phases=[phase]).phase_analysis
    assert result.phases[0].native_type == "UNMAPPED_NATIVE"
    assert result.phases[0].phase_type == "unknown"
    assert result.efforts == []
    assert result.recoveries == []


@pytest.mark.parametrize(
    "duration,distance,expected_missing",
    [
        (None, 800, "duration"),
        (0, 800, None),
        (240, None, "distance"),
        (240, 0, None),
    ],
)
def test_missing_or_zero_duration_and_distance_never_create_pace(
    duration, distance, expected_missing,
):
    phase = _phase(0, "effort", duration=duration, distance=distance)
    result = build_workout_analysis_v2(_workout(), [], phases=[phase]).phase_analysis
    assert result.efforts[0].pace_sec_per_km is None
    if expected_missing:
        assert expected_missing in result.missing_data


def test_missing_heart_rate_remains_none_and_is_reported():
    result = build_workout_analysis_v2(
        _workout(), [], phases=[_phase(0, "recovery", duration=180, distance=20)]
    ).phase_analysis
    recovery = result.recoveries[0]
    assert recovery.average_hr is None
    assert recovery.max_hr is None
    assert "heart_rate" in result.missing_data
    assert recovery.pace_sec_per_km == 9000


def test_reported_speed_is_used_only_when_duration_distance_are_not_both_available():
    phase = _phase(0, "effort", speed=4.0)
    result = build_workout_analysis_v2(_workout(), [], phases=[phase]).phase_analysis
    assert result.efforts[0].pace_sec_per_km == 250


@pytest.mark.parametrize(
    "duration,distance,expected_pace",
    [
        (0, 800, None),
        (240, 0, None),
        (0, 0, None),
        (0, None, None),
        (None, 0, None),
        (None, 800, 250),
        (240, None, 250),
        (None, None, 250),
    ],
)
def test_speed_fallback_distinguishes_explicit_zero_from_missing_measurements(
    duration, distance, expected_pace,
):
    result = build_workout_analysis_v2(
        _workout(), [],
        phases=[_phase(0, "effort", duration=duration, distance=distance, speed=4)],
    ).phase_analysis
    assert result.available is True
    assert result.efforts[0].pace_sec_per_km == expected_pace
    assert result.effort_statistics.average_pace_sec_per_km == expected_pace
    assert ("duration" in result.missing_data) is (duration is None)
    assert ("distance" in result.missing_data) is (distance is None)
    assert ("pace" in result.missing_data) is (expected_pace is None)
    assert "incoherent_pace" not in result.limitations
    assert result.effort_regularity.available is False
    assert result.effort_regularity.pace_dispersion_sec_per_km is None


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("duration,distance", [(None, None), (240, None), (None, 800)])
def test_invalid_speed_never_supplies_fallback_pace(speed, duration, distance):
    result = build_workout_analysis_v2(
        _workout(), [],
        phases=[_phase(0, "effort", duration=duration, distance=distance, speed=speed)],
    ).phase_analysis
    assert result.efforts[0].pace_sec_per_km is None
    assert result.effort_statistics.average_pace_sec_per_km is None
    assert result.effort_regularity.pace_sample_count == 0
    assert result.effort_regularity.available is False
    assert "pace" in result.missing_data
    assert "incoherent_pace" not in result.limitations


@pytest.mark.parametrize("speed", [None, 0, -1, float("nan"), float("inf"), float("-inf")])
def test_positive_measurements_still_supply_pace_without_valid_speed(speed):
    result = build_workout_analysis_v2(
        _workout(), [],
        phases=[_phase(0, "effort", duration=240, distance=800, speed=speed)],
    ).phase_analysis
    assert result.efforts[0].pace_sec_per_km == 300
    assert "incoherent_pace" not in result.limitations


@pytest.mark.parametrize(
    "distance,expected_pace,incoherent",
    [(960, 250, False), (800, 250, False), (768, 250, False), (767, None, True)],
)
def test_speed_coherence_threshold_and_speed_authority_are_unchanged(
    distance, expected_pace, incoherent,
):
    result = build_workout_analysis_v2(
        _workout(), [],
        phases=[_phase(0, "effort", duration=240, distance=distance, speed=4)],
    ).phase_analysis
    assert result.efforts[0].pace_sec_per_km == expected_pace
    assert ("incoherent_pace" in result.limitations) is incoherent
    assert result.effort_regularity.pace_sample_count == (0 if incoherent else 1)


@pytest.mark.parametrize("valid_count", [1, 2])
@pytest.mark.parametrize("zero_measurement,basis", [("distance", "duration"), ("duration", "distance")])
def test_zero_invalidated_pace_is_excluded_without_changing_other_statistics(
    valid_count, zero_measurement, basis,
):
    efforts = [
        _phase(index, "effort", duration=duration, distance=distance, avg_hr=150, max_hr=160)
        for index, (duration, distance) in enumerate(
            [(240, 800), (240, 840)] if basis == "duration" else [(240, 800), (252, 800)]
        )
    ][:valid_count]
    efforts.append(_phase(
        valid_count, "effort",
        duration=0 if zero_measurement == "duration" else 240,
        distance=0 if zero_measurement == "distance" else 800,
        speed=4, avg_hr=160, max_hr=170,
    ))
    analysis = build_workout_analysis_v2(_workout(), [], phases=efforts)
    result = analysis.phase_analysis
    regularity = result.effort_regularity
    valid_paces = [phase.duration_s * 1000 / phase.distance_m for phase in efforts[:-1]]
    assert result.available is True
    assert result.efforts[-1].pace_sec_per_km is None
    assert regularity.comparable_effort_count == valid_count + 1
    assert regularity.comparability_basis == basis
    assert regularity.pace_sample_count == valid_count
    assert regularity.available is (valid_count == 2)
    assert regularity.partial_comparison is True
    assert regularity.average_pace_sec_per_km == pytest.approx(sum(valid_paces) / valid_count)
    if valid_count == 1:
        assert regularity.pace_dispersion_sec_per_km is None
        assert regularity.first_to_last_pace_change_sec_per_km is None
        assert result.limitations == [
            "effort_paces_incomplete", "insufficient_comparable_effort_paces",
        ]
    else:
        assert regularity.pace_dispersion_sec_per_km == pytest.approx(
            abs(valid_paces[1] - valid_paces[0]) / 2,
        )
        assert regularity.first_to_last_pace_change_sec_per_km == pytest.approx(
            valid_paces[1] - valid_paces[0],
        )
        assert result.limitations == ["effort_paces_incomplete"]
    assert result.effort_statistics.total_duration_s == sum(phase.duration_s for phase in efforts)
    assert result.effort_statistics.total_distance_m == sum(phase.distance_m for phase in efforts)
    assert result.effort_statistics.average_hr == pytest.approx((150 * valid_count + 160) / (valid_count + 1))
    assert result.effort_statistics.max_hr == 170
    assert regularity.average_duration_s == pytest.approx(
        sum(phase.duration_s for phase in efforts) / len(efforts),
    )
    assert regularity.average_hr_change_bpm == 10
    baseline = build_workout_analysis_v2(_workout(), []).model_dump(exclude={"phase_analysis"})
    assert analysis.model_dump(exclude={"phase_analysis"}) == baseline


def test_incoherent_reported_speed_suppresses_pace_and_adds_limitation():
    phase = _phase(0, "effort", duration=240, distance=800, speed=1.0)
    result = build_workout_analysis_v2(_workout(), [], phases=[phase]).phase_analysis
    assert result.efforts[0].pace_sec_per_km is None
    assert "incoherent_pace" in result.limitations


def test_noncomparable_efforts_do_not_receive_regularity_comparison():
    phases = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=600, distance=1600),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=phases).phase_analysis
    assert result.effort_regularity.available is False
    assert result.effort_regularity.comparable_effort_count == 1
    assert result.effort_regularity.pace_sample_count == 1
    assert "efforts_not_comparable" in result.limitations


def test_fixed_duration_efforts_compare_on_duration_despite_distance_changes():
    efforts = [
        _phase(index, "effort", duration=240, distance=distance)
        for index, distance in enumerate((800, 900, 1000, 1100))
    ]
    regularity = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis.effort_regularity
    assert regularity.comparability_basis == "duration"
    assert regularity.comparable_effort_count == 4
    assert regularity.available is True


def test_fixed_distance_efforts_compare_on_distance_despite_duration_changes():
    efforts = [
        _phase(index, "effort", duration=duration, distance=1000)
        for index, duration in enumerate((240, 360, 480))
    ]
    regularity = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis.effort_regularity
    assert regularity.comparability_basis == "distance"
    assert regularity.comparable_effort_count == 3
    assert regularity.available is True


def test_incompatible_duration_and_distance_groups_do_not_mix_comparison_criteria():
    efforts = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240, distance=1400),
        _phase(2, "effort", duration=500, distance=800),
        _phase(3, "effort", duration=500, distance=1400),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis
    regularity = result.effort_regularity
    assert regularity.comparability_basis == "duration"
    assert regularity.comparable_effort_count == 2
    assert regularity.effort_count == 4
    assert regularity.partial_comparison is True
    assert regularity.available is True
    assert "efforts_partially_comparable" in result.limitations


def test_two_structurally_comparable_efforts_with_valid_paces_enable_regularity():
    efforts = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240, distance=840),
    ]
    regularity = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis.effort_regularity
    assert regularity.comparable_effort_count == 2
    assert regularity.pace_sample_count == 2
    assert regularity.available is True
    assert regularity.pace_dispersion_sec_per_km == pytest.approx(7.142857, abs=1e-5)


def test_structurally_comparable_efforts_without_valid_paces_are_unavailable():
    efforts = [
        _phase(0, "effort", duration=240),
        _phase(1, "effort", duration=240),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis
    regularity = result.effort_regularity
    assert regularity.comparable_effort_count == 2
    assert regularity.pace_sample_count == 0
    assert regularity.available is False
    assert regularity.pace_dispersion_sec_per_km is None
    assert "efforts_not_comparable" not in result.limitations
    assert "effort_paces_incomplete" in result.limitations
    assert "insufficient_comparable_effort_paces" in result.limitations


def test_one_valid_pace_among_three_comparable_efforts_is_unavailable():
    efforts = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240),
        _phase(2, "effort", duration=240),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis
    regularity = result.effort_regularity
    assert regularity.comparable_effort_count == 3
    assert regularity.pace_sample_count == 1
    assert regularity.available is False
    assert regularity.pace_dispersion_sec_per_km is None
    assert "effort_paces_incomplete" in result.limitations


def test_two_valid_paces_among_three_comparable_efforts_are_available_but_partial():
    efforts = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240, distance=840),
        _phase(2, "effort", duration=240),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis
    regularity = result.effort_regularity
    assert regularity.comparable_effort_count == 3
    assert regularity.pace_sample_count == 2
    assert regularity.available is True
    assert regularity.partial_comparison is True
    assert regularity.pace_dispersion_sec_per_km == pytest.approx(7.142857, abs=1e-5)
    assert "effort_paces_incomplete" in result.limitations


def test_missing_heart_rate_does_not_invalidate_comparable_pace_regularity():
    efforts = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240, distance=840),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis
    assert result.effort_regularity.available is True
    assert result.effort_regularity.pace_sample_count == 2
    assert result.effort_regularity.average_hr_change_bpm is None
    assert result.effort_statistics.average_hr is None


def test_first_to_last_pace_change_uses_the_first_and_last_efforts_in_selected_cohort():
    efforts = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=600, distance=2000),
        _phase(2, "effort", duration=240, distance=810),
    ]
    result = build_workout_analysis_v2(_workout(), [], phases=efforts).phase_analysis
    regularity = result.effort_regularity
    assert regularity.comparability_basis == "duration"
    assert regularity.comparable_effort_count == 2
    assert regularity.pace_sample_count == 2
    assert regularity.first_to_last_pace_change_sec_per_km == pytest.approx(-3.7037037)
    assert regularity.average_pace_sec_per_km == pytest.approx(298.1481481)
    assert regularity.partial_comparison is True


def test_one_repetition_has_descriptive_values_but_no_regularity_claim():
    result = build_workout_analysis_v2(
        _workout(), [], phases=[_phase(0, "effort", duration=240, distance=800)]
    ).phase_analysis
    assert result.effort_statistics.count == 1
    assert result.effort_regularity.available is False
    assert result.effort_regularity.average_duration_s == 240
    assert result.effort_regularity.comparable_effort_count == 1
    assert result.effort_regularity.pace_sample_count == 1
    assert result.effort_regularity.pace_dispersion_sec_per_km is None


def test_regular_and_irregular_repetitions_report_descriptive_dispersion_only():
    regular = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240, distance=800),
        _phase(2, "effort", duration=240, distance=800),
    ]
    irregular = [
        _phase(0, "effort", duration=240, distance=800),
        _phase(1, "effort", duration=240, distance=760),
        _phase(2, "effort", duration=240, distance=720),
    ]
    regularity = build_workout_analysis_v2(_workout(), [], phases=regular).phase_analysis.effort_regularity
    irregularity = build_workout_analysis_v2(_workout(), [], phases=irregular).phase_analysis.effort_regularity
    assert regularity.available and regularity.pace_dispersion_sec_per_km == 0
    assert irregularity.available and irregularity.pace_dispersion_sec_per_km > 0


def test_legacy_response_payload_and_kilometre_split_contract_remain_compatible():
    analysis = build_workout_analysis_v2(_workout(), [])
    old_payload = analysis.model_dump(mode="json")
    old_payload.pop("phase_analysis")
    restored = WorkoutAnalysisV2Response.model_validate(old_payload)
    assert restored.phase_analysis.available is False
    assert restored.phase_analysis.effort_regularity.available is False
    assert restored.evidence.has_splits is True


class _Cursor:
    def sort(self, *_args):
        return self

    async def to_list(self, length=None):
        return []


class _Collection:
    def __init__(self, docs):
        self.docs = docs
        self.find_one_queries = []

    async def find_one(self, query, *_args, **_kwargs):
        self.find_one_queries.append(query)
        return next(
            (dict(doc) for doc in self.docs if all(doc.get(key) == value for key, value in query.items())),
            None,
        )

    def find(self, *_args, **_kwargs):
        return _Cursor()


def _service_db(user_id="user-a", cached_details=None):
    workout = {
        "id": "garmin-synthetic-activity",
        "user_id": user_id,
        "external_id": "synthetic-activity",
        "data_source": "garmin",
        "date": "2026-10-01",
        "type": "run",
        "name": "Synthetic workout",
        "distance_km": 6.0,
        "duration_minutes": 35,
        "km_splits": [],
    }
    activity = {
        "user_id": user_id,
        "external_id": "synthetic-activity",
        "activity_details": cached_details,
    }
    return SimpleNamespace(
        workouts=_Collection([workout]),
        garmin_activities=_Collection([activity]),
    )


def _cached_details(phases):
    return {
        "schema_version": ACTIVITY_PHASE_SCHEMA_VERSION,
        "status": "complete",
        "source": "garmin",
        "endpoint": "typed-splits",
        "phases": phases,
    }


def _cached_rows():
    return [
        {
            "order": index,
            "native_type": "INTERVAL_ACTIVE",
            "phase_type": "effort",
            "duration_s": 240,
            "distance_m": 800,
            "average_speed_mps": None,
            "average_hr": None,
            "max_hr": None,
            "min_hr": None,
            "source": "garmin",
        }
        for index in range(2)
    ]


def _run(coro):
    return asyncio.run(coro)


def test_scoped_loader_reads_valid_cache_and_keeps_prescription_unmatched():
    db = _service_db(cached_details=_cached_details(_cached_rows()))
    result = _run(load_scoped_workout_analysis_v2(
        db=db, user_id="user-a", workout_id="garmin-synthetic-activity", language="en",
    ))
    assert result is not None
    _, analysis = result
    assert analysis.phase_analysis.available is True
    assert analysis.phase_analysis.source == "garmin"
    assert analysis.phase_analysis.effort_regularity.available is True
    assert "prescription" not in analysis.phase_analysis.model_dump()
    assert db.garmin_activities.find_one_queries[0]["user_id"] == "user-a"


@pytest.mark.parametrize("zero_measurement", ["duration_s", "distance_m"])
def test_scoped_loader_preserves_zero_and_missing_measurements_for_speed_fallback(zero_measurement):
    rows = _cached_rows()
    rows[0].update({zero_measurement: 0, "average_speed_mps": 4})
    rows[1].update({zero_measurement: None, "average_speed_mps": 4})
    db = _service_db(cached_details=_cached_details(rows))
    _, analysis = _run(load_scoped_workout_analysis_v2(
        db=db, user_id="user-a", workout_id="garmin-synthetic-activity", language="en",
    ))
    result = analysis.phase_analysis
    assert result.available is True
    assert [phase.order for phase in result.phases] == [0, 1]
    assert [phase.phase_type for phase in result.phases] == ["effort", "effort"]
    assert getattr(result.phases[0], zero_measurement) == 0
    assert getattr(result.phases[1], zero_measurement) is None
    assert [phase.pace_sec_per_km for phase in result.efforts] == [None, 250]
    assert result.effort_regularity.pace_sample_count == 1
    assert result.effort_regularity.available is False
    assert result.effort_regularity.partial_comparison is True
    assert result.limitations == [
        "effort_paces_incomplete", "insufficient_comparable_effort_paces",
    ]
    assert db.garmin_activities.find_one_queries == [
        {"user_id": "user-a", "external_id": "synthetic-activity"},
    ]


@pytest.mark.parametrize("speed", [-1, float("nan"), float("inf"), float("-inf")])
def test_scoped_loader_rejects_invalid_cached_speed(speed):
    rows = _cached_rows()
    rows[0]["average_speed_mps"] = speed
    _, analysis = _run(load_scoped_workout_analysis_v2(
        db=_service_db(cached_details=_cached_details(rows)),
        user_id="user-a", workout_id="garmin-synthetic-activity", language="en",
    ))
    assert analysis.phase_analysis.available is False
    assert analysis.phase_analysis.efforts == []
    assert analysis.phase_analysis.limitations == ["structured_phases_unavailable"]


@pytest.mark.parametrize(
    "details",
    [
        None,
        {"schema_version": 1, "status": "complete", "source": "garmin", "endpoint": "typed-splits", "phases": []},
        {"schema_version": ACTIVITY_PHASE_SCHEMA_VERSION, "status": "failed", "source": "garmin", "endpoint": "typed-splits", "phases": _cached_rows()},
        {**_cached_details(_cached_rows()), "phases": [{"order": 0, "phase_type": "not-a-phase", "source": "garmin"}]},
    ],
)
def test_absent_invalid_or_incomplete_cache_falls_back_to_standard(details):
    result = _run(load_scoped_workout_analysis_v2(
        db=_service_db(cached_details=details),
        user_id="user-a",
        workout_id="garmin-synthetic-activity",
        language="en",
    ))
    assert result is not None
    _, analysis = result
    assert analysis.phase_analysis.available is False
    assert analysis.phase_analysis.analysis_type == "standard"


def test_foreign_user_workout_is_not_loaded_and_foreign_phases_are_not_read():
    db = _service_db(user_id="user-b", cached_details=_cached_details(_cached_rows()))
    result = _run(load_scoped_workout_analysis_v2(
        db=db, user_id="user-a", workout_id="garmin-synthetic-activity", language="en",
    ))
    assert result is None
    assert db.garmin_activities.find_one_queries == []


def test_foreign_activity_cache_with_same_external_id_is_not_consumed():
    db = _service_db(cached_details=_cached_details(_cached_rows()))
    db.garmin_activities.docs[0]["user_id"] = "user-b"
    result = _run(load_scoped_workout_analysis_v2(
        db=db,
        user_id="user-a",
        workout_id="garmin-synthetic-activity",
        language="en",
    ))
    assert result is not None
    _, analysis = result
    assert analysis.phase_analysis.available is False
    assert db.garmin_activities.find_one_queries[0] == {
        "user_id": "user-a",
        "external_id": "synthetic-activity",
    }


def test_cache_only_phase_loader_does_not_enqueue_or_fetch_provider_data():
    source = open(load_scoped_workout_analysis_v2.__code__.co_filename, encoding="utf-8").read()
    assert "request_activity_details" not in source
    assert "fetch_activity_details" not in source
    assert "get_provider_for_user" not in source
