"""PR#215 — RunIndex speed cleanup structural + behavior guards."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

sys_path_root = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(sys_path_root))

from engine.run_index_engine import calculate_run_index, calculate_speed_score


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _runtime_backend_py_sources() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(BACKEND_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(root, fname)
            if "/tests/" in full or os.path.basename(full).startswith("test_"):
                continue
            result.append((full, _read(full)))
    return result


def _runtime_non_comment_lines() -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for path, src in _runtime_backend_py_sources():
        for idx, raw_line in enumerate(src.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append((path, idx, raw_line))
    return rows


def _count_runtime_line_matches(patterns: list[str]) -> int:
    total = 0
    compiled = [re.compile(p) for p in patterns]
    for _, _, line in _runtime_non_comment_lines():
        for pat in compiled:
            if pat.search(line):
                total += 1
    return total


def _run(days_ago: int, distance_km: float, pace_min_km: float, avg_hr: int | None = None, **extras) -> dict:
    duration_minutes = distance_km * pace_min_km
    payload = {
        "type": "run",
        "date": (date(2026, 7, 7) - timedelta(days=days_ago)).isoformat(),
        "distance_km": distance_km,
        "duration_minutes": round(duration_minutes, 1),
        "avg_pace_min_km": pace_min_km,
        "avg_speed_kmh": round(60.0 / pace_min_km, 2),
        "avg_heart_rate": avg_hr,
    }
    payload.update(extras)
    return payload


def test_synthetic_vma_proxy_runtime_consumers_zero():
    """SYNTHETIC_VMA_PROXY_RUNTIME_CONSUMERS = 0"""
    SYNTHETIC_VMA_PROXY_RUNTIME_CONSUMERS = _count_runtime_line_matches(
        [r"\bestimated_vma_proxy\b", r"\bvma_proxy\b"]
    )
    assert SYNTHETIC_VMA_PROXY_RUNTIME_CONSUMERS == 0


def test_synthetic_vo2_from_speed_runtime_consumers_zero():
    """SYNTHETIC_VO2_FROM_SPEED_RUNTIME_CONSUMERS = 0"""
    SYNTHETIC_VO2_FROM_SPEED_RUNTIME_CONSUMERS = _count_runtime_line_matches(
        [r"speed[^\n]{0,120}\*\s*3\.5", r"\*\s*3\.5[^\n]{0,120}speed"]
    )
    assert SYNTHETIC_VO2_FROM_SPEED_RUNTIME_CONSUMERS == 0


def test_speed_percent_vma_conversions_zero():
    """SPEED_PERCENT_VMA_CONVERSIONS = 0"""
    SPEED_PERCENT_VMA_CONVERSIONS = _count_runtime_line_matches(
        [
            r"speed\s*/\s*0\.85",
            r"speed\s*/\s*0\.90",
            r"speed\s*/\s*0\.95",
            r"avg_speed_kmh\s*/\s*0\.85",
            r"avg_speed_kmh\s*/\s*0\.90",
            r"avg_speed_kmh\s*/\s*0\.95",
        ]
    )
    assert SPEED_PERCENT_VMA_CONVERSIONS == 0


def test_speed_score_computable_from_observed_race_performance():
    runs = [
        _run(5, 5.0, 4.35, 162),
        _run(18, 9.0, 4.9, 154),
        _run(33, 7.0, 5.1, 150),
    ]
    speed = calculate_speed_score(runs, date(2026, 7, 7))
    assert speed["score"] is not None
    assert speed["components"]["race_performance_score"] is not None


def test_speed_score_computable_from_sustained_speed_only():
    runs = [
        _run(4, 6.5, 5.0, 152),
        _run(11, 7.5, 5.1, 149),
        _run(20, 7.0, 4.9, 156),
    ]
    speed = calculate_speed_score(runs, date(2026, 7, 7))
    assert speed["score"] is not None
    assert speed["components"]["race_performance_score"] is None
    assert speed["components"]["sustained_speed_score"] is not None


def test_speed_score_is_null_when_observed_inputs_insufficient():
    runs = [
        _run(2, 2.0, 5.0, 150),
        _run(8, 2.5, 5.2, 148),
    ]
    speed = calculate_speed_score(runs, date(2026, 7, 7))
    assert speed["score"] is None
    assert speed["components"]["race_performance_score"] is None
    assert speed["components"]["sustained_speed_score"] is None


@pytest.mark.parametrize(
    "extra_key, left, right",
    [
        ("garmin_vo2max", 39.0, 57.0),
        ("race_predictions", {"5k": 1320}, {"5k": 1180}),
        ("training_paces_v2", {"z5": "3:35/km"}, {"z5": "4:00/km"}),
    ],
)
def test_run_index_not_coupled_to_forbidden_external_signals(extra_key: str, left, right):
    base_runs = [
        _run(3, 5.0, 4.3, 166),
        _run(10, 10.0, 4.8, 158),
        _run(17, 14.0, 5.1, 152),
        _run(24, 8.0, 4.9, 160),
    ]
    runs_left = [dict(run, **{extra_key: left}) for run in base_runs]
    runs_right = [dict(run, **{extra_key: right}) for run in base_runs]
    left_result = calculate_run_index(runs_left, date(2026, 7, 7))
    right_result = calculate_run_index(runs_right, date(2026, 7, 7))
    assert left_result == right_result


def test_runindex_global_pillar_weights_unchanged():
    src = _read(os.path.join(BACKEND_DIR, "engine", "run_index_engine.py"))
    assert '(speed["score"], 0.40)' in src
    assert '(endurance["score"], 0.25)' in src
    assert '(consistency["score"], 0.20)' in src
    assert '(efficiency["score"], 0.15)' in src
    assert '(speed["confidence"] if speed["score"] is not None else None, 0.40)' in src
    assert '(endurance["confidence"] if endurance["score"] is not None else None, 0.25)' in src
    assert '(consistency["confidence"] if consistency["score"] is not None else None, 0.20)' in src
    assert '(efficiency["confidence"] if efficiency["score"] is not None else None, 0.15)' in src
