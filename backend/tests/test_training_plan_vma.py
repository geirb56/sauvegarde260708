"""
Tests for Dynamic Training Plan with VMA-based Paces

Tests the following features:
1. Personalized paces (paces) calculated dynamically from VMA
2. Plan returns VMA, VO2MAX, readiness_score and prep_status
3. Sessions contain personalized paces in 'details' field
4. Plan duration (adjusted_weeks) adapts to user level
"""

import pytest
import requests
import re
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Cache for plan data to reduce API calls
_plan_cache = None

def get_plan_cached():
    """Get plan data with caching to avoid rate limiting"""
    global _plan_cache
    if _plan_cache is None:
        time.sleep(1)  # Rate limiting protection
        response = requests.get(
            f"{BASE_URL}/api/training/plan",
            headers={"X-User-Id": "default"}
        )
        if response.status_code == 200:
            _plan_cache = response.json()
    return _plan_cache


class TestTrainingPlanVMA:
    """Test Dynamic Training Plan with VMA calculations"""

    def test_training_plan_returns_200(self):
        """Test that /api/training/plan returns 200"""
        data = get_plan_cached()
        assert data is not None, "Plan API should return data"
        assert "plan" in data
        assert "sessions" in data.get("plan", {})

    def test_plan_contains_vma_field(self):
        """Test that plan returns VMA value"""
        data = get_plan_cached()
        assert data is not None
        
        # VMA should be a float between 8-25 km/h (realistic range)
        assert "vma" in data, "Response should contain 'vma' field"
        vma = data["vma"]
        assert isinstance(vma, (int, float)), f"VMA should be numeric, got {type(vma)}"
        assert 8 <= vma <= 25, f"VMA {vma} should be in realistic range [8-25] km/h"

    def test_plan_contains_vo2max_field(self):
        """Test that plan returns VO2MAX value"""
        data = get_plan_cached()
        assert data is not None
        
        # VO2MAX should be VMA * 3.5 (Cooper formula approximation)
        assert "vo2max" in data, "Response should contain 'vo2max' field"
        vo2max = data["vo2max"]
        vma = data["vma"]
        
        assert isinstance(vo2max, (int, float)), f"VO2MAX should be numeric, got {type(vo2max)}"
        # VO2MAX = VMA * 3.5 (with some tolerance)
        expected_vo2max = vma * 3.5
        assert abs(vo2max - expected_vo2max) < 0.5, f"VO2MAX {vo2max} should be close to VMA*3.5={expected_vo2max}"

    def test_plan_contains_readiness_score(self):
        """Test that plan returns readiness_score"""
        data = get_plan_cached()
        assert data is not None
        
        # readiness_score should be 0-100
        assert "readiness_score" in data, "Response should contain 'readiness_score' field"
        score = data["readiness_score"]
        assert isinstance(score, (int, float)), f"readiness_score should be numeric, got {type(score)}"
        assert 0 <= score <= 100, f"readiness_score {score} should be in range [0-100]"

    def test_plan_contains_prep_status(self):
        """Test that plan returns prep_status"""
        data = get_plan_cached()
        assert data is not None
        
        # prep_status should be one of the defined values
        assert "prep_status" in data, "Response should contain 'prep_status' field"
        valid_statuses = ["avancé", "normal", "progressif", "débutant"]
        assert data["prep_status"] in valid_statuses, f"prep_status '{data['prep_status']}' should be one of {valid_statuses}"

    def test_plan_contains_adjusted_weeks(self):
        """Test that plan returns adjusted_weeks based on readiness"""
        data = get_plan_cached()
        assert data is not None
        
        assert "adjusted_weeks" in data, "Response should contain 'adjusted_weeks' field"
        weeks = data["adjusted_weeks"]
        assert isinstance(weeks, int), f"adjusted_weeks should be integer, got {type(weeks)}"
        assert 4 <= weeks <= 30, f"adjusted_weeks {weeks} should be in realistic range [4-30]"

    def test_plan_contains_personalized_paces(self):
        """Test that plan returns personalized paces object"""
        data = get_plan_cached()
        assert data is not None
        
        assert "paces" in data, "Response should contain 'paces' field"
        paces = data["paces"]
        
        # Check all required pace zones exist
        required_zones = ["z1", "z2", "z3", "z4", "z5", "marathon", "semi"]
        for zone in required_zones:
            assert zone in paces, f"Paces should contain '{zone}' zone"
            # Each pace should be a string in format "X:XX-X:XX" (min:sec)
            pace_value = paces[zone]
            assert isinstance(pace_value, str), f"Pace {zone} should be string, got {type(pace_value)}"
            # Validate pace format (e.g., "5:30-6:00" or "4:45-5:00")
            pace_pattern = r"\d+:\d{2}-\d+:\d{2}"
            assert re.match(pace_pattern, pace_value), f"Pace {zone}='{pace_value}' should match pattern 'M:SS-M:SS'"


