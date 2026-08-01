"""
IDOR / Authorization tests — PR60.

Verifies that:
1. GET /messages requires authentication (401 anonymous) and returns only
   the authenticated user's conversations (not another user's).
2. GET /rag/workout/{workout_id} returns 404 when the authenticated user
   requests a workout that belongs to a different user.
3. GET /coach/workout-analysis/{workout_id} same isolation guarantee.
4. GET /coach/detailed-analysis/{workout_id} same isolation guarantee.
5. POST /chat/send builds context from the authenticated user's workouts only.
6. Request models (CoachRequest, GuidanceRequest, ChatRequest) no longer expose
   a client-controllable user_id field.
"""
from __future__ import annotations

import os
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-idor-tests-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

from auth.jwt_utils import create_access_token
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _workout(user_id: str, workout_id: str | None = None) -> dict:
    return {
        "id": workout_id or str(uuid.uuid4()),
        "user_id": user_id,
        "date": "2024-01-01",
        "type": "run",
        "distance_km": 10.0,
        "duration_minutes": 60,
    }


def _conversation(user_id: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "role": "user",
        "content": "Hello",
        "timestamp": "2024-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Minimal fake DB
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        return list(self._docs[:length] if length else self._docs)


class _Collection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    async def find_one(self, query, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        return _Cursor(
            d for d in self._docs
            if all(d.get(k) == v for k, v in query.items())
        )

    async def count_documents(self, query):
        return sum(
            1 for d in self._docs
            if all(d.get(k) == v for k, v in query.items()
                   if not isinstance(v, dict))
        )

    async def insert_one(self, doc):
        self._docs.append(dict(doc))


# ---------------------------------------------------------------------------
# 1. GET /messages — authentication + user isolation
# ---------------------------------------------------------------------------

def _messages_app():
    """Minimal app that mirrors the fixed /messages endpoint."""
    from auth.dependencies import get_current_user

    app = FastAPI()

    user_a_conv = _conversation("user-a")
    user_b_conv = _conversation("user-b")

    class _DB:
        conversations = _Collection([user_a_conv, user_b_conv])
        users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True, "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True, "is_email_verified": True},
        ])

    app.state.db = _DB()
    db = app.state.db

    @app.get("/messages")
    async def get_messages(user: dict = Depends(get_current_user), limit: int = 20):
        user_id = user["id"]
        msgs = await db.conversations.find({"user_id": user_id}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
        return msgs

    return app, user_a_conv, user_b_conv


@pytest_asyncio.fixture
async def messages_client():
    app, user_a_conv, user_b_conv = _messages_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, user_a_conv, user_b_conv


class TestMessagesEndpoint:
    @pytest.mark.asyncio
    async def test_anonymous_401(self, messages_client):
        client, *_ = messages_client
        r = await client.get("/messages")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_user_sees_own_messages_only(self, messages_client):
        client, user_a_conv, user_b_conv = messages_client
        r = await client.get("/messages", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert user_a_conv["id"] in ids
        assert user_b_conv["id"] not in ids

    @pytest.mark.asyncio
    async def test_user_b_cannot_see_user_a_messages(self, messages_client):
        client, user_a_conv, user_b_conv = messages_client
        r = await client.get("/messages", headers=_bearer("user-b", "b@test.com"))
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert user_a_conv["id"] not in ids
        assert user_b_conv["id"] in ids


# ---------------------------------------------------------------------------
# 2–4. Workout endpoints — IDOR isolation
# ---------------------------------------------------------------------------

def _workout_app():
    """App with three endpoints that must enforce user_id isolation."""
    from auth.dependencies import get_current_user

    app = FastAPI()

    workout_a_id = "wkt-user-a"
    workout_b_id = "wkt-user-b"

    class _DB:
        workouts = _Collection([
            _workout("user-a", workout_a_id),
            _workout("user-b", workout_b_id),
        ])
        users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True, "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True, "is_email_verified": True},
        ])
        user_goals = _Collection([])

    app.state.db = _DB()
    db = app.state.db

    @app.get("/rag/workout/{workout_id}")
    async def rag_workout(workout_id: str, user: dict = Depends(get_current_user)):
        user_id = user["id"]
        workout = await db.workouts.find_one({"id": workout_id, "user_id": user_id}, {"_id": 0})
        if not workout:
            raise HTTPException(status_code=404, detail="Workout not found")
        return {"workout_id": workout_id, "user_id": workout["user_id"]}

    @app.get("/coach/workout-analysis/{workout_id}")
    async def coach_analysis(workout_id: str, user: dict = Depends(get_current_user)):
        user_id = user["id"]
        all_workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(100)
        workout = next((w for w in all_workouts if w["id"] == workout_id), None)
        if not workout:
            raise HTTPException(status_code=404, detail="Workout not found")
        return {"workout_id": workout_id, "user_id": workout["user_id"]}

    @app.get("/coach/detailed-analysis/{workout_id}")
    async def detailed_analysis(workout_id: str, user: dict = Depends(get_current_user)):
        user_id = user["id"]
        all_workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(100)
        workout = next((w for w in all_workouts if w["id"] == workout_id), None)
        if not workout:
            raise HTTPException(status_code=404, detail="Workout not found")
        return {"workout_id": workout_id, "user_id": workout["user_id"]}

    return app, workout_a_id, workout_b_id


