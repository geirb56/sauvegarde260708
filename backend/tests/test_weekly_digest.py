"""
Legacy weekly digest endpoint removal tests.
"""

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestWeeklyDigestEndpointRemoval:
    def test_digest_endpoint_returns_404(self):
        response = requests.get(f"{BASE_URL}/api/coach/digest?language=en")
        assert response.status_code == 404

    def test_digest_latest_endpoint_returns_404(self):
        response = requests.get(f"{BASE_URL}/api/coach/digest/latest")
        assert response.status_code == 404

    def test_digest_history_endpoint_returns_404(self):
        response = requests.get(f"{BASE_URL}/api/coach/digest/history?limit=10&skip=0")
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
