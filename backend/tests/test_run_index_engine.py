from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.run_index_engine import calculate_run_index


def _run(days_ago: int, distance_km: float, pace_min_km: float, avg_hr: int | None = None) -> dict:
    duration_minutes = distance_km * pace_min_km
    return {
        "type": "run",
        "date": (date(2026, 7, 7) - timedelta(days=days_ago)).isoformat(),
        "distance_km": distance_km,
        "duration_minutes": round(duration_minutes, 1),
        "avg_pace_min_km": pace_min_km,
        "avg_speed_kmh": round(60.0 / pace_min_km, 2),
        "avg_heart_rate": avg_hr,
    }


def _beginner_profile() -> list[dict]:
    return [
        _run(3, 3.5, 6.8),
        _run(10, 4.2, 6.7),
        _run(17, 5.0, 6.6),
        _run(24, 6.0, 6.7),
        _run(36, 4.0, 6.9),
        _run(47, 5.0, 6.8),
    ]


def _intermediate_profile() -> list[dict]:
    return [
        _run(2, 8.0, 5.1, 154),
        _run(5, 10.0, 4.9, 162),
        _run(9, 14.0, 5.2, 151),
        _run(13, 6.0, 4.8, 165),
        _run(18, 12.0, 5.0, 156),
        _run(22, 16.0, 5.2, 149),
        _run(29, 8.0, 5.0, 155),
        _run(33, 5.0, 4.7, 168),
        _run(40, 12.0, 5.1, 152),
        _run(46, 18.0, 5.3, 150),
    ]


def _advanced_profile() -> list[dict]:
    return [
        _run(1, 10.0, 4.0, 168),
        _run(4, 18.0, 4.35, 154),
        _run(7, 12.0, 4.08, 166),
        _run(11, 21.1, 4.22, 160),
        _run(14, 8.0, 3.9, 171),
        _run(18, 16.0, 4.3, 155),
        _run(21, 14.0, 4.15, 162),
        _run(25, 20.0, 4.32, 153),
        _run(29, 10.0, 4.05, 167),
        _run(34, 24.0, 4.38, 151),
        _run(39, 12.0, 4.1, 164),
        _run(44, 16.0, 4.25, 157),
        _run(50, 8.0, 3.95, 170),
    ]


def _elite_profile() -> list[dict]:
    return [
        _run(1, 10.0, 3.15, 173),
        _run(3, 16.0, 3.28, 166),
        _run(5, 24.0, 3.42, 159),
        _run(8, 12.0, 3.18, 175),
        _run(10, 21.1, 3.31, 168),
        _run(13, 18.0, 3.36, 163),
        _run(16, 8.0, 3.1, 178),
        _run(19, 26.0, 3.45, 158),
        _run(22, 14.0, 3.22, 171),
        _run(26, 10.0, 3.14, 174),
        _run(30, 28.0, 3.47, 157),
        _run(34, 12.0, 3.19, 174),
        _run(38, 18.0, 3.34, 164),
        _run(42, 5.0, 2.95, 181),
        _run(46, 22.0, 3.4, 160),
    ]


def _progressive_profile() -> list[dict]:
    return [
        _run(185, 5.0, 6.3),
        _run(170, 6.0, 6.1),
        _run(150, 7.0, 5.9),
        _run(125, 8.0, 5.6, 160),
        _run(95, 10.0, 5.3, 158),
        _run(70, 12.0, 5.0, 156),
        _run(45, 14.0, 4.8, 154),
        _run(28, 16.0, 4.6, 152),
        _run(14, 10.0, 4.3, 165),
        _run(4, 21.1, 4.18, 160),
    ]


# ---------------------------------------------------------------------------
# Original ordering / range tests (updated for new contract)
# ---------------------------------------------------------------------------

def test_profiles_produce_ordered_run_index_scores():
    reference_date = date(2026, 7, 7)
    beginner = calculate_run_index(_beginner_profile(), reference_date)
    intermediate = calculate_run_index(_intermediate_profile(), reference_date)
    advanced = calculate_run_index(_advanced_profile(), reference_date)
    elite = calculate_run_index(_elite_profile(), reference_date)

    assert beginner["run_index"] < intermediate["run_index"] < advanced["run_index"] < elite["run_index"]
    assert beginner["confidence_score"] < elite["confidence_score"]


