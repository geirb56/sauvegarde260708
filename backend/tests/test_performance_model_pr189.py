from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Optional

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import RACE_DISTANCES_M, evaluate_performance_quality, predict_races

TODAY = date(2026, 8, 24)


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


def _benchmark_runs(with_hr: bool = True) -> list[DomainActivity]:
    hrs = [125.0, 128.0, 131.0, 134.0, 137.0, 140.0] if with_hr else [None] * 6
    maxs = [160.0, 162.0, 164.0, 166.0, 168.0, 170.0] if with_hr else [None] * 6
    rows = [
        (85, 8_000.0, 3_300.0),
        (72, 9_000.0, 3_700.0),
        (60, 10_000.0, 4_150.0),
        (48, 11_000.0, 4_600.0),
        (36, 12_000.0, 5_050.0),
        (24, 13_000.0, 5_500.0),
    ]
    out = []
    for idx, (d, dist, dur) in enumerate(rows):
        out.append(_run(days_ago=d, distance_m=dist, duration_s=dur, avg_hr=hrs[idx], max_hr=maxs[idx]))
    return out


def _pace_s_per_km(time_s: float, dist_m: float) -> float:
    return time_s / (dist_m / 1000.0)


def _pred_by_label(result):
    return {p.distance_label: p for p in result.predictions}


def _assert_monotonic(preds):
    labels = ["5K", "10K", "Semi", "Marathon"]
    paces = []
    for lbl in labels:
        pred = preds[lbl]
        assert pred.predicted_time_s is not None
        paces.append(_pace_s_per_km(pred.predicted_time_s, RACE_DISTANCES_M[lbl]))
    assert paces[0] <= paces[1] <= paces[2] <= paces[3]


def test_a_single_qualified_10k_uses_single_curve_and_riegel():
    acts = _benchmark_runs() + [
        _run(days_ago=5, distance_m=10_000.0, duration_s=3_000.0, avg_hr=156.0, max_hr=175.0)
    ]
    result = predict_races(acts, TODAY)
    preds = _pred_by_label(result)

    _assert_monotonic(preds)
    assert result.race_curve_diagnostics["curve_method"] == "single_performance_riegel"
    assert result.race_curve_diagnostics["curve_k"] == pytest.approx(1.06, rel=1e-6)

    source_time = 3_000.0
    source_dist = 10_000.0
    for label, target in RACE_DISTANCES_M.items():
        expected = source_time * (target / source_dist) ** 1.06
        assert preds[label].predicted_time_s == pytest.approx(round(expected, 1), abs=0.11)


def test_b_two_coherent_qualified_performances_fit_common_curve():
    acts = _benchmark_runs() + [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_470.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=6, distance_m=10_000.0, duration_s=3_080.0, avg_hr=160.0, max_hr=178.0),
    ]
    result = predict_races(acts, TODAY)
    preds = _pred_by_label(result)

    _assert_monotonic(preds)
    assert result.race_curve_diagnostics["contributors_count"] >= 2
    assert 1.0 <= result.race_curve_diagnostics["curve_k"] <= 1.25


def test_c_crossing_sources_case_is_monotonic_from_raw_curve():
    acts = _benchmark_runs() + [
        _run(days_ago=12, distance_m=5_000.0, duration_s=1_360.0, avg_hr=162.0, max_hr=178.0),
        _run(days_ago=9, distance_m=18_000.0, duration_s=6_250.0, avg_hr=154.0, max_hr=176.0),
    ]
    result = predict_races(acts, TODAY)
    preds = _pred_by_label(result)

    _assert_monotonic(preds)
    a = result.race_curve_diagnostics["curve_a"]
    k = result.race_curve_diagnostics["curve_k"]
    for label, dist in RACE_DISTANCES_M.items():
        expected = a * (dist ** k)
        assert preds[label].predicted_time_s == pytest.approx(round(expected, 1), abs=0.11)


