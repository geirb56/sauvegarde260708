from __future__ import annotations

import inspect

import pytest

from garmin.data_layer import GarminDailyMetrics
from garmin.runner import GccliError, GccliRunner


SLEEP_REAL = {
    "dailySleepDTO": {
        "calendarDate": "2026-08-03",
        "sleepTimeSeconds": 24660,
        "averageRespirationValue": 12.0,
    }
}

HR_REAL = {
    "calendarDate": "2026-08-03",
    "restingHeartRate": 48,
}

HRV_REAL = {
    "hrvSummary": {
        "lastNightAvg": 61,
        "weeklyAvg": 58,
    }
}


def test_pr03_sleep_real_payload_normalization():
    m = GarminDailyMetrics.from_gccli(sleep=SLEEP_REAL)
    assert m.date == "2026-08-03"
    assert m.sleep_hours == pytest.approx(6.85, abs=0.1)
    assert m.respiration == 12.0


def test_pr03_sleep_zero_seconds_is_none():
    m = GarminDailyMetrics.from_gccli(sleep={"dailySleepDTO": {"sleepTimeSeconds": 0}})
    assert m.sleep_hours is None


def test_pr03_hrv_absent_is_none():
    m = GarminDailyMetrics.from_gccli(hrv={})
    assert m.hrv is None


def test_pr03_hrv_real_value():
    m = GarminDailyMetrics.from_gccli(hrv=HRV_REAL)
    assert m.hrv == 61


def test_pr03_resting_hr_real_payload():
    m = GarminDailyMetrics.from_gccli(hr=HR_REAL)
    assert m.resting_hr == 48


@pytest.mark.parametrize("payload", [{}, [], None])
def test_pr03_partial_payloads_never_raise(payload):
    m = GarminDailyMetrics.from_gccli(
        date=None,
        hr=payload,
        sleep=payload,
        stress=payload,
        body_battery=payload,
        hrv=payload,
    )
    assert m.model_dump() == {
        "date": None,
        "resting_hr": None,
        "sleep_hours": None,
        "sleep_score": None,
        "stress": None,
        "body_battery": None,
        "respiration": None,
        "hrv": None,
        "source": "garmin",
    }


def test_pr03_contract_historical_keys_and_additive_subdocument():
    m = GarminDailyMetrics.from_gccli(date="2026-08-03", hr=HR_REAL, sleep=SLEEP_REAL, hrv={})
    normalized = m.model_dump()

    doc = {
        "date": normalized["date"],
        "resting_hr": normalized["resting_hr"],
        "sleep_hours": normalized["sleep_hours"],
        "sleep_score": normalized["sleep_score"],
        "hrv": normalized["hrv"],
        "stress": normalized["stress"],
        "body_battery": normalized["body_battery"],
        "respiration": normalized["respiration"],
        "source": normalized["source"],
        "garmin_daily_metrics": normalized,
    }

    for key in ("date", "resting_hr", "sleep_hours", "sleep_score", "hrv"):
        assert key in doc

    assert "garmin_daily_metrics" in doc
    assert doc["garmin_daily_metrics"] == normalized


def test_pr03_absence_never_falls_back_to_defaults():
    m = GarminDailyMetrics.from_gccli()
    assert m.resting_hr is None
    assert m.sleep_hours is None
    assert m.sleep_score is None
    assert m.hrv is None
    assert m.stress is None
    assert m.body_battery is None
    assert m.respiration is None


def test_pr03_runner_uses_only_existing_gccli_health_commands():
    source = inspect.getsource(GccliRunner.fetch_daily_metrics)
    banned = (
        "health stress",
        "health body-battery",
        "health respiration",
        "health training-readiness",
        "health training-status",
        "health max-metrics",
        "health race-predictions",
    )
    for cmd in banned:
        assert cmd not in source


