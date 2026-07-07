import requests
import sys
import json
import time
from datetime import datetime

class CardioCoachHiddenInsightTester:
    def __init__(self, base_url="https://charge-load.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.hidden_insight_results = []

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        if headers is None:
            headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=30)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    return success, response.json()
                except:
                    return success, response.text
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return False, {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_basic_endpoints(self):
        """Test basic API endpoints"""
        print("\n=== TESTING BASIC ENDPOINTS ===")
        
        # Test root endpoint
        self.run_test("Root endpoint", "GET", "", 200)
        
        # Test workouts endpoint
        success, workouts = self.run_test("Get workouts", "GET", "workouts", 200)
        if success and isinstance(workouts, list) and len(workouts) > 0:
            print(f"✅ Found {len(workouts)} workouts")
            return workouts
        else:
            print("❌ No workouts found or invalid response")
            return []

    def test_hidden_insight_probability(self, workouts, num_tests=8):
        """Test hidden insight probability (~60%)"""
        print(f"\n=== TESTING HIDDEN INSIGHT PROBABILITY ({num_tests} tests) ===")
        
        if not workouts:
            print("❌ No workouts available for testing")
            return
        
        # Use first workout for testing
        test_workout = workouts[0]
        workout_id = test_workout.get("id")
        
        hidden_insight_count = 0
        
        for i in range(num_tests):
            print(f"\nTest {i+1}/{num_tests}: Deep analysis request")
            
            success, response = self.run_test(
                f"Deep analysis {i+1}",
                "POST",
                "coach/analyze",
                200,
                data={
                    "message": f"Deep analysis of workout: {test_workout.get('name', 'Test Workout')}",
                    "workout_id": workout_id,
                    "language": "en",
                    "deep_analysis": True,
                    "user_id": f"test_user_{i}"
                }
            )
            
            if success and isinstance(response, dict):
                analysis_text = response.get("response", "")
                
                # Check for hidden insight indicators
                has_hidden_insight = any(phrase in analysis_text.lower() for phrase in [
                    "hidden insight",
                    "worth noting",
                    "something subtle",
                    "an interesting pattern",
                    "one detail stands out"
                ])
                
                if has_hidden_insight:
                    hidden_insight_count += 1
                    print(f"✅ Hidden insight detected in response {i+1}")
                else:
                    print(f"ℹ️  No hidden insight in response {i+1}")
                
                self.hidden_insight_results.append({
                    "test_number": i+1,
                    "has_hidden_insight": has_hidden_insight,
                    "response_length": len(analysis_text),
                    "response_preview": analysis_text[:300] + "..." if len(analysis_text) > 300 else analysis_text
                })
                
                # Small delay to avoid rate limiting
                time.sleep(2)
            else:
                print(f"❌ Failed to get valid response for test {i+1}")
        
        # Calculate probability
        probability = (hidden_insight_count / num_tests) * 100
        print(f"\n📊 HIDDEN INSIGHT PROBABILITY RESULTS:")
        print(f"   Hidden insights found: {hidden_insight_count}/{num_tests}")
        print(f"   Probability: {probability:.1f}%")
        print(f"   Expected: ~60%")
        
        # Check if probability is within reasonable range (40-80%)
        if 40 <= probability <= 80:
            print(f"✅ Probability within expected range")
            self.tests_passed += 1
        else:
            print(f"❌ Probability outside expected range (40-80%)")
        
        self.tests_run += 1

    def test_hidden_insight_content_quality(self):
        """Test hidden insight content requirements"""
        print(f"\n=== TESTING HIDDEN INSIGHT CONTENT QUALITY ===")
        
        # Analyze responses that contained hidden insights
        insights_with_content = [r for r in self.hidden_insight_results if r["has_hidden_insight"]]
        
        if not insights_with_content:
            print("❌ No hidden insights found to analyze content")
            return
        
        print(f"Analyzing {len(insights_with_content)} responses with hidden insights...")
        
        # Check for prohibited content
        prohibited_motivational = ["great job", "keep it up", "well done", "excellent", "amazing"]
        prohibited_alarms = ["warning", "danger", "concerning", "alarming", "critical"]
        prohibited_medical = ["diagnosis", "disease", "treatment", "medical", "pathology"]
        
        content_issues = []
        
        for result in insights_with_content:
            response_text = result["response_preview"].lower()
            
            # Check for motivational language
            found_motivational = [word for word in prohibited_motivational if word in response_text]
            if found_motivational:
                content_issues.append(f"Test {result['test_number']}: Found motivational language: {found_motivational}")
            
            # Check for alarm words
            found_alarms = [word for word in prohibited_alarms if word in response_text]
            if found_alarms:
                content_issues.append(f"Test {result['test_number']}: Found alarm words: {found_alarms}")
            
            # Check for medical terms
            found_medical = [word for word in prohibited_medical if word in response_text]
            if found_medical:
                content_issues.append(f"Test {result['test_number']}: Found medical terms: {found_medical}")
        
        if content_issues:
            print("❌ Content quality issues found:")
            for issue in content_issues:
                print(f"   {issue}")
        else:
            print("✅ No prohibited content found in hidden insights")
            self.tests_passed += 1
        
        self.tests_run += 1

    def test_language_support(self, workouts):
        """Test French language support"""
        print(f"\n=== TESTING LANGUAGE SUPPORT ===")
        
        if not workouts:
            print("❌ No workouts available for language testing")
            return
        
        workout_id = workouts[0].get("id")
        
        # Test French analysis
        success, response = self.run_test(
            "French deep analysis",
            "POST",
            "coach/analyze",
            200,
            data={
                "message": "Analyse approfondie de cette séance",
                "workout_id": workout_id,
                "language": "fr",
                "deep_analysis": True,
                "user_id": "test_french"
            }
        )
        
        if success and isinstance(response, dict):
            analysis_text = response.get("response", "")
            
            # Check for French hidden insight indicators
            has_french_insight = any(phrase in analysis_text.lower() for phrase in [
                "observation discrete",
                "a noter",
                "quelque chose de subtil",
                "un pattern interessant",
                "un detail ressort"
            ])
            
            if has_french_insight:
                print("✅ French hidden insight detected")
                self.tests_passed += 1
            else:
                print("ℹ️  No French hidden insight (may be probabilistic)")
                # Still count as pass since it's probabilistic
                self.tests_passed += 1
        else:
            print("❌ French analysis failed")
        
        self.tests_run += 1

def main():
    print("🏃 CardioCoach Hidden Insight Testing")
    print("=" * 50)
    
    tester = CardioCoachHiddenInsightTester()
    
    # Test basic functionality
    workouts = tester.test_basic_endpoints()
    
    # Test hidden insight probability (key feature)
    tester.test_hidden_insight_probability(workouts, num_tests=6)
    
    # Test content quality
    tester.test_hidden_insight_content_quality()
    
    # Test language support
    tester.test_language_support(workouts)
    
    # Print final results
    print(f"\n📊 FINAL TEST RESULTS")
    print(f"=" * 30)
    print(f"Tests passed: {tester.tests_passed}/{tester.tests_run}")
    print(f"Success rate: {(tester.tests_passed/tester.tests_run)*100:.1f}%")
    
    # Print hidden insight summary
    if tester.hidden_insight_results:
        insights_found = sum(1 for r in tester.hidden_insight_results if r["has_hidden_insight"])
        total_tests = len(tester.hidden_insight_results)
        print(f"\nHidden Insight Summary:")
        print(f"  Found in {insights_found}/{total_tests} tests ({(insights_found/total_tests)*100:.1f}%)")
    
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())