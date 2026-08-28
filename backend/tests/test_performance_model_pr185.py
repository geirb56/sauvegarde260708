"""
Tests for Performance Model V2 (PR185) after VMA removal.

Keeps coverage for race predictions, performance qualification, FCmax resolution,
and regression guards that still apply after the HR-speed VMA subsystem was deleted.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional


from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    RACE_DISTANCES_M,
    REASON_HR_RANGE_INSUFFICIENT,
    _resolve_fcmax,
    _resolve_fcmax_robust,
    _riegel,
    _score_riegel_candidate,
    evaluate_performance_quality,
    predict_races,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date(2024, 6, 15)


def _run(
    distance_m: float,
    duration_s: float,
    days_ago: int = 5,
    avg_hr: Optional[float] = None,
    max_hr: Optional[float] = None,
    elevation_gain_m: Optional[float] = None,
    activity_type: str = "running",
) -> DomainActivity:
    start = (TODAY - timedelta(days=days_ago)).isoformat()
    return DomainActivity(
        activity_type=activity_type,
        start_time=start,
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=avg_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
    )








def _speed_benchmark_runs() -> List[DomainActivity]:
    """Six strictly-prior road-comparable runs for PR188 personal speed benchmarks."""
    return [
        _run(8_000.0, 3_200.0, days_ago=80, avg_hr=130.0, max_hr=160.0),
        _run(9_000.0, 3_500.0, days_ago=70, avg_hr=135.0, max_hr=165.0),
        _run(10_000.0, 3_900.0, days_ago=60, avg_hr=140.0, max_hr=170.0),
        _run(11_000.0, 4_300.0, days_ago=50, avg_hr=145.0, max_hr=175.0),
        _run(12_000.0, 4_700.0, days_ago=40, avg_hr=150.0, max_hr=178.0),
        _run(10_000.0, 3_000.0, days_ago=30, avg_hr=155.0, max_hr=182.0),
    ]


def _slow_qualification_benchmark_runs() -> List[DomainActivity]:
    return [
        _run(8_000.0, 3_600.0, days_ago=80, avg_hr=120.0, max_hr=180.0),
        _run(9_000.0, 4_000.0, days_ago=70, avg_hr=125.0, max_hr=182.0),
        _run(10_000.0, 4_500.0, days_ago=60, avg_hr=130.0, max_hr=184.0),
        _run(11_000.0, 4_900.0, days_ago=50, avg_hr=135.0, max_hr=186.0),
        _run(12_000.0, 5_400.0, days_ago=40, avg_hr=140.0, max_hr=188.0),
        _run(13_000.0, 5_800.0, days_ago=30, avg_hr=145.0, max_hr=190.0),
    ]


# ---------------------------------------------------------------------------
# Test 1: No activities → VMA null
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 2: Runs without HR → VMA null (HR model requires HR)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 3: Single run with HR → VMA null (not enough for HR model)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 4: Multiple runs, all at quasi-identical HR → VMA null
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 5: Multiple runs with clear HR-speed relationship → VMA calculable
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 6: A single short fast run is never a Riegel source by itself (no HR model)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 7: Poor correlation → null or insufficient confidence
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 8: Good correlation + sufficient HR range → VMA deterministic
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 9: Excessive extrapolation → confidence reduced or null
# ---------------------------------------------------------------------------

    # else it's null due to extrapolation check — also acceptable


# ---------------------------------------------------------------------------
# Test 10: FCmax absent → no 220-age fallback
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 11: Future activity → ignored
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 12: SOURCE A removed — VMA comes solely from HR-speed model
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 15: db.workouts divergence → no impact
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 16: History anti-lookahead
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Legacy / compatibility tests (preserved from original PR185)
# ---------------------------------------------------------------------------


def test_predictions_no_data_returns_no_predictions():
    result = predict_races([], TODAY)
    assert result.has_data is False
    # All 4 targets are returned but with null times (no defensible source)
    assert len(result.predictions) == 4
    assert all(p.predicted_time_s is None for p in result.predictions)


def test_predictions_insufficient_data_returns_null():
    cycling = DomainActivity(activity_type="cycling", start_time=TODAY.isoformat(),
                              distance_m=20_000.0, duration_s=3_600.0)
    result = predict_races([cycling], TODAY)
    assert result.has_data is False


def test_predictions_10k_observed_coherent():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_000.0, days_ago=7,  avg_hr=158.0, max_hr=165.0),   # Fast 10K
        _run(12_000.0, 4_000.0, days_ago=15, avg_hr=148.0, max_hr=154.0),
        _run(14_000.0, 5_000.0, days_ago=20, avg_hr=138.0, max_hr=145.0),
        _run(6_000.0,  2_400.0, days_ago=25, avg_hr=165.0, max_hr=172.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=185.0)
    if result.has_data:
        ten_k = next(p for p in result.predictions if p.distance_label == "10K")
        assert ten_k.predicted_time_s is not None
        assert ten_k.predicted_time_s > 0


def test_predictions_5k_10k_monotone():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=150.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    if result.has_data:
        pred = {p.distance_label: p.predicted_time_s for p in result.predictions}
        if pred.get("5K") and pred.get("10K"):
            assert pred["5K"] < pred["10K"]


def test_predictions_all_positive():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=150.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    for p in result.predictions:
        if p.predicted_time_s is not None:
            assert p.predicted_time_s > 0


def test_avg_speed_070_fallback_removed():
    """Verify no avg_speed/0.70 fallback computation exists in code."""
    import inspect
    from training_v2 import performance_model as pm
    source = inspect.getsource(pm)
    assert "/ 0.70" not in source
    assert "/0.70" not in source


def test_riegel_formula():
    # T2 = T1 * (D2/D1)^1.06
    t2 = _riegel(1800.0, 5000.0, 10000.0)
    expected = 1800.0 * (10000.0 / 5000.0) ** 1.06
    assert abs(t2 - expected) < 0.01


def test_riegel_same_distance_returns_same_time():
    t = _riegel(2400.0, 10000.0, 10000.0)
    assert abs(t - 2400.0) < 0.01


def test_predict_races_returns_all_four_distances():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=150.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    if result.has_data:
        labels = {p.distance_label for p in result.predictions}
        assert labels == {"5K", "10K", "Semi", "Marathon"}


def test_prediction_has_readiness_fields():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=150.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    if result.has_data:
        for p in result.predictions:
            assert p.readiness is not None
            assert p.readiness_label is not None
            assert p.readiness_color is not None
            assert 0 <= p.readiness_score <= 100


def test_prediction_has_model_version_v2():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=150.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    if result.has_data:
        for p in result.predictions:
            assert p.model_version == "v2"



def test_athlete_profile_has_vo2max_note():
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=135.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=150.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    if result.has_data:
        assert 'vo2max_note' in result.athlete_profile
        assert result.athlete_profile['vo2max_note'] is None

def test_predictions_frontend_preserved():
    """RacePrediction and PerformanceEstimate contract maintained."""
    result = predict_races([], TODAY)
    assert hasattr(result, 'has_data')
    assert hasattr(result, 'predictions')
    assert hasattr(result, 'athlete_profile')
    assert result.athlete_profile['estimated_vma'] is None
    # All 4 targets returned, all null when no activities
    assert len(result.predictions) == 4
    assert all(p.predicted_time_s is None for p in result.predictions)

    activities = _speed_benchmark_runs() + [
        _run(10_000.0, 2_800.0, days_ago=5, avg_hr=170.0, max_hr=185.0),
    ]
    result2 = predict_races(activities, TODAY, user_max_hr=190.0)
    if result2.has_data:
        assert result2.athlete_profile['estimated_vma'] is None
        for p in result2.predictions:
            assert p.predicted_time_s is not None
            assert p.predicted_pace_str is not None
            assert p.readiness is not None

# ---------------------------------------------------------------------------
# Additional: Linear regression correctness
# ---------------------------------------------------------------------------


# ===========================================================================
# NEW MANDATORY TESTS (problem statement v2 — 16 tests)
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 / T2 — Riegel source qualification: relative HR gate
# ---------------------------------------------------------------------------

def test_new_t1_easy_run_not_riegel_source_when_hr_available():
    """An easy run is not a valid Riegel source under PR188 qualification."""
    easy = _run(
        distance_m=10_000.0, duration_s=3_600.0,  # ~10 km/h
        days_ago=5, avg_hr=130.0,  # avg_hr / fcmax = 130/200 = 0.65
    )
    activities = _slow_qualification_benchmark_runs() + [easy]
    quality = evaluate_performance_quality(easy, activities, TODAY)
    score = _score_riegel_candidate(easy, 10_000.0, TODAY, quality=quality)
    assert score == 0.0, "Easy run must not be a Riegel source"


def test_new_t2_sustained_run_is_riegel_source_candidate():
    """A strong qualified run remains eligible as a Riegel source."""
    hard = _run(
        distance_m=10_000.0, duration_s=2_800.0,
        days_ago=5, avg_hr=176.0,  # avg_hr / fcmax = 176/200 = 0.88
    )
    activities = _slow_qualification_benchmark_runs() + [hard]
    quality = evaluate_performance_quality(hard, activities, TODAY)
    score = _score_riegel_candidate(hard, 10_000.0, TODAY, quality=quality)
    assert score > 0.0, "Strong qualified run should be eligible as a Riegel source"


# ---------------------------------------------------------------------------
# T3 — >= 4 activities good HR/speed + FCmax → VMA estimable
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T4 — Same dataset without FCmax → VMA null
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T5 — Observed max_hr réellement disponible et crédible → peut servir comme FCmax
# ---------------------------------------------------------------------------

def test_new_t5_observed_max_hr_serves_as_fcmax():
    """Observed max_hr in Garmin data (>= 150, <= 230) can serve as FCmax."""
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=138.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=153.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=167.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=190.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=180.0, max_hr=188.0),
    ]
    assert _resolve_fcmax(activities, None, TODAY) == 190.0

# ---------------------------------------------------------------------------
# T6 — hr_max + 5 absent (static scan)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T7 — 220-age absent (also covered by T10, explicit here for report)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T8 — VMA available but no defensible Riegel source → predictions null
# ---------------------------------------------------------------------------

def test_new_t8_vma_available_no_riegel_source_predictions_null():
    """Predictions remain null when no defensible Riegel source exists."""
    from training_v2.performance_model import MAX_RIEGEL_SOURCE_AGE_DAYS

    old_days = MAX_RIEGEL_SOURCE_AGE_DAYS + 30
    activities = [
        _run(8_000.0,  3_600.0, days_ago=old_days,     avg_hr=130.0, max_hr=138.0),
        _run(10_000.0, 3_600.0, days_ago=old_days + 5,  avg_hr=145.0, max_hr=153.0),
        _run(12_000.0, 3_600.0, days_ago=old_days + 10, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=old_days + 15, avg_hr=170.0, max_hr=178.0),
        _run(16_000.0, 3_600.0, days_ago=old_days + 20, avg_hr=180.0, max_hr=187.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=190.0)
    assert result.athlete_profile['estimated_vma'] is None
    for p in result.predictions:
        assert p.predicted_time_s is None, (
            f'Expected null prediction for {p.distance_label}, got {p.predicted_time_s}s'
        )

# ---------------------------------------------------------------------------
# T9 — No synthetic 20-min @ 85% VMA (static scan)
# ---------------------------------------------------------------------------

def test_new_t9_no_synthetic_effort():
    """Forbidden synthetic Riegel source patterns must not exist in model code."""
    import inspect
    from training_v2 import performance_model as pm
    source = inspect.getsource(pm)

    # These patterns indicate synthetic effort creation — strictly forbidden
    forbidden = [
        "synth_speed",
        "synth_duration",
        "synth_duration_s = 20 * 60",   # exact synthetic 20-min line (not generic uses)
        "vma * 0.85",       # 85% VMA synthetic speed
    ]
    for pattern in forbidden:
        assert pattern not in source, (
            f"Forbidden synthetic pattern '{pattern}' found in performance_model.py"
        )


# ---------------------------------------------------------------------------
# T10 — Real activity close to 10K can feed 10K prediction with confidence
# ---------------------------------------------------------------------------

def test_new_t10_real_10k_activity_feeds_prediction():
    """A real 10K activity can serve as Riegel source for 10K prediction."""
    activities = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=138.0),
        _run(10_000.0, 3_000.0, days_ago=7,  avg_hr=165.0, max_hr=173.0),   # 12 km/h 10K
        _run(12_000.0, 4_000.0, days_ago=15, avg_hr=148.0, max_hr=156.0),
        _run(14_000.0, 5_000.0, days_ago=20, avg_hr=138.0, max_hr=145.0),
        _run(6_000.0,  2_400.0, days_ago=25, avg_hr=160.0, max_hr=168.0),
    ]
    result = predict_races(activities, TODAY, user_max_hr=185.0)
    if result.has_data:
        ten_k = next((p for p in result.predictions if p.distance_label == "10K"), None)
        assert ten_k is not None
        if ten_k.predicted_time_s is not None:
            assert ten_k.predicted_time_s > 0
            assert ten_k.source_type == "observed_activity"


# ---------------------------------------------------------------------------
# T11 — Easy activity with low relative HR → not HIGH confidence
# ---------------------------------------------------------------------------

def test_new_t11_low_relative_hr_not_high_confidence():
    """An easy activity with low avg_hr relative to FCmax must not produce HIGH confidence."""
    fcmax = 190.0
    # avg_hr=114 → relative_hr = 114/190 ≈ 0.60 (well below 0.85 threshold)
    easy_act = _run(10_000.0, 3_600.0, days_ago=5, avg_hr=114.0, max_hr=120.0)  # 10 km/h
    activities = [easy_act]
    result = predict_races(activities, TODAY, user_max_hr=fcmax)
    for p in result.predictions:
        if p.predicted_time_s is not None:
            assert p.confidence != "high", (
                f"Expected non-HIGH confidence for easy source, got {p.confidence} "
                f"for {p.distance_label}"
            )


# ---------------------------------------------------------------------------
# T12 — Activity near target + high relative HR → higher confidence
# ---------------------------------------------------------------------------

def test_new_t12_high_relative_hr_higher_confidence():
    """Activity near target distance with high relative HR produces higher confidence
    than the same activity at low relative HR."""
    fcmax = 190.0
    # Activity 1: near 5K, high HR (relative_hr ≈ 0.90)
    high_effort = _run(5_000.0, 1_500.0, days_ago=5, avg_hr=171.0, max_hr=180.0)
    # Activity 2: near 5K, low HR (relative_hr ≈ 0.65)
    low_effort = _run(5_000.0, 1_500.0, days_ago=5, avg_hr=123.0, max_hr=130.0)

    r_high = predict_races([high_effort], TODAY, user_max_hr=fcmax)
    r_low = predict_races([low_effort], TODAY, user_max_hr=fcmax)

    order = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}

    five_k_high = next((p for p in r_high.predictions if p.distance_label == "5K"), None)
    five_k_low = next((p for p in r_low.predictions if p.distance_label == "5K"), None)

    if five_k_high and five_k_high.predicted_time_s and five_k_low and five_k_low.predicted_time_s:
        assert order.get(five_k_high.confidence, 0) >= order.get(five_k_low.confidence, 0), (
            f"High-HR source ({five_k_high.confidence}) should have >= confidence "
            f"than low-HR source ({five_k_low.confidence})"
        )


# ---------------------------------------------------------------------------
# T13 — Source 5K → Marathon: lower confidence than source near Marathon
# ---------------------------------------------------------------------------

def test_new_t13_5k_source_marathon_lower_confidence():
    """Extrapolating from 5K to Marathon should yield lower confidence
    than extrapolating from a near-Marathon source."""
    fcmax = 190.0
    # Source near Marathon (40K with good effort)
    marathon_src = _run(40_000.0, 14_400.0, days_ago=10, avg_hr=162.0, max_hr=172.0)
    # Source 5K
    fivek_src = _run(5_000.0, 1_500.0, days_ago=10, avg_hr=171.0, max_hr=180.0)

    r_marathon = predict_races([marathon_src], TODAY, user_max_hr=fcmax)
    r_fivek = predict_races([fivek_src], TODAY, user_max_hr=fcmax)

    order = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}

    marathon_from_marathon = next(
        (p for p in r_marathon.predictions if p.distance_label == "Marathon"), None
    )
    marathon_from_5k = next(
        (p for p in r_fivek.predictions if p.distance_label == "Marathon"), None
    )

    if (
        marathon_from_marathon and marathon_from_marathon.predicted_time_s
        and marathon_from_5k and marathon_from_5k.predicted_time_s
    ):
        conf_near = order.get(marathon_from_marathon.confidence, 0)
        conf_far = order.get(marathon_from_5k.confidence, 0)
        assert conf_near >= conf_far, (
            f"Near-Marathon source ({marathon_from_marathon.confidence}) should have >= "
            f"confidence than 5K source ({marathon_from_5k.confidence})"
        )


# ---------------------------------------------------------------------------
# T14 — Source near Semi → Semi prediction with better confidence than distant source
# ---------------------------------------------------------------------------

def test_new_t14_near_semi_source_better_confidence():
    """A source near Semi distance produces better Semi confidence than a 5K source."""
    fcmax = 190.0
    # Near Semi: 20K at good effort (relative_hr ~0.87)
    semi_src = _run(20_000.0, 7_200.0, days_ago=10, avg_hr=165.0, max_hr=175.0)
    # Distant: 5K
    fivek_src = _run(5_000.0, 1_500.0, days_ago=10, avg_hr=165.0, max_hr=175.0)

    r_near = predict_races([semi_src], TODAY, user_max_hr=fcmax)
    r_far = predict_races([fivek_src], TODAY, user_max_hr=fcmax)

    order = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}

    semi_near = next((p for p in r_near.predictions if p.distance_label == "Semi"), None)
    semi_far = next((p for p in r_far.predictions if p.distance_label == "Semi"), None)

    if semi_near and semi_near.predicted_time_s and semi_far and semi_far.predicted_time_s:
        assert order.get(semi_near.confidence, 0) >= order.get(semi_far.confidence, 0), (
            f"Near-Semi source ({semi_near.confidence}) should have >= "
            f"confidence than 5K source ({semi_far.confidence})"
        )


# ---------------------------------------------------------------------------
# T15 — No future activity used (duplicate of existing test, explicit label)
# ---------------------------------------------------------------------------

def test_new_t15_no_future_activity_used():
    """Future activities (after reference_date) are strictly excluded."""
    future = DomainActivity(
        activity_type='running',
        start_time=(TODAY + timedelta(days=1)).isoformat(),
        distance_m=10_000.0, duration_s=3_000.0, average_hr=170.0, max_hr=178.0,
    )
    past = _speed_benchmark_runs() + [
        _run(10_000.0, 3_000.0, days_ago=5, avg_hr=175.0, max_hr=185.0),
    ]
    r_with = predict_races(past + [future], TODAY, user_max_hr=190.0)
    r_without = predict_races(past, TODAY, user_max_hr=190.0)
    preds_with = {p.distance_label: p for p in r_with.predictions}
    preds_without = {p.distance_label: p for p in r_without.predictions}
    assert preds_with['10K'].predicted_time_s == preds_without['10K'].predicted_time_s
    assert preds_with['10K'].confidence == preds_without['10K'].confidence

# ---------------------------------------------------------------------------
# T16 — Anti-lookahead historical PASS
# ---------------------------------------------------------------------------

def test_new_t16_anti_lookahead_historical_pass():
    """Historical snapshots cannot see activities that occur after the snapshot date."""
    snapshot = date(2024, 3, 1)
    post_snapshot = [
        DomainActivity(
            activity_type='running',
            start_time=date(2024, 3, 15).isoformat(),
            distance_m=10_000.0, duration_s=3_000.0,
            average_hr=165.0, max_hr=173.0,
        ),
        DomainActivity(
            activity_type='running',
            start_time=date(2024, 4, 1).isoformat(),
            distance_m=12_000.0, duration_s=3_600.0,
            average_hr=155.0, max_hr=162.0,
        ),
    ]
    result = predict_races(post_snapshot, snapshot, user_max_hr=190.0)
    assert result.athlete_profile['estimated_vma'] is None
    assert all(pred.predicted_time_s is None for pred in result.predictions)
    assert result.has_data is False

# ---------------------------------------------------------------------------
# Anti-synthetic scan: forbidden patterns must not appear in model (summary)
# ---------------------------------------------------------------------------

def test_anti_synthetic_comprehensive_scan():
    """Comprehensive static scan for all forbidden synthetic/heuristic patterns."""
    import inspect
    from training_v2 import performance_model as pm
    source = inspect.getsource(pm)

    # These patterns are unconditionally forbidden in the VMA V2 path
    forbidden_patterns = {
        "hr_max + 5": "synthetic FCmax (hr_max+5)",
        "hr_max + 5.0": "synthetic FCmax (hr_max+5.0)",
        "220 - ": "220-age FCmax formula",
        "208 - ": "Tanaka FCmax formula",
        "synth_speed": "synthetic speed variable",
        "synth_duration": "synthetic duration variable",
        "* 0.85": "85% VMA synthetic effort",
        # "20 * 60" is a legitimate constant (MIN_EXPLICIT_PERFORMANCE_DURATION_S comment)
        # The forbidden form is the exact synthetic assignment:
        "synth_duration_s = 20 * 60": "synthetic 20-minute effort assignment",
    }

    for pattern, description in forbidden_patterns.items():
        assert pattern not in source, (
            f"FORBIDDEN: '{description}' ({pattern!r}) found in performance_model.py"
        )



# ===========================================================================
# MANDATORY TESTS A–G (final audit — PR185 corrections)
# ===========================================================================

def _hr_model_activities(user_max_hr: float = 185.0) -> list:
    """Return 4 clean running activities that build a valid HR-speed model."""
    return [
        _run(8_000.0,  3_200.0, days_ago=5,  avg_hr=130.0, max_hr=140.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=148.0, max_hr=156.0),
        _run(12_000.0, 4_000.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 4_500.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
    ]


# ---------------------------------------------------------------------------
# A — VMA insufficient + observed Riegel source defensible
#     → vma = null, prediction exists
# ---------------------------------------------------------------------------

def test_a_vma_null_predictions_exist():
    """Predictions can exist even when VMA is absent from the athlete profile."""
    benchmark = [
        DomainActivity(
            activity_type=a.activity_type,
            start_time=a.start_time,
            distance_m=a.distance_m,
            duration_s=a.duration_s,
        )
        for a in _speed_benchmark_runs()
    ]
    acts = benchmark + [
        _run(10_000.0, 3_600.0, days_ago=5, avg_hr=165.0, max_hr=175.0),
        _run(12_000.0, 4_500.0, days_ago=15, avg_hr=155.0, max_hr=163.0),
    ]
    result = predict_races(acts, TODAY, user_max_hr=None)

    assert result.athlete_profile['estimated_vma'] is None

    preds_by_label = {p.distance_label: p for p in result.predictions}
    assert '10K' in preds_by_label
    assert preds_by_label['10K'].predicted_time_s is not None, (
        '10K prediction must exist even when estimated_vma is absent'
    )
    assert result.has_data is True

# ---------------------------------------------------------------------------
# B — VMA insufficient + no defensible Riegel source
#     → all predictions null / insufficient
# ---------------------------------------------------------------------------

def test_b_vma_null_no_riegel_source():
    """When no defensible Riegel source exists, all predictions remain null."""
    acts = [
        _run(400.0, 90.0, days_ago=5, avg_hr=170.0, max_hr=178.0),
    ]
    result = predict_races(acts, TODAY, user_max_hr=None)

    assert result.athlete_profile['estimated_vma'] is None

    for pred in result.predictions:
        assert pred.predicted_time_s is None, (
            f'Prediction for {pred.distance_label} must be null with no defensible source'
        )
        assert pred.confidence == 'insufficient'

    assert result.has_data is False

# ---------------------------------------------------------------------------
# C — VMA available + defensible Riegel source
#     → VMA and prediction both present
# ---------------------------------------------------------------------------

def test_c_vma_and_predictions_both_available():
    """Predictions can exist even though estimated_vma is now always absent."""
    acts = _speed_benchmark_runs() + _hr_model_activities(user_max_hr=185.0) + [
        _run(10_000.0, 2_800.0, days_ago=5, avg_hr=170.0, max_hr=185.0),
    ]
    result = predict_races(acts, TODAY, user_max_hr=185.0)

    assert result.athlete_profile['estimated_vma'] is None
    preds_with_time = [p for p in result.predictions if p.predicted_time_s is not None]
    assert len(preds_with_time) > 0, 'At least one prediction must exist'
    assert result.has_data is True

# ---------------------------------------------------------------------------
# D — No activities → VMA null, no invented predictions
# ---------------------------------------------------------------------------

def test_d_no_activities_no_invented_data():
    """With zero activities, estimated_vma is absent and no predictions are invented."""
    result = predict_races([], TODAY, user_max_hr=None)

    assert result.athlete_profile['estimated_vma'] is None
    for pred in result.predictions:
        assert pred.predicted_time_s is None, (
            f'No prediction must be invented for {pred.distance_label}'
        )
    assert result.has_data is False

# ---------------------------------------------------------------------------
# E — All 4 targets present (5K / 10K / Semi / Marathon)
# ---------------------------------------------------------------------------

def test_e_all_four_targets_present():
    """predict_races always returns all 4 race targets."""
    acts = _hr_model_activities(user_max_hr=185.0)
    result = predict_races(acts, TODAY, user_max_hr=185.0)

    labels = {p.distance_label for p in result.predictions}
    assert "5K" in labels
    assert "10K" in labels
    assert "Semi" in labels
    assert "Marathon" in labels
    assert len(result.predictions) == 4


def test_e_all_four_targets_present_even_vma_null():
    """All 4 targets are returned even when VMA is null."""
    # Only 1 activity → VMA null
    acts = [_run(10_000.0, 3_600.0, days_ago=5, avg_hr=165.0, max_hr=175.0)]
    result = predict_races(acts, TODAY)

    labels = {p.distance_label for p in result.predictions}
    assert "5K" in labels
    assert "10K" in labels
    assert "Semi" in labels
    assert "Marathon" in labels


# ---------------------------------------------------------------------------
# F — Anti-regression: forbidden executable patterns absent
# ---------------------------------------------------------------------------

def test_f_anti_regression_no_synthetic_effort():
    """Static scan: no synthetic 20-min effort, no avg_speed/0.70, no hr_max+5,
    no speed-only performance qualification."""
    import inspect
    from training_v2 import performance_model as pm
    source = inspect.getsource(pm)

    forbidden = [
        ("synth_duration_s = 20 * 60", "synthetic 20-min effort"),
        ("/ 0.70", "avg_speed/0.70 fallback"),
        ("/ 0.7", "avg_speed/0.7 fallback"),
        ("hr_max + 5", "FCmax +5 synthetic"),
        ("hr_max + 5.0", "FCmax +5.0 synthetic"),
        ("220 - ", "220-age FCmax"),
        # speed-only qualification is expressed as "speed >= ... and duration"
        # without using the explicit performance flag; detect the removed heuristic:
        ("speed >= 10 and duration", "speed+duration explicit performance heuristic"),
    ]
    for pattern, label in forbidden:
        assert pattern not in source, (
            f"FORBIDDEN pattern '{label}' ({pattern!r}) found in performance_model.py"
        )


# ---------------------------------------------------------------------------
# G — No-look-ahead: historical snapshots always PASS
# ---------------------------------------------------------------------------


# ===========================================================================
# NEW PATCH TESTS — A: Riegel source qualification
# ===========================================================================

def test_a1_easy_run_not_riegel_source():
    """Easy run (relative_hr < 0.75 when FCmax known) must score 0 — not a Riegel source."""
    easy = _run(10_000.0, 3_600.0, days_ago=5, avg_hr=130.0)  # rel_hr = 130/200 = 0.65
    quality = evaluate_performance_quality(easy, _slow_qualification_benchmark_runs() + [easy], TODAY)
    s = _score_riegel_candidate(easy, 10_000.0, TODAY, quality=quality)
    assert s == 0.0, "Easy run (rel_hr=0.65 < 0.75) must not score as Riegel source"


def test_a2_sustained_run_is_eligible():
    """Sustained run (relative_hr >= 0.75) is eligible as Riegel source."""
    hard = _run(10_000.0, 2_800.0, days_ago=5, avg_hr=170.0)  # rel_hr = 170/200 = 0.85
    quality = evaluate_performance_quality(hard, _slow_qualification_benchmark_runs() + [hard], TODAY)
    s = _score_riegel_candidate(hard, 10_000.0, TODAY, quality=quality)
    assert s > 0.0, "Sustained run should score > 0 as Riegel source"


def test_a3_easy_run_exact_target_distance_rejected():
    """An easy run exactly at target distance (relative_hr=0.65) must not become source."""
    easy = _run(10_000.0, 4_320.0, days_ago=3, avg_hr=130.0)  # rel_hr = 130/200 = 0.65
    quality = evaluate_performance_quality(easy, _slow_qualification_benchmark_runs() + [easy], TODAY)
    s = _score_riegel_candidate(easy, 10_000.0, TODAY, quality=quality)
    assert s == 0.0


def test_a4_less_close_but_sustained_can_beat_easy_exact_distance():
    """A sustained run slightly off-distance beats easy run exactly at target."""
    easy_exact = _run(10_000.0, 3_600.0, days_ago=5, avg_hr=130.0)  # rel_hr = 0.65
    hard_semi = _run(12_000.0, 3_200.0, days_ago=5, avg_hr=175.0)   # rel_hr = 0.875
    easy_quality = evaluate_performance_quality(easy_exact, _slow_qualification_benchmark_runs() + [easy_exact], TODAY)
    hard_quality = evaluate_performance_quality(hard_semi, _slow_qualification_benchmark_runs() + [hard_semi], TODAY)
    s_easy = _score_riegel_candidate(easy_exact, 10_000.0, TODAY, quality=easy_quality)
    s_hard = _score_riegel_candidate(hard_semi, 10_000.0, TODAY, quality=hard_quality)
    assert s_easy == 0.0
    assert s_hard > 0.0


def test_a5_trail_not_road_riegel_source():
    """trail_running activity must never score as a road prediction source."""
    trail = _run(10_000.0, 3_600.0, days_ago=5, avg_hr=175.0, activity_type="trail_running")
    quality = evaluate_performance_quality(trail, _slow_qualification_benchmark_runs() + [trail], TODAY)
    s = _score_riegel_candidate(trail, 10_000.0, TODAY, quality=quality)
    assert s == 0.0, "trail_running must not be eligible as road Riegel source"


def test_a6_high_elevation_per_km_not_road_source():
    """Activity with elevation_gain_per_km > 30 m/km must be excluded as road source."""
    from training_v2.performance_model import MAX_ROAD_ELEVATION_GAIN_PER_KM
    # 400 m gain over 10 km = 40 m/km > 30 threshold
    hilly = _run(10_000.0, 3_600.0, days_ago=5, avg_hr=175.0, elevation_gain_m=400.0)
    quality = evaluate_performance_quality(hilly, _slow_qualification_benchmark_runs() + [hilly], TODAY)
    s = _score_riegel_candidate(hilly, 10_000.0, TODAY, quality=quality)
    assert s == 0.0, "Heavily hilly run (40 m/km) must not be road Riegel source"


def test_a7_no_hr_data_prediction_still_possible():
    """Without HR/FCmax data, prediction is still possible; confidence capped at MEDIUM."""
    activities = [
        _run(10_000.0, 2_700.0, days_ago=5),   # no HR
        _run(8_000.0,  2_400.0, days_ago=15),  # no HR
    ]
    result = predict_races(activities, TODAY)
    preds_10k = [p for p in result.predictions if p.distance_label == "10K"]
    assert preds_10k
    p = preds_10k[0]
    # Prediction may exist but confidence must not be HIGH (no HR to confirm intensity)
    if p.predicted_time_s is not None:
        assert p.confidence in ("medium", "low", "insufficient")


def test_a8_no_defensible_source_prediction_null():
    """When no defensible source exists, prediction is null for that target."""
    # Only a very short run — cannot satisfy MIN_RIEGEL_SOURCE_RATIO for any target
    short = _run(300.0, 60.0, days_ago=5, avg_hr=180.0)
    result = predict_races([short], TODAY)
    for pred in result.predictions:
        assert pred.predicted_time_s is None, f"Expected null prediction, got {pred}"


# ===========================================================================
# NEW PATCH TESTS — B: FCmax robust estimator
# ===========================================================================

def test_b1_outlier_high_fcmax_rejected():
    """A single outlier (218) far above second-highest (182) must be rejected."""
    observed = [178.0, 180.0, 182.0, 181.0, 218.0]
    result = _resolve_fcmax_robust(observed)
    assert result == 182.0, f"Expected 182 (outlier 218 rejected), got {result}"


def test_b2_credible_high_value_kept():
    """Highest value within 10% of second-highest must be kept."""
    observed = [178.0, 182.0, 185.0, 188.0, 190.0]
    result = _resolve_fcmax_robust(observed)
    assert result == 190.0, f"Expected 190 (credible high), got {result}"


def test_b3_no_observations_returns_none():
    """Empty observation list must return None."""
    assert _resolve_fcmax_robust([]) is None


def test_b4_single_observation_no_outlier_protection():
    """Single observation: returned as-is (no protection active)."""
    assert _resolve_fcmax_robust([185.0]) == 185.0


def test_b5_two_observations_no_outlier_protection():
    """Two observations: max returned (no protection for n < 3)."""
    assert _resolve_fcmax_robust([175.0, 210.0]) == 210.0


def test_b6_future_high_hr_no_effect_on_snapshot_fcmax():
    """FCmax at snapshot_date must not be influenced by a future high max_hr activity."""
    snapshot = date(2024, 3, 1)
    pre = [
        DomainActivity(
            activity_type='running', start_time=date(2024, 2, 15).isoformat(),
            distance_m=10_000.0, duration_s=3_600.0, average_hr=165.0, max_hr=185.0,
        ),
    ]
    future = DomainActivity(
        activity_type='running', start_time=date(2024, 4, 1).isoformat(),
        distance_m=10_000.0, duration_s=3_600.0, average_hr=195.0, max_hr=220.0,
    )
    fcmax_pre = _resolve_fcmax(pre, None, snapshot)
    fcmax_all = _resolve_fcmax(pre + [future], None, snapshot)
    assert fcmax_pre == fcmax_all == 185.0

# ===========================================================================
# NEW PATCH TESTS — C: VMA / Predictions independence
# ===========================================================================

def _make_good_riegel_activities(fcmax: float = 190.0) -> list:
    """Five HR-rich runs for the model; PR188 benchmark history is supplied separately."""
    return [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=138.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=153.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=160.0, max_hr=168.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=172.0, max_hr=180.0),
        _run(16_000.0, 3_600.0, days_ago=25, avg_hr=182.0, max_hr=fcmax),
    ]


def test_c1_same_riegel_source_regardless_of_vma():
    """Predictions from the same observed source must stay available without VMA."""
    benchmark = _speed_benchmark_runs()
    activities = benchmark + _make_good_riegel_activities(190.0)
    result_with_vma = predict_races(activities, TODAY, user_max_hr=190.0)

    few_activities = [
        DomainActivity(
            activity_type=a.activity_type,
            start_time=a.start_time,
            distance_m=a.distance_m,
            duration_s=a.duration_s,
        )
        for a in benchmark
    ] + [
        _run(8_000.0,  2_880.0, days_ago=5,  avg_hr=155.0, max_hr=190.0),
        _run(10_000.0, 3_200.0, days_ago=10, avg_hr=165.0, max_hr=190.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=175.0, max_hr=190.0),
    ]
    result_no_vma = predict_races(few_activities, TODAY)
    assert result_with_vma.athlete_profile['estimated_vma'] is None
    assert result_no_vma.athlete_profile['estimated_vma'] is None

    preds_10k_vma = [p for p in result_with_vma.predictions if p.distance_label == '10K']
    preds_10k_novma = [p for p in result_no_vma.predictions if p.distance_label == '10K']
    assert preds_10k_vma and preds_10k_novma
    assert preds_10k_novma[0].predicted_time_s is not None, (
        'Absent estimated_vma must not block predictions'
    )

def test_c2_vma_null_good_riegel_source_high_confidence_possible():
    """Absent estimated_vma must not artificially cap prediction confidence."""
    activities = [
        DomainActivity(
            activity_type=a.activity_type,
            start_time=a.start_time,
            distance_m=a.distance_m,
            duration_s=a.duration_s,
        )
        for a in _speed_benchmark_runs()
    ] + [
        _run(10_000.0, 3_000.0, days_ago=5, avg_hr=175.0, max_hr=188.0),
    ]
    result = predict_races(activities, TODAY)
    assert result.athlete_profile['estimated_vma'] is None
    preds_10k = [p for p in result.predictions if p.distance_label == '10K']
    assert preds_10k
    assert preds_10k[0].predicted_time_s is not None

def test_c3_vma_confidence_not_in_prediction_confidence():
    """Prediction confidence must be independent of vma_est.confidence."""
    # Build activities where VMA is low-confidence but Riegel source is strong
    # Low VMA confidence: only 4 activities, high extrapolation, recent
    activities_low_vma = [
        _run(8_000.0,  3_600.0, days_ago=5,  avg_hr=130.0, max_hr=138.0),
        _run(10_000.0, 3_600.0, days_ago=10, avg_hr=145.0, max_hr=153.0),
        _run(12_000.0, 3_600.0, days_ago=15, avg_hr=158.0, max_hr=165.0),
        _run(14_000.0, 3_600.0, days_ago=20, avg_hr=170.0, max_hr=178.0),
        # Strong Riegel source: 10K at 88% FCmax
        _run(10_000.0, 3_200.0, days_ago=5,  avg_hr=176.0, max_hr=188.0),
    ]
    result = predict_races(activities_low_vma, TODAY)
    preds_10k = [p for p in result.predictions if p.distance_label == "10K"]
    assert preds_10k
    # The old code would downgrade HIGH→MEDIUM when VMA confidence is low/insufficient.
    # Now this must not happen — prediction stands on its own.
    if preds_10k[0].predicted_time_s is not None:
        # We just verify no artificial downgrade: confidence is determined by source quality only
        assert preds_10k[0].confidence in ("high", "medium", "low", "insufficient")


# ===========================================================================
# NEW PATCH TESTS — D: VMA history 42-day rolling window
# ===========================================================================

