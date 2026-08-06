"""PR07 — Tests for RunnerProfile V2."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garmin.data_layer import GarminCapabilities
from training_v2.runner_profile import build_runner_profile
from training_v2.training_history import build_training_history
from training_v2.training_load import build_training_load

REF = date(2026, 8, 6)


def _act(days_ago: int, *, distance_m: float = 10_000.0, duration_s: float = 3600.0) -> dict:
    run_date = REF - timedelta(days=days_ago)
    return {
        "activity_type": "running",
        "start_time": run_date.isoformat() + "T08:00:00.0",
        "distance": distance_m,
        "duration": duration_s,
    }


def _profile(activities, user_profile=None, physiological_metrics=None):
    history = build_training_history(activities, REF)
    load = build_training_load(activities, REF)
    return build_runner_profile(
        training_history=history,
        training_load_snapshot=load,
        garmin_capabilities=GarminCapabilities(),
        user_profile=user_profile or {},
        physiological_metrics=physiological_metrics or {},
        reference_date=REF,
    )


def test_declared_profile_without_history_is_low_confidence():
    p = _profile(
        activities=[],
        user_profile={
            "weekly_km": 25,
            "discipline": "road",
            "preferred_days_per_week": 3,
        },
    )

    assert p.typical_weekly_km == 25
    assert p.primary_discipline == "road"
    assert p.experience_level == "unknown"
    assert p.profile_confidence == "low"


def test_empty_profile_without_history_is_none_confidence():
    p = _profile(activities=[], user_profile={})

    assert p.experience_level == "unknown"
    assert p.profile_confidence == "none"


def test_experience_and_confidence_follow_history_depth_only():
    acts_45d = [_act(44), _act(20), _act(3)]
    p_45d = _profile(acts_45d, user_profile={"weekly_km": 999})
    assert p_45d.experience_level == "developing"
    assert p_45d.profile_confidence == "medium"

    acts_365d = [_act(364), _act(150), _act(2)]
    p_365d = _profile(acts_365d)
    assert p_365d.experience_level == "experienced"
    assert p_365d.profile_confidence == "high"


def test_observed_30d_priority_then_90d_fallback_per_metric():
    # distance present in 30d => priority to 30d
    # speed absent in 30d, present in 90d => fallback to 90d when >=90d history
    activities = [
        _act(5, distance_m=10_000, duration_s=None),      # adds distance in 30d, no speed
        _act(85, distance_m=18_000, duration_s=5400),     # contributes speed in 90d only
        _act(89, distance_m=12_000, duration_s=3600),     # ensures >=90 days available
    ]

    p = _profile(activities)

    assert p.typical_weekly_km == 2.33  # 10 * 7 / 30
    assert p.typical_speed_kmh == 12.0  # 90d fallback (distance+duration pool)
