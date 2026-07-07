"""
Test RAG Enrichment with Detailed Strava Data
Tests split_analysis, hr_analysis, cadence_analysis in /api/rag/workout/{id}
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test workout ID with detailed Strava data (splits, hr_analysis, cadence_analysis)
TEST_WORKOUT_ID = "strava_17130033093"


class TestRAGWorkoutSplitAnalysis:
    """Test split_analysis data in /api/rag/workout/{id}"""
    
    def test_workout_has_split_analysis(self):
        """RAG workout should return split_analysis object"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "workout" in data, "Response should contain 'workout'"
        workout = data["workout"]
        
        assert "split_analysis" in workout, "workout should contain 'split_analysis'"
        split_analysis = workout["split_analysis"]
        assert isinstance(split_analysis, dict), "split_analysis should be a dict"
        print(f"✓ split_analysis found: {split_analysis}")
    
    def test_split_analysis_has_fastest_km(self):
        """split_analysis should have fastest_km"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        split_analysis = data["workout"]["split_analysis"]
        
        assert "fastest_km" in split_analysis, "split_analysis should have 'fastest_km'"
        assert isinstance(split_analysis["fastest_km"], int), "fastest_km should be int"
        print(f"✓ fastest_km = {split_analysis['fastest_km']}")
    
    def test_split_analysis_has_slowest_km(self):
        """split_analysis should have slowest_km"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        split_analysis = data["workout"]["split_analysis"]
        
        assert "slowest_km" in split_analysis, "split_analysis should have 'slowest_km'"
        assert isinstance(split_analysis["slowest_km"], int), "slowest_km should be int"
        print(f"✓ slowest_km = {split_analysis['slowest_km']}")
    
    def test_split_analysis_has_pace_drop(self):
        """split_analysis should have pace_drop"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        split_analysis = data["workout"]["split_analysis"]
        
        assert "pace_drop" in split_analysis, "split_analysis should have 'pace_drop'"
        assert isinstance(split_analysis["pace_drop"], (int, float)), "pace_drop should be numeric"
        print(f"✓ pace_drop = {split_analysis['pace_drop']}")
    
    def test_split_analysis_has_consistency_score(self):
        """split_analysis should have consistency_score"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        split_analysis = data["workout"]["split_analysis"]
        
        assert "consistency_score" in split_analysis, "split_analysis should have 'consistency_score'"
        score = split_analysis["consistency_score"]
        assert isinstance(score, (int, float)), "consistency_score should be numeric"
        assert 0 <= score <= 100, f"consistency_score should be 0-100, got {score}"
        print(f"✓ consistency_score = {score}%")
    
    def test_split_analysis_has_negative_split(self):
        """split_analysis should have negative_split boolean"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        split_analysis = data["workout"]["split_analysis"]
        
        assert "negative_split" in split_analysis, "split_analysis should have 'negative_split'"
        assert isinstance(split_analysis["negative_split"], bool), "negative_split should be bool"
        print(f"✓ negative_split = {split_analysis['negative_split']}")


class TestRAGWorkoutHRAnalysis:
    """Test hr_analysis data in /api/rag/workout/{id}"""
    
    def test_workout_has_hr_analysis(self):
        """RAG workout should return hr_analysis object"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        workout = data["workout"]
        assert "hr_analysis" in workout, "workout should contain 'hr_analysis'"
        hr_analysis = workout["hr_analysis"]
        assert isinstance(hr_analysis, dict), "hr_analysis should be a dict"
        print(f"✓ hr_analysis found: {hr_analysis}")
    
    def test_hr_analysis_has_min_hr(self):
        """hr_analysis should have min_hr"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        hr_analysis = data["workout"]["hr_analysis"]
        
        assert "min_hr" in hr_analysis, "hr_analysis should have 'min_hr'"
        min_hr = hr_analysis["min_hr"]
        assert isinstance(min_hr, (int, float)), "min_hr should be numeric"
        assert min_hr > 0, f"min_hr should be > 0, got {min_hr}"
        print(f"✓ min_hr = {min_hr} bpm")
    
    def test_hr_analysis_has_avg_hr(self):
        """hr_analysis should have avg_hr"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        hr_analysis = data["workout"]["hr_analysis"]
        
        assert "avg_hr" in hr_analysis, "hr_analysis should have 'avg_hr'"
        avg_hr = hr_analysis["avg_hr"]
        assert isinstance(avg_hr, (int, float)), "avg_hr should be numeric"
        assert avg_hr > 0, f"avg_hr should be > 0, got {avg_hr}"
        print(f"✓ avg_hr = {avg_hr} bpm")
    
    def test_hr_analysis_has_max_hr(self):
        """hr_analysis should have max_hr"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        hr_analysis = data["workout"]["hr_analysis"]
        
        assert "max_hr" in hr_analysis, "hr_analysis should have 'max_hr'"
        max_hr = hr_analysis["max_hr"]
        assert isinstance(max_hr, (int, float)), "max_hr should be numeric"
        assert max_hr > 0, f"max_hr should be > 0, got {max_hr}"
        print(f"✓ max_hr = {max_hr} bpm")
    
    def test_hr_analysis_has_hr_drift(self):
        """hr_analysis should have hr_drift"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        hr_analysis = data["workout"]["hr_analysis"]
        
        assert "hr_drift" in hr_analysis, "hr_analysis should have 'hr_drift'"
        hr_drift = hr_analysis["hr_drift"]
        assert isinstance(hr_drift, (int, float)), "hr_drift should be numeric"
        print(f"✓ hr_drift = {hr_drift} bpm")
    
    def test_hr_values_logical(self):
        """HR values should be logically consistent (min <= avg <= max)"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        hr_analysis = data["workout"]["hr_analysis"]
        
        min_hr = hr_analysis["min_hr"]
        avg_hr = hr_analysis["avg_hr"]
        max_hr = hr_analysis["max_hr"]
        
        assert min_hr <= avg_hr, f"min_hr ({min_hr}) should be <= avg_hr ({avg_hr})"
        assert avg_hr <= max_hr, f"avg_hr ({avg_hr}) should be <= max_hr ({max_hr})"
        print(f"✓ HR values logical: {min_hr} <= {avg_hr} <= {max_hr}")


class TestRAGWorkoutCadenceAnalysis:
    """Test cadence_analysis data in /api/rag/workout/{id}"""
    
    def test_workout_has_cadence_analysis(self):
        """RAG workout should return cadence_analysis object"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        workout = data["workout"]
        assert "cadence_analysis" in workout, "workout should contain 'cadence_analysis'"
        cadence_analysis = workout["cadence_analysis"]
        assert isinstance(cadence_analysis, dict), "cadence_analysis should be a dict"
        print(f"✓ cadence_analysis found: {cadence_analysis}")
    
    def test_cadence_analysis_has_min_cadence(self):
        """cadence_analysis should have min_cadence"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        cadence_analysis = data["workout"]["cadence_analysis"]
        
        assert "min_cadence" in cadence_analysis, "cadence_analysis should have 'min_cadence'"
        min_cad = cadence_analysis["min_cadence"]
        assert isinstance(min_cad, (int, float)), "min_cadence should be numeric"
        print(f"✓ min_cadence = {min_cad} spm")
    
    def test_cadence_analysis_has_max_cadence(self):
        """cadence_analysis should have max_cadence"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        cadence_analysis = data["workout"]["cadence_analysis"]
        
        assert "max_cadence" in cadence_analysis, "cadence_analysis should have 'max_cadence'"
        max_cad = cadence_analysis["max_cadence"]
        assert isinstance(max_cad, (int, float)), "max_cadence should be numeric"
        print(f"✓ max_cadence = {max_cad} spm")
    
    def test_cadence_analysis_has_avg_cadence(self):
        """cadence_analysis should have avg_cadence"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        cadence_analysis = data["workout"]["cadence_analysis"]
        
        assert "avg_cadence" in cadence_analysis, "cadence_analysis should have 'avg_cadence'"
        avg_cad = cadence_analysis["avg_cadence"]
        assert isinstance(avg_cad, (int, float)), "avg_cadence should be numeric"
        print(f"✓ avg_cadence = {avg_cad} spm")
    
    def test_cadence_analysis_has_stability(self):
        """cadence_analysis should have cadence_stability"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        cadence_analysis = data["workout"]["cadence_analysis"]
        
        assert "cadence_stability" in cadence_analysis, "cadence_analysis should have 'cadence_stability'"
        stability = cadence_analysis["cadence_stability"]
        assert isinstance(stability, (int, float)), "cadence_stability should be numeric"
        assert 0 <= stability <= 100, f"cadence_stability should be 0-100, got {stability}"
        print(f"✓ cadence_stability = {stability}%")


