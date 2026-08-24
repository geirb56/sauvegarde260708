from __future__ import annotations

from datetime import date
from typing import Optional

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    PERFORMANCE_MIN_RELATIVE_HR,
    PERFORMANCE_MIN_SPEED_PERCENTILE_WITH_HR,
    PERFORMANCE_SCORE_THRESHOLD,
    REASON_PERF_NO_SPEED_BENCHMARK,
    REASON_PERF_QUALIFIED_HR_SPEED,
    REASON_PERF_QUALIFIED_SPEED_ONLY,
    REASON_PERF_SCORE_TOO_LOW,
    REASON_PERF_SPEED_TOO_LOW,
    evaluate_performance_quality,
    predict_races,
)

REF = date(2026, 8, 24)


def _run(
    start_date: date,
    distance_m: float,
    duration_s: float,
    avg_hr: Optional[float] = None,
    max_hr: Optional[float] = None,
    elevation_gain_m: Optional[float] = None,
    activity_type: str = "running",
    moving_duration_s: Optional[float] = None,
) -> DomainActivity:
    return DomainActivity(
        activity_type=activity_type,
        start_time=start_date.isoformat(),
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=avg_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
        moving_duration_s=moving_duration_s,
    )


def _benchmark_2025() -> list[DomainActivity]:
    return [
        _run(date(2025, 9, 20), 8_000.0, 3200.0, avg_hr=128.0, max_hr=166.0),
        _run(date(2025, 10, 1), 9_000.0, 3400.0, avg_hr=132.0, max_hr=168.0),
        _run(date(2025, 10, 12), 10_000.0, 3600.0, avg_hr=138.0, max_hr=170.0),
        _run(date(2025, 10, 24), 11_000.0, 3850.0, avg_hr=142.0, max_hr=172.0),
        _run(date(2025, 11, 7), 12_000.0, 4050.0, avg_hr=148.0, max_hr=175.0),
        _run(date(2025, 11, 21), 13_000.0, 4200.0, avg_hr=152.0, max_hr=178.0),
    ]


def _benchmark_2026(with_hr: bool = True) -> list[DomainActivity]:
    avg = [118.0, 122.0, 126.0, 130.0, 133.0, 135.0] if with_hr else [None] * 6
    return [
        _run(date(2026, 5, 30), 8_000.0, 3200.0, avg_hr=avg[0], max_hr=160.0 if with_hr else None),
        _run(date(2026, 6, 12), 9_000.0, 3350.0, avg_hr=avg[1], max_hr=162.0 if with_hr else None),
        _run(date(2026, 6, 28), 10_000.0, 3600.0, avg_hr=avg[2], max_hr=164.0 if with_hr else None),
        _run(date(2026, 7, 10), 11_000.0, 3920.0, avg_hr=avg[3], max_hr=166.0 if with_hr else None),
        _run(date(2026, 7, 24), 12_000.0, 4050.0, avg_hr=avg[4], max_hr=168.0 if with_hr else None),
        _run(date(2026, 8, 8), 13_000.0, 4200.0, avg_hr=avg[5], max_hr=170.0 if with_hr else None),
    ]


def _strict_prior_hr_benchmark_2026() -> list[DomainActivity]:
    return [
        _run(date(2026, 5, 30), 8_000.0, 3200.0, avg_hr=118.0, max_hr=160.0),
        _run(date(2026, 6, 12), 9_000.0, 3350.0, avg_hr=122.0, max_hr=165.0),
        _run(date(2026, 6, 28), 10_000.0, 3600.0, avg_hr=126.0, max_hr=170.0),
        _run(date(2026, 7, 10), 11_000.0, 3920.0, avg_hr=130.0, max_hr=174.0),
        _run(date(2026, 7, 24), 12_000.0, 4050.0, avg_hr=133.0, max_hr=178.0),
        _run(date(2026, 8, 8), 13_000.0, 4200.0, avg_hr=135.0, max_hr=180.0),
    ]


def _ordinary_recent_7k() -> DomainActivity:
    return _run(date(2026, 8, 20), 7_230.0, 2460.0, avg_hr=136.4, max_hr=170.0)


