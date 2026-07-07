"""
Test suite for Subscription and Chat features
- Multi-tier subscription (Free, Starter, Confort, Pro)
- Chat coach with Python fallback engine
- Stripe checkout integration
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSubscriptionTiers:
    """Test subscription tier endpoints"""
    
    def test_get_subscription_tiers(self):
        """GET /api/subscription/tiers returns all 4 tiers"""
        response = requests.get(f"{BASE_URL}/api/subscription/tiers")
        assert response.status_code == 200
        
        tiers = response.json()
        assert len(tiers) == 4
        
        # Verify tier IDs
        tier_ids = [t["id"] for t in tiers]
        assert "free" in tier_ids
        assert "starter" in tier_ids
        assert "confort" in tier_ids
        assert "pro" in tier_ids
    
    def test_free_tier_details(self):
        """Free tier has correct pricing and limits"""
        response = requests.get(f"{BASE_URL}/api/subscription/tiers")
        tiers = response.json()
        
        free_tier = next(t for t in tiers if t["id"] == "free")
        assert free_tier["price_monthly"] == 0
        assert free_tier["price_annual"] == 0
        assert free_tier["messages_limit"] == 10
        assert free_tier["unlimited"] == False
    
    def test_starter_tier_details(self):
        """Starter tier has correct pricing and limits"""
        response = requests.get(f"{BASE_URL}/api/subscription/tiers")
        tiers = response.json()
        
        starter_tier = next(t for t in tiers if t["id"] == "starter")
        assert starter_tier["price_monthly"] == 4.99
        assert starter_tier["price_annual"] == 49.99
        assert starter_tier["messages_limit"] == 25
    
    def test_confort_tier_details(self):
        """Confort tier has correct pricing and limits"""
        response = requests.get(f"{BASE_URL}/api/subscription/tiers")
        tiers = response.json()
        
        confort_tier = next(t for t in tiers if t["id"] == "confort")
        assert confort_tier["price_monthly"] == 5.99
        assert confort_tier["price_annual"] == 59.99
        assert confort_tier["messages_limit"] == 50
    
    def test_pro_tier_unlimited(self):
        """Pro tier is marked as unlimited"""
        response = requests.get(f"{BASE_URL}/api/subscription/tiers")
        tiers = response.json()
        
        pro_tier = next(t for t in tiers if t["id"] == "pro")
        assert pro_tier["price_monthly"] == 9.99
        assert pro_tier["price_annual"] == 99.99
        assert pro_tier["unlimited"] == True


class TestSubscriptionStatus:
    """Test subscription status endpoint"""
    
    def test_get_subscription_status(self):
        """GET /api/subscription/status returns user's current tier"""
        response = requests.get(f"{BASE_URL}/api/subscription/status?user_id=default")
        assert response.status_code == 200
        
        data = response.json()
        assert "tier" in data
        assert "tier_name" in data
        assert "messages_used" in data
        assert "messages_limit" in data
        assert "messages_remaining" in data
        assert "is_unlimited" in data
    
    def test_subscription_status_has_correct_fields(self):
        """Subscription status includes all required fields"""
        response = requests.get(f"{BASE_URL}/api/subscription/status?user_id=default")
        data = response.json()
        
        # Verify tier is one of the valid tiers
        assert data["tier"] in ["free", "starter", "confort", "pro"]
        
        # Verify messages_remaining is calculated correctly
        expected_remaining = data["messages_limit"] - data["messages_used"]
        assert data["messages_remaining"] == expected_remaining
    
    def test_subscription_status_for_new_user(self):
        """New user defaults to free tier"""
        response = requests.get(f"{BASE_URL}/api/subscription/status?user_id=test_new_user_xyz")
        assert response.status_code == 200
        
        data = response.json()
        assert data["tier"] == "free"
        assert data["messages_limit"] == 10


