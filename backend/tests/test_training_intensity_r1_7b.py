"""R1.7B — Tests for TrainingIntensityProfile.

Covers test cases A through M as specified in the problem statement.
"""
from __future__ import annotations

import sys
import os
from datetime import date, timedelta, datetime
from typing import Optional

import pytest

# Ensure the backend package is importable when running from repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from training_v2.training_intensity import (
    TrainingIntensityProfile,
    build_training_intensity_profile,
)
from training_v2.domain_activity import DomainActivity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF = date(2026, 8, 12)  # arbitrary fixed reference date


def _running(
    *,
    start: date = REF,
    duration_s: Optional[float] = 3600.0,
    moderate: Optional[float] = None,
    vigorous: Optional[float] = None,
    activity_type: str = "running",
) -> DomainActivity:
    return DomainActivity(
        activity_type=activity_type,
        start_time=start,
        duration_s=duration_s,
        moderate_intensity_minutes=moderate,
        vigorous_intensity_minutes=vigorous,
    )


# ---------------------------------------------------------------------------
# A — no activities
# ---------------------------------------------------------------------------


def test_a_no_activities():
    profile = build_training_intensity_profile([], REF)
    assert profile.duration_minutes == 0.0
    assert profile.moderate_minutes is None
    assert profile.vigorous_minutes is None
    assert profile.activities_total == 0
    assert profile.activities_with_intensity == 0
    assert profile.activities_without_intensity == 0
    assert profile.intensity_coverage_ratio is None


# ---------------------------------------------------------------------------
# B — one 60-min running activity yesterday with known moderate and vigorous
# ---------------------------------------------------------------------------


def test_b_single_activity_yesterday():
    act = _running(
        start=REF - timedelta(days=1),
        duration_s=3600.0,
        moderate=30.0,
        vigorous=10.0,
    )
    profile = build_training_intensity_profile([act], REF)
    assert profile.duration_minutes == 60.0
    assert profile.moderate_minutes == 30.0
    assert profile.vigorous_minutes == 10.0
    assert profile.activities_total == 1
    assert profile.activities_with_intensity == 1
    assert profile.activities_without_intensity == 0
    assert profile.intensity_coverage_ratio == 1.0


# ---------------------------------------------------------------------------
# C — two activities with partial intensity data
# ---------------------------------------------------------------------------


def test_c_two_activities_partial_intensity():
    a = _running(start=REF, duration_s=1800.0, moderate=20.0, vigorous=None)
    b = _running(start=REF - timedelta(days=1), duration_s=1800.0, moderate=None, vigorous=10.0)
    profile = build_training_intensity_profile([a, b], REF)
    assert profile.moderate_minutes == 20.0
    assert profile.vigorous_minutes == 10.0
    assert profile.activities_total == 2
    assert profile.activities_with_intensity == 2
    assert profile.intensity_coverage_ratio == 1.0


# ---------------------------------------------------------------------------
# D — explicit zero is a known datum; activity is WITH intensity
# ---------------------------------------------------------------------------


def test_d_explicit_zero_counts_as_known():
    act = _running(start=REF, duration_s=1800.0, moderate=0.0, vigorous=0.0)
    profile = build_training_intensity_profile([act], REF)
    assert profile.moderate_minutes == 0.0
    assert profile.vigorous_minutes == 0.0
    assert profile.activities_with_intensity == 1
    assert profile.activities_without_intensity == 0
    assert profile.intensity_coverage_ratio == 1.0


# ---------------------------------------------------------------------------
# E — both fields None → WITHOUT intensity; coverage = 0.0
# ---------------------------------------------------------------------------


def test_e_both_none_without_intensity():
    act = _running(start=REF, duration_s=1800.0, moderate=None, vigorous=None)
    profile = build_training_intensity_profile([act], REF)
    assert profile.moderate_minutes is None
    assert profile.vigorous_minutes is None
    assert profile.activities_without_intensity == 1
    assert profile.activities_with_intensity == 0
    assert profile.intensity_coverage_ratio == 0.0


# ---------------------------------------------------------------------------
# F — one known, one unknown → coverage = 0.5
# ---------------------------------------------------------------------------


def test_f_mixed_coverage():
    known = _running(start=REF, duration_s=1800.0, moderate=10.0, vigorous=None)
    unknown = _running(start=REF - timedelta(days=1), duration_s=1800.0, moderate=None, vigorous=None)
    profile = build_training_intensity_profile([known, unknown], REF)
    assert profile.activities_total == 2
    assert profile.activities_with_intensity == 1
    assert profile.activities_without_intensity == 1
    assert profile.intensity_coverage_ratio == 0.5


# ---------------------------------------------------------------------------
# G — activity on J-2 is excluded
# ---------------------------------------------------------------------------


