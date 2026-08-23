"""PR185 — Performance Model V2 base tests.

Tests cover the core HR-speed VMA model, FCmax robustness,
Riegel predictions, and independence between VMA and Predictions.

Comments referring to "explicit performance", "threshold speed", or
"dual path" have been removed as SOURCE A is no longer part of the model.

Run from the backend directory:
    python -m pytest tests/test_performance_model_pr185.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    RIEGEL_K,
    VMA_WINDOW_DAYS,
    estimate_vma,
    get_race_predictions,
    _performance_duration_s,
    _robust_fcmax,
    _riegel_predict,
    _speed_kmh,
)

REF = date(2026, 8, 6)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _run(
    *,
    date_str: str = "2026-08-01",
    distance_m: float = 10000.0,
    duration_s: float = 3600.0,
    moving_duration_s: float | None = None,
    average_hr: float | None = 150.0,
    max_hr: float | None = 170.0,
    activity_type: str = "running",
    elevation_gain_m: float | None = None,
) -> DomainActivity:
    return DomainActivity(
        activity_type=activity_type,
        start_time=date_str,
        distance_m=distance_m,
        duration_s=duration_s,
        moving_duration_s=moving_duration_s,
        average_hr=average_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
    )


def _regression_dataset() -> List[DomainActivity]:
    """Return a minimal valid HR-speed dataset for regression tests.

    5 runs at different intensities spread over the 42-day window.
    FCmax = 190 from max_hr values.
    """
    return [
        _run(date_str="2026-08-01", distance_m=10000, duration_s=3600, average_hr=140, max_hr=190),
        _run(date_str="2026-07-25", distance_m=10000, duration_s=3300, average_hr=155, max_hr=185),
        _run(date_str="2026-07-18", distance_m=10000, duration_s=3000, average_hr=168, max_hr=188),
        _run(date_str="2026-07-10", distance_m=10000, duration_s=2800, average_hr=178, max_hr=190),
        _run(date_str="2026-06-30", distance_m=10000, duration_s=2600, average_hr=183, max_hr=189),
    ]


# ---------------------------------------------------------------------------
# _performance_duration_s
# ---------------------------------------------------------------------------


class TestPerformanceDurationS:
    def test_prefers_moving_duration_when_valid(self):
        act = _run(duration_s=3600, moving_duration_s=3000)
        assert _performance_duration_s(act) == 3000.0

    def test_fallback_when_moving_absent(self):
        act = _run(duration_s=3600, moving_duration_s=None)
        assert _performance_duration_s(act) == 3600.0

    def test_fallback_when_moving_zero(self):
        act = DomainActivity(
            activity_type="running",
            duration_s=3600,
            moving_duration_s=0.0,
        )
        assert _performance_duration_s(act) == 3600.0

    def test_fallback_when_moving_exceeds_duration(self):
        act = DomainActivity(
            activity_type="running",
            duration_s=3600,
            moving_duration_s=4000.0,
        )
        assert _performance_duration_s(act) == 3600.0

    def test_returns_none_when_both_absent(self):
        act = DomainActivity(activity_type="running")
        assert _performance_duration_s(act) is None


# ---------------------------------------------------------------------------
# _speed_kmh
# ---------------------------------------------------------------------------


class TestSpeedKmh:
    def test_uses_moving_duration_for_speed(self):
        # 10 km in 3000 s → 12 km/h
        act = _run(distance_m=10000, duration_s=3600, moving_duration_s=3000)
        assert _speed_kmh(act) == pytest.approx(12.0, abs=0.01)

    def test_fallback_speed_when_no_moving_duration(self):
        # 10 km in 3600 s → 10 km/h
        act = _run(distance_m=10000, duration_s=3600, moving_duration_s=None)
        assert _speed_kmh(act) == pytest.approx(10.0, abs=0.01)

    def test_returns_none_without_duration(self):
        act = DomainActivity(activity_type="running", distance_m=10000)
        assert _speed_kmh(act) is None


# ---------------------------------------------------------------------------
# _robust_fcmax
# ---------------------------------------------------------------------------


class TestRobustFcmax:
    def test_no_activities_returns_none(self):
        assert _robust_fcmax([]) is None

    def test_single_activity(self):
        act = _run(max_hr=185)
        assert _robust_fcmax([act]) == 185.0

    def test_n3_no_outlier_returns_highest(self):
        acts = [_run(max_hr=h) for h in [188, 185, 182]]
        assert _robust_fcmax(acts) == 188.0

    def test_n3_outlier_uses_second_highest(self):
        # 210 > 185 * 1.10 → use 185
        acts = [_run(max_hr=h) for h in [210, 185, 182]]
        assert _robust_fcmax(acts) == 185.0

    def test_n2_uses_highest(self):
        acts = [_run(max_hr=h) for h in [200, 185]]
        assert _robust_fcmax(acts) == 200.0

    def test_none_max_hr_ignored(self):
        acts = [_run(max_hr=None), _run(max_hr=185), _run(max_hr=180)]
        assert _robust_fcmax(acts) == 185.0


# ---------------------------------------------------------------------------
# estimate_vma
# ---------------------------------------------------------------------------


class TestEstimateVma:
    def test_insufficient_when_no_fcmax(self):
        acts = [_run(max_hr=None) for _ in range(5)]
        result = estimate_vma(acts, reference_date=REF)
        assert result.confidence == "insufficient"
        assert result.vma_kmh is None

    def test_insufficient_when_too_few_activities(self):
        acts = [_run(date_str="2026-08-01", average_hr=160, max_hr=185)]
        result = estimate_vma(acts, reference_date=REF)
        assert result.confidence == "insufficient"
        assert result.vma_kmh is None

    def test_returns_vma_with_sufficient_data(self):
        acts = _regression_dataset()
        result = estimate_vma(acts, reference_date=REF)
        # May be good or moderate depending on R²
        assert result.vma_kmh is not None
        assert result.vma_kmh > 0
        assert result.confidence in ("good", "moderate")

    def test_trail_excluded_from_vma(self):
        acts = [
            _run(date_str="2026-08-01", activity_type="trail_running", average_hr=160, max_hr=185),
            _run(date_str="2026-07-28", activity_type="trail_running", average_hr=155, max_hr=185),
            _run(date_str="2026-07-21", activity_type="trail_running", average_hr=170, max_hr=185),
        ]
        result = estimate_vma(acts, reference_date=REF)
        assert result.confidence == "insufficient"

    def test_no_look_ahead(self):
        future_act = _run(date_str="2026-08-10", average_hr=180, max_hr=195)
        past_acts = _regression_dataset()
        result_without_future = estimate_vma(past_acts, reference_date=REF)
        result_with_future = estimate_vma(past_acts + [future_act], reference_date=REF)
        # Adding a future activity should not change estimate when reference is today (REF)
        assert result_without_future.vma_kmh == result_with_future.vma_kmh


# ---------------------------------------------------------------------------
# Riegel predictions
# ---------------------------------------------------------------------------


class TestRiegel:
    def _qualified_source(self, *, fcmax: float = 190.0) -> DomainActivity:
        """Return a Riegel-eligible activity with relative_hr >= 0.80."""
        avg_hr = fcmax * 0.85  # 0.85 >= 0.80
        return _run(
            date_str="2026-08-01",
            distance_m=10000,
            duration_s=2700,  # ~37 min 10K
            average_hr=avg_hr,
            max_hr=fcmax,
        )

    def test_no_predictions_when_no_fcmax(self):
        acts = [_run(max_hr=None, average_hr=150)]
        result = get_race_predictions(acts, reference_date=REF)
        assert result["has_data"] is False
        assert result["predictions"] == []

    def test_no_predictions_when_relative_hr_low(self):
        # relative_hr = 0.75 < 0.80
        act = _run(date_str="2026-08-01", average_hr=143, max_hr=190, duration_s=3600, distance_m=10000)
        result = get_race_predictions([act], reference_date=REF)
        assert result["has_data"] is False

    def test_eligible_at_boundary(self):
        # relative_hr exactly 0.80 → eligible
        act = _run(date_str="2026-08-01", average_hr=152, max_hr=190, duration_s=3600, distance_m=10000)
        result = get_race_predictions([act], reference_date=REF)
        assert result["has_data"] is True

    def test_predictions_include_standard_distances(self):
        act = self._qualified_source()
        result = get_race_predictions([act], reference_date=REF)
        labels = [p["distance"] for p in result["predictions"]]
        assert "5K" in labels
        assert "10K" in labels
        assert "Semi" in labels
        assert "Marathon" in labels

    def test_riegel_formula_correctness(self):
        # T1=2700s, D1=10000m → T(5K) = 2700 * (5000/10000)^1.06
        t1, d1, d2 = 2700.0, 10000.0, 5000.0
        expected = _riegel_predict(t1, d1, d2)
        act = self._qualified_source()
        result = get_race_predictions([act], reference_date=REF)
        five_k = next(p for p in result["predictions"] if p["distance"] == "5K")
        assert five_k["predicted_time_s"] == pytest.approx(expected, abs=1)

    def test_no_predictions_without_average_hr(self):
        act = _run(date_str="2026-08-01", average_hr=None, max_hr=190, duration_s=3600, distance_m=10000)
        result = get_race_predictions([act], reference_date=REF)
        assert result["has_data"] is False

    def test_trail_excluded_from_riegel(self):
        act = _run(
            date_str="2026-08-01",
            activity_type="trail_running",
            average_hr=160,
            max_hr=190,
            duration_s=3600,
            distance_m=10000,
        )
        result = get_race_predictions([act], reference_date=REF)
        assert result["has_data"] is False

    def test_no_synthetic_source(self):
        # Empty activities → no fabricated source
        result = get_race_predictions([], reference_date=REF)
        assert result["has_data"] is False
        assert result["source"] is None


# ---------------------------------------------------------------------------
# VMA / Predictions independence
# ---------------------------------------------------------------------------


class TestIndependence:
    """VMA and Race Predictions are fully independent.

    Same Riegel source must produce identical predictions regardless of
    whether VMA is available.
    """

    def _acts_with_vma(self) -> List[DomainActivity]:
        """A dataset where VMA can be estimated (good regression data) +
        a valid Riegel source with larger distance to be selected as best."""
        base = _regression_dataset()
        # Riegel source has 20km to beat all 10km regression activities in selection
        riegel_source = _run(
            date_str="2026-08-02",
            distance_m=20000,
            duration_s=5400,
            average_hr=162,  # 162/190 ≈ 0.853
            max_hr=190,
        )
        return base + [riegel_source]

    def _acts_no_vma(self) -> List[DomainActivity]:
        """Same Riegel source, but VMA model has no data (only one activity)."""
        riegel_source = _run(
            date_str="2026-08-02",
            distance_m=20000,
            duration_s=5400,
            average_hr=162,
            max_hr=190,
        )
        return [riegel_source]

    def test_same_predicted_time_with_or_without_vma(self):
        with_vma = get_race_predictions(self._acts_with_vma(), reference_date=REF)
        without_vma = get_race_predictions(self._acts_no_vma(), reference_date=REF)

        assert with_vma["has_data"] is True
        assert without_vma["has_data"] is True

        for p_with, p_without in zip(
            with_vma["predictions"], without_vma["predictions"]
        ):
            assert p_with["distance"] == p_without["distance"]
            assert p_with["predicted_time_s"] == p_without["predicted_time_s"]

    def test_vma_confidence_does_not_change_predictions(self):
        acts = self._acts_with_vma()
        vma_result = estimate_vma(acts, reference_date=REF)
        pred_result = get_race_predictions(acts, reference_date=REF)

        # Whether VMA is good or insufficient should not matter to predictions
        assert pred_result["has_data"] is True
        # Predictions exist regardless of VMA confidence
        assert len(pred_result["predictions"]) > 0
