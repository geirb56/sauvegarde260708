from __future__ import annotations

import asyncio
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
        self._duplicate_upsert_once: set[tuple[str, str]] = set()
        self._duplicate_upsert_raised: set[tuple[str, str]] = set()

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for key, value in query.items():
            if isinstance(value, dict):
                if "$gte" in value:
                    if doc.get(key) is None or doc.get(key) < value["$gte"]:
                        return False
                if "$lt" in value:
                    if doc.get(key) is None or doc.get(key) >= value["$lt"]:
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

    async def find_one_and_update(
        self,
        query: dict,
        update: dict,
        upsert: bool = False,
        return_document=None,
    ) -> dict | None:
        key_tuple = (str(query.get("user_id", "")), str(query.get("month_key", "")))
        idx = None
        for i, d in enumerate(self._docs):
            if self._matches(d, query):
                idx = i
                break

        created = False
        if idx is None:
            if not upsert:
                return None
            if (
                key_tuple in self._duplicate_upsert_once
                and key_tuple not in self._duplicate_upsert_raised
            ):
                self._duplicate_upsert_raised.add(key_tuple)
                winner_doc: dict = {}
                for k, v in query.items():
                    if not isinstance(v, dict):
                        winner_doc[k] = v
                winner_doc.update(update.get("$setOnInsert", {}))
                self._docs.append(winner_doc)
                raise server.DuplicateKeyError("simulated duplicate key race")
            base_doc: dict = {}
            for k, v in query.items():
                if not isinstance(v, dict):
                    base_doc[k] = v
            set_on_insert = update.get("$setOnInsert", {})
            base_doc.update(set_on_insert)
            self._docs.append(base_doc)
            idx = len(self._docs) - 1
            created = True

        target = dict(self._docs[idx])
        if "$inc" in update:
            for k, inc_value in update["$inc"].items():
                target[k] = int(target.get(k, 0)) + int(inc_value)
        if "$set" in update:
            for k, set_value in update["$set"].items():
                target[k] = set_value
        if "$setOnInsert" in update and created:
            for k, set_value in update["$setOnInsert"].items():
                if k not in target:
                    target[k] = set_value

        self._docs[idx] = target
        return dict(target)

    async def update_one(self, query: dict, update: dict):
        idx = None
        for i, d in enumerate(self._docs):
            if self._matches(d, query):
                idx = i
                break
        if idx is None:
            return SimpleNamespace(matched_count=0, modified_count=0)

        target = dict(self._docs[idx])
        if "$inc" in update:
            for k, inc_value in update["$inc"].items():
                target[k] = int(target.get(k, 0)) + int(inc_value)
        if "$set" in update:
            for k, set_value in update["$set"].items():
                target[k] = set_value
        self._docs[idx] = target
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def delete_many(self, query: dict):
        before = len(self._docs)
        self._docs = [d for d in self._docs if not self._matches(d, query)]
        return SimpleNamespace(deleted_count=before - len(self._docs))

    async def create_index(self, *_a, **_kw):
        return None