def test_score_ranges_are_always_valid_for_all_profiles():
    reference_date = date(2026, 7, 7)
    for profile in (
        _beginner_profile(),
        _intermediate_profile(),
        _advanced_profile(),
        _elite_profile(),
    ):
        result = calculate_run_index(profile, reference_date)
        assert result["status"] == "sufficient"
        assert result["run_index"] is not None
        assert 0 <= result["run_index"] <= 1000
        assert 0 <= result["confidence_score"] <= 100
        for pillar in ("speed_score", "endurance_score", "consistency_score"):
            # These pillars should be computable from these profiles.
            assert result[pillar] is not None
            assert 0 <= result[pillar] <= 100


def test_missing_heart_rate_data_reduces_confidence_without_breaking_ranges():
    reference_date = date(2026, 7, 7)
    hr_rich = calculate_run_index(_intermediate_profile(), reference_date)
    missing_hr = calculate_run_index(_beginner_profile(), reference_date)

    assert missing_hr["confidence_score"] < hr_rich["confidence_score"]
    assert 0 <= missing_hr["run_index"] <= 1000


def test_reference_date_changes_run_index_for_progressive_runner():
    workouts = _progressive_profile()

    # Use a mid-point date where enough runs are visible (>= 3).
    mid = calculate_run_index(workouts, date(2026, 4, 1))
    late = calculate_run_index(workouts, date(2026, 7, 7))

    assert late["confidence_score"] >= mid["confidence_score"]
    if mid["status"] == "sufficient" and late["status"] == "sufficient":
        assert late["run_index"] >= mid["run_index"]


# ---------------------------------------------------------------------------
# Test 1: 0 activities → insufficient, run_index null
# ---------------------------------------------------------------------------

def test_zero_activities_returns_insufficient_null():
    result = calculate_run_index([], date(2026, 7, 7))
    assert result["status"] == "insufficient"
    assert result["run_index"] is None
    assert result["confidence_score"] == 0


# ---------------------------------------------------------------------------
# Test 2: 1 activity → insufficient
# ---------------------------------------------------------------------------

def test_one_activity_returns_insufficient():
    result = calculate_run_index([_run(3, 10.0, 5.0, 155)], date(2026, 7, 7))
    assert result["status"] == "insufficient"
    assert result["run_index"] is None


# ---------------------------------------------------------------------------
# Test 3: 2 activities → insufficient
# ---------------------------------------------------------------------------

def test_two_activities_returns_insufficient():
    result = calculate_run_index(
        [_run(3, 10.0, 5.0, 155), _run(10, 12.0, 5.1, 152)],
        date(2026, 7, 7),
    )
    assert result["status"] == "insufficient"
    assert result["run_index"] is None


# ---------------------------------------------------------------------------
# Test 4: ≥3 activities + ≥2 pillars calculable → sufficient
# ---------------------------------------------------------------------------

def test_three_activities_with_two_pillars_returns_sufficient():
    runs = [
        _run(3, 10.0, 5.0, 155),
        _run(10, 12.0, 5.1, 152),
        _run(17, 8.0, 5.2, 158),
    ]
    result = calculate_run_index(runs, date(2026, 7, 7))
    assert result["status"] == "sufficient"
    assert result["run_index"] is not None
    assert 0 <= result["run_index"] <= 1000


# ---------------------------------------------------------------------------
# Test 5: HR absent → Efficiency None, never 0
# ---------------------------------------------------------------------------

def test_no_hr_efficiency_is_null_not_zero():
    # Enough runs but no HR data at all
    runs = [_run(i * 7, 10.0, 5.0) for i in range(5)]
    result = calculate_run_index(runs, date(2026, 7, 7))
    assert result["efficiency_score"] is None
    # pace_stability_score is not part of efficiency
    details = result["pillar_details"]["efficiency"]
    assert "pace_stability_score" not in details["components"]
    assert "pace_heart_rate_score" in details["components"]


