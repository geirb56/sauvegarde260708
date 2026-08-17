"""PR132 — Tests for RecentTrainingResponse & WorkoutExecutionFacts.

Test coverage map (spec §18):
  A  — 0 activities → unavailable
  B  — 1–4 activities → insufficient, facts available, trends unknown
  C  — 5 activities in 28 days → sufficient
  D  — 10 activities → selected 10
  E  — 11+ activities → only 10 most recent
  F  — activity at J-29 → excluded
  G  — future activity → excluded
  H  — non-running activity → excluded
  I  — unplanned run → included in RecentTrainingResponse
  J  — HR absent → HR fields None, never 0
  K  — distance or duration absent → efficiency None
  L  — HR + distance + duration available → deterministic efficiency
  M  — intensity unknown → None ≠ 0 respected
  N  — planned 10 km / actual 8 km → ratio 0.8, no pass/fail
  O  — duration ratio deterministic
  P  — no LT1/LT2 attributes
  Q  — no cardiac drift intra-run attribute
  R  — no TRIMP/TSS/EPOC
  S  — no garmin import in training_response
  T  — no training_engine import in training_response
  U  — no rag_engine import in training_response
  V  — no llm_coach import in training_response
  W  — no datetime.now/date.today in training_response source
  X  — same inputs + reference_date → identical result (determinism)
"""

from __future__ import annotations

import ast
import importlib
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import pytest

# Ensure backend is on the path
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from training_v2.domain_activity import DomainActivity, to_domain_activity
from training_v2.training_response import (
    RecentTrainingResponse,
    WorkoutExecutionFacts,
    analyze_workout_execution,
    build_recent_training_response,
    _cardiac_efficiency,
    _half_split_trend,
)
from training_v2.workout_generator import WorkoutPrescription

REF = date(2026, 8, 6)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _run(
    days_ago: int,
    distance_m: Optional[float] = 8000.0,
    duration_s: Optional[float] = 2400.0,
    average_hr: Optional[float] = None,
    max_hr: Optional[float] = None,
    elevation_gain_m: Optional[float] = None,
    moderate_intensity_minutes: Optional[float] = None,
    vigorous_intensity_minutes: Optional[float] = None,
    activity_type: str = "running",
) -> DomainActivity:
    """Build a DomainActivity at reference_date - days_ago."""
    start = REF - timedelta(days=days_ago)
    return DomainActivity(
        activity_type=activity_type,
        start_time=start,
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=average_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
        moderate_intensity_minutes=moderate_intensity_minutes,
        vigorous_intensity_minutes=vigorous_intensity_minutes,
    )


def _prescription(
    distance_km: Optional[float] = 10.0,
    duration_minutes: Optional[int] = 60,
    workout_type: str = "easy",
) -> WorkoutPrescription:
    return WorkoutPrescription(
        day="monday",
        workout_type=workout_type,
        intensity_class="low",
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=(),
    )


# ---------------------------------------------------------------------------
# A — 0 activities → unavailable
# ---------------------------------------------------------------------------

def test_A_zero_activities_unavailable():
    result = build_recent_training_response([], REF)
    assert result.response_status == "unavailable"
    assert result.confidence == "none"
    assert result.selected_running_activities == 0
    assert result.observed_runs == 0
    assert result.observed_distance_km is None
    assert result.observed_duration_minutes is None
    assert "no_recent_running_activities" in result.reason_codes


# ---------------------------------------------------------------------------
# B — 1–4 activities → insufficient, facts available, structural trends unknown
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_B_insufficient(n):
    acts = [_run(i * 3) for i in range(n)]
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "insufficient"
    assert result.confidence == "low"
    # facts are computed
    assert result.observed_distance_km is not None
    assert result.observed_runs == n
    # structural trends not reliable
    assert result.volume_trend == "unknown"
    assert result.cardiac_efficiency_trend == "unknown"
    assert result.long_run_trend == "unknown"
    assert result.frequency_pattern == "unknown"


# ---------------------------------------------------------------------------
# C — 5 activities → sufficient
# ---------------------------------------------------------------------------

def test_C_five_activities_sufficient():
    acts = [_run(i * 4) for i in range(5)]
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.confidence == "moderate"
    assert result.selected_running_activities == 5


# ---------------------------------------------------------------------------
# D — 10 activities → all selected
# ---------------------------------------------------------------------------

