from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "coach-contract-test-secret-32chars!!")
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


def _bearer(user_id: str, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = list(docs)

    def sort(self, key: str, direction: int) -> "_Cursor":
        reverse = direction == -1
        self._docs.sort(key=lambda d: d.get(key, ""), reverse=reverse)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int | None = None, **_kwargs) -> list[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self._docs = list(docs or [])

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for key, value in query.items():
            if isinstance(value, dict):
                if "$gte" in value:
                    if doc.get(key) is None or doc.get(key) < value["$gte"]:
                        return False
            elif doc.get(key) != value:
                return False
        return True

    def find(self, query: dict | None = None, projection: dict | None = None) -> _Cursor:
        q = query or {}
        filtered = [dict(d) for d in self._docs if self._matches(d, q)]
        if projection:
            include = {k for k, v in projection.items() if v}
            exclude = {k for k, v in projection.items() if not v}
            if include:
                filtered = [{k: d.get(k) for k in include if k in d} for d in filtered]
            elif exclude:
                filtered = [{k: v for k, v in d.items() if k not in exclude} for d in filtered]
        return _Cursor(filtered)

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        for d in self._docs:
            if self._matches(d, query):
                result = dict(d)
                if projection:
                    result = {k: v for k, v in result.items() if projection.get(k, 1)}
                return result
        return None

    async def count_documents(self, query: dict) -> int:
        return sum(1 for d in self._docs if self._matches(d, query))

    async def insert_one(self, doc: dict):
        self._docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def delete_many(self, query: dict):
        before = len(self._docs)
        self._docs = [d for d in self._docs if not self._matches(d, query)]
        return SimpleNamespace(deleted_count=before - len(self._docs))

    async def create_index(self, *_a, **_kw):
        return None


class _FakeDB:
    def __init__(self, conversations: list[dict] | None = None):
        self.conversations = _Collection(conversations or [])
        self.chat_messages = _Collection([])
        self.garmin_activities = _Collection([])
        self.garmin_connections = _Collection([])
        self.garmin_daily_metrics = _Collection([])
        self.workouts = _Collection([])
        self.user_goals = _Collection([])

    def __getattr__(self, name: str):
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


class _ContextPayload:
    def model_dump(self, mode: str = "json") -> dict:
        return {"canonical": {"week": "ok"}, "mode": mode}


async def _coach_response_stub(**_kwargs):
    return "coach-response", True, {"provider": "test"}


async def _free_access(_db, user_id: str):
    return UserAccess(user_id=user_id, tier=Tier.FREE)


async def _trial_access(_db, user_id: str):
    return UserAccess(user_id=user_id, tier=Tier.TRIAL)


async def _premium_access(_db, user_id: str):
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


async def _run_analyze(fake_db: _FakeDB, access_fn, *, user_id: str = "user-a", message: str = "hello"):
    patches = [
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db, create=True),
        patch("server.get_user_access", AsyncMock(side_effect=access_fn)),
        patch("server._resolve_goal_v2", AsyncMock(return_value=SimpleNamespace())),
        patch("server._resolve_canonical_reference_date", return_value=datetime(2026, 1, 15, tzinfo=timezone.utc).date()),
        patch("server.mongo_garmin_activities_to_domain", side_effect=lambda docs: []),
        patch("server.build_training_load", return_value=SimpleNamespace()),
        patch("server.build_readiness_v2_from_garmin_data", return_value=None),
        patch("server.build_readiness_decision", return_value=SimpleNamespace()),
        patch("server.predict_races", return_value=SimpleNamespace()),
        patch("server.load_canonical_training_paces", AsyncMock(return_value=SimpleNamespace())),
        patch("server.get_training_v2_week", AsyncMock(return_value={})),
        patch("server.get_today_adaptive_session", AsyncMock(return_value={})),
        patch("server.build_coach_context_v2", AsyncMock(return_value=_ContextPayload())),
        patch("server.enrich_chat_response", AsyncMock(side_effect=_coach_response_stub)),
    ]

    if hasattr(server.rate_limiter, "requests"):
        server.rate_limiter.requests.clear()

    with (
        patches[0], patches[1], patches[2], patches[3], patches[4],
        patches[5], patches[6], patches[7], patches[8], patches[9],
        patches[10], patches[11], patches[12], patches[13], patches[14],
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id, f"{user_id}@test.com"),
                json={"message": message, "language": "en"},
            )


def _iso_at(base: datetime, idx: int) -> str:
    return (base + timedelta(minutes=idx)).isoformat()


async def test_free_quota_allows_10_and_blocks_11th():
    fake_db = _FakeDB()
    for i in range(10):
        resp = await _run_analyze(fake_db, _free_access, message=f"msg-{i}")
        assert resp.status_code == 200

    blocked = await _run_analyze(fake_db, _free_access, message="msg-11")
    assert blocked.status_code == 429


