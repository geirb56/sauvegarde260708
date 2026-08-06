"""PR05 — Tests for TrainingHistory (7 / 30 / 90 day windows).

All tests are deterministic: they use a fixed reference_date of 2026-08-06.

Window convention (inclusive both ends):
  7-day  : 2026-07-31 … 2026-08-06
  30-day : 2026-07-08 … 2026-08-06
  90-day : 2026-05-09 … 2026-08-06

Run from the backend directory:
    python -m pytest tests/test_training_history_pr05.py -q
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.training_history import (
    TrainingHistory,
    TrainingWindow,
    build_training_history,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF = date(2026, 8, 6)


def _act(
    activity_type: str,
    days_ago: int,
    distance_m: float | None = 10_000.0,
    duration_s: float | None = 3600.0,
) -> dict:
    """Build a minimal flat activity dict (days_ago relative to REF)."""
    run_date = REF - timedelta(days=days_ago)
    return {
        "activity_type": activity_type,
        "start_time": run_date.isoformat() + "T08:00:00.0",
        "distance": distance_m,
        "duration": duration_s,
    }


def _act_sub(
    activity_type: str,
    days_ago: int,
    distance_m: float | None = 10_000.0,
    duration_s: float | None = 3600.0,
) -> dict:
    """Build an activity dict with a garmin_activity sub-document (PR02)."""
    run_date = REF - timedelta(days=days_ago)
    sub = {
        "activity_type": activity_type,
        "start_time": run_date.isoformat() + "T08:00:00.0",
        "distance_m": distance_m,
        "duration_s": duration_s,
    }
    return {
        "activity_type": "SHOULD_BE_IGNORED",  # must be overridden by sub-doc
        "start_time": "SHOULD_BE_IGNORED",
        "distance": 99_999_999,
        "duration": 99_999_999,
        "garmin_activity": sub,
    }


# ---------------------------------------------------------------------------
# 1. Empty history
# ---------------------------------------------------------------------------


class TestEmptyHistory:
    def test_all_windows_zero(self):
        h = build_training_history([], REF)
        for w in (h.window_7d, h.window_30d, h.window_90d):
            assert w.distance_km == 0.0
            assert w.duration_hours == 0.0
            assert w.activity_count == 0
            assert w.average_speed_kmh is None
            assert w.longest_run_km is None

    def test_no_running_history(self):
        h = build_training_history([], REF)
        assert h.has_any_running_history is False
        assert h.has_7d_history is False
        assert h.has_30d_history is False
        assert h.has_90d_history is False
        assert h.days_since_last_run is None
        assert h.last_run_date is None
        assert h.available_history_days == 0


# ---------------------------------------------------------------------------
# 2. Activity type filtering
# ---------------------------------------------------------------------------


class TestActivityTypeFiltering:
    ACTIVITIES = [
        _act("running", 2),
        _act("trail_running", 5),
        _act("treadmill_running", 6),
        _act("cycling", 3),
        _act("walking", 4),
        # absent type
        {"start_time": (REF - timedelta(days=1)).isoformat(), "distance": 5000, "duration": 1800},
    ]

    def test_only_running_types_counted(self):
        h = build_training_history(self.ACTIVITIES, REF)
        assert h.window_7d.activity_count == 3  # running + trail + treadmill
        assert h.window_30d.activity_count == 3

    def test_cycling_excluded(self):
        cycling_only = [_act("cycling", 2)]
        h = build_training_history(cycling_only, REF)
        assert h.has_any_running_history is False

    def test_absent_type_excluded(self):
        no_type = [{"start_time": (REF - timedelta(days=1)).isoformat(), "distance": 5000, "duration": 1800}]
        h = build_training_history(no_type, REF)
        assert h.has_any_running_history is False


# ---------------------------------------------------------------------------
# 3. Window assignment (J-2, J-10, J-45, J-100)
# ---------------------------------------------------------------------------


class TestWindowAssignment:
    ACTIVITIES = [
        _act("running", 2),    # in 7d, 30d, 90d
        _act("running", 10),   # in 30d, 90d (not 7d)
        _act("running", 45),   # in 90d only
        _act("running", 100),  # outside all windows
    ]

    def setup_method(self):
        self.h = build_training_history(self.ACTIVITIES, REF)

    def test_7d_window(self):
        assert self.h.window_7d.activity_count == 1

    def test_30d_window(self):
        assert self.h.window_30d.activity_count == 2

    def test_90d_window(self):
        assert self.h.window_90d.activity_count == 3

    def test_j100_excluded_from_all(self):
        # Only 3 activities across 90d
        assert self.h.window_90d.activity_count == 3


# ---------------------------------------------------------------------------
# 4. Inclusive boundaries (J-6, J-7, J-29, J-30, J-89, J-90)
# ---------------------------------------------------------------------------


class TestInclusiveBoundaries:
    """
    Window convention: [reference_date - (N-1), reference_date] inclusive.

    7-day  boundary: J-6 IN, J-7 IN  (start = REF - 6)
    30-day boundary: J-29 IN, J-30 IN (start = REF - 29)
    90-day boundary: J-89 IN, J-90 IN (start = REF - 89)
    """

    def _h(self, days_ago):
        return build_training_history([_act("running", days_ago)], REF)

    def test_j6_in_7d(self):
        assert self._h(6).window_7d.activity_count == 1

    def test_j7_in_7d(self):
        assert self._h(7).window_7d.activity_count == 0  # REF - 7 < window start (REF-6)

    def test_j29_in_30d(self):
        assert self._h(29).window_30d.activity_count == 1

    def test_j30_in_30d(self):
        assert self._h(30).window_30d.activity_count == 0  # REF-30 < window start (REF-29)

    def test_j89_in_90d(self):
        assert self._h(89).window_90d.activity_count == 1

    def test_j90_in_90d(self):
        assert self._h(90).window_90d.activity_count == 0  # REF-90 < window start (REF-89)


# ---------------------------------------------------------------------------
# 5. Future activity ignored
# ---------------------------------------------------------------------------


class TestFutureActivity:
    def test_future_ignored(self):
        future = _act("running", -1)  # REF + 1
        h = build_training_history([future], REF)
        assert h.has_any_running_history is False
        assert h.window_7d.activity_count == 0


# ---------------------------------------------------------------------------
# 6. Invalid distances and durations
# ---------------------------------------------------------------------------


class TestInvalidValues:
    def _h_single(self, distance_m, duration_s):
        acts = [_act("running", 2, distance_m=distance_m, duration_s=duration_s)]
        return build_training_history(acts, REF)

    def test_none_distance(self):
        h = self._h_single(None, 3600.0)
        assert h.window_7d.distance_km == 0.0
        assert h.window_7d.activity_count == 1  # counts because duration is valid

    def test_zero_distance(self):
        h = self._h_single(0, 3600.0)
        assert h.window_7d.distance_km == 0.0

    def test_negative_distance(self):
        h = self._h_single(-500, 3600.0)
        assert h.window_7d.distance_km == 0.0

    def test_none_duration(self):
        h = self._h_single(10_000.0, None)
        assert h.window_7d.duration_hours == 0.0
        assert h.window_7d.distance_km == 10.0

    def test_zero_duration_no_speed(self):
        h = self._h_single(10_000.0, 0)
        assert h.window_7d.average_speed_kmh is None

    def test_negative_duration(self):
        h = self._h_single(10_000.0, -100)
        assert h.window_7d.duration_hours == 0.0

    def test_both_invalid_no_count(self):
        h = self._h_single(None, None)
        assert h.window_7d.activity_count == 0

    def test_no_exception_raised(self):
        for dist, dur in [(None, None), (0, 0), (-1, -1), ("bad", "bad")]:
            self._h_single(dist, dur)  # must not raise


# ---------------------------------------------------------------------------
# 7. Weighted average speed
# ---------------------------------------------------------------------------


class TestWeightedAverageSpeed:
    def test_weighted_not_simple_mean(self):
        """
        Run A: 10 km in 1 h  → individual speed 10 km/h
        Run B:  5 km in 0.25 h → individual speed 20 km/h

        Simple mean of speeds: (10 + 20) / 2 = 15 km/h  — WRONG
        Weighted total:        15 km / 1.25 h = 12 km/h  — CORRECT
        """
        acts = [
            _act("running", 2, distance_m=10_000.0, duration_s=3_600.0),
            _act("running", 3, distance_m=5_000.0, duration_s=900.0),
        ]
        h = build_training_history(acts, REF)
        assert h.window_30d.average_speed_kmh == pytest.approx(12.0, abs=0.01)

    def test_no_speed_when_duration_zero(self):
        acts = [_act("running", 2, distance_m=10_000.0, duration_s=0)]
        h = build_training_history(acts, REF)
        assert h.window_7d.average_speed_kmh is None


# ---------------------------------------------------------------------------
# 8. Longest run per window
# ---------------------------------------------------------------------------


class TestLongestRun:
    def test_longest_is_max(self):
        acts = [
            _act("running", 2, distance_m=5_000.0, duration_s=1800),
            _act("running", 3, distance_m=15_000.0, duration_s=3600),
            _act("running", 4, distance_m=8_000.0, duration_s=2400),
        ]
        h = build_training_history(acts, REF)
        assert h.window_7d.longest_run_km == 15.0

    def test_none_when_no_valid_distance(self):
        acts = [_act("running", 2, distance_m=None, duration_s=1800)]
        h = build_training_history(acts, REF)
        assert h.window_7d.longest_run_km is None

    def test_longest_per_window(self):
        acts = [
            _act("running", 2, distance_m=5_000.0, duration_s=1800),   # 7d
            _act("running", 10, distance_m=20_000.0, duration_s=7200),  # 30d
        ]
        h = build_training_history(acts, REF)
        assert h.window_7d.longest_run_km == 5.0
        assert h.window_30d.longest_run_km == 20.0


# ---------------------------------------------------------------------------
# 9. Last run date and days since last run
# ---------------------------------------------------------------------------


class TestLastRun:
    def test_last_run_date(self):
        acts = [
            _act("running", 5),
            _act("running", 2),
            _act("running", 10),
        ]
        h = build_training_history(acts, REF)
        assert h.last_run_date == (REF - timedelta(days=2)).isoformat()

    def test_days_since_last_run(self):
        acts = [_act("running", 3)]
        h = build_training_history(acts, REF)
        assert h.days_since_last_run == 3

    def test_none_when_no_history(self):
        h = build_training_history([], REF)
        assert h.last_run_date is None
        assert h.days_since_last_run is None


# ---------------------------------------------------------------------------
# 10. History depth indicators
# ---------------------------------------------------------------------------


class TestHistoryDepth:
    def test_40_day_history(self):
        # First activity at J-40
        acts = [
            _act("running", 40),
            _act("running", 20),
            _act("running", 5),
        ]
        h = build_training_history(acts, REF)
        assert h.available_history_days >= 40
        assert h.has_any_running_history is True
        assert h.has_7d_history is True
        assert h.has_30d_history is True
        assert h.has_90d_history is False

    def test_100_day_history(self):
        acts = [
            _act("running", 100),
            _act("running", 2),
        ]
        h = build_training_history(acts, REF)
        assert h.has_90d_history is True

    def test_5_day_history(self):
        acts = [_act("running", 5)]
        h = build_training_history(acts, REF)
        assert h.has_7d_history is False
        assert h.has_30d_history is False
        assert h.has_90d_history is False


# ---------------------------------------------------------------------------
# 11. Input format compatibility
# ---------------------------------------------------------------------------


class TestInputCompatibility:
    def test_flat_dict(self):
        acts = [_act("running", 2, distance_m=10_000.0, duration_s=3600.0)]
        h = build_training_history(acts, REF)
        assert h.window_7d.distance_km == 10.0

    def test_garmin_activity_subdoc(self):
        """garmin_activity sub-document must take priority over flat fields."""
        acts = [_act_sub("running", 2, distance_m=12_000.0, duration_s=3600.0)]
        h = build_training_history(acts, REF)
        # Must use sub-doc distance (12 km), not flat 99_999_999 m
        assert h.window_7d.distance_km == 12.0

    def test_subdoc_type_overrides_flat(self):
        """activity_type from sub-doc must be used, not flat."""
        # flat says cycling, sub-doc says running → must count as running
        act = _act_sub("running", 2, distance_m=5_000.0, duration_s=1800.0)
        act["activity_type"] = "cycling"
        h = build_training_history([act], REF)
        assert h.window_7d.activity_count == 1

    def test_flat_cycling_subdoc_excluded(self):
        """Sub-doc cycling must be excluded even if flat says running."""
        act = _act_sub("cycling", 2, distance_m=5_000.0, duration_s=1800.0)
        act["activity_type"] = "running"
        h = build_training_history([act], REF)
        assert h.window_7d.activity_count == 0


# ---------------------------------------------------------------------------
# 12. Distance / speed rounding
# ---------------------------------------------------------------------------


class TestRounding:
    def test_distance_rounded_to_2_decimals(self):
        # 3 × 3333.33 m = 9999.99 m → 9.999999… km → rounded 10.0
        acts = [
            _act("running", 1, distance_m=3333.33, duration_s=600),
            _act("running", 2, distance_m=3333.33, duration_s=600),
            _act("running", 3, distance_m=3333.34, duration_s=600),
        ]
        h = build_training_history(acts, REF)
        # Just check no exception and result is a float with ≤2 decimals
        val = h.window_7d.distance_km
        assert isinstance(val, float)
        assert round(val, 2) == val

    def test_speed_rounded_to_2_decimals(self):
        acts = [_act("running", 1, distance_m=10_000.0, duration_s=3_601.0)]
        h = build_training_history(acts, REF)
        speed = h.window_7d.average_speed_kmh
        assert speed is not None
        assert round(speed, 2) == speed