def _known_10k_performance() -> DomainActivity:
    return _run(date(2025, 12, 14), 10_020.0, 3021.0, avg_hr=163.0, max_hr=178.0)


def _fast_18k_moderate_hr() -> DomainActivity:
    return _run(date(2026, 8, 22), 18_010.0, 5638.0, avg_hr=136.4, max_hr=170.0)


def _speed_only_star() -> DomainActivity:
    return _run(date(2026, 8, 23), 10_000.0, 2900.0)


def _speed_only_ordinary() -> DomainActivity:
    return _run(date(2026, 8, 23), 10_000.0, 3500.0)


def test_case_a_recent_ordinary_run_not_qualified():
    activities = _benchmark_2026() + [_ordinary_recent_7k()]
    quality = evaluate_performance_quality(_ordinary_recent_7k(), activities, REF)

    assert quality.qualified is False
    assert quality.reason_code == REASON_PERF_SPEED_TOO_LOW
    assert quality.benchmark_count == 6
    assert quality.personal_speed_percentile == pytest.approx(66.6667, rel=1e-4)
    assert quality.relative_avg_hr == pytest.approx(0.8024, rel=1e-4)
    assert quality.score == pytest.approx(0.4921, rel=1e-4)


def test_case_b_known_10k_performance_qualified_and_selected_for_5k_10k():
    activities = _benchmark_2025() + _benchmark_2026() + [
        _known_10k_performance(),
        _ordinary_recent_7k(),
        _fast_18k_moderate_hr(),
    ]

    quality = evaluate_performance_quality(_known_10k_performance(), activities, REF)
    assert quality.qualified is True
    assert quality.reason_code == REASON_PERF_QUALIFIED_HR_SPEED
    assert quality.personal_speed_percentile == 100.0
    assert quality.relative_avg_hr == pytest.approx(0.9157, rel=1e-4)
    assert quality.score == 1.0

    result = predict_races(activities, REF)
    predictions = {p.distance_label: p for p in result.predictions}
    # PR189 — Performance Curve V2: the qualified 10K performance contributes to the common
    # curve together with another qualified benchmark run. With multiple contributors,
    # source_distance_m / source_quality_score / source_relative_hr refer to the single
    # contributor only when contributors_count == 1. With multiple contributors these
    # fields are None (no single source). The curve itself is shared by all four targets.
    assert predictions["5K"].contributors_count >= 1
    assert predictions["5K"].predicted_time_s is not None
    assert predictions["10K"].predicted_time_s is not None
    # Monotonicity invariant: pace must not decrease as distance increases
    paces = [p.predicted_time_s / (p.distance_km * 1000) for p in result.predictions
             if p.predicted_time_s is not None]
    for i in range(len(paces) - 1):
        assert paces[i] <= paces[i + 1]


def test_case_c_long_fast_moderate_hr_follows_formula_without_special_case():
    activities = _benchmark_2026() + [_ordinary_recent_7k(), _fast_18k_moderate_hr()]
    quality = evaluate_performance_quality(_fast_18k_moderate_hr(), activities, REF)

    expected = (
        quality.score is not None
        and quality.score >= PERFORMANCE_SCORE_THRESHOLD
        and (quality.personal_speed_percentile or 0.0) >= PERFORMANCE_MIN_SPEED_PERCENTILE_WITH_HR
        and (quality.relative_avg_hr or 0.0) >= PERFORMANCE_MIN_RELATIVE_HR
    )

    assert quality.personal_speed_percentile == 100.0
    assert quality.relative_avg_hr == pytest.approx(0.8024, rel=1e-4)
    assert quality.score == pytest.approx(0.6421, rel=1e-4)
    assert quality.qualified is expected
    assert quality.reason_code == REASON_PERF_SCORE_TOO_LOW


def test_case_d_speed_only_extreme_run_qualified_low_confidence():
    activities = _benchmark_2026(with_hr=False) + [_speed_only_star()]
    quality = evaluate_performance_quality(_speed_only_star(), activities, REF)

    assert quality.qualified is True
    assert quality.reason_code == REASON_PERF_QUALIFIED_SPEED_ONLY
    assert quality.confidence == "low"
    assert quality.relative_avg_hr is None
    assert quality.personal_speed_percentile == 100.0
    assert quality.score == 1.0