def test_d_recency_affects_common_curve_without_per_target_splitting():
    old_strong = _run(days_ago=80, distance_m=10_000.0, duration_s=2_880.0, avg_hr=164.0, max_hr=180.0)
    recent_slightly_weaker = _run(days_ago=4, distance_m=10_000.0, duration_s=3_020.0, avg_hr=160.0, max_hr=178.0)
    anchor = _run(days_ago=10, distance_m=5_000.0, duration_s=1_500.0, avg_hr=159.0, max_hr=178.0)

    base = predict_races(_benchmark_runs() + [old_strong, anchor], TODAY)
    with_recent = predict_races(_benchmark_runs() + [old_strong, anchor, recent_slightly_weaker], TODAY)

    b10 = _pred_by_label(base)["10K"].predicted_time_s
    r10 = _pred_by_label(with_recent)["10K"].predicted_time_s
    assert b10 is not None and r10 is not None
    assert r10 != b10
    assert with_recent.race_curve_diagnostics["curve_method"] in {
        "weighted_log_fit",
        "robust_weighted_log_fit",
        "prior_k_conflict_fallback",
    }


def test_e_outlier_does_not_dominate_curve():
    core = _benchmark_runs() + [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_500.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=9, distance_m=10_000.0, duration_s=3_120.0, avg_hr=159.0, max_hr=177.0),
        _run(days_ago=6, distance_m=21_097.5, duration_s=6_900.0, avg_hr=160.0, max_hr=178.0),
    ]
    outlier = _run(days_ago=5, distance_m=5_000.0, duration_s=1_120.0, avg_hr=164.0, max_hr=179.0)

    base = predict_races(core, TODAY)
    with_outlier = predict_races(core + [outlier], TODAY)

    b10 = _pred_by_label(base)["10K"].predicted_time_s
    o10 = _pred_by_label(with_outlier)["10K"].predicted_time_s
    assert b10 is not None and o10 is not None
    assert abs(o10 - b10) / b10 < 0.20


def test_f_input_order_invariance_for_curve_and_predictions():
    acts = _benchmark_runs() + [
        _run(days_ago=14, distance_m=5_000.0, duration_s=1_490.0, avg_hr=159.0, max_hr=177.0),
        _run(days_ago=7, distance_m=10_000.0, duration_s=3_100.0, avg_hr=160.0, max_hr=178.0),
        _run(days_ago=5, distance_m=15_000.0, duration_s=4_980.0, avg_hr=158.0, max_hr=176.0),
    ]
    shuffled = list(reversed(acts))

    forward = predict_races(acts, TODAY)
    backward = predict_races(shuffled, TODAY)

    assert forward.race_curve_diagnostics == backward.race_curve_diagnostics
    assert forward.predictions == backward.predictions


def test_g_future_lookahead_is_disabled_for_curve():
    base_acts = _benchmark_runs() + [
        _run(days_ago=9, distance_m=10_000.0, duration_s=3_080.0, avg_hr=160.0, max_hr=178.0),
        _run(days_ago=6, distance_m=5_000.0, duration_s=1_495.0, avg_hr=159.0, max_hr=177.0),
    ]
    future = DomainActivity(
        activity_type="running",
        start_time=(TODAY + timedelta(days=2)).isoformat(),
        distance_m=10_000.0,
        duration_s=2_700.0,
        average_hr=168.0,
        max_hr=184.0,
    )

    a = predict_races(base_acts, TODAY)
    b = predict_races(base_acts + [future], TODAY)

    assert a.race_curve_diagnostics == b.race_curve_diagnostics
    assert a.predictions == b.predictions


def test_h_non_qualified_activity_contribution_is_zero():
    candidate = _run(days_ago=7, distance_m=10_000.0, duration_s=2_980.0, avg_hr=120.0, max_hr=170.0)
    acts = _benchmark_runs() + [candidate]
    quality = evaluate_performance_quality(candidate, acts, TODAY)
    assert quality.qualified is False

    baseline = predict_races(_benchmark_runs(), TODAY)
    with_non_qualified = predict_races(acts, TODAY)
    assert baseline.race_curve_diagnostics == with_non_qualified.race_curve_diagnostics
    base_preds = _pred_by_label(baseline)
    test_preds = _pred_by_label(with_non_qualified)
    for label in [*RACE_DISTANCES_M.keys()]:
        assert base_preds[label].predicted_time_s == test_preds[label].predicted_time_s
        assert base_preds[label].confidence == test_preds[label].confidence


def test_i_speed_only_qualification_feeds_curve():
    acts = _benchmark_runs(with_hr=False) + [
        _run(days_ago=6, distance_m=10_000.0, duration_s=2_980.0)
    ]
    result = predict_races(acts, TODAY)
    preds = _pred_by_label(result)

    assert result.race_curve_diagnostics["qualified_performance_count"] >= 1
    assert preds["10K"].predicted_time_s is not None
    assert preds["10K"].source_relative_hr is None


