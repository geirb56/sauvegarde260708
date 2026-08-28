"""PR216 — canonical writable Training V2 cycle start date endpoint."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr216-start-date-secret-32chars!")
os.environ.setdefault("JWT_SECRET", "test-pr216-start-date-secret-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import server  # noqa: E402
from access_control import ROUTE_ACCESS_MAP, RouteAccess, Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402


class _UpdateResult:
    matched_count = 1
    modified_count = 1


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def _match(self, doc: dict, query: dict) -> bool:
        for key, value in query.items():
            if isinstance(value, dict):
                continue
            if doc.get(key) != value:
                return False
        return True

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if self._match(doc, q):
                return dict(doc)
        return None

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> _UpdateResult:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if self._match(doc, q):
                doc.update(update.get("$set", {}))
                return _UpdateResult()
        if upsert:
            self._docs.append({**q, **update.get("$set", {})})
        return _UpdateResult()

    async def create_index(self, *_a: Any, **_kw: Any) -> None:
        return None


class _FakeDB:
    def __init__(self, *, training_cycles: Optional[List[dict]] = None, user_goals: Optional[List[dict]] = None) -> None:
        self.training_cycles = _Collection(training_cycles)
        self.user_goals = _Collection(user_goals)

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


def _bearer(user_id: str = "pr216-user", email: str = "pr216@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


async def _post(fake_db: _FakeDB, user_id: str, payload: dict) -> httpx.Response:
    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/training/v2/cycle/start-date",
                headers=_bearer(user_id),
                json=payload,
            )


def test_route_access_marks_start_date_endpoint_premium():
    assert ROUTE_ACCESS_MAP["/api/training/v2/cycle/start-date"] == RouteAccess.PREMIUM


@pytest.mark.asyncio
async def test_updates_only_authenticated_users_cycle_start_date():
    fake_db = _FakeDB(
        training_cycles=[
            {"user_id": "pr216-user", "goal": "MARATHON", "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc)},
            {"user_id": "other-user", "goal": "MARATHON", "start_date": datetime(2026, 7, 1, tzinfo=timezone.utc)},
        ],
        user_goals=[{"user_id": "pr216-user", "event_date": "2026-10-12"}],
    )

    response = await _post(fake_db, "pr216-user", {"start_date": "2026-08-20"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "updated"
    assert body["cycle"]["start_date"] == "2026-08-20"
    own_cycle = next(doc for doc in fake_db.training_cycles._docs if doc["user_id"] == "pr216-user")
    other_cycle = next(doc for doc in fake_db.training_cycles._docs if doc["user_id"] == "other-user")
    assert own_cycle["start_date"].date() == date(2026, 8, 20)
    assert other_cycle["start_date"].date() == date(2026, 7, 1)


@pytest.mark.asyncio
async def test_missing_cycle_returns_explicit_400():
    response = await _post(_FakeDB(), "pr216-user", {"start_date": "2026-08-20"})

    assert response.status_code == 400
    assert "No training cycle defined" in response.json()["detail"]


@pytest.mark.asyncio
async def test_future_start_date_is_rejected():
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "pr216-user", "goal": "MARATHON", "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc)}],
        user_goals=[{"user_id": "pr216-user", "event_date": "2026-10-12"}],
    )

    response = await _post(fake_db, "pr216-user", {"start_date": tomorrow})

    assert response.status_code == 400
    assert response.json()["detail"] == "plan_start_date cannot be in the future."


@pytest.mark.asyncio
async def test_start_date_after_race_date_is_rejected():
    fake_db = _FakeDB(
        training_cycles=[{"user_id": "pr216-user", "goal": "MARATHON", "start_date": datetime(2026, 8, 1, tzinfo=timezone.utc)}],
        user_goals=[{"user_id": "pr216-user", "event_date": "2026-08-15"}],
    )

    response = await _post(fake_db, "pr216-user", {"start_date": "2026-08-20"})

    assert response.status_code == 400
    assert response.json()["detail"] == "plan_start_date must be on or before race_date."