def test_D_ten_activities_selected():
    acts = [_run(i * 2) for i in range(10)]
    result = build_recent_training_response(acts, REF)
    assert result.selected_running_activities == 10
    assert result.response_status == "sufficient"


# ---------------------------------------------------------------------------
# E — 11+ activities → only 10 most recent selected
# ---------------------------------------------------------------------------

def test_E_eleven_activities_cap_at_ten():
    # 11 activities in window: days_ago 0..21 (every 2 days)
    acts = [_run(i * 2) for i in range(11)]
    result = build_recent_training_response(acts, REF)
    assert result.selected_running_activities == 10
    assert result.available_running_activities == 11
    assert "activities_capped_at_10" in result.reason_codes
    # Most recent 10 selected → oldest (days_ago=20) excluded from fine analysis
    # But observed_distance_km uses ALL 11 in-window activities: 11 × 8 km = 88 km
    assert result.observed_distance_km == pytest.approx(88.0)


# ---------------------------------------------------------------------------
# F — activity at J-29 → excluded
# ---------------------------------------------------------------------------

def test_F_activity_29_days_ago_excluded():
    acts = [
        _run(29),  # out of 28-day window
        _run(1),   # in window
    ]
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 1
    assert result.selected_running_activities == 1


# ---------------------------------------------------------------------------
# G — future activity → excluded
# ---------------------------------------------------------------------------

def test_G_future_activity_excluded():
    future = DomainActivity(
        activity_type="running",
        start_time=REF + timedelta(days=1),
        distance_m=5000.0,
        duration_s=1800.0,
    )
    acts = [future, _run(2)]
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 1


# ---------------------------------------------------------------------------
# H — non-running activity → excluded
# ---------------------------------------------------------------------------

def test_H_non_running_excluded():
    cycle = DomainActivity(
        activity_type="cycling",
        start_time=REF - timedelta(days=1),
        distance_m=30000.0,
        duration_s=3600.0,
    )
    swim = DomainActivity(
        activity_type="swimming",
        start_time=REF - timedelta(days=2),
        distance_m=1500.0,
        duration_s=2700.0,
    )
    acts = [cycle, swim, _run(3)]
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 1


# ---------------------------------------------------------------------------
# I — unplanned run → included in RecentTrainingResponse
# ---------------------------------------------------------------------------

def test_I_unplanned_run_included():
    """An activity with no matching prescription is a valid running observation."""
    unplanned = _run(5, distance_m=12000.0)
    acts = [_run(1), unplanned, _run(10)]
    result = build_recent_training_response(acts, REF)
    assert result.observed_runs == 3
    # All 3 distances should be counted: 8+12+8 = 28 km
    assert result.observed_distance_km == pytest.approx(28.0)


# ---------------------------------------------------------------------------
# J — HR absent → HR fields None, never 0
# ---------------------------------------------------------------------------

def test_J_hr_absent_is_none_not_zero():
    acts = [_run(i * 3, average_hr=None) for i in range(5)]
    result = build_recent_training_response(acts, REF)
    assert result.average_hr_recent is None
    assert result.hr_coverage_count == 0
    # All efficiency samples None when HR missing
    for sample in result.cardiac_efficiency_samples:
        assert sample is None
    assert result.cardiac_efficiency_trend == "unknown"
    assert "hr_data_unavailable" in result.reason_codes


# ---------------------------------------------------------------------------
# K — distance or duration absent → efficiency None
# ---------------------------------------------------------------------------

def test_K_missing_distance_efficiency_none():
    act_no_dist = DomainActivity(
        activity_type="running",
        start_time=REF - timedelta(days=1),
        distance_m=None,
        duration_s=1800.0,
        average_hr=150.0,
    )
    assert _cardiac_efficiency(act_no_dist) is None


def test_K_missing_duration_efficiency_none():
    act_no_dur = DomainActivity(
        activity_type="running",
        start_time=REF - timedelta(days=1),
        distance_m=8000.0,
        duration_s=None,
        average_hr=150.0,
    )
    assert _cardiac_efficiency(act_no_dur) is None


def test_K_zero_distance_efficiency_none():
    act_zero = DomainActivity(
        activity_type="running",
        start_time=REF,
        distance_m=0.0,
        duration_s=1800.0,
        average_hr=150.0,
    )
    assert _cardiac_efficiency(act_zero) is None


# ---------------------------------------------------------------------------
# L — HR + distance + duration → deterministic efficiency
# ---------------------------------------------------------------------------

