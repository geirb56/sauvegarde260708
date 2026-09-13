"""Regression tests for /api/training/set-goal idempotence."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

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

pytestmark = pytest.mark.asyncio

_USER_ID = "goal-idempotence-user"


class _FakeUserGoalsCollection:
    def __init__(self):
        self.delete_many_calls: list[dict] = []

    async def delete_many(self, query: dict):
        self.delete_many_calls.append(dict(query))


class _FakeTrainingCyclesCollection:
    def __init__(self, initial_doc: Optional[dict] = None):
        self.doc = dict(initial_doc or {})
        self.update_one_calls: list[tuple[dict, dict, bool]] = []

    async def find_one(self, query: dict, projection: Optional[dict] = None):
        if self.doc and all(self.doc.get(k) == v for k, v in query.items()):
            return dict(self.doc)
        return None

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        self.update_one_calls.append((dict(query), dict(update), bool(upsert)))
        if self.doc and all(self.doc.get(k) == v for k, v in query.items()):
            self.doc.update(update.get("$set", {}))
            return
        if upsert:
            self.doc = {**query, **update.get("$set", {})}


class _NoopCollection:
    async def find_one(self, query: dict, projection: Optional[dict] = None):
        return None

    async def update_one(self, *args: Any, **kwargs: Any):
        return None

    async def delete_one(self, *args: Any, **kwargs: Any):
        return None

    def find(self, *args: Any, **kwargs: Any):
        return self

    def sort(self, *args: Any, **kwargs: Any):
        return self

    def limit(self, *args: Any, **kwargs: Any):
        return self

    async def to_list(self, *args: Any, **kwargs: Any):
        return []


class _FakeDB:
    def __init__(self, initial_goal: str, initial_start_date: datetime):
        self.training_cycles = _FakeTrainingCyclesCollection(
            {
                "user_id": _USER_ID,
                "goal": initial_goal,
                "start_date": initial_start_date,
                "updated_at": initial_start_date,
            }
        )
        self.user_goals = _FakeUserGoalsCollection()

    def __getattr__(self, name: str):
        col = _NoopCollection()
        object.__setattr__(self, name, col)
        return col


def _bearer() -> dict:
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, "goal-idempotence@test.com")}


async def _mock_get_user_access(db, user_id):
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


@pytest_asyncio.fixture
async def client_factory():
    clients: list[httpx.AsyncClient] = []
    started_patches: list[list[Any]] = []

    async def _build(initial_goal: str):
        start_date = datetime.now(timezone.utc) - timedelta(days=10)
        fake_db = _FakeDB(initial_goal=initial_goal, initial_start_date=start_date)
        patches = [
            patch.object(server, "db", fake_db),
            patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
        ]
        for p in patches:
            p.start()
        started_patches.append(patches)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        )
        client._fake_db = fake_db
        clients.append(client)
        return client

    try:
        yield _build
    finally:
        for client in clients:
            await client.aclose()
        for patch_group in started_patches:
            for p in patch_group:
                p.stop()


async def test_same_goal_is_unchanged_and_preserves_state(client_factory):
    client = await client_factory("SEMI")
    before_start_date = client._fake_db.training_cycles.doc["start_date"]

    resp = await client.post("/api/training/set-goal?goal=SEMI", headers=_bearer())

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unchanged"
    assert body["goal"] == "SEMI"
    assert client._fake_db.training_cycles.update_one_calls == []
    assert client._fake_db.training_cycles.doc["start_date"] == before_start_date
    assert client._fake_db.user_goals.delete_many_calls == []


async def test_same_goal_maintenance_is_idempotent(client_factory):
    client = await client_factory("MAINTENANCE")
    before_start_date = client._fake_db.training_cycles.doc["start_date"]

    resp = await client.post("/api/training/set-goal?goal=maintenance", headers=_bearer())

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unchanged"
    assert body["goal"] == "MAINTENANCE"
    assert client._fake_db.training_cycles.update_one_calls == []
    assert client._fake_db.training_cycles.doc["start_date"] == before_start_date
    assert client._fake_db.user_goals.delete_many_calls == []


async def test_training_plan_goal_can_switch_to_maintenance(client_factory):
    client = await client_factory("SEMI")

    resp = await client.post("/api/training-plan/set-goal?goal=MAINTENANCE", headers=_bearer())

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "updated"
    assert body["goal"] == "MAINTENANCE"
    assert body["cycle_weeks"] == 52
    assert body["description"] == "Maintenance"
    assert len(client._fake_db.training_cycles.update_one_calls) == 1
    assert client._fake_db.training_cycles.doc["goal"] == "MAINTENANCE"
    assert client._fake_db.user_goals.delete_many_calls == []


async def test_goal_change_updates_cycle_without_touching_user_goals(client_factory):
    client = await client_factory("SEMI")
    before_start_date = client._fake_db.training_cycles.doc["start_date"]

    resp = await client.post("/api/training/set-goal?goal=MARATHON", headers=_bearer())

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "updated"
    assert body["goal"] == "MARATHON"
    assert len(client._fake_db.training_cycles.update_one_calls) == 1
    assert client._fake_db.training_cycles.doc["goal"] == "MARATHON"
    assert client._fake_db.training_cycles.doc["start_date"] != before_start_date
    assert client._fake_db.user_goals.delete_many_calls == []
