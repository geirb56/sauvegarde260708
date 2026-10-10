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
    assert "efforts_not_comparable" in result.limitations


def test_one_repetition_has_descriptive_values_but_no_regularity_claim():
    result = build_workout_analysis_v2(
        _workout(), [], phases=[_phase(0, "effort", duration=240, distance=800)]
    ).phase_analysis
    assert result.effort_statistics.count == 1
    assert result.effort_regularity.available is False
    assert result.effort_regularity.average_duration_s == 240
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
