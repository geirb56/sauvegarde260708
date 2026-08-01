"""
IDOR / Authorization — integration tests (PR60).

These tests hit the **real** FastAPI routes registered in server.py, using an
in-memory fake database and thin service mocks so that:
  - No live MongoDB, Redis or LLM connection is required;
  - The actual authentication middleware (auth_user), subscription middleware,
    request routing, and user-isolation logic are exactly the production code.

Scenarios covered for each endpoint:
  1. Anonymous request (no JWT)            → 4xx (401 on FREE routes, 401/403 on PREMIUM routes)
  2. Owner (PREMIUM user, JWT matches)     → 200
  3. Non-owner (PREMIUM user, other user)  → 404 / empty list

Routes under test:
  GET  /api/messages
  GET  /api/rag/workout/{workout_id}
  GET  /api/coach/workout-analysis/{workout_id}
  GET  /api/coach/detailed-analysis/{workout_id}
  POST /api/chat/send
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Environment must be set before server is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("JWT_SECRET_KEY", "integration-test-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Ensure the backend's `config` *package* (backend/config/) is used,
# not the root-level config.py which may have been imported by other tests
# in the same pytest session.
if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    # If config was loaded from the root config.py (a plain file, not a
    # package), remove it so server.py can load the backend config package.
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402 — must come after env vars and path fixup
from auth.jwt_utils import create_access_token  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _workout(user_id: str, workout_id: str) -> dict:
    return {
        "id": workout_id,
        "user_id": user_id,
        "date": "2024-01-01",
        "type": "run",
        "distance_km": 10.0,
        "duration_minutes": 60,
    }


# ---------------------------------------------------------------------------
# In-memory fake MongoDB collections
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, docs: list) -> None:
        self._docs = list(docs)

    def sort(self, *a, **kw) -> "_Cursor":
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int | None = None) -> list:
        return list(self._docs[:length] if length is not None else self._docs)


class _Collection:
    def __init__(self, docs: list | None = None) -> None:
        self._docs: list = list(docs or [])

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def find(self, query: dict | None = None, projection: dict | None = None) -> _Cursor:
        q = query or {}
        results = [d for d in self._docs if all(d.get(k) == v for k, v in q.items())]
        return _Cursor(results)

    async def count_documents(self, query: dict) -> int:
        return sum(
            1 for d in self._docs
            if all(
                d.get(k) == v
                for k, v in query.items()
                if not isinstance(v, dict)   # skip $gte etc.
            )
        )

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def create_index(self, *a, **kw) -> None:
        pass


class _FakeDB:
    """Minimal fake database pre-populated for IDOR tests."""

    WORKOUT_A_ID = "wkt-integration-a"
    WORKOUT_B_ID = "wkt-integration-b"

    def __init__(self) -> None:
        self.workouts = _Collection([
            _workout("user-a", self.WORKOUT_A_ID),
            _workout("user-b", self.WORKOUT_B_ID),
        ])
        self.conversations = _Collection([
            {"id": str(uuid.uuid4()), "user_id": "user-a",
             "role": "user", "content": "Hello A", "timestamp": "2024-01-01T00:00:00Z"},
            {"id": str(uuid.uuid4()), "user_id": "user-b",
             "role": "user", "content": "Hello B", "timestamp": "2024-01-01T00:00:00Z"},
        ])
        self.chat_messages = _Collection()
        self.user_goals = _Collection()
        self.subscriptions = _Collection()
        self.users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True,
             "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True,
             "is_email_verified": True},
        ])

    # Allow attribute access for any collection name, returning an empty _Collection
    def __getattr__(self, name: str) -> _Collection:
        col: _Collection = _Collection()
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Service stubs (avoid LLM / external I/O)
# ---------------------------------------------------------------------------

def _stub_session_analysis(*_a: Any, **_kw: Any) -> dict:
    return {
        "summary": "Good run",
        "meaning": "Solid effort",
        "advice": "Keep it up",
        "recovery": "Easy tomorrow",
        "metrics": {
            "session_type": "moderate",
            "intensity_level": "moderate",
            "training_load": 50,
        },
    }


async def _stub_localize(fields: dict, *_a: Any, **_kw: Any) -> dict:
    return dict(fields)


def _stub_rag_analysis(*_a: Any, **_kw: Any) -> dict:
    """generate_workout_analysis_rag is a sync function — must not be AsyncMock."""
    return {
        "comparison": {"progression": "stable"},
        "points_forts": ["Consistent pace"],
        "points_ameliorer": ["Cadence"],
        "tips": ["Hydrate well"],
        "rag_sources": {},
        "workout": {"km": 10},
    }


async def _stub_coach_analyze(*_a: Any, **_kw: Any) -> tuple:
    return "Great workout!", False


async def _stub_coach_chat(*_a: Any, **_kw: Any) -> tuple:
    return "Training tip here", False, {}


def _get_user_access(db: Any, user_id: str) -> UserAccess:
    """
    Grant PREMIUM to the two test users; FREE to anything else
    (anonymous callers have their IP used as user_id by the middleware).
    """
    if user_id in ("user-a", "user-b"):
        return UserAccess(user_id=user_id, tier=Tier.PREMIUM)
    return UserAccess(user_id=user_id, tier=Tier.FREE)


# ---------------------------------------------------------------------------
# Shared fixture: patched real app client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def real_client():
    """
    httpx.AsyncClient backed by the real server.app with:
      - server.db replaced by an in-memory fake
      - heavy service functions stubbed out
      - test users granted PREMIUM access; anonymous callers stay FREE
    """
    fake_db = _FakeDB()

    patches = [
        patch.object(server, "db", fake_db),
        patch("server.generate_session_analysis", _stub_session_analysis),
        patch("server.localization", MagicMock(
            localize_fields=AsyncMock(side_effect=_stub_localize)
        )),
        patch("server.generate_workout_analysis_rag", _stub_rag_analysis),
        patch("server.coach_analyze_workout", AsyncMock(
            side_effect=_stub_coach_analyze
        )),
        patch("server.coach_chat_response", AsyncMock(
            side_effect=_stub_coach_chat
        )),
        # get_user_access is called by the subscription middleware and by chat/send.
        # Give test users PREMIUM access so they can reach the route handlers;
        # all other callers (e.g. anonymous with IP as user_id) remain FREE.
        patch("server.get_user_access", AsyncMock(
            side_effect=_get_user_access
        )),
    ]

    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            yield client, fake_db
    finally:
        for p in reversed(started):
            p.stop()


# ---------------------------------------------------------------------------
# 1. GET /api/messages
# ---------------------------------------------------------------------------

class TestMessagesIntegration:
    async def test_anonymous_denied(self, real_client):
        """Unauthenticated request to a premium route must be denied (4xx)."""
        client, _ = real_client
        r = await client.get("/api/messages")
        assert r.status_code in (401, 403)

    async def test_owner_sees_own_messages(self, real_client):
        client, fake_db = real_client
        conv_a_id = fake_db.conversations._docs[0]["id"]
        r = await client.get(
            "/api/messages",
            headers=_bearer("user-a", "a@test.com"),
        )
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert conv_a_id in ids

    async def test_user_b_cannot_see_user_a_messages(self, real_client):
        client, fake_db = real_client
        conv_a_id = fake_db.conversations._docs[0]["id"]
        r = await client.get(
            "/api/messages",
            headers=_bearer("user-b", "b@test.com"),
        )
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert conv_a_id not in ids


# ---------------------------------------------------------------------------
# 2. GET /api/rag/workout/{workout_id}
# ---------------------------------------------------------------------------

class TestRagWorkoutIntegration:
    async def test_anonymous_denied(self, real_client):
        client, _ = real_client
        r = await client.get(f"/api/rag/workout/{_FakeDB.WORKOUT_A_ID}")
        assert r.status_code in (401, 403)

    async def test_owner_gets_200(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/rag/workout/{_FakeDB.WORKOUT_A_ID}",
            headers=_bearer("user-a", "a@test.com"),
        )
        assert r.status_code == 200

    async def test_non_owner_gets_404(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/rag/workout/{_FakeDB.WORKOUT_A_ID}",
            headers=_bearer("user-b", "b@test.com"),
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. GET /api/coach/workout-analysis/{workout_id}
# ---------------------------------------------------------------------------

class TestCoachWorkoutAnalysisIntegration:
    async def test_anonymous_denied(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/coach/workout-analysis/{_FakeDB.WORKOUT_A_ID}"
        )
        assert r.status_code in (401, 403)

    async def test_owner_gets_200(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/coach/workout-analysis/{_FakeDB.WORKOUT_A_ID}",
            headers=_bearer("user-a", "a@test.com"),
        )
        assert r.status_code == 200

    async def test_non_owner_gets_404(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/coach/workout-analysis/{_FakeDB.WORKOUT_A_ID}",
            headers=_bearer("user-b", "b@test.com"),
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 4. GET /api/coach/detailed-analysis/{workout_id}
# ---------------------------------------------------------------------------

class TestCoachDetailedAnalysisIntegration:
    async def test_anonymous_denied(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/coach/detailed-analysis/{_FakeDB.WORKOUT_A_ID}"
        )
        assert r.status_code in (401, 403)

    async def test_owner_gets_200(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/coach/detailed-analysis/{_FakeDB.WORKOUT_A_ID}",
            headers=_bearer("user-a", "a@test.com"),
        )
        assert r.status_code == 200

    async def test_non_owner_gets_404(self, real_client):
        client, _ = real_client
        r = await client.get(
            f"/api/coach/detailed-analysis/{_FakeDB.WORKOUT_A_ID}",
            headers=_bearer("user-b", "b@test.com"),
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. POST /api/chat/send
# ---------------------------------------------------------------------------

class TestChatSendIntegration:
    async def test_anonymous_returns_401(self, real_client):
        """chat/send is a FREE route — unauthenticated request reaches auth_user → 401."""
        client, _ = real_client
        r = await client.post(
            "/api/chat/send",
            json={"message": "Hello", "use_local_llm": True},
        )
        assert r.status_code == 401

    async def test_owner_gets_200(self, real_client):
        client, _ = real_client
        r = await client.post(
            "/api/chat/send",
            json={"message": "How was my last run?", "use_local_llm": True},
            headers=_bearer("user-a", "a@test.com"),
        )
        assert r.status_code == 200
        data = r.json()
        assert "message_id" in data
        assert "messages_remaining" in data

    async def test_workouts_scoped_to_authenticated_user(self, real_client):
        """chat/send fetches workouts only for the JWT user — verify isolation."""
        client, fake_db = real_client
        r = await client.post(
            "/api/chat/send",
            json={"message": "What should I do next?", "use_local_llm": True},
            headers=_bearer("user-b", "b@test.com"),
        )
        assert r.status_code == 200
        stored_user_ids = [m["user_id"] for m in fake_db.chat_messages._docs]
        assert all(uid == "user-b" for uid in stored_user_ids), (
            f"Messages were stored for unexpected users: {stored_user_ids}"
        )