def test_L_efficiency_deterministic():
    act = DomainActivity(
        activity_type="running",
        start_time=REF,
        distance_m=10000.0,
        duration_s=3600.0,
        average_hr=150.0,
    )
    speed = 10000.0 / 3600.0          # m/s
    expected = speed / 150.0
    assert _cardiac_efficiency(act) == pytest.approx(expected)


def test_L_efficiency_in_response():
    acts = [
        _run(i * 3, distance_m=10000.0, duration_s=3600.0, average_hr=150.0)
        for i in range(5)
    ]
    result = build_recent_training_response(acts, REF)
    for sample in result.cardiac_efficiency_samples:
        assert sample is not None
        assert sample == pytest.approx((10000.0 / 3600.0) / 150.0)


# ---------------------------------------------------------------------------
# M — intensity unknown → None ≠ 0 respected
# ---------------------------------------------------------------------------

def test_M_intensity_none_not_zero():
    act = _run(1, moderate_intensity_minutes=None, vigorous_intensity_minutes=None)
    result = build_recent_training_response([act], REF)
    assert result.intensity_coverage_count == 0
    # DomainActivity fields themselves
    assert act.moderate_intensity_minutes is None
    assert act.vigorous_intensity_minutes is None


def test_M_intensity_zero_is_zero():
    act = _run(1, moderate_intensity_minutes=0.0, vigorous_intensity_minutes=0.0)
    assert act.moderate_intensity_minutes == 0.0
    assert act.vigorous_intensity_minutes == 0.0


# ---------------------------------------------------------------------------
# N — planned 10 km / actual 8 km → ratio 0.8, no pass/fail
# ---------------------------------------------------------------------------

def test_N_distance_ratio_0_8():
    planned = _prescription(distance_km=10.0, duration_minutes=60)
    actual = _run(0, distance_m=8000.0, duration_s=2400.0)
    facts = analyze_workout_execution(planned, actual, REF)
    assert facts.distance_ratio == pytest.approx(0.8)
    # No verdict attributes
    assert not hasattr(facts, "verdict")
    assert not hasattr(facts, "score")
    assert not hasattr(facts, "passed")
    assert not hasattr(facts, "failed")


# ---------------------------------------------------------------------------
# O — duration ratio deterministic
# ---------------------------------------------------------------------------

def test_O_duration_ratio():
    planned = _prescription(distance_km=None, duration_minutes=60)
    actual = _run(0, distance_m=None, duration_s=3000.0)
    facts = analyze_workout_execution(planned, actual, REF)
    assert facts.duration_ratio == pytest.approx(3000.0 / 60.0 / 60.0)


def test_O_duration_ratio_exact():
    planned = _prescription(distance_km=10.0, duration_minutes=50)
    actual = _run(0, distance_m=8000.0, duration_s=2500.0)
    facts = analyze_workout_execution(planned, actual, REF)
    # actual_duration_minutes = 2500/60, planned = 50
    assert facts.duration_ratio == pytest.approx((2500.0 / 60.0) / 50.0)


# ---------------------------------------------------------------------------
# P — no LT1/LT2 attributes on RecentTrainingResponse
# ---------------------------------------------------------------------------

def test_P_no_LT1_LT2():
    result = build_recent_training_response([], REF)
    assert not hasattr(result, "lt1")
    assert not hasattr(result, "lt2")
    assert not hasattr(result, "vt1")
    assert not hasattr(result, "vt2")


# ---------------------------------------------------------------------------
# Q — no cardiac drift attribute
# ---------------------------------------------------------------------------

def test_Q_no_cardiac_drift():
    result = build_recent_training_response([], REF)
    assert not hasattr(result, "cardiac_drift")
    assert not hasattr(result, "hr_drift")
    assert not hasattr(result, "cardiac_decoupling")


# ---------------------------------------------------------------------------
# R — no TRIMP/TSS/EPOC
# ---------------------------------------------------------------------------

def test_R_no_TRIMP_TSS_EPOC():
    result = build_recent_training_response([], REF)
    assert not hasattr(result, "trimp")
    assert not hasattr(result, "tss")
    assert not hasattr(result, "epoc")


# ---------------------------------------------------------------------------
# S / T / U / V — no forbidden imports in training_response.py
# ---------------------------------------------------------------------------

def _source_text() -> str:
    import training_v2.training_response as mod
    return open(mod.__file__).read()


