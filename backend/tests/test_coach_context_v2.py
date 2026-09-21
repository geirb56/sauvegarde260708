from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import patch

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
from auth.jwt_utils import create_access_token  # noqa: E402
from training_v2.training_load import build_training_load  # noqa: E402


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_Cursor":
        reverse = direction < 0
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=reverse)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs = list(docs or [])
        self.calls = {"find": 0, "find_one": 0}

    def _matches(self, doc: dict, query: Optional[dict]) -> bool:
        for key, value in (query or {}).items():
            doc_value = doc.get(key)
            if isinstance(value, dict):
                if "$gte" in value and (doc_value is None or doc_value < value["$gte"]):
                    return False
                continue
            if doc_value != value:
                return False
        return True

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        self.calls["find"] += 1
        return _Cursor([dict(d) for d in self._docs if self._matches(d, query)])

    async def find_one(self, query: dict, projection: Optional[dict] = None, sort: Any = None) -> Optional[dict]:
        self.calls["find_one"] += 1
        docs = [dict(d) for d in self._docs if self._matches(d, query)]
        if sort and docs:
            field, direction = sort[0]
            docs.sort(key=lambda d: d.get(field) or "", reverse=direction < 0)
        return docs[0] if docs else None

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        for idx, doc in enumerate(self._docs):
            if self._matches(doc, query):
                self._docs[idx] = {**doc, **update.get("$set", {})}
                return
        if upsert:
            payload = dict(query)
            payload.update(update.get("$set", {}))
            self._docs.append(payload)


class _FakeDB:
    def __init__(
        self,
        *,
        user_id: str,
        workouts: Optional[List[dict]] = None,
        garmin_activities: Optional[List[dict]] = None,
        training_cycles: Optional[List[dict]] = None,
        training_feedback: Optional[List[dict]] = None,
    ) -> None:
        self.workouts = _Collection(workouts or [])
        self.garmin_activities = _Collection(garmin_activities or [])
        self.training_cycles = _Collection(training_cycles or [])
        self.training_feedback = _Collection(training_feedback or [])
        self.training_prefs = _Collection([])
        self.user_goals = _Collection([])
        self.user_profiles = _Collection([])
        self.garmin_connections = _Collection([{"user_id": user_id, "connected": False}])
        self.garmin_daily_metrics = _Collection([])
        self.conversations = _Collection([])
        self.training_plans = _Collection([])

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _bearer(user_id: str) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, "coach@example.com")}


def _workout(user_id: str, days_ago: int, *, distance_km: float, duration_min: float) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "id": f"w-{days_ago}",
        "user_id": user_id,
        "date": dt.isoformat(),
        "activity_type": "running",
        "distance_km": distance_km,
        "duration_minutes": duration_min,
    }


def _garmin_activity(user_id: str, days_ago: int, *, distance_m: float, duration_s: float, avg_hr: float, max_hr: float) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": dt.isoformat(),
        "distance": distance_m,
        "duration": duration_s,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
    }


def _seed_fake_db(user_id: str) -> _FakeDB:
    workouts = [
        _workout(user_id, d, distance_km=8.0 + (d % 3), duration_min=42.0 + d)
        for d in range(1, 25)
    ]
    garmin_activities = [
        _garmin_activity(
            user_id,
            d,
            distance_m=7000.0 + (d % 6) * 800.0,
            duration_s=1700.0 + (d % 5) * 220.0,
            avg_hr=138.0 + (d % 7) * 4.0,
            max_hr=165.0 + (d % 4) * 3.0,
        )
        for d in range(1, 33)
    ]
    cycles = [{"user_id": user_id, "goal": "SEMI", "start_date": datetime.now(timezone.utc) - timedelta(days=35)}]
    feedback = [
        {"user_id": user_id, "date": (date.today() - timedelta(days=3)).isoformat(), "workout_id": "a1", "status": "done"},
        {"user_id": user_id, "date": (date.today() - timedelta(days=1)).isoformat(), "workout_id": "a2", "status": "missed"},
    ]
    return _FakeDB(
        user_id=user_id,
        workouts=workouts,
        garmin_activities=garmin_activities,
        training_cycles=cycles,
        training_feedback=feedback,
    )


