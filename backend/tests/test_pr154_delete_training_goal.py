"""PR #154 — Verify DELETE /training/goal no longer accesses db.training_goals.

Tests the real route via httpx.AsyncClient against a fake DB.
Proves:
1. DELETE /training/goal works and returns success.
2. Active collections (training_context, training_cycles) are cleaned.
3. No access to the legacy db.training_goals collection.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional
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

_USER_ID = "pr154-test-user"


# ---------------------------------------------------------------------------
# Fake DB with tracking
# ---------------------------------------------------------------------------

class _DeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


class _TrackedCollection:
    """Minimal collection that tracks calls."""

    def __init__(self, name: str, docs: Optional[List[dict]] = None):
        self.name = name
        self._docs: List[dict] = list(docs or [])
        self.calls: List[tuple] = []

    async def delete_one(self, query: dict) -> _DeleteResult:
        self.calls.append(("delete_one", query))
        before = len(self._docs)
        self._docs = [d for d in self._docs if not all(d.get(k) == v for k, v in query.items())]
        return _DeleteResult(before - len(self._docs))

    async def find_one(self, query: dict, projection=None):
        self.calls.append(("find_one", query))
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def update_one(self, *a, **kw):
        self.calls.append(("update_one", a))

    def find(self, query=None, projection=None):
        self.calls.append(("find", query))
        return self

    def sort(self, *a, **kw):
        return self

    def limit(self, n):
        return self

    async def to_list(self, length=None):
        return []

    async def create_index(self, *a, **kw):
        pass

    async def count_documents(self, query):
        return 0


class _FakeDB:
    def __init__(self):
        self.training_context = _TrackedCollection(
            "training_context", [{"user_id": _USER_ID, "data": "ctx"}]
        )
        self.training_cycles = _TrackedCollection(
            "training_cycles", [{"user_id": _USER_ID, "goal": "10K"}]
        )
        # Legacy collection — should NEVER be accessed
        self.training_goals = _TrackedCollection("training_goals", [])
        self._accessed_attrs: List[str] = []

    def __getattr__(self, name: str):
        if name.startswith("_") or name in ("training_context", "training_cycles", "training_goals"):
            raise AttributeError(name)
        col = _TrackedCollection(name)
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bearer() -> dict:
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, "test@pr154.com")}


async def _mock_get_user_access(db, user_id):
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


@pytest_asyncio.fixture
async def client():
    fake_db = _FakeDB()
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as ac:
            ac._fake_db = fake_db
            yield ac
    finally:
        for p in started:
            p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeleteTrainingGoalPR154:
    """DELETE /api/training/goal removes active collections, not legacy."""

    async def test_delete_succeeds(self, client):
        resp = await client.delete("/api/training/goal", headers=_bearer())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "deleted" in body["message"].lower() or "goal" in body["message"].lower()

    async def test_active_collections_cleaned(self, client):
        await client.delete("/api/training/goal", headers=_bearer())
        db = client._fake_db
        assert len(db.training_context.calls) > 0
        assert any(c[0] == "delete_one" for c in db.training_context.calls)
        assert len(db.training_cycles.calls) > 0
        assert any(c[0] == "delete_one" for c in db.training_cycles.calls)

    async def test_no_access_to_legacy_training_goals(self, client):
        await client.delete("/api/training/goal", headers=_bearer())
        db = client._fake_db
        assert db.training_goals.calls == [], (
            f"Legacy db.training_goals was accessed: {db.training_goals.calls}"
        )

    async def test_delete_no_data_returns_no_goal(self, client):
        db = client._fake_db
        db.training_context._docs.clear()
        db.training_cycles._docs.clear()
        resp = await client.delete("/api/training/goal", headers=_bearer())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
