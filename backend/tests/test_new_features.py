"""
Test suite for CardioCoach new features:
1. Recovery Score on Dashboard (circular gauge 0-100)
2. User Goal (event with date) in Settings
3. Weekly Review with goal context and recommendations followup
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestRecoveryScore:
    """Test Recovery Score feature on Dashboard"""
    
    def test_dashboard_insight_returns_recovery_score(self):
        """GET /api/dashboard/insight should return recovery_score object"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "recovery_score" in data, "Response should contain recovery_score"
        
        recovery = data["recovery_score"]
        assert recovery is not None, "recovery_score should not be None"
        
    def test_recovery_score_has_required_fields(self):
        """Recovery score should have score, status, phrase, days_since_last_workout"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        recovery = response.json()["recovery_score"]
        
        # Check required fields
        assert "score" in recovery, "recovery_score should have 'score'"
        assert "status" in recovery, "recovery_score should have 'status'"
        assert "phrase" in recovery, "recovery_score should have 'phrase'"
        assert "days_since_last_workout" in recovery, "recovery_score should have 'days_since_last_workout'"
        
    def test_recovery_score_value_range(self):
        """Recovery score should be between 0 and 100"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        score = response.json()["recovery_score"]["score"]
        assert isinstance(score, (int, float)), "Score should be numeric"
        assert 0 <= score <= 100, f"Score should be 0-100, got {score}"
        
    def test_recovery_score_status_values(self):
        """Recovery status should be ready, moderate, or low"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        status = response.json()["recovery_score"]["status"]
        assert status in ["ready", "moderate", "low"], f"Invalid status: {status}"
        
    def test_recovery_score_phrase_not_empty(self):
        """Recovery phrase should be a non-empty string"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        phrase = response.json()["recovery_score"]["phrase"]
        assert isinstance(phrase, str), "Phrase should be a string"
        assert len(phrase) > 0, "Phrase should not be empty"
        
    def test_recovery_score_french_language(self):
        """Recovery score should return French phrase when language=fr"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=fr")
        assert response.status_code == 200
        
        recovery = response.json()["recovery_score"]
        assert recovery is not None
        assert "phrase" in recovery
        # French phrases should contain French words
        phrase = recovery["phrase"].lower()
        # Check for common French words
        french_indicators = ["corps", "seance", "recuperation", "fatigue", "repos", "pret"]
        has_french = any(word in phrase for word in french_indicators)
        assert has_french, f"Phrase should be in French: {phrase}"


class TestUserGoal:
    """Test User Goal CRUD operations"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up test goals before and after each test"""
        # Cleanup before
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=test_user")
        yield
        # Cleanup after
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=test_user")
    
    def test_create_goal_success(self):
        """POST /api/user/goal should create a goal successfully"""
        goal_data = {
            "event_name": "TEST_Marathon de Paris",
            "event_date": "2026-04-05"
        }
        response = requests.post(
            f"{BASE_URL}/api/user/goal?user_id=test_user",
            json=goal_data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, "Response should indicate success"
        assert "goal" in data, "Response should contain goal object"
        
    def test_create_goal_returns_correct_data(self):
        """Created goal should have correct event_name and event_date"""
        goal_data = {
            "event_name": "TEST_Paris Marathon",
            "event_date": "2026-04-05"
        }
        response = requests.post(
            f"{BASE_URL}/api/user/goal?user_id=test_user",
            json=goal_data
        )
        assert response.status_code == 200
        
        goal = response.json()["goal"]
        assert goal["event_name"] == "TEST_Paris Marathon"
        assert goal["event_date"] == "2026-04-05"
        assert "id" in goal, "Goal should have an ID"
        assert "user_id" in goal, "Goal should have user_id"
        
    def test_get_goal_returns_created_goal(self):
        """GET /api/user/goal should return the created goal"""
        # First create a goal
        goal_data = {
            "event_name": "TEST_Berlin Marathon",
            "event_date": "2026-09-27"
        }
        requests.post(f"{BASE_URL}/api/user/goal?user_id=test_user", json=goal_data)
        
        # Then get it
        response = requests.get(f"{BASE_URL}/api/user/goal?user_id=test_user")
        assert response.status_code == 200
        
        goal = response.json()
        assert goal is not None, "Should return the goal"
        assert goal["event_name"] == "TEST_Berlin Marathon"
        assert goal["event_date"] == "2026-09-27"
        
    def test_get_goal_returns_null_when_no_goal(self):
        """GET /api/user/goal should return null when no goal exists"""
        # Ensure no goal exists
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=test_user_no_goal")
        
        response = requests.get(f"{BASE_URL}/api/user/goal?user_id=test_user_no_goal")
        assert response.status_code == 200
        
        data = response.json()
        assert data is None, "Should return null when no goal exists"
        
    def test_delete_goal_success(self):
        """DELETE /api/user/goal should delete the goal"""
        # First create a goal
        goal_data = {
            "event_name": "TEST_London Marathon",
            "event_date": "2026-04-26"
        }
        requests.post(f"{BASE_URL}/api/user/goal?user_id=test_user", json=goal_data)
        
        # Delete it
        response = requests.delete(f"{BASE_URL}/api/user/goal?user_id=test_user")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("deleted") == True, "Should indicate deletion success"
        
    def test_delete_goal_verify_removed(self):
        """After DELETE, GET should return null"""
        # Create and delete
        goal_data = {
            "event_name": "TEST_NYC Marathon",
            "event_date": "2026-11-01"
        }
        requests.post(f"{BASE_URL}/api/user/goal?user_id=test_user", json=goal_data)
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=test_user")
        
        # Verify removed
        response = requests.get(f"{BASE_URL}/api/user/goal?user_id=test_user")
        assert response.status_code == 200
        assert response.json() is None, "Goal should be removed"
        
    def test_update_goal_replaces_existing(self):
        """POST /api/user/goal should replace existing goal"""
        # Create first goal
        requests.post(
            f"{BASE_URL}/api/user/goal?user_id=test_user",
            json={"event_name": "TEST_First Event", "event_date": "2026-01-01"}
        )
        
        # Create second goal (should replace)
        response = requests.post(
            f"{BASE_URL}/api/user/goal?user_id=test_user",
            json={"event_name": "TEST_Second Event", "event_date": "2026-06-15"}
        )
        assert response.status_code == 200
        
        # Verify only second goal exists
        get_response = requests.get(f"{BASE_URL}/api/user/goal?user_id=test_user")
        goal = get_response.json()
        assert goal["event_name"] == "TEST_Second Event"
        assert goal["event_date"] == "2026-06-15"


class TestWeeklyReviewWithGoal:
    """Test Weekly Review with user goal context and recommendations followup"""
    
    def test_digest_returns_user_goal(self):
        """GET /api/coach/digest should return user_goal if set"""
        # First ensure a goal exists for default user
        goal_data = {
            "event_name": "Marathon de Paris",
            "event_date": "2026-04-05"
        }
        requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json=goal_data)
        
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "user_goal" in data, "Response should contain user_goal field"
        
    def test_digest_user_goal_has_correct_fields(self):
        """user_goal in digest should have event_name and event_date"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        user_goal = response.json().get("user_goal")
        if user_goal:  # Only test if goal exists
            assert "event_name" in user_goal, "user_goal should have event_name"
            assert "event_date" in user_goal, "user_goal should have event_date"
            
    def test_digest_returns_recommendations_followup(self):
        """GET /api/coach/digest should return recommendations_followup field"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        assert "recommendations_followup" in data, "Response should contain recommendations_followup field"
        
    def test_digest_recommendations_followup_is_string(self):
        """recommendations_followup should be a string (can be empty)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        followup = response.json().get("recommendations_followup")
        assert isinstance(followup, str), f"recommendations_followup should be string, got {type(followup)}"
        
    def test_digest_french_with_goal(self):
        """French digest should also include user_goal and recommendations_followup"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=fr")
        assert response.status_code == 200
        
        data = response.json()
        assert "user_goal" in data, "French response should contain user_goal"
        assert "recommendations_followup" in data, "French response should contain recommendations_followup"
        
    def test_digest_still_has_core_fields(self):
        """Digest should still have all core fields (coach_summary, signals, metrics, etc.)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        # Core fields from previous implementation
        assert "coach_summary" in data, "Should have coach_summary"
        assert "signals" in data, "Should have signals"
        assert "metrics" in data, "Should have metrics"
        assert "recommendations" in data, "Should have recommendations"
        assert "period_start" in data, "Should have period_start"
        assert "period_end" in data, "Should have period_end"


class TestDashboardInsightComplete:
    """Test complete dashboard insight response"""
    
    def test_dashboard_insight_has_all_fields(self):
        """Dashboard insight should have coach_insight, week, month, and recovery_score"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        data = response.json()
        assert "coach_insight" in data, "Should have coach_insight"
        assert "week" in data, "Should have week stats"
        assert "month" in data, "Should have month stats"
        assert "recovery_score" in data, "Should have recovery_score"
        
    def test_week_stats_structure(self):
        """Week stats should have sessions, volume_km, load_signal"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        week = response.json()["week"]
        assert "sessions" in week, "Week should have sessions"
        assert "volume_km" in week, "Week should have volume_km"
        assert "load_signal" in week, "Week should have load_signal"
        
    def test_month_stats_structure(self):
        """Month stats should have volume_km, active_weeks, trend"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=en")
        assert response.status_code == 200
        
        month = response.json()["month"]
        assert "volume_km" in month, "Month should have volume_km"
        assert "active_weeks" in month, "Month should have active_weeks"
        assert "trend" in month, "Month should have trend"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
