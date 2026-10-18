"""Synthetic laps only; the service uses in-memory collections, never Garmin/Mongo."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from garmin.activity_laps import FIELDS, normalize_activity_laps
from garmin_laps_analysis import adapt_garmin_laps
from workout_analysis_v2 import build_workout_analysis_v2
from workout_analysis_v2_service import (
    enrich_workout_from_garmin_activity,
    load_scoped_workout_analysis_v2,
)


def fixture(distances=(1000, 1000, 1000, 1000), durations=(300, 300, 330, 330)):
    start = datetime(2026, 10, 10, 8, tzinfo=timezone.utc)
    laps = []
    for index, (distance, duration) in enumerate(zip(distances, durations)):
        laps.append({
            "lap_index": index + 1, "order": index,
            "start_time_gmt": start.isoformat(), "distance_m": distance,
            "duration_s": duration, "moving_duration_s": duration,
            "elapsed_duration_s": duration, "average_speed_mps": distance / duration,
            "average_hr": 145 + index * 5, "max_hr": 175, "intensity_type": "ACTIVE",
        })
        start += timedelta(seconds=duration)
    workout = {
        "id": "garmin-123", "external_id": "123", "user_id": "synthetic",
        "name": "Synthetic run", "type": "run", "date": "2026-10-10",
        "distance_km": sum(distances) / 1000, "duration_minutes": sum(durations) / 60,
    }
    activity = {
        "user_id": "synthetic", "external_id": "123", "source": "garmin",
        "activity_laps": {
            "schema_version": 1, "status": "complete", "source": "garmin",
            "endpoint": "splits", "laps": laps,
        },
    }
    return workout, activity


def analyze(workout, activity, language="en"):
    return build_workout_analysis_v2(
        enrich_workout_from_garmin_activity(workout, activity), [], language,
    )


def test_valid_kilometres_exact_units_and_no_mutation():
    workout, activity = fixture()
    original = deepcopy((workout, activity))
    result = adapt_garmin_laps(workout, activity)
    assert result.status == "eligible"
    assert result.km_splits == [
        {"km": index, "distance_m": 1000, "duration_s": duration,
         "pace_min_km": duration / 60, "avg_hr": hr}
        for index, duration, hr in zip(range(1, 5), (300, 300, 330, 330), (145, 150, 155, 160))
    ]
    assert (workout, activity) == original
    analysis = analyze(workout, activity)
    assert analysis.evidence.has_splits
    assert analysis.pacing.fastest_split_min_km == 5
    assert analysis.pacing.slowest_split_min_km == 5.5
    # Kilometre laps alone do not classify a continuous workout.
    assert not analysis.signals.session_structure.available
    assert analysis.coach_language.conclusions == []
    assert analysis.physiology.hr_drift is None


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_measured_conclusion_requires_independent_continuous_evidence(language):
    workout, activity = fixture()
    workout["session_structure"] = "continuous"
    before = build_workout_analysis_v2(workout, [], language)
    assert before.coach_language.conclusions == []
    analysis = analyze(workout, activity, language)
    item, = analysis.coach_language.conclusions
    assert item.code == "coach.execution.pace_hr"
    assert item.evidence["second_half_pace_change_sec_per_km"] == pytest.approx(30)
    assert item.evidence["first_half_hr_bpm"] == pytest.approx(147.5)
    assert item.evidence["second_half_hr_bpm"] == pytest.approx(157.5)
    assert item.metadata["coverage"] == "whole_session"
    assert item.metadata["hr_aggregation"] == "duration_weighted_measured"
    assert analysis.physiology.hr_drift is None
    assert all(word not in item.text.lower() for word in ("fatigue", "drift", "deriva"))


def test_last_partial_lap_is_measured_not_promoted_to_kilometre():
    workout, activity = fixture((1000, 1000, 250), (300, 330, 90))
    workout["session_structure"] = "continuous"
    result = adapt_garmin_laps(workout, activity)
    assert result.status == "eligible"
    assert len(result.km_splits) == 2
    assert all(row["distance_m"] == 1000 for row in result.km_splits)
    item, = analyze(workout, activity).coach_language.conclusions
    assert item.evidence["measured_distance_km"] == 2
    assert item.evidence["split_count"] == 2
    assert item.metadata["coverage"] == "measured_segments"
    assert item.metadata["comparison_scope"] == "first_last_measured_segments"
    assert "second_half_pace_change_sec_per_km" not in item.evidence


@pytest.mark.parametrize("distances", [(400, 400, 400), (500, 500), (2000, 2000), (250,),
                                          (1000, 250, 1000), (1000, 1001.1)])
def test_non_kilometric_laps_are_never_interpolated(distances):
    workout, activity = fixture(distances, (300,) * len(distances))
    result = adapt_garmin_laps(workout, activity)
    assert result.status == "non_kilometric"
    assert result.km_splits == []
    assert not analyze(workout, activity).evidence.has_splits


@pytest.mark.parametrize("intensity", ["RECOVERY", "REST", "WARMUP", "COOLDOWN", "UNKNOWN", {}, 1])
def test_structured_laps_do_not_become_continuous_even_with_stale_label(intensity):
    workout, activity = fixture()
    workout["session_structure"] = "continuous"
    activity["activity_laps"]["laps"][1]["intensity_type"] = intensity
    assert adapt_garmin_laps(workout, activity).status == "non_kilometric"
    assert analyze(workout, activity).coach_language.conclusions == []


def test_intervals_with_recovery_distances_never_produce_km_conclusion():
    workout, activity = fixture((1000, 200, 1000, 200), (240, 120, 250, 120))
    workout["session_structure"] = "intervals"
    for lap in activity["activity_laps"]["laps"][1::2]:
        lap["intensity_type"] = "RECOVERY"
    assert adapt_garmin_laps(workout, activity).km_splits == []
    assert analyze(workout, activity).coach_language.conclusions == []


@pytest.mark.parametrize("missing_indices", [(0, 1, 2, 3), (1,), (0, 3)])
def test_missing_hr_preserves_pace_but_never_crosses_with_summary_hr(missing_indices):
    workout, activity = fixture()
    workout.update(session_structure="continuous", avg_heart_rate=160)
    for index in missing_indices:
        activity["activity_laps"]["laps"][index]["average_hr"] = None
    item, = analyze(workout, activity).coach_language.conclusions
    assert item.code == "coach.pacing"
    assert not any("hr" in key or "heart_rate" in key for key in item.evidence)


@pytest.mark.parametrize("key,value", [
    ("distance_m", None), ("distance_m", 0), ("distance_m", -1), ("distance_m", 400),
    ("distance_m", "1000"), ("distance_m", True), ("distance_m", float("inf")),
    ("duration_s", None), ("duration_s", 0), ("duration_s", -1),
    ("duration_s", float("nan")), ("duration_s", 10 ** 1000),
    ("average_hr", 0), ("average_hr", -1), ("average_hr", True),
    ("average_hr", float("nan")), ("average_hr", 180), ("max_hr", 140),
    ("average_speed_mps", 12), ("average_speed_mps", 0),
    ("moving_duration_s", 301), ("elapsed_duration_s", 299),
    ("average_moving_speed_mps", 10),
])
def test_invalid_or_incoherent_measurements_fail_closed(key, value):
    workout, activity = fixture()
    activity["activity_laps"]["laps"][0][key] = value
    assert adapt_garmin_laps(workout, activity).km_splits == []


@pytest.mark.parametrize("field,value", [
    ("distance_km", 5), ("distance_km", 3.9), ("distance_km", None),
    ("duration_minutes", 0), ("duration_minutes", 22), ("duration_minutes", 20),
])
def test_missing_or_incoherent_summary_prevents_partial_coverage(field, value):
    workout, activity = fixture()
    workout[field] = value
    assert adapt_garmin_laps(workout, activity).km_splits == []


@pytest.mark.parametrize("change", ["reverse", "duplicate", "missing_first", "duplicate_index",
                                         "order", "boolean_index", "bad_lap"])
def test_lap_order_is_validated_never_sorted_or_skipped(change):
    workout, activity = fixture()
    laps = activity["activity_laps"]["laps"]
    if change == "reverse":
        laps.reverse()
    elif change == "duplicate":
        laps[1] = deepcopy(laps[0])
    elif change == "missing_first":
        del laps[0]
    elif change == "duplicate_index":
        laps[1]["lap_index"] = 3
    elif change == "order":
        laps[1]["order"] = 0
    elif change == "boolean_index":
        laps[0]["lap_index"] = True
    else:
        laps[0] = None
    assert adapt_garmin_laps(workout, activity).km_splits == []


def normalize_synthetic_laps(laps):
    raw = [{source: lap[target] for source, target in FIELDS.items() if target in lap}
           for lap in laps]
    return normalize_activity_laps({"activityId": 123, "lapDTOs": raw}, "123")


@pytest.mark.parametrize("indices,accepted", [
    ((1, 2, 3, 4), True),
    ((0, 1, 2, 3), False),
    ((2, 4, 6, 8), True),
    ((21, 22, 24, 30), True),
    ((1, 2, 2, 4), False),
    ((4, 3, 2, 1), False),
    ((-1, 1, 2, 3), False),
    ((True, 2, 3, 4), False),
    ((1.0, 2, 3, 4), False),
    ((None, 2, 3, 4), False),
])
def test_native_indices_match_producer_without_changing_kilometre_ordinals(indices, accepted):
    workout, activity = fixture()
    laps = activity["activity_laps"]["laps"]
    for lap, native_index in zip(laps, indices):
        lap["lap_index"] = native_index
    original = deepcopy(activity)
    if accepted:
        normalized = normalize_synthetic_laps(laps)
        assert [lap["lap_index"] for lap in normalized] == list(indices)
        activity["activity_laps"]["laps"] = normalized
        result = adapt_garmin_laps(workout, activity)
        assert result.status == "eligible"
        assert [row["km"] for row in result.km_splits] == [1, 2, 3, 4]
        assert [row["duration_s"] for row in result.km_splits] == [300, 300, 330, 330]
        assert [lap["lap_index"] for lap in normalized] == list(indices)
        analysis = analyze(workout, activity)
        assert not analysis.signals.session_structure.available
        assert analysis.coach_language.conclusions == []
    else:
        with pytest.raises(ValueError, match="Invalid lap order or duplicate"):
            normalize_synthetic_laps(laps)
        assert adapt_garmin_laps(workout, activity).status == "invalid_order"
        assert activity == original


@pytest.mark.parametrize("orders,accepted", [
    ((0, 1, 2, 3), True), ((2, 4, 6, 8), True),
    ((0, 1, 1, 3), False), ((3, 2, 1, 0), False),
    ((-1, 1, 2, 3), False), ((False, 1, 2, 3), False),
])
def test_order_contract_still_matches_producer_for_nonconsecutive_native_indices(orders, accepted):
    workout, activity = fixture()
    laps = activity["activity_laps"]["laps"]
    for lap, native_index, order in zip(laps, (2, 4, 6, 8), orders):
        lap.update(lap_index=native_index, order=order)
    if accepted:
        activity["activity_laps"]["laps"] = normalize_synthetic_laps(laps)
        assert adapt_garmin_laps(workout, activity).status == "eligible"
    else:
        with pytest.raises(ValueError, match="Invalid lap order or duplicate"):
            normalize_synthetic_laps(laps)
        assert adapt_garmin_laps(workout, activity).status == "invalid_order"


@pytest.mark.parametrize("intensity", ["ACTIVE", "RECOVERY", "REST", "WARMUP", "COOLDOWN",
                                      "UNKNOWN", "active", "UNVERIFIED_NATIVE_VALUE"])
def test_producer_preserves_intensity_strings_but_adapter_does_not_invent_mapping(intensity):
    workout, activity = fixture()
    for lap in activity["activity_laps"]["laps"]:
        lap["intensity_type"] = intensity
    normalized = normalize_synthetic_laps(activity["activity_laps"]["laps"])
    assert all(lap["intensity_type"] == intensity for lap in normalized)
    activity["activity_laps"]["laps"] = normalized
    result = adapt_garmin_laps(workout, activity)
    assert result.status == ("eligible" if intensity == "ACTIVE" else "non_kilometric")
    assert analyze(workout, activity).coach_language.conclusions == []


@pytest.mark.parametrize("omit", [True, False])
def test_missing_intensity_requires_other_measurements_and_never_proves_continuous(omit):
    workout, activity = fixture()
    for lap in activity["activity_laps"]["laps"]:
        if omit:
            lap.pop("intensity_type")
        else:
            lap["intensity_type"] = None
    normalized = normalize_synthetic_laps(activity["activity_laps"]["laps"])
    assert all(lap["intensity_type"] is None for lap in normalized)
    activity["activity_laps"]["laps"] = normalized
    assert adapt_garmin_laps(workout, activity).status == "eligible"
    analysis = analyze(workout, activity)
    assert not analysis.signals.session_structure.available
    assert analysis.coach_language.conclusions == []
    normalized[0]["duration_s"] = None
    assert adapt_garmin_laps(workout, activity).km_splits == []


@pytest.mark.parametrize("change", ["distance", "duration", "chronology", "partial"])
def test_gapped_native_indices_preserve_measurement_and_tail_guards(change):
    workout, activity = fixture()
    laps = activity["activity_laps"]["laps"]
    for lap, native_index in zip(laps, (2, 4, 6, 8)):
        lap["lap_index"] = native_index
    if change == "distance":
        for lap in laps:
            lap.update(distance_m=1001, average_speed_mps=1001 / lap["duration_s"])
        assert adapt_garmin_laps(workout, activity).status == "non_kilometric"
    elif change == "duration":
        workout["duration_minutes"] += 1
        assert adapt_garmin_laps(workout, activity).status == "incoherent_duration"
    elif change == "chronology":
        laps[1]["start_time_gmt"] = "2026-10-10T08:05:02Z"
        assert adapt_garmin_laps(workout, activity).status == "incoherent_chronology"
    else:
        laps[-1].update(distance_m=250, average_speed_mps=250 / laps[-1]["duration_s"])
        workout["distance_km"] = 3.25
        result = adapt_garmin_laps(workout, activity)
        assert result.status == "eligible"
        assert [row["km"] for row in result.km_splits] == [1, 2, 3]
        assert all(row["distance_m"] == 1000 for row in result.km_splits)


@pytest.mark.parametrize("change", ["missing", "reverse", "overlap", "gap", "offset", "invalid"])
def test_chronology_rejects_unaccounted_gaps_overlaps_or_mixed_timestamps(change):
    workout, activity = fixture()
    lap = activity["activity_laps"]["laps"][1]
    if change == "missing":
        lap["start_time_gmt"] = None
    elif change == "reverse":
        lap["start_time_gmt"] = "2026-10-10T07:55:00Z"
    elif change == "overlap":
        lap["start_time_gmt"] = "2026-10-10T08:04:58Z"
    elif change == "gap":
        lap["start_time_gmt"] = "2026-10-10T08:05:02Z"
    elif change == "offset":
        lap["start_time_gmt"] = "2026-10-10T08:05:00+02:00"
    else:
        lap["start_time_gmt"] = "yesterday"
    assert adapt_garmin_laps(workout, activity).km_splits == []


def test_optional_timestamps_and_speeds_are_not_invented_or_required():
    workout, activity = fixture()
    for lap in activity["activity_laps"]["laps"]:
        for key in ("start_time_gmt", "average_speed_mps", "moving_duration_s", "elapsed_duration_s"):
            lap.pop(key)
    assert adapt_garmin_laps(workout, activity).status == "eligible"


def test_accounted_pause_uses_elapsed_for_chronology_not_for_pace():
    workout, activity = fixture()
    laps = activity["activity_laps"]["laps"]
    laps[0]["elapsed_duration_s"] += 60
    for lap in laps[1:]:
        start = datetime.fromisoformat(lap["start_time_gmt"])
        lap["start_time_gmt"] = (start + timedelta(seconds=60)).isoformat()
    result = adapt_garmin_laps(workout, activity)
    assert result.status == "eligible"
    assert result.km_splits[0]["duration_s"] == 300
    assert result.km_splits[0]["pace_min_km"] == 5
    assert "session_structure" not in enrich_workout_from_garmin_activity(workout, activity)


def test_second_resolution_start_times_accept_measured_fractional_durations():
    workout, activity = fixture(durations=(341.128, 341.128, 341.128, 341.128))
    for lap in activity["activity_laps"]["laps"]:
        lap["start_time_gmt"] = datetime.fromisoformat(lap["start_time_gmt"]).replace(
            microsecond=0,
        ).isoformat()
    result = adapt_garmin_laps(workout, activity)
    assert result.status == "eligible"
    assert all(row["duration_s"] == 341.128 for row in result.km_splits)


def test_second_resolution_tolerance_cannot_accumulate_unmeasured_gaps():
    workout, activity = fixture()
    for index, lap in enumerate(activity["activity_laps"]["laps"]):
        start = datetime.fromisoformat(lap["start_time_gmt"])
        lap["start_time_gmt"] = (start + timedelta(seconds=index * 0.75)).isoformat()
    assert adapt_garmin_laps(workout, activity).status == "incoherent_chronology"


def test_single_kilometre_and_partial_tail_cannot_make_two_coach_samples():
    workout, activity = fixture((1000, 250), (300, 90))
    workout["session_structure"] = "continuous"
    result = adapt_garmin_laps(workout, activity)
    assert len(result.km_splits) == 1
    assert analyze(workout, activity).coach_language.conclusions == []


@pytest.mark.parametrize("distances,eligible", [
    ((999.5, 1000.5), True), ((1001, 999), True),
    ((1001, 1001), False), ((998.9, 1000), False),
])
def test_kilometre_recording_tolerance_never_snaps_or_accumulates(distances, eligible):
    workout, activity = fixture(distances, (300, 300))
    result = adapt_garmin_laps(workout, activity)
    assert (result.status == "eligible") is eligible
    if eligible:
        assert [row["distance_m"] for row in result.km_splits] == list(distances)
        assert sum(row["duration_s"] for row in result.km_splits) == 600


@pytest.mark.parametrize("extra_distance,eligible", [(0.005, True), (0.0051, False)])
def test_summary_rounding_allowance_does_not_fabricate_missing_metres(extra_distance, eligible):
    workout, activity = fixture()
    workout.update(distance_km=4 + extra_distance, session_structure="continuous")
    result = adapt_garmin_laps(workout, activity)
    assert (result.status == "eligible") is eligible
    if eligible:
        item, = analyze(workout, activity).coach_language.conclusions
        assert item.evidence["measured_distance_km"] == 4
        assert item.metadata["coverage"] == "measured_segments"


@pytest.mark.parametrize("seconds,eligible", [(30, True), (30.01, False), (-30, True), (-30.01, False)])
def test_summary_duration_rounding_has_fixed_not_relative_allowance(seconds, eligible):
    workout, activity = fixture()
    workout["duration_minutes"] += seconds / 60
    assert (adapt_garmin_laps(workout, activity).status == "eligible") is eligible


@pytest.mark.parametrize("key,value", [
    ("schema_version", 2), ("schema_version", True), ("schema_version", 1.0),
    ("status", "running"), ("status", "empty"), ("status", []),
    ("source", "manual"), ("endpoint", "typed-splits"),
    ("laps", []), ("laps", None), ("laps", {}), ("laps", [None] * 1001),
])
def test_incomplete_or_malformed_cache_cannot_enrich(key, value):
    workout, activity = fixture()
    activity["activity_laps"][key] = value
    assert adapt_garmin_laps(workout, activity).km_splits == []


@pytest.mark.parametrize("cache,status", [(None, "missing"), ([], "invalid_cache"),
                                         ({}, "invalid_cache")])
def test_missing_cache_is_noop(cache, status):
    workout, activity = fixture()
    activity["activity_laps"] = cache
    assert adapt_garmin_laps(workout, activity).status == status
    assert enrich_workout_from_garmin_activity(workout, activity) == workout


def test_empty_cache_has_no_conclusion():
    workout, activity = fixture()
    activity["activity_laps"].update(status="empty", laps=[])
    assert adapt_garmin_laps(workout, activity).status == "empty"
    assert analyze(workout, activity).coach_language.conclusions == []


def test_non_garmin_activity_is_not_enriched():
    workout, activity = fixture()
    workout["id"] = "manual-123"
    assert adapt_garmin_laps(workout, activity).status == "not_garmin"
    assert enrich_workout_from_garmin_activity(workout, activity) == workout


@pytest.mark.parametrize("origin", ["workout", "activity", "raw_payload", "garmin_activity"])
@pytest.mark.parametrize("empty_workout", [False, True])
def test_existing_nonempty_splits_have_priority(origin, empty_workout):
    workout, activity = fixture()
    if empty_workout:
        workout["km_splits"] = []
    existing = [{"km": 1, "pace_min_km": 4, "avg_hr": 160}]
    if origin == "workout":
        workout["km_splits"] = existing
    elif origin == "activity":
        activity["km_splits"] = existing
    else:
        activity[origin] = {"km_splits": existing}
    assert enrich_workout_from_garmin_activity(workout, activity)["km_splits"] == existing


@pytest.mark.parametrize("existing", [None, []])
def test_absent_or_empty_splits_can_use_valid_laps(existing):
    workout, activity = fixture()
    workout["km_splits"] = existing
    assert len(enrich_workout_from_garmin_activity(workout, activity)["km_splits"]) == 4


class Cursor:
    def sort(self, *_):
        return self

    async def to_list(self, **_):
        return []


def service(workout, activity, language="en"):
    db = SimpleNamespace(
        workouts=SimpleNamespace(find_one=AsyncMock(return_value=workout),
                                 find=lambda *_: Cursor()),
        garmin_activities=SimpleNamespace(find_one=AsyncMock(return_value=activity)),
    )
    result = asyncio.run(load_scoped_workout_analysis_v2(
        db=db, user_id="synthetic", workout_id=workout["id"], language=language,
    ))
    return result, db


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_service_preserves_single_garmin_phase_and_uses_measured_laps(language):
    workout, activity = fixture()
    activity["activity_details"] = {
        "schema_version": 2, "status": "complete", "source": "garmin",
        "endpoint": "typed-splits", "phases": [{
            "order": 0, "phase_type": "effort", "source": "garmin",
            "duration_s": 1260, "distance_m": 4000,
        }],
    }
    (enriched, analysis), db = service(workout, activity, language)
    assert len(enriched["km_splits"]) == 4
    assert analysis.signals.session_structure.code == "continuous"
    assert len(analysis.phase_analysis.phases) == 1
    assert analysis.coach_language.conclusions[0].code == "coach.execution.pace_hr"
    assert db.garmin_activities.find_one.call_args.args[0] == {
        "user_id": "synthetic", "external_id": "123",
    }


def test_service_existing_interval_phases_remain_authoritative():
    workout, activity = fixture()
    activity["activity_details"] = {
        "schema_version": 2, "status": "complete", "source": "garmin",
        "endpoint": "typed-splits", "phases": [
            {"order": index, "phase_type": kind, "source": "garmin",
             "distance_m": distance, "duration_s": duration}
            for index, (kind, distance, duration) in enumerate([
                ("effort", 1000, 240), ("recovery", 200, 120), ("effort", 1000, 250),
            ])
        ],
    }
    (_, analysis), _ = service(workout, activity)
    assert analysis.signals.session_structure.code == "intervals"
    assert [p.phase_type for p in analysis.phase_analysis.phases] == ["effort", "recovery", "effort"]
    assert all(item.category == "repetitions" for item in analysis.coach_language.conclusions)
    assert analysis.physiology.hr_drift is None


def test_service_non_garmin_never_reads_laps():
    workout, activity = fixture()
    workout["id"] = "manual-123"
    (enriched, analysis), db = service(workout, activity)
    db.garmin_activities.find_one.assert_not_awaited()
    assert "km_splits" not in enriched
    assert not analysis.evidence.has_splits


def test_service_without_laps_is_identical_to_existing_analysis():
    workout, activity = fixture()
    del activity["activity_laps"]
    (_, analysis), _ = service(workout, activity)
    assert analysis == build_workout_analysis_v2(workout, [])


def test_single_kilometre_is_not_enough_for_coach_conclusion():
    workout, activity = fixture((1000,), (300,))
    workout["session_structure"] = "continuous"
    assert adapt_garmin_laps(workout, activity).status == "eligible"
    assert analyze(workout, activity).coach_language.conclusions == []