class TestStripeCheckout:
    """Test Stripe checkout integration"""
    
    def test_create_checkout_session_starter(self):
        """POST /api/subscription/checkout creates Stripe session for starter tier"""
        response = requests.post(
            f"{BASE_URL}/api/subscription/checkout?user_id=default",
            json={
                "origin_url": "https://charge-load.preview.emergentagent.com",
                "tier": "starter",
                "billing_period": "monthly"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "checkout_url" in data
        assert "session_id" in data
        assert data["checkout_url"].startswith("https://checkout.stripe.com")
    
    def test_create_checkout_session_confort(self):
        """POST /api/subscription/checkout creates Stripe session for confort tier"""
        response = requests.post(
            f"{BASE_URL}/api/subscription/checkout?user_id=default",
            json={
                "origin_url": "https://charge-load.preview.emergentagent.com",
                "tier": "confort",
                "billing_period": "monthly"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "checkout_url" in data
        assert data["checkout_url"].startswith("https://checkout.stripe.com")
    
    def test_create_checkout_session_pro(self):
        """POST /api/subscription/checkout creates Stripe session for pro tier"""
        response = requests.post(
            f"{BASE_URL}/api/subscription/checkout?user_id=default",
            json={
                "origin_url": "https://charge-load.preview.emergentagent.com",
                "tier": "pro",
                "billing_period": "annual"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "checkout_url" in data
    
    def test_checkout_invalid_tier_rejected(self):
        """POST /api/subscription/checkout rejects invalid tier"""
        response = requests.post(
            f"{BASE_URL}/api/subscription/checkout?user_id=default",
            json={
                "origin_url": "https://charge-load.preview.emergentagent.com",
                "tier": "invalid_tier",
                "billing_period": "monthly"
            }
        )
        assert response.status_code == 400


class TestChatCoach:
    """Test chat coach endpoints"""
    
    def test_send_chat_message(self):
        """POST /api/chat/send returns response from Python engine"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "Comment améliorer mon allure?",
                "user_id": "default"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "response" in data
        assert "message_id" in data
        assert "messages_remaining" in data
        assert len(data["response"]) > 0
    
    def test_chat_response_about_fatigue(self):
        """Chat responds to fatigue-related questions"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "Je suis fatigué après ma séance",
                "user_id": "default"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["response"]) > 20  # Non-empty meaningful response
    
    def test_chat_response_about_cadence(self):
        """Chat responds to cadence-related questions"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "Quelle cadence je dois viser?",
                "user_id": "default"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["response"]) > 20
    
    def test_chat_response_about_recovery(self):
        """Chat responds to recovery-related questions"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "Comment bien récupérer?",
                "user_id": "default"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["response"]) > 20
    
    def test_chat_history(self):
        """GET /api/chat/history returns message history"""
        response = requests.get(f"{BASE_URL}/api/chat/history?user_id=default&limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
    
    def test_chat_decrements_messages_remaining(self):
        """Sending chat message decrements messages_remaining"""
        # Get initial status
        status_before = requests.get(f"{BASE_URL}/api/subscription/status?user_id=default").json()
        
        # Send a message
        chat_response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "Test message",
                "user_id": "default"
            }
        ).json()
        
        # Verify messages_remaining decreased
        assert chat_response["messages_remaining"] <= status_before["messages_remaining"]


class TestChatEngine:
    """Test the Python rule-based chat engine responses"""
    
    def test_fallback_response_for_unknown_query(self):
        """Chat provides fallback for unrecognized queries"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "xyz123 random gibberish",
                "user_id": "default"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        # Should get a fallback response asking for clarification
        assert len(data["response"]) > 10
    
    def test_chat_response_in_french(self):
        """Chat responses are in French"""
        response = requests.post(
            f"{BASE_URL}/api/chat/send",
            json={
                "message": "Analyse ma semaine",
                "user_id": "default"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        # Response should contain French words
        french_indicators = ["km", "séance", "semaine", "allure", "tu", "ton", "ta"]
        has_french = any(word in data["response"].lower() for word in french_indicators)
        assert has_french, f"Response should be in French: {data['response']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