def test_case_e_speed_only_ordinary_rejected():
    activities = _benchmark_2026(with_hr=False) + [_speed_only_ordinary()]
    quality = evaluate_performance_quality(_speed_only_ordinary(), activities, REF)

    assert quality.qualified is False
    assert quality.reason_code == REASON_PERF_SPEED_TOO_LOW
    assert quality.relative_avg_hr is None
    assert quality.personal_speed_percentile == pytest.approx(66.6667, rel=1e-4)
    assert quality.score == pytest.approx(0.6667, rel=1e-4)


def test_no_lookahead_future_speed_not_used_for_past_percentile():
    candidate = _ordinary_recent_7k()
    future_faster = _run(date(2026, 8, 23), 10_000.0, 2500.0, avg_hr=175.0, max_hr=175.0)
    base = _benchmark_2026() + [candidate]

    without_future = evaluate_performance_quality(candidate, base, REF)
    with_future = evaluate_performance_quality(candidate, base + [future_faster], REF)

    assert without_future.personal_speed_percentile == with_future.personal_speed_percentile
    assert without_future.score == with_future.score


def test_no_lookahead_future_fcmax_not_used_for_past_relative_hr():
    candidate = _ordinary_recent_7k()
    future_higher_fcmax = _run(date(2026, 8, 23), 9_000.0, 2600.0, avg_hr=150.0, max_hr=205.0)
    base = _benchmark_2026() + [candidate]

    without_future = evaluate_performance_quality(candidate, base, REF)
    with_future = evaluate_performance_quality(candidate, base + [future_higher_fcmax], REF)

    assert without_future.relative_avg_hr == with_future.relative_avg_hr


def test_strict_prior_fcmax_excludes_current_activity_max_hr():
    candidate = _run(
        date(2026, 8, 20),
        10_000.0,
        3000.0,
        avg_hr=160.0,
        max_hr=220.0,
        moving_duration_s=3000.0,
    )
    quality = evaluate_performance_quality(candidate, _strict_prior_hr_benchmark_2026() + [candidate], REF)

    assert quality.historical_fcmax == 180.0
    assert quality.relative_avg_hr == pytest.approx(round(160.0 / 180.0, 4), rel=1e-4)


def test_current_activity_max_hr_self_influence_is_disabled():
    prior = _strict_prior_hr_benchmark_2026()
    activity_a = _run(
        date(2026, 8, 20),
        10_000.0,
        3000.0,
        avg_hr=160.0,
        max_hr=180.0,
        moving_duration_s=3000.0,
    )
    activity_b = _run(
        date(2026, 8, 20),
        10_000.0,
        3000.0,
        avg_hr=160.0,
        max_hr=220.0,
        moving_duration_s=3000.0,
    )
    activities = prior + [activity_a, activity_b]

    quality_a = evaluate_performance_quality(activity_a, activities, REF)
    quality_b = evaluate_performance_quality(activity_b, activities, REF)

    assert quality_a.historical_fcmax == quality_b.historical_fcmax == 180.0
    assert quality_a.relative_avg_hr == quality_b.relative_avg_hr == pytest.approx(round(160.0 / 180.0, 4), rel=1e-4)
    assert quality_a.score == quality_b.score
    assert quality_a.qualified == quality_b.qualified
    assert quality_a.confidence == quality_b.confidence


def test_same_day_fcmax_cross_influence_is_disabled():
    candidate = _run(
        date(2026, 8, 20),
        10_000.0,
        3000.0,
        avg_hr=160.0,
        max_hr=180.0,
        moving_duration_s=3000.0,
    )
    same_day_other = _run(
        date(2026, 8, 20),
        8_000.0,
        2400.0,
        avg_hr=172.0,
        max_hr=220.0,
        moving_duration_s=2400.0,
    )
    quality = evaluate_performance_quality(candidate, _strict_prior_hr_benchmark_2026() + [same_day_other, candidate], REF)

    assert quality.historical_fcmax == 180.0
    assert quality.relative_avg_hr == pytest.approx(round(160.0 / 180.0, 4), rel=1e-4)


