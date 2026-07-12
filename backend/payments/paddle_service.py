"""
Paddle Billing Service
======================

Handles Paddle Billing integration for RunIndex premium subscriptions.

Supported webhook events:
- transaction.completed
- subscription.created
- subscription.updated
- subscription.canceled
- subscription.paused
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Paddle API base URLs
PADDLE_API_URLS = {
    "sandbox": "https://sandbox-api.paddle.com",
    "production": "https://api.paddle.com",
}


class PaddleService:
    """Paddle Billing API client."""

    def __init__(
        self,
        api_key: str,
        webhook_secret: str,
        environment: str = "sandbox",
        price_id: str = "",
    ):
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.environment = environment
        self.price_id = price_id
        self.base_url = PADDLE_API_URLS.get(environment, PADDLE_API_URLS["sandbox"])

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    async def create_checkout(
        self,
        user_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a Paddle hosted-checkout transaction.

        Returns a dict with keys:
          - checkout_url: str
          - transaction_id: str
        """
        if not self.api_key or not self.price_id:
            raise ValueError("Paddle API key and price ID must be configured")

        payload: Dict[str, Any] = {
            "items": [{"price_id": self.price_id, "quantity": 1}],
            "checkout": {
                "url": success_url,
            },
            "custom_data": {
                "user_id": user_id,
                "product": "runindex_early_adopter",
                "plan": "early_adopter",
            },
        }

        if customer_email:
            payload["customer"] = {"email": customer_email}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/transactions",
                headers=self._auth_headers(),
                json=payload,
                timeout=30.0,
            )

        if response.status_code not in (200, 201):
            error_body = response.text
            logger.error(
                "Paddle create_checkout error %s: %s",
                response.status_code,
                error_body,
            )
            raise RuntimeError(
                f"Paddle API error {response.status_code}: {error_body}"
            )

        data = response.json().get("data", {})
        checkout_url = data.get("checkout", {}).get("url") or data.get("url", "")
        transaction_id = data.get("id", "")

        return {
            "checkout_url": checkout_url,
            "transaction_id": transaction_id,
        }

    # ------------------------------------------------------------------
    # Transaction / Subscription status
    # ------------------------------------------------------------------

    async def get_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """Retrieves a Paddle transaction by ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/transactions/{transaction_id}",
                headers=self._auth_headers(),
                timeout=30.0,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Paddle get_transaction error {response.status_code}: {response.text}"
            )

        return response.json().get("data", {})

    async def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Retrieves a Paddle subscription by ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/subscriptions/{subscription_id}",
                headers=self._auth_headers(),
                timeout=30.0,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Paddle get_subscription error {response.status_code}: {response.text}"
            )

        return response.json().get("data", {})

    async def cancel_subscription(self, subscription_id: str, effective_from: str = "next_billing_period") -> Dict[str, Any]:
        """Cancels a Paddle subscription."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/subscriptions/{subscription_id}/cancel",
                headers=self._auth_headers(),
                json={"effective_from": effective_from},
                timeout=30.0,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Paddle cancel_subscription error {response.status_code}: {response.text}"
            )

        return response.json().get("data", {})

    # ------------------------------------------------------------------
    # Webhook verification
    # ------------------------------------------------------------------

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        Verifies a Paddle webhook signature.

        Paddle sends:  Paddle-Signature: ts=<timestamp>;h1=<hmac_hex>
        The HMAC is computed over  "<timestamp>:<raw_body>"  using the
        webhook secret as the key (SHA-256).
        """
        if not self.webhook_secret:
            logger.warning("Paddle webhook secret not configured – skipping verification")
            return True

        try:
            parts = dict(item.split("=", 1) for item in signature_header.split(";"))
            ts = parts.get("ts", "")
            received_hash = parts.get("h1", "")
        except Exception:
            logger.error("Malformed Paddle-Signature header: %s", signature_header)
            return False

        signed_payload = f"{ts}:{raw_body.decode('utf-8')}".encode("utf-8")
        expected_hash = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_hash, received_hash)

    def parse_webhook_event(self, raw_body: bytes) -> Dict[str, Any]:
        """Parses a Paddle webhook event body."""
        return json.loads(raw_body)

    # ------------------------------------------------------------------
    # Event processing helpers
    # ------------------------------------------------------------------

    def extract_user_id_from_event(self, event: Dict[str, Any]) -> str:
        """Extracts the user_id stored in custom_data of the event."""
        data = event.get("data", {})
        custom_data = data.get("custom_data") or {}
        return custom_data.get("user_id", "default")

    def extract_subscription_info(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extracts subscription/customer IDs and status from a Paddle event.

        Returns a dict with:
          - customer_id
          - subscription_id
          - status  (active | canceled | paused | trialing | past_due)
          - next_billed_at  (ISO 8601 or None)
        """
        data = event.get("data", {})
        return {
            "customer_id": data.get("customer_id", ""),
            "subscription_id": data.get("id", ""),
            "status": data.get("status", "active"),
            "next_billed_at": data.get("next_billed_at"),
            "scheduled_change": data.get("scheduled_change"),
        }

    def extract_transaction_info(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extracts transaction info from a transaction.completed event.

        Returns a dict with:
          - transaction_id
          - customer_id
          - subscription_id
          - status
          - custom_data
        """
        data = event.get("data", {})
        return {
            "transaction_id": data.get("id", ""),
            "customer_id": data.get("customer_id", ""),
            "subscription_id": data.get("subscription_id", ""),
            "status": data.get("status", ""),
            "custom_data": data.get("custom_data") or {},
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }


def get_paddle_service() -> Optional[PaddleService]:
    """
    Returns a configured PaddleService instance, or None if Paddle is not
    configured (missing API key).
    """
    api_key = os.environ.get("PADDLE_API_KEY", "")
    webhook_secret = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
    environment = os.environ.get("PADDLE_ENVIRONMENT", "sandbox")
    price_id = os.environ.get("PADDLE_PRICE_ID", "")

    if not api_key:
        return None

    return PaddleService(
        api_key=api_key,
        webhook_secret=webhook_secret,
        environment=environment,
        price_id=price_id,
    )