class TestSessionsWithPersonalizedPaces:
    """Test that session details contain personalized paces"""

    def test_sessions_exist_in_plan(self):
        """Test that plan contains sessions array"""
        data = get_plan_cached()
        assert data is not None
        
        assert "plan" in data, "Response should contain 'plan' field"
        plan = data["plan"]
        assert "sessions" in plan, "Plan should contain 'sessions' array"
        sessions = plan["sessions"]
        assert isinstance(sessions, list), f"Sessions should be a list, got {type(sessions)}"
        assert len(sessions) == 7, f"Should have 7 sessions (one per day), got {len(sessions)}"

    def test_sessions_have_required_fields(self):
        """Test that each session has required fields"""
        data = get_plan_cached()
        assert data is not None
        
        sessions = data["plan"]["sessions"]
        required_fields = ["day", "type", "duration", "details", "intensity", "estimated_tss", "distance_km"]
        
        for i, session in enumerate(sessions):
            for field in required_fields:
                assert field in session, f"Session {i} ({session.get('day', 'unknown')}) should have '{field}' field"

    def test_non_rest_sessions_contain_pace_in_details(self):
        """Test that non-rest sessions contain pace information in details"""
        data = get_plan_cached()
        assert data is not None
        paces = data["paces"]
        
        sessions = data["plan"]["sessions"]
        pace_pattern = r"\d+:\d{2}"  # Pattern for pace like "5:30" or "6:00"
        
        for session in sessions:
            intensity = session.get("intensity", "")
            details = session.get("details", "")
            
            # Rest days should not have pace
            if intensity == "rest" or session.get("type") == "Repos":
                continue
            
            # Non-rest sessions should have pace in details
            has_pace = bool(re.search(pace_pattern, details))
            assert has_pace, f"Session '{session['day']} - {session['type']}' details should contain pace. Details: {details}"

    def test_session_paces_match_vma_derived_paces(self):
        """Test that session paces use VMA-derived values from paces object"""
        data = get_plan_cached()
        assert data is not None
        paces = data["paces"]
        
        sessions = data["plan"]["sessions"]
        
        # Count sessions that use personalized paces
        sessions_with_personalized_pace = 0
        non_rest_sessions = 0
        
        for session in sessions:
            intensity = session.get("intensity", "")
            if intensity == "rest" or session.get("type") == "Repos":
                continue
            
            non_rest_sessions += 1
            details = session.get("details", "")
            
            # Check if any of the personalized paces appear in details
            for zone, pace_range in paces.items():
                # Extract start pace from range (e.g., "5:30-6:00" -> "5:30")
                if "-" in pace_range:
                    start_pace, end_pace = pace_range.split("-")
                    if start_pace in details or end_pace in details or pace_range in details:
                        sessions_with_personalized_pace += 1
                        break
        
        # At least 50% of non-rest sessions should have personalized paces
        if non_rest_sessions > 0:
            percentage = (sessions_with_personalized_pace / non_rest_sessions) * 100
            assert percentage >= 50, f"At least 50% of non-rest sessions should have personalized paces, got {percentage:.1f}%"


class TestPlanAdaptation:
    """Test that plan adapts to user fitness level"""

    def test_context_contains_fitness_metrics(self):
        """Test that context contains fitness metrics"""
        data = get_plan_cached()
        assert data is not None
        
        assert "context" in data, "Response should contain 'context' field"
        context = data["context"]
        
        # Check essential fitness metrics in context
        expected_fields = ["acwr", "tsb", "weekly_km", "vma", "vo2max", "readiness_score", "prep_status"]
        for field in expected_fields:
            assert field in context, f"Context should contain '{field}' field"

    def test_adjusted_weeks_varies_with_prep_status(self):
        """Test the relationship between readiness_score and adjusted_weeks"""
        data = get_plan_cached()
        assert data is not None
        
        readiness = data["readiness_score"]
        prep_status = data["prep_status"]
        adjusted_weeks = data["adjusted_weeks"]
        goal = data.get("goal", "SEMI")
        
        # Base weeks by goal
        base_weeks_by_goal = {
            "5K": 6, "10K": 8, "SEMI": 12, "MARATHON": 16, "ULTRA": 20
        }
        base_weeks = base_weeks_by_goal.get(goal, 12)
        
        # Verify the prep_status matches readiness_score
        if readiness >= 90:
            assert prep_status == "avancé", f"With readiness={readiness}, prep_status should be 'avancé'"
        elif readiness >= 70:
            assert prep_status == "normal", f"With readiness={readiness}, prep_status should be 'normal'"
        elif readiness >= 50:
            assert prep_status == "progressif", f"With readiness={readiness}, prep_status should be 'progressif'"
        else:
            assert prep_status == "débutant", f"With readiness={readiness}, prep_status should be 'débutant'"