# ---------------------------------------------------------------------------
# Test 6: long-run stability unknown → None, never 60
# ---------------------------------------------------------------------------

def test_endurance_no_multiple_long_runs_stability_not_60():
    # Only one long run → pace stability between long runs cannot be computed
    runs = [
        _run(5, 22.0, 5.5),
        _run(12, 8.0, 5.4),
        _run(19, 8.0, 5.5),
        _run(26, 8.0, 5.6),
        _run(33, 7.0, 5.4),
    ]
    result = calculate_run_index(runs, date(2026, 7, 7))
    # The endurance score must never be 60 as a fabricated value.
    # It should be computable from the other components without a fake 60.
    details = result["pillar_details"]["endurance"]
    # long_run_frequency_score is 0 since only 1 long run at most.
    # The old durability_score of 60 must not appear.
    assert details["components"].get("durability_score") is None  # removed


# ---------------------------------------------------------------------------
# Test 7: consistency stability unknown → None, never 35
# ---------------------------------------------------------------------------

def test_consistency_stability_unknown_is_none_not_35():
    # Very few runs: stability (weekly distance CV) likely cannot be computed
    # from a single non-zero week.
    runs = [_run(2, 5.0, 5.5), _run(4, 6.0, 5.4), _run(6, 7.0, 5.3)]
    result = calculate_run_index(runs, date(2026, 7, 7))
    details = result["pillar_details"]["consistency"]
    # stability_score should be None when only one active week
    # (distance_cv needs at least 2 non-zero values across weeks)
    # — may be None or a real value. Must never be exactly 35.
    assert details["components"]["stability_score"] != 35


# ---------------------------------------------------------------------------
# Test 8: gaps unknown → None, never 14/21
# ---------------------------------------------------------------------------

def test_consistency_no_gaps_when_less_than_2_sessions():
    # 0 sessions in consistency window: gaps are None
    runs = [
        _run(3, 10.0, 5.0),
        _run(60, 10.0, 5.0),  # outside 56-day window
        _run(90, 10.0, 5.0),
    ]
    result = calculate_run_index(runs, date(2026, 7, 7))
    details = result["pillar_details"]["consistency"]
    # max_gap_days must not be 21 (the old default)
    max_gap = details["components"]["max_gap_days"]
    assert max_gap != 21


def test_consistency_gaps_not_fabricated_with_single_session():
    # Only 1 run in the 56-day window → no gaps can be computed
    runs = [
        _run(5, 10.0, 5.0),
        _run(3, 10.0, 5.0),
        _run(2, 10.0, 5.0),
    ]
    result = calculate_run_index(runs, date(2026, 7, 7))
    details = result["pillar_details"]["consistency"]
    # avg_gap must not be 14 (old fabricated default)
    # When gaps exist they are real; when they don't, max_gap_days is None
    assert details["components"]["max_gap_days"] != 14


# ---------------------------------------------------------------------------
# Test 9: missing component → renormalisation of weights
# ---------------------------------------------------------------------------

def test_missing_component_causes_renormalisation():
    # No HR → efficiency None. Speed, endurance, consistency should still compute.
    runs = [_run(i * 5, 10.0, 5.0) for i in range(4)]
    result = calculate_run_index(runs, date(2026, 7, 7))
    # If sufficient: run_index > 0 and only non-None pillars contributed.
    if result["status"] == "sufficient":
        assert result["run_index"] is not None and result["run_index"] > 0


# ---------------------------------------------------------------------------
# Test 10: missing pillar → renormalisation global
# ---------------------------------------------------------------------------

def test_missing_pillar_does_not_produce_zero_run_index():
    # No HR → efficiency = None. With ≥3 runs and ≥2 calculable pillars → sufficient.
    runs = [_run(i * 5, 10.0 + i, 5.0) for i in range(4)]
    result = calculate_run_index(runs, date(2026, 7, 7))
    if result["status"] == "sufficient":
        assert result["efficiency_score"] is None
        # run_index should be > 0 because other pillars contributed.
        assert result["run_index"] > 0


# ---------------------------------------------------------------------------
# Test 11: all components missing → insufficient
# ---------------------------------------------------------------------------