def test_j_marathon_only_extrapolation_is_symmetric_and_visible():
    acts = _benchmark_runs() + [
        _run(days_ago=5, distance_m=42_195.0, duration_s=14_700.0, avg_hr=158.0, max_hr=178.0)
    ]
    result = predict_races(acts, TODAY)
    preds = _pred_by_label(result)

    assert preds["5K"].predicted_time_s is None
    assert preds["5K"].extrapolation_ratio == pytest.approx(8.439, rel=1e-3)
    assert preds["10K"].predicted_time_s is not None
    assert preds["10K"].extrapolation_ratio == pytest.approx(4.2195, rel=1e-4)


def test_k_5k_only_marathon_not_returned_when_extrapolation_excessive():
    acts = _benchmark_runs() + [
        _run(days_ago=5, distance_m=5_000.0, duration_s=1_460.0, avg_hr=160.0, max_hr=178.0)
    ]
    result = predict_races(acts, TODAY)
    preds = _pred_by_label(result)

    assert preds["Marathon"].predicted_time_s is None
    assert preds["Marathon"].confidence == "insufficient"
    assert preds["Marathon"].extrapolation_ratio == pytest.approx(8.439, rel=1e-3)


def _make_deterministic_scenario(seed: int) -> list[DomainActivity]:
    rnd = random.Random(seed)
    acts = _benchmark_runs()
    n = 1 + (seed % 4)
    base_a = 0.155 + (seed % 5) * 0.008
    base_k = 1.03 + (seed % 6) * 0.01
    distances = [5_000.0, 8_000.0, 10_000.0, 15_000.0, 21_097.5, 30_000.0]
    acts.append(
        _run(
            days_ago=3,
            distance_m=10_000.0,
            duration_s=round(base_a * (10_000.0 ** base_k), 1),
            avg_hr=158.0,
            max_hr=178.0,
        )
    )
    for idx in range(n):
        dist = distances[(seed + idx * 2) % len(distances)]
        noise = 1.0 + rnd.uniform(-0.03, 0.03)
        dur = base_a * (dist ** base_k) * noise
        acts.append(
            _run(
                days_ago=3 + idx * 3,
                distance_m=dist,
                duration_s=round(dur, 1),
                avg_hr=157.0 + (idx % 3),
                max_hr=178.0,
            )
        )
    return acts


def test_l_monotonicity_property_over_120_deterministic_scenarios():
    failures = 0
    complete = 0
    for seed in range(120):
        result = predict_races(_make_deterministic_scenario(seed), TODAY)
        preds = _pred_by_label(result)
        if any(preds[l].predicted_time_s is None for l in ["5K", "10K", "Semi", "Marathon"]):
            continue
        complete += 1
        paces = [
            _pace_s_per_km(preds["5K"].predicted_time_s, RACE_DISTANCES_M["5K"]),
            _pace_s_per_km(preds["10K"].predicted_time_s, RACE_DISTANCES_M["10K"]),
            _pace_s_per_km(preds["Semi"].predicted_time_s, RACE_DISTANCES_M["Semi"]),
            _pace_s_per_km(preds["Marathon"].predicted_time_s, RACE_DISTANCES_M["Marathon"]),
        ]
        if not (paces[0] <= paces[1] <= paces[2] <= paces[3]):
            failures += 1
    assert complete >= 100
    assert failures == 0


def test_m_stability_with_coherent_added_performance():
    base = _benchmark_runs() + [
        _run(days_ago=15, distance_m=5_000.0, duration_s=1_500.0, avg_hr=158.0, max_hr=176.0),
        _run(days_ago=8, distance_m=10_000.0, duration_s=3_120.0, avg_hr=159.0, max_hr=177.0),
    ]
    added = _run(days_ago=4, distance_m=15_000.0, duration_s=4_900.0, avg_hr=160.0, max_hr=178.0)

    r0 = predict_races(base, TODAY)
    r1 = predict_races(base + [added], TODAY)
    p0 = _pred_by_label(r0)
    p1 = _pred_by_label(r1)

    for label in ["5K", "10K", "Semi"]:
        assert p0[label].predicted_time_s is not None and p1[label].predicted_time_s is not None
        rel = abs(p1[label].predicted_time_s - p0[label].predicted_time_s) / p0[label].predicted_time_s
        assert rel < 0.15
