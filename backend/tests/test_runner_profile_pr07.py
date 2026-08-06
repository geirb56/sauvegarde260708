"""PR07 — Tests for RunnerProfile."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garmin.data_layer import GarminCapabilities
from training_v2.runner_profile import RunnerProfile, build_runner_profile
from training_v2.training_history import TrainingHistory, TrainingWindow, build_training_history
from training_v2.training_load import build_training_load

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
    return TrainingHistory(
        window_7d=_window(days=7),
        window_30d=window_30d or _window(days=30),
        window_90d=window_90d or _window(days=90),
        days_since_last_run=None,
        last_run_date=None,
        available_history_days=available_history_days,
        has_7d_history=available_history_days >= 7,
        has_30d_history=available_history_days >= 30,
        has_90d_history=available_history_days >= 90,
        has_any_running_history=available_history_days > 0,
    )


def _profile(
    *,
    training_history: TrainingHistory | None = None,
    user_profile: dict | None = None,
    garmin_capabilities: GarminCapabilities | None = None,
    physiological_metrics: dict | None = None,
) -> RunnerProfile:
    return build_runner_profile(
        training_history=training_history or _history(),
        training_load=build_training_load([], REF),
        user_profile=user_profile,
        garmin_capabilities=garmin_capabilities,
        physiological_metrics=physiological_metrics,
        reference_date=REF,
    )


def test_empty_history_has_no_fallback_and_unknown_profile():
    profile = _profile()

    assert profile.experience_level == "unknown"
    assert profile.typical_weekly_km is None
    assert profile.typical_weekly_hours is None
    assert profile.typical_runs_per_week is None
    assert profile.typical_long_run_km is None
    assert profile.typical_speed_kmh is None
    assert profile.available_history_days == 0
    assert profile.profile_confidence == "none"


def test_typical_metrics_are_computed_from_30_day_window():
    history = _history(
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

    profile = _profile(training_history=history)

    assert profile.typical_weekly_km == 28.0
    assert profile.typical_weekly_hours == 2.8
    assert profile.typical_runs_per_week == 2.8
    assert profile.typical_long_run_km == 18.0
    assert profile.typical_speed_kmh == 10.0


def test_rounding_happens_only_on_final_output():
    history = _history(
        available_history_days=30,
        window_30d=_window(
            days=30,
            distance_km=100.01,
            duration_hours=10.01,
            activity_count=5,
            average_speed_kmh=10.01,
            longest_run_km=15.55,
        ),
    )

    profile = _profile(training_history=history)

    assert profile.typical_weekly_km == 23.34
    assert profile.typical_weekly_hours == 2.34
    assert profile.typical_runs_per_week == 1.17


@pytest.mark.parametrize(
    ("history_days", "expected"),
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
def test_experience_level_thresholds(history_days: int, expected: str):
    assert _profile(training_history=_history(available_history_days=history_days)).experience_level == expected


@pytest.mark.parametrize(
    ("history_days", "expected"),
    [
        (0, "none"),
        (29, "low"),
        (30, "medium"),
        (89, "medium"),
        (90, "high"),
    ],
)
def test_profile_confidence_thresholds(history_days: int, expected: str):
    assert _profile(training_history=_history(available_history_days=history_days)).profile_confidence == expected


def test_absent_physiology_stays_absent():
    profile = _profile()

    assert profile.vo2max is None
    assert profile.vma_kmh is None
    assert profile.max_hr is None
    assert profile.resting_hr is None


def test_present_physiology_is_preserved_exactly():
    profile = _profile(
        user_profile={"max_hr": 189},
        physiological_metrics={
            "vo2max": 52.4,
            "vma_kmh": 16.2,
            "resting_hr": 48,
        },
    )

    assert profile.vo2max == 52.4
    assert profile.vma_kmh == 16.2
    assert profile.max_hr == 189
    assert profile.resting_hr == 48


def test_no_implicit_estimations_are_added():
    profile = _profile(
        user_profile={"age": 40},
        physiological_metrics={"vo2max": 51.2},
    )

    assert profile.vo2max == 51.2
    assert profile.vma_kmh is None
    assert profile.max_hr is None


def test_garmin_capabilities_are_copied_deterministically():
    rich = _profile(
        garmin_capabilities=GarminCapabilities(
            has_hrv=True,
            has_vo2max=True,
            has_training_readiness=True,
            has_power=True,
            has_running_dynamics=True,
        )
    )
    absent = _profile(garmin_capabilities=None)
    empty = _profile(garmin_capabilities=GarminCapabilities())

    assert rich.has_hrv is True
    assert rich.has_vo2max is True
    assert rich.has_training_readiness is True
    assert rich.has_power is True
    assert rich.has_running_dynamics is True

    assert absent.has_hrv is False
    assert absent.has_vo2max is False
    assert absent.has_training_readiness is False
    assert absent.has_power is False
    assert absent.has_running_dynamics is False

    assert empty.has_hrv is False
    assert empty.has_vo2max is False
    assert empty.has_training_readiness is False
    assert empty.has_power is False
    assert empty.has_running_dynamics is False


def test_constraints_are_normalised_without_interpretation():
    empty = _profile()
    filled = _profile(
        user_profile={
            "preferred_long_run_day": " Sunday ",
            "injury_constraints": [" knee pain ", "", "no downhill"],
            "availability_constraints": [" Tuesday evening ", "Saturday"],
        }
    )

    assert empty.injury_constraints == []
    assert empty.availability_constraints == []
    assert empty.preferred_long_run_day is None

    assert filled.preferred_long_run_day == "sunday"
    assert filled.injury_constraints == ["knee pain", "no downhill"]
    assert filled.availability_constraints == ["Tuesday evening", "Saturday"]


@pytest.mark.parametrize(
    ("user_profile", "expected_preferred", "expected_max"),
    [
        ({"preferred_days_per_week": 0}, None, None),
        ({"preferred_days_per_week": 1}, 1, None),
        ({"preferred_days_per_week": 7, "max_days_per_week": 7}, 7, 7),
        ({"max_days_per_week": 8}, None, None),
        ({"preferred_days_per_week": 5, "max_days_per_week": 4}, None, 4),
    ],
)
def test_days_per_week_validation(user_profile: dict, expected_preferred: int | None, expected_max: int | None):
    profile = _profile(user_profile=user_profile)

    assert profile.preferred_days_per_week == expected_preferred
    assert profile.max_days_per_week == expected_max


def test_model_is_immutable():
    profile = _profile()
    with pytest.raises(Exception):
        profile.age = 99  # type: ignore[misc]


def test_determinism():
    activities = [
        {
            "activity_type": "running",
            "start_time": "2026-08-02T08:00:00",
            "distance": 10_000.0,
            "duration": 3600.0,
        },
        {
            "activity_type": "running",
            "start_time": "2026-07-20T08:00:00",
            "distance": 18_000.0,
            "duration": 7200.0,
        },
    ]
    history = build_training_history(activities, REF)
    caps = GarminCapabilities(has_hrv=True, has_power=False)
    user_profile = {
        "age": 41,
        "sex": "M",
        "discipline": "trail_running",
        "preferred_days_per_week": 4,
        "max_days_per_week": 5,
        "preferred_long_run_day": "Saturday",
        "injury_constraints": ["achilles"],
        "availability_constraints": ["Wednesday"],
        "max_hr": 188,
    }
    physiological_metrics = {"vo2max": 50.5, "resting_hr": 49}

    profile_a = _profile(
        training_history=history,
        user_profile=user_profile,
        garmin_capabilities=caps,
        physiological_metrics=physiological_metrics,
    )
    profile_b = _profile(
        training_history=history,
        user_profile=user_profile,
        garmin_capabilities=caps,
        physiological_metrics=physiological_metrics,
    )

    assert profile_a == profile_b