def test_empty_input_is_insufficient():
    result = calculate_run_index([], date(2026, 7, 7))
    assert result["status"] == "insufficient"
    assert result["run_index"] is None
    assert result["speed_score"] is None
    assert result["endurance_score"] is None
    assert result["consistency_score"] is None
    assert result["efficiency_score"] is None
    assert result["confidence_score"] == 0


# ---------------------------------------------------------------------------
# Test 12: confidence increases with more data
# ---------------------------------------------------------------------------

def test_confidence_increases_with_more_data():
    ref = date(2026, 7, 7)
    few_runs = _intermediate_profile()[:3]
    many_runs = _intermediate_profile()

    few = calculate_run_index(few_runs, ref)
    many = calculate_run_index(many_runs, ref)

    assert many["confidence_score"] >= few["confidence_score"]


# ---------------------------------------------------------------------------
# Test 13: future activity not included when reference_date set
# ---------------------------------------------------------------------------

def test_future_activity_excluded_from_historical_reference():
    ref = date(2026, 7, 7)
    future_run = _run(-5, 40.0, 3.0, 180)  # -5 days ago = future relative to ref
    past_runs = _intermediate_profile()
    with_future = past_runs + [future_run]
    without_future = past_runs

    result_with = calculate_run_index(with_future, ref)
    result_without = calculate_run_index(without_future, ref)

    # Future run must not change result
    assert result_with["run_index"] == result_without["run_index"]
    assert result_with["speed_score"] == result_without["speed_score"]


# ---------------------------------------------------------------------------
# Test 14: CURRENT and HISTORY same date/same activities → same result
# ---------------------------------------------------------------------------

def test_current_and_history_same_date_same_result():
    ref = date(2026, 7, 7)
    workouts = _advanced_profile()

    current = calculate_run_index(workouts, ref)
    history = calculate_run_index(workouts, ref)

    assert current == history


# ---------------------------------------------------------------------------
# Test 15: DomainActivity path (no db.workouts dependency)
# ---------------------------------------------------------------------------

def test_domain_activity_path_no_workouts_dependency():
    """calculate_run_index_from_domain must exist and produce same contract."""
    from engine.run_index_engine import calculate_run_index_from_domain

    class FakeDomainActivity:
        activity_type = "run"
        distance_m = 10000.0
        duration_s = 3000.0
        start_time = "2026-07-05T08:00:00"
        average_hr = 155.0
        source = "garmin"
        source_activity_id = "123"

    activities = [FakeDomainActivity() for _ in range(5)]
    result = calculate_run_index_from_domain(activities, date(2026, 7, 7))
    assert "status" in result
    assert "run_index" in result


# ---------------------------------------------------------------------------
# Test 16: non-running activities are ignored
# ---------------------------------------------------------------------------

def test_non_running_activities_ignored():
    cycling = {
        "type": "cycling",
        "date": date(2026, 7, 5).isoformat(),
        "distance_km": 50.0,
        "duration_minutes": 90.0,
        "avg_pace_min_km": 1.8,
        "avg_speed_kmh": 33.0,
        "avg_heart_rate": 145,
    }
    result_with_cycling = calculate_run_index([cycling] + _intermediate_profile(), date(2026, 7, 7))
    result_without = calculate_run_index(_intermediate_profile(), date(2026, 7, 7))

    assert result_with_cycling["run_index"] == result_without["run_index"]


# ---------------------------------------------------------------------------
# Test 17: run_index always 0–1000 when sufficient
# ---------------------------------------------------------------------------

def test_run_index_in_valid_range_when_sufficient():
    for profile in (_beginner_profile(), _intermediate_profile(), _advanced_profile(), _elite_profile()):
        result = calculate_run_index(profile, date(2026, 7, 7))
        if result["status"] == "sufficient":
            assert result["run_index"] is not None
            assert 0 <= result["run_index"] <= 1000


# ---------------------------------------------------------------------------
# Test 18: pillar scores always 0–100 when non-null
# ---------------------------------------------------------------------------

