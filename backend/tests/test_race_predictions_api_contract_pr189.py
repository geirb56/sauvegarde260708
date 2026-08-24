from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import List, Optional
from unittest.mock import patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "integration-test-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from server import auth_user  # noqa: E402


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        query = query or {}

        def _match(doc: dict) -> bool:
            for k, v in query.items():
                if doc.get(k) != v:
                    return False
            return True

        return _Cursor([dict(d) for d in self._docs if _match(d)])


class _FakeDB:
    def __init__(self, garmin_activities: List[dict]) -> None:
        self.garmin_activities = _Collection(garmin_activities)


def _override_user(user_id: str):
    async def _inner():
        return {"id": user_id}

    return _inner


def _bearer(user_id: str, email: str = "test@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _ga(
    user_id: str,
    *,
    days_ago: int,
    distance_m: float,
    duration_s: float,
    avg_hr: float,
    max_hr: float,
) -> dict:
    start = date.today() - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": f"{start.isoformat()}T08:00:00+00:00",
        "distance_m": distance_m,
        "duration_s": duration_s,
        "average_hr": avg_hr,
        "max_hr": max_hr,
    }


@pytest.mark.asyncio
async def test_pr189_race_predictions_api_exposes_curve_diagnostics_and_prediction_extrapolation():
    user_id = "pr189-api-contract"
    activities = [
        _ga(user_id, days_ago=85, distance_m=8_000.0, duration_s=3_300.0, avg_hr=125.0, max_hr=160.0),
        _ga(user_id, days_ago=72, distance_m=9_000.0, duration_s=3_700.0, avg_hr=128.0, max_hr=162.0),
        _ga(user_id, days_ago=60, distance_m=10_000.0, duration_s=4_150.0, avg_hr=131.0, max_hr=164.0),
        _ga(user_id, days_ago=48, distance_m=11_000.0, duration_s=4_600.0, avg_hr=134.0, max_hr=166.0),
        _ga(user_id, days_ago=36, distance_m=12_000.0, duration_s=5_050.0, avg_hr=137.0, max_hr=168.0),
        _ga(user_id, days_ago=24, distance_m=13_000.0, duration_s=5_500.0, avg_hr=140.0, max_hr=170.0),
        _ga(user_id, days_ago=14, distance_m=5_000.0, duration_s=1_470.0, avg_hr=158.0, max_hr=176.0),
        _ga(user_id, days_ago=6, distance_m=10_000.0, duration_s=3_080.0, avg_hr=160.0, max_hr=178.0),
    ]
    fake_db = _FakeDB(garmin_activities=activities)
    server.app.dependency_overrides[auth_user] = _override_user(user_id)
    try:
        with (
            patch.object(server.app.state, "db", fake_db, create=True),
            patch("server.db", fake_db),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app),
                base_url="http://test",
            ) as client:
                response = await client.get("/api/training/race-predictions", headers=_bearer(user_id))
    finally:
        server.app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["has_data"] is True
    assert "predictions" in payload and len(payload["predictions"]) == 4
    assert "race_curve_diagnostics" in payload

    diag = payload["race_curve_diagnostics"]
    for key in [
        "curve_method",
        "curve_k",
        "contributors_count",
        "qualified_performance_count",
        "observed_distance_min_km",
        "observed_distance_max_km",
        "fit_quality",
        "k_conflict",
        "k_fallback_applied",
    ]:
        assert key in diag

    for pred in payload["predictions"]:
        assert "distance" in pred
        assert "predicted_time" in pred
        assert "confidence" in pred
        assert "predicted_time_s" in pred
        assert "extrapolation_ratio" in pred
        assert "is_strong_extrapolation" in pred
        assert "curve_method" in pred
        assert "curve_k" in pred
        assert "contributors_count" in pred
