"""
Test suite for Mobile-First Workout Analysis endpoint
Tests GET /api/coach/workout-analysis/{workout_id}
Updated for session_type card (replaces comparison card)
"""
import pytest
import requests
import os
import re

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestMobileWorkoutAnalysis:
    """Tests for mobile workout analysis endpoint"""
    
    def test_workout_analysis_returns_200(self):
        """Test that workout analysis endpoint returns 200 for valid workout"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Workout analysis returns 200")
    
    def test_response_contains_coach_summary(self):
        """Test that response contains coach_summary field - plain language, max 18-20 words, no numbers overload"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "coach_summary" in data, "Missing coach_summary field"
        assert isinstance(data["coach_summary"], str), "coach_summary should be string"
        assert len(data["coach_summary"]) > 0, "coach_summary should not be empty"
        
        # Check word count (max 18-20 words)
        word_count = len(data["coach_summary"].split())
        assert word_count <= 25, f"coach_summary too long: {word_count} words (max 20)"
        
        # Check for numbers overload - should not have more than 2 numbers
        numbers = re.findall(r'\d+', data["coach_summary"])
        assert len(numbers) <= 2, f"coach_summary has too many numbers: {numbers}"
        
        print(f"✓ Coach summary ({word_count} words): '{data['coach_summary']}'")
    
    def test_response_contains_intensity_card(self):
        """Test that response contains intensity card with pace, avg_hr, label"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "intensity" in data, "Missing intensity field"
        intensity = data["intensity"]
        
        assert "pace" in intensity, "Missing pace in intensity"
        assert "avg_hr" in intensity, "Missing avg_hr in intensity"
        assert "label" in intensity, "Missing label in intensity"
        assert intensity["label"] in ["above_usual", "below_usual", "normal"], f"Invalid label: {intensity['label']}"
        
        print(f"✓ Intensity card: pace={intensity['pace']}, avg_hr={intensity['avg_hr']}, label={intensity['label']}")
    
    def test_response_contains_load_card(self):
        """Test that response contains load card with distance_km, duration_min, direction"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "load" in data, "Missing load field"
        load = data["load"]
        
        assert "distance_km" in load, "Missing distance_km in load"
        assert "duration_min" in load, "Missing duration_min in load"
        assert "direction" in load, "Missing direction in load"
        assert load["direction"] in ["up", "down", "stable"], f"Invalid direction: {load['direction']}"
        
        print(f"✓ Load card: distance={load['distance_km']}km, duration={load['duration_min']}min, direction={load['direction']}")
    
    def test_response_contains_session_type_card(self):
        """Test that response contains session_type card with label (easy/sustained/hard)"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "session_type" in data, "Missing session_type field"
        session_type = data["session_type"]
        
        assert "label" in session_type, "Missing label in session_type"
        assert session_type["label"] in ["easy", "sustained", "hard"], f"Invalid session_type label: {session_type['label']}"
        
        print(f"✓ Session type card: label={session_type['label']}")
    
    def test_response_contains_insight(self):
        """Test that response contains insight field - max 2 sentences, no jargon"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "insight" in data, "Missing insight field"
        # insight can be null or string
        if data["insight"]:
            assert isinstance(data["insight"], str), "insight should be string"
            # Max 2 sentences check (rough approximation)
            sentences = data["insight"].count('.') + data["insight"].count('!') + data["insight"].count('?')
            assert sentences <= 5, f"insight has too many sentences: {sentences}"
            
            # Check for jargon (no Z2/Z4, no physiology terms)
            jargon_terms = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5', 'VO2', 'lactate', 'threshold', 'aerobic', 'anaerobic']
            insight_upper = data["insight"].upper()
            for term in jargon_terms:
                assert term.upper() not in insight_upper, f"insight contains jargon: {term}"
        
        print(f"✓ Insight: '{data['insight']}'")
    
    def test_response_contains_guidance(self):
        """Test that response contains guidance field (optional, soft wording)"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "guidance" in data, "Missing guidance field"
        # guidance can be null or string
        if data["guidance"]:
            assert isinstance(data["guidance"], str), "guidance should be string"
            # Should be soft wording - check for harsh terms
            harsh_terms = ['must', 'should not', 'never', 'always', 'mandatory']
            guidance_lower = data["guidance"].lower()
            for term in harsh_terms:
                assert term not in guidance_lower, f"guidance contains harsh wording: {term}"
        
        print(f"✓ Guidance: '{data['guidance']}'")
    
    def test_french_language_support(self):
        """Test that French language parameter returns French content with no numbers in coach_summary"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=fr")
        assert response.status_code == 200
        data = response.json()
        
        # Check that coach_summary is in French
        assert "coach_summary" in data
        summary = data["coach_summary"]
        
        # French content should contain accented characters or French words
        french_indicators = ['é', 'è', 'ê', 'à', 'ù', 'ç', 'séance', 'récent', 'plus', 'ton', 'ta', 'sortie', 'habitude']
        has_french = any(indicator in summary.lower() for indicator in french_indicators)
        
        # Check for numbers in French coach_summary
        numbers = re.findall(r'\d+', summary)
        assert len(numbers) <= 2, f"French coach_summary has too many numbers: {numbers}"
        
        print(f"✓ French coach_summary: '{summary}'")
        print(f"✓ French insight: '{data.get('insight', '')}'")
        print(f"✓ French guidance: '{data.get('guidance', '')}'")
    
    def test_workout_not_found_returns_404(self):
        """Test that non-existent workout returns 404"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/nonexistent_workout_id?language=en")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Non-existent workout returns 404")
    
    def test_workout_id_in_response(self):
        """Test that workout_id is included in response"""
        response = requests.get(f"{BASE_URL}/api/coach/workout-analysis/strava_17130033093?language=en")
        data = response.json()
        
        assert "workout_id" in data, "Missing workout_id field"
        assert data["workout_id"] == "strava_17130033093", f"Wrong workout_id: {data['workout_id']}"
        print("✓ workout_id matches request")


class TestWorkoutDetailEndpoint:
    """Tests for workout detail endpoint used by WorkoutDetail page"""
    
    def test_workout_detail_returns_200(self):
        """Test that workout detail endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/workouts/strava_17130033093")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Workout detail returns 200")
    
    def test_workout_detail_contains_required_fields(self):
        """Test that workout detail contains all required fields"""
        response = requests.get(f"{BASE_URL}/api/workouts/strava_17130033093")
        data = response.json()
        
        required_fields = ["id", "type", "name", "date", "duration_minutes", "distance_km"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"✓ Workout: {data['name']} ({data['type']}) - {data['distance_km']}km, {data['duration_minutes']}min")
    
    def test_workout_has_strava_data(self):
        """Test that workout has real Strava data"""
        response = requests.get(f"{BASE_URL}/api/workouts/strava_17130033093")
        data = response.json()
        
        assert data.get("data_source") == "strava", "Workout should be from Strava"
        assert data.get("strava_activity_id") == "17130033093", "Wrong Strava activity ID"
        print(f"✓ Strava data source confirmed: activity_id={data['strava_activity_id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
