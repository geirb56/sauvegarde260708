"""
Tests for the CardioCoach running screen endpoint.
GET /api/cardio-coach

Validates:
- Endpoint is reachable and returns 200.
- Response contains all required fields (recommendation, metrics, history, etc.).
- Recommendation value is one of the three valid options.
- All metric status values are valid colour tokens.
- History contains at most 7 entries.
- Falls back gracefully (returns mock data) when Terra is not connected.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

VALID_RECOMMENDATIONS = {"RUN HARD", "EASY RUN", "REST"}
VALID_COLORS = {"green", "yellow", "red"}
VALID_STATUSES = {"green", "yellow", "red"}

# Use a test-only user ID that will not have a Terra token stored.
TEST_USER = "test_cardio_coach_user_no_terra"


class TestCardioCoachEndpoint:
    """GET /api/cardio-coach"""

    def test_endpoint_returns_200(self):
        """Should always return HTTP 200."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200, response.text

    def test_response_contains_top_level_fields(self):
        """Response must include all required top-level keys."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        data = response.json()
        required_keys = {
            "mock",
            "recommendation",
            "recommendation_emoji",
            "recommendation_color",
            "next_workout",
            "metrics",
            "reasons",
            "history",
        }
        for key in required_keys:
            assert key in data, f"Missing key: {key}"
        print(f"✓ Top-level fields present: {list(data.keys())}")

    def test_recommendation_is_valid(self):
        """Recommendation must be one of RUN HARD, EASY RUN, REST."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        data = response.json()
        assert data["recommendation"] in VALID_RECOMMENDATIONS, (
            f"Unexpected recommendation: {data['recommendation']}"
        )
        print(f"✓ Recommendation: {data['recommendation']}")

    def test_recommendation_color_is_valid(self):
        """recommendation_color must be one of green / yellow / red."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        data = response.json()
        assert data["recommendation_color"] in VALID_COLORS, (
            f"Unexpected color: {data['recommendation_color']}"
        )

    def test_metrics_contains_required_fields(self):
        """metrics object must contain all expected computed fields."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        metrics = response.json()["metrics"]
        required_metric_keys = {
            "hrv_today",
            "hrv_baseline",
            "hrv_delta",
            "hrv_status",
            "rhr_today",
            "rhr_baseline",
            "rhr_delta",
            "rhr_status",
            "sleep_hours",
            "sleep_efficiency",
            "sleep_score",
            "sleep_status",
            "training_load",
            "training_load_status",
            "fatigue_physio",
            "fatigue_ratio",
            "fatigue_status",
        }
        for key in required_metric_keys:
            assert key in metrics, f"Missing metric key: {key}"
        print(f"✓ All metric fields present")

    def test_metric_status_values_are_valid(self):
        """All *_status fields in metrics must be green, yellow, or red."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        metrics = response.json()["metrics"]
        status_keys = ["hrv_status", "rhr_status", "sleep_status", "training_load_status", "fatigue_status"]
        for key in status_keys:
            assert metrics[key] in VALID_STATUSES, (
                f"Invalid status '{metrics[key]}' for {key}"
            )
        print(f"✓ All status colours are valid")

    def test_reasons_is_non_empty_list(self):
        """reasons must be a non-empty list of strings."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        reasons = response.json()["reasons"]
        assert isinstance(reasons, list), "reasons should be a list"
        assert len(reasons) > 0, "reasons should not be empty"
        for r in reasons:
            assert isinstance(r, str), f"reason entry should be a string: {r}"
        print(f"✓ reasons: {reasons[:2]}")

    def test_history_has_at_most_7_entries(self):
        """history must have at most 7 entries."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        history = response.json()["history"]
        assert isinstance(history, list), "history should be a list"
        assert len(history) <= 7, f"history should have at most 7 entries, got {len(history)}"
        print(f"✓ history entries: {len(history)}")

    def test_history_entries_have_required_fields(self):
        """Each history entry must have day, training_load, fatigue_ratio."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        history = response.json()["history"]
        for entry in history:
            assert "day" in entry, "history entry missing 'day'"
            assert "training_load" in entry, "history entry missing 'training_load'"
            assert "fatigue_ratio" in entry, "history entry missing 'fatigue_ratio'"
        print(f"✓ history entry fields valid")

    def test_next_workout_has_label(self):
        """next_workout must contain a non-empty label."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        nw = response.json()["next_workout"]
        assert isinstance(nw, dict), "next_workout should be a dict"
        assert "label" in nw and nw["label"], "next_workout.label should be non-empty"
        print(f"✓ next_workout: {nw}")

    def test_mock_flag_is_present(self):
        """mock field must be a boolean."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach?user_id={TEST_USER}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["mock"], bool), "mock should be a boolean"
        # For a user without Terra, mock should be True.
        assert data["mock"] is True, "Should return mock=True when no Terra token exists"
        print(f"✓ mock={data['mock']}")

    def test_default_user_id_works(self):
        """Endpoint should be callable without user_id (defaults to 'default')."""
        response = requests.get(f"{BASE_URL}/api/cardio-coach")
        assert response.status_code == 200, response.text
        print(f"✓ Default user_id works: {response.json()['recommendation']}")
