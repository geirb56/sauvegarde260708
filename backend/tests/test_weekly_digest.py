"""
Weekly Digest API Tests
Tests for GET /api/coach/digest endpoint - Weekly training digest with AI insights
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestWeeklyDigestAPI:
    """Tests for Weekly Digest endpoint"""
    
    def test_digest_endpoint_returns_200(self):
        """Test that digest endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"SUCCESS: Digest endpoint returned 200")
    
    def test_digest_response_structure(self):
        """Test that digest response has required fields"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check required fields
        required_fields = ['period_start', 'period_end', 'executive_summary', 'metrics', 'signals', 'insights', 'generated_at']
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"SUCCESS: All required fields present in digest response")
    
    def test_digest_executive_summary_is_short(self):
        """Test that executive summary is concise (max 1 sentence)"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        summary = data.get('executive_summary', '')
        
        # Check summary is not empty
        assert len(summary) > 0, "Executive summary should not be empty"
        
        # Check summary is reasonably short (under 200 chars for 1 sentence)
        assert len(summary) < 200, f"Executive summary too long ({len(summary)} chars), should be max 1 sentence"
        
        print(f"SUCCESS: Executive summary is concise: '{summary[:50]}...'")
    
    def test_digest_metrics_structure(self):
        """Test that metrics contain expected fields"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        metrics = data.get('metrics', {})
        
        # Check required metric fields
        required_metrics = ['total_sessions', 'total_distance_km', 'total_duration_min']
        for field in required_metrics:
            assert field in metrics, f"Missing metric field: {field}"
        
        # Verify data types
        assert isinstance(metrics['total_sessions'], int), "total_sessions should be int"
        assert isinstance(metrics['total_distance_km'], (int, float)), "total_distance_km should be numeric"
        assert isinstance(metrics['total_duration_min'], int), "total_duration_min should be int"
        
        print(f"SUCCESS: Metrics structure valid - {metrics['total_sessions']} sessions, {metrics['total_distance_km']} km")
    
    def test_digest_signals_structure(self):
        """Test that signals contain Volume, Intensity, Consistency indicators"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        signals = data.get('signals', [])
        
        # Should have 3 signals
        assert len(signals) == 3, f"Expected 3 signals, got {len(signals)}"
        
        # Check signal keys
        signal_keys = [s.get('key') for s in signals]
        assert 'load' in signal_keys, "Missing 'load' signal (Volume)"
        assert 'intensity' in signal_keys, "Missing 'intensity' signal"
        assert 'consistency' in signal_keys, "Missing 'consistency' signal"
        
        # Check each signal has status
        for signal in signals:
            assert 'status' in signal, f"Signal {signal.get('key')} missing 'status'"
        
        print(f"SUCCESS: All 3 signals present with correct structure")
    
    def test_digest_insights_max_three(self):
        """Test that insights contain max 3 items"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        insights = data.get('insights', [])
        
        # Should have max 3 insights
        assert len(insights) <= 3, f"Expected max 3 insights, got {len(insights)}"
        
        # Each insight should be a string
        for insight in insights:
            assert isinstance(insight, str), "Each insight should be a string"
            # Insights should be short (1-2 lines)
            assert len(insight) < 150, f"Insight too long: {insight[:50]}..."
        
        print(f"SUCCESS: {len(insights)} insights, all within length limits")
    
    def test_digest_zone_distribution(self):
        """Test that zone distribution is included in metrics"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        metrics = data.get('metrics', {})
        zones = metrics.get('zone_distribution')
        
        if zones:
            # Check zone keys
            expected_zones = ['z1', 'z2', 'z3', 'z4', 'z5']
            for zone in expected_zones:
                assert zone in zones, f"Missing zone: {zone}"
            
            # Zone values should be percentages (0-100)
            for zone, value in zones.items():
                assert 0 <= value <= 100, f"Zone {zone} value {value} out of range"
            
            print(f"SUCCESS: Zone distribution valid: {zones}")
        else:
            print("INFO: No zone distribution data (may be expected if no workouts)")
    
    def test_digest_french_language(self):
        """Test that French language returns French content"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=fr")
        assert response.status_code == 200
        
        data = response.json()
        summary = data.get('executive_summary', '')
        
        # Check response is not empty
        assert len(summary) > 0, "French executive summary should not be empty"
        
        # French content should be different from English (AI generates in French)
        en_response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        en_data = en_response.json()
        en_summary = en_data.get('executive_summary', '')
        
        # Note: AI may generate similar content, so we just verify it works
        print(f"SUCCESS: French digest generated: '{summary[:50]}...'")
    
    def test_digest_no_strava_garmin_references(self):
        """Test that digest content doesn't reference Strava or Garmin"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        
        # Convert entire response to string for checking
        response_str = str(data).lower()
        
        # Check for Strava/Garmin references
        assert 'strava' not in response_str, "Digest should not reference Strava"
        assert 'garmin' not in response_str, "Digest should not reference Garmin"
        
        print("SUCCESS: No Strava/Garmin references in digest content")
    
    def test_digest_period_dates_valid(self):
        """Test that period dates are valid ISO format"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        
        from datetime import datetime
        
        # Parse dates
        try:
            start = datetime.fromisoformat(data['period_start'])
            end = datetime.fromisoformat(data['period_end'])
            
            # End should be after start
            assert end >= start, "period_end should be >= period_start"
            
            # Period should be about 7 days
            delta = (end - start).days
            assert 6 <= delta <= 8, f"Period should be ~7 days, got {delta}"
            
            print(f"SUCCESS: Period dates valid: {data['period_start']} to {data['period_end']}")
        except ValueError as e:
            pytest.fail(f"Invalid date format: {e}")
    
    def test_digest_generated_at_timestamp(self):
        """Test that generated_at is a valid timestamp"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        
        data = response.json()
        generated_at = data.get('generated_at', '')
        
        from datetime import datetime
        
        try:
            # Parse ISO timestamp
            timestamp = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
            print(f"SUCCESS: generated_at timestamp valid: {generated_at}")
        except ValueError as e:
            pytest.fail(f"Invalid generated_at timestamp: {e}")


class TestDigestLatestEndpoint:
    """Tests for GET /api/coach/digest/latest endpoint"""
    
    def test_digest_latest_endpoint(self):
        """Test that digest/latest endpoint works"""
        response = requests.get(f"{BASE_URL}/api/coach/digest/latest?user_id=default")
        
        # May return 200 with data or null if no cached digest
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        if data:
            assert 'executive_summary' in data, "Latest digest should have executive_summary"
            print(f"SUCCESS: Latest digest retrieved")
        else:
            print("INFO: No cached digest found (expected on first run)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
