"""
Test suite for Weekly Review (Bilan de la semaine) - /api/coach/digest endpoint
Tests the new 6-card structure:
- CARTE 1: Coach Summary (1 phrase)
- CARTE 2: Visual Signals (Volume/Intensity/Regularity)
- CARTE 3: Essential Numbers with comparison vs last week
- CARTE 4: Coach Reading (2-3 phrases)
- CARTE 5: Recommendations (action-oriented)
- CARTE 6: Ask Coach button (frontend only)
"""
import pytest
import requests
import os
import re

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestWeeklyReviewEndpoint:
    """Test /api/coach/digest endpoint - Weekly Review structure"""
    
    def test_digest_endpoint_returns_200(self):
        """Test that /api/coach/digest returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /api/coach/digest returns 200 OK")
    
    def test_response_has_coach_summary(self):
        """Test that response contains coach_summary (CARTE 1)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "coach_summary" in data, "Missing coach_summary field"
        assert isinstance(data["coach_summary"], str), "coach_summary should be a string"
        assert len(data["coach_summary"]) > 0, "coach_summary should not be empty"
        print(f"✓ coach_summary present: '{data['coach_summary'][:50]}...'")
    
    def test_response_has_signals(self):
        """Test that response contains signals array (CARTE 2)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "signals" in data, "Missing signals field"
        assert isinstance(data["signals"], list), "signals should be a list"
        assert len(data["signals"]) == 3, f"Expected 3 signals, got {len(data['signals'])}"
        
        # Check signal keys
        signal_keys = [s["key"] for s in data["signals"]]
        assert "load" in signal_keys, "Missing 'load' signal"
        assert "intensity" in signal_keys, "Missing 'intensity' signal"
        assert "consistency" in signal_keys, "Missing 'consistency' signal"
        print(f"✓ signals present with keys: {signal_keys}")
    
    def test_signals_have_correct_structure(self):
        """Test that each signal has key, status, and value fields"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        
        for signal in data["signals"]:
            assert "key" in signal, "Signal missing 'key' field"
            assert "status" in signal, "Signal missing 'status' field"
            assert "value" in signal, "Signal missing 'value' field"
            
            # Validate status values
            if signal["key"] == "load":
                assert signal["status"] in ["up", "down", "stable"], f"Invalid load status: {signal['status']}"
            elif signal["key"] == "intensity":
                assert signal["status"] in ["hard", "easy", "balanced"], f"Invalid intensity status: {signal['status']}"
            elif signal["key"] == "consistency":
                assert signal["status"] in ["high", "moderate", "low"], f"Invalid consistency status: {signal['status']}"
        
        print("✓ All signals have correct structure and valid status values")
    
    def test_response_has_metrics(self):
        """Test that response contains metrics (CARTE 3)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "metrics" in data, "Missing metrics field"
        
        metrics = data["metrics"]
        assert "total_sessions" in metrics, "Missing total_sessions in metrics"
        assert "total_distance_km" in metrics, "Missing total_distance_km in metrics"
        assert "total_duration_min" in metrics, "Missing total_duration_min in metrics"
        
        assert isinstance(metrics["total_sessions"], int), "total_sessions should be int"
        assert isinstance(metrics["total_distance_km"], (int, float)), "total_distance_km should be numeric"
        assert isinstance(metrics["total_duration_min"], int), "total_duration_min should be int"
        
        print(f"✓ metrics present: {metrics['total_sessions']} sessions, {metrics['total_distance_km']}km, {metrics['total_duration_min']}min")
    
    def test_response_has_comparison(self):
        """Test that response contains comparison vs last week"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "comparison" in data, "Missing comparison field"
        
        comparison = data["comparison"]
        assert "sessions_diff" in comparison, "Missing sessions_diff in comparison"
        assert "distance_diff_km" in comparison, "Missing distance_diff_km in comparison"
        assert "distance_diff_pct" in comparison, "Missing distance_diff_pct in comparison"
        assert "duration_diff_min" in comparison, "Missing duration_diff_min in comparison"
        
        print(f"✓ comparison present: {comparison['distance_diff_pct']}% vs last week")
    
    def test_response_has_coach_reading(self):
        """Test that response contains coach_reading (CARTE 4)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "coach_reading" in data, "Missing coach_reading field"
        assert isinstance(data["coach_reading"], str), "coach_reading should be a string"
        # coach_reading can be empty if no data
        print(f"✓ coach_reading present: '{data['coach_reading'][:50]}...' (length: {len(data['coach_reading'])})")
    
    def test_response_has_recommendations(self):
        """Test that response contains recommendations (CARTE 5)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "recommendations" in data, "Missing recommendations field"
        assert isinstance(data["recommendations"], list), "recommendations should be a list"
        # Should have 1-2 recommendations if there's data
        if data["metrics"]["total_sessions"] > 0:
            assert len(data["recommendations"]) >= 1, "Should have at least 1 recommendation"
            assert len(data["recommendations"]) <= 2, "Should have at most 2 recommendations"
        print(f"✓ recommendations present: {len(data['recommendations'])} items")
    
    def test_response_has_period_dates(self):
        """Test that response contains period_start and period_end"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        assert "period_start" in data, "Missing period_start field"
        assert "period_end" in data, "Missing period_end field"
        assert "generated_at" in data, "Missing generated_at field"
        
        # Validate date format (ISO format)
        assert re.match(r'\d{4}-\d{2}-\d{2}', data["period_start"]), "Invalid period_start format"
        assert re.match(r'\d{4}-\d{2}-\d{2}', data["period_end"]), "Invalid period_end format"
        
        print(f"✓ period dates present: {data['period_start']} to {data['period_end']}")


class TestWeeklyReviewFrench:
    """Test French language support for Weekly Review"""
    
    def test_french_digest_returns_200(self):
        """Test that French digest returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=fr", timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /api/coach/digest?language=fr returns 200 OK")
    
    def test_french_coach_summary_is_french(self):
        """Test that French coach_summary is in French"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=fr", timeout=60)
        data = response.json()
        
        # Check for French words/patterns
        coach_summary = data.get("coach_summary", "").lower()
        if len(coach_summary) > 10:  # Only check if there's content
            # French indicators
            french_indicators = ["semaine", "bon", "bien", "sans", "avec", "pour", "une", "des", "les", "est", "pas"]
            has_french = any(word in coach_summary for word in french_indicators)
            # English indicators (should NOT be present)
            english_indicators = ["week", "good", "the", "and", "for", "with", "your"]
            has_english = any(word in coach_summary for word in english_indicators)
            
            assert has_french or not has_english, f"French summary may contain English: {coach_summary[:100]}"
        
        print(f"✓ French coach_summary: '{data['coach_summary'][:50]}...'")
    
    def test_french_response_has_same_structure(self):
        """Test that French response has same structure as English"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=fr", timeout=60)
        data = response.json()
        
        required_fields = ["period_start", "period_end", "coach_summary", "coach_reading", 
                          "recommendations", "metrics", "comparison", "signals", "generated_at"]
        
        for field in required_fields:
            assert field in data, f"Missing field in French response: {field}"
        
        print("✓ French response has all required fields")


