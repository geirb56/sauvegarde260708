#!/usr/bin/env python3
"""
PHASE 2 Backend Test Suite for CardioCoach Garmin Connector
Tests new daily metrics sync, workout mirroring, and enhanced cleanup.
Provider: MockProvider (no real Garmin credentials needed)
"""

import requests
import json
import sys
from typing import Dict, Any

# Backend URL from frontend/.env
BASE_URL = "https://charge-load.preview.emergentagent.com/api"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def log_test(name: str):
    print(f"\n{Colors.BLUE}{'='*80}{Colors.RESET}")
    print(f"{Colors.BLUE}TEST: {name}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*80}{Colors.RESET}")

def log_success(msg: str):
    print(f"{Colors.GREEN}✓ {msg}{Colors.RESET}")

def log_error(msg: str):
    print(f"{Colors.RED}✗ {msg}{Colors.RESET}")

def log_info(msg: str):
    print(f"{Colors.YELLOW}ℹ {msg}{Colors.RESET}")

def pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2)

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def add_pass(self):
        self.passed += 1
    
    def add_fail(self, error: str):
        self.failed += 1
        self.errors.append(error)
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{Colors.BLUE}{'='*80}{Colors.RESET}")
        print(f"{Colors.BLUE}TEST SUMMARY{Colors.RESET}")
        print(f"{Colors.BLUE}{'='*80}{Colors.RESET}")
        print(f"Total: {total} | Passed: {Colors.GREEN}{self.passed}{Colors.RESET} | Failed: {Colors.RED}{self.failed}{Colors.RESET}")
        
        if self.errors:
            print(f"\n{Colors.RED}FAILED TESTS:{Colors.RESET}")
            for i, error in enumerate(self.errors, 1):
                print(f"{i}. {error}")
        
        return self.failed == 0

results = TestResults()

# ============================================================================
# PHASE 2 TESTS
# ============================================================================

def test_phase2_sync_with_metrics():
    """Test A: Sync now returns both synced_count AND metrics_count"""
    log_test("PHASE 2-A: POST /api/garmin/sync returns synced_count AND metrics_count")
    
    user_id = "p2test"
    connect_url = f"{BASE_URL}/garmin/connect?user_id={user_id}"
    sync_url = f"{BASE_URL}/garmin/sync?user_id={user_id}"
    
    try:
        # First connect
        log_info("Connecting user...")
        connect_resp = requests.post(connect_url, json={}, timeout=10)
        if connect_resp.status_code != 200:
            log_error(f"Connect failed with status {connect_resp.status_code}")
            results.add_fail(f"PHASE 2-A: Connect failed")
            return False
        
        connect_data = connect_resp.json()
        if connect_data.get("status") != "connected":
            log_error(f"Expected status 'connected', got '{connect_data.get('status')}'")
            results.add_fail(f"PHASE 2-A: Connect status not 'connected'")
            return False
        
        log_success("Connected successfully")
        
        # Now sync
        log_info("Syncing activities and metrics...")
        sync_resp = requests.post(sync_url, timeout=10)
        log_info(f"Status Code: {sync_resp.status_code}")
        log_info(f"Response: {pretty_json(sync_resp.json())}")
        
        if sync_resp.status_code != 200:
            log_error(f"Expected status 200, got {sync_resp.status_code}")
            results.add_fail(f"PHASE 2-A: Sync failed with status {sync_resp.status_code}")
            return False
        
        data = sync_resp.json()
        
        # Verify success
        if not data.get("success"):
            log_error(f"Expected success=true, got {data.get('success')}")
            results.add_fail(f"PHASE 2-A: Sync success=false")
            return False
        
        # Verify synced_count > 0
        synced_count = data.get("synced_count", 0)
        if synced_count <= 0:
            log_error(f"Expected synced_count > 0, got {synced_count}")
            results.add_fail(f"PHASE 2-A: synced_count not > 0")
            return False
        
        # Verify metrics_count == 7
        metrics_count = data.get("metrics_count", 0)
        if metrics_count != 7:
            log_error(f"Expected metrics_count == 7, got {metrics_count}")
            results.add_fail(f"PHASE 2-A: metrics_count != 7 (got {metrics_count})")
            return False
        
        log_success(f"Sync succeeded: synced_count={synced_count}, metrics_count={metrics_count}")
        log_success("✓ Both synced_count > 0 AND metrics_count == 7")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"PHASE 2-A: Exception - {str(e)}")
        return False


