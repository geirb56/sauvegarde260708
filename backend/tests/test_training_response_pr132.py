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
    # Most recent 10 selected → oldest (days_ago=20) excluded
    # Verify total distance: 10 × 8 km
    assert result.observed_distance_km == pytest.approx(80.0)


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
