#!/usr/bin/env python3

import requests
import sys
import json
import time
from datetime import datetime

class GuidanceAPITester:
    def __init__(self, base_url="https://charge-load.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=45):
        """Run a single API test"""
        url = f"{self.base_url}/api/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=timeout)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    return True, response_data
                except:
                    return True, response.text
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
                self.failed_tests.append({
                    "test": name,
                    "endpoint": endpoint,
                    "expected": expected_status,
                    "actual": response.status_code,
                    "response": response.text[:200]
                })
                return False, {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            self.failed_tests.append({
                "test": name,
                "endpoint": endpoint,
                "error": str(e)
            })
            return False, {}

    def test_generate_guidance_english(self):
        """Test adaptive guidance generation in English"""
        success, response = self.run_test(
            "Generate Adaptive Guidance (EN)",
            "POST",
            "coach/guidance",
            200,
            data={"language": "en", "user_id": "default"},
            timeout=60  # Longer timeout for AI processing
        )
        
        if success:
            print(f"   Status: {response.get('status', 'N/A')}")
            print(f"   Guidance length: {len(response.get('guidance', ''))} chars")
            print(f"   Generated at: {response.get('generated_at', 'N/A')}")
            
            # Check status is valid
            valid_statuses = ["maintain", "adjust", "hold_steady"]
            status = response.get('status')
            if status in valid_statuses:
                print(f"   ✅ Valid status: {status}")
            else:
                print(f"   ❌ Invalid status: {status}")
                
            # Check guidance content
            guidance = response.get('guidance', '')
            if len(guidance) > 50:  # Should have substantial content
                print(f"   ✅ Guidance has substantial content")
                
                # Check for session suggestions (max 3)
                session_indicators = guidance.upper().count('SESSION')
                print(f"   Found {session_indicators} session indicators")
                
                # Check for rationale ("why now" or similar)
                rationale_keywords = ['why', 'because', 'helps', 'targets', 'focus', 'now']
                found_rationale = any(keyword in guidance.lower() for keyword in rationale_keywords)
                if found_rationale:
                    print(f"   ✅ Contains rationale for suggestions")
                else:
                    print(f"   ⚠️  May be missing rationale")
                    
                # Check tone (should be calm, technical, non-motivational)
                motivational_words = ['great', 'awesome', 'excellent', 'amazing', 'fantastic']
                found_motivational = any(word in guidance.lower() for word in motivational_words)
                if not found_motivational:
                    print(f"   ✅ Tone appears calm and non-motivational")
                else:
                    print(f"   ⚠️  May contain motivational language")
                    
                # Check for medical language (should be avoided)
                medical_words = ['diagnosis', 'treatment', 'medical', 'disease', 'pathology']
                found_medical = any(word in guidance.lower() for word in medical_words)
                if not found_medical:
                    print(f"   ✅ No medical language detected")
                else:
                    print(f"   ❌ Contains medical language: should be avoided")
                    
                print(f"   Preview: {guidance[:150]}...")
                    
            else:
                print(f"   ❌ Guidance content too short")
                
        return success, response

    def test_generate_guidance_french(self):
        """Test adaptive guidance generation in French"""
        success, response = self.run_test(
            "Generate Adaptive Guidance (FR)",
            "POST",
            "coach/guidance",
            200,
            data={"language": "fr", "user_id": "default"},
            timeout=60  # Longer timeout for AI processing
        )
        
        if success:
            print(f"   Status: {response.get('status', 'N/A')}")
            print(f"   Guidance length: {len(response.get('guidance', ''))} chars")
            
            # Check for French status terms
            guidance = response.get('guidance', '')
            french_status_terms = ['maintenir', 'ajuster', 'consolider']
            found_french = any(term in guidance.lower() for term in french_status_terms)
            if found_french:
                print(f"   ✅ Contains French status terms")
            else:
                print(f"   ⚠️  May not contain expected French terms")
                
            # Check for French session indicators
            french_session_terms = ['seance', 'entrainement', 'session']
            found_sessions = any(term in guidance.lower() for term in french_session_terms)
            if found_sessions:
                print(f"   ✅ Contains French session terminology")
            else:
                print(f"   ⚠️  May be missing French session terms")
                
            print(f"   Preview: {guidance[:150]}...")
                
        return success, response

    def test_get_latest_guidance(self):
        """Test retrieving latest guidance"""
        success, response = self.run_test(
            "Get Latest Guidance",
            "GET",
            "coach/guidance/latest?user_id=default",
            200
        )
        
        if success and response:
            print(f"   Status: {response.get('status', 'N/A')}")
            print(f"   Generated at: {response.get('generated_at', 'N/A')}")
            print(f"   User ID: {response.get('user_id', 'N/A')}")
            print(f"   Language: {response.get('language', 'N/A')}")
            
            # Check if training summary is included
            training_summary = response.get('training_summary')
            if training_summary:
                print(f"   ✅ Includes training summary")
                last_14d = training_summary.get('last_14d', {})
                print(f"   Last 14d sessions: {last_14d.get('count', 0)}")
                print(f"   Last 14d distance: {last_14d.get('total_km', 0)} km")
            else:
                print(f"   ⚠️  Missing training summary")
                
        elif success and not response:
            print(f"   ℹ️  No guidance found (empty response)")
        
        return success, response

    def test_guidance_status_detection(self):
        """Test that guidance status is properly detected from AI response"""
        success, response = self.run_test(
            "Status Detection Test",
            "GET",
            "coach/guidance/latest?user_id=default",
            200
        )
        
        if success and response:
            status = response.get('status')
            valid_statuses = ["maintain", "adjust", "hold_steady"]
            if status in valid_statuses:
                print(f"   ✅ Valid status detected: {status}")
            else:
                print(f"   ❌ Invalid status: {status}")
        else:
            print(f"   ⚠️  No guidance to test status detection")
        
        return success, response

def main():
    print("🎯 CardioCoach Adaptive Guidance Testing")
    print("=" * 50)
    
    tester = GuidanceAPITester()
    
    # Test guidance generation in English
    print("\n⚠️  Testing Guidance Generation (EN) (may take 30-60 seconds)...")
    tester.test_generate_guidance_english()
    
    # Test guidance generation in French
    print("\n⚠️  Testing Guidance Generation (FR) (may take 30-60 seconds)...")
    tester.test_generate_guidance_french()
    
    # Test getting latest guidance
    print("\n📋 Testing Latest Guidance Retrieval...")
    tester.test_get_latest_guidance()
    
    # Test status detection
    print("\n🔍 Testing Status Detection...")
    tester.test_guidance_status_detection()
    
    # Print summary
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tester.tests_passed}/{tester.tests_run} passed")
    
    if tester.failed_tests:
        print("\n❌ Failed Tests:")
        for failure in tester.failed_tests:
            error_msg = failure.get('error', f"Status {failure.get('actual')} != {failure.get('expected')}")
            print(f"   - {failure['test']}: {error_msg}")
    
    success_rate = (tester.tests_passed / tester.tests_run) * 100 if tester.tests_run > 0 else 0
    print(f"\n🎯 Success Rate: {success_rate:.1f}%")
    
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())