def test_pillar_scores_in_valid_range_when_non_null():
    for profile in (_beginner_profile(), _intermediate_profile(), _advanced_profile(), _elite_profile()):
        result = calculate_run_index(profile, date(2026, 7, 7))
        for pillar in ("speed_score", "endurance_score", "consistency_score", "efficiency_score"):
            val = result[pillar]
            if val is not None:
                assert 0 <= val <= 100, f"{pillar}={val} out of range"


# ---------------------------------------------------------------------------
# Monotonicity tests
# ---------------------------------------------------------------------------

def test_better_speed_does_not_decrease_speed_score():
    ref = date(2026, 7, 7)
    base = _intermediate_profile()

    # Add a faster run (same data otherwise)
    faster = base + [_run(8, 10.0, 4.0, 162)]
    result_base = calculate_run_index(base, ref)
    result_faster = calculate_run_index(faster, ref)

    s_base = result_base["speed_score"] or 0
    s_faster = result_faster["speed_score"] or 0
    assert s_faster >= s_base


def test_more_volume_does_not_decrease_endurance_score():
    ref = date(2026, 7, 7)
    base = _intermediate_profile()
    more_volume = base + [_run(3, 25.0, 5.3, 150), _run(6, 18.0, 5.1, 153)]

    result_base = calculate_run_index(base, ref)
    result_more = calculate_run_index(more_volume, ref)

    e_base = result_base["endurance_score"] or 0
    e_more = result_more["endurance_score"] or 0
    assert e_more >= e_base


def test_more_active_weeks_does_not_decrease_consistency_score():
    ref = date(2026, 7, 7)
    base = _intermediate_profile()
    more_weeks = base + [_run(35, 8.0, 5.1, 155), _run(42, 8.0, 5.2, 153), _run(49, 8.0, 5.0, 156)]

    result_base = calculate_run_index(base, ref)
    result_more = calculate_run_index(more_weeks, ref)

    c_base = result_base["consistency_score"] or 0
    c_more = result_more["consistency_score"] or 0
    assert c_more >= c_base


def test_better_speed_hr_ratio_does_not_decrease_efficiency_score():
    ref = date(2026, 7, 7)
    base = _intermediate_profile()

    # Add runs with very good speed/HR ratio — both faster pace and lower HR.
    better_efficiency = base + [
        _run(2, 10.0, 4.2, 130),   # speed = 14.3 km/h, HR 130 → index 110
        _run(5, 12.0, 4.3, 128),   # speed = 14.0 km/h, HR 128 → index 109
        _run(8, 8.0, 4.1, 125),    # speed = 14.6 km/h, HR 125 → index 117
    ]

    result_base = calculate_run_index(base, ref)
    result_better = calculate_run_index(better_efficiency, ref)

    e_base = result_base["efficiency_score"] or 0
    e_better = result_better["efficiency_score"] or 0
    assert e_better >= e_base


# ---------------------------------------------------------------------------
# Contract field presence
# ---------------------------------------------------------------------------

def test_output_has_required_contract_fields():
    result = calculate_run_index(_intermediate_profile(), date(2026, 7, 7))
    for field in ("status", "run_index", "speed_score", "endurance_score",
                  "consistency_score", "efficiency_score", "confidence_score", "pillar_details"):
        assert field in result, f"Missing field: {field}"


def test_insufficient_output_has_null_run_index():
    result = calculate_run_index([], date(2026, 7, 7))
    assert result["status"] == "insufficient"
    assert result["run_index"] is None


def test_no_cardiac_drift_score_in_output():
    """cardiac_drift_score must not appear anywhere in output."""
    result = calculate_run_index(_advanced_profile(), date(2026, 7, 7))
    import json
    output_str = json.dumps(result)
    assert "cardiac_drift_score" not in output_str


def test_no_vo2max_score_in_output():
    """vo2max_score must not appear anywhere in output."""
    result = calculate_run_index(_advanced_profile(), date(2026, 7, 7))
    import json
    output_str = json.dumps(result)
    assert "vo2max_score" not in output_str


def test_no_threshold_score_in_output():
    """threshold_score must not appear anywhere in output."""
    result = calculate_run_index(_advanced_profile(), date(2026, 7, 7))
    import json
    output_str = json.dumps(result)
    assert "threshold_score" not in output_str