class _FakeDB:
    def __init__(self, conversations: list[dict] | None = None):
        self.conversations = _Collection(conversations or [])
        self.coach_quota_counters = _Collection([])
        self.garmin_activities = _Collection([])
        self.garmin_connections = _Collection([])
        self.garmin_daily_metrics = _Collection([])
        self.workouts = _Collection([])
        self.user_goals = _Collection([])

    def __getattr__(self, name: str):
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _month_start_iso() -> str:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _month_ts(offset_minutes: int = 0) -> str:
    start = datetime.now(timezone.utc).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    return (start + timedelta(minutes=offset_minutes)).isoformat()


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
        patch("server.llm_coach.enrich_chat_response", AsyncMock(side_effect=_coach_response_stub)),
    ]

    if hasattr(server.rate_limiter, "requests"):
        server.rate_limiter.requests.clear()

    with (
        patches[0], patches[1], patches[2], patches[3], patches[4],
        patches[5], patches[6], patches[7], patches[8], patches[9],
        patches[10], patches[11], patches[12], patches[13],
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
    assert len(fake_db.coach_quota_counters._docs) == 1


async def test_coach_analyze_route_uses_canonical_service_function():
    fake_db = _FakeDB()
    service_mock = AsyncMock(return_value=server.CoachResponse(response="ok", message_id="m1"))
    with (
        patch.object(server, "db", fake_db),
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
        patch("server.llm_coach.enrich_chat_response", AsyncMock(side_effect=_coach_response_stub)),
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
        patch("server.get_user_access", AsyncMock(side_effect=_premium_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            r = await client.post(
                "/api/chat/send",
                headers=_bearer("user-a", "a@test.com"),
                json={"message": "legacy"},
            )
            r_history = await client.get("/api/chat/history", headers=_bearer("user-a", "a@test.com"))
            r_store = await client.post(
                "/api/chat/store-response?message_id=x&response=y",
                headers=_bearer("user-a", "a@test.com"),
            )

    assert r.status_code == 404
    assert r_history.status_code == 404
    assert r_store.status_code == 404


async def test_route_registry_has_no_legacy_chat_routes():
    route_signatures = {
        (getattr(route, "path", None), tuple(sorted(getattr(route, "methods", set()) or set())))
        for route in server.app.routes
    }
    assert ("/api/chat/send", ("POST",)) not in route_signatures
    assert ("/api/chat/history", ("GET",)) not in route_signatures
    assert ("/api/chat/history", ("DELETE",)) not in route_signatures
    assert ("/api/chat/store-response", ("POST",)) not in route_signatures


async def test_free_counter_bootstrap_uses_existing_conversations():
    now = datetime.now(timezone.utc)
    docs = [
        {
            "id": f"b{i}",
            "user_id": "user-a",
            "role": "user",
            "content": "old",
            "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
        }
        for i in range(7)
    ]
    fake_db = _FakeDB(conversations=docs)

    resp = await _run_analyze(fake_db, _free_access, message="bootstrap")
    assert resp.status_code == 200
    assert len(fake_db.coach_quota_counters._docs) == 1
    counter = fake_db.coach_quota_counters._docs[0]
    assert counter["baseline"] == 7
    assert counter["count"] == 8


async def test_free_concurrency_allows_only_one_when_at_9_of_10():
    now = datetime.now(timezone.utc)
    docs = [
        {
            "id": f"c{i}",
            "user_id": "user-a",
            "role": "user",
            "content": f"m{i}",
            "timestamp": (now - timedelta(minutes=20 - i)).isoformat(),
        }
        for i in range(9)
    ]
    fake_db = _FakeDB(conversations=docs)

    r1, r2 = await asyncio.gather(
        _run_analyze(fake_db, _free_access, message="concurrent-1"),
        _run_analyze(fake_db, _free_access, message="concurrent-2"),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 429]

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    user_count = await fake_db.conversations.count_documents(
        {"user_id": "user-a", "role": "user", "timestamp": {"$gte": month_start}}
    )
    assert user_count == 10
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 10


async def test_concurrent_first_use_initialization_creates_single_counter_document():
    fake_db = _FakeDB(conversations=[])
    r1, r2 = await asyncio.gather(
        _run_analyze(fake_db, _free_access, message="first-1"),
        _run_analyze(fake_db, _free_access, message="first-2"),
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 2


async def test_duplicate_key_retry_during_counter_initialization_uses_winner_document():
    fake_db = _FakeDB(conversations=[])
    key = ("user-a", _current_month_key())
    fake_db.coach_quota_counters._duplicate_upsert_once.add(key)

    resp = await _run_analyze(fake_db, _free_access, message="dup-retry")
    assert resp.status_code == 200
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 1


async def test_previous_month_usage_does_not_consume_current_month_quota():
    now = datetime.now(timezone.utc)
    prev_month = (now.replace(day=1) - timedelta(days=1)).replace(day=15)
    docs = [
        {
            "id": f"p{i}",
            "user_id": "user-a",
            "role": "user",
            "content": "old",
            "timestamp": prev_month.isoformat(),
        }
        for i in range(10)
    ]
    fake_db = _FakeDB(conversations=docs)

    resp = await _run_analyze(fake_db, _free_access, message="new-month")
    assert resp.status_code == 200
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 1


async def test_history_clear_bootstraps_counter_before_delete_for_10_used_and_blocks_next():
    docs = [
        {"id": f"h{i}", "user_id": "user-a", "role": "user", "content": "x", "timestamp": _month_ts(i)}
        for i in range(10)
    ] + [
        {"id": "ha", "user_id": "user-a", "role": "assistant", "content": "a", "timestamp": _month_ts(20)}
    ]
    fake_db = _FakeDB(conversations=docs)

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            clear_resp = await client.delete("/api/coach/history", headers=_bearer("user-a", "a@test.com"))
            assert clear_resp.status_code == 200

    assert len(fake_db.conversations._docs) == 0
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 10

    blocked = await _run_analyze(fake_db, _free_access, message="after-clear-10")
    assert blocked.status_code == 429


async def test_history_clear_preserves_partial_usage_counter_for_7_used():
    docs = [
        {"id": f"p{i}", "user_id": "user-a", "role": "user", "content": "x", "timestamp": _month_ts(i)}
        for i in range(7)
    ]
    fake_db = _FakeDB(conversations=docs)

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            clear_resp = await client.delete("/api/coach/history", headers=_bearer("user-a", "a@test.com"))
            assert clear_resp.status_code == 200

    assert len(fake_db.conversations._docs) == 0
    assert fake_db.coach_quota_counters._docs[0]["count"] == 7

    for i in range(3):
        ok = await _run_analyze(fake_db, _free_access, message=f"after-clear-7-{i}")
        assert ok.status_code == 200
    blocked = await _run_analyze(fake_db, _free_access, message="after-clear-7-block")
    assert blocked.status_code == 429


async def test_history_clear_keeps_existing_counter_unchanged():
    docs = [{"id": "u1", "user_id": "user-a", "role": "user", "content": "x", "timestamp": _month_ts(1)}]
    fake_db = _FakeDB(conversations=docs)
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-a",
        "month_key": _current_month_key(),
        "count": 8,
        "baseline": 8,
        "created_at": _month_ts(0),
        "updated_at": _month_ts(0),
    })

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            clear_resp = await client.delete("/api/coach/history", headers=_bearer("user-a", "a@test.com"))
            assert clear_resp.status_code == 200

    assert len(fake_db.conversations._docs) == 0
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 8


async def test_subscription_status_uses_free_counter_after_history_clear():
    fake_db = _FakeDB(conversations=[])
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-a",
        "month_key": _current_month_key(),
        "count": 8,
        "baseline": 8,
        "created_at": _month_ts(0),
        "updated_at": _month_ts(0),
    })

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.get("/api/subscription/status", headers=_bearer("user-a", "a@test.com"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages_used"] == 8
    assert data["messages_limit"] == 10
    assert data["messages_remaining"] == 2
    assert data["is_unlimited"] is False


async def test_subscription_status_bootstraps_counter_from_conversations_when_missing():
    docs = [
        {"id": f"s{i}", "user_id": "user-a", "role": "user", "content": "x", "timestamp": _month_ts(i)}
        for i in range(6)
    ]
    fake_db = _FakeDB(conversations=docs)

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.get("/api/subscription/status", headers=_bearer("user-a", "a@test.com"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages_used"] == 6
    assert data["messages_limit"] == 10
    assert data["messages_remaining"] == 4
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 6


async def test_subscription_status_month_isolation_for_free_counter():
    now = datetime.now(timezone.utc)
    prev_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    fake_db = _FakeDB(conversations=[])
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-a",
        "month_key": prev_month,
        "count": 10,
        "baseline": 10,
        "created_at": _month_ts(-10000),
        "updated_at": _month_ts(-10000),
    })

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.get("/api/subscription/status", headers=_bearer("user-a", "a@test.com"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages_used"] == 0
    assert data["messages_remaining"] == 10
    month_docs = [d for d in fake_db.coach_quota_counters._docs if d["month_key"] == _current_month_key()]
    assert len(month_docs) == 1
    assert month_docs[0]["count"] == 0


async def test_history_clear_and_status_are_user_isolated():
    docs = [
        {"id": "a1", "user_id": "user-a", "role": "user", "content": "a", "timestamp": _month_ts(1)},
        {"id": "b1", "user_id": "user-b", "role": "user", "content": "b", "timestamp": _month_ts(2)},
    ]
    fake_db = _FakeDB(conversations=docs)
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-b",
        "month_key": _current_month_key(),
        "count": 9,
        "baseline": 9,
        "created_at": _month_ts(0),
        "updated_at": _month_ts(0),
    })

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            clear_a = await client.delete("/api/coach/history", headers=_bearer("user-a", "a@test.com"))
            status_b = await client.get("/api/subscription/status", headers=_bearer("user-b", "b@test.com"))

    assert clear_a.status_code == 200
    assert status_b.status_code == 200
    data_b = status_b.json()
    assert data_b["messages_used"] == 9
    assert data_b["messages_remaining"] == 1
    b_counter = [
        d for d in fake_db.coach_quota_counters._docs
        if d["user_id"] == "user-b" and d["month_key"] == _current_month_key()
    ]
    assert len(b_counter) == 1
    assert b_counter[0]["count"] == 9


async def test_free_reservation_rolls_back_when_failure_occurs_before_user_message_write():
    fake_db = _FakeDB()

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
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
        patch("server.build_coach_context_v2", AsyncMock(side_effect=RuntimeError("boom-before-user-save"))),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/coach/analyze",
                headers=_bearer("user-a", "a@test.com"),
                json={"message": "rollback-check", "language": "en"},
            )

    assert resp.status_code == 500
    assert len(fake_db.conversations._docs) == 0
    assert len(fake_db.coach_quota_counters._docs) == 1
    assert fake_db.coach_quota_counters._docs[0]["count"] == 0


async def test_user_message_persisted_then_llm_failure_still_consumes_free_slot():
    fake_db = _FakeDB()

    async def _llm_fail(**_kwargs):
        return "", False, {"provider": "test"}

    with (
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
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
        patch("server.llm_coach.enrich_chat_response", AsyncMock(side_effect=_llm_fail)),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.post(
                "/api/coach/analyze",
                headers=_bearer("user-a", "a@test.com"),
                json={"message": "llm-failure", "language": "en"},
            )

    assert resp.status_code == 503
    user_messages = [m for m in fake_db.conversations._docs if m.get("role") == "user"]
    assistant_messages = [m for m in fake_db.conversations._docs if m.get("role") == "assistant"]
    assert len(user_messages) == 1
    assert len(assistant_messages) == 0
    assert fake_db.coach_quota_counters._docs[0]["count"] == 1
