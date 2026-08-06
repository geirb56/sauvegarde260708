"""PR07 — Tests for RunnerProfile V2.

All tests use a fixed reference_date of 2026-08-06 for full determinism.

Run from the backend directory:
    python -m pytest tests/test_runner_profile_pr07.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from garmin.data_layer import GarminCapabilities
from training_v2 import RunnerProfile, TrainingHistory, TrainingLoadSnapshot, TrainingWindow, build_runner_profile

REF = date(2026, 8, 6)


def _window(
    *,
    days: int,
    distance_km: float = 0.0,
    duration_hours: float = 0.0,
    activity_count: int = 0,
    average_speed_kmh: float | None = None,
    longest_run_km: float | None = None,
) -> TrainingWindow:
    return TrainingWindow(
        days=days,
        distance_km=distance_km,
        duration_hours=duration_hours,
        activity_count=activity_count,
        average_speed_kmh=average_speed_kmh,
        longest_run_km=longest_run_km,
    )


def _history(
    *,
    available_history_days: int = 0,
    window_30d: TrainingWindow | None = None,
    window_90d: TrainingWindow | None = None,
) -> TrainingHistory:
    window_30d = window_30d or _window(days=30)
    window_90d = window_90d or _window(days=90)
    has_any = any(
        (
            window_30d.activity_count > 0,
            window_90d.activity_count > 0,
            window_30d.distance_km > 0,
            window_90d.distance_km > 0,
            window_30d.duration_hours > 0,
            window_90d.duration_hours > 0,
        )
    )
    return TrainingHistory(
        window_7d=_window(days=7),
        window_30d=window_30d,
        window_90d=window_90d,
        days_since_last_run=0 if has_any else None,
        last_run_date=REF.isoformat() if has_any else None,
        available_history_days=available_history_days,
        has_7d_history=has_any and available_history_days >= 7,
        has_30d_history=has_any and available_history_days >= 30,
        has_90d_history=has_any and available_history_days >= 90,
        has_any_running_history=has_any,
    )


def _load() -> TrainingLoadSnapshot:
    return TrainingLoadSnapshot(
        reference_date=REF,
        acute_load_7d=0.0,
        load_28d=0.0,
        chronic_weekly_load=0.0,
        acwr=None,
        status="unavailable",
        is_available=False,
        has_sufficient_history=False,
        confidence="none",
        activities_7d=0,
        activities_28d=0,
        previous_7d_load=0.0,
        load_change_percent=None,
    )


def _build(
    *,
    training_history: TrainingHistory | None = None,
    user_profile: dict | None = None,
    garmin_capabilities: GarminCapabilities | None = None,
    physiological_metrics: dict | None = None,
) -> RunnerProfile:
    return build_runner_profile(
        training_history=training_history or _history(),
        training_load=_load(),
        user_profile=user_profile,
        garmin_capabilities=garmin_capabilities,
        physiological_metrics=physiological_metrics,
        reference_date=REF,
    )


def test_empty_history_has_no_fallback_and_unknown_profile():
    profile = _build()
    assert profile.experience_level == "unknown"
    assert profile.typical_weekly_km is None
    assert profile.typical_weekly_hours is None
    assert profile.typical_runs_per_week is None
    assert profile.typical_long_run_km is None
    assert profile.typical_speed_kmh is None
    assert profile.available_history_days == 0
    assert profile.profile_confidence == "none"
    assert profile.primary_discipline == "unknown"


def test_declared_profile_without_history_is_blocking_case():
    profile = _build(
        user_profile={
            "weekly_km": 25,
            "discipline": "road",
            "preferred_days_per_week": 3,
        }
    )
    assert profile.typical_weekly_km == 25.0
    assert profile.primary_discipline == "road"
    assert profile.preferred_days_per_week == 3
    assert profile.experience_level == "unknown"
    assert profile.profile_confidence == "low"


def test_typical_metrics_are_built_from_30d_history():
    profile = _build(
        training_history=_history(
            available_history_days=30,
            window_30d=_window(
                days=30,
                distance_km=120.0,
                duration_hours=12.0,
                activity_count=12,
                average_speed_kmh=10.0,
                longest_run_km=18.0,
            ),
        )
    )
    assert profile.typical_weekly_km == 28.0
    assert profile.typical_weekly_hours == 2.8
    assert profile.typical_runs_per_week == 2.8
    assert profile.typical_long_run_km == 18.0
    assert profile.typical_speed_kmh == 10.0


def test_no_intermediate_rounding_is_applied():
    profile = _build(
        training_history=_history(
            available_history_days=30,
            window_30d=_window(
                days=30,
                distance_km=100.01,
                duration_hours=10.01,
                activity_count=5,
            ),
        )
    )
    assert profile.typical_weekly_km == round(100.01 * 7.0 / 30.0, 2)
    assert profile.typical_weekly_hours == round(10.01 * 7.0 / 30.0, 2)
    assert profile.typical_runs_per_week == round(5 * 7.0 / 30.0, 2)


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, "unknown"),
        (29, "beginner"),
        (30, "developing"),
        (89, "developing"),
        (90, "established"),
        (364, "established"),
        (365, "experienced"),
    ],
)
def test_experience_levels_follow_history_depth(days, expected):
    profile = _build(
        training_history=_history(
            available_history_days=days,
            window_30d=_window(days=30, activity_count=1, distance_km=10.0),
        )
    )
    assert profile.experience_level == expected


@pytest.mark.parametrize(
    ("history_days", "user_profile", "expected"),
    [
        (0, None, "none"),
        (0, {"weekly_km": 25}, "low"),
        (10, None, "low"),
        (30, None, "medium"),
        (90, None, "high"),
    ],
)
def test_profile_confidence_levels(history_days, user_profile, expected):
    history = _history(
        available_history_days=history_days,
        window_30d=_window(days=30, activity_count=1, distance_km=10.0) if history_days else _window(days=30),
    )
    profile = _build(training_history=history, user_profile=user_profile)
    assert profile.profile_confidence == expected


def test_absent_physiology_stays_absent():
    profile = _build(user_profile={"age": 42})
    assert profile.vo2max is None
    assert profile.vma_kmh is None
    assert profile.max_hr is None
    assert profile.resting_hr is None


def test_present_physiology_is_preserved_exactly():
    profile = _build(
        physiological_metrics={
            "vo2max": 52.4,
            "vma_kmh": 15.8,
            "max_hr": 189,
            "resting_hr": 48,
        }
    )
    assert profile.vo2max == 52.4
    assert profile.vma_kmh == 15.8
    assert profile.max_hr == 189
    assert profile.resting_hr == 48


def test_no_implicit_vma_or_max_hr_estimation():
    profile = _build(
        user_profile={"age": 36},
        physiological_metrics={"vo2max": 50.0},
    )
    assert profile.vo2max == 50.0
    assert profile.vma_kmh is None
    assert profile.max_hr is None


def test_capabilities_are_copied_deterministically():
    profile = _build(
        garmin_capabilities=GarminCapabilities(
            has_hrv=True,
            has_vo2max=False,
            has_training_readiness=True,
            has_power=False,
            has_running_dynamics=True,
        )
    )
    assert profile.has_hrv is True
    assert profile.has_vo2max is False
    assert profile.has_training_readiness is True
    assert profile.has_power is False
    assert profile.has_running_dynamics is True


def test_absent_capabilities_default_to_false():
    profile = _build()
    assert profile.has_hrv is False
    assert profile.has_vo2max is False
    assert profile.has_training_readiness is False
    assert profile.has_power is False
    assert profile.has_running_dynamics is False


def test_constraints_are_normalized_without_interpretation():
    profile = _build(
        user_profile={
            "injury_constraints": [" knee ", "", "hamstring"],
            "availability_constraints": None,
        }
    )
    assert profile.injury_constraints == ["knee", "hamstring"]
    assert profile.availability_constraints == []


def test_days_per_week_validation_and_incompatibility():
    zero_days = _build(user_profile={"preferred_days_per_week": 0, "max_days_per_week": 7})
    one_day = _build(user_profile={"preferred_days_per_week": 1, "max_days_per_week": 7})
    seven_days = _build(user_profile={"preferred_days_per_week": 7, "max_days_per_week": 7})
    eight_days = _build(user_profile={"preferred_days_per_week": 8, "max_days_per_week": 8})
    incompatible = _build(user_profile={"preferred_days_per_week": 5, "max_days_per_week": 4})

    assert zero_days.preferred_days_per_week is None
    assert one_day.preferred_days_per_week == 1
    assert seven_days.preferred_days_per_week == 7
    assert eight_days.preferred_days_per_week is None
    assert incompatible.preferred_days_per_week is None
    assert incompatible.max_days_per_week == 4


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("road", "road"),
        ("running", "road"),
        ("trail", "trail"),
        ("trail_running", "trail"),
        ("treadmill", "treadmill"),
        ("treadmill_running", "treadmill"),
        ("mixed", "mixed"),
        ("unknown", "unknown"),
        ("unsupported", "unknown"),
    ],
)
def test_primary_discipline_mapping(raw_value, expected):
    profile = _build(user_profile={"discipline": raw_value})
    assert profile.primary_discipline == expected


def test_model_is_frozen():
    profile = _build(user_profile={"weekly_km": 25})
    with pytest.raises(Exception):
        profile.typical_weekly_km = 30.0


def test_identical_inputs_produce_identical_models():
    history = _history(
        available_history_days=90,
        window_30d=_window(days=30, distance_km=120.0, duration_hours=12.0, activity_count=12, longest_run_km=18.0),
    )
    kwargs = {
        "training_history": history,
        "user_profile": {"discipline": "road", "preferred_days_per_week": 3},
        "garmin_capabilities": GarminCapabilities(has_hrv=True),
        "physiological_metrics": {"resting_hr": 50},
    }
    profile_a = _build(**kwargs)
    profile_b = _build(**kwargs)
    assert profile_a == profile_b


def test_90d_window_is_only_a_fallback_when_30d_is_insufficient():
    profile = _build(
        training_history=_history(
            available_history_days=90,
            window_30d=_window(days=30),
            window_90d=_window(days=90, distance_km=180.0, duration_hours=18.0, activity_count=18, longest_run_km=22.0),
        )
    )
    assert profile.typical_weekly_km == 14.0
    assert profile.typical_weekly_hours == 1.4
    assert profile.typical_runs_per_week == 1.4
    assert profile.typical_long_run_km == 22.0


def test_90d_fallback_is_blocked_when_history_depth_is_below_90_days():
    profile = _build(
        training_history=_history(
            available_history_days=45,
            window_30d=_window(days=30, average_speed_kmh=None),
            window_90d=_window(days=90, average_speed_kmh=11.5),
        ),
        user_profile={},
    )
    assert profile.typical_speed_kmh is None


def test_90d_fallback_is_used_when_history_depth_reaches_90_days():
    profile = _build(
        training_history=_history(
            available_history_days=90,
            window_30d=_window(days=30, average_speed_kmh=None),
            window_90d=_window(days=90, average_speed_kmh=11.5),
        )
    )
    assert profile.typical_speed_kmh == 11.5


def test_declared_metric_aliases_use_first_valid_value():
    profile = _build(
        user_profile={
            "typical_weekly_km": 42,
            "weekly_km": 39,
            "typical_weekly_hours": 4.5,
            "weekly_hours": 4.0,
            "typical_runs_per_week": 5,
            "runs_per_week": 4,
            "typical_long_run_km": 21,
            "long_run_km": 18,
            "typical_speed_kmh": 12.5,
            "average_speed_kmh": 11.0,
        }
    )
    assert profile.typical_weekly_km == 42.0
    assert profile.typical_weekly_hours == 4.5
    assert profile.typical_runs_per_week == 5.0
    assert profile.typical_long_run_km == 21.0
    assert profile.typical_speed_kmh == 12.5


def test_declared_metric_aliases_fall_back_to_official_secondary_keys():
    profile = _build(
        user_profile={
            "typical_weekly_km": None,
            "weekly_km": 39,
            "typical_weekly_hours": "",
            "weekly_hours": 4.0,
            "typical_runs_per_week": 0,
            "runs_per_week": 4,
            "typical_long_run_km": -1,
            "long_run_km": 18,
            "typical_speed_kmh": "invalid",
            "average_speed_kmh": 11.0,
        }
    )
    assert profile.typical_weekly_km == 39.0
    assert profile.typical_weekly_hours == 4.0
    assert profile.typical_runs_per_week == 4.0
    assert profile.typical_long_run_km == 18.0
    assert profile.typical_speed_kmh == 11.0
