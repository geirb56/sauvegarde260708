#!/usr/bin/env python3
"""
Test CardioCoach Dashboard 'cardio-coach' block returns REAL Garmin-derived data.

Background: GET /api/cardio-coach now computes from real Garmin data (resting HR + sleep 
from gccli; training load/ACWR/fatigue computed from real activities) when the user's 
Garmin is connected. The 'default' user is connected with real data already synced.

Tests:
1. GET /api/cardio-coach?user_id=default → expect HTTP 200 and REAL Garmin data
2. Regression tests: VMA history, race predictions, workouts
3. Garmin connector health check
"""

import requests
import sys
from typing import Dict, Any

# External base URL from frontend/.env
BASE_URL = "https://charge-load.preview.emergentagent.com/api"
USER_ID = "default"

# Test results tracking
test_results = []
failed_tests = []


def log_test(test_num: str, description: str, passed: bool, details: str = ""):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    result = f"Test {test_num}: {status} - {description}"
    if details:
        result += f"\n  Details: {details}"
    print(result)
    test_results.append({"test": test_num, "description": description, "passed": passed, "details": details})
    if not passed:
        failed_tests.append({"test": test_num, "description": description, "details": details})


def test_1_cardio_coach_real_data():
    """Test 1: GET /api/cardio-coach?user_id=default returns REAL Garmin data"""
    print("\n" + "="*80)
    print("TEST 1: CardioCoach endpoint returns REAL Garmin data (not mock)")
    print("="*80)
    
    try:
        url = f"{BASE_URL}/cardio-coach?user_id={USER_ID}"
        response = requests.get(url, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            log_test("1", "CardioCoach endpoint HTTP 200", False, f"Expected 200, got {response.status_code}")
            return False
        
        data = response.json()
        print(f"Response keys: {list(data.keys())}")
        
        # CRITICAL: Verify mock == false
        if data.get("mock") != False:
            log_test("1a", "CardioCoach mock field", False, f"Expected mock=false, got mock={data.get('mock')}")
            return False
        else:
            log_test("1a", "CardioCoach mock field", True, "mock=false (not using static mock)")
        
        # CRITICAL: Verify source == "garmin"
        if data.get("source") != "garmin":
            log_test("1b", "CardioCoach source field", False, f"Expected source='garmin', got source='{data.get('source')}'")
            return False
        else:
            log_test("1b", "CardioCoach source field", True, "source='garmin' (using real Garmin data)")
        
        # Verify metrics object exists
        metrics = data.get("metrics")
        if not metrics:
            log_test("1c", "CardioCoach metrics object", False, "metrics object missing")
            return False
        
        print(f"Metrics: {metrics}")
        
        # Verify rhr_today is a real number (around 44-50)
        rhr_today = metrics.get("rhr_today")
        if not isinstance(rhr_today, (int, float)) or rhr_today <= 0:
            log_test("1d", "CardioCoach metrics.rhr_today", False, f"Expected real number > 0, got {rhr_today}")
            return False
        else:
            log_test("1d", "CardioCoach metrics.rhr_today", True, f"rhr_today={rhr_today} (real value)")
        
        # Verify sleep_hours is a real number (> 0)
        sleep_hours = metrics.get("sleep_hours")
        if not isinstance(sleep_hours, (int, float)) or sleep_hours <= 0:
            log_test("1e", "CardioCoach metrics.sleep_hours", False, f"Expected real number > 0, got {sleep_hours}")
            return False
        else:
            log_test("1e", "CardioCoach metrics.sleep_hours", True, f"sleep_hours={sleep_hours} (real value)")
        
        # Verify training_load (ACWR) is a number > 0
        training_load = metrics.get("training_load")
        if not isinstance(training_load, (int, float)) or training_load <= 0:
            log_test("1f", "CardioCoach metrics.training_load", False, f"Expected number > 0, got {training_load}")
            return False
        else:
            log_test("1f", "CardioCoach metrics.training_load", True, f"training_load={training_load} (ACWR computed from real activities)")
        
        # Verify fatigue_ratio is a number >= 0 (must NOT be negative)
        fatigue_ratio = metrics.get("fatigue_ratio")
        if not isinstance(fatigue_ratio, (int, float)) or fatigue_ratio < 0:
            log_test("1g", "CardioCoach metrics.fatigue_ratio", False, f"Expected number >= 0, got {fatigue_ratio}")
            return False
        else:
            log_test("1g", "CardioCoach metrics.fatigue_ratio", True, f"fatigue_ratio={fatigue_ratio} (>= 0, not negative)")
        
        # Verify hrv_available == false (this account's device has no HRV)
        hrv_available = metrics.get("hrv_available")
        if hrv_available != False:
            log_test("1h", "CardioCoach metrics.hrv_available", False, f"Expected hrv_available=false, got {hrv_available}")
            return False
        else:
            log_test("1h", "CardioCoach metrics.hrv_available", True, "hrv_available=false (expected for this device)")
        
        # Verify hrv_today, hrv_baseline, hrv_delta are null
        hrv_today = metrics.get("hrv_today")
        hrv_baseline = metrics.get("hrv_baseline")
        hrv_delta = metrics.get("hrv_delta")
        
        if hrv_today is not None:
            log_test("1i", "CardioCoach metrics.hrv_today", False, f"Expected null, got {hrv_today}")
            return False
        
        if hrv_baseline is not None:
            log_test("1i", "CardioCoach metrics.hrv_baseline", False, f"Expected null, got {hrv_baseline}")
            return False
        
        if hrv_delta is not None:
            log_test("1i", "CardioCoach metrics.hrv_delta", False, f"Expected null, got {hrv_delta}")
            return False
        
        log_test("1i", "CardioCoach HRV fields", True, "hrv_today, hrv_baseline, hrv_delta all null (expected)")
        
        # Verify history is an array of up to 7 items
        history = data.get("history")
        if not isinstance(history, list):
            log_test("1j", "CardioCoach history array", False, f"Expected array, got {type(history)}")
            return False
        
        if len(history) == 0 or len(history) > 7:
            log_test("1j", "CardioCoach history array", False, f"Expected 1-7 items, got {len(history)}")
            return False
        
        # Verify each history item has required fields
        first_history = history[0]
        if not all(k in first_history for k in ["day", "training_load", "fatigue_ratio"]):
            log_test("1j", "CardioCoach history array", False, f"Missing required fields in history item: {first_history}")
            return False
        
        log_test("1j", "CardioCoach history array", True, f"history has {len(history)} items with required fields")
        
        # Verify reasons is a non-empty array
        reasons = data.get("reasons")
        if not isinstance(reasons, list) or len(reasons) == 0:
            log_test("1k", "CardioCoach reasons array", False, f"Expected non-empty array, got {reasons}")
            return False
        
        # Verify reasons includes resting-HR reason and "HRV not recorded" reason
        reasons_text = " ".join(reasons).lower()
        
        has_rhr_reason = "rhr" in reasons_text or "resting" in reasons_text
        has_hrv_not_recorded = "hrv not recorded" in reasons_text or "hrv not available" in reasons_text
        
        if not has_rhr_reason:
            log_test("1k", "CardioCoach reasons (RHR)", False, f"Expected resting-HR reason, got: {reasons}")
            return False
        
        if not has_hrv_not_recorded:
            log_test("1k", "CardioCoach reasons (HRV not recorded)", False, f"Expected 'HRV not recorded' reason, got: {reasons}")
            return False
        
        log_test("1k", "CardioCoach reasons array", True, f"reasons includes RHR and 'HRV not recorded' ({len(reasons)} reasons total)")
        
        print("\n✅ TEST 1 PASSED: CardioCoach returns REAL Garmin data (not mock)")
        return True
        
    except Exception as e:
        log_test("1", "CardioCoach endpoint", False, f"Exception: {str(e)}")
        return False


def test_2_regression_vma_history():
    """Test 2: Regression - GET /api/training/vma-history with header X-User-Id: default"""
    print("\n" + "="*80)
    print("TEST 2: Regression - VMA history endpoint")
    print("="*80)
    
    try:
        url = f"{BASE_URL}/training/vma-history"
        headers = {"X-User-Id": USER_ID}
        response = requests.get(url, headers=headers, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            log_test("2", "VMA history endpoint", False, f"Expected 200, got {response.status_code}")
            return False
        
        data = response.json()
        print(f"Response: {data}")
        
        # Verify has_data == true
        has_data = data.get("has_data")
        if has_data != True:
            log_test("2", "VMA history has_data", False, f"Expected has_data=true, got {has_data}")
            return False
        
        log_test("2", "VMA history endpoint", True, "has_data=true (computed from real activities)")
        return True
        
    except Exception as e:
        log_test("2", "VMA history endpoint", False, f"Exception: {str(e)}")
        return False


def test_3_regression_race_predictions():
    """Test 3: Regression - GET /api/training/race-predictions with header X-User-Id: default"""
    print("\n" + "="*80)
    print("TEST 3: Regression - Race predictions endpoint")
    print("="*80)
    
    try:
        url = f"{BASE_URL}/training/race-predictions"
        headers = {"X-User-Id": USER_ID}
        response = requests.get(url, headers=headers, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            log_test("3", "Race predictions endpoint", False, f"Expected 200, got {response.status_code}")
            return False
        
        data = response.json()
        print(f"Response: {data}")
        
        # Verify has_data == true
        has_data = data.get("has_data")
        if has_data != True:
            log_test("3", "Race predictions has_data", False, f"Expected has_data=true, got {has_data}")
            return False
        
        log_test("3", "Race predictions endpoint", True, "has_data=true (computed from real activities)")
        return True
        
    except Exception as e:
        log_test("3", "Race predictions endpoint", False, f"Exception: {str(e)}")
        return False


def test_4_regression_workouts():
    """Test 4: Regression - GET /api/workouts?user_id=default returns real Garmin workouts"""
    print("\n" + "="*80)
    print("TEST 4: Regression - Workouts endpoint (NO mock ids)")
    print("="*80)
    
    try:
        url = f"{BASE_URL}/workouts?user_id={USER_ID}"
        response = requests.get(url, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            log_test("4", "Workouts endpoint", False, f"Expected 200, got {response.status_code}")
            return False
        
        workouts = response.json()
        print(f"Total workouts: {len(workouts)}")
        
        # Filter Garmin workouts
        garmin_workouts = [w for w in workouts if w.get("data_source") == "garmin"]
        print(f"Garmin workouts: {len(garmin_workouts)}")
        
        if len(garmin_workouts) == 0:
            log_test("4", "Workouts endpoint", False, "No data_source='garmin' workouts found")
            return False
        
        # CRITICAL: Verify NO ids containing "mock"
        mock_ids = [w.get("id") for w in garmin_workouts if "mock" in w.get("id", "").lower()]
        if mock_ids:
            log_test("4", "Workouts endpoint (NO mock ids)", False, f"Found mock ids: {mock_ids}")
            return False
        
        log_test("4", "Workouts endpoint", True, f"Found {len(garmin_workouts)} Garmin workouts (data_source='garmin', NO mock ids)")
        return True
        
    except Exception as e:
        log_test("4", "Workouts endpoint", False, f"Exception: {str(e)}")
        return False


def test_5_garmin_status():
    """Test 5: Garmin connector health - GET /api/garmin/status?user_id=default"""
    print("\n" + "="*80)
    print("TEST 5: Garmin connector health check")
    print("="*80)
    
    try:
        url = f"{BASE_URL}/garmin/status?user_id={USER_ID}"
        response = requests.get(url, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            log_test("5", "Garmin status endpoint", False, f"Expected 200, got {response.status_code}")
            return False
        
        data = response.json()
        print(f"Response: {data}")
        
        # Verify connected == true
        connected = data.get("connected")
        if connected != True:
            log_test("5a", "Garmin connected", False, f"Expected connected=true, got {connected}")
            return False
        else:
            log_test("5a", "Garmin connected", True, "connected=true")
        
        # Verify provider == "gccli"
        provider = data.get("provider")
        if provider != "gccli":
            log_test("5b", "Garmin provider", False, f"Expected provider='gccli', got {provider}")
            return False
        else:
            log_test("5b", "Garmin provider", True, "provider='gccli'")
        
        # Verify activity_count > 0
        activity_count = data.get("activity_count", 0)
        if activity_count <= 0:
            log_test("5c", "Garmin activity_count", False, f"Expected activity_count > 0, got {activity_count}")
            return False
        else:
            log_test("5c", "Garmin activity_count", True, f"activity_count={activity_count} (> 0)")
        
        print("\n✅ TEST 5 PASSED: Garmin connector healthy")
        return True
        
    except Exception as e:
        log_test("5", "Garmin status endpoint", False, f"Exception: {str(e)}")
        return False


def main():
    """Run all tests in order"""
    print("\n" + "="*80)
    print("CARDIOCOACH DASHBOARD - REAL GARMIN DATA TESTING")
    print("="*80)
    print(f"Base URL: {BASE_URL}")
    print(f"User ID: {USER_ID}")
    print("="*80)
    
    # Run tests in order
    test_1_cardio_coach_real_data()
    test_2_regression_vma_history()
    test_3_regression_race_predictions()
    test_4_regression_workouts()
    test_5_garmin_status()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed_count = sum(1 for r in test_results if r["passed"])
    total_count = len(test_results)
    
    print(f"Total Tests: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total_count - passed_count}")
    
    if failed_tests:
        print("\n" + "="*80)
        print("FAILED TESTS")
        print("="*80)
        for failed in failed_tests:
            print(f"Test {failed['test']}: {failed['description']}")
            print(f"  Details: {failed['details']}")
    
    print("\n" + "="*80)
    
    # Exit with appropriate code
    if failed_tests:
        sys.exit(1)
    else:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
