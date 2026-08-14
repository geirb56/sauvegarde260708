"""PR #128 — /api/dashboard must use Training Load V2."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any, List, Optional
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

if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from training_v2.training_load import build_training_load  # noqa: E402


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_Cursor":
        reverse = direction < 0
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=reverse)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs = list(docs or [])

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        def _match(doc: dict) -> bool:
            for key, value in (query or {}).items():
                if isinstance(value, dict):
                    continue
                if doc.get(key) != value:
                    return False
            return True

        return _Cursor([dict(doc) for doc in self._docs if _match(doc)])

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        for doc in (await self.find(query, projection).to_list(length=None)):
            return doc
        return None


class _FakeDB:
    def __init__(
        self,
        *,
        workouts: Optional[List[dict]] = None,
        garmin_activities: Optional[List[dict]] = None,
        garmin_daily_metrics: Optional[List[dict]] = None,
    ) -> None:
        self.workouts = _Collection(workouts)
        self.garmin_activities = _Collection(garmin_activities)
        self.garmin_daily_metrics = _Collection(garmin_daily_metrics)

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


def _bearer(user_id: str, email: str = "test@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _garmin_act(user_id: str, days_ago: int, duration_s: Optional[float]) -> dict:
    act_date = date.today() - timedelta(days=days_ago)
    doc = {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": act_date.isoformat() + "T08:00:00",
    }
    if duration_s is not None:
        doc["duration"] = duration_s
    return doc


def _metrics_doc(user_id: str, days_ago: int) -> dict:
    metric_date = date.today() - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "date": metric_date.isoformat(),
        "resting_hr": 52.0,
        "hrv": 64.0,
        "sleep_hours": 7.5,
        "sleep_score": 80.0,
    }


@pytest.mark.asyncio
async def test_dashboard_acwr_matches_training_load_v2():
    user_id = "dashboard-user-a"
    acts = [_garmin_act(user_id, d, 1800.0) for d in range(28)]
    metrics = [_metrics_doc(user_id, d) for d in range(14)]
    workouts = [{"user_id": user_id, "date": date.today().isoformat(), "distance_km": 10.0}]
    fake_db = _FakeDB(workouts=workouts, garmin_activities=acts, garmin_daily_metrics=metrics)

    with patch.object(server.app.state, "db", fake_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/dashboard", headers=_bearer(user_id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["acwr"] == build_training_load(acts, date.today()).acwr


@pytest.mark.asyncio
async def test_dashboard_no_history_returns_acwr_none():
    user_id = "dashboard-user-empty"
    fake_db = _FakeDB()

    with patch.object(server.app.state, "db", fake_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/dashboard", headers=_bearer(user_id))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["acwr"] is None
    assert payload["status"] == "unavailable"


@pytest.mark.asyncio
async def test_dashboard_multi_user_uses_only_request_user():
    user_a = "dashboard-user-a"
    user_b = "dashboard-user-b"
    acts_a = [_garmin_act(user_a, d, 1800.0) for d in range(28)]
    acts_b = [_garmin_act(user_b, d, 3600.0) for d in range(28)]
    metrics_a = [_metrics_doc(user_a, d) for d in range(14)]
    metrics_b = [_metrics_doc(user_b, d) for d in range(14)]
    fake_db = _FakeDB(
        garmin_activities=acts_a + acts_b,
        garmin_daily_metrics=metrics_a + metrics_b,
    )

    with patch.object(server.app.state, "db", fake_db):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/dashboard", headers=_bearer(user_b, "b@example.com"))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["acwr"] == build_training_load(acts_b, date.today()).acwr
