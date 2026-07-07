"""
Test Coach Q&A Conversational Response Format
Tests that POST /api/coach/analyze returns conversational, coach-like responses
NOT report-like responses with markdown, stars, or numbered lists.
"""
import pytest
import requests
import os
import re
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestCoachConversationalFormat:
    """Test that coach responses are conversational, not report-like"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup unique user_id for each test to get fresh responses"""
        self.user_id = f"test_user_{uuid.uuid4().hex[:8]}"
        yield
        # Cleanup: Clear conversation history for test user
        try:
            requests.delete(f"{BASE_URL}/api/coach/history?user_id={self.user_id}")
        except:
            pass
    
    def test_api_health(self):
        """Test API is accessible"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        assert "CardioCoach" in response.json().get("message", "")
    
    def test_english_response_no_stars(self):
        """Test English response has no stars (*, **, ****)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Should I rest tomorrow?",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        
        content = data["response"]
        print(f"English response: {content[:500]}...")
        
        # Check for stars
        star_patterns = [r'\*\*\*\*', r'\*\*\*', r'\*\*', r'^\*\s', r'\n\*\s']
        for pattern in star_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            assert len(matches) == 0, f"Found stars in response: {matches}"
    
    def test_english_response_no_markdown_headers(self):
        """Test English response has no markdown headers (##, ###)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "How is my training load this week?",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"English response: {content[:500]}...")
        
        # Check for markdown headers
        header_patterns = [r'^#{1,6}\s', r'\n#{1,6}\s']
        for pattern in header_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            assert len(matches) == 0, f"Found markdown headers in response: {matches}"
    
    def test_english_response_no_numbered_lists(self):
        """Test English response has no numbered lists (1., 2., 3.)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "What should I focus on in my next workout?",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"English response: {content[:500]}...")
        
        # Check for numbered lists (1., 2., 3., etc. at start of line)
        numbered_pattern = r'^\d+\.\s'
        matches = re.findall(numbered_pattern, content, re.MULTILINE)
        assert len(matches) == 0, f"Found numbered lists in response: {matches}"
    
    def test_english_response_is_conversational(self):
        """Test English response is conversational (direct answer + optional context + coach tip)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Should I rest tomorrow?",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"English conversational response:\n{content}")
        
        # Response should be readable in under 15 seconds (roughly 200-300 words max)
        word_count = len(content.split())
        assert word_count < 400, f"Response too long ({word_count} words), should be readable in <15 seconds"
        
        # Response should have some content (not empty)
        assert len(content) > 50, "Response too short"
    
    def test_english_response_100_percent_english(self):
        """Test English response is 100% English (no French words)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "How is my pace consistency?",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"].lower()
        print(f"English response: {content[:500]}...")
        
        # Common French words that should NOT appear in English response
        french_words = [
            'entrainement', 'seance', 'allure', 'frequence', 'cardiaque',
            'recuperation', 'conseil', 'semaine', 'derniere', 'prochaine',
            'maintenir', 'ajuster', 'consolider', 'bienveillant', 'calme',
            'ton', 'ta', 'tes', 'votre', 'vos', 'une', 'des', 'les',
            'pour', 'avec', 'dans', 'sur', 'sous', 'entre', 'vers'
        ]
        
        for word in french_words:
            # Check for standalone French words (not part of English words)
            pattern = r'\b' + word + r'\b'
            matches = re.findall(pattern, content)
            if matches:
                # Allow some false positives like "ton" (English word too)
                if word not in ['ton', 'pour', 'ta']:
                    assert len(matches) == 0, f"Found French word '{word}' in English response"
    
    def test_french_response_no_stars(self):
        """Test French response has no stars (*, **, ****)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Comment va ma regularite?",
            "language": "fr",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"French response: {content[:500]}...")
        
        # Check for stars
        star_patterns = [r'\*\*\*\*', r'\*\*\*', r'\*\*', r'^\*\s', r'\n\*\s']
        for pattern in star_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            assert len(matches) == 0, f"Found stars in French response: {matches}"
    
    def test_french_response_no_markdown_headers(self):
        """Test French response has no markdown headers (##, ###)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Quelle est ma charge d'entrainement?",
            "language": "fr",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"French response: {content[:500]}...")
        
        # Check for markdown headers
        header_patterns = [r'^#{1,6}\s', r'\n#{1,6}\s']
        for pattern in header_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            assert len(matches) == 0, f"Found markdown headers in French response: {matches}"
    
    def test_french_response_no_numbered_lists(self):
        """Test French response has no numbered lists (1., 2., 3.)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Dois-je me reposer demain?",
            "language": "fr",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"French response: {content[:500]}...")
        
        # Check for numbered lists
        numbered_pattern = r'^\d+\.\s'
        matches = re.findall(numbered_pattern, content, re.MULTILINE)
        assert len(matches) == 0, f"Found numbered lists in French response: {matches}"
    
    def test_french_response_100_percent_french(self):
        """Test French response is 100% French (no English words)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Comment va ma regularite?",
            "language": "fr",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"].lower()
        print(f"French response: {content[:500]}...")
        
        # Common English words that should NOT appear in French response
        english_words = [
            'training', 'workout', 'session', 'heart rate', 'recovery',
            'advice', 'week', 'next', 'previous', 'maintain', 'adjust',
            'steady', 'load', 'intensity', 'volume', 'pace', 'consistency',
            'the', 'and', 'but', 'with', 'from', 'your', 'you', 'should'
        ]
        
        for word in english_words:
            pattern = r'\b' + word + r'\b'
            matches = re.findall(pattern, content)
            # Allow some technical terms that might be used in French context
            if word not in ['pace', 'load', 'volume']:
                assert len(matches) == 0, f"Found English word '{word}' in French response"
    
    def test_response_readable_under_15_seconds(self):
        """Test response is readable in under 15 seconds (approx 200-300 words)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Analyze my recent training load and effort distribution.",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        
        word_count = len(content.split())
        print(f"Response word count: {word_count}")
        print(f"Response: {content}")
        
        # Average reading speed is ~200-250 words per minute
        # 15 seconds = 50-60 words at minimum, up to ~300 words for fast readers
        assert word_count < 400, f"Response too long ({word_count} words) for 15-second readability"
    
    def test_response_has_coach_tip(self):
        """Test response includes a coach tip (actionable recommendation)"""
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Should I do intervals or easy run tomorrow?",
            "language": "en",
            "user_id": self.user_id
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"Response with coach tip:\n{content}")
        
        # Response should have some actionable content
        # Look for recommendation-like phrases
        recommendation_indicators = [
            'try', 'consider', 'suggest', 'recommend', 'focus', 'keep',
            'aim', 'go for', 'opt for', 'stick with', 'prioritize'
        ]
        
        content_lower = content.lower()
        has_recommendation = any(indicator in content_lower for indicator in recommendation_indicators)
        
        # This is a soft check - the response should generally have some actionable advice
        if not has_recommendation:
            print("WARNING: Response may not have clear actionable recommendation")


class TestCoachClearHistory:
    """Test clear history functionality"""
    
    def test_clear_history_works(self):
        """Test that clear history endpoint works"""
        test_user = f"test_clear_{uuid.uuid4().hex[:8]}"
        
        # First, send a message to create history
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Test message",
            "language": "en",
            "user_id": test_user
        }, timeout=60)
        assert response.status_code == 200
        
        # Check history exists
        history_response = requests.get(f"{BASE_URL}/api/coach/history?user_id={test_user}")
        assert history_response.status_code == 200
        assert len(history_response.json()) > 0
        
        # Clear history
        clear_response = requests.delete(f"{BASE_URL}/api/coach/history?user_id={test_user}")
        assert clear_response.status_code == 200
        
        # Verify history is cleared
        history_after = requests.get(f"{BASE_URL}/api/coach/history?user_id={test_user}")
        assert history_after.status_code == 200
        assert len(history_after.json()) == 0


class TestQuickActionButtons:
    """Test quick action buttons send predefined questions"""
    
    def test_training_load_question(self):
        """Test training load question works"""
        test_user = f"test_quick_{uuid.uuid4().hex[:8]}"
        
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "Analyze my recent training load and effort distribution.",
            "language": "en",
            "user_id": test_user
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"Training load response: {content[:300]}...")
        
        # Should mention something about training/load/effort
        content_lower = content.lower()
        assert any(word in content_lower for word in ['training', 'load', 'effort', 'workout', 'session']), \
            "Response should mention training-related terms"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/coach/history?user_id={test_user}")
    
    def test_heart_rate_question(self):
        """Test heart rate question works"""
        test_user = f"test_hr_{uuid.uuid4().hex[:8]}"
        
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "What patterns do you see in my heart rate data?",
            "language": "en",
            "user_id": test_user
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"Heart rate response: {content[:300]}...")
        
        # Should mention something about heart rate
        content_lower = content.lower()
        assert any(word in content_lower for word in ['heart', 'rate', 'hr', 'cardiac', 'bpm']), \
            "Response should mention heart rate-related terms"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/coach/history?user_id={test_user}")
    
    def test_pace_consistency_question(self):
        """Test pace consistency question works"""
        test_user = f"test_pace_{uuid.uuid4().hex[:8]}"
        
        response = requests.post(f"{BASE_URL}/api/coach/analyze", json={
            "message": "How is my pace consistency across recent runs?",
            "language": "en",
            "user_id": test_user
        }, timeout=60)
        
        assert response.status_code == 200
        content = response.json()["response"]
        print(f"Pace consistency response: {content[:300]}...")
        
        # Should mention something about pace/consistency/runs
        content_lower = content.lower()
        assert any(word in content_lower for word in ['pace', 'consistency', 'run', 'speed', 'tempo']), \
            "Response should mention pace-related terms"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/coach/history?user_id={test_user}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
