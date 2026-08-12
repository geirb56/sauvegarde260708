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

from training_v2 import DomainActivity
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

    def test_domain_activity(self):
        acts = [
            DomainActivity(
                activity_type="running",
                start_time=(REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
                distance_m=12_000.0,
                duration_s=3600.0,
            )
        ]
        h = build_training_history(acts, REF)
        assert h.window_7d.distance_km == 12.0

    def test_generic_object_with_domain_fields(self):
        class _Activity:
            activity_type = "running"
            start_time = (REF - timedelta(days=2)).isoformat() + "T08:00:00.0"
            distance_m = 5_000.0
            duration_s = 1800.0

        h = build_training_history([_Activity()], REF)
        assert h.window_7d.activity_count == 1

    def test_non_running_domain_activity_excluded(self):
        act = DomainActivity(
            activity_type="cycling",
            start_time=(REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
            distance_m=5_000.0,
            duration_s=1800.0,
        )
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


# ---------------------------------------------------------------------------
# 13. Garmin date formats (PR89)
# ---------------------------------------------------------------------------


class TestGarminDateFormats:
    """Verify that all real-world Garmin date strings are parsed correctly."""

    # REF = 2026-08-06 ; J-4 = 2026-08-02
    _EXPECTED_DISTANCE = 10.0

    def _h_with_start_time(self, start_time: str):
        act = {
            "activity_type": "running",
            "start_time": start_time,
            "distance": 10_000.0,
            "duration": 3600.0,
        }
        return build_training_history([act], REF)

    def test_space_separated(self):
        """Garmin native format with space: '2026-08-02 10:08:20'."""
        h = self._h_with_start_time("2026-08-02 10:08:20")
        assert h.window_7d.activity_count == 1
        assert h.window_7d.distance_km == self._EXPECTED_DISTANCE

    def test_t_separated(self):
        h = self._h_with_start_time("2026-08-02T10:08:20")
        assert h.window_7d.activity_count == 1

    def test_t_separated_with_z(self):
        h = self._h_with_start_time("2026-08-02T10:08:20Z")
        assert h.window_7d.activity_count == 1

    def test_t_separated_with_tz_offset(self):
        h = self._h_with_start_time("2026-08-02T10:08:20+02:00")
        assert h.window_7d.activity_count == 1

    def test_date_only(self):
        h = self._h_with_start_time("2026-08-02")
        assert h.window_7d.activity_count == 1

    def test_space_separated_enters_correct_windows(self):
        """J-4 must be in 7d, 30d, 90d windows but not outside them."""
        h = self._h_with_start_time("2026-08-02 10:08:20")
        assert h.window_7d.activity_count == 1
        assert h.window_30d.activity_count == 1
        assert h.window_90d.activity_count == 1

    def test_invalid_date_graceful(self):
        """Unparseable date must be silently skipped, not raise."""
        act = {
            "activity_type": "running",
            "start_time": "not-a-date",
            "distance": 10_000.0,
            "duration": 3600.0,
        }
        h = build_training_history([act], REF)
        assert h.window_7d.activity_count == 0


# ---------------------------------------------------------------------------
# 14. Secured average_speed_kmh (PR89)
# ---------------------------------------------------------------------------


class TestSecuredAverageSpeed:
    """Speed numerator/denominator must only include activities with
    BOTH valid distance AND valid duration simultaneously."""

    def test_dist_only_does_not_inflate_speed(self):
        """Activity with distance but no duration must not push speed upward
        by reducing the effective duration pool."""
        acts = [
            # proper activity: 10 km in 1 h → 10 km/h
            _act("running", 2, distance_m=10_000.0, duration_s=3600.0),
            # distance only — must not enter speed calculation
            _act("running", 3, distance_m=100_000.0, duration_s=None),
        ]
        h = build_training_history(acts, REF)
        # Speed must be 10 km / 1 h = 10 km/h, not (110 km / 1 h)
        assert h.window_7d.average_speed_kmh == pytest.approx(10.0, abs=0.01)
        # But total distance must include both contributions
        assert h.window_7d.distance_km == pytest.approx(110.0, abs=0.01)

    def test_dur_only_does_not_dilute_speed(self):
        """Activity with duration but no distance must not dilute speed by
        adding to the effective duration pool."""
        acts = [
            # proper activity: 10 km in 1 h → 10 km/h
            _act("running", 2, distance_m=10_000.0, duration_s=3600.0),
            # duration only — must not enter speed calculation
            _act("running", 3, distance_m=None, duration_s=7200.0),
        ]
        h = build_training_history(acts, REF)
        # Speed must be 10 km / 1 h = 10 km/h, not (10 km / 3 h)
        assert h.window_7d.average_speed_kmh == pytest.approx(10.0, abs=0.01)
        # But total duration must include both contributions
        assert h.window_7d.duration_hours == pytest.approx(3.0, abs=0.01)

    def test_no_speed_when_all_dist_only(self):
        """No speed when every activity has distance but no duration."""
        acts = [
            _act("running", 1, distance_m=10_000.0, duration_s=None),
            _act("running", 2, distance_m=5_000.0, duration_s=None),
        ]
        h = build_training_history(acts, REF)
        assert h.window_7d.average_speed_kmh is None

    def test_no_speed_when_all_dur_only(self):
        """No speed when every activity has duration but no distance."""
        acts = [
            _act("running", 1, distance_m=None, duration_s=3600.0),
        ]
        h = build_training_history(acts, REF)
        assert h.window_7d.average_speed_kmh is None

    def test_speed_correct_with_mixed_activities(self):
        """Mixed pool: only pairs (dist, dur) contribute to speed."""
        acts = [
            _act("running", 1, distance_m=10_000.0, duration_s=3600.0),  # pair
            _act("running", 2, distance_m=5_000.0, duration_s=900.0),    # pair
            _act("running", 3, distance_m=20_000.0, duration_s=None),    # dist-only
            _act("running", 4, distance_m=None, duration_s=7200.0),      # dur-only
        ]
        h = build_training_history(acts, REF)
        # Speed = (10+5) km / (1+0.25) h = 12 km/h
        assert h.window_7d.average_speed_kmh == pytest.approx(12.0, abs=0.01)


# ---------------------------------------------------------------------------
# 15. available_history_days — inclusive convention (DQ.1)
# ---------------------------------------------------------------------------


class TestAvailableHistoryDaysInclusiveConvention:
    """available_history_days must use the inclusive convention:
    (reference_date - first_date).days + 1.

    So a single activity on J yields 1 day, on J-6 → 7, J-7 → 8, etc.
    """

    def _days(self, days_ago: int) -> int:
        acts = [_act("running", days_ago)]
        return build_training_history(acts, REF).available_history_days

    def test_activity_on_J_is_1_day(self):
        assert self._days(0) == 1

    def test_activity_on_J_minus_6_is_7_days(self):
        assert self._days(6) == 7

    def test_activity_on_J_minus_7_is_8_days(self):
        assert self._days(7) == 8

    def test_activity_on_J_minus_27_is_28_days(self):
        assert self._days(27) == 28

    def test_activity_on_J_minus_29_is_30_days(self):
        assert self._days(29) == 30

    def test_activity_on_J_minus_89_is_90_days(self):
        assert self._days(89) == 90


# ---------------------------------------------------------------------------
# 16. Consistency between TrainingHistory and TrainingLoad (DQ.1)
# ---------------------------------------------------------------------------


class TestHistoryLoadDepthConsistency:
    """TrainingHistory and TrainingLoadSnapshot must report the same
    available_history_days for identical activity inputs."""

    @staticmethod
    def _load_available_days(acts: list) -> int:
        """Replicate the available_history_days calculation from TrainingLoad."""
        from training_v2.training_load import _extract_fields, _activity_load_minutes
        from training_v2.training_history import RUNNING_TYPES

        run_activities = []
        for raw in acts:
            fields = _extract_fields(raw)
            if fields.get("activity_type") in RUNNING_TYPES:
                act_date = fields.get("activity_date")
                if act_date is None or act_date <= REF:
                    run_activities.append(fields)

        valid_dates = [
            f["activity_date"] for f in run_activities
            if f["activity_date"] is not None
            and f["activity_date"] <= REF
            and _activity_load_minutes(f) is not None
        ]
        return (REF - min(valid_dates)).days + 1 if valid_dates else 0

    def test_same_depth_single_activity(self):
        acts = [_act("running", 27)]
        h = build_training_history(acts, REF)
        assert h.available_history_days == self._load_available_days(acts) == 28

    def test_same_depth_multiple_activities(self):
        acts = [
            _act("running", 89),
            _act("running", 30),
            _act("running", 2),
        ]
        h = build_training_history(acts, REF)
        assert h.available_history_days == self._load_available_days(acts)
