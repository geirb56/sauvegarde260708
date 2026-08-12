from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garmin.data_layer import GarminActivity, GarminCapabilities
from garmin.domain_adapter import to_domain_activity, to_domain_capabilities
from training_v2 import DomainActivity, DomainCapabilities
from training_v2.domain_activity import to_domain_activity as coerce_domain_activity
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

    domain_activity = to_domain_activity(garmin_activity)

    assert domain_activity == DomainActivity(
        activity_type="running",
        start_time="2026-08-04T08:00:00.0",
        distance_m=12345.6,
        duration_s=4321.0,
        source="garmin",
        source_activity_id="123",
    )


def test_garmin_to_domain_capabilities():
    garmin_capabilities = GarminCapabilities(
        has_hrv=True,
        has_vo2max=False,
        has_training_readiness=True,
        has_training_status=True,
        has_body_battery=True,
        has_stress=True,
        has_running_dynamics=False,
        has_power=True,
        has_race_predictions=True,
    )

    domain_capabilities = to_domain_capabilities(garmin_capabilities)

    assert domain_capabilities == DomainCapabilities(
        has_hrv=True,
        has_vo2max=False,
        has_training_readiness=True,
        has_power=True,
        has_running_dynamics=False,
    )


def test_garmin_data_layer_has_no_training_v2_dependency():
    data_layer_path = Path(__file__).resolve().parents[1] / "garmin" / "data_layer.py"
    content = data_layer_path.read_text()

    assert "training_v2" not in content


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


def test_domain_activity_provenance_defaults_to_none_when_absent():
    domain_activity = coerce_domain_activity(
        {
            "activity_type": "running",
            "start_time": (REF - timedelta(days=1)).isoformat() + "T08:00:00.0",
            "distance_m": 5000.0,
            "duration_s": 1800.0,
        }
    )

    assert domain_activity.source is None
    assert domain_activity.source_activity_id is None


def test_training_history_and_load_ignore_provenance_fields():
    base_activity = DomainActivity(
        activity_type="running",
        start_time=(REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
        distance_m=10000.0,
        duration_s=3600.0,
    )
    same_activity_with_provenance = DomainActivity(
        activity_type=base_activity.activity_type,
        start_time=base_activity.start_time,
        distance_m=base_activity.distance_m,
        duration_s=base_activity.duration_s,
        source="garmin",
        source_activity_id="abc123",
    )

    assert build_training_history([same_activity_with_provenance], REF) == build_training_history([base_activity], REF)
    assert build_training_load([same_activity_with_provenance], REF) == build_training_load([base_activity], REF)


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
