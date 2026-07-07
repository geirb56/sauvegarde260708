#!/usr/bin/env python3
"""
Backend API Testing Script for CardioCoach
Tests all endpoints after mock removal to ensure no 500 errors and proper graceful degradation.
"""

import requests
import sys
import json
from typing import Dict, List, Optional

# Backend URL from frontend/.env
BASE_URL = "https://charge-load.preview.emergentagent.com/api"

# Test results tracking
test_results = []
failed_tests = []
critical_issues = []


def log_test(test_name: str, passed: bool, message: str, critical: bool = False):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    result = {
        "test": test_name,
        "passed": passed,
        "message": message,
        "critical": critical
    }
    test_results.append(result)
    
    if not passed:
        failed_tests.append(result)
        if critical:
            critical_issues.append(result)
    
    print(f"{status}: {test_name}")
    print(f"   {message}")
    print()


def test_1_workouts_default_user():
    """Test 1: GET /api/workouts?user_id=default → 200, ~30 workouts, ALL data_source=='garmin', NO 'mock' in id"""
    test_name = "Test 1: GET /api/workouts?user_id=default"
    
    try:
        response = requests.get(f"{BASE_URL}/workouts", params={"user_id": "default"}, timeout=10)
        
        if response.status_code != 200:
            log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            return None
        
        workouts = response.json()
        
        if not isinstance(workouts, list):
            log_test(test_name, False, f"Expected list, got {type(workouts)}", critical=True)
            return None
        
        # Check count
        count = len(workouts)
        if count < 25 or count > 35:
            log_test(test_name, False, f"Expected ~30 workouts, got {count}", critical=False)
        
        # Check all have data_source='garmin'
        non_garmin = [w for w in workouts if w.get("data_source") != "garmin"]
        if non_garmin:
            log_test(test_name, False, f"Found {len(non_garmin)} workouts with data_source != 'garmin'", critical=True)
            return workouts
        
        # Check NO 'mock' in any id
        mock_ids = [w for w in workouts if "mock" in w.get("id", "").lower()]
        if mock_ids:
            log_test(test_name, False, f"Found {len(mock_ids)} workouts with 'mock' in id: {[w['id'] for w in mock_ids[:3]]}", critical=True)
            return workouts
        
        log_test(test_name, True, f"Returned {count} workouts, all with data_source='garmin', NO mock ids found", critical=False)
        return workouts
        
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)
        return None