async def test_free_quota_resets_on_calendar_month_change():
    feb_docs = [
        {
            "id": f"u-{i}",
            "user_id": "user-a",
            "role": "user",
            "content": "old",
            "timestamp": f"2026-02-{(i % 28) + 1:02d}T12:00:00+00:00",
        }
        for i in range(10)
    ]
    fake_db = _FakeDB(conversations=feb_docs)

    class _MarchDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            dt = datetime(2026, 3, 2, 8, 0, 0, tzinfo=timezone.utc)
            return dt if tz else dt.replace(tzinfo=None)

    with patch("server.datetime", _MarchDateTime):
        resp = await _run_analyze(fake_db, _free_access, message="new-month")
    assert resp.status_code == 200


async def test_trial_is_unlimited_beyond_10_messages():
    fake_db = _FakeDB()
    for i in range(12):
        resp = await _run_analyze(fake_db, _trial_access, message=f"trial-{i}")
        assert resp.status_code == 200


async def test_premium_is_unlimited_beyond_25_messages():
    fake_db = _FakeDB()
    for i in range(26):
        resp = await _run_analyze(fake_db, _premium_access, message=f"premium-{i}")
        assert resp.status_code == 200


async def test_history_returns_last_50_in_chronological_order():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    docs = [
        {"id": f"m{i}", "user_id": "user-a", "role": "user", "content": str(i), "timestamp": _iso_at(base, i)}
        for i in range(1, 81)
    ]
    fake_db = _FakeDB(conversations=docs)

    with (
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db, create=True),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            r = await client.get("/api/coach/history?limit=50", headers=_bearer("user-a", "a@test.com"))

    assert r.status_code == 200
    payload = r.json()
    assert len(payload) == 50
    assert payload[0]["id"] == "m31"
    assert payload[-1]["id"] == "m80"


async def test_user_isolation_for_history_and_quota():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    docs = [
        {"id": f"a{i}", "user_id": "user-a", "role": "user", "content": "a", "timestamp": _iso_at(base, i)}
        for i in range(10)
    ] + [
        {"id": "b1", "user_id": "user-b", "role": "user", "content": "b", "timestamp": _iso_at(base, 11)}
    ]
    fake_db = _FakeDB(conversations=docs)

    with (
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db, create=True),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            hist_b = await client.get("/api/coach/history?limit=50", headers=_bearer("user-b", "b@test.com"))
            assert hist_b.status_code == 200
            assert all(msg["user_id"] == "user-b" for msg in hist_b.json())

    # user-a exhausted FREE quota; user-b must still be allowed
    resp_b = await _run_analyze(fake_db, _free_access, user_id="user-b", message="still-allowed")
    assert resp_b.status_code == 200


async def test_new_coach_messages_write_only_to_conversations_not_chat_messages():
    fake_db = _FakeDB()
    resp = await _run_analyze(fake_db, _free_access, message="storage-check")
    assert resp.status_code == 200

    assert len(fake_db.conversations._docs) == 2
    assert len(fake_db.chat_messages._docs) == 0


async def test_coach_analyze_route_uses_canonical_service_function():
    fake_db = _FakeDB()
    service_mock = AsyncMock(return_value=server.CoachResponse(response="ok", message_id="m1"))
    with (
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db, create=True),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
        patch("server.process_coach_message", service_mock),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            r = await client.post(
                "/api/coach/analyze",
                headers=_bearer("user-a", "a@test.com"),
                json={"message": "delegate", "language": "en"},
            )

    assert r.status_code == 200
    assert service_mock.await_count == 1


async def test_subscription_authority_function_is_used_for_coach_processing():
    fake_db = _FakeDB()
    access_mock = AsyncMock(side_effect=_premium_access)

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", access_mock),
        patch("server._resolve_goal_v2", AsyncMock(return_value=SimpleNamespace())),
        patch("server._resolve_canonical_reference_date", return_value=datetime(2026, 1, 15, tzinfo=timezone.utc).date()),
        patch("server.mongo_garmin_activities_to_domain", side_effect=lambda docs: []),
        patch("server.build_training_load", return_value=SimpleNamespace()),
        patch("server.build_readiness_v2_from_garmin_data", return_value=None),
        patch("server.build_readiness_decision", return_value=SimpleNamespace()),
        patch("server.predict_races", return_value=SimpleNamespace()),
        patch("server.load_canonical_training_paces", AsyncMock(return_value=SimpleNamespace())),
        patch("server.get_training_v2_week", AsyncMock(return_value={})),
        patch("server.get_today_adaptive_session", AsyncMock(return_value={})),
        patch("server.build_coach_context_v2", AsyncMock(return_value=_ContextPayload())),
        patch("server.enrich_chat_response", AsyncMock(side_effect=_coach_response_stub)),
    ):
        response = await server.process_coach_message(
            request=server.CoachRequest(message="authority"),
            user={"id": "user-authority"},
        )

    assert response.message_id
    assert any(call.args[1] == "user-authority" for call in access_mock.await_args_list)


async def test_legacy_chat_send_endpoint_is_absent():
    fake_db = _FakeDB()
    with (
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db, create=True),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            r = await client.post(
                "/api/chat/send",
                headers=_bearer("user-a", "a@test.com"),
                json={"message": "legacy"},
            )

    assert r.status_code == 404
