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


# ---------------------------------------------------------------------------
# R1.7A — intensity minutes tests
# ---------------------------------------------------------------------------

def test_intensity_minutes_a_positive_values():
    """A) moderate=30, vigorous=10 → preserved exactly."""
    da = coerce_domain_activity({"moderate_intensity_minutes": 30, "vigorous_intensity_minutes": 10})
    assert da.moderate_intensity_minutes == 30.0
    assert da.vigorous_intensity_minutes == 10.0


def test_intensity_minutes_b_zero_values():
    """B) moderate=0, vigorous=0 → preserved as 0, not None."""
    da = coerce_domain_activity({"moderate_intensity_minutes": 0, "vigorous_intensity_minutes": 0})
    assert da.moderate_intensity_minutes == 0.0
    assert da.vigorous_intensity_minutes == 0.0


def test_intensity_minutes_c_none_values():
    """C) moderate=None, vigorous=None → preserved as None."""
    da = coerce_domain_activity({"moderate_intensity_minutes": None, "vigorous_intensity_minutes": None})
    assert da.moderate_intensity_minutes is None
    assert da.vigorous_intensity_minutes is None


def test_intensity_minutes_d_negative_values():
    """D) Negative values → None."""
    da = coerce_domain_activity({"moderate_intensity_minutes": -1, "vigorous_intensity_minutes": -5.5})
    assert da.moderate_intensity_minutes is None
    assert da.vigorous_intensity_minutes is None


def test_intensity_minutes_e_bool_values():
    """E) Bool → None."""
    da = coerce_domain_activity({"moderate_intensity_minutes": True, "vigorous_intensity_minutes": False})
    assert da.moderate_intensity_minutes is None
    assert da.vigorous_intensity_minutes is None


def test_intensity_minutes_f_non_numeric_values():
    """F) Non-numeric → None."""
    da = coerce_domain_activity({"moderate_intensity_minutes": "30", "vigorous_intensity_minutes": [10]})
    assert da.moderate_intensity_minutes is None
    assert da.vigorous_intensity_minutes is None


def test_intensity_minutes_g_garmin_adapter_passes_values():
    """G) GarminActivity with intensity minutes → adapter → DomainActivity with same values."""
    raw = {
        "activityId": 999,
        "activityType": {"typeKey": "running"},
        "summaryDTO": {
            "startTimeGMT": "2026-08-04T08:00:00.0",
            "distance": 10000.0,
            "duration": 3600.0,
            "moderateIntensityMinutes": 30,
            "vigorousIntensityMinutes": 10,
        },
    }
    garmin_activity = GarminActivity.from_summary(raw)
    da = to_domain_activity(garmin_activity)
    assert da.moderate_intensity_minutes == 30.0
    assert da.vigorous_intensity_minutes == 10.0


def test_intensity_minutes_h_garmin_adapter_no_intensity():
    """H) GarminActivity without intensity minutes → DomainActivity None, no fallback."""
    raw = {
        "activityId": 998,
        "activityType": {"typeKey": "running"},
        "summaryDTO": {
            "startTimeGMT": "2026-08-04T08:00:00.0",
            "distance": 10000.0,
            "duration": 3600.0,
        },
    }
    garmin_activity = GarminActivity.from_summary(raw)
    da = to_domain_activity(garmin_activity)
    assert da.moderate_intensity_minutes is None
    assert da.vigorous_intensity_minutes is None


def test_intensity_minutes_i_training_load_unchanged():
    """I) TrainingHistory/TrainingLoad results identical with or without intensity fields."""
    base = DomainActivity(
        activity_type="running",
        start_time=(REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
        distance_m=10000.0,
        duration_s=3600.0,
    )
    with_intensity = DomainActivity(
        activity_type="running",
        start_time=(REF - timedelta(days=2)).isoformat() + "T08:00:00.0",
        distance_m=10000.0,
        duration_s=3600.0,
        moderate_intensity_minutes=30.0,
        vigorous_intensity_minutes=10.0,
    )

    assert build_training_history([base], REF) == build_training_history([with_intensity], REF)
    assert build_training_load([base], REF) == build_training_load([with_intensity], REF)


def test_domain_activity_no_provider_imports():
    """Provider-neutrality: training_v2/domain_activity.py has no garmin/terra/strava imports."""
    domain_activity_path = Path(__file__).resolve().parents[1] / "training_v2" / "domain_activity.py"
    content = domain_activity_path.read_text()
    for provider in ("garmin", "terra", "strava"):
        assert provider not in content, f"Unexpected '{provider}' reference in domain_activity.py"


def test_zero_and_none_are_distinct():
    """0 and None must remain distinguishable after coercion."""
    zero = coerce_domain_activity({"moderate_intensity_minutes": 0, "vigorous_intensity_minutes": 0})
    none_ = coerce_domain_activity({})
    assert zero.moderate_intensity_minutes == 0.0
    assert none_.moderate_intensity_minutes is None
    assert zero.moderate_intensity_minutes != none_.moderate_intensity_minutes
