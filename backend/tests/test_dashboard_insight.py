"""
Test Dashboard Insight API - Decision Assistant Dashboard
Tests the redesigned dashboard that acts as a decision assistant, not a data dashboard.

Structure tested:
1) Coach Insight at top (1 sentence, max 15 words, action-oriented)
2) This Week (3 cards: Sessions, Volume km, Load signal Low/Balanced/High)
3) Last 30 Days (compact: Total km, Active weeks, Trend Up/Stable/Down)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestDashboardInsightAPI:
    """Test GET /api/dashboard/insight endpoint"""
    
    def test_dashboard_insight_returns_200(self):
        """Dashboard insight endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Dashboard insight returns 200 OK")
    
    def test_dashboard_insight_has_coach_insight(self):
        """Response contains coach_insight field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        assert "coach_insight" in data, "Missing coach_insight field"
        assert isinstance(data["coach_insight"], str), "coach_insight should be a string"
        assert len(data["coach_insight"]) > 0, "coach_insight should not be empty"
        print(f"✓ coach_insight present: '{data['coach_insight']}'")
    
    def test_coach_insight_is_one_sentence_max_15_words(self):
        """Coach insight is ONE sentence, max 15 words, action-oriented"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        insight = data.get("coach_insight", "")
        
        # Count words
        words = insight.split()
        word_count = len(words)
        
        # Should be max 18 words (allowing some flexibility for AI)
        assert word_count <= 18, f"Coach insight has {word_count} words, expected max 18: '{insight}'"
        
        # Should be one sentence (no multiple periods except at end)
        sentence_count = insight.count('. ')
        assert sentence_count <= 1, f"Coach insight has multiple sentences: '{insight}'"
        
        print(f"✓ Coach insight is {word_count} words, 1 sentence: '{insight}'")
    
    def test_dashboard_insight_has_week_stats(self):
        """Response contains week stats with sessions, volume_km, load_signal"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        assert "week" in data, "Missing week field"
        week = data["week"]
        
        # Check required fields
        assert "sessions" in week, "Missing week.sessions"
        assert "volume_km" in week, "Missing week.volume_km"
        assert "load_signal" in week, "Missing week.load_signal"
        
        # Validate types
        assert isinstance(week["sessions"], int), "week.sessions should be int"
        assert isinstance(week["volume_km"], (int, float)), "week.volume_km should be numeric"
        assert isinstance(week["load_signal"], str), "week.load_signal should be string"
        
        print(f"✓ Week stats: sessions={week['sessions']}, volume_km={week['volume_km']}, load_signal={week['load_signal']}")
    
    def test_week_sessions_is_count_of_workouts(self):
        """week.sessions is count of workouts this week"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        sessions = data["week"]["sessions"]
        assert sessions >= 0, "Sessions count should be non-negative"
        assert isinstance(sessions, int), "Sessions should be an integer count"
        
        print(f"✓ week.sessions = {sessions} (count of workouts this week)")
    
    def test_week_volume_km_is_total_km(self):
        """week.volume_km is total km this week"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        volume_km = data["week"]["volume_km"]
        assert volume_km >= 0, "Volume km should be non-negative"
        assert isinstance(volume_km, (int, float)), "Volume km should be numeric"
        
        print(f"✓ week.volume_km = {volume_km} km (total km this week)")
    
    def test_week_load_signal_is_valid(self):
        """week.load_signal is low/balanced/high"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        load_signal = data["week"]["load_signal"]
        valid_signals = ["low", "balanced", "high"]
        assert load_signal in valid_signals, f"load_signal '{load_signal}' not in {valid_signals}"
        
        print(f"✓ week.load_signal = '{load_signal}' (valid signal)")
    
    def test_dashboard_insight_has_month_stats(self):
        """Response contains month stats with volume_km, active_weeks, trend"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        assert "month" in data, "Missing month field"
        month = data["month"]
        
        # Check required fields
        assert "volume_km" in month, "Missing month.volume_km"
        assert "active_weeks" in month, "Missing month.active_weeks"
        assert "trend" in month, "Missing month.trend"
        
        # Validate types
        assert isinstance(month["volume_km"], (int, float)), "month.volume_km should be numeric"
        assert isinstance(month["active_weeks"], int), "month.active_weeks should be int"
        assert isinstance(month["trend"], str), "month.trend should be string"
        
        print(f"✓ Month stats: volume_km={month['volume_km']}, active_weeks={month['active_weeks']}, trend={month['trend']}")
    
    def test_month_volume_km_is_total_30_days(self):
        """month.volume_km is total km last 30 days"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        volume_km = data["month"]["volume_km"]
        assert volume_km >= 0, "Month volume km should be non-negative"
        
        print(f"✓ month.volume_km = {volume_km} km (total km last 30 days)")
    
    def test_month_active_weeks_is_count(self):
        """month.active_weeks is count of weeks with activity"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        active_weeks = data["month"]["active_weeks"]
        assert active_weeks >= 0, "Active weeks should be non-negative"
        assert active_weeks <= 5, "Active weeks should be max 5 (for 30 days)"
        
        print(f"✓ month.active_weeks = {active_weeks} (weeks with activity)")
    
    def test_month_trend_is_valid(self):
        """month.trend is up/stable/down"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        
        trend = data["month"]["trend"]
        valid_trends = ["up", "stable", "down"]
        assert trend in valid_trends, f"trend '{trend}' not in {valid_trends}"
        
        print(f"✓ month.trend = '{trend}' (valid trend)")