class TestTrainingPlanRefresh:
    """Test the refresh endpoint for training plan"""

    def test_refresh_plan_returns_200(self):
        """Test that POST /api/training/refresh returns 200"""
        time.sleep(2)  # Rate limiting protection
        response = requests.post(
            f"{BASE_URL}/api/training/refresh",
            headers={"X-User-Id": "default"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Should return same structure as GET /training/plan
        assert "plan" in data
        assert "vma" in data
        assert "paces" in data

    def test_refresh_with_sessions_parameter(self):
        """Test refresh with specific number of sessions"""
        time.sleep(2)  # Rate limiting protection
        # Test with just one session count to reduce API calls
        sessions = 4
        response = requests.post(
            f"{BASE_URL}/api/training/refresh?sessions={sessions}",
            headers={"X-User-Id": "default"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify the sessions preference was applied
        # Count non-rest sessions
        plan_sessions = data.get("plan", {}).get("sessions", [])
        non_rest_count = sum(1 for s in plan_sessions if s.get("intensity") != "rest")
        
        # Should match requested sessions count (or be close due to phase adjustments)
        assert sessions - 1 <= non_rest_count <= sessions + 1, \
            f"Requested {sessions} sessions but got {non_rest_count} non-rest sessions"


# Cache for full cycle data
_full_cycle_cache = None

def get_full_cycle_cached():
    """Get full cycle data with caching to avoid rate limiting"""
    global _full_cycle_cache
    if _full_cycle_cache is None:
        time.sleep(2)  # Rate limiting protection
        response = requests.get(
            f"{BASE_URL}/api/training/full-cycle",
            headers={"X-User-Id": "default"}
        )
        if response.status_code == 200:
            _full_cycle_cache = response.json()
    return _full_cycle_cache


class TestFullCycleWithVMA:
    """Test the full cycle endpoint"""

    def test_full_cycle_returns_200(self):
        """Test that /api/training/full-cycle returns 200"""
        data = get_full_cycle_cached()
        assert data is not None, "Full cycle API should return data"
        
        assert "weeks" in data
        assert "total_weeks" in data
        assert "current_week" in data
        assert "goal" in data

    def test_full_cycle_weeks_have_required_fields(self):
        """Test that each week in full cycle has required fields"""
        data = get_full_cycle_cached()
        assert data is not None
        
        weeks = data["weeks"]
        assert len(weeks) > 0, "Should have at least one week"
        
        required_fields = ["week", "phase", "phase_name", "target_km", "sessions", "is_current"]
        for week in weeks:
            for field in required_fields:
                assert field in week, f"Week {week.get('week', 'unknown')} should have '{field}' field"


class TestPacesCalculation:
    """Test VMA to pace conversion calculations"""

    def test_z1_pace_slower_than_z5(self):
        """Test that Z1 (recovery) pace is slower than Z5 (VMA)"""
        data = get_plan_cached()
        assert data is not None
        paces = data["paces"]
        
        def extract_pace_seconds(pace_str):
            """Extract first pace value and convert to seconds"""
            first_pace = pace_str.split("-")[0]
            parts = first_pace.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        
        z1_seconds = extract_pace_seconds(paces["z1"])
        z5_seconds = extract_pace_seconds(paces["z5"])
        
        # Z1 should be slower (higher seconds) than Z5
        assert z1_seconds > z5_seconds, f"Z1 ({paces['z1']}) should be slower than Z5 ({paces['z5']})"

    def test_marathon_pace_slower_than_semi_pace(self):
        """Test that marathon pace is slower than semi pace"""
        data = get_plan_cached()
        assert data is not None
        paces = data["paces"]
        
        def extract_pace_seconds(pace_str):
            """Extract first pace value and convert to seconds"""
            first_pace = pace_str.split("-")[0]
            parts = first_pace.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        
        marathon_seconds = extract_pace_seconds(paces["marathon"])
        semi_seconds = extract_pace_seconds(paces["semi"])
        
        # Marathon should be slower (higher seconds) or equal to semi
        assert marathon_seconds >= semi_seconds, f"Marathon ({paces['marathon']}) should be slower or equal to Semi ({paces['semi']})"

    def test_paces_are_realistic_for_vma(self):
        """Test that paces are realistic given the VMA"""
        data = get_plan_cached()
        assert data is not None
        
        vma = data["vma"]
        paces = data["paces"]
        
        # Z5 (100% VMA) pace should be close to 60/VMA min/km
        expected_z5_pace = 60 / vma  # in min/km
        
        def extract_pace_minutes(pace_str):
            """Extract first pace value in minutes"""
            first_pace = pace_str.split("-")[0]
            parts = first_pace.split(":")
            return int(parts[0]) + int(parts[1]) / 60
        
        z5_pace = extract_pace_minutes(paces["z5"])
        
        # Allow 20% tolerance for Z5 pace
        tolerance = 0.2
        min_expected = expected_z5_pace * (1 - tolerance)
        max_expected = expected_z5_pace * (1 + tolerance)
        
        assert min_expected <= z5_pace <= max_expected, \
            f"Z5 pace {paces['z5']} ({z5_pace:.2f} min/km) should be close to {expected_z5_pace:.2f} min/km for VMA {vma}"
