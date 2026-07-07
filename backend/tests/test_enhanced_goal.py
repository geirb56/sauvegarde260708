"""
Test Enhanced Goal Feature with Distance Types and Target Pace Calculation
Tests:
- Distance type selector (5k, 10k, semi, marathon, ultra)
- Target time in hours:minutes format
- Automatic pace calculation
- Goal display with distance_km, target_time, target_pace
- Coach recommendations adapted to target pace
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestEnhancedGoalAPI:
    """Test enhanced goal API with distance types and pace calculation"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up goal before and after each test"""
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
        yield
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
    
    def test_api_health(self):
        """Test API is accessible"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        assert response.json()["message"] == "CardioCoach API"
    
    # Test distance type options
    def test_create_goal_5k(self):
        """Test creating 5k goal with target time"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_5k Race",
            "event_date": "2026-06-15",
            "distance_type": "5k",
            "target_time_minutes": 25  # 25 minutes = 5:00/km pace
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        goal = data["goal"]
        
        # Verify distance_type and distance_km
        assert goal["distance_type"] == "5k"
        assert goal["distance_km"] == 5.0
        
        # Verify target time
        assert goal["target_time_minutes"] == 25
        
        # Verify pace calculation: 25min / 5km = 5:00/km
        assert goal["target_pace"] == "5:00"
    
    def test_create_goal_10k(self):
        """Test creating 10k goal with target time"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_10k Race",
            "event_date": "2026-07-20",
            "distance_type": "10k",
            "target_time_minutes": 50  # 50 minutes = 5:00/km pace
        })
        assert response.status_code == 200
        goal = response.json()["goal"]
        
        assert goal["distance_type"] == "10k"
        assert goal["distance_km"] == 10.0
        assert goal["target_time_minutes"] == 50
        assert goal["target_pace"] == "5:00"
    
    def test_create_goal_semi_marathon(self):
        """Test creating semi-marathon (half marathon) goal"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Half Marathon",
            "event_date": "2026-09-10",
            "distance_type": "semi",
            "target_time_minutes": 105  # 1h45 = 105 minutes
        })
        assert response.status_code == 200
        goal = response.json()["goal"]
        
        assert goal["distance_type"] == "semi"
        assert goal["distance_km"] == 21.1
        assert goal["target_time_minutes"] == 105
        # 105min / 21.1km = 4.976 min/km = 4:58/km
        assert goal["target_pace"] is not None
        # Pace should be around 4:58 or 4:59
        pace_parts = goal["target_pace"].split(":")
        assert int(pace_parts[0]) == 4
        assert 55 <= int(pace_parts[1]) <= 59
    
    def test_create_goal_marathon(self):
        """Test creating marathon goal with target time"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Marathon de Paris",
            "event_date": "2026-04-05",
            "distance_type": "marathon",
            "target_time_minutes": 225  # 3h45 = 225 minutes
        })
        assert response.status_code == 200
        goal = response.json()["goal"]
        
        assert goal["distance_type"] == "marathon"
        assert goal["distance_km"] == 42.195
        assert goal["target_time_minutes"] == 225
        # 225min / 42.195km = 5.33 min/km = 5:19/km
        assert goal["target_pace"] is not None
        pace_parts = goal["target_pace"].split(":")
        assert int(pace_parts[0]) == 5
        assert 18 <= int(pace_parts[1]) <= 21  # Allow small rounding variance
    
    def test_create_goal_ultra(self):
        """Test creating ultra marathon goal"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Ultra Trail",
            "event_date": "2026-08-15",
            "distance_type": "ultra",
            "target_time_minutes": 360  # 6 hours
        })
        assert response.status_code == 200
        goal = response.json()["goal"]
        
        assert goal["distance_type"] == "ultra"
        assert goal["distance_km"] == 50.0
        assert goal["target_time_minutes"] == 360
        # 360min / 50km = 7.2 min/km = 7:12/km
        assert goal["target_pace"] is not None
        pace_parts = goal["target_pace"].split(":")
        assert int(pace_parts[0]) == 7
        assert 10 <= int(pace_parts[1]) <= 14
    
    def test_goal_without_target_time(self):
        """Test creating goal without target time - pace should be null"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Fun Run",
            "event_date": "2026-05-01",
            "distance_type": "10k",
            "target_time_minutes": None
        })
        assert response.status_code == 200
        goal = response.json()["goal"]
        
        assert goal["distance_type"] == "10k"
        assert goal["distance_km"] == 10.0
        assert goal["target_time_minutes"] is None
        assert goal["target_pace"] is None
    
    def test_goal_with_zero_target_time(self):
        """Test creating goal with zero target time - pace should be null"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Casual Race",
            "event_date": "2026-05-15",
            "distance_type": "5k"
            # No target_time_minutes field
        })
        assert response.status_code == 200
        goal = response.json()["goal"]
        
        assert goal["distance_type"] == "5k"
        assert goal["distance_km"] == 5.0
        assert goal["target_pace"] is None
    
    def test_get_goal_returns_all_fields(self):
        """Test GET goal returns all enhanced fields"""
        # Create goal first
        requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Complete Goal",
            "event_date": "2026-10-01",
            "distance_type": "marathon",
            "target_time_minutes": 240  # 4 hours
        })
        
        # Get goal
        response = requests.get(f"{BASE_URL}/api/user/goal?user_id=default")
        assert response.status_code == 200
        goal = response.json()
        
        # Verify all fields present
        assert "id" in goal
        assert "user_id" in goal
        assert "event_name" in goal
        assert "event_date" in goal
        assert "distance_type" in goal
        assert "distance_km" in goal
        assert "target_time_minutes" in goal
        assert "target_pace" in goal
        assert "created_at" in goal
        
        # Verify values
        assert goal["event_name"] == "TEST_Complete Goal"
        assert goal["distance_type"] == "marathon"
        assert goal["distance_km"] == 42.195
        assert goal["target_time_minutes"] == 240
        # 240min / 42.195km = 5.69 min/km = 5:41/km
        assert goal["target_pace"] is not None
    
    def test_delete_goal(self):
        """Test deleting goal"""
        # Create goal
        requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_To Delete",
            "event_date": "2026-12-01",
            "distance_type": "5k"
        })
        
        # Delete
        response = requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
        assert response.status_code == 200
        assert response.json()["deleted"] == True
        
        # Verify deleted
        get_response = requests.get(f"{BASE_URL}/api/user/goal?user_id=default")
        assert get_response.status_code == 200
        assert get_response.json() is None