class TestRAGWorkoutComparison:
    """Test comparison with similar workouts including splits_comparison"""
    
    def test_comparison_has_splits_comparison(self):
        """comparison should have splits_comparison from previous similar workouts"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "comparison" in data, "Response should contain 'comparison'"
        comparison = data["comparison"]
        
        # splits_comparison may be empty string if no comparison available
        if comparison.get("similar_found", 0) > 0:
            assert "splits_comparison" in comparison, "comparison should have 'splits_comparison'"
            print(f"✓ splits_comparison = '{comparison.get('splits_comparison', '')}'")
        else:
            print("✓ No similar workouts found, splits_comparison not required")
    
    def test_comparison_has_progression(self):
        """comparison should have progression indicator"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        data = response.json()
        comparison = data["comparison"]
        
        if comparison.get("similar_found", 0) > 0:
            assert "progression" in comparison, "comparison should have 'progression'"
            print(f"✓ progression = '{comparison.get('progression', '')}'")
        else:
            print("✓ No similar workouts found, progression not required")


class TestRAGSources:
    """Test rag_sources metadata"""
    
    def test_rag_sources_indicates_detailed_data(self):
        """rag_sources should indicate which detailed data is available"""
        response = requests.get(f"{BASE_URL}/api/rag/workout/{TEST_WORKOUT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "rag_sources" in data, "Response should contain 'rag_sources'"
        sources = data["rag_sources"]
        
        # Check for detailed data indicators
        assert "detailed_splits" in sources, "rag_sources should have 'detailed_splits'"
        assert "hr_analysis" in sources, "rag_sources should have 'hr_analysis'"
        assert "cadence_analysis" in sources, "rag_sources should have 'cadence_analysis'"
        
        print(f"✓ rag_sources: detailed_splits={sources['detailed_splits']}, hr_analysis={sources['hr_analysis']}, cadence_analysis={sources['cadence_analysis']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
