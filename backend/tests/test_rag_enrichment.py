from __future__ import annotations

import os
import sys

os.environ.setdefault("ENVIRONMENT", "test")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from workout_analysis_v2 import build_workout_analysis_v2  # noqa: E402


def _workout(**overrides):
    workout = {
        "id": "run-1",
        "user_id": "user-a",
        "name": "Run 1",
        "date": "2024-01-10T07:00:00+00:00",
        "type": "run",
        "distance_km": 10.0,
        "duration_minutes": 60,
        "avg_pace_min_km": 6.0,
        "km_splits": [],
        "split_analysis": {},
        "hr_analysis": {},
        "cadence_analysis": {},
    }
    workout.update(overrides)
    return workout


def test_v2_replacement_preserves_split_evidence_without_fake_pace_drop():
    analysis = build_workout_analysis_v2(
        workout=_workout(
            km_splits=[
                {"km": 1, "pace_min_km": 5.7},
                {"km": 2, "pace_min_km": 6.4},
            ],
            split_analysis={"fastest_split_pace": 5.7, "slowest_split_pace": 6.4},
        ),
        historical_workouts=[],
    )
    assert analysis.evidence.has_splits is True
    assert analysis.pacing.fastest_split_min_km == 5.7
    assert analysis.pacing.slowest_split_min_km == 6.4
    assert analysis.pacing.pace_drop_min_km is None


def test_v2_replacement_preserves_hr_facts_without_intensity_classification():
    analysis = build_workout_analysis_v2(
        workout=_workout(avg_heart_rate=170, max_heart_rate=180),
        historical_workouts=[],
    )
    assert analysis.physiology.available is True
    assert analysis.physiology.avg_hr == 170
    assert analysis.physiology.max_hr == 180
    assert analysis.signals.intensity.available is False
    assert analysis.signals.intensity.code is None


def test_v2_replacement_treats_zone_distribution_as_non_authoritative_without_provenance():
    analysis = build_workout_analysis_v2(
        workout=_workout(
            avg_heart_rate=166,
            max_heart_rate=184,
            effort_zone_distribution={"z1": 5, "z2": 25, "z3": 20, "z4": 30, "z5": 20},
        ),
        historical_workouts=[],
    )
    assert analysis.evidence.has_hr_zones is True
    assert analysis.physiology.zone_distribution["z5"] == 20.0
    assert analysis.signals.intensity.available is False
    assert analysis.signals.session_type.code == "standard"


def test_v2_replacement_preserves_cadence_evidence():
    analysis = build_workout_analysis_v2(
        workout=_workout(avg_cadence_spm=176),
        historical_workouts=[],
    )
    assert analysis.evidence.has_cadence is True