def test_future_fcmax_lookahead_is_disabled():
    candidate = _run(
        date(2026, 8, 20),
        10_000.0,
        3000.0,
        avg_hr=160.0,
        max_hr=180.0,
        moving_duration_s=3000.0,
    )
    future = _run(
        date(2026, 8, 21),
        9_000.0,
        2500.0,
        avg_hr=170.0,
        max_hr=220.0,
        moving_duration_s=2500.0,
    )
    base = _strict_prior_hr_benchmark_2026() + [candidate]

    without_future = evaluate_performance_quality(candidate, base, REF)
    with_future = evaluate_performance_quality(candidate, base + [future], REF)

    assert without_future.historical_fcmax == with_future.historical_fcmax == 180.0
    assert without_future.relative_avg_hr == with_future.relative_avg_hr
    assert without_future.personal_speed_percentile == with_future.personal_speed_percentile
    assert without_future.score == with_future.score
    assert without_future.qualified == with_future.qualified
    assert without_future.confidence == with_future.confidence


def test_benchmark_uses_only_strictly_prior_runs():
    candidate = _run(date(2026, 8, 20), 10_000.0, 3000.0, avg_hr=165.0, max_hr=170.0)
    same_day_fast = _run(date(2026, 8, 20), 10_000.0, 2400.0, avg_hr=170.0, max_hr=170.0)
    activities = _benchmark_2026() + [candidate, same_day_fast]

    quality = evaluate_performance_quality(candidate, activities, REF)

    assert quality.benchmark_count == 6
    assert quality.personal_speed_percentile == 100.0


def test_snapshot_replay_stable_with_future_data():
    snapshot = date(2026, 8, 20)
    candidate = _ordinary_recent_7k()
    future = _fast_18k_moderate_hr()
    activities = _benchmark_2026() + [candidate]

    q1 = evaluate_performance_quality(candidate, activities, snapshot)
    q2 = evaluate_performance_quality(candidate, activities + [future], snapshot)

    assert q1 == q2


def test_cold_start_without_five_prior_runs_is_not_qualified():
    candidate = _ordinary_recent_7k()
    activities = _benchmark_2026()[:4] + [candidate]

    quality = evaluate_performance_quality(candidate, activities, REF)

    assert quality.qualified is False
    assert quality.reason_code == REASON_PERF_NO_SPEED_BENCHMARK
    assert quality.benchmark_count == 4
    assert quality.personal_speed_percentile is None


def test_predictions_are_deterministic_with_quality_fields():
    activities = _benchmark_2025() + _benchmark_2026() + [
        _known_10k_performance(),
        _ordinary_recent_7k(),
        _fast_18k_moderate_hr(),
    ]

    result_a = predict_races(activities, REF)
    result_b = predict_races(list(activities), REF)

    assert result_a == result_b
    predictions = {p.distance_label: p for p in result_a.predictions}
    # PR189 — Performance Curve V2: with multiple qualified contributors, single-source
    # metadata fields (source_quality_confidence, source_speed_percentile, source_relative_hr)
    # are None. Determinism and prediction availability are the key invariants.
    assert predictions["5K"].contributors_count >= 1
    assert predictions["Semi"].predicted_time_s is not None
    assert predictions["Marathon"].predicted_time_s is not None
    # Curve diagnostics are always populated when a curve exists
    assert predictions["5K"].curve_k is not None
    assert predictions["5K"].curve_a is not None


def test_input_order_does_not_change_quality_or_predictions():
    activities = _benchmark_2025() + _benchmark_2026() + [
        _known_10k_performance(),
        _ordinary_recent_7k(),
        _fast_18k_moderate_hr(),
    ]
    reversed_activities = list(reversed(activities))

    quality_forward = evaluate_performance_quality(_known_10k_performance(), activities, REF)
    quality_reversed = evaluate_performance_quality(_known_10k_performance(), reversed_activities, REF)
    prediction_forward = predict_races(activities, REF)
    prediction_reversed = predict_races(reversed_activities, REF)

    assert quality_forward == quality_reversed
    assert prediction_forward == prediction_reversed
