"""Tests for GET /api/garmin/vo2max-history."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

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
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, key: str, direction: int):
        reverse = direction < 0
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=reverse)
        return self

    async def to_list(self, length: Optional[int] = None):
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs = list(docs or [])

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        query = query or {}
        results = []
        for doc in self._docs:
            ok = True
            for key, expected in query.items():
                if isinstance(expected, dict):
                    if "$ne" in expected and doc.get(key) == expected["$ne"]:
                        ok = False
                        break
                    if "$gte" in expected and (doc.get(key) or "") < expected["$gte"]:
                        ok = False
                        break
                elif doc.get(key) != expected:
                    ok = False
                    break
            if ok:
                results.append(dict(doc))
        return _Cursor(results)


class _FakeDB:
    def __init__(self, garmin_vo2max_docs: Optional[List[dict]] = None) -> None:
        self.garmin_vo2max = _Collection(garmin_vo2max_docs or [])


def _bearer(user_id: str) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, "test@example.com")}


def _premium_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


@pytest.mark.asyncio
async def test_vo2max_history_user_isolation_and_order():
    fake_db = _FakeDB(
        garmin_vo2max_docs=[
            {"user_id": "u1", "date": "2026-01-02", "vo2max_running": 40.0, "vo2max_running_precise": 40.3},
            {"user_id": "u1", "date": "2026-04-10", "vo2max_running": 42.0, "vo2max_running_precise": 42.2},
            {"user_id": "u2", "date": "2026-04-11", "vo2max_running": 99.0, "vo2max_running_precise": 99.9},
            {"user_id": "u1", "date": "2026-07-05", "vo2max_running": 43.0, "vo2max_running_precise": 43.5},
        ]
    )
    with patch.object(server, "db", fake_db), patch("server.get_user_access", AsyncMock(side_effect=_premium_access)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            response = await client.get("/api/garmin/vo2max-history?period=12m", headers=_bearer("u1"))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [point["date"] for point in payload["history"]] == ["2026-01-02", "2026-04-10", "2026-07-05"]
    assert payload["current"]["date"] == "2026-07-05"
    assert payload["current"]["value"] == 43.0


@pytest.mark.asyncio
async def test_vo2max_history_period_filter_sparse_semantics_and_no_data():
    today = datetime.now(timezone.utc).date()
    old_date = today.replace(year=today.year - 2).isoformat()
    recent_date = today.isoformat()

    fake_db = _FakeDB(
        garmin_vo2max_docs=[
            {"user_id": "u1", "date": old_date, "vo2max_running": 41.0},
            {"user_id": "u1", "date": recent_date, "vo2max_running": 44.0},
            {"user_id": "u1", "date": today.isoformat(), "vo2max_running": None},
        ]
    )
    with patch.object(server, "db", fake_db), patch("server.get_user_access", AsyncMock(side_effect=_premium_access)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            response = await client.get("/api/garmin/vo2max-history?period=3m", headers=_bearer("u1"))

    assert response.status_code == 200, response.text
    payload = response.json()
    dates = [point["date"] for point in payload["history"]]
    assert old_date not in dates
    assert all("source" in point and point["source"] == "garmin" for point in payload["history"])

    empty_db = _FakeDB(garmin_vo2max_docs=[])
    with patch.object(server, "db", empty_db), patch("server.get_user_access", AsyncMock(side_effect=_premium_access)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            empty_response = await client.get("/api/garmin/vo2max-history?period=12m", headers=_bearer("u1"))

    assert empty_response.status_code == 200
    empty_payload = empty_response.json()
    assert empty_payload["current"] is None
    assert empty_payload["history"] == []
