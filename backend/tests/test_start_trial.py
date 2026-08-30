"""`/api/subscription/start-trial` hardening tests.

Hits the real /api/subscription/start-trial route in server.py via an in-process
ASGI client with an in-memory fake DB. No live Mongo/Redis/LLM/Paddle needed.

Covered:
  - anonymous (no JWT) -> 401
  - authenticated user -> 403 (direct trial bypass blocked)
"""
from __future__ import annotations

import os
import sys
from typing import Any
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
from auth.jwt_utils import create_access_token  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402

pytestmark = pytest.mark.asyncio


def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


class _Collection:
    def __init__(self) -> None:
        self._docs: list[dict] = []

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            new = dict(query)
            new.update(update.get("$set", {}))
            self._docs.append(new)

    async def create_index(self, *a, **kw) -> None:
        pass


class _FakeDB:
    def __init__(self) -> None:
        self.subscriptions = _Collection()

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection()
        object.__setattr__(self, name, col)
        return col


def _free_access(db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.FREE)


@pytest_asyncio.fixture
async def client():
    fake_db = _FakeDB()
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as c:
            yield c, fake_db
    finally:
        for p in reversed(started):
            p.stop()


async def test_start_trial_requires_auth(client):
    c, _ = client
    r = await c.post("/api/subscription/start-trial")
    assert r.status_code == 401


async def test_start_trial_rejects_direct_activation(client):
    c, fake_db = client
    r = await c.post("/api/subscription/start-trial", headers=_bearer("u-trial", "u@test.com"))
    assert r.status_code == 403
    assert "garmin" in r.json().get("detail", "").lower()
    sub = await fake_db.subscriptions.find_one({"user_id": "u-trial"})
    assert sub is None
