"""PR06 — Tests for TrainingLoadSnapshot (deterministic training-load engine V2).

All tests use a fixed reference_date of 2026-08-06 to ensure full
determinism — no datetime.now() is called anywhere.

Window boundaries for REF = 2026-08-06
---------------------------------------
  Acute 7-day    : 2026-07-31 … 2026-08-06  (J-6 … J+0)
  Chronic 28-day : 2026-07-10 … 2026-08-06  (J-27 … J+0)
  Previous 7-day : 2026-07-24 … 2026-07-30  (J-13 … J-7)

Run from the backend directory:
    python -m pytest tests/test_training_v2_training_load.py -q
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.training_load import (
    TrainingLoadSnapshot,
    build_training_load,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REF = date(2026, 8, 6)

# Exact window dates for REF
ACUTE_START = REF - timedelta(days=6)         # 2026-07-31
CHRONIC_START = REF - timedelta(days=27)      # 2026-07-10
PREV_START = REF - timedelta(days=13)         # 2026-07-24
PREV_END = REF - timedelta(days=7)            # 2026-07-30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _act(
    activity_type: str,
    days_ago: int,
    distance_m: float | None = 10_000.0,
    duration_s: float | None = 3600.0,
) -> dict:
    """Flat activity dict (days_ago relative to REF)."""
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
    """Activity dict with a garmin_activity sub-document (PR02 convention)."""
    run_date = REF - timedelta(days=days_ago)
    return {
        "garmin_activity": {
            "activity_type": activity_type,
            "start_time": run_date.isoformat() + "T08:00:00.0",
            "distance_m": distance_m,
            "duration_s": duration_s,
        }
    }


def _running(days_ago: int, *, distance_m=10_000.0, duration_s=3600.0) -> dict:
    return _act("running", days_ago, distance_m=distance_m, duration_s=duration_s)


def _trail(days_ago: int, *, distance_m=10_000.0, duration_s=3600.0) -> dict:
    return _act("trail_running", days_ago, distance_m=distance_m, duration_s=duration_s)


def snap(activities, ref=REF) -> TrainingLoadSnapshot:
    return build_training_load(activities, ref)


# ---------------------------------------------------------------------------
# Test 1: no activities
# ---------------------------------------------------------------------------


def test_no_activities():
    s = snap([])
    assert s.acute_load_7d == 0.0
    assert s.load_28d == 0.0
    assert s.chronic_weekly_load == 0.0
    assert s.acwr is None
    assert s.status == "unavailable"
    assert s.is_available is False
    assert s.has_sufficient_history is False
    assert s.confidence == "none"
    assert s.activities_7d == 0
    assert s.activities_28d == 0
    assert s.previous_7d_load == 0.0
    assert s.load_change_percent is None


# ---------------------------------------------------------------------------
# Test 2: only non-running activities
# ---------------------------------------------------------------------------


def test_only_non_running_activities():
    activities = [
        _act("cycling", 3, distance_m=20_000, duration_s=3600),
        _act("swimming", 1, distance_m=2_000, duration_s=1800),
    ]
    s = snap(activities)
    assert s.acute_load_7d == 0.0
    assert s.load_28d == 0.0
    assert s.acwr is None
    assert s.confidence == "none"


# ---------------------------------------------------------------------------
# Test 3: one valid running activity in the last 7 days
# ---------------------------------------------------------------------------


def test_one_activity_in_7d():
    s = snap([_running(2, duration_s=1800.0)])
    assert s.acute_load_7d == 30.0   # 1800 / 60
    assert s.activities_7d == 1


# ---------------------------------------------------------------------------
# Test 4: exact load from duration
# ---------------------------------------------------------------------------


def test_load_from_duration():
    # 5400 seconds = 90 minutes
    s = snap([_running(1, duration_s=5400.0, distance_m=12_000.0)])
    assert s.acute_load_7d == 90.0


# ---------------------------------------------------------------------------
# Test 5: distance alone produces no load (no fallback)
# ---------------------------------------------------------------------------


def test_distance_only_produces_no_load():
    # Duration absent → no load, even with a valid distance.
    # Distance may be used by TrainingHistory for volume metrics but does NOT
    # generate a synthetic load in TrainingLoadSnapshot.
    s = snap([_running(1, duration_s=None, distance_m=10_000.0)])
    assert s.acute_load_7d == 0.0
    assert s.activities_7d == 0


# ---------------------------------------------------------------------------
# Test 6: duration is the sole source of load
# ---------------------------------------------------------------------------


def test_duration_is_sole_load_source():
    # 3600 s → 60 min regardless of distance value
    s = snap([_running(1, duration_s=3600.0, distance_m=20_000.0)])
    assert s.acute_load_7d == 60.0


# ---------------------------------------------------------------------------
# Test 7: zero or negative duration produces no load (no distance fallback)
# ---------------------------------------------------------------------------


def test_zero_duration_no_load():
    # duration = 0 → invalid; distance present but ignored
    s = snap([_running(1, duration_s=0.0, distance_m=10_000.0)])
    assert s.acute_load_7d == 0.0
    assert s.activities_7d == 0


def test_negative_duration_no_load():
    # duration < 0 → invalid; distance present but ignored
    s = snap([_running(1, duration_s=-100.0, distance_m=5_000.0)])
    assert s.acute_load_7d == 0.0
    assert s.activities_7d == 0


# ---------------------------------------------------------------------------
# Test 8: no duration and no distance → excluded
# ---------------------------------------------------------------------------


def test_no_duration_no_distance_excluded():
    s = snap([_running(1, duration_s=None, distance_m=None)])
    assert s.acute_load_7d == 0.0
    assert s.activities_7d == 0


# ---------------------------------------------------------------------------
# Test 9: future activities excluded
# ---------------------------------------------------------------------------


def test_future_activity_excluded():
    future = {
        "activity_type": "running",
        "start_time": (REF + timedelta(days=1)).isoformat() + "T08:00:00",
        "distance": 10_000,
        "duration": 3600,
    }
    s = snap([future])
    assert s.acute_load_7d == 0.0
    assert s.activities_7d == 0


# ---------------------------------------------------------------------------
# Test 10: J-6 is included in the 7-day acute window
# ---------------------------------------------------------------------------


def test_j_minus_6_included_in_acute_window():
    # days_ago=6 → ACUTE_START (2026-07-31) — must be included
    s = snap([_running(6)])
    assert s.activities_7d == 1
    assert s.acute_load_7d > 0.0


# ---------------------------------------------------------------------------
# Test 11: J-7 is NOT in the acute window
# ---------------------------------------------------------------------------


def test_j_minus_7_excluded_from_acute_window():
    # days_ago=7 → 2026-07-30 — outside [J-6 … J+0]
    s = snap([_running(7)])
    assert s.activities_7d == 0
    assert s.acute_load_7d == 0.0


# ---------------------------------------------------------------------------
# Test 12: J-27 is included in the 28-day window
# ---------------------------------------------------------------------------


def test_j_minus_27_included_in_28d_window():
    # days_ago=27 → CHRONIC_START (2026-07-10) — must be included
    s = snap([_running(27)])
    assert s.activities_28d == 1
    assert s.load_28d > 0.0


# ---------------------------------------------------------------------------
# Test 13: chronic_weekly_load = load_28d / 4
# ---------------------------------------------------------------------------


def test_chronic_weekly_load_is_28d_divided_by_4():
    activities = [_running(i) for i in range(5)]   # 5 activities in past 7 days
    s = snap(activities)
    expected = round(s.load_28d / 4.0, 2)
    assert s.chronic_weekly_load == expected


# ---------------------------------------------------------------------------
# Test 14: exact ACWR calculation
# ---------------------------------------------------------------------------


def test_acwr_calculation():
    # Acute: 1 run of 60 min in past 7 days
    # 28-day load: same run
    # acute=60, load_28d=60, chronic_weekly=15, acwr=4.0
    s = snap([_running(2, duration_s=3600.0)])
    assert s.acute_load_7d == 60.0
    assert s.load_28d == 60.0
    assert s.chronic_weekly_load == 15.0
    assert s.acwr == 4.0


# ---------------------------------------------------------------------------
# Test 15: acwr is None when load_28d == 0
# ---------------------------------------------------------------------------


def test_acwr_none_when_no_28d_load():
    s = snap([])
    assert s.acwr is None


# ---------------------------------------------------------------------------
# Test 16: status "unavailable" when no denominator
# ---------------------------------------------------------------------------


def test_status_unavailable_without_denominator():
    s = snap([])
    assert s.status == "unavailable"
    assert s.is_available is False


# ---------------------------------------------------------------------------
# Test 17: each ACWR status at boundary values
# ---------------------------------------------------------------------------


def _acwr_acute_minutes(target_acwr: float, B_min: float = 60.0) -> float:
    """Return A (minutes) so that ACWR = 4A / (B + A) = target_acwr.

    Derivation:
        target_acwr × (B + A) = 4A
        target_acwr × B = A × (4 - target_acwr)
        A = target_acwr × B / (4 - target_acwr)

    Note: the acute load A is also included in load_28d, so
        chronic_weekly_load = (B + A) / 4
        ACWR = A / chronic_weekly_load = 4A / (B + A)
    """
    return target_acwr * B_min / (4.0 - target_acwr)


def _snap_for_acwr(target_acwr: float, B_min: float = 60.0) -> TrainingLoadSnapshot:
    """Build a snapshot whose computed ACWR equals target_acwr.

    B_min minutes are spread across days 8-11 (inside 28-day window,
    outside the 7-day acute window).
    A = target_acwr × B / (4 - target_acwr) minutes are placed at day 1
    (inside the acute window).
    """
    base = [_running(8 + i, duration_s=B_min / 4 * 60.0) for i in range(4)]
    A_min = _acwr_acute_minutes(target_acwr, B_min)
    return snap(base + [_running(1, duration_s=A_min * 60.0)])


def test_status_very_low():
    # ACWR < 0.50 — target 0.30
    # B=60 min, A = 0.30×60/3.70 = 18/3.7 min; ACWR = 4A/(60+A) = 72/240 = 0.30
    s = _snap_for_acwr(0.30)
    assert s.acwr == pytest.approx(0.30, abs=0.001)
    assert s.status == "very_low"


def test_status_at_very_low_boundary():
    # ACWR = 0.50 exactly (lower bound of "low")
    # B=60, A = 0.50×60/3.50 = 60/7 min; ACWR = 4×(60/7)/(60+60/7) = 240/480 = 0.50
    s = _snap_for_acwr(0.50)
    assert s.acwr == pytest.approx(0.50, abs=0.001)
    assert s.status == "low"


def test_status_low():
    # 0.50 ≤ ACWR < 0.80 — interior value 0.60
    # B=60, A = 0.60×60/3.40 = 180/17 min; ACWR = 4×(180/17)/(60+180/17) = 720/1200 = 0.60
    s = _snap_for_acwr(0.60)
    assert s.acwr == pytest.approx(0.60, abs=0.001)
    assert s.status == "low"


def test_status_at_balanced_low_boundary():
    # ACWR = 0.80 exactly (lower bound of "balanced")
    # B=60, A = 0.80×60/3.20 = 15 min = 900 s; ACWR = 4×15/(60+15) = 60/75 = 0.80
    s = _snap_for_acwr(0.80)
    assert s.acwr == pytest.approx(0.80, abs=0.001)
    assert s.status == "balanced"


def test_status_balanced():
    # 0.80 ≤ ACWR ≤ 1.30 — interior value 1.00
    # B=60, A = 1.00×60/3.00 = 20 min; ACWR = 4×20/(60+20) = 80/80 = 1.00
    s = _snap_for_acwr(1.00)
    assert s.acwr == pytest.approx(1.00, abs=0.001)
    assert s.status == "balanced"


def test_status_at_balanced_high_boundary():
    # ACWR = 1.30 exactly (upper bound of "balanced")
    # B=60, A = 1.30×60/2.70 = 260/9 min; ACWR = 4×(260/9)/(60+260/9) = 1040/800 = 1.30
    s = _snap_for_acwr(1.30)
    assert s.acwr == pytest.approx(1.30, abs=0.001)
    assert s.status == "balanced"


def test_status_elevated():
    # 1.30 < ACWR ≤ 1.50 — interior value 1.40
    # B=60, A = 1.40×60/2.60 = 420/13 min; ACWR = 4×(420/13)/(60+420/13) = 1680/1200 = 1.40
    s = _snap_for_acwr(1.40)
    assert s.acwr == pytest.approx(1.40, abs=0.001)
    assert s.status == "elevated"


def test_status_at_elevated_high_boundary():
    # ACWR = 1.50 exactly (upper bound of "elevated")
    # B=60, A = 1.50×60/2.50 = 36 min = 2160 s; ACWR = 4×36/(60+36) = 144/96 = 1.50
    s = _snap_for_acwr(1.50)
    assert s.acwr == pytest.approx(1.50, abs=0.001)
    assert s.status == "elevated"


def test_status_high():
    # ACWR > 1.50 — use 1.60
    # B=60, A = 1.60×60/2.40 = 40 min = 2400 s; ACWR = 4×40/(60+40) = 160/100 = 1.60
    s = _snap_for_acwr(1.60)
    assert s.acwr == pytest.approx(1.60, abs=0.001)
    assert s.status == "high"


# ---------------------------------------------------------------------------
# Test 18: previous 7-day window [J-13 … J-7]
# ---------------------------------------------------------------------------


def test_previous_window_boundaries():
    # J-13 (days_ago=13) must be in prev window
    # J-7 (days_ago=7) must be in prev window
    # J-14 (days_ago=14) must NOT be in prev window
    # J-6 (days_ago=6) must NOT be in prev window (it's in acute)
    activities = [
        _running(13, duration_s=600.0),   # in prev window
        _running(7, duration_s=600.0),    # in prev window
        _running(14, duration_s=600.0),   # outside
        _running(6, duration_s=600.0),    # in acute
    ]
    s = snap(activities)
    # prev_7d_load = 2 runs × 10 min = 20 min
    assert s.previous_7d_load == 20.0
    assert s.acute_load_7d == 10.0


# ---------------------------------------------------------------------------
# Test 19: load_change_percent calculation
# ---------------------------------------------------------------------------


def test_load_change_percent():
    # acute=60, previous=30 → change = (60-30)/30 × 100 = 100.0%
    activities = [
        _running(2, duration_s=3600.0),   # 60 min in acute
        _running(8, duration_s=1800.0),   # 30 min in previous window
    ]
    s = snap(activities)
    assert s.acute_load_7d == 60.0
    assert s.previous_7d_load == 30.0
    assert s.load_change_percent == 100.0


# ---------------------------------------------------------------------------
# Test 20: load_change_percent is None when previous_7d_load == 0
# ---------------------------------------------------------------------------


def test_load_change_none_when_no_previous():
    s = snap([_running(2)])
    assert s.previous_7d_load == 0.0
    assert s.load_change_percent is None


# ---------------------------------------------------------------------------
# Test 21: insufficient history
# ---------------------------------------------------------------------------


def test_insufficient_history():
    # Only 5 days of history
    s = snap([_running(5)])
    assert s.has_sufficient_history is False
    assert s.confidence == "low"


# ---------------------------------------------------------------------------
# Test 22: exactly sufficient history (28 days)
# ---------------------------------------------------------------------------


def test_exactly_sufficient_history():
    # With inclusive convention: activity at J-27 →
    # available_history_days = (REF - (REF-27)).days + 1 = 27 + 1 = 28 → sufficient
    s = snap([_running(27)])
    assert s.has_sufficient_history is True
    assert s.confidence == "high"

    # Activity at J-26 → available_history_days = 26 + 1 = 27 < 28 → not sufficient
    s2 = snap([_running(26)])
    assert s2.has_sufficient_history is False
    assert s2.confidence == "medium"


# ---------------------------------------------------------------------------
# Test 23: confidence levels "none", "low", "medium", "high"
# ---------------------------------------------------------------------------


def test_confidence_none():
    s = snap([])
    assert s.confidence == "none"


def test_confidence_low():
    # 5 days of history
    s = snap([_running(5)])
    assert s.confidence == "low"


def test_confidence_medium():
    # 20 days of history (>= 14, < 28)
    s = snap([_running(20)])
    assert s.confidence == "medium"


def test_confidence_high():
    # 30 days of history (>= 28)
    s = snap([_running(30)])
    assert s.confidence == "high"


# Inclusive boundary transitions (convention: available_history_days = days_elapsed + 1)
def test_confidence_low_at_boundary():
    # 13 days of history → "low" (< 14)
    # days_ago=12 → available = 12 + 1 = 13
    s = snap([_running(12)])
    assert s.confidence == "low"


def test_confidence_medium_at_lower_boundary():
    # 14 days of history → "medium" (>= 14)
    # days_ago=13 → available = 13 + 1 = 14
    s = snap([_running(13)])
    assert s.confidence == "medium"


def test_confidence_medium_at_upper_boundary():
    # 27 days of history → still "medium" (< 28)
    # days_ago=26 → available = 26 + 1 = 27
    s = snap([_running(26)])
    assert s.confidence == "medium"
    assert s.has_sufficient_history is False


def test_confidence_high_at_boundary():
    # 28 days of history → "high" (>= 28)
    # days_ago=27 → available = 27 + 1 = 28
    s = snap([_running(27)])
    assert s.confidence == "high"
    assert s.has_sufficient_history is True


# ---------------------------------------------------------------------------
# Test 24: garmin_activity sub-document (PR02 convention)
# ---------------------------------------------------------------------------


def test_subdocument_activity():
    act = _act_sub("running", 2, distance_m=10_000.0, duration_s=3600.0)
    s = snap([act])
    assert s.acute_load_7d == 60.0
    assert s.activities_7d == 1


# ---------------------------------------------------------------------------
# Test 25: Pydantic GarminActivity objects
# ---------------------------------------------------------------------------


def test_pydantic_object_activity():
    from datetime import datetime

    class _FakeActivity:
        activity_type = "running"
        start_time = (REF - timedelta(days=2)).isoformat() + "T08:00:00"
        distance_m = 10_000.0
        duration_s = 1800.0

    s = snap([_FakeActivity()])
    assert s.acute_load_7d == 30.0  # 1800/60


# ---------------------------------------------------------------------------
# Test 26: model is immutable (frozen)
# ---------------------------------------------------------------------------


def test_model_immutability():
    s = snap([_running(1)])
    with pytest.raises(Exception):
        s.acute_load_7d = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 27: determinism — same inputs produce same output
# ---------------------------------------------------------------------------


def test_determinism():
    activities = [_running(i) for i in range(10)]
    s1 = snap(activities)
    s2 = snap(activities)
    assert s1 == s2


# ---------------------------------------------------------------------------
# Test 28: no dependency on system time
# ---------------------------------------------------------------------------


def test_no_system_time_dependency():
    """The module must not depend on system time — all results are determined by
    the explicitly provided reference_date, not by datetime.now()."""
    activities = [_running(1)]
    # Calling with two different explicit reference dates must yield different
    # results that correspond only to the supplied dates, proving no system
    # clock dependency.
    s1 = build_training_load(activities, date(2026, 1, 1))
    s2 = build_training_load(activities, date(2026, 8, 6))
    # s1 won't contain the activity (it's in the future relative to 2026-01-01)
    assert s1.activities_7d == 0
    # s2 will contain it
    assert s2.activities_7d == 1


# ---------------------------------------------------------------------------
# Test 29: activity with only a valid duration
# ---------------------------------------------------------------------------


def test_only_valid_duration():
    s = snap([_running(1, duration_s=2400.0, distance_m=None)])
    assert s.acute_load_7d == 40.0   # 2400 / 60


# ---------------------------------------------------------------------------
# Coherence: 28-day window ≠ 30-day window
# ---------------------------------------------------------------------------


def test_28d_window_not_30d():
    """Explicit coherence check: the chronic window is 28 days, not 30 days.

    The chronic window is [J-27 ; J] (inclusive on both ends) — 28 calendar days.
    An activity at J-28 (days_ago=28) is OUTSIDE the chronic window.
    An activity at J-27 (days_ago=27) is the earliest date inside the window.

    J-28 and beyond are NOT in the 28-day window.
    """
    # Activity exactly at J-28 — outside the 28-day window [J-27 … J]
    s_j28 = snap([_running(28)])
    assert s_j28.load_28d == 0.0   # J-28 is NOT in [J-27 … J+0]
    assert s_j28.activities_28d == 0

    # Activity at J-27 — inside the 28-day window (boundary)
    s_j27 = snap([_running(27)])
    assert s_j27.load_28d > 0.0   # J-27 IS in [J-27 … J+0]
    assert s_j27.activities_28d == 1


# ---------------------------------------------------------------------------
# Additional: trail_running and treadmill_running are accepted
# ---------------------------------------------------------------------------


def test_trail_running_accepted():
    s = snap([_trail(2, duration_s=3600.0)])
    assert s.acute_load_7d == 60.0


def test_treadmill_running_accepted():
    act = _act("treadmill_running", 2, duration_s=1800.0)
    s = snap([act])
    assert s.acute_load_7d == 30.0


# ---------------------------------------------------------------------------
# Additional: acwr rounding (3 decimal places)
# ---------------------------------------------------------------------------


def test_acwr_rounded_to_3_decimals():
    # 4 × 900 s = 60 min in 28d; chronic_weekly = 15 min
    # acute: 1 run of 700 s = 700/60 ≈ 11.6667 min  → acwr = 11.6667/15 ≈ 0.7778
    activities = [_running(8 + i, duration_s=900.0) for i in range(4)] + [
        _running(1, duration_s=700.0)
    ]
    s = snap(activities)
    # Verify acwr has at most 3 decimal places
    assert s.acwr is not None
    assert round(s.acwr, 3) == s.acwr


# ---------------------------------------------------------------------------
# Additional: load_change_percent rounding (1 decimal place)
# ---------------------------------------------------------------------------


def test_load_change_percent_rounded_to_1_decimal():
    activities = [
        _running(2, duration_s=700.0),   # acute
        _running(8, duration_s=900.0),   # previous
    ]
    s = snap(activities)
    if s.load_change_percent is not None:
        assert round(s.load_change_percent, 1) == s.load_change_percent
