"""
Test RAG Endpoints for CardioCoach
Tests the RAG-enriched dashboard, weekly review, and workout analysis endpoints.
Bug fix verification: endpoints should return km_total > 0, nb_seances > 0, allure_moy not N/A
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestRAGDashboard:
    """Test /api/rag/dashboard endpoint - should return non-zero metrics"""
    
    def test_rag_dashboard_returns_200(self):
        """RAG dashboard endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ RAG dashboard returns 200")
    
    def test_rag_dashboard_km_total_greater_than_zero(self):
        """RAG dashboard should return km_total > 0 (bug fix verification)"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        data = response.json()
        
        assert "metrics" in data, "Response should contain 'metrics'"
        metrics = data["metrics"]
        
        km_total = metrics.get("km_total", 0)
        assert km_total > 0, f"km_total should be > 0, got {km_total}"
        print(f"✓ RAG dashboard km_total = {km_total} km (> 0)")
    
    def test_rag_dashboard_nb_seances_greater_than_zero(self):
        """RAG dashboard should return nb_seances > 0 (bug fix verification)"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        data = response.json()
        
        metrics = data["metrics"]
        nb_seances = metrics.get("nb_seances", 0)
        assert nb_seances > 0, f"nb_seances should be > 0, got {nb_seances}"
        print(f"✓ RAG dashboard nb_seances = {nb_seances} (> 0)")
    
    def test_rag_dashboard_allure_moy_not_na(self):
        """RAG dashboard should return allure_moy not N/A (bug fix verification)"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        data = response.json()
        
        metrics = data["metrics"]
        allure_moy = metrics.get("allure_moy", "N/A")
        assert allure_moy != "N/A", f"allure_moy should not be N/A, got {allure_moy}"
        print(f"✓ RAG dashboard allure_moy = {allure_moy} (not N/A)")
    
    def test_rag_dashboard_duree_totale_not_zero(self):
        """RAG dashboard should return duree_totale not 0h00 (bug fix verification)"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        data = response.json()
        
        metrics = data["metrics"]
        duree_totale = metrics.get("duree_totale", "0h00")
        assert duree_totale != "0h00", f"duree_totale should not be 0h00, got {duree_totale}"
        print(f"✓ RAG dashboard duree_totale = {duree_totale} (not 0h00)")
    
    def test_rag_dashboard_has_rag_summary(self):
        """RAG dashboard should return rag_summary text"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        data = response.json()
        
        assert "rag_summary" in data, "Response should contain 'rag_summary'"
        assert len(data["rag_summary"]) > 0, "rag_summary should not be empty"
        print(f"✓ RAG dashboard has rag_summary ({len(data['rag_summary'])} chars)")
    
    def test_rag_dashboard_has_points_forts(self):
        """RAG dashboard should return points_forts list"""
        response = requests.get(f"{BASE_URL}/api/rag/dashboard")
        data = response.json()
        
        assert "points_forts" in data, "Response should contain 'points_forts'"
        assert isinstance(data["points_forts"], list), "points_forts should be a list"
        print(f"✓ RAG dashboard has {len(data['points_forts'])} points_forts")


class TestRAGWeeklyReview:
    """Test /api/rag/weekly-review endpoint - should return non-zero metrics"""
    
    def test_rag_weekly_review_returns_200(self):
        """RAG weekly review endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/rag/weekly-review")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ RAG weekly review returns 200")
    
    def test_rag_weekly_review_km_total_greater_than_zero(self):
        """RAG weekly review should return km_total > 0"""
        response = requests.get(f"{BASE_URL}/api/rag/weekly-review")
        data = response.json()
        
        assert "metrics" in data, "Response should contain 'metrics'"
        metrics = data["metrics"]
        
        km_total = metrics.get("km_total", 0)
        assert km_total > 0, f"km_total should be > 0, got {km_total}"
        print(f"✓ RAG weekly review km_total = {km_total} km (> 0)")
    
    def test_rag_weekly_review_has_comparison(self):
        """RAG weekly review should return comparison with previous week"""
        response = requests.get(f"{BASE_URL}/api/rag/weekly-review")
        data = response.json()
        
        assert "comparison" in data, "Response should contain 'comparison'"
        comparison = data["comparison"]
        
        assert "vs_prev_week" in comparison, "comparison should have vs_prev_week"
        assert "km_current" in comparison, "comparison should have km_current"
        print(f"✓ RAG weekly review comparison: {comparison['vs_prev_week']}")
    
    def test_rag_weekly_review_has_rag_summary(self):
        """RAG weekly review should return rag_summary text"""
        response = requests.get(f"{BASE_URL}/api/rag/weekly-review")
        data = response.json()
        
        assert "rag_summary" in data, "Response should contain 'rag_summary'"
        assert len(data["rag_summary"]) > 0, "rag_summary should not be empty"
        print(f"✓ RAG weekly review has rag_summary ({len(data['rag_summary'])} chars)")