class TestGoalInDigest:
    """Test goal display in weekly digest/review"""
    
    @pytest.fixture(autouse=True)
    def setup_goal(self):
        """Set up a goal for digest tests"""
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
        requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Marathon Test",
            "event_date": "2026-06-01",
            "distance_type": "marathon",
            "target_time_minutes": 210  # 3h30 = 210 minutes
        })
        yield
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
    
    def test_digest_includes_goal_with_pace(self):
        """Test weekly digest includes goal with target_pace"""
        response = requests.get(f"{BASE_URL}/api/coach/digest?user_id=default&language=en")
        assert response.status_code == 200
        data = response.json()
        
        # Check user_goal is present
        assert "user_goal" in data
        user_goal = data["user_goal"]
        
        if user_goal:  # Goal should be present
            assert user_goal["event_name"] == "TEST_Marathon Test"
            assert user_goal["distance_type"] == "marathon"
            assert user_goal["distance_km"] == 42.195
            assert user_goal["target_time_minutes"] == 210
            # 210min / 42.195km = 4.98 min/km = 4:58/km
            assert user_goal["target_pace"] is not None
            pace_parts = user_goal["target_pace"].split(":")
            assert int(pace_parts[0]) == 4
            assert 55 <= int(pace_parts[1]) <= 59


class TestPaceCalculation:
    """Test pace calculation accuracy for different scenarios"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up goal before and after each test"""
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
        yield
        requests.delete(f"{BASE_URL}/api/user/goal?user_id=default")
    
    def test_pace_5k_in_25min(self):
        """5k in 25 minutes = 5:00/km"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Pace Test 1",
            "event_date": "2026-01-01",
            "distance_type": "5k",
            "target_time_minutes": 25
        })
        goal = response.json()["goal"]
        assert goal["target_pace"] == "5:00"
    
    def test_pace_10k_in_45min(self):
        """10k in 45 minutes = 4:30/km"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Pace Test 2",
            "event_date": "2026-01-01",
            "distance_type": "10k",
            "target_time_minutes": 45
        })
        goal = response.json()["goal"]
        assert goal["target_pace"] == "4:30"
    
    def test_pace_marathon_in_3h45(self):
        """Marathon in 3h45 (225min) = ~5:19/km"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Pace Test 3",
            "event_date": "2026-01-01",
            "distance_type": "marathon",
            "target_time_minutes": 225
        })
        goal = response.json()["goal"]
        # 225 / 42.195 = 5.333... = 5:19 or 5:20
        pace_parts = goal["target_pace"].split(":")
        assert int(pace_parts[0]) == 5
        assert 19 <= int(pace_parts[1]) <= 20
    
    def test_pace_semi_in_1h30(self):
        """Semi-marathon in 1h30 (90min) = ~4:16/km"""
        response = requests.post(f"{BASE_URL}/api/user/goal?user_id=default", json={
            "event_name": "TEST_Pace Test 4",
            "event_date": "2026-01-01",
            "distance_type": "semi",
            "target_time_minutes": 90
        })
        goal = response.json()["goal"]
        # 90 / 21.1 = 4.265... = 4:15 or 4:16
        pace_parts = goal["target_pace"].split(":")
        assert int(pace_parts[0]) == 4
        assert 15 <= int(pace_parts[1]) <= 17


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
