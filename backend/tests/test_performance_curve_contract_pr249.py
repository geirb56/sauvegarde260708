from __future__ import annotations

from datetime import date, timedelta

import pytest

import training_v2.performance_model as pm
from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import PerformanceQuality, RIEGEL_K, predict_races

TODAY = date(2026, 9, 1)


def _activity(*, days_ago: int, distance_m: float, duration_s: float) -> DomainActivity:
    return DomainActivity(
        activity_type="running",
        start_time=(TODAY - timedelta(days=days_ago)).isoformat(),
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=165.0,
        max_hr=185.0,
    )


def _quality(confidence: str, score: float = 0.9) -> PerformanceQuality:
    return PerformanceQuality(
        qualified=True,
        score=score,
        confidence=confidence,
        personal_speed_percentile=95.0,
        benchmark_count=10,
        relative_avg_hr=0.9,
        historical_fcmax=185.0,
        reason_code="TEST_QUALIFIED",
    )


def _build(pool):
    curve = pm._build_performance_curve(pool, TODAY)
    assert curve is not None
    return curve


def _dur(a: float, k: float, d_m: float) -> float:
    return a * (d_m ** k)


def test_case_a_old_high_outside_90d_not_used_for_slope_evidence():
    old_high = (_activity(days_ago=91, distance_m=21_097.5, duration_s=6300.0), _quality("high", 0.95))
    med = (_activity(days_ago=12, distance_m=10_000.0, duration_s=2700.0), _quality("medium", 0.82))
    low = (_activity(days_ago=7, distance_m=5_000.0, duration_s=1320.0), _quality("low", 0.75))

    curve = _build([old_high, med, low])

    assert curve.slope_evidence_count == 0
    assert curve.k == pytest.approx(RIEGEL_K, rel=1e-9)
    assert curve.k_fallback_applied is True
    assert curve.method == "prior_k_low_slope_evidence_fallback"
    assert curve.k_identifiability_reason == "no_slope_evidence_high_observations"


def test_case_b_two_recent_high_with_spread_can_personalize_k():
    k_true = 1.12
    a_true = 1200.0 / (5_000.0 ** k_true)
    high_5k = (_activity(days_ago=8, distance_m=5_000.0, duration_s=_dur(a_true, k_true, 5_000.0)), _quality("high", 0.96))
    high_semi = (_activity(days_ago=5, distance_m=21_097.5, duration_s=_dur(a_true, k_true, 21_097.5)), _quality("high", 0.95))

    curve = _build([high_5k, high_semi])

    assert curve.slope_evidence_count == 2
    assert curve.method == "two_point_prior_shrinkage_fit"
    assert curve.k != pytest.approx(RIEGEL_K, rel=1e-6)
    assert curve.k_fallback_applied is False


def test_case_c_two_recent_high_with_narrow_spread_fallback():
    high_10k = (_activity(days_ago=9, distance_m=10_000.0, duration_s=2500.0), _quality("high", 0.95))
    high_10k_close = (_activity(days_ago=6, distance_m=10_200.0, duration_s=2555.0), _quality("high", 0.94))

    curve = _build([high_10k, high_10k_close])

    assert curve.slope_evidence_count == 2
    assert curve.k_identifiable is False
    assert curve.k_identifiability_reason == "insufficient_slope_evidence_spread"
    assert curve.k == pytest.approx(RIEGEL_K, rel=1e-9)
    assert curve.k_fallback_applied is True


def test_case_d_three_recent_high_learn_personal_k():
    k_true = 1.11
    a_true = 1185.0 / (5_000.0 ** k_true)
    pool = [
        (_activity(days_ago=7, distance_m=5_000.0, duration_s=_dur(a_true, k_true, 5_000.0)), _quality("high", 0.97)),
        (_activity(days_ago=10, distance_m=10_000.0, duration_s=_dur(a_true, k_true, 10_000.0)), _quality("high", 0.96)),
        (_activity(days_ago=13, distance_m=21_097.5, duration_s=_dur(a_true, k_true, 21_097.5)), _quality("high", 0.95)),
    ]

    curve = _build(pool)

    assert curve.slope_evidence_count == 3
    assert curve.k_fallback_applied is False
    assert curve.k_identifiable is True
    assert curve.k == pytest.approx(k_true, abs=0.03)


