import os
import sys
from pathlib import Path


_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from training_engine import (  # noqa: E402
    DEFAULT_WEEKLY_KM,
    compute_current_weekly_km,
    compute_target_km,
    is_running,
    normalized_distance_km,
)


def test_normalized_distance_km_distance_km():
    assert normalized_distance_km({"distance_km": 10}) == 10


def test_normalized_distance_km_distance_meters():
    assert normalized_distance_km({"distance": 10000}) == 10


def test_normalized_distance_km_distance_kilometers():
    assert normalized_distance_km({"distance": 10}) == 10


def test_normalized_distance_km_missing_none_invalid():
    assert normalized_distance_km({}) == 0
    assert normalized_distance_km({"distance_km": None}) == 0
    assert normalized_distance_km({"distance": "invalid"}) == 0


def test_is_running_allowed_types():
    assert is_running({"type": "run"})
    assert is_running({"type": "running"})
    assert is_running({"type": "trail_running"})
    assert is_running({"type": "treadmill_running"})


def test_is_running_rejects_non_running():
    assert not is_running({"type": "cycling"})
    assert not is_running({"type": "swimming"})
    assert not is_running({"type": "walking"})
    assert not is_running({"type": "strength_training"})


def test_compute_current_weekly_km_four_weeks_normal():
    workouts_28 = [{"type": "run", "distance_km": 20}] * 4
    assert compute_current_weekly_km(workouts_28) == 20


def test_compute_current_weekly_km_no_activity_fallback():
    assert compute_current_weekly_km([]) == DEFAULT_WEEKLY_KM


def test_compute_current_weekly_km_running_only():
    workouts_28 = [
        {"type": "run", "distance_km": 20},
        {"type": "cycling", "distance_km": 50},
        {"type": "swimming", "distance_km": 10},
    ]
    assert compute_current_weekly_km(workouts_28) == 5


def test_compute_current_weekly_km_mixed_formats():
    workouts_28 = [
        {"type": "run", "distance_km": 10},
        {"type": "running", "distance": 10000},
        {"type": "trail_running", "distance": 8},
        {"type": "cycling", "distance": 100000},
    ]
    assert compute_current_weekly_km(workouts_28) == 7


def test_compute_current_weekly_km_no_running_fallback():
    workouts_28 = [
        {"type": "cycling", "distance_km": 50},
        {"type": "swimming", "distance": 10000},
    ]
    assert compute_current_weekly_km(workouts_28) == DEFAULT_WEEKLY_KM


def test_compute_target_km_pr2_non_regression():
    assert compute_target_km(20, "SEMI", "taper") == 11


def test_source_unique_usage_in_plan_paths():
    root = Path(__file__).resolve().parents[1]
    coach_src = (root / "coach_service.py").read_text(encoding="utf-8")
    server_src = (root / "server.py").read_text(encoding="utf-8")
    assert "weekly_km = compute_current_weekly_km(workouts_28)" in coach_src
    assert "base_weekly_km = compute_current_weekly_km(workouts_28)" in server_src
    assert '"weekly_km": compute_current_weekly_km(workouts_28)' in server_src
    assert "else 25" not in server_src
    assert "km_7 < 0.5" not in coach_src
    assert "km_7 < 0.5" not in server_src
