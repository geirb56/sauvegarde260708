"""
Legacy weekly review endpoint removal tests.
"""

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestWeeklyReviewEndpointRemoval:
    def test_digest_endpoint_removed_en(self):
        response = requests.get(f"{BASE_URL}/api/coach/digest?language=en", timeout=60)
        assert response.status_code == 404

    def test_digest_endpoint_removed_fr(self):
        response = requests.get(f"{BASE_URL}/api/coach/digest?language=fr", timeout=60)
        assert response.status_code == 404

    def test_digest_latest_removed(self):
        response = requests.get(f"{BASE_URL}/api/coach/digest/latest", timeout=30)
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