def test_g_activity_j_minus_2_excluded():
    old = _running(start=REF - timedelta(days=2), duration_s=3600.0, moderate=30.0, vigorous=10.0)
    profile = build_training_intensity_profile([old], REF)
    assert profile.activities_total == 0
    assert profile.duration_minutes == 0.0
    assert profile.moderate_minutes is None
    assert profile.vigorous_minutes is None
    assert profile.intensity_coverage_ratio is None


# ---------------------------------------------------------------------------
# H — future activity is excluded
# ---------------------------------------------------------------------------


def test_h_future_activity_excluded():
    future = _running(start=REF + timedelta(days=1), duration_s=3600.0, moderate=30.0)
    profile = build_training_intensity_profile([future], REF)
    assert profile.activities_total == 0


# ---------------------------------------------------------------------------
# I — non-running activity is excluded
# ---------------------------------------------------------------------------


def test_i_non_running_excluded():
    cycling = DomainActivity(
        activity_type="cycling",
        start_time=REF,
        duration_s=3600.0,
        moderate_intensity_minutes=40.0,
        vigorous_intensity_minutes=20.0,
    )
    profile = build_training_intensity_profile([cycling], REF)
    assert profile.activities_total == 0
    assert profile.intensity_coverage_ratio is None


# ---------------------------------------------------------------------------
# J — invalid duration but valid intensity: activity counted, duration skipped
# ---------------------------------------------------------------------------


def test_j_invalid_duration_valid_intensity():
    act = _running(start=REF, duration_s=None, moderate=25.0, vigorous=5.0)
    profile = build_training_intensity_profile([act], REF)
    assert profile.activities_total == 1
    assert profile.duration_minutes == 0.0
    assert profile.moderate_minutes == 25.0
    assert profile.vigorous_minutes == 5.0
    assert profile.activities_with_intensity == 1


# ---------------------------------------------------------------------------
# K — determinism with explicit reference_date
# ---------------------------------------------------------------------------


def test_k_determinism():
    acts = [
        _running(start=REF, duration_s=1800.0, moderate=15.0, vigorous=5.0),
        _running(start=REF - timedelta(days=1), duration_s=1800.0, moderate=10.0, vigorous=3.0),
    ]
    p1 = build_training_intensity_profile(acts, REF)
    p2 = build_training_intensity_profile(acts, REF)
    assert p1 == p2
    assert p1.reference_date == REF
    assert p1.window_days == 2


# ---------------------------------------------------------------------------
# L — no provider dependency (import check)
# ---------------------------------------------------------------------------


def test_l_no_provider_dependency():
    import importlib
    import training_v2.training_intensity as mod

    source = mod.__file__
    with open(source) as fh:
        lines = fh.readlines()

    # Detect actual import statements referencing provider namespaces.
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(("#", '"""', "'")):
            for forbidden in ("import garmin", "import terra", "import strava",
                              "from garmin", "from terra", "from strava"):
                assert forbidden not in stripped, (
                    f"training_intensity.py must not import provider namespace: {stripped!r}"
                )


# ---------------------------------------------------------------------------
# M — existing TrainingHistory + TrainingLoad + DomainActivity tests still pass
# ---------------------------------------------------------------------------


def test_m_existing_modules_importable():
    """Smoke-check that the three audited modules can be imported cleanly."""
    from training_v2.training_history import TrainingHistory, build_training_history
    from training_v2.training_load import TrainingLoadSnapshot, build_training_load
    from training_v2.domain_activity import DomainActivity

    assert TrainingHistory is not None
    assert TrainingLoadSnapshot is not None
    assert DomainActivity is not None


# ---------------------------------------------------------------------------
# Extra: verify trail_running and treadmill_running are also included
# ---------------------------------------------------------------------------


def test_running_subtypes_included():
    trail = _running(start=REF, duration_s=1800.0, moderate=5.0, activity_type="trail_running")
    tread = _running(start=REF, duration_s=900.0, vigorous=8.0, activity_type="treadmill_running")
    profile = build_training_intensity_profile([trail, tread], REF)
    assert profile.activities_total == 2
    assert profile.moderate_minutes == 5.0
    assert profile.vigorous_minutes == 8.0


# ---------------------------------------------------------------------------
# Extra: None + 0 → 0 (not None)
# ---------------------------------------------------------------------------


def test_none_plus_zero_equals_zero():
    a = _running(start=REF, duration_s=1800.0, moderate=0.0, vigorous=None)
    b = _running(start=REF - timedelta(days=1), duration_s=1800.0, moderate=None, vigorous=None)
    profile = build_training_intensity_profile([a, b], REF)
    assert profile.moderate_minutes == 0.0
    assert profile.vigorous_minutes is None


# ---------------------------------------------------------------------------
# Extra: TrainingIntensityProfile is immutable
# ---------------------------------------------------------------------------


def test_profile_is_immutable():
    profile = build_training_intensity_profile([], REF)
    with pytest.raises(Exception):
        profile.duration_minutes = 999.0  # type: ignore[misc]