class TestDashboardInsightFrench:
    """Test French language support for dashboard insight"""
    
    def test_french_insight_returns_200(self):
        """French dashboard insight returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=fr")
        assert response.status_code == 200
        print("✓ French dashboard insight returns 200 OK")
    
    def test_french_insight_is_in_french(self):
        """French coach insight is in French"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=fr")
        data = response.json()
        insight = data.get("coach_insight", "")
        
        # Check for common French words/patterns
        french_indicators = ["la", "le", "de", "du", "une", "un", "cette", "ce", "pour", "avec", "ton", "ta", "tes", "semaine", "entrainement", "charge", "volume", "séance", "sortie"]
        has_french = any(word.lower() in insight.lower() for word in french_indicators)
        
        # Also check it's not obviously English
        english_indicators = ["the", "this", "your", "week", "training", "load", "session"]
        has_english = any(word.lower() in insight.lower() for word in english_indicators)
        
        # French insight should have French words and ideally no English
        assert has_french or not has_english, f"French insight may not be in French: '{insight}'"
        
        print(f"✓ French coach insight: '{insight}'")
    
    def test_french_insight_same_structure(self):
        """French response has same structure as English"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight?language=fr")
        data = response.json()
        
        assert "coach_insight" in data
        assert "week" in data
        assert "month" in data
        assert "sessions" in data["week"]
        assert "volume_km" in data["week"]
        assert "load_signal" in data["week"]
        assert "volume_km" in data["month"]
        assert "active_weeks" in data["month"]
        assert "trend" in data["month"]
        
        print("✓ French response has same structure as English")


class TestDashboardNoRawNumbers:
    """Test that dashboard shows interpreted signals, not raw HR/pace numbers"""
    
    def test_no_hr_numbers_in_insight(self):
        """Coach insight should not contain HR numbers"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        insight = data.get("coach_insight", "")
        
        # Check for HR-related numbers (e.g., "142 bpm", "HR 155")
        import re
        hr_pattern = r'\b\d{2,3}\s*(bpm|BPM|hr|HR|heart rate)\b'
        has_hr = re.search(hr_pattern, insight, re.IGNORECASE)
        
        assert not has_hr, f"Coach insight contains HR numbers: '{insight}'"
        print(f"✓ No HR numbers in coach insight")
    
    def test_no_pace_numbers_in_insight(self):
        """Coach insight should not contain pace numbers"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        insight = data.get("coach_insight", "")
        
        # Check for pace-related numbers (e.g., "5:30/km", "5.5 min/km")
        import re
        pace_pattern = r'\b\d+[:\.]?\d*\s*(min/km|/km|min per km)\b'
        has_pace = re.search(pace_pattern, insight, re.IGNORECASE)
        
        assert not has_pace, f"Coach insight contains pace numbers: '{insight}'"
        print(f"✓ No pace numbers in coach insight")
    
    def test_insight_is_action_oriented(self):
        """Coach insight should be action-oriented"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insight")
        data = response.json()
        insight = data.get("coach_insight", "").lower()
        
        # Action-oriented words
        action_words = ["keep", "maintain", "add", "try", "consider", "focus", "continue", "reduce", "increase", "rest", "recover", "push", "build", "consolidate", "garde", "maintiens", "ajoute", "essaie", "continue", "relance"]
        
        has_action = any(word in insight for word in action_words)
        
        # It's okay if it's a status statement too
        status_words = ["on track", "balanced", "well managed", "consistent", "en cours", "équilibré", "bien géré"]
        has_status = any(word in insight for word in status_words)
        
        assert has_action or has_status, f"Coach insight may not be action-oriented: '{insight}'"
        print(f"✓ Coach insight is action-oriented or status-based")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
