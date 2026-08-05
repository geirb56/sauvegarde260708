from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garmin.models import GarminActivity, GarminCapabilities, GarminDailyMetrics
from garmin.providers.gccli_provider import GccliProvider
from garmin.runner import GccliRunner


def test_garmin_activity_model_accepts_none():
    model = GarminActivity()
    assert model.to_dict()["activity_id"] is None


def test_garmin_daily_metrics_model_accepts_none():
    model = GarminDailyMetrics()
    assert model.to_dict()["hrv"] is None
    assert model.to_dict()["stress"] is None


def test_garmin_capabilities_model_defaults():
    model = GarminCapabilities()
    assert model.to_dict()["has_hrv"] is None


def test_gccli_provider_normalizes_activity_summary_and_details():
    raw = {
        "activityId": 42,
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-01-02T08:00:00",
        "distance": 10000.0,
        "duration": 3600.0,
        "movingDuration": 3500.0,
        "averageSpeed": 2.78,
        "averageMovingSpeed": 2.86,
        "maxSpeed": 4.2,
        "averageHR": 150,
        "maxHR": 176,
        "minHR": 90,
        "averageRunCadence": 172.5,
        "maxRunCadence": 188.0,
        "strideLength": 1.12,
        "steps": 9821,
        "elevationGain": 80.0,
        "elevationLoss": 75.0,
        "calories": 700,
        "moderateIntensityMinutes": 20,
        "vigorousIntensityMinutes": 35,
        "lapCount": 10,
        "detailsAvailable": True,
        "splitSummaries": [{"lap": 1}],
        "hrTimeInZone_1": 10,
    }
    normalized = GccliProvider._normalize(raw)
    data = normalized["garmin_activity"]
    assert data["activity_id"] == "42"
    assert data["moving_duration_s"] == 3500.0
    assert data["max_hr"] == 176
    assert data["has_hr_zones"] is True
    assert data["has_splits"] is True
    assert data["details_available"] is True


def test_gccli_provider_normalizes_empty_activity_payload():
    normalized = GccliProvider._normalize({})
    data = normalized["garmin_activity"]
    assert data["activity_id"] is None
    assert data["activity_type"] == "running"
    assert data["details_available"] is None


def test_runner_daily_metrics_handles_empty_payloads():
    runner = GccliRunner.__new__(GccliRunner)
    runner._run_json = MagicMock(return_value={})
    runner._ensure_available = MagicMock()
    metrics = runner.fetch_daily_metrics(days=1, account="test@example.com")
    assert metrics == []


def test_runner_capabilities_handles_empty_payloads():
    runner = GccliRunner.__new__(GccliRunner)
    runner._run_json = MagicMock(return_value={})
    runner._ensure_available = MagicMock()
    capabilities = runner.fetch_capabilities(account="test@example.com")
    assert capabilities["has_hrv"] is False
    assert capabilities["has_body_battery"] is False