def test_case_e_medium_low_do_not_move_k_when_three_recent_high_exist():
    k_true = 1.11
    a_true = 1185.0 / (5_000.0 ** k_true)
    high_pool = [
        (_activity(days_ago=7, distance_m=5_000.0, duration_s=_dur(a_true, k_true, 5_000.0)), _quality("high", 0.97)),
        (_activity(days_ago=10, distance_m=10_000.0, duration_s=_dur(a_true, k_true, 10_000.0)), _quality("high", 0.96)),
        (_activity(days_ago=13, distance_m=21_097.5, duration_s=_dur(a_true, k_true, 21_097.5)), _quality("high", 0.95)),
    ]
    baseline = _build(high_pool)

    mixed = high_pool + [
        (_activity(days_ago=11, distance_m=12_000.0, duration_s=5000.0), _quality("medium", 0.80)),
        (_activity(days_ago=14, distance_m=15_000.0, duration_s=7000.0), _quality("low", 0.72)),
        (_activity(days_ago=9, distance_m=8_000.0, duration_s=4200.0), _quality("medium", 0.78)),
    ]
    with_mixed = _build(mixed)

    assert with_mixed.slope_evidence_count == baseline.slope_evidence_count
    assert with_mixed.k_raw == pytest.approx(baseline.k_raw, abs=0.01)
    assert with_mixed.k == pytest.approx(baseline.k, abs=0.01)


def test_case_f_old_high_influential_does_not_move_k_or_slope_evidence_range():
    k_true = 1.10
    a_true = 1210.0 / (5_000.0 ** k_true)
    recent_high = [
        (_activity(days_ago=6, distance_m=5_000.0, duration_s=_dur(a_true, k_true, 5_000.0)), _quality("high", 0.97)),
        (_activity(days_ago=8, distance_m=10_000.0, duration_s=_dur(a_true, k_true, 10_000.0)), _quality("high", 0.96)),
        (_activity(days_ago=11, distance_m=21_097.5, duration_s=_dur(a_true, k_true, 21_097.5)), _quality("high", 0.95)),
    ]
    baseline = _build(recent_high)

    old_influential_high = (_activity(days_ago=140, distance_m=42_195.0, duration_s=10_000.0), _quality("high", 0.99))
    with_old = _build(recent_high + [old_influential_high])

    assert with_old.slope_evidence_count == baseline.slope_evidence_count
    assert with_old.slope_evidence_distance_min == baseline.slope_evidence_distance_min
    assert with_old.slope_evidence_distance_max == baseline.slope_evidence_distance_max
    assert with_old.k_raw == pytest.approx(baseline.k_raw, abs=0.01)
    assert with_old.k == pytest.approx(baseline.k, abs=0.01)
    # PR249 scope boundary: old HIGH can still influence A calibration via qualified pool.
    assert with_old.a != pytest.approx(baseline.a, rel=1e-6, abs=1e-9)


def test_case_f_boundary_90_included_91_excluded_for_slope_evidence():
    k_true = 1.10
    a_true = 1210.0 / (5_000.0 ** k_true)
    base = [
        (_activity(days_ago=6, distance_m=5_000.0, duration_s=_dur(a_true, k_true, 5_000.0)), _quality("high", 0.97)),
        (_activity(days_ago=8, distance_m=10_000.0, duration_s=_dur(a_true, k_true, 10_000.0)), _quality("high", 0.96)),
        (_activity(days_ago=11, distance_m=21_097.5, duration_s=_dur(a_true, k_true, 21_097.5)), _quality("high", 0.95)),
    ]
    curve_base = _build(base)

    high_90 = (_activity(days_ago=90, distance_m=42_195.0, duration_s=10_000.0), _quality("high", 0.99))
    high_91 = (_activity(days_ago=91, distance_m=42_195.0, duration_s=10_000.0), _quality("high", 0.99))

    curve_90 = _build(base + [high_90])
    curve_91 = _build(base + [high_91])

    assert curve_90.slope_evidence_count == curve_base.slope_evidence_count + 1
    assert curve_91.slope_evidence_count == curve_base.slope_evidence_count
    assert curve_90.slope_evidence_distance_max > curve_base.slope_evidence_distance_max
    assert curve_91.slope_evidence_distance_max == curve_base.slope_evidence_distance_max


