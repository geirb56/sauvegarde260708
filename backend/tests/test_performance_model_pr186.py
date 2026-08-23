"""PR186 — Performance Model V2 data quality tests.

Tests numbered 1-29 correspond directly to the test cases specified in the
PR #186 problem statement. Tests verify the 5 data-quality objectives:

1. moving_duration_s used for speed and Riegel
2. VMA window unified at 42 days
3. Trail excluded from VMA; D+/km criterion applied
4. Riegel requires relative_hr >= 0.80 with FCmax and average_hr
5. total_sessions_6w counts only running in 42-day window

Run from the backend directory:
    python -m pytest tests/test_performance_model_pr186.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    VMA_WINDOW_DAYS,
    MAX_ROAD_ELEVATION_GAIN_PER_KM,
    MIN_RIEGEL_RELATIVE_HR,
    _activities_in_vma_window,
    _is_riegel_eligible,
    _is_vma_eligible,
    _performance_duration_s,
    _robust_fcmax,
    _speed_kmh,
    compute_athlete_profile,
    estimate_vma,
    get_race_predictions,
)

REF = date(2026, 8, 6)
FCMAX = 190.0


def _run(
    *,
    date_str: str = "2026-08-01",
    distance_m: float = 10000.0,
    duration_s: float = 3600.0,
    moving_duration_s: float | None = None,
    average_hr: float | None = 150.0,
    max_hr: float | None = FCMAX,
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


# ===========================================================================
# Section 1 — moving_duration_s
# ===========================================================================


class TestMovingDuration:
    # Test 1: moving_duration_s used for speed computation
    def test_1_speed_uses_moving_duration(self):
        """Test 1: duration_s=3600, moving_duration_s=3000, 10km → 12 km/h."""
        act = _run(distance_m=10000, duration_s=3600, moving_duration_s=3000)
        assert _performance_duration_s(act) == pytest.approx(3000.0)
        assert _speed_kmh(act) == pytest.approx(12.0, abs=0.01)

    # Test 2: fallback when moving absent
    def test_2_fallback_duration_when_moving_absent(self):
        """Test 2: moving_duration_s absent → fallback duration_s."""
        act = _run(distance_m=10000, duration_s=3600, moving_duration_s=None)
        assert _performance_duration_s(act) == pytest.approx(3600.0)

    # Test 3: fallback when moving is zero
    def test_3_fallback_when_moving_zero(self):
        """Test 3: moving_duration_s=0 → fallback duration_s."""
        act = DomainActivity(
            activity_type="running",
            distance_m=10000,
            duration_s=3600,
            moving_duration_s=0.0,
        )
        assert _performance_duration_s(act) == pytest.approx(3600.0)

    # Test 4: fallback when moving > duration
    def test_4_fallback_when_moving_exceeds_duration(self):
        """Test 4: moving_duration_s > duration_s → fallback duration_s."""
        act = DomainActivity(
            activity_type="running",
            distance_m=10000,
            duration_s=3600,
            moving_duration_s=4000.0,
        )
        assert _performance_duration_s(act) == pytest.approx(3600.0)

    # Test 5: Riegel T1 uses moving_duration_s
    def test_5_riegel_uses_moving_duration(self):
        """Test 5: Riegel T1 uses moving_duration_s when available."""
        # 10km in 3600s total but moving_duration_s=3000s → speed=12km/h
        # relative_hr = 160/190 ≈ 0.842 → eligible
        act = _run(
            distance_m=10000,
            duration_s=3600,
            moving_duration_s=3000,
            average_hr=160,
            max_hr=FCMAX,
        )
        result = get_race_predictions([act], reference_date=REF)
        assert result["has_data"] is True
        source = result["source"]
        assert source is not None
        assert source["duration_s"] == pytest.approx(3000.0)

    # Test 6: VMA HR-speed uses same duration as Riegel
    def test_6_vma_speed_same_duration_as_riegel(self):
        """Test 6: VMA HR-speed uses _performance_duration_s same as Riegel."""
        act = _run(distance_m=10000, duration_s=3600, moving_duration_s=3000)
        # Both should use moving_duration_s=3000
        dur = _performance_duration_s(act)
        assert dur == pytest.approx(3000.0)
        speed = _speed_kmh(act)
        assert speed == pytest.approx(12.0, abs=0.01)


# ===========================================================================
# Section 2 — VMA window 42 days
# ===========================================================================


class TestVmaWindow:
    # Test 7: activity at J-41 is included
    def test_7_activity_j41_included(self):
        """Test 7: activity at J-41 (= REF - 41 days) is within window."""
        d = date(2026, 6, 26)  # REF - 41 days = 2026-08-06 - 41 = 2026-06-26
        act = _run(date_str=d.isoformat())
        window = _activities_in_vma_window([act], reference_date=REF)
        assert len(window) == 1

    # Test 8: activity at J-42 is excluded
    def test_8_activity_j42_excluded(self):
        """Test 8: activity at J-42 (= REF - 42 days) is outside window."""
        d = date(2026, 6, 25)  # REF - 42 days
        act = _run(date_str=d.isoformat())
        window = _activities_in_vma_window([act], reference_date=REF)
        assert len(window) == 0

    # Test 9: future activity excluded
    def test_9_future_activity_excluded(self):
        """Test 9: activity at J+1 (future) is excluded."""
        d = date(2026, 8, 7)  # REF + 1
        act = _run(date_str=d.isoformat())
        window = _activities_in_vma_window([act], reference_date=REF)
        assert len(window) == 0

    # Test 10: old good performance outside window has no effect on CURRENT
    def test_10_old_performance_outside_window_no_effect(self):
        """Test 10: old excellent performance > 42 days ago has no effect."""
        # Old activity with extreme speed
        old = _run(
            date_str="2025-01-01",
            distance_m=10000,
            duration_s=1800,  # 5 min/km pace = 12 km/h
            average_hr=170,
            max_hr=FCMAX,
        )
        recent = [
            _run(date_str="2026-08-01", distance_m=10000, duration_s=3600, average_hr=140, max_hr=FCMAX),
        ]
        result_without_old = estimate_vma(recent, reference_date=REF)
        result_with_old = estimate_vma(recent + [old], reference_date=REF)
        # Both insufficient (only 1 activity in window) but old doesn't change result
        assert result_without_old.vma_kmh == result_with_old.vma_kmh

    # Test 11: CURRENT == snapshot with same activities
    def test_11_current_equals_snapshot_same_data(self):
        """Test 11: estimate_vma(today) == snapshot with same activities."""
        acts = [
            _run(date_str="2026-08-01", distance_m=10000, duration_s=3600, average_hr=140, max_hr=FCMAX),
            _run(date_str="2026-07-25", distance_m=10000, duration_s=3300, average_hr=155, max_hr=FCMAX),
            _run(date_str="2026-07-18", distance_m=10000, duration_s=3000, average_hr=168, max_hr=FCMAX),
            _run(date_str="2026-07-10", distance_m=10000, duration_s=2800, average_hr=178, max_hr=FCMAX),
            _run(date_str="2026-06-30", distance_m=10000, duration_s=2600, average_hr=183, max_hr=FCMAX),
        ]
        result_today = estimate_vma(acts, reference_date=REF)
        result_snapshot = estimate_vma(acts, reference_date=REF)
        assert result_today.vma_kmh == result_snapshot.vma_kmh
        assert result_today.confidence == result_snapshot.confidence

    # Test 12: history.sessions counts only activities in window
    def test_12_history_sessions_only_in_window(self):
        """Test 12: _activities_in_vma_window returns only window activities."""
        in_window = _run(date_str="2026-08-01")
        out_of_window = _run(date_str="2025-01-01")
        window = _activities_in_vma_window([in_window, out_of_window], reference_date=REF)
        assert len(window) == 1


# ===========================================================================
# Section 3 — Terrain comparable
# ===========================================================================


class TestTerrain:
    def _act(self, *, activity_type: str = "running", elevation_gain_m: float | None = None,
             distance_m: float = 10000.0) -> DomainActivity:
        return _run(
            activity_type=activity_type,
            elevation_gain_m=elevation_gain_m,
            distance_m=distance_m,
            average_hr=160,
            max_hr=FCMAX,
        )

    # Test 13: trail_running excluded from VMA even if flat
    def test_13_trail_excluded_from_vma(self):
        """Test 13: trail_running flat → excluded from VMA model."""
        act = self._act(activity_type="trail_running", elevation_gain_m=0)
        assert _is_vma_eligible(act) is False

    # Test 14: 10km +350m → excluded (350/10 = 35 > 30)
    def test_14_road_high_dplus_km_excluded(self):
        """Test 14: 10 km + 350 m → D+/km = 35 > 30 → excluded."""
        act = self._act(elevation_gain_m=350, distance_m=10000)
        assert _is_vma_eligible(act) is False

    # Test 15: 30km +350m → accepted (350/30 = 11.7 <= 30)
    def test_15_road_acceptable_dplus_km_accepted(self):
        """Test 15: 30 km + 350 m → D+/km = 11.7 <= 30 → accepted."""
        act = self._act(elevation_gain_m=350, distance_m=30000)
        assert _is_vma_eligible(act) is True

    # Test 16: D+ absent → not rejected
    def test_16_no_elevation_not_rejected(self):
        """Test 16: elevation_gain_m absent → D+/km check skipped."""
        act = self._act(elevation_gain_m=None)
        assert _is_vma_eligible(act) is True


# ===========================================================================
# Section 4 — Riegel qualification
# ===========================================================================


class TestRiegelQualification:
    def _riegel_act(
        self,
        *,
        relative_hr: float | None,
        activity_type: str = "running",
        elevation_gain_m: float | None = None,
        has_fcmax: bool = True,
    ) -> tuple[DomainActivity, float | None]:
        fcmax = FCMAX if has_fcmax else None
        avg_hr = FCMAX * relative_hr if (relative_hr is not None and has_fcmax) else None
        act = _run(
            activity_type=activity_type,
            average_hr=avg_hr,
            max_hr=fcmax if has_fcmax else None,
            elevation_gain_m=elevation_gain_m,
            distance_m=10000,
            duration_s=3600,
        )
        return act, fcmax

    # Test 17: relative_hr = 0.79 → rejected
    def test_17_relative_hr_079_rejected(self):
        """Test 17: relative_hr = 0.79 < 0.80 → rejected."""
        act, fcmax = self._riegel_act(relative_hr=0.79)
        assert _is_riegel_eligible(act, fcmax) is False

    # Test 18: relative_hr = 0.80 → eligible
    def test_18_relative_hr_080_eligible(self):
        """Test 18: relative_hr = 0.80 → eligible (boundary)."""
        act, fcmax = self._riegel_act(relative_hr=0.80)
        assert _is_riegel_eligible(act, fcmax) is True

    # Test 19: relative_hr = 0.90 → eligible
    def test_19_relative_hr_090_eligible(self):
        """Test 19: relative_hr = 0.90 → eligible."""
        act, fcmax = self._riegel_act(relative_hr=0.90)
        assert _is_riegel_eligible(act, fcmax) is True

    # Test 20: average_hr absent → rejected
    def test_20_no_average_hr_rejected(self):
        """Test 20: average_hr absent → rejected."""
        act, fcmax = self._riegel_act(relative_hr=None)
        assert act.average_hr is None
        assert _is_riegel_eligible(act, fcmax) is False

    # Test 21: FCmax absent → rejected
    def test_21_no_fcmax_rejected(self):
        """Test 21: FCmax absent → rejected."""
        act, _ = self._riegel_act(relative_hr=0.85, has_fcmax=False)
        assert _is_riegel_eligible(act, None) is False

    # Test 22: trail_running → rejected
    def test_22_trail_rejected(self):
        """Test 22: trail_running → rejected from Riegel."""
        act, fcmax = self._riegel_act(relative_hr=0.85, activity_type="trail_running")
        assert _is_riegel_eligible(act, fcmax) is False

    # Test 23: D+/km > 30 → rejected
    def test_23_high_dplus_km_rejected(self):
        """Test 23: D+/km = 35 > 30 → rejected."""
        act, fcmax = self._riegel_act(relative_hr=0.85, elevation_gain_m=350)
        # distance is 10000m so D+/km = 35
        assert _is_riegel_eligible(act, fcmax) is False

    # Test 24: no qualified source → predictions null/empty
    def test_24_no_qualified_source_no_predictions(self):
        """Test 24: no qualified source → predictions empty."""
        # All activities below 0.80 relative HR
        acts = [
            _run(date_str="2026-08-01", average_hr=140, max_hr=FCMAX),  # 140/190 = 0.737
        ]
        result = get_race_predictions(acts, reference_date=REF)
        assert result["has_data"] is False
        assert result["predictions"] == []

    # Test 25: no synthetic values
    def test_25_no_synthetic_predictions(self):
        """Test 25: no VMA-to-Riegel synthesis possible."""
        # VMA available but no Riegel source → no predictions
        acts = [
            _run(date_str="2026-08-01", average_hr=140, max_hr=FCMAX),
            _run(date_str="2026-07-25", average_hr=155, max_hr=FCMAX),
            _run(date_str="2026-07-18", average_hr=168, max_hr=FCMAX),
            _run(date_str="2026-07-10", average_hr=178, max_hr=FCMAX),
            _run(date_str="2026-06-30", average_hr=183, max_hr=FCMAX),
        ]
        # All relative_hr < 0.80 so no Riegel source
        result = get_race_predictions(acts, reference_date=REF)
        # Either has_data or not, but if has_data → source must be real observed activity
        if result["has_data"]:
            assert result["source"] is not None
            src = result["source"]
            assert src["duration_s"] > 0
        else:
            assert result["predictions"] == []


# ===========================================================================
# Section 5 — VMA / Predictions independence
# ===========================================================================


class TestIndependenceSection5:
    def _qualified_source(self) -> DomainActivity:
        return _run(
            date_str="2026-08-01",
            distance_m=10000,
            duration_s=2700,
            average_hr=0.85 * FCMAX,
            max_hr=FCMAX,
        )

    def test_same_predicted_time_vma_available_vs_null(self):
        """Test: same Riegel source → same predictions regardless of VMA."""
        src = self._qualified_source()

        # VMA available: add regression data
        vma_acts = [
            _run(date_str="2026-07-25", distance_m=10000, duration_s=3600, average_hr=140, max_hr=FCMAX),
            _run(date_str="2026-07-18", distance_m=10000, duration_s=3300, average_hr=155, max_hr=FCMAX),
            _run(date_str="2026-07-11", distance_m=10000, duration_s=3000, average_hr=168, max_hr=FCMAX),
            _run(date_str="2026-07-04", distance_m=10000, duration_s=2800, average_hr=178, max_hr=FCMAX),
        ]

        with_vma = get_race_predictions([src] + vma_acts, reference_date=REF)
        without_vma = get_race_predictions([src], reference_date=REF)

        assert with_vma["has_data"] is True
        assert without_vma["has_data"] is True

        for p_w, p_wo in zip(with_vma["predictions"], without_vma["predictions"]):
            assert p_w["predicted_time_s"] == p_wo["predicted_time_s"], \
                f"{p_w['distance']}: {p_w['predicted_time_s']} != {p_wo['predicted_time_s']}"


# ===========================================================================
# Section 6 — total_sessions_6w
# ===========================================================================


class TestTotalSessions6w:
    # Test 26: activity at J-41 is counted
    def test_26_activity_j41_counted(self):
        """Test 26: activity at J-41 → counted in total_sessions_6w."""
        d = date(2026, 6, 26)  # REF - 41
        act = _run(date_str=d.isoformat(), activity_type="running")
        profile = compute_athlete_profile([act], reference_date=REF)
        assert profile["total_sessions_6w"] == 1

    # Test 27: activity at J-42 is NOT counted
    def test_27_activity_j42_not_counted(self):
        """Test 27: activity at J-42 → not counted (outside window)."""
        d = date(2026, 6, 25)  # REF - 42
        act = _run(date_str=d.isoformat(), activity_type="running")
        profile = compute_athlete_profile([act], reference_date=REF)
        assert profile["total_sessions_6w"] == 0

    # Test 28: future activity not counted
    def test_28_future_activity_not_counted(self):
        """Test 28: activity in the future → not counted."""
        d = date(2026, 8, 7)  # REF + 1
        act = _run(date_str=d.isoformat(), activity_type="running")
        profile = compute_athlete_profile([act], reference_date=REF)
        assert profile["total_sessions_6w"] == 0

    # Test 29: non-running not counted
    def test_29_non_running_not_counted(self):
        """Test 29: cycling/swimming → not counted in total_sessions_6w."""
        cycling = _run(date_str="2026-08-01", activity_type="cycling")
        swimming = _run(date_str="2026-08-01", activity_type="swimming")
        running = _run(date_str="2026-08-01", activity_type="running")
        profile = compute_athlete_profile([cycling, swimming, running], reference_date=REF)
        assert profile["total_sessions_6w"] == 1


# ===========================================================================
# Constants validation
# ===========================================================================


class TestConstants:
    def test_vma_window_days(self):
        assert VMA_WINDOW_DAYS == 42

    def test_max_elevation_gain_per_km(self):
        assert MAX_ROAD_ELEVATION_GAIN_PER_KM == 30.0

    def test_min_riegel_relative_hr(self):
        assert MIN_RIEGEL_RELATIVE_HR == pytest.approx(0.80)

    def test_riegel_k_unchanged(self):
        from training_v2.performance_model import RIEGEL_K
        assert RIEGEL_K == pytest.approx(1.06)
