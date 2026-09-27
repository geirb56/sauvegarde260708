"""
Test Dashboard Insight API - factual dashboard contract.
"""

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestDashboardInsightAPI:
    def test_dashboard_insight_returns_200(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_dashboard_insight_no_coach_insight_field(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        assert "coach_insight" not in data

    def test_dashboard_insight_has_week_stats(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        assert "week" in data
        week = data["week"]
        assert "sessions" in week
        assert "volume_km" in week
        assert "load_signal" in week
        assert isinstance(week["sessions"], int)
        assert isinstance(week["volume_km"], (int, float))
        assert week["load_signal"] is None

    def test_dashboard_insight_has_month_stats(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        assert "month" in data
        month = data["month"]
        assert "volume_km" in month
        assert "active_weeks" in month
        assert "trend" in month
        assert isinstance(month["volume_km"], (int, float))
        assert isinstance(month["active_weeks"], int)
        assert month["trend"] in ["up", "stable", "down"]

    def test_dashboard_insight_has_recovery_and_run_index(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        assert "recovery_score" in data
        assert "run_index" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
