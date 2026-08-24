"""PR #191 — slope-evidence separation for the Performance Curve.

QUALIFIED (contributes to level A) vs SLOPE-EVIDENCE (defensible for learning k).
Only PR #188 "high" confidence observations are slope evidence; a data-driven k
requires >= K_SLOPE_EVIDENCE_MIN_COUNT high observations with sufficient distance
spread, otherwise k falls back to RIEGEL_K while A still uses all qualified points.
"""
import math
from datetime import date, timedelta

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    _build_performance_curve, PerformanceQuality, RIEGEL_K,
    K_SLOPE_EVIDENCE_MIN_COUNT,
)

REF = date(2026, 8, 24)


def _act(dist_km, dur_s, days_ago):
    d = REF - timedelta(days=days_ago)
    return DomainActivity(
        activity_type="running",
        start_time=d.isoformat(),
        distance_m=dist_km * 1000.0,
        duration_s=dur_s,
        moving_duration_s=dur_s,
        average_hr=150.0,
        max_hr=175.0,
    )


def _q(confidence, score=1.0, pct=100.0, rel=0.90):
    return PerformanceQuality(
        qualified=True, score=score, confidence=confidence,
        personal_speed_percentile=pct, benchmark_count=10,
        relative_avg_hr=rel, historical_fcmax=182.0, reason_code="ok",
    )


def _time_for(A, dist_km, k):
    return A * (dist_km * 1000.0) ** k


# --------------------------------------------------------------------------
# TEST A — runtime pathology: many flat sustained runs + 1 true short perf.
# The wide high+medium spread must NOT auto-learn a flat k anymore.
# --------------------------------------------------------------------------
def test_a_pathology_single_high_falls_back_to_prior():
    pool = [
        (_act(10.0, 3020, 253), _q("high")),          # the only real perf
        (_act(7.07, 2504, 227), _q("medium", 0.89, 85, 0.89)),
        (_act(20.63, 7604, 177), _q("medium", 0.86, 75, 0.89)),
        (_act(6.06, 1998, 542), _q("low", 1.0, 100, None)),
        (_act(21.27, 7352, 344), _q("low", 1.0, 100, None)),
        (_act(8.79, 3232, 602), _q("low", 1.0, 100, None)),
    ]
    curve = _build_performance_curve(pool, REF)
    assert curve.slope_evidence_count == 1
    assert curve.slope_evidence_count < K_SLOPE_EVIDENCE_MIN_COUNT
    assert curve.k_fallback_applied is True
    assert curve.method == "prior_k_low_slope_evidence_fallback"
    assert curve.k == RIEGEL_K
    assert curve.k_identifiability_reason == "insufficient_slope_evidence_count"
    # A still uses ALL qualified observations
    assert curve.qualified_performance_count == 6
    # k_raw retains the data-driven (flat) slope for diagnostics
    assert curve.k_raw is not None and curve.k_raw < 1.05


# --------------------------------------------------------------------------
# TEST B — true multi-distance performances following a known k != 1.06.
# The engine MUST learn the synthetic k (not collapse to Riegel 1.06).
# --------------------------------------------------------------------------
def test_b_true_multidistance_learns_k():
    A, k_true = 0.9, 1.11
    pool = [
        (_act(5.0, _time_for(A, 5.0, k_true), 20), _q("high")),
        (_act(10.0, _time_for(A, 10.0, k_true), 25), _q("high")),
        (_act(21.0975, _time_for(A, 21.0975, k_true), 30), _q("high")),
    ]
    curve = _build_performance_curve(pool, REF)
    assert curve.slope_evidence_count == 3
    assert curve.method == "robust_weighted_log_fit"
    assert curve.k_fallback_applied is False
    assert curve.k_identifiable is True
    assert abs(curve.k - k_true) < 0.03, curve.k
    assert abs(curve.k - RIEGEL_K) > 0.03  # NOT permanently Riegel


