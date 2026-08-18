"""PR138 — characterization tests for legacy performance extraction."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.performance import (  # noqa: E402
    build_legacy_pace_zones,
    build_legacy_performance_compatibility,
    compute_vo2max_from_vma,
    estimate_legacy_vma_from_normalized_runs,
    vma_pace,
    vma_pace_range,
)


def _legacy_vma_and_paces(runs: list[dict]) -> tuple[float, float, str, str, dict]:
    paces = []
    vma_efforts = []
    for run in runs:
        dist = run.get("distance_km")
        duration_min = run.get("duration_minutes")
        if dist is None or duration_min is None or dist <= 0 or duration_min <= 0:
            continue
        pace = duration_min / dist
        if 3 < pace < 10:
            paces.append(pace)
            if duration_min >= 6 and pace < 5.5:
                vma_efforts.append({"speed_kmh": 60.0 / pace, "duration": duration_min})

    if paces:
        avg_pace = sum(paces) / len(paces)
        if vma_efforts:
            best_effort = max(vma_efforts, key=lambda item: item["speed_kmh"])
            if best_effort["duration"] >= 20:
                estimated_vma = best_effort["speed_kmh"] / 0.85
            elif best_effort["duration"] >= 12:
                estimated_vma = best_effort["speed_kmh"] / 0.90
            else:
                estimated_vma = best_effort["speed_kmh"] / 0.95
            vma_method = "effort"
        else:
            estimated_vma = (60.0 / avg_pace) / 0.70
            vma_method = "average"
    else:
        estimated_vma = 12.0
        vma_method = "default"

    estimated_vma = round(estimated_vma, 1)
    vo2max = round(estimated_vma * 3.5, 1)
    vma_confidence = {"effort": "high", "average": "low", "default": "low"}[vma_method]

    def _pace(vma_pct: float) -> str:
        speed = max(0.1, estimated_vma * vma_pct)
        pace = 60.0 / speed
        mins = int(pace)
        secs = int((pace % 1) * 60)
        return f"{mins}:{secs:02d}"

    personalized_paces = {
        "z1": f"{_pace(0.65)}-{_pace(0.70)}",
        "z2": f"{_pace(0.75)}-{_pace(0.80)}",
        "z3": f"{_pace(0.82)}-{_pace(0.87)}",
        "z4": f"{_pace(0.88)}-{_pace(0.93)}",
        "z5": f"{_pace(0.95)}-{_pace(1.00)}",
        "marathon": f"{_pace(0.78)}-{_pace(0.82)}",
        "semi": f"{_pace(0.82)}-{_pace(0.85)}",
    }
    return estimated_vma, vo2max, vma_method, vma_confidence, personalized_paces


@pytest.mark.parametrize(
    ("vma", "pct", "expected"),
    [
        (15.0, 0.65, "6:09"),
        (15.0, 0.95, "4:13"),
        (None, 0.65, "--:--"),
        (16.2, 0.0, "--:--"),
    ],
)
def test_vma_pace_characterization(vma, pct, expected):
    assert vma_pace(vma, pct) == expected


@pytest.mark.parametrize(
    ("vma", "low", "high"),
    [
        (15.0, 0.65, 0.70),
        (16.2, 0.82, 0.87),
        (None, 0.65, 0.70),
    ],
)
def test_vma_pace_range_characterization(vma, low, high):
    expected = f"{vma_pace(vma, low)}-{vma_pace(vma, high)}"
    assert vma_pace_range(vma, low, high) == expected


@pytest.mark.parametrize(
    "runs",
    [
        [
            {"distance_km": 10.0, "duration_minutes": 45.0},
            {"distance_km": 12.0, "duration_minutes": 60.0},
            {"distance_km": 8.0, "duration_minutes": 36.0},
        ],
        [
            {"distance_km": 8.0, "duration_minutes": 48.0},
            {"distance_km": 10.0, "duration_minutes": 60.0},
            {"distance_km": 5.0, "duration_minutes": 30.0},
        ],
        [
            {"distance_km": None, "duration_minutes": 40.0},
            {"distance_km": 10.0, "duration_minutes": None},
            {"distance_km": 0.0, "duration_minutes": 20.0},
        ],
        [],
    ],
)
def test_legacy_vma_vo2max_and_paces_equivalence(runs):
    expected = _legacy_vma_and_paces(runs)
    assert estimate_legacy_vma_from_normalized_runs(runs) == (
        expected[0],
        expected[2],
        expected[3],
    )
    assert build_legacy_performance_compatibility(runs) == expected


def test_build_legacy_pace_zones_matches_legacy_shape():
    estimated_vma, _, _, _, expected_paces = _legacy_vma_and_paces(
        [{"distance_km": 10.0, "duration_minutes": 45.0}]
    )
    assert build_legacy_pace_zones(estimated_vma) == expected_paces


@pytest.mark.parametrize(
    ("vma", "expected_vo2max"),
    [
        (15.9, 55.6),
        (12.0, 42.0),
        (None, None),
        (0.0, None),
    ],
)
def test_compute_vo2max_from_vma_characterization(vma, expected_vo2max):
    assert compute_vo2max_from_vma(vma) == expected_vo2max


def test_coach_service_uses_extracted_performance_module():
    source = (Path(__file__).resolve().parents[1] / "coach_service.py").read_text()
    assert "build_legacy_performance_compatibility" in source
