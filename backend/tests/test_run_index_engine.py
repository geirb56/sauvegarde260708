from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.run_index_engine import calculate_run_index


def _run(days_ago: int, distance_km: float, pace_min_km: float, avg_hr: int | None = None) -> dict:
    duration_minutes = distance_km * pace_min_km
    return {
        "type": "run",
        "date": (date(2026, 7, 7) - timedelta(days=days_ago)).isoformat(),
        "distance_km": distance_km,
        "duration_minutes": round(duration_minutes, 1),
        "avg_pace_min_km": pace_min_km,
        "avg_speed_kmh": round(60.0 / pace_min_km, 2),
        "avg_heart_rate": avg_hr,
    }


def _beginner_profile() -> list[dict]:
    return [
        _run(3, 3.5, 6.8),
        _run(10, 4.2, 6.7),
        _run(17, 5.0, 6.6),
        _run(24, 6.0, 6.7),
        _run(36, 4.0, 6.9),
        _run(47, 5.0, 6.8),
    ]


def _intermediate_profile() -> list[dict]:
    return [
        _run(2, 8.0, 5.1, 154),
        _run(5, 10.0, 4.9, 162),
        _run(9, 14.0, 5.2, 151),
        _run(13, 6.0, 4.8, 165),
        _run(18, 12.0, 5.0, 156),
        _run(22, 16.0, 5.2, 149),
        _run(29, 8.0, 5.0, 155),
        _run(33, 5.0, 4.7, 168),
        _run(40, 12.0, 5.1, 152),
        _run(46, 18.0, 5.3, 150),
    ]


def _advanced_profile() -> list[dict]:
    return [
        _run(1, 10.0, 4.0, 168),
        _run(4, 18.0, 4.35, 154),
        _run(7, 12.0, 4.08, 166),
        _run(11, 21.1, 4.22, 160),
        _run(14, 8.0, 3.9, 171),
        _run(18, 16.0, 4.3, 155),
        _run(21, 14.0, 4.15, 162),
        _run(25, 20.0, 4.32, 153),
        _run(29, 10.0, 4.05, 167),
        _run(34, 24.0, 4.38, 151),
        _run(39, 12.0, 4.1, 164),
        _run(44, 16.0, 4.25, 157),
        _run(50, 8.0, 3.95, 170),
    ]


def _elite_profile() -> list[dict]:
    return [
        _run(1, 10.0, 3.15, 173),
        _run(3, 16.0, 3.28, 166),
        _run(5, 24.0, 3.42, 159),
        _run(8, 12.0, 3.18, 175),
        _run(10, 21.1, 3.31, 168),
        _run(13, 18.0, 3.36, 163),
        _run(16, 8.0, 3.1, 178),
        _run(19, 26.0, 3.45, 158),
        _run(22, 14.0, 3.22, 171),
        _run(26, 10.0, 3.14, 174),
        _run(30, 28.0, 3.47, 157),
        _run(34, 12.0, 3.19, 174),
        _run(38, 18.0, 3.34, 164),
        _run(42, 5.0, 2.95, 181),
        _run(46, 22.0, 3.4, 160),
    ]


def test_profiles_produce_ordered_run_index_scores():
    reference_date = date(2026, 7, 7)
    beginner = calculate_run_index(_beginner_profile(), reference_date)
    intermediate = calculate_run_index(_intermediate_profile(), reference_date)
    advanced = calculate_run_index(_advanced_profile(), reference_date)
    elite = calculate_run_index(_elite_profile(), reference_date)

    assert beginner["run_index"] < intermediate["run_index"] < advanced["run_index"] < elite["run_index"]
    assert beginner["confidence_score"] < elite["confidence_score"]


def test_score_ranges_are_always_valid_for_all_profiles():
    reference_date = date(2026, 7, 7)
    for profile in (
        _beginner_profile(),
        _intermediate_profile(),
        _advanced_profile(),
        _elite_profile(),
    ):
        result = calculate_run_index(profile, reference_date)
        assert 0 <= result["run_index"] <= 1000
        assert 0 <= result["confidence_score"] <= 100
        for pillar in ("speed_score", "endurance_score", "consistency_score", "efficiency_score"):
            assert 0 <= result[pillar] <= 100


def test_missing_heart_rate_data_reduces_confidence_without_breaking_ranges():
    reference_date = date(2026, 7, 7)
    hr_rich = calculate_run_index(_intermediate_profile(), reference_date)
    missing_hr = calculate_run_index(_beginner_profile(), reference_date)

    assert missing_hr["confidence_score"] < hr_rich["confidence_score"]
    assert 0 <= missing_hr["run_index"] <= 1000
    assert 0 <= missing_hr["efficiency_score"] <= 100


def test_empty_profile_returns_zero_scores_and_zero_confidence():
    result = calculate_run_index([], date(2026, 7, 7))

    assert result["run_index"] == 0
    assert result["confidence_score"] == 0
    assert result["speed_score"] == 0
    assert result["endurance_score"] == 0
    assert result["consistency_score"] == 0
    assert result["efficiency_score"] == 0