class TestRAGWorkoutAnalysis:
    """Test /api/rag/workout/{id} endpoint - should return workout with km > 0"""
    
    def test_rag_workout_analysis_returns_200(self):
        """RAG workout analysis endpoint should return 200 for valid workout"""
        # Use a known valid workout ID
        workout_id = "strava_17453996690"
        response = requests.get(f"{BASE_URL}/api/rag/workout/{workout_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ RAG workout analysis returns 200 for {workout_id}")
    
    def test_rag_workout_analysis_km_greater_than_zero(self):
        """RAG workout analysis should return workout with km > 0"""
        workout_id = "strava_17453996690"
        response = requests.get(f"{BASE_URL}/api/rag/workout/{workout_id}")
        data = response.json()
        
        assert "workout" in data, "Response should contain 'workout'"
        workout = data["workout"]
        
        km = workout.get("km", 0)
        assert km > 0, f"workout km should be > 0, got {km}"
        print(f"✓ RAG workout analysis km = {km} km (> 0)")
    
    def test_rag_workout_analysis_duree_not_zero(self):
        """RAG workout analysis should return workout with duree not 0"""
        workout_id = "strava_17453996690"
        response = requests.get(f"{BASE_URL}/api/rag/workout/{workout_id}")
        data = response.json()
        
        workout = data["workout"]
        duree = workout.get("duree", "0 min")
        assert duree != "0 min" and duree != "0h00", f"workout duree should not be 0, got {duree}"
        print(f"✓ RAG workout analysis duree = {duree} (not 0)")
    
    def test_rag_workout_analysis_has_comparison(self):
        """RAG workout analysis should return comparison with similar workouts"""
        workout_id = "strava_17453996690"
        response = requests.get(f"{BASE_URL}/api/rag/workout/{workout_id}")
        data = response.json()
        
        assert "comparison" in data, "Response should contain 'comparison'"
        comparison = data["comparison"]
        
        assert "similar_found" in comparison, "comparison should have similar_found"
        print(f"✓ RAG workout analysis found {comparison['similar_found']} similar workouts")
    
    def test_rag_workout_analysis_404_for_invalid_id(self):
        """RAG workout analysis should return 404 for invalid workout ID"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/invalid_workout_id_12345")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ RAG workout analysis returns 404 for invalid ID")


class TestWorkoutsEndpoint:
    """Test /api/workouts endpoint - should return 125 workouts"""
    
    def test_workouts_returns_200(self):
        """Workouts endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/workouts")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Workouts endpoint returns 200")
    
    def test_workouts_returns_expected_count(self):
        """Workouts endpoint should return ~125 workouts"""
        response = requests.get(f"{BASE_URL}/api/workouts")
        data = response.json()
        
        assert isinstance(data, list), "Response should be a list"
        count = len(data)
        assert count >= 100, f"Expected at least 100 workouts, got {count}"
        print(f"✓ Workouts endpoint returns {count} workouts (expected ~125)")
    
    def test_workouts_have_required_fields(self):
        """Workouts should have required fields"""
        response = requests.get(f"{BASE_URL}/api/workouts")
        data = response.json()
        
        if data:
            workout = data[0]
            required_fields = ["id", "type", "name", "date", "distance_km"]
            for field in required_fields:
                assert field in workout, f"Workout should have '{field}' field"
            print(f"✓ Workouts have required fields: {required_fields}")


class TestDashboardInsight:
    """Test /api/dashboard/insight endpoint - existing endpoint that should work"""
    
    def test_dashboard_insight_returns_200(self):
        """Dashboard insight endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Dashboard insight returns 200")
    
    def test_dashboard_insight_has_coach_insight(self):
        """Dashboard insight should return coach_insight"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        assert "coach_insight" in data, "Response should contain 'coach_insight'"
        assert len(data["coach_insight"]) > 0, "coach_insight should not be empty"
        print(f"✓ Dashboard insight has coach_insight: '{data['coach_insight'][:50]}...'")
    
    def test_dashboard_insight_has_week_data(self):
        """Dashboard insight should return week data"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        assert "week" in data, "Response should contain 'week'"
        week = data["week"]
        assert "sessions" in week, "week should have 'sessions'"
        assert "volume_km" in week, "week should have 'volume_km'"
        print(f"✓ Dashboard insight week: {week['sessions']} sessions, {week['volume_km']} km")
    
    def test_dashboard_insight_has_recovery_score(self):
        """Dashboard insight should return recovery_score"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        assert "recovery_score" in data, "Response should contain 'recovery_score'"
        recovery = data["recovery_score"]
        assert "score" in recovery, "recovery_score should have 'score'"
        assert "status" in recovery, "recovery_score should have 'status'"
        print(f"✓ Dashboard insight recovery: score={recovery['score']}, status={recovery['status']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
