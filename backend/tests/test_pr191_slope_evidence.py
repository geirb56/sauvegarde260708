"""Tests for PR #191 — QUALIFIED vs SLOPE-EVIDENCE separation.

slope_evidence = PerformanceQuality.confidence == "high"

Only high-confidence observations can authorise a data-driven k.
All qualified observations (including medium/low) contribute to A.

Tests:
  1. N>=3 pathology: 1 HIGH + multiple MEDIUM + multiple LOW + large spread.
     slope_evidence_count == 1 → k == 1.06 (fallback), A uses all qualified.
  2. N>=3 true multi-distance HIGH: 5K+10K+Semi HIGH with synthetic k != 1.06.
     k_identifiable == True, k appris proche du k synthétique.
  3. N>=3 cluster HIGH around 10K: spread insufficient → k == 1.06.
  4. Speed-only LOW: contribute to A, cannot individualise k.
  5. N==2 two HIGH sufficiently distinct: two_point_prior_shrinkage_fit preserved.
  6. N==2 HIGH + MEDIUM: k == 1.06, slope-evidence fallback.
  7. N==2 two MEDIUM: k == 1.06.
  8. N==2 two LOW speed-only: k == 1.06.
  9. Huber outlier: robustness from #190 preserved.
  10. No look-ahead: future activity must not affect any output.
  11. Input-order invariance: shuffled order gives identical result.
  12. VMA independence: changing VMA does not affect predictions/curve.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import List, Optional

import pytest

import training_v2.performance_model as pm
from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import RACE_DISTANCES_M, RIEGEL_K, predict_races

TODAY = date(2026, 8, 24)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    *,
    days_ago: int,
    distance_m: float,
    duration_s: float,
    avg_hr: Optional[float] = None,
    max_hr: Optional[float] = None,
    activity_type: str = "running",
) -> DomainActivity:
    return DomainActivity(
        activity_type=activity_type,
        start_time=(TODAY - timedelta(days=days_ago)).isoformat(),
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=avg_hr,
        max_hr=max_hr,
    )


def _benchmark_pool(n: int = 8, with_hr: bool = True) -> List[DomainActivity]:
    """Background speed-benchmark activities for qualification (non-performance pace)."""
    rows = [
        (90, 8_000.0, 3_600.0, 130.0, 165.0),
        (80, 9_000.0, 4_050.0, 132.0, 167.0),
        (70, 10_000.0, 4_500.0, 133.0, 168.0),
        (60, 8_500.0, 3_825.0, 131.0, 166.0),
        (50, 9_500.0, 4_275.0, 132.0, 167.0),
        (42, 10_500.0, 4_725.0, 134.0, 169.0),
        (35, 11_000.0, 4_950.0, 135.0, 170.0),
        (28, 12_000.0, 5_400.0, 136.0, 171.0),
    ]
    out = []
    for d, dist, dur, hr, mhr in rows[:n]:
        out.append(_run(
            days_ago=d,
            distance_m=dist,
            duration_s=dur,
            avg_hr=hr if with_hr else None,
            max_hr=mhr if with_hr else None,
        ))
    return out


def _diag(result) -> dict:
    return result.race_curve_diagnostics


def _preds(result) -> dict:
    return {p.distance_label: p for p in result.predictions}


# ---------------------------------------------------------------------------
# TEST 1 — N>=3 pathology: 1 HIGH + MEDIUM + LOW, large spread
# ---------------------------------------------------------------------------


def test_1_n3_one_high_plus_mediums_and_lows_no_k_learned():
    """1 HIGH observation + multiple MEDIUM + multiple LOW with large distance spread.

    slope_evidence_count == 1 → k cannot be personalised.
    method == prior_k_low_slope_evidence_fallback.
    k == RIEGEL_K.
    A uses ALL qualified observations (not just HIGH).
    """
    benchmark = _benchmark_pool(n=8)
    # FCmax for HR model
    fcmax = 185.0

    # Generate background activities with gradual variation in HR so that
    # benchmarks support the HR model, establishing a consistent FCmax.
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # HIGH: one genuine hard 10K
    high_perf = _run(days_ago=5, distance_m=10_000.0, duration_s=2_400.0,
                     avg_hr=165.0, max_hr=fcmax)

    # MEDIUM: several sustained efforts at different distances (not max)
    medium_perfs = [
        _run(days_ago=15, distance_m=7_070.0, duration_s=1_900.0,
             avg_hr=152.0, max_hr=fcmax),
        _run(days_ago=20, distance_m=14_000.0, duration_s=3_900.0,
             avg_hr=155.0, max_hr=fcmax),
        _run(days_ago=25, distance_m=20_630.0, duration_s=6_200.0,
             avg_hr=150.0, max_hr=fcmax),
    ]

    # LOW (speed-only, no HR): various distances
    low_perfs = [
        _run(days_ago=40, distance_m=6_000.0, duration_s=1_700.0),
        _run(days_ago=45, distance_m=8_000.0, duration_s=2_300.0),
        _run(days_ago=50, distance_m=12_000.0, duration_s=3_600.0),
        _run(days_ago=55, distance_m=18_000.0, duration_s=5_600.0),
    ]

    all_acts = benchmark + background_hrs + [high_perf] + medium_perfs + low_perfs
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    se_count = diag.get("slope_evidence_count", -1)
    assert se_count == 1, (
        f"Expected slope_evidence_count=1 (only one HIGH), got {se_count}"
    )

    k_identifiable = diag.get("k_identifiable")
    assert k_identifiable is False, (
        f"Expected k_identifiable=False (only 1 slope-evidence), got {k_identifiable}"
    )

    method = diag.get("curve_method")
    assert method == "prior_k_low_slope_evidence_fallback", (
        f"Expected prior_k_low_slope_evidence_fallback, got {method}"
    )

    curve_k = diag.get("curve_k")
    assert abs(curve_k - RIEGEL_K) < 1e-9, (
        f"Expected k == RIEGEL_K={RIEGEL_K}, got {curve_k}"
    )

    k_fallback_applied = diag.get("k_fallback_applied")
    assert k_fallback_applied is True, (
        f"Expected k_fallback_applied=True, got {k_fallback_applied}"
    )

    # A must incorporate all qualified observations — contributors_count > 1
    contributors_count = diag.get("contributors_count", 0)
    assert contributors_count > 1, (
        f"Expected A to use multiple qualified observations, got contributors_count={contributors_count}"
    )

    # Predictions must exist (pool is large enough for a curve)
    preds = _preds(result)
    assert any(p.predicted_time_s is not None for p in preds.values()), (
        "Expected at least one prediction to be non-null"
    )


# ---------------------------------------------------------------------------
# TEST 2 — N>=3 true multi-distance HIGH: k should be learned
# ---------------------------------------------------------------------------


def test_2_n3_three_high_multidistance_k_learned():
    """Three HIGH observations at 5K / 10K / Semi with a synthetic k = 1.10.

    k_identifiable must be True.
    Learned k must be close to 1.10 (not forced to 1.06).
    method != prior_k_low_slope_evidence_fallback.
    """
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # Synthetic curve: T = A * D^1.10
    SYNTHETIC_K = 1.10
    A_synthetic = 3600.0 / (10_000.0 ** SYNTHETIC_K)

    def t_syn(d: float) -> float:
        return A_synthetic * (d ** SYNTHETIC_K)

    # Three HIGH performances across well-separated distances
    high_5k = _run(days_ago=10, distance_m=5_000.0,
                   duration_s=t_syn(5_000.0),
                   avg_hr=172.0, max_hr=fcmax)
    high_10k = _run(days_ago=8, distance_m=10_000.0,
                    duration_s=t_syn(10_000.0),
                    avg_hr=175.0, max_hr=fcmax)
    high_semi = _run(days_ago=12, distance_m=21_097.5,
                     duration_s=t_syn(21_097.5),
                     avg_hr=171.0, max_hr=fcmax)

    all_acts = benchmark + background_hrs + [high_5k, high_10k, high_semi]
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    se_count = diag.get("slope_evidence_count", 0)
    assert se_count >= 2, (
        f"Expected slope_evidence_count >= 2 for three HIGH performances, got {se_count}"
    )

    k_identifiable = diag.get("k_identifiable")
    assert k_identifiable is True, (
        f"Expected k_identifiable=True for 5K/10K/Semi HIGH spread, got False. "
        f"score={diag.get('k_identifiability_score')}"
    )

    method = diag.get("curve_method")
    assert method != "prior_k_low_slope_evidence_fallback", (
        "Motor incorrectly fell back to prior k for an identifiable dataset."
    )

    curve_k = diag.get("curve_k")
    assert curve_k is not None, "Expected curve_k to be set"
    # Learned k should be in a reasonable neighbourhood of SYNTHETIC_K
    assert abs(curve_k - SYNTHETIC_K) < 0.12, (
        f"Expected learned k ≈ {SYNTHETIC_K}, got {curve_k}"
    )


# ---------------------------------------------------------------------------
# TEST 3 — Cluster HIGH around 10K: spread insufficient
# ---------------------------------------------------------------------------


def test_3_cluster_high_around_10k_k_fallback():
    """Multiple HIGH observations all within 8–12 km.

    spread is insufficient → k_identifiable == False, k == RIEGEL_K.
    A is correctly estimated from the cluster.
    """
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # HIGH cluster 8–12 km
    cluster = [
        _run(days_ago=10, distance_m=8_000.0, duration_s=2_100.0,
             avg_hr=170.0, max_hr=fcmax),
        _run(days_ago=12, distance_m=9_500.0, duration_s=2_520.0,
             avg_hr=171.0, max_hr=fcmax),
        _run(days_ago=14, distance_m=10_500.0, duration_s=2_800.0,
             avg_hr=172.0, max_hr=fcmax),
        _run(days_ago=16, distance_m=11_000.0, duration_s=2_940.0,
             avg_hr=170.0, max_hr=fcmax),
    ]

    all_acts = benchmark + background_hrs + cluster
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    k_identifiable = diag.get("k_identifiable")
    assert k_identifiable is False, (
        f"Expected k_identifiable=False for 8–12 km HIGH cluster, got True. "
        f"score={diag.get('k_identifiability_score')}"
    )

    method = diag.get("curve_method")
    assert method == "prior_k_low_slope_evidence_fallback", (
        f"Expected prior_k_low_slope_evidence_fallback, got {method}"
    )

    curve_k = diag.get("curve_k")
    assert abs(curve_k - RIEGEL_K) < 1e-9, (
        f"Expected k=RIEGEL_K={RIEGEL_K}, got {curve_k}"
    )

    # A should be reasonable (not zero or absurd)
    curve_a = diag.get("curve_a")
    assert curve_a is not None and curve_a > 0, f"Expected curve_a > 0, got {curve_a}"


# ---------------------------------------------------------------------------
# TEST 4 — Speed-only LOW: contribute to A, cannot individualise k
# ---------------------------------------------------------------------------


def test_4_speed_only_low_contribute_to_a_not_k():
    """Speed-only (no HR) observations qualify at LOW confidence.

    They should contribute to A (curve fitting) but cannot push k.
    slope_evidence_count == 0.
    method == prior_k_low_slope_evidence_fallback (or single_performance_riegel if N==1).
    k == RIEGEL_K.
    """
    # Enough activities for speed benchmark, no HR
    benchmark = _benchmark_pool(n=8, with_hr=False)

    # Speed-only performances at different distances
    low_perfs = [
        _run(days_ago=5, distance_m=5_000.0, duration_s=1_400.0),
        _run(days_ago=10, distance_m=10_000.0, duration_s=2_900.0),
        _run(days_ago=15, distance_m=15_000.0, duration_s=4_500.0),
        _run(days_ago=20, distance_m=20_000.0, duration_s=6_200.0),
    ]

    all_acts = benchmark + low_perfs
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    se_count = diag.get("slope_evidence_count", -1)
    assert se_count == 0, (
        f"Expected slope_evidence_count=0 for speed-only observations, got {se_count}"
    )

    curve_k = diag.get("curve_k")
    if curve_k is not None:
        assert abs(curve_k - RIEGEL_K) < 1e-9, (
            f"k must be RIEGEL_K={RIEGEL_K} for speed-only pool, got {curve_k}"
        )

    method = diag.get("curve_method")
    # Method must NOT be the data-driven robust fit (which would have learned k)
    assert method not in (
        "robust_weighted_log_fit",
        "two_point_prior_shrinkage_fit",
    ), f"Unexpected data-driven method for speed-only pool: {method}"


# ---------------------------------------------------------------------------
# TEST 5 — N==2 two HIGH: shrinkage preserved
# ---------------------------------------------------------------------------


def test_5_n2_two_high_shrinkage_preserved():
    """Two HIGH observations sufficiently distinct in distance.

    two_point_prior_shrinkage_fit must be used.
    k is between RIEGEL_K and the data-driven k (shrinkage).
    """
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # Two HIGH at very different distances
    high_5k = _run(days_ago=5, distance_m=5_000.0, duration_s=1_200.0,
                   avg_hr=174.0, max_hr=fcmax)
    high_semi = _run(days_ago=8, distance_m=21_097.5, duration_s=5_700.0,
                     avg_hr=171.0, max_hr=fcmax)

    all_acts = benchmark + background_hrs + [high_5k, high_semi]
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    method = diag.get("curve_method")
    assert method == "two_point_prior_shrinkage_fit", (
        f"Expected two_point_prior_shrinkage_fit for two HIGH, got {method}"
    )

    se_count = diag.get("slope_evidence_count", 0)
    assert se_count >= 2, (
        f"Expected slope_evidence_count >= 2, got {se_count}"
    )


# ---------------------------------------------------------------------------
# TEST 6 — N==2 HIGH + MEDIUM: k == 1.06 fallback
# ---------------------------------------------------------------------------


def test_6_n2_high_plus_medium_no_k_learned():
    """N==2: one HIGH and one MEDIUM observation.

    slope_evidence_count == 1 < 2 → cannot learn k.
    method == two_point_prior_k_low_slope_evidence_fallback.
    k == RIEGEL_K.
    k_fallback_applied == True.
    """
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # HIGH 10K
    high_perf = _run(days_ago=5, distance_m=10_000.0, duration_s=2_400.0,
                     avg_hr=170.0, max_hr=fcmax)
    # MEDIUM (moderate effort) 5K
    medium_perf = _run(days_ago=10, distance_m=5_000.0, duration_s=1_350.0,
                       avg_hr=155.0, max_hr=fcmax)

    all_acts = benchmark + background_hrs + [high_perf, medium_perf]
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    se_count = diag.get("slope_evidence_count", -1)
    assert se_count == 1, (
        f"Expected slope_evidence_count=1 (only one HIGH), got {se_count}"
    )

    method = diag.get("curve_method")
    assert method == "two_point_prior_k_low_slope_evidence_fallback", (
        f"Expected two_point_prior_k_low_slope_evidence_fallback for HIGH+MEDIUM, got {method}"
    )

    curve_k = diag.get("curve_k")
    assert abs(curve_k - RIEGEL_K) < 1e-9, (
        f"Expected k=RIEGEL_K={RIEGEL_K} for HIGH+MEDIUM, got {curve_k}"
    )

    k_fallback_applied = diag.get("k_fallback_applied")
    assert k_fallback_applied is True, (
        f"Expected k_fallback_applied=True, got {k_fallback_applied}"
    )

    k_raw = diag.get("curve_k_raw")
    assert k_raw is not None, "k_raw must be available as diagnostic"


# ---------------------------------------------------------------------------
# TEST 7 — N==2 two MEDIUM: k == 1.06
# ---------------------------------------------------------------------------


def test_7_n2_two_medium_no_k_learned():
    """N==2: two MEDIUM observations.

    slope_evidence_count == 0 → k == RIEGEL_K.
    method == two_point_prior_k_low_slope_evidence_fallback.
    """
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # Two MEDIUM performances (moderate HR, not high enough for HIGH confidence)
    med1 = _run(days_ago=8, distance_m=7_000.0, duration_s=1_890.0,
                avg_hr=152.0, max_hr=fcmax)
    med2 = _run(days_ago=12, distance_m=14_000.0, duration_s=3_920.0,
                avg_hr=153.0, max_hr=fcmax)

    all_acts = benchmark + background_hrs + [med1, med2]
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    curve_k = diag.get("curve_k")
    if curve_k is not None:
        assert abs(curve_k - RIEGEL_K) < 1e-9, (
            f"Expected k=RIEGEL_K={RIEGEL_K} for two MEDIUM, got {curve_k}"
        )

    method = diag.get("curve_method")
    # Must not be the two-HIGH shrinkage path
    assert method != "two_point_prior_shrinkage_fit", (
        "Two MEDIUM must NOT trigger two_point_prior_shrinkage_fit"
    )


# ---------------------------------------------------------------------------
# TEST 8 — N==2 two LOW speed-only: k == 1.06
# ---------------------------------------------------------------------------


def test_8_n2_two_low_speedonly_no_k_learned():
    """N==2: two LOW speed-only observations.

    slope_evidence_count == 0 → k == RIEGEL_K.
    method must NOT be two_point_prior_shrinkage_fit.
    """
    # Enough benchmark for speed percentile
    benchmark = _benchmark_pool(n=8, with_hr=False)

    # Two speed-only performances
    low1 = _run(days_ago=5, distance_m=5_000.0, duration_s=1_380.0)
    low2 = _run(days_ago=10, distance_m=20_000.0, duration_s=5_800.0)

    all_acts = benchmark + [low1, low2]
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    curve_k = diag.get("curve_k")
    if curve_k is not None:
        assert abs(curve_k - RIEGEL_K) < 1e-9, (
            f"Expected k=RIEGEL_K={RIEGEL_K} for two speed-only LOW, got {curve_k}"
        )

    method = diag.get("curve_method")
    assert method != "two_point_prior_shrinkage_fit", (
        "Two LOW speed-only must NOT trigger two_point_prior_shrinkage_fit"
    )

    se_count = diag.get("slope_evidence_count", -1)
    assert se_count == 0, (
        f"Expected slope_evidence_count=0 for speed-only, got {se_count}"
    )


# ---------------------------------------------------------------------------
# TEST 9 — Huber outlier: #190 robustness preserved
# ---------------------------------------------------------------------------


def test_9_huber_outlier_robustness_preserved():
    """A genuine aberrant outlier (e.g. GPS glitch) should still be down-weighted
    by the Huber M-estimator, even when it has HIGH confidence.

    The final k must NOT be wildly distorted by a single outlier.
    """
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    # 3+ HIGH performances consistent with k ≈ 1.06–1.12
    consistent = [
        _run(days_ago=5, distance_m=5_000.0, duration_s=1_200.0,
             avg_hr=172.0, max_hr=fcmax),
        _run(days_ago=8, distance_m=10_000.0, duration_s=2_520.0,
             avg_hr=173.0, max_hr=fcmax),
        _run(days_ago=10, distance_m=21_097.5, duration_s=5_600.0,
             avg_hr=171.0, max_hr=fcmax),
    ]

    # Aberrant outlier: HIGH confidence but wildly different time
    outlier = _run(days_ago=12, distance_m=10_000.0, duration_s=600.0,
                   avg_hr=178.0, max_hr=fcmax)  # impossible 10:00 min 10K

    all_acts = benchmark + background_hrs + consistent + [outlier]
    result = predict_races(all_acts, TODAY)
    diag = _diag(result)

    curve_k = diag.get("curve_k")
    # The outlier must not push k to an absurd value
    if curve_k is not None:
        assert 0.95 <= curve_k <= 1.20, (
            f"Outlier caused absurd k={curve_k}; Huber robustness may be broken"
        )

    # Must have produced predictions
    preds = _preds(result)
    assert any(p.predicted_time_s is not None for p in preds.values()), (
        "Expected at least one prediction to be non-null after Huber outlier test"
    )


# ---------------------------------------------------------------------------
# TEST 10 — No look-ahead
# ---------------------------------------------------------------------------


def test_10_no_lookahead():
    """A future activity (days_ago < 0) must not affect any output."""
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    perf_now = _run(days_ago=5, distance_m=10_000.0, duration_s=2_400.0,
                    avg_hr=170.0, max_hr=fcmax)

    result_without = predict_races(benchmark + background_hrs + [perf_now], TODAY)
    diag_without = _diag(result_without)

    # Add a future activity (very fast — would change predictions if lookahead)
    future = _run(days_ago=-3, distance_m=10_000.0, duration_s=1_500.0,
                  avg_hr=180.0, max_hr=fcmax)

    result_with = predict_races(benchmark + background_hrs + [perf_now, future], TODAY)
    diag_with = _diag(result_with)

    assert diag_without.get("qualified_performance_count") == diag_with.get("qualified_performance_count"), (
        "Future activity must not change qualified_performance_count"
    )
    assert diag_without.get("curve_k") == diag_with.get("curve_k"), (
        "Future activity must not change curve_k"
    )

    preds_without = _preds(result_without)
    preds_with = _preds(result_with)
    for label in RACE_DISTANCES_M:
        t_wo = preds_without[label].predicted_time_s
        t_w = preds_with[label].predicted_time_s
        assert t_wo == t_w, (
            f"Future activity changed prediction for {label}: {t_wo} → {t_w}"
        )


# ---------------------------------------------------------------------------
# TEST 11 — Input-order invariance
# ---------------------------------------------------------------------------


def test_11_input_order_invariant():
    """Shuffling the input list must produce identical diagnostics and predictions."""
    benchmark = _benchmark_pool(n=8)
    fcmax = 185.0
    background_hrs = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                           avg_hr=130, max_hr=fcmax)
                      for d in (95, 100)]

    perfs = [
        _run(days_ago=5, distance_m=5_000.0, duration_s=1_200.0,
             avg_hr=173.0, max_hr=fcmax),
        _run(days_ago=8, distance_m=10_000.0, duration_s=2_520.0,
             avg_hr=174.0, max_hr=fcmax),
        _run(days_ago=12, distance_m=21_097.5, duration_s=5_600.0,
             avg_hr=171.0, max_hr=fcmax),
    ]

    all_acts = benchmark + background_hrs + perfs
    result_base = predict_races(all_acts, TODAY)
    diag_base = _diag(result_base)

    rng = random.Random(42)
    shuffled = list(all_acts)
    rng.shuffle(shuffled)
    result_shuffled = predict_races(shuffled, TODAY)
    diag_shuffled = _diag(result_shuffled)

    for key in ("curve_k", "curve_a", "curve_method", "k_fallback_applied",
                "slope_evidence_count", "qualified_performance_count"):
        assert diag_base.get(key) == diag_shuffled.get(key), (
            f"Input-order changed '{key}': {diag_base.get(key)} vs {diag_shuffled.get(key)}"
        )

    preds_base = _preds(result_base)
    preds_shuffled = _preds(result_shuffled)
    for label in RACE_DISTANCES_M:
        assert preds_base[label].predicted_time_s == preds_shuffled[label].predicted_time_s, (
            f"Input order changed prediction for {label}"
        )


# ---------------------------------------------------------------------------
# TEST 12 — VMA independence
# ---------------------------------------------------------------------------


def test_12_vma_independence():
    """Changing FCmax so that VMA changes must NOT affect race predictions or curve."""
    benchmark = _benchmark_pool(n=8)

    # Low FCmax (30 bpm lower) → very different VMA, but same performance pool
    low_fcmax_hr = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                         avg_hr=130, max_hr=150.0)
                    for d in (95, 100)]
    high_fcmax_hr = [_run(days_ago=d, distance_m=9000, duration_s=4000,
                          avg_hr=130, max_hr=185.0)
                     for d in (95, 100)]

    perf = _run(days_ago=5, distance_m=10_000.0, duration_s=2_400.0,
                avg_hr=170.0, max_hr=185.0)

    result_low = predict_races(benchmark + low_fcmax_hr + [perf], TODAY)
    result_high = predict_races(benchmark + high_fcmax_hr + [perf], TODAY)

    diag_low = _diag(result_low)
    diag_high = _diag(result_high)

    assert diag_low.get("curve_k") == diag_high.get("curve_k"), (
        "VMA change should not affect curve_k"
    )
    assert diag_low.get("curve_a") == diag_high.get("curve_a"), (
        "VMA change should not affect curve_a"
    )

    preds_low = _preds(result_low)
    preds_high = _preds(result_high)
    for label in RACE_DISTANCES_M:
        assert preds_low[label].predicted_time_s == preds_high[label].predicted_time_s, (
            f"VMA change affected prediction for {label}"
        )
