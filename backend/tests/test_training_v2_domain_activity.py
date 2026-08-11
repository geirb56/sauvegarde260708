from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garmin.data_layer import GarminActivity
from training_v2 import DomainActivity
from training_v2.training_history import build_training_history
from training_v2.training_load import build_training_load

REF = date(2026, 8, 6)

RAW_GARMIN_ACTIVITY = {
    "activityId": 123,
    "activityType": {"typeKey": "running"},
    "summaryDTO": {
        "startTimeGMT": "2026-08-04T08:00:00.0",
        "distance": 12345.6,
        "duration": 4321.0,
    },
}


def test_garmin_to_domain_activity():
    garmin_activity = GarminActivity.from_summary(RAW_GARMIN_ACTIVITY)

    domain_activity = garmin_activity.to_domain_activity()

    assert domain_activity == DomainActivity(
        activity_type="running",
        start_time="2026-08-04T08:00:00.0",
        distance_m=12345.6,
        duration_s=4321.0,
    )


def test_training_history_accepts_domain_activity():
    activity = DomainActivity(
        activity_type="running",
        start_time=(REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
        distance_m=10000.0,
        duration_s=3600.0,
    )

    history = build_training_history([activity], REF)

    assert history.window_7d.distance_km == 10.0
    assert history.window_7d.duration_hours == 1.0
    assert history.window_7d.activity_count == 1


def test_training_load_results_preserved_for_domain_activity():
    legacy_input = {
        "activity_type": "running",
        "start_time": (REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
        "distance": 10000.0,
        "duration": 3600.0,
    }
    domain_activity = DomainActivity(
        activity_type="running",
        start_time=legacy_input["start_time"],
        distance_m=10000.0,
        duration_s=3600.0,
    )

    assert build_training_load([domain_activity], REF) == build_training_load([legacy_input], REF)


def test_training_v2_activity_path_has_no_garmin_references():
    training_v2_dir = Path(__file__).resolve().parents[1] / "training_v2"
    files = [
        training_v2_dir / "domain_activity.py",
        training_v2_dir / "training_history.py",
        training_v2_dir / "training_load.py",
    ]

    for file_path in files:
        content = file_path.read_text()
        assert "GarminActivity" not in content
        assert "garmin_activity" not in content