def test_single_qualified_observation_uses_prior_with_explicit_fallback():
    one_high = [
        (_activity(days_ago=7, distance_m=10_000.0, duration_s=2500.0), _quality("high", 0.95)),
    ]
    curve = _build(one_high)

    assert curve.method == "single_performance_riegel"
    assert curve.k == pytest.approx(RIEGEL_K, rel=1e-9)
    assert curve.k_fallback_applied is True
    assert curve.k_identifiable is False
    assert curve.k_raw is None
    assert curve.slope_evidence_count == 1


def test_case_g_one_recent_high_plus_many_non_high_forces_fallback_but_keeps_level_curve():
    pool = [
        (_activity(days_ago=7, distance_m=10_000.0, duration_s=2500.0), _quality("high", 0.95)),
        (_activity(days_ago=9, distance_m=5_000.0, duration_s=1500.0), _quality("medium", 0.82)),
        (_activity(days_ago=12, distance_m=8_000.0, duration_s=2600.0), _quality("low", 0.76)),
        (_activity(days_ago=14, distance_m=12_000.0, duration_s=4000.0), _quality("medium", 0.80)),
        (_activity(days_ago=18, distance_m=21_097.5, duration_s=7600.0), _quality("low", 0.70)),
    ]

    curve = _build(pool)

    assert curve.slope_evidence_count == 1
    assert curve.k == pytest.approx(RIEGEL_K, rel=1e-9)
    assert curve.k_fallback_applied is True
    assert curve.k_identifiable is False
    assert curve.k_raw is None
    assert curve.k_identifiability_reason == "insufficient_slope_evidence_count"
    assert curve.a > 0


def test_no_lookahead_future_activity_never_affects_curve():
    base = [
        (_activity(days_ago=5, distance_m=5_000.0, duration_s=1200.0), _quality("high", 0.97)),
        (_activity(days_ago=7, distance_m=10_000.0, duration_s=2580.0), _quality("high", 0.95)),
        (_activity(days_ago=12, distance_m=21_097.5, duration_s=5850.0), _quality("high", 0.94)),
    ]
    future = (_activity(days_ago=-2, distance_m=10_000.0, duration_s=1800.0), _quality("high", 0.99))

    c1 = _build(base)
    c2 = _build(base + [future])

    assert c2.slope_evidence_count == c1.slope_evidence_count
    assert c2.k == pytest.approx(c1.k, abs=1e-9)
    assert c2.a == pytest.approx(c1.a, abs=1e-9)


def test_diagnostics_expose_slope_evidence_window_days():
    benchmark = [
        _activity(days_ago=95, distance_m=8_000.0, duration_s=3600.0),
        _activity(days_ago=85, distance_m=9_000.0, duration_s=4050.0),
        _activity(days_ago=75, distance_m=10_000.0, duration_s=4500.0),
        _activity(days_ago=65, distance_m=8_500.0, duration_s=3825.0),
        _activity(days_ago=55, distance_m=9_500.0, duration_s=4275.0),
    ]
    performances = [
        _activity(days_ago=10, distance_m=5_000.0, duration_s=1200.0),
        _activity(days_ago=8, distance_m=10_000.0, duration_s=2520.0),
        _activity(days_ago=6, distance_m=21_097.5, duration_s=5700.0),
    ]
    result = predict_races(benchmark + performances, TODAY)
    diag = result.race_curve_diagnostics
    assert diag.get("slope_evidence_window_days") == pm.SLOPE_EVIDENCE_WINDOW_DAYS
    assert diag.get("slope_evidence_window_days") == 90