def _import_names(src: str) -> set[str]:
    """Return all top-level module names referenced in import statements."""
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_S_no_garmin_import():
    names = _import_names(_source_text())
    assert "garmin" not in names


def test_T_no_training_engine_import():
    names = _import_names(_source_text())
    assert "training_engine" not in names


def test_U_no_rag_engine_import():
    names = _import_names(_source_text())
    assert "rag_engine" not in names


def test_V_no_llm_coach_import():
    names = _import_names(_source_text())
    assert "llm_coach" not in names


# ---------------------------------------------------------------------------
# W — no datetime.now / date.today in source
# ---------------------------------------------------------------------------

def test_W_no_datetime_now_or_date_today():
    """Verify datetime.now() and date.today() are not called in training_response."""
    import training_v2.training_response as mod
    src = open(mod.__file__).read()
    tree = ast.parse(src)
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Match attr calls like datetime.now() or date.today()
            if isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
    assert "now" not in call_names, "datetime.now() must not be called"
    assert "today" not in call_names, "date.today() must not be called"


# ---------------------------------------------------------------------------
# X — determinism: same inputs → same result
# ---------------------------------------------------------------------------

def test_X_deterministic():
    acts = [_run(i * 2, average_hr=140.0 + i) for i in range(8)]
    r1 = build_recent_training_response(acts, REF)
    r2 = build_recent_training_response(acts, REF)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_boundary_28_days_included():
    """Activity exactly 27 days ago (= window start) must be included."""
    act = _run(27)
    result = build_recent_training_response([act], REF)
    assert result.available_running_activities == 1


def test_boundary_28_days_excluded():
    """Activity 28 days ago (= reference_date - 28) is outside the window."""
    act = _run(28)
    result = build_recent_training_response([act], REF)
    assert result.available_running_activities == 0


def test_domain_activity_new_fields_preserved():
    """Extended DomainActivity fields survive round-trip via to_domain_activity."""
    raw = {
        "activity_type": "running",
        "start_time": "2026-08-01",
        "distance_m": 10000.0,
        "duration_s": 3600.0,
        "average_hr": 155.0,
        "max_hr": 178.0,
        "elevation_gain_m": 120.5,
    }
    act = to_domain_activity(raw)
    assert act.average_hr == 155.0
    assert act.max_hr == 178.0
    assert act.elevation_gain_m == 120.5


def test_domain_activity_zero_hr_becomes_none():
    """HR value of 0 must be stored as None."""
    raw = {"activity_type": "running", "average_hr": 0, "max_hr": 0}
    act = to_domain_activity(raw)
    assert act.average_hr is None
    assert act.max_hr is None


def test_domain_activity_negative_hr_becomes_none():
    raw = {"activity_type": "running", "average_hr": -10}
    act = to_domain_activity(raw)
    assert act.average_hr is None


def test_partial_hr_coverage():
    """8 runs, only 2 with HR → HR trend unknown, but other trends may be valid."""
    acts = [_run(i * 3, average_hr=(150.0 if i < 2 else None)) for i in range(8)]
    result = build_recent_training_response(acts, REF)
    assert result.hr_coverage_count == 2
    assert result.cardiac_efficiency_trend == "unknown"  # only 2 samples, < 4 for trend
    assert "hr_data_partial" in result.reason_codes


def test_volume_trend_increasing():
    """Second half distances clearly larger → volume_trend = increasing."""
    # oldest: 4 × 5 km, newest: 4 × 8 km
    acts = (
        [_run(20 - i * 2, distance_m=5000.0) for i in range(4)]
        + [_run(6 - i * 2, distance_m=8000.0) for i in range(4)]
    )
    result = build_recent_training_response(acts, REF)
    assert result.volume_trend == "increasing"


def test_volume_trend_decreasing():
    acts = (
        [_run(20 - i * 2, distance_m=8000.0) for i in range(4)]
        + [_run(6 - i * 2, distance_m=5000.0) for i in range(4)]
    )
    result = build_recent_training_response(acts, REF)
    assert result.volume_trend == "decreasing"


def test_half_split_trend_unknown_below_4():
    assert _half_split_trend([1.0, 2.0, 3.0]) == "unknown"


def test_half_split_trend_stable():
    values = [5.0, 5.1, 5.0, 5.0, 5.1, 5.0]
    assert _half_split_trend(values) == "stable"