def test_2_workouts_nonexistent_user():
    """Test 2: GET /api/workouts?user_id=nonexistent_user_xyz999 → 200 with empty list []"""
    test_name = "Test 2: GET /api/workouts?user_id=nonexistent_user_xyz999"
    
    try:
        response = requests.get(f"{BASE_URL}/workouts", params={"user_id": "nonexistent_user_xyz999"}, timeout=10)
        
        if response.status_code != 200:
            log_test(test_name, False, f"Expected 200, got {response.status_code} (should return empty list, not error)", critical=True)
            return
        
        workouts = response.json()
        
        if not isinstance(workouts, list):
            log_test(test_name, False, f"Expected list, got {type(workouts)}", critical=True)
            return
        
        if len(workouts) != 0:
            log_test(test_name, False, f"Expected empty list [], got {len(workouts)} workouts (should not return mock data)", critical=True)
            return
        
        log_test(test_name, True, "Returned empty list [] (graceful degradation, no 500, no mock)", critical=False)
        
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_3_workout_by_id(real_workout_id: Optional[str]):
    """Test 3: GET /api/workouts/{real_id} → 200; GET /api/workouts/bogus-id-123 → 404"""
    
    # Test 3a: Real workout ID
    if real_workout_id:
        test_name = "Test 3a: GET /api/workouts/{real_garmin_id}"
        try:
            response = requests.get(f"{BASE_URL}/workouts/{real_workout_id}", params={"user_id": "default"}, timeout=10)
            
            if response.status_code != 200:
                log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            else:
                workout = response.json()
                if workout.get("id") != real_workout_id:
                    log_test(test_name, False, f"Expected id={real_workout_id}, got {workout.get('id')}", critical=True)
                else:
                    log_test(test_name, True, f"Returned workout with id={real_workout_id}", critical=False)
        except Exception as e:
            log_test(test_name, False, f"Exception: {str(e)}", critical=True)
    
    # Test 3b: Bogus workout ID
    test_name = "Test 3b: GET /api/workouts/bogus-id-123"
    try:
        response = requests.get(f"{BASE_URL}/workouts/bogus-id-123", params={"user_id": "default"}, timeout=10)
        
        if response.status_code == 404:
            log_test(test_name, True, "Returned 404 (not mock, not 500)", critical=False)
        elif response.status_code == 200:
            workout = response.json()
            if "mock" in workout.get("id", "").lower():
                log_test(test_name, False, "Returned 200 with mock data (should return 404)", critical=True)
            else:
                log_test(test_name, False, "Returned 200 (should return 404)", critical=True)
        else:
            log_test(test_name, False, f"Expected 404, got {response.status_code}", critical=True)
            
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_4_coach_digest():
    """Test 4: GET /api/coach/digest?user_id=default&language=en → 200 with valid weekly review"""
    test_name = "Test 4: GET /api/coach/digest?user_id=default&language=en"
    
    try:
        response = requests.get(f"{BASE_URL}/coach/digest", params={"user_id": "default", "language": "en"}, timeout=15)
        
        if response.status_code != 200:
            log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            return
        
        digest = response.json()
        
        # Check for required fields in weekly review
        if not isinstance(digest, dict):
            log_test(test_name, False, f"Expected dict, got {type(digest)}", critical=True)
            return
        
        # Check for key fields (structure may vary, but should have some content)
        has_content = any(key in digest for key in ["summary", "advice", "metrics", "message", "review"])
        
        if not has_content:
            log_test(test_name, False, f"Response missing expected fields. Keys: {list(digest.keys())}", critical=True)
            return
        
        log_test(test_name, True, f"Returned valid weekly review with keys: {list(digest.keys())[:5]}", critical=False)
        
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_5_coach_guidance():
    """Test 5: POST /api/coach/guidance with JSON {"user_id":"default","language":"en"} → 200"""
    test_name = "Test 5: POST /api/coach/guidance"
    
    try:
        response = requests.post(
            f"{BASE_URL}/coach/guidance",
            json={"user_id": "default", "language": "en"},
            timeout=15
        )
        
        if response.status_code != 200:
            log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            return
        
        guidance = response.json()
        
        if not isinstance(guidance, dict):
            log_test(test_name, False, f"Expected dict, got {type(guidance)}", critical=True)
            return
        
        # Check for guidance content
        has_guidance = any(key in guidance for key in ["guidance", "status", "message", "advice"])
        
        if not has_guidance:
            log_test(test_name, False, f"Response missing expected fields. Keys: {list(guidance.keys())}", critical=True)
            return
        
        log_test(test_name, True, f"Returned valid guidance with keys: {list(guidance.keys())}", critical=False)
        
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_6_workout_analysis(real_workout_id: Optional[str]):
    """Test 6: GET /api/coach/workout-analysis/{garmin_id}?language=en → 200; bogus id → 404"""
    
    # Test 6a: Real workout ID
    if real_workout_id:
        test_name = "Test 6a: GET /api/coach/workout-analysis/{real_garmin_id}"
        try:
            response = requests.get(f"{BASE_URL}/coach/workout-analysis/{real_workout_id}", params={"language": "en"}, timeout=15)
            
            if response.status_code != 200:
                log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            else:
                analysis = response.json()
                if not isinstance(analysis, dict):
                    log_test(test_name, False, f"Expected dict, got {type(analysis)}", critical=True)
                else:
                    log_test(test_name, True, f"Returned workout analysis with keys: {list(analysis.keys())[:5]}", critical=False)
        except Exception as e:
            log_test(test_name, False, f"Exception: {str(e)}", critical=True)
    
    # Test 6b: Bogus workout ID
    test_name = "Test 6b: GET /api/coach/workout-analysis/bogus-id-456"
    try:
        response = requests.get(f"{BASE_URL}/coach/workout-analysis/bogus-id-456", params={"language": "en"}, timeout=15)
        
        if response.status_code == 404:
            log_test(test_name, True, "Returned 404 (not mock, not 500)", critical=False)
        elif response.status_code == 200:
            log_test(test_name, False, "Returned 200 (should return 404 for bogus id)", critical=True)
        else:
            log_test(test_name, False, f"Expected 404, got {response.status_code}", critical=True)
            
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_7_detailed_analysis(real_workout_id: Optional[str]):
    """Test 7: GET /api/coach/detailed-analysis/{garmin_id}?language=en → 200; bogus id → 404"""
    
    # Test 7a: Real workout ID
    if real_workout_id:
        test_name = "Test 7a: GET /api/coach/detailed-analysis/{real_garmin_id}"
        try:
            response = requests.get(f"{BASE_URL}/coach/detailed-analysis/{real_workout_id}", params={"language": "en"}, timeout=15)
            
            if response.status_code != 200:
                log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            else:
                analysis = response.json()
                if not isinstance(analysis, dict):
                    log_test(test_name, False, f"Expected dict, got {type(analysis)}", critical=True)
                else:
                    log_test(test_name, True, f"Returned detailed analysis with keys: {list(analysis.keys())[:5]}", critical=False)
        except Exception as e:
            log_test(test_name, False, f"Exception: {str(e)}", critical=True)
    
    # Test 7b: Bogus workout ID
    test_name = "Test 7b: GET /api/coach/detailed-analysis/bogus-id-789"
    try:
        response = requests.get(f"{BASE_URL}/coach/detailed-analysis/bogus-id-789", params={"language": "en"}, timeout=15)
        
        if response.status_code == 404:
            log_test(test_name, True, "Returned 404 (not mock, not 500)", critical=False)
        elif response.status_code == 200:
            log_test(test_name, False, "Returned 200 (should return 404 for bogus id)", critical=True)
        else:
            log_test(test_name, False, f"Expected 404, got {response.status_code}", critical=True)
            
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_8_cardio_coach():
    """Test 8: GET /api/cardio-coach?user_id=default → mock:false, source=='garmin'"""
    test_name = "Test 8: GET /api/cardio-coach?user_id=default"
    
    try:
        response = requests.get(f"{BASE_URL}/cardio-coach", params={"user_id": "default"}, timeout=10)
        
        if response.status_code != 200:
            log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            return
        
        cardio_coach = response.json()
        
        if not isinstance(cardio_coach, dict):
            log_test(test_name, False, f"Expected dict, got {type(cardio_coach)}", critical=True)
            return
        
        # Check mock field
        mock_value = cardio_coach.get("mock")
        if mock_value is True:
            log_test(test_name, False, f"mock=true (should be false, using real Garmin data)", critical=True)
            return
        
        # Check source field
        source_value = cardio_coach.get("source")
        if source_value != "garmin":
            log_test(test_name, False, f"source='{source_value}' (should be 'garmin')", critical=True)
            return
        
        log_test(test_name, True, f"mock={mock_value}, source='{source_value}' (using real Garmin data)", critical=False)
        
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_9_dashboard():
    """Test 9: GET /api/dashboard?user_id=default → 200"""
    test_name = "Test 9: GET /api/dashboard?user_id=default"
    
    try:
        response = requests.get(f"{BASE_URL}/dashboard", params={"user_id": "default"}, timeout=10)
        
        if response.status_code != 200:
            log_test(test_name, False, f"Expected 200, got {response.status_code}", critical=True)
            return
        
        dashboard = response.json()
        
        if not isinstance(dashboard, dict):
            log_test(test_name, False, f"Expected dict, got {type(dashboard)}", critical=True)
            return
        
        log_test(test_name, True, f"Returned dashboard with keys: {list(dashboard.keys())}", critical=False)
        
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def test_10_mock_runner_removed():
    """Test 10: GET /api/mock-runner → 404; GET /api/mock-runner/vma-history → 404"""
    
    # Test 10a: /api/mock-runner
    test_name = "Test 10a: GET /api/mock-runner"
    try:
        response = requests.get(f"{BASE_URL}/mock-runner", timeout=10)
        
        if response.status_code == 404:
            log_test(test_name, True, "Returned 404 (endpoint removed as expected)", critical=False)
        else:
            log_test(test_name, False, f"Expected 404, got {response.status_code} (endpoint should be removed)", critical=True)
            
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)
    
    # Test 10b: /api/mock-runner/vma-history
    test_name = "Test 10b: GET /api/mock-runner/vma-history"
    try:
        response = requests.get(f"{BASE_URL}/mock-runner/vma-history", timeout=10)
        
        if response.status_code == 404:
            log_test(test_name, True, "Returned 404 (endpoint removed as expected)", critical=False)
        else:
            log_test(test_name, False, f"Expected 404, got {response.status_code} (endpoint should be removed)", critical=True)
            
    except Exception as e:
        log_test(test_name, False, f"Exception: {str(e)}", critical=True)


