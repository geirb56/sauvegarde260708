"""Tests for PR #190 — k identifiability + quality-aware Huber.

Tests:
  1. Runtime pathology reproduction — flat speed-only pool + 1 high-confidence
     short performance: k must not be accepted as ~1.0 via robust_weighted_log_fit.
  2. Narrow distance cluster — many good observations all at 8–12 km:
     k_identifiable == False, method == prior_k_low_slope_evidence_fallback.
  3. Identifiable true curve — high-quality spread 5K / 10K / semi:
     k_identifiable == True, motor learns a reasonable k.
  4. True outlier protection — real aberrant point still under-weighted;
     quality-aware Huber floor does not bypass genuine outlier protection.
  5. Speed-only pool useful but insufficient for slope — speed-only pool still
     produces predictions via prior k; k_identifiable == False.
  6. No look-ahead — future activity must not affect any output.
  7. Input-order invariance — shuffled order gives identical result.
  8. VMA independence — changing VMA output does not affect predictions/curve.
  9. C190 conflict priority — k_raw out of [1.0, 1.25] AND k_identifiable False:
     k_conflict must be True and method must be prior_k_conflict_fallback.
  10. C190 identifiability fallback — k_raw in [1.0, 1.25] AND k_identifiable False:
      k_conflict must be False and method must be prior_k_low_slope_evidence_fallback.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import List, Optional

import pytest

import training_v2.performance_model as pm
from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import RACE_DISTANCES_M, predict_races

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


def _benchmark_pool(n: int = 7, with_hr: bool = True) -> List[DomainActivity]:
    """Generate a background pool of speed-benchmark activities for qualification."""
    rows = [
        (85, 8_000.0, 3_300.0, 125.0, 160.0),
        (72, 9_000.0, 3_700.0, 127.0, 162.0),
        (60, 10_000.0, 4_100.0, 129.0, 164.0),
        (50, 8_500.0, 3_500.0, 126.0, 161.0),
        (42, 9_500.0, 3_900.0, 128.0, 163.0),
        (35, 10_500.0, 4_350.0, 130.0, 165.0),
        (28, 11_000.0, 4_600.0, 131.0, 166.0),
        (22, 12_000.0, 5_050.0, 132.0, 167.0),
        (18, 8_000.0, 3_320.0, 126.0, 162.0),
        (14, 9_000.0, 3_730.0, 128.0, 164.0),
    ]
    out = []
    for i, (d, dist, dur, hr, mhr) in enumerate(rows[:n]):
        out.append(_run(
            days_ago=d,
            distance_m=dist,
            duration_s=dur,
            avg_hr=hr if with_hr else None,
            max_hr=mhr if with_hr else None,
        ))
    return out


def _preds(result) -> dict:
    return {p.distance_label: p for p in result.predictions}


# ---------------------------------------------------------------------------
# TEST 1 — Runtime pathology reproduction
# ---------------------------------------------------------------------------

def test_1_runtime_pathology_flat_speedonly_plus_one_high_quality():
    """Reproduce the runtime bug: 14 speed-only low-confidence activities at
    roughly constant pace over 6–21 km, plus 1 genuine high-quality shorter
    performance.

    The forbidden outcome is:
      curve_k ≈ 1.0 accepted via robust_weighted_log_fit
      (the nuage flat-majority declares the high-quality point an outlier).

    Expected: either the high-confidence point's Huber weight is not crushed
    (quality-aware floor), or k_identifiable == False and the motor returns
    prior_k_low_slope_evidence_fallback.
    """
    # Benchmark pool for personal-speed-percentile computation
    bench = _benchmark_pool(n=10, with_hr=False)

    # 14 speed-only low-confidence performances, all at ~6:05/km, 6–21 km.
    # These will have quality_confidence="low" (speed-only fallback #188).
    flat_runs: List[DomainActivity] = []
    distances = [
        6_100, 7_200, 8_000, 9_000, 10_500, 11_000, 12_000,
        13_000, 14_000, 15_000, 16_000, 18_000, 19_000, 21_100,
    ]
    for i, dist_m in enumerate(distances):
        pace = 6.08 + (i % 3) * 0.02   # ~6:06–6:10/km, nearly flat
        dur_s = pace * 60.0 * (dist_m / 1000.0)
        flat_runs.append(_run(
            days_ago=90 + i * 2,
            distance_m=dist_m,
            duration_s=dur_s,
        ))

    # 1 genuine high-quality short effort: 10.02 km at 5:02/km with valid HR
    # This performance has significantly faster pace → carries slope information.
    high_perf = _run(
        days_ago=10,
        distance_m=10_020.0,
        duration_s=10_020.0 / 1000.0 * 5.033 * 60.0,   # ≈ 5:02/km
        avg_hr=165.0,
        max_hr=182.0,
    )

    activities = bench + flat_runs + [high_perf]
    result = predict_races(activities, TODAY)
    diag = result.race_curve_diagnostics

    # FORBIDDEN outcome: k ≈ 1.0 accepted as robust_weighted_log_fit
    # Either the quality-aware Huber keeps the high point's weight reasonable,
    # OR the identifiability check rejects k and falls back to prior.
    curve_method = diag.get("curve_method")
    curve_k = diag.get("curve_k")

    if curve_method == "robust_weighted_log_fit":
        # If motor still uses data-driven k, high-quality point must NOT have
        # been crushed: check that k is meaningfully above 1.0.
        assert curve_k is not None and curve_k > 1.02, (
            f"Forbidden: robust_weighted_log_fit with k={curve_k:.4f} ≈ 1.0. "
            "The high-quality short effort was silenced by Huber."
        )
    else:
        # Identifiability fallback or single/two-point method
        allowed_fallback_methods = {
            "prior_k_low_slope_evidence_fallback",
            "two_point_prior_shrinkage_fit",
            "single_performance_riegel",
        }
        assert curve_method in allowed_fallback_methods or (
            diag.get("k_identifiable") is False
        ), f"Unexpected curve_method={curve_method} with k={curve_k}"

    # Predictions must exist (predictions still work via prior k if needed)
    preds = _preds(result)
    assert preds["5K"].predicted_time_s is not None or preds["Marathon"].predicted_time_s is not None


# ---------------------------------------------------------------------------
# TEST 2 — Narrow distance cluster → k not identifiable
# ---------------------------------------------------------------------------

def test_2_narrow_distance_cluster_k_not_identifiable():
    """Many high-quality performances all at 8–12 km.

    Even though there are many contributors, the distance spread is too narrow
    to identify k.  Motor must fall back to prior_k_low_slope_evidence_fallback.
    """
    bench = _benchmark_pool(n=10, with_hr=True)

    # 6 high-quality performances tightly clustered at 8–12 km
    cluster: List[DomainActivity] = []
    cluster_distances = [8_000, 9_000, 10_000, 10_500, 11_000, 12_000]
    for i, dist_m in enumerate(cluster_distances):
        # ~5:20/km
        dur_s = dist_m / 1000.0 * 5.33 * 60.0
        cluster.append(_run(
            days_ago=10 + i * 5,
            distance_m=dist_m,
            duration_s=dur_s,
            avg_hr=162.0 + i,
            max_hr=180.0 + i,
        ))

    activities = bench + cluster
    result = predict_races(activities, TODAY)
    diag = result.race_curve_diagnostics

    assert diag.get("k_identifiable") is False, (
        f"Expected k_identifiable=False for 8–12 km cluster, got {diag.get('k_identifiable')}. "
        f"k_identifiability_score={diag.get('k_identifiability_score'):.4f}"
    )
    assert diag.get("curve_method") == "prior_k_low_slope_evidence_fallback", (
        f"Expected prior_k_low_slope_evidence_fallback, got {diag.get('curve_method')}"
    )
    assert diag.get("curve_k") == pytest.approx(pm.RIEGEL_K, rel=1e-6)

    # Predictions must still be available (curve exists via prior k)
    preds = _preds(result)
    assert any(p.predicted_time_s is not None for p in result.predictions)


# ---------------------------------------------------------------------------
# TEST 3 — Identifiable true curve
# ---------------------------------------------------------------------------

def test_3_identifiable_true_curve_k_learned():
    """High-quality performances spread 5 km / 10 km / semi.

    Motor should learn a data-driven k and k_identifiable must be True.
    The learned k should be within a reasonable range (not forced to 1.06).
    """
    bench = _benchmark_pool(n=10, with_hr=True)

    # True synthetic k = 1.08, anchored at 5 km = 20:00 (1200s)
    k_true = 1.08
    a_true = 1200.0 / (5_000.0 ** k_true)   # ≈ 0.1216
    distances = [5_000.0, 10_000.0, 21_097.5]
    perfs: List[DomainActivity] = []
    for i, dist_m in enumerate(distances):
        dur_s = a_true * (dist_m ** k_true)
        perfs.append(_run(
            days_ago=5 + i * 7,
            distance_m=dist_m,
            duration_s=dur_s,
            avg_hr=158.0 + i * 2,
            max_hr=176.0 + i * 2,
        ))

    activities = bench + perfs
    result = predict_races(activities, TODAY)
    diag = result.race_curve_diagnostics

    assert diag.get("k_identifiable") is True, (
        f"Expected k_identifiable=True for 5K/10K/semi spread, got False. "
        f"score={diag.get('k_identifiability_score')}"
    )
    # Motor should NOT force prior k when data is identifiable
    assert diag.get("curve_method") != "prior_k_low_slope_evidence_fallback", (
        "Motor incorrectly fell back to prior k for an identifiable dataset."
    )
    # Learned k should be in a reasonable range around 1.08
    curve_k = diag.get("curve_k")
    assert curve_k is not None
    assert 1.0 <= curve_k <= 1.25
    # The learned k should be closer to 1.08 than to 1.0 or 1.25
    assert abs(curve_k - k_true) < 0.12, (
        f"Expected k≈{k_true}, got {curve_k:.4f} — deviation too large"
    )


def test_pr216_curve_confidence_floor_keeps_defendable_prediction_low_not_insufficient():
    quality = pm.PerformanceQuality(
        qualified=True,
        score=0.55,
        confidence="low",
        personal_speed_percentile=75.0,
        benchmark_count=8,
        relative_avg_hr=None,
        historical_fcmax=None,
        reason_code="TEST",
    )
    activity = _run(days_ago=160, distance_m=10_000.0, duration_s=3_200.0)
    contributor = pm._CurveObservation(
        activity=activity,
        quality=quality,
        distance_m=10_000.0,
        duration_s=3_200.0,
        days_ago=160,
        base_weight=1.0,
        robust_weight=1.0,
    )
    curve = pm._CurveModel(
        method="robust_weighted_log_fit",
        a=1.0,
        k=1.06,
        fit_quality=0.39,
        k_conflict=True,
        k_fallback_applied=False,
        k_raw=1.06,
        two_point_evidence_strength=None,
        qualified_performance_count=3,
        contributors=(contributor,),
        observed_distance_min=10_000.0,
        observed_distance_max=10_000.0,
    )

    confidence = pm._curve_prediction_confidence(curve, extrapolation_ratio=3.5)

    assert confidence == "low"


# ---------------------------------------------------------------------------
# TEST 4 — True outlier is still under-weighted
# ---------------------------------------------------------------------------

def test_4_true_outlier_still_reduced():
    """A genuinely aberrant observation must still be down-weighted by Huber.

    Quality-aware Huber floors prevent zeroing, but an artefact that is far
    outside the residual distribution should still see its weight reduced.
    This test verifies that the real outlier protection is preserved.
    """
    bench = _benchmark_pool(n=10, with_hr=True)

    # Core coherent performances
    core_perfs = [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_500.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=9, distance_m=10_000.0, duration_s=3_120.0, avg_hr=159.0, max_hr=177.0),
        _run(days_ago=6, distance_m=21_097.5, duration_s=6_900.0, avg_hr=160.0, max_hr=178.0),
    ]
    # Genuine aberrant outlier: 5 km in under 10 minutes (physiologically implausible for the pool)
    outlier = _run(days_ago=5, distance_m=5_000.0, duration_s=580.0, avg_hr=162.0, max_hr=180.0)

    activities_core = bench + core_perfs
    activities_with_outlier = bench + core_perfs + [outlier]

    result_core = predict_races(activities_core, TODAY)
    result_with = predict_races(activities_with_outlier, TODAY)

    # Both must produce predictions
    assert any(p.predicted_time_s is not None for p in result_core.predictions)
    assert any(p.predicted_time_s is not None for p in result_with.predictions)

    # The outlier must have been down-weighted: its robust_weight should be
    # substantially lower than its base_weight.
    diag_with = result_with.race_curve_diagnostics
    contributors = diag_with.get("contributors", [])
    # Find the outlier contribution (5 km, ~580s)
    outlier_contribs = [
        c for c in contributors
        if abs(c["distance_m"] - 5_000.0) < 100 and c["duration_s"] < 650
    ]
    if outlier_contribs:
        oc = outlier_contribs[0]
        ratio = oc["robust_weight"] / oc["base_weight"] if oc["base_weight"] > 0 else 1.0
        assert ratio < 0.90, (
            f"Outlier robust_weight/base_weight={ratio:.3f}: outlier not sufficiently down-weighted. "
            "Quality-aware Huber floor must not bypass genuine outlier protection."
        )

    # The 5K prediction must not be dominated by the impossible outlier time
    preds_core = _preds(result_core)
    preds_with = _preds(result_with)
    t5k_core = preds_core["5K"].predicted_time_s
    t5k_with = preds_with["5K"].predicted_time_s
    if t5k_core is not None and t5k_with is not None:
        # Adding the outlier should not produce a wildly faster prediction
        assert t5k_with > 500.0, (
            f"5K prediction collapsed to {t5k_with:.0f}s — outlier dominated the curve."
        )


# ---------------------------------------------------------------------------
# TEST 5 — Speed-only pool still produces predictions via prior k
# ---------------------------------------------------------------------------

def test_5_speedonly_pool_still_predicts_via_prior_k():
    """A pool of speed-only low-confidence activities must still produce
    predictions (via prior k fallback), but must NOT claim k_identifiable=True.
    """
    bench = _benchmark_pool(n=10, with_hr=False)   # no HR → speed-only benchmarks

    # Several speed-only qualified performances at various distances
    solo_perfs: List[DomainActivity] = []
    for dist_m, days, pace_minkm in [
        (6_000.0, 20, 6.1),
        (10_000.0, 25, 6.2),
        (15_000.0, 30, 6.3),
    ]:
        dur_s = dist_m / 1000.0 * pace_minkm * 60.0
        solo_perfs.append(_run(days_ago=days, distance_m=dist_m, duration_s=dur_s))

    activities = bench + solo_perfs
    result = predict_races(activities, TODAY)
    diag = result.race_curve_diagnostics

    # k_identifiable must be False (no high/medium quality data)
    assert diag.get("k_identifiable") is False, (
        "Speed-only pool must not be identifiable for k. "
        f"Got k_identifiable={diag.get('k_identifiable')}, method={diag.get('curve_method')}"
    )

    # But predictions should still be possible via prior k
    preds = _preds(result)
    has_prediction = any(p.predicted_time_s is not None for p in result.predictions)
    # If curve is available, predictions exist; if no qualified performances, curve may be None
    if diag.get("curve_method") is not None:
        # Curve was built; predictions must work for at least some distances
        assert has_prediction, (
            "Speed-only pool with curve should still produce at least one prediction."
        )


# ---------------------------------------------------------------------------
# TEST 6 — No look-ahead
# ---------------------------------------------------------------------------

def test_6_no_lookahead():
    """A future activity (start_time > TODAY) must not affect any output."""
    bench = _benchmark_pool(n=10, with_hr=True)
    core_perfs = [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_500.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=9, distance_m=10_000.0, duration_s=3_120.0, avg_hr=159.0, max_hr=177.0),
        _run(days_ago=6, distance_m=21_097.5, duration_s=6_900.0, avg_hr=160.0, max_hr=178.0),
    ]

    # Future activity: extremely fast performance — must be ignored
    future = DomainActivity(
        activity_type="running",
        start_time=(TODAY + timedelta(days=5)).isoformat(),
        distance_m=42_195.0,
        duration_s=7_200.0,   # 2h marathon — impossibly good
        average_hr=165.0,
        max_hr=182.0,
    )

    activities_base = bench + core_perfs
    activities_with_future = bench + core_perfs + [future]

    result_base = predict_races(activities_base, TODAY)
    result_with = predict_races(activities_with_future, TODAY)

    diag_base = result_base.race_curve_diagnostics
    diag_with = result_with.race_curve_diagnostics

    assert diag_base["curve_k"] == diag_with["curve_k"], "Future activity affected curve_k"
    assert diag_base["curve_a"] == diag_with["curve_a"], "Future activity affected curve_a"
    assert diag_base["curve_method"] == diag_with["curve_method"], "Future activity affected curve_method"
    assert diag_base.get("k_identifiable") == diag_with.get("k_identifiable"), \
        "Future activity affected k_identifiable"

    preds_base = _preds(result_base)
    preds_with = _preds(result_with)
    for label in RACE_DISTANCES_M:
        tb = preds_base[label].predicted_time_s
        tw = preds_with[label].predicted_time_s
        assert tb == tw, f"Future activity changed {label} prediction: {tb} → {tw}"


# ---------------------------------------------------------------------------
# TEST 7 — Input-order invariance
# ---------------------------------------------------------------------------

def test_7_input_order_invariant():
    """Shuffling the activity list must not change any output."""
    bench = _benchmark_pool(n=10, with_hr=True)
    core_perfs = [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_500.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=9, distance_m=10_000.0, duration_s=3_120.0, avg_hr=159.0, max_hr=177.0),
        _run(days_ago=6, distance_m=21_097.5, duration_s=6_900.0, avg_hr=160.0, max_hr=178.0),
    ]
    activities = bench + core_perfs

    result_orig = predict_races(activities, TODAY)

    rng = random.Random(42)
    shuffled = activities[:]
    rng.shuffle(shuffled)
    result_shuf = predict_races(shuffled, TODAY)

    diag_orig = result_orig.race_curve_diagnostics
    diag_shuf = result_shuf.race_curve_diagnostics

    assert diag_orig["curve_k"] == diag_shuf["curve_k"], "Order changed curve_k"
    assert diag_orig["curve_a"] == diag_shuf["curve_a"], "Order changed curve_a"
    assert diag_orig["curve_method"] == diag_shuf["curve_method"], "Order changed curve_method"
    assert diag_orig.get("k_identifiable") == diag_shuf.get("k_identifiable"), \
        "Order changed k_identifiable"

    preds_orig = _preds(result_orig)
    preds_shuf = _preds(result_shuf)
    for label in RACE_DISTANCES_M:
        to = preds_orig[label].predicted_time_s
        ts = preds_shuf[label].predicted_time_s
        assert to == ts, f"Order changed {label} prediction: {to} → {ts}"


# ---------------------------------------------------------------------------
# TEST 8 — VMA independence
# ---------------------------------------------------------------------------

def test_8_vma_independence():
    """Varying VMA output (by changing the HR data used for VMA estimation)
    must not change predictions, curve_k, curve_a, curve_method, or
    identifiability diagnostics.

    Race predictions depend on qualified performances and the performance curve,
    NOT on VMA.

    VMA activities are deliberately at lower speed than the benchmark pool so
    that they cannot qualify as performance observations.  The only difference
    between the two runs is the presence or absence of HR on those slow VMA
    activities, which affects estimate_vma() but not the performance curve.
    """
    bench = _benchmark_pool(n=10, with_hr=True)
    core_perfs = [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_500.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=9, distance_m=10_000.0, duration_s=3_120.0, avg_hr=159.0, max_hr=177.0),
        _run(days_ago=6, distance_m=21_097.5, duration_s=6_900.0, avg_hr=160.0, max_hr=178.0),
    ]

    # VMA activities: slow enough (8.2 km/h → 0th percentile vs benchmark pool)
    # so they CANNOT qualify as performances; they contribute only to VMA.
    # Benchmark pool speed ≈ 8.73–8.78 km/h → 8.2 km/h is below all benchmarks.
    _vma_dur_s = round(10_000.0 / (8.2 / 3.6))   # ≈ 4390s at 8.2 km/h

    # Good HR: wide HR spread → VMA model succeeds
    # max_hr=162 kept ≤ benchmark pool max (167) so FCmax for core perfs is unchanged
    vma_acts_good = [
        _run(days_ago=d, distance_m=10_000.0, duration_s=_vma_dur_s,
             avg_hr=125.0 + d * 1.5, max_hr=162)
        for d in range(3, 40, 6)
    ]
    # No HR: VMA model will fail or give different estimate
    vma_acts_degraded = [
        _run(days_ago=d, distance_m=10_000.0, duration_s=_vma_dur_s)
        for d in range(3, 40, 6)
    ]

    acts_good_vma = bench + core_perfs + vma_acts_good
    acts_poor_vma = bench + core_perfs + vma_acts_degraded

    result_good = predict_races(acts_good_vma, TODAY)
    result_poor = predict_races(acts_poor_vma, TODAY)

    # VMA may legitimately differ
    vma_good = result_good.athlete_profile.get("estimated_vma")
    vma_poor = result_poor.athlete_profile.get("estimated_vma")

    diag_good = result_good.race_curve_diagnostics
    diag_poor = result_poor.race_curve_diagnostics

    # These must be identical regardless of VMA
    assert diag_good["curve_k"] == diag_poor["curve_k"], \
        f"VMA change affected curve_k: {diag_good['curve_k']} → {diag_poor['curve_k']}"
    assert diag_good["curve_a"] == diag_poor["curve_a"], \
        f"VMA change affected curve_a: {diag_good['curve_a']} → {diag_poor['curve_a']}"
    assert diag_good["curve_method"] == diag_poor["curve_method"], \
        "VMA change affected curve_method"
    assert diag_good.get("k_identifiable") == diag_poor.get("k_identifiable"), \
        "VMA change affected k_identifiable"

    preds_good = _preds(result_good)
    preds_poor = _preds(result_poor)
    for label in RACE_DISTANCES_M:
        tg = preds_good[label].predicted_time_s
        tp = preds_poor[label].predicted_time_s
        assert tg == tp, f"VMA change affected {label} prediction: {tg} → {tp}"


# ---------------------------------------------------------------------------
# TEST 9 — k_conflict has priority over low-identifiability (C190 invariant)
# ---------------------------------------------------------------------------

def test_9_k_conflict_has_priority_over_low_identifiability():
    """N>=3 dataset where k_raw is out of [1.0, 1.25] AND k_identifiable is False.

    The fit produces a steep k > 1.25 from a narrow distance cluster (9–11 km).
    Both conditions are simultaneously true, but k_conflict must take priority.

    Expected:
      k_conflict == True
      k_fallback_applied == True
      curve_method == "prior_k_conflict_fallback"
      curve_k == 1.06
      k_raw preserved out of range (> 1.25)
    """
    bench = _benchmark_pool(n=7, with_hr=True)

    # 3 performances in a narrow 9–11 km cluster with steeply increasing times
    # (pace degrades rapidly with distance) → robust fit yields k_raw >> 1.25.
    # All are faster than the benchmark pool so they qualify as performances.
    # Narrow distance spread keeps k_identifiability_score < K_IDENTIFIABILITY_MIN_WX_VAR.
    steep_perfs: List[DomainActivity] = [
        _run(days_ago=30, distance_m=9_000.0, duration_s=2_700.0, avg_hr=158.0, max_hr=178.0),
        _run(days_ago=20, distance_m=10_000.0, duration_s=3_300.0, avg_hr=160.0, max_hr=180.0),
        _run(days_ago=10, distance_m=11_000.0, duration_s=4_000.0, avg_hr=162.0, max_hr=182.0),
    ]

    activities = bench + steep_perfs
    result = predict_races(activities, TODAY)
    diag = result.race_curve_diagnostics

    # k_raw must be preserved (out of range)
    k_raw = diag.get("curve_k_raw")
    assert k_raw is not None, "k_raw must be present"
    assert k_raw > pm.CURVE_K_MAX or k_raw < pm.CURVE_K_MIN, (
        f"Expected k_raw outside [{pm.CURVE_K_MIN}, {pm.CURVE_K_MAX}], got {k_raw:.4f}"
    )

    # Conflict must be detected (from k_raw, not from any replaced slope)
    assert diag.get("k_conflict") is True, (
        f"Expected k_conflict=True, got {diag.get('k_conflict')}. "
        f"k_raw={k_raw:.4f}, curve_method={diag.get('curve_method')}"
    )

    # Conflict takes priority; method must be prior_k_conflict_fallback
    assert diag.get("curve_method") == "prior_k_conflict_fallback", (
        f"Expected prior_k_conflict_fallback, got {diag.get('curve_method')}"
    )
    assert diag.get("curve_k") == pytest.approx(pm.RIEGEL_K, rel=1e-6)
    assert diag.get("k_fallback_applied") is True

    # k_identifiable may be False (observable) but must not mask the conflict
    assert diag.get("k_identifiable") is False, (
        "Expected k_identifiable=False for this narrow cluster"
    )


# ---------------------------------------------------------------------------
# TEST 10 — k_raw in range + low identifiability → identifiability fallback
# ---------------------------------------------------------------------------

def test_10_k_raw_in_range_low_identifiability_fallback():
    """N>=3 dataset where k_raw is within [1.0, 1.25] but k_identifiable is False.

    Narrow distance cluster but Riegel-consistent times keep k_raw ≈ 1.06.
    No conflict; identifiability fallback should apply.

    Expected:
      k_conflict == False
      curve_method == "prior_k_low_slope_evidence_fallback"
      curve_k == 1.06
    """
    bench = _benchmark_pool(n=7, with_hr=True)

    # 3 performances in a narrow 9–11 km cluster with Riegel-consistent times
    # (k≈1.06) → k_raw remains within [1.0, 1.25]. All faster than benchmark pool.
    # Narrow distance spread keeps k_identifiability_score < K_IDENTIFIABILITY_MIN_WX_VAR.
    k_target = pm.RIEGEL_K
    a_anchor = 2700.0 / (9_000.0 ** k_target)
    consistent_perfs: List[DomainActivity] = []
    for dist_m, days in [(9_000.0, 30), (10_000.0, 20), (11_000.0, 10)]:
        dur_s = a_anchor * (dist_m ** k_target)
        consistent_perfs.append(
            _run(days_ago=days, distance_m=dist_m, duration_s=dur_s,
                 avg_hr=158.0, max_hr=178.0)
        )

    activities = bench + consistent_perfs
    result = predict_races(activities, TODAY)
    diag = result.race_curve_diagnostics

    # No conflict expected
    assert diag.get("k_conflict") is False, (
        f"Expected k_conflict=False, got {diag.get('k_conflict')}. "
        f"k_raw={diag.get('curve_k_raw')}, curve_method={diag.get('curve_method')}"
    )

    # Identifiability fallback must apply (narrow distance spread)
    assert diag.get("k_identifiable") is False, (
        f"Expected k_identifiable=False for narrow cluster, got {diag.get('k_identifiable')}"
    )
    assert diag.get("curve_method") == "prior_k_low_slope_evidence_fallback", (
        f"Expected prior_k_low_slope_evidence_fallback, got {diag.get('curve_method')}"
    )
    assert diag.get("curve_k") == pytest.approx(pm.RIEGEL_K, rel=1e-6)