def test_execution_facts_no_distance_planned():
    """If planned has no distance, distance_ratio is None."""
    planned = _prescription(distance_km=None, duration_minutes=45)
    actual = _run(0, distance_m=8000.0, duration_s=2700.0)
    facts = analyze_workout_execution(planned, actual, REF)
    assert facts.distance_ratio is None


def test_execution_facts_actual_hr_transported():
    planned = _prescription(distance_km=10.0, duration_minutes=60)
    actual = _run(0, distance_m=10000.0, duration_s=3600.0, average_hr=155.0)
    facts = analyze_workout_execution(planned, actual, REF)
    assert facts.actual_average_hr == 155.0


def test_trail_running_included():
    act = DomainActivity(
        activity_type="trail_running",
        start_time=REF - timedelta(days=2),
        distance_m=15000.0,
        duration_s=7200.0,
    )
    result = build_recent_training_response([act], REF)
    assert result.available_running_activities == 1


def test_treadmill_running_included():
    act = DomainActivity(
        activity_type="treadmill_running",
        start_time=REF - timedelta(days=1),
        distance_m=8000.0,
        duration_s=2700.0,
    )
    result = build_recent_training_response([act], REF)
    assert result.available_running_activities == 1


def test_observed_runs_per_week():
    # 7 runs in 28 days → 1.75 per week
    acts = [_run(i * 3) for i in range(7)]
    result = build_recent_training_response(acts, REF)
    assert result.observed_runs_per_week == pytest.approx(7 / 28 * 7)


# ---------------------------------------------------------------------------
# BUG1 — volume_trend is calendar-based (total distance, not mean per run)
# ---------------------------------------------------------------------------

def test_volume_trend_calendar_counts_total_not_average():
    """
    Old half (J-27→J-14): 2 runs × 10 km = 20 km total
    Recent half (J-13→J): 4 runs × 10 km = 40 km total
    Average per run = 10 km in both halves → old code returned 'stable'.
    Calendar-total volume has doubled → correct code returns 'increasing'.
    """
    # old half: 2 runs at days_ago 16 and 20 (both < freq_boundary J-13)
    old_half = [_run(16, distance_m=10_000.0), _run(20, distance_m=10_000.0)]
    # recent half: 4 runs at days_ago 0, 3, 6, 10 (all >= freq_boundary J-13)
    recent_half = [
        _run(0, distance_m=10_000.0),
        _run(3, distance_m=10_000.0),
        _run(6, distance_m=10_000.0),
        _run(10, distance_m=10_000.0),
    ]
    acts = old_half + recent_half
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.volume_trend == "increasing"


def test_volume_trend_stable_when_totals_equal():
    """Equal total distances in both halves → stable."""
    # 3 runs in old half, 3 in recent half, same distance
    acts = [
        _run(27, distance_m=10_000.0),
        _run(20, distance_m=10_000.0),
        _run(16, distance_m=10_000.0),
        _run(5, distance_m=10_000.0),
        _run(2, distance_m=10_000.0),
        _run(1, distance_m=10_000.0),
    ]
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.volume_trend == "stable"


def test_volume_trend_decreasing_when_recent_half_lower():
    """Recent total < old total × 0.90 → decreasing."""
    # old half: 3 × 10 km = 30 km; recent half: 2 × 10 km = 20 km (< 30×0.90=27)
    acts = [
        _run(27, distance_m=10_000.0),
        _run(20, distance_m=10_000.0),
        _run(16, distance_m=10_000.0),  # still in old half (< J-13)
        _run(5, distance_m=10_000.0),   # recent half
        _run(1, distance_m=10_000.0),   # recent half
    ]
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.volume_trend == "decreasing"


# ---------------------------------------------------------------------------
# BUG2/3 — Global 28d facts are not distorted by the 10-activity cap
# ---------------------------------------------------------------------------

def test_global_facts_use_all_activities_not_capped_10():
    """
    20 runs in window: observed_runs = 20, runs_per_week ≈ 5.0.
    Selected = 10 (most recent) for fine analysis.
    """
    acts = [_run(i) for i in range(20)]  # days_ago 0..19, all within 28d
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 20
    assert result.selected_running_activities == 10
    # Global facts: ALL 20 activities
    assert result.observed_runs == 20
    assert result.observed_runs_per_week == pytest.approx(20 / 28 * 7)
    # Distance: 20 × 8 km = 160 km
    assert result.observed_distance_km == pytest.approx(160.0)
    # Duration: 20 × 2400s / 60 = 800 min
    assert result.observed_duration_minutes == pytest.approx(800.0)
    assert "activities_capped_at_10" in result.reason_codes