@pytest.mark.asyncio
async def test_coach_context_served_session_matches_training_today():
    user_id = "coach-v2-served"
    fake_db = _seed_fake_db(user_id)
    captured = {}

    async def _fake_enrich(user_message, context, conversation_history, user_id):
        captured["context"] = context
        return "ok", True, {}

    with patch.object(server, "db", fake_db), patch("llm_coach.enrich_chat_response", side_effect=_fake_enrich):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            today_resp = await client.get("/api/training/today", headers=_bearer(user_id))
            coach_resp = await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id),
                json={"message": "What is today's session?", "language": "en"},
            )

    assert today_resp.status_code == 200, today_resp.text
    assert coach_resp.status_code == 200, coach_resp.text
    today_payload = today_resp.json()
    expected_served = today_payload.get("adapted_prescription") or today_payload.get("planned_session")
    assert captured["context"]["served_prescription"] == expected_served


@pytest.mark.asyncio
async def test_coach_context_plan_change_keeps_planned_memory_history():
    user_id = "coach-v2-memory"
    fake_db = _seed_fake_db(user_id)
    captured_contexts = []

    async def _fake_enrich(user_message, context, conversation_history, user_id):
        captured_contexts.append(context)
        return "ok", True, {}

    with patch.object(server, "db", fake_db), patch("llm_coach.enrich_chat_response", side_effect=_fake_enrich):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            first = await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id),
                json={"message": "Plan status?", "language": "en"},
            )
            await fake_db.training_cycles.update_one(
                {"user_id": user_id},
                {"$set": {"goal": "MARATHON"}},
                upsert=True,
            )
            second = await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id),
                json={"message": "Plan changed?", "language": "en"},
            )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(captured_contexts) == 2
    assert captured_contexts[0]["planned_memory_history"]
    assert captured_contexts[0]["planned_memory_history"] == captured_contexts[1]["planned_memory_history"]


@pytest.mark.asyncio
async def test_coach_context_does_not_access_training_plans_collection():
    user_id = "coach-v2-no-training-plans"
    fake_db = _seed_fake_db(user_id)

    async def _fake_enrich(user_message, context, conversation_history, user_id):
        return "ok", True, {}

    with patch.object(server, "db", fake_db), patch("llm_coach.enrich_chat_response", side_effect=_fake_enrich):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id),
                json={"message": "context?", "language": "en"},
            )

    assert resp.status_code == 200, resp.text
    assert fake_db.training_plans.calls["find"] == 0
    assert fake_db.training_plans.calls["find_one"] == 0


@pytest.mark.asyncio
async def test_coach_context_load_and_paces_match_v2_authorities():
    user_id = "coach-v2-authorities"
    fake_db = _seed_fake_db(user_id)
    captured = {}

    async def _fake_enrich(user_message, context, conversation_history, user_id):
        captured["context"] = context
        return "ok", True, {}

    with patch.object(server, "db", fake_db), patch("llm_coach.enrich_chat_response", side_effect=_fake_enrich):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id),
                json={"message": "check load and paces", "language": "en"},
            )

    assert resp.status_code == 200, resp.text
    context = captured["context"]
    domain_activities = server.mongo_garmin_activities_to_domain(fake_db.garmin_activities._docs)
    expected_load = build_training_load(domain_activities, date.today())
    expected_perf = server.predict_races(domain_activities, date.today())
    expected_paces = server.load_canonical_training_paces(expected_perf)

    assert context["training_load_v2"]["acwr"] == expected_load.acwr
    assert context["training_load_v2"]["status"] == expected_load.status
    assert context["training_load_v2"]["confidence"] == expected_load.confidence
    assert context["training_paces"] == expected_paces


@pytest.mark.asyncio
async def test_coach_context_absent_data_stays_unavailable():
    user_id = "coach-v2-unavailable"
    fake_db = _FakeDB(
        user_id=user_id,
        workouts=[],
        garmin_activities=[],
        training_cycles=[{"user_id": user_id, "goal": "SEMI", "start_date": datetime.now(timezone.utc)}],
        training_feedback=[],
    )
    captured = {}

    async def _fake_enrich(user_message, context, conversation_history, user_id):
        captured["context"] = context
        return "ok", True, {}

    with patch.object(server, "db", fake_db), patch("llm_coach.enrich_chat_response", side_effect=_fake_enrich):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            resp = await client.post(
                "/api/coach/analyze",
                headers=_bearer(user_id),
                json={"message": "what data is missing?", "language": "en"},
            )

    assert resp.status_code == 200, resp.text
    context = captured["context"]
    assert context["training_load_v2"]["acwr"] is None
    assert context["training_load_v2"]["status"] == "unavailable"
    assert context["training_paces"]["status"] == "unavailable"
    assert context["training_paces"]["paces"] is None
    assert context["performance_v2"]["has_data"] is False