# --------------------------------------------------------------------------
# TEST C — excellent level around 10K only: high evidence but no spread.
# A is estimated; k stays prior for lack of multi-distance slope evidence.
# --------------------------------------------------------------------------
def test_c_10k_cluster_keeps_prior_k():
    pool = [
        (_act(9.8, 2950, 20), _q("high")),
        (_act(10.0, 3010, 25), _q("high")),
        (_act(10.2, 3080, 30), _q("high")),
    ]
    curve = _build_performance_curve(pool, REF)
    assert curve.slope_evidence_count == 3
    assert curve.k == RIEGEL_K
    assert curve.k_fallback_applied is True
    assert curve.method == "prior_k_low_slope_evidence_fallback"
    assert curve.k_identifiability_reason == "insufficient_slope_evidence_spread"
    assert curve.a > 0  # level still estimated


# --------------------------------------------------------------------------
# TEST D — speed-only (low) observations support A but never define k alone.
# --------------------------------------------------------------------------
def test_d_speed_only_cannot_define_k():
    pool = [
        (_act(6.0, 1980, 100), _q("low", 1.0, 100, None)),
        (_act(12.0, 4200, 150), _q("low", 1.0, 100, None)),
        (_act(20.0, 7400, 200), _q("low", 1.0, 100, None)),
    ]
    curve = _build_performance_curve(pool, REF)
    assert curve.slope_evidence_count == 0
    assert curve.k == RIEGEL_K
    assert curve.k_fallback_applied is True
    assert curve.qualified_performance_count == 3  # A uses them


# --------------------------------------------------------------------------
# TEST E — outlier protection preserved: a single aberrant high point among
# consistent slope-evidence performances must not dominate k.
# --------------------------------------------------------------------------
def test_e_outlier_does_not_break_curve():
    A, k_true = 0.9, 1.10
    pool = [
        (_act(5.0, _time_for(A, 5.0, k_true), 20), _q("high")),
        (_act(10.0, _time_for(A, 10.0, k_true), 25), _q("high")),
        (_act(15.0, _time_for(A, 15.0, k_true), 28), _q("high")),
        (_act(21.0975, _time_for(A, 21.0975, k_true), 30), _q("high")),
        (_act(12.0, 1500, 26), _q("high")),  # absurdly fast (GPS glitch)
    ]
    curve = _build_performance_curve(pool, REF)
    # k should stay near the true slope, not be dragged by the outlier
    assert abs(curve.k - k_true) < 0.10, curve.k


# --------------------------------------------------------------------------
# TEST G — input-order invariance.
# --------------------------------------------------------------------------
def test_g_input_order_invariant():
    A, k_true = 0.9, 1.09
    base = [
        (_act(5.0, _time_for(A, 5.0, k_true), 20), _q("high")),
        (_act(10.0, _time_for(A, 10.0, k_true), 25), _q("high")),
        (_act(21.0975, _time_for(A, 21.0975, k_true), 30), _q("high")),
    ]
    c1 = _build_performance_curve(base, REF)
    c2 = _build_performance_curve(list(reversed(base)), REF)
    assert abs(c1.k - c2.k) < 1e-9
    assert abs(c1.a - c2.a) < 1e-6


# --------------------------------------------------------------------------
# TEST F — no-lookahead: future activities are ignored by the curve builder.
# --------------------------------------------------------------------------
def test_f_no_lookahead():
    future = DomainActivity(
        activity_type="running", start_time=(REF + timedelta(days=10)).isoformat(),
        distance_m=10000.0, duration_s=2400.0, moving_duration_s=2400.0,
        average_hr=150.0, max_hr=175.0,
    )
    pool = [
        (future, _q("high")),
        (_act(5.0, 1500, 20), _q("high")),
        (_act(10.0, 3200, 25), _q("high")),
    ]
    curve = _build_performance_curve(pool, REF)
    # future point excluded -> only 2 slope-evidence contributors remain
    assert all(c.days_ago >= 0 for c in curve.contributors)