def test_volume_trend_calendar_calendar_uses_all_activities_not_cap():
    """
    14 runs in old half + 6 in recent half → decreasing.
    If capped at 10 most recent the old half would be empty → 'unknown' (wrong).
    Calendar-based logic must use all in-window activities.
    """
    # old half (days_ago 14..27): 14 runs × 5 km = 70 km
    old_half = [_run(14 + i, distance_m=5_000.0) for i in range(14)]
    # recent half (days_ago 0..13): 6 runs × 5 km = 30 km  (< 70×0.90=63 → decreasing)
    recent_half = [_run(i, distance_m=5_000.0) for i in range(6)]
    acts = old_half + recent_half
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 20
    assert result.selected_running_activities == 10
    assert result.response_status == "sufficient"
    # Calendar total: old=70km, recent=30km → decreasing (not 'unknown')
    assert result.volume_trend == "decreasing"


# ---------------------------------------------------------------------------
# §14-D — volume_trend: unknown when insufficient data in one half
# ---------------------------------------------------------------------------

def test_volume_trend_unknown_insufficient_coverage():
    """
    5 activities but only 1 has a valid distance (in recent half only) → unknown.
    Requires at least 1 valid distance in EACH half.
    """
    # 3 activities without distance in old half + 2 with distance in recent half
    acts = (
        [_run(20, distance_m=None), _run(18, distance_m=None), _run(16, distance_m=None)]
        + [_run(5, distance_m=10_000.0), _run(1, distance_m=10_000.0)]
    )
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.volume_trend == "unknown"


def test_volume_trend_unknown_total_below_4():
    """
    5 activities but only 2 have valid distances (1 old, 1 recent) → unknown.
    Requires at least 4 activities with valid distance total.
    """
    acts = (
        [_run(20, distance_m=10_000.0)]   # old half, valid
        + [_run(18, distance_m=None), _run(16, distance_m=None), _run(14, distance_m=None)]
        + [_run(5, distance_m=10_000.0)]  # recent half, valid
    )
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.volume_trend == "unknown"


# ---------------------------------------------------------------------------
# §15 — frequency_pattern: >10 activities, not distorted by cap
# ---------------------------------------------------------------------------

def test_frequency_pattern_not_capped_at_10():
    """
    14 activities total: 4 in old half, 10 in recent half.
    Even though MAX_SELECTED = 10, frequency_pattern must use ALL 14.
    4 → 10 is clearly increasing (> 4 * 1.10 = 4.4).
    """
    # old half: days_ago 14..17 (4 runs)
    old_half = [_run(14 + i) for i in range(4)]
    # recent half: days_ago 0..9 (10 runs)
    recent_half = [_run(i) for i in range(10)]
    acts = old_half + recent_half
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 14
    assert result.selected_running_activities == 10
    assert result.response_status == "sufficient"
    assert result.frequency_pattern == "increasing"


def test_frequency_pattern_uses_full_window_decreasing():
    """
    Old half: 10 runs, recent half: 4 runs → decreasing.
    Correctly computed even when >10 total in window.
    """
    old_half = [_run(14 + i) for i in range(10)]
    recent_half = [_run(i) for i in range(4)]
    acts = old_half + recent_half
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 14
    assert result.frequency_pattern == "decreasing"


# ---------------------------------------------------------------------------
# §16 — long_run_trend: calendar-based (old 14d vs recent 14d)
# ---------------------------------------------------------------------------

def test_long_run_trend_calendar_increasing():
    """
    Old half longest = 10 km; recent half longest = 15 km → increasing.
    Uses ALL in-window activities, calendar-based split.
    """
    acts = [
        _run(20, distance_m=10_000.0),  # old half
        _run(18, distance_m=8_000.0),   # old half
        _run(16, distance_m=9_000.0),   # old half
        _run(5, distance_m=15_000.0),   # recent half
        _run(2, distance_m=12_000.0),   # recent half
        _run(1, distance_m=11_000.0),   # recent half
    ]
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.long_run_trend == "increasing"