def main():
    """Run all tests"""
    print("=" * 80)
    print("CardioCoach Backend Testing - Mock Removal Verification")
    print("=" * 80)
    print()
    
    # Test 1: Get workouts for default user (and extract a real workout ID)
    workouts = test_1_workouts_default_user()
    real_workout_id = None
    if workouts and len(workouts) > 0:
        # Get first workout with id starting with 'garmin-'
        for w in workouts:
            if w.get("id", "").startswith("garmin-"):
                real_workout_id = w["id"]
                break
    
    # Test 2: Nonexistent user
    test_2_workouts_nonexistent_user()
    
    # Test 3: Workout by ID
    test_3_workout_by_id(real_workout_id)
    
    # Test 4: Coach digest
    test_4_coach_digest()
    
    # Test 5: Coach guidance
    test_5_coach_guidance()
    
    # Test 6: Workout analysis
    test_6_workout_analysis(real_workout_id)
    
    # Test 7: Detailed analysis
    test_7_detailed_analysis(real_workout_id)
    
    # Test 8: Cardio coach
    test_8_cardio_coach()
    
    # Test 9: Dashboard
    test_9_dashboard()
    
    # Test 10: Mock runner removed
    test_10_mock_runner_removed()
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()
    
    total_tests = len(test_results)
    passed_tests = len([t for t in test_results if t["passed"]])
    failed_count = len(failed_tests)
    critical_count = len(critical_issues)
    
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {failed_count}")
    print(f"Critical Issues: {critical_count}")
    print()
    
    if critical_issues:
        print("CRITICAL ISSUES:")
        print("-" * 80)
        for issue in critical_issues:
            print(f"❌ {issue['test']}")
            print(f"   {issue['message']}")
            print()
    
    if failed_tests and not critical_issues:
        print("FAILED TESTS (Non-Critical):")
        print("-" * 80)
        for test in failed_tests:
            print(f"⚠️  {test['test']}")
            print(f"   {test['message']}")
            print()
    
    if passed_tests == total_tests:
        print("✅ ALL TESTS PASSED!")
        print()
        print("VERIFICATION COMPLETE:")
        print("- No 500 errors due to removed mock")
        print("- Empty-data cases degrade gracefully (empty list or 404)")
        print("- No mock data returned anywhere")
        print("- All endpoints working with real Garmin data")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print()
        print("Please review the failed tests above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