def test_pr03_runner_adds_garmin_daily_metrics_subdocument():
    runner = GccliRunner.__new__(GccliRunner)
    runner.gccli_path = "gccli"
    runner.home = "/tmp"
    runner.keyring_backend = "file"
    runner.timeout = 45
    runner.max_retries = 3

    payload_map = {
        "health hr": HR_REAL,
        "health sleep": SLEEP_REAL,
        "health hrv": {},
    }

    def fake_run_json(args, account=None):
        return payload_map.get(" ".join(args[:2]), {})

    runner._run_json = fake_run_json
    runner._ensure_available = lambda: None
    runner.is_authenticated = lambda _account=None: True

    metrics = runner.fetch_daily_metrics(days=1)
    assert len(metrics) == 1
    doc = metrics[0]
    assert doc["date"] == "2026-08-03"
    assert doc["resting_hr"] == 48
    assert "garmin_daily_metrics" in doc
    assert doc["garmin_daily_metrics"]["date"] == "2026-08-03"


def test_pr03_fetch_result_technical_failure_not_mapped_to_no_data():
    runner = GccliRunner.__new__(GccliRunner)
    runner.gccli_path = "gccli"
    runner.home = "/tmp"
    runner.keyring_backend = "file"
    runner.timeout = 45
    runner.max_retries = 3
    runner.is_authenticated = lambda _account=None: True

    def failing_run_json(args, account=None):
        raise GccliError(f"gccli {' '.join(args)} timeout")

    runner._run_json = failing_run_json
    runner._ensure_available = lambda: None

    result = runner.fetch_daily_metrics_result(days=1)
    assert result.metrics == []
    assert result.status == "technical_failure"
    assert result.endpoint_failure_count == 3


def test_pr03_fetch_result_success_no_data_without_exception():
    runner = GccliRunner.__new__(GccliRunner)
    runner.gccli_path = "gccli"
    runner.home = "/tmp"
    runner.keyring_backend = "file"
    runner.timeout = 45
    runner.max_retries = 3
    runner.is_authenticated = lambda _account=None: True
    runner._run_json = lambda _args, account=None: {}
    runner._ensure_available = lambda: None

    result = runner.fetch_daily_metrics_result(days=1)
    assert result.metrics == []
    assert result.status == "success_no_data"


def test_pr03_fetch_result_health_hr_error_is_technical_state():
    runner = GccliRunner.__new__(GccliRunner)
    runner.gccli_path = "gccli"
    runner.home = "/tmp"
    runner.keyring_backend = "file"
    runner.timeout = 45
    runner.max_retries = 3
    runner.is_authenticated = lambda _account=None: True

    def run_json(args, account=None):
        key = " ".join(args[:2])
        if key == "health hr":
            raise GccliError("health hr timeout")
        if key == "health sleep":
            return SLEEP_REAL
        if key == "health hrv":
            return HRV_REAL
        return {}

    runner._run_json = run_json
    runner._ensure_available = lambda: None
    result = runner.fetch_daily_metrics_result(days=1)
    assert result.status == "partial_success"
    assert any(item["endpoint"] == "health hr" for item in result.endpoint_failures)


def test_pr03_fetch_result_health_sleep_error_is_technical_state():
    runner = GccliRunner.__new__(GccliRunner)
    runner.gccli_path = "gccli"
    runner.home = "/tmp"
    runner.keyring_backend = "file"
    runner.timeout = 45
    runner.max_retries = 3
    runner.is_authenticated = lambda _account=None: True

    def run_json(args, account=None):
        key = " ".join(args[:2])
        if key == "health hr":
            return HR_REAL
        if key == "health sleep":
            raise GccliError("health sleep timeout")
        if key == "health hrv":
            return HRV_REAL
        return {}

    runner._run_json = run_json
    runner._ensure_available = lambda: None
    result = runner.fetch_daily_metrics_result(days=1)
    assert result.status == "partial_success"
    assert any(item["endpoint"] == "health sleep" for item in result.endpoint_failures)


def test_pr03_fetch_result_two_endpoint_errors_one_empty_is_technical_failure():
    runner = GccliRunner.__new__(GccliRunner)
    runner.gccli_path = "gccli"
    runner.home = "/tmp"
    runner.keyring_backend = "file"
    runner.timeout = 45
    runner.max_retries = 3
    runner.is_authenticated = lambda _account=None: True

    def run_json(args, account=None):
        key = " ".join(args[:2])
        if key in {"health hr", "health sleep"}:
            raise GccliError(f"{key} timeout")
        if key == "health hrv":
            return {}
        return {}

    runner._run_json = run_json
    runner._ensure_available = lambda: None
    result = runner.fetch_daily_metrics_result(days=1)
    assert result.metrics == []
    assert result.status == "technical_failure"
