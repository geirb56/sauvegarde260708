"""C420 — deterministic fast/slow lap pattern. SYNTHETIC laps only (no Garmin, no Mongo).

The real 05/11, 10/10, 12/10, 13/09 and 19/10 payloads are not available to the test suite: the
fixtures below reproduce the *shape* reported for each session, never its measured values.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from garmin_laps_analysis import adapt_garmin_laps, detect_lap_pattern


def build(specs, date=(2026, 11, 5), hr=None, **extra_by_position):
    """specs: [(duration_s, pace_s_per_km)] -> (workout, activity)."""
    start = datetime(*date, 8, tzinfo=timezone.utc)
    laps, total_d, total_t = [], 0.0, 0.0
    for i, (duration, pace) in enumerate(specs):
        distance = round(duration / pace * 1000, 1)
        lap = {
            "lap_index": i + 1, "order": i, "start_time_gmt": start.isoformat(),
            "distance_m": distance, "duration_s": duration, "moving_duration_s": duration,
            "elapsed_duration_s": duration, "average_speed_mps": distance / duration,
            "average_hr": (hr(i) if hr else 140 + i), "max_hr": 190, "intensity_type": "ACTIVE",
        }
        lap.update(extra_by_position.get(str(i), {}))
        laps.append(lap)
        start += timedelta(seconds=lap["elapsed_duration_s"])
        total_d += distance
        total_t += duration
    workout = {"id": "garmin-1", "external_id": "1", "type": "run", "data_source": "garmin",
               "date": "%04d-%02d-%02d" % date, "distance_km": round(total_d / 1000, 2),
               "duration_minutes": total_t / 60}
    return workout, {"external_id": "1", "activity_laps": {
        "schema_version": 1, "status": "complete", "source": "garmin", "endpoint": "splits", "laps": laps}}


# 05/11 shape: 23 laps = 4 warm-up laps, 7 x (60 s fast / 60 s slow), 5 cool-down laps.
SHAPE_0511 = (
    [(360, 360)] * 4
    + [(60, 230), (60, 390)] * 7
    + [(360, 360), (288, 360), (180, 360), (108, 360), (60, 400)]
)


def session_0511(**kw):
    return build(SHAPE_0511, **kw)


def test_0511_shape_detects_seven_repetitions_with_warmup_and_cooldown():
    workout, activity = session_0511(hr=lambda i: 130 + i * 2)
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed" and result["lap_count"] == 23
    pattern = result["pattern"]
    assert pattern["repetition_count"] == 7
    assert pattern["fast_segments"]["typical_duration_s"] == 60
    assert pattern["slow_segments"]["typical_duration_s"] == 60
    assert pattern["fast_segments"]["typical_pace_sec_per_km"] == 230
    assert [s["lap_position"] for s in pattern["fast_segments"]["segments"]] == list(range(5, 18, 2))
    assert len(pattern["slow_segments"]["segments"]) == 7
    assert result["confidence"] == "high"
    assert result["probable_warmup"]["last_lap_position"] == 4
    assert result["probable_cooldown"]["first_lap_position"] == 19
    assert "not a recorded phase" in result["probable_warmup"]["basis"]
    assert "not proof of a programmed recovery" in pattern["slow_segments_meaning"]
    assert pattern["fast_segments"]["avg_hr_change_first_to_last_bpm"] == 24  # raw laps 5 -> 17


def test_detector_values_match_raw_laps_and_do_not_mutate_inputs():
    workout, activity = session_0511(hr=lambda i: 130 + i * 2)
    original = deepcopy((workout, activity))
    result = detect_lap_pattern(workout, activity)
    assert (workout, activity) == original
    laps = activity["activity_laps"]["laps"]
    for segment in result["pattern"]["fast_segments"]["segments"]:
        raw = laps[segment["lap_position"] - 1]
        assert segment["duration_s"] == raw["duration_s"]
        assert segment["length_m"] == pytest.approx(raw["distance_m"], abs=0.05)
        assert segment["avg_hr_bpm"] == raw["average_hr"]
        assert segment["pace_sec_per_km"] == pytest.approx(
            raw["duration_s"] / raw["distance_m"] * 1000, abs=0.05)
    assert adapt_garmin_laps(workout, activity).status == "non_kilometric"  # km splits untouched


def test_missing_hr_is_unknown_not_zero():
    workout, activity = session_0511()
    for lap in activity["activity_laps"]["laps"]:
        lap["average_hr"] = None
    fast = detect_lap_pattern(workout, activity)["pattern"]["fast_segments"]
    assert fast["hr_evolution_available"] is False and "avg_hr_change_first_to_last_bpm" not in fast
    assert all(s["avg_hr_bpm"] is None for s in fast["segments"])


# 10/10 shape: 4 x 4 min with 2 min slow between, warm-up and cool-down.
SHAPE_1010 = [(600, 360)] + [(240, 255), (120, 390)] * 3 + [(240, 255)] + [(600, 370)]


def test_1010_four_by_four_minutes():
    workout, activity = build(SHAPE_1010, date=(2026, 10, 10))
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed"
    assert result["pattern"]["repetition_count"] == 4
    assert result["pattern"]["fast_segments"]["typical_duration_s"] == 240
    assert result["pattern"]["slow_segments"]["typical_duration_s"] == 120
    assert len(result["pattern"]["slow_segments"]["segments"]) == 3  # no trailing recovery before the cool-down
    assert result["probable_warmup"]["lap_count"] == 1 and result["probable_cooldown"]["lap_count"] == 1


@pytest.mark.parametrize("name,specs", [
    ("continuous_12_10", [(1800, 340), (1500, 335)]),
    ("continuous_13_09_many_laps", [(300, 330), (310, 335), (305, 328), (320, 340), (290, 325),
                                    (300, 332), (310, 336), (295, 329)]),
    ("treadmill_19_10_steady", [(600, 345)] * 6),
    ("gradual_drift", [(300, 300 + 4 * i) for i in range(10)]),
])
def test_continuous_sessions_never_get_an_invented_pattern(name, specs):
    workout, activity = build(specs, date=(2026, 10, 12))
    result = detect_lap_pattern(workout, activity)
    assert result["status"] in ("unknown", "no_pattern_observed")
    assert "pattern" not in result


def test_kilometre_autolaps_hide_structure_and_stay_unknown():
    workout, activity = build([(300, 300)] * 9 + [(150, 300)], date=(2026, 9, 13))
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "unknown"
    assert result["reason"] == "kilometre_laps_hide_intra_lap_structure"


def test_treadmill_with_only_slow_fast_blocks_is_not_a_repeated_alternation():
    # one fast block only: a single effort is not a repetition
    workout, activity = build([(600, 360), (600, 250), (600, 360), (600, 360)], date=(2026, 10, 19))
    assert detect_lap_pattern(workout, activity)["status"] in ("unknown", "no_pattern_observed")


def test_two_repetitions_are_not_enough():
    workout, activity = build([(300, 360), (60, 230), (60, 390), (60, 230), (300, 360)])
    assert "pattern" not in detect_lap_pattern(workout, activity)


def test_recorded_pause_is_not_a_recovery_and_breaks_the_chain():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 3 + [(60, 230), (60, 390), (60, 230)] + [(300, 360)]
    # lap 6 (index 5) becomes a recorded pause: slow in pace, 2 min elapsed for 60 s of running
    workout, activity = build(specs, **{"6": {"elapsed_duration_s": 120}})
    # keep chronology coherent for the elapsed difference
    laps = activity["activity_laps"]["laps"]
    start = datetime.fromisoformat(laps[0]["start_time_gmt"])
    for lap in laps:
        lap["start_time_gmt"] = start.isoformat()
        start += timedelta(seconds=lap["elapsed_duration_s"])
    result = detect_lap_pattern(workout, activity)
    assert {"code": "recorded_pause", "lap_position": 7} in result["anomalies"]
    assert result["status"] == "pattern_observed"
    assert result["pattern"]["repetition_count"] == 3  # the chain stops at the pause
    assert 7 not in [s["lap_position"] for s in result["pattern"]["slow_segments"]["segments"]]
    assert result["confidence"] == "low"


def test_stationary_lap_is_flagged_and_excluded():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 4 + [(60, 230)] + [(300, 360)]
    workout, activity = build(specs, **{"4": {"moving_duration_s": 20}})
    result = detect_lap_pattern(workout, activity)
    assert {"code": "stationary_time", "lap_position": 5} in result["anomalies"]
    assert result["status"] == "pattern_observed" and result["pattern"]["repetition_count"] == 3
    assert 5 not in [s["lap_position"] for s in result["pattern"]["slow_segments"]["segments"]]


def test_incomplete_final_lap_is_flagged_not_counted_as_effort():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 4 + [(12, 230)]
    workout, activity = build(specs)
    result = detect_lap_pattern(workout, activity)
    assert {"code": "incomplete_final_lap", "lap_position": 10} in result["anomalies"]
    assert result["pattern"]["repetition_count"] == 4
    assert result["confidence"] == "low"


def test_irregular_durations_do_not_form_a_pattern():
    specs = [(60, 230), (60, 390), (200, 230), (30, 390), (60, 230), (300, 390), (60, 230)]
    workout, activity = build(specs)
    assert "pattern" not in detect_lap_pattern(workout, activity)


def test_explicit_intensity_labels_are_reported_not_interpreted():
    workout, activity = session_0511()
    for lap in activity["activity_laps"]["laps"][5:7]:
        lap["intensity_type"] = "REST"
    result = detect_lap_pattern(workout, activity)
    assert {"code": "intensity_labels_recorded_not_interpreted", "labels": ["REST"],
            "lap_positions_by_label": {"REST": [6, 7]}} in result["anomalies"]
    assert result["pattern"]["repetition_count"] == 7  # label never decides the role of a lap


@pytest.mark.parametrize("mutate,reason", [
    (lambda w, a: a.pop("activity_laps"), "laps_missing"),
    (lambda w, a: w.update(distance_km=50.0), "coverage_incomplete"),
    (lambda w, a: a["activity_laps"]["laps"][3].update(duration_s=-1), "laps_invalid"),
    (lambda w, a: w.update(id="manual-1", data_source="manual"), "not_garmin"),
])
def test_unverifiable_laps_abstain(mutate, reason):
    workout, activity = session_0511()
    mutate(workout, activity)
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "unavailable" and result["reason"] == reason


def test_result_is_deterministic():
    workout, activity = session_0511(hr=lambda i: 130 + i)
    assert detect_lap_pattern(workout, activity) == detect_lap_pattern(workout, activity)


# ---------------------------------------------------------------- PR #411 review regressions

def test_zero_or_invalid_hr_is_unknown_never_a_trend():
    workout, activity = session_0511()
    for lap in activity["activity_laps"]["laps"][4:6]:
        lap["average_hr"] = 0
    fast = detect_lap_pattern(workout, activity)["pattern"]["fast_segments"]
    assert fast["segments"][0]["avg_hr_bpm"] is None
    assert fast["hr_evolution_available"] is False
    assert "avg_hr_change_first_to_last_bpm" not in fast


def test_small_pause_above_recording_tolerance_is_excluded_from_alternation():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 4 + [(60, 230)] + [(300, 360)]
    workout, activity = build(specs, **{"4": {"elapsed_duration_s": 70}})  # 60 s lap, 10 s paused
    laps = activity["activity_laps"]["laps"]
    start = datetime.fromisoformat(laps[0]["start_time_gmt"])
    for lap in laps:
        lap["start_time_gmt"] = start.isoformat()
        start += timedelta(seconds=lap["elapsed_duration_s"])
    result = detect_lap_pattern(workout, activity)
    assert {"code": "recorded_pause", "lap_position": 5} in result["anomalies"]
    assert result["confidence"] != "high"
    assert 5 not in [s["lap_position"] for s in result["pattern"]["slow_segments"]["segments"]]


@pytest.mark.parametrize("repetitions", [3, 4])
def test_complete_short_final_repetition_is_kept(repetitions):
    specs = [(300, 360)] + [(20, 230), (40, 390)] * (repetitions - 1) + [(20, 230)]
    workout, activity = build(specs)
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed"
    assert result["pattern"]["repetition_count"] == repetitions
    assert result["pattern"]["fast_segments"]["typical_duration_s"] == 20
    assert not any(a["code"] == "incomplete_final_lap" for a in result["anomalies"])


def test_truncated_final_effort_is_still_flagged_incomplete():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 4 + [(15, 230)]
    workout, activity = build(specs)
    result = detect_lap_pattern(workout, activity)
    assert {"code": "incomplete_final_lap", "lap_position": 10} in result["anomalies"]
    assert result["pattern"]["repetition_count"] == 4


def test_efforts_after_a_pause_are_not_labelled_cooldown():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 3 + [(60, 230), (60, 390), (60, 230)] + [(300, 360)]
    workout, activity = build(specs, **{"6": {"elapsed_duration_s": 120}})
    laps = activity["activity_laps"]["laps"]
    start = datetime.fromisoformat(laps[0]["start_time_gmt"])
    for lap in laps:
        lap["start_time_gmt"] = start.isoformat()
        start += timedelta(seconds=lap["elapsed_duration_s"])
    result = detect_lap_pattern(workout, activity)
    assert "probable_cooldown" not in result
    unclassified = next(a for a in result["anomalies"] if a["code"] == "laps_outside_pattern_unclassified")
    assert 8 in unclassified["lap_positions"]  # the later fast effort stays unclassified
    assert result["probable_warmup"]["last_lap_position"] == 1


def test_efforts_before_a_stationary_lap_are_not_labelled_warmup():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 2 + [(60, 230), (60, 390)] * 4 + [(300, 360)]
    workout, activity = build(specs, **{"5": {"moving_duration_s": 20}})
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed"
    assert result["pattern"]["first_lap_position"] == 8  # the earlier efforts precede the stationary lap
    assert "probable_warmup" not in result
    assert any(a["code"] == "laps_outside_pattern_unclassified" for a in result["anomalies"])


def test_aberrant_19m_lap_does_not_distort_detection():
    specs = [(360, 360)] * 3 + [(60, 230), (60, 390)] * 7 + [(360, 360)] * 3
    workout, activity = build(specs)
    laps = activity["activity_laps"]["laps"]
    laps[16].update(distance_m=19.0, duration_s=180, moving_duration_s=180, elapsed_duration_s=180,
                    average_speed_mps=19 / 180)
    start = datetime.fromisoformat(laps[0]["start_time_gmt"])
    for lap in laps:
        lap["start_time_gmt"] = start.isoformat()
        start += timedelta(seconds=lap["elapsed_duration_s"])
    workout["distance_km"] = round(sum(l["distance_m"] for l in laps) / 1000, 2)
    workout["duration_minutes"] = sum(l["duration_s"] for l in laps) / 60
    result = detect_lap_pattern(workout, activity)
    assert {"code": "aberrant_lap", "lap_position": 17} in result["anomalies"]
    assert result["status"] == "pattern_observed"
    assert result["confidence"] == "low"
    assert 17 not in [s["lap_position"] for r in ("fast_segments", "slow_segments")
                      for s in result["pattern"][r]["segments"]]
    assert result["pattern"]["fast_segments"]["typical_pace_sec_per_km"] == 230


# ---------------------------------------------------------------- C420B chronology correction

def restamp(activity, offsets=None, drop_at=None, gap=0):
    """Rewrite starts from elapsed times, adding per-lap rounding offsets and an optional real gap."""
    laps = activity["activity_laps"]["laps"]
    start = datetime.fromisoformat(laps[0]["start_time_gmt"])
    for i, lap in enumerate(laps):
        if drop_at is not None and i == drop_at:
            start += timedelta(seconds=gap)
        lap["start_time_gmt"] = (start + timedelta(seconds=(offsets or {}).get(i, 0))).isoformat()
        start += timedelta(seconds=lap["elapsed_duration_s"])


@pytest.mark.parametrize("rounding", [1.0, 1.5, 2.0, -2.0])
def test_timestamp_rounding_up_to_two_seconds_is_accepted(rounding):
    workout, activity = session_0511()
    restamp(activity, {i: rounding if i % 2 else 0 for i in range(23)})
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed" and result["pattern"]["repetition_count"] == 7
    assert not [a for a in result["anomalies"] if a["code"].startswith("chronology_")]


def test_real_interruption_beyond_rounding_breaks_the_chain():
    workout, activity = session_0511()
    restamp(activity, drop_at=11, gap=5)  # 5 s unrecorded between lap 11 and 12
    result = detect_lap_pattern(workout, activity)
    assert {"code": "chronology_gap", "lap_position": 12} in result["anomalies"]
    assert result["status"] == "pattern_observed"
    positions = [s["lap_position"] for s in result["pattern"]["fast_segments"]["segments"]]
    assert not (set(positions) & {5, 11} and set(positions) & {13, 15})  # chain never crosses the gap
    assert result["pattern"]["repetition_count"] < 7 and result["confidence"] == "low"


def test_isolated_chronology_anomaly_keeps_the_locally_reliable_pattern():
    workout, activity = session_0511()
    restamp(activity, drop_at=20, gap=30)  # anomaly inside the cool-down only
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed" and result["pattern"]["repetition_count"] == 7
    assert "probable_cooldown" not in result
    assert {"code": "chronology_gap", "lap_position": 21} in result["anomalies"]


def test_widespread_chronology_breaks_abstain():
    workout, activity = session_0511()
    restamp(activity, {i: 10 * i for i in range(23)})
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "unavailable" and result["reason"] == "chronology_incoherent"


def test_recorded_pause_with_coherent_chronology_still_excluded():
    specs = [(300, 360)] + [(60, 230), (60, 390)] * 4 + [(60, 230)] + [(300, 360)]
    workout, activity = build(specs, **{"4": {"elapsed_duration_s": 70}})
    restamp(activity)
    result = detect_lap_pattern(workout, activity)
    assert {"code": "recorded_pause", "lap_position": 5} in result["anomalies"]
    assert not [a for a in result["anomalies"] if a["code"].startswith("chronology_")]


def test_laps_covering_part_of_the_session_are_flagged_not_rejected():
    workout, activity = session_0511()
    workout["distance_km"] *= 1.3
    workout["duration_minutes"] *= 1.3
    result = detect_lap_pattern(workout, activity)
    assert result["status"] == "pattern_observed"
    partial = [a for a in result["anomalies"] if a["code"] == "laps_cover_partial_session"]
    assert partial and 0.7 < partial[0]["covered_distance_ratio"] < 0.8
    assert result["confidence"] == "low"
    assert "probable_warmup" not in result and "probable_cooldown" not in result


def test_laps_covering_too_little_or_more_than_the_session_stay_unavailable():
    workout, activity = session_0511()
    workout["distance_km"] *= 3
    workout["duration_minutes"] *= 3
    assert detect_lap_pattern(workout, activity)["reason"] == "coverage_incomplete"
    workout, activity = session_0511()
    workout["distance_km"] *= 0.8
    workout["duration_minutes"] *= 0.8
    assert detect_lap_pattern(workout, activity)["reason"] == "coverage_incomplete"


def test_rounding_noise_never_creates_a_pattern_in_a_continuous_run():
    specs = [(300, 360)] + [(60, 355), (60, 362)] * 6 + [(300, 360)]
    workout, activity = build(specs)
    restamp(activity, {i: (i % 3) - 1 for i in range(len(specs))})
    result = detect_lap_pattern(workout, activity)
    assert result["status"] in ("no_pattern_observed", "unknown")


def test_labels_are_reported_with_positions_without_changing_roles():
    workout, activity = session_0511()
    for i in (4, 6):
        activity["activity_laps"]["laps"][i]["intensity_type"] = "INTERVAL"
    result = detect_lap_pattern(workout, activity)
    label = next(a for a in result["anomalies"] if a["code"] == "intensity_labels_recorded_not_interpreted")
    assert label["lap_positions_by_label"] == {"INTERVAL": [5, 7]}
    assert result["pattern"]["repetition_count"] == 7