class TestWeeklyReviewContentQuality:
    """Test content quality of Weekly Review"""
    
    def test_coach_summary_is_one_sentence(self):
        """Test that coach_summary is approximately one sentence"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        
        coach_summary = data.get("coach_summary", "")
        if len(coach_summary) > 10:
            # Count sentences (rough approximation)
            sentence_count = len(re.findall(r'[.!?]+', coach_summary))
            assert sentence_count <= 2, f"coach_summary should be ~1 sentence, found {sentence_count}"
        
        print(f"✓ coach_summary is concise: {len(coach_summary)} chars")
    
    def test_coach_reading_is_2_3_sentences(self):
        """Test that coach_reading is 2-3 sentences"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        
        coach_reading = data.get("coach_reading", "")
        if len(coach_reading) > 10:
            # Count sentences (rough approximation)
            sentence_count = len(re.findall(r'[.!?]+', coach_reading))
            assert sentence_count <= 5, f"coach_reading should be 2-3 sentences, found {sentence_count}"
        
        print(f"✓ coach_reading is appropriate length: {len(coach_reading)} chars")
    
    def test_recommendations_are_action_oriented(self):
        """Test that recommendations are action-oriented"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        
        recommendations = data.get("recommendations", [])
        if recommendations:
            # Action verbs that should appear
            action_verbs = ["add", "keep", "try", "do", "make", "run", "ride", "focus", "maintain", "increase", "decrease", "start", "finish"]
            
            for rec in recommendations:
                rec_lower = rec.lower()
                has_action = any(verb in rec_lower for verb in action_verbs)
                # Not a strict requirement, just informational
                print(f"  Recommendation: '{rec[:60]}...' (action-oriented: {has_action})")
        
        print(f"✓ {len(recommendations)} recommendations checked")
    
    def test_no_markdown_in_content(self):
        """Test that content has no markdown formatting"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en", timeout=60)
        data = response.json()
        
        content_fields = ["coach_summary", "coach_reading"]
        for field in content_fields:
            content = data.get(field, "")
            # Check for markdown patterns
            assert "**" not in content, f"Found markdown bold in {field}"
            assert "##" not in content, f"Found markdown header in {field}"
            assert "```" not in content, f"Found markdown code block in {field}"
            assert "* " not in content or content.count("* ") < 3, f"Found markdown list in {field}"
        
        print("✓ No markdown formatting in content")


class TestWeeklyReviewLatestEndpoint:
    """Test /api/coach/digest/latest endpoint"""
    
    def test_latest_digest_returns_200_or_null(self):
        """Test that /api/coach/digest/latest returns 200"""
        response = requests.get(f"{BASE_URL}/api/coach/digest/latest?user_id=default", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /api/coach/digest/latest returns 200 OK")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