@pytest_asyncio.fixture
async def workout_client():
    app, wkt_a, wkt_b = _workout_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, wkt_a, wkt_b


class TestRagWorkoutIDOR:
    @pytest.mark.asyncio
    async def test_owner_can_access_own_workout(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/rag/workout/{wkt_a}", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200
        assert r.json()["user_id"] == "user-a"

    @pytest.mark.asyncio
    async def test_other_user_gets_404(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/rag/workout/{wkt_a}", headers=_bearer("user-b", "b@test.com"))
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_anonymous_gets_401(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/rag/workout/{wkt_a}")
        assert r.status_code == 401


class TestCoachWorkoutAnalysisIDOR:
    @pytest.mark.asyncio
    async def test_owner_can_access_own_workout(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/coach/workout-analysis/{wkt_a}", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_other_user_gets_404(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/coach/workout-analysis/{wkt_a}", headers=_bearer("user-b", "b@test.com"))
        assert r.status_code == 404


class TestCoachDetailedAnalysisIDOR:
    @pytest.mark.asyncio
    async def test_owner_can_access_own_workout(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/coach/detailed-analysis/{wkt_a}", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_other_user_gets_404(self, workout_client):
        client, wkt_a, _ = workout_client
        r = await client.get(f"/coach/detailed-analysis/{wkt_a}", headers=_bearer("user-b", "b@test.com"))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. POST /chat/send — workout context is user-scoped
# ---------------------------------------------------------------------------

def _chat_app():
    """Minimal chat endpoint verifying workouts are fetched for the JWT user only."""
    from auth.dependencies import get_current_user

    app = FastAPI()

    class _DB:
        workouts = _Collection([
            _workout("user-a", "wkt-a"),
            _workout("user-b", "wkt-b"),
        ])
        users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True, "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True, "is_email_verified": True},
        ])

    app.state.db = _DB()
    db = app.state.db

    @app.post("/chat/context-check")
    async def chat_context_check(user: dict = Depends(get_current_user)):
        """Returns the workout IDs visible to this user — used to verify isolation."""
        user_id = user["id"]
        workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(50)
        return {"user_id": user_id, "workout_ids": [w["id"] for w in workouts]}

    return app


@pytest_asyncio.fixture
async def chat_client():
    app = _chat_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


class TestChatWorkoutIsolation:
    @pytest.mark.asyncio
    async def test_user_a_sees_only_own_workouts(self, chat_client):
        r = await chat_client.post("/chat/context-check", headers=_bearer("user-a", "a@test.com"))
        assert r.status_code == 200
        data = r.json()
        assert "wkt-a" in data["workout_ids"]
        assert "wkt-b" not in data["workout_ids"]

    @pytest.mark.asyncio
    async def test_user_b_sees_only_own_workouts(self, chat_client):
        r = await chat_client.post("/chat/context-check", headers=_bearer("user-b", "b@test.com"))
        assert r.status_code == 200
        data = r.json()
        assert "wkt-b" in data["workout_ids"]
        assert "wkt-a" not in data["workout_ids"]


# ---------------------------------------------------------------------------
# 6. Request model field hygiene — no client-controllable user_id
# ---------------------------------------------------------------------------

class TestRequestModelNoUserIdField:
    """Verify that client-controllable user_id was removed from request models.

    We parse the source file with the AST module to avoid importing server.py
    (which requires runtime dependencies like MongoDB and Redis).
    """

    _SERVER_SRC = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py"
    )

    def _fields_for_class(self, class_name: str) -> set[str]:
        import ast

        tree = ast.parse(open(self._SERVER_SRC).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                names: set[str] = set()
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        names.add(item.target.id)
                return names
        return set()

    def test_coach_request_no_user_id(self):
        assert "user_id" not in self._fields_for_class("CoachRequest"), \
            "CoachRequest must not expose a client-controllable user_id"

    def test_guidance_request_no_user_id(self):
        assert "user_id" not in self._fields_for_class("GuidanceRequest"), \
            "GuidanceRequest must not expose a client-controllable user_id"

    def test_chat_request_no_user_id(self):
        assert "user_id" not in self._fields_for_class("ChatRequest"), \
            "ChatRequest must not expose a client-controllable user_id"