def test_long_run_trend_calendar_decreasing():
    """
    Old half longest = 15 km; recent half longest = 10 km → decreasing.
    """
    acts = [
        _run(20, distance_m=15_000.0),  # old half
        _run(18, distance_m=14_000.0),  # old half
        _run(16, distance_m=12_000.0),  # old half
        _run(5, distance_m=10_000.0),   # recent half
        _run(2, distance_m=9_000.0),    # recent half
        _run(1, distance_m=8_000.0),    # recent half
    ]
    result = build_recent_training_response(acts, REF)
    assert result.long_run_trend == "decreasing"


def test_long_run_trend_calendar_stable():
    """
    Old half longest = 10 km; recent half longest = 10.5 km → stable (< 10 %).
    """
    acts = [
        _run(20, distance_m=10_000.0),   # old half
        _run(18, distance_m=8_000.0),    # old half
        _run(16, distance_m=9_000.0),    # old half
        _run(5, distance_m=10_500.0),    # recent half
        _run(2, distance_m=9_500.0),     # recent half
        _run(1, distance_m=8_000.0),     # recent half
    ]
    result = build_recent_training_response(acts, REF)
    assert result.long_run_trend == "stable"


def test_long_run_trend_unknown_no_old_half_dist():
    """
    All valid distances in recent half only → unknown (old half has none).
    """
    acts = [
        _run(20, distance_m=None),  # old half, no distance
        _run(18, distance_m=None),  # old half, no distance
        _run(16, distance_m=None),  # old half, no distance
        _run(5, distance_m=10_000.0),
        _run(2, distance_m=10_000.0),
        _run(1, distance_m=10_000.0),
    ]
    result = build_recent_training_response(acts, REF)
    assert result.long_run_trend == "unknown"


def test_long_run_trend_uses_all_activities_not_cap():
    """
    20 activities in window — cap would cut old-half distances; calendar must not.
    Old half: 14 runs × 12 km; recent: 6 runs × 10 km → decreasing.
    """
    old_half = [_run(14 + i, distance_m=12_000.0) for i in range(14)]
    recent_half = [_run(i, distance_m=10_000.0) for i in range(6)]
    acts = old_half + recent_half
    result = build_recent_training_response(acts, REF)
    assert result.available_running_activities == 20
    assert result.selected_running_activities == 10
    assert result.long_run_trend == "decreasing"


# ---------------------------------------------------------------------------
# §17-A — cardiac efficiency: comparable flat terrain → trend computable
# ---------------------------------------------------------------------------

def test_17A_cardiac_efficiency_comparable_flat_terrain():
    """
    5 runs, all with valid HR/distance/duration, low similar elevation_rate
    (≤ 5 m D+/km each).  terrain_max − terrain_min ≤ 30 → trend computable.
    All identical efficiency values → 'stable'.
    """
    # elevation_gain_m = 40 m, distance_km = 10 → rate = 4 m/km (flat)
    acts = [
        _run(
            i * 4,
            distance_m=10_000.0,
            duration_s=3600.0,
            average_hr=150.0,
            elevation_gain_m=40.0,  # 4 m/km
        )
        for i in range(5)
    ]
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.cardiac_efficiency_trend != "unknown", (
        "Comparable flat terrain: trend must be computable"
    )
    assert result.cardiac_efficiency_trend == "stable"


# ---------------------------------------------------------------------------
# §17-B — cardiac efficiency: mixed flat+hilly → dispersion exceeds threshold
# ---------------------------------------------------------------------------

def test_17B_cardiac_efficiency_mixed_terrain_unknown():
    """
    2 flat runs (elevation_rate ≈ 5 m/km) + 3 very hilly runs (≈ 80 m/km).
    terrain_max − terrain_min ≈ 75 m/km > 30 threshold → unknown.
    """
    flat_acts = [
        _run(
            i * 5,
            distance_m=10_000.0,
            duration_s=3600.0,
            average_hr=150.0,
            elevation_gain_m=50.0,   # 5 m/km
        )
        for i in range(2)
    ]
    hilly_acts = [
        _run(
            20 + i * 2,
            distance_m=10_000.0,
            duration_s=3600.0,
            average_hr=150.0,
            elevation_gain_m=800.0,  # 80 m/km
        )
        for i in range(3)
    ]
    acts = flat_acts + hilly_acts
    result = build_recent_training_response(acts, REF)
    assert result.cardiac_efficiency_trend == "unknown", (
        "Mixed flat + hilly terrain exceeds threshold: must be unknown"
    )


# ---------------------------------------------------------------------------
# §17-C — cardiac efficiency: elevation unknown on majority → unknown
# ---------------------------------------------------------------------------

