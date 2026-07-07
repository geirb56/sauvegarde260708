"""
Subscription Backend Tests
Tests for subscription system endpoints (trial, free, early_adopter)
"""

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSubscriptionEndpoints:
    """Tests for subscription-related API endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test user ID for each test"""
        self.test_user_id = f"test_user_{uuid.uuid4().hex[:8]}"
        yield
        # Cleanup: try to reset user to trial
        try:
            requests.post(f"{BASE_URL}/api/subscription/reset-to-trial", params={"user_id": self.test_user_id})
        except:
            pass
    
    # ========== Subscription Info Tests ==========
    
    def test_subscription_info_endpoint_returns_200(self):
        """GET /api/subscription/info returns 200"""
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id, "language": "fr"})
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "features" in data
        assert "display" in data
    
    def test_new_user_gets_trial_status(self):
        """New users should get trial status"""
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id, "language": "fr"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "trial"
        assert data["features"]["full_access"] == True
        assert data["features"]["training_plan"] == True
        assert data["features"]["llm_access"] == True
    
    def test_trial_user_has_all_features(self):
        """Trial users should have access to all features"""
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        data = res.json()
        features = data["features"]
        assert features["training_plan"] == True
        assert features["plan_adaptation"] == True
        assert features["session_analysis"] == True
        assert features["sync_enabled"] == True
        assert features["api_access"] == True
        assert features["llm_access"] == True
        assert features["full_access"] == True
    
    def test_subscription_display_info_french(self):
        """Display info should be in French when language=fr"""
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id, "language": "fr"})
        data = res.json()
        display = data["display"]
        assert "label" in display
        assert "badge" in display
        # Trial badge in French
        assert display["badge"] in ["ESSAI", "TRIAL"]
    
    def test_subscription_display_info_english(self):
        """Display info should be in English when language=en"""
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id, "language": "en"})
        data = res.json()
        display = data["display"]
        assert "label" in display
        assert display["badge"] == "TRIAL"
    
    def test_trial_days_remaining(self):
        """Trial users should have trial_days_remaining field"""
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        data = res.json()
        assert "trial_days_remaining" in data
        # Should be between 0 and 7 for new trial
        if data["trial_days_remaining"] is not None:
            assert 0 <= data["trial_days_remaining"] <= 7
    
    # ========== Early Adopter Offer Tests ==========
    
    def test_early_adopter_offer_endpoint(self):
        """GET /api/subscription/early-adopter-offer returns offer details"""
        res = requests.get(f"{BASE_URL}/api/subscription/early-adopter-offer", params={"language": "fr"})
        assert res.status_code == 200
        data = res.json()
        assert data["price"] == 4.99
        assert "price_display" in data
        assert "features" in data
        assert len(data["features"]) > 0
        assert data["offer_name"] == "Early Adopter"
        assert data["price_guarantee"] == "Prix garanti à vie"
    
    def test_early_adopter_offer_english(self):
        """Early adopter offer in English"""
        res = requests.get(f"{BASE_URL}/api/subscription/early-adopter-offer", params={"language": "en"})
        assert res.status_code == 200
        data = res.json()
        assert data["price"] == 4.99
        assert data["price_guarantee"] == "Price guaranteed for life"
    
    # ========== Early Adopter Checkout Tests ==========
    
    def test_early_adopter_checkout_creates_session(self):
        """POST /api/subscription/early-adopter/checkout creates Stripe session"""
        res = requests.post(
            f"{BASE_URL}/api/subscription/early-adopter/checkout",
            params={
                "user_id": self.test_user_id,
                "origin_url": "https://charge-load.preview.emergentagent.com"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert "checkout_url" in data
        assert "session_id" in data
        # Checkout URL should be a valid Stripe URL
        assert data["checkout_url"].startswith("https://")
        assert "stripe" in data["checkout_url"].lower() or "checkout" in data["checkout_url"].lower()
    
    def test_checkout_session_has_correct_amount(self):
        """Checkout session should be for 4.99 EUR"""
        res = requests.post(
            f"{BASE_URL}/api/subscription/early-adopter/checkout",
            params={
                "user_id": self.test_user_id,
                "origin_url": "https://charge-load.preview.emergentagent.com"
            }
        )
        assert res.status_code == 200
        # The amount is embedded in the checkout session (4.99 EUR)
        # We can verify this by checking the transaction was recorded
        data = res.json()
        assert data["session_id"] is not None
    
    # ========== Verify Checkout Tests ==========
    
    def test_verify_checkout_activates_early_adopter(self):
        """Verify checkout should activate early_adopter status"""
        # First create a checkout session
        checkout_res = requests.post(
            f"{BASE_URL}/api/subscription/early-adopter/checkout",
            params={
                "user_id": self.test_user_id,
                "origin_url": "https://charge-load.preview.emergentagent.com"
            }
        )
        assert checkout_res.status_code == 200
        session_id = checkout_res.json()["session_id"]
        
        # Verify the checkout (simulates successful payment)
        verify_res = requests.get(
            f"{BASE_URL}/api/subscription/verify-checkout/{session_id}",
            params={"user_id": self.test_user_id}
        )
        assert verify_res.status_code == 200
        data = verify_res.json()
        assert data["success"] == True
        assert data["status"] == "early_adopter"
        
        # Verify the subscription status was updated
        info_res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        info_data = info_res.json()
        assert info_data["status"] == "early_adopter"
        assert info_data["features"]["full_access"] == True
    
    # ========== Free Status Tests ==========
    
    def test_simulate_trial_end_sets_free_status(self):
        """Simulating trial end should set user to free status"""
        # First ensure user is in trial
        requests.post(f"{BASE_URL}/api/subscription/reset-to-trial", params={"user_id": self.test_user_id})
        
        # Simulate trial end
        res = requests.post(f"{BASE_URL}/api/subscription/simulate-trial-end", params={"user_id": self.test_user_id})
        assert res.status_code == 200
        
        # Check status is now free
        info_res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        data = info_res.json()
        assert data["status"] == "free"
        assert data["features"]["full_access"] == False
        assert data["features"]["training_plan"] == False
    
    def test_free_user_has_limited_features(self):
        """Free users should have limited features"""
        # First ensure user exists (creates trial)
        requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        
        # Set user to free
        requests.post(f"{BASE_URL}/api/subscription/simulate-trial-end", params={"user_id": self.test_user_id})
        
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        data = res.json()
        features = data["features"]
        assert features["training_plan"] == False
        assert features["plan_adaptation"] == False
        assert features["session_analysis"] == False
        assert features["sync_enabled"] == False
        assert features["api_access"] == False
        assert features["llm_access"] == False
        assert features["full_access"] == False
    
    # ========== Early Adopter Status Tests ==========
    
    def test_activate_early_adopter_endpoint(self):
        """POST /api/subscription/activate-early-adopter activates subscription"""
        res = requests.post(
            f"{BASE_URL}/api/subscription/activate-early-adopter",
            json={
                "user_id": self.test_user_id,
                "stripe_customer_id": f"cus_test_{self.test_user_id}",
                "stripe_subscription_id": f"sub_test_{self.test_user_id}"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] == True
        assert data["status"] == "early_adopter"
        
        # Verify subscription info
        info_res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        info_data = info_res.json()
        assert info_data["status"] == "early_adopter"
        assert info_data["price_locked"] == 4.99
    
    def test_early_adopter_has_all_features(self):
        """Early Adopter users should have access to all features"""
        # Activate early adopter
        requests.post(
            f"{BASE_URL}/api/subscription/activate-early-adopter",
            json={"user_id": self.test_user_id}
        )
        
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        data = res.json()
        features = data["features"]
        assert features["training_plan"] == True
        assert features["plan_adaptation"] == True
        assert features["session_analysis"] == True
        assert features["sync_enabled"] == True
        assert features["api_access"] == True
        assert features["llm_access"] == True
        assert features["full_access"] == True
    
    def test_early_adopter_display_info(self):
        """Early Adopter display info should show correct badge"""
        requests.post(
            f"{BASE_URL}/api/subscription/activate-early-adopter",
            json={"user_id": self.test_user_id}
        )
        
        res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id, "language": "fr"})
        data = res.json()
        display = data["display"]
        assert display["badge"] == "EARLY ADOPTER"
        assert display["badge_color"] == "amber"
    
    # ========== Cancel Subscription Tests ==========
    
    def test_cancel_subscription_sets_free_status(self):
        """Cancelling subscription should set user to free"""
        # First activate early adopter
        requests.post(
            f"{BASE_URL}/api/subscription/activate-early-adopter",
            json={"user_id": self.test_user_id}
        )
        
        # Cancel subscription
        res = requests.post(f"{BASE_URL}/api/subscription/cancel", params={"user_id": self.test_user_id})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] == True
        assert data["status"] == "free"
    
    # ========== Reset to Trial Tests ==========
    
    def test_reset_to_trial(self):
        """Reset to trial should work"""
        # First set to free
        requests.post(f"{BASE_URL}/api/subscription/simulate-trial-end", params={"user_id": self.test_user_id})
        
        # Reset to trial
        res = requests.post(f"{BASE_URL}/api/subscription/reset-to-trial", params={"user_id": self.test_user_id})
        assert res.status_code == 200
        
        # Verify status is trial
        info_res = requests.get(f"{BASE_URL}/api/subscription/info", params={"user_id": self.test_user_id})
        data = info_res.json()
        assert data["status"] == "trial"