def test_phase2_daily_metrics_endpoint():
    """Test B: GET /api/garmin/daily-metrics returns proper structure"""
    log_test("PHASE 2-B: GET /api/garmin/daily-metrics?user_id=p2test&days=7")
    
    user_id = "p2test"
    url = f"{BASE_URL}/garmin/daily-metrics?user_id={user_id}&days=7"
    
    try:
        response = requests.get(url, timeout=10)
        log_info(f"Status Code: {response.status_code}")
        log_info(f"Response: {pretty_json(response.json())}")
        
        if response.status_code != 200:
            log_error(f"Expected status 200, got {response.status_code}")
            results.add_fail(f"PHASE 2-B: Status {response.status_code}")
            return False
        
        data = response.json()
        
        # Verify structure: {metrics: [...], latest: {...}, count: N}
        if "metrics" not in data:
            log_error("Missing 'metrics' field")
            results.add_fail(f"PHASE 2-B: Missing 'metrics' field")
            return False
        
        if "latest" not in data:
            log_error("Missing 'latest' field")
            results.add_fail(f"PHASE 2-B: Missing 'latest' field")
            return False
        
        if "count" not in data:
            log_error("Missing 'count' field")
            results.add_fail(f"PHASE 2-B: Missing 'count' field")
            return False
        
        metrics = data["metrics"]
        latest = data["latest"]
        count = data["count"]
        
        # Verify count == 7
        if count != 7:
            log_error(f"Expected count == 7, got {count}")
            results.add_fail(f"PHASE 2-B: count != 7 (got {count})")
            return False
        
        # Verify metrics list has 7 items
        if len(metrics) != 7:
            log_error(f"Expected 7 metrics items, got {len(metrics)}")
            results.add_fail(f"PHASE 2-B: len(metrics) != 7")
            return False
        
        # Verify latest is not null
        if latest is None:
            log_error("Expected latest to be non-null")
            results.add_fail(f"PHASE 2-B: latest is null")
            return False
        
        # Verify each metric has required fields
        required_fields = ["date", "hrv", "resting_hr", "sleep_hours", "sleep_score", "source"]
        for i, metric in enumerate(metrics):
            missing = [f for f in required_fields if f not in metric]
            if missing:
                log_error(f"Metric {i} missing fields: {missing}")
                results.add_fail(f"PHASE 2-B: Metric {i} missing {missing}")
                return False
            
            # Verify source == "garmin"
            if metric.get("source") != "garmin":
                log_error(f"Metric {i} source != 'garmin' (got '{metric.get('source')}')")
                results.add_fail(f"PHASE 2-B: Metric {i} source != 'garmin'")
                return False
        
        log_success(f"Retrieved {count} daily metrics")
        log_success(f"Latest metric: date={latest.get('date')}, hrv={latest.get('hrv')}, resting_hr={latest.get('resting_hr')}, sleep_hours={latest.get('sleep_hours')}, sleep_score={latest.get('sleep_score')}")
        log_success("All metrics have required fields (date, hrv, resting_hr, sleep_hours, sleep_score, source='garmin') ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"PHASE 2-B: Exception - {str(e)}")
        return False


def test_phase2_workouts_mirroring():
    """Test C: Activities mirrored into /api/workouts with data_source='garmin'"""
    log_test("PHASE 2-C: GET /api/workouts?user_id=p2test shows garmin activities")
    
    user_id = "p2test"
    url = f"{BASE_URL}/workouts?user_id={user_id}"
    
    try:
        response = requests.get(url, timeout=10)
        log_info(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            log_error(f"Expected status 200, got {response.status_code}")
            results.add_fail(f"PHASE 2-C: Status {response.status_code}")
            return False
        
        workouts = response.json()
        log_info(f"Retrieved {len(workouts)} workouts")
        
        # Filter garmin workouts
        garmin_workouts = [w for w in workouts if w.get("data_source") == "garmin"]
        
        if len(garmin_workouts) == 0:
            log_error("No workouts with data_source='garmin' found")
            results.add_fail(f"PHASE 2-C: No garmin workouts found")
            return False
        
        log_info(f"Found {len(garmin_workouts)} garmin workouts")
        
        # Verify each garmin workout has required fields
        required_fields = ["id", "type", "name", "date", "duration_minutes", "distance_km", "avg_heart_rate", "avg_pace_min_km"]
        valid_types = ["run", "cycle", "swim"]
        
        for i, workout in enumerate(garmin_workouts):
            # Verify id starts with "garmin-"
            workout_id = workout.get("id", "")
            if not workout_id.startswith("garmin-"):
                log_error(f"Workout {i} id doesn't start with 'garmin-': {workout_id}")
                results.add_fail(f"PHASE 2-C: Workout {i} id doesn't start with 'garmin-'")
                return False
            
            # Verify required fields
            missing = [f for f in required_fields if f not in workout]
            if missing:
                log_error(f"Workout {i} missing fields: {missing}")
                results.add_fail(f"PHASE 2-C: Workout {i} missing {missing}")
                return False
            
            # Verify type is valid
            workout_type = workout.get("type")
            if workout_type not in valid_types:
                log_error(f"Workout {i} type '{workout_type}' not in {valid_types}")
                results.add_fail(f"PHASE 2-C: Workout {i} invalid type")
                return False
            
            # Verify name is non-empty
            if not workout.get("name"):
                log_error(f"Workout {i} has empty name")
                results.add_fail(f"PHASE 2-C: Workout {i} empty name")
                return False
            
            # Verify duration_minutes is int
            duration = workout.get("duration_minutes")
            if not isinstance(duration, int):
                log_error(f"Workout {i} duration_minutes not int: {type(duration)}")
                results.add_fail(f"PHASE 2-C: Workout {i} duration not int")
                return False
            
            # Verify distance_km > 0
            distance = workout.get("distance_km")
            if not isinstance(distance, (int, float)) or distance <= 0:
                log_error(f"Workout {i} distance_km not > 0: {distance}")
                results.add_fail(f"PHASE 2-C: Workout {i} distance not > 0")
                return False
        
        # Show sample workout
        sample = garmin_workouts[0]
        log_success(f"Found {len(garmin_workouts)} garmin workouts")
        log_success(f"Sample: id={sample.get('id')}, type={sample.get('type')}, name={sample.get('name')}, duration={sample.get('duration_minutes')}min, distance={sample.get('distance_km')}km, HR={sample.get('avg_heart_rate')}, pace={sample.get('avg_pace_min_km')}min/km")
        log_success("All garmin workouts have valid structure ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"PHASE 2-C: Exception - {str(e)}")
        return False


def test_phase2_idempotency():
    """Test D: Sync twice - no duplicate workouts or metrics"""
    log_test("PHASE 2-D: Idempotency - sync twice for same user")
    
    user_id = "p2test"
    sync_url = f"{BASE_URL}/garmin/sync?user_id={user_id}"
    workouts_url = f"{BASE_URL}/workouts?user_id={user_id}"
    metrics_url = f"{BASE_URL}/garmin/daily-metrics?user_id={user_id}&days=7"
    
    try:
        # Get initial counts
        log_info("Getting initial counts...")
        workouts_resp1 = requests.get(workouts_url, timeout=10)
        metrics_resp1 = requests.get(metrics_url, timeout=10)
        
        if workouts_resp1.status_code != 200 or metrics_resp1.status_code != 200:
            log_error("Failed to get initial counts")
            results.add_fail(f"PHASE 2-D: Failed to get initial counts")
            return False
        
        workouts1 = workouts_resp1.json()
        metrics1 = metrics_resp1.json()
        
        garmin_workouts_count1 = len([w for w in workouts1 if w.get("data_source") == "garmin"])
        metrics_count1 = metrics1.get("count", 0)
        
        log_success(f"Initial: {garmin_workouts_count1} garmin workouts, {metrics_count1} metrics")
        
        # Sync again
        log_info("Syncing again...")
        sync_resp = requests.post(sync_url, timeout=10)
        if sync_resp.status_code != 200:
            log_error(f"Sync failed with status {sync_resp.status_code}")
            results.add_fail(f"PHASE 2-D: Sync failed")
            return False
        
        sync_data = sync_resp.json()
        log_info(f"Sync response: {pretty_json(sync_data)}")
        
        # Get counts after second sync
        log_info("Getting counts after second sync...")
        workouts_resp2 = requests.get(workouts_url, timeout=10)
        metrics_resp2 = requests.get(metrics_url, timeout=10)
        
        if workouts_resp2.status_code != 200 or metrics_resp2.status_code != 200:
            log_error("Failed to get counts after sync")
            results.add_fail(f"PHASE 2-D: Failed to get counts after sync")
            return False
        
        workouts2 = workouts_resp2.json()
        metrics2 = metrics_resp2.json()
        
        garmin_workouts_count2 = len([w for w in workouts2 if w.get("data_source") == "garmin"])
        metrics_count2 = metrics2.get("count", 0)
        
        log_success(f"After sync: {garmin_workouts_count2} garmin workouts, {metrics_count2} metrics")
        
        # Verify counts are stable
        if garmin_workouts_count1 != garmin_workouts_count2:
            log_error(f"Garmin workouts count changed: {garmin_workouts_count1} -> {garmin_workouts_count2}")
            results.add_fail(f"PHASE 2-D: Garmin workouts duplicated")
            return False
        
        if metrics_count1 != metrics_count2:
            log_error(f"Metrics count changed: {metrics_count1} -> {metrics_count2}")
            results.add_fail(f"PHASE 2-D: Metrics duplicated")
            return False
        
        log_success(f"Garmin workouts count stable: {garmin_workouts_count1} == {garmin_workouts_count2} ✓")
        log_success(f"Metrics count stable: {metrics_count1} == {metrics_count2} ✓")
        log_success("No duplicates created ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"PHASE 2-D: Exception - {str(e)}")
        return False


def test_phase2_disconnect_cleanup():
    """Test E: Disconnect removes garmin metrics AND garmin workouts only"""
    log_test("PHASE 2-E: Disconnect cleanup - removes garmin data only")
    
    user_id = "p2test"
    disconnect_url = f"{BASE_URL}/garmin/disconnect?user_id={user_id}"
    metrics_url = f"{BASE_URL}/garmin/daily-metrics?user_id={user_id}&days=7"
    workouts_url = f"{BASE_URL}/workouts?user_id={user_id}"
    
    try:
        # Disconnect
        log_info("Disconnecting...")
        disconnect_resp = requests.post(disconnect_url, timeout=10)
        log_info(f"Status Code: {disconnect_resp.status_code}")
        log_info(f"Response: {pretty_json(disconnect_resp.json())}")
        
        if disconnect_resp.status_code != 200:
            log_error(f"Expected status 200, got {disconnect_resp.status_code}")
            results.add_fail(f"PHASE 2-E: Disconnect failed")
            return False
        
        data = disconnect_resp.json()
        if not data.get("success"):
            log_error(f"Expected success=true, got {data.get('success')}")
            results.add_fail(f"PHASE 2-E: Disconnect success=false")
            return False
        
        log_success("Disconnect succeeded")
        
        # Verify daily-metrics count == 0
        log_info("Checking daily-metrics after disconnect...")
        metrics_resp = requests.get(metrics_url, timeout=10)
        if metrics_resp.status_code != 200:
            log_error(f"Metrics endpoint failed with status {metrics_resp.status_code}")
            results.add_fail(f"PHASE 2-E: Metrics endpoint failed")
            return False
        
        metrics_data = metrics_resp.json()
        log_info(f"Metrics response: {pretty_json(metrics_data)}")
        
        metrics_count = metrics_data.get("count", -1)
        if metrics_count != 0:
            log_error(f"Expected metrics count == 0, got {metrics_count}")
            results.add_fail(f"PHASE 2-E: Metrics not cleaned up (count={metrics_count})")
            return False
        
        log_success("Daily metrics cleaned up (count == 0) ✓")
        
        # Verify no garmin workouts remain
        log_info("Checking workouts after disconnect...")
        workouts_resp = requests.get(workouts_url, timeout=10)
        if workouts_resp.status_code != 200:
            log_error(f"Workouts endpoint failed with status {workouts_resp.status_code}")
            results.add_fail(f"PHASE 2-E: Workouts endpoint failed")
            return False
        
        workouts = workouts_resp.json()
        garmin_workouts = [w for w in workouts if w.get("data_source") == "garmin"]
        
        if len(garmin_workouts) > 0:
            log_error(f"Found {len(garmin_workouts)} garmin workouts after disconnect (should be 0)")
            results.add_fail(f"PHASE 2-E: Garmin workouts not cleaned up")
            return False
        
        log_success("Garmin workouts cleaned up (0 remaining) ✓")
        log_success("Disconnect cleanup complete ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"PHASE 2-E: Exception - {str(e)}")
        return False


def test_phase2_empty_metrics():
    """Test F: daily-metrics for user that never synced returns empty data"""
    log_test("PHASE 2-F: GET /api/garmin/daily-metrics for never-synced user")
    
    user_id = "neversynced_xyz_12345"
    url = f"{BASE_URL}/garmin/daily-metrics?user_id={user_id}&days=7"
    
    try:
        response = requests.get(url, timeout=10)
        log_info(f"Status Code: {response.status_code}")
        log_info(f"Response: {pretty_json(response.json())}")
        
        # Must be 200, not 500
        if response.status_code != 200:
            log_error(f"Expected status 200, got {response.status_code}")
            results.add_fail(f"PHASE 2-F: Status {response.status_code} (expected 200)")
            return False
        
        data = response.json()
        
        # Verify structure
        if "metrics" not in data or "latest" not in data or "count" not in data:
            log_error("Missing required fields in response")
            results.add_fail(f"PHASE 2-F: Missing fields")
            return False
        
        # Verify empty data
        if data["metrics"] != []:
            log_error(f"Expected metrics == [], got {data['metrics']}")
            results.add_fail(f"PHASE 2-F: metrics not empty")
            return False
        
        if data["latest"] is not None:
            log_error(f"Expected latest == null, got {data['latest']}")
            results.add_fail(f"PHASE 2-F: latest not null")
            return False
        
        if data["count"] != 0:
            log_error(f"Expected count == 0, got {data['count']}")
            results.add_fail(f"PHASE 2-F: count not 0")
            return False
        
        log_success("HTTP 200 (no 500 error) ✓")
        log_success("Response: {metrics: [], latest: null, count: 0} ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"PHASE 2-F: Exception - {str(e)}")
        return False


# ============================================================================
# REGRESSION TESTS (PHASE 1 features must still work)
# ============================================================================

def test_regression_connect():
    """Regression: Connect without password"""
    log_test("REGRESSION: POST /api/garmin/connect (no password required)")
    
    user_id = "regression_user_1"
    url = f"{BASE_URL}/garmin/connect?user_id={user_id}"
    
    try:
        response = requests.post(url, json={}, timeout=10)
        log_info(f"Status Code: {response.status_code}")
        log_info(f"Response: {pretty_json(response.json())}")
        
        if response.status_code != 200:
            log_error(f"Expected status 200, got {response.status_code}")
            results.add_fail(f"REGRESSION-Connect: Status {response.status_code}")
            return False
        
        data = response.json()
        
        if data.get("status") != "connected":
            log_error(f"Expected status 'connected', got '{data.get('status')}'")
            results.add_fail(f"REGRESSION-Connect: Status not 'connected'")
            return False
        
        log_success("Connect works without password ✓")
        log_success(f"Status: {data['status']}, Provider: {data.get('provider')}")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"REGRESSION-Connect: Exception - {str(e)}")
        return False


def test_regression_status():
    """Regression: Status endpoint"""
    log_test("REGRESSION: GET /api/garmin/status")
    
    user_id = "regression_user_1"
    url = f"{BASE_URL}/garmin/status?user_id={user_id}"
    
    try:
        response = requests.get(url, timeout=10)
        log_info(f"Status Code: {response.status_code}")
        log_info(f"Response: {pretty_json(response.json())}")
        
        if response.status_code != 200:
            log_error(f"Expected status 200, got {response.status_code}")
            results.add_fail(f"REGRESSION-Status: Status {response.status_code}")
            return False
        
        data = response.json()
        
        # Should have connected, provider, last_sync, activity_count
        required = ["connected", "provider", "last_sync", "activity_count"]
        missing = [f for f in required if f not in data]
        if missing:
            log_error(f"Missing fields: {missing}")
            results.add_fail(f"REGRESSION-Status: Missing {missing}")
            return False
        
        log_success("Status endpoint works ✓")
        log_success(f"Connected: {data['connected']}, Provider: {data['provider']}")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"REGRESSION-Status: Exception - {str(e)}")
        return False


def test_regression_mfa():
    """Regression: MFA Mode 2 simulation"""
    log_test("REGRESSION: MFA Mode 2 simulation")
    
    user_id = "mfa_p2"
    url = f"{BASE_URL}/garmin/connect?user_id={user_id}"
    
    try:
        # First call with simulate_mfa=true
        log_info("First call with simulate_mfa=true...")
        resp1 = requests.post(url, json={"simulate_mfa": True}, timeout=10)
        log_info(f"Response 1: {pretty_json(resp1.json())}")
        
        if resp1.status_code != 200:
            log_error(f"Expected status 200, got {resp1.status_code}")
            results.add_fail(f"REGRESSION-MFA: First call status {resp1.status_code}")
            return False
        
        data1 = resp1.json()
        if data1.get("status") != "mfa_required":
            log_error(f"Expected status 'mfa_required', got '{data1.get('status')}'")
            results.add_fail(f"REGRESSION-MFA: First call not 'mfa_required'")
            return False
        
        log_success("First call returned 'mfa_required' ✓")
        
        # Retry
        log_info("Retrying...")
        resp2 = requests.post(url, json={"simulate_mfa": True}, timeout=10)
        log_info(f"Response 2: {pretty_json(resp2.json())}")
        
        if resp2.status_code != 200:
            log_error(f"Expected status 200, got {resp2.status_code}")
            results.add_fail(f"REGRESSION-MFA: Retry status {resp2.status_code}")
            return False
        
        data2 = resp2.json()
        if data2.get("status") != "connected":
            log_error(f"Expected status 'connected', got '{data2.get('status')}'")
            results.add_fail(f"REGRESSION-MFA: Retry not 'connected'")
            return False
        
        log_success("Retry returned 'connected' ✓")
        log_success("MFA Mode 2 working ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"REGRESSION-MFA: Exception - {str(e)}")
        return False


def test_regression_sync_before_connect():
    """Regression: Sync-before-connect guard"""
    log_test("REGRESSION: Sync-before-connect guard")
    
    user_id = "never_connected_xyz_999"
    url = f"{BASE_URL}/garmin/sync?user_id={user_id}"
    
    try:
        response = requests.post(url, timeout=10)
        log_info(f"Status Code: {response.status_code}")
        log_info(f"Response: {pretty_json(response.json())}")
        
        # Should be 200 with success=false
        if response.status_code != 200:
            log_error(f"Expected status 200, got {response.status_code}")
            results.add_fail(f"REGRESSION-SyncGuard: Status {response.status_code}")
            return False
        
        data = response.json()
        
        if data.get("success") != False:
            log_error(f"Expected success=false, got {data.get('success')}")
            results.add_fail(f"REGRESSION-SyncGuard: success not false")
            return False
        
        message = data.get("message", "")
        if "not connected" not in message.lower():
            log_error(f"Expected 'not connected' message, got '{message}'")
            results.add_fail(f"REGRESSION-SyncGuard: Wrong message")
            return False
        
        log_success("Sync-before-connect guard works ✓")
        log_success(f"Message: {message}")
        log_success("No 500 error ✓")
        
        results.add_pass()
        return True
        
    except Exception as e:
        log_error(f"Exception: {str(e)}")
        results.add_fail(f"REGRESSION-SyncGuard: Exception - {str(e)}")
        return False


def main():
    print(f"\n{Colors.BLUE}{'='*80}{Colors.RESET}")
    print(f"{Colors.BLUE}CardioCoach Garmin Connector - PHASE 2 Backend Test Suite{Colors.RESET}")
    print(f"{Colors.BLUE}Base URL: {BASE_URL}{Colors.RESET}")
    print(f"{Colors.BLUE}Provider: MockProvider (GARMIN_PROVIDER=mock){Colors.RESET}")
    print(f"{Colors.BLUE}{'='*80}{Colors.RESET}")
    
    print(f"\n{Colors.YELLOW}{'='*80}{Colors.RESET}")
    print(f"{Colors.YELLOW}PHASE 2 TESTS (New Features){Colors.RESET}")
    print(f"{Colors.YELLOW}{'='*80}{Colors.RESET}")
    
    # PHASE 2 tests
    test_phase2_sync_with_metrics()
    test_phase2_daily_metrics_endpoint()
    test_phase2_workouts_mirroring()
    test_phase2_idempotency()
    test_phase2_disconnect_cleanup()
    test_phase2_empty_metrics()
    
    print(f"\n{Colors.YELLOW}{'='*80}{Colors.RESET}")
    print(f"{Colors.YELLOW}REGRESSION TESTS (PHASE 1 Features){Colors.RESET}")
    print(f"{Colors.YELLOW}{'='*80}{Colors.RESET}")
    
    # Regression tests
    test_regression_connect()
    test_regression_status()
    test_regression_mfa()
    test_regression_sync_before_connect()
    
    # Print summary
    success = results.summary()
    
    if success:
        print(f"\n{Colors.GREEN}{'='*80}{Colors.RESET}")
        print(f"{Colors.GREEN}ALL TESTS PASSED ✓{Colors.RESET}")
        print(f"{Colors.GREEN}{'='*80}{Colors.RESET}")
        sys.exit(0)
    else:
        print(f"\n{Colors.RED}{'='*80}{Colors.RESET}")
        print(f"{Colors.RED}SOME TESTS FAILED ✗{Colors.RESET}")
        print(f"{Colors.RED}{'='*80}{Colors.RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()