def test_17C_cardiac_efficiency_majority_elevation_unknown():
    """
    5 runs with valid HR/distance/duration, but only 2 have elevation_gain_m.
    < 4 samples with BOTH valid efficiency AND known elevation_rate → unknown.
    """
    acts_with_elev = [
        _run(i * 4, distance_m=10_000.0, duration_s=3600.0, average_hr=150.0,
             elevation_gain_m=40.0)
        for i in range(2)
    ]
    acts_no_elev = [
        _run(10 + i * 4, distance_m=10_000.0, duration_s=3600.0, average_hr=150.0,
             elevation_gain_m=None)
        for i in range(3)
    ]
    acts = acts_with_elev + acts_no_elev
    result = build_recent_training_response(acts, REF)
    assert result.cardiac_efficiency_trend == "unknown", (
        "Majority elevation unknown: conservative → unknown"
    )


# ---------------------------------------------------------------------------
# §17-D — no terrain speed correction in source
# ---------------------------------------------------------------------------

def test_17D_no_terrain_speed_correction_in_source():
    """
    Verify no grade-adjusted pace / speed correction formula is implemented in
    training_response.py.  Structural guard: no forbidden identifier in code.
    """
    import training_v2.training_response as mod
    src = open(mod.__file__).read()
    # These are code-level identifiers for terrain speed corrections — never allowed.
    # Comments and docstrings are excluded by checking only assignment/call patterns.
    forbidden_code = ["grade_adjusted", "trail_factor", "elevation_factor", "speed_adjusted"]
    for token in forbidden_code:
        assert token not in src, (
            f"Forbidden terrain correction identifier '{token}' found in source"
        )



# ---------------------------------------------------------------------------
# §17-E — BLOCKING: unknown-terrain samples must NOT influence the trend
# ---------------------------------------------------------------------------

def test_17E_unknown_terrain_does_not_influence_trend():
    """
    4 runs with stable efficiency AND known flat terrain (comparable).
    2 additional runs with valid but extreme efficiency AND elevation_gain_m=None.

    Expected: cardiac_efficiency_trend is computed ONLY on the 4 comparable
    samples → "stable".  The 2 unknown-terrain extremes must NOT shift the
    trend to increasing/decreasing.

    This test would have FAILED with the old code (which used valid_efficiencies
    including terrain-unknown activities).

    Comparable runs: distance=10 000 m, duration=3 600 s, HR=150 → eff≈0.01852
    elevation_gain_m=40 → rate=4 m/km (flat).  All 4 identical → stable.

    Unknown-terrain runs: same distance/duration, HR=30 (extremely high eff)
    elevation_gain_m=None → must be excluded from trend.
    """
    # 4 comparable, stable runs — oldest first (days_ago 20,15,10,5)
    comparable_acts = [
        _run(
            days_ago,
            distance_m=10_000.0,
            duration_s=3_600.0,
            average_hr=150.0,
            elevation_gain_m=40.0,   # 4 m/km — flat
        )
        for days_ago in (20, 15, 10, 5)
    ]
    # 2 unknown-terrain runs with extreme efficiency (very low HR → very high eff)
    unknown_terrain_acts = [
        _run(
            days_ago,
            distance_m=10_000.0,
            duration_s=3_600.0,
            average_hr=30.0,         # extreme efficiency value
            elevation_gain_m=None,   # terrain unknown — must NOT enter trend
        )
        for days_ago in (25, 3)
    ]
    acts = comparable_acts + unknown_terrain_acts
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    # The 2 extreme unknown-terrain runs must not shift the trend
    assert result.cardiac_efficiency_trend == "stable", (
        "Unknown-terrain samples must be excluded from trend; "
        f"got {result.cardiac_efficiency_trend!r} instead of 'stable'"
    )


# ---------------------------------------------------------------------------
# §15-extra — frequency_pattern: no old-half baseline → unknown
# ---------------------------------------------------------------------------

def test_frequency_pattern_unknown_no_old_half_baseline():
    """
    All 5 runs in recent half (no runs in old half) → no baseline → unknown.
    Consistent with volume_trend behaviour when old_half has no data.
    """
    acts = [_run(i) for i in range(5)]  # days_ago 0..4, all in recent half
    result = build_recent_training_response(acts, REF)
    assert result.response_status == "sufficient"
    assert result.frequency_pattern == "unknown"
