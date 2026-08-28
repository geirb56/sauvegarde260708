"""PR216 — Dashboard and Progress share a single canonical current RunIndex."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import List, Optional
from unittest.mock import patch

import dashboard_insight_cache as _dic
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

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_Cursor":
        self._docs.sort(key=lambda doc: doc.get(field) or "", reverse=direction < 0)
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
                doc_value = doc.get(key)
                if isinstance(value, dict):
                    if "$gte" in value and (doc_value is None or doc_value < value["$gte"]):
                        return False
                    if "$lte" in value and (doc_value is None or doc_value > value["$lte"]):
                        return False
                    continue
                if doc_value != value:
                    return False
            return True

        return _Cursor([dict(doc) for doc in self._docs if _match(doc)])

    async def update_one(self, filter_doc: dict, update_doc: dict, upsert: bool = False):
        for index, doc in enumerate(self._docs):
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                self._docs[index] = {**doc, **update_doc.get("$set", {})}
                return
        if upsert:
            self._docs.append(dict(update_doc.get("$set", {})))


class _FakeDB:
    def __init__(self, *, garmin_activities: List[dict], run_index_scores: Optional[List[dict]] = None) -> None:
        self.garmin_activities = _Collection(garmin_activities)
        self.run_index_scores = _Collection(run_index_scores)

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


def _override_user(user_id: str):
    async def _inner():
        return {"id": user_id}

    return _inner


def _bearer(user_id: str, email: str = "test@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _garmin_act(user_id: str, *, days_ago: int, km: float, minutes: float, avg_hr: float) -> dict:
    act_date = date.today() - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": f"{act_date.isoformat()}T08:00:00+00:00",
        "distance_m": km * 1000.0,
        "duration_s": minutes * 60.0,
        "average_hr": avg_hr,
        "source": "garmin",
    }


async def _get_json(fake_db: _FakeDB, user_id: str, path: str) -> dict:
    _dic._cache.clear()
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
                response = await client.get(path, headers=_bearer(user_id))
    finally:
        server.app.dependency_overrides.clear()
        _dic._cache.clear()

    assert response.status_code == 200, response.text
    return response.json()


def _run_index_for_today(fake_db: _FakeDB) -> int:
    today = date.today().isoformat()
    doc = next(doc for doc in fake_db.run_index_scores._docs if doc["date"] == today)
    return doc["run_index"]


def _seed_fake_db(user_id: str) -> _FakeDB:
    return _FakeDB(
        garmin_activities=[
            _garmin_act(user_id, days_ago=42, km=8.0, minutes=44.0, avg_hr=150.0),
            _garmin_act(user_id, days_ago=28, km=10.0, minutes=49.0, avg_hr=156.0),
            _garmin_act(user_id, days_ago=14, km=12.0, minutes=56.0, avg_hr=160.0),
            _garmin_act(user_id, days_ago=7, km=16.0, minutes=73.0, avg_hr=158.0),
            _garmin_act(user_id, days_ago=2, km=21.1, minutes=92.0, avg_hr=162.0),
            _garmin_act(user_id, days_ago=0, km=10.0, minutes=42.0, avg_hr=168.0),
        ],
        run_index_scores=[
            {
                "user_id": user_id,
                "date": (date.today() - timedelta(days=30)).isoformat(),
                "run_index": 245,
                "speed_score": 24,
                "endurance_score": 25,
                "consistency_score": 26,
                "efficiency_score": 27,
            },
            {
                "user_id": user_id,
                "date": date.today().isoformat(),
                "run_index": 123,
                "speed_score": 12,
                "endurance_score": 12,
                "consistency_score": 12,
                "efficiency_score": 12,
            },
        ],
    )


async def test_dashboard_then_progress_share_same_current_and_preserve_history():
    user_id = "pr216-dashboard-first"
    fake_db = _seed_fake_db(user_id)

    dashboard = await _get_json(fake_db, user_id, "/api/dashboard/insight")
    progress = await _get_json(fake_db, user_id, "/api/run-index/history?period=6m")

    current_x = dashboard["run_index"]["run_index"]
    today_snapshot = _run_index_for_today(fake_db)

    assert current_x is not None
    assert current_x != 245
    assert progress["current_run_index"] == current_x
    assert today_snapshot == current_x
    assert any(point["date"] == (date.today() - timedelta(days=30)).isoformat() and point["run_index"] == 245 for point in progress["history"])


async def test_progress_then_dashboard_share_same_current_independent_of_navigation_order():
    user_id = "pr216-progress-first"
    fake_db = _seed_fake_db(user_id)

    progress = await _get_json(fake_db, user_id, "/api/run-index/history?period=6m")
    dashboard = await _get_json(fake_db, user_id, "/api/dashboard/insight")

    current_x = dashboard["run_index"]["run_index"]
    today_snapshot = _run_index_for_today(fake_db)

    assert current_x is not None
    assert progress["current_run_index"] == current_x
    assert today_snapshot == current_x